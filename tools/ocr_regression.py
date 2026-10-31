"""Does the OCR install actually read structures? Answer with numbers, not vibes.

Every molecule here is first drawn by ChemDraw through our own pipeline, so the
input pictures have a known answer by construction: whatever the reader returns
must canonicalise to the same InChIKey as the SMILES we drew. A reader that
cannot be imported, cannot be started, or returns something else is reported as
such -- the table is the verdict, not a claim about the table.

Usage:  python tools/ocr_regression.py [--engines molvec,decimer] [--limit 5]
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

MOLECULES = [
    ("阿司匹林", "CC(=O)Oc1ccccc1C(=O)O"),
    ("咖啡因", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"),
    ("布洛芬", "CC(C)Cc1ccc(cc1)C(C)C(=O)O"),
    ("苯佐卡因", "CCOC(=O)c1ccc(N)cc1"),
    ("葡萄糖(开链)", "OCC(O)C(O)C(O)C(O)C=O"),
    ("(S)-布洛芬", "CC(C)Cc1ccc(cc1)[C@@H](C)C(=O)O"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR regression over known drawings")
    parser.add_argument("--engines", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    from chemdraw_tool.v2 import ocr as ocr_mod
    from chemdraw_tool.v2 import tasks

    reports = ocr_mod.engine_reports()
    ready = [name for name, row in reports.items() if row.get("available")]
    wanted = ([row.strip() for row in args.engines.split(",") if row.strip()]
              or ready)
    wanted = [name for name in wanted if name in ready]
    missing = {name: row for name, row in reports.items()
               if name not in ready}
    if not wanted:
        print("no reader is installed; nothing to measure")
        print(json.dumps(missing, indent=2, ensure_ascii=False))
        return 1

    rows = MOLECULES if not args.limit else MOLECULES[:args.limit]
    drawings = []
    for label, smiles in rows:
        started = time.perf_counter()
        payload = tasks.draw(smiles, width_mm=90, dpi=300)
        elapsed = (time.perf_counter() - started) * 1000
        preview = ((payload.get("data") or {}).get("preview") or {})
        path = preview.get("path") or ""
        if not payload.get("ok") or not path or not os.path.exists(path):
            print("could not draw %s: %s" % (label, payload.get("failure")))
            return 2
        drawings.append({"label": label, "smiles": smiles, "path": path,
                         "draw_ms": round(elapsed, 1)})

    started = time.perf_counter()
    outcome = ocr_mod.read_batch([row["path"] for row in drawings], wanted)
    total_ms = round((time.perf_counter() - started) * 1000, 1)

    table = []
    hits = {name: 0 for name in wanted}
    for row in drawings:
        truth = ocr_mod._canonical(row["smiles"])
        image = os.path.basename(row["path"])
        for name in wanted:
            answers = ((outcome["answers"].get(name) or {}).get(image)) or []
            got = ocr_mod._canonical(answers[0]) if answers else {}
            hit = bool(got) and got["inchikey"] == truth["inchikey"]
            hits[name] += 1 if hit else 0
            table.append({"molecule": row["label"], "engine": name,
                          "hit": hit, "got": answers[0] if answers else "",
                          "want": truth["smiles"]})

    print("| 分子 | 引擎 | 判读 | 结果 |")
    print("|---|---|---|---|")
    for item in table:
        mark = "PASS" if item["hit"] else "FAIL"
        got = item["got"] or "(没有输出)"
        print("| %s | %s | %s | `%s` |" % (item["molecule"], item["engine"],
                                            mark, got[:44]))
    print()
    for name in wanted:
        print("%s: %d/%d 命中，合计 %.1f s" % (name, hits[name], len(drawings),
                                              outcome["engine_ms"].get(name, 0) / 1000))
    for note in outcome["notes"][:6]:
        print("note:", note)
    for name, row in missing.items():
        print("unavailable:", name, "-", row.get("reason"))

    payload = {"drawings": drawings, "table": table, "hits": hits,
               "engine_ms": outcome["engine_ms"], "total_ms": total_ms,
               "notes": outcome["notes"], "unavailable": missing}
    target = args.out or os.path.join(ROOT, "test", "out", "ocr_regression.json")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    print("wrote", target)
    worst = min(hits.values()) if hits else 0
    return 0 if worst == len(drawings) else 1


if __name__ == '__main__':
    sys.exit(main())
