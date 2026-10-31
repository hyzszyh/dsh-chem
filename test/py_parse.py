r"""Assertions for chem_parse: names, sequences, and one fixed picture."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import parse  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


PARA = "RZVAJINKPMORJF-UHFFFAOYSA-N"

cn = parse.handle({"source": "扑热息痛"})
check("chinese name resolves", cn["ok"] is True)
check("paracetamol inchikey", cn["data"]["inchikey"] == PARA, str(cn["data"].get("inchikey")))
check("source reported", cn["channel"] == "builtin-dictionary", str(cn["channel"]))

en = parse.handle({"source": "Acetaminophen"})
check("english name case-insensitive", en["data"]["inchikey"] == PARA, str(en["data"].get("inchikey")))

aspirin = parse.handle({"source": "阿司匹林"})
check("aspirin inchikey", aspirin["data"]["inchikey"].startswith("BSYNRYMUTXBXSQ"), str(aspirin["data"]["inchikey"]))

# Auto-detection order, measured 2026-10-30: aspirin matched the residue pattern
# (A-S-P-I-R-I-N) and came back as a 7-residue peptide instead of C9H8O4; CCO was
# rejected as a SMILES because it has no lowercase aromatic/nitro characters.
auto_aspirin = parse.handle({"source": "aspirin"})
check("auto aspirin is the drug, not a peptide", auto_aspirin["data"]["formula"] == "C9H8O4",
      str(auto_aspirin["data"].get("formula")))
auto_smiles = parse.handle({"source": "CCO"})
check("auto reads CCO as SMILES", auto_smiles["data"]["formula"] == "C2H6O",
      str(auto_smiles["data"].get("formula")))
auto_benzaldehyde = parse.handle({"source": "苯甲醛"})
check("auto resolves 苯甲醛", auto_benzaldehyde["data"]["formula"] == "C7H6O",
      str(auto_benzaldehyde.get("failure", {}).get("code")))
auto_seq = parse.handle({"source": "ACDEF"})
check("auto still reads a residue string as a sequence",
      auto_seq["data"]["residues"] == 5, str(auto_seq["data"].get("residues")))

bad = parse.handle({"source": "unobtainium-42"})
check("unknown name rejected", bad["ok"] is False and bad["failure"]["code"] == "unresolved-name",
      str(bad.get("failure", {}).get("code")))
check("unknown name mentions network option", "PubChem" in bad["failure"]["hint"], bad["failure"].get("hint", ""))

missing = parse.handle({})
check("empty rejected", missing["ok"] is False and missing["failure"]["code"] == "missing-input")

smiles_echo = parse.handle({"source": "CC(=O)Nc1ccc(O)cc1"})
check("smiles passes through", smiles_echo["ok"] is True and smiles_echo["channel"] == "smiles")
check("smiles inchikey", smiles_echo["data"]["inchikey"] == PARA)

gly2 = parse.handle({"kind": "seq", "source": "GG"})
check("dipeptide ok", gly2["ok"] is True, str(gly2.get("failure")))
check("dipeptide formula", gly2["data"]["formula"] == "C4H8N2O3", str(gly2["data"].get("formula")))
check("dipeptide mw", abs(gly2["data"]["mw"] - 132.118) < 0.01, str(gly2["data"].get("mw")))

tri = parse.handle({"kind": "seq", "source": "Gly-Ala-Ser"})
check("three-letter sequence", tri["ok"] is True, str(tri.get("failure")))
check("three residues", tri["data"]["residues"] == 3, str(tri["data"].get("residues")))
check("peptide warns about templates", any("残基模板" in w for w in tri["warnings"]), str(tri["warnings"]))

proline = parse.handle({"kind": "seq", "source": "PGG"})
check("proline accepted", proline["ok"] is True, str(proline.get("failure")))

badseq = parse.handle({"kind": "seq", "source": "GGX"})
check("unknown residue rejected", badseq["ok"] is False and badseq["failure"]["code"] == "bad-sequence",
      str(badseq.get("failure", {}).get("code")))

# One fixed picture must give one fixed InChIKey. DECIMER reads the RDKit render
# exactly; MolVec crashes on it, which the result reports rather than hides.
image_path = ROOT / "test" / "out" / "w3" / "paracetamol_85mm.png"
if not image_path.is_file():
    # test/out is generated and gitignored, so a fresh clone starts without the
    # fixture. Render it here: the assertion is about reading a picture, not about
    # inheriting one (measured: a clean `git archive` copy failed this suite until
    # the fixture was produced).
    image_path.parent.mkdir(parents=True, exist_ok=True)
    from chem import draw as drawmod  # noqa: E402
    fixture_smiles = parse._lookup_name("paracetamol")[0]
    drawn = drawmod.handle({"smiles": fixture_smiles, "format": "png", "widthMm": 85,
                            "out": str(image_path)})
    check("picture fixture rendered", drawn.get("ok") is True and image_path.is_file(),
          str(drawn.get("failure")))
if image_path.is_file():
    picture = parse.handle({"kind": "image", "source": str(image_path), "engines": ["decimer"]})
    check("picture parsed", picture["ok"] is True, str(picture.get("failure", {}).get("code")))
    if picture["ok"]:
        check("picture inchikey matches", picture["data"]["best"]["inchikey"] == PARA,
              str(picture["data"]["best"].get("inchikey")))
        check("picture flags confirmation", picture["data"]["needs_confirmation"] is True)
        check("picture warns slow", any("秒" in w for w in picture["warnings"]), str(picture["warnings"][:2]))
else:
    check("picture fixture present", False, str(image_path))

no_image = parse.handle({"kind": "image", "source": "D:/nope/missing.png"})
check("missing image rejected", no_image["ok"] is False and no_image["failure"]["code"] == "no-such-image",
      str(no_image.get("failure", {}).get("code")))

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_parse: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
