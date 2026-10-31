# dsh-chem（插件本体）

把本机的化学计算与绘图能力接到 agent 手上。学生说人话，拿回来的是能直接交的图、表和文件。

- **形态**：DSH 宿主插件（15 个工具）+ 右栏面板 + Python 引擎
- **运行时**：独立 venv（`%LOCALAPPDATA%/dsh-chem/runtime`），装一次，之后离线
- **联网**：只有 `chem_parse` 在显式 `network=true` 时查 PubChem，其余全本地

## 15 个工具

| 工具 | 做什么 |
|---|---|
| `chem_parse` | 名称 / 图片 / 序列 → 结构（本机 OCSR 多引擎按 InChIKey 投票） |
| `chem_clean` | 体检、规范化、互变异构、PAINS / BRENK 警示 |
| `chem_draw` | 分子 / 联系表 / 反应式 / 机理箭头 / 3D 构象；PNG·SVG·向量 PDF·TIFF |
| `chem_props` | 分子式、精确质量、分子量、logP、TPSA、QED 等描述符 |
| `chem_calc` | 配平、投料、产率、HRMS 与元素分析文字、96 孔板 |
| `chem_compare` | 相似性、MCS、聚类、SAR 表 |
| `chem_table` | 批量描述符表、数据清洗、4PL 拟合 |
| `chem_db` | 本地 SQLite 库：导入 / 子结构 / 相似 / 区间检索 / 导出 |
| `chem_ml` | 描述符 → 训练 → 折外交叉验证 → 预测 + 适用域 |
| `chem_enum` | 变体、组合库、立体异构、互变异构枚举 |
| `chem_retro` | 单步断键（13 条教学模板），可展开两步 |
| `chem_spectra` | 1H/13C/IR/MS 规则估算 + 观测峰比对 |
| `chem_exam` | 批改（八种判定）+ Word 报告 |
| `chem_office` | Word 结构报告、SI 表（docx + xlsx）、PPT 页 |
| `chem_vendor` | CDXML 读写 / 合并 / 拆分；cdx、EPS 走 ChemDraw 通道 |

## 边界（写在插件里，不藏在别处）

- 二进制 `.cdx` 读写、EPS、Word 内嵌 OLE 对象需要本机 ChemDraw 的可验证接口，本机实测不可用，
  一律返回 `needs-vendor` 而不是假装成功；CDXML 走本地解析，能完整往返。
- NMR 是规则估算（1H ±0.3 ppm、13C 给区间），输出里每次都标注。
- 逆合成是模板库，不是全合成搜索。

## 装进 DSH

```
python tools/install_plugin.py     # 从仓库复制成 ~/.dsh/plugins/dsh-chem（含引擎）
```

插件是自包含的一个文件夹：JS、`engine/`（`bin/chem.py` + `core/`）、`node_modules` 桩全在里面，
`data` 是指向 `%LOCALAPPDATA%/dsh-chem` 的 junction。工作区（D 盘源码）删掉之后照常工作，
`node test/w11_install.mjs` 就是这条的断言。

## 面板

右栏「化学绘图」：填结构 → 画 / 收藏 / 体检 / 投稿图 / 3D / 拼联系表；点历史产物可读回结构。
面板不 spawn Python，它通过宿主开的回环桥（127.0.0.1，白名单 15 个工具）转发给同一个引擎。
