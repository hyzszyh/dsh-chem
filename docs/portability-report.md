# 可移植性审查：换一台机器，哪里会崩

> 审查对象：`core/`、`bin/`、`scripts/`、`test/` 下全部 `.py`（51 个文件），外加 `pyproject.toml`、`requirements.txt`、`README.md`、`docs/quickstart.md`。
> 审查日期 2026-10-29。每条都指到 `文件:行号`，原文照抄，不写「建议增加测试」这类空话。
> 实证来源：附录 A 的探针脚本（本机 64 位 Python 3.11.9 实跑）+ 附录 B 的可复现 grep。

## 摘要

**① 高：别人直接跑不起来 / 静默产出废图**

- **条数**：4
- **一句话**：缺 Pillow、`kd_open` import 即崩、test/ 写死个人路径、缺 Pillow 时静默不裁边

**② 中：能跑，但出问题时你查不出来**

- **条数**：9
- **一句话**：个人路径进产品代码（两份副本）、hint 写死别人机器的解释器、`ui_capture` 裸 import、`kd_native` 只捕 `OSError`、KingDraw 版本无记录、3.9 声明无证据 等

**③ 低：可接受的假设，但要写进 README**

- **条数**：7
- **一句话**：`__file__` 推导根、`sys.maxsize` 位宽判据、tasklist 只作 best-effort 等


**一句话结论**：代码本身的移植性比预期好 —— 除 `kd_open.py`（import 期）与 `ui_capture.py`（两处裸 import）外，所有 Windows 专有依赖都懒加载并降级成结构化 `Failure`（附录 A 实测：`doctor cd` 在 pywin32 缺失时返回 `E08/import`）。真正会让新人卡住的是**依赖清单漏了 Pillow**（连带出图链路静默降级）和**仓库里躺着一批写死 `<workdir>\...` 的脚本**。

---

## ① 高优先级（会让别人直接跑不起来，必须改）

### H1 · `requirements.txt` / `pyproject.toml` 漏了 Pillow，而出图主链路依赖它

**位置**
- `requirements.txt:6` — `rdkit>=2023.9`（全文只有 rdkit + pywin32，无 Pillow）
- `pyproject.toml:12-15` — `dependencies = ["rdkit>=2023.9", "pywin32>=306; sys_platform == 'win32'"]`
- 用到 Pillow 的地方：`core/chemdraw_tool/artwork.py:74`（`from PIL import Image`）、`core/chemdraw_tool/adapters/cd_com.py:132`（`_dpi_tag`）、`core/chemdraw_tool/adapters/cd_com.py:149`（`_trim_png`）、`core/chemdraw_tool/ui_capture.py:122`（`from PIL import ImageGrab`）

**原文**（`artwork.py:73-80`）
```python
def _open(path):
    from PIL import Image
    return Image.open(path)
```

**为什么是问题**：`docs/quickstart.md` 让新人 `pip install -r requirements.txt` 之后就去用工具，而 Pillow 不在清单里、也不是 pywin32/rdkit 的依赖。于是 `artwork.check()` 会走到 `except Exception` 分支，报一句**误导性的** `E06 cannot read image`（实测见附录 A-D：detail 里才是 `ModuleNotFoundError: import of PIL halted`）。出图验收是 M2 的核心能力，新人第一张图就会撞上。

**建议改法**：两处都加 `pillow>=10`（Pillow 12.3.0 是开发机实测版本，10 是保守下限）；若想保持「核心轻量」，就改成 extras（`[project.optional-dependencies] artwork = ["pillow>=10"]`）+ 在 quickstart 里明确写出 `pip install -e .[artwork]`，并让 `artwork.check()` 在缺 Pillow 时返回 `E08 NOT_INSTALLED`（message: `Pillow is required for artwork.check`），而不是 `E06 cannot read image`。

### H2 · `adapters/kd_open.py` 在 import 期就调 `ctypes.WinDLL`，非 Windows 上 import 即崩

**位置**：`core/chemdraw_tool/adapters/kd_open.py:69-74`
**原文**
```python
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, ctypes.c_ssize_t)

_gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
```

**为什么是问题**：`ctypes.WinDLL` 只在 Windows 上存在。这个模块是**全项目唯一**在模块级绑定 Win32 的（同项目的 `ui_capture.py:22`、`kd_uia.py:35`、`doctor/cd.py:71`、`cd_com.py:260` 全部是函数内懒加载）。实测把 `ctypes.WinDLL` 摘掉模拟非 Windows：
```nowrap
chemdraw_tool.adapters.kd_open    FAIL AttributeError: module 'ctypes' has no attribute 'WinDLL'
```
而 `core/chemdraw_tool/cli.py:126` 里 `from .adapters import kd_open` 是 `kd open` 子命令的**函数内** import —— 也就是说别人在非 Windows 或缺少 user32 的环境里敲 `kd open`，拿到的是 Python traceback，而不是项目统一约定的结构化 `Failure`。这与 `doctor cd` 的行为（附录 A-C：pywin32 缺失 → `E08/import`）不一致。

**建议改法**：把三个 DLL 句柄收进惰性访问器，例如
```python
_LIB = {}
def _lib(name):
    if name not in _LIB:
        _LIB[name] = ctypes.WinDLL(name, use_last_error=True)
    return _LIB[name]
```
并在 `open_file` / `capture_window` / `list_pids` 入口用 `try: ... except (AttributeError, OSError) as exc:` 包成 `Result(ok=False, failure=Failure(code=ErrorCode.NOT_INSTALLED, stage='platform', detail=...))`，message 写「the KingDraw open channel needs Windows Win32 APIs」。

### H3 · `test/` 里 12 个脚本把开发者机器的绝对路径写进 `sys.path`

**位置与原文**（全部是 `sys.path.insert(0, r'<repo>\core')` 这一类）

**`test/e2e_cd_open.py:2`**

- **写死的东西**：`ROOT = r'<repo>'`

**`test/e2e_cd_reopen.py:2`**

- **写死的东西**：同上

**`test/e2e_cd_ascii.py:2`**

- **写死的东西**：`ROOT = ...`；`:6` 另写 `ascii_dir = r'D:\Test'`

**`test/e2e_visual_check.py:14`**

- **写死的东西**：`ROOT = ...`

**`test/probe_artwork.py:2`**

- **写死的东西**：`sys.path.insert(0, r'D:\...\core')`

**`test/probe_datatypes.py:4` / `probe_docs_collection.py:4` / `probe_makeatom.py:4`**

- **写死的东西**：`ROOT = ...`

**`test/probe_signatures.py:28`**

- **写死的东西**：`path = r'D:\...\docs\com_item_document.txt'`

**`test/probe_uia.py:9` / `test/probe_printwindow64.py:15`**

- **写死的东西**：`sys.path.insert(0, r'D:\...\core')`；后者 `:61` 还写死 `outdir`

**`test/probe_king_worker.py:4-5`**

- **写死的东西**：直接调用 `D:\...\runtime\py32\python.exe` 与 `D:\...\bin\kd_worker.py`

**`test/probe_kd_ret.py:13`、`probe_kd_exports.py:12`、`probe_kd_open.py:20`、`probe_kd_signatures.py:21`、`probe_kd_uia.py:22`**

- **写死的东西**：`D:\tool\KingDraw` 作为 DLL 默认路径


**为什么是问题**：这些文件在仓库里看起来就是「验证脚本」，新人 clone 下来第一反应就是跑一个，结果 `FileNotFoundError` 或 import 到空气里。注意**真正的回归测试是可移植的**：`test/acceptance_m1.py:38-40` 用 `os.path.dirname(os.path.abspath(__file__))` 推导 `ROOT`，`test/test_kd_*.py` 走 `KINGDRAW_HOME` 环境变量，`test/test_cd_adapter.py:275` 用 `TEMP`。所以问题只集中在 `probe_*` 与 `e2e_*`。

**建议改法**：统一改成三行推导（与 `bin/cli.py:13-15` 同一写法）
```python
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'core'))
```
KingDraw 路径改成 `os.environ.get('KINGDRAW_HOME', ...)`（`probe_kd_open.py:20` 其实已经这么写了，只是默认值仍是个人路径）。另外建议把 `probe_*`/`e2e_*` 移进 `test/probes/` 并在开头加一行 `# dev-only probe, not part of the test suite`，让新人分得清「该跑的」和「当时取证用的」。

### H4 · 缺 Pillow 时 `_trim_png` 静默返回 `None`，裁边/转 RGB 被跳过且无提示

**位置**：`core/chemdraw_tool/adapters/cd_com.py:148-151`
**原文**
```python
    try:
        from PIL import Image
    except Exception:
        return None
```

**为什么是问题**：这是 ChemDraw 通道**导出主链路**上的一环（`cd_com.py:1146` `trim_info = _trim_png(...)`）。没有 Pillow 时它一声不响地返回 `None`，结果是：PNG 保持 RGBA、保持 Width/Height 加出来的透明留白、dpi 仍是 144。调用方只看到 `'trim': null`，很容易当成「这张图本来就没什么可裁的」而直接交稿 —— 而出版社退的正是这三件事（见 `docs/journal-artwork.md`）。这和 H1 同源，但即便补了依赖，这个 `except` 也把「图片损坏」和「缺库」压成了同一个无声结果。

**建议改法**：区分两种失败并回传原因，例如
```python
    try:
        from PIL import Image
    except ImportError as exc:
        return {'skipped': 'pillow-missing', 'detail': str(exc)}
```
让 `export()` 把 `skipped` 放进 `Result.warnings`，至少调用方能看到「这张图没裁边，因为 Pillow 没装」。

---

## ② 中优先级（能跑，但会让诊断变困难）

### M1 · 失败提示里写死了开发者机器的解释器路径

**位置**：`core/chemdraw_tool/cli.py:176-179`
**原文**
```python
            hint='Run with '
                 r'%LOCALAPPDATA%\Programs\Python\Python311\python.exe',
```

**为什么是问题**：这条 `hint` 恰好出现在「用 32 位解释器跑 ChemDraw 命令」的错误路径上 —— 也就是新人最容易撞的时刻。它会告诉对方去执行一个**别人机器上的用户名目录**，比不给建议更糟。
**建议改法**：`hint='Run this command with a 64-bit CPython 3.11 (e.g. `py -3.11` or the full path shown by `py -0p`)'`，或者干脆 `hint='See docs/quickstart.md §2 for the two-interpreter layout'`。

### M2 · 个人 KingDraw 目录被写成产品的第一个默认值（且两份副本）

**位置**：`core/chemdraw_tool/adapters/kd_native.py:49-53` 与 `core/chemdraw_tool/doctor/kd.py:21-25`
**原文**（两处逐字相同）
```python
DEFAULT_HOMES = [
    r'D:\tool\KingDraw',
    r'C:\Program Files\KingDraw',
    r'C:\Program Files (x86)\KingDraw',
]
```

**为什么是问题**：①`D:\tool\KingDraw` 是开发机的私有布局，被当成**首选**探测路径；②同一张表被复制了两份，将来改一处忘另一处；③`kd_native.py:251` 的失败 detail 会把 `', '.join(DEFAULT_HOMES)` 原样回给用户，等于把别人的目录结构展示给所有人。
**建议改法**：删掉个人路径，保留 `Program Files` / `Program Files (x86)`；并且把**整个 `find_home` 收敛成一份**：`kd_native.py:176-198` 与 `doctor/kd.py:58-80` 现在是从注释到逻辑逐行雷同的两个副本（都是「显式 → `KINGDRAW_HOME` → `HKCR\kingfile\shell\open\command` → 默认表」）。`doctor/kd.py:73` 直接 `candidates.extend(DEFAULT_HOMES)`，等于把这张私有表又抄了一遍。建议 `doctor/kd.py` 改成 `from .adapters.kd_native import find_home`（`doctor` 已经复用了 `BINDINGS`，同一模式）。

### M3 · KingDraw 的 ABI 是实测出来的，但代码里没有任何版本记录

**位置**：`core/chemdraw_tool/adapters/kd_native.py:55-58`（`_SPECS` 表，注释只说 "discovered by the probes"）、`core/chemdraw_tool/doctor/kd.py:15-19`（`EXPORTS` 12 个名字）
**对比**：KingDraw 的版本信息只出现在**文档**里 —— `PLAN.md:66-70` 的 `.king` 头部 `KingDraw V2.2 / 20180420`；对 `core/` 全目录 grep `20180420`、`version` 均无命中。

**为什么是问题**：别人装了同系列的新版 KingDraw，`smilesToMol` 之类的签名若变了，症状是 `exports=11/12` 或调用后拿到空指针，而 `doctor` 只会说「少一个导出」，不会说「你可能装了不同版本的 KingDraw」。排查成本全落在用户身上。
**建议改法**：`doctor kd` 的 `details` 里加 `dll_version`（`ctypes` + `GetFileVersionInfoW`，或 `win32api.GetFileVersionInfo`，pywin32 已在依赖里），并把开发机实测版本写进 `README.md` 与 `kd_native` 的模块 docstring（现在只有 `cxml.py:7` 写了「verified against ChemDraw 26」这种单边信息）。

### M4 · 32 位版 ChemDraw 会命中备选 ProgID，但跨位宽 COM 一定失败，且错误描述为空

**位置**：`core/chemdraw_tool/adapters/cd_com.py:81`
**原文**：`PROGIDS = ('ChemDraw_x64.Application', 'ChemDraw.Application')`

**为什么是问题**：备选 ProgID 本意是兼容，但 32 位 ChemDraw 的本地服务器无法被 64 位进程实例化，Windows 返回的错误描述常常是空的（正是 `PROGRESS.md:51` 记下的那个坑的另一种成因）。用户会看到「连不上」，而 `doctor` 分不清「没装」「没激活」「装的是 32 位」。
**建议改法**：在 `doctor cd` 里追加一次注册表探测（`HKLM\SOFTWARE\WOW6432Node\Classes\ChemDraw.Application`），命中就直接给一条明确 failure：`ChemDraw 32-bit detected; this tool needs ChemDraw Professional 64-bit`。

### M5 · `requires-python = ">=3.9"` 没有任何执行证据

**位置**：`pyproject.toml:10`
**为什么是问题**：开发机只有 3.11.9，仓库里也没有 CI（`.github/` 不存在）。静态看代码是 3.9 兼容的（`core/` 全部 14 个模块都有 `from __future__ import annotations`，没有 `match` 语句，`dataclass` 字段都是 `from typing import Optional` 风格），但「声明支持 3.9」这件事没人验证过。`bin/cli.py`、`bin/kd_worker.py`、`bin/kd_uia.py` 这三个启动器**没有** `from __future__`，目前也没用新语法，属于「恰好安全」。
**建议改法**：要么改 `requires-python = ">=3.11"`（与 `scripts/fetch_runtime.py:23` 固定的 3.11.9 一致，最省事），要么保留 3.9 但加一条最小冒烟（`python -c "import chemdraw_tool.cli, chemdraw_tool.artwork"`）到 CI 的 3.9/3.11 矩阵里。

### M6 · ASCII 暂存目录的兜底是 `C:\Windows\Temp`，而首选可能本身就是中文

**位置**：`core/chemdraw_tool/adapters/cd_com.py:97-101` 与使用处 `:958-961`
**原文**
```python
_ASCII_TEMP_CANDIDATES = (
    None,               # tempfile.gettempdir()
    r'C:\Windows\Temp',
    r'C:\Temp',
)
```
```python
for base in _ASCII_TEMP_CANDIDATES:
    candidate = tempfile.gettempdir() if base is None else base
    if not os.path.isdir(candidate) or not _is_ascii(candidate):
```

**为什么是问题**：逻辑本身是对的（逐个验证 ASCII 才用），但兜底项 `C:\Windows\Temp` 在受限账户/受管机器上可能不可写，`C:\Temp` 默认不存在 —— 也就是说在「用户名是中文 + 无写权限」的机器上，三条候选全灭，而失败路径给出的建议只是「换个路径」。
**建议改法**：首选改成主动创建 `tempfile.mkdtemp(prefix='cdtool-')` 并断言 `_is_ascii`（`%TEMP%` 通常是 ASCII，但用户名决定它可能不是），失败再退到 `C:\Windows\Temp`；三条都不可用时返回明确 `Failure(code=E08, stage='stage_path', detail='no ASCII-writable temp dir; set TEMP to an ASCII path')`。

### M7 · 唯一一处 `subprocess` 没指定 `encoding`，与全项目 UTF-8 约定不一致

**位置**：`core/chemdraw_tool/doctor/cd.py:38-41`
**原文**
```python
        out = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq ChemDraw.exe', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=15,
        ).stdout
```
**为什么是问题**：`text=True` 不带 `encoding` 时按 `locale.getpreferredencoding()` 解码，在中文 Windows 上就是 cp936。`tasklist` 的 CSV 目前是纯 ASCII 所以不炸，但同一个项目里 `mcp_server.py:41-42`、`test/probe_king_worker.py:6` 都显式写了 `encoding='utf-8', errors='replace'`，这里是个将来会咬人的例外。
**建议改法**：补上 `encoding='utf-8', errors='replace'`（`errors='replace'` 保证 cp936 输出也不会抛）。

### M8 · `ui_capture.py` 同样在函数里裸 import，非 Windows/缺 Pillow 时抛异常而不是给 `Failure`

**位置**：`core/chemdraw_tool/ui_capture.py:21-23` 与 `:118-122`
**原文**
```python
def _windows() -> list:
    import win32gui
    import win32process
```
```python
def capture(hwnd: int, out_path: str, settle: float = 0.2,
            raise_to_front: bool = True) -> Result:
    '''Grab one window's rectangle into a PNG. Returns the file facts.'''
    import win32gui
    from PIL import ImageGrab
```

**为什么是问题**：这两处 import 在 `try` 之外（`:124` 的 `try` 只包住了 `win32gui.GetWindowRect`）。所以「没装 Pillow」或「不在 Windows」时，`capture()` 直接抛 `ModuleNotFoundError`/`ImportError`，与函数签名承诺的 `-> Result` 不符；同文件的其它 Windows 调用（`flash_to_front`、`:110-115`）都老老实实包了 `except`。
**建议改法**：把这两个 import 移进 `try`，失败时返回 `Result(ok=False, failure=Failure(code=ErrorCode.NOT_INSTALLED, stage='import', detail=str(exc)))`；`_windows()` 同理返回 `[]` 并在调用处（`:60`、`:192`）给出「没有可枚举的窗口」的明确 failure。

### M9 · `kd_native` 的加载守卫只捕 `OSError`，捕不到「非 Windows 上 `ctypes.WinDLL` 不存在」

**位置**：`core/chemdraw_tool/adapters/kd_native.py:263-264`
**原文**
```python
                self._dll = ctypes.WinDLL(os.path.join(home, DLL_NAME))
            except OSError as exc:
```

**为什么是问题**：DLL 加载失败在 Windows 上是 `OSError`（已正确处理），但在没有 `WinDLL` 属性的平台上，异常是 `AttributeError`，不会被这一条 `except` 抓住，于是 `load()` 抛出去，`_load_failure` 白设。同类问题在 `kd_open` 是 import 期崩（H2），这里则是调用期崩。
**建议改法**：`except (OSError, AttributeError) as exc:`（或先 `getattr(ctypes, 'WinDLL', None)` 判空后直接给 `KD_NOT_FOUND` + `stage='platform'`），message 明确写「this channel requires Windows」。
---

## ③ 低优先级（可接受的假设，但要在 README 里写明）

**L1**

- **假设**：两个解释器分工：64 位跑 COM/rdkit，32 位跑 `GRDKitDll.dll`
- **位置**：`core/chemdraw_tool/kd_worker.py:3`、`mcp_server.py:3-7`、`scripts/fetch_runtime.py:1-5`
- **现状判断**：**合理的硬约束**，且用 `sys.maxsize` 守卫并给结构化 Failure
- **写进 README 的话**：「本项目需要两个解释器；它们的分工由位宽决定，不是配置项」

**L2**

- **假设**：位宽判据统一用 `sys.maxsize`
- **位置**：`cli.py:186`、`doctor/cd.py:61`、`doctor/kd.py:117`、`kd_native.py:172`、`kd_open.py:899`、`mcp_server.py:143`
- **现状判断**：**可靠**（CPython 上 32 位是 2^31-1、64 位是 2^63-1，`> 2**32` 判别正确）。唯一不一致：`test/acceptance_m1.py:66` 写成 `sys.maxsize < 2 ** 62`，等价但风格不同
- **写进 README 的话**：无需

**L3**

- **假设**：用 `__file__` 推导项目根，不依赖 CWD
- **位置**：`bin/cli.py:13-15`、`bin/kd_worker.py:11-13`、`bin/kd_uia.py:13-15`、`mcp_server.py:23-26`
- **现状判断**：**好**：所以 `python bin/cli.py` 在任何目录都能跑。代价是不能用 `python -m chemdraw_tool` 跑 embeddable（已在 docstring 写明）
- **写进 README 的话**：「用 `python bin/cli.py`，不要 `python -m`」

**L4**

- **假设**：`tasklist` / `taskkill` 只作 best-effort
- **位置**：`doctor/cd.py:34-49`（`except Exception: return []`）、`test/test_cd_adapter.py:76`、`test/test_cd_cli_mcp.py:64`
- **现状判断**：**可接受**：失败被吞成空列表，`doctor` 仍能出结论（`instances_before: []`）。但只有测试会真的 `taskkill`
- **写进 README 的话**：「Windows 上的进程清理用 tasklist/taskkill；非 Windows 不支持」

**L5**

- **假设**：`kd_open.py:916` 的 `C:\Python311\python.exe` / `C:\Python312\python.exe` 兜底
- **位置**：`core/chemdraw_tool/adapters/kd_open.py:902-927`
- **现状判断**：**可接受**：前面已有 `PYTHON64_ENV` 环境变量、`sys.executable`、`LOCALAPPDATA\Programs\Python\Python3xx` 三级探测，这两条只是最后兜底
- **写进 README 的话**：「UIA 需要一个装了 pywinauto 的 64 位解释器，可用 `PYTHON64_ENV` 指定」

**L6**

- **假设**：UIA 需要 `pywinauto`，但它不在依赖里
- **位置**：`core/chemdraw_tool/kd_uia.py:33-38`（`_import_pywinauto()` 返回 None）
- **现状判断**：**可接受**：`available()` 为 False 时上层降级，不崩；属于可选增强
- **写进 README 的话**：「KingDraw 的文档级验证需要 `pip install pywinauto`；不装就只能看像素」

**L7**

- **假设**：项目路径可以含中文
- **位置**：`cd_com.py:1017`、`:1095-1112`（非 ASCII 目标先写 ASCII 暂存再拷贝）
- **现状判断**：**已处理**：这是产品主动绕开的场景，`PROGRESS.md:198` 有实测记录
- **写进 README 的话**：「本项目目录放在中文路径下是受支持的（导出会先落 ASCII 暂存）；但自己写脚本直接调 `SaveAs` 时要先落 ASCII 路径」


### 附带的仓库卫生（不影响运行，但会让人误判）

- 仓库根有三个开发残留：`_probe_rdcdxml.py`、`_probe32.ps1`、`_kdcom.ps1` —— 既不是包的一部分，也没有文档说明。
- `test/out/qs_verify/` 里躺着一份**含 venv 的整库副本**（`test/out/qs_verify/chem-draw-tool/` 与 `test/out/qs_verify/venv/`），是当时验证 quickstart 留下的。已被 `.gitignore` 的 `test/out/` 覆盖，不会进 git，但会让人以为仓库里有两份源码。
- `.gitignore` 本身是**合格**的：`__pycache__/`、`runtime/py32/`、`runtime/*.zip`、`test/out/`、`.agent-teams/` 都排除了 —— 这条不需要改。

### 顺带发现（不属于可移植性，但既然翻到了）

`core/chemdraw_tool/cdxml.py:7-9` 的模块 docstring 与代码**互相矛盾**：

```text
Format notes (verified against ChemDraw 26): a CDXML page holds fragment nodes;
each atom is n with Element = atomic number and p = 'x y' in points; each bond
is b with B = bond order and p0/p1 pointing at atom ids.
```

而同一文件的 `:73-75` 实际写的是 `B="<起原子 id>"`、`E="<终原子 id>"`、`Order="<键级>"`：

```python
'B="%d"' % (bond.GetBeginAtomIdx() + 1),
'E="%d"' % (bond.GetEndAtomIdx() + 1),
'Order="%d"' % order,
```

代码是对的（`PROGRESS.md:212-219` 有那次静默插入 0 原子的完整修复记录），**错的是 docstring**。下一句 `PROGRESS.md:219` 还专门写了「B/E 装两个原子的 id，Order 装键级」—— 也就是说谁照 docstring 写新代码，就会重新引入那个 bug。建议删掉 docstring 里那半句。

---

## 附录 A · 实测证据

探针脚本 `%TEMP%\portability_probe.py`（64 位 Python 3.11.9，2026-10-29 实跑）：

```text nowrap
== A. import laziness (what a bare import pulls in) ==
  chemdraw_tool                          ok   heavy=['winreg']
  chemdraw_tool.models                   ok   heavy=['winreg']
  chemdraw_tool.artwork                  ok   heavy=['winreg']
  chemdraw_tool.adapters.kd_native       ok   heavy=['winreg']
  chemdraw_tool.adapters.cd_com          ok   heavy=['winreg']
  chemdraw_tool.doctor.cd                ok   heavy=['winreg']
  chemdraw_tool.doctor.kd                ok   heavy=['winreg']
  chemdraw_tool.cli                      ok   heavy=['winreg']

== B. kd_open import when ctypes.WinDLL is absent (simulates non-Windows) ==
  chemdraw_tool.adapters.kd_open         FAIL AttributeError: module 'ctypes' has no attribute 'WinDLL'

== C. doctor.cd.inspect() with pywin32 unavailable ==
  available=False failures=['E08/import']
  message='pywin32 is not installed for this interpreter'

== D. artwork.check() with Pillow unavailable ==
  ok=False code=E06 message='cannot read image' detail='ModuleNotFoundError: import of PIL halted; None in sys.modules'
```

读法：A 说明**除 `kd_open` 外**所有模块都能在任何平台 import（Pillow / rdkit / pywin32 / pywinauto 全是懒加载）；B 是 H2 的直接证据；C 说明「懒加载 + 结构化 Failure」这套模式已经在 `doctor cd` 上生效，`kd_open` 应该照抄；D 是 H1 的证据 —— 缺 Pillow 时错误码是 `E06`（解析失败）而不是 `E08`（缺依赖），用户会去怀疑图片本身。

## 附录 B · 可复现的检查命令

```bash
cd $REPO

# 1) 硬编码绝对路径（排除 test/out 里的产物副本）
grep -rn -E '[A-Za-z]:\\\\|[A-Za-z]:/' --include=*.py core bin scripts test \
  | grep -v 'test/out/'

# 2) 模块级 Win32 绑定（应为空，除了 kd_open.py:69-74）
grep -rn -E '^_[a-z0-9]+ = ctypes\.(WinDLL|WINFUNCTYPE)' --include=*.py core

# 3) 位宽判据是否统一
grep -rn 'sys.maxsize' --include=*.py core bin test | grep -v 'test/out/'

# 4) 第三方 import 与依赖清单对账
grep -rn -E '^\s*(from|import) (PIL|rdkit|pywinauto|win32|pythoncom)' \
  --include=*.py core | sort -u
cat requirements.txt

# 5) 个人路径（应为空）
grep -rn '<user>' --include=*.py core bin scripts
```

## 附录 C · 依赖清单对账（问题 5 的直接回答）

**`rdkit`**

- **出现在**：`identity.py:18`、`cdxml.py:27,61`、`cd_com.py:189,203,654,813,834`
- **清单里有吗**：✅ `requirements.txt:6`
- **判断**：核心必需

**`pywin32`（`win32com`/`pythoncom`/`win32clipboard`/`win32gui`/`win32process`/`win32con`）**

- **出现在**：`cd_com.py:260,469,595`、`doctor/cd.py:71`、`ui_capture.py:22,75,95,108,121`
- **清单里有吗**：✅ `requirements.txt:8`（带 `sys_platform == 'win32'`）
- **判断**：核心必需（Windows）

**`Pillow`**

- **出现在**：`artwork.py:74,79`、`cd_com.py:132,149`、`ui_capture.py:122`
- **清单里有吗**：❌ **缺失**
- **判断**：**核心必需** → H1

**`pywinauto`**

- **出现在**：`kd_uia.py:35`（懒加载，失败返回 None）
- **清单里有吗**：❌ 缺失（设计如此）
- **判断**：可选增强 → L6

**`comtypes` / `pyautogui` / `numpy`**

- **出现在**：无
- **清单里有吗**：—
- **判断**：不需要（`kd_open.py:34-37` 明确记录「32 位 runtime 里没有它们」，因此走 ctypes + zlib）

**标准库**

- **出现在**：`ctypes`、`struct`、`zlib`、`subprocess`、`json`、`winreg`
- **清单里有吗**：—
- **判断**：—


**32 位 embeddable 解释器能 import 什么**：只有标准库 + `ctypes`。`kd_open.py:34-37` 与 `bin/kd_uia.py:3-5` 都写明了「bundled 32-bit runtime has no pywinauto, comtypes, Pillow, pywin32 or pyautogui (all checked)」。所以任何要在 py32 里跑的代码只能碰 `ctypes` + 标准库 —— 这也是 `kd_worker` 那种「JSON over pipe」边界存在的根本原因。

## 附录 D · 两张逐点核对表（问题 1 与问题 2 的直接回答）

### D.1 Windows 专有 API —— 逐处判定

**`ctypes.WinDLL('user32'/'kernel32'/'gdi32')`**

- **调用点**：`adapters/kd_open.py:69-74`
- **装载时机**：**import 期**
- **非 Windows 上的实际行为**：`AttributeError`，模块 import 即崩（附录 A-B 实测）
- **判定**：❌ **H2**

**`ctypes.WinDLL(GRDKitDll.dll)`**

- **调用点**：`adapters/kd_native.py:263`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：`AttributeError` 逃过 `except OSError`
- **判定**：❌ **M9**

**`ctypes.WinDLL` + `WINFUNCTYPE`**

- **调用点**：`doctor/kd.py:152` 及 `_bind`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：同上，但 doctor 前置有 `sys.maxsize` 守卫，实际到不了
- **判定**：⚠️ 可接受

**`os.add_dll_directory`**

- **调用点**：`adapters/kd_native.py:258`、`doctor/kd.py:145`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：`except Exception: pass` 静默跳过
- **判定**：✅ 已容错

**`winreg`（`HKCR\kingfile\shell\open\command`）**

- **调用点**：`adapters/kd_native.py:184-186`、`doctor/kd.py:65-68`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：`except Exception: pass` 静默跳过
- **判定**：✅ 已容错

**`win32com.client` / `pythoncom`**

- **调用点**：`adapters/cd_com.py:260-261,469`、`doctor/cd.py:71-72`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：打包成 `E08/import` 结构化失败（附录 A-C 实测）
- **判定**：✅ 范本

**`win32clipboard`**

- **调用点**：`adapters/cd_com.py:595`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：同上，随 pywin32 一起缺
- **判定**：✅

**`win32gui` / `win32process` / `win32con`**

- **调用点**：`ui_capture.py:22-23,75-76,95-96,108-109,121`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：**`_windows()` 与 `capture()` 的 import 在 `try` 外**，抛 `ImportError`
- **判定**：❌ **M8**

**`PIL.ImageGrab`**

- **调用点**：`ui_capture.py:122`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：同样在 `try` 外
- **判定**：❌ **M8**（与 H1 同源）

**`tasklist`**

- **调用点**：`doctor/cd.py:38-41`
- **装载时机**：调用期
- **非 Windows 上的实际行为**：`except Exception: return []`，doctor 继续工作
- **判定**：✅ best-effort

**`taskkill`**

- **调用点**：`test/test_cd_adapter.py:76`、`test/test_cd_cli_mcp.py:64`
- **装载时机**：测试期
- **非 Windows 上的实际行为**：只有 Windows 上跑得通（符合预期）
- **判定**：✅ 可接受

**路径分隔符手写拼接**

- **调用点**：——
- **装载时机**：——
- **非 Windows 上的实际行为**：**一处都没有**：全项目用 `os.path.join`，grep `+ '\\'` 零命中
- **判定**：✅ 无问题


### D.2 硬编码绝对路径 —— 逐条判定

**`adapters/kd_native.py:50`**

- **原文**：`r'D:\tool\KingDraw'`
- **判定**：开发机私有布局，**默认表第一项**
- ❌ **M2**（死路径，且优先于 Program Files）

**`doctor/kd.py:22`**

- **原文**：同上
- **判定**：同一份表的第二份副本
- ❌ **M2**

**`cli.py:178`**

- **原文**：`r'<user-home>\...\Python311\python.exe'`
- **判定**：失败 hint 文本
- ❌ **M1**（只出现在提示里，不影响执行）

**`adapters/kd_open.py:916`**

- **原文**：`r'C:\Python311\python.exe'`、`r'C:\Python312\python.exe'`
- **判定**：探测**兜底**，前面有 `PYTHON64_ENV` → `sys.executable` → `LOCALAPPDATA`
- ✅ 低（L5）

**`adapters/cd_com.py:99-100`**

- **原文**：`r'C:\Windows\Temp'`、`r'C:\Temp'`
- **判定**：ASCII 暂存**兜底**，逐个验证可写/可 ASCII
- ⚠️ 中（M6）

**`cd_com.py:26-28`**

- **原文**：`'%TEMP%\cdprobe\...'`、`'<workdir>\...'`
- **判定**：**注释里的实测记录**，不是可执行代码
- ✅ 无影响（但会让人以为项目依赖这些路径）

**`test/e2e_cd_open.py:2` 等 12 个脚本**

- **原文**：`ROOT = r'<repo>'`
- **判定**：开发脚本硬编码
- ❌ **H3**

**`test/probe_kd_ret.py:13` 等 5 个脚本**

- **原文**：`r'D:\tool\KingDraw\GRDKitDll.dll'`
- **判定**：同上（`probe_kd_open.py:20` 已支持 `KINGDRAW_HOME`）
- ❌ **H3**

**`test/acceptance_m1.py:3`、`test/test_cd_adapter.py:5`、`test/test_cd_cli_mcp.py:5`**

- **原文**：只出现在 **docstring 的用法示例**里，正文用 `__file__` 推导
- **判定**：✅ 建议顺手改文档字符串

**`test/acceptance_m1.py:76`、`test/probe_kd_capture.py:142`**

- **原文**：`tasklist` 参数 / `os.environ.get('TEMP', r'C:\Users\...\Temp')`
- **判定**：环境变量优先，硬编码只是兜底
- ✅ 低

**`scripts/fetch_runtime.py:24-25`**

- **原文**：`URL = 'https://www.python.org/ftp/python/%s/%s'`
- **判定**：只用文件名拼接，**无主机绝对路径**
- ✅ 无问题


### D.3 结论对照（问题 3/4/6 一句话回答）

- **问题 3（位宽）**：判据统一用 `sys.maxsize`，位置见 L2；**可靠**，不需要改判据。`kd_native.py:242-243` 还把 `sys.maxsize` 与 `ctypes.sizeof(c_void_p)*8` 一起写进 detail，诊断质量比多数项目好。
- **问题 4（编码）**：入口全部 `reconfigure(encoding='utf-8')` —— `bin/cli.py:9`、`core/chemdraw_tool/kd_worker.py:109`、`kd_uia.py:145`、`mcp_server.py:462`；跨进程 JSON 走 `encoding='utf-8', errors='replace'`（`mcp_server.py:41-42`、`test/probe_king_worker.py:6`）。**唯一缺口是 M7 那一处 `text=True` 无 encoding**。
- **问题 6（版本敏感）**：ChemDraw 侧有据 —— `cdxml.py:7` 写明 `verified against ChemDraw 26`，`PROGIDS` 给两个 ProgID，`doctor cd` 回报真实 `version` 与 `fullname`；KingDraw 侧**没有**（M3）。类型库 22.0 的事实只存在于 `docs/com_item_document.txt` 与 PROGRESS，代码里没有断言，属于「不假设反而更稳」，不算问题。
