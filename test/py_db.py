r"""Assertions for chem_db: a real SQLite library, queried three ways."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import db  # noqa: E402

results = []
TMP = Path(tempfile.mkdtemp(prefix="dsh-chem-db-"))
LIB = {"db": str(TMP / "lib.db")}


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


def call(**kwargs):
    payload = dict(LIB)
    payload.update(kwargs)
    return db.handle(payload)


SEED = "CCO\te-thanol\nCC(=O)O\tacetic acid\nc1ccccc1\tbenzene\nCC(=O)Nc1ccc(O)cc1\tparacetamol\n"

added = call(action="add", text=SEED)
check("add ok", added["ok"] is True, str(added.get("failure")))
check("added 4", added["data"]["added"] == 4, str(added["data"].get("added")))
check("total 4", added["data"]["total"] == 4, str(added["data"].get("total")))

again = call(action="add", text=SEED)
check("duplicates skipped", again["data"]["added"] == 0 and again["data"]["duplicates"] == 4,
      str((again["data"]["added"], again["data"]["duplicates"])))
check("total still 4", again["data"]["total"] == 4)

props_row = call(action="search", mode="filter", name="paracetamol")["data"]["hits"][0]
check("rotb populated", props_row["rotb"] is not None, str(props_row["rotb"]))
check("heavy populated", props_row["heavy"] == 11, str(props_row["heavy"]))
check("inchikey stored", props_row["inchikey"] == "RZVAJINKPMORJF-UHFFFAOYSA-N", props_row["inchikey"])

ring = call(action="search", mode="substructure", query="c1ccccc1")
check("substructure benzene finds 2", ring["data"]["count"] == 2, str(ring["data"]["count"]))
check("matched atoms listed", len(ring["data"]["hits"][0]["matched_atoms"]) == 6,
      str(ring["data"]["hits"][0]["matched_atoms"]))

amide = call(action="search", mode="substructure", query="CC(=O)N")
check("substructure amide finds paracetamol", amide["data"]["count"] == 1, str(amide["data"]["count"]))

sim = call(action="search", mode="similarity", query="CCO", cutoff=0.1)
check("similarity sorted", sim["data"]["hits"][0]["similarity"] == 1.0, str(sim["data"]["hits"][0]["similarity"]))
check("similarity cutoff honoured", all(h["similarity"] >= 0.1 for h in sim["data"]["hits"]))

# 60 would also catch acetic acid (60.052); the window has to exclude it on purpose.
mw = call(action="search", mode="filter", mwMin=70, mwMax=100)
check("mw filter finds benzene", mw["data"]["count"] == 1, str(mw["data"]["count"]))
check("mw filter values in range", all(70 <= h["mw"] <= 100 for h in mw["data"]["hits"]))

stats = call(action="stats")
check("stats total 4", stats["data"]["total"] == 4, str(stats["data"]["total"]))
check("stats mw range", abs(stats["data"]["mwMin"] - 46.069) < 1e-3, str(stats["data"]["mwMin"]))

sdf_path = TMP / "export.sdf"
exported = call(action="export", format="sdf", out=str(sdf_path))
check("export sdf ok", exported["ok"] is True, str(exported.get("failure")))
check("export sdf records", Path(exported["data"]["path"]).read_text(encoding="utf-8").count("$$$$") == 4,
      str(Path(exported["data"]["path"]).read_text(encoding="utf-8").count("$$$$")))
csv_text = call(action="export", format="csv")["data"]["inline"]
check("export csv has header", csv_text.startswith("smiles,inchikey"), csv_text[:30])

imported = call(action="add", path=str(sdf_path))
check("round trip import dedupes", imported["data"]["added"] == 0 and imported["data"]["duplicates"] == 4,
      str((imported["data"]["added"], imported["data"]["duplicates"])))

removed = call(action="remove", inchikey="UHOVQNZJYSORNB-UHFFFAOYSA-N")
check("remove one", removed["data"]["removed"] == 1, str(removed["data"]["removed"]))
check("total 3 after remove", call(action="stats")["data"]["total"] == 3)

bad = call(action="add", text="C1CC totally-broken")
check("bad smiles skipped not fatal", bad["ok"] is True and len(bad["data"]["skipped"]) >= 1,
      str(bad["data"].get("skipped"))[:100])

unknown = call(action="nope")
check("unknown action rejected", unknown["ok"] is False and unknown["failure"]["code"] == "unknown-action",
      str(unknown.get("failure", {}).get("code")))

missing_file = call(action="add", path=str(TMP / "nope.sdf"))
check("missing file reported", missing_file["ok"] is False, str(missing_file.get("failure", {}).get("code")))

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_db: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
