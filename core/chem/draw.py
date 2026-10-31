"""chem_draw: figures that survive a journal's production desk.

One tool, four views:
  mol   -- one structure, at a physical width in mm, with margin and bond-length
           measured and reported instead of eyeballed
  grid  -- a contact sheet: equal bond lengths across panels, so molecules can
           actually be compared
  rxn   -- reaction scheme (honestly reported as raster, vector needs ChemDraw)
  mech  -- SVG with curved electron-pushing arrows drawn between atom pairs

Formats: png, svg, pdf (vector, via SVG -> PyMuPDF), tif (with dpi metadata),
eps (needs ChemDraw -- reported as needs-vendor, never faked).
"""
from __future__ import annotations

import os
import statistics
from pathlib import Path

from . import mol as molmod

MM_PER_INCH = 25.4
PRESETS = {
    "cn-1col": 80.0, "cn-2col": 170.0, "acs-1col": 82.6, "acs-2col": 177.8,
    "rsc-1col": 83.0, "nature-1col": 89.0, "nature-2col": 183.0, "elsevier-1col": 90.0,
}
MIN_BOND_PX = 8.0
PADDING = 0.06


def _px(width_mm, dpi):
    return max(32, int(round(width_mm / MM_PER_INCH * dpi)))


def _prepare(smiles):
    from rdkit import Chem
    m = molmod.parse_struct(smiles)
    Chem.rdDepictor.Compute2DCoords(m)
    return m


def _options():
    from rdkit.Chem.Draw import rdMolDraw2D
    opts = rdMolDraw2D.MolDrawOptions()
    opts.padding = PADDING
    opts.bondLineWidth = 2
    opts.addStereoAnnotation = True
    return opts


def _bond_stats(drawer, m):
    """Bond length in pixels, measured on a Cairo render.

    The SVG backend reports coordinates in its own units (415 px for a bond that
    is 149 px in the PNG), so measurements always come from one backend. Two
    numbers that disagree would be worse than one that is merely approximate.
    """
    from rdkit.Chem.Draw import rdMolDraw2D
    cairo = rdMolDraw2D.MolDraw2DCairo(drawer.Width(), drawer.Height())
    cairo.SetDrawOptions(_options())
    rdMolDraw2D.PrepareAndDrawMolecule(cairo, m)
    cairo.FinishDrawing()
    drawer = cairo
    lengths = []
    for bond in m.GetBonds():
        # GetDrawCoords takes an atom index here; passing a Point3D is rejected
        # by the C++ signature, which is how this was found.
        a = drawer.GetDrawCoords(bond.GetBeginAtomIdx())
        b = drawer.GetDrawCoords(bond.GetEndAtomIdx())
        lengths.append(((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5)
    if not lengths:
        return {"median_px": None, "min_px": None, "bonds": 0}
    return {"median_px": round(statistics.median(lengths), 2),
            "min_px": round(min(lengths), 2), "bonds": len(lengths)}


def _ink_margin(png_bytes):
    """Margin actually left around the ink.

    Measured on luminance, not alpha: RDKit's Cairo backend writes RGB with no
    transparency at all, so an alpha bbox reports the full canvas and the margin
    silently reads as 0% (which is exactly how this was caught).
    """
    import io

    from PIL import Image
    image = Image.open(io.BytesIO(png_bytes)).convert("L")
    width, height = image.size
    ink = image.point(lambda v: 255 if v < 250 else 0)
    bbox = ink.getbbox()
    if not bbox:
        return {"width": width, "height": height, "margin_px": 0, "ratio": 0.0, "ink_px": 0}
    left, top, right, bottom = bbox
    margin = min(left, top, width - right, height - bottom)
    return {"width": width, "height": height, "margin_px": int(margin),
            "ratio": round(margin / max(1, min(width, height)), 4),
            "ink_px": [right - left, bottom - top]}


def _write(path, payload, binary=False):
    if not path:
        return None
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8", "newline": ""}
    with open(path, mode, **kwargs) as handle:
        handle.write(payload)
    return os.path.abspath(path)


def _svg_to_pdf(svg_text, width_mm):
    """Vector PDF at the requested physical size.

    PyMuPDF maps the SVG's px width to points 1:1, so a 1004 px figure came out
    1004 pt wide (354 mm) -- a journal would reject it. The page is therefore
    rebuilt at width_mm * 72/25.4 and the vector content is placed into it.
    """
    import pymupdf
    svg_doc = pymupdf.open(stream=svg_text.encode("utf-8"), filetype="svg")
    # show_pdf_page() refuses a non-PDF source, so the SVG becomes a PDF first;
    # the second document then only re-frames it at the right physical width.
    intermediate = pymupdf.open("pdf", svg_doc.convert_to_pdf())
    src_rect = intermediate[0].rect
    width_pt = width_mm * 72.0 / MM_PER_INCH
    height_pt = width_pt * (src_rect.height / max(1e-6, src_rect.width))
    out = pymupdf.open()
    page = out.new_page(width=width_pt, height=height_pt)
    page.show_pdf_page(page.rect, intermediate, 0)
    data = out.tobytes()
    out.close()
    intermediate.close()
    svg_doc.close()
    return data


def _png_to_tiff(png_bytes, dpi):
    import io

    from PIL import Image
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="TIFF", dpi=(dpi, dpi))
    return buffer.getvalue()


def _draw_one(smiles, payload):
    from rdkit.Chem.Draw import rdMolDraw2D

    preset = payload.get("preset")
    width_mm = float(payload.get("widthMm") or PRESETS.get(preset, 85.0))
    dpi = int(payload.get("dpi") or 300)
    fmt = (payload.get("format") or "png").strip().lower()
    if fmt == "eps":
        return {"ok": False, "failure": {
            "code": "needs-vendor", "format": "eps",
            "message": "EPS 需要 ChemDraw 通道（W6 的 chem_vendor）；本地矢量路径只到 PDF",
            "hint": "改要 format=pdf（同样矢量），或等 chem_vendor 的 eps"}}

    m = _prepare(smiles)
    width_px = _px(width_mm, dpi)
    height_px = int(round(width_px * 0.72))
    opts = _options()

    if fmt in ("svg", "pdf"):
        drawer = rdMolDraw2D.MolDraw2DSVG(width_px, height_px)
        drawer.SetDrawOptions(opts)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, m)
        drawer.FinishDrawing()
        stats = _bond_stats(drawer, m)
        svg = drawer.GetDrawingText()
        if fmt == "svg":
            payload_bytes, binary, media = svg, False, "image/svg+xml"
        else:
            payload_bytes, binary, media = _svg_to_pdf(svg, width_mm), True, "application/pdf"
    else:
        drawer = rdMolDraw2D.MolDraw2DCairo(width_px, height_px)
        drawer.SetDrawOptions(opts)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, m)
        drawer.FinishDrawing()
        stats = _bond_stats(drawer, m)
        png = drawer.GetDrawingText()
        if fmt == "png":
            payload_bytes, binary, media = png, True, "image/png"
        elif fmt == "tif" or fmt == "tiff":
            payload_bytes, binary, media = _png_to_tiff(png, dpi), True, "image/tiff"
        else:
            return {"ok": False, "failure": {"code": "bad-format",
                                             "message": "不认识的 format：" + fmt,
                                             "hint": "png | svg | pdf | tif | eps"}}

    out_path = _write(payload.get("out"), payload_bytes, binary=binary)
    margin = _ink_margin(_as_png(smiles, width_px, height_px))
    readable = stats["median_px"] is not None and stats["median_px"] >= MIN_BOND_PX
    data = {"format": fmt, "media": media, "widthMm": round(width_mm, 2), "dpi": dpi,
            "widthPx": width_px, "heightPx": height_px,
            "bytes": len(payload_bytes), "path": out_path,
            "bonds": stats, "readable": readable,
            "minBondPx": MIN_BOND_PX, "padding": margin,
            "vector": fmt in ("svg", "pdf")}
    warnings = []
    if not readable:
        warnings.append("键长中位数 %s px 低于 %s px，缩小后看着会糊" % (stats["median_px"], MIN_BOND_PX))
    if margin["ratio"] < 0.02:
        warnings.append("留白只有 %.1f%%，裁切风险高" % (margin["ratio"] * 100))
    if preset:
        data["preset"] = preset
    return {"ok": True, "channel": "rdkit", "data": data,
            "warnings": warnings,
            "evidence": {"layout": "RDKit Compute2DCoords", "padding": PADDING}}


def _as_png(smiles, width_px, height_px):
    from rdkit.Chem.Draw import rdMolDraw2D
    m = _prepare(smiles)
    drawer = rdMolDraw2D.MolDraw2DCairo(width_px, height_px)
    drawer.SetDrawOptions(_options())
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, m)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def _draw_grid(list_text, payload):
    from rdkit.Chem import Draw
    from rdkit.Chem.Draw import rdMolDraw2D

    items = [s for s in str(list_text or "").replace("\n", ",").split(",") if s.strip()]
    if not items:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要分子列表"}}
    mols, legends, skipped = [], [], []
    for text in items:
        try:
            mols.append(_prepare(text))
            legends.append(text[:28])
        except molmod.MolError:
            skipped.append(text)
    if not mols:
        return {"ok": False, "failure": {"code": "no-valid", "message": "没有可画的分子"}}

    columns = int(payload.get("columns") or 3)
    width_mm = float(payload.get("widthMm") or PRESETS.get(payload.get("preset"), 170.0))
    dpi = int(payload.get("dpi") or 300)
    fmt = (payload.get("format") or "png").strip().lower()
    if fmt == "eps":
        return {"ok": False, "failure": {"code": "needs-vendor", "format": "eps",
                                        "message": "网格图的 EPS 同样需要 ChemDraw 通道"}}
    total_px = _px(width_mm, dpi)
    cell = max(90, total_px // max(1, columns))
    image = Draw.MolsToGridImage(mols, molsPerRow=columns, subImgSize=(cell, cell),
                                 legends=legends, useSVG=False)
    import io
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    if fmt == "tif" or fmt == "tiff":
        payload_bytes, binary, media = _png_to_tiff(png, dpi), True, "image/tiff"
    elif fmt == "png":
        payload_bytes, binary, media = png, True, "image/png"
    else:
        from PIL import Image
        svg_drawer = rdMolDraw2D.MolDraw2DSVG(total_px, total_px)
        del svg_drawer
        return {"ok": False, "failure": {"code": "raster-grid",
                                        "message": "网格图目前只出 PNG/TIFF；要矢量请单画或用 svg 逐张",
                                        "hint": "format=png | tif"}}
    out_path = _write(payload.get("out"), payload_bytes, binary=binary)
    return {"ok": True, "channel": "rdkit",
            "data": {"format": fmt, "media": media, "count": len(mols),
                     "skipped": skipped, "columns": columns,
                     "widthMm": round(width_mm, 2), "dpi": dpi,
                     "cellPx": cell, "bytes": len(payload_bytes), "path": out_path,
                     "vector": False},
            "warnings": (["%d 个输入画不出来：%s" % (len(skipped), ", ".join(skipped[:3]))] if skipped else []),
            "evidence": {"layout": "MolsToGridImage, equal bond length across panels"}}


def _draw_rxn(reaction, payload):
    from rdkit.Chem import AllChem, Draw

    text = str(reaction or "")
    if ">>" not in text:
        return {"ok": False, "failure": {"code": "bad-reaction",
                                        "message": "反应式需要 A.B>>C.D 的形式"}}
    try:
        rxn = AllChem.ReactionFromSmarts(text)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "failure": {"code": "bad-reaction", "message": str(exc)[:200]}}
    dpi = int(payload.get("dpi") or 300)
    width_mm = float(payload.get("widthMm") or PRESETS.get(payload.get("preset"), 170.0))
    width_px = _px(width_mm, dpi)
    cell = max(120, width_px // 3)
    image = Draw.ReactionToImage(rxn, subImgSize=(cell, cell))
    import io
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    out_path = _write(payload.get("out"), png, binary=True)
    return {"ok": True, "channel": "rdkit",
            "data": {"format": "png", "media": "image/png", "bytes": len(png),
                     "cellPx": cell, "widthMm": round(width_mm, 2), "dpi": dpi,
                     "path": out_path, "vector": False},
            "warnings": ["反应式是位图（ReactionToImage）；要矢量请用 chem_vendor 走 ChemDraw"],
            "evidence": {"renderer": "rdkit.Chem.Draw.ReactionToImage"}}


def _draw_mech(smiles, payload):
    """Molecule as SVG with curved arrows; arrows given as [from, to, bend]."""
    from rdkit.Chem.Draw import rdMolDraw2D

    arrows = payload.get("arrows") or []
    if not isinstance(arrows, list):
        return {"ok": False, "failure": {"code": "bad-arrows", "message": "arrows 必须是列表"}}
    m = _prepare(smiles)
    width_mm = float(payload.get("widthMm") or PRESETS.get(payload.get("preset"), 85.0))
    dpi = int(payload.get("dpi") or 300)
    width_px = _px(width_mm, dpi)
    height_px = int(round(width_px * 0.72))
    drawer = rdMolDraw2D.MolDraw2DSVG(width_px, height_px)
    drawer.SetDrawOptions(_options())
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, m)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    overlay = []
    for index, spec in enumerate(arrows):
        try:
            start, end = int(spec[0]), int(spec[1])
            bend = float(spec[2]) if len(spec) > 2 else 0.25
        except (TypeError, ValueError, IndexError):
            continue
        if start >= m.GetNumAtoms() or end >= m.GetNumAtoms():
            continue
        a = drawer.GetDrawCoords(start)
        b = drawer.GetDrawCoords(end)
        # The SVG y axis grows downward, so flip when converting.
        ax, ay, bx, by = a.x, height_px - a.y, b.x, height_px - b.y
        mx, my = (ax + bx) / 2, (ay + by) / 2
        dx, dy = bx - ax, by - ay
        norm = max(1e-6, (dx ** 2 + dy ** 2) ** 0.5)
        cx, cy = mx - dy * bend, my + dx * bend
        overlay.append(
            '<path d="M %.1f %.1f Q %.1f %.1f %.1f %.1f" fill="none" stroke="#c0392b" '
            'stroke-width="2.2" marker-end="url(#arrowhead%d)"/>' % (ax, ay, cx, cy, bx, by, index))
        overlay.append(
            '<defs><marker id="arrowhead%d" markerWidth="6" markerHeight="6" refX="5" refY="3" '
            'orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#c0392b"/></marker></defs>' % index)
    if overlay:
        svg = svg.replace("</svg>", "\n".join(overlay) + "\n</svg>")
    out_path = _write(payload.get("out"), svg)
    return {"ok": True, "channel": "rdkit",
            "data": {"format": "svg", "media": "image/svg+xml", "bytes": len(svg),
                     "arrows_drawn": len(overlay) // 2, "widthPx": width_px,
                     "heightPx": height_px, "path": out_path, "vector": True},
            "evidence": {"arrows": "quadratic Bezier with marker arrowhead, colour #c0392b"}}


def _draw_3d(smiles, payload):
    """ETKDG embedding + MMFF, written as mol/xyz/pdb.

    Living inside chem_draw instead of taking a sixteenth tool name: the panel and
    the contract both count tools, and a conformer is a way of drawing a molecule.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    m = molmod.parse_struct(smiles)
    work = Chem.AddHs(m)
    seed = int(payload.get("seed") or 0xF00D)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    embed = AllChem.EmbedMolecule(work, params)
    if embed != 0:
        return {"ok": False, "failure": {"code": "embed-failed",
                                        "message": "ETKDG 生成不出 3D 构象",
                                        "hint": "结构太刚性或含异常价态；先 chem_clean"}}
    energy = None
    optimized = False
    if not payload.get("noOptimize"):
        try:
            result = AllChem.MMFFOptimizeMolecule(work, maxIters=int(payload.get("maxIters") or 500))
            optimized = result == 0
            props = AllChem.MMFFGetMoleculeProperties(work)
            if props is not None:
                energy = round(AllChem.MMFFGetMoleculeForceField(work, props).CalcEnergy(), 4)
        except Exception:  # noqa: BLE001
            optimized = False
    out = payload.get("out") or ""
    suffix = Path(out).suffix.lower().lstrip(".") if out else "mol"
    if suffix == "xyz":
        body = Chem.MolToXYZBlock(work)
    elif suffix == "pdb":
        body = Chem.MolToPDBBlock(work)
    else:
        body = Chem.MolToMolBlock(work)
    path = _write(out, body) if out else None
    return {"ok": True, "channel": "rdkit",
            "data": {"view": "3d", "format": suffix, "smiles": molmod.canonical(m),
                     "atoms": work.GetNumAtoms(), "heavyAtoms": m.GetNumAtoms(),
                     "optimized": optimized, "energy": energy,
                     "path": path, "bytes": len(body), "seed": seed},
            "warnings": ([] if optimized else ["MMFF 没有完全收敛，构象只是几何合理的起点"]),
            "evidence": {"embedder": "ETKDGv3", "forcefield": "MMFF94"}}


def handle(payload):
    view = (payload.get("view") or "mol").strip().lower()
    if view == "3d":
        text = payload.get("smiles") or ""
        if not text:
            return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles"}}
        return _draw_3d(text, payload)
    if view == "mol":
        text = payload.get("smiles") or ""
        if not text:
            return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles"}}
        return _draw_one(text, payload)
    if view == "grid":
        return _draw_grid(payload.get("smilesList") or payload.get("smiles"), payload)
    if view == "rxn":
        return _draw_rxn(payload.get("smiles") or payload.get("reaction"), payload)
    if view == "mech":
        return _draw_mech(payload.get("smiles") or "", payload)
    return {"ok": False, "failure": {"code": "unknown-view", "message": "不认识的 view：" + view,
                                    "hint": "mol | grid | rxn | mech"}}
