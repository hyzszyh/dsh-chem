"""chem_vendor: CDXML and ChemDraw, with the vendor limits stated up front.

What works without the vendor (native, verified here):
  read/write/merge/split of CDXML, SDF and molfile.

What needs ChemDraw over COM:
  binary .cdx read/write, EPS, and preview rendering. This build's
  Documents.Open() and SaveAs() are measured silent no-ops, so those paths are
  attempted, re-read, and reported as failures when the round trip does not
  hold. CDXML is the interchange format ChemDraw itself reads and writes, so the
  practical workflow is covered without pretending the binary path works.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import mol as molmod


def _format_of(path):
    target = Path(path)
    if not target.is_file():
        return None
    head = target.read_bytes()[:64]
    if head.startswith(b"VjCD"):
        return "cdx"
    if head.lstrip().startswith(b"<?xml") or b"<CDXML" in head:
        return "cdxml"
    if head.startswith(b"$$$$") or b"V2000" in head or b"V3000" in head:
        return "sdf"
    return target.suffix.lower().lstrip(".") or "unknown"


def _cdxml_records(text):
    """Parse CDXML into molecules; one per connected component."""
    from rdkit import Chem

    root = ET.fromstring(text)
    atoms, bonds = {}, []
    order = []
    for node in root.iter("n"):
        node_id = node.get("id")
        if node_id is None:
            continue
        element = (node.get("Element") or "C").strip() or "C"
        position = (node.get("p") or "").split()
        atoms[node_id] = {"element": element,
                          "charge": int(float(node.get("Charge") or 0)),
                          "xy": (float(position[0]), float(position[1])) if len(position) >= 2 else (0.0, 0.0),
                          "isotope": node.get("Isotope")}
        order.append(node_id)
    for bond in root.iter("b"):
        begin, end = bond.get("B"), bond.get("E")
        if begin in atoms and end in atoms:
            bonds.append((begin, end, float(bond.get("Order") or 1)))

    rw = Chem.RWMol()
    index = {}
    for node_id in order:
        info = atoms[node_id]
        try:
            atom = Chem.Atom(info["element"])
        except Exception:  # noqa: BLE001
            atom = Chem.Atom("C")
        atom.SetFormalCharge(info["charge"])
        if info["isotope"]:
            try:
                atom.SetIsotope(int(float(info["isotope"])))
            except ValueError:
                pass
        index[node_id] = rw.AddAtom(atom)
    types = {1.0: Chem.BondType.SINGLE, 2.0: Chem.BondType.DOUBLE, 3.0: Chem.BondType.TRIPLE,
             1.5: Chem.BondType.SINGLE, 4.0: Chem.BondType.QUADRUPLE}
    for begin, end, value in bonds:
        rw.AddBond(index[begin], index[end], types.get(value, Chem.BondType.SINGLE))
    parent = rw.GetMol()
    conformer = Chem.Conformer(parent.GetNumAtoms())
    for node_id, info in atoms.items():
        conformer.SetAtomPosition(index[node_id],
                                 (info["xy"][0] / 20.0, -info["xy"][1] / 20.0, 0.0))
    parent.RemoveAllConformers()
    parent.AddConformer(conformer, assignId=True)

    fragments = Chem.GetMolFrags(parent, asMols=True, sanitizeFrags=False)
    out = []
    for fragment in fragments:
        if fragment.GetNumAtoms() == 0:
            continue
        try:
            Chem.SanitizeMol(fragment)
            Chem.AssignStereochemistry(fragment, cleanIt=True, force=True)
        except Exception:  # noqa: BLE001
            continue
        out.append(fragment)
    return out


def _read_native(path):
    from rdkit import Chem

    fmt = _format_of(path)
    if fmt == "cdxml":
        return _cdxml_records(Path(path).read_text(encoding="utf-8", errors="replace"))
    if fmt in ("sdf", "mol"):
        if fmt == "mol":
            m = Chem.MolFromMolFile(str(path), sanitize=True, removeHs=True)
            return [m] if m is not None else []
        supplier = Chem.SDMolSupplier(str(path), sanitize=True, removeHs=True)
        return [m for m in supplier if m is not None]
    return []


def _cdxml_document(mols, names):
    """One CDXML page, one fragment per molecule, laid out left to right."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    node_id, bond_id, pages, offset_x = 1, 1, [], 0.0
    fragments = []
    for mol, name in zip(mols, names):
        work = Chem.Mol(mol)
        AllChem.Compute2DCoords(work)
        conformer = work.GetConformer()
        xs = [conformer.GetAtomPosition(i).x for i in range(work.GetNumAtoms())]
        ys = [conformer.GetAtomPosition(i).y for i in range(work.GetNumAtoms())]
        shift = offset_x - (min(xs) if xs else 0.0)
        offset_x += (max(xs) - min(xs) if xs else 0.0) + 2.0
        nodes, edges = [], []
        ids = {}
        for atom in work.GetAtoms():
            ids[atom.GetIdx()] = node_id
            point = conformer.GetAtomPosition(atom.GetIdx())
            attributes = 'id="%d" p="%.2f %.2f"' % (node_id, (point.x + shift) * 20.0,
                                                    -point.y * 20.0)
            if atom.GetSymbol() != "C":
                attributes += ' Element="%s"' % atom.GetSymbol()
            if atom.GetFormalCharge():
                attributes += ' Charge="%d"' % atom.GetFormalCharge()
            nodes.append("<n %s/>" % attributes)
            node_id += 1
        for bond in work.GetBonds():
            order = {Chem.BondType.SINGLE: 1, Chem.BondType.DOUBLE: 2,
                     Chem.BondType.TRIPLE: 3, Chem.BondType.AROMATIC: 1.5}.get(bond.GetBondType(), 1)
            edges.append('<b id="%d" B="%d" E="%d" Order="%s"/>'
                         % (bond_id, ids[bond.GetBeginAtomIdx()], ids[bond.GetEndAtomIdx()], order))
            bond_id += 1
        # No anchor <n> inside the fragment: an extra node with a real id became a
        # phantom methane on read-back (two molecules came back as four records).
        fragments.append('<fragment id="%d">\n  %s\n  %s\n</fragment>'
                         % (len(fragments) + 1, "\n  ".join(nodes), "\n  ".join(edges)))
        pages.append(name)
    width = max(540.0, (offset_x + 2.0) * 20.0)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CDXML Name="dsh-chem"><page id="1" BoundingBox="0 0 %.2f 400">\n%s\n</page></CDXML>'
            % (width, "\n".join(fragments)))


def _chemdraw():
    """Return a live ChemDraw channel or raise MolError(needs-vendor)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from chemdraw_tool.adapters import cd_com
        channel = cd_com.channel()
    except Exception as exc:  # noqa: BLE001
        raise molmod.MolError("needs-vendor", "ChemDraw 通道起不来：%s" % str(exc)[:120],
                              "确认 ChemDraw 已安装；CDXML 路径不需要它")
    return channel


def _do_read(payload):
    path = payload.get("path") or ""
    if not path or not Path(path).is_file():
        return {"ok": False, "failure": {"code": "no-such-file", "path": path,
                                        "message": "找不到文件"}}
    fmt = _format_of(path)
    notes = []
    mols = _read_native(path)
    channel_used = "native"
    if fmt == "cdx":
        try:
            channel = _chemdraw()
            channel.open_binary(str(path)) if hasattr(channel, "open_binary") else None
            opened = channel.read_current("smiles") if hasattr(channel, "read_current") else None
            text = getattr(opened, "value", None) or getattr(opened, "smiles", None)
            if text:
                mols = [molmod.parse_struct(t) for t in str(text).split() if t]
                channel_used = "chemdraw"
            else:
                notes.append("ChemDraw 打不开这个 .cdx（本机 Documents.Open 是静默空操作）")
        except molmod.MolError as exc:
            notes.append(exc.message)
    if not mols:
        return {"ok": False, "failure": {
            "code": "unreadable", "format": fmt, "path": path,
            "message": "读不出结构（format=%s）" % fmt,
            "hint": "cdxml / sdf / mol 走本地解析；二进制 cdx 需要 ChemDraw 打开后另存为 cdxml",
            "notes": notes}}
    records = []
    for index, m in enumerate(mols, start=1):
        records.append({"index": index, "smiles": molmod.canonical(m),
                        "formula": molmod.formula(m), "inchikey": molmod.inchikey(m),
                        "atoms": m.GetNumAtoms()})
    return {"ok": True, "channel": channel_used,
            "data": {"path": path, "format": fmt, "count": len(records), "records": records},
            "warnings": notes}


def _do_write(payload):
    from rdkit import Chem
    from rdkit.Chem import AllChem

    text = payload.get("smiles") or payload.get("smilesList") or ""
    if isinstance(text, list):
        items = [str(t) for t in text]
    else:
        items = [s.strip() for s in str(text).replace(",", "\n").splitlines() if s.strip()]
    if not items:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles 列表"}}
    out = payload.get("out") or ""
    if not out:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 out（目标文件路径）"}}
    suffix = Path(out).suffix.lower().lstrip(".")
    names = payload.get("names") or []
    mols = [molmod.parse_struct(s) for s in items]
    if suffix == "cdxml":
        body = _cdxml_document(mols, [names[i] if i < len(names) else "mol-%d" % (i + 1)
                                      for i in range(len(mols))])
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        parsed = _read_native(target)
        return {"ok": True, "channel": "native-cdxml",
                "data": {"path": str(target), "count": len(mols), "bytes": len(body),
                         "reread": len(parsed),
                         "rereadInchikeys": [molmod.inchikey(m) for m in parsed]},
                "evidence": {"verified": "wrote, then parsed the file back"}}
    if suffix in ("sdf", "mol"):
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        writer = Chem.SDWriter(str(target))
        for index, m in enumerate(mols):
            AllChem.Compute2DCoords(m)
            m.SetProp("_Name", names[index] if index < len(names) else "mol-%d" % (index + 1))
            writer.write(m)
        writer.close()
        return {"ok": True, "channel": "rdkit",
                "data": {"path": str(target), "count": len(mols), "bytes": target.stat().st_size}}
    if suffix == "cdx":
        try:
            channel = _chemdraw()
        except molmod.MolError as exc:
            return {"ok": False, "failure": {"code": exc.code, "message": exc.message,
                                            "hint": "先写 cdxml，让 ChemDraw 另存为 cdx"}}
        produced = False
        save = getattr(channel, "save_as", None)
        if callable(save):
            result = save(str(out))
            produced = bool(getattr(result, "ok", False))
        if not produced or not Path(out).is_file():
            return {"ok": False, "failure": {
                "code": "vendor-save-failed", "format": "cdx",
                "message": "本机 ChemDraw 的 SaveAs 是静默空操作，写不出 .cdx",
                "hint": "写 cdxml（ChemDraw 可直接打开），或用 ChemDraw 界面另存"}}
        return {"ok": True, "channel": "chemdraw",
                "data": {"path": out, "count": len(mols), "bytes": Path(out).stat().st_size}}
    return {"ok": False, "failure": {"code": "bad-format", "message": "不认识的扩展名：" + suffix,
                                    "hint": "cdxml | sdf | mol | cdx"}}


def _do_merge(payload):
    paths = payload.get("paths") or payload.get("inputs") or []
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.replace(",", "\n").splitlines() if p.strip()]
    if not paths:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 paths 列表"}}
    mols, names, problems = [], [], []
    for path in paths:
        try:
            found = _read_native(path)
        except Exception as exc:  # noqa: BLE001
            problems.append({"path": path, "error": str(exc)[:120]})
            continue
        if not found:
            problems.append({"path": path, "error": "读不出结构"})
            continue
        for m in found:
            mols.append(m)
            names.append(Path(path).stem)
    if not mols:
        return {"ok": False, "failure": {"code": "nothing-to-merge", "problems": problems,
                                        "message": "没有可合并的结构"}}
    out = payload.get("out") or ""
    suffix = Path(out).suffix.lower().lstrip(".") if out else "cdxml"
    if suffix not in ("cdxml", "sdf"):
        return {"ok": False, "failure": {"code": "bad-format",
                                        "message": "合并只支持 cdxml / sdf 输出"}}
    written = _do_write({"smiles": [molmod.canonical(m) for m in mols], "names": names, "out": out})
    if not written.get("ok"):
        return written
    written["data"]["mergedFrom"] = len(paths)
    written["data"]["problems"] = problems
    if problems:
        written.setdefault("warnings", []).append("%d 个输入读不出来，已跳过" % len(problems))
    return written


def _do_split(payload):
    path = payload.get("path") or ""
    outdir = payload.get("outDir") or payload.get("out") or ""
    if not path or not outdir:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 path 和 outDir"}}
    mols = _read_native(path)
    if not mols:
        return {"ok": False, "failure": {"code": "unreadable", "message": "读不出结构：" + path}}
    suffix = (payload.get("format") or Path(path).suffix.lstrip(".") or "cdxml").lower()
    target_dir = Path(outdir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    written = []
    if suffix == "sdf":
        from rdkit import Chem
        from rdkit.Chem import AllChem
        for index, m in enumerate(mols, start=1):
            target = target_dir / ("%s-%02d.sdf" % (stem, index))
            AllChem.Compute2DCoords(m)
            writer = Chem.SDWriter(str(target))
            writer.write(m)
            writer.close()
            written.append(str(target))
    else:
        for index, m in enumerate(mols, start=1):
            target = target_dir / ("%s-%02d.cdxml" % (stem, index))
            body = _cdxml_document([m], ["part-%d" % index])
            target.write_text(body, encoding="utf-8")
            written.append(str(target))
    return {"ok": True, "channel": "native",
            "data": {"path": path, "parts": len(written), "files": written}}


def _do_eps(payload):
    out = payload.get("out") or ""
    smiles = payload.get("smiles") or ""
    if not out:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 out"}}
    try:
        channel = _chemdraw()
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message,
                                        "hint": "EPS 只能由 ChemDraw 出；本地矢量请用 chem_draw format=pdf"}}
    if smiles and hasattr(channel, "draw_smiles"):
        channel.draw_smiles(smiles)
    exporter = getattr(channel, "export", None)
    if not callable(exporter):
        return {"ok": False, "failure": {"code": "needs-vendor", "message": "ChemDraw 通道没有 export 方法"}}
    exporter(str(out), "eps")
    if not Path(out).is_file():
        return {"ok": False, "failure": {"code": "vendor-export-failed", "format": "eps",
                                        "message": "ChemDraw 没有写出 EPS",
                                        "hint": "改用 chem_draw format=pdf（矢量，本地可出）"}}
    head = Path(out).read_bytes()[:20]
    return {"ok": True, "channel": "chemdraw",
            "data": {"path": str(out), "bytes": Path(out).stat().st_size,
                     "postscriptHeader": head.startswith(b"%!PS"), "vector": True}}


def _do_preview(payload):
    out = payload.get("out") or ""
    if not out:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 out"}}
    try:
        channel = _chemdraw()
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message,
                                        "hint": "预览需要 ChemDraw；本地出图请用 chem_draw"}}
    if payload.get("smiles") and hasattr(channel, "draw_smiles"):
        channel.draw_smiles(payload["smiles"])
    exporter = getattr(channel, "export", None)
    if callable(exporter):
        exporter(str(out), "png")
    if not Path(out).is_file():
        return {"ok": False, "failure": {"code": "vendor-export-failed", "message": "ChemDraw 没写出 PNG"}}
    return {"ok": True, "channel": "chemdraw",
            "data": {"path": str(out), "bytes": Path(out).stat().st_size}}


PROGIDS = ("ChemDraw_x64.Application", "ChemDraw.Application", "ChemDraw_x64.Document")


def _do_probe():
    """Report what the vendor channel can actually do on this machine.

    Measured, not assumed: dispatch each known ProgID and keep the name it answers
    with. The 64-bit build answers to ChemDraw_x64.Application; the un-suffixed name
    is the 32-bit one and raises 'invalid class string' here. A detector that only
    knows the old name calls a perfectly working ChemDraw 'not installed'.
    """
    data = {"chemdraw": {"progid": None, "name": None, "exe": None, "dispatch": False},
            "kingdraw": {"progid": None, "dispatch": False},
            "formats": {"cdxml": "native", "sdf": "native", "mol": "native",
                        "cdx": "measured-unwritable", "eps": "chemdraw",
                        "preview": "chemdraw"}}
    notes = []

    try:
        import win32com.client as win32
    except Exception as exc:  # noqa: BLE001
        data["chemdraw"]["note"] = "pywin32 不可用：%s" % str(exc)[:80]
        win32 = None

    if win32 is not None:
        for progid in PROGIDS:
            try:
                app = win32.Dispatch(progid)
            except Exception as exc:  # noqa: BLE001
                notes.append("%s: %s" % (progid, str(exc)[:60]))
                continue
            name = None
            for attribute in ("Name", "FullName", "Caption"):
                try:
                    value = getattr(app, attribute)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(value, str) and value:
                    name = value
                    break
            try:
                data["chemdraw"]["exe"] = str(getattr(app, "FullName", "") or "") or None
            except Exception:  # noqa: BLE001
                pass
            data["chemdraw"].update({"progid": progid, "name": name, "dispatch": True})
            # Do not Quit here: cd_com keeps a module-level channel, and quitting the
            # instance the probe just created left later exports writing nothing
            # (measured: eps worked 3/3 alone, failed whenever a probe had quit first).
            del app
            break

    if not data["chemdraw"]["dispatch"]:
        exe = _chemdraw_exe()
        data["chemdraw"]["exe"] = exe
        data["formats"]["eps"] = "needs-vendor"
        data["formats"]["preview"] = "needs-vendor"

    return {"ok": True, "channel": "probe", "data": data,
            "warnings": notes,
            "evidence": {"measured": "Dispatched %d ProgID candidate(s)" % len(PROGIDS)}}


def _chemdraw_exe():
    roots = [r"C:\Program Files\RevvitySignalsSoftware\ChemDrawApplications_x64",
             r"C:\Program Files (x86)\RevvitySignalsSoftware\ChemDrawApplications"]
    for root in roots:
        candidate = Path(root) / "ChemDraw.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def handle(payload):
    # The tool surface (chem_vendor) speaks 'do' and calls the target file 'path';
    # the handlers below predate it and speak 'action' / 'out'. Without this adapter
    # every call fell through to action=info and answered no-such-file on a path that
    # was never meant to be an input -- the whole vendor channel looked unavailable.
    payload = dict(payload or {})
    action = (payload.get("action") or payload.get("do") or "info").strip().lower()
    aliases = {
        "cdx-read": "read", "read-cdx": "read", "open": "read",
        "cdx-write": "write", "write-cdx": "write", "cdxml-write": "write",
        "save": "write", "to-eps": "eps", "png": "preview", "render-png": "preview",
    }
    action = aliases.get(action, action)
    if payload.get("path") and not payload.get("out") and action in ("write", "merge", "split", "eps", "preview"):
        payload["out"] = payload["path"]
    try:
        if action in ("probe", "status", "capabilities"):
            return _do_probe()
        if action == "info":
            path = payload.get("path") or ""
            if not path or not Path(path).is_file():
                return {"ok": False, "failure": {"code": "no-such-file", "path": path}}
            fmt = _format_of(path)
            records = _read_native(path)
            return {"ok": True, "channel": "native", "data": {
                "path": path, "format": fmt, "bytes": Path(path).stat().st_size,
                "records": len(records),
                "needsVendor": fmt == "cdx"}}
        if action == "read":
            return _do_read(payload)
        if action in ("write", "save"):
            return _do_write(payload)
        if action == "merge":
            return _do_merge(payload)
        if action == "split":
            return _do_split(payload)
        if action == "eps":
            return _do_eps(payload)
        if action in ("preview", "render"):
            return _do_preview(payload)
        if action == "close":
            try:
                channel = _chemdraw()
            except molmod.MolError as exc:
                return {"ok": True, "channel": "none", "data": {"closed": False,
                                                                "note": exc.message}}
            closer = getattr(channel, "close", None)
            if callable(closer):
                closer()
            return {"ok": True, "channel": "chemdraw", "data": {"closed": True}}
        return {"ok": False, "failure": {"code": "unknown-action", "message": "不认识的 action：" + action,
                                        "hint": "info | read | write | merge | split | eps | preview | close"}}
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message, "hint": exc.hint}}
