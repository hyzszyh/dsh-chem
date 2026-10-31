"""chem_enum: every structure a scaffold implies, listed instead of imagined.

  variant  -- one scaffold, many substituents (teaching sets, derivative tables)
  library  -- two or three attachment points, cartesian product
  stereo   -- every stereoisomer, with the cap enforced rather than silent
  tautomer -- the tautomer set RDKit's own enumerator produces
"""
from __future__ import annotations

import itertools

from . import mol as molmod

MAX_OUTPUT = 200


def _cap(rows, limit=MAX_OUTPUT):
    truncated = len(rows) > limit
    return rows[:limit], truncated


def _replace_dummy(scaffold, substituent, map_index=1):
    """Attach one fragment at one labelled dummy, keeping the rest intact."""
    from rdkit import Chem
    core = Chem.MolFromSmiles(scaffold)
    if core is None:
        raise molmod.MolError("bad-scaffold", "骨架 SMILES 解析不了：" + scaffold)
    frag = Chem.MolFromSmiles(substituent)
    if frag is None:
        raise molmod.MolError("bad-substituent", "取代基 SMILES 解析不了：" + substituent)
    # [#0:n] is "the dummy atom", whereas [*:n] is a query for *any* atom, which
    # matched all seven atoms of benzene and attached the fragment to a carbon.
    matches = core.GetSubstructMatches(Chem.MolFromSmarts("[#0:%d]" % map_index))
    if not matches:
        raise molmod.MolError("no-dummy",
                              "骨架里没有 [*:%d] 标记" % map_index,
                              "用 [*:1] / [*:2] 标出连接点")
    dummy = core.GetAtomWithIdx(matches[0][0])
    if not dummy.GetNeighbors():
        raise molmod.MolError("lone-dummy", "骨架里的 [*:%d] 没有连接任何原子" % map_index)
    # ReplaceSubstructs does the surgery RDKit already knows how to do: hand it the
    # dummy, the fragment, and replacementConnectionPoint=0 so the fragment's first
    # atom takes the dummy's place on the parent. Hand-rolled RemoveAtom+AddBond
    # left aromatic flags pointing at atoms that were no longer in a ring.
    pattern = Chem.MolFromSmarts("[#0:%d]" % map_index)
    replaced = Chem.ReplaceSubstructs(core, pattern, frag, replacementConnectionPoint=0,
                                      replaceAll=False)
    if not replaced:
        raise molmod.MolError("replace-failed", "连接失败：[*:%d] + %s" % (map_index, substituent))
    out = replaced[0]
    if out is None:
        raise molmod.MolError("replace-null", "替换产物为空：[*:%d] + %s" % (map_index, substituent))
    Chem.SanitizeMol(out)
    return out


def handle(payload):
    from rdkit import Chem

    mode = (payload.get("mode") or "variant").strip().lower()

    if mode in ("variant", "library"):
        scaffold = payload.get("scaffold") or ""
        if not scaffold:
            return {"ok": False, "failure": {"code": "missing-input", "message": "需要 scaffold（带 [*:1] 标记）"}}
        if "[*" not in scaffold:
            return {"ok": False, "failure": {"code": "no-attachment",
                                            "message": "骨架里没有 [*:n] 连接点标记",
                                            "hint": "例：c1ccc([*:1])cc1"}}

        def split(text):
            if isinstance(text, list):
                return [str(t) for t in text if str(t).strip()]
            return [s.strip() for s in str(text or "").replace("\n", ",").split(",") if s.strip()]

        groups = [split(payload.get("substituents")),
                  split(payload.get("substituents2")),
                  split(payload.get("substituents3"))]
        if not groups[0]:
            return {"ok": False, "failure": {"code": "missing-input", "message": "需要 substituents"}}
        slots = len([g for g in groups if g]) or 1

        rows, failures = [], []
        combos = list(itertools.product(*[g for g in groups if g]))
        for combo in combos:
            try:
                current = scaffold
                for index, substituent in enumerate(combo, start=1):
                    current = Chem.MolToSmiles(_replace_dummy(current, substituent, index))
                m = molmod.parse_struct(current)
                rows.append({"smiles": molmod.canonical(m), "formula": molmod.formula(m),
                             "inchikey": molmod.inchikey(m),
                             "substituents": list(combo)})
            except molmod.MolError as exc:
                failures.append({"substituents": list(combo), "error": exc.message})
            except Exception as exc:  # noqa: BLE001
                failures.append({"substituents": list(combo), "error": str(exc)[:120]})
        unique, seen = [], set()
        for row in rows:
            if row["inchikey"] in seen:
                continue
            seen.add(row["inchikey"])
            unique.append(row)
        kept, truncated = _cap(unique)
        return {"ok": True, "channel": "rdkit",
                "data": {"mode": mode, "scaffold": scaffold, "slots": slots,
                         "requested": len(combos), "produced": len(unique),
                         "duplicates_removed": len(rows) - len(unique),
                         "truncated": truncated, "structures": kept,
                         "failures": failures[:20]},
                "warnings": (["%d 个组合失败" % len(failures)] if failures else [])
                            + (["结果截断到 %d 条" % MAX_OUTPUT] if truncated else [])}

    if mode == "stereo":
        text = payload.get("smiles") or ""
        if not text:
            return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles"}}
        from rdkit.Chem.EnumerateStereoisomers import (EnumerateStereoisomers,
                                                       StereoEnumerationOptions)
        m = molmod.parse_struct(text)
        limit = int(payload.get("max") or MAX_OUTPUT)
        options = StereoEnumerationOptions(unique=True, maxIsomers=limit,
                                           onlyUnassigned=bool(payload.get("onlyUnassigned")))
        isomers, failures = [], []
        for isomer in EnumerateStereoisomers(m, options):
            try:
                isomers.append({"smiles": Chem.MolToSmiles(isomer),
                                "inchikey": molmod.inchikey(isomer),
                                "formula": molmod.formula(isomer)})
            except Exception as exc:  # noqa: BLE001
                failures.append(str(exc)[:100])
        return {"ok": True, "channel": "rdkit",
                "data": {"mode": "stereo", "input": text, "count": len(isomers),
                         "max": limit, "isomers": isomers, "failures": failures},
                "warnings": (["达到上限 %d，可能还有更多异构体" % limit]
                             if len(isomers) >= limit else [])}

    if mode == "tautomer":
        text = payload.get("smiles") or ""
        if not text:
            return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles"}}
        from rdkit.Chem.MolStandardize import rdMolStandardize
        m = molmod.parse_struct(text)
        enumerator = rdMolStandardize.TautomerEnumerator()
        found, failures = [], []
        for tautomer in enumerator.Enumerate(m):
            try:
                found.append({"smiles": Chem.MolToSmiles(tautomer),
                              "inchikey": molmod.inchikey(tautomer),
                              "formula": molmod.formula(tautomer)})
            except Exception as exc:  # noqa: BLE001
                failures.append(str(exc)[:100])
        kept, truncated = _cap(found)
        return {"ok": True, "channel": "rdkit",
                "data": {"mode": "tautomer", "input": text, "count": len(found),
                         "truncated": truncated, "tautomers": kept, "failures": failures}}

    return {"ok": False, "failure": {"code": "unknown-mode", "message": "不认识的 mode：" + mode,
                                    "hint": "variant | library | stereo | tautomer"}}
