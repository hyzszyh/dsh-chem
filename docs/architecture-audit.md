# 后端架构审计（t20）

- 范围：`core/chemdraw_tool/`（`adapters/cd_com.py`、`adapters/kd_export.py`、`adapters/kd_native.py`、`mcp_server.py`、`crosscheck.py`、`identity.py`、`cli.py`）、`bin/`、`dsh-plugin/lib/`
- 日期：2026-10-29 · 性质：审计 + 就地修掉能修的，修不了的写方案
- 六类检查项：资源生命周期 / 并发重入 / 异常路径清理 / 编码边界 / 超时 / 数据流一致性
- 约束遵守：没有为审计跑 ChemDraw 或 KingDraw 长测试；全部证据来自 mock 注入、静态读数与磁盘计数。跑完已清理 `/tmp` 残留

## 结论摘要

****P0** · 3**

- **内容**：覆盖用户剪贴板不还原 · 导出桥每次泄漏一个临时目录（实测 25 692 个 / 2.9 GB）· SaveAs 异常时泄漏 staging 目录
- **状态**：**已修**，各带回归断言

****P1** · 4**

- **内容**：MCP 常驻进程对 COM 没有超时（一个卡住的调用冻结整个服务器）· `identity` 不是 Result 信封 · `kd export` 的 `path` 指输入而 `cd export` 的 `out` 指输出 · 跨进程 Quit 竞态
- **状态**：P1-1 已于 t21 修掉（`com_broker.py` + 10 条新断言）；其余 3 条：2 条锁死断言，1 条给方案未修

****P2** · 4**

- **内容**：桥接启动失败时 log 句柄挡住清理（已修）· SIGKILL 路径未实测 · 非文本剪贴板无法还原 · `.kdx` 保留是设计
- **状态**：已记录


**一句话**：真正会伤到用户的三个问题都在资源清理和用户共享状态上，而且都能用「跑一次看磁盘 / 看剪贴板」证明。并发这一项反而是**清白的**：MCP 是串行 loop，进程内不存在重入。

## 方法（可复现）

**磁盘计数**

- **用在哪**：`ls -d $TEMP/kd_export_bridge_* | wc -l`、`cdstage_*`
- **结果**：修前 **25 692** 个桥接目录、2 个 staging 目录；`du -sh /tmp` = **2.9 G**

**mock 注入**

- **用在哪**：`subprocess.Popen`、`tempfile`、`win32clipboard`、`os.path` 全部在函数边界打桩
- **结果**：不启动任何厂商进程即可复现每条

**串行性证明**

- **用在哪**：往 `_serve_loop` 灌三条请求，`handle` 里记录 start/end 顺序
- **结果**：严格 start1→end1→start2→end2，见 `test_11`

**静态读数**

- **用在哪**：grep `try/finally`、`rmtree`、`timeout=`、`Quit`、`clipboard`
- **结果**：见各类结论


---

## P0-1 · 粘贴路线覆盖用户剪贴板且从不还原

**问题**

- **内容**：`insert_via_paste()`（`cd_com.py:608`）为了走 `doc.Paste()` 必须把 SMILES 写进剪贴板，写完不还原；结果里只有一句 warning：`the clipboard was overwritten by this call`（`:665`）。用户复制的内容在调用后永久消失

**触发条件**

- **内容**：任何人用 `cd draw --route paste`，或插件 `chemdraw_draw` 传 `route=paste`

**后果**

- **内容**：用户数据丢失（不可撤销）。这是唯一一条会毁掉剪贴板上别的东西的路径

**复现（修前）**

- **内容**：mock `win32clipboard` 后调 `insert_via_paste('CCO')`：`SetClipboardText` 只被调用一次（写入 SMILES），返回 `data` 里没有 `clipboard_restored`，`warnings=['the clipboard was overwritten by this call']`

**复现（修后）**

- **内容**：`python test/test_architecture_backend.py ClipboardRestore`：`SetClipboardText` 被调用两次（先 SMILES、后用户原文），`data['clipboard_restored'] is True`，`warnings == []`

**修复**

- **内容**：新增 `_clipboard_text()`（依次试 `CF_UNICODETEXT` / `CF_TEXT`，bytes 按 UTF-8 解）与 `_restore_clipboard()`（尽力而为，失败返回 False 而不抛）；`insert_via_paste` 在打开剪贴板读原文→写入 SMILES→`CloseClipboard`→`Paste()`→**还原原文**；还原失败才保留 warning，成功的调用不再报「覆盖」

**残留**

- **内容**：只能还原**文本**。用户剪贴板里若是图片、文件列表或富文本，`EmptyClipboard()` 之后无法重建，此时 `clipboard_restored=false` + warning 仍是唯一诚实的答案（`data` 里给了这个字段，调用方可以据此提示）

**回归断言**

- **内容**：`test_04~test_07`（读两种格式 / 还原成功 / 还原失败不抛 / 结果字段与警告）


## P0-2 · KingDraw 导出桥接每次泄漏一个临时目录（实测 25 692 个，2.9 GB）

**问题**

- **内容**：`_export_via_bridge()`（`kd_export.py:542`）为每次导出创建 `kd_export_bridge_*`，里放 `result.json` 与 `helper.log`。代码只删了 `result.json`（`:590`），**目录本身从不删除**

**触发条件**

- **内容**：每一次走桥接的 `kd export` / MCP `kingdraw_export` / 插件 `kingdraw_export`

**后果**

- **内容**：稳态泄漏：每次一个目录（两个文件）。本机实测残留 **25 692 个**，`/tmp` 合计 **2.9 GB**。MCP 常驻 + 批量出图时这是线性增长

**复现（修前）**

- **内容**：`ls -d "$TEMP"/kd_export_bridge_* | wc -l` → `25692`；`ls -la` 其中一个：只有 `helper.log`（0 字节）

**复现（修后）**

- **内容**：`python test/test_architecture_backend.py ExportBridgeScratch`：成功路径与「helper 什么都没写」路径都断言 `_bridge_dirs()` 增量为空；手工连跑三轮全量测试，计数恒为 **0**

**修复**

- **内容**：从 `mkdtemp` 起把整个函数体套进 `try:`，`finally: shutil.rmtree(bridge_dir, ignore_errors=True)`；清理已实测：`25692 → 0`，三轮复跑保持 0

**附带**

- **内容**：同一函数里 `log_handle` 在 `Popen` 抛 `OSError` 时没关（见 P2-1）——Windows 上打开的文件句柄会让 `rmtree` 静默失败，等于把泄漏原样放回这条路径；已一并修

**回归断言**

- **内容**：`test_01`（成功路径）、`test_02`（helper 无输出）、`test_12`（helper 起不来）


## P0-3 · SaveAs 抛异常时泄漏 ChemDraw staging 目录

**问题**

- **内容**：`export()` 给非 ASCII 目标建 `cdstage_*`（`cd_com.py:1097`）。空文件路径有 `rmtree`（`:1261`）、复制路径有 `finally`（`:1290`），但 **`SaveAs` 抛异常那条 return（原 `:1252`）什么都不清**

**触发条件**

- **内容**：中文/非 ASCII 输出路径 + ChemDraw 在 SaveAs 时抛 COM 异常（激活模态框、文件被占用）

**后果**

- **内容**：每次失败留一个空目录；不会炸，但和 P0-2 是同一类「越失败越脏」

**复现（修前）**

- **内容**：mock 一个 `SaveAs` 抛 `RuntimeError` 的 doc，`export('…/中文导出测试.png','png')` 之后 `$TEMP` 多一个 `cdstage_*`

**复现（修后）**

- **内容**：`test_03`：同一调用后 `_stage_dirs()` 增量为空

**修复**

- **内容**：在 `except` 分支里 `if staged_from: shutil.rmtree(staged_from, ignore_errors=True)` 后再 return

**回归断言**

- **内容**：`test_03`（顺带断言失败消息里带 `SaveAs`，防止把异常吞成成功）


---

## P1-1 · MCP 常驻进程对 COM 调用没有超时：一个卡住的调用冻结整个服务器 —— **t21 已修**

**问题**

- **内容**：`_serve_loop()` 是 `for line in sys.stdin` 的单线程循环（`mcp_server.py:556`），`handle()` 同步执行 `tools/call`。ChemDraw 的 COM 调用**没有任何超时**（`cd_com` 全模块 grep 不到 `timeout`）。而 KingDraw 侧有 `WORKER_TIMEOUT=40`（`:27`）、`crosscheck` 有 `KD_TIMEOUT=60`、`kd_open` 有 deadline

**触发条件**

- **内容**：ChemDraw 弹模态框（激活提示、另存为对话框、大图导出）、COM 服务器无响应。已实测过一次类的现象：插件侧 `chemdraw_*` 全部超时（`dsh-plugin/README.md:60` 的排查条目就是这么写的）

**后果**

- **内容**：服务器进程永久阻塞：后续 `tools/call`、甚至 `ping` 都不再处理，客户端只能杀进程。杀进程本身不会留幽灵 ChemDraw（`LocalServer32` 在最后一个客户端释放后自退），但**已经画好的内容全部丢失**，且错误信息为空（Windows 给的描述是空的）

**复现**

- **内容**：已证明串行性（`test_11`）；把 `handle` 换成一个永不返回的函数，第二条请求不再被处理。真机复现需要制造模态框，属「需实跑」

**修复（t21 已按此方案落地，见文末「t21 实施记录」）**

- **内容**：建议**专用 STA 线程 + 队列**：所有 COM 调用只在一个由该线程创建的公寓里执行，主循环用 `queue.Queue` 投递任务并 `get(timeout=…)`；超时后不杀线程（COM 无法安全取消），而是把该通道标记为 `wedged`，后续调用立即返回 `E09` 并附「重启服务器」提示。**不能**简单丢进 `ThreadPoolExecutor`：在别的线程里碰由主线程创建的 COM 对象会触发跨公寓错误

**为什么不顺手改**

- **内容**：触及 `mcp_server` 生命周期与 `cd_com` 的单例语义（`channel()` 是 process-wide），改错会让「一次卡死」变成「永久不可用」；需要单独的验证轮次。t21 单开一轮做掉了，做法是给 `_cd_channel()` 套一层代理，15 个工具的处理函数一行没改


## P1-2 · `identity` 不是 Result 信封（全项目唯一例外）

**问题**

- **内容**：`identity.identify()` 返回**扁平字典**：`ok/input/canonical_smiles/inchikey/formula/evidence/note`（失败时加 `failure`）。没有 `data`、`channel`、`degraded`、`degrade_reason`、`elapsed_ms`、`warnings`、`evidence_note`

**触发条件**

- **内容**：MCP `chem_identity`、插件 `chem_identity`、CLI `identity` 全部走它

**后果**

- **内容**：消费方若按 `Result` 解析（读 `payload['data']`）会 `KeyError`。MCP 只靠 `ok` 判 `isError`，所以协议层没错，但「同一服务器 15 个工具里 14 个是信封、1 个不是」是认知负担

**复现**

- **内容**：`python test/test_architecture_backend.py Envelopes`：断言 `ok` 存在、`failure` 在成功时缺席、且 `data/channel/degraded/warnings` **均不存在**

**现存防错**

- **内容**：`models.Result.to_dict()` 的键集合也有断言（`test_10`），两头都钉住

**修复（未做）**

- **内容**：改成 `Result(data={...})` 需要同时动 CLI 的渲染（`_render` 吃 `channel/version/...`）与插件文档，收益是形式统一、风险是所有既有消费者。**建议保留扁平结构并在 `docs/architecture-audit.md` 与 MCP 工具描述里明写**——已在此登记，并由 `test_09` 防止它「悄悄变成另一种形状」


## P1-3 · `path` 一词在两处指向相反的东西

**问题**

- **内容**：`kd export <path>` 的 `path` 是**输入**（molfile），输出是 `--out`（`cli.py:569`）；`cd export <out>` 的 `out` 是**输出**（`cli.py` 的 `cd export` 位置参数）。MCP 侧对应的是 `kingdraw_export(input, out)` 与 `chemdraw_export(path=输出)` —— 同一个词 `path` 在 KingDraw 侧指输入、在 ChemDraw 侧指输出

**触发条件**

- **内容**：任何人凭直觉把 `kd export` 的第一个参数当输出路径

**后果**

- **内容**：参数错位：写出的图落到 molfile 路径旁，或直接报读不到输入。不会静默损坏数据，但会浪费一轮

**复现**

- **内容**：`python bin/cli.py kd export --help` → `positional arguments: path`；`python bin/cli.py cd export --help` → `positional arguments: out`；`python tools/contract_sync.py --dump | grep -A2 positional`

**修复（未做，待定）**

- **内容**：把 `kd export` / `kd save` 的位置参数 dest 改名 `src`（`usage` 里显示 `<src>`，纯呈现层），或至少在 `help` 文案里写「输入 molfile」。**没动**是因为它改变的是用户可见的 usage 行，属于 `t17` 那条「公开契约」的边界，交 captain 定


## P1-4 · 跨进程 Quit 竞态 —— **本轮实测：现行架构下不可达**

> 结论先说：代码里的竞态路径是真的，但触发它需要「一个进程跨调用持有实例」，而 t21 的 `com_broker`
> 让常驻进程每次调用结束就放掉实例。三组真跑实验见下方「实测」。**已从待修降为架构约束。**

**问题**

- **内容**：`channel()` 是**进程内**单例（`cd_com.py:1497`），`connect()` 先 `GetActiveObject`（附到已运行实例）再退回 `Dispatch`。于是：进程 A 自建实例（`started_by_us=True`），进程 B 随后 attach（`started_by_us=False`）。A 退出时 `close()` 无条件 `Quit()`（`:371`），B 手里的 COM 对象即刻失效

**触发条件**

- **内容**：MCP 服务器常驻（它起的实例）+ 另一个终端跑一条 `cd draw`（attach 上去）；然后 MCP 收到会话结束 → `_shutdown()` → `Quit()`

**后果**

- **内容**：B 的下一次调用抛 `COM object is no longer valid`（或空错误描述）。**不会**关掉用户自己的实例（`attached` 分支只清内容不 Quit），所以伤的只是另一个自动化进程

**实测（这一轮真跑了，结论推翻了上面的触发条件）**

三组实验，全部真 ChemDraw，每组之间 `taskkill` 清场：

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| 实验 | 进程 | 结果 |
|---|---|---|
| 两个 `cd figure` 同时跑，错开 0.4 s，3 轮 | 6 次调用 | 6/6 成功，无残留实例 |
| `crosscheck` + `cd figure` + `cd capabilities` 三路，错开 1.0 / 1.5 s，3 轮 | 9 次调用 | 9/9 成功 |
| 常驻 MCP 起实例 → 一次性 CLI attach → 关掉 MCP（即本条目写的触发条件） | 3 次调用 | 全部成功 |

第二组同时每 0.15 s 采一次实例数：**整个过程只有 1 个 ChemDraw 实例**，说明两个进程确实共用了它，
共享是真的——只是 `Quit()` 没有落进对方的调用窗口。

第三组是决定性的一组：resident 调完一次 `chemdraw_draw` 之后立刻数，**实例数是 0**。
也就是说 t21 加的 `com_broker` 在每次调用结束后就把实例放掉了，常驻进程根本不跨调用持有 ChemDraw。
本条目写的触发条件（「MCP 常驻起的实例 + 另一个终端 attach，然后 MCP 收到会话结束 → Quit」）
**在当前架构下不存在**。

**结论**：代码里的路径仍然真实（`close()` → `if self.started_by_us: self._app.Quit()`，`:371-373`，
没有任何「还有别人在用吗」的判断），但**现行架构下走不到**。留着这条是为了：将来若引入常驻实例
（例如给 MCP 加速而缓存实例），必须同时处理它。届时的可行方案：`%TEMP%\chem-draw-tool.attachers`
放 pid 文件，`connect()` 追加、`close()` 前检查是否只剩自己；或退一步——自建实例也永不 `Quit()`。

**不再列为待修**：这一轮之前它排 P1，现在降为「架构约束」——不是风险，是将来改架构时的前置条件。


---

## P2-1 · 硬杀之后会留下一个 ChemDraw 窗口（实测；不修，理由如下）

复现（`python test/out/orphan_probe.py`，脚本内容见本节末）：起一个正在出图的 CLI，
1.5 秒后 `TerminateProcess`，再数 `ChemDraw.exe`。

<!-- nowrap: 程序输出，原样引用 -->
```text nowrap
ChemDraw instances before: 0
during the run: 1
after a hard kill: 1
next command rc=0 in 0.3 s
  ok = True | rows = 10
ChemDraw instances at the end: 1
after cleanup: 0
```

结论分两半，必须分开说：

- **功能没坏。** 下一次命令 0.3 s 内接上这个残留实例并正常返回（attach 而不是新起），
  所以硬杀不会累积实例，也不会把后续调用卡住。
- **窗口留下了。** 因为 `close()` 只 Quit **自己启动的**实例，而硬杀让 `finally` 根本没跑。
  用户看到的是一个多出来的空 ChemDraw 窗口，直到他自己关掉。

**为什么不修。** 要清理它就得能证明"这个实例是我上次启动的"。唯一可用的凭据是
PID + 进程创建时间，而 PID 会被复用——按一个过期的 PID 去 Quit，可能关掉用户正开着、
里面有未保存结构的那个 ChemDraw。**误杀一个有内容的实例，比多留一个空窗口严重得多**，
所以这条停在"记录在案"。

**Ctrl-C 不是这个情况。** 它走 Python 的 finally，`ch.close()` 会执行，实例正常退出。
这条不再靠"读代码觉得对"，而是 `test/test_architecture_backend.py::test_13` 用 AST
断言 `_cd_dispatch` 在 try 里、`ch.close()` 在 finally 里（删掉 close 该断言立刻红，已验）。

<!-- nowrap: 复现脚本，原样可跑 -->
```python nowrap
import os, subprocess, sys, time
def count():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ChemDraw.exe', '/NH'],
                         capture_output=True, text=True, errors='replace').stdout
    return out.count('ChemDraw.exe')
print('before:', count())
proc = subprocess.Popen([sys.executable, 'bin/cli.py', 'cd', 'figure',
                         'test/out/orphan/probe.png', '--width-mm', '85',
                         '--dpi', '1200', '--smiles', 'c1ccccc1O'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5); print('during:', count())
proc.terminate(); proc.wait(30); time.sleep(3)
print('after a hard kill:', count())
subprocess.run(['taskkill', '/F', '/IM', 'ChemDraw.exe'], capture_output=True)
```

## P2-2 · 一个无窗口的 KingDraw 残留，会把后面所有「打开并确认」的检查拖进超时

**现象（全量扫的时候被发现的）**

一次全量里四个套件红了，症状各不相同：`test_kd_export` 报 E05（每条 123 s）、
`test_kd_open` 报 `KeyError: 'open'`、`test_kd_save` 报 E05、`test_misuse` 有两条超时。
单独重跑这四组 4/4 全过。

**根因**：起作用的不是这四个套件，是**它们之前那次运行留下的一个 KingDraw 进程**。它占着
单实例锁，于是下一次启动把文件转发给一个谁也看不见的窗口，工具等满 `--timeout`（默认 90 s）
再报 E05，并把同样的状态继续留给下一轮。

**反证（这一条很重要，否则结论就反了）**：用户**正常开着** KingDraw（有窗口，pid 59268）时，
`kd export` **15.0 s 成功**。所以不是「开着就坏」，坏的是「启动后等不到窗口」这条路。

**修的部分（消息层）**：原来那段失败提示只有两种说法，而实际有三种状态，且最乱的一种正好没被覆盖——
`existing` 为空（启动时没看到进程）但 `still_running` 非空（现在冒出来一个）时，提示说的是
「Leave it running or close it by hand; this tool does not kill processes」，读者完全不知道
「有一个我既没 attach、也归因不了的进程」这件事。现在拆成 `_no_window_hint()` 三个分支：

1. attach 到过的实例没出窗口 → 指名那个 pid，建议手工看或关掉重试；
2. 冒出来一个归因不了的进程 → 明说它多半是上次中断的残留、它占着单实例锁，给出
   `taskkill /F /IM KingDraw.WpfForm.exe`；
3. 一个进程都没有 → 给 `--timeout`（三个子命令都有：20 / 30 / 90）。

判据：`test/test_kd_adapter.py` 三条（17 条里的后三条），把旧的一句话放回去立刻不满足断言。

**没修的部分**：等待本身。默认 90 s 的窗口等待对「本来就不会出窗口」的情况仍然太长；
`--timeout` 是现有逃生口，但默认值没动——缩短它会影响真正慢启动的机器，而那种机器我手上没有。
**没查清的部分**：那个无窗口实例是怎么产生的（怀疑是被 taskkill 中断的 `KingDraw.WpfForm.exe`
残留，未证实）。跑测器里加了一条对应特征，下次再遇到会直接说是这个原因，而不是四个互不相关的红。

## P2-3 · 机器读的那条输出，有三个能一次踩中的坑

这一轮从**干净克隆**开始用（见 PROGRESS 第三轮），三个坑都是在那条路上踩出来的，
共同点是：人眼看不见，脚本必踩。

### (a) `--json` 仍往 stderr 写备忘，`2>&1` 之后文件不是 JSON

`cd figure ... --json > out.json 2>&1` 是最自然的写法，尤其是调试失败的时候。
实测产出的文件第一行是 `chem-draw-tool: 2 warnings: ...`，第二行才是 `{`，
任何解析器都读不了它——而 `--json` 的全部意义就是这个文件。

修：备忘只在 **stdout 还是终端**时才写 stderr（`_stdout_is_a_terminal()`）。人在终端里仍然看得到；
重定向/管道/插件/测试拿到的就是纯 JSON。判据 `test_presentation.py::test_merged_json_capture_still_parses`。

### (b) 参数用错，要先等 COM 服务器连上才报得出来

`cd modify` 不带任何编辑参数时，正确回答是「告诉我要改什么」。实测在没装 ChemDraw 的机器上，
拿到的是 E01「连不上 ChemDraw」——真实错误一辈子不出现，因为这条检查写在 `_cd_dispatch` 里，
而它只在通道打开之后才跑。`cd figure` 的错误提示同理。

修：抽出 `_cd_validate_args()`，在 `_open_cd_channel()` **之前**调用。判据是
`test_architecture_backend.py::test_14_argument_checks_run_before_the_channel_opens`——
查的是源码里的调用顺序，因为在装着 ChemDraw 的机器上这个顺序看不出来（两种顺序都给同样的答案）。

### (c) `cd figure` 的位置参数是输出，传源文件时提示指向反方向

`cd figure phenol.mol --out out.png` 里，`phenol.mol` 被当成**输出名**，然后报
「nothing was drawn ... pass a file instead of a string」——让用户去做他刚做过的事；
更糟的是那个源文件离被 SaveAs 覆盖只差一步。

修：位置参数的**名字以化学后缀结尾**（存在与否都算——`cd figure` 只写 PNG，`.mol` 结尾永远不可能是输出名）
且没给 `--smiles` 时，直接说清楚它是输出位置并给出正确写法。

第一版判据要求 `isfile`，于是干净克隆上（那个文件本来就不存在）又退回原句——这和前面三个坑是同一类错误：
规则依赖的是一台机器的状态，而不是这个命令的语义。判据现在两条路径都断言：
`test_presentation.py::test_a_source_file_where_the_image_goes_is_named`（顺带断言源文件没被吃掉）。

### 顺带量出来的一条曲线（85 mm 到底能到多少 dpi）

同一条路上撞出来的问题：示例脚本声明 85 mm @ 1200 dpi（ACS 单栏 + 期刊线图下限），
这条导出路径却卡在 **1922 px**，于是它安静地交出一张 40.7 mm 的图。

| 要求 dpi | 实得像素 | 实得宽度 |
|---|---|---|
| 300 | 995×672 | 84.2 mm |
| 500 | 1656×1121 | 84.1 mm |
| **574** | **1901×1288** | **84.1 mm** |
| 600 | 1922×1302 | 81.4 mm ← 撞上限 |
| 1200 | 1922×1302 | 40.7 mm ← 撞上限 |

所以答案是 574，而原来的提示只说「出来是 40.7 mm」。修：撞上限时算 `dpi_fit = 画布宽 × 25.4 / 目标毫米`，
写进 `data.figure.dpi_fit` 和那句警告里；示例脚本读到它之后自动按 574 再导一次，产出真 85 mm 的图
（`test_examples.py` 现在断言落在 85 ± 1.7 mm）。

## P2-4 · MCP 层：失败是诚实的，但说法不能直接用

这一轮把 MCP 服务器当**敌意客户端**来打：真实 stdio、真实 JSON-RPC，一次一条脏输入。
先记**过的那些**（都是实测，不是推断）：

| 打进去 | 回来的 | 判 |
|---|---|---|
| 通知（无 id） | 无响应 | 对 |
| `this is not json` | `-32700` | 对，服务没死 |
| `nosuch/method` | `-32601` | 对 |
| `no_such_tool` | `isError` + `unknown tool` | 对 |
| 50 KB 参数 | 正常回答 | 循环没崩 |
| 脏输入后的正常调用 | 正常回答 | 对 |

**没过的**是缺参数那一条。实测 `tools/call chem_identity {}` 回的是：

```json
{"ok": false, "failure": {"code": "E99", "message": "tool raised",
 "detail": "t recent call last):\n  File \"...mcp_server.py\", line 536, ..."}}
```

三件事同时不对：`detail` 是**被从中间截断的 Python traceback**（开头那个 `t` 是 `Traceback` 的尾巴）；
`message` 只说「tool raised」，没说是什么；真实原因 `KeyError: 'smiles'` 一个字没提，
而 schema 里明明写着 `required: ['smiles']`。

对人和对 agent 都糟：人看到 traceback 以为工具坏了；agent 拿到 `E99` 无从下手，只能瞎试。

**修**：`KeyError` 单独认，回 `E06 / stage=arguments`，message 写成
`missing required argument 'smiles' for chem_identity`，detail 写「要什么、给了什么」，
hint 从 schema 的 `required` 与 `properties` 生成（顺带报出 schema 里没声明的参数）。
其余异常不再外泄 traceback，只给 `工具名 raised 异常类型` + 异常自带的 message。

**判据**：`test/test_mcp_wire.py` 从 8 条扩到 16 条，脏输入那一段一次跑完七种，
并显式断言「缺参数的答案里不许出现 Traceback，也不许出现 tool raised」——
这两句就是把旧行为钉死的钉子。
## P2 清单

**P2-1**

- **问题**：`_export_via_bridge` 的 `log_handle` 在 `Popen` 抛 `OSError` 时未关闭；Windows 上打开句柄会让 `rmtree` 静默失败，等于把 P0-2 泄漏原样放回
- **处置**：**已修**：`log_handle = None` 初始化 + `except` 分支先关闭；`test_12` 覆盖

**P2-2**

- **问题**：`SIGKILL` / 断电路径上 ChemDraw 与 KingDraw 会不会留后台：`serve()` 有 `try/finally → _shutdown()`，但 `finally` 只管正常退出与 `SystemExit`；`SIGKILL` 下进程直接消失，留下的是「依赖 `LocalServer32` 自退」这一种可能
- **处置**：记录为**需实跑**（要真起 ChemDraw + `Stop-Process -Force`），见「未验证」

**P2-3**

- **问题**：非文本剪贴板无法还原（图片/文件列表/富文本）
- **处置**：只能如实报告（`clipboard_restored=false` + warning），不假装还原

**P2-4**

- **问题**：`keep_kdx=True` 时 `workdir` 有意保留（`kd_export.py:507` 的 `if not keep_kdx`）——这是设计不是泄漏，但目录名 `kd_export_*` 与桥接的 `kd_export_bridge_*` 同类，容易在排查时误判
- **处置**：记录在案；如要区分，可在目录里写一个 `README.txt` 说明它为何存在


## 六类检查项的逐项结论

### 1. 资源生命周期

**COM `Application`**

- **谁创建**：`connect()`（`cd_com.py:273`）
- **谁释放**：`close()`：仅 `started_by_us` 才 `Quit()`，attach 的只清内容（`:358-392`）
- **结论**：**正确**。跨进程那一层见 P1-4（本轮实测：现行架构下不可达）

**COM 文档**

- **谁创建**：`document()` → `Documents.Add()`
- **谁释放**：`close()` 里对 attach 场景 `_clear_document()`；`Document.Close()` 实测是 no-op，已在 warning 里说明
- **结论**：**正确且诚实**

**`cdstage_*`**

- **谁创建**：`_stage_dir()`
- **谁释放**：空文件路径 ✓、复制路径 `finally` ✓、**SaveAs 异常路径 ✗ → 已修**
- **结论**：已修（P0-3）

**`kd_export_bridge_*`**

- **谁创建**：`_export_via_bridge()`
- **谁释放**：**没人释放 → 已修**
- **结论**：已修（P0-2），实测 25 692 → 0

**`kd_export_*`（workdir）**

- **谁创建**：`export_image()`（`:388`）
- **谁释放**：`finally` 里 `rmtree`（`keep_kdx` 时故意保留）
- **结论**：**正确**

**32 位 worker 子进程**

- **谁创建**：`mcp_server.call_worker` / `crosscheck._kd_call`
- **谁释放**：`subprocess.run` 自带回收 + `timeout`
- **结论**：**正确**（无泄漏，每次一个短命进程，代价是 1–2 s/次，已知）

**64 位导出 helper**

- **谁创建**：`_export_via_bridge`
- **谁释放**：deadline 后 `terminate()`/`kill()`（`:576-584`）
- **结论**：**正确**

**ZIP 句柄（`.kdx`）**

- **谁创建**：`zipfile.ZipFile(kdx_path)` / `(kdx)`
- **谁释放**：都是 `with` 块（`kd_export.py:253,451`）
- **结论**：**正确**

**`_StdoutGuard` 的 fd**

- **谁创建**：`os.dup(1)` + `os.open(devnull)`
- **谁释放**：`__exit__` 里 `dup2` + 双 `close`（`mcp_server.py:114-126`）
- **结论**：**正确**，`test_08` 钉住


### 2. 并发与重入 —— 结论：进程内不会互相破坏，理由是可证明的串行

- `_serve_loop()` 单线程逐行读 stdin（`mcp_server.py:556`），`handle()` 同步执行；`test_11` 用三条请求证明执行序严格为 `start1→end1→start2→end2→start3→end3`。**因此不存在两个 `tools/call` 同时在跑的窗口**。
- 进程内共享可变状态只有三处：`cd_com._shared`（`channel()` 单例）、`ChemDrawChannel._app/_doc`、`kd_native` 的 `_shared_lock`（已有 `RLock`）。串行前提下都不需要额外加锁 —— 但**这也正是 P1-1 的代价**：串行换来的是「一个卡死 = 全员卡死」。
- 跨进程（P1-4）**曾经**是唯一一处「会」的并发问题：两个进程 attach 到同一实例，谁 `Quit` 谁就把别人的
  COM 引用打断。本轮真跑了三组（两个 `cd figure` ×3、三路混跑 ×3、常驻 MCP + 一次性 CLI ×1），
  **15 次进程调用 0 失败**；采样确认它们共用同一个实例（全程实例数 1），只是 `Quit()` 没落进对方窗口。
  结论见 P1-4：现行架构下不可达。
- `crosscheck` 的 `shutdown()`（`crosscheck.py:375`）只是转调 `cd_com.close()`，语义与 CLI 退出一致；MCP 里没有暴露 `shutdown` 工具，只在 `serve()` 的 `finally` 里调（`mcp_server.py:551`），所以**不存在「一个工具调用把服务器自己的 ChemDraw 关掉」**的路径。

### 3. 异常路径的清理

**工具函数抛异常**

- **现状**：`handle()` 里 `except Exception` 兜底成 `E99 tool raised`（`mcp_server.py:524-527`），`_StdoutGuard` 的 `with` 保证 fd 还原

**`SystemExit` / 正常退出**

- **现状**：`serve()` 的 `finally → _shutdown() → cd_com.close()`（`:548-551`）

**`KeyboardInterrupt`（Ctrl-C 跑 CLI）**

- **现状**：CLI 没有统一 `finally` 关闭通道；进程消失后 COM 引用释放。**不实测**（会真起 ChemDraw），记为需实跑

**`SIGKILL`**

- **现状**：同上，只能依赖 `LocalServer32` 自退；记为需实跑


### 4. 编码边界

**ChemDraw `SaveAs`**

- **处理**：非 ASCII 目标先写 ASCII staging 再拷回（`cd_com.py:1231-1290`）；中文路径实测踩过
- **结论**：**已覆盖**，失败时 staging 已修

**JSON / stdio**

- **处理**：`ensure_ascii=False` + `reconfigure(encoding='utf-8', errors='replace')`（`mcp_server.py:543-547`）；worker 桥 `text=True, encoding='utf-8'`
- **结论**：**一致**

**`.king` 读写**

- **处理**：Python 层 `open(...,'wb')`，路径由操作系统处理
- **结论**：**无问题**（不经 COM）

**`.kdx` 成员名**

- **处理**：只读不写；`zipfile` 解出的名字当数据用，不拼路径
- **结论**：**无问题**

**Pillow 写回**

- **处理**：`artwork.normalize` 用路径直写，Pillow 支持中文路径
- **结论**：**无问题**

**未发现同类静默点**

- **处理**：grep 后新增隐患：`kd_export` 的 `--out` 与 `kd_save` 的 `out` 都是 Python 层写文件，不经过 SaveAs
- **结论**：**无**


### 5. 超时

**`subprocess.run`（worker / reader / doctor 的 tasklist）**

- **超时**：✓ 40 / 120 / 15 s
- **备注**：全部覆盖

**`subprocess.run`（UIA 桥 `_uia_via_bridge`）**

- **超时**：✓ `max(1.0, timeout)`
- **备注**：—

**`Popen`（导出 helper）**

- **超时**：✓ deadline + `terminate/kill`
- **备注**：—

**COM 调用（draw/export/figure/read/modify/capabilities）**

- **超时**：✓ t21 起有：`com_broker` 的每调用截止时间（`CHEMTOOL_COM_TIMEOUT`，默认 120 s）
- **备注**：**P1-1 已修**：超时返回 `E10 COM_STALLED`，通道标记 wedged，`ping` 与 KingDraw 不受影响；冷却后自动探测恢复

**`kd_open.open_file` / `close_app` / `wait_for_main_window`**

- **超时**：✓ 全部 deadline 化
- **备注**：—


### 6. 数据流一致性

**`Result` 信封**

- **结论**：`models.py:108-121` 十个键；`test_10` 钉住键集合。MCP 返回的是 `res.to_dict()`，`tools/call` 用 `ok` 判 `isError`

**唯一例外**

- **结论**：`identity.identify()` 扁平结构（P1-2，`test_09` 钉住）

**`data` 字段命名**

- **结论**：两处「同名不同义」：`kd export` 的 `path` 是输入（P1-3）；`kd_export` 的 `data.path` 是**输出**路径。其余（`out`/`format`/`resolution`/`width_pt`）跨通道一致

**`failure` 结构**

- **结论**：统一 `code/message/hint/detail/channel/stage`（`models.py:86-97`）；`mcp_server` 的 `call_worker` 手写 dict 但键一致

**`degraded`**

- **结论**：KingDraw 预览图明确置 `degraded=True` + `degrade_reason`（`kd_export.py:629-632`）；`crosscheck` 单引擎时置 degraded（`crosscheck.py:369`）· 一致

---

## 回归断言（防止下一轮退回去）

`python test/test_architecture_backend.py` —— 12 条，全部 mock，无厂商进程，约 0.06 s：

**01**

- **断言**：桥接成功后 `kd_export_bridge_*` 无新增
- **守护的问题**：P0-2

**02**

- **断言**：helper 无输出时同样无残留
- **守护的问题**：P0-2（失败路径）

**03**

- **断言**：`SaveAs` 抛异常后 `cdstage_*` 无新增
- **守护的问题**：P0-3

**04**

- **断言**：`_clipboard_text` 能读 `CF_UNICODETEXT` 与 `CF_TEXT`（bytes 按 UTF-8）
- **守护的问题**：P0-1

**05**

- **断言**：`_restore_clipboard` 写回原文并返回 True
- **守护的问题**：P0-1

**06**

- **断言**：还原失败返回 False 而不抛
- **守护的问题**：P0-1

**07**

- **断言**：`insert_via_paste` 的结果带 `clipboard_restored=True`、`warnings==[]`，且 `SetClipboardText` 顺序为「SMILES → 用户原文」
- **守护的问题**：P0-1 端到端

**08**

- **断言**：`_StdoutGuard` 退出后 `sys.stdout` 复原、fd 1 仍可用
- **守护的问题**：通知：**不是**问题，防止未来改坏

**09**

- **断言**：`identity.identify` 仍是扁平结构（无 `data/channel/degraded/warnings`）
- **守护的问题**：P1-2 的显式决定

**10**

- **断言**：`Result.to_dict()` 键集合等于十个已知键
- **守护的问题**：信封不被悄悄改形状

**11**

- **断言**：`_serve_loop` 严格串行（start/end 顺序）
- **守护的问题**：P1-1 的现状（串行是有意的）

**12**

- **断言**：helper 起不来（`Popen` 抛 `OSError`）时也无残留
- **守护的问题**：P2-1


## 未验证 / 需实跑清单

**U1**

- **事项**：Ctrl-C / `Stop-Process -Force` 之后 ChemDraw 会不会留后台
- **为什么没做**：需要真起 ChemDraw
- **建议命令**：`cd draw …` 起实例，另开窗口 `Stop-Process -Name ChemDraw -Force`，再 `tasklist | findstr ChemDraw`

**U2**

- **事项**：P1-1 的真机复现（模态框冻结服务器）
- **为什么没做**：需要人工制造模态框
- **建议命令**：起 MCP，手工把 ChemDraw 弹到「激活」对话框，再连发两个 `tools/call`

**U3**

- **事项**：P1-4 的跨进程竞态 —— **本轮已实跑，结论是不可达**（见 P1-4），此条作废
- **为什么没做**：需要两进程 + 真实例
- **建议命令**：A：`python -m chemdraw_tool.mcp_server`；B：`cd draw 'CCO'`；结束 A 看 B 的下一次调用

**U4**

- **事项**：粘贴路线在真机上的剪贴板还原
- **为什么没做**：需要真 ChemDraw + 真剪贴板
- **建议命令**：复制一段文字，`cd draw 'CCO' --route paste`，再 `Ctrl-V` 看回来的是不是原来的文字

---

## t21 实施记录：COM 超时保护已落地

上面 P1-1 的方案原样实现了，改动集中在**新增的一个模块**里，15 个 MCP 工具的处理函数一行未改。

### 结构

- **新增 `core/chemdraw_tool/com_broker.py`**：一个 worker 线程在启动时自己调 `pythoncom.CoInitialize()`，COM 对象只在这条线程上创建与使用（`test_05` 断言通道对象是在 `chemdraw-com` 线程上 new 出来的）。调用方把 `(方法名, 参数)` 投进 `queue.Queue`，用 `future.result(timeout=…)` 等截止时间。
- **`mcp_server._cd_channel()` 改为返回代理**（`com_broker.ChannelProxy`）：`__getattr__` 把任何方法调用转发到 broker，所以 `ch.draw_smiles(...)`、`ch.export(...)`、`ch._doc_count()` 这些既有写法保持不变。`connect()` 也走同一条路 —— 它同样会因模态框卡住。
- **`_cd_capabilities` 顺带修掉一个旁路**：它原先自己 `cd_com.ChemDrawChannel()` new 一个通道（绕开单例，也在主线程碰 COM），现在走 `_cd_channel()`。
- **`_shutdown()` 改为 `com_broker.shutdown(deadline=10)`**：`close()`/`Quit()` 必须在持有对象的公寓线程里执行，从主线程直接调是跨公寓。

### 超时之后的行为（明确约定）

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| 状态 | 行为 |
|---|---|
| 超时发生 | 返回 `E10 COM_STALLED`（`models.py` 新增，`ERROR_TEXT` 有中文可读提示），`stage='com-timeout'`，`hint` 让人去看 ChemDraw 窗口并关掉对话框 |
| 通道被标记 `wedged` | 后续 ChemDraw 调用**立即**返回同一失败（`test_03`：第二次 < 0.3 s，`detail` 里带 `wedged` 与卡住的方法名） |
| 同一时刻的其它请求 | `ping` 照常应答（`test_02`），KingDraw 工具照常工作（`test_04`）—— 两条通道独立的价值就体现在这里 |
| 恢复 | 冷却 `CHEMTOOL_COM_RETRY_AFTER`（默认 30 s）后，下一个请求会启动**新一代 worker** 并用 `connect()` 做一次探测（`CHEMTOOL_COM_PROBE_TIMEOUT`，默认 5 s）；探测通过就解除 wedged 并继续服务（`test_06`）。不需要重启服务器 |
| 卡死的 worker 线程 | 停在 COM 调用里无法安全取消，作为 daemon 线程留下；对话框关掉或进程退出即回收。这一点在模块 docstring 里写明了 |

### 可调参数（环境变量）

| 变量 | 默认 | 作用 |
|---|---|---|
| `CHEMTOOL_COM_TIMEOUT` | 120 s | 单次 COM 调用的截止时间 |
| `CHEMTOOL_COM_PROBE_TIMEOUT` | 5 s | 恢复探测的截止时间 |
| `CHEMTOOL_COM_RETRY_AFTER` | 30 s | wedged 之后多久允许探测 |

### 契约未变（有断言）

- 15 个 MCP 工具的名字与顺序由 `test_com_timeout.test_10` 钉住；返回信封形状由 `test_07` 逐键断言（`ok/data/failure/channel/degraded/degrade_reason/evidence/elapsed_ms/warnings/evidence_note`）。
- 只新增失败码 `E10`，没有改动任何既有码的语义。

### 新增断言（`python test/test_com_timeout.py`，10 条，4.2 s，全部 mock）

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| # | 断言 | 证明什么 |
|---|---|---|
| 01 | 串行 loop 里一个没有截止时间的调用让 `ping` 等了 1.2 s | **修复前**的样子（复现 P1-1） |
| 02 | 慢调用返回 `E10`，同一窗口内 `ping` 有应答，总耗时 < 2 s | **修复后** |
| 03 | wedged 后第二次调用 < 0.3 s 且 `detail` 含 `wedged` | 不会每个请求都卡满超时 |
| 04 | wedged 期间 `kingdraw_formula` 正常返回 | 另一条通道不受影响 |
| 05 | 通道对象在 `chemdraw-com` 线程上创建 | 公寓线程隔离真的生效 |
| 06 | 冷却后新一代 worker 探测成功并解除 wedged | 恢复路径可用 |
| 07 | 失败信封十键齐全、`code=E10`、`stage=com-timeout`、`hint` 提到窗口与对话框 | 契约与可读性 |
| 08 | worker 被卡住时 `shutdown()` 仍在 1.5 s 内返回 | 退出不会被拖死 |
| 09 | `ErrorCode.COM_STALLED == 'E10'` 且 `ERROR_TEXT` 有文案 | 错误码登记 |
| 10 | `TOOLS` 仍是那 15 个、顺序不变 | **对外契约一个都没变** |

### 同轮的 P1-4（跨进程 Quit 竞态）—— 当时未做，留到下一轮（**已由本轮实测结案：不可达**）

captain 实测撞到「两个进程同时操作 ChemDraw 时 `Documents.Add()` 失败」。这一条**没有**在本轮处理，原因：

1. 便宜的修法（`%TEMP%` 里放 pid 租约文件）会引入新的失效模式——租约残留会让自建实例**永不 Quit**，从「偶尔打断别人」变成「每次留一个不可见 ChemDraw」，比原问题更糟。
2. 另一种修法（自建实例也永不 Quit，靠 `LocalServer32` 无人引用自退）需要真机验证「最后一个客户端释放后进程确实退出」，而这恰好和本轮约束冲突：**别的成员正在驱动真 ChemDraw**，现在去 `Quit`/杀进程会打断他们的验证，得到不可复现的结论。
3. 它是可自愈的瞬时故障：captain 观察到重跑两次即正常，说明是竞态窗口而不是稳定失效。

下一轮建议的做法：先做**只读探针**（`GetActiveObject` 后只查 `Documents.Count`，不做 `Add`）确认「同一实例上是否已有别的自动化客户端」，再决定要不要引入租约文件；确诊之后再改 `close()` 的 Quit 条件。
