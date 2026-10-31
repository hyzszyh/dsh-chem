"""chem_parse: name, picture, or sequence in; structure out.

Three sources, one honest rule: never invent a structure.
  name  -- built-in teaching dictionary (Chinese + English + common synonyms),
           then OPSIN if its jar is present, then PubChem only when the caller
           explicitly allows the network.
  image -- the OCSR stack this project already had (MolVec + DECIMER, MolScribe
           as an optional third vote). Voting by InChIKey, so a single reader
           being wrong cannot silently win.
  seq   -- one-letter or three-letter peptide sequences, built from residue
           templates; the output says what was approximated.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import mol as molmod

# Teaching dictionary: the names that actually appear in undergraduate work.
# Deliberately short and curated -- a long scraped list would be a different,
# worse artifact than a list someone can read and argue with.
DICTIONARY = [
    # Second batch (2026-10-30): 苯甲醛 and friends were the first names an
    # undergraduate reaches for, and the dictionary answered 查不出.
    ("benzaldehyde", "O=Cc1ccccc1"), ("苯甲醛", "O=Cc1ccccc1"),
    ("benzoic acid", "OC(=O)c1ccccc1"), ("苯甲酸", "OC(=O)c1ccccc1"),
    ("salicylic acid", "OC(=O)c1ccccc1O"), ("水杨酸", "OC(=O)c1ccccc1O"),
    ("acetylsalicylic acid", "CC(=O)Oc1ccccc1C(=O)O"), ("阿司匹林", "CC(=O)Oc1ccccc1C(=O)O"),
    ("乙酰水杨酸", "CC(=O)Oc1ccccc1C(=O)O"),
    ("acetaldehyde", "CC=O"), ("乙醛", "CC=O"),
    ("formaldehyde", "C=O"), ("甲醛", "C=O"),
    ("aniline", "Nc1ccccc1"), ("苯胺", "Nc1ccccc1"),
    ("nitrobenzene", "[O-][N+](=O)c1ccccc1"), ("硝基苯", "[O-][N+](=O)c1ccccc1"),
    ("chlorobenzene", "Clc1ccccc1"), ("氯苯", "Clc1ccccc1"),
    ("styrene", "C=Cc1ccccc1"), ("苯乙烯", "C=Cc1ccccc1"),
    ("bromoethane", "CCBr"), ("溴乙烷", "CCBr"),
    ("acetic anhydride", "CC(=O)OC(C)=O"), ("乙酸酐", "CC(=O)OC(C)=O"),
    ("ethylene glycol", "OCCO"), ("乙二醇", "OCCO"),
    ("glycerol", "OCC(O)CO"), ("甘油", "OCC(O)CO"),
    ("urea", "NC(N)=O"), ("尿素", "NC(N)=O"),
    ("lactic acid", "CC(O)C(=O)O"), ("乳酸", "CC(O)C(=O)O"),
    ("citric acid", "OC(=O)CC(O)(CC(=O)O)C(=O)O"), ("柠檬酸", "OC(=O)CC(O)(CC(=O)O)C(=O)O"),
    ("cyclohexane", "C1CCCCC1"), ("环己烷", "C1CCCCC1"),
    ("n-hexane", "CCCCCC"), ("正己烷", "CCCCCC"),
    ("ethyl acetate", "CCOC(C)=O"), ("乙酸乙酯", "CCOC(C)=O"),
    ("phenol", "Oc1ccccc1"), ("苯酚", "Oc1ccccc1"),
    ("toluene", "Cc1ccccc1"), ("甲苯", "Cc1ccccc1"),
    ("paracetamol", "CC(=O)Nc1ccc(O)cc1"), ("对乙酰氨基酚", "CC(=O)Nc1ccc(O)cc1"),
    ("aspirin", "CC(=O)Oc1ccccc1C(=O)O"),
    ("ethanol", "CCO"), ("酒精", "CCO"), ("乙醇", "CCO"),
    ("methanol", "CO"), ("甲醇", "CO"),
    ("acetic acid", "CC(=O)O"), ("醋酸", "CC(=O)O"), ("乙酸", "CC(=O)O"),
    ("acetone", "CC(=O)C"), ("丙酮", "CC(=O)C"),
    ("benzene", "c1ccccc1"), ("苯", "c1ccccc1"),
    ("toluene", "Cc1ccccc1"), ("甲苯", "Cc1ccccc1"),
    ("phenol", "Oc1ccccc1"), ("苯酚", "Oc1ccccc1"), ("石炭酸", "Oc1ccccc1"),
    ("paracetamol", "CC(=O)Nc1ccc(O)cc1"), ("acetaminophen", "CC(=O)Nc1ccc(O)cc1"),
    ("对乙酰氨基酚", "CC(=O)Nc1ccc(O)cc1"), ("扑热息痛", "CC(=O)Nc1ccc(O)cc1"),
    ("aspirin", "CC(=O)Oc1ccccc1C(=O)O"), ("acetylsalicylic acid", "CC(=O)Oc1ccccc1C(=O)O"),
    ("阿司匹林", "CC(=O)Oc1ccccc1C(=O)O"), ("乙酰水杨酸", "CC(=O)Oc1ccccc1C(=O)O"),
    ("caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"), ("咖啡因", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"),
    ("ibuprofen", "CC(C)Cc1ccc(cc1)C(C)C(=O)O"), ("布洛芬", "CC(C)Cc1ccc(cc1)C(C)C(=O)O"),
    ("salicylic acid", "OC(=O)c1ccccc1O"), ("水杨酸", "OC(=O)c1ccccc1O"),
    ("benzoic acid", "OC(=O)c1ccccc1"), ("苯甲酸", "OC(=O)c1ccccc1"),
    ("urea", "NC(=O)N"), ("尿素", "NC(=O)N"),
    ("glucose", "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"), ("葡萄糖", "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"),
    ("glycine", "NCC(=O)O"), ("甘氨酸", "NCC(=O)O"),
    ("alanine", "N[C@@H](C)C(=O)O"), ("丙氨酸", "N[C@@H](C)C(=O)O"),
    ("pyridine", "c1ccncc1"), ("吡啶", "c1ccncc1"),
    ("aniline", "Nc1ccccc1"), ("苯胺", "Nc1ccccc1"),
    ("nitrobenzene", "O=[N+]([O-])c1ccccc1"), ("硝基苯", "O=[N+]([O-])c1ccccc1"),
    ("formaldehyde", "C=O"), ("甲醛", "C=O"),
    ("acetaldehyde", "CC=O"), ("乙醛", "CC=O"),
    ("ethyl acetate", "CCOC(C)=O"), ("乙酸乙酯", "CCOC(C)=O"),
    ("chloroform", "ClC(Cl)Cl"), ("氯仿", "ClC(Cl)Cl"), ("三氯甲烷", "ClC(Cl)Cl"),
    ("dichloromethane", "ClCCl"), ("二氯甲烷", "ClCCl"),
    ("dmso", "CS(C)=O"), ("二甲基亚砜", "CS(C)=O"),
    ("dmf", "CN(C)C=O"), ("n,n-dimethylformamide", "CN(C)C=O"), ("n，n-二甲基甲酰胺", "CN(C)C=O"),
    ("thf", "C1CCOC1"), ("四氢呋喃", "C1CCOC1"),
    ("naphthalene", "c1ccc2ccccc2c1"), ("萘", "c1ccc2ccccc2c1"),
    ("indole", "c1ccc2[nH]ccc2c1"), ("吲哚", "c1ccc2[nH]ccc2c1"),
    ("furan", "c1ccoc1"), ("呋喃", "c1ccoc1"),
    ("thiophene", "c1ccsc1"), ("噻吩", "c1ccsc1"),
    ("imidazole", "c1c[nH]cn1"), ("咪唑", "c1c[nH]cn1"),
    ("quinoline", "c1ccc2ncccc2c1"), ("喹啉", "c1ccc2ncccc2c1"),
    ("cyclohexane", "C1CCCCC1"), ("环己烷", "C1CCCCC1"),
    ("menthol", "CC(C)C1CCC(C)CC1O"), ("薄荷醇", "CC(C)C1CCC(C)CC1O"),
    ("vanillin", "COc1cc(C=O)ccc1O"), ("香草醛", "COc1cc(C=O)ccc1O"),
    ("cholesterol", "CC(C)CCCC(C)C1CCC2C1(CCC3C2CC=C4C3(CCC(C4)O)C)C"), ("胆固醇", "CC(C)CC1CCC2C1(CCC3C2CC=C4C3(CCC(C4)O)C)C"),
    ("dopamine", "NCCc1ccc(O)c(O)c1"), ("多巴胺", "NCCc1ccc(O)c(O)c1"),
    ("serotonin", "NCCc1c[nH]c2ccc(O)cc12"), ("5-羟色胺", "NCCc1c[nH]c2ccc(O)cc12"),
    ("tryptophan", "N[C@@H](Cc1c[nH]c2ccccc12)C(=O)O"), ("色氨酸", "N[C@@H](Cc1c[nH]c2ccccc12)C(=O)O"),
    ("nicotinamide", "NC(=O)c1cccnc1"), ("烟酰胺", "NC(=O)c1cccnc1"),
    ("ascorbic acid", "OC[C@H](O)[C@H]1OC(=O)C(O)=C1O"), ("维生素c", "OC[C@H](O)[C@H]1OC(=O)C(O)=C1O"),
    ("water", "O"), ("水", "O"),
    ("ammonia", "N"), ("氨", "N"),
    ("methane", "C"), ("甲烷", "C"),
]

THREE_LETTER = {
    "ALA": ("A", "alanine"), "ARG": ("R", "arginine"), "ASN": ("N", "asparagine"),
    "ASP": ("D", "aspartic acid"), "CYS": ("C", "cysteine"), "GLN": ("Q", "glutamine"),
    "GLU": ("E", "glutamic acid"), "GLY": ("G", "glycine"), "HIS": ("H", "histidine"),
    "ILE": ("I", "isoleucine"), "LEU": ("L", "leucine"), "LYS": ("K", "lysine"),
    "MET": ("M", "methionine"), "PHE": ("F", "phenylalanine"), "PRO": ("P", "proline"),
    "SER": ("S", "serine"), "THR": ("T", "threonine"), "TRP": ("W", "tryptophan"),
    "TYR": ("Y", "tyrosine"), "VAL": ("V", "valine"),
}

SIDECHAIN = {
    "G": "", "A": "C", "V": "C(C)C", "L": "CC(C)C", "I": "[C@@H](C)CC",
    "S": "CO", "T": "[C@@H](C)O", "C": "CS", "M": "CCSC",
    "D": "CC(=O)O", "E": "CCC(=O)O", "N": "CC(=O)N", "Q": "CCC(=O)N",
    "K": "CCCCN", "R": "CCCNC(=N)N", "H": "Cc1c[nH]cn1",
    "F": "Cc1ccccc1", "Y": "Cc1ccc(O)cc1", "W": "Cc1c[nH]c2ccccc12",
    "P": "PROLINE",
}

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


def _engine_root():
    local = os.environ.get("LOCALAPPDATA") or ""
    return Path(local) / "chem-draw-tool" / "engines"


def _lookup_name(text):
    key = text.strip().lower().replace(" ", " ")
    for name, smiles in DICTIONARY:
        if key == name.lower():
            return smiles, name
    compact = re.sub(r"[\s\-_]+", "", key)
    for name, smiles in DICTIONARY:
        if compact == re.sub(r"[\s\-_]+", "", name.lower()):
            return smiles, name
    return None, None


def _try_opsin(text):
    jar = _engine_root() / "opsin" / "opsin.jar"
    if not jar.is_file():
        return None, "OPSIN jar 不在 %s" % jar
    import subprocess
    try:
        proc = subprocess.run(["java", "-jar", str(jar), "-o", "smi", text],
                              capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return None, "OPSIN 运行失败：%s" % str(exc)[:80]
    if proc.returncode != 0:
        return None, "OPSIN 解析不了：%s" % (proc.stderr or "").strip()[:80]
    return (proc.stdout or "").strip().splitlines()[0], None


def _try_pubchem(text):
    import json
    import urllib.parse
    import urllib.request
    url = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s/property/"
           "SMILES,IsomericSMILES,MolecularFormula/JSON"
           % urllib.parse.quote(text))
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "PubChem 查询失败：%s" % str(exc)[:80]
    rows = payload.get("PropertyTable", {}).get("Properties") or []
    if not rows:
        return None, "PubChem 没有这个名称的记录"
    return rows[0].get("SMILES") or rows[0].get("IsomericSMILES"), None


def _from_name(text, payload):
    smiles, matched = _lookup_name(text)
    source = "builtin-dictionary"
    notes = []
    if not smiles:
        smiles, opsin_note = _try_opsin(text)
        if smiles:
            source = "opsin"
        elif opsin_note:
            notes.append(opsin_note)
    if not smiles and payload.get("network"):
        smiles, note = _try_pubchem(text)
        if smiles:
            source = "pubchem"
        elif note:
            notes.append(note)
    if not smiles:
        return {"ok": False, "failure": {
            "code": "unresolved-name", "name": text,
            "message": "查不出这个名称对应的结构",
            "hint": "传 SMILES 最稳；或用 network=true 让我查 PubChem（会联网）",
            "notes": notes}}
    m = molmod.parse_struct(smiles)
    return {"ok": True, "channel": source,
            "data": {"input": text, "matched_name": matched, "smiles": molmod.canonical(m),
                     "formula": molmod.formula(m), "inchikey": molmod.inchikey(m)},
            "warnings": notes}


def _from_image(path, payload):
    image_path = Path(str(path))
    if not image_path.is_file():
        return {"ok": False, "failure": {"code": "no-such-image", "path": str(image_path),
                                        "message": "找不到这张图"}}
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from chemdraw_tool.v2 import ocr  # the OCSR stack this project already had

    engines = payload.get("engines")
    if isinstance(engines, str):
        engines = [e.strip() for e in engines.split(",") if e.strip()]
    result = ocr.read_image(str(image_path), llm_hint=str(payload.get("hint") or ""),
                            engines=engines)
    best = result.get("best") or {}
    if not best:
        return {"ok": False, "failure": {
            "code": "no-structure", "image": str(image_path),
            "message": "图里的结构认不出来",
            "hint": "先确认图里确实是完整结构式（不要裁掉键、不要只有局部）",
            "notes": result.get("notes"), "engine_ms": result.get("engine_ms")}}
    candidates = []
    for row in result.get("candidates") or []:
        candidates.append({"smiles": row.get("smiles"), "inchikey": row.get("inchikey"),
                           "formula": row.get("formula"), "votes": row.get("votes"),
                           "sources": row.get("sources"), "confidence": row.get("confidence")})
    return {"ok": True, "channel": "local-ocr",
            "data": {"image": str(image_path), "best": best, "candidates": candidates,
                     "rejected": result.get("rejected"), "proposals": result.get("proposals"),
                     "needs_confirmation": result.get("needs_confirmation"),
                     "engine_ms": result.get("engine_ms"), "notes": result.get("notes")},
            "warnings": (["识别结果需要人工确认（票数不足）：只有一个识别器给出答案"]
                         if result.get("needs_confirmation") else [])
                        + (["识别耗时 %.0f 秒（模型加载），慢但结果可用" % (max(result.get("engine_ms", {}).values() or [0]) / 1000)]
                           if (result.get("engine_ms") or {}) and max(result.get("engine_ms").values()) > 30000 else []),
            "evidence": {"engines": {k: v for k, v in (result.get("engines") or {}).items()},
                         "voting": "InChIKey"}}


def _from_sequence(text):
    tokens = re.split(r"[\s\-]+", text.strip().upper())
    if all(tok in THREE_LETTER for tok in tokens if tok):
        letters = [THREE_LETTER[tok][0] for tok in tokens if tok]
    else:
        compact = re.sub(r"[^A-Z]", "", text.upper())
        if not compact or any(ch not in SIDECHAIN for ch in compact):
            return None, "序列里有非标准残基：" + "".join(ch for ch in compact if ch not in SIDECHAIN)
        letters = list(compact)
    if not letters:
        return None, "序列为空"
    fragments = []
    for letter in letters:
        side = SIDECHAIN[letter]
        if side == "PROLINE":
            fragments.append("N1CCC[C@H]1C(=O)")
        else:
            fragments.append("N[C@@H](%s)C(=O)" % side if side else "NCC(=O)")
    # Fragments already end in "C(=O)", and SMILES lets the next "N..." continue
    # that carbonyl, so plain concatenation builds the amide bonds. Slicing the
    # last character (an early attempt) produced "NCC(=OO" instead.
    smiles = "".join(fragments) + "O"
    return smiles, None


def _residue_count(text):
    """Count residues, reading three-letter codes as one residue each."""
    tokens = [tok for tok in re.split(r"[\s\-]+", text.strip().upper()) if tok]
    if tokens and all(tok in THREE_LETTER for tok in tokens):
        return len(tokens)
    return len(re.sub(r"[^A-Z]", "", text.upper()))


def _from_seq(text):
    smiles, problem = _from_sequence(text)
    if problem:
        return {"ok": False, "failure": {"code": "bad-sequence", "message": problem,
                                        "hint": "标准 20 种氨基酸的单字母或三字母代码"}}
    m = molmod.parse_struct(smiles)
    from rdkit.Chem import Descriptors
    return {"ok": True, "channel": "residue-templates",
            "data": {"sequence": re.sub(r"[\s\-]+", "", text.upper()),
                     "smiles": molmod.canonical(m), "formula": molmod.formula(m),
                     "mw": round(Descriptors.MolWt(m), 3),
                     "residues": _residue_count(text)},
            "warnings": ["肽链由残基模板拼接，环肽/修饰残基/非天然氨基酸不支持"]}


def _looks_like_image(text):
    return text.lower().endswith(IMAGE_SUFFIXES) or Path(text).is_file()


def handle(payload):
    text = str(payload.get("source") or payload.get("text") or "").strip()
    kind = str(payload.get("kind") or "").strip().lower()
    if not text:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 source"}}

    if kind == "image" or (not kind and _looks_like_image(text)):
        return _from_image(text, payload)
    if kind == "seq":
        return _from_seq(text)
    if kind == "name":
        return _from_name(text, payload)

    # Auto: SMILES-ish is already a structure; a name we actually know beats a
    # residue guess; only then try the sequence; otherwise resolve the name.
    # Measured 2026-10-30: aspirin matched the residue pattern (A-S-P-I-R-I-N) and
    # came back as a 7-residue peptide, MW 769.9, instead of C9H8O4.
    # Try the SMILES parse for any ASCII token, not only ones containing c/n/o/s/p/:
    # the narrow test rejected CCO, so "CCO" came back as an unresolved name
    # (measured 2026-10-30). RDKit rejects words like aspirin or ACDEF by itself.
    if re.fullmatch(r"[A-Za-z0-9@+\-\[\]\(\)=#\\$:/%.]+", text):
        try:
            m = molmod.parse_struct(text)
            return {"ok": True, "channel": "smiles",
                    "data": {"input": text, "smiles": molmod.canonical(m),
                             "formula": molmod.formula(m), "inchikey": molmod.inchikey(m)}}
        except molmod.MolError:
            pass
    # _lookup_name returns (smiles, name) and a miss is (None, None) -- truthy, so
    # the tuple itself cannot be the test.
    if _lookup_name(text)[0]:
        return _from_name(text, payload)
    if re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY\s\-]{3,}", text.upper()) and " " not in text.strip():
        candidate = _from_seq(text)
        if candidate.get("ok"):
            return candidate
    return _from_name(text, payload)
