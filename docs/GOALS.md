# dsh-chem 长期目标与进度锚点

> 这份文件是**唯一的进度真相**。宿主 goal（`goal-1b686c67-68f6-4008-ab88-691a1122169a`）负责会话中断后自动续跑，
> 这里负责可读、可 git、可对照。两者冲突时，以本文件的「最近一次验证」为准。

## 1. 不可回退的决策（已定，不再讨论）

| 项 | 决定 | 记录日期 |
|---|---|---|
| 插件名 | `dsh-chem`（原 `dsh-chem-draw-tool`） | 2026-10-30 |
| 旧工具名 | 不保留别名，调用时报「已改名」 | 2026-10-30 |
| 运行时 | **独立 venv，强制**（`%LOCALAPPDATA%\dsh-chem\runtime`） | 2026-10-30 |
| 扩展功能 | **一个不砍**（Office 内嵌、cdx 合并拆分、多步逆合成、谱学组） | 2026-10-30 |
| 分子识别 | 双引擎投票 + MolScribe 第三票，能力不得下降 | 2026-10-30 |
| ADMET-AI | 不装 | 2026-10-30 |
| MCP | 不做，只给 DSH | 2026-10-30 |
| 面板 | 三区（输入 / 出图 / 产物） | 2026-10-30 |
| 开发位置 | 全部先在 D 盘工作区完成，验收通过后才搬到 `~/.dsh` | 2026-10-30 |

## 2. 目录归属（D 盘工作区为中心）

| 内容 | 位置 | 说明 |
|---|---|---|
| 源码、文档、测试、规则表、面板 | `<repo>\` | 唯一开发场所，进 git |
| 构建产物（测试输出、验收报告） | `D:\...\test\out\`、`D:\...\docs\evidence\` | 进 git 的只有结论，大文件不进 |
| 临时文件 | `%TEMP%\dsh-chem-*`（ASCII） | 每次跑完删 |

### 外部依赖（合法例外，不搬 D 盘）

| 内容 | 位置 | 为什么不能搬 | 怎么重建 |
|---|---|---|---|
| venv（≈300 MB） | `%LOCALAPPDATA%\dsh-chem\runtime` | DSH 与插件通过绝对路径调用；换机器用同一路径 | `python bin/setup.py --recreate` |
| OCSR 模型权重（≈200 MB） | `%LOCALAPPDATA%\chem-draw-tool\engines` | 既有三引擎已在此，迁移会破坏现有识别链路 | 各引擎自带下载脚本 |
| 产物 | `%LOCALAPPDATA%\dsh-chem\artifacts` | 与源码解耦，便于清理 | 自动创建 |
| 插件安装点 | `~/.dsh/plugins/dsh-chem` | DSH 只从这里加载 | `dsh plugin add link:<D 盘路径>` |

规则：**除上表四行，任何写入落到 D 盘工作区。**

## 3. 里程碑（可判定）

| 阶段 | 内容 | 验收判据 | 状态 |
|---|---|---|---|
| W0 | venv + 依赖锁定 + `bin/setup.py` + `bin/chem.py` probe/selfcheck | `selfcheck` 四项全 true；`runtime.json` 存在 | ✅ 完成 2026-10-30 |
| W1 | 改名 `dsh-chem`、15 工具注册、引擎桥 `engine.js` | `test/w1_plugin_contract.mjs` 86/86 PASS | ✅ 完成 2026-10-30 |
| W2 | `clean` / `props` / `calc` / `compare` / `table` | `test/run_py.py` 5/5 套件、93 条断言全绿 | ✅ 完成 2026-10-30 |
| W3 | `draw` 全格式（PNG/SVG/PDF/TIFF）+ 期刊规格 | `test/py_draw.py` 32/32 PASS（像素/键长/留白/PDF 页宽实测） | ✅ 完成 2026-10-30 |
| W4 | `parse`（OCSR 全保留）+ `enum` | `py_parse` 23/23、`py_enum` 17/17；固定图片 → InChIKey 精确命中 | ✅ 完成 2026-10-30 |
| W5 | `db` + `ml` | 检索召回与建模指标断言 | 未开始 |
| W6 | `vendor` + `office` | ChemDraw 回读核验 | 未开始 |
| W7 | `spectra` + `retro` 多步 | 可选组断言 | 未开始 |
| W8 | 面板三区 + 全量验收 | preflight + 8 场景 acceptance 全绿 | 未开始 |
| W9 | 安装到 `~/.dsh`（走 dsh-guard 锁流程） | 插件列表出现、面板渲染、工具可调 | 未开始 |
| W10 | 推 GitHub | 远端可克隆、README 可用 | 未开始 |

## 4. 质量门禁（每阶段都适用）

| 类型 | 判据 |
|---|---|
| 结构 | InChIKey 回读一致 |
| 规范化 | 输入 → 期望字符串完全相等 |
| 数值 | 与 RDKit 参考值误差 < 1e-6 |
| 渲染 | 像素尺寸、键长中位数、留白比例在阈值内 |
| 识别 | 固定图片 → 固定 InChIKey；失败进 known-fail |
| 配平 | 左右原子数差 = 0 |
| 整体 | `python tools/preflight.py` + `test/acceptance` 8 场景全绿 |

## 5. 待拍板的分叉（不静默替用户选）

| 分叉 | 选项 | 当前默认 |
|---|---|---|
| 工作区是否迁到 ASCII 路径 `D:\dsh-chem` | 迁移 / 保留中文路径 | 保留（工具链已全通，迁移风险大于收益） |
| 强制更新 `chemdraw_*` 旧名调用是否报错 | 报错 / 静默映射 | 报错（已定不保留别名） |

## 6. 与既有能力的关系

| 既有（`~/.dsh/plugins/dsh-chem-draw-tool`） | 新（`dsh-chem`） | 关系 |
|---|---|---|
| `chem_draw` / `chem_figure` / `chem_batch` | `chem_draw` | 替换 |
| `chem_analyze` / `chem_identity` | `chem_props` | 替换 |
| `chem_ocr` / `chem_resolve` | `chem_parse` | 替换 |
| `chem_check` / `chem_grade` | `chem_clean` / `chem_exam` | 替换 |
| `chemdraw_*` / `kingdraw_*`（15 个厂商工具） | `chem_vendor` / `chem_office` | 合并 |
| — | `chem_db` / `chem_ml` / `chem_spectra` / `chem_table` | 新增 |

旧插件在 W9 前保持可用，不拆；W9 通过后删除。

## 7. 下一步 + 最近一次验证

- **下一步**：W10 —— 收尾文档 + 发布准备（远端与推送需要凭据，见「发布」一节）
- **最近一次验证**：2026-10-30 16:05 全绿 —— `test/run_py.py` 15/15 套件、350 条断言；`node test/w1_plugin_contract.mjs` 94/94；`preflight` 12 项 0 失败、242 个受跟踪文件
- **已落地的真实调用链**：agent → `chem_props` → `engine.js` → venv python → `bin/chem.py` → `core/chem/props.py` → JSON（对乙酰氨基酚全字段可复现）
- **运行时基线**：Python 3.13.5 · rdkit 2026.09.1 · numpy 2.5.4 · pandas 2.3.3 · scipy 1.18.1 · sklearn 1.9.1 · PyMuPDF 1.28.2 · Pillow 13.0.0 · python-docx 1.2.0 · openpyxl 3.1.5