# 能力全集 v3 —— 12 族 64 项，逐项给实现与可行性

写于 2026-10-30。v1 是 19 类粗表，v2 是施工方案，v3 是你指出「漏得太多」之后的补全。
本机实测（Python 3.11 / RDKit 2026.09.1）：`sklearn 1.9.0`、`scipy 1.17.1`、`matplotlib 3.10.8`、
`openpyxl 3.1.5`、`python-docx 1.2.0` 全部已装；RDKit 28 个能力子模块 25 个可用；
对乙酰氨基酚互变异构枚举实测出 6 个。

## A. 结构表示与注册（8）

| 能力 | 实现 | 本地 | 入插件 |
|---|---|---|---|
| 多格式互转（SMILES/InChI/Mol/SDF/XYZ/PDB/CDXML/CML/RXN/PDBQT/Mae） | RDKit + Open Babel | ✅ | ✅ |
| 标准化管线（去盐、中和、最大片段、金属断开） | rdMolStandardize | ✅ | ✅ |
| **互变异构枚举 + tautomer-aware 去重** | TautomerEnumerator（实测 6 个） | ✅ | ✅ |
| 结构注册与去重（InChIKey 全层/骨架层） | RDKit | ✅ | ✅ |
| 名称→结构（IUPAC/俗名/缩写/CAS） | OPSIN jar + 内置表 | 需 Java 25（已有） | ✅ |
| **结构→IUPAC 名** | STOUT / ChemAxon（商业） | 需 torch 模型 | ⚠️ 可选 |
| 分子式与元素组成（含 DBE、氮规则、同位素分布模拟） | 纯 Python + RDKit | ✅ | ✅ |
| 肽/核苷/糖序列（HELM、氨基酸序列→SMILES） | 自写模板 + RDKit | ✅ | ✅ |

## B. 检索与相似性（7）

| 能力 | 实现 | 本地 | 入插件 |
|---|---|---|---|
| 精确检索 / 按 ID 检索 | SQLite + 索引 | ✅ | ✅ |
| 子结构检索（SMARTS、递归 SMARTS） | RDKit | ✅ | ✅ |
| 相似性检索（ECFP/MACCS/原子对/拓扑扭转/pharm2D + Tanimoto） | rdFingerprintGenerator | ✅ | ✅ |
| 大库相似检索（百万级，FPSim2 索引） | fpsim2 0.7.4 | ✅ | 可选组 |
| 聚类与多样性挑样（Butina、层次、骨架聚类） | RDKit | ✅ | ✅ |
| MCS / 骨架 / 通用核心 | rdFMCS + Scaffolds | ✅ | ✅ |
| MMP（匹配分子对）与活性悬崖 | mmpdb 3.1.6 | ✅ | 可选组 |

## C. 描述符与性质（7）

| 能力 | 实现 | 本地 |
|---|---|---|
| 基础描述符（MW/精确质量/logP/TPSA/HBD/HBA/可旋转键/环系/sp3/复杂度） | RDKit | ✅ |
| 药化过滤（Lipinski/Veber/QED/SA/MPO/PAINS/BRENK/Lilly） | RDKit + 规则表 | ✅ |
| 图论描述符（Wiener/Zagreb/Balaban/自相关/BCUT） | RDKit CalcAUTOCORR2D 等 | ✅ |
| 3D 描述符（PMI/NPR/回转半径/SASA/体积） | RDKit + rdFreeSASA | ✅ |
| **pKa / logD（pH 依赖）** | 经验规则 + 可选模型 | ⚠️ 近似 |
| 元素分析与 HRMS 文本（[M+H]+ 精确到 4 位小数） | 纯 Python | ✅ |
| 批量表（CSV/SDF → 描述符矩阵 → 排序筛选） | pandas | ✅ |

## D. 立体、构象与 3D（5）

| 能力 | 实现 | 本地 |
|---|---|---|
| CIP 标记、未定义手性检测、E/Z | rdCIPLabeler | ✅ |
| 立体异构枚举（含手性拆分计数） | EnumerateStereoisomers | ✅ |
| 3D 嵌入 + MMFF/UFF 优化 + 能量 | AllChem | ✅ |
| 构象集合：生成、聚类、RMSD、叠合 | rdMolAlign / rdMolTransforms | ✅ |
| 形状与药效团（Gobbi/2D ph4、形状 Tanimoto） | Pharm2D / rdShapeHelpers | ✅ |

## E. 反应与合成（6）

| 能力 | 实现 | 本地 |
|---|---|---|
| 配平、原子守恒、当量/投料/产率 | 纯 Python（已有） | ✅ |
| 反应 SMARTS、RXN 文件、反应枚举（库生成） | rdChemReactions | ✅ |
| 原子映射（图变换） | ReactionFromSmarts + 可选 RXNMapper | ✅ / 可选 |
| 单步逆合成（模板断键） | rdchiral 1.1.0 | ✅ 可选组 |
| 多步路线搜索 | AiZynthFinder 4.4.1 | ✅ 可选组（要模型） |
| 反应分类 / 产率 / 条件推荐 | 规则 + 可选 ML | ⚠️ 弱 |

## F. 数据与建模（6）

| 能力 | 实现 | 本地 |
|---|---|---|
| 数据清洗（去重、标准化、缺失、异常） | ChEMBL 管线思路 + pandas | ✅ |
| 描述符矩阵 → 模型训练（RF/XGB/线性/chemprop） | sklearn 1.9.0 | ✅ |
| 划分策略（随机/骨架/scaffold split/分层）+ 交叉验证 | sklearn + RDKit 骨架 | ✅ |
| 指标与解释（R²/MAE/AUC、SHAP、适用域） | sklearn + 自写 AD | ✅ |
| 高通量实验数据分析（板图、Z'、CV%、IC50 四参数拟合、归一化） | scipy.optimize | ✅ |
| 生成与优化（REINVENT 需 torch；枚举式库设计可本地做） | — | ⚠️ 半边 |

## G. 谱学与分析（5）

| 能力 | 实现 | 本地 |
|---|---|---|
| NMR 谱处理（FID→谱、相位、基线、寻峰、积分） | nmrglue 0.12 | ✅ 可选组 |
| 质谱谱库匹配（余弦/加权余弦、中性丢失） | matchms 0.33.1 | ✅ 可选组 |
| 分子式反推（精确质量 + 同位素模式 + 规则） | 纯 Python | ✅ |
| NMR 化学位移预测 | nmrshiftdb2/HOSE 需数据；DFT 需量化 | ⚠️ 弱 |
| IR/Raman、UV-Vis 预测 | 无成熟开源 | ❌ |

## H. 安全与合规（3）

| 能力 | 实现 | 本地 |
|---|---|---|
| 结构警示（爆炸性、过氧化物、反应性基团） | 规则表（SMARTS） | ✅ |
| GHS/SDS 查询 | PubChem GHS（需网络，可缓存） | ⚠️ |
| 危险试剂/废液提示 | 内置表 | ✅ |

## I. 绘图与交付（6）

| 能力 | 实现 | 本地 |
|---|---|---|
| 2D 出图（宽度/dpi/留白/高亮/原子编号/差异对比） | RDKit + ChemDraw | ✅ |
| 反应式与多步路线图、scope 图 | RDKit 模板 + ChemDraw | ✅ |
| 机理弯箭头（电子推动） | 自写 SVG 层 | ✅ |
| TLC 板 / 装置图 / 联系表 | 自写渲染 | ✅ |
| 投稿级规格（期刊宽度、dpi、字体、三线表、SI 表） | 已有 | ✅ |
| Word/PPT 内嵌可编辑对象、CDX 合并拆分 | ChemDraw COM | ✅（已有 ChemDraw） |

## J. 实验与自动化（4）

| 能力 | 实现 | 本地 |
|---|---|---|
| 加样表/稀释序列/板图生成（96/384 孔） | 纯 Python | ✅ |
| Opentrons 协议产出（Python 脚本） | 模板生成 | ✅ |
| HPLC 梯度/溶剂换算、TLC Rf | 纯 Python | ✅ |
| 真实机械臂执行 | 硬件 | ❌ |

## K. 教学与评测（3）

| 能力 | 实现 | 本地 |
|---|---|---|
| 批改（结构/命名/反应/计算题） | RDKit + OCSR（已有） | ✅ |
| 出题变体与联系表、答案断言 | 已有 | ✅ |
| 基准评测（ChemBench 风格） | 自建小集 | ✅ |

## L. 外部世界（4）

| 能力 | 实现 | 本地 |
|---|---|---|
| PubChem / ChEMBL / Crossref / 专利检索 | HTTP + 本地缓存 | 需网络 |
| 文献 PDF 抽取（结构图 + 文本 + 表格） | OCSR + pdfplumber | ✅ |
| 蛋白-配体对接 | Vina/GNINA | ❌ 需二进制 |
| 量子化学 | xTB/Psi4 | ❌ 需二进制 |

---

## 工具面：19 → 26

新增 7 个：`chem_db`（本地库：导入/ID/子结构/相似检索）、`chem_ml`（训练/验证/预测/解释）、
`chem_table`（批量表 + 高通量数据分析）、`chem_fingerprint`（指纹与相似矩阵）、
`chem_tautomer`（互变异构枚举与规范化）、`chem_formula`（分子式/DBE/同位素/HRMS）、
`chem_assay`（板图/加样表/IC50 曲线）。

`chem_props` 吸收药化过滤与图论描述符；`chem_parse` 吸收名称解析与序列→结构；
`chem_compare` 吸收聚类/MMP/MCS；`chem_exam` 吸收自建评测集。

## 估时（修订）

| 阶段 | 内容 | 估时 |
|---|---|---|
| W0–W1 | 运行时 + 改名迁移 | 7 h |
| W2 | P0 核心（normalize/props/compare/enum/sheet/check/draw） | 12 h |
| W3 | db + fingerprint + table（课程第 03/05 讲的能力） | 10 h |
| W4 | ml + assay（建模与高通量数据分析） | 10 h |
| W5 | 面板 5 组 + 26 工具接线 | 8 h |
| W6 | mechanism / characterize / reaction_figure / formula | 10 h |
| W7 | edit / office / tautomer / parse 扩展 | 8 h |
| W8 | retro / lookup / spectra（可选组） | 10 h |
| **合计** | | **≈ 75 h ≈ 9–10 个工作日** |

## 边界（明确不做）

1. 量子化学、对接——需外部二进制，缺就不做（用户已定：只做本机能跑的）。
2. 真实机械臂执行——硬件。
3. IR/UV 预测——没有可用开源模型。
4. 结构→IUPAC 名——需 torch 模型，非默认。
