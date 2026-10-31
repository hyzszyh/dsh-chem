# 施工预期：把「本地能跑的化学信息学」收进一个插件

写于 2026-10-30。这是施工前的约定书，不是完成报告。原则只有一条：
**凡本机能跑的，都进同一个插件；凡需要云端才能跑的，默认不进。**

---

## 1. 目标形态

一个 DSH 插件（host 半 + client 半 + 一个 Python 引擎），对外暴露 `chem_*` 工具。
用户视角只有一件事：告诉 agent 要什么，拿到能交的图/表/文件。

```
dsh-chem/
├─ dsh-plugin/            # 宿主插件（cordis）+ 右栏面板（client bundle）
├─ core/chemdraw_tool/    # Python 引擎（确定性计算 + 渲染 + 识别）
├─ bin/chem               # CLI 入口，插件逐次调用它
├─ skills/                # 面向 agent 的使用说明（DSH skill 目录）
├─ docs/                  # 能力地图、施工文档
└─ test/                  # 确定性断言 + acceptance 场景
```

## 2. 引擎阶梯（默认全本地）

| 优先级 | 引擎 | 用在哪 | 代价 |
|---|---|---|---|
| 1 | **RDKit** | 结构读写、规范化、描述符、相似性、SAR、2D 渲染、3D、反应、性质表 | 毫秒级，无窗口 |
| 2 | **本地 OCSR**（molvec + decimer，可选 molscribe） | 图 → 结构 | 秒级，无网络 |
| 3 | **ChemDraw COM** | 只在这些时候：要 `.cdx`、要 EPS/TIF 1200 dpi、要 Word/PPT 内嵌对象、RDKit 布局体检不过 | 1.5–2.3 s，会抢焦点 |
| 4 | **KingDraw** | 没有 ChemDraw 的机器兜底 | 秒级 |

硬规则：**画图默认不启动 GUI**。只有显式要厂商文件时才升级。

## 3. 工具面（19 个，按用户意图命名）

| 工具 | 一句话 | 引擎 | 依赖 |
|---|---|---|---|
| `chem_parse` | 名称/标识符/图片 → 结构 | RDKit + OPSIN + OCSR | 可选 OPSIN jar |
| `chem_normalize` | 去盐/中和/互变/立体 → canonical + InChIKey | RDKit | 无 |
| `chem_check` | 价键/芳香/电荷/手性/断片体检 | RDKit | 无 |
| `chem_draw` | 2D 出图（宽度/ dpi / 留白 / 引擎选择） | RDKit / ChemDraw | 无 |
| `chem_edit` | CDX/CDXML 合并、拆分、清理、高亮 | ChemDraw | 需 ChemDraw |
| `chem_reaction_figure` | 反应式 + 路线图 + scope 图 | RDKit + ChemDraw | 无 |
| `chem_mechanism` | 机理草稿 + 弯箭头渲染（SVG/CDXML） | RDKit | 无 |
| `chem_props` | 描述符、类药性、QED、SA | RDKit | 无 |
| `chem_compare` | 相似性、MCS、聚类、骨架、SAR 表 | RDKit | 无 |
| `chem_enum` | 变体、立体异构、R 基枚举 | RDKit | 无 |
| `chem_sheet` | 联系表 / SAR 表 / CSV → 图 | RDKit | 无 |
| `chem_conformer` | 3D 构象、电荷、能量 | RDKit（+xTB 可选） | xTB 可选 |
| `chem_retro` | 单步断键 → 多步搜索 | rdchiral（+AiZynthFinder 可选） | rdchiral |
| `chem_stoich` | 配平、投料、理论产率、SI 表 | 纯 Python | 无 |
| `chem_characterize` | HRMS 句、表征段落 | 纯 Python + RDKit | 无 |
| `chem_lookup` | PubChem / ChEMBL / 文献（**唯一可能联网**） | HTTP + 缓存 | 需网络 |
| `chem_exam` | 批改、出题 | RDKit + OCSR | 无 |
| `chem_office` | Word/PPT 内嵌可编辑对象 | ChemDraw COM | 需 ChemDraw |
| `chem_close` | 收工关窗 | COM | 需 ChemDraw |

## 4. 依赖策略

- **核心零依赖**：RDKit 已在全局 Python 3.11（2026.09.1, 30 MB），P0 全部只靠它。
- **可选依赖分组**（装一组解锁一批工具）：

| 组 | 包 | 解锁 |
|---|---|---|
| `retro` | rdchiral 1.1.0 | `chem_retro` 单步 |
| `similar` | fpsim2 0.7.4, mmpdb 3.1.6 | 大库相似检索、MMP |
| `admet` | admet-ai 2.0.1 | ADMET 端点 |
| `spectra` | matchms 0.33.1, nmrglue 0.12 | 质谱匹配、NMR 处理 |
| `names` | OPSIN jar（Java 25 已有） | 离线名称→结构 |
| `chemdraw` | 无（COM 由已装 ChemDraw 提供） | `.cdx`、EPS、Office 内嵌 |

- 缺依赖时**不是报错崩掉**，而是该工具返回「缺 `retro` 组：pip install rdchiral」，
  其余工具照常可用。

## 5. 旧插件怎么处理

1. **备份**：`~/.dsh/plugins/dsh-chem-draw-tool` → `D:\...\backup\plugin-<日期>`（纯复制，不压缩）。
2. **评估旧代码**：`lib/index.js` 的 15 个工具逐个对照上表，哪些函数直接搬、哪些重写。
3. **清理**：旧文件删除，但保留 profile 的 `link:` 接线（若沿用插件 id）或重新接线（若改名）。
4. **回滚**：任何一步失败，把备份复制回去即可，profile 接线不动。

## 6. 验收（Definition of Done）

每个工具都要有**确定性断言**，不接受「看起来对」：

- 结构类：InChIKey 回读一致；
- 规范类：给定输入 → 期望输出字符串相等；
- 数值类：与 RDKit 参考实现误差 < 1e-6；
- 渲染类：像素尺寸、键长中位数、留白比例在阈值内；
- 识别类：固定图片 → 固定 InChIKey（允许失败的样本要显式列为 known-fail）。

整体门禁沿用现有：`python tools/preflight.py` + `python tools/acceptance_v2.py`（8 场景）
+ 22 个测试套件，全绿才提交。

## 7. 里程碑

| 阶段 | 内容 | 验收 | 需要新依赖 |
|---|---|---|---|
| P0 | normalize / compare / props 补全 / enum 立体 / sheet / check 加强 / draw 的 RDKit 通道 | 7 个工具的确定性断言全绿 | 无 |
| P1 | mechanism（SVG 弯箭头）、characterize（HRMS/SI 表）、reaction_figure 的路线图 | 图与文本断言 | 无 |
| P2 | edit / office（CDX、Word/PPT 内嵌） | ChemDraw 回读核验 | 需 ChemDraw（已有） |
| P3 | retro（rdchiral）、lookup 缓存、spectra | known-fail 清单外的样本通过 | 需装 3 组 |

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| ChemDraw COM 抢焦点/卡死 | 默认不启动；进程超时强杀；每次调用前检查实例 |
| 插件启动把客户端搞崩（已发生过一次） | 客户端 apply 全部 try/catch；嵌套 inject；启动自报写日志 |
| 依赖装不上导致整插件不可用 | 缺依赖只降级对应工具，不阻断加载 |
| 测试套件在无终端环境挂起 | 每个套件加超时；挂起记为 known-hang 并单独跑 |
| Windows 路径/中文路径 | 全部走 pathlib + UTF-8，产物目录用 ASCII |

## 9. 不做

- MCP（用户已决定：一个插件足够）。
- 自研化学算法（一律 RDKit / 厂商）。
- 量子化学、对接（外部二进制，缺就不做）。
- 联网默认开启（`chem_lookup` 显式调用才出网，结果落缓存）。
