r"""Assertions for chem_compare: similarity, MCS, clustering, SAR."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import compare  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


sim = compare.handle({"mode": "sim", "query": "CC(=O)Oc1ccccc1C(=O)O",
                     "smilesList": "OC(=O)c1ccccc1O,CCO"})
d = sim["data"]
check("sim ok", sim["ok"] is True)
check("sim sorted desc", d["results"][0]["tanimoto"] >= d["results"][1]["tanimoto"],
      str([r["tanimoto"] for r in d["results"]]))
check("salicylic closer than ethanol", d["results"][0]["tanimoto"] > 0.4 and d["results"][1]["tanimoto"] < 0.2,
      str([r["tanimoto"] for r in d["results"]]))
check("query props present", abs(d["query_props"]["mw"] - 180.159) < 1e-3, str(d["query_props"]["mw"]))

identical = compare.handle({"mode": "sim", "query": "c1ccccc1", "smilesList": "c1ccccc1"})
check("identical tanimoto 1.0", abs(identical["data"]["results"][0]["tanimoto"] - 1.0) < 1e-9,
      str(identical["data"]["results"][0]["tanimoto"]))

mcs = compare.handle({"mode": "mcs", "smilesList": "Cc1ccccc1,c1ccccc1O"})
md = mcs["data"]
check("mcs ok", mcs["ok"] is True)
check("mcs atoms 6", md["atoms"] == 6, str(md["atoms"]))
from rdkit import Chem  # noqa: E402
smarts_mol = Chem.MolFromSmarts(md["smarts"])
check("mcs smarts parses to 6 atoms", smarts_mol is not None and smarts_mol.GetNumAtoms() == 6,
      md["smarts"])

needs_two = compare.handle({"mode": "mcs", "smilesList": "CCO"})
check("mcs needs two", needs_two["ok"] is False and needs_two["failure"]["code"] == "needs-two")

cluster = compare.handle({"mode": "cluster", "cutoff": 0.4,
                          "smilesList": "Cc1ccccc1,Cc1ccc(C)cc1,Cc1ccc(O)cc1,CCO"})
cd = cluster["data"]
check("cluster ok", cluster["ok"] is True)
check("cluster count >= 2", cd["cluster_count"] >= 2, str(cd["cluster_count"]))
check("biggest cluster first", cd["clusters"][0]["size"] >= cd["clusters"][-1]["size"],
      str([c["size"] for c in cd["clusters"]]))
ethanol_cluster = [c for c in cd["clusters"]
                   if any("CCO" == m["smiles"] for m in c["members"])]
check("ethanol clustered alone", ethanol_cluster and ethanol_cluster[0]["size"] == 1,
      str(ethanol_cluster[0]["size"]) if ethanol_cluster else "missing")

sar = compare.handle({"mode": "sar", "query": "Cc1ccccc1", "smilesList": "Cc1ccc(O)cc1,CCO"})
sd = sar["data"]
check("sar ok", sar["ok"] is True)
check("sar rows 2", sd["count"] == 2, str(sd["count"]))
check("sar delta mw", abs(sd["rows"][0]["d_mw"] - (sd["rows"][0]["mw"] - sd["reference_props"]["mw"])) < 1e-6)

bad_mode = compare.handle({"mode": "vibes"})
check("unknown mode rejected", bad_mode["ok"] is False and bad_mode["failure"]["code"] == "unknown-mode")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_compare: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
