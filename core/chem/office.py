"""chem_office: structures into Word, PowerPoint and SI tables.

Word and PowerPoint get a 600 dpi PNG placed at a physical width, so a caption
stays attached to the right picture and the figure does not explode the page.
OLE embedding of a live ChemDraw object needs a compound-file writer this build
does not have; that limitation is reported, not faked.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import draw, mol as molmod

DEFAULT_WIDTH_MM = 80.0


def _png(smiles, out_dir, width_mm=DEFAULT_WIDTH_MM, dpi=600, tag="struct"):
    target = Path(out_dir) / (tag + ".png")
    result = draw.handle({"smiles": smiles, "widthMm": width_mm, "dpi": dpi, "out": str(target)})
    if not result.get("ok"):
        raise molmod.MolError("draw-failed", "画不出结构：" + smiles,
                              str(result.get("failure", {}).get("message"))[:120])
    return result["data"]


def _target(payload, default_name):
    """Resolve the output file: out / path / file, always absolute.

    The tool surface sends `path`; this module used to read only `out` and fall
    back to a bare file name, so the document landed in whatever directory the
    engine happened to run in -- inside the installed plugin (measured
    2026-10-30: chem_office wrote plugins/dsh-chem/engine/structure.docx).
    """
    raw = payload.get("out") or payload.get("path") or payload.get("file") or ""
    if not raw:
        raise molmod.MolError(
            "missing-input",
            "需要 out 或 path：请给绝对路径，别让文档落进插件目录",
            "例：target=docx, path=C:/Users/me/Desktop/结构.docx, smiles=CCO")
    target = Path(str(raw)).expanduser()
    if not target.is_absolute():
        target = (Path(payload.get("cwd") or Path.cwd()) / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _docx_structure(payload):
    from docx import Document
    from docx.shared import Pt

    smiles = payload.get("smiles") or ""
    if not smiles:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles"}}
    target = _target(payload, "structure.docx")
    work = target.parent / (target.stem + "-assets")
    work.mkdir(parents=True, exist_ok=True)
    width_mm = float(payload.get("widthMm") or DEFAULT_WIDTH_MM)
    figure = _png(smiles, work, width_mm=width_mm, dpi=int(payload.get("dpi") or 600))

    document = Document()
    paragraphs = payload.get("paragraphs") or []
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    title = payload.get("title") or ""
    if title:
        document.add_heading(title, level=1)
    for line in paragraphs:
        document.add_paragraph(str(line))
    document.add_picture(figure["path"], width=__import__("docx").shared.Mm(width_mm))
    caption = payload.get("caption") or "图 1  结构式"
    run = document.add_paragraph()
    run.alignment = 1
    text = run.add_run(caption)
    text.font.size = Pt(9)
    if payload.get("notes"):
        document.add_paragraph(str(payload["notes"]))
    document.save(str(target))
    return {"ok": True, "channel": "python-docx",
            "data": {"path": str(target), "bytes": target.stat().st_size,
                     "figure": figure["path"], "widthMm": width_mm,
                     "paragraphs": len(paragraphs),
                     "embeddedOle": False},
            "warnings": ["图片是 600 dpi PNG；可编辑的 ChemDraw OLE 对象本机不可用（另存 cdxml 交给 ChemDraw）"]}


def _si_table(payload):
    rows = payload.get("rows") or []
    if not rows and payload.get("db"):
        from . import db as dbmod
        found = dbmod.handle({"action": "list", "db": payload["db"], "limit": int(payload.get("limit") or 200)})
        rows = (found.get("data") or {}).get("hits") or []
    if not rows:
        return {"ok": False, "failure": {"code": "no-rows",
                                        "message": "没有数据：给 rows 或 db 路径"}}
    columns = payload.get("columns") or ["canonical", "formula", "mw", "logp", "tpsa", "name"]
    headers = payload.get("headers") or {"canonical": "SMILES", "formula": "分子式",
                                         "mw": "分子量", "logp": "logP", "tpsa": "TPSA",
                                         "name": "名称", "inchikey": "InChIKey"}
    target = _target(payload, "si-table.docx")
    from docx import Document
    document = Document()
    if payload.get("title"):
        document.add_heading(str(payload["title"]), level=2)
    table = document.add_table(rows=1, cols=len(columns) + 1)
    table.style = "Table Grid"
    header = table.rows[0].cells
    header[0].text = "编号"
    for index, column in enumerate(columns, start=1):
        header[index].text = headers.get(column, column)
    for number, row in enumerate(rows, start=1):
        cells = table.add_row().cells
        cells[0].text = str(number)
        for index, column in enumerate(columns, start=1):
            value = row.get(column)
            if isinstance(value, float):
                value = "%.2f" % value
            cells[index].text = "" if value is None else str(value)
    document.save(str(target))
    result = {"ok": True, "channel": "python-docx",
              "data": {"path": str(target), "rows": len(rows), "columns": columns,
                       "bytes": target.stat().st_size}}
    xlsx_raw = payload.get("xlsx") or payload.get("xlsxPath") or ""
    if xlsx_raw:
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = payload.get("sheet") or "SI"
        sheet.append(["#"] + [headers.get(c, c) for c in columns])
        for number, row in enumerate(rows, start=1):
            sheet.append([number] + [row.get(c) for c in columns])
        book = Path(str(xlsx_raw)).expanduser()
        if not book.is_absolute():
            book = (Path.cwd() / book).resolve()
        book.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(str(book))
        result["data"]["xlsx"] = str(book)
    return result


def _pptx_structure(payload):
    from pptx import Presentation
    from pptx.util import Emu, Inches

    smiles = payload.get("smiles") or ""
    if not smiles:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles"}}
    target = _target(payload, "slide.pptx")
    work = target.parent / (target.stem + "-assets")
    work.mkdir(parents=True, exist_ok=True)
    figure = _png(smiles, work, width_mm=float(payload.get("widthMm") or 90.0), dpi=400)

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = payload.get("title") or "结构式"
    slide.shapes.add_picture(figure["path"], Inches(1.0), Inches(1.6), width=Inches(4.0))
    if payload.get("notes"):
        box = slide.shapes.add_textbox(Inches(5.4), Inches(1.8), Inches(4.2), Inches(3.0))
        box.text_frame.text = str(payload["notes"])
    deck.save(str(target))
    return {"ok": True, "channel": "python-pptx",
            "data": {"path": str(target), "bytes": target.stat().st_size,
                     "figure": figure["path"], "slides": 1}}


def handle(payload):
    # The tool surface sends `target`, not `action`; defaulting to docx quietly
    # turned every si-table and pptx request into a Word document (measured 2026-10-30).
    action = str(payload.get("action") or payload.get("target") or payload.get("do") or "docx")
    action = action.strip().lower().replace("_", "-")
    try:
        if action in ("docx", "word", "structure"):
            return _docx_structure(payload)
        if action in ("table", "si", "si_table", "si-table", "sit"):
            return _si_table(payload)
        if action in ("pptx", "ppt", "slide"):
            return _pptx_structure(payload)
        return {"ok": False, "failure": {"code": "unknown-action", "message": "不认识的 action：" + action,
                                        "hint": "docx | table | pptx"}}
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message, "hint": exc.hint}}
