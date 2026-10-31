r"""Assertions for chem_calc: balance, masses, HRMS, plate."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import calc  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


ester = calc.handle({"reaction": "CCO.CC(=O)O>>CC(=O)OCC.O", "scaleMmol": 10})
d = ester["data"]
check("balanced", d["balanced"] is True)
check("coefficients 1:1:1:1", d["coefficients"] == [1, 1, 1, 1], str(d["coefficients"]))
eth = d["rows"][0]
check("ethanol 10 mmol -> 460.69 mg", abs(eth["mg"] - 460.69) < 0.02, str(eth["mg"]))
acetate = [r for r in d["rows"] if r["role"] == "product"][0]
check("ethyl acetate theoretical 881.06 mg", abs(acetate["theoretical_mg"] - 881.06) < 0.02,
      str(acetate["theoretical_mg"]))
check("mass balance conserved", abs(d["mass_balance_mg"] - 1061.21) < 0.05, str(d["mass_balance_mg"]))

with_yield = calc.handle({"reaction": "CCO.CC(=O)O>>CC(=O)OCC.O", "scaleMmol": 10, "yieldPercent": 80})
check("yield applied", abs(with_yield["data"]["actual_mg"] - 704.85) < 0.05,
      str(with_yield["data"]["actual_mg"]))

unbalanced = calc.handle({"reaction": "CCO.O>>CC(=O)O"})
check("unbalanced reported", unbalanced["data"]["balanced"] is False)
check("unbalanced lists elements", "diff" in unbalanced["data"]["problem"],
      str(unbalanced["data"]["problem"].get("diff")))

bad_reaction = calc.handle({"reaction": "CCO"})
check("bad reaction rejected", bad_reaction["ok"] is False and bad_reaction["failure"]["code"] == "bad-reaction")

hrms = calc.handle({"kind": "hrms", "smiles": "CC(=O)Nc1ccc(O)cc1"})
hd = hrms["data"]
check("hrms formula", hd["formula"] == "C8H9NO2", hd["formula"])
check("hrms exact mass", abs(hd["exact_mass"] - 151.063329) < 1e-6, str(hd["exact_mass"]))
h_adduct = {a["adduct"]: a["mz"] for a in hd["adducts"]}
check("[M+H]+ 152.0706", abs(h_adduct["[M+H]+"] - 152.0706) < 5e-4, str(h_adduct["[M+H]+"]))
check("[M+Na]+ 174.0525", abs(h_adduct["[M+Na]+"] - 174.0525) < 5e-4, str(h_adduct["[M+Na]+"]))
check("hrms text", hd["text"].startswith("HRMS (ESI) m/z calcd for C8H9NO2"), hd["text"])

plate = calc.handle({"kind": "plate", "startConc": 100, "dilution": 2, "count": 8, "replicates": 2})
p = plate["data"]
check("plate series starts 100", p["series"][0]["conc"] == 100)
check("plate series halves", p["series"][1]["conc"] == 50, str(p["series"][1]["conc"]))
check("plate wells 16", p["well_count"] == 16, str(p["well_count"]))
check("plate well ids", p["wells"][0]["well"] == "A1", p["wells"][0]["well"])

bad_dilution = calc.handle({"kind": "plate", "dilution": 1})
check("dilution<=1 rejected", bad_dilution["ok"] is False and bad_dilution["failure"]["code"] == "bad-dilution")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_calc: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
