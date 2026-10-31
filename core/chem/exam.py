"""chem_exam: mark student structures against an answer key.

Verdicts are graded on structure, not on how the answer was written: the same
molecule typed differently is correct; a wrong stereocentre is its own verdict
because it is a different mistake from a wrong skeleton.
"""
from __future__ import annotations

from pathlib import Path

from . import mol as molmod

VERDICTS = {
    "correct": "正确",
    "stereo": "结构对，立体化学错",
    "tautomer": "互变异构体",
    "isomer": "同分异构但连接方式不同",
    "substituent": "骨架相同，取代基不同",
    "partial": "骨架部分相同",
    "wrong": "结构不对",
    "unreadable": "读不出结构",
}


def _strip_stereo(m):
    from rdkit import Chem
    copy = Chem.Mol(m)
    Chem.RemoveStereochemistry(copy)
    return copy


def _clean_copy(m):
    from rdkit.Chem.MolStandardize import rdMolStandardize
    chooser = rdMolStandardize.LargestFragmentChooser()
    uncharger = rdMolStandardize.Uncharger()
    try:
        return uncharger.uncharge(chooser.choose(m))
    except Exception:  # noqa: BLE001
        return m


def _mcs_ratio(reference, candidate):
    from rdkit.Chem import rdFMCS
    if reference is None or candidate is None:
        return 0.0
    result = rdFMCS.FindMCS([reference, candidate], timeout=2, completeRingsOnly=False,
                            ringMatchesRingOnly=False)
    if not result.numAtoms:
        return 0.0
    # Divided by the LARGER heavy-atom count: dividing by the smaller one gave
    # ethanol a 100% MCS against paracetamol.
    base = max(max(1, reference.GetNumHeavyAtoms()), max(1, candidate.GetNumHeavyAtoms()))
    return result.numAtoms / base


def _classify(answer, candidate):
    from rdkit import Chem
    if answer is None or candidate is None:
        return "unreadable", "结构解析不了"
    if molmod.inchikey(answer) == molmod.inchikey(candidate):
        return "correct", "结构完全一致"
    cleaned_answer, cleaned_candidate = _clean_copy(answer), _clean_copy(candidate)
    if molmod.inchikey(cleaned_answer) == molmod.inchikey(cleaned_candidate):
        return "correct", "去掉盐/酸碱形式后一致"
    if molmod.inchikey(_strip_stereo(answer)) == molmod.inchikey(_strip_stereo(candidate)):
        return "stereo", "骨架一致，手性/双键构型不同"
    from rdkit.Chem.MolStandardize import rdMolStandardize
    enumerator = rdMolStandardize.TautomerEnumerator()
    answer_forms = {molmod.inchikey(t) for t in enumerator.Enumerate(cleaned_answer)}
    candidate_forms = {molmod.inchikey(t) for t in enumerator.Enumerate(cleaned_candidate)}
    if answer_forms & candidate_forms:
        return "tautomer", "互为互变异构体"
    ratio = _mcs_ratio(cleaned_answer, cleaned_candidate)
    same_formula = (molmod.formula(answer) == molmod.formula(candidate)
                    and answer.GetNumHeavyAtoms() == candidate.GetNumHeavyAtoms())
    if same_formula:
        # Same molecular formula, different structure, and neither stereo nor
        # tautomer: that is a constitutional isomer by definition, whatever the
        # MCS overlap is (CCO vs COC only shares two atoms).
        return "isomer", "分子式相同，连接方式不同（共享 %d%% 骨架）" % int(ratio * 100)
    if ratio >= 0.9:
        return "substituent", "骨架相同，取代基不同"
    if ratio >= 0.5:
        return "partial", "共享 %d%% 骨架" % int(ratio * 100)
    return "wrong", "结构不对"


def _resolve(text):
    """A submission may be a SMILES, a name, or a picture path."""
    raw = str(text).strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        from . import parse as parsemod
        found = parsemod.handle({"kind": "image", "source": raw})
        if found.get("ok"):
            return molmod.parse_struct(found["data"]["best"]["smiles"])
        return None
    try:
        return molmod.parse_struct(raw)
    except molmod.MolError:
        from . import parse as parsemod
        found = parsemod.handle({"source": raw})
        if found.get("ok"):
            return molmod.parse_struct(found["data"]["smiles"])
        return None


def _grade(payload):
    answer_text = payload.get("answer") or ""
    if not answer_text:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 answer"}}
    answer = _resolve(answer_text)
    if answer is None:
        return {"ok": False, "failure": {"code": "bad-answer", "message": "标准答案读不出来：" + str(answer_text)[:40]}}
    raw = payload.get("submissions") or ""
    if isinstance(raw, list):
        items = [str(s) for s in raw]
    else:
        items = [s.strip() for s in str(raw).replace(",", "\n").splitlines() if s.strip()]
    if not items:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 submissions"}}
    rows, tally = [], {key: 0 for key in VERDICTS}
    for index, text in enumerate(items, start=1):
        candidate = _resolve(text)
        if candidate is None:
            verdict, reason = "unreadable", "读不出结构"
        else:
            verdict, reason = _classify(answer, candidate)
        tally[verdict] += 1
        rows.append({"index": index, "submission": text, "verdict": verdict,
                     "verdictZh": VERDICTS[verdict], "reason": reason,
                     "smiles": molmod.canonical(candidate) if candidate is not None else None,
                     "inchikey": molmod.inchikey(candidate) if candidate is not None else None})
    score = round(100.0 * tally["correct"] / len(rows), 1)
    return {"ok": True, "channel": "rdkit",
            "data": {"answer": molmod.canonical(answer),
                     "answerInchikey": molmod.inchikey(answer),
                     "count": len(rows), "score": score, "tally": tally, "results": rows}}


def _report(payload):
    graded = _grade(payload)
    if not graded.get("ok"):
        return graded
    out = payload.get("out") or "grading.docx"
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    from docx import Document
    document = Document()
    document.add_heading(payload.get("title") or "结构式批改结果", level=1)
    document.add_paragraph("标准答案：%s（%s）" % (graded["data"]["answer"],
                                                 graded["data"]["answerInchikey"]))
    document.add_paragraph("得分：%.1f 分（正确 %d / 共 %d）"
                           % (graded["data"]["score"], graded["data"]["tally"]["correct"],
                              graded["data"]["count"]))
    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    header = table.rows[0].cells
    for index, text in enumerate(["序号", "学生答案", "判定", "说明"]):
        header[index].text = text
    for row in graded["data"]["results"]:
        cells = table.add_row().cells
        cells[0].text = str(row["index"])
        cells[1].text = row["smiles"] or row["submission"]
        cells[2].text = row["verdictZh"]
        cells[3].text = row["reason"]
    document.save(str(target))
    return {"ok": True, "channel": "python-docx",
            "data": {"path": str(target), "bytes": target.stat().st_size,
                     "score": graded["data"]["score"], "tally": graded["data"]["tally"],
                     "results": graded["data"]["results"]}}


def handle(payload):
    action = (payload.get("action") or "grade").strip().lower()
    if action == "grade":
        return _grade(payload)
    if action in ("report", "docx"):
        return _report(payload)
    if action == "rubric":
        return {"ok": True, "channel": "docs", "data": {"verdicts": VERDICTS,
                                                        "scoring": "correct 计满分，其余 0 分；stereo/tautomer 单独列出便于讲评"}}
    return {"ok": False, "failure": {"code": "unknown-action", "message": "不认识的 action：" + action,
                                    "hint": "grade | report | rubric"}}
