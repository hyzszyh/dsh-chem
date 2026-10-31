# Agent 接口规范（v2 草案）

> 一句话定位：**让化学专业的学生不打开 ChemDraw / KingDraw，在 agent 里说人话，拿到可直接交的东西。**
> 本文件回答两个问题：这个接口要实现什么、解决谁的什么痛点。每条能力都必须指得出证据。

## 1. 为什么现在的暴露面不对

现状：MCP 有两套面（`--surface tasks` 14 个任务级、默认 16 个动作级），插件 30 个（v1 动作级 15 +
v2 任务级 15）。动作级那批是——`chemdraw_draw`、`chemdraw_export`、
`kingdraw_smiles_to_mol`、`kingdraw_to3d`……一个动作一个工具，和 CLI 的 21 条叶子命令一一对应。

这对人友好（可以拼），对 agent 不友好：

1. **agent 的每一步都要「读返回 → 决策」**，调用轮次是成本。「画好并出图」现在是 draw → export →
   figure 三次调用、读三份返回，而它本可以是一次。
2. **agent 看不见屏幕**。画完只拿到一个 `path`，它无法自检重叠、错位、裁切，学生还得自己开 ChemDraw
   看一眼——那这个接口就没解决痛点。
3. **学生会说「阿司匹林」「64-19-7」，不会说 SMILES**。没有名称/CAS 入口，agent 只能反问，或者编一个。
4. **它不知道自己上一步把东西画到了哪个文档**。没有状态查询，于是重复画、画错页、对已关闭的窗口等到超时。
5. **失败后它要能换路**，而现在只有一个 `failure.hint` 句子，没有「还能试什么」的清单。

## 2. 学生真正的任务（不是「画一个分子」）

- **A 出作业/讲义图**：一次画多个、风格统一、能贴进 Word/PPT。证据：《例谈 KingDraw 在高中化学教学
  中的应用》（理科考试研究 2023, 30(17):53-56）摘要明说一线教学「难以绘制化合物的结构式、3D 结构模型
  和合成路线图」；ChemDraw 手册 Templates(203)、Captions(92)。
- **B 实验报告的性质表**：分子式、分子量、精确质量、logP、TPSA、氢键给受体。证据：ChemDraw 手册
  Structure Analysis(221)、Chemical Properties(228, 279)、Property Calculations(377)。
- **C 投稿图**：单栏结构图与 Scheme，尺寸/分辨率被期刊卡死。证据：中文期刊规范（结构式/反应式单栏
  8 cm，图式单栏/双栏 17 cm）；Nature [结构式样式指南](https://www.nature.com/documents/nr-chemical-structures-guide.pdf)。
- **D 结构体检**：交作业/投稿前查价键错、立体冲突、排版乱。证据：ChemDraw 手册 Checking Structures(126)、
  Chemical Warnings(127)；本机 COM 实测有 `NumChemicalWarnings`。
- **E 名称→结构**：学生只记得名字（阿司匹林/对乙酰氨基酚/IUPAC 名）。证据：ChemDraw 手册
  Name to Structure(216)；KingDraw 那篇教学论文里的「化合物百科搜索辅助绘制」。
- **F 反应式与计量表**：合成路线、Scheme、当量表。证据：手册 Drawing Reactions(194)、Stoichiometry
  Grid(200)；COM 实测有 `ReactionSchemes` 与 `MakeStoichiometryGrid`。
- **G 2D→3D**：送 Gaussian/ORCA 前取初始构象。证据：手册 3D Viewing(239)、3D Properties(344)；
  学生侧对应痛点是「导师不会教的 3D 结构转化」。
- **H 批量**：20 个分子出 20 张图、一个 SDF。证据：手册 ChemScript(208) 的官方示例就是「一次清理
  多个 ChemDraw 文件里的全部结构」。
- **I 结构身份核对**：确认两个来源是不是同一化合物。证据：本项目 `crosscheck` 已用 InChIKey；学术圈常用
  ChemSpider/PubChem 对照。

**不在这一版**：图像识别（截图/PDF → 结构，需 OSRA/DECIMER 级模型）、NMR 预测（ChemNMR 只在
Professional 且无 COM 入口）、Markush→SDF 展开（无 COM 入口）、ChemACX（需订阅）。

## 3. 设计原则

1. **任务级聚合**：一次调用交付一件可交的东西，而不是交付一个文件路径。
2. **视觉反馈是硬要求**：任何绘图/出图工具都返回一张可渲染的预览图（MCP `image` content），让 agent
   自己看见重叠、裁切、比例，再决定要不要重画。
3. **身份随产物走**：每个结构产物都带 SMILES + InChIKey + 分子式，agent 拿去核对/汇报，不用再调一次。
4. **状态可查**：`chem_status` 给出通道可用性、打开的文档与页面、锁持有者、上次动作。
5. **失败给出下一步**：`failure.next_steps` 是「还能试什么」的清单，不是一句日志。
6. **降级必须如实**：换引擎、丢立体、丢同位素都写进 `degraded.lost`，不许静默成功。
7. **可重复调用**：同一请求重复执行不产生重复对象或半成品文件。

## 4. 工具清单（v2）

- `chem_status`（无输入）→ 通道表（可用/不可用+原因）、打开的文档、页面尺寸、锁、上次动作。无副作用。
- `chem_catalog(task?)` → 能力目录：能做哪些任务、用哪个工具、前置条件、证据等级。解决「学生不知道怎么开口」。
- `chem_resolve(名称/中文名/CAS/SMILES/分子式)` → 结构身份 + 来源（rdkit / PubChem / 本地词典）。
- `chem_draw(SMILES|名称|molblock, page?, position?, style?)` → 落地到页面 + 读回 SMILES + CDXML
  + **预览 PNG** + warnings。
- `chem_figure(preset|width_mm, dpi, format)` → 期刊图 + 预览 + 实测像素与 dpi 真话。
  预设：ACS 单栏/RSC/中文期刊 8 cm/图式 17 cm/自定义。
- `chem_check()` → 化学警告逐条（价键/立体/重叠）+ 建议改法。
- `chem_analyze()` → 性质表：分子式、精确质量、MW、logP、TPSA、HBD/HBA、电荷、立体中心。
- `chem_read(as)` → 当前页结构（smiles / molblock / cdxml）。
- `chem_reaction(反应物/产物/条件)` → 反应式对象 + 化学计量表。
- `chem_batch(列表, what)` → N 个产物 + 联系表 + 逐项状态。
- `chem_convert(结构, to)` → mol / smiles / sdf / king / cdxml / 3d，丢信息的如实说明。
- `chem_close(target)` → 关窗口/关文档，报告还剩什么。

原子级动作（现在的 16 个）**不删**，降为内部实现与调试面；插件与 MCP 默认只暴露上面这一层。

## 5. 返回契约

```json
{
  "ok": true,
  "task": "chem_figure",
  "did": ["drew 21 atoms onto page 1", "exported 80 mm @ 600 dpi"],
  "artifacts": [
    {"path": "phenol.png", "kind": "image", "bytes": 20977, "viewer": "image"}
  ],
  "identity": {
    "smiles": "c1ccccc1O",
    "inchikey": "ISWSIDIOOBJBQZ-UHFFFAOYSA-N",
    "formula": "C6H6O"
  },
  "evidence": "A",
  "warnings": [],
  "degraded": {"reason": "", "lost": []},
  "state": {"documents": 1, "page": 1, "atoms": 21},
  "failure": null,
  "elapsed_ms": 228
}
```

失败时 `failure` 填 `code` / `message` / `hint` / **`next_steps`**，例如：

```json
{"code": "E01", "message": "ChemDraw is not running",
 "next_steps": ["chem_figure with engine=kingdraw",
                 "run scripts/install.ps1",
                 "chem_status to see which channel is up"]}
```

## 6. 与现状的差距

- **画/出图/回读**：有，但是动作级；缺预览图、缺一次到位的聚合。
- **期刊预设**：只有手工 `width_mm`；缺 ACS/RSC/Nature/中文期刊预设与尺寸校验。
- **结构体检**：没有。COM 已见 `NumChemicalWarnings`，可做。
- **性质表**：没有。RDKit 可算，可做。
- **反应式/计量表**：没有。COM 已见对象，可做。
- **批量**：没有（靠脚本循环）。可做。
- **名称/CAS 入口**：没有。需 PubChem/OPSIN，联网或离线降级。
- **状态/目录**：只有 `chemdraw_capabilities`；缺文档与页面状态、缺任务级目录。

## 7. 怎样算解决了痛点

五个端到端剧本，在真实 DSH 会话里跑，记录**工具调用次数 / 人工介入次数 / 产物是否可直接交付**：

1. 「把阿司匹林、咖啡因、苯酚画成一张作业图」→ 期望 1 次 `chem_batch`，3 张图 + 联系表，人工 0 次。
2. 「给我阿司匹林的性质表，我要填实验报告」→ 1 次 `chem_analyze`，表格可直接粘。
3. 「按中文期刊单栏 8 cm、600 dpi 出图」→ 1 次 `chem_figure`，实测宽度 80 mm。
4. 「检查我这个结构画得对不对」→ 1 次 `chem_check`，给出警告与修法。
5. 「帮我查 64-19-7 是什么，画出来」→ `chem_resolve` → `chem_draw`，2 次调用。

判据：每个剧本 ≤3 次工具调用、0 次打开厂商软件界面、产物无需返工。
## 8. 从「打开软件」到「关上」的全部可能性

按一个人真正的工作顺序分五段。每行末尾是状态：`[现有]` 已有能力、`[新增]` 本版要做、
`[命令面]` 软件里有、需要命令/UI 层才能触发、`[不做]` 明确不做。

### A 把想法变成结构（输入）

- A1 只记得名字/俗名/商品名 → 对 agent 说「阿司匹林」`[新增]`
- A2 只有 CAS 号 → 「64-19-7 是什么」`[新增]`
- A3 有一张图片（教材截图 / 试卷 / PDF 插图 / 手写照片）→ 「照着这张图画出来」`[新增]`
- A4 有 SMILES / InChI / 分子式 → 「C9H8O4 画出来」`[部分现有]`
- A5 有一份文件（.cdx / .cdxml / .mol / .sdf / .king）→ 「打开这个文件」`[现有 kd / 部分 cd]`
- A6 只有一句自然语言描述 → 「对位有羟基的苯甲醛」`[新增，LLM 生成 + 校验]`

### B 编辑与作图

- B1 画一个结构到页面 `[现有]`
- B2 一次画多个、自动排布、风格统一 `[新增]`
- B3 改结构：加/删/替换基团、编号、着色、电荷与孤对电子 `[部分现有：cd modify]`
- B4 排版整理：Clean Up、对齐、统一键长、居中 `[命令面]`
- B5 立体化学：楔形键、R/S 标注、Fischer / Newman / 透视式 `[部分；Fischer/Newman 属命令面]`
- B6 通式结构 / Markush / R 基团 `[命令面：MakeAltGroup、Expand Generic Structure]`
- B7 反应式：箭头、条件、原子映射、自动编号 `[命令面：Map Reaction Atoms、Autonumber Reaction]`
- B8 机理图：电子进攻弯箭头 `[新增，已实测可建：MakeArrow 默认 IsArc=True]`
- B9 生物大分子：肽 / DNA / RNA 序列、HELM、质粒图 `[命令面：BioDraw、MakePlasmidMap]`

### C 校验

- C1 结构体检：价键、立体冲突、重叠、化学警告 `[命令面：Check Structure、Show Chemical Warnings]`
- C2 身份核对：InChIKey 跨引擎 `[现有 crosscheck]`
- C3 计量核算：当量、摩尔质量、投料量、产率 `[命令面：Analyze Stoichiometry]`
- C4 谱图指认：¹H / ¹³C 预测与谱-结构归属 `[命令面：Predict ¹H-NMR / ¹³C-NMR Shifts、Make Spectrum-Structure Assignment]`

### D 产出

- D1 投稿图：期刊预设尺寸、dpi、trim `[部分现有：cd figure，缺预设]`
- D2 讲义 / 试卷 / PPT：批量、联系表、透明底、EMF 矢量 `[新增]`
- D3 数据表：性质、元素分析、SI 表格 `[新增]`
- D4 交换格式：SDF / CSV / CDXML / .king / mol / InChI `[部分现有]`
- D5 3D：构象、3D 属性、送计算 `[命令面：3D Clean Up、Add 3D Property；KingDraw 侧现有]`
- D6 谱图与 TLC 板图 `[命令面：MakeTLCPlate]`

### E 教学与批改

- E1 批改学生结构（检查 + 与学生答案差异）`[C1 的组合]`
- E2 出题/变体（同一骨架换取代基）`[B6 + chem_batch]`
- E3 课堂演示（TLC、轨道、逐步机理）`[命令面：MakeTLCPlate、MakeOrbital、B8]`

## 9. 「直接操作软件」实测（能不能绕过 COM 的缺口）

本机测到的三件事，决定了 3D / NMR / 命名这些没有 COM 对象的能力怎么落地：

1. **命令面是完整可枚举的**：`app.MenuBars` 拿到 23 个菜单、**357 条命令**，每条有 `caption` 与
   `CommandID`（例：Check Structure=355、Clean Up Structure=356）。命令清单已落盘 `chemdraw_commands.json`。
2. **`Execute()` 这条路不通**：`item.Execute()` 抛 `-2147352567 发生意外`，文档指纹不变（结构没被动过）。
3. **`WM_COMMAND` 这条路危险**：向主窗口 `PostMessage(WM_COMMAND, 356)` 之后，COM 报
   `RPC 服务器不可用`、窗口句柄随即失效——把应用打死了。**不要用。**

剩下的正路是 **UI Automation**：UIA 能直接看到菜单栏（File / Edit / View / Object / Structure / Text /
Curves / Colors / Search / Add-ins / Window / Help 共 13 项），和有命令的窗口相比是可点的。
另外 `File > Run ChemScript` 说明应用侧有 ChemScript 集成，装上 ChemScript 后是最干净的脚本通道。

结论：3D、NMR、命名转换、Clean Up、计量表这些**走「菜单/UI 自动化 + 前后指纹校验」**，不假装 COM 万能。

## 10. 图像识别（OCR 结构式）方案

不依赖大模型的多模态能力——它在结构式上本来就不可靠。用专用引擎 + 化学校验 + 投票：

1. **多引擎**：OSRA（C++ 可执行）、MolVec（Java）、DECIMER（Python/TF）、MolScribe（Python/torch），
   按机器上能装成功的两个以上并行跑。
2. **化学校验**：每个候选交给 RDKit 做价键与芳香性检查，失败的直接淘汰。
3. **投票与置信度**：两个引擎的 InChIKey 一致 → 高置信；不一致 → 返回候选列表 + 差异说明。
4. **回退**：低置信时**不猜**，把裁剪后的图和候选一起返回，让用户指认；never silently assert。
5. **增强**：对截图先做预处理（去背景、二值化、放大、裁边），这一步比换模型更有效。