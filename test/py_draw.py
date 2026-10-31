r"""Assertions for chem_draw: physical size, vector output, measurable layout."""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from PIL import Image  # noqa: E402

from chem import draw  # noqa: E402

results = []
TMP = Path(tempfile.mkdtemp(prefix="dsh-chem-draw-"))


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


def out(name):
    return str(TMP / name)


SMI = "CC(=O)Nc1ccc(O)cc1"

png = draw.handle({"smiles": SMI, "widthMm": 85, "dpi": 300, "out": out("p.png")})
pd = png["data"]
check("png ok", png["ok"] is True)
check("png width 1004 px", pd["widthPx"] == 1004, str(pd["widthPx"]))
check("png bytes on disk", Path(pd["path"]).is_file() and pd["bytes"] > 5000, str(pd["bytes"]))
check("png magic", Path(pd["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n")
check("bond length measured", 20 <= pd["bonds"]["median_px"] <= 400, str(pd["bonds"]["median_px"]))
check("readable", pd["readable"] is True)
check("margin measured", 0.02 <= pd["padding"]["ratio"] <= 0.15, str(pd["padding"]["ratio"]))
check("not vector", pd["vector"] is False)

preset = draw.handle({"smiles": SMI, "preset": "acs-1col", "dpi": 300})
check("preset width 82.6mm", preset["data"]["widthMm"] == 82.6, str(preset["data"]["widthMm"]))
check("preset px", preset["data"]["widthPx"] == 976, str(preset["data"]["widthPx"]))

svg = draw.handle({"smiles": SMI, "format": "svg", "out": out("p.svg")})
check("svg ok", svg["ok"] is True)
svg_text = Path(svg["data"]["path"]).read_text(encoding="utf-8")
check("svg contains svg tag", "<svg" in svg_text)
check("svg is vector", svg["data"]["vector"] is True)
check("svg bond measured from cairo", 20 <= svg["data"]["bonds"]["median_px"] <= 400,
      str(svg["data"]["bonds"]["median_px"]))

pdf = draw.handle({"smiles": SMI, "format": "pdf", "widthMm": 85, "out": out("p.pdf")})
pdf_bytes = Path(pdf["data"]["path"]).read_bytes()
check("pdf magic", pdf_bytes[:5] == b"%PDF-")
check("pdf is vector", pdf["data"]["vector"] is True)
import pymupdf  # noqa: E402
doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
page_w_pt = doc[0].rect.width
doc.close()
check("pdf page width ~241 pt", abs(page_w_pt - 240.94) < 2.0, str(round(page_w_pt, 2)))

tif = draw.handle({"smiles": SMI, "format": "tif", "dpi": 600, "out": out("p.tif")})
image = Image.open(tif["data"]["path"])
check("tif dpi 600", image.info.get("dpi") == (600, 600), str(image.info.get("dpi")))
check("tif width doubled", image.size[0] == 2008, str(image.size[0]))
image.close()

eps = draw.handle({"smiles": SMI, "format": "eps"})
check("eps needs vendor", eps["ok"] is False and eps["failure"]["code"] == "needs-vendor",
      str(eps.get("failure", {}).get("code")))

grid = draw.handle({"view": "grid", "smilesList": "CCO,CC(=O)O,c1ccccc1", "columns": 2,
                    "widthMm": 170, "out": out("g.png")})
check("grid ok", grid["ok"] is True)
check("grid count 3", grid["data"]["count"] == 3, str(grid["data"]["count"]))
check("grid file", Path(grid["data"]["path"]).is_file())

grid_bad = draw.handle({"view": "grid", "smilesList": "CCO,C1CC"})
check("grid skips invalid", grid_bad["data"]["count"] == 1 and len(grid_bad["data"]["skipped"]) == 1,
      str(grid_bad["data"]["skipped"]))

rxn = draw.handle({"view": "rxn", "smiles": "CCO.CC(=O)O>>CC(=O)OCC.O", "out": out("r.png")})
check("rxn ok", rxn["ok"] is True)
check("rxn honest about raster", rxn["data"]["vector"] is False)
check("rxn warns", any("位图" in w for w in rxn.get("warnings", [])), str(rxn.get("warnings")))

mech = draw.handle({"view": "mech", "smiles": "OC(=O)C=CC(=O)O", "arrows": [[0, 3, 0.3]],
                    "out": out("m.svg")})
mech_text = Path(mech["data"]["path"]).read_text(encoding="utf-8")
check("mech ok", mech["ok"] is True)
check("mech arrow drawn", mech["data"]["arrows_drawn"] == 1, str(mech["data"]["arrows_drawn"]))
check("mech svg has marker", "marker-end" in mech_text)

bad_out_of_range = draw.handle({"view": "mech", "smiles": "CCO", "arrows": [[0, 99, 0.2]]})
check("mech ignores bad atoms", bad_out_of_range["data"]["arrows_drawn"] == 0,
      str(bad_out_of_range["data"]["arrows_drawn"]))

missing = draw.handle({"view": "mol"})
check("missing smiles rejected", missing["ok"] is False and missing["failure"]["code"] == "missing-input")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_draw: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
