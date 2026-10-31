r"""Assertions for chem_spectra: the numbers are estimates, and they add up."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import spectra  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


ETH = spectra.handle({"smiles": "CCO"})
check("predict ok", ETH["ok"] is True, str(ETH.get("failure")))
data = ETH["data"]
check("all hydrogens assigned", data["protonAssigned"] == data["totalHydrogens"],
      "%s/%s" % (data["protonAssigned"], data["totalHydrogens"]))
check("ethanol has 3 proton signals", data["protonEnvironments"] == 3,
      str(data["protonEnvironments"]))
shifts = sorted(row["shift"] for row in data["nmr1h"])
check("ethanol shifts 0.9 / 2.5 / 3.6", shifts == [0.9, 2.5, 3.6], str(shifts))
methyl = [row for row in data["nmr1h"] if row["shift"] == 0.9][0]
check("methyl integrates 3H", methyl["integration"] == 3, str(methyl["integration"]))
check("methyl is a triplet", methyl["multiplicity"] == "t", methyl["multiplicity"])
check("estimates carry a warning", any("±0.3" in w for w in ETH["warnings"]), str(ETH["warnings"]))

PARA = spectra.handle({"smiles": "CC(=O)Nc1ccc(O)cc1"})
para = PARA["data"]
check("paracetamol H count 9", para["totalHydrogens"] == 9, str(para["totalHydrogens"]))
check("paracetamol assigned 9", para["protonAssigned"] == 9, str(para["protonAssigned"]))
environments = {row["environment"] for row in para["nmr1h"]}
check("paracetamol has phenol OH", "酚 O-H" in environments, str(sorted(environments)))
check("paracetamol has amide NH", "酰胺 N-H" in environments, str(sorted(environments)))
check("paracetamol acetyl CH3 at 2.2",
      any(row["shift"] == 2.2 and row["integration"] == 3 for row in para["nmr1h"]),
      str([(r["shift"], r["integration"]) for r in para["nmr1h"]]))

carbons = {row["environment"] for row in para["nmr13c"]}
check("13C sees carbonyl", "羰基 C" in carbons, str(sorted(carbons)))
check("13C sees aromatic", "芳香 C" in carbons, str(sorted(carbons)))
check("13C gives ranges not points",
      all(isinstance(row["range"], list) and len(row["range"]) == 2 for row in para["nmr13c"]))

ir = {row["group"] for row in para["ir"]}
check("IR has O-H", "O-H 伸缩" in ir, str(sorted(ir)))
check("IR has amide C=O", "酰胺 C=O" in ir, str(sorted(ir)))
check("IR has aromatic C=C", "芳环 C=C" in ir, str(sorted(ir)))

ms = para["ms"]
check("MS exact mass paracetamol", abs(ms["exactMass"] - 151.063329) < 1e-5, str(ms["exactMass"]))
check("MS [M+H]+ 152.0706", abs(ms["adducts"]["[M+H]+"] - 152.0706) < 1e-3,
      str(ms["adducts"]["[M+H]+"]))
check("MS [M-H]- 150.0561", abs(ms["adducts"]["[M-H]-"] - 150.0557) < 1e-2,
      str(ms["adducts"]["[M-H]-"]))
check("MS expected loss H2O present", any(row["loss"] == "H2O" for row in ms["expectedLosses"]),
      str([r["loss"] for r in ms["expectedLosses"]]))

good = spectra.handle({"action": "compare", "smiles": "CCO", "peaks": "1.2,2.6,3.7", "tolerance": 0.4})
check("compare matches all three", len(good["data"]["matched"]) == 3,
      str(len(good["data"]["matched"])))
check("compare coverage 1.0", good["data"]["coverage"] == 1.0, str(good["data"]["coverage"]))
check("compare finds no unexplained signals", not good["data"]["unexplainedSignals"],
      str(good["data"]["unexplainedSignals"]))

bad = spectra.handle({"action": "compare", "smiles": "CCO", "peaks": "1.2,9.9", "tolerance": 0.3})
check("compare flags unmatched peak", len(bad["data"]["unmatchedPeaks"]) == 1,
      str(bad["data"]["unmatchedPeaks"]))
check("compare warns", bool(bad["warnings"]), str(bad["warnings"]))

check("ir action works", spectra.handle({"action": "ir", "smiles": "CC(=O)O"})["ok"] is True)
check("ms action works", spectra.handle({"action": "ms", "smiles": "CCO"})["ok"] is True)
check("missing smiles rejected",
      spectra.handle({})["failure"]["code"] == "missing-input")
check("compare without peaks rejected",
      spectra.handle({"action": "compare", "smiles": "CCO"})["failure"]["code"] == "missing-input")
check("unknown action rejected",
      spectra.handle({"action": "wat", "smiles": "CCO"})["failure"]["code"] == "unknown-action")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_spectra: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
