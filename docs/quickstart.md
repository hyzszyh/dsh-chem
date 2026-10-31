# 五分钟上手：装好、并确认两条通道各自可用

> 目标读者：第一次拿到这个仓库的人。照着走完，不需要问任何人，就能知道**这台机器上哪条通道能用、哪条不能**。
> 本文命令都在项目根目录执行。2026-10-29 由独立 QA **按本文件原样实跑**了一遍，命令层面全部通过；该次实跑查出的字段与判定式错误已按实测修正（记录见 [quickstart-verified.md](quickstart-verified.md)）。

## 1. 先说清楚：两条通道是独立的

| 你装了 | ChemDraw 通道 | KingDraw 通道 |
|---|---|---|
| ChemDraw 26 | 可用 | 需要 KingDraw 的 DLL |
| KingDraw | 需要 ChemDraw | 可用 |
| 两个都装 | 可用 | 可用 |
| 两个都没装 | 不可用 | 不可用 |

**只装一个就够了。** 两条通道各自 `doctor`、各自报错，一条不可用不会拖垮另一条。这是设计目标，也是本项目唯一的硬承诺。

## 2. 前置条件

| 项 | 要求 | 是否必需 |
|---|---|---|
| 操作系统 | **Windows 10 / 11（x64）** | 必需 |
| Python（主进程） | **64 位 Python 3.11**（3.11.9 实测） | 必需 |
| ChemDraw | **ChemDraw Professional 26.x（Revvity）**，且**已激活** | 想用 ChemDraw 通道才需要 |
| KingDraw | 任意近版，安装目录里有 `GRDKitDll.dll` | 想用 KingDraw 通道才需要 |

> 命令里的 `python` 指**你的 64 位 Python 3.11**。若你机器上 `python` 指向别的版本，把它换成完整路径即可。

## 3. 五分钟路径

### 步骤 1 · 拿到代码

代码已经在硬盘上的（压缩包解出、别人拷给你、或你就在本机），直接进目录：

```bash
cd chem-draw-tool
```

从远端取的：

```bash
git clone <仓库地址> chem-draw-tool
cd chem-draw-tool
```

`<仓库地址>` 要换成实际发布地址，**照抄这一行会失败**。判断自己站对了位置：这个目录里应该同时看得到 `bin/cli.py` 和 `core/chemdraw_tool/`。

### 步骤 2 · 装依赖

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` 只有三项：`rdkit`（结构解析）、`pillow`（出图与截图）、`pywin32`（仅 Windows 的 COM 绑定）。没有这个文件时等价于：

```bash
python -m pip install rdkit pillow pywin32
```

`pillow` 不是可选项：出去的图要改 dpi、转 RGB、裁留白，窗口截图要读像素。缺它时错误会伪装成「图片无法读取」，而不是「少了库」——照着报错去查图片格式，根因根本不在这。

### 步骤 3 · 取 32 位运行时（KingDraw 通道要用）

```bash
python scripts/fetch_runtime.py
```

它把 **3.11.9 embeddable 32 位 Python** 下载并解包到 `runtime/py32/`（约 10 MB，因体积不进 git）。想先看现状：

```bash
python scripts/fetch_runtime.py --verify
```

> 还没装过时这条命令返回 **rc=1** 并打印 `present: false`。那是「确实没有」这个事实，不是命令出错——看到 rc=1 就去装，别以为脚本坏了。装好之后同一条命令 rc=0。

> 只用 ChemDraw 通道可跳过这一步。反过来，只用 KingDraw 也必须先做这一步。

### 步骤 4 · 两条 doctor

```bash
# ChemDraw 通道（64 位解释器）
python bin/cli.py doctor cd --json

# KingDraw 通道（必须是 32 位解释器）
runtime/py32/python.exe bin/cli.py doctor kd --json
```

### 步骤 5 · 看到 `available: true`

两条都 `true` → 收工，去读 [docs/index.md](index.md) 决定下一步。
一条 `true` 一条 `false` → **正常**，只装了一个软件就是这样，按 §5 处理 `false` 那条。
两条都 `false` → 先看 §5 的第 1、2 条。

### 顺手验一下功能（可选）

```bash
# 分子身份：SMILES -> 规范式 / InChIKey / 分子式（64 位）
python bin/cli.py identity 'CC(=O)Oc1ccccc1C(=O)O'

# KingDraw 换算（32 位解释器）
runtime/py32/python.exe bin/cli.py kd formula --smiles 'CC(=O)Oc1ccccc1C(=O)O'

# 跨引擎对账：同一个分子过两个厂商的引擎，用 InChIKey 判断是不是同一个（64 位）
python bin/cli.py crosscheck 'c1ccccc1O'

# 存成 KingDraw 原生 .king（32 位；输入得先是 molfile）
runtime/py32/python.exe bin/cli.py kd save test/out/x.mol --out test/out/x.king

# 让 KingDraw 也出一张图（64 位；预览级，投稿请用 cd figure）
python bin/cli.py kd export test/out/x.mol --out test/out/x_kingdraw.png
```

### ChemDraw 的一组子命令（64 位）

```bash
python bin/cli.py cd draw 'c1ccccc1O'                          # 画进 ChemDraw
python bin/cli.py cd export out.png                           # 导出当前文档
python bin/cli.py cd figure out.png --width-mm 85 --dpi 1200  # 按期刊规格出图
python bin/cli.py cd read --format smiles                     # 读回结构
python bin/cli.py cd capabilities                             # 这台机器能做什么
```

投稿用的图走 `cd figure`，别用 `cd export` 直接交——后者写进 PNG 的 dpi 恒为 144。

## 4. 「看到什么算成功」——字段对照

`doctor --json` 输出的是 `DoctorReport` 字典（下面是**节选**，完整字段还有 `capabilities` / `evidence` / `evidence_note`）。**别拿版本号当判据**（版本随机器变），只看结构。

### ChemDraw 通道

```jsonc
{
  "channel": "chemdraw",
  "available": true,            // ← 唯一的总判定
  "version": "",                // 实测恒为空串：app.Name 拿不到版本，别拿它当判据
  "home": "",                   // 实测恒为空串；真正的 exe 路径在 details.fullname
  "details": {
    "progid": "ChemDraw_x64.Application",
    "fullname": "C:\\Program Files\\...\\ChemDraw.exe",   // ← 装在哪看这个字段
    "attached": false,          // true = 复用了你已经开着的实例
    "started_by_us": true,      // true = 这次 doctor 自己拉起的进程
    "documents_open": 0,        // 数字即可
    "elapsed_ms": 1038          // 数字即可，量级 1 秒
  },
  "failures": []                // 必须为空数组
}
```

判定：`available == true` 且 `failures == []`。

### KingDraw 通道

```jsonc
{
  "channel": "kingdraw",
  "available": true,
  "version": "GRDKitDll exports=12/12",  // ← 关键是 12/12，不是版本号
  "details": {
    "exports_found": ["supKingToJson", "cleanUp", "..."],  // ← 是名字数组，不是数字
    "exports_expected": 12,                                // ← 数字在这里
    "exports_missing": [],               // 必须为空
    // "bind_errors": [...]  ← 这个键出现就说明有函数绑不上，看内容
    "elapsed_ms": 71
  },
  "failures": []
}
```

判定：`available == true`、`len(details.exports_found) == details.exports_expected`、`exports_missing == []`、没有 `bind_errors`。

> 写 `exports_found == exports_expected` 是错的：`exports_found` 是名字数组，跟数字比永远为假。这个错曾经原样写在本文里，照着抄会得到「通道明明正常却判定失败」的假警报。

> `doctor` 是**动作**不是读配置：它会真的建一个 COM 实例、真的调一次 DLL。所以结论代表「这台机器**现在**能不能干」，不代表「理论上支持」。

## 5. 常见错误对照表（全部来自本机实测）

**`doctor cd` 失败、错误描述为空、ChemDraw 窗口根本没出现**

- **原因**：**ChemDraw 启动时挂着未勾选的激活提示模态框**，COM 创建被它挡住，Windows 给的错误描述是空的
- **处置**：手动打开一次 ChemDraw，勾上「以后不再显示」并关掉，再跑 doctor

**`doctor cd` 报 `E02`**

- **原因**：许可/激活未完成，COM 建不了文档
- **处置**：在 ChemDraw 界面里完成激活；激活不了的机器上该通道不可用

**64 位解释器跑 `doctor kd` 报 `E04`**

- **原因**：`GRDKitDll.dll` 是 **x86**，64 位进程加载不了；本项目已把它包成结构化错误
- **处置**：换 `runtime/py32/python.exe bin/cli.py doctor kd`（步骤 3 装的那个）

**自己写代码 `ctypes.WinDLL('GRDKitDll.dll')` 时抛 `OSError: [WinError 193] 不是有效的 Win32 应用程序`**

- **原因**：同上，只是绕过了本项目的适配层，看到的是裸错误
- **处置**：同上；裸 WinError 193 就是位宽不匹配的原始形态

**32 位解释器跑 `doctor cd` 报 `E04`：`ChemDraw automation needs the 64-bit interpreter; this one is 32-bit`**

`detail` 是 `sys.maxsize=2147483647`（不是空的）。`E04` 是共享的「解释器位宽不对」码，
两个方向都用它：ChemDraw 这边是「要 64 位」，KingDraw 那边是「要 32 位」，靠 `message` 区分。
`E08` 是 `NOT_INSTALLED`，与位宽无关。

- **原因**：`ChemDraw_x64.Application` 是 **64 位**本地服务器，32 位进程连不上
- **处置**：用 64 位 Python 跑 ChemDraw 通道；两条通道天生要两个解释器

**MCP 常驻进程中 `chemdraw_*` 工具报 `E10`（`COM_STALLED`）**

- **原因**：ChemDraw 没在截止时间内应答，最常见的就是它弹了个对话框（激活提示、另存为、大图导出进度）在等人点。t21 之前的表现不是报错而是**整个服务器不再应答**，连 `ping` 都超时
- **处置**：去看 ChemDraw 窗口把对话框关掉，然后重试。通道在超时后会被标记 `wedged`，后续调用**立即**返回同一个 `E10`（不会每个请求再卡一次）；冷却 `CHEMTOOL_COM_RETRY_AFTER`（默认 30 s）后下一个请求会自动探测一次，通了就恢复，不需要重启服务器。这期间 KingDraw 通道一直可用
- **调试**：截止时间用 `CHEMTOOL_COM_TIMEOUT`（默认 120 s）调，探测预算用 `CHEMTOOL_COM_PROBE_TIMEOUT`（默认 5 s）调

**`runtime/py32/python.exe` 不存在**

- **原因**：没跑 `scripts/fetch_runtime.py`
- **处置**：跑它，或先 `--verify` 看现状

**代码放在**中文路径**下，导出图片**不报错但文件没生成****

- **原因**：ChemDraw 的 `SaveAs` 对非 ASCII 路径是**空操作**：不抛异常、不产文件。本项目目录名就带中文，已踩过
- **处置**：适配器已改为「先写 ASCII 临时目录再拷过去」，正常使用不受影响。**自己写脚本直接调 `SaveAs` 时**必须先落 ASCII 路径；本卷 8.3 短名被禁用，`GetShortPathName` 这条退路不存在

**导出的 PNG 被出版社判不合格：dpi 显示 **144**、色彩模式 RGBA**

- **原因**：ChemDraw 写进 PNG 的 dpi 元数据**恒为 144**，与传入 `resolution` 无关；模式是 RGBA
- **处置**：用 `artwork.normalize(...)` 改写 dpi、转 RGB、存 TIFF；或改交矢量（EPS/SVG）

**截图（`capture_window`）拿到**白屏 / 纯色**画面**

- **原因**：KingDraw 是 WPF 应用，`PrintWindow` 对它常返回白帧（`ok=True`、单色）；结构画布是 DirectX 表面，`PrintWindow` 本来就不包含
- **处置**：代码会自动回退 BitBlt，但**必须先把窗口提到前台**——否则抓到的是挡在前面的别的窗口（早期版本就这样「证明」过一次渲染）。画布区是白的属正常，不代表结构没加载；判据是颜色数与字节数像不像真实界面

**控制台打印含中文的路径时 `UnicodeEncodeError` / 乱码**

- **原因**：Windows 控制台默认 cp1252
- **处置**：`bin/cli.py` 入口已把 stdout/stderr 重配为 UTF-8；自己写脚本时先 `export PYTHONIOENCODING=utf-8`（git bash）或 `$env:PYTHONIOENCODING="utf-8"`（PowerShell）

**某个 COM 属性名突然报不存在，但明明有（`Name` 报错、`name` 正常）**

- **原因**：曾用 `EnsureDispatch` 生成过类型库缓存，之后属性名变成**大小写敏感**
- **处置**：生产代码一律用 `win32com.client.dynamic.Dispatch`（本项目已如此）；历史缓存的机器删掉 `site-packages/win32com/gen_py` 下的缓存目录

**导出尺寸卡在某个值上不去（本机约 2637×2191）**

- **原因**：这台机器的 ChemDraw 有**导出像素上限**，dpi 传 1500 或 2183 结果一样
- **处置**：`export_figure` 撞上限会 warning 并按实际尺寸返回，不假装成功；需要更大图请分块或改交矢量

**`kd king` 读 `.king` 时 `nodes` 为空**

- **原因**：`kingCleanUp` 期望的输入形态还没定论（原始字节与 V2000 molblock 都返回 `success:true` 但空结果）
- **处置**：读 `.king` 走已验证的 `supKingToJson` 路径（`kd king` 即此路径）；`kingCleanUp` 暂不承诺可用


## 6. 想跑自检（可选）

```bash
# KingDraw 适配器：14 项断言（32 位解释器）
runtime/py32/python.exe test/test_kd_adapter.py

# ChemDraw 适配器：17 项断言（64 位解释器）
python test/test_cd_adapter.py

# 跨引擎对账：11 项断言（64 位解释器）
python test/test_crosscheck.py

# KingDraw 存 .king：7 项断言（32 位解释器）
runtime/py32/python.exe test/test_kd_save.py
```

想看 CLI 有哪些命令：

```bash
python bin/cli.py --help
python bin/cli.py doctor --help
```

> `doctor all` 会在**当前**解释器上同时探测两条通道。用 64 位跑 `doctor all` 时 kd 那一半必然报 `E04`——这是位宽提示不是故障。要看真实 kd 状态，请用 32 位解释器单跑 `doctor kd`。
>
> 这种情况下整条命令的退出码是 **rc=1**：退出码的含义是「所有通道都可用」，不是「命令本身跑成功了」。一条通道真不可用时 rc=1 是正确行为，别拿它当失败重试。

## 7. 未验证的东西（照实写，不吹）

以下**没有**在本项目验证过：

- **跨机器可移植性**：只在开发机（Windows 11 x64 + ChemDraw 26.1.0.6327）跑过，没有第二台机器复现。
- **ChemDraw 其他版本**：25.x 及更早、27.x 均未测试，COM 界面是否有差异未知。
- **非英文界面 / 非默认安装路径**：未测试；安装位置靠默认目录与注册表探测，特殊部署可能找不到。
- **KingDraw 版本差异**：只对开发机那一版做过 ABI 取证（12 个导出）。
- **只装 KingDraw、不装 ChemDraw 的完整流程**：设计上支持，实测覆盖有限。
- **PDF 交付**：本机 ChemDraw 的导出类型里**没有 PDF**，矢量只能走 EPS/SVG。
- **`--keep-open` 留不住 ChemDraw 窗口**：ChemDraw 注册为 `LocalServer32`，COM 引用一释放进程就自己退出，所以这个开关只能做到「不主动 Quit」，做不到「跑完还留在你桌面上」。实测 `doctor cd --keep-open` 返回后 `tasklist` 里依然是 0 个 ChemDraw.exe。要接着用，从开始菜单自己打开。
- **MCP 层与 DSH 插件层**：MCP server 已实现（12 个工具，stdio JSON-RPC）；DSH 插件已写好并通过「能被 DSH 加载」的验证，但 **desktop profile 的接线、十个工具的端到端调用尚未验证**。本文不代表「全部功能已就绪」。

## 8. 接下来读什么

[docs/index.md](index.md) 是所有文档的索引，按「你现在的处境」分好了该读哪份。

---

*文档版本：2026-10-29 · 命令与字段由独立 QA 按本文件原样实跑核对（含当时 CLI 尚无 `cd` 子命令组、现已补上）；实跑记录见 [quickstart-verified.md](quickstart-verified.md)*
