# 化学 agent 能力的并集：九个成品能做什么，我们该合成一个什么插件

写于 2026-10-30。目的：把 CC / Codex / DSH 三个生态里所有化学插件的**功能**取并集，
去重、分级、落到「一个 DSH 插件」的工具面上。不看形态，只看到底能干哪些事。

## 0. 取样（九个）

| 来源 | 形态 | 覆盖重心 |
|---|---|---|
| codex-organic-chem | CC+Codex skill + MCP（17 个工具） | 读图、归一化、构象、反应、机理、路线图、审阅、文献 |
| chemdraw-skill | Skill + 760MB Python 运行时 | **最广**：CDX/CDXML、试卷插图、CSV→SAR、TLC、装置、NMR、专利 Markush、Office 嵌入、ChemScript |
| chemdraw-mcp | MCP（PyPI） | 名称→结构（OPSIN/PubChem/NCI）、GHS 安全、官能团高亮、对比、反应式、IR/TLC/滴定/药动曲线、Anki |
| dshchem | DSH 插件（24 工具） | 校验、描述符、能量、逆合成、AiZynthFinder、ADMET、Vina 对接、聚类、MCS、枚举、虚拟筛选 |
| rdkit-mcp-server | MCP | RDKit 原生全套 |
| ChemClaw / scientific-agent-skills / computational-chemistry-agent-skills | 技能库 | 广度聚合 |
| SmiledMCP / PubChem-MCP / ChEMBL MCP | MCP | 数据库检索与相似性 |
| RDKit 社区（Cookbook / rdMolStandardize / RGroupDecomposition / PandasTools / rdchiral） | 库 | 一切确定性化学的底座 |
| 本项目 | DSH 插件（15 工具） | 厂商原生 + 读图 + 投稿版式 + 教学 |

## 1. 能力并集（按「用户想要什么」分组）

标记：`已有` = 本项目已实现；`可加` = RDKit/纯 Python 就能做；`需二进制` = 要外部程序；
`需网络` = 要查库；`厂商` = 必须 ChemDraw/KingDraw。

### A. 结构输入与解析
- SMILES / InChI / Molfile / CDXML / RXN 解析 — 已有
- 名称→结构：英文名、IUPAC、德文俗名、CAS — 需网络（OPSIN / PubChem / NCI）
- 图片→结构（截图、拍照、试卷）— 已有（molvec + decimer 双引擎投票）；可加 OSRA / MolScribe
- 专利 Markush 通式（R 基、可变环、多中心键）→ CXSMILES/V3000 — 可加（难，后置）
- 反应 SMILES 解析（A.B>>C.D）— 已有

### B. 规范化与体检
- canonical / InChI / InChIKey — 已有
- 去盐、取最大片段、电荷中和、互变异构规范化（rdMolStandardize）— 可加
- 价键/芳香性/自由基/同位素/断片检查 — 已有
- 立体化学：R/S 标注、未指定手性提示、立体异构枚举 — 部分已有，`rdCIPLabeler` + `EnumerateStereoisomers` 可补齐
- 原子数/键数/环数/芳香环/可旋转键/TPSA/logP/氢键给受 — 已有（analyze）

### C. 绘图与版面
- 2D 排版出图（PNG/SVG，300/1200 dpi）— 已有（ChemDraw）；可加 RDKit 快通道
- 留白、物理宽度、键长体检（readable）— 已有
- 干净布局 / 重排 / 洗牌（clean up）— 厂商
- 官能团高亮、两结构差异高亮 — 可加（RDKit highlight）
- 反应式（条件文字、原子映射）— 已有
- 多步路线图 / 底物拓展图（scope figure）— 可加
- 机理图：弯箭头、孤对电子、形式电荷、中间体 — 可加（SVG 层手工布局）／厂商（CDXML）
- TLC 板（泳道/斑点/Rf）、装置图 — 厂商（ChemDraw 模板）
- 谱图示意：IR 曲线、滴定曲线、药动曲线 — 可加（matplotlib + RDKit）

### D. 厂商文件
- `.cdx` / `.cdxml` 读写 — 已有（cdxml + CDX 转换）
- 合并 / 拆分 / 清理 / 转格式 — 厂商（ChemScript/COM）
- Word / PowerPoint 内嵌**可编辑**对象 — 厂商（COM），本项目未做
- ChemDraw API 覆盖审计（哪条路走 COM、哪条走 CDXML）— 厂商

### E. 计算
- 描述符、类药性五规则、QED、SA score — 可加
- ADMET 端点（104 项）— 可加（模型依赖，重）
- 相似性（Tanimoto/指纹）、聚类（Butina）、MCS、Murcko 骨架 — 可加
- R-group 分解 / SAR 表（RGroupDecomposition）— 可加
- 枚举（R 基组合）、变体生成 — 部分已有（variants）
- 3D 构象（ETKDG + MMFF）— 已有
- 电荷（Gasteiger/MMFF）、部分电荷标注 — 可加
- 能量：xTB / CREST — 需二进制
- 对接：AutoDock Vina — 需二进制
- 虚拟筛选（批对接 + 汇总）— 需二进制 + 脚本

### F. 反应化学
- 配平 / 原子守恒检查 — 已有
- 原子映射（AAM）— 已有（reaction）
- 条件推荐（试剂/条件族）— 可加（规则库）
- 逆合成：单步断键 — 可加（rdchiral 模板）
- 逆合成：BFS 多步 / AiZynthFinder — 需二进制/模型
- 机理草稿 + 校验 + 渲染 — 可加（规则）

### G. 表征与报告
- 投料表 / 当量 / 理论产率 — 已有（stoich）
- SI 原料表（含过程质量强度）— 可加
- HRMS 表征句、完整表征段落 — 可加（模板 + 计算值）
- 多步路线总产率 — 可加
- 试剂安全提示 / GHS — 需网络（PubChem）

### H. 数据检索
- PubChem 交叉核对（CID/名称/分子式/SMILES/IUPAC/InChIKey）— 部分已有（resolve）
- ChEMBL 生物活性 — 需网络
- Crossref 文献 / PDF 文本提取 — 可加（本机已有 pdf 能力）
- 配方/实验库（跨会话记忆）— 可加

### I. 教学
- 批改（对/错/手性错/异构体/画错）— 已有
- 出题变体（骨架 + 取代基）— 已有
- 联系表 / 作业图 — 已有（batch）
- 试卷插图、讲义插图（ACS Document 1996）— 厂商
- 命名练习（结构→IUPAC）— 需网络

### J. 图像识别（单独列，因为最容易出幻觉）
- 单引擎识别 + 置信度 — 已有
- 双引擎投票 — 已有
- 外接矩形定位、多候选 — 可加
- 人工复核提示（拒绝过度自信）— 已有（warnings）

## 2. 合成一个插件：建议的工具面（19 个）

按「用户意图」命名，不按库命名：

| # | 工具 | 吸收的并集能力 | 实现 |
|---|---|---|---|
| 1 | `chem_parse` | 名称/标识符/图片 → 结构（合并 resolve + ocr） | 已有 + 可加 |
| 2 | `chem_normalize` | 去盐/中和/互变/立体/InChIKey | 可加（rdMolStandardize） |
| 3 | `chem_check` | 价键/芳香/电荷/未指定手性 | 已有 |
| 4 | `chem_draw` | 2D 出图（引擎阶梯、留白、dpi、宽度） | 已有 + 可加 |
| 5 | `chem_edit` | CDX/CDXML 合并/拆分/清理/高亮/对比 | 厂商 |
| 6 | `chem_reaction_figure` | 反应式 + 路线图 + scope 图 | 已有（reaction）+ 可加 |
| 7 | `chem_mechanism` | 机理草稿/校验/弯箭头渲染 | 可加 |
| 8 | `chem_props` | 描述符/药性/QED/SA/ADMET | 已有（analyze）+ 可加 |
| 9 | `chem_compare` | 相似性/MCS/聚类/骨架/R-group | 可加 |
| 10 | `chem_sheet` | 联系表 / SAR 表 / CSV→图 | 已有（batch）+ 可加 |
| 11 | `chem_enum` | 变体/立体异构/R 基枚举 | 已有（variants）+ 可加 |
| 12 | `chem_conformer` | 3D/构象/电荷/能量(xTB) | 已有（3d）+ 需二进制 |
| 13 | `chem_retro` | 单步断键 / BFS / 条件推荐 | 可加 + 需二进制 |
| 14 | `chem_stoich` | 配平/投料/产率/SI 表 | 已有 |
| 15 | `chem_characterize` | HRMS/表征段落/报告 | 可加 |
| 16 | `chem_lookup` | PubChem/ChEMBL/文献/PDF | 部分已有 |
| 17 | `chem_exam` | 批改/出题 | 已有 |
| 18 | `chem_office` | Word/PPT 嵌入可编辑对象 | 厂商 |
| 19 | `chem_close` | 收工关窗 | 已有 |

## 3. 落地顺序

- **P0（一周内，全部 RDKit，不碰 GUI）**：normalize、props 补全、compare、enum 立体、sheet、check 加强、
  draw 的 RDKit 快通道。验收：每项都有确定性断言，不依赖 ChemDraw。
- **P1（厂商原生差异）**：edit（CDX 合并/拆分/清理）、office（Word/PPT 嵌入）、mechanism 的 CDXML 输出。
- **P2（重依赖）**：retro（rdchiral→AiZynthFinder）、conformer 的 xTB、ADMET、对接。

## 4. 与现状的差

现 15 个工具里 9 个可原地升级到并集；缺的是 normalize / compare / mechanism / characterize /
office / edit / retro 六块。换句话说：**并集不是再造，是在现有骨架上补六块 + 收敛命名。**

## 5. 不做

- MCP：DSH 不需要，一个插件足够（用户明确决定）。
- 自己实现化学：全部走 RDKit / 厂商。
- 逆合成与对接自研：有现成二进制/库就用，没有就不做。
