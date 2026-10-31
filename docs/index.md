# 文档索引

> 一眼看清：**你现在处于哪一步，就读哪一份**。新增文档必须在这张表里登记，否则等于没交付。

## 按处境查

**第一次拿到仓库，想知道怎么装**

- **读这份**：[quickstart.md](quickstart.md)
- **一句话说明**：五分钟装好并确认两条通道各自可用；含「看到什么算成功」与 13 条实测错误对照表

**改完代码，想一条命令确认没改坏**

- **跑这条**：`python test/run_all.py`（说明在 [../README.md](../README.md) 的「自检」一节）
- **一句话说明**：替你挑解释器与厂商前置，22 个套件一条命令；缺前置报 SKIP 并说清缺什么，不报 PASS

**想让 agent 直接画分子、出图、批改作业**

- **读这份**：[v2/requirements.md](v2/requirements.md)（决策与实测）与 [agent-interface.md](agent-interface.md)
- **一句话说明**：15 个任务级工具，`python bin/v2.py <verb>` 或 `python bin/mcp.py --surface tasks`；
  一次调用一个任务，带预览图与 InChIKey

**想知道需求里那八个剧本实测成什么样**

- **读这份**：[v2/acceptance.md](v2/acceptance.md)
- **一句话说明**：`python tools/acceptance_v2.py` 跑完八个剧本 10 次调用、13 秒；
  6 个通过，2 个部分完成（OCR 缺引擎、条件标注未实现），缺口写在表里

**想知道这个项目到底能干什么、不能干什么**

- **读这份**：[../README.md](../README.md)
- **一句话说明**：30 秒概览：两条通道的能力矩阵、依赖、证据等级 A/B/C、已知限制

**遇到怪现象、怀疑是环境/库的坑**

- **读这份**：[../PROGRESS.md](../PROGRESS.md)
- **一句话说明**：每次交付的实测证据与踩坑账本（含静默失败清单），按时间倒序，最该先搜的地方

**想知道接下来做什么、有哪些风险没除**

- **读这份**：[../PLAN.md](../PLAN.md)
- **一句话说明**：当前路线图与风险账本；v1/v2 早期方案见 [PLAN-v1.md](../PLAN-v1.md)、[PLAN-v2.md](../PLAN-v2.md)（存档，已被 PLAN.md 取代）

**要写 ChemDraw COM 调用，需要确认方法与签名**

- **读这份**：[com_item_document.txt](com_item_document.txt)
- **一句话说明**：本机 ChemDraw 26 的 COM 接口签名全量 dump：Document / Application / Documents 的每个成员

**要把分子「放进」ChemDraw 或把图「拿出来」**

- **读这份**：[upstream-com-notes.md](upstream-com-notes.md)
- **一句话说明**：上游 live-chemdraw-mcp 的原始做法与实测结论：`Objects.Data` 参数插入、SaveAs 的 Format 取法、GetData 的 dpi 陷阱

**要自己生成 CDXML，或者 CDXML 打不开**

- **读这份**：[cdxml-minimal.md](cdxml-minimal.md)
- **一句话说明**：169 字节的最小可插入/可打开子集、逐属性必要性实验、芳香键与 id 规则的静默失败

**要按期刊要求出图、或验收一张图**

- **读这份**：[journal-artwork.md](journal-artwork.md)
- **一句话说明**：ACS/RSC/Wiley/Elsevier 的 artwork 硬性数值（带原文与抓取日期）、硬性 vs 惯例、Pillow 验收片段

**想知道 M1 两条通道验收到底过了什么**

- **读这份**：[acceptance-m1.md](acceptance-m1.md)
- **一句话说明**：M1 双通道验收记录：InChIKey 一致性、往返一致、失败路径、进程卫生；`test/acceptance_m1.py` 一条命令可复跑

**想把这个项目拷到另一台机器，或担心它只在我这里能跑**

- **读这份**：[portability-report.md](portability-report.md)
- **一句话说明**：可移植性审查：硬编码路径、Windows 假设、位宽与编码假设、依赖完整性，逐条带文件:行号

**照 quickstart 做却对不上输出**

- **读这份**：[quickstart-verified.md](quickstart-verified.md)
- **一句话说明**：独立 QA 按 quickstart 原样实跑的记录与勘误；quickstart 里有几处字段说明被它推翻过，两份要一起看

**怀疑文档在手机上、或在 GitHub 上没法读**

- **读这份**：[render-audit.md](render-audit.md)
- **一句话说明**：渲染审计：超宽表格、代码块长行、标题跳跃、链接文字、图片引用、首屏密度；配 `bin/md_render_check.py` 一条命令复跑

**怀疑文档之间互相打架**

- **读这份**：[docs-audit.md](docs-audit.md)
- **一句话说明**：文档一致性巡检：链接、命令真伪、过期声明、数字与字段名核对，按 P0/P1/P2 分级

**担心代码里藏着会伤到用户的坑（关掉别人的 ChemDraw、覆盖剪贴板、泄漏磁盘）**

- **读这份**：[architecture-audit.md](architecture-audit.md)
- **一句话说明**：后端架构审计：资源生命周期（实测泄漏过 25 692 个临时目录 / 2.9 GB）、并发与重入、异常清理、编码边界、超时、数据流一致性；按「会不会伤到用户」排序

**想试各种误操作，或者想知道错误信息够不够清楚**

- **读这份**：[misuse-catalog.md](misuse-catalog.md)
- **一句话说明**：误用目录：空输入、不存在的文件、禁止的结构、缺装软件、位宽误用、同路径重复保存；每条给复现命令与修前/修后输出，配 `test/test_misuse.py` 一条命令复跑


## 工程文件（不是文档，但会被问）

**[requirements.txt](../requirements.txt)**

- **作用**：运行时依赖：`rdkit` + `pillow` + `pywin32`（仅 Windows，带环境标记）

**[pyproject.toml](../pyproject.toml)**

- **作用**：打包元数据、`chemdraw-tool` 入口点、依赖真相源（requirements.txt 与它保持一致）

**[LICENSE](../LICENSE)**

- **作用**：MIT，2026，chem-draw-tool contributors

**[bin/cli.py](../bin/cli.py)**

- **作用**：薄启动器：两个解释器都能直接跑包，不必先安装

**[bin/md_render_check.py](../bin/md_render_check.py)**

- **作用**：渲染体检：表格宽度（CJK 按 2 列）、代码块长行、标题跳跃、链接文字、图片引用；退出码 0/1 可进 CI

**[tools/preflight.py](../tools/preflight.py)**

- **作用**：能不能交出去的一次性判定：必需文件、有无密钥、有无超大文件、相对链接是否都指向真实文件、每个 `.py` 能否编译、每个 `.ps1` 是否带 UTF-8 BOM、`test/out` 与 `runtime` 是否漏进版本库。`--strict` 给 CI 用

**[test/render_terminal.py](../test/render_terminal.py)**

- **作用**：把 CLI 输出按真实字宽（CJK 占 2 列）渲染成终端样式图，用于拍窄终端下的列碰撞与断词 —— 这些问题在纯文本里看不出来

**[test/render_markdown.py](../test/render_markdown.py)**

- **作用**：用本机 Edge/Chromium headless 真渲染 Markdown 并截图，带页边墨迹门禁（边缘有墨即说明页面被裁）；用来回答「手机上这表还能读吗」

**[scripts/fetch_runtime.py](../scripts/fetch_runtime.py)**

- **作用**：下载 32 位 embeddable Python 到 `runtime/py32/`（KingDraw 通道的宿主）

**[core/chemdraw_tool/artwork.py](../core/chemdraw_tool/artwork.py)**

- **作用**：出图规格换算与验收：`check()` / `normalize()` / `resolution_for()` / `canvas_pt()`


## 两处需要留意的已知偏差

1. ~~journal-artwork.md §6.2 的反解方向~~ **已于 2026-10-29 修正**：§6.2 现在写的是 `resolution = px_w × 36 / content_width_pt`，§6.3 的参数表加了「Width 只决定画布、不缩放图形」的警告。代码实现是 `artwork.resolution_for(target_px_width, content_width_pt)` 与 `cd_com.export_figure(width_mm=, dpi=)`；对照实验在 PROGRESS.md 的「我的 `artwork.export_args` 是错的」一节。
2. ~~[README.md](../README.md) 顶部的状态行写于 M0~~ **已于 2026-10-29 更新**：状态行现在描述 M1/M2 的实际能力。仍然建议以 `doctor` 的实时输出为准——文档会滞后，`doctor` 不会。

## 写文档的约定

- **每条结论都要能追到证据**：实测写命令与输出，外部规范写 URL + 抓取日期，推断就标「推断」，没验证就标「未验证」。
- **证据等级**沿用 README：A = 本机实测跑通且可复现；B = 接口存在但流程没跑通；C = 来自上游文档或其他机器。
- **不删旧条目**：PROGRESS.md 只追加；文档若被推翻，在该文档里保留原结论并注明「已被 X 推翻」，不要悄悄改掉。
- **新增能力必须让契约对账保持绿色**：同一个能力同时声明在三处 —— `core/chemdraw_tool/mcp_server.py` 的 `TOOLS`、`dsh-plugin/lib/index.js` 的 `defineTool` 注册、`core/chemdraw_tool/cli.py` 的 argparse 子树。加完能力先跑 `python test/test_contract_sync.py`（或 `python tools/contract_sync.py` 看人读版），它把三方的名字/参数/必填项逐条对账，漂移会点名「哪一侧是真相源」。真相源是 **Python 侧**：插件只允许是子集或等价映射（可以改 camelCase、可以把参数落到临时文件再按位置传），但不得调用不存在的子命令或选项、不得声明一个自己从不转发的参数。人工读三份文件不算控制手段。
