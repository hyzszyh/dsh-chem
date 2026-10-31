"""chem_compare: is this molecule like that one, and why.

sim     -- Tanimoto over Morgan/MACCS fingerprints, sorted, with the fields you
           would actually argue about (MW, logP, TPSA) beside the score.
mcs     -- maximum common substructure across a set: the shared core, as SMARTS.
cluster -- Butina clustering at a similarity cutoff, so "pick 20 diverse ones"
           stops being a manual job.
sar     -- a structure-activity-ready table: similarity plus per-property deltas
           against a reference compound.
"""
from __future__ import annotations

import re

from . import mol as molmod


def _split_list(text):
    return [s for s in re.split(r"[\n,;]+", str(text or "")) if s.strip()]


def _gen():
    from rdkit.Chem import rdFingerprintGenerator
    return rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def _props(m):
    from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
    return {"mw": round(Descriptors.MolWt(m), 3),
            "logp": round(Crippen.MolLogP(m), 3),
            "tpsa": round(rdMolDescriptors.CalcTPSA(m), 3)}


def _rows(molecules):
    rows = []
    for i, text in enumerate(molecules):
        try:
            m = molmod.parse_struct(text)
        except molmod.MolError:
            rows.append({"index": i, "input": text, "valid": False})
            continue
        row = {"index": i, "input": text, "valid": True,
               "smiles": molmod.canonical(m), "formula": molmod.formula(m)}
        row.update(_props(m))
        rows.append(row)
    return rows


def _sim(payload):
    from rdkit import DataStructs
    query_text = payload.get("query") or ""
    candidates = _split_list(payload.get("smilesList") or payload.get("smiles") or "")
    if not query_text or not candidates:
        return {"ok": False, "failure": {"code": "missing-input",
                                        "message": "需要 query 与 smilesList"}}
    try:
        query = molmod.parse_struct(query_text)
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message, "hint": exc.hint}}

    gen = _gen()
    query_fp = gen.GetFingerprint(query)
    results = []
    for row in _rows(candidates):
        if not row["valid"]:
            results.append({"index": row["index"], "valid": False, "input": row["input"]})
            continue
        m = molmod.parse_struct(row["smiles"])
        score = DataStructs.TanimotoSimilarity(query_fp, gen.GetFingerprint(m))
        item = dict(row)
        item["tanimoto"] = round(score, 4)
        results.append(item)
    results.sort(key=lambda r: (-(r.get("tanimoto") or -1), r["index"]))
    return {"ok": True, "channel": "rdkit",
            "data": {"query": molmod.canonical(query), "query_props": _props(query),
                     "count": len(results), "results": results},
            "evidence": {"fingerprint": "Morgan r=2, 2048 bits", "metric": "Tanimoto"}}


def _mcs(payload):
    from rdkit.Chem import rdFMCS
    items = _split_list(payload.get("smilesList") or payload.get("smiles") or "")
    if len(items) < 2:
        return {"ok": False, "failure": {"code": "needs-two", "message": "MCS 至少需要两个分子"}}
    mols = []
    for text in items:
        try:
            mols.append(molmod.parse_struct(text))
        except molmod.MolError:
            continue
    if len(mols) < 2:
        return {"ok": False, "failure": {"code": "needs-two", "message": "有效分子少于两个"}}
    res = rdFMCS.FindMCS(mols, timeout=int(payload.get("timeoutSeconds") or 10),
                         completeRingsOnly=True)
    return {"ok": True, "channel": "rdkit",
            "data": {"smarts": res.smartsString, "atoms": res.numAtoms, "bonds": res.numBonds,
                     "cancelled": bool(res.canceled), "mol_count": len(mols)},
            "evidence": {"method": "rdFMCS, completeRingsOnly"}}


def _cluster(payload):
    from rdkit import DataStructs
    from rdkit.ML.Cluster import Butina
    items = _split_list(payload.get("smilesList") or payload.get("smiles") or "")
    cutoff = float(payload.get("cutoff") or 0.4)
    mols, rows = [], []
    for i, text in enumerate(items):
        try:
            m = molmod.parse_struct(text)
        except molmod.MolError:
            continue
        mols.append(m)
        rows.append({"index": i, "smiles": molmod.canonical(m), "formula": molmod.formula(m)})
    if len(mols) < 2:
        return {"ok": False, "failure": {"code": "needs-two", "message": "聚类至少需要两个有效分子"}}
    gen = _gen()
    fps = [gen.GetFingerprint(m) for m in mols]
    distances = []
    for i in range(1, len(fps)):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        distances.extend([1.0 - s for s in sims])
    clusters = Butina.ClusterData(distances, len(fps), cutoff, isDistData=True)
    out = []
    for cid, members in enumerate(clusters):
        out.append({"cluster": cid, "size": len(members),
                    "members": [rows[i] for i in members]})
    out.sort(key=lambda c: -c["size"])
    return {"ok": True, "channel": "rdkit",
            "data": {"cutoff": cutoff, "clusters": out, "cluster_count": len(out)},
            "evidence": {"method": "Butina on 1 - Tanimoto (Morgan r=2)"}}


def _sar(payload):
    query_text = payload.get("query") or ""
    items = _split_list(payload.get("smilesList") or payload.get("smiles") or "")
    if not query_text or not items:
        return {"ok": False, "failure": {"code": "missing-input",
                                        "message": "SAR 表需要 query（参照分子）与 smilesList"}}
    base = _sim({"query": query_text, "smilesList": payload.get("smilesList") or payload.get("smiles")})
    if not base.get("ok"):
        return base
    ref = base["data"]["query_props"]
    table = []
    for row in base["data"]["results"]:
        if not row.get("valid"):
            continue
        table.append({
            "index": row["index"], "smiles": row["smiles"], "formula": row["formula"],
            "tanimoto": row["tanimoto"],
            "mw": row["mw"], "d_mw": round(row["mw"] - ref["mw"], 3),
            "logp": row["logp"], "d_logp": round(row["logp"] - ref["logp"], 3),
            "tpsa": row["tpsa"], "d_tpsa": round(row["tpsa"] - ref["tpsa"], 3),
        })
    return {"ok": True, "channel": "rdkit",
            "data": {"reference": base["data"]["query"], "reference_props": ref,
                     "rows": table, "count": len(table)},
            "evidence": {"note": "d_* 是相对参照分子的差值"}}
def handle(payload):
    mode = (payload.get("mode") or "sim").strip().lower()
    if mode == "sim":
        return _sim(payload)
    if mode == "mcs":
        return _mcs(payload)
    if mode == "cluster":
        return _cluster(payload)
    if mode == "sar":
        return _sar(payload)
    return {"ok": False, "failure": {"code": "unknown-mode", "message": "不认识的 mode：" + mode,
                                    "hint": "sim | mcs | cluster | sar"}}
