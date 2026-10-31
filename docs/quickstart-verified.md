# quickstart 实跑核验（t11）

- 角色：从没碰过这个项目的人，严格照 `docs/quickstart.md` 逐条执行
- 时间：2026-10-29 01:09 – 01:16（约 7 分钟）
- 环境：Windows 11 x64；`python` → `%LOCALAPPDATA%\Programs\Python\Python311\python.exe`，`python -V` = **Python 3.11.9**（64 位，win_amd64）；pip 26.1.2
- ChemDraw 26：`C:\Program Files\RevvitySignalsSoftware\ChemDrawApplications_x64\ChemDraw.exe`，ProgID `ChemDraw_x64.Application`
- KingDraw：`D:\tool\KingDraw`（12/12 导出）
- 网络：可用（PyPI 200 / python.org 下载成功）
- 被测快照：把仓库（排除 `runtime/`、`__pycache__`、`test/out`、`.agent-teams`）复制到 `test/out/qs_verify/chem-draw-tool`。
  复制时刻 `core/chemdraw_tool/cli.py` 的 mtime 是 01:08:46，**已含 t8 新增的 `cd` 子命令组**；`docs/quickstart.md` 的 mtime 是 01:07:53。
  也就是说本报告核的是「quickstart 定稿之后、cli.py 又加了一组子命令」这个状态。
- 干净环境复验：另建 `test/out/qs_verify/venv`（无 system-site-packages），只装 `requirements.txt`，用它跑全部 64 位命令（用完已删，安装日志见证据目录）。

## 一句话结论

**命令层面全部跑通，没有硬阻塞**：pip / fetch_runtime / 两条 doctor / identity / kd formula / 两个自检 / help 的退出码与行为都符合预期，
其中最容易出错的两条（**没预先开 ChemDraw 时 `doctor cd` 自动起实例并退出**、**32 位 `doctor kd` 返回 `available: true`**）都实测成立。

**问题集中在「看到什么算成功」这一节的字段名与判定式**：§4 的 5 处逐字不符，其中 `exports_found == exports_expected` 这条判定式在真实 JSON 上**根本不成立**（数组 vs 整数）。
另有一处字段说明错误在 §5（E08 行的 `detail`），以及 CLI 新增 `cd` 组在文档里完全缺席。

## 步骤表

**1 · §3 步1 拿到代码**

- **命令（原样照抄）**：`git clone <仓库地址> chem-draw-tool`
- **实际结果（rc / 耗时 / 关键输出）**：**无法执行**：本目录 `git rev-parse` → `fatal: not a git repository`；文档未给真实仓库地址
- **与文档一致**：部分
- **偏差说明**：占位符 `<仓库地址>` 未填，照抄会失败；文档的回退（"拿到解压目录直接 cd"）可用，本报告即用回退

**2 · §3 步2 装依赖**

- **命令（原样照抄）**：`python -m pip install -r requirements.txt`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，2153 ms；4 行 `Requirement already satisfied`（rdkit 2026.9.1 / pywin32 312 / numpy 2.4.3 / Pillow 12.3.0）
- **与文档一致**：一致
- **偏差说明**：无。另在**全新 venv** 复验：安装依赖清单成功（rdkit-2026.9.1、Pillow-13.0.0、numpy-2.4.6、pywin32-312，rc=0），且 t8 新增的 `cd draw/export/figure/read/capabilities` 在该 venv 下全部 rc=0 —— **依赖清单够用，没有漏新 import**

**3 · §3 步3 看现状**

- **命令（原样照抄）**：`python scripts/fetch_runtime.py --verify`
- **实际结果（rc / 耗时 / 关键输出）**：首次 rc=**1**，输出 `present    : False`；装好后 rc=0，输出 `present: True` + archive + sha256
- **与文档一致**：部分
- **偏差说明**：文档没写这条的预期输出与退出码，读者看到 rc=1 会以为出错（P2）

**4 · §3 步3 取运行时**

- **命令（原样照抄）**：`python scripts/fetch_runtime.py`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，1622 ms；下载 `python-3.11.9-embed-win32.zip` 10,113,050 B，解包到 `runtime/py32/`
- **与文档一致**：一致
- **偏差说明**：无（"约 10 MB" 属实）

**5 · §3 步4 ChemDraw doctor**

- **命令（原样照抄）**：`python bin/cli.py doctor cd --json`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，2531 ms（复跑 2617 ms）；`available: true`、`failures: []`、`started_by_us: true`、`attached: false`、`elapsed_ms: 584`
- **与文档一致**：部分
- **偏差说明**：**自动起实例并退出：成立** —— 执行前 `tasklist` 无 ChemDraw.exe，执行后「立即」与「6 秒后」两次 `tasklist` 都是 0 个进程。但 §4 里的 `channel` / `version` / `home` 三个字段与真实 JSON 不符（见字段表）

**6 · §3 步4 KingDraw doctor**

- **命令（原样照抄）**：`runtime/py32/python.exe bin/cli.py doctor kd --json`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，367 ms；`available: true`、`version: "GRDKitDll exports=12/12"`、`exports_missing: []`、`failures: []`
- **与文档一致**：部分
- **偏差说明**：核心判据成立；但 `details.exports_found` 是**数组**不是整数（见字段表 P0-1）

**7 · §3 顺手验功能**

- **命令（原样照抄）**：`python bin/cli.py identity 'CC(=O)Oc1ccccc1C(=O)O'`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，210 ms；`inchikey: BSYNRYMUTXBXSQ-UHFFFAOYSA-N`、`formula: C9H8O4`
- **与文档一致**：一致
- **偏差说明**：无（文档未列字段，命令可用）

**8 · §3 顺手验功能**

- **命令（原样照抄）**：`runtime/py32/python.exe bin/cli.py kd formula --smiles 'CC(=O)Oc1ccccc1C(=O)O'`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，160 ms；`data.text: "C9H8O4"`
- **与文档一致**：一致
- **偏差说明**：无

**9 · §6 自检**

- **命令（原样照抄）**：`runtime/py32/python.exe test/test_kd_adapter.py`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，183 ms；`14 passed, 0 failed, 14 total`
- **与文档一致**：一致
- **偏差说明**：无（文档写"14 项断言"）

**10 · §6 自检**

- **命令（原样照抄）**：`python test/test_cd_adapter.py`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0，11 691 ms；`16 passed, 0 failed, 16 total`
- **与文档一致**：一致
- **偏差说明**：无（文档写"16 项断言"）

**11 · §6 看命令**

- **命令（原样照抄）**：`python bin/cli.py --help` / `doctor --help`
- **实际结果（rc / 耗时 / 关键输出）**：rc=0；usage 为 `{doctor,identity,kd,cd}`；新增 `cd` 组含 draw/export/figure/read/capabilities
- **与文档一致**：**不一致**
- **偏差说明**：quickstart 全文没有 `cd` 组；文末"命令均对照 --help 真实输出核过"因此已过期（P1-2）

**12 · §6 注**

- **命令（原样照抄）**：`python bin/cli.py doctor all --json`（64 位）
- **实际结果（rc / 耗时 / 关键输出）**：rc=**1**，1864 ms；chemdraw `available: true`，kingdraw `E04`
- **与文档一致**：一致
- **偏差说明**：文档说的"kd 那一半必然 E04"成立；但没提 **rc=1**，脚本里会被当成失败（P2）


进程卫生：以上 12 步跑完，`tasklist /FI "IMAGENAME eq ChemDraw.exe"` 为空；attach 场景另行验证（见下）。全程未出现 UTF-8 / 中文路径报错。

## §4 字段逐字核对（这一节问题最多）

**L99 `"channel": "cd"`**

- **真实 JSON**：`"channel": "chemdraw"`
- **一致**：✗

**L101 `"version": "ChemDraw ..."`，说"以 ChemDraw 开头即可"**

- **真实 JSON**：`"version": ""`（`app.Name` 为空串，不是抛错）
- **一致**：✗

**L102 `"home": "...\\ChemDraw.exe"`，说"指向实际的可执行文件"**

- **真实 JSON**：`"home": ""`；exe 路径实际在 `"details": {"fullname": "C:\\Program Files\\...\\ChemDraw.exe"}`
- **一致**：✗

**L104 `details.progid == "ChemDraw_x64.Application"`**

- **真实 JSON**：一致
- **一致**：✓

**L105 `details.attached`**

- **真实 JSON**：无实例时 `"attached": false`；有实例时 `"attached": true, "started_by_us": false`
- **一致**：✓（语义也对）

**L106 `details.started_by_us`**

- **真实 JSON**：自起实例时 `true`
- **一致**：✓

**L107 `details.documents_open`**

- **真实 JSON**：`0`（数字）
- **一致**：✓

**L108 `details.elapsed_ms` 量级 1 秒**

- **真实 JSON**：`584`
- **一致**：✓

**L110 `failures == []`**

- **真实 JSON**：`[]`
- **一致**：✓

**L120 `"channel": "kd"`**

- **真实 JSON**：`"channel": "kingdraw"`
- **一致**：✗

**L122 `"version": "GRDKitDll exports=12/12"`**

- **真实 JSON**：逐字一致
- **一致**：✓

**L124 `details.exports_found: 12`（整数）**

- **真实 JSON**：`exports_found` 是**12 个导出名的数组**；整数在 `exports_expected`
- **一致**：✗

**L125 `details.exports_expected: 12`**

- **真实 JSON**：`12`
- **一致**：✓

**L126 `details.exports_missing: []`**

- **真实 JSON**：`[]`
- **一致**：✓

**L127 "出现 `@bind_errors`@ 就说明有函数绑不上"**

- **真实 JSON**：本机不出现（12/12 全绑定）
- **一致**：✓

**L128 `details.elapsed_ms: 71`**

- **真实 JSON**：`69`
- **一致**：✓（示例值，量级对）

****L134 判定式** `exports_found == exports_expected`**

- **真实 JSON**：数组 == 整数，**永远为假**
- **一致**：✗ **最严重**


## §5 错误对照表复现（4 条）

**L144**

- **场景**：64 位跑 `doctor kd`
- **实际现象（逐字）**：rc=1，`failures[0].code = "E04"`，`message = "KingDraw core library is x86; this interpreter is x64"`，`hint = "Run with runtime/py32/python.exe"`
- **判断**：准确

**L144 后半**

- **场景**："或直接 `OSError: [WinError 193] 不是有效的 Win32 应用程序`"
- **实际现象（逐字）**：用 64 位 `ctypes.WinDLL('D:/tool/KingDraw/GRDKitDll.dll')` 复现：`OSError: [WinError 193] %1 不是有效的 Win32 应用程序。`
- **判断**：现象存在，但本机是中文 locale 且带 `%1` 前缀，文档引文与实测字符串不完全一致（P1-3）；另外 CLI 走的是 E04 分支，**不会**抛 WinError 193，文档把两条路混在一行

**L145**

- **场景**：32 位跑 `doctor cd`
- **实际现象（逐字）**：rc=1，`code = "E08"`，`message = "This interpreter is 32-bit; ChemDraw automation needs 64-bit"`，**`detail = ""`**
- **判断**：码对了，但文档说"**detail** 说 This interpreter is 32-bit" —— 那句话在 `message` 里，`detail` 是空串（P1-1）

**L146**

- **场景**：`runtime/py32/python.exe` 不存在
- **实际现象（逐字）**：`bash: runtime/py32/python.exe: No such file or directory`，rc=127，CLI 根本没被调用
- **判断**：处置（先跑 `fetch_runtime.py` / `--verify`）正确；"现象"列没写清用户实际看到的是 shell 报错（P2）

**L147 旁证**

- **场景**：中文路径导出
- **实际现象（逐字）**：`cd draw 'c1ccccc1O' --out .../venv_phenol.png` → 8339 B 文件生成，JSON 里带 ASCII 暂存警告
- **判断**：准确（适配器已绕过），不算问题


> 另外验证了 §4 L105 的语义："`attached: true` = 复用了你已经开着的实例"：手工启动 ChemDraw 后再跑 `doctor cd --json`，
> 得到 `attached: true, started_by_us: false`，且**该用户实例在 doctor 结束后仍存活**（`tasklist` 计数 1），与"只 Quit 自己起的实例"一致。

## 必须修的文档问题（按严重度）

**P0 —— 会让人做出错误判断，必须改**

1. **§4 KingDraw 判定式写错（L134）**：`exports_found == exports_expected` 在真实 JSON 上永远为假 —— `exports_found` 是 12 个名字的数组，`exports_expected` 才是整数 12。
   应改为 `len(details.exports_found) == details.exports_expected`；L124 的示例值也要从 `12` 改成数组（或改成 `len()` 的说明）。
2. **§4 ChemDraw `home` 字段不存在（L102）**：真实 `home` 恒为 `""`，exe 路径在 `details.fullname`。照文档核对会误判"环境不对"。
3. **§4 ChemDraw `version` 恒为空（L101）**：本机 `app.Name` 返回空串，`version` 永远 `""`，不是"以 ChemDraw 开头"。想把版本/安装位置当判据，应改用 `details.fullname`。
4. **§4 两处 `channel` 取值写错（L99 / L120）**：`cd` → 实际 `chemdraw`；`kd` → 实际 `kingdraw`。读者按文档 grep 会搜不到。
5. **§3 步1 无法照做（L32-37）**：`<仓库地址>` 是占位符，且当前目录不是 git 仓库。发布前填真实地址，或把"解压目录"那条写成唯一入口并给出验证方式。

**P1 —— 会误导排障，建议改**

6. **§5 L145 E08 行字段说错**：`This interpreter is 32-bit` 在 `message` 里，`detail` 是空串。
7. **§6 / 文末（L165-170、L192）**："命令均对照 `--help` 真实输出核过"已过期：CLI 现在有 `cd` 子命令组（doctor/draw/export/figure/read/capabilities），quickstart 完全没提。至少补一行 `python bin/cli.py cd --help`，并说明它需要 64 位解释器。
8. **§5 L144 把两种失败并列在一行**：CLI 的 64 位 `doctor kd` 走 E04 分支、不抛 `WinError 193`；`WinError 193` 只在"自己用 ctypes 直接加载 DLL"时出现。建议拆成两行，并注明本机消息是中文 locale。

**P2 —— 不影响结论，但读者会停顿**

9. **§3 步3 `--verify`（L59-61）**：没写预期输出与退出码。实测未安装时 rc=1 且 `present : False`，属正常，文档应点明。
10. **§6 注（L172）**：64 位跑 `doctor all` 时 kd 不可用会让**整条命令 rc=1**，文档只说"是位宽提示不是故障"，没说退出码，写进 CI 的人会踩到。

## 顺带发现（代码侧，不属 quickstart 修正，交 dev-cd 判断）

1. **`doctor/cd.py::_running_pids()` 恒返回 []** —— 实测机器上明明有 `ChemDraw.exe PID 980`（tasklist CSV: `"ChemDraw.exe","980","Console","4","154,328 K"`），
   函数返回 `[]`。原因：解析时只 `strip("'")` 去单引号，而 tasklist 的 CSV 用**双引号**，于是 `'"ChemDraw.exe"'.startswith('chemdraw')` 为假。
   影响：`details.instances_before` 永远为空；且 `started_by_us = (not attached) and len(pids_before)==0` 这条判定在"用户实例存在但 `GetActiveObject` 失败"时会误报 `started_by_us=true` 并 `Quit()` 掉**用户**的实例，有丢未保存数据的风险。建议 `strip('"')`。
2. **`--keep-open` 实测无效果**：`doctor cd --json --keep-open` 返回后立即 `tasklist` 计数为 0（与不加该开关一样）。
   代码里 `quit_if_started=not args.keep_open` 是接上的，推测是 Python 进程退出释放 COM 后 ChemDraw 自行退出；需要决定是改行为还是改文案。
3. `doctor cd` 的下一层 `details` 键比文档示例多（`instances_before` / `fullname` / `document_names`）—— 文档已声明是"节选"，不算问题，但 `fullname` 恰好是 `home` 该指向的东西。

## 本次未验证

- **真实 `git clone` 流程**：本机不是 git 仓库、无远端地址，只验证了"解压目录"那条回退。
- **§5 L142 激活模态框场景**：需要一台 ChemDraw 未激活/弹模态框的机器，本机无法复现。
- **"只装 KingDraw 不装 ChemDraw"的完整流程**：不能为了验证卸载 ChemDraw（文档 §7 自己也列为未验证）。
- **ChemDraw 25.x / 27.x、KingDraw 其他版本、非默认安装路径**：无第二套环境。
- **MCP / DSH 插件层**：quickstart 没给命令，§7 自己写了"仍在推进"，本报告不涉及。

## 证据

- 逐步输出：`test/out/qs_verify/log/<步骤>.{cmd,out,err}` + `timings.tsv`（每条命令原文、stdout、stderr、rc、毫秒）
- 补充验证：`test/out/qs_verify/log2/`（`doctor_cd_fresh` / `attach_user` / `venv_*` / `keep_open*` / `venv_install.txt`）
- 被测快照与重新下载的 `runtime/py32` 留在 `test/out/qs_verify/chem-draw-tool`（29 MB）；临时 venv（179 MB）用完已删，安装记录转写在 `log2/venv_install.txt`。
- 复跑方式：`bash test/out/qs_verify/run_steps.sh`（逐条命令与 quickstart 原文一致，不含任何改写）。
