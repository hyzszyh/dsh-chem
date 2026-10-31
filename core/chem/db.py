r"""chem_db: a local molecule library you can actually query.

SQLite at %LOCALAPPDATA%\dsh-chem\library.db. Every row keeps its canonical
SMILES, InChIKey, key properties and a Morgan fingerprint, so three kinds of
question are cheap: "which of my compounds contain this fragment", "which is
closest to this one", and "what do I have with MW between 200 and 400".
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from . import mol as molmod

SCHEMA = """
CREATE TABLE IF NOT EXISTS molecules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    smiles TEXT NOT NULL,
    canonical TEXT NOT NULL,
    inchikey TEXT NOT NULL UNIQUE,
    formula TEXT,
    mw REAL, logp REAL, tpsa REAL, hbd INTEGER, hba INTEGER,
    rotb INTEGER, rings INTEGER, heavy INTEGER,
    name TEXT, tags TEXT, source TEXT,
    fp_hex TEXT,
    created TEXT
);
CREATE INDEX IF NOT EXISTS idx_canonical ON molecules(canonical);
CREATE INDEX IF NOT EXISTS idx_mw ON molecules(mw);
"""

PROP_FIELDS = ("mw", "logp", "tpsa", "hbd", "hba", "rotb", "rings", "heavy")


def db_path(payload=None):
    override = (payload or {}).get("db")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local) / "dsh-chem" / "library.db"


def _connect(payload=None):
    path = db_path(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn, path


def _fingerprint(m):
    from rdkit.Chem import rdFingerprintGenerator
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    return gen.GetFingerprint(m)


def _fp_hex(m):
    from rdkit import DataStructs
    return DataStructs.BitVectToBinaryText(_fingerprint(m)).hex()


def _props(m):
    from . import props
    row = props._compute(m)
    # props.py names these differently from the columns; guessing the names here
    # left rotb and heavy NULL in every row, which the column review caught.
    return {"mw": row.get("mw"), "logp": row.get("logp"), "tpsa": row.get("tpsa"),
            "hbd": row.get("hbd"), "hba": row.get("hba"),
            "rotb": row.get("rotatable_bonds"), "rings": row.get("rings"),
            "heavy": row.get("heavy_atoms")}


def _read_source(payload):
    """Accept a file, an inline text block, or a list; return [(smiles, name)]."""
    text = payload.get("text") or ""
    path = payload.get("path") or ""
    fmt = (payload.get("format") or "").strip().lower()
    rows = []
    if path:
        target = Path(path)
        if not target.is_file():
            raise molmod.MolError("no-such-file", "找不到文件：" + str(target))
        suffix = fmt or target.suffix.lower().lstrip(".")
        if suffix in ("sdf", "mol", "sd"):
            from rdkit import Chem
            supplier = Chem.SDMolSupplier(str(target), sanitize=True, removeHs=True)
            for item in supplier:
                if item is None:
                    continue
                rows.append((Chem.MolToSmiles(item), item.GetProp("_Name") if item.HasProp("_Name") else ""))
            return rows
        text = target.read_text(encoding="utf-8", errors="replace")
        fmt = fmt or ("csv" if target.suffix.lower() == ".csv" else "smiles")
    if fmt == "csv":
        import csv
        import io
        reader = csv.DictReader(io.StringIO(text))
        column = payload.get("smilesColumn") or "smiles"
        name_column = payload.get("nameColumn") or "name"
        for row in reader:
            smiles = (row.get(column) or "").strip()
            if smiles:
                rows.append((smiles, (row.get(name_column) or "").strip()))
        return rows
    for chunk in str(text).replace(",", "\n").splitlines():
        line = chunk.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else line.split(None, 1)
        rows.append((parts[0], parts[1].strip() if len(parts) > 1 else ""))
    return rows


def _insert(conn, smiles, name="", tags="", source="", strict=False):
    m = molmod.parse_struct(smiles)
    key = molmod.inchikey(m)
    values = _props(m)
    try:
        conn.execute(
            "INSERT INTO molecules (smiles, canonical, inchikey, formula, mw, logp, tpsa, hbd,"
            " hba, rotb, rings, heavy, name, tags, source, fp_hex, created)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (smiles, molmod.canonical(m), key, molmod.formula(m), values["mw"], values["logp"],
             values["tpsa"], values["hbd"], values["hba"], values["rotb"], values["rings"],
             values["heavy"], name, tags, source, _fp_hex(m),
             time.strftime("%Y-%m-%dT%H:%M:%S")))
        return {"status": "added", "inchikey": key, "canonical": molmod.canonical(m)}
    except sqlite3.IntegrityError:
        if strict:
            raise molmod.MolError("duplicate", "库里已经有这个分子：" + key)
        return {"status": "duplicate", "inchikey": key}


def _row_to_dict(row):
    data = {key: row[key] for key in row.keys() if key != "fp_hex"}
    return data


def _do_add(conn, payload):
    rows = _read_source(payload)
    if not rows:
        return {"ok": False, "failure": {"code": "no-input", "message": "没有读到任何分子"}}
    added, duplicates, skipped = [], 0, []
    for smiles, name in rows:
        try:
            outcome = _insert(conn, smiles, name=name, source=payload.get("source") or "",
                              tags=payload.get("tags") or "",
                              strict=bool(payload.get("strict")))
        except molmod.MolError as exc:
            skipped.append({"smiles": smiles, "error": exc.message})
            continue
        if outcome["status"] == "added":
            added.append(outcome["inchikey"])
        else:
            duplicates += 1
    conn.commit()
    return {"ok": True, "channel": "sqlite",
            "data": {"db": str(db_path(payload)), "read": len(rows), "added": len(added),
                     "duplicates": duplicates, "skipped": skipped,
                     "total": conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]},
            "warnings": (["%d 个分子解析不了，已跳过" % len(skipped)] if skipped else [])}


def _do_search(conn, payload):
    from rdkit import DataStructs
    query_smiles = payload.get("query") or payload.get("smiles") or ""
    mode = (payload.get("mode") or ("substructure" if query_smiles else "filter")).strip().lower()
    limit = int(payload.get("limit") or 50)
    offset = int(payload.get("offset") or 0)

    if mode in ("substructure", "smart", "smarts"):
        if not query_smiles:
            return {"ok": False, "failure": {"code": "missing-input", "message": "子结构检索需要 query"}}
        from rdkit import Chem
        pattern = Chem.MolFromSmarts(query_smiles) or Chem.MolFromSmiles(query_smiles)
        if pattern is None:
            return {"ok": False, "failure": {"code": "bad-query", "message": "查询结构解析不了"}}
        hits = []
        for row in conn.execute("SELECT * FROM molecules"):
            try:
                candidate = molmod.parse_struct(row["canonical"])
            except molmod.MolError:
                continue
            match = candidate.GetSubstructMatch(pattern)
            if match:
                data = _row_to_dict(row)
                data["matched_atoms"] = list(match)
                hits.append(data)
        hits.sort(key=lambda r: r["mw"] or 0)
        return {"ok": True, "channel": "rdkit-substruct", "data": {
            "mode": "substructure", "query": query_smiles, "count": len(hits),
            "limit": limit, "offset": offset, "hits": hits[offset:offset + limit]}}

    if mode in ("similar", "similarity", "sim"):
        if not query_smiles:
            return {"ok": False, "failure": {"code": "missing-input", "message": "相似性检索需要 query"}}
        cutoff = float(payload.get("cutoff") or 0.3)
        reference = _fingerprint(molmod.parse_struct(query_smiles))
        rows = []
        for row in conn.execute("SELECT * FROM molecules"):
            if not row["fp_hex"]:
                continue
            fingerprint = DataStructs.CreateFromBinaryText(bytes.fromhex(row["fp_hex"]))
            score = DataStructs.TanimotoSimilarity(reference, fingerprint)
            if score >= cutoff:
                data = _row_to_dict(row)
                data["similarity"] = round(score, 4)
                rows.append(data)
        rows.sort(key=lambda r: -r["similarity"])
        return {"ok": True, "channel": "morgan-tanimoto", "data": {
            "mode": "similarity", "query": query_smiles, "cutoff": cutoff,
            "count": len(rows), "limit": limit, "offset": offset,
            "hits": rows[offset:offset + limit]}}

    if mode == "filter":
        clauses, params = [], []
        for field in PROP_FIELDS:
            low = payload.get(field + "Min")
            high = payload.get(field + "Max")
            if low is not None:
                clauses.append("%s >= ?" % field)
                params.append(float(low))
            if high is not None:
                clauses.append("%s <= ?" % field)
                params.append(float(high))
        if payload.get("name"):
            clauses.append("(name LIKE ? OR canonical LIKE ?)")
            params.extend(["%" + str(payload["name"]) + "%"] * 2)
        if payload.get("tags"):
            clauses.append("tags LIKE ?")
            params.append("%" + str(payload["tags"]) + "%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute("SELECT COUNT(*) FROM molecules" + where, params).fetchone()[0]
        rows = conn.execute("SELECT * FROM molecules" + where +
                            " ORDER BY mw LIMIT ? OFFSET ?", params + [limit, offset])
        return {"ok": True, "channel": "sqlite", "data": {
            "mode": "filter", "count": total, "limit": limit, "offset": offset,
            "hits": [_row_to_dict(r) for r in rows]}}

    return {"ok": False, "failure": {"code": "unknown-mode", "message": "不认识的 mode：" + mode,
                                    "hint": "substructure | similarity | filter"}}


def _do_export(conn, payload):
    fmt = (payload.get("format") or "sdf").strip().lower()
    out = payload.get("out")
    rows = [r for r in conn.execute("SELECT * FROM molecules ORDER BY id")]
    if not rows:
        return {"ok": False, "failure": {"code": "empty", "message": "库里没有分子"}}
    if fmt == "smiles":
        body = "\n".join(r["canonical"] for r in rows) + "\n"
    elif fmt == "csv":
        header = "smiles,inchikey,formula,mw,logp,tpsa,name,tags"
        lines = [header]
        for r in rows:
            lines.append(",".join(str(r[k] if r[k] is not None else "") for k in
                                  ("canonical", "inchikey", "formula", "mw", "logp", "tpsa",
                                   "name", "tags")))
        body = "\n".join(lines) + "\n"
    elif fmt in ("sdf", "mol"):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        chunks = []
        for index, r in enumerate(rows, start=1):
            m = molmod.parse_struct(r["canonical"])
            AllChem.Compute2DCoords(m)
            m.SetProp("_Name", r["name"] or ("mol-%d" % index))
            m.SetProp("inchikey", r["inchikey"])
            m.SetProp("mw", "%.3f" % (r["mw"] or 0))
            chunks.append(Chem.MolToMolBlock(m) + "$$$$\n")
        body = "".join(chunks)
    else:
        return {"ok": False, "failure": {"code": "bad-format", "message": "不认识的 format：" + fmt}}
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return {"ok": True, "channel": "export", "data": {
            "format": fmt, "count": len(rows), "path": str(target), "bytes": len(body)}}
    return {"ok": True, "channel": "export", "data": {"format": fmt, "count": len(rows),
                                                      "bytes": len(body), "inline": body}}


def handle(payload):
    action = (payload.get("action") or "search").strip().lower()
    if action == "path":
        return {"ok": True, "channel": "sqlite", "data": {"db": str(db_path(payload))}}
    if action == "stats":
        conn, path = _connect(payload)
        total = conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]
        span = conn.execute("SELECT MIN(mw), MAX(mw), AVG(mw) FROM molecules").fetchone()
        conn.close()
        return {"ok": True, "channel": "sqlite", "data": {
            "db": str(path), "total": total,
            "mwMin": round(span[0], 3) if span[0] is not None else None,
            "mwMax": round(span[1], 3) if span[1] is not None else None,
            "mwAvg": round(span[2], 3) if span[2] is not None else None}}
    if action == "remove":
        conn, path = _connect(payload)
        if payload.get("all"):
            conn.execute("DELETE FROM molecules")
            conn.commit()
            conn.close()
            return {"ok": True, "channel": "sqlite", "data": {"db": str(path), "removed": "all"}}
        key = payload.get("inchikey") or ""
        if not key:
            conn.close()
            return {"ok": False, "failure": {"code": "missing-input", "message": "需要 inchikey 或 all"}}
        cursor = conn.execute("DELETE FROM molecules WHERE inchikey = ?", (key,))
        conn.commit()
        removed = cursor.rowcount
        conn.close()
        return {"ok": True, "channel": "sqlite", "data": {"removed": removed, "inchikey": key}}

    conn, path = _connect(payload)
    try:
        if action == "add":
            try:
                return _do_add(conn, payload)
            except molmod.MolError as exc:
                return {"ok": False, "failure": {"code": exc.code, "message": exc.message,
                                                "hint": exc.hint}}
        if action in ("search", "query"):
            return _do_search(conn, payload)
        if action == "export":
            return _do_export(conn, payload)
        if action == "list":
            rows = conn.execute("SELECT * FROM molecules ORDER BY id LIMIT ? OFFSET ?",
                                (int(payload.get("limit") or 50), int(payload.get("offset") or 0)))
            return {"ok": True, "channel": "sqlite", "data": {
                "hits": [_row_to_dict(r) for r in rows]}}
        return {"ok": False, "failure": {"code": "unknown-action", "message": "不认识的 action：" + action,
                                        "hint": "add | search | list | export | remove | stats | path"}}
    finally:
        conn.close()
