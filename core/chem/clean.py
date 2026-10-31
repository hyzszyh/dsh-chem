"""chem_clean: find the problems, then optionally fix them.

Three actions, one input:
  check  -- report findings with codes and atom indices, change nothing
  fix    -- standardize (cleanup, largest fragment, uncharge, normalize, tautomer)
  filter -- medicinal-chemistry structural alerts (PAINS / BRENK / NIH / ZINC)

The fixes are RDKit's own standardization objects, not a hand-written pipeline:
that is what makes the output match ChEMBL-style curation instead of whatever
this file happened to think was right.
"""
from __future__ import annotations

from . import mol as molmod


def _chem():
    from rdkit import Chem
    return Chem


def _check(m):
    Chem = _chem()
    findings = []

    frags = Chem.GetMolFrags(m)
    if len(frags) > 1:
        findings.append({"code": "disconnected", "severity": "warn",
                         "message": "%d 个断开的片段（盐、溶剂化物或数据错误）" % len(frags),
                         "hint": "如果这是盐，用 action=fix 取最大片段"})

    charge = Chem.GetFormalCharge(m)
    if charge != 0:
        findings.append({"code": "net-charge", "severity": "info",
                         "message": "净电荷 %+d" % charge,
                         "hint": "中性形式通常更适合比较；action=fix 会尝试中和"})

    radicals = sum(a.GetNumRadicalElectrons() for a in m.GetAtoms())
    if radicals:
        findings.append({"code": "radical", "severity": "error",
                         "message": "%d 个未成对电子" % radicals,
                         "hint": "检查是否漏写电荷或氢"})

    if m.GetNumHeavyAtoms() == 0:
        findings.append({"code": "no-heavy-atoms", "severity": "error",
                         "message": "没有任何重原子"})

    unassigned = [idx for idx, label in
                  Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False)
                  if label == "?"]
    if unassigned:
        findings.append({"code": "undefined-stereo", "severity": "warn",
                         "message": "%d 个手性中心未标构型" % len(unassigned),
                         "atoms": unassigned,
                         "hint": "要固定构型就写明 @/@@，否则不要声称拿到了单一对映体"})

    if m.GetNumConformers() and m.GetConformer().Is3D():
        conf = m.GetConformer()
        closest = None
        for a in range(m.GetNumAtoms()):
            for b in range(a + 1, m.GetNumAtoms()):
                d = (conf.GetAtomPosition(a) - conf.GetAtomPosition(b)).Length()
                if closest is None or d < closest[0]:
                    closest = (d, a, b)
        if closest and closest[0] < 0.5:
            findings.append({"code": "atoms-too-close", "severity": "error",
                             "message": "原子 %d 与 %d 相距 %.3f Å" % (closest[1], closest[2], closest[0]),
                             "hint": "三维坐标冲突，多半是格式转换时坐标错位"})

    try:
        Chem.SanitizeMol(Chem.Mol(m))
    except Exception as exc:  # noqa: BLE001 - the message is the finding
        findings.append({"code": "sanitize-failed", "severity": "error",
                         "message": str(exc)[:200]})
    return findings


def _standardizer():
    from rdkit.Chem.MolStandardize import rdMolStandardize as ms
    return ms


def _fix(m):
    ms = _standardizer()
    steps = []
    current = m

    cleaned = ms.Cleanup(current)
    if _chem().MolToSmiles(cleaned) != _chem().MolToSmiles(current):
        steps.append("cleanup")
    current = cleaned

    chooser = ms.LargestFragmentChooser()
    largest = chooser.choose(current)
    if _chem().MolToSmiles(largest) != _chem().MolToSmiles(current):
        steps.append("largest-fragment")
    current = largest

    uncharged = ms.Uncharger().uncharge(current)
    if _chem().MolToSmiles(uncharged) != _chem().MolToSmiles(current):
        steps.append("uncharge")
    current = uncharged

    normalized = ms.Normalizer().normalize(current)
    if _chem().MolToSmiles(normalized) != _chem().MolToSmiles(current):
        steps.append("normalize")
    current = normalized

    tautomer = ms.TautomerEnumerator().Canonicalize(current)
    if _chem().MolToSmiles(tautomer) != _chem().MolToSmiles(current):
        steps.append("canonical-tautomer")
    current = tautomer

    return current, steps


CATALOGS = ("PAINS", "BRENK", "NIH", "ZINC")


def _filter(m):
    from rdkit.Chem import FilterCatalog
    params = FilterCatalog.FilterCatalogParams()
    used = []
    for name in CATALOGS:
        flag = getattr(FilterCatalog.FilterCatalogParams.FilterCatalogs, name)
        params.AddCatalog(flag)
        used.append(name)
    catalog = FilterCatalog.FilterCatalog(params)
    hits = []
    for entry in catalog.GetMatches(m):
        item = {"description": entry.GetDescription()}
        try:
            item["catalog"] = str(entry.GetProp("FilterSet"))
        except Exception:  # noqa: BLE001 - older builds do not expose it
            item["catalog"] = "unknown"
        hits.append(item)
    return hits, used


def handle(payload):
    text = payload.get("smiles") or payload.get("structure") or ""
    action = (payload.get("action") or "check").strip().lower()
    try:
        m = molmod.parse_struct(text)
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message, "hint": exc.hint}}

    before = molmod.canonical(m)

    if action == "check":
        findings = _check(m)
        blocking = [f for f in findings if f["severity"] == "error"]
        return {"ok": True, "channel": "rdkit",
                "data": {"canonical_smiles": before,
                         "formula": molmod.formula(m),
                         "clean": not findings,
                         "findings": findings,
                         "errors": len(blocking), "warnings": len(findings) - len(blocking)}}

    if action == "fix":
        fixed, steps = _fix(m)
        findings = _check(fixed)
        return {"ok": True, "channel": "rdkit",
                "data": {"before": before,
                         "after": molmod.canonical(fixed),
                         "formula_before": molmod.formula(m),
                         "formula_after": molmod.formula(fixed),
                         "steps": steps,
                         "changed": before != molmod.canonical(fixed),
                         "remaining_findings": findings}}

    if action == "filter":
        hits, used = _filter(m)
        return {"ok": True, "channel": "rdkit",
                "data": {"canonical_smiles": before,
                         "catalogs": used,
                         "hits": hits,
                         "flagged": bool(hits)},
                "evidence": {"catalogs": used, "source": "RDKit FilterCatalog"}}

    return {"ok": False, "failure": {"code": "unknown-action",
                                    "message": "不认识的 action：" + action,
                                    "hint": "check | fix | filter"}}
