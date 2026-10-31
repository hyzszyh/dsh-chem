r"""Assertions for chem_exam: every kind of wrong answer gets its own verdict."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import exam  # noqa: E402

results = []
TMP = Path(tempfile.mkdtemp(prefix="dsh-chem-exam-"))


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


def verdict_of(answer, submission):
    graded = exam.handle({"answer": answer, "submissions": submission})
    if not graded.get("ok"):
        return graded.get("failure", {}).get("code")
    return graded["data"]["results"][0]["verdict"]


check("identical is correct", verdict_of("CCO", "CCO") == "correct")
check("different spelling is correct", verdict_of("OCC", "CCO") == "correct")
check("salt form is correct", verdict_of("CC(=O)O", "CC(=O)[O-].[Na+]") == "correct")
check("stereo mismatch detected", verdict_of("CC(Cl)Br", "C[C@H](Cl)Br") == "stereo",
      str(verdict_of("CC(Cl)Br", "C[C@H](Cl)Br")))
check("tautomer detected", verdict_of("CC(=O)C", "C=C(O)C") == "tautomer",
      str(verdict_of("CC(=O)C", "C=C(O)C")))
check("isomer detected", verdict_of("CCO", "COC") == "isomer", str(verdict_of("CCO", "COC")))
check("substituent change detected", verdict_of("CC(=O)Nc1ccc(O)cc1", "CC(=O)Nc1ccc(OC)cc1") == "substituent",
      str(verdict_of("CC(=O)Nc1ccc(O)cc1", "CC(=O)Nc1ccc(OC)cc1")))
check("unrelated molecule is wrong", verdict_of("CC(=O)Nc1ccc(O)cc1", "CCO") == "wrong",
      str(verdict_of("CC(=O)Nc1ccc(O)cc1", "CCO")))
check("garbage is unreadable", verdict_of("CCO", "not-a-structure") == "unreadable")

batch = exam.handle({"answer": "CC(=O)Nc1ccc(O)cc1",
                     "submissions": ["CC(=O)Nc1ccc(O)cc1", "CCO", "not-a-molecule"]})
check("batch count 3", batch["data"]["count"] == 3, str(batch["data"].get("count")))
check("batch score 33.3", batch["data"]["score"] == 33.3, str(batch["data"].get("score")))
check("tally covers all verdicts", set(batch["data"]["tally"]) == set(exam.VERDICTS),
      str(sorted(batch["data"]["tally"])))
check("answer inchikey echoed", batch["data"]["answerInchikey"] == "RZVAJINKPMORJF-UHFFFAOYSA-N",
      batch["data"]["answerInchikey"])

report_path = TMP / "grade.docx"
report = exam.handle({"action": "report", "answer": "CCO", "submissions": ["CCO", "COC"],
                      "out": str(report_path)})
check("report ok", report["ok"] is True, str(report.get("failure")))
check("report written", report_path.is_file())
from docx import Document  # noqa: E402
document = Document(str(report_path))
check("report has table", len(document.tables) == 1)
check("report table rows 3", len(document.tables[0].rows) == 3, str(len(document.tables[0].rows)))

rubric = exam.handle({"action": "rubric"})
check("rubric lists verdicts", "verdicts" in rubric["data"])
check("rubric has 8 verdicts", len(rubric["data"]["verdicts"]) == 8,
      str(len(rubric["data"]["verdicts"])))

missing = exam.handle({"answer": "CCO"})
check("missing submissions rejected", missing["ok"] is False and missing["failure"]["code"] == "missing-input")
bad_answer = exam.handle({"answer": "zzz-not-a-molecule", "submissions": "CCO"})
check("bad answer rejected", bad_answer["ok"] is False and bad_answer["failure"]["code"] == "bad-answer",
      str(bad_answer.get("failure", {}).get("code")))

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_exam: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
