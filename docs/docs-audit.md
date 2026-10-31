# 文档一致性巡检（t14）

- 范围：巡检开始时的全部 14 份 Markdown（`README.md`、`PROGRESS.md`、`PLAN.md`、`PLAN-v1.md`、`PLAN-v2.md`、`docs/` 8 份 md + `com_item_document.txt`、`dsh-plugin/README.md`）+ 文档里引用的工程文件；本报告自身是第 15 份
- 日期：2026-10-29
- 性质：**只报告，不改文件**。下面每一条都给出「改哪里、改成什么」，由 captain 决定是否执行
- 未跑 ChemDraw / KingDraw（避免留进程），因此少数条目只能标「需实跑」，见附录 E

## 摘要

****P0** · 3**

- **一句话**：同一台机器上同一字段有**两个相反版本的实测记录**；DSH 插件的工具表**漏了一个已注册的工具**；索引自称「不登记等于没交付」却漏掉 2 份文档（其中一份正是 quickstart 的勘误）

****P1** · 13**

- **一句话**：数字全面过期（MCP 12→13、插件 10→11、断言 16→17、依赖 2→3）；README 状态行仍停在 M0；quickstart 完全没有 `cd` 组与 `crosscheck`；PROGRESS/PLAN 里三处「尚未开始／还没写」已被代码推翻

****P2** · 9**

- **一句话**：个人路径出现在示例命令里；表格行数「12 条」实为 13 条；MCP 没有 `chem_doctor`、插件没有 `chemdraw_capabilities` 这类不对称没有任何文档说明


**结论**：命令层面是干净的 —— 48 处文档命令逐条对照 `--help`，**没有不存在的子命令，也没有拼错的选项**；34 条相对链接**零断链**。坏掉的全是「事实层」：数字、状态、以及最要命的一处相反实测记录。

## 检查方法（可复现）

**内部链接**

- **做法**：用脚本抽出全部 `[x](y.md)` 相对链接，按文件所在目录解析后 `stat`
- **结果**：34 条，断链 0

**命令真伪**

- **做法**：`python bin/cli.py {--help,kd --help,doctor --help,cd --help,crosscheck --help,cd draw --help,kd formula --help,kd mol --help,kd king --help,cd export --help,cd figure --help,cd read --help,identity --help}` 的真实输出
- **结果**：48 条文档命令全部命中；0 处拼错

**过期声明**

- **做法**：grep `尚未|仍在|还没|TODO|未实现|待实现|进行中|未落地`
- **结果**：13 处命中，其中 6 处已被代码推翻

**数字一致性**

- **做法**：静态计数：`grep -c "    name: '" dsh-plugin/lib/index.js`、`grep -c "'name': '" core/chemdraw_tool/mcp_server.py`、`grep -c "def test_" test/*.py`、`EXPORTS` 列表长度
- **结果**：插件 11、MCP 13、测试 17/11/11/14/9、导出 12

**字段名**

- **做法**：对照 `models.py:150-161`（`DoctorReport.to_dict`）、`models.py:118-121`（`Result.to_dict`）与文档 JSON 示例
- **结果**：见附录 D，剩 1 处（`version`）


---

## P0 — 照文档做会失败或得出错误结论

**`docs/quickstart.md:113` + `docs/quickstart-verified.md:46,83` vs `PROGRESS.md:18`**

- **问题类型**：过期声明（**相反事实**）
- **现状**：quickstart 写 `"version": ""` 并注明「实测恒为空串：`app.Name` 拿不到版本，别拿它当判据」；quickstart-verified 把它列为 P0 并断言「本机 `app.Name` 返回空串，`version` 永远 `""`」。**但 `PROGRESS.md:18` 记录的真实输出是 `version: ChemDraw Professional 26.1.0.6327`**
- **应该是什么**：三份文档必须收敛到一个事实。代码路径是 `doctor/cd.py:133 report.version = str(getattr(app, 'Name', '') or '')`，而 `cli.py:27-28` **只在非空时才打印** —— 也就是说 PROGRESS 那行能出现，就证明当时 `version` 非空。建议实测一次 `python bin/cli.py doctor cd --json` 定案（见附录 E），再统一：若确实非空，删掉 quickstart 的「恒为空」并改成「`version` 是 `app.Name`，形如 `ChemDraw Professional 26.1.0.6327`，可用它确认版本与实例类型」；若为空，PROGRESS.md:18 那行要加注「已被 2026-10-29 复测推翻」。（按 `docs/index.md:39` 的约定：被推翻的结论要保留原文 + 注明推翻，不能悄悄改）
- **严重度**：**P0**

**`dsh-plugin/README.md:9-20`**

- **问题类型**：数字/清单不一致（**工具表少一行**）
- **现状**：「它做什么」表只列 10 个工具（`chem_doctor`、`chem_identity`、`chemdraw_draw/export/figure/read`、`kingdraw_convert/formula/read_king/open`），**没有 `chem_crosscheck`**
- **应该是什么**：`dsh-plugin/lib/index.js:52` 注册了 `chem_crosscheck`（调 `cli.py crosscheck`，`index.js:61`），共 **11** 个工具。表里补一行：`chem_crosscheck`｜同一分子用 rdkit + KingDraw 两个引擎各算一遍再比，不一致就报警｜只要 rdkit + 32 位运行时
- **严重度**：**P0**

**`docs/index.md:3` vs 实际内容**

- **问题类型**：文档间互相打架（**索引失守**）
- **现状**：索引开头声明「新增文档必须在这张表里登记，否则等于没交付」，但 `docs/` 下 9 份文件里 **`portability-report.md` 与 `quickstart-verified.md` 没有登记**；后者恰恰是「照 quickstart 跑一遍」的勘误报告
- **应该是什么**：补两行。读者按索引读不到 quickstart-verified，就会直接吃 quickstart 里那些**已被勘误**的说法（`version` 那条就是典型）；这是唯一一条「索引缺登记 → 直接导致错误结论」的链路，所以给 P0 而不是 P1
- **严重度**：**P0**


## P1 — 能跑通，但数字/状态已过期

**`README.md:5`**

- **问题类型**：过期声明
- **现状**：「状态：M0 探路完成，M1 通道适配器在写。当前可用的只有一条命令（`doctor`），别当成成品。」
- **应该是什么**：现在 CLI 有 5 个顶层命令、`cd` 组 6 个子命令、`kd` 组 8 个、MCP 13 个工具、插件 11 个工具。`docs/index.md:33` 承认这行旧了，但**承认不等于修**——README 是 GitHub 首屏，这行会让人直接判定「只有 doctor」
- **严重度**：**P1**

**`README.md:26-35`**

- **问题类型**：命令清单缺失
- **现状**：快速开始只给 3 条：`doctor cd`、`doctor kd`、`identity`
- **应该是什么**：缺 `cd draw/export/figure/read/capabilities` 与 `crosscheck`。至少补 `python bin/cli.py cd figure 'CC(=O)Oc1ccccc1C(=O)O' --width-mm 85 --dpi 300 out.png` 与 `python bin/cli.py crosscheck 'c1ccccc1O'`——这两条是项目最像「产品」的动作
- **严重度**：**P1**

**`docs/quickstart.md`（全文）**

- **问题类型**：命令清单缺失
- **现状**：12 步走完只覆盖 `doctor`/`identity`/`kd formula`/自检；**`cd` 子命令组完全缺席**（`docs/quickstart-verified.md:36,90` 已指出），`crosscheck` 也缺席
- **应该是什么**：加一节「画一张图」：`python bin/cli.py cd figure --width-mm 85 --dpi 300 out.png` + `python bin/cli.py crosscheck '<smiles>'`。`--width-mm` / `--dpi` / `--format` 都是真实选项（已核 `cd figure --help`）
- **严重度**：**P1**

**`docs/quickstart.md:203`**

- **问题类型**：数字不一致
- **现状**：「MCP server 已实现（**12 个工具**，stdio JSON-RPC）」
- **2026-10-29 复核**：现在是 **15** 个——`kingdraw_*` 7 个、`chemdraw_*` 6 个（新增了 `chemdraw_modify`），
  加上 `chem_identity` / `chem_crosscheck`。下面这 13 是当时（2026-10）的实测数，保留原文。
- **应该是什么**：实际 **13** 个：`mcp_server.py` 里 13 个 `'name':`（`chem_identity`、`kingdraw_smiles_to_mol/mol_to_smiles/formula/read_king/match/to3d`、`chemdraw_draw/export/figure/read/capabilities`、`chem_crosscheck`）。**没有 `chem_doctor`**（doctor 只在 CLI/插件层）
- **严重度**：**P1**

**`docs/quickstart.md:203`、`dsh-plugin/README.md:64,71`、`PROGRESS.md:270,272,277`**

- **问题类型**：数字不一致
- **现状**：一律写「十个工具 / 10 个工具」
- **应该是什么**：实际 **11**（`dsh-plugin/lib/index.js` 注册 11 个 `name:`）。`PROGRESS.md` 属只追加的历史条目，可在最新条目里更正一句「插件现为 11 个工具（新增 `chem_crosscheck`）」
- **严重度**：**P1**

**`docs/quickstart.md:174-178`、`PROGRESS.md:183`**

- **问题类型**：数字不一致
- **现状**：「ChemDraw 适配器：**16** 项断言」「`16 passed, 0 failed`」
- **应该是什么**：`test/test_cd_adapter.py` 现有 **17** 个 `def test_`（含 `test_13_capabilities_name_the_measured_routes`，`test_cd_adapter.py:327`）。需实跑确认是 17 passed（见附录 E）。`test_kd_adapter.py` 的 14 项 ✓ 仍准确
- **严重度**：**P1**

**`docs/index.md:23`、`README.md:41`**

- **问题类型**：数字不一致（**依赖**）
- **现状**：索引说 requirements 是「`rdkit` + `pywin32`」；README 依赖写「`rdkit`、`pywin32`」
- **应该是什么**：`requirements.txt` 与 `pyproject.toml:12-16` 现在是 **3 项**：`rdkit>=2023.9`、`pillow>=9.0`、`pywin32>=306; sys_platform == "win32"`（Pillow 已按 `PROGRESS.md:320` 补上）
- **严重度**：**P1**

**`docs/quickstart-verified.md:36`**

- **问题类型**：过期声明（**勘误自身过期**）
- **现状**：记录 usage 为 `{doctor,identity,kd,cd}`
- **应该是什么**：现为 `{doctor,identity,kd,crosscheck,cd}`（顶层已加 `crosscheck`）。这份文档是「验过的快照」，要加一句「此后 CLI 又新增 `crosscheck`」
- **严重度**：**P1**

**`docs/quickstart.md:211`**

- **问题类型**：过期声明（**可信度标签失真**）
- **现状**：文末：「命令与字段由独立 QA 按本文件原样实跑核对（含当时 CLI 尚无 `cd` 子命令组、现已补上）」
- **应该是什么**：读者会把它读成「命令与字段都核过了」，但字段层的 `version`（`:113`）仍是错的，`crosscheck` 仍缺席。建议改成「命令层已实跑核对；字段层 5 处不符中已修 4 处，`version` 待复测 —— 详见 quickstart-verified.md」
- **严重度**：**P1**

**`PROGRESS.md:331`**

- **问题类型**：过期声明（**与同文件打架**）
- **现状**：「未验证项…MCP 层与 DSH 插件层（**尚未开始**）」
- **应该是什么**：同文件 `:139` 有「MCP server：7 个工具」、`:270` 有「`dsh-plugin/`… 10 个工具」。三层都已实现，只是端到端未验。应改为「MCP/插件层已实现但端到端未验（见 :277 的未验清单）」
- **严重度**：**P1**

**`PROGRESS.md:322-329`**

- **问题类型**：过期声明
- **现状**：标题「## 进行中：M2 的两块拼图」，下面 4 行任务表（t1/t2/t3/t4）
- **应该是什么**：M2 早已完结，这 4 行是历史状态。建议把标题改成「（已完结）M2 的两块拼图」或在表前加一行「以下为当时状态，已全部完成」
- **严重度**：**P1**

**`PLAN.md:168`**

- **问题类型**：过期声明
- **现状**：「3. **常驻宿主还没写**。现在每次现起 32 位 PowerShell，一次一两秒」
- **应该是什么**：常驻宿主**已写**：`core/chemdraw_tool/kd_worker.py` + `bin/kd_worker.py`，MCP 用 `WORKER = bin/kd_worker.py`（`mcp_server.py:26`）、crosscheck 用 `KD_WORKER`（`crosscheck.py:46`），协议是「64 位主进程 → JSON over pipe → 32 位 worker」（`PROGRESS.md:120-125`）。另外「PowerShell」也已不是当前实现（是 Python worker）
- **严重度**：**P1**

**`PLAN.md:26`**

- **问题类型**：数字不一致
- **现状**：「12 个导出函数可在 32 位宿主调通（**已验 5 个**）」
- **应该是什么**：现为 **12/12**：`doctor/kd.py:15-19` 的 `EXPORTS` 12 项；`docs/quickstart.md:135` 与 `PROGRESS.md:34` 都记 `GRDKitDll exports=12/12`。这行属「本轮实测到的新事实」历史条目，加注「已推进到 12/12」即可
- **严重度**：**P1**



## P2 — 可接受，但会让人多花时间

**`PROGRESS.md:134`**

- **问题类型**：个人路径入示例
- **现状**：`runtime/py32/python.exe bin/cli.py kd king D:/tool/KingDraw/Cyclohexane.king`
- **应该是什么**：换成 `<你的 KingDraw 安装目录>/Cyclohexane.king`，或先说明「路径换成你自己的」。照抄这条命令的人一定失败
- **严重度**：**P2**

**`PLAN.md:24`**

- **问题类型**：个人路径入示例
- **现状**：`"D:\tool\KingDraw\KingDraw.WpfForm.exe" "%1"`（作为注册表实测证据）
- **应该是什么**：这是**证据原文**，保留合理；建议加一句「本机路径，别台机器不同」以免被当成默认值
- **严重度**：**P2**

**`dsh-plugin/README.md:48`**

- **问题类型**：表述含糊
- **现状**：「以及本机开发时用的那个路径」
- **应该是什么**：`lib/config.js:41` 实际写死 `<repo>`。要么写明（让读者知道有个可疑默认值），要么删除该候选
- **严重度**：**P2**

**`docs/index.md:9`**

- **问题类型**：数字不一致
- **现状**：quickstart 一句话说明写「12 条实测错误对照表」
- **应该是什么**：`docs/quickstart.md` §5 实为 **13** 条数据行
- **严重度**：**P2**

**`core/chemdraw_tool/mcp_server.py`（13 工具，无 `chem_doctor`） vs `dsh-plugin/lib/index.js`（11 工具，有 `chem_doctor`、无 `chemdraw_capabilities`）**

- **问题类型**：不对称无说明
- **现状**：两条对外通道的工具集合不同，但没有任何文档解释差异
- **应该是什么**：在 `docs/index.md` 或 README 加一行对照：MCP 13（含 `chemdraw_capabilities`、不含 doctor）/ 插件 11（含 `chem_doctor`、`chem_crosscheck`、`kingdraw_open`，不含 `capabilities`）
- **严重度**：**P2**

**`README.md:28,31`、`docs/quickstart.md:81,84`**

- **问题类型**：隐含假设
- **现状**：全部用裸 `python` / `runtime/py32/python.exe`
- **应该是什么**：文档没提醒「`python` 必须是 64 位」；`quickstart-verified.md:5` 记了本机路径，但正文没有。建议在第一条命令前加「`python -c "import sys;print(sys.maxsize>2**32)"` 应为 True」
- **严重度**：**P2**

**`PLAN-v2.md:71`、`PLAN-v1.md:59,65,191`**

- **问题类型**：存档数字
- **现状**：「注册 14 个工具」「6 个工具 + 1 个自检」「注册 7 个工具」等
- **应该是什么**：两份文件头已标「已被 PLAN.md 取代」的存档，历史数字属正常；无需改，但**别在索引里把它们当现状引用**（`docs/index.md:12` 已正确标注「存档」✓）
- **严重度**：**P2**

**三个不同接口用了三套近义键名**

- **问题类型**：字段命名
- **现状**：doctor 侧：`details.exports_found`（数组）/`exports_expected`（整数）/`exports_missing`（`doctor/kd.py:178-180`）；adapter 侧：`data.exports_bound`（数组）/`data.pointer_bits`（`kd_native.py:313-315`）；文档分别照各自接口写，**单看都对**（`acceptance-m1.md:63` 的 `exports_bound 12/12` 就是 adapter 口径）
- **应该是什么**：建议在 `docs/index.md` 的写文档约定里加一行「引用导出数时注明出自哪个接口（doctor 还是 adapter），两者键名不同」，避免下一个人以为 `exports_bound` 是笔误去「修」它
- **严重度**：**P2**

**`docs/acceptance-m1.md:88`**

- **问题类型**：范围注记
- **现状**：「这一条只证明了『信封 + 不抛』，还没有证明 ChemDraw 自己会拒绝垃圾输入」
- **应该是什么**：这是**主动声明边界**，写法正确，无需改。列在此处只为说明本轮巡检看过它、判定不是问题
- **严重度**：**P2**


---

## 附录 A · 命令真伪全表

`--help` 逐层核对结果：**48 处文档命令全部有效，0 处拼错**。顶层 usage 为 `chem-draw-tool {doctor,identity,kd,crosscheck,cd}`；`cd` 组 `{doctor,draw,export,figure,read,capabilities}`；`kd` 组 `{mol,smiles,formula,king,match,to3d,layout,open}`。

**`README.md:28`**

- **文档里的命令**：`python bin/cli.py doctor cd --json`
- **核对结果**：✓ `doctor` 支持 `{cd,kd,all}` + `--json`

**`README.md:31`**

- **文档里的命令**：`runtime/py32/python.exe bin/cli.py doctor kd --json`
- **核对结果**：✓

**`README.md:34`**

- **文档里的命令**：`python bin/cli.py identity '<smiles>'`
- **核对结果**：✓ 位置参数 `smiles`

**`PROGRESS.md:17,33`**

- **文档里的命令**：同上两条 doctor
- **核对结果**：✓

**`PROGRESS.md:132`**

- **文档里的命令**：`... kd formula --smiles '<smiles>'`
- **核对结果**：✓ `kd formula` 有 `--smiles` / `--mol`

**`PROGRESS.md:133`**

- **文档里的命令**：`... kd mol --smiles c1ccccc1O --out phenol.mol`
- **核对结果**：✓ `kd mol` 有 `smiles` + `--out`

**`PROGRESS.md:134`**

- **文档里的命令**：`... kd king D:/tool/KingDraw/Cyclohexane.king`
- **核对结果**：✓ `kd king` 收位置参数 `path`（路径本身是个人路径，见 P2）

**`PROGRESS.md:251-253`**

- **文档里的命令**：`chemdraw-tool cd draw|export|figure|read|capabilities|doctor`、`chemdraw-tool kd mol|...|open`
- **核对结果**：✓ 与 `pyproject.toml:19`（`chemdraw-tool = "chemdraw_tool.cli:main"`）一致；但裸 `chemdraw-tool` 要求 `pip install -e .` 已执行，文档没提这个前提

**`docs/quickstart.md:64,70`**

- **文档里的命令**：`python scripts/fetch_runtime.py` / `--verify`
- **核对结果**：✓ 脚本存在，`--verify` 存在（`quickstart-verified.md:28` 实跑 rc=1/0）

**`docs/quickstart.md:81,84,97,100`**

- **文档里的命令**：两条 doctor + `identity` + `kd formula`
- **核对结果**：✓

**`docs/quickstart.md:175,178`**

- **文档里的命令**：`runtime/py32/python.exe test/test_kd_adapter.py`、`python test/test_cd_adapter.py`
- **核对结果**：✓ 两文件存在（断言数过期，见 P1）

**`docs/quickstart.md:184,185`**

- **文档里的命令**：`python bin/cli.py --help` / `doctor --help`
- **核对结果**：✓

**`docs/quickstart.md:159`（行内）**

- **文档里的命令**：`runtime/py32/python.exe bin/cli.py doctor kd`
- **核对结果**：✓

**`docs/quickstart-verified.md:28-37`**

- **文档里的命令**：12 步实跑命令
- **核对结果**：✓ 全部有效（含 `doctor all --json`，rc=1 属正确行为，`quickstart.md:188-190` 已说明）

**`docs/quickstart-verified.md:37`**

- **文档里的命令**：`python bin/cli.py doctor all --json`
- **核对结果**：✓ `doctor` 接受 `all`

**`dsh-plugin/README.md:30,35`**

- **文档里的命令**：`dsh plugin --profile desktop add/remove ...`
- **核对结果**：⚠️ DSH 自身命令，不在本仓库校验范围（未核）

**`dsh-plugin/README.md:57`**

- **文档里的命令**：`python scripts/fetch_runtime.py`
- **核对结果**：✓

**`docs/quickstart.md`（缺）**

- **文档里的命令**：无 `cd` / `crosscheck` 任何示例
- **核对结果**：✗ 缺失项，见 P1（**不是**命令写错，是根本没写）


## 附录 B · 链接盘点与索引覆盖

- 相对链接共 **34 条**，其中 `md` 互链 21 条、指向工程文件 13 条；**断链 0**。
- 交叉验证：`docs/index.md` 提到的 `../README.md`、`../PROGRESS.md`、`../PLAN.md`、`../PLAN-v1.md`、`../PLAN-v2.md`、`requirements.txt`、`pyproject.toml`、`LICENSE`、`bin/cli.py`、`scripts/fetch_runtime.py`、`core/chemdraw_tool/artwork.py` 全部存在。
- **索引覆盖缺口**：`docs/` 下现有 10 个文件（本报告写入后为 10：9 份 md + 1 份 txt），索引表格覆盖 6 个（`quickstart`、`com_item_document.txt`、`upstream-com-notes`、`cdxml-minimal`、`journal-artwork`、`acceptance-m1`）+ 自身；**缺 `portability-report.md`、`quickstart-verified.md`**（P0-3），本次新增的 `docs-audit.md` 同样待登记。

| 文档 | 被索引覆盖 | 备注 |
|---|---|---|
| `docs/quickstart.md` | ✓ `index.md:9` | 但索引对它的描述「12 条错误对照表」过期（P2） |
| `docs/com_item_document.txt` | ✓ `index.md:13` | — |
| `docs/upstream-com-notes.md` | ✓ `index.md:14` | — |
| `docs/cdxml-minimal.md` | ✓ `index.md:15` | — |
| `docs/journal-artwork.md` | ✓ `index.md:16` | — |
| `docs/acceptance-m1.md` | ✓ `index.md:17` | — |
| `docs/portability-report.md` | ✗ | 缺登记（P0-3） |
| `docs/quickstart-verified.md` | ✗ | 缺登记（P0-3），且它是 quickstart 的勘误来源 |
| `docs/index.md` | —（自身） | — |

## 附录 C · 数字对账表

**MCP 工具数**

- **文档写的**：12（`quickstart.md:203`）
- **代码/实测**：**13**（`mcp_server.py` 内 13 个 `'name':`，含 `chem_crosscheck`、`chemdraw_capabilities`）
- **判定**：✗

**MCP 工具数（历史）**

- **文档写的**：7（`PROGRESS.md:139` 标题）
- **代码/实测**：同上
- **判定**：✗（历史条目）

**插件工具数**

- **文档写的**：10（`quickstart.md:203`、`dsh-plugin/README.md:64,71`、`PROGRESS.md:270,272,277`）
- **代码/实测**：**11**（`dsh-plugin/lib/index.js` 11 个 `name:`）
- **判定**：✗

**插件工具表行数**

- **文档写的**：10（`dsh-plugin/README.md:9-20`）
- **代码/实测**：11，缺 `chem_crosscheck`
- **判定**：✗ **P0**

**`test_cd_adapter.py` 断言**

- **文档写的**：16（`quickstart.md:177`、`PROGRESS.md:183`）
- **代码/实测**：静态 17 个 `def test_`（需实跑确认 17 passed）
- **判定**：✗

**`test_kd_adapter.py` 断言**

- **文档写的**：14（`quickstart.md:174`、`PROGRESS.md:88`）
- **代码/实测**：14 ✓
- **判定**：✓

**其余测试文件**

- **文档写的**：未在任何文档出现
- **代码/实测**：`test_cd_cli_mcp.py` 11、`test_crosscheck.py` 11、`test_kd_open.py` 9
- **判定**：缺失登记（P2）

**导出数**

- **文档写的**：12/12（`quickstart.md:135`、`PROGRESS.md:34`、`quickstart-verified.md:31`）
- **代码/实测**：`doctor/kd.py:15-19` 的 `EXPORTS` 12 项 ✓
- **判定**：✓

**导出数（历史）**

- **文档写的**：已验 5 个（`PLAN.md:26`）
- **代码/实测**：12/12
- **判定**：✗（历史条目）

**依赖项数**

- **文档写的**：2（`index.md:23`、`README.md:41`）
- **代码/实测**：**3**（`requirements.txt:5,11,15`：rdkit / pillow / pywin32）
- **判定**：✗

**quickstart 错误表**

- **文档写的**：12 条（`index.md:9`）
- **代码/实测**：13 条数据行
- **判定**：✗

**CLI 顶层命令**

- **文档写的**：4（`quickstart-verified.md:36` 记 `{doctor,identity,kd,cd}`）
- **代码/实测**：**5**（另有 `crosscheck`）
- **判定**：✗

**文档份数登记**

- **文档写的**：—
- **代码/实测**：仓库 14 份 md，索引表覆盖 12 份（含 5 份根级）
- **判定**：见附录 B


## 附录 D · 字段名对账（`DoctorReport` / `Result`）

`DoctorReport.to_dict()`（`models.py:150-161`）的真实键：`channel` / `available` / `version` / `home` / `details` / `capabilities` / `failures` / `evidence` / `evidence_note`。
`Result.to_dict()`（`models.py:118-121`）：`ok` / `data` / `failure` / `channel` / `degraded` / `degrade_reason` / `evidence` / `elapsed_ms` / `warnings` / `evidence_note`。

**`quickstart.md:111`**

- **文档写的字段**：`"channel": "chemdraw"`
- **真实键**：`chemdraw`
- **判定**：✓（曾经写成 `cd`，已修）

**`quickstart.md:112`**

- **文档写的字段**：`"available": true`
- **真实键**：✓
- **判定**：✓

**`quickstart.md:113`**

- **文档写的字段**：`"version": ""`
- **真实键**：键存在，**值待定**（与 `PROGRESS.md:18` 冲突）
- **判定**：✗ **P0-1**

**`quickstart.md:114`**

- **文档写的字段**：`"home": ""`，exe 在 `details.fullname`
- **真实键**：✓ `home` 恒空、`fullname` 在 details（`doctor/cd.py:136-140`）
- **判定**：✓（已修）

**`quickstart.md:116-121`**

- **文档写的字段**：`progid` / `fullname` / `attached` / `started_by_us` / `documents_open` / `elapsed_ms`
- **真实键**：全部存在（`doctor/cd.py:129,136-140,146,178`）
- **判定**：✓

**`quickstart.md:133`**

- **文档写的字段**：`"channel": "kingdraw"`
- **真实键**：✓
- **判定**：✓（已修）

**`quickstart.md:135`**

- **文档写的字段**：`version: "GRDKitDll exports=12/12"`
- **真实键**：`doctor/kd.py:236` 逐字一致
- **判定**：✓

**`quickstart.md:137-139`**

- **文档写的字段**：`exports_found` 数组 / `exports_expected` 整数 / `exports_missing` 数组
- **真实键**：✓（`doctor/kd.py:178-180`）
- **判定**：✓（已修）

**`quickstart.md:140`**

- **文档写的字段**：`bind_errors` 出现即绑不上
- **真实键**：`doctor/kd.py:177` 只有绑定时才写该键
- **判定**：✓

**`quickstart.md:147`**

- **文档写的字段**：判定式 `len(exports_found) == exports_expected`
- **真实键**：✓ 正确写法
- **判定**：✓（已修）

**`quickstart-verified.md:33`**

- **文档写的字段**：`data.text: "C9H8O4"`
- **真实键**：`Result.data['text']` ✓
- **判定**：✓

**全部文档**

- **文档写的字段**：未出现 `"success"` / `"returncode"` 等假字段
- **真实键**：—
- **判定**：✓ 无此类错


## 附录 E · 必须实跑才能定案的清单（本轮未跑，避免留进程）

**E1**

- **待定案的事**：`doctor cd --json` 的 `version` 到底是不是空串（P0-1 的根）
- **建议命令**：`python bin/cli.py doctor cd --json`（64 位）
- **判定标准**：看 `version` 与 `details.fullname`；同时记录 `attached`

**E2**

- **待定案的事**：`test_cd_adapter.py` 现在是 17 项还是 16 项
- **建议命令**：`python test/test_cd_adapter.py`
- **判定标准**：末行 `N passed, 0 failed, N total`

**E3**

- **待定案的事**：`crosscheck` 在只装 ChemDraw 的机器上的降级行为
- **建议命令**：`python bin/cli.py crosscheck 'c1ccccc1O' --json`
- **判定标准**：`degraded` / `degrade_reason` 是否如实

**E4**

- **待定案的事**：插件的 11 个工具端到端是否真能调
- **建议命令**：DSH 里调 `chem_doctor` / `chem_crosscheck`
- **判定标准**：见 `dsh-plugin/README.md:71` 自认「未验」

**E5**

- **待定案的事**：`chemdraw-tool` 裸命令是否需要先 `pip install -e .`
- **建议命令**：`chemdraw-tool --help`
- **判定标准**：若报 command not found，则 `PROGRESS.md:251-253` 需加前提


## 附：本轮**确认没问题**的项（省得下一个人重复查）

**相对链接**

- **结论**：34 条，0 断链

**文档命令与 `--help`**

- **结论**：48 处全命中，0 处拼错子命令/选项

**`docs/` 内部链接指向 `../README.md` 等上层文件**

- **结论**：全部解析正确（`../` 相对路径没写错）

**`DoctorReport` 字段名**

- **结论**：除 `version` 一处外，文档示例与 `models.py:150-161` 完全对齐

**`exports_found == exports_expected` 这个历史错**

- **结论**：已在 `quickstart.md:147,149` 修好并加了警告

**`channel` 取值 `cd`/`kd` 的历史错**

- **结论**：已在 `quickstart.md:111,133` 修好

**`home` 字段语义（历史错）**

- **结论**：已在 `quickstart.md:114` 修好

**`PLAN-v1.md` / `PLAN-v2.md` 的存档标注**

- **结论**：`docs/index.md:12` 与两文件自身都写明「存档、已被 PLAN.md 取代」✓
