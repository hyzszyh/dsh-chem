r"""Assertions for chem_retro: disconnections must return real precursors."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import retro  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


def routes_of(smiles, **kwargs):
    payload = {"smiles": smiles}
    payload.update(kwargs)
    return retro.handle(payload)


ACID = "QTBSBXVTEAMEQO-UHFFFAOYSA-N"
ETHANOL = "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"

ester = routes_of("CCOC(C)=O")
check("ester ok", ester["ok"] is True, str(ester.get("failure")))
check("ester gives a route", ester["data"]["disconnections"] >= 1, str(ester["data"]["disconnections"]))
first = ester["data"]["routes"][0]
check("ester precursors are acid + ethanol", set(first["precursorInchikeys"]) == {ACID, ETHANOL},
      str(first["precursorInchikeys"]))
check("ester names the template", first["template"] == "酯化", str(first["template"]))

amide = routes_of("CC(=O)Nc1ccc(O)cc1")
amide_keys = {tuple(sorted(route["precursorInchikeys"])) for route in amide["data"]["routes"]}
check("amide route exists", bool(amide_keys), str(amide["data"]["disconnections"]))
check("amide route includes acetic acid",
      any(ACID in key for key in amide_keys), str(sorted(amide_keys)[:2]))
aminophenol = "PLIKAWJENQZMHA-UHFFFAOYSA-N"
check("amide route includes 4-aminophenol",
      any(aminophenol in key for key in amide_keys), str(sorted(amide_keys)[:2]))

biaryl = routes_of("c1ccc(cc1)-c1ccccc1")
suzuki = [route for route in biaryl["data"]["routes"] if route["template"] == "Suzuki 联芳"]
check("biaryl found by Suzuki", len(suzuki) == 1, str([r["template"] for r in biaryl["data"]["routes"]]))
check("biaryl precursors are two aryls", len(suzuki[0]["precursors"]) == 2,
      str(suzuki[0]["precursors"]))

alcohol = routes_of("CC(O)(C)c1ccccc1")
check("tertiary alcohol has a Grignard route",
      any(route["template"] == "格氏加成" for route in alcohol["data"]["routes"]),
      str([route["template"] for route in alcohol["data"]["routes"]]))

deep = routes_of("CCOC(C)=O", depth=2, limit=4)
check("depth 2 explored more nodes", deep["data"]["nodesExplored"] > ester["data"]["nodesExplored"],
      "%s vs %s" % (deep["data"]["nodesExplored"], ester["data"]["nodesExplored"]))
check("depth 2 warns about heuristics", any("启发式" in w for w in deep["warnings"]),
      str(deep["warnings"]))
check("depth 2 keeps level-1 routes", len(deep["data"]["routes"]) == ester["data"]["disconnections"],
      str(len(deep["data"]["routes"])))

plain = routes_of("CCCCCC")
check("alkane has no route", plain["data"]["disconnections"] == 0, str(plain["data"]["disconnections"]))
check("alkane explains why", any("模板库" in w for w in plain["warnings"]), str(plain["warnings"]))

templates = retro.handle({"action": "templates"})
check("template list", templates["data"]["count"] == len(retro.TEMPLATES), str(templates["data"]["count"]))
check("template list has smarts", all("smarts" in row for row in templates["data"]["templates"]))

check("missing smiles rejected", retro.handle({})["failure"]["code"] == "missing-input")
check("unknown action rejected", retro.handle({"action": "wat"})["failure"]["code"] == "unknown-action")

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_retro: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
