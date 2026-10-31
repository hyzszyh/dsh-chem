"""chem_table: many molecules at once, plus the plates they came from.

matrix -- a list of structures -> a descriptor table -> optional CSV, with a
          small filter language so "MW<250 and HBD<=2" is a request, not a script.
clean  -- standardize a list, drop duplicates by InChIKey, report what went.
fit    -- four-parameter logistic fit for a dose-response curve (IC50/EC50).
"""
from __future__ import annotations

import csv
import io
import re

from . import clean as cleanmod
from . import mol as molmod
from . import props as propsmod


def _split_list(text):
    return [s for s in re.split(r"[\n,;]+", str(text or "")) if s.strip()]


FIELD_ALIASES = {
    "mw": "mw", "mass": "mw", "logp": "logp", "tpsa": "tpsa",
    "hbd": "hbd", "hba": "hba", "rot": "rotatable_bonds",
    "rotatable": "rotatable_bonds", "rings": "rings", "qed": "qed",
    "heavy": "heavy_atoms", "charge": "formal_charge", "fsp3": "fraction_csp3",
}

CLAUSE = re.compile(r"^\s*([A-Za-z_]+)\s*(<=|>=|==|<|>)\s*([-+]?\d*\.?\d+)\s*$")


def _compare(value, op, threshold):
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    return abs(value - threshold) < 1e-9


def _apply_filter(row, expression):
    if not expression:
        return True
    text = expression.replace("&&", " and ").replace("||", " or ")
    for group in re.split(r"\s+or\s+", text):
        clauses = re.split(r"\s+and\s+", group)
        ok = True
        for clause in clauses:
            match = CLAUSE.match(clause)
            if not match:
                return False
            name, op, raw = match.groups()
            key = FIELD_ALIASES.get(name.lower(), name.lower())
            if key not in row or row[key] is None:
                return False
            if not _compare(float(row[key]), op, float(raw)):
                ok = False
                break
        if ok:
            return True
    return False


def _matrix(payload):
    items = _split_list(payload.get("smilesList") or payload.get("smiles") or "")
    if not items:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smilesList"}}
    wanted = [f.strip() for f in str(payload.get("fields") or "").split(",") if f.strip()]
    rows, invalid = [], []
    for i, text in enumerate(items):
        try:
            m = molmod.parse_struct(text)
        except molmod.MolError as exc:
            invalid.append({"index": i, "input": text, "code": exc.code})
            continue
        values = propsmod._compute(m)
        row = {"index": i, "input": text}
        row.update(values)
        if wanted:
            row = {k: row[k] for k in ["index", "input"] + [w for w in wanted if w in row]}
        rows.append(row)

    expression = payload.get("filter")
    if expression:
        rows = [r for r in rows if _apply_filter(r, expression)]

    sort_key = payload.get("sort")
    if sort_key and rows and sort_key in rows[0]:
        rows.sort(key=lambda r: r.get(sort_key) or 0)

    out_path = payload.get("out")
    if out_path:
        buffer = io.StringIO()
        if rows:
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
            with open(out_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(buffer.getvalue())
    return {"ok": True, "channel": "rdkit+pandas",
            "data": {"count": len(rows), "invalid": invalid, "filter": expression or None,
                     "rows": rows, "csv": out_path or None},
            "evidence": {"descriptors": "same code path as chem_props"}}


def _clean(payload):
    items = _split_list(payload.get("smilesList") or payload.get("smiles") or "")
    if not items:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smilesList"}}
    kept, removed, seen = [], [], {}
    for i, text in enumerate(items):
        try:
            m = molmod.parse_struct(text)
        except molmod.MolError as exc:
            removed.append({"index": i, "input": text, "reason": exc.code})
            continue
        fixed, steps = cleanmod._fix(m)
        key = molmod.inchikey(fixed) or molmod.canonical(fixed)
        if key in seen:
            removed.append({"index": i, "input": text, "reason": "duplicate",
                            "same_as": seen[key], "canonical": molmod.canonical(fixed)})
            continue
        seen[key] = i
        kept.append({"index": i, "smiles": molmod.canonical(fixed),
                     "inchikey": molmod.inchikey(fixed), "formula": molmod.formula(fixed),
                     "steps": steps})
    return {"ok": True, "channel": "rdkit",
            "data": {"kept": kept, "removed": removed,
                     "kept_count": len(kept), "removed_count": len(removed)},
            "evidence": {"dedupe": "InChIKey of the standardized structure"}}


def _four_pl(x, bottom, top, ic50, hill):
    return bottom + (top - bottom) / (1.0 + (x / ic50) ** hill)


def _fit(payload):
    from scipy.optimize import curve_fit
    xs = payload.get("x") or payload.get("concentrations")
    ys = payload.get("y") or payload.get("responses")
    if not xs or not ys:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 x 与 y 两组数"}}
    try:
        xs = [float(v) for v in xs]
        ys = [float(v) for v in ys]
    except (TypeError, ValueError):
        return {"ok": False, "failure": {"code": "bad-numbers", "message": "x/y 必须是数字"}}
    if len(xs) != len(ys) or len(xs) < 4:
        return {"ok": False, "failure": {"code": "not-enough-points",
                                        "message": "至少 4 个点，且 x 与 y 等长"}}
    if min(xs) <= 0:
        return {"ok": False, "failure": {"code": "non-positive-x",
                                        "message": "浓度必须为正数（4PL 里会取对数）"}}
    import statistics
    guess = [min(ys), max(ys), statistics.geometric_mean(xs), 1.0]
    try:
        params, _ = curve_fit(_four_pl, xs, ys, p0=guess, maxfev=20000)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "failure": {"code": "fit-failed", "message": str(exc)[:200]}}
    bottom, top, ic50, hill = [float(v) for v in params]
    predicted = [_four_pl(x, bottom, top, ic50, hill) for x in xs]
    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, predicted))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return {"ok": True, "channel": "scipy",
            "data": {"ic50": round(ic50, 6), "bottom": round(bottom, 4), "top": round(top, 4),
                     "hill": round(hill, 4), "r2": round(r2, 6), "points": len(xs),
                     "predicted": [round(p, 4) for p in predicted]},
            "evidence": {"model": "4-parameter logistic, scipy.optimize.curve_fit"}}


def handle(payload):
    action = (payload.get("action") or "matrix").strip().lower()
    if action == "matrix":
        return _matrix(payload)
    if action == "clean":
        return _clean(payload)
    if action == "fit":
        return _fit(payload)
    return {"ok": False, "failure": {"code": "unknown-action", "message": "不认识的 action：" + action,
                                    "hint": "matrix | clean | fit"}}
