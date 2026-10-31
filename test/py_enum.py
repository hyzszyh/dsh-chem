r"""Assertions for chem_enum: variants, libraries, stereoisomers, tautomers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import enum as enummod  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


variant = enummod.handle({"mode": "variant", "scaffold": "c1ccccc1[*:1]",
                          "substituents": "C,O,N"})
check("variant ok", variant["ok"] is True, str(variant.get("failure")))
check("variant produces 3", variant["data"]["produced"] == 3, str(variant["data"].get("produced")))
check("toluene present", any(s["smiles"] == "Cc1ccccc1" for s in variant["data"]["structures"]),
      str([s["smiles"] for s in variant["data"]["structures"]][:4]))

dupes = enummod.handle({"mode": "variant", "scaffold": "c1ccccc1[*:1]", "substituents": "C,C,O"})
check("duplicates removed", dupes["data"]["produced"] == 2 and dupes["data"]["duplicates_removed"] == 1,
      str((dupes["data"]["produced"], dupes["data"]["duplicates_removed"])))

library = enummod.handle({"mode": "library", "scaffold": "c1cc([*:1])ccc1[*:2]",
                          "substituents": "C,O", "substituents2": "F,Cl"})
check("library ok", library["ok"] is True, str(library.get("failure")))
check("library 2x2", library["data"]["produced"] == 4, str(library["data"].get("produced")))
check("library slots", library["data"]["slots"] == 2, str(library["data"].get("slots")))

no_dummy = enummod.handle({"mode": "variant", "scaffold": "c1ccccc1", "substituents": "C"})
check("scaffold without dummy rejected",
      no_dummy["ok"] is False and no_dummy["failure"]["code"] == "no-attachment",
      str(no_dummy.get("failure", {}).get("code")))

bad_frag = enummod.handle({"mode": "variant", "scaffold": "c1ccccc1[*:1]", "substituents": "C1CC"})
check("bad substituent reported not raised", bad_frag["ok"] is True and bad_frag["data"]["produced"] == 0
      and bad_frag["data"]["failures"], str(bad_frag["data"].get("failures"))[:120])

stereo = enummod.handle({"mode": "stereo", "smiles": "CC(Cl)Br"})
check("stereo 2 isomers", stereo["data"]["count"] == 2, str(stereo["data"].get("count")))
keys = {row["inchikey"] for row in stereo["data"]["isomers"]}
check("stereo isomers differ", len(keys) == 2, str(len(keys)))

no_stereo = enummod.handle({"mode": "stereo", "smiles": "CCO"})
check("achiral single isomer", no_stereo["data"]["count"] == 1, str(no_stereo["data"].get("count")))

capped = enummod.handle({"mode": "stereo", "smiles": "CC(Cl)C(Br)C(F)C(I)", "max": 4})
check("cap respected", capped["data"]["count"] <= 4, str(capped["data"].get("count")))
check("cap warns", bool(capped["warnings"]), str(capped.get("warnings")))

taut = enummod.handle({"mode": "tautomer", "smiles": "CC(=O)Nc1ccc(O)cc1"})
check("tautomers found", taut["data"]["count"] >= 2, str(taut["data"].get("count")))
check("parent among tautomers",
      any(row["inchikey"] == "RZVAJINKPMORJF-UHFFFAOYSA-N" for row in taut["data"]["tautomers"]))

unknown = enummod.handle({"mode": "nonsense", "smiles": "CCO"})
check("unknown mode rejected", unknown["ok"] is False and unknown["failure"]["code"] == "unknown-mode",
      str(unknown.get("failure", {}).get("code")))

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_enum: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
