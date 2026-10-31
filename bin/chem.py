#!/usr/bin/env python
"""dsh-chem engine entry: one subcommand = one tool, JSON in / JSON out.

Contract: the LAST line on stdout is always a single JSON object.
Anything libraries print while working is captured and discarded.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

TOOLS = ["parse", "clean", "draw", "props", "calc", "compare", "table", "db",
         "ml", "enum", "retro", "spectra", "exam", "office", "vendor"]


def emit(obj, code=0):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()
    raise SystemExit(code)


def _progid_path(progid):
    """Resolve a COM ProgID to its server executable via HKCR."""
    try:
        import winreg
    except Exception:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\CLSID") as k:
            clsid = winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None
    for sub in ("LocalServer32", "InprocServer32"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + "\\" + sub) as k2:
                raw = winreg.QueryValueEx(k2, "")[0].strip('"')
                return raw.split(" --")[0].split(" /")[0].strip()
        except OSError:
            continue
    return None


def probe():
    info = {"python": sys.version.split()[0], "executable": sys.executable,
            "packages": {}, "vendors": {}, "ocr": {}, "root": str(ROOT)}
    for name in ("rdkit", "numpy", "pandas", "sklearn", "scipy", "PIL", "pymupdf", "docx", "openpyxl"):
        try:
            mod = __import__(name)
            info["packages"][name] = getattr(mod, "__version__", "ok")
        except Exception:
            info["packages"][name] = None
    eng = Path(os.environ.get("LOCALAPPDATA", ".") or ".") / "chem-draw-tool" / "engines"
    for label in ("molvec", "decimer", "molscribe"):
        info["ocr"][label] = (eng / label).exists()
    found = None
    for progid in ("ChemDraw_x64.Application", "ChemDraw.Application"):
        found = _progid_path(progid)
        if found:
            break
    info["vendors"]["chemdraw"] = found
    info["vendors"]["kingdraw"] = None
    for progid in ("KingDrawObject.Document", "KingDrawXObject", "KingDraw.Application"):
        found = _progid_path(progid)
        if found:
            info["vendors"]["kingdraw"] = found
            break
    return info


def selfcheck():
    """Prove the runtime actually computes and renders, not just imports."""
    out = {"ok": False, "checks": []}
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, rdMolDescriptors
        from rdkit.Chem.Draw import rdMolDraw2D

        mol = Chem.MolFromSmiles("CC(=O)Nc1ccc(O)cc1")
        mw = round(Descriptors.MolWt(mol), 2)
        formula = rdMolDescriptors.CalcMolFormula(mol)
        out["checks"].append({"name": "mw", "value": mw, "expect": 151.16, "ok": abs(mw - 151.16) < 0.01})
        out["checks"].append({"name": "formula", "value": formula, "expect": "C8H9NO2", "ok": formula == "C8H9NO2"})

        d = rdMolDraw2D.MolDraw2DCairo(400, 300)
        rdMolDraw2D.PrepareAndDrawMolecule(d, mol)
        d.FinishDrawing()
        png = d.GetDrawingText()
        out["checks"].append({"name": "png", "bytes": len(png), "ok": png[:8] == b"\x89PNG\r\n\x1a\n"})

        svg_d = rdMolDraw2D.MolDraw2DSVG(400, 300)
        rdMolDraw2D.PrepareAndDrawMolecule(svg_d, mol)
        svg_d.FinishDrawing()
        svg = svg_d.GetDrawingText()
        import pymupdf
        doc = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
        pdf = doc.tobytes()
        out["checks"].append({"name": "svg_to_pdf", "bytes": len(pdf), "ok": pdf[:5] == b"%PDF-"})
        out["ok"] = all(c["ok"] for c in out["checks"])
    except Exception as exc:  # noqa: BLE001 - report, never raise
        out["error"] = type(exc).__name__ + ": " + str(exc)[:200]
    return out


def parse_payload(rest):
    """Tool arguments arrive as one JSON blob: --json '{"smiles": "CCO"}'."""
    if "--json" in rest:
        idx = rest.index("--json")
        if idx + 1 < len(rest):
            try:
                payload = json.loads(rest[idx + 1])
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}
    return {}


def dispatch(cmd, rest):
    if cmd == "probe":
        return {"ok": True, "probe": probe()}
    if cmd == "selfcheck":
        res = selfcheck()
        res["probe"] = probe()
        return res
    payload = parse_payload(rest)
    if cmd in TOOLS:
        from chem.cli import run_tool
        return run_tool(cmd, payload)
    return {"ok": False, "error": "unknown subcommand: " + cmd, "known": ["probe", "selfcheck"] + TOOLS}


def main(argv):
    if not argv:
        emit({"ok": False, "error": "no subcommand"}, 2)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = dispatch(argv[0], argv[1:])
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:300]}
    emit(result, 0 if result.get("ok") else 2)


if __name__ == "__main__":
    main(sys.argv[1:])
