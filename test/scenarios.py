r"""Eight user journeys, end to end, on the real engine.

Each scenario is a sequence a student or teacher would actually run, and each
assertion is a measured number or a file that had to exist. This is the
acceptance gate that the per-module suites cannot give: it is what "the plugin
works" means.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import (calc, db, draw, enum, exam, ml, office, parse, props, retro,  # noqa: E402
                  spectra, table, vendor)

TMP = Path(tempfile.mkdtemp(prefix="dsh-chem-scenario-"))
PARA = "CC(=O)Nc1ccc(O)cc1"
PARA_KEY = "RZVAJINKPMORJF-UHFFFAOYSA-N"
failures = []


def check(scenario, label, ok, detail=""):
    if not ok:
        failures.append("%s / %s" % (scenario, label))
    print("%-4s %-58s %s%s" % ("ok" if ok else "FAIL", label,
                               "[" + detail + "]" if detail else "",
                               "" if ok else "   <-- " + scenario))


def s1_submission_figure():
    """投稿配图：ACS 单栏 82.6 mm，PNG + 矢量 PDF，留白和键长都要过线。"""
    name = "S1 投稿配图"
    png = draw.handle({"smiles": PARA, "preset": "acs-1col", "dpi": 600,
                       "out": str(TMP / "s1.png")})
    # 82.6 mm at 600 dpi is 1951.18 px, and the renderer rounds to 1951.
    check(name, "PNG 1951 px wide at 600 dpi", png["data"]["widthPx"] == 1951,
          str(png["data"]["widthPx"]))
    check(name, "bond length readable", png["data"]["readable"], str(png["data"]["bonds"]["median_px"]))
    check(name, "margin inside 2-15%", 0.02 <= png["data"]["padding"]["ratio"] <= 0.15,
          str(png["data"]["padding"]["ratio"]))
    pdf = draw.handle({"smiles": PARA, "preset": "acs-1col", "format": "pdf",
                       "out": str(TMP / "s1.pdf")})
    import pymupdf
    doc = pymupdf.open(pdf["data"]["path"])
    width_pt = doc[0].rect.width
    doc.close()
    check(name, "PDF page width ~234 pt", abs(width_pt - 82.6 * 72 / 25.4) < 2.0, str(round(width_pt, 1)))
    check(name, "PDF vector", pdf["data"]["vector"] is True)


def s2_read_a_picture():
    """看图识别：把 S1 的图再读回来，InChIKey 必须对上。"""
    name = "S2 看图读结构"
    figure = draw.handle({"smiles": PARA, "widthMm": 85, "dpi": 300,
                          "out": str(TMP / "s2.png")})
    found = parse.handle({"kind": "image", "source": figure["data"]["path"], "engines": ["decimer"]})
    check(name, "picture parsed", found["ok"] is True, str(found.get("failure", {}).get("code")))
    if found["ok"]:
        check(name, "InChIKey matches target", found["data"]["best"]["inchikey"] == PARA_KEY,
              found["data"]["best"]["inchikey"])
        check(name, "flags single-reader confirmation", found["data"]["needs_confirmation"] is True)


def s3_mark_homework():
    """作业批改：四个答案四类判定，再出一份 Word 报告。"""
    name = "S3 作业批改"
    graded = exam.handle({"answer": PARA,
                          "submissions": [PARA, "CC(=O)Nc1ccc(OC)cc1", "CCO", "nonsense"]})
    check(name, "four submissions graded", graded["data"]["count"] == 4, str(graded["data"]["count"]))
    check(name, "one correct", graded["data"]["tally"]["correct"] == 1, str(graded["data"]["tally"]))
    check(name, "score 25.0", graded["data"]["score"] == 25.0, str(graded["data"]["score"]))
    check(name, "substituent verdict used", graded["data"]["tally"]["substituent"] == 1,
          str(graded["data"]["tally"]))
    report = exam.handle({"action": "report", "answer": PARA,
                          "submissions": [PARA, "CCO"], "out": str(TMP / "s3.docx")})
    check(name, "report written", Path(report["data"]["path"]).stat().st_size > 20000,
          str(report["data"]["bytes"]))


def s4_reaction_maths():
    """反应计算：10 mmol 酯化，配平残差必须为 0，投料质量要对得上。"""
    name = "S4 配平与投料"
    stoich = calc.handle({"kind": "stoich", "reaction": "CC(=O)O.OCC>>CC(=O)OCC.O",
                          "scaleMmol": 10})
    check(name, "stoich ok", stoich["ok"] is True, str(stoich.get("failure")))
    rows = stoich["data"]["rows"]
    by_name = {row["role"] + ":" + str(row["smiles"]): row for row in rows}
    products = [row for row in rows if row["role"] == "product"]
    check(name, "ethyl acetate 881.06 mg", abs(products[0]["theoretical_mg"] - 881.06) < 0.5,
          str(products[0]["theoretical_mg"]))
    check(name, "water is the co-product", products[1]["formula"] == "H2O", products[1]["formula"])
    check(name, "equation balanced", stoich["data"]["balanced"] is True,
          str(stoich["data"].get("coefficients")))
    reactant_mass = sum(row.get("theoretical_mg", row["mg"])
                        for row in rows if row["role"] == "reactant")
    product_mass = sum(row["theoretical_mg"] for row in rows if row["role"] == "product")
    check(name, "mass closes within 0.05 mg", abs(reactant_mass - product_mass) < 0.05,
          "%.2f vs %.2f" % (reactant_mass, product_mass))
    check(name, "reactant roles labelled", len(by_name) >= 2, str(len(by_name)))


def s5_teaching_set():
    """批量出题：一个骨架 × 九个组合，去重后全部画进联系表。"""
    name = "S5 同系列出题"
    library = enum.handle({"mode": "library", "scaffold": "c1cc([*:1])ccc1[*:2]",
                           "substituents": "C,O,N", "substituents2": "F,Cl,N"})
    check(name, "9 combinations produced", library["data"]["produced"] == 9,
          str(library["data"]["produced"]))
    sheet = draw.handle({"view": "grid",
                         "smilesList": ",".join(row["smiles"] for row in library["data"]["structures"]),
                         "columns": 3, "widthMm": 150, "out": str(TMP / "s5.png")})
    check(name, "contact sheet drawn", sheet["data"]["count"] == 9, str(sheet["data"]["count"]))
    check(name, "sheet file exists", Path(sheet["data"]["path"]).stat().st_size > 20000,
          str(sheet["data"]["bytes"]))


def s6_literature_table():
    """文献整理：一组结构算成性质表，再落成 Word SI 表。"""
    name = "S6 结构性质表"
    matrix = table.handle({"action": "matrix", "smiles": "CCO,CC(=O)O,c1ccccc1," + PARA})
    check(name, "four rows", len(matrix["data"]["rows"]) == 4, str(len(matrix["data"]["rows"])))
    paracetamol = [row for row in matrix["data"]["rows"] if row["inchikey"] == PARA_KEY][0]
    check(name, "paracetamol MW 151.165", abs(paracetamol["mw"] - 151.165) < 1e-3, str(paracetamol["mw"]))
    document = office.handle({"action": "table", "rows": matrix["data"]["rows"],
                              "title": "SI 表 1", "out": str(TMP / "s6.docx"),
                              "xlsx": str(TMP / "s6.xlsx")})
    check(name, "SI docx written", Path(document["data"]["path"]).is_file())
    check(name, "rows in table", document["data"]["rows"] == 4, str(document["data"]["rows"]))
    check(name, "xlsx companion", Path(document["data"]["xlsx"]).is_file())


def s7_report_document():
    """写报告：结构图 + 正文 + 图注，一次生成 Word。"""
    name = "S7 报告文档"
    report = office.handle({"action": "docx", "smiles": PARA, "title": "乙酰水杨酸的合成",
                            "paragraphs": ["对乙酰氨基酚的结构见图 1。"],
                            "caption": "图 1  对乙酰氨基酚",
                            "out": str(TMP / "s7.docx")})
    import zipfile
    with zipfile.ZipFile(report["data"]["path"]) as archive:
        media = [n for n in archive.namelist() if n.startswith("word/media/")]
        body = archive.read("word/document.xml").decode("utf-8")
    check(name, "docx has a picture", len(media) == 1, str(media))
    check(name, "caption inside document", "图 1  对乙酰氨基酚" in body)
    check(name, "honest about no OLE", any("OLE" in w for w in report["warnings"]),
          str(report["warnings"][:1]))


def s8_library_and_qsar():
    """建库 + 检索 + 建模型：SQLite 往返、子结构命中、交叉验证出数。"""
    name = "S8 库与模型"
    lib = {"db": str(TMP / "lib.db")}
    added = db.handle({**lib, "action": "add", "text": "\n".join([
        "CCO ethanol", "CC(=O)O acetic acid", "c1ccccc1 benzene", PARA + " paracetamol"])})
    check(name, "four molecules stored", added["data"]["added"] == 4, str(added["data"]["added"]))
    hits = db.handle({**lib, "action": "search", "mode": "substructure", "query": "c1ccccc1"})
    check(name, "benzene search finds 2", hits["data"]["count"] == 2, str(hits["data"]["count"]))
    sdf = db.handle({**lib, "action": "export", "format": "sdf", "out": str(TMP / "s8.sdf")})
    check(name, "sdf export", sdf["data"]["count"] == 4, str(sdf["data"]["count"]))
    read_back = vendor.handle({"action": "read", "path": sdf["data"]["path"]})
    check(name, "sdf reads back", read_back["data"]["count"] == 4, str(read_back["data"]["count"]))

    csv_path = TMP / "s8.csv"
    csv_path.write_text("smiles,activity\n" + "\n".join([
        "CCO,0.9", "CCCCO,1.6", "CCCCCO,2.1", "CCCCCCO,2.6", "CCCCCCCO,3.1",
        "c1ccccc1,2.6", "Cc1ccccc1,3.1", "CC(=O)O,0.5", "OC(=O)c1ccccc1O,1.5",
        PARA + ",1.4", "Cn1cnc2c1c(=O)n(C)c(=O)n2C,0.2",
        "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O,-1.5"]), encoding="utf-8")
    trained = ml.handle({"action": "train", "path": str(csv_path), "model": "rf", "name": "s8"})
    check(name, "model trained", trained["ok"] is True, str(trained.get("failure")))
    check(name, "cv r2 reported", trained["data"]["cv"]["r2"] > 0.3, str(trained["data"]["cv"]["r2"]))
    predicted = ml.handle({"action": "predict", "model": "s8", "smiles": "CCCCO"})
    inside = predicted["data"]["predictions"][0]
    check(name, "prediction in domain", inside["insideApplicability"] is True,
          str(inside["nearestTrainingSimilarity"]))


def s9_spectra_and_retro():
    """谱图与逆合成：峰能不能被结构解释，断键能不能回到原料。"""
    name = "S9 谱图与逆合成"
    explained = spectra.handle({"action": "compare", "smiles": PARA,
                                "peaks": "9.5,7.6,7.3,2.2", "tolerance": 0.4})
    check(name, "all four observed peaks explained", len(explained["data"]["matched"]) == 4,
          str(len(explained["data"]["matched"])))
    decomposed = retro.handle({"smiles": "CCOC(C)=O"})
    first = decomposed["data"]["routes"][0]
    check(name, "ester goes back to acid + alcohol",
          set(first["precursorInchikeys"]) == {"QTBSBXVTEAMEQO-UHFFFAOYSA-N",
                                              "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"},
          str(first["precursorInchikeys"]))


SCENARIOS = [s1_submission_figure, s2_read_a_picture, s3_mark_homework, s4_reaction_maths,
             s5_teaching_set, s6_literature_table, s7_report_document, s8_library_and_qsar,
             s9_spectra_and_retro]

print("scenarios: %d" % len(SCENARIOS))
for scenario in SCENARIOS:
    scenario()

print("")
if failures:
    print("scenarios: %d checks FAILED" % len(failures))
    for row in failures:
        print("  - " + row)
    raise SystemExit(1)
print("scenarios: all checks passed (%d scenarios)" % len(SCENARIOS))
