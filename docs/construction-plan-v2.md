# 施工预期 v2 —— dsh-chem：一个可移植的本地化学插件

写于 2026-10-30。v1 是方案，v2 是你拍板后的定稿。**这一版只做规划，不写实现。**

## 0. 决策记录（你选的）

| 项 | 决定 |
|---|---|
| 插件名 | 改名 **`dsh-chem`**（原 `dsh-chem-draw-tool`） |
| 旧工具名 | **不保留别名**，直接切到 19 工具面（破坏性变更，见 §4） |
| 依赖位置 | 见 §1：**不污染 DSH 自带运行时**，用独立 venv，但可用 DSH 的 Python 建 |
| 本轮范围 | 先出工程预期（本文档），不动代码 |
| 面板 | **同步改造**成 19 工具对应的界面 |

## 1. 跨机器运行时（你问的「用 dsh 的 py」——部分可行）

实测结论：

| 事实 | 证据 |
|---|---|
| DSH 自带 Python 3.12.14，位置 `~/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe` | 直接跑出来 |
| 自带环境有 PIL / pandas / numpy / **pip 26.2.1** | 导入成功 |
| **自带环境没有 RDKit** | `import rdkit` 报 ImportError |
| PyPI 有 `rdkit-2026.9.1-cp312-cp312-win_amd64.whl` | 查 PyPI JSON，24 个 wheel 中含该文件 |
| 自带环境 `venv` 模块可用 | `import venv` 成功 |
| 自带环境当前**建不了临时文件**（tempdir 探测失败） | `pip --dry-run` 直接抛 FileNotFoundError |

所以方案是：**用 DSH 的 Python 建 venv，但依赖装在 venv 里，绝不装进 DSH 运行时**。

```
bin/setup.ps1
  1. 找 Python：DSH 自带 3.12 → 系统 3.10–3.13（按序探测）
  2. TMP/TEMP 强制设为 ASCII 可写目录（绕过上面那个 tempdir 坑）
  3. 建 venv：%LOCALAPPDATA%\dsh-chem\runtime
  4. 装锁定版本（requirements.txt，pin 到具体版本）
  5. 写 runtime.json（python 版本、每个包的版本、安装时间）
  6. 自检：import rdkit、渲染一张测试图、写产物目录
```

装完 = **永久离线**，换机器只需重跑一次 `setup.ps1`。可选组（retro/similar/admet/spectra/names）
按需 `--extras` 装，不装不影响主流程。

## 2. 目录（改名后）

```
dsh-chem/
├─ dsh-plugin/            # cordis 宿主插件 + 右栏面板 client bundle
│   ├─ lib/index.js       # 19 个工具注册
│   ├─ lib/sidebar-bridge.js
│   ├─ lib/client.js
│   └─ cordis.patch.yml
├─ core/chem/             # Python 引擎（原 core/chemdraw_tool）
├─ bin/chem               # CLI（插件与面板共用）
├─ bin/setup.ps1          # 运行时引导
├─ requirements.txt       # 锁定版本
├─ skills/chem/           # agent 使用说明
├─ docs/                  # 能力地图、施工文档、验收记录
└─ test/                  # 断言 + acceptance
```

产物与日志统一挪到：`%LOCALAPPDATA%\dsh-chem\{artifacts,logs,runtime}`。

## 3. 引擎阶梯（默认不启动 GUI）

RDKit（默认，ms 级）→ 本地 OCSR（秒级）→ ChemDraw（只在要 `.cdx`/EPS/Office 内嵌/布局体检不过）
→ KingDraw（无 ChemDraw 时兜底）。

## 4. 工具面（19 个，无别名）

`parse / normalize / check / draw / edit / reaction_figure / mechanism / props / compare /
enum / sheet / conformer / retro / stoich / characterize / lookup / exam / office / close`

**破坏性变更清单**（旧名 → 新名）：

| 旧 | 新 |
|---|---|
| `chem_identity` / `chem_analyze` | `chem_props` |
| `chem_convert` | `chem_draw`（含格式转换）或 `chem_normalize` |
| `chem_resolve` / `chem_ocr` | `chem_parse` |
| `chem_batch` / `chem_variants` | `chem_sheet` / `chem_enum` |
| `chem_figure` | `chem_draw --preset <期刊>` |
| `chem_grade` | `chem_exam grade` |

旧名调用会直接报「已改名，参见 docs」并给出新名 —— **不静默失败**。

## 5. 面板改造（19 工具 → 5 个分组）

| 分组 | 界面元素 |
|---|---|
| 画 | 输入框 + 宽度/引擎 + 「画出来」+ 投稿预设 |
| 算 | 性质表、规范化、相似性、SAR 表按钮 |
| 反应 | 反应式输入、配平、逆合成（缺依赖时置灰并说明） |
| 教学 | 批改、出题、联系表 |
| 产物 | 现有画廊（轮询、收藏、过滤）保留 |

面板不重复实现化学：所有按钮都打到同一个 `bin/chem`。

## 6. 迁移步骤（可回滚）

1. 备份：`~/.dsh/plugins/dsh-chem-draw-tool` → `D:\...\backup\plugin-20261030`；
2. 仓库改名与重构（git 历史保留）；
3. `bin/setup.ps1` 建 venv 并自检；
4. `dsh plugin --profile desktop remove dsh-chem-draw-tool` → `add link:<新目录>`；
5. 重启，确认 19 个工具出现、面板 5 组渲染；
6. 跑 acceptance 8 场景；
7. 全绿后再删旧目录；任何一步失败 → 复制备份回去。

## 7. 工作分解与估时

| 阶段 | 内容 | 估时 |
|---|---|---|
| W0 | 建 venv + 依赖锁定 + setup 自检 | 4 h |
| W1 | 仓库改名、路径迁移、日志与产物目录 | 3 h |
| W2 | P0 七项（normalize/compare/props/enum/sheet/check/draw-RDKit） | 10 h |
| W3 | 工具面重命名 + 破坏性变更提示 + 文档 | 4 h |
| W4 | 面板 5 组改造 | 6 h |
| W5 | mechanism / characterize / reaction_figure | 8 h |
| W6 | edit / office（CDMX、Word/PPT） | 6 h |
| W7 | retro / lookup 缓存 / spectra（可选组） | 6 h |
| **合计** | | **≈ 47 h ≈ 6 个工作日** |

## 8. 验收（每个工具都要确定性断言）

- 结构类：InChIKey 回读一致；
- 规范类：输入 → 期望字符串相等；
- 数值类：与 RDKit 参考实现误差 < 1e-6；
- 渲染类：像素尺寸、键长中位数、留白比例在阈值内；
- 识别类：固定图片 → 固定 InChIKey，失败样本进 known-fail 清单；
- 门禁：preflight + acceptance 8 场景 + 全部测试套件绿。

## 9. 风险

| 风险 | 对策 |
|---|---|
| 自带 Python 建不了 temp 目录 | setup 里强制 TMP/TEMP；失败则回退系统 Python |
| RDKit 换版本导致数值漂移 | requirements 里 pin 版本，断言按版本记录 |
| ChemDraw COM 抢焦点/卡死 | 默认不启动；超时强杀；调用前置检查 |
| 插件启动搞崩客户端（已发生一次） | client apply 全 try/catch，嵌套 inject，自报日志 |
| 依赖缺失阻断整插件 | 缺依赖只降级对应工具 |

## 10. 还没定的（需要你后续拍板）

1. 旧工具名的旧调用会出现「已改名」错误 —— 你是否接受在自己已有的会话里看到一次报错？
2. `admet` 组会拉 torch（约 2 GB），要不要进默认安装？
3. 是否要我把 acceptance 从 8 场景扩到覆盖 19 工具（跑一次约 3–5 分钟）？
