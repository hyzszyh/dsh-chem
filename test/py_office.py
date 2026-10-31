r"""Assertions for chem_office: the picture and the table really are inside the file."""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import office  # noqa: E402

results = []
TMP = Path(tempfile.mkdtemp(prefix="dsh-chem-office-"))


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


PARA = "CC(=O)Nc1ccc(O)cc1"

docx_path = TMP / "report.docx"
made = office.handle({"action": "docx", "smiles": PARA, "title": "实验一", "out": str(docx_path),
                      "caption": "图 1 对乙酰氨基酚", "paragraphs": ["本文说明结构。"]})
check("docx ok", made["ok"] is True, str(made.get("failure")))
check("docx file exists", docx_path.is_file() and docx_path.stat().st_size > 10000,
      str(docx_path.stat().st_size if docx_path.is_file() else "missing"))
with zipfile.ZipFile(docx_path) as archive:
    names = archive.namelist()
    xml = archive.read("word/document.xml").decode("utf-8")
check("docx embeds a picture part", any(n.startswith("word/media/") for n in names),
      str([n for n in names if n.startswith("word/media/")][:3]))
check("docx has caption text", "图 1 对乙酰氨基酚" in xml)
check("docx has body text", "本文说明结构。" in xml)
check("docx honest about ole", any("OLE" in w for w in made["warnings"]), str(made["warnings"]))

rows = [{"canonical": "CCO", "formula": "C2H6O", "mw": 46.069, "logp": -0.0014, "tpsa": 20.23,
         "name": "乙醇"},
        {"canonical": PARA, "formula": "C8H9NO2", "mw": 151.165, "logp": 0.46, "tpsa": 49.33,
         "name": "对乙酰氨基酚"}]
table = office.handle({"action": "table", "rows": rows, "out": str(TMP / "si.docx"),
                       "xlsx": str(TMP / "si.xlsx"), "title": "SI 表"})
check("si table ok", table["ok"] is True, str(table.get("failure")))
check("si rows counted", table["data"]["rows"] == 2, str(table["data"].get("rows")))
from docx import Document  # noqa: E402
document = Document(str(TMP / "si.docx"))
check("docx table exists", len(document.tables) == 1, str(len(document.tables)))
check("docx table rows 3", len(document.tables[0].rows) == 3, str(len(document.tables[0].rows)))
check("docx header translated", document.tables[0].rows[0].cells[1].text == "SMILES",
      document.tables[0].rows[0].cells[1].text)
check("xlsx written", Path(table["data"]["xlsx"]).is_file())
from openpyxl import load_workbook  # noqa: E402
sheet = load_workbook(table["data"]["xlsx"]).active
check("xlsx row count", sheet.max_row == 3, str(sheet.max_row))
check("xlsx first data row", sheet.cell(row=2, column=1).value == 1, str(sheet.cell(row=2, column=1).value))

pptx_path = TMP / "deck.pptx"
deck = office.handle({"action": "pptx", "smiles": PARA, "out": str(pptx_path),
                      "title": "结构式汇报", "notes": "对乙酰氨基酚"})
check("pptx ok", deck["ok"] is True, str(deck.get("failure")))
check("pptx file exists", pptx_path.is_file())
from pptx import Presentation  # noqa: E402
presentation = Presentation(str(pptx_path))
check("pptx one slide", len(presentation.slides) == 1, str(len(presentation.slides)))
kinds = [shape.shape_type for shape in presentation.slides[0].shapes]
check("pptx has a picture", any("PICTURE" in str(k) for k in kinds), str(kinds))
check("pptx has a title", presentation.slides[0].shapes.title.text == "结构式汇报",
      presentation.slides[0].shapes.title.text)

# Public surface: the tool schema sends target/path, not action/out. Both used to be
# ignored -- target fell back to docx and path fell back to a bare file name, so
# pptx and si-table came out as Word files in the engine directory (measured 2026-10-30).
path_only = TMP / "path-only.docx"
made_path = office.handle({"target": "docx", "path": str(path_only), "smiles": PARA})
check("target=docx honours path", made_path["ok"] is True and path_only.is_file(),
      str(made_path.get("failure")))
check("reported path is absolute", Path(made_path["data"]["path"]).is_absolute(),
      made_path["data"]["path"])

public_deck = TMP / "public-slide.pptx"
made_deck = office.handle({"target": "pptx", "path": str(public_deck), "smiles": PARA})
check("target=pptx makes a deck", made_deck["ok"] is True and public_deck.is_file(),
      str(made_deck.get("failure")))
if public_deck.is_file():
    with zipfile.ZipFile(public_deck) as archive:
        check("pptx has a presentation part", "ppt/presentation.xml" in archive.namelist())

public_table = TMP / "public-si.docx"
made_si = office.handle({"target": "si-table", "path": str(public_table),
                         "rows": [{"canonical": "CCO", "formula": "C2H6O", "mw": 46.07}]})
check("target=si-table makes a table doc", made_si["ok"] is True, str(made_si.get("failure")))
if public_table.is_file():
    with zipfile.ZipFile(public_table) as archive:
        body = archive.read("word/document.xml").decode("utf-8")
    check("si-table really contains a table", "<w:tbl" in body)

no_path = office.handle({"target": "docx", "smiles": PARA})
check("docx without out/path refused", no_path["ok"] is False
      and no_path["failure"]["code"] == "missing-input",
      str(no_path.get("failure", {}).get("code")))

empty = office.handle({"action": "table", "rows": []})
check("empty table rejected", empty["ok"] is False and empty["failure"]["code"] == "no-rows",
      str(empty.get("failure", {}).get("code")))
bad = office.handle({"action": "docx"})
check("missing smiles rejected", bad["ok"] is False and bad["failure"]["code"] == "missing-input")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_office: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
