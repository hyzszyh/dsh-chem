"""chem_spectra: teaching-grade spectrum estimates, labelled with their error bar.

There is no quantum NMR predictor in this runtime, so nothing here pretends to
be one. Proton shifts come from functional-group rules (about +-0.3 ppm),
carbon shifts from hybridisation and neighbourhood (about +-5 ppm, reported as a
range), IR bands from group frequencies with the usual ranges, and MS gives the
exact mass with the common adducts and neutral losses. The useful part is
compare: hand it the peaks a student measured and find out whether the structure
explains them.
"""
from __future__ import annotations

import re

from . import mol as molmod

# name, SMARTS, index of the proton-bearing atom inside the match, shift,
# multiplicity, tolerance. The index matters: marking every atom in a match put
# ethanol's OH and CH3 at the ester O-CH2 shift.
PROTON_RULES = [
    ("羧酸 O-H", "[CX3](=O)[OX2H1]", 1, 12.0, "br s", 0.6),
    ("酚 O-H", "c[OX2H1]", 1, 9.4, "br s", 0.6),
    ("醇 O-H", "[OX2H1;!$(O[CX3]=O);!$(Oc)]", 0, 2.5, "br s", 0.8),
    ("醛 C-H", "[CX3H1](=O)[#6]", 0, 9.8, "s", 0.3),
    ("酰胺 N-H", "[NX3][CX3](=O)", 0, 7.6, "br s", 0.6),
    ("胺 N-H", "[NX3;H1,H2;!$(NC=O)]", 0, 1.8, "br s", 0.8),
    ("芳环 C-H", "[cH]", 0, 7.3, "m", 0.6),
    ("烯 C-H", "[CX3H1]=[#6]", 0, 5.4, "m", 0.4),
    ("炔 C-H", "[CX2H1]#[#6]", 0, 2.0, "s", 0.3),
    ("甲氧基 O-CH3", "[OX2]([CH3])[#6]", 1, 3.8, "s", 0.3),
    ("酯 O-CH2", "[CX3](=O)[OX2][CX4H2]", 2, 4.2, "q", 0.4),
    ("卤代烷 C-F", "[CX4][F]", 0, 4.4, "m", 0.4),
    ("卤代烷 C-Cl", "[CX4][Cl]", 0, 3.6, "m", 0.4),
    ("卤代烷 C-Br", "[CX4][Br]", 0, 3.4, "m", 0.4),
    ("卤代烷 C-I", "[CX4][I]", 0, 3.2, "m", 0.4),
    ("连氧 sp3 C-H", "[CX4][OX2]", 0, 3.6, "m", 0.4),
    ("连氮 sp3 C-H", "[CX4][NX3]", 0, 2.6, "m", 0.4),
    ("羰基 alpha C-H", "[CX4][CX3](=O)", 0, 2.2, "m", 0.4),
    ("芳环苄位 C-H", "[CX4][c]", 0, 2.4, "m", 0.4),
    ("sp3 CH", "[CX4H1]", 0, 1.5, "m", 0.4),
    ("sp3 CH2", "[CX4H2]", 0, 1.3, "m", 0.4),
    ("sp3 CH3", "[CX4H3]", 0, 0.9, "t", 0.4),
]

IR_GROUPS = [
    ("O-H 伸缩", "[OX2H]", "3200-3600", "强、宽", 3200, 3600),
    ("N-H 伸缩", "[NX3;H1,H2]", "3300-3500", "中", 3300, 3500),
    ("C-H (sp) 伸缩", "[CX2H1]", "3250-3330", "强", 3250, 3330),
    ("C-H (sp2) 伸缩", "[CX3H1,CX3H2]=[#6]", "3000-3100", "中", 3000, 3100),
    ("C-H (sp3) 伸缩", "[CX4H1,CX4H2,CX4H3]", "2850-2960", "强", 2850, 2960),
    ("羧酸 C=O", "[CX3](=O)[OX2H1]", "1700-1725", "强", 1700, 1725),
    ("酯 C=O", "[CX3](=O)[OX2][#6]", "1735-1750", "强", 1735, 1750),
    ("酰胺 C=O", "[CX3](=O)[NX3]", "1630-1690", "强", 1630, 1690),
    ("醛 C=O", "[CX3H1](=O)[#6]", "1720-1740", "强", 1720, 1740),
    ("酮 C=O", "[#6][CX3](=O)[#6]", "1705-1725", "强", 1705, 1725),
    ("芳环 C=C", "c1ccccc1", "1450-1600", "中（2-3 条）", 1450, 1600),
    ("C=C 伸缩", "[CX3]=[CX3;!$(C=O)]", "1620-1680", "中", 1620, 1680),
    ("C≡N 伸缩", "[NX1]#[CX2]", "2210-2260", "中", 2210, 2260),
    ("C-O 伸缩", "[OX2][#6]", "1000-1300", "强", 1000, 1300),
    ("N-O (硝基)", "[N+](=O)[O-]", "1500-1560, 1340-1380", "强（两条）", 1340, 1560),
    ("S=O (砜/亚砜)", "[SX3,SX4](=O)", "1030-1070, 1300-1350", "强", 1030, 1350),
    ("C-F", "[CX4][F]", "1000-1400", "强", 1000, 1400),
    ("C-Cl", "[CX4][Cl]", "600-800", "中", 600, 800),
    ("C-Br", "[CX4][Br]", "500-600", "中", 500, 600),
]

LOSSES = [
    ("H2O", "[OX2H1]", 18.0106, "脱水（醇/羧酸）"),
    ("CO2", "[CX3](=O)[OX2H1]", 43.9898, "羧酸脱羧"),
    ("OCH3", "[OX2][CH3]", 31.0184, "甲氧基断裂"),
    ("CO", "[CX3](=O)[#6]", 27.9949, "羰基脱羰"),
    ("NH3", "[NX3;H2,H3;!$(NC=O)]", 17.0265, "胺脱氨"),
    ("C2H4", "[CX4H2][CX4H2]", 28.0313, "烷基断裂（McLafferty 常见）"),
    ("HCl", "[CX4][Cl]", 35.9767, "卤代烷脱 HCl"),
]


def _match_rule(mol, smarts):
    from rdkit import Chem
    pattern = Chem.MolFromSmarts(smarts)
    if pattern is None:
        return []
    return mol.GetSubstructMatches(pattern)


def _proton_environments(mol):
    from rdkit import Chem

    ranks = list(Chem.CanonicalRankAtoms(mol, breakTies=False))
    hits = {}
    for name, smarts, position, shift, multiplicity, tolerance in PROTON_RULES:
        for match in _match_rule(mol, smarts):
            if position >= len(match):
                continue
            # Only the proton-bearing atom in the match takes the shift. Marking
            # every atom in the match put ethanol's OH and CH3 at 4.1 ppm too.
            index = match[position]
            if index in hits:
                continue
            atom = mol.GetAtomWithIdx(index)
            if atom.GetTotalNumHs() == 0:
                continue
            hits[index] = (name, shift, multiplicity, tolerance)

    groups = {}
    for index, (name, shift, multiplicity, tolerance) in hits.items():
        atom = mol.GetAtomWithIdx(index)
        hydrogens = atom.GetTotalNumHs()
        key = (ranks[index], name, round(shift, 1))
        if key in groups:
            groups[key]["integration"] += hydrogens
            continue
        groups[key] = {"environment": name, "shift": shift, "tolerance": tolerance,
                       "integration": hydrogens, "multiplicity": multiplicity,
                       "atoms": 1, "gn": None}
    rows = sorted(groups.values(), key=lambda r: -r["shift"])
    for row in rows:
        total = row["integration"]
        row["signal"] = "%sH %s" % (total, row["multiplicity"])
    return rows


def _carbon_environments(mol):
    from rdkit import Chem

    ranks = list(Chem.CanonicalRankAtoms(mol, breakTies=False))
    seen, rows = {}, []
    for atom in mol.GetAtoms():
        if atom.GetSymbol() != "C":
            continue
        index = atom.GetIdx()
        if ranks[index] in seen:
            seen[ranks[index]]["integration"] += 1
            continue
        aromatic = atom.GetIsAromatic()
        carbonyl = any(bond.GetBondTypeAsDouble() == 2 and
                       bond.GetOtherAtom(atom).GetSymbol() == "O"
                       for bond in atom.GetBonds())
        nitrile = any(bond.GetBondTypeAsDouble() == 3 for bond in atom.GetBonds())
        if carbonyl:
            environment, low, high = "羰基 C", 165.0, 210.0
        elif nitrile:
            environment, low, high = "腈 C", 115.0, 125.0
        elif aromatic:
            environment, low, high = "芳香 C", 110.0, 155.0
        elif atom.GetHybridization() == Chem.HybridizationType.SP2:
            environment, low, high = "烯 C", 100.0, 150.0
        elif atom.GetHybridization() == Chem.HybridizationType.SP:
            environment, low, high = "炔 C", 65.0, 90.0
        else:
            hetero = sum(1 for n in atom.GetNeighbors() if n.GetSymbol() not in ("C", "H"))
            environment = "sp3 C（连杂原子）" if hetero else "sp3 C"
            low, high = (50.0, 80.0) if hetero else (5.0, 50.0)
        row = {"environment": environment, "range": [low, high], "integration": 1,
               "atoms": [index]}
        seen[ranks[index]] = row
        rows.append(row)
    rows.sort(key=lambda r: r["range"][0])
    return rows


def _ir_bands(mol):
    rows = []
    for name, smarts, label, intensity, low, high in IR_GROUPS:
        matches = _match_rule(mol, smarts)
        if matches:
            rows.append({"group": name, "range": label, "intensity": intensity,
                         "count": len(matches), "low": low, "high": high})
    return rows


def _ms(mol, payload):
    from rdkit.Chem import Descriptors, rdMolDescriptors
    from . import calc as calcmod
    exact = rdMolDescriptors.CalcExactMolWt(mol)
    adducts = {}
    for label, delta in (("[M+H]+", calcmod.PROTON), ("[M+Na]+", calcmod.SODIUM),
                         ("[M+K]+", calcmod.POTASSIUM), ("[M+NH4]+", calcmod.PROTON + 17.026549),
                         ("[M-H]-", -calcmod.PROTON)):
        adducts[label] = round(exact + delta, 4)
    losses = []
    for label, smarts, mass, note in LOSSES:
        if _match_rule(mol, smarts):
            losses.append({"loss": label, "mass": round(mass, 4),
                           "fragment": round(exact - mass, 4), "note": note})
    return {"exactMass": round(exact, 6), "molecularWeight": round(Descriptors.MolWt(mol), 3),
            "nominalMass": int(round(exact)), "formula": molmod.formula(mol),
            "adducts": adducts, "expectedLosses": losses}


def _predict(payload):
    smiles = payload.get("smiles") or ""
    if not smiles:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles"}}
    m = molmod.parse_struct(smiles)
    from rdkit.Chem import rdMolDescriptors
    total_h = sum(atom.GetTotalNumHs() for atom in m.GetAtoms())
    protons = _proton_environments(m)
    assigned = sum(row["integration"] for row in protons)
    carbons = _carbon_environments(m)
    data = {"smiles": molmod.canonical(m), "formula": molmod.formula(m),
            "totalHydrogens": total_h, "protonEnvironments": len(protons),
            "protonAssigned": assigned, "nmr1h": protons,
            "carbonEnvironments": len(carbons), "nmr13c": carbons,
            "ir": _ir_bands(m), "ms": _ms(m, payload)}
    warnings = []
    if assigned != total_h:
        warnings.append("有 %d 个氢没有落到规则里（预测表不全）" % (total_h - assigned))
    warnings.append("1H 位移为官能团规则估算（±0.3 ppm），13C 只给区间；不能当计算结果引用")
    return {"ok": True, "channel": "rule-based", "data": data, "warnings": warnings,
            "evidence": {"nmr1h": "functional-group rules, %d rules" % len(PROTON_RULES),
                         "nmr13c": "hybridisation + neighbourhood ranges",
                         "ir": "group frequencies with ranges",
                         "ms": "exact mass + adducts + neutral losses"}}


def _compare(payload):
    smiles = payload.get("smiles") or ""
    peaks = payload.get("peaks") or payload.get("observed") or []
    if isinstance(peaks, str):
        peaks = [p.strip() for p in re.split(r"[,\s]+", peaks) if p.strip()]
    if not smiles or not peaks:
        return {"ok": False, "failure": {"code": "missing-input",
                                        "message": "需要 smiles 和 peaks（观测峰列表）"}}
    predicted = _predict({"smiles": smiles})
    if not predicted.get("ok"):
        return predicted
    tolerance = float(payload.get("tolerance") or 0.3)
    table = predicted["data"]["nmr1h"]
    observed = []
    for peak in peaks:
        try:
            observed.append(float(peak))
        except ValueError:
            continue
    matched, unmatched, missing = [], [], []
    used = set()
    for peak in observed:
        best, best_delta = None, None
        for index, row in enumerate(table):
            delta = abs(row["shift"] - peak)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                best, best_delta = index, delta
        if best is None:
            unmatched.append({"peak": peak, "reason": "预测表里 %.1f ppm 附近没有信号" % peak})
        else:
            used.add(best)
            matched.append({"peak": peak, "predicted": table[best]["shift"],
                            "delta": round(best_delta, 3),
                            "environment": table[best]["environment"],
                            "integration": table[best]["integration"]})
    for index, row in enumerate(table):
        if index not in used:
            missing.append({"predicted": row["shift"], "environment": row["environment"],
                            "integration": row["integration"]})
    coverage = round(len(matched) / max(1, len(table)), 3)
    return {"ok": True, "channel": "rule-based", "data": {
        "smiles": predicted["data"]["smiles"], "tolerance": tolerance,
        "observed": len(observed), "predictedSignals": len(table),
        "matched": matched, "unmatchedPeaks": unmatched, "unexplainedSignals": missing,
        "coverage": coverage},
        "warnings": (["有 %d 个观测峰没有对应信号，结构可能不对或溶剂峰" % len(unmatched)]
                     if unmatched else []),
        "evidence": predicted["evidence"]}


def handle(payload):
    action = (payload.get("action") or "predict").strip().lower()
    if action in ("predict", "table", "all"):
        return _predict(payload)
    if action in ("compare", "match"):
        return _compare(payload)
    if action == "ir":
        m = molmod.parse_struct(payload.get("smiles") or "")
        return {"ok": True, "channel": "rule-based",
                "data": {"smiles": molmod.canonical(m), "bands": _ir_bands(m)}}
    if action == "ms":
        m = molmod.parse_struct(payload.get("smiles") or "")
        return {"ok": True, "channel": "rule-based", "data": _ms(m, payload)}
    return {"ok": False, "failure": {"code": "unknown-action", "message": "不认识的 action：" + action,
                                    "hint": "predict | compare | ir | ms"}}
