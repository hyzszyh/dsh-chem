r"""Assertions for chem_ml: cross-validated QSAR with an applicability domain."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import ml  # noqa: E402

results = []
TMP = Path(tempfile.mkdtemp(prefix="dsh-chem-ml-"))


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


# A small synthetic set with a real, learnable trend: logP-like labels from a
# property the descriptors see directly, so a correct pipeline gets a good R2.
DATA = """smiles,activity
CCO,0.9
CCCCO,1.6
CCCCCO,2.1
CCCCCCO,2.6
CCCCCCCO,3.1
c1ccccc1,2.6
Cc1ccccc1,3.1
CC(=O)O,0.5
OC(=O)c1ccccc1O,1.5
CC(=O)Nc1ccc(O)cc1,1.4
Cn1cnc2c1c(=O)n(C)c(=O)n2C,0.2
OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O,-1.5
"""
csv_path = TMP / "train.csv"
csv_path.write_text(DATA, encoding="utf-8")

trained = ml.handle({"action": "train", "path": str(csv_path), "model": "rf", "name": "t_props"})
check("train ok", trained["ok"] is True, str(trained.get("failure")))
check("rows counted", trained["data"]["rows"] == 12, str(trained["data"].get("rows")))
check("features 16", trained["data"]["features"] == 16, str(trained["data"]["features"]))
r2 = trained["data"]["cv"]["r2"]
check("cv r2 positive", r2 > 0.3, str(r2))
check("model file written", Path(trained["data"]["modelPath"]).is_file())
check("meta file written", Path(trained["data"]["metaPath"]).is_file())

predicted = ml.handle({"action": "predict", "model": "t_props", "smiles": "CCCCO"})
check("predict ok", predicted["ok"] is True, str(predicted.get("failure")))
check("predict count 1", predicted["data"]["count"] == 1)
value = predicted["data"]["predictions"][0]
check("prediction finite", isinstance(value["predicted"], float), str(value))
check("prediction near truth", abs(value["predicted"] - 1.6) < 1.0, str(value["predicted"]))
check("in domain", value["insideApplicability"] is True, str(value["nearestTrainingSimilarity"]))

far = ml.handle({"action": "predict", "model": "t_props",
                 "smiles": "C1CC2CCC3CCCC4CCC1C1C2C3C41"})
check("far molecule flagged out of domain",
      far["data"]["predictions"][0]["insideApplicability"] is False
      or far["data"]["outsideApplicability"] >= 1,
      str(far["data"]["predictions"][0]["nearestTrainingSimilarity"]))

listed = ml.handle({"action": "list"})
check("model listed", any(row["model"] == "t_props" for row in listed["data"]["models"]),
      str([row["model"] for row in listed["data"]["models"]]))

described = ml.handle({"action": "describe", "model": "t_props"})
check("describe hides fingerprints", "trainFingerprints" not in described["data"])
check("describe keeps metrics", described["data"]["metrics"]["r2"] == r2, str(described["data"]["metrics"]))

pls = ml.handle({"action": "train", "path": str(csv_path), "model": "pls", "name": "t_pls"})
check("pls trains", pls["ok"] is True, str(pls.get("failure")))
check("pls kind recorded", pls["data"]["kind"] in ("pls", "plsregression"), str(pls["data"].get("kind")))

tiny_path = TMP / "tiny.csv"
tiny_path.write_text("smiles,activity\nCCO,1\nCCCCO,2\n", encoding="utf-8")
tiny = ml.handle({"action": "train", "path": str(tiny_path), "model": "rf", "name": "t_tiny"})
check("too few rows rejected", tiny["ok"] is False and tiny["failure"]["code"] == "too-few-rows",
      str(tiny.get("failure", {}).get("code")))

bad_model = ml.handle({"action": "train", "path": str(csv_path), "model": "magic", "name": "t_bad"})
check("unknown model rejected", bad_model["ok"] is False and bad_model["failure"]["code"] == "bad-model",
      str(bad_model.get("failure", {}).get("code")))

no_model = ml.handle({"action": "predict", "model": "does-not-exist", "smiles": "CCO"})
check("missing model rejected", no_model["ok"] is False and no_model["failure"]["code"] == "no-model",
      str(no_model.get("failure", {}).get("code")))

skipped_rows = ml.handle({"action": "train", "path": str(csv_path), "model": "linear", "name": "t_lin",
                          "labelColumn": "activity"})
check("linear trains", skipped_rows["ok"] is True, str(skipped_rows.get("failure")))
check("linear reports metrics", "rmse" in skipped_rows["data"]["cv"], str(skipped_rows["data"]["cv"]))

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_ml: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
