"""chem_calc: the arithmetic a chemist actually does at the bench.

stoich -- balance a reaction from element counts alone (no atom mapping needed),
          then turn one mmol into masses, mmol and theoretical yield.
hrms   -- exact-mass text for a characterization section, with adducts.
plate  -- a dilution series and a 96/384-well map you can hand to a robot.

Balance is solved, not assumed: the element-count matrix is row-reduced over
rationals, and the single positive null vector is scaled to smallest integers.
An unbalanced equation therefore comes back with the missing elements listed
instead of a wrong "1:1" pretend.
"""
from __future__ import annotations

import re
from fractions import Fraction
from math import gcd

from . import mol as molmod

PROTON = 1.007276
SODIUM = 22.989218
POTASSIUM = 38.963158
FORMULA_RE = re.compile(r"([A-Z][a-z]?)(\d*)")


def _chem():
    from rdkit import Chem
    return Chem


def formula_counts(formula):
    counts = {}
    for symbol, number in FORMULA_RE.findall(formula or ""):
        counts[symbol] = counts.get(symbol, 0) + (int(number) if number else 1)
    return counts


def _lcm(a, b):
    return a * b // gcd(a, b)


def _rref(matrix):
    rows = [list(map(Fraction, row)) for row in matrix]
    if not rows:
        return rows, []
    ncols = len(rows[0])
    pivot_cols = []
    r = 0
    for c in range(ncols):
        pivot = None
        for i in range(r, len(rows)):
            if rows[i][c] != 0:
                pivot = i
                break
        if pivot is None:
            continue
        rows[r], rows[pivot] = rows[pivot], rows[r]
        lead = rows[r][c]
        rows[r] = [v / lead for v in rows[r]]
        for i in range(len(rows)):
            if i != r and rows[i][c] != 0:
                factor = rows[i][c]
                rows[i] = [a - factor * b for a, b in zip(rows[i], rows[r])]
        pivot_cols.append(c)
        r += 1
        if r == len(rows):
            break
    return rows, pivot_cols


def nullspace(matrix, ncols):
    rows, pivots = _rref(matrix)
    free = [c for c in range(ncols) if c not in pivots]
    basis = []
    for f in free:
        vec = [Fraction(0)] * ncols
        vec[f] = Fraction(1)
        for i, pc in enumerate(pivots):
            vec[pc] = -rows[i][f]
        basis.append(vec)
    return basis


def balance(reactants, products):
    """Return (coeffs, None) or (None, reason). coeffs cover reactants+products."""
    mols = []
    for text in list(reactants) + list(products):
        try:
            mols.append(molmod.parse_struct(text))
        except molmod.MolError as exc:
            return None, {"code": exc.code, "message": exc.message, "species": text}
    counts = [formula_counts(molmod.formula(m)) for m in mols]
    elements = sorted({e for c in counts for e in c})
    n_reactants = len(reactants)
    matrix = []
    for element in elements:
        # Products enter with a negative sign: the nullspace then IS the
        # balanced equation, and a mixed-sign vector means "cannot balance".
        matrix.append([counts[i].get(element, 0) * (1 if i < n_reactants else -1)
                       for i in range(len(counts))])
    basis = nullspace(matrix, len(mols))
    if not basis:
        left, right = {}, {}
        for element in elements:
            left[element] = sum(counts[i].get(element, 0) for i in range(len(reactants)))
            right[element] = sum(counts[i].get(element, 0) for i in range(len(reactants), len(counts)))
        diff = {e: left[e] - right[e] for e in elements if left[e] != right[e]}
        return None, {"code": "no-solution",
                      "message": "配不平，元素差：" + ", ".join("%s %+d" % (e, d) for e, d in sorted(diff.items())),
                      "left": left, "right": right, "diff": diff}
    if len(basis) > 1:
        return None, {"code": "ambiguous", "message": "存在多个线性无关的解，无法唯一配平"}
    vec = basis[0]
    if all(v <= 0 for v in vec):
        vec = [-v for v in vec]
    if not all(v > 0 for v in vec):
        left, right = {}, {}
        for element in elements:
            sign = 1 if element else 1
            left[element] = sum(counts[i].get(element, 0) for i in range(len(reactants)))
            right[element] = sum(counts[i].get(element, 0) for i in range(len(reactants), len(counts)))
            del sign
        diff = {e: left[e] - right[e] for e in elements if left[e] != right[e]}
        return None, {"code": "unbalanced",
                      "message": "两边元素不守恒：" + ", ".join(
                          "%s %+d" % (e, d) for e, d in sorted(diff.items())),
                      "left": left, "right": right, "diff": diff}
    denom = 1
    for v in vec:
        denom = _lcm(denom, v.denominator)
    ints = [int(v * denom) for v in vec]
    shared = 0
    for v in ints:
        shared = gcd(shared, v)
    if shared > 1:
        ints = [v // shared for v in ints]
    return ints, None


def parse_reaction(text):
    """'A.B>>C.D' or 'A>cond>B' -> (reactants, products, condition)."""
    if ">>" in text:
        left, right = text.split(">>", 1)
        return left, right, None
    parts = text.split(">")
    if len(parts) == 3:
        return parts[0], parts[2], parts[1] or None
    raise ValueError("反应式需要 A.B>>C.D 或 A>条件>B 的形式")


def handle(payload):
    kind = (payload.get("kind") or "stoich").strip().lower()
    if kind == "stoich":
        return _stoich(payload)
    if kind == "hrms":
        return _hrms(payload)
    if kind == "plate":
        return _plate(payload)
    return {"ok": False, "failure": {"code": "unknown-kind", "message": "不认识的 kind：" + kind,
                                    "hint": "stoich | hrms | plate"}}


def _stoich(payload):
    from rdkit.Chem import Descriptors
    text = payload.get("reaction") or ""
    try:
        left, right, condition = parse_reaction(text)
    except ValueError as exc:
        return {"ok": False, "failure": {"code": "bad-reaction", "message": str(exc)}}
    reactants = [s for s in re.split(r"[.\s]+", left) if s]
    products = [s for s in re.split(r"[.\s]+", right) if s]
    if not reactants or not products:
        return {"ok": False, "failure": {"code": "bad-reaction", "message": "反应物或产物为空"}}

    coeffs, problem = balance(reactants, products)
    scale = float(payload.get("scaleMmol") or 1.0)
    yield_percent = payload.get("yieldPercent")

    rows = []
    total_mass = 0.0
    if coeffs:
        first = coeffs[0]
        for i, text_s in enumerate(reactants):
            m = molmod.parse_struct(text_s)
            mw = Descriptors.MolWt(m)
            mmol = scale * coeffs[i] / first
            mass = mw * mmol
            total_mass += mass
            rows.append({"role": "reactant", "smiles": molmod.canonical(m),
                         "formula": molmod.formula(m), "coefficient": coeffs[i],
                         "mmol": round(mmol, 4), "mg": round(mass, 3), "mw": round(mw, 4)})
        for j, text_p in enumerate(products):
            m = molmod.parse_struct(text_p)
            mw = Descriptors.MolWt(m)
            mmol = scale * coeffs[len(reactants) + j] / first
            mass = mw * mmol
            rows.append({"role": "product", "smiles": molmod.canonical(m),
                         "formula": molmod.formula(m), "coefficient": coeffs[len(reactants) + j],
                         "mmol": round(mmol, 4), "mg": round(mass, 3), "mw": round(mw, 4),
                         "theoretical_mg": round(mass, 3)})
    data = {"balanced": bool(coeffs), "coefficients": coeffs, "condition": condition,
            "basis_mmol": scale, "rows": rows,
            "mass_balance_mg": round(total_mass, 3)}
    if yield_percent:
        data["yield_percent"] = float(yield_percent)
        if coeffs:
            # Yield belongs to the first product the user wrote, not to whatever
            # happened to land last in the list (usually water).
            first_product = rows[len(reactants)]
            data["yield_basis"] = "first product written"
            data["actual_mg"] = round(first_product["theoretical_mg"] * float(yield_percent) / 100.0, 3)
    if problem:
        data["problem"] = problem
    return {"ok": True, "channel": "pure-python", "data": data,
            "evidence": {"method": "rational nullspace of the element-count matrix"}}


def _hrms(payload):
    from rdkit.Chem import Descriptors
    text = payload.get("smiles") or payload.get("reaction") or ""
    try:
        m = molmod.parse_struct(text)
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message, "hint": exc.hint}}
    exact = Descriptors.ExactMolWt(m)
    formula = molmod.formula(m)
    charge = _chem().GetFormalCharge(m)
    adducts = []
    for label, delta, mode in (("[M+H]+", PROTON, "pos"), ("[M+Na]+", SODIUM, "pos"),
                               ("[M+K]+", POTASSIUM, "pos"), ("[M-H]-", -PROTON, "neg")):
        mz = exact + delta
        adducts.append({"adduct": label, "mz": round(mz, 4), "mode": mode})
    base = adducts[0]
    calcd = "%.4f" % base["mz"]
    return {"ok": True, "channel": "pure-python",
            "data": {"canonical_smiles": molmod.canonical(m), "formula": formula,
                     "exact_mass": round(exact, 6), "formal_charge": charge,
                     "adducts": adducts,
                     "text": "HRMS (ESI) m/z calcd for %s [M+H]+ %s, found ___" % (formula, calcd)},
            "evidence": {"proton": PROTON, "definition": "ExactMolWt + adduct mass"}}


def _plate(payload):
    start = float(payload.get("startConc") or 100.0)
    factor = float(payload.get("dilution") or 2.0)
    count = int(payload.get("count") or 8)
    replicates = int(payload.get("replicates") or 1)
    volume = float(payload.get("volumeUl") or 100.0)
    if factor <= 1:
        return {"ok": False, "failure": {"code": "bad-dilution", "message": "稀释倍数必须大于 1"}}
    series = []
    conc = start
    for i in range(count):
        series.append({"step": i + 1, "conc": round(conc, 4),
                       "transferUl": round(volume / factor, 2) if i else None})
        conc /= factor
    wells = []
    row_letters = "ABCDEFGH"
    for i in range(count):
        for rep in range(replicates):
            well = "%s%d" % (row_letters[i % 8], (i // 8) * replicates + rep + 1)
            wells.append({"well": well, "conc": series[i]["conc"], "volumeUl": volume})
    return {"ok": True, "channel": "pure-python",
            "data": {"series": series, "wells": wells, "well_count": len(wells),
                     "dilution": factor, "volumeUl": volume},
            "evidence": {"rule": "each step transfers volume/factor into an equal volume"}}
