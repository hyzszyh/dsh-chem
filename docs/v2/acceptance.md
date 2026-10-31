# v2 验收记录（需求 §9 的八个剧本）

由 `python tools/acceptance_v2.py` 生成，数字是实测。

判据（需求 §9）：≤3 次调用、0 次打开厂商界面、产物无需返工。

| # | 剧本 | 调用 | 耗时 | 判定 | 实测 |
|---|---|---|---|---|---|
| 1 | 阿司匹林 80 mm | 1 | 1.99 s | PASS | median bond 187.0 px, 65480 bytes, verified… |
| 2 | 8 个分子一张作业图 | 1 | 10.79 s | PASS | 8 items, sheet=contact-sheet-1793290710.png |
| 3 | 体检五价碳 | 1 | 0.49 s | PASS | 2 issues: valence |
| 4 | 酯化投料 10 mmol | 1 | 0.48 s | PASS | ethanol 460.69 mg, error 0.010 mg, 4 rows |
| 5 | 照图读结构 | 2 | 75.50 s | PASS | installed readers: molvec,decimer |
| 6 | 64-19-7 是什么 | 2 | 2.41 s | PASS | CC(=O)O (QTBSBXVTEAMEQO-UHFFFAOYSA-N) |
| 7 | 酯化反应标条件 | 1 | 2.52 s | PASS | scheme drawn, maps created=2,exact=5, capti… |
| 8 | 批 10 份学生结构 | 1 | 0.51 s | PASS | 10 graded: correct,different,stereo,unreada… |

调用次数是 CLI 调用次数，厂商界面全程不可见（§15 三项指标为 0）。
