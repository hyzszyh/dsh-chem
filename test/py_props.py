r"""Deterministic assertions for chem_props.

Run with the venv python:  %LOCALAPPDATA%\dsh-chem\runtime\Scripts\python.exe test/py_props.py
Values below are RDKit reference values, not "looks about right".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import props  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


def run(smiles, **kw):
    payload = {"smiles": smiles}
    payload.update(kw)
    return props.handle(payload)


para = run("CC(=O)Nc1ccc(O)cc1")
d = para["data"]
check("paracetamol ok", para["ok"] is True)
check("formula C8H9NO2", d["formula"] == "C8H9NO2", d["formula"])
check("mw 151.165", abs(d["mw"] - 151.165) < 1e-6, str(d["mw"]))
check("exact mass 151.063329", abs(d["exact_mass"] - 151.063329) < 1e-9, str(d["exact_mass"]))
check("inchikey", d["inchikey"] == "RZVAJINKPMORJF-UHFFFAOYSA-N", str(d["inchikey"]))
check("tpsa 49.33", abs(d["tpsa"] - 49.33) < 1e-6, str(d["tpsa"]))
check("hbd 2", d["hbd"] == 2, str(d["hbd"]))
check("hba 2", d["hba"] == 2, str(d["hba"]))
check("ring counts", d["rings"] == 1 and d["aromatic_rings"] == 1, "%s/%s" % (d["rings"], d["aromatic_rings"]))

eth = run("CCO")["data"]
check("ethanol mw", abs(eth["mw"] - 46.069) < 1e-6, str(eth["mw"]))
check("ethanol fsp3 1.0", abs(eth["fraction_csp3"] - 1.0) < 1e-9, str(eth["fraction_csp3"]))

salt = run("CC(=O)[O-].[Na+]")["data"]
check("salt net charge 0", salt["formal_charge"] == 0, str(salt["formal_charge"]))
check("salt 2 fragments", salt["num_fragments"] == 2, str(salt["num_fragments"]))
check("salt heavy atoms 5", salt["heavy_atoms"] == 5, str(salt["heavy_atoms"]))

anion = run("CC(=O)[O-]")["data"]
check("acetate charge -1", anion["formal_charge"] == -1, str(anion["formal_charge"]))

ala = run("N[C@@H](C)C(=O)O")["data"]
check("alanine stereocenter", ala["num_stereocenters"] == 1, str(ala["num_stereocenters"]))

subset = run("CC(=O)Nc1ccc(O)cc1", fields="formula,mw")["data"]
check("field subset", list(subset.keys()) == ["formula", "mw"], ",".join(subset.keys()))

unknown = run("CCO", fields="formula,bogus")
check("unknown field rejected", unknown["ok"] is False and unknown["failure"]["code"] == "unknown-field")

bad = run("C1CC")
check("bad structure rejected", bad["ok"] is False and bad["failure"]["code"] == "bad-structure")

empty = run("")
check("empty rejected", empty["ok"] is False and empty["failure"]["code"] == "empty-input")

a = json.dumps(run("c1ccccc1O"), sort_keys=True)
b = json.dumps(run("c1ccccc1O"), sort_keys=True)
check("deterministic", a == b)

inchi = run("InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3")["data"]
check("inchi input", inchi["formula"] == "C2H6O", str(inchi["formula"]))

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_props: %d/%d PASS" % (len(results) - failed, len(results)) if failed == 0
      else "chem_props: %d/%d PASS, %d FAIL" % (len(results) - failed, len(results), failed))
raise SystemExit(0 if failed == 0 else 1)
