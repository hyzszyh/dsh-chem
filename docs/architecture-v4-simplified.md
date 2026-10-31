# 架构简化（v4）：13 个工具、零安装启动、COM 触点减半

写于 2026-10-30。起点是 v3 的 20 工具 / 57 小时 / 必装 300 MB venv。
目标：不砍分子识别的前提下，把工具数、安装步骤、厂商触点都压下去。

## 一、砍掉的东西

| 项 | 原来 | 现在 | 收益 |
|---|---|---|---|
| 工具数 | 20 | **13**（合并同实现、同意图） | 上下文更短、选错概率更低 |
| 必装运行时 | 独立 venv 300 MB | **复用现有 Python**（已装 rdkit/sklearn/scipy/fitz/PIL/docx/openpyxl），缺才建 venv | 首次 0 安装 |
| 桥端点 | 7 | **3**（state / artifacts / call） | 诊断代码全删 |
| 端口探测 | 37373–37376 四个 | **一个固定端口 + 配置文件** | 去掉启动竞态 |
| 面板分组 | 5 组 | **3 区**（输入 / 出图 / 产物） | 界面工作量减半 |
| COM 触点 | 4（cdx 读写、Office 内嵌、结构命名、EPS） | **2**（cdx 读写、EPS） | 抢焦点风险减半 |
| 测试套件 | 22 | **10**（按工具归并） | 维护成本 |

## 二、13 个工具

| 工具 | 吸收了什么 | 动作参数 |
|---|---|---|
| `chem_parse` | 名称→结构、缩写、CAS、**图片识别（全保留）**、序列→SMILES | `source=name\|image\|seq` |
| `chem_clean` | 规范化 + 互变异构 + 体检 + 药化过滤 | `action=check\|fix\|filter` |
| `chem_draw` | 2D 出图 + 反应式 + 机理箭头 + 联系表 + 期刊规格 | `view=mol\|rxn\|mech\|grid` |
| `chem_props` | 描述符 + 分子式/DBE + 精确质量 | `fields=...` |
| `chem_calc` | 配平 + 投料 + HRMS/元素分析文字 + 板图/稀释 | `kind=stoich\|hrms\|plate` |
| `chem_compare` | 指纹 + 相似性 + MCS + 骨架 + 聚类 + SAR 表 | `mode=sim\|mcs\|cluster\|sar` |
| `chem_table` | 批量表 + 数据清洗 + IC50 拟合 | `action=matrix\|clean\|fit` |
| `chem_db` | 导入 / ID 查 / 子结构查 / 相似查 / 去重 | `op=import\|get\|sub\|sim` |
| `chem_ml` | 训练 / 骨架切分 CV / 预测 / 指标 / 重要性 | `action=train\|predict\|evaluate` |
| `chem_enum` | 变体 + 立体枚举 + 组合库 | `mode=variant\|stereo\|library` |
| `chem_retro` | 单步断键（rdchiral） | `depth=1` |
| `chem_exam` | 批改 + 出题 + 答案断言 | `action=grade\|make` |
| `chem_vendor` | ChemDraw/KingDraw：cdx 读写、EPS、预览、关窗 | `do=cdx\|eps\|preview\|close` |

**分子识别能力不减**：`chem_parse` 的 OCSR 仍是 molvec + DECIMER 双引擎投票，
MolScribe 作为可选第三票；多候选、置信度、known-fail 清单全部保留。

## 三、运行时：零安装优先，缺了才建

\u0060\u0060\u0060
bin/chem.py 启动 → 找解释器（按序，取第一个含 rdkit 的）
  1. %LOCALAPPDATA%\dsh-chem\runtime\python.exe   （专用，若已建）
  2. 系统 Python 3.10–3.13                          （本机 3.11 已全装）
  3. DSH 自带 3.12 → 建 venv → 装依赖               （兜底）
都不含 rdkit → 返回明确指引，不抛栈
\u0060\u0060\u0060

首次运行把解释器路径与包版本写进 `runtime.json`；版本漂移时提示重建，不静默降级。

## 四、分层：三层砍成两层半

\u0060\u0060\u0060
① 插件（JS）：参数校验 + spawn + 结果整形       约 400 行
② 引擎（Python）：入口 bin/chem.py，子命令 = 工具名，一进一出 JSON
③ 引擎内部：parse / clean / draw / props / calc / compare / table / db / ml / enum / retro / exam / vendor / ocr
\u0060\u0060\u0060

去掉原来的任务目录中转与多次嵌套：**一个工具 = 一次子进程 = 一次 JSON**。

## 五、推迟（不进 v1）

| 项 | 原因 |
|---|---|
| Word/PPT 内嵌可编辑 ChemDraw 对象 | OLE 最易抢焦点、最易卡死；学生插 PNG 已够 |
| `.cdx` 合并/拆分/模板库 | 同类风险且非高频 |
| 多步逆合成 | 需 1 GB 模型，学生用不到 |
| ADMET / STOUT / 谱学组 / chemprop | 已确认不装 |

## 六、修正后的工期

| 阶段 | 内容 | 估时 |
|---|---|---|
| W0 | `bin/chem.py` 骨架 + 解释器探测 + probe 自检 | 2 h |
| W1 | 改名 `dsh-chem`、13 工具注册、薄桥 | 5 h |
| W2 | clean / props / calc / compare / table | 9 h |
| W3 | draw（mol/rxn/mech/grid）+ 期刊规格 | 7 h |
| W4 | parse（含 OCSR 全保留）+ enum | 6 h |
| W5 | db + ml | 8 h |
| W6 | vendor（cdx/EPS/预览）+ exam | 5 h |
| W7 | 面板 3 区 + 全量验收 | 5 h |
| **合计** | | **约 47 h ≈ 6 个工作日** |

比 v3（75 h）少 28 小时，比 v2（57 h）少 10 小时。