r"""Assertions for chem_table: matrix, filtering, dedupe, 4PL fit."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import table  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


matrix = table.handle({"action": "matrix",
                       "smilesList": "CCO,CC(=O)Nc1ccc(O)cc1,c1ccccc1"})
md = matrix["data"]
check("matrix ok", matrix["ok"] is True)
check("matrix rows 3", md["count"] == 3, str(md["count"]))
para = md["rows"][1]
check("matrix paracetamol mw", abs(para["mw"] - 151.165) < 1e-6, str(para["mw"]))
check("matrix has qed", "qed" in para)

filtered = table.handle({"action": "matrix", "smilesList": "CCO,CC(=O)Nc1ccc(O)cc1", "filter": "MW<100"})
check("filter keeps only ethanol", filtered["data"]["count"] == 1, str(filtered["data"]["count"]))
check("filter kept the right one", filtered["data"]["rows"][0]["formula"] == "C2H6O",
      filtered["data"]["rows"][0]["formula"])

two_clauses = table.handle({"action": "matrix", "smilesList": "CCO,CC(=O)Nc1ccc(O)cc1",
                            "filter": "MW<200 and HBD<=2"})
check("two clauses", two_clauses["data"]["count"] == 2, str(two_clauses["data"]["count"]))

subset = table.handle({"action": "matrix", "smilesList": "CCO", "fields": "mw,logp"})
check("field subset", list(subset["data"]["rows"][0].keys()) == ["index", "input", "mw", "logp"],
      ",".join(subset["data"]["rows"][0].keys()))

invalid = table.handle({"action": "matrix", "smilesList": "CCO,C1CC"})
check("invalid tracked", len(invalid["data"]["invalid"]) == 1 and invalid["data"]["count"] == 1,
      str(invalid["data"]["invalid"]))

dedupe = table.handle({"action": "clean", "smilesList": "CCO,OCC,CC(=O)[O-].[Na+],CCO"})
dd = dedupe["data"]
check("dedupe kept 2", dd["kept_count"] == 2, str(dd["kept_count"]))
check("duplicate removed", any(r["reason"] == "duplicate" for r in dd["removed"]),
      str([r["reason"] for r in dd["removed"]]))
check("salt standardized", any(r["formula"] == "C2H4O2" for r in dd["kept"]),
      str([r["formula"] for r in dd["kept"]]))

xs = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
ys = [round(100.0 / (1.0 + (x / 1.5) ** 1.2), 3) for x in xs]
fit = table.handle({"action": "fit", "x": xs, "y": ys})
fd = fit["data"]
check("fit ok", fit["ok"] is True)
check("fit recovers ic50 1.5", abs(fd["ic50"] - 1.5) / 1.5 < 0.05, str(fd["ic50"]))
check("fit r2 high", fd["r2"] > 0.99, str(fd["r2"]))
check("fit hill ~1.2", abs(fd["hill"] - 1.2) < 0.15, str(fd["hill"]))

bad_x = table.handle({"action": "fit", "x": [0, 1, 2, 3], "y": [1, 2, 3, 4]})
check("non-positive x rejected", bad_x["ok"] is False and bad_x["failure"]["code"] == "non-positive-x")

short = table.handle({"action": "fit", "x": [1, 2], "y": [1, 2]})
check("too few points rejected", short["ok"] is False and short["failure"]["code"] == "not-enough-points")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_table: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
