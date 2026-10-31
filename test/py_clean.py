r"""Assertions for chem_clean."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import clean  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


mixed = clean.handle({"smiles": "CC(=O)[O-].[Na+].c1ccc(O)cc1", "action": "fix"})
check("salt fix ok", mixed["ok"] is True)
check("largest fragment kept", mixed["data"]["after"] == "Oc1ccccc1", mixed["data"]["after"])
check("formula after", mixed["data"]["formula_after"] == "C6H6O", mixed["data"]["formula_after"])
check("steps recorded", "largest-fragment" in mixed["data"]["steps"], ",".join(mixed["data"]["steps"]))
check("changed flag", mixed["data"]["changed"] is True)
check("no findings after fix", mixed["data"]["remaining_findings"] == [])

salt_check = clean.handle({"smiles": "CC(=O)[O-].[Na+]", "action": "check"})
codes = [f["code"] for f in salt_check["data"]["findings"]]
check("disconnected found", "disconnected" in codes, ",".join(codes))
check("check reports clean=false", salt_check["data"]["clean"] is False)

stereo = clean.handle({"smiles": "CC(O)CC", "action": "check"})
stereo_findings = [f for f in stereo["data"]["findings"] if f["code"] == "undefined-stereo"]
check("undefined stereo found", len(stereo_findings) == 1)
check("undefined stereo atoms", stereo_findings[0]["atoms"] == [1], str(stereo_findings[0]["atoms"]))

ethanol = clean.handle({"smiles": "CCO", "action": "check"})
check("ethanol clean", ethanol["data"]["clean"] is True, str(ethanol["data"]["findings"]))

quinone = clean.handle({"smiles": "O=C1C=CC(=O)C=C1", "action": "filter"})
check("quinone flagged", quinone["data"]["flagged"] is True)
check("quinone hits", len(quinone["data"]["hits"]) >= 1, str(len(quinone["data"]["hits"])))
check("catalog names", "PAINS" in quinone["data"]["catalogs"], ",".join(quinone["data"]["catalogs"]))

caffeine = clean.handle({"smiles": "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "action": "filter"})
check("caffeine not flagged", caffeine["data"]["flagged"] is False, str(caffeine["data"]["hits"]))

bad = clean.handle({"smiles": "C1CC", "action": "check"})
check("bad structure rejected", bad["ok"] is False and bad["failure"]["code"] == "bad-structure")

unknown = clean.handle({"smiles": "CCO", "action": "teleport"})
check("unknown action rejected", unknown["ok"] is False and unknown["failure"]["code"] == "unknown-action")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_clean: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
