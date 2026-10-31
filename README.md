# dsh-chem

**把化学工具交给 agent，学生说人话，拿回来能直接交的图、表和文档。**

一个 DSH 宿主插件（15 个工具）+ 一个 Python 引擎（独立 venv）。分子识别、性质计算、出图、
配平投料、批改、检索建库、谱图核对、逆合成断键都在本机跑；联网只有「按名称查结构」一个可选开关。

> 状态：15/15 工具实现完毕，全部有自动化断言。最后一次全量验证见 [docs/验收报告.md](docs/验收报告.md)。
>
> 本仓库是**源码 + 引擎 + 插件**三件套；插件通过 `link:` 接进 DSH，引擎跑在
> `%LOCALAPPDATA%/dsh-chem/runtime` 的独立 venv 里，装一次之后离线可用。

## 一次调用给一个结果（本机实测值，不是示意）

| 你说什么 | 工具 | 实际拿回来 |
|---|---|---|
| 乙醇的分子量 | `chem_props` | MW 46.069、C2H6O、`LFQSCWFLJHTTHZ-UHFFFAOYSA-N`，约 300 ms |
| 苯酚画成 ACS 单栏 | `chem_draw` | 1004×723 px PNG、27 504 B；`format=pdf` 出向量 PDF 1 457 B |
| 10 mmol 酯化要称多少 | `chem_calc` | 乙酸 600.52 mg + 乙醇 460.69 mg → 乙酸乙酯 881.06 mg + 水 180.15 mg，质量闭合 |
| 阿司匹林是什么结构 | `chem_parse` | C9H8O4、`BSYNRYMUTXBXSQ-UHFFFAOYSA-N`（本地字典，不联网） |
| 出一份实验报告 | `chem_office` | 57 378 B docx，600 dpi 图 + 图注 + 正文 |
| 期刊要 EPS | `chem_vendor` `do=eps` | 5 038 B、`%!PS` 头，走 ChemDraw 26.1 |
| 我这台装了 ChemDraw 没 | `chem_vendor` `do=probe` | `ChemDraw_x64.Application` → ChemDraw Professional 26.1.0.6327 |

把这些数字写出来，是因为它们能被复现：同一条命令在装了插件的机器上重跑，结果一致。

## 跑得起来的条件

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | Windows x64 | COM 通道、注册表探测、`mklink /J` 都是 Windows 专有 |
| Python | 3.11 / 3.13（实测） | `bin/setup.py` 建独立 venv，不碰系统环境 |
| DSH | 声明兼容 `0.2.0-rc.2`、`0.2.1-rc.3` | 见 `dsh-plugin/package.json` 的 `dsh.compatibility` |
| RDKit | 必需 | 结构解析、性质、出图、大部分断言都靠它 |
| ChemDraw | 可选 | 只在 EPS、PNG 预览、cdx 时用到；没装会返回 `needs-vendor` 并给替代方案 |
| KingDraw | 可选，当前未接通 | 本机没有可验证的 ProgID，能探测到但驱动不了 |
| 联网 | 仅一个开关 | `chem_parse` 查不到本地字典时才走 PubChem，默认不开 |
| 看图读结构 | 需要识别模型，不随仓库分发 | 模型放 `%LOCALAPPDATA%\dsh-chem\models`；缺模型时 `chem_parse kind=image` 会说明缺哪个引擎，其他工具不受影响 |

## 为什么不是又一个画图脚本

学生真正会说的需求长这样：「帮我把这两个分子画成 ACS 单栏、300 dpi 的投稿图」「这张截图里的结构是什么」
「这十个人的作业判一下」「10 mmol 酯化要称多少」「这批结构的 logP 列个表」「这六个峰和这个结构对得上吗」。
这些需求里没有一个是「画一条键」，全都是「一次要一个结果」。

所以工具的切法按**结果**切，不按 API 切：

| 工具 | 学生怎么问 | 拿回来什么 |
|---|---|---|
| `chem_parse` | 「看看这张图 / 这个中文名是什么结构」 | SMILES、InChIKey、分子式，以及**哪个识别器给的、要不要人工确认** |
| `chem_clean` | 「这个结构有问题吗」 | 体检报告 / 规范化后的结构（盐、电荷、互变异构、PAINS 警示） |
| `chem_draw` | 「画成期刊单栏，矢量」 | PNG / SVG / **向量 PDF** / TIFF，附**实测**键长、留白、物理尺寸；`view=3d` 出构象 |
| `chem_props` | 「它的分子量和精确质量」 | 分子式、MW、exact mass、logP、TPSA、QED 等 |
| `chem_calc` | 「配平 / 10 mmol 要称多少 / HRMS 怎么写」 | 系数、各物质量、质量闭合校验、可抄进实验报告的谱学文字 |
| `chem_compare` | 「这两个有多像 / 分几类」 | Tanimoto、MCS、聚类、SAR 表 |
| `chem_table` | 「这批结构列个性质表 / 拟合 IC50」 | 表格、4PL 拟合参数 |
| `chem_db` | 「我库里哪些含这个骨架」 | SQLite：子结构 / 相似性 / 性质区间检索，SDF·CSV 导入导出 |
| `chem_ml` | 「用这批数据建个预测模型」 | 交叉验证指标（真实折外预测）+ 适用域判断 |
| `chem_enum` | 「这个骨架做一套衍生物 / 有几个立体异构」 | 组合库（去重）、立体异构体、互变异构体 |
| `chem_retro` | 「这个酯从什么原料来」 | 断键方案 + 前体结构（13 条教学级模板，可展开两步） |
| `chem_spectra` | 「我测的峰和这个结构对得上吗」 | 1H/13C/IR/MS 估算表 + **峰比对**报告（哪些峰解释不了） |
| `chem_exam` | 「这十份作业判一下」 | 逐份判定（正确 / 立体化学错 / 互变异构 / 同分异构 / 取代基不同 / 不对）+ Word 报告 |
| `chem_office` | 「生成实验报告 / SI 表 / 汇报页」 | Word（图 + 图注 + 正文）、SI 表（docx + xlsx）、PPT；`target=docx\|pptx\|si-table` + `path=` |
| `chem_vendor` | 「跟 ChemDraw 换文件 / 我这装了没」 | `do=probe` 报实测能力；CDXML·SDF·MOL 本地读写、合并、拆分；EPS 与预览走 ChemDraw |

## 一条命令装起来（陌生人从零）

前置：Windows x64、Python 3.11+（`python` 能在命令行里跑）、DSH 0.2.0-rc.2 或更新。
ChemDraw 不是必需的——装了就多出 EPS / PNG 预览 / cdx 探测。

```
git clone https://github.com/hyzszyh/dsh-chem.git
cd dsh-chem
python bin/setup.py            # 建独立 venv（%LOCALAPPDATA%\dsh-chem\runtime），装 RDKit 等 → 约 300 MB
python tools/install_plugin.py # 复制进 ~/.dsh/plugins/dsh-chem，并自动改 profile 接线
```

`bin/setup.py` 最后会打印一份 JSON：`ok: true` 表示九个核心包全部 import 成功；
`ok: false` 会带 `hint` 和失败的 `steps`（最常见是网络或版本约束）。

`tools/install_plugin.py` 做三件事，缺一不可：把插件和引擎复制到 `~/.dsh/plugins/dsh-chem`；
在 `<profile>/node_modules` 建到它的目录联接（宿主按这个路径解析 bundle）；在 profile 的
`package.json` 里补 `dependencies.dsh-chem` 与 `dsh.profile.bundles`（第一次改动会留一份
`package.json.dsh-chem-backup`）。所以**不需要手改任何配置**。

**装完重开 DSH**，右栏出现「化学绘图」面板，模型侧多出 15 个 `chem_*` 工具。

自查三连（都是只读，不改任何东西）：

```
python tools/install_plugin.py --check          # 已装副本与源码逐文件比哈希
python ~/.dsh/plugins/dsh-chem/engine/bin/chem.py selfcheck   # 解释器、包版本、SVG→PDF
python tools/publish_scan.py                    # 本机标识扫描（维护者用）
```

卸载：`python tools/install_plugin.py --remove`（同时把 profile 里的接线撤掉）。


安装后的样子——**工作区删掉也能跑**：

```
~/.dsh/plugins/dsh-chem/
    lib/            index.js engine.js sidebar-bridge.js client.js
    engine/bin/     chem.py
    engine/core/    chem/**.py chemdraw_tool/**
    node_modules/   @deepseek-ai/dsh-tools（2 KB 桩，自动加载用）
    data ->         %LOCALAPPDATA%/dsh-chem（junction：venv、库、模型）
```

接线（在 `~/.dsh/profiles/desktop/package.json` 里改一行，bundles 里保持 `dsh-chem`）：

```
"dependencies": { "dsh-chem": "link:C:/Users/<you>/.dsh/plugins/dsh-chem" }
```

装好之后自检（不需要源码目录）：

```
python ~/.dsh/plugins/dsh-chem/engine/bin/chem.py selfcheck
# {"ok": true, "checks": [mw 151.16, formula C8H9NO2, png 9754 B, svg_to_pdf 1630 B], ...}
```

`engine.js` 两种布局都认：`<plugin>/engine/bin/chem.py` 优先，找不到才回源码仓库。
所以同一份文件在 D 盘开发和安装后都能用，不需要为安装打补丁。

重开 DSH 后，右栏出现「化学绘图」面板，模型侧多出 15 个 `chem_*` 工具。

## 验证怎么做的

不靠「看起来对了」，靠数字。每层都有可重复的命令：

| 层 | 命令 | 断言数 |
|---|---|---|
| 引擎单元 | `python test/run_py.py` | 364 条断言（15 个套件） |
| 插件契约 | `node test/w1_plugin_contract.mjs` | 94 条（工具名、描述、参数、端到端执行） |
| 面板桥 | `node test/w8_bridge.mjs` | 14 条（白名单、转发、产物、路径穿越） |
| 接线 | `node test/w9_wiring.mjs` | 10 条（按 profile 链接的路径真加载、真执行） |
| 面板契约 | `node test/w10_panel.mjs` | 14 条（端点、动词、字段一致性、v2 残留文案） |
| 安装副本 | `node test/w11_install.mjs` | 10 条（副本自带引擎、入口不指向源码、profile 按包名解析、真调一次） |
| 用户场景 | `python test/scenarios.py` | 9 个场景 / 32 条检查 |
| 仓库体检 | `python tools/preflight.py` | 12 项（文档数字与代码一致、无逃逸序列等） |

所有测试的路径都从文件自身推导：把仓库 `git archive` 到另一个目录照样跑（已验，见下）。

几个实测数字（本机，RDKit 2026.09.1、Python 3.13.5）：

- 对乙酰氨基酚：MW 151.165，exact mass 151.063329，[M+H]+ 152.0706，InChIKey `RZVAJINKPMORJF-UHFFFAOYSA-N`
- ACS 单栏 82.6 mm：300 dpi → 976 px；600 dpi → 1951 px；向量 PDF 页宽 **234.1 pt**
- 自己画的 85 mm 图再读回来：DECIMER 命中同一个 InChIKey（首次约 71 s，含模型加载）
- 酯化 10 mmol：乙酸 600.52 mg + 乙醇 460.69 mg → 乙酸乙酯 881.06 mg + 水 180.15 mg，质量闭合
- 9 个场景（投稿图 / 看图 / 批改 / 配平 / 出题 / 性质表 / 报告 / 库+模型 / 谱图+逆合成）全部通过

## 诚实的边界

这些都是**实测过的限制**，写在这里而不是藏进 issue：

- **二进制 `.cdx` 写不出**：本机 ChemDraw 26.1 的 `SaveAs()` 对 cdx 是静默空操作（换路径、换格式都试过），
  所以 `do=cdx-write` 直接返回 `vendor-save-failed` 并提示改用 cdxml，不假装成功。
- **EPS 与 PNG 预览要 ChemDraw**：装了就能出（实测 EPS 5 038 B、预览 3 096 B，连跑 3 次一致）；
  没装则返回 `needs-vendor` 并建议改用 `chem_draw format=pdf`（PyMuPDF 保证真矢量）。
- **探测 ProgID 只认 64 位名字**：本机是 `ChemDraw_x64.Application`；不带后缀的 `ChemDraw.Application`
  是 32 位名字，只会报「无效的类字符串」——只认旧名字的检测会把装好的 ChemDraw 判成没装。
- **Word/PPT 里没有可编辑的 ChemDraw OLE 对象**：缺复合文档写入能力，目前是 600 dpi PNG + 图注；
  要可编辑就把 cdxml 交给 ChemDraw。
- **NMR 是规则估算，不是预测**：1H ±0.3 ppm、13C 只给区间，输出里每次都写明。
- **逆合成是 13 条断键模板**：覆盖常见教学反应，不是全合成搜索；没命中会明说模板库不够。
- **MolVec 在本工具自绘的 PNG 上会崩**：所以单引擎结果一律标「需人工确认」；DECIMER 那条路是准的。
- **KingDraw 通道未接通**：ProgID 在本机没有 `LocalServer32`，没有可验证的驱动方式。

## 目录

```
bin/            chem.py（引擎入口）、setup.py（venv 引导）
core/chem/      引擎本体：parse clean draw props calc compare table db ml enum retro spectra exam office vendor
dsh-plugin/     DSH 宿主插件（15 工具）+ 右栏面板 + 回环桥
test/           15 个引擎套件 + 4 个 JS 契约/桥/接线测试 + 9 场景验收
tools/          preflight 体检、publish_scan 发布前脱敏扫描、sanitize_paths 路径通用化
docs/           架构、决策、工程预期、验收报告、路线图、发布说明
```

## 发布

推之前跑三条，任何一条不是 0 就别推：

```
python tools/publish_scan.py     # 用户名 / 盘符路径 / 临时目录 / 密钥 在 tracked 文件里必须为 0
python tools/preflight.py        # 文档里的数字与代码一致（工具数、套件数、文件名）
python test/run_py.py            # 引擎断言
```

推送。先说清楚这台机器的现实：`github.com:443` 连不上（21 秒超时），`api.github.com` 通（300 ms），
所以 `git push` 走不通，但 REST API 走得通。仓库里带了一个实测可用的替代路径：

```
python tools/push_via_api.py --repo <owner>/<name> --branch main --tag v0.2.0
```

它按 Git Data API 走 blob → tree → commit → ref：只上传远端还没有的 blob（blob id 就是内容 SHA-1，
已在远端的不重复上传；第二次推送只传了 2 个 blob，第三次 1 个）。远端生成的提交与本地 SHA 不同——
内容一致，靠末尾那次 `tree` 比对证明；要看提交本身就去网页，`git fetch` 在本机网络下用不了。
已在远端的不重复上传），最后核对远端 tree 与本地 `HEAD^{tree}` 是否一致。令牌取自 `GITHUB_TOKEN`
或 `git credential fill`，不落盘、不打印。

网络正常时的常规做法：

```
git tag -a v0.2.0 -m "dsh-chem 0.2.0"
git remote add origin git@github.com:<you>/dsh-chem.git
git push -u origin main --tags
```

两条要知道的：

- **历史里还有早期路径**：`publish_scan.py` 会把 tracked 文件和历史分别计数。当前树是 0；旧提交里仍有
  本机工作区名与登录名，要彻底清掉只能 `git filter-repo` 重写历史。只 clone 最新代码使用不受影响。
- **客户端面板只在宿主启动时加载**：装完或升级后要重开 DSH，否则右栏还是旧 bundle。

许可证：MIT（见 [LICENSE](LICENSE)）。
