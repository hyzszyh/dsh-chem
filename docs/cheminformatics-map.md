# 化学信息学能力地图 × 现有实现（Python / Agent 生态）

写于 2026-10-30。两件事：**表一** 这个领域到底能解决什么；**表二** 每一件事现在靠什么解决，
以及在本机的落地条件（纯本地 / 需外部二进制 / 需网络）。

星数取 GitHub API，版本取 PyPI 实测（`pip index versions`）；「本机」指这台 Windows +
ChemDraw + KingDraw + Python 3.11 + RDKit 2026.09.1 的机器。

---

## 表一：能力地图（19 类，能解决的事）

| # | 领域 | 能解决的问题 |
|---|---|---|
| 1 | 结构表示与格式 | SMILES/InChI/Mol/SDF/PDB/XYZ/CIF/CDXML/CML/RXN 互转；批量转换；二维/三维、显式氢、坐标读写 |
| 2 | 规范化与清洗 | 去盐、取最大片段、电荷中和、互变异构规范化、芳香化、立体标记修复、canonical/InChIKey |
| 3 | 名称与标识符 | 名称→结构（IUPAC/俗名/CAS/德文名）、结构→标识符、同义名、供应商编号解析 |
| 4 | 图像识别 OCSR | 截图/照片/PDF/专利图 → 结构；反应图 → 反应 SMILES；多候选与置信度 |
| 5 | 2D 绘图与版面 | 排版、清理重排、官能团高亮、两结构差异高亮、反应式、多步路线图、scope 图、SAR 图、TLC 板、装置图、机理弯箭头 |
| 6 | 3D 与构象 | 3D 嵌入、构象枚举、几何优化、部分电荷、构象聚类、叠合、RMSD |
| 7 | 量子化学与能量 | 半经验/DFT 单点与优化、生成焓、自由能、反应能垒、光谱预测 |
| 8 | 描述符与理化性质 | 分子量、logP、TPSA、氢键给受、可旋转键、环系、复杂度、3D 形状描述符 |
| 9 | 类药性与 ADMET | 五规则、QED、合成可行性、溶解度、渗透、代谢、毒性、104 项端点预测 |
| 10 | 相似性与聚类 | 指纹、Tanimoto、Butina 聚类、Murcko 骨架、MCS、匹配分子对（MMP）、子结构检索 |
| 11 | 反应化学 | 配平、原子守恒、原子映射、反应分类、条件/试剂推荐、产率预测 |
| 12 | 逆合成与路线 | 单步断键、多步搜索、模板库、成本/可行性评分、路线排序 |
| 13 | 生成与优化 | 分子生成、骨架跃迁、多目标优化、枚举（R 基 / 立体异构 / 组合库） |
| 14 | 对接与筛选 | 对接姿态、打分、虚拟筛选、相互作用分析 |
| 15 | 光谱 | NMR 数据处理与寻峰积分、NMR 化学位移预测、质谱谱库匹配、IR/Raman |
| 16 | 文献与数据库 | PubChem / ChEMBL / Crossref / 专利检索、PDF 文本与表格抽取、ELN 记录 |
| 17 | 晶体与材料 | CIF 解析、周期性与对称性、晶格、材料数据库查询 |
| 18 | 教学与评测 | 批改、出题变体、联系表、基准评测集 |
| 19 | 报告与交付 | 投稿级图（dpi/宽度/格式）、Word/PPT 内嵌对象、SI 表、HRMS 表征段、PDF 讲义 |

---

## 表二：每类现在靠什么解决

| # | 领域 | 代表实现（Python / Agent） | 成熟度证据 | 本地条件 | 本机现状 |
|---|---|---|---|---|---|
| 1 | 格式转换 | RDKit；**Open Babel**（1398★，wheel 3.1.1.23）；**Indigo**（epam.indigo 1.46.0）；CDK（Java） | 都可 pip 安装 | 纯本地 | RDKit ✅，Open Babel/Indigo 未装 |
| 2 | 规范化 | RDKit `rdMolStandardize`；MolVS（已并入 RDKit）；**ChEMBL Structure Pipeline** | 实测 3.0 ms / 分子 | 纯本地 | ✅ 可用（未接进 CLI） |
| 3 | 名称解析 | **OPSIN**（244★，Java jar）；PubChem PUG-REST（pubchempy 1.0.5）；NCI CACTUS；CAS Common Chemistry | OPSIN 昨天还在推 | OPSIN 纯本地（需 Java）；PubChem 需网络 | Java 25 ✅；OPSIN 未落地；PubChem 已接 |
| 4 | OCSR | **DECIMER**（414★，PyPI 2.8.1）；**MolScribe**（344★，1.1.1）；**MolVec**（69★）；OSRA；**MolNexTR**（171★）；Imago | DECIMER 本月仍活跃 | 纯本地（模型权重需下载一次） | molvec + decimer ✅；molscribe 卡 OpenNMT 2.x ❌ |
| 5 | 2D 绘图 | RDKit `rdMolDraw2D`；Indigo；**Ketcher**（926★，JS）；ChemDraw/KingDraw；ChemDoodle（商业） | — | RDKit/Ketcher 纯本地；ChemDraw 需 COM | RDKit ✅；ChemDraw ✅；KingDraw ✅ |
| 6 | 3D 构象 | RDKit ETKDG+MMFF；Open Babel；**xTB/CREST**（外部）；**Uni-Mol**（1175★） | — | RDKit 本地；xTB 需二进制 | RDKit ✅（3d 已接） |
| 7 | 量子化学 | Psi4、PySCF、xTB、ASE（3.29.0）、QCEngine | 都可 conda/pip | 需外部二进制 | 未装 |
| 8 | 描述符 | RDKit；**Mordred**（484★，1.2.0，2024 后停更）；**molfeat**（1.0.0）；descriptastorus | — | 纯本地 | RDKit ✅ |
| 9 | 类药性/ADMET | RDKit QED/Lipinski；**ADMET-AI**（357★，2.0.1）；**Chemprop**（2514★，2.3.1）；**DeepChem**（7107★，2.8.0） | 三者都在维护 | 纯本地（模型权重下载一次） | RDKit ✅；ADMET 未装 |
| 10 | 相似性/聚类 | RDKit（Butina/MCS/Murcko）；**FPSim2**（185★，0.7.4）；**mmpdb**（303★，3.1.6） | mmpdb 今天仍在推 | 纯本地 | RDKit 部分 ✅；FPSim2/mmpdb 未装 |
| 11 | 反应 | RDKit `rdChemReactions`；**RXNMapper**（386★，0.4.3）；LocalMapper；ASKCOS | — | RXNMapper 需 torch + 权重 | RDKit 原子映射 ✅ |
| 12 | 逆合成 | **rdchiral**（191★，1.1.0）；**AiZynthFinder**（4.4.1）；ASKCOS（279★，2023 停更） | rdchiral 稳定但停更 | rdchiral 纯本地；AiZynthFinder 需模型下载 | 未装 |
| 13 | 生成 | **REINVENT4**（890★，GitHub 安装）；Uni-Mol；MolGPT | — | 需 torch + 权重 | 未装 |
| 14 | 对接 | AutoDock Vina / GNINA / DiffDock（外部程序） | — | 需二进制 | 未装 |
| 15 | 光谱 | **matchms**（0.33.1，质谱）；**nmrglue**（0.12，NMR 处理）；CFM-ID；nmrshiftdb | — | 纯本地 | 未装 |
| 16 | 文献/数据库 | pubchempy；**chembl-webresource-client**（0.10.9）；Crossref；**ChemDataExtractor** | — | **需网络** | PubChem ✅ |
| 17 | 晶体/材料 | **pymatgen**（2026.10.24）；ASE；spglib | — | 纯本地 | 未装 |
| 18 | 教学/评测 | **ChemBench**（147★）；**ChemCrow**（968★，2024 停）；**Coscientist**（212★） | 都是 agent 先例 | —— | 本项目已有批改/出题 |
| 19 | 交付 | ChemDraw COM（Word/PPT/CDX）；RDKit SVG/PNG；本项目留白与键长体检 | — | 厂商需安装 | ChemDraw ✅；Office 嵌入未做 |

---

## 结论

1. **19 类里 13 类纯本地可解**（RDKit 一个包覆盖 1/2/5/6/8/9/10/11 的大部分），
   真正需要外部二进制的只有量子化学、对接、xTB 三类，需要网络的只有第 16 类。
2. **agent 先例已被验证**：ChemCrow（968★）证明了「LLM + 化学工具」可行，
   ChemBench（147★）证明了这个方向需要评测集。我们不做新范式，只做工程化。
3. 本机缺口是明确的 6 个包 + 1 个 jar：`rdchiral`、`fpsim2`、`mmpdb`、`admet-ai`、
   `matchms`、`nmrglue`、OPSIN jar —— 全部 pip/下载一次即永久离线。
