# 前人做到哪一步了：CC / Codex / DSH 三个生态的化学插件调研

写于 2026-10-30。目的不是证明这个项目有独创性 —— 恰恰相反，是为了先承认重叠，
再决定剩下的活该怎么干。

结论先放这里：

1. Claude Code 与 Codex **都有插件市场**，而且都在 2026 年内成型。我上一轮说
   「它们只有 skill」是错的，检索方法也错了（见第 2 节）。
2. 有机化学的**成品**至少四个，而且和我高度重合：`codex-organic-chem`
   （Codex + Claude Code 双技能 + MCP + OCSR）、`chemdraw-skill`（ChemDraw 原生，
   星最多）、`dshchem`（DSH 原生，24 个 chem_* 工具）、`ToolUniverse`（哈佛，
   通用科学工具箱，已在 CC 插件市场上架）。
3. 本项目唯一没有被别人同时占住的组合是：**厂商原生文件（.cdx/.king）的双向闭环
   + 投稿级尺寸体检 + 教学向批改**。其余能力都是别人的既有能力。
4. 面向本科生做通用插件是**合理方向**，但必须换载体：本地 Python 引擎 + MCP
   是三个生态通用的最小公倍数，DSH 插件只能算其中一个外壳。

---

## 1. 三个生态的插件机制（可以直接对照的）

| | Claude Code | Codex | DSH |
|---|---|---|---|
| 分发单元 | 插件（marketplace.json + `.claude-plugin/`）+ Skill + MCP server | 插件目录 + Skill（`.agents/skills`）+ MCP server | `dsh plugin add link:<路径>`，bundle + cordis.patch.yml |
| 市场形态 | 官方 marketplace + 社区 awesome 列表 | 官方目录（约 75 个插件 / 11 类）+ 社区 awesome | dsh-market / awesome-dsh-plugin / 创意工坊 |
| 能力挂载点 | commands / agents / hooks / skills / .mcp.json | skills / MCP / 命令 | tools / slots（客户端 UI）/ 预设 |
| 化学落点 | 插件上架，或 MCP 直连 | 同上 | 插件 + 预设 |

关键差别：**CC 与 Codex 的插件都以「文件树 + MCP」为契约，DSH 以 cordis 服务为契约。**
所以一个只写 DSH 插件的项目，天然进不了另外两个市场 —— 这是本项目最大的结构性短板。

## 2. 我上一轮为什么没找到（方法论错误，值得记下来）

- 我用能力词检索（"chemistry mcp"、"rdkit mcp"），没有用**生态词**检索
  （plugin / marketplace / awesome / catalogue / 目录）。
- 我只查了 GitHub 搜索，没有查**市场本身**：`awesome-claude-code-plugins`、
  `awesome-codex-plugins`、`awesome-codex-cli`、官方 marketplace 文档。
- 我把「skill」和「plugin」当成互斥的两件事；实际是 2026 年两者已经融合
  （插件里带 skill，skill 里带 MCP server）。
- 中文检索缺失：`dshchem`、`chemdraw-skill` 这类项目主要靠中文 README 被发现。

## 3. 已存在的成品

| 项目 | 形态 | 覆盖 | 备注 |
|---|---|---|---|
| [LaoZhong-Mihari/codex-organic-chem](https://github.com/LaoZhong-Mihari/codex-organic-chem) | Codex + Claude Code 双 skill + 本地 CLI + MCP server | OCSR 适配器、RDKit 归一化/绘图/描述符/构象/电荷、Open Babel / xTB / CREST、反应合理性检查、逆合成提示、条件族、机理草稿、Ketcher/ChemDoodle 集成的审阅 UI | **和我最像**，但走 MCP，不碰厂商软件 |
| [ZiChenWang114514/chemdraw-skill](https://github.com/ZiChenWang114514/chemdraw-skill) | Skill（Claude Code / Codex / Gemini CLI / Copilot / Cursor），★34，MIT，有 CI 与官网 | ChemDraw 原生可编辑结构、论文图重建、SAR 面板、Word/PPT 活对象、称量、原子映射 | **厂商路线的天花板**，跨 agent 分发做得完整 |
| [cloudbywu/dshchem](https://github.com/cloudbywu/dshchem) | DSH 插件 + agent 预设 + skills | 24 个 `chem_*" 工具：校验/描述符/PubChem/能量/反应/配方库/文献/PDF/逆合成（含 AiZynthFinder）/官能团/试剂/类药性/相似性/聚类/MCS/枚举/ADMET/Vina 对接/虚拟筛选 | DSH 里唯一的成体系成品 |
| [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | CC 插件市场条目 + 通用科学工具集 | 600+ 科学工具，化学只是其中一类 | 「大而全」的另一条路 |
| jurimaxam-dotcom/chemdraw-mcp | MCP（PyPI 0.4.0） | 名称/SMILES → 投稿级 2D、反应式 | 最小可用切片 |
| InternScience/ChemClaw、K-Dense-AI/scientific-agent-skills、jinzhezenggroup/computational-chemistry-agent-skills | 技能库 | 广度优先 | 靠聚合取胜 |

## 4. 差距矩阵（本项目 vs 四个直接对手）

| 能力 | 本项目 | codex-organic-chem | chemdraw-skill | dshchem |
|---|---|---|---|---|
| 安装载体 | DSH 插件（cordis） | Skill + MCP | Skill | DSH 插件 + 预设 |
| 跨 agent 可用 | 否 | 是（Codex + CC） | 是（6 个外壳） | 否 |
| 默认渲染 | ChemDraw/KingDraw（要窗口，1.5–2.3 s） | RDKit（0.015 s，无窗口） | ChemDraw | RDKit |
| 厂商原生文件 .cdx/.king | 有（双向） | 无 | 有（.cdx） | 无 |
| 图像→结构 | molvec + decimer 双引擎投票 | OCSR 适配器 | DECIMER/OPSIN | 无 |
| 投稿尺寸/留白/键长体检 | 有 | 无 | 部分 | 无 |
| 逆合成 / 对接 / ADMET | 无 | 逆合成提示、机理草稿 | 无 | 有（AiZynthFinder/Vina） |
| Word/PPT 活对象 | 无 | 无 | 有 | 无 |
| 教学向（批改、出题、配平） | 有 | 无 | 无 | 无 |
| 自动化验收 | 8 场景 + 22 套件 | CI | CI + validate 工作流 | 有 CI |
| 对外分发 | 无（本机） | GitHub | GitHub + PyPI + 官网 | GitHub |

一句话：**我的强项是「厂商文件 + 读图 + 交付体检 + 教学」，弱项是「载体、广度、分发」。**

## 5. RDKit 社区该站在哪

本科生向的通用插件不该自己实现化学。该直接站在这些成熟件上：

- `rdkit.Chem.Draw.rdMolDraw2D` —— PNG/SVG 渲染，300/1200 dpi 可控，0.015 s/分子。
- `rdMolStandardize` —— 归一化、最大片段、电荷修正，回答「这个 SMILES 到底对不对」。
- `RGroupDecomposition` / `MurckoScaffold` —— SAR 表、母核拆解，正是本科毕设常问的。
- `PandasTools` —— 一批分子 ↔ DataFrame，作业图与批量属性天然对齐。
- `EnumerateStereoisomers` / `rdCIPLabeler` —— 手性、R/S 标注，教学刚需。
- `rdchiral` / `rdChemReactions` —— 反应模板、断键、原子映射。
- `Descriptors` / `Crippen` / `Lipinski` —— 性质与类药性五规则。
- RDKit Cookbook 与 `rdkit-devel` 邮件列表仍是「某个 API 到底怎么用」的最快答案。

## 6. 面向本科生的通用插件：方案

### 6.1 他们要的其实是六件事

1. 把结构画成**能交的图**（作业、报告、论文）。
2. 判断**这张图是什么分子**（截图、拍照、别人给的图）。
3. 判断**这个反应对不对、配没配平**。
4. 问**这个分子什么性质**（分子量、logP、氢键、手性）。
5. **一次出一套**（作业图、SAR 表、对比图）。
6. **被批改**（对/错、手性错、异构体）。

### 6.2 MVP（本轮可做）

- **载体**：本地 Python 引擎 + `bin/chem` CLI + 一个 MCP server（stdio），DSH 插件与
  CC/Codex 都只是它的外壳。
- **引擎阶梯**：RDKit 默认（无窗口、毫秒级）；ChemDraw 只在需要 `.cdx`/EPS/TIF
  或 RDKit 布局体检不过时升级；KingDraw 仅在无 ChemDraw 时兜底。
- **五个动词**：`draw`（含留白与键长体检）、`read`（图→结构，双引擎投票）、
  `check`（价键/芳香/电荷/立体）、`props`（性质表）、`sheet`（联系表/SAR 表）。
- **交付物**：PNG/SVG（默认）+ .cdx（要导师签字那种）+ 一张 CSV 性质表。

### 6.3 不做

- 不做逆合成/对接/ADMET（dshchem 已做且更专业，重复投入没有回报）。
- 不自己实现化学算法（RDKit 已覆盖）。
- 不做「万金油 agent」，只做「把化学做对、把图交得出去」。

## 7. 立即可执行的三步

1. 把引擎阶梯落地：`draw` 默认 RDKit，`--engine chemdraw` 显式升级。验收脚本同步。
2. 抽出 MCP server（约 200 行，复用现有 CLI），让 CC / Codex / DSH 三头可用。
3. 仓库推到 GitHub，附一份对照本文件的能力矩阵 —— 承认重叠，比假装首创更有说服力。
