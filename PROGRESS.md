# 进度账本

> 每次推进后追加，不删旧条目。证据只写可复现的命令与数字，失败也照写。

> **现状速查（2026-10-29，随交付滚动更新）**
>
> 这份账本按时间追加，早期条目描述的是各自当时的状态，往后读会和现在打架。要看**现在**能干什么，看这一段：
>
> - **ChemDraw 通道**：画进去、导出图片、按期刊规格出图、读回结构。
> - **KingDraw 通道**：格式转换、算分子式、读 `.king`、把结构送进 App 打开、把 molfile 存成 `.king`（自己写的明文格式，见下方条目）。
> - **跨引擎**：`crosscheck` 拿同一个分子过两个厂商的引擎，用 InChIKey 对账。苯酚 / 阿司匹林 / 咖啡因三引擎结果完全一致。
> - **交付层**：命令行、MCP server（16 个工具）、DSH 插件（15 个工具；**需要你自己接线**，命令在 `dsh-plugin/README.md`）。三个数字是不同集合，不是同一批的两种写法——差异由 `tools/contract_sync.py` 列出。
> - **自检**：`python test/run_all.py` 一条命令跑全部 22 个套件（本机约 212 秒），缺前置的报 SKIP 不报 PASS。
> - **文档数字由机器守**：`tools/preflight.py` 会数套件/工具的真实数量，并与 README、`docs/index.md`、
>   `dsh-plugin/README.md` 和本文件头部写的数字比对，不一致即 FAIL（历史条目不算，它们记的是当时）。
> - **输出形态**：命令行默认可读摘要，机器读加 `--json`（21 条叶子命令全部支持）。
> - **还没做的**：desktop profile 接线（要退出 Electron，会话内做不到）、跨机器验证、KingDraw 的氢数与手性写入。
> - **一处历史记录已失效**：本账本早期条目里 `doctor cd` 曾打印过 `version: ChemDraw Professional 26.1.0.6327`。2026-10-29 在**冷启动**与**attach 到用户实例**两种场景各复测一次，`version` 均为空串（`app.Name` 取不到版本）。以复测为准；老条目保留是因为它记录的是当时的输出。

## 2026-10-29 · M0 完成：两条通道的可行性全部落地

### 宿主机位宽分工（关键约束）

**ChemDraw**

- **宿主**：64 位 Python 3.11.9 + pywin32
- **原因**：COM ProgID `ChemDraw_x64.Application` 是 64 位本地服务器

**KingDraw**

- **宿主**：`runtime/py32/python.exe`（3.11.9 embeddable 32 位）
- **原因**：`GRDKitDll.dll` 是 x86，64 位解释器加载报 `WinError 193`


### ChemDraw 通道 · A 级证据

```
$ python bin/cli.py doctor cd --json
available: true   version: ChemDraw Professional 26.1.0.6327   elapsed_ms: 1038
started_by_us: true   fullname: <ChemDraw 安装目录>\ChemDraw.exe   # 完整值略，见 doctor 输出
```

COM 接口签名已 dump 到 [docs/com_item_document.txt](docs/com_item_document.txt)，要点：

- `Application` 暴露 `Documents / ActiveDocument / ImportDataTypes(45) / ExportDataTypes(54) / Visible / Quit`。
- `Documents` 暴露 `Add() / Item(index) / Count / Close() / Open(Filename, password, Format)`。
- `Document` 有 92 个成员，绘图相关的都在：`MakeAtom() / MakeBond(at1, at2) / MakeArrow() / MakeBracket(type) / MakeCaption() / MakeSpline() / MakeTLCPlate() / MakeTable() / MakeStoichiometryGrid() / Paste() / SaveAs(Filename, Format, resolution, Width, Height)`。
- `IChemDrawDataType` 只有三个属性：`MIME / Extension / Valid` —— 挑导出格式靠 `Extension` 比对。
- `MakeAtom()` 无参数调用后 `Atoms.Count` 从 0 变 1、`MakeBond(at1, at2)` 调用后 `Bonds.Count` 从 0 变 1，**绘图 API 真实可用**。

### KingDraw 通道 · A 级证据

```
$ runtime/py32/python.exe bin/cli.py doctor kd --json
available: true   version: GRDKitDll exports=12/12   elapsed_ms: 71
smilesToMol('c1ccccc1O') -> 497 bytes RDKit molfile
molToSmiles -> 'Oc1ccccc1'   getFormula('CC(=O)Oc1ccccc1C(=O)O') -> 'C9H8O4'
smiles2dTo3d('CCO') -> 684 bytes 3D molfile   supKingToJson(Cyclohexane.king) ->
    2356 bytes JSON
```

12 个导出全部实测通过，且整套调用 71 ms —— 比绕 PowerShell 快两个数量级。DLL 会往 stdout 打调试行（`new rdkit`、`atomkey C_3`），`doctor/kd.py` 里的 `_MuteStdout` 已把它屏蔽掉。

### 已排除的路线

- **OLE 自动化 KingDraw**：`KingDrawXObject` CLSID `{D46EAD57-4162-4C7E-9349-0B2281F7B24A}` 在 HKCR 下没有 `LocalServer32` 也没有 `InprocServer32`，32 位 `New-Object` 只暴露 .NET 基类方法。作废，不留后路。
- **`Documents.Open` 打开 CDXML**：调用不抛异常，但 `Documents.Count` 保持不变，ChemDraw 自己另存的 cdxml 同样打不开。文件格式不是原因，调用方式才是。当前由 dev-cd 继续攻。

### 本机踩到的坑（写进代码前记住）

1. `win32com.client.gencache.EnsureDispatch` 一旦生成类型库缓存，属性名变成**大小写敏感**（`Name` → 报错，`name` → 通过）。生产代码一律用 `win32com.client.dynamic.Dispatch`。
2. Python 打印含中文的 Windows 路径到默认 cp1252 控制台会 `UnicodeEncodeError`。`bin/cli.py` 已在入口把 stdout/stderr 重配为 UTF-8。
3. ChemDraw 启动时若有未勾选的激活提示模态框，COM 创建会失败且错误描述为空。勾掉「以后不再显示」后恢复。

## 2026-10-29 · t1 交付：ChemDraw 插入与导出的通路已定

read-com 把两个未决问题都撞穿了，结论改变实现路线（详细证据见 [docs/upstream-com-notes.md](docs/upstream-com-notes.md)、[docs/cdxml-minimal.md](docs/cdxml-minimal.md)）。

### 插入结构：`Objects.Data` 的 raw property-put

```python
raw = doc.Objects._oleobj_
dispid = raw.GetIDsOfNames(0, 'Data')
raw.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, mime, payload_bytes)
```

- payload 必须 `bytes`。传 `str` 时 pywin32 按 BSTR marshalling，ChemDraw 的 setter 会先窄化到系统 ANSI 代码页（cp1252），`→` 当场变 `?` 且不可逆。
- mime 写错返回 S_OK 但零插入 —— **每次插入后必须断言 `Atoms.Count` 变大**。
- 一次插入产生一个 Group；盐（`[Na+].[OH-]`）会多出外层包装 Group，按包围盒包含关系识别。
- 实测 `chemical/x-daylight-smiles` + `b'c1ccccc1O'`：atoms 0→7、bonds 0→7、groups 0→1。

### 导出：必须带 Format 对象

`doc.SaveAs(path, fmt, resolution, width, height)`，`fmt` 从 `app.ExportDataTypes` 按 `Extension` 挑（本机 54 项：png = 49/50、svg = 47、emf = 43/44）。像素宽 ≈ `W × resolution / 36`，实测 300 dpi / 1200×900 出 10034×7534 PNG。`GetData(mime, dpi)` 的 dpi 参数在本机完全无效（恒 106×76），只能当缩略图。

### `Documents.Open` 静默失败的根因

应用**没有文档窗口**时 Open 什么也不做：不抛错、返回 IChemDrawDocument、`Documents.Count` 不变。先 `Visible = True` + `Documents.Add()` 再 Open 才正常，且 Format 参数非必需。装载自产 CDXML 更该直接走 `Objects.Data('text/xml')`，不必绕文件。

### CDXML 最小体：169 字节

必填只有 `<n>` 的 `id`/`p` 与 `<b>` 的 `id`/`B`/`E`，prolog、DOCTYPE、BoundingBox、Z、AtomID 全可省。**缺 atom id 会静默得到 0 原子**。坐标单位 point、原点左上、y 向下。芳香键只写 `Order="1.5"` 会被静默降级成单键，必须配 `<graphic OvalType="Circle">`，因此生成侧走 Kekulé 或 RDKit→molfile 更稳。

### 对架构的影响

CD 通道不再需要「CDXML 文件 → 打开 → 保存」的绕行：插入用 mime + bytes 直送，导出用 Format 对象，读回用 `GetData`。`cdxml.py` 从主路径降级为「需要精确控制坐标与排版」时的备选。

## 2026-10-29 · t2 交付：KingDraw 通道闭环

`adapters/kd_native.py` 把 12 个导出全部包成 `models.Result`，`test/test_kd_adapter.py` **14 项断言全过**（`runtime/py32/python.exe test/test_kd_adapter.py` → `14 passed, 0 failed`）。

### ABI 是取证出来的，不是猜的

**4**

- **形参**：单个 `char*`
- **函数**：supKingToJson, molToSmiles, smilesToMol, getMolFormula, getFormula, mol2dTo3d, smiles2dTo3d

**8**

- **形参**：两个 `char*` → int
- **函数**：structMatch, substructMatch

**20**

- **形参**：`char*, double, double`
- **函数**：smilesToMolBA（返回 200×200 的 V3000 molblock）

**24**

- **形参**：`char*, double, double, void*`
- **函数**：cleanUp, kingCleanUp


三处只在实测中才暴露的真相：

1. `supKingToJson` 与 `kingCleanUp` 在 PE 导出表里**只有** stdcall 装饰名 `_supKingToJson@4` / `_kingCleanUp@24`，绑定器必须先试原名再试装饰名。
2. `cleanUp` / `kingCleanUp` 的第 4 个槽是**指针不是 int**：传 0 会在厂商代码里 access violation，必须给可写 buffer。
3. `getMolFormula` 吃 molblock、`getFormula` 吃 SMILES；`mol2dTo3d` 吃 molblock、`smiles2dTo3d` 吃 SMILES —— 名字对称但入参不同。

### 顺带修掉的架构问题

`doctor/kd.py` 原本自己维护一份函数签名，与适配器各说各话。现在 doctor 通过 `kd_native.BINDINGS` 复用同一张 ABI 表，单一真相源。改完立刻暴露了一个真实缺陷：绑定失败被 `except Exception: pass` 静默吞掉，doctor 会报告 `exports=0/12` 而 DLL 完好。现在失败原因写进 `details.bind_errors`，不再静默。

### 仍未定论（照实记）

`kingCleanUp` 期望的输入形态没定：`.king` 原始字节与 V2000 molblock 都返回 `success:true` 但 `nodes` 为空。读 `.king` 的已验证路径是 `supKingToJson`，这条留着。

## 2026-10-29 · 进程边界与 MCP 层落地

### 一个必须先解决的矛盾

ChemDraw 的 COM 服务器是 64 位，KingDraw 的 DLL 是 32 位，**同一个解释器不可能同时干两件事**。硬解只有一条路：主进程跑 64 位，KingDraw 的每次调用转交给 32 位子进程。

```
64 位主进程（MCP / CLI）  --JSON over pipe-->  runtime/py32/python.exe bin/kd_worker.py
      |                                                   |
      +---- pywin32 --> ChemDraw COM                      +---- ctypes --> GRDKitDll.dll
```

`bin/kd_worker.py` 是入口（embeddable 解释器不把当前目录放进 `sys.path`，所以不能用 `-m`，必须由启动器显式插入 `core/`）；`core/chemdraw_tool/kd_worker.py` 是协议端，一次一个请求、一个请求一个新进程，避免厂商 DLL 的状态跨调用泄漏。

这么做还有额外好处：DLL 崩了只崩子进程，主进程照常返回结构化 Failure。

### CLI：KingDraw 子命令

```bash
runtime/py32/python.exe bin/cli.py kd formula \
    --smiles 'CC(=O)Oc1ccccc1C(=O)O'   # -> C9H8O4, 26 ms
runtime/py32/python.exe bin/cli.py kd mol     --smiles c1ccccc1O --out phenol.mol
runtime/py32/python.exe bin/cli.py kd king    D:/tool/KingDraw/Cyclohexane.king
```

64 位解释器跑这些命令不会崩，会得到 `E04` 加一句「改用 runtime/py32/python.exe」。

### MCP server：7 个工具

`core/chemdraw_tool/mcp_server.py` 实现了 stdio JSON-RPC 2.0（`initialize` / `tools/list` / `tools/call` / `ping`），不依赖任何 MCP SDK。工具：`chem_identity`、`kingdraw_smiles_to_mol`、`kingdraw_mol_to_smiles`、`kingdraw_formula`、`kingdraw_read_king`、`kingdraw_match`、`kingdraw_to3d`。

实测（喂三条消息进 stdin）：`tools/list` 正常返回全部 schema；`kingdraw_formula` 返回 `C9H8O4`、`isError:false`、26 ms；`kingdraw_match('c1ccccc1O','Oc1ccccc1')` → `true`。

### `.king` 读出来是结构化对象了

`supKingToJson` 返回的是「JSON 里套 JSON」，直接透传会逼每个调用方二次解析。worker 里做了一次解包，现在 `data.nodes[0]` 就是 `{'index':1, 'type':'C', 'hCount':2, 'point':{'x':0.78,'y':0.0,'z':0.0}, ...}`，6 个碳的环己烷一目了然。

## 2026-10-29 · t6 交付：期刊 artwork 规范，以及它揭穿的三件事

read-com 把 ACS / RSC / Wiley / Elsevier 的 author guidelines 逐条抓了下来（每条带原文片段、URL、抓取日期，见 [docs/journal-artwork.md](docs/journal-artwork.md)）。硬性数值：

| 期刊 | 线稿 | 灰度 | 彩图 | 单栏宽 | 最大深度 | 字号下限 |
|---|---|---|---|---|---|---|
| ACS (JACS) | 1200 dpi | 600 | 300 | ≤240 pt (3.33 in) | 660 pt (9.167 in) | 4.5 pt |
| RSC | 600 | 600 | 600 | 未取得（站点 403） | — | — |
| Wiley | 600 | 300 | 300 | 80 mm | 180 mm | — |
| Elsevier | 1000 | 500 | 300 | 90 mm | 190 mm | 6 pt |

### 三条改变 M2 设计的实测结论

1. **本机 `ExportDataTypes` 的 54 项里没有 PDF**。想要矢量交付，只剩 EPS 和 SVG 两条路。
2. **`SaveAs` 出来的 PNG，dpi 元数据恒为 144**，与传入的 `resolution` 无关（6 个样本一致），且色彩模式是 RGBA。出版社读的是 dpi 标签而不是像素数，所以这张图直接投出去会被退。
3. **`W` 与 `resolution` 只放大像素，不会改变物理尺寸**。10034 px 在 300 dpi 下就是 849 mm 宽——比双栏宽 3 倍。必须**先定目标像素、再反解 Width**，顺序反过来一定出错。

### 因此新增 `artwork.py`

```python
artwork.export_args(4000, 1200)
# -> {'width': 120.0, 'resolution': 1200}   ACS 单栏 1200 dpi
artwork.export_args(3543, 1000)
# -> {'width': 127.55, 'resolution': 1000}  Elsevier 90 mm
artwork.check(png, journal='acs', min_dpi=1200)
artwork.normalize(png, tif, dpi=1200, max_width_mm=85)
```

实测一轮：一张 4000×3000 的 RGBA / 144 dpi PNG，`check` 报出 3 条硬问题（dpi 低于 1200、RGBA、格式不是 tif/eps）；`normalize` 之后变成 4000×3000 的 RGB、1200 dpi、84.7 mm（1.56 MB TIFF），复查 `ok: true`。

### 未证实项（照实记）

RSC 栏宽与字号、ACS 的格式清单、Elsevier 高度上限、Wiley 字号与线宽、144 dpi 是否随版本变化、无 PDF 时的替代交付路径 —— 这些都标了「未证实」写进文档，没有含糊过去。

## 2026-10-29 · t3 交付：ChemDraw 通道打通，并推翻了我自己写错的公式

`adapters/cd_com.py` + `test/test_cd_adapter.py` **16 项断言全过**（`16 passed, 0 failed`）。阿司匹林实测：写入 13 atoms / 13 bonds，读回 SMILES 精确一致；导出 PNG 15729 字节 550×458；`export_figure` 出 2352×1954 RGB @1200 dpi、物理 50 mm，`artwork.check` 的 issues 为空。

### 五条插入路线，全部实测

**smiles（默认）**

- **调用**：`Objects.Data('chemical/x-daylight-smiles')`
- **结果**：13/13，芳香性保留

**molblock**

- **调用**：`Objects.Data('chemical/x-mdl-molfile')`
- **结果**：13/13

**cdxml**

- **调用**：`Objects.Data('text/xml')`
- **结果**：13/13（必须 B/E + Order + Kekulé）

**paste**

- **调用**：剪贴板 CF_TEXT + `doc.Paste()`
- **结果**：13/13，但会覆盖用户剪贴板

**objects**

- **调用**：`MakeAtom` / `MakeBond` + 坐标回赋值
- **结果**：13/13，但**隐式氢不落库**，读回分子式不对 → 不作默认

**open**

- **调用**：`Documents.Open(path)`
- **结果**：失败，已作为可诊断 Failure 暴露


### 三个新的静默失败（都写进了代码注释与测试）

1. **`SaveAs` 对非 ASCII 路径是空操作**：不抛异常、不产生文件。本项目自己的中文路径就中招。`export()` 改为先写 ASCII 临时目录再拷贝；本卷 8.3 短名被禁用，`GetShortPathName` 原样返回，所以那个退路也不存在。
2. **`Document.Close(saveChanges, Filename)` 是空操作**：返回后 `Documents.Count` 不变、原子还在。只有 `Application.Quit()` 真能销毁文档，因此只 Quit 自己起的实例，attach 到用户的实例一律不动。
3. **`Graphics.Item(1).Delete()` 无效**：同文档连画三次，Graphics 计数 1→2→3 删不掉，残留把出图 ink 从 550×458 撑到 2373×3090。所以每次绘图强制新建文档。

### 我的 `artwork.export_args` 是错的，已改

我按 read-com 的反推写了一版「给定像素反解 Width」，方向反了。实测：同一个 66.2 pt 宽的分子，`Width` 传 78.2 / 234.7 / 309，导出的图**都是 550 px 宽**——`Width` 与 `Height` 只加画布空白，图形按 `resolution/36` 像素每 point 的自然尺寸绘制，不会变。按 Width 反解只会把纸撑大，分子一点没变大。

正确方向是 `resolution = 目标像素 × 36 / content_width_pt`。已替换为 `artwork.resolution_for(4000, 66.2) == 2175`，并加了 `canvas_pt()` 与 `MAX_EXPORT_PX = (2637, 2191)`。

### 出图有硬上限

这台机器的 ChemDraw 不管 dpi 传 1500 还是 2183，导出都是 2637×2191 px。所以「1200 dpi 下 85 mm 宽（4016 px）」单次 SaveAs 达不到，`export_figure` 撞到上限会 warning 并按实际尺寸返回，不假装成功。

### `cdxml.py` 的 bug：我自己写的，已修

```diff
- <b id="14" B="1" p0="1" p1="2"/>          <!-- 键级塞 B、原子引用塞 p0/p1 -->
+ <b id="14" B="1" E="2" Order="1"/>        <!-- B/E 是原子 id，Order 才是键级 -->
```

CDXML 的键命名与其它化学工具全都不一样：`B`/`E` 装两个原子的 id，`Order` 装键级。写成直觉的 `B=键级` + `p0/p1=原子`，ChemDraw 会**静默插入 0 个原子**——这正是我最早那份 CDXML 打不开的原因。另外芳香键必须先 Kekulé 化，只写 `Order="1.5"` 会被静默降级成单键。两处都已修。

## 2026-10-29 · t4 交付：M1 双通道验收 5/5

`test/acceptance_m1.py` 一条命令跑完五项，退出码 0；记录在 [docs/acceptance-m1.md](docs/acceptance-m1.md)。

### 分子身份三处一致（这是整个架构的握手键）

| 分子 | ChemDraw | KingDraw | rdkit |
|---|---|---|---|
| 苯酚 | ISWSIDIOOBJBQZ-UHFFFAOYSA-N | 同 | 同 |
| 阿司匹林 | BSYNRYMUTXBXSQ-UHFFFAOYSA-N | 同 | 同 |
| 咖啡因 | RYYVLZVUVIJVGH-UHFFFAOYSA-N | 同 | 同 |

**一个必须记住的细节**：ChemDraw 读回的 SMILES 字面量会被重排（阿司匹林读回来是 `CC(Oc1c(C(O)=O)cccc1)=O`），但 InChIKey 不变。所以跨通道比对身份**只能用 InChIKey，不能用字符串相等**——如果哪天有人写了个 `if smiles_a == smiles_b` 的断言，它会在正确的实现上失败。

### 其余四项

2. KingDraw：SMILES → V3000 molblock → SMILES，三个分子 rdkit canonical 严格相等；`getFormula` 与 `getMolFormula` 算出 C6H6O / C9H8O4 / C8H10N4O2，与 rdkit 一致。
3. ChemDraw：苯酚 7/7、阿司匹林 13/13、咖啡因 14/15 原子/键；PNG 8339 / 15729 / 18320 字节。
4. 非法 SMILES：两通道都返回 E06 结构化 Failure，无未捕获异常。补强探针还发现一种更阴的情况——**空 SMILES 能过 rdkit 但插 0 个原子**，ChemDraw 自身报 `accepted the call but inserted no atoms`，这类「引擎接受了但什么都没做」必须显式检查。
5. 进程卫生：baseline 无 ChemDraw → 自起实例（`attached=false`）→ 关闭后 `Quit` → 约 1 s 后消失，`tasklist` 干净。

### 本轮没覆盖的（照实记）

第 5 项只验了干净场景（运行前无 ChemDraw），attach 到用户已有实例后的残留未实测；本轮未重跑 t3 的五条插入路线；`.king` 读取与 `kingCleanUp` 未纳入。

## 2026-10-29 · t7/t8 交付 + DSH 插件落地

### 两条通道现在在 CLI 与 MCP 上完全对称

```
CLI   chemdraw-tool cd draw|export|figure|read|capabilities|doctor
      chemdraw-tool kd mol|smiles|formula|king|match|to3d|layout|open
MCP   chemdraw_draw|export|figure|read|capabilities  (5)
      kingdraw_smiles_to_mol|mol_to_smiles|formula|read_king|match|to3d  (6)
      chem_identity  (+ 本轮补的 ok 字段)
```

`test/test_cd_cli_mcp.py` **11/11 通过**。stdio 纯净靠 `_StdoutGuard`：`tools/call` 执行期间把 fd 1 指向 devnull 并把 `sys.stdout` 换成 sink，响应在恢复之后才写——实测连续 7 条消息 7 行合法 JSON，零污染。

### KingDraw 的「文档真的打开了」改用无障碍树取证

像素这条路走不通，而且不是位宽问题：64 位进程里 `PrintWindow(flag=0)` 只画出标题栏、客户区全黑（363 色，白色占 0.19%），`PrintWindow(flag=2 / PW_RENDERFULLCONTENT)` 反而 94% 全白。KingDraw 用 WPF/D3D 渲染，内容在 GPU 表面，不落到 GDI 能读的地方。

UIAutomation 可以，而且证据更强：`pywinauto(backend='uia').connect(process=pid)` 之后遍历 descendants 拿到 `TabItem KingDraw.WpfForm.KDLayoutDocument` 与 `Text aspirin_kd.mol`——文件名是精确字符串，比「截图像样」可靠得多。`test/test_kd_open.py` 现在 **9 passed / 0 failed**，像素只作辅助证据，文件名带 `_chrome_only`。

UIA 只在 64 位 Python 里有（pywinauto 装不进去 embeddable），所以 32 位 worker 通过桥接调用，往返 1.06–1.36 s。

### DSH 插件

`dsh-plugin/` 是插件的**源代码**，留在仓库里跟着 clone 走，安装时 DSH 用 `link:` 指过来而不复制。10 个工具，`lib/` 三个文件：`config.js`（找 checkout 与解释器）、`bridge.js`（spawn CLI 并解析 Result）、`index.js`（注册工具）。

设计上刻意分成十个工具而不是一个「智能绘图」：只装了 KingDraw 的人不该因为 ChemDraw 报错就看到失败，反过来也一样；分开之后每条失败信息能直接说「这个通道缺什么」。插件里没有一行化学逻辑——改 Python 侧不需要重装插件。

验证到哪一步（如实）：

- 已验：`dsh plugin --profile _probe add "link:..."` 装上（rc=0）；`--dump-config-schema` **rc=0、stderr 0 行**、schema 里出现 `dsh-chem-draw-tool` 的 id 与 name，无 `ERR_MODULE`/`Cannot find`。
- 未验：`apply()` 里 `ctx.tools.register` 的真实执行（schema 只证明模块能被 import）；10 个工具的端到端调用；desktop profile 的接线——**需要完全退出 Electron，会话内做不到**，留给用户执行。

按 `~/.dsh/AGENTS.md` 走完了：取锁 → 建临时 `_probe` profile → 验证 → 删 profile → `unlock` → `clean`（`ok:true, leftovers:[]`，research 只剩 `LOG.md` 与 `dsh-guard.mjs`）。本轮对 `.dsh` 的净改动为 0 字节。

### 顺带修掉的一个真 bug

MCP 的 `chem_identity` 一直返回 `isError: true`，因为 `identity.identify()` 的返回体里没有 `ok` 字段，而 `handle()` 用 `payload.get('ok')` 判定。补上之后又发现第二个问题：rdkit 解析失败会把 `SMILES Parse Error` 打到 stderr，现在 `RDLogger.DisableLog('rdApp.*')` 关掉，实测 stderr **0 字节**。


## t11：新手文档被按原样实跑了一遍

QA 照 `docs/quickstart.md` 一步不差地跑下来，产出 `docs/quickstart-verified.md`。命令层面**全部通过**（pip、fetch_runtime、两条 doctor、identity、kd formula、两个自检 14/14 与 16/16、help），还另建了一个只装 `requirements.txt` 的干净 venv 复核依赖完整性——`cd draw/export/figure/read/capabilities` 在那个 venv 下全部 rc=0，说明依赖清单没有漏 import。

但「命令能跑」和「文档说得对」是两件事。它抓出五个字段级错误，全在「看到什么算成功」那一节：

| 文档写的 | 实测 |
|---|---|
| `channel: "cd"` / `"kd"` | `chemdraw` / `kingdraw` |
| `version` 以 ChemDraw 开头 | 恒为空串（`app.Name` 取不到版本） |
| `home` 指向 exe | 恒为空串，真实路径在 `details.fullname` |
| `exports_found: 12` | 是**名字数组**，数字在 `exports_expected` |
| `exports_found == exports_expected` | 永远为假——拿数组跟整数比 |

最后一条最阴：按文档的判定式，KingDraw 通道明明 12/12 正常也会被判成失败。新手遇到这种「明明装了却报错」的局面，多半会去重装软件。

还有一条不是字段错而是流程错：步骤 1 写的是 `git clone <仓库地址>`，而 `<仓库地址>` 是占位符、这个目录当时也还不是 git 仓库——照抄第一步就失败。已改成「代码已在硬盘上就 `cd` 进去」，并给了判断站对位置的依据。

### 顺带修掉一个会让用户丢工作的 bug

`doctor/cd.py::_running_pids()` **恒返回空列表**。它解析 `tasklist` 的 CSV 时只 `strip("'")` 去掉单引号，而 tasklist 用的是双引号——于是每行的镜像名带着前导 `"`，`startswith('chemdraw')` 永远不成立。实测机器上明明有 `ChemDraw.exe` PID 980，函数返回 `[]`。

这个空列表流进 `started_by_us = (not attached) and len(pids_before) == 0`，意味着：**用户自己开着 ChemDraw 在画图，doctor 会认为「没有实例在跑」，于是把用户的实例 Quit 掉**。未保存的文档就没了。

修法分两层：
1. 改用 `csv.reader` 解析（顺带解决内存列 `204,124 K` 的千位逗号把行拆错的问题）；
2. 读不到进程列表时返回 `None` 而不是 `[]`——**「不知道」不能等于「没有」**。判定改成 `pids_before == []`，只有确定为空才允许 Quit。

验证：真实 tasklist 行 `"python.exe","37640","Console","4","204,124 K"` 经 csv 解析得到 `['python.exe','37640',...]`；`doctor cd` 端到端 rc=0、stderr 0 字节、`started_by_us: true`、退出后无 ChemDraw 残留。

另一条 `--keep-open` 实测无效，查下来不是 bug 而是 `LocalServer32` 的固有行为：COM 引用一释放进程就自己退出。已写进「已知限制」，没有假装修好。

### Pillow 那条也一并落地

`requirements.txt` / `pyproject.toml` 补上 `pillow>=9.0`，并把 quickstart 里「只有两项」改成「只有三项」——包括它缺失时会把「少了库」伪装成「图片无法读取」这一点。


## t12：KingDraw 现在能「存」，但不是靠它自己的另存为

这一条的结论和预期相反，值得记下来。

**A 路（用 UIA 驱动菜单另存为）跑通了，但产品不产出 `.king`。** 全程 UIA、零坐标点击：`菜单(M)` → `文件(F)` → `另存为(A)` → 浏览 → 原生对话框（文件名 `auto_id=1001`，保存 `auto_id=1`）→ 落盘。输入 `xxx.king`，落盘文件叫 `xxx.king.kdx`。因为 KingDraw 26 的保存类型下拉里**只有 `KDX 文件(*.kdx)`**，注释还写着「KDX 为新版的拓展的 King 文件，能够完全覆盖 King 格式」。而 `.kdx` 是 ZIP（头 `PK\x03\x04`，里面有 `docProp`、`media/p_jpg.jpg`），`supKingToJson` 读它返回 `success/code 100` 但 `nodes=[]`；同一个调用喂真的 `.king` 给 6 节点 6 键。

导出图片也堵着：`导出(E)` 直接弹「请登录后使用导出图片功能」。

**所以 B 路：自己写 `.king`。** 它是纯文本，格式已逆推出来：

```
Begin Header / KingDraw V2.2 / 20180420
Device / SysConfig
Begin Ctab
  Atom 行: <i> <elem> <x> <y> #ff000000
  Bond 行: <i> <order> <a1> <a2> 0 #ff000000
END
```

三重验证（缺一不可）：写出来 → 厂商自己的 `supKingToJson` 读回 → `kd_open` 送进 App 看 UIA 里有没有对应文档页。往返结果：苯环 6/6、苯酚 7/7、阿司匹林 13/13、乙醇 3/3，键数与元素序列全部相等；`kd_open` 打开自己写的 `.king` 后，UIA 树里 `Text = 'kd_save_phenol.king'`。

**限制照实写**：写出的 `.king` 含 2D 坐标、元素、键级；**HCount 未计算、手性与芳香标记不写入**。拓扑和元素可验，氢数和立体化学目前不保证。

顺手把 t10 点出的 `kd_open` 模块级 `ctypes.WinDLL` 修了：`_bind_windows_apis` 懒绑定 + `_LazyDll` 代理，`WINFUNCTYPE` 与 `Process32First/Next` 的 `argtypes` 一起挪进去。模拟非 Windows 后 import 不再崩，`close_app`/`uia_documents` 返回 `E08`、`list_pids` 返回 `[]`；真实 Windows 路径与 t5 套件（9 passed）回归正常。

## t14：文档巡检，以及一个字段的定案

read-com 把十来份文档对着代码核了一遍。**链接层和命令层是干净的**：34 条相对链接 0 断链，48 处文档里的命令逐条对照 13 个 `--help` 全部命中，没有不存在的子命令，也没有拼错的选项。坏的全在事实层。

三条 P0 里最要紧的是「同一字段两个相反的实测记录」：`quickstart.md` 写 `version` 恒为空串，而本账本早期条目记的是 `ChemDraw Professional 26.1.0.6327`。不实跑无法裁决，于是跑了：冷启动（`started_by_us: true`）与 attach 用户实例（`attached: true`、`documents_open: 1`）两种场景，**`version` 都是空串**。定案为「恒为空串」，历史条目按约定保留并加注。

另外两条 P0：`dsh-plugin/README.md` 的工具表漏了新加的 `chem_crosscheck`（那张表就是用户的调用清单）；`docs/index.md` 自称「新增文档必须登记，否则等于没交付」，却漏登了两份刚产出的文档。都已补。

P1 的 13 条是过期数字与状态，其中两处最误导：`README.md` 首屏还写着「当前可用的只有一条命令（doctor）」（写于 M0），`PROGRESS.md` 里「MCP 层与 DSH 插件层尚未开始」与同一个文件后面的交付记录自相矛盾。首屏已改成 M1/M2 的现状；账本顶部加了「现状速查」，历史条目不删——那份文件的价值就在于记录当时发生了什么。
## 2026-10-29 · 首次提交：92 个文件，四个套件全绿

仓库此前**不是 git 仓库**——`git rev-parse` 报 `fatal: not a git repository`。推 GitHub 之前先把它变成一个能直接 push 的仓库。

提交前清掉的东西：

- `_probe32.ps1`、`_kdcom.ps1`、`_probe_rdcdxml.py`：开发期临时探针，散在仓库根。
- `runtime/test_py32.py`：探针，而且里面写死了 `D:\tool\KingDraw`。
- `.gitignore` 里 `runtime/py32/` + `runtime/*.zip` 改成整个 `runtime/`——那个目录是生成物（`scripts/fetch_runtime.py` 会重建），只 ignore 子目录会漏掉别的东西。

结果：**92 个文件、556 KB**（不含 `.git`）。`runtime/`、`test/out/`、`.agent-teams/`、`__pycache__` 都不进仓库。

```
45b296e 两条通道各自跑通，并且能互相验证
```

### 交付前的验收（一条命令跑完四套）

| 套件 | 解释器 | 结果 |
|---|---|---|
| `test_kd_adapter.py` | py32 | **14 passed / 0 failed** |
| `test_kd_save.py` | py32 | **6 passed / 1 skipped / 0 failed**（5.0s） |
| `test_crosscheck.py` | py64 | **11 tests OK**（5.9s） |
| `test_cd_adapter.py` | py64 | **17 passed / 0 failed** |

合计 48 项通过、0 失败、1 跳过。跑完 `tasklist` 里 ChemDraw 与 KingDraw 进程均为 0。

**那 1 个 skip 是什么，说清楚**：`test_the_vendor_app_only_saves_kdx` —— 验证「KingDraw 的另存为只能产出 `.kdx`、且 `.kdx` 读回 `nodes=[]`」的那条。它要走 UIA 点开菜单再弹原生保存对话框，**需要人盯着**，所以默认跳过而不是伪造通过。结论本身已由 t12 的人工实测记录，这条测试只是想把那个实测变成可复跑的，目前没做到。

### 这一版离「能交出去」还差什么

1. **push 到远端**：需要仓库地址（现在只是本地仓库，没有 remote）。
2. **DSH 插件的 desktop 接线**：`dsh plugin --profile desktop add "link:<路径>\dsh-plugin"`，必须先退出 Electron，由用户执行。
3. **跨机器验证**：只在这台机器上跑过，可移植性审查（`docs/portability-report.md`）列出了别人可能撞上的点，但没有第二台机器复现。

## 2026-10-29 · 补齐「示例」「安装脚本」「改」三样

目标里写的是「画/读/改/排/查/出六类动作」加「README、LICENSE、示例、测试、安装脚本」。前四样早就有，后三样这一轮补上。

### 「改」：`cd modify`，改已经打开的页面

之前所有 ChemDraw 动作都走 `draw_smiles()`，而它**每次都新建文档**——这是对的（旧内容删不干净：实测 `Graphics.Item(1).Delete()` 无效，残留图形把导出画面从 550×458 撑到 2373×3090），但它答不了「用户正开着结构，让 agent 改一下」。

新增 `ChemDrawChannel.modify(replace=, clear=, delete_atom=, delete_object=)`，在**当前**文档上原地编辑。实测（单进程内连续操作）：

| 步骤 | 结果 |
|---|---|
| `draw_smiles('c1ccccc1O')` | 7 个原子 |
| `read_current('smiles')` | `Oc1ccccc1` |
| `modify(delete_atom=7)` | `['deleted atom 7']`，6 原子 / 5 键 |
| `read_current('smiles')` | `Occccc` |
| `modify(replace='CC(=O)O')` | `['cleared the page', 'inserted the replacement']`，4 原子 / 3 键 |
| `read_current('smiles')` | `CC(O)=O` |

CLI 是 `cd modify --replace/--clear/--delete-atom/--delete-object [--out]`，MCP 是 `chemdraw_modify`，插件也是同名工具。

两个实测坑写进了方法注释：删原子会连键一起删；清空必须同时排空 `Graphics/Pictures/Captions/...` 这些对象集合，否则残留图形照样印进导出图。

### 示例：`examples/`

三个脚本，按「需要装什么」递进，都实测能跑：

- `batch_identity.py`（只要 rdkit）→ 已跑：苯酚 `ISWSIDIOOBJBQZ-UHFFFAOYSA-N`、阿司匹林 `BSYNRYMUTXBXSQ-UHFFFAOYSA-N`、咖啡因 `RYYVLZVUVIJVGH-UHFFFAOYSA-N`
- `draw_figure.py`（加 ChemDraw）→ 画一个分子 + 出 ACS 单栏图
- `crosscheck_batch.py`（加 32 位运行时）→ 三引擎对账

### 安装脚本：`install.ps1`

一条命令：找解释器（并检查是不是 64 位）→ `pip install -r requirements.txt` → `fetch_runtime.py` → 两条通道各体检一次 → 汇总表。

设计上**每步失败都不中断**，因为真实情况常常是「ChemDraw 能用、KingDraw 缺运行时」，半好状态下更该看到全貌。实测 `install.ps1 -SkipRuntime`：rc=0，五项全 ok（py 3.11.9 64 位、依赖、runtime 跳过、chemdraw available、kingdraw available）。

顺带修了中文乱码：`[Console]::OutputEncoding = UTF8`，否则在多数 Windows 终端里输出全是 `????`，失败的那一步根本没法读。

### 验收剧本跑到哪了

**ChemDraw 出图 —— 通过。** `cd figure --width-mm 85 --dpi 1200` 得到：

```
1922 x 1302 px, RGB, dpi 1200, 60 种颜色, 墨迹覆盖 8.37%, 62931 字节
```

**分子身份 —— 通过。** 苯酚 / 阿司匹林 / 咖啡因各跑一次 `crosscheck`，rdkit、KingDraw、ChemDraw 三个引擎的 InChIKey 全部一致，`agree=True`。

**KingDraw 出图 —— 进行中。** 它被产品堵着（导出图片要登录，WPF 画布截不到），正在试的路子是从 `.kdx` 容器里取出 KingDraw 自己渲染的预览 JPG。结果未出，不预设通过。

一个必须记录的诚实细节：这次 `cd figure` 带了两条 warning，其中一条是**这台机器的 ChemDraw 导出上限约 1922 px**，所以 1200 dpi 下实际只有 40.7 mm 宽，而不是要求的 85 mm。撞上限时按实际尺寸返回并告警，不假装成功——这正是当初把「假成功」改成硬失败的意义。

## 2026-10-29 · KingDraw 也能出图了（预览级），验收剧本四条全过

`kd export` 打通。之前判断「KingDraw 出不了图」是对的——导出图片要登录，WPF/D3D 画布截不到——但漏了一条侧门：**`.kdx` 是 ZIP，里面带着 KingDraw 自己渲染的预览 JPG**。

实测 `.kdx` 里有三张图（同一个分子）：

| 成员 | 尺寸 | 颜色数 | 判断 |
|---|---|---|---|
| `media/p_jpg.jpg` | 108×120 | **348** | 真渲染，苯环和 OH 都在 |
| `media/p_png.png` | 108×120 | 10 | 退化占位 |
| `media/p_thumbnail.png` | 300×300 | 11 | 像素最大，但就是个黑块 |

这里我给的指令是错的：我说「取最大那张」，按面积会挑到那张 300×300 的黑块。实现改成了**色彩丰富度优先、面积其次**，并把这条偏离写进代码注释和 warnings。预览随分子变大：苯酚 108×120、阿司匹林 147×141、胆固醇 270×233。

### 验收剧本：四条全过

| 要求 | 结果 |
|---|---|
| ChemDraw 产出一张图 | 1922×1302 px、RGB、dpi 1200、60 色、墨迹 8.37%、62931 字节 |
| KingDraw 产出一张图 | 300×333 px、2266 色、26633 字节（源 108×120，×2.78 插值放大） |
| 分子身份一致 | 苯酚 / 阿司匹林 / 咖啡因 × rdkit / KingDraw / ChemDraw，InChIKey 全部一致 |
| 无残留进程 | ChemDraw 0、KingDraw 0 |

### 预览级怎么讲清楚

KingDraw 这张是**预览级**：源图只有 108×120，放大是插值不是重渲染，分辨率由 KingDraw 定、改不了。所以 `Result` 里 `degraded=True`，`warnings[0]` 直接写「not publication artwork — use the ChemDraw channel (`cd figure`)」，`data` 同时给 `source_size` 与输出尺寸。拿去投 ACS 会被退，这一点必须在工具返回值里就拦住，而不是等用户被拒稿。

### t15 顺手修的三个真坑

1. **桥接可能无限递归**：机器上同时有 Python313/311，只有 311 装了 `pywinauto`+`Pillow`；原逻辑按目录名取了 313，313 又走桥接 → 互相等，表现为「挂 120 秒」。现在真去问解释器 `import pywinauto, PIL`，并给 helper 打环境变量防重入。
2. **管道死锁**：KingDraw 是 helper 的孙进程，会继承 stdio，`capture_output=True` 时管道 EOF 永不到。改成 stdout 指向真实文件句柄。
3. **helper 干完不退出**：UIA/comtypes 收尾吊住解释器（结果已写、App 已关，30 秒后进程还活着）。改成写完文件 `os._exit()`，父进程轮询结果文件。

这三个都不是「功能没做对」，而是「做好了但会挂住」——最容易被误当成「软件慢」而放过。

## 2026-10-29 · 最终验收：五个套件 52 项通过，两张图各自成立

```
kd_adapter   14 passed, 0 failed                  (py32, 纯 DLL)
kd_save       6 passed, 1 skipped, 0 failed       (py32, 4.8s)
kd_export     4 passed, 0 failed                  (py64, 32.4s)
crosscheck   11 tests, OK                         (py64, 5.9s)
cd_adapter   17 passed, 0 failed                  (py64)
----------------------------------------------------------
52 passed, 1 skipped, 0 failed
```

```
phenol_chemdraw.png   1922x1302  RGB      62931 B      60 colours   dpi 1200
phenol_kingdraw.png    300x333   RGB      26633 B    2266 colours   源 108x120 插值
```

跑完 `tasklist` 里 ChemDraw 与 KingDraw 进程均为 0。

那个 skip 仍然是 `test_the_vendor_app_only_saves_kdx`——它要人盯着原生保存对话框，所以默认跳过。结论本身已由 t12 的人工实测记录，只是没变成可复跑的测试。

### 六类动作的落点

| 动作 | ChemDraw | KingDraw |
|---|---|---|
| 画 | `cd draw` | `kd mol`（SMILES→molfile）+ `kd open` |
| 读 | `cd read` | `kd smiles` / `kd king` |
| 改 | `cd modify`（替换/清空/删原子/删图形） | `kd save`（重建） |
| 排 | `cd figure` 的版面换算 | `kd layout`（W×H 盒内重排） |
| 查 | `crosscheck` / `cd capabilities` | `identity` / `kd match` / `doctor` |
| 出 | `cd export` / `cd figure` | `kd export`（预览级） |

### 目标达成情况

- 三层交付：命令行（5 组子命令）、MCP server（14 个工具）、DSH 插件（14 个工具）——**对称且可分别使用**。
- 两条独立通道，位宽分工清楚：ChemDraw 走 64 位 COM，KingDraw 走 32 位原生 DLL，中间 JSON over pipe。
- 完整仓库：README / LICENSE / 示例（3 个可运行脚本）/ 测试（5 个套件）/ 安装脚本（`install.ps1`）。
- 验收剧本：两条通道各产出一张图，三个引擎的 InChIKey 一致。

**仍未做的，照实记**：desktop profile 的插件接线（要退出 Electron，会话内做不到）、跨机器验证（只有这一台）。这两条不在本轮验收范围，但它们是「别人能不能用」的分界线，不能含糊。

## 2026-10-29 · 插件层从「能加载」到「能调用」

之前对插件的验证只到「DSH 能把它当 bundle 加载、模块能 import」——我明确写过这一层的界线：**装得上不等于调得通**。这一轮把它补上。

做法：给 `@deepseek-ai/dsh-tools` 放一个本地 stub（只导出恒等 `defineTool`），然后直接 import `dsh-plugin/lib/index.js`，用一个假的 `ctx.tools.register` 收集注册结果，再**真调** CLI。

```
node test/test_plugin_tools.mjs
```

检查项（60 条全部通过）：

- 14 个工具全部注册，无重名；每个都有 description / parameters / execute / output.renderer
- 通道分布对得上：`chemdraw_*` 5 个、`kingdraw_*` 6 个、共享的 `chem_*` 3 个
- **真实往返**：`chem_identity('c1ccccc1O')` → `ISWSIDIOOBJBQZ-UHFFFAOYSA-N`、`C6H6O`
- **失败路径**：非法 SMILES 不抛异常，返回 `ok=false` 且带错误码

最后一条第一次是**红的**，由此揪出一个真问题。

### identity 的错误原本没有 code

十三个工具的失败都长这样：`{'ok': false, 'failure': {'code': 'E06', 'message': ..., 'hint': ...}}`。只有 `identity` 是扁平的：`{'ok': false, 'note': 'rdkit could not parse this SMILES'}`——**没有 code，没有 hint**。

对 agent 来说这是关键差别：`ok=false + code=E08` 意味着「去装 rdkit」，`code=E06` 意味着「换个 SMILES 再试」。只有一句 `note`，两者分不出来，只能原样转述给用户。

修法刻意保守：扁平字段全部保留（`input`/`canonical_smiles`/`inchikey`/`formula` 还在顶层，现有调用方不受影响），**加上** `failure` 对象。

```json
{"ok": false, "failure": {"code": "E06", "channel": "rdkit", "stage": "parse",
 "message": "rdkit could not parse this SMILES", "hint": "Check the SMILES syntax"},
 "input": "nope", "canonical_smiles": null, "inchikey": null}
```

回归：`test_cd_cli_mcp.py` 11/11 仍通过（加字段不改结构，没有破坏 MCP 的 `isError` 判定）。

### 分子式一致性也验了

目标写的是「分子身份（InChIKey/分子式）一致」，之前只验了 InChIKey。补验阿司匹林：

```
rdkit     key=BSYNRYMUTXBXSQ-UHFFFAOYSA-N  formula=C9H8O4
kingdraw  key=BSYNRYMUTXBXSQ-UHFFFAOYSA-N  formula=C9H8O4
chemdraw  key=BSYNRYMUTXBXSQ-UHFFFAOYSA-N  formula=C9H8O4
```

两个身份维度、三个引擎，全部一致。

| 成员 | 任务 | 依赖 |
|---|---|---|
| read-com | t1 调研 COM 插入/导出与 CDXML 最小子集 | — |
| dev-kd | t2 KingDraw 适配器 `adapters/kd_native.py` | — |
| dev-cd | t3 ChemDraw 适配器 `adapters/cd_com.py` | t1 |
| qa | t4 M1 双通道验收（InChIKey 一致、往返一致、失败路径、进程卫生） | t2, t3 |

未验证项（明确写出）：跨机器可移植性、ChemDraw 非英文界面路径、KingDraw 版本差异、MCP 层与 DSH 插件层（尚未开始）。

## 2026-10-29 · 呈现层审计：拍下来才看得见的那批问题

> 这一轮不看功能对不对（前面已经验过），只看**人第一次用会撞到什么**。所有截图在 `test/out/shots/`，复现命令写在每条里。

### 取证工具（本轮新增，都可重跑）

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| 工具 | 干什么 | 为什么不能用肉眼代替 |
|---|---|---|
| `test/render_terminal.py <名> <列宽> -- <命令>` | 用真实 Consolas 字宽 + CJK 双宽把 CLI 输出渲染成终端样式图 | 本会话没有可见控制台可拍（实测：可见窗口里既无 `ConsoleWindowClass` 也无 Windows Terminal），而列碰撞只由字形度量决定，所以按度量重建 |
| `test/render_markdown.py <md> --width N` | Edge/Chromium headless 真渲染 Markdown 并截图 | 表格是否溢出、代码块是否截断，只有渲染后才知道 |

两个工具本身都出过会"说谎"的 bug，都修了：
- `render_markdown.py` 第一版只靠 `--window-size` 约束宽度，420px 下正文仍按更宽布局、右边缘被裁，看起来像"表格溢出"，实际是工具 bug。现在宽度钉在 CSS 里，并加了**页边墨迹门禁**：`L=0 R=0` 才放行（有墨即被裁）。
- 同一个脚本第一版没开 `footnotes` 扩展，README 的 `[^progid]` 直接漏成字面量；开 `tables/fenced_code/footnotes/sane_lists` 后才与 GitHub 一致。

### P0 · `install.ps1` 没有 BOM，README 第一条命令直接语法错误

复现：`powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1` → 退出码 1：
```
At ...\install.ps1:57 char:32
+ Note 'python' $true ('{0} ({1} ?? ) ...
Unexpected token '???' in expression or statement.
Missing closing '}' in statement block or type definition.
```
根因：文件是无 BOM 的 UTF-8。Windows PowerShell 5.1（新手敲 `powershell` 就是这个）按 ANSI(cp936) 读无 BOM 的 `.ps1`，中文全部解坏，引号配对随之崩溃。
修：加 UTF-8 BOM。加完同一条命令 **exit=0**，输出五行汇总（见 `test/out/shots/install_out_90col.png`）。
防回归：`test/test_install_script.py` 断言根目录与 `scripts/` 下每个 `.ps1` 都有 BOM 且正文是合法 UTF-8（4 条，全过）。

### P0 · README 让读者跑 `doctor both`，而这个值不存在

合法值是 `{cd,kd,all}`。`doctor both` → `invalid choice: 'both'`。已改成 `doctor all`，并注明「64 位跑这条时 kd 那一半报位宽、退出码 1 是预期」。

### P0 · CLI 默认输出从 JSON 改成人读之后，插件当场断了

`cmd_identity` 改成四行摘要后，`chem_identity` 工具报 `E99: the CLI did not return a JSON result`——因为 `bridge.js` 把 stdout 当 JSON 解析。已在插件侧给 `identity`、`crosscheck` 补 `--json`。
这是结构问题不是笔误：CLI 的默认输出在「人读」和「JSON」之间摇摆，而插件依赖 JSON，**每改一次呈现就可能断一次**，`tools/contract_sync.py` 抓不到（它只对账参数，不对账输出格式）。

### P1 · 终端表格被超长值顶开（这就是本项目里"文字重叠"的真实形态）

`doctor all` 在 80 列下：`route` 列宽 `%-14s`，而 `com-object+rdkit` 有 16 字符，把 `ok` 列从第 20 列推到第 22 列——同一张表里出现两种列位置。修法：列宽按内容计算（扫一遍取 max），而不是写死。

### P1 · 窄终端把 InChIKey 劈断，复制即错

40 列下旧版 `identity` 输出：`"inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA` / `-N"`。字符串里没有断行点，终端只能硬切，复制得到的是残缺的 key 且无任何提示。改成人读摘要后每行都短，40 列下完整（`identity_40_40col.png`）。

### P1 · 插件卡片把整份 JSON 直接糊在脸上

14 个工具共用一个 `render: (_args, value) => [{type:'text', text:value}]`，于是 `chem_identity` 的卡片第一行是 `{`，InChIKey 要往下滚。改成**先摘要后全文**：`✓`/`✗` + 错误码 + 关键字段，再接 `— 完整结果 —` 与原始信封，信息一点没少。降级结果额外标「预览级，不是投稿级」。`test/test_plugin_render.mjs` 14 条断言全过。

### 并行撞车（不是代码 bug，但会让人误判）

跑 `crosscheck` 时遇到 `Documents.Add() failed`，紧接着重跑两次都正常。同一时刻另有成员在跑审计——**ChemDraw 只有一个 COM 实例，A 进程自建实例退出时 `Quit()`，会把 B 进程 attach 的引用打断**。已提醒成员：见到这类错误先原样重试一次。

### 工具计数修正

「现状速查」里写的是 MCP 13 / 插件 12，实测 **MCP 15 / 插件 14**。已改，并注明这两个数字是不同集合（差异由 `tools/contract_sync.py` 列出）。
## 2026-10-29 · 自检与优化：输出契约收敛，加上一条能跑全量的命令

> 这一轮先补掉上一轮明确留白的**输出契约**（它当时被两个成员在维护的断言挡着），再拿"新人第一次跑"的顺序去找问题。

### P0 · 20 条命令两种输出形态，同一份结果对错各半

复现（改前）：`runtime/py32/python.exe bin/cli.py kd formula --smiles c1ccccc1O` 打 15 行 JSON 信封，
答案 `C6H6O` 在第 8 行；而 `doctor` / `identity` / `crosscheck` 打的是人读摘要。同一份结果，一半命令一种形态。

根因：`--json` 只长在 4 个 parser 上，`_emit_result()` 无条件 `json.dumps`。插件和 MCP 又把 stdout 当 JSON 读，
所以**谁都不敢先动**——这正是它上一次只做了一半的原因。

修：20 条叶子命令统一「默认可读 / `--json` 出信封」。`--json` 由 `_add_json_flag()` 在 `build_parser()`
返回前遍历整棵 argparse 树统一补（不是逐个改 22 个 parser，否则下一个子命令还得靠谁记得）；
`_emit_result(res, out, as_json)` 认这个标志；插件 `spawnCli` 统一追加 `--json`。
守门：`test/test_contract_sync.py::test_13` 断言 20 条叶子全部接受 `--json`。

**这是唯一一处对外可见的破坏性变更**：`kd *` / `cd *` 默认从 JSON 变人读。项目未发布，代价为零。
MCP 层不受影响——`mcp_server.py` 只把 32 位 worker 当子进程调，不经过 `cli.py`。

### P1 · 收敛过程中自己造的两个显示问题（40 列截图才发现）

第一版把失败摘要直接 `print` 出去，40 列下终端硬折：`automation` 被切成 `auto` / `mation`，续行顶格；
`fix` 里的路径折成 `App` / `Data\Local\Programs\...` / `hon.exe`。改法：复用已有的 `_render_failure`
（`│` 引导条 + 悬挂缩进）。对照图见 `docs/img/presentation/11-json-wrap-*.png`。

第二条不是新的，是 `_wrap` 的老洞：它只在**路径位于行首**时缩短，前面一旦有词（`Run with`）就退化成硬折，
与它自己 docstring 里「路径宁可缩短也不折」相反。影响不止新渲染器，`identity` / `crosscheck` / `doctor` 的
fix 行都走这条路。改法：分词后先判断「这个词在任何位置都放不下」并提前缩短。

### P0 · 示例脚本四个键全都读错了，一直在打 `None x None px`

复现：`python examples/draw_figure.py` →

<!-- nowrap: 程序输出，原样引用 -->
```text nowrap
drew None atoms / None bonds
wrote phenol_acs_single_column.png - None x None px
      None mm at None dpi
```

真值是 `atoms_after` / `bonds_after`（`draw_smiles`）和 `data['figure']` 里的 `width_px` / `height_px` /
`dpi` / `width_mm`（`export_figure`）。退出码一直是 0、PNG 真的写出来了 1922x1302——**没有异常、没有测试红**，
因为那几个数只是打印，没有断言。

修：按真值重写那三行。防回归：`test/test_examples.py` 4 条——真跑三个示例、禁止输出出现 `None`、
出图那行必须匹配 `\d+ x \d+ px, \d+ dpi, \w+ mode`，另有一条静态检查：示例里每个 `.get('key')`
的键必须真的在某个模块里出现过（运行期只看得到执行到的分支，这条看源码）。

### P1 · 那次提交把生成出来的 PNG 一起提交了

`examples/out/phenol_acs_single_column.png` 进了仓库。`test/out`、`runtime` 早有"生成物不入库"的守门，
`examples/out/` 漏了。已补进 `.gitignore`，并把 preflight 那条检查从两处扩到三处（第 11 条旁边）。

### P1 · `cd_com.py` 的模块 docstring 里有非法转义

里面写着 `'%TEMP%\cdprobe\p_ascii.png'`，不是 raw 字符串，`\T` 是非法转义（3.12 起 import 就报警）。
今天恰好还是对的（非法转义原样保留），但 `\t` `\n` 也是很合理的目录名，写错就静默变成控制字符。
改成 `r'''`；preflight 新增第 11 条：编译时把 `SyntaxWarning` / `DeprecationWarning` 当失败。

### 实测留档 · 硬杀会留下一个 ChemDraw 窗口（不修，理由在此）

起一个正在出图的 CLI，1.5 s 后 `TerminateProcess`：实例数 `0 → 1 → 1`；下一次命令 0.3 s 内接上它并正常返回。
功能没坏、也不会累积（下一次是 attach 不是新起），但窗口留着。不修：唯一的所有权凭据是会被复用的 PID，
误杀一个用户正开着、里面有未保存结构的实例，比多留一个空窗口严重得多。
Ctrl-C 不是这个情况——它走 `finally`，`ch.close()` 照常执行；这条用 AST 断言钉住了
（`test_architecture_backend.py::test_13`，删掉 close 立刻红）。详见 `docs/architecture-audit.md` P2-1。

### 新增 · `python test/run_all.py`：一条命令跑全部自检

17 个套件要两个解释器（KingDraw 的 DLL 是 x86、ChemDraw 的 typelib 是 x64）、两个厂商程序、还要 node。
「哪个文件要哪个解释器」以前只记在人脑子里，所以「你跑测试了吗」没有可复现的答案。

本轮实测：**17 passed, 0 failed, 0 skipped in 168.4s**，退出码 0。缺前置的报 `SKIP` 并说清缺什么，
**不报 PASS**；套件表与目录对不上（新加一个 `test_*.py` 忘了登记）直接 `exit 2` 并指名。

### 本轮数字

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| 项 | 改前 | 改后 |
|---|---|---|
| 叶子命令能出 JSON 的比例 | 4 / 20 | 20 / 20 |
| `kd formula` 默认输出行数（80 列） | 15（答案在第 8 行） | 6（答案在第 4 行） |
| preflight 检查项 | 10 | 11 |
| 测试套件 | 16 | 17 |
| 一条命令跑全量 | 没有 | `test/run_all.py`，168 s |
## 2026-10-29 · 补记：一次不可复现的红，和跑测器自己的一个毛病

全量扫了四遍，记全：

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| 序 | 跑什么 | 结果 | 用时 |
|---|---|---|---|
| 1 | 全部 17 个套件 | 17 passed | 168.4 s |
| 2 | 全部 17 个套件 | 15 passed, **2 failed** | 319.4 s |
| 3 | 只跑红的那组（cd 三条 + misuse） | 4 passed | 96.6 s |
| 4 | 全部 17 个套件 | 17 passed | 181.5 s |

第 2 遍里 `test_misuse::test_the_format_extension_is_added_on_both_channels` 卡了 126.14 s
（`CHEMTOOL_COM_TIMEOUT` 是 120 s，同一量级），紧接着 `test_no_vendor_process_is_left_behind`
因为那次超时留下的 `KingDraw.WpfForm.exe` 被判红；同轮 `test_kd_save` 也红。这组单独重跑 4/4 全过。

**根因未证实**，所以这里不写"应该是 COM 卡住"。能确定的只有三条：126 s 与 COM 截止时间同量级；
一行代码没改就恢复了；失败那轮留下了 vendor 进程。与本项目已记的跨进程 COM 相遇（P1-4）同族。

跑测器因此改了一处，改的是它自己的毛病：第一次失败时它只打最后三行，而那三行是
`12 passed, 2 failed`——**说清了多少，没说清是什么**。现在优先打带判据的行（`FAIL` / `Traceback` /
`AssertionError`），统计行缀在后面；命中已知瞬时特征（`E10` / `COM_STALLED` / `Documents.Add() failed`）
再补一行提示。**没有加自动重试**：重试会正好把这种红藏起来，而"哪一遍红过"是这一轮唯一有价值的信息。
## 2026-10-29 · 第二轮：`--help` 被中文撑破，以及一条「已知风险」被实测推翻

> 这一轮挑了两个之前没碰的面：新人真正敲的第一条命令（`--help`），和审计文档里唯一一条挂着没做的后端风险（P1-4）。

### P1 · `--help` 在 40 列下被中文帮助撑破（上一轮自己埋的）

复现：`COLUMNS=40 python bin/cli.py kd smiles --help`——

<!-- nowrap: 程序输出，原样引用 -->
```text nowrap
  --json      打印完整结果信封（机器可读）
```

这一行是 42 列。argparse 折行按**字符数**算：14 个汉字记 14 列、印出来 28 列，于是它认为放得下，
终端在第 40 列硬切，剩下的 `）` 单独掉到下一行行首（`docs/img/presentation/12-help-before-40col.png`）。

修：改成 `print the full result envelope as JSON`。这不只是长度问题——扫了一遍，这行是全项目
**唯一**一处非 ASCII 的 argparse 帮助文字，其余全英文；顺手统一了语言。

判据：`test/test_presentation.py::test_every_leaf_help_fits_forty_columns`，走全部 20 条叶子的
`--help`，40 列下散文行一律不许超宽。例外留得很窄：argparse 拆不开一个不可分的选项组
（实测 `doctor` 的 usage 要 61 列、`cd draw` 的选项列 47 列），这类行按「行首就是选项本身、
整行最多一个空格」识别；`--json      打印…` 是选项 + 一串空格 + 帮助，属散文，必须折。
把中文放回去，这条判据立刻报 `(42, '  --json      打印完整结果信封（机器可读）')`。

### 后端 · P1-4 跨进程 Quit 竞态：代码路径真实，触发条件不存在

审计文档里它排 P1、挂了两轮，写的触发条件是「MCP 常驻起的实例 + 另一个终端 attach，然后 MCP 退出」。
这一轮真跑了：

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| 实验 | 调用次数 | 失败 |
|---|---|---|
| 两个 `cd figure` 同时跑，错开 0.4 s，3 轮 | 6 | 0 |
| `crosscheck` + `cd figure` + `cd capabilities` 三路混跑，3 轮 | 9 | 0 |
| 常驻 MCP 起实例 → 一次性 CLI attach → 关掉 MCP | 3 | 0 |

同时每 0.15 s 采一次实例数：整个过程**只有 1 个 ChemDraw 实例**，两个进程确实共用了它——
共享是真的，只是 `Quit()` 没落进对方的调用窗口。

决定性的在第三组：resident 调完一次 `chemdraw_draw` 之后立刻数，**实例数是 0**。t21 加的
`com_broker` 每次调用结束就把实例放掉了，常驻进程根本不跨调用持有 ChemDraw——审计文档写的那个
触发条件**在当前架构下不存在**。

处理：不修代码，改文档。P1-4 从「待修」降为「架构约束」，并把 5 处交叉引用一起改口
（两处分析结论、两处待办清单、一处历史记录加注）。**留着这条的理由**：将来若为加速而给 MCP
缓存实例，这条立刻复活，届时的前置条件写在条目里。

### 本轮数字

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| 项 | 改前 | 改后 |
|---|---|---|
| 40 列下 `--help` 超宽的行 | 20 条叶子中 2 条（`kd smiles` 42 列、`cd figure` 46 列） | 0 条散文行 |
| `test_presentation` | 15 条 | 16 条 |
| 待修的后端风险 | 1（P1-4） | 0 |
| 并发调用实测 | 1 次失败（未复现） | 15 次调用 0 失败 |
## 2026-10-29 · 第二轮补记：全量里的四个红，其实是同一个原因

> 上一轮记下的"一次不可复现的红"，这一轮又红了两次，而且是稳定可复现的——只是复现条件不在代码里，
> 在**桌面状态**里。

### 现象

全量扫，四个套件红，症状各不相同：`test_kd_export`（每条 123 s，E05）、`test_kd_open`（`KeyError: 'open'`）、
`test_kd_save`（E05）、`test_misuse`（两条超时）。单独重跑这四组 4/4 全过。

### 根因

起作用的不是这四个套件，是**它们之前那次运行留下的一个 KingDraw 进程**。它占着单实例锁：下一次启动
把文件转发给一个谁也看不见的窗口，工具等满 `--timeout`（默认 90 s）报 E05，然后把同样的状态留给下一轮。
所以「先红一次 → 之后每次都红」是同一个残留，不是四个 bug。

### 反证（不写这条，结论就反了）

用户**正常开着** KingDraw（有窗口，pid 59268）时，`kd export` **15.0 s 成功**。所以不是「开着就坏」，
坏的是「启动后等不到窗口」这条路。

### 修了什么

只修消息层，代码路径没动。原来那段失败提示只有两种说法，而实际有三种状态，最乱的一种正好没覆盖：
`existing` 空（启动时没看到进程）但 `still_running` 非空（现在冒出来一个）时，提示是
「Leave it running or close it by hand」，读者完全不知道「有一个我没 attach、也归因不了的进程」这件事。
现在 `_no_window_hint()` 三个分支：指名 pid / 明说残留并给 `taskkill` / 给 `--timeout`。
判据 `test/test_kd_adapter.py` 三条，把旧那句话放回去立刻不满足断言。

跑测器也加了一条对应特征：下次再遇到，它会直接说「是残留的 KingDraw，后面几个套件会因此失败，
不是它们自己的问题」，而不是甩出四个互不相关的红。

### 没修 / 没查清

- **没修等待时长**：默认 90 s 对「本来就不会出窗口」的情况仍然太长。`--timeout` 是现有逃生口，
  但没改默认值——缩短会影响真正慢启动的机器，而那种机器我手上没有。
- **没查清那个无窗口实例怎么产生的**（怀疑是被 taskkill 中断的残留，未证实）。这条留在
  `docs/architecture-audit.md` P2-2 里，标的是「怀疑」。


## 2026-10-29 · 第三轮：从干净克隆开始用一遍

> 前两轮所有数字都是在**已经装好**的工作目录里量的。这一轮先把仓库 clone 到空目录，只跑 `install.ps1`，
> 再走 README 建议的那几步——这才是读者真正会经历的顺序。

### 结果：干净克隆能跑（这条要先说，因为后面三个坑都是在这条路上踩的）

克隆里没有 `runtime/`、没有 `examples/out/`、没有任何未跟踪文件（152 个跟踪文件）。
`install.ps1` rc=0，五项全 `[ok]`（python / dependencies / kingdraw-runtime / chemdraw / kingdraw，
32 位运行时是脚本当场下的）。三条示例 rc=0，`examples/out/` 由脚本自己创建。

### 坑一：`--json` 的 stderr 备忘让 `2>&1` 变成非法 JSON

`cd figure ... --json > out.json 2>&1` 产出 2613 字节，第一行是 `chem-draw-tool: 2 warnings: ...`，
解析器直接死在 `Expecting value: line 1 column 1`。修：备忘只在 stdout 还是终端时写 stderr。
修后同一个命令产出 2456 字节纯 JSON，`json.loads` 通过。

### 坑二：参数错误要先连上 COM 服务器才报得出来

`cd modify` 不带编辑参数，正确回答是「告诉我要改什么」，实测在没装 ChemDraw 的机器上只会拿到
E01「连不上 ChemDraw」。原因：这条检查写在 `_cd_dispatch` 里，而它只在通道打开之后才跑。
修：抽 `_cd_validate_args()`，在 `_open_cd_channel()` 之前调用；判据查**源码调用顺序**，
因为在装着 ChemDraw 的机器上两种顺序给同样的答案，行为测试看不出来。

### 坑三：`cd figure` 的位置参数是输出，传源文件时提示指向反方向

`cd figure phenol.mol --out out.png` → `phenol.mol` 被当成输出名 → 「nothing was drawn ... pass a file
instead of a string」，让用户去做他刚做过的事。修：位置参数的名字以化学后缀结尾（存在与否都算）且没给 `--smiles` 时直接说清楚。判据里两条路径都断言——
干净克隆上那个文件本来就不存在，而要求 `isfile` 的版本在那里又退回原句，正是这一轮踩到的第二次。

### 顺带：85 mm 到底能到多少 dpi（量出来的曲线）

| 要求 | 实得像素 | 实得宽度 |
|---|---|---|
| 300 dpi | 995×672 | 84.2 mm |
| 500 dpi | 1656×1121 | 84.1 mm |
| 574 dpi | 1901×1288 | 84.1 mm |
| 600 dpi | 1922×1302 | 81.4 mm ← 撞 1922 px 上限 |
| 1200 dpi | 1922×1302 | 40.7 mm ← 撞上限 |

上限就是 1922 px，所以「85 mm 能到多少 dpi」有精确答案 574，而原来的警告只说「出来是 40.7 mm」。
修：撞上限时把 `dpi_fit`（画布宽 × 25.4 ÷ 目标毫米）算出来，进 `data.figure.dpi_fit` 和警告正文；
示例脚本读到它自动按 574 重导一次，产出真 85 mm 的图。

### 本轮数字

| 项 | 修前 | 修后 |
|---|---|---|
| `test_presentation` | 16 | **18**（+合并流解析、+位置参数） |
| `test_architecture_backend` | 13 | **14**（+调用顺序） |
| `test_examples` | 4 | 4（断言收紧到 85 ± 1.7 mm） |
| 干净克隆 | 没量过 | 全绿，3 示例 rc=0 |
| `--json > f 2>&1` | 非法 JSON | 2456 字节可解析 |


## 2026-10-29 · 第四轮：把 MCP 服务器当敌意客户端来打

> 前三轮都在命令行这一侧。这一轮换到 MCP stdio 那一侧：真实 JSON-RPC、一次一条脏输入。

### 先记过的（实测，不是推断）

通知（无 id）不回答、`this is not json` 回 `-32700`、未知方法回 `-32601`、未知工具回
`result.isError = true`、50 KB 参数不崩、脏输入之后正常调用照常工作。
`isError` 这一条单独验了：工具级失败确实是 `isError: true`，不是「假装成功的文本」。

### 没过的：缺参数回了一个被截断的 traceback

`tools/call chem_identity {}` →
`{"code": "E99", "message": "tool raised", "detail": "t recent call last): ..."}`。

开头那个 `t` 是 `Traceback` 的尾巴——`detail` 是 `format_exc()[-800:]`，从中间截断的。
三件事同时不对：吐 traceback、message 不说是什么错、`KeyError: 'smiles'` 不提，
而 schema 里明写着 `required: ['smiles']`。

修：`KeyError` 单独认，回 `E06 / stage=arguments`，指名缺哪个参数，hint 从 schema 的 required
和 properties 生成（顺带报 schema 里没声明的参数）；其余异常只给 `工具名 raised 异常类型`。

判据 `test_mcp_wire.py` 8 → **16** 条，其中两条是钉子：缺参数的答案里不许出现 `Traceback`、
也不许出现 `tool raised`。

### 本轮数字

| 项 | 修前 | 修后 |
|---|---|---|
| `test_mcp_wire` | 8 条，只有 happy path | **16 条** |
| 缺参数的答复 | `E99 tool raised` + 截断 traceback | `E06 missing required argument` |
| 无 id 的请求 | 回 `id: null`（违反 JSON-RPC） | 不回答 |


## 2026-10-29 · 第四轮续：让一个子代理当第一次使用的人

> 目标里写着「用子代理与脚本模拟真实人类使用」，前几轮都是我自己换视角。这一轮真的起了一个子代理，
> 给它一条硬约束：不许碰会开窗口的命令，只走第一条路径、纯参数和 --json。它交回 8 条，全部可复现。

### 两条是静默错答（比崩溃难发现得多）

**`kd match` 的答案被整个丢掉。** `kd match 'CCO' 'c1ccccc1'` 和 `kd match 'CCO' 'CCO'` 输出
**逐字节相同**（各 63 字节、rc 都是 0），只有加 `--json` 才看得出 `data: false` 与 `true`。
原因：`_render_result` 只走 dict 和 str 两个分支，裸布尔被静默跳过。修：补标量分支并给它一个名字
（`match : false`），判据 `test_presentation.py::test_a_one_value_answer_is_never_dropped` 同时断言
两者输出必须不同。

**`kd king` 把空结构报成成功。** 喂 `requirements.txt`（甚至空文件、普通 molfile）给 `kd king`，
回 `ok: true`、rc=0、无 warning，而 nodes/bonds/texts/sups/shapes 全空。修：解析出来后若五类全空，
标 degraded 并给一句「这文件里没有结构」，人类形态显示 NOTICE 行。不直接判 E06——空画布是合法状态，
但静默交付空答案不是。

### 三条是把本机信息/错误信息泄进了产品

- **E04 的 hint 写死我本机的绝对路径** `<user-home>\...\python.exe`。这在任何别的机器上都是错的，
  而且贴不了。改成「用 64 位 python 重跑，不是 runtime/py32/python.exe」。
- **裸敲 `kd` / `cd` 得到的是顶层五项表**，而那张表里没有一条 kd 动作——等于答非所问。改成打印该通道自己的
  命令表，rc 仍是 2（命令没敲完）。
- **敲错选项报的是顶层 usage**：`identity CCO extra` 打印五项表并说 `<command>`，指到错的命令。
  原因是 argparse 永远把 unrecognized 报给调用 `parse_args` 的那个 parser。改成 `parse_known_args` +
  按 `cmd`/`kd_cmd`/`cd_cmd` 找到真正持有叶子的 parser 再 `error()`，于是 usage 行就是那条命令的。

### 三条是文档在说谎

- README 说「每个子命令 `--json` 都是完整信封」，但 `doctor` 是 `channel`/`available`/`capabilities`、
  `identity` 是扁平字段，都没有 `data`。改文档并点名两个例外（判 doctor 的成败看 `available`）。
- README 的 MCP 工具清单写着 `chem_doctor`（不存在），`kingdraw_*` 写 6 个（实为 7 个）；
  3+6+6 恰好等于 15，把错掩住了。按 `tools/list` 的真实清单重写。
- `docs/quickstart.md` 说 32 位跑 `doctor cd` 报 `E08`、message 是 `This interpreter is 32-bit`、detail 为空。
  实测是 `E04`、message 更长、detail 是 `sys.maxsize=2147483647`。`E08` 是 `NOT_INSTALLED`，与位宽无关。

### 子代理顺带指出、本轮没修的

- 纯粹的参数错误（文件不存在）的信封里 `evidence = "C"`、`evidence_note = "design inference, not yet
  verified"`——一条路径错误谈不上「设计推断」，这句注解没有意义。
- `doctor --json` 的 `version` / `home` 是 `""`，只有人类形态才显示 `unknown`。
- 多处 `failure.detail` 为 `""`。

### 本轮数字

| 项 | 修前 | 修后 |
|---|---|---|
| `kd match` 两种答案 | 都是 63 字节，无法区分 | `match : true` / `match : false` |
| `kd king` 非 .king 内容 | `ok: true`，五类全空 | `degraded` + NOTICE |
| E04 hint | `<user-home>\...` | 与本机无关的一句 |
| `identity CCO extra` | 顶层五项表 | `usage: chem-draw-tool identity ...` |
| 裸 `kd` | 顶层五项表 | kd 的 11 条命令表 |
| `test_presentation` | 18 | **19** |


## 2026-10-29 · 第五轮：把最后一块没验过的交付面验了（DSH 插件真加载）

> 前四轮全在 CLI 与 MCP 两侧。插件这个面一直停在「装得上」——`--dump-config-schema` 能过只证明
> 模块能被 import，`apply()` 里 `ctx.tools.register` 有没有真跑过，从来没人看过。

### 做法（一次性 _probe profile，不碰 desktop）

按 `~/.dsh/skills/dsh-plugin-ops` 的 A8②：建一个临时 profile，`dsh plugin --profile _probe add link:...`，
再跑 `dsh --profile _probe --dump-config-schema`——这一步会**真的导入**每个 bundle 并读它的配置 schema。
写 `.dsh` 前按 `AGENTS.md` 取了互斥锁，验完删 profile、解锁、`clean` 回 `ok:true`，LOG 有成对条目。

### 结果：三段都对

| 检查 | 证据 |
|---|---|
| 接线痕迹 | dependencies = `link:D:/.../dsh-plugin`；bundles 含插件名；有 junction |
| 真加载 | rc=0，stdout 600161 字节，**stderr 0 字节**，schema 里出现插件名 5 次 |
| 注册面 | 桩 ctx 调 `apply()` → 14 个工具全部注册，`inject=['tools']` |

没验的那一段写清楚了：desktop 接线与界面出现要退出 Electron 重启，那是用户的动作；
14 个工具的端到端调用要真开窗口，CLI 侧已由 17 个套件覆盖。

### 顺带修掉子代理留下的一条

纯路径错误（`kd formula --mol /nope.mol`）的信封里写着 `evidence: "C"` +
`"design inference, not yet verified"`——一条路径检查谈不上「设计推断」。改成 `A`（`measured on this machine`），
因为这确实是本机量到的事实，而不是推断。

### 本轮数字

| 项 | 修前 | 修后 |
|---|---|---|
| 插件 `apply()` | 未验 | 14 个工具全部注册 |
| 真加载 | 只验到 import | rc=0 / stderr 0 字节 / 600 KB schema |
| 路径错误的 evidence | `C` + 无意义注解 | `A` + `measured on this machine` |


## 2026-10-29 · 第六轮：查产品的核心承诺——结构保真

> 前五轮查的是「能不能用明白」和「装得上不」。这一轮查「说得对不对」：一个化学工具如果丢掉手性、
> 电荷或同位素，比界面错位严重得多，而且**看上去完全正常**——图还是那张图。

### 做法

12 个分子，每个都带一个「会丢的东西」，两个通道各走一遍，用 InChIKey 比（不是比 SMILES 字符串——
ChemDraw 读回来会重排 SMILES 顺序，字符串比较没有意义）：

| 分子 | 要保住的 |
|---|---|
| L-丙氨酸 / D-丙氨酸 | 四面体手性，两个对映体必须不同 |
| (E)-2-丁烯 / (Z)-2-丁烯 | 双键几何，两个必须不同 |
| 乙酸根 / 三甲铵 | 形式电荷，负和正 |
| 氘代甲醇 | 同位素层 |
| 咖啡因 | 稠合杂芳环 |
| 葡萄糖 | 四个手性中心 |
| 水 | 单个重原子，没有键 |

### 结果：两个通道 12/12 全部精确保住

| 分子 | KingDraw | ChemDraw |
|---|---|---|
| L-丙氨酸 | QNAYBMKLOCPYGJ-UWTATZPHSA-N | 同 |
| D-丙氨酸 | QNAYBMKLOCPYGJ-REOHCLBHSA-N | 同 |
| (E)-2-丁烯 | IAQRGUVFOMOMEM-ONEGZZNKSA-N | 同 |
| (Z)-2-丁烯 | IAQRGUVFOMOMEM-ARJAWSKDSA-N | 同 |
| 乙酸根 | QTBSBXVTEAMEQO-UHFFFAOYSA-M | 同 |
| 葡萄糖 | WQZGKKKJIJFFOK-VFUOTHLCSA-N | 同 |

（其余六个同此，`test/test_structure_fidelity.py` 里有全表。）

这条结论值得单独记：它说明两个引擎在**手性、双键几何、形式电荷、同位素**四类信息上没有分歧，
而 quartet 里任何一项出错都会让 InChIKey 的第二段变化。

### 变成常驻测试

新增 `test/test_structure_fidelity.py`（两个测试类各自 skip 自己的引擎，另加一条「两种写法产同一个文件」），已进 `run_all.py`，
套件数 17 → **18**。两条断言都是 InChIKey 相等 + **比较次数必须等于分子数**——
否则循环一个都没跑也会「通过」，那是假绿。

判据有牙：两个丙氨酸的 InChIKey 第二段是 `UWTATZPHSA` vs `REOHCLBHSA`，
任何丢手性的通道都会让它们相等而红。

### 顺带修掉一个我自己连踩三次的坑

写这个审计时，我三次把输入喂错：`kd mol --smiles CCO`、`kd smiles --mol x.mol` 全部报
`unrecognized arguments`。原因是 `kd mol` / `kd smiles` 收**位置参数**，而 `kd formula` / `kd to3d` /
`kd layout` 收 `--smiles` / `--mol`——同一个 CLI 两种约定，学了一个就会在另一个上撞墙。

修：两个子命令都加同名选项作为位置参数的别名，两种写法等价；一个都不给时给自己的 E06 而不是 argparse 的 usage。

### 顺手撞出来的一个更严重的问题：报告路径会把报告打掉

第一次跑全量时崩成这样：

```
  File "test/run_all.py", line 137, in transient_hint
    for signature, hint in TRANSIENT:
ValueError: too many values to unpack (expected 2)
```

是我第三轮加的那条「KingDraw 残留」特征写成了四个字符串元素（换行时忘了 `+`）。要命的是：
`transient_hint()` **只在有套件失败时才调用**。所以它安静地过了三个全绿的全量，
而它第一次被执行，正是某套件红了、我要读失败原因的那一刻——报告本身炸了，
后面的套件一个都没跑，我甚至不知道是哪个套件红的。

修法有两层：一是把元组写对；二是这种「只在失败路径上跑」的代码必须有专门的检查——
在 `run_all.py` 模块级验证每行是 `(signature, hint)` 两元组（错的话 import 就炸，
不等到凌晨三点），再加 `test_architecture_backend` 的第十五条：逐行解开、
逐条调 `transient_hint`、并确认绿日志返回 `None`。

这一条比它修的表面 bug 重要：**报告路径不参与正常路径的任何测试**，是典型的盲区。

### 本轮数字

| 项 | 结果 |
|---|---|
| 结构保真 | KingDraw 12/12、ChemDraw 12/12 |
| 套件数 | 17 → **18**；全量 18 passed / 177.8s |
| 失败提示表 | 四元素元组（只在失败时炸）→ 校验 + 一条测试 |
| `test_architecture_backend` | 14 → 15 条 |
| `kd mol` / `kd smiles` 写法 | 位置参数或 `--smiles` / `--mol` 都行 |


## 2026-10-29 · 第七轮：宽度预算这条承诺，到底守不守

> 渲染器给自己定了个规矩：任何一行都不超过终端宽度。这一轮去量这句话。

### 复现：32 列下有两条

```
OVERFLOW failure  w=32  line 9 is 35 cols: '  │ detail : sys.maxsize=2147483647'
```

原因：`_wrap()` 的立场是「绝不把一个词劈开」（这个立场本身对——Windows 路径被劈成
`AppData\L` + `ocal\Programs` 是噪音）。但 `sys.maxsize=2147483647` 是 20 列的
**不可断 token**，而 `  │ detail : ` 前缀有 13 列，32 列塞不下，于是整词吐出 → 溢出。

第二条是看出来的：32 列下 `identity` 把 InChIKey 劈成
`BSYNRYMUTXBXSQ-UHFFFA` / `OYSA-N` 两行。这条尤其严重，因为 `_render_identity` 的
docstring 自己写着「复制半截 key 就是错的 key，而且看不出来」——渲染器的存在理由，
在窄屏上被自己破坏了。

### 修复：三层，各管一件事

- **兜底**：`_wrap()` 遇到单独一行也放不下的词时按列硬切，续行挂在同一缩进。不溢出是底线。
- **失败块**：值列窄于 20 列时标签独占一行（`  │ detail:`），值另起。13 列前缀在 32 列终端里占 41%，不值。
- **字段块**：值是不可断 token 且比剩余宽度长时标签独占一行。判定是三条件——
  放不下 **且** 无空格 **且** 堆叠后放得下：只对 key/hash 这类东西生效，散文照旧在标签右侧折行。

堆叠判据是这三条一起：散文不该被堆叠（右边还有地方写），路径不该被折（会被 `_shorten_path` 中间省略）。

修完 32 列：

```
inchikey:
  BSYNRYMUTXBXSQ-UHFFFAOYSA-N
formula  : C9H8O4
```

### 验证：两个口径都归零

- **合成信封**：8 种形态（ok / 文本 / 标量 / degraded / evidence-C / 失败 / 长路径 / 中文）
  × 8 个宽度（32–120）→ **0 溢出**。
- **真实命令**：doctor、identity（正常与失败）、kd formula、kd match（真与假）、kd smiles（缺文件）
  × 32/40/60 三个宽度 → **0 溢出**。

两个都成了常驻测试：`test_presentation` 加两条
（`test_no_rendered_line_ever_exceeds_the_width_it_was_given`、
`test_a_key_that_does_not_fit_beside_its_label_gets_its_own_line`），19 → **21** 条。

写第二条测试时自己踩了一次：`_render_identity()` 内部读的是 `COLUMNS`，我在外面传一个、
循环里排一串宽度，测的却是环境里那个 —— 改 `os.environ` 后才真的在变。

### 本轮数字

| 项 | 结果 |
|---|---|
| 溢出（合成信封） | 1 条 → 0 |
| 溢出（真实命令） | 0 → 0（回归护栏） |
| 32 列下的 InChIKey | 被劈开 → 完整独占一行 |
| `test_presentation` | 19 → 21 条 |


## 2026-10-29 · 第八轮：同一个事实，人眼视图和机器视图说法不一致

> 每个信封都有两个视图：给终端看的摘要，和给脚本读的 `--json`。它们应该是同一个人说的同一句话。
> 这一轮去量这句话，量出三处矛盾。

### 复现：三处

**一、`doctor --json` 根本不是合法的 JSON 文档。** 它给每个通道各打一个对象，背靠背：

```
{ "channel": "chemdraw", ... }
{ "channel": "kingdraw", ... }
```

`json.loads(stdout)` → `Extra data: line 120 column 1`。任何脚本都读不了；能读的只有
用 `raw_decode` 循环的写法，而没人会为一个 CLI 写那个。

**二、同一个字段，两个视图说不同的话。** 人眼说 `version : unknown`，机器里是 `"version": ""`。
`""` 的含义是「确知为空」，`unknown` 是「不知道」——脚本拿到空串分不出这两种，而人眼视图早就分得清。
同类还有 `home`、`failure.detail`、`degrade_reason`、`capability.note`。

**三、健康的机器上 `doctor` 恒返回 1。** 这台机器：64 位解释器够不到 KingDraw，32 位够不到 ChemDraw，
而代码取两者的 `max()`——于是**任何一个解释器下 `doctor` 都说失败**，虽然工具完全可用。

### 修复

- `_doctor_body()`：问一个通道回对象，问多个回数组。单通道形状不变，现有脚本（包括本仓库的测试）不用改。
- `_doctor_status()`：**至少一个通道可用**就返回 0。问单个通道时仍然如实答那个通道
  （`doctor kd` 在 64 位下仍是 1，在 32 位下是 0）。
- `models._or_none()`：`Failure.hint/detail/stage`、`Result.degrade_reason`、`Capability.note`、
  `DoctorReport.version/home` 在 `to_dict()` 里空串一律变 `null`。一处收口，四个类型全覆盖。

抽成两个纯函数是为了可测：原来这段逻辑埋在 `cmd_doctor` 里，测它就要真的把 ChemDraw 拉起来、再杀掉。

### 验证

- **8 条命令的 `--json`**：8/8 是单个 JSON 值；`doctor` 为数组、`doctor cd` 为对象。
- **空串哨兵**（version / home / detail / hint / note / degrade_reason）：8 条命令里 **0** 个。
- **退出码**：`doctor` 1（本机 64 位下确实两通道都不全）、`doctor cd` 0、
  `doctor kd` 在 64 位下 1、在 32 位下 0。
- **常驻测试**：`test_contract_sync` 新增 `test_01b_…`，把两条规矩和退出码规则一起钉住。

写这轮时自己又猜错一次参数：`doctor --channel cd` —— 它收位置参数。这和第六轮 `kd mol --smiles`
是同一类错误：CLI 里同时存在位置参数与选项两种风格，学了一个就会在另一个上撞墙。
第六轮给 `kd mol` / `kd smiles` 加了别名；`doctor` 这次**没有**加——`--channel` 在别处也不存在，
只是我自己的错觉，加了反而是给一个没人用的写法留后门。

### 本轮数字

| 项 | 修前 | 修后 |
|---|---|---|
| `doctor --json` | 两个文档背靠背，`json.loads` 失败 | 单值是对象，多值是数组 |
| 空串哨兵 | 每条健康信封 1 个，医生 2 个 | 0（统一 `null`） |
| `doctor` 退出码（本机） | 恒 1 | 有通道可用即 0 |


## 2026-10-29 · 第九轮：把导出的图真的打开看（截图取证）

> 前八轮全在文字上：终端渲染、JSON 契约、结构保真。目标里写着「截图取证」「文字重叠/错位/溢出」，
> 而我一直只用文字交代这件事。这一轮把图导出来，真的看。

### 复现：导出的 PNG 四边贴肉

五个分子（乙酸根、葡萄糖、咖啡因、季铵、C30 直链）走 `cd export`，用 PIL 量墨迹到四边的边距：

```
molecule    size          margins L/T/R/B  verdict
acetate     260x242       0/0/-1/-1        CLIPPED at L/T/R/B
glucose     692x422       0/0/-1/-1        CLIPPED at L/T/R/B
quaternary  240x240       0/0/-1/-1        CLIPPED at L/T/R/B
```

打开图看，乙酸根那条通往甲基的 C–C 键末端正好落在最后一列像素上——读起来像**被裁断的键**，
而不是一个甲基。季铵更明显：四个键从四条边被切断。

根因不在导出区域（那里确实留了 6 pt 边），而在导出后的修剪：`_trim_png()` 按 alpha 外接框**精确**裁剪，
把边距连同透明区一起修掉了。所以「图四周有纸」这个直觉在成品上完全不成立。

### 修复

- `_trim_png(staged, in_place, pad_px)`：裁剪框按 `pad_px` 外扩，并夹在原图范围内。
- `export(trim_pad_pt=2.0)`：2 pt 换算成像素（300 dpi 下 17 px，约占小分子的 5%），
  正好让末端键不再贴边。envelope 里新增 `trimmed.pad_px`，可核。
- **`export_figure` 传 0**：这条路径的区域是按「你要多宽的纸」算出来的，再塞一圈纸就漂了。

最后一条是撞出来的：第一版对两条路径都加了 padding，全量立刻红两条——
`examples/draw_figure.py` 的 85 mm 图变成 79.6 mm，`test_08_export_figure_is_submittable` 的物理宽度也漂了。
**一个修复在同一份代码里同时服务两种契约时，必须分开**：普通导出没有宽度契约（多圈纸无害），
出版图有（85 mm 就是 85 mm）。

### 验证

| 口径 | 修前 | 修后 |
|---|---|---|
| 五个分子的四边边距 | 0 / 0 / 0 / 0 | 17 / 17 / 16 / 16 |
| 乙酸根 C–C 键末端 | 落在最后一列 | 距边 17 px |
| 85 mm 出版图 | 84.1 mm | 84.1 mm（不受影响） |
| 常驻断言 | — | `test_cd_cli_mcp` 量导出的四边边距必须 ≥ 8 px |

图（同一个乙酸根，修前 / 修后）：`test/out/gallery/acetate.png` 宽 260 → 294 px。

### 本轮数字

| 项 | 结果 |
|---|---|
| 贴边的导出 | 5/5 个分子 |
| 修复后贴边 | 0/5 |
| 全量 | 18 passed / 185.9s |


## 2026-10-29 · 第十轮：出版图说自己是 40.7 mm，其实它有 85 mm

> 第九轮给普通导出加了纸边，故意绕开了 `cd figure`，因为它的区域是按「你要多宽的纸」算的。
> 这一轮去量那条路径，量出更硬的问题：它报告的物理宽度是错的。

### 复现

```
cd figure 50  1922x1302  width_mm=40.7  dpi=976
cd figure 85  1922x1302  width_mm=40.7  dpi=574
```

要 50 和要 85，回来的都是 **40.7 mm**。而同一份 1922 px 按 976 dpi 是 50.0 mm、按 574 dpi 是 85.0 mm。
错在收尾那一步：`artwork.normalize()` 把 PNG 的 dpi 标签写成**你请求的 1200**，于是
`1922 / 1200 × 25.4 = 40.7 mm`。像素没变，说法变了——文件还是那个文件，只是它对自己的尺寸撒了谎。

更刺眼的是那一行警告：

```
this build caps ... so the figure is 40.7 mm wide instead of 85.0 mm ...;
574 dpi is the largest that still fills 85 mm
```

同一句话里先说「只有 40.7 mm」，再说「574 dpi 仍然填满 85 mm」——它自己指出了一个它没采用的答案。
而 `examples/draw_figure.py` 一直在**手动**做那件事：要 85，读 `dpi_fit`，按 574 重导。
工具的主路径需要它自己的示例来教，这是个坏信号。

### 修复

cap 命中时，标签跟着像素能支撑的 dpi 走：

- `achieved_dpi = dpi_fit`（1922 px / 85 mm → 574）；`normalize(dpi=achieved_dpi)` 写标签。
- `artwork.check(min_dpi=min(请求, 实际))`：请求的 dpi 是愿望，拿它当验收下限会把每一张 cap 图都判红。
- envelope 里同时给 `dpi`（实际）, `dpi_fit`, `requested_dpi`（请求），三件事分开说。
- 警告改写成「%g mm 出来是 %d dpi，不是 %d」——一句话只有一个说法。

### 验证

| 请求 | 修前 | 修后 |
|---|---|---|
| `--width-mm 50` | 报 40.7 mm（实际 50.0 @ 976 dpi） | **50.0 mm** @ 976 dpi |
| `--width-mm 85` | 报 40.7 mm（实际 85.0 @ 574 dpi） | **85.0 mm** @ 574 dpi |
| 示例脚本 | 手工重导一次才拿到 84.1 mm | 第一次调用即 85.0 mm、0 issues |

`test_cd_adapter` 的 `test_08` 原来把旧行为写成了断言（`width_mm < 60`），按新契约改成
「宽度是要的那个、dpi 说它用了多少、`requested_dpi` 仍是 1200」——这条改动在测试里写了理由，
不是为了让红灯变绿。

### 这一轮也回答了第九轮留的问题

`cd figure` 的四边仍然是贴边的（margin 0/0/0/0），这是**故意**的：它的宽度是精确契约，
再塞一圈纸就漂。纸边归 `cd export`（2 pt），出版图的纸由排版方决定。两条路径两种契约，各说各的。

### 本轮数字

| 项 | 修前 | 修后 |
|---|---|---|
| 出版图的物理宽度 | 恒报 40.7 mm | 要多少报多少（50.0 / 85.0） |
| 示例脚本 | 需要手动二次导出 | 一次到位，0 issues |
| 全量 | — | 18 passed / 177.8s |


## 2026-10-29 · 第十一轮：存出来的 .king 打开没有元素，等于一张假图

> 第九、十轮看的是 ChemDraw 的画。这一轮把同样的方法用到 KingDraw 的画上，
> 结果撞出一件比排版严重得多的事。

### 复现

`kd mol` → `kd save` → `kd export`，三个分子走同一串：

```
molecule   png size     margins L/T/R/B   verdict
acetate    336x300      (8, 9, 171, 152)  右边 171 px、下边 152 px 全空
caffeine   300x350      (0, 7, 14, 10)    左边贴死
glucose    380x300      (8, 12, 16, 13)
```

打开图看：**葡萄糖画的是一张光秃秃的环己烷**，六个氧、OH、立体键全不见；咖啡因是一张没有 N 的嘌呤骨架。
同一份 molfile 直接导出（不经过 .king）却是完全正确的——楔形键、HO/OH、环氧样样都在。

所以东西是在 `kd save` 那一步丢的。但 `.king` 里结构其实是对的：

```
{"type": "O", "label": "", "hCount": 0, ...}   ← 12 个节点，6 个是 O
```

元素在，只是 **`label` 是空的**。而 KingDraw 渲染字母用的是 `label`，不是元素那一列。

### 定位

格式是这个工具**手写**的（`kd_save.king_text()`），参照物是本机的 `Cyclohexane.king`——
**全碳**，所以标签字段在样本里从来没出现过。写异原子时只知道元素列，不知道还要一个 `Label=`。

对照组实验（给杂原子追加不同属性，看导出的图有没有字母）：

| 写法 | 导出尺寸 | 墨迹像素 | 结论 |
|---|---|---|---|
| 无（基线） | 240x212 | 5083 | 光秃顶点 |
| `Label=O` | 260x236 | **6355** | **字母出现** |
| `label=O` | 240x212 | 5083 | 被忽略 |
| `Html=O` | 240x212 | 5083 | 被忽略 |
| `Text=O` | 240x212 | 5083 | 被忽略 |

### 修复

`king_text()` 给碳以外的原子追加 ` Label=<元素>`：碳保持裸顶点（这是骨架式的正确画法），
其余原子自己报名。修后同一串导出，葡萄糖的六个 O 全部出现。

### 验证

| 口径 | 修前 | 修后 |
|---|---|---|
| 葡萄糖 .king 导出 | 光秃己烷环 | 6 个 O 标签 |
| 乙酸根导出 | 裸顶点 | 两个 O |
| `.king` 里的 `label` | 空 | `O` |
| 常驻测试 | — | `test_kd_save` 新增：6 个 O 必须带 `Label=O`，碳必须不带 |

### 顺手修掉的排版

`kd export` 从不裁边：乙酸根那张图右边 171 px、下边 152 px 全是死白，图挤在左上角。
加了 `_trim_to_ink()`：按背景色（取四角像素，不假设白）找墨迹框，裁掉死白，再补一圈均匀边距（短边 6%）。
裁完 336x300 → 240x212，四边 7/8/8/5。

（咖啡因裁完左边仍是 0：墨迹贴在 KingDraw 自己的画布边上，裁不出纸——那是它的渲染位置问题，
要往外补画布才解决，留给下一轮。）

### 还剩的缺口（写清楚，不是藏起来）

标签现在只是 `O`，正确的写法是 `OH`——格式里 `HCount=<n>` 是已知属性（`kd_save` 的文档字符串里记着），
但写入时没有从结构里取氢数。这是「氢数/手性写入」那条老缺口的一半，下一轮补。

### 本轮数字

| 项 | 结果 |
|---|---|
| 丢标签的 .king | 每个含杂原子的分子 |
| 修后 | 0（碳以外全部报名） |
| kd 导出死白 | 右边 171 px → 0 |
| 全量 | 18 passed / 177.9s |


## 2026-10-29 · 第十二轮：让羟基写成 OH，而不是一个孤零零的 O

> 上一轮把元素标签修出来了，但标签只是 `O`。对化学家来说 `O` 和 `OH` 是两个东西：
> 前者是氧负离子或自由基，后者是羟基。这一轮补上氢。

### 先证伪一个想当然

`.king` 格式的文档字符串里明明白白写着 `#ff000000 [HCount=<n>]`，所以第一版实现是
给原子追加 `HCount=1`。导出后**图与上一版字节完全相同**（同一个 sha256）：

```
{"type": "O", "label": "", "hCount": 0}   ← 格式里有这个字段
HCount=1 写进去 → 渲染不变
```

KingDraw 渲染时**根本不看 `HCount`**。

### 那么 `Label` 是什么

对照乙醇（一个羟基）试三种写法：

| 写法 | 导出尺寸 | 墨迹 | 结论 |
|---|---|---|---|
| `Label=O HCount=1` | 260x104 | 4235 | 只画 O |
| `Label=OH` | **296x104** | 4770 | **画出 OH** |
| `Label=HO` | 260x104 | 4235 | 画出 HO（朝向由它自己定） |

`Label` 不是元素符号，是**要画的文本本身**。所以氢必须拼进标签里。

### 氢数从哪来

写入器只有元素和键级，没有氢。用价电子规则算：

```
N/O/P/S/卤素：H = 价 - 键级和 + 形式电荷
C/B：        H = 价 - 键级和 - 形式电荷
```

形式电荷原本没被解析——这一轮补上 V2000 的 `M  CHG` 与 V3000 的 `CHG=`。
不然乙酸根的 O⁻（一键）会被算成 1 个氢，渲染成 `OH`，那比不写还错。

价表只覆盖有机结构真会出现的元素；表里没有的元素不写氢数，保持旧行为。

### 验证

| 分子 | 期望 | 实际写入的标签 |
|---|---|---|
| 乙醇 | 一个 OH | `Label=OH` |
| 葡萄糖 | 5 个 OH + 1 个环 O | 五个 `Label=OH`，环上 `Label=O` |
| 丙氨酸 | NH2 + 羰基 O + 羟基 OH | `Label=NH2` / `Label=O` / `Label=OH` |
| 咖啡因 | 4 个 N、2 个羰基 O，全不带氢 | 全部裸标签 |

导出图：葡萄糖从「六个裸 O」变成正确的吡喃糖画法（五个 HO/OH、环上 O），
连左右朝向都由 KingDraw 自己处理（左侧写成 HO）。

`test_kd_save` 那条断言收紧为：五个 `Label=OH`、一个裸 `Label=O`、碳不带标签。

### 还差一件

电荷符号仍然没画：乙酸根的 `O⁻` 只显示 `O`。氢数算对了（电荷在内部参与了计算），
但减号没有出现在图上。`Label=O-` 能否渲染、会不会破坏解析，下一轮验。

### 本轮数字

| 项 | 结果 |
|---|---|
| 羟基标签 | `O` → `OH` |
| 形式电荷解析 | 无 → V2000 + V3000 |
| 影响到的套件 | kd_save 6 passed 1 skipped、kd_export 4 passed |


## 2026-10-29 · 第十三轮：电荷画出来了，无窗口的残留进程也拦下来了

### 一、电荷符号

乙酸根上一轮只显示 `O`，减号没有。四种写法对照（量尺寸与墨迹）：

| 写法 | 导出 | 墨迹 | 结论 |
|---|---|---|---|
| 基线（`Label=O`） | 260x236 | 6355 | 无符号 |
| `Label=O-` | 276x240 | 6492 | **画出减号** |
| `Charge=-1` | 260x236 | 6355 | 被忽略 |
| `Html=O<sup>-</sup>` | 260x236 | 6355 | 被忽略 |
| `Text=O-` | 240x232 | 5513 | **标签消失**（危险） |

所以符号跟氢一样，只能拼进 `Label` 里。实现：`元素 + 氢 + 符号`，顺序按化学惯例
（`NH3+`、`O-`）。

还想让它成为上标，试过 Unicode 上标减号 `O⁻`（280x240）——KingDraw 把它压平了，
与 ASCII 减号同高。那就用 ASCII：不依赖字体覆盖，别的机器上不会变方框。

验证：乙酸根 `Label=O-`（羰基那个仍是 `Label=O`，因为它一键带双键、无氢无电荷）；
甲铵 `Label=NH3+`。纯 Python 单测断言 `M  CHG` 被解析进原子、且写进标签。

### 二、无窗口的残留进程（更重的一条）

今天跑 `test_kd_save` 时撞上：`open_file` 卡满 25 秒后 E05——

```
KingDraw was already running (pid 78472) but no window could be attributed to it
```

而文件本身完全正常。这是老陷阱：KingDraw 单实例，残留进程持有那把锁，新启动把文件
交给一个**谁都看不见的窗口**，于是等到超时。历史记录里它一次造成过两个 123 秒超时、
四个套件三种不同症状的失败。

原来的代码只把 pid 写进 `detail` 让人自己去 `taskkill`。这一轮改成自己收尸：

1. 启动**之前**扫一遍：有没有「连窗口都没有」的 KingDraw 进程（`visible_only=False`
   也为空，所以连 splash 都不存在）；
2. 有就 `close_app`（WM_CLOSE）；
3. **收不到就强杀**——`close_app` 只发 WM_CLOSE，没有窗口的进程永远不会回应，
   这正是不修就永远修不好的原因；
4. 清掉了就写进 `data['stale_instances_cleared']` 并附一条 warning，不静默。

为什么强杀是可以的：一个连窗口都没有的进程，不可能正在给谁看东西，所以不会毁掉
未保存的可见工作；而它确实占着那把锁。

验证（新增 `test_a_windowless_leftover_is_cleared_before_launch`）：拿一个真进程
冒充残留（没有窗口的 python，`list_pids` 用包装函数把它并进来），结果：

```
cleared [{'pid': 56560, 'closed': False, 'terminated': True}], opened in pid 51916
```

`closed: False` 是重点——WM_CLOSE 发出去没人接（没窗口），正是必须强杀的证据；
强杀后进程确实消失，随后文件在**新** pid 里打开，第一次就成功。

（真实的无窗口 KingDraw 没法按需造出来，所以用替身进程走同一条分支；今天那次 E05
就是这条分支的「修前」证据。）

### 本轮数字

| 项 | 结果 |
|---|---|
| 电荷 | 不显示 → `O-` / `NH3+` |
| 无窗口残留 | 卡满 25 秒后失败 → 启动前清掉，一次成功 |
| kd_save | 9 total（8 passed 1 skipped），15.0s |


## 2026-10-29 · 第十四轮：.king 装不下立体键，那就别假装装得下

### 复现

同一份 L-丙氨酸 molfile，两条路导出：

| 路径 | 尺寸 | 墨迹 | 图上有什么 |
|---|---|---|---|
| molfile 直接导出 | 384x272 | 12918 | 虚楔形 + 元素颜色 |
| 经 `kd save` 转 .king 再导出 | 396x300 | 8664 | **平的**，楔形没了 |

手性中心丢了，而图上看起来完全正常——这正是最糟的一种错。

### 找字段（三组对照）

1. 键行的第 5 个字段（`align`）：0–5 逐个试，尺寸与墨迹几乎不动（8613–8664），
   只有抗锯齿级别的差别，**不是立体**。
2. 键的 `type`：3 画出三键、4 画出双线，6/7 画出**两条平行线**（也不是楔形），
   8 是单线中间断一下。**没有哪个值画出楔形。**
3. 读侧：`supKingToJson` 对一根键只报 `index/layerIndex/colorHex/type/align/
   startNode/endNode`，**没有别的字段可用**；节点侧只有一个空的 `propertys` 列表。

再加上一条结构性证据：DLL 里没有 mol→king 的转换器（`supKingToJson`、`kingCleanUp`、
`molToSmiles`、`smilesToMol`…就是全部），这个 .king 文本一直是本工具手写的，
没有任何上游实现可以照抄。

结论：**这个 .king 方言不表达立体化学。**

### 修复：不静默

格式装不下可以接受，装不下还不说不行。`kd save` 现在：

1. 数出源文件里有几根带立体的键（V2000 键行第 4 列）；V3000 用 `CFG=` 属性，
   两种方言都要认——这里踩过一个坑：V3000 的键行只有 4 个数字，按 5 个匹配会永远数到 0；
2. 命中就 `degraded=True` + `degrade_reason` 写明丢了几根、怎么办；
3. 再追加一条 warning（人读的通道上显示成 `! this .king opens flat: 1 stereo bond(s) ...`）。

验证（`test_stereo_is_reported_as_not_carried`）：手写一个带 `6` 标记的 molblock，
`stereo_bonds` 数到 1、去掉标记数到 0；`save_as_king` 之后 `degraded=True`、
`stereo_bonds_not_carried=1`、warning 里有 `opens flat`。

顺带核过：葡萄糖（5 个立体中心）数到 5，苯数到 0，V2000 与 V3000 都数对。

README 的「已知限制」也补了这一条——这是用户该知道的事，不该只躺在 PROGRESS 里。

### 本轮数字

| 项 | 结果 |
|---|---|
| 手性结构经 .king | 静默变平 → 报 degraded + 警告 |
| 立体键计数 | V2000 / V3000 都对（5 / 0 / 1 三个样本）|
| kd_save | 10 total（9 passed 1 skipped），14.8s |


## 2026-10-29 · 第十五轮：同一分子两条路，长出一张不一样的图

### 一、右边的 171 像素死白，和左边贴死的那条键

上一轮记过：`kd export` 会把结构裁到只剩墨迹，但「补边距」是**往外扩框再夹到画布边界**——
墨迹贴着 KingDraw 自己的画布时，那一侧根本没有纸可以扩，于是回来还是 0 px。

改成：裁出墨迹 → **贴到一块新画布上**，四边各留同样的边距。跟画布大小无关了。

| 分子 | 修前 | 修后（L/T/R/B） |
|---|---|---|
| 乙酸根 | 8 / 9 / 171 / 152 | 14 / 14 / 15 / 14 |
| 咖啡因 | **0** / 7 / 14 / 10 | 15 / 15 / 15 / 15 |
| 葡萄糖 | 8 / 12 / 16 / 13 | 16 / 16 / 16 / 16 |

`test_kd_export` 新增断言：四边最小边距 ≥ 4 px，且最大值与最小值相差 ≤ 2 px。

### 二、颜色：同一个分子，两个通道画出两个样子

把 L-丙氨酸 molfile 直接交给 KingDraw 导出，氧是红的、氮是蓝的；同一份结构经
`kd save` 转成 .king 再导出，**全是黑的**。颜色是写在每个原子上的（`colorHex`），
我们一直写 `#ff000000`。

对照实验（咖啡因，数像素）：

| 写法 | 有色像素 | 结论 |
|---|---|---|
| 基线（全黑） | 0 | 灰图 |
| N → `#ff0000ff` | 蓝像素 1192 | 生效 |
| O → `#ffff0000` | 红像素 408 | 生效 |

那就按 KingDraw 自己的主题写：N 蓝、O 红、S 黄、P 橙、卤素绿/棕/紫，碳保持黑。
修后葡萄糖五个 HO/OH 全红、咖啡因四个 N 全蓝。

断言落在两处：`.king` 里氧原子行必须带 `#ffff0000`、碳必须带 `#ff000000`；
导出图上必须有 > 20 个有色像素（每个样本都含氧或氮）。

### 三、顺手把文档字符串改成真的

`kd_save` 顶上的格式说明还停留在「原子行没有 label 属性」的年代——那一整段现在
是错的。改成实测出来的三条：`Label` 是要画的文本、电荷写进标签、颜色按元素给；
外加一条「装不下立体键」。注释写错比没写更费人。

### 本轮数字

| 项 | 结果 |
|---|---|
| 咖啡因左边距 | 0 → 15 px |
| 四边边距一致性 | 差 171 px → 差 ≤ 1 px |
| 有色像素（葡萄糖） | 0 → 2515 |
| kd_save / kd_export | 10 total（9+1skt）/ 4 passed |


## 2026-10-29 · 第十六轮：新用户 clone 下来，第一条命令就被告知去跑一个不存在的文件

### 复现

把仓库 clone 到干净目录（153 个文件，没有 `runtime/`——它是 install.ps1 下载的，不进仓库），
跑第一条 KingDraw 命令：

```
$ python bin/cli.py kd mol 'CCO' --out x.mol
[E04] KingDraw core library is x86 but this interpreter is x64
  │ fix    : Run with the bundled 32-bit runtime: runtime/py32/python.exe
```

**那个文件不在 clone 里。** 提示让读者去跑一个他手上没有的东西，而这正是新用户见到的
第一句话。`cd` 通道没事（它走 COM，不需要 32 位），所以只坏一半，更容易被当成偶发。

### 修复

把「该用哪个解释器」从常量变成函数（`models.bitness_hint()`），看磁盘上到底有没有那个解释器：

- **有** `runtime/py32/python.exe`：提示保持原样，
  `Run with the bundled 32-bit runtime: runtime/py32/python.exe`。
- **没有**（刚 clone）：改成让它去取，
  `This checkout has no 32-bit runtime yet: run install.ps1 (or python `
  `scripts/fetch_runtime.py) to fetch it, or set CHEMTOOL_PYTHON32 to any 32-bit python.exe`。

同一句话原来散在四处（`models.ERROR_TEXT`、`kd_native`、`doctor/kd.py`、`kd_save`），现在统一
从一个函数出，键名 `CHEMTOOL_PYTHON32` 也从 `models` 导出，不再各写一遍。

### 验证

1. 单元：新增 `test_14_a_checkout_without_the_runtime_says_how_to_get_it`——空目录必须提到
   `install.ps1` 与 `CHEMTOOL_PYTHON32` 且**不能**提那个不存在的路径；放一个假的 py32 进去后
   反过来。合同套件 15 tests OK。
2. 端到端：把修好的提交 clone 到干净目录，重跑同一命令，看提示变成新文案。
3. 本机（runtime 在）提示保持原样——不给老用户制造噪音。

### 二、干净 clone 里跑测试：两个套件是红的

跑 `python test/run_all.py`：**9 passed, 2 failed, 7 skipped**。红的两个是 `test_cd_adapter`
与 `test_cd_cli_mcp`，都是这句：

```
assert data['staged'] is True, 'a Chinese path must go through ASCII staging'
```

它们把文件写进 `test/out`，而 `test/out` 只有**因为仓库本身在中文路径下**才是中文路径。
clone 到 `C:\src\...` 就没有中文了，于是「没有触发暂存」——测试其实在断言**仓库的位置**，
不是在测代码。换句话说：这条重要的保护（SaveAs 遇中文路径静默不写）只在作者那台机器上被测。

修法：路径由测试自己造——写进 `test/out/导出中文路径/`。中文是测试的前提，不该是环境的巧合。
修后同一份 clone：`test_cd_adapter` 17 passed、`test_cd_cli_mcp` 11 passed。

### 三、`(degraded: None)`：Python 的 None 漏进了人读输出

同一个干净 clone 还让 `test_examples` 变红，因为示例脚本印了：

```
phenol    agree=True
          kingdraw  -
          (degraded: None)   ← 这一行
```

原因：KingDraw 那条腿没跑起来（没有 32 位运行时），结果标了 `degraded=True` 但没有
`degrade_reason`，而脚本直接 `% (data.get('degrade_reason'))`。主仓库里跑不出来，因为那边
这条腿起得来。

修：没有理由就别印 `None`，改成说人话——`(degraded: a channel did not contribute)`。
`cli.py` 里同样位置（`degraded: ` 后面接空串）也补成 `no reason recorded`。

（`test_03` 里那条 `assertNotIn('None', blob)` 本来就在守这件事，只是主仓库永远走不到那条分支。
这条断言现在有意义了。）

### 四、这一轮的结论

| 视角 | 修前 | 修后 |
|---|---|---|
| 新 clone 首条命令 | 指向不存在的路径 | 给出取回它的办法 |
| 新 clone 跑全量 | 9 passed / 2 failed / 7 skipped | **11 passed / 0 failed / 7 skipped** |
| 中文路径测试 | 依赖仓库位置 | 自己造中文目录 |
| degraded 无理由 | 印 `None` | 印人话 |
### 这一轮记下的一件事

「clone 下来能不能跑」不是文档问题，是**第一条命令的报错文案**问题。README 里写清楚了
要跑 install.ps1，但没人会在报错之后回去翻 README——他只会照着 `fix:` 那一行做。

### 本轮数字

| 项 | 结果 |
|---|---|
| 新 clone 首条命令 | 指向不存在的路径 → 给出取回它的办法 |
| 提示出处 | 4 处硬编码 → 1 个函数 |
| 合同套件 | 14 → 15 tests，OK |


## 2026-10-29 · 第十七轮：新用户那条路，真的走通了

上一轮修的是「报错别指向不存在的文件」。这一轮把 README 让新用户走的那条路**整条跑完**：
干净 clone → `install.ps1` → 全量测试。

### 复现（走一遍）

```
$ git clone <repo> C:\Users\...\Temp\chemdraw_fresh4     # 153 个文件，没有 runtime/
$ powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1

chem-draw-tool 安装
正在安装依赖 (rdkit / pillow / pywin32) ...
正在下载 32 位 Python 运行时 (约 10 MB) ...
  archive sha256: daf24de7fb3b173e94e56a201d3f38dfedebbdc7ed1925f7aeb8ed588e2b4189
  unpacked into ...\chemdraw_fresh4\runtime\py32

汇总
[ok]  python            py -3.11 (64 位) — 3.11.9
[ok]  dependencies      rdkit / pillow / pywin32
[ok]  kingdraw-runtime  runtime\py32\python.exe
[ok]  chemdraw          available
[ok]  kingdraw          available
```

五步全 ok，包括真的把 10 MB 运行时下下来、解开、两条通道各体检一次。

### 装完之后这个 clone 能不能干活

```
$ runtime/py32/python.exe bin/cli.py kd mol 'c1ccccc1O' --out test/clone_phenol.mol
  bytes  : 497
$ runtime/py32/python.exe bin/cli.py kd save test/clone_phenol.mol \
      --out test/clone_phenol.king
  waited_s                : 0.063
```

KingDraw 两条命令在 clone 里直接跑通。同时验证了上一轮那条修复的**另一半**：运行时一到位，
提示自动变回 `Run with the bundled 32-bit runtime: runtime/py32/python.exe`——
它不是永远挂一段 download 说明，而是看磁盘上有什么。

### 全量

```
$ python test/run_all.py
18 passed, 0 failed, 0 skipped in 215.1s
```

干净 clone、装完、一条不跳。仓库内是 18 passed / ~184s，差的那 30 秒是新目录没有文件缓存。

### 这一轮的意义

「clone 下来能跑」以前只是 README 上的一句话，现在是跑出来的：**153 个文件 → 5 个 ok → 18/18**。
这条链路里任何一个环节（依赖、运行时下载、sha256、解包、两条体检）出问题，这张表都会是红的。


## 2026-10-29 · 第十八轮：插件到底有没有被宿主跑起来

前面每轮验的都是 CLI。插件是另一条交付面：它把 20 条 CLI 命令包成 14 个 DSH 工具。
之前只做到「模块能被 import」「用桩 ctx 调 apply() 注册了 14 个工具」——
**宿主有没有真的跑它，一直是未验的**。

### 怎么验才算数

按 skill 里的三重验证做，只跳过需要退出 Electron 的那一步（会话内退不出宿主）：

```
(1) dsh plugin --profile _probe add "link:<repo>/dsh-plugin"
    → Done in 257ms, 1 package；peer 警告符合预期（@deepseek-ai/* 由宿主提供）
(2) dsh --profile _probe --dump-config-schema
    → rc=0，stderr 0 字节，600161 字节 composed schema 里出现 dsh-chem-draw-tool
(3) apply() 里加了个诊断钩子，起真实例读它
    → {"applied":true,"tools":14,"node":"v24.21.0"}
```

第 (2) 步已经把「接线成功但不加载」这类问题排掉了（`Cannot find package` 会在这一步炸）。
但那是 import，不是 apply。第 (3) 步才是：**插件自己的最后一行代码被宿主执行了**。

### 诊断钩子

`DSH_CHEM_DRAW_SMOKE=<file>` 让 `apply()` 结尾追加一行 JSON（应用成功 / 注册了哪些工具 / node 版本），
不设时**零行为**。这不是为测试而生的玩具：`装了没反应` 最难取证的就是「宿主到底跑没跑它」——
界面里看不到，日志里也没有。现在一条环境变量就能回答。

14 个工具的名字也一起写进了记录（`chem_doctor` … `kingdraw_open`），和
`test/test_plugin_tools.mjs` 里那条 `tool count is 14` 互相印证：一个验桩、一个验真实宿主。

### 一次自找的破坏（以及怎么救回来）

写完 `~/.dsh/research/LOG.md` 时我犯了个低级错误：只读了前 3 行就整篇 `write`，
**把之前几十条工程日志覆盖没了**。

救法：`~/.dsh/storages/session_projcache` 里各会话的转录还留着原文，解析 JSON 后按
`## [BEGIN] … ## [END]` 抓块、按 (时间戳, 任务名) 去重、取最长且首尾完整的副本，
重建出 **41 条、48 KB、BEGIN/END 配平**的日志；三条只剩残缺副本的（`$T` 占位那几条）
在文末的恢复注记里点名列不出来，而不是假装完整。

顺手把这条教训写进日志本身：**覆盖一个只读过一部分的文件 = 数据丢失**；追加用 `>>`。

### 本轮数字

| 项 | 结果 |
|---|---|
| 宿主真实激活 | 未验 → applied:true, 14 tools, node v24.21.0 |
| 一次性 profile | 建 → 验 → 删（10 文件 / 22 KB，junction 先删）|
| research 目录 | LOG.md + dsh-guard.mjs，`clean → ok:true` |
| 日志 | 覆盖丢失 → 从会话缓存恢复 41 条，BEGIN/END 配平 |

## 2026-10-29 · 第十九轮：两条命令同时跑会怎样

前十八轮都是「一条命令，跑对了吗」。这一轮问的是：**两条同时跑会怎样**。

### 复现

两条 `kd export` 同时启动，各自结构不同（咖啡因 / 葡萄糖）：

```
平行  caffeine rc=1 122.5s img=None  failure=KingDraw was launched with the
                                          file but never confirmed it opened
平行  glucose  rc=1 122.5s img=None  failure=同上
%TEMP% 残留 kd_export_*: 44 个
```

两个都等满超时、一张图没出。逐条跑同样的两条：16.3 s 和 16.3 s，都成功。
原因是 KingDraw 单实例：第二次启动把文件转交给已有窗口，于是两个进程都在等一个
永远不会出现的「自己的」文档。

### 修法

GUI 操作串行化——`core/chemdraw_tool/applock.py`，命名互斥体（`Local\\chem-draw-tool.kingdraw`）：

- 互斥体而非锁文件：持有者崩溃时内核自动释放，不会把后面所有调用卡死到有人手工清理。
- 同线程可重入：`kd export` 持锁后再调 `kd open`，内层不能等外层。
- 等待有上限，超时给一句话（`CHEMTOOL_APP_LOCK_TIMEOUT` 可调）。
- 直接路径（本进程驱动窗口）在 `export_as_image` 里持锁；桥接路径由 64 位助手自己持锁
  （外层持锁会和助手互相等，所以特意分开）。

顺手修了 `shutil.rmtree(..., ignore_errors=True)`：那 44 个目录就是它吞掉的——KingDraw 刚写完
`.kdx` 还握着文件，删除失败，静默使其不可见。现在重试 ~4 s，仍失败就往 stderr 写一行。

### 验证

| 场景 | 修前 | 修后 |
|---|---|---|
| 两条 `kd export` 同时 | 122.5 s 双双失败，0 图 | 16.5 s / 32.6 s 依次成功，图与串行逐字节同尺寸 |
| 桥接模式同时 | 未测 | 33.4 s / 33.4 s 依次成功 |
| `%TEMP%` 残留 | 44 | 0 |

新增 `test/test_applock.py`（5 条）：跨进程真的互斥、等待有界且有话说、同线程嵌套不死锁、
持有者被 kill 后下一次调用不被卡死（WAIT_ABANDONED）、环境变量预算生效。全套 2.7 s。

### 没改的

ChemDraw 侧**没加锁**：两条 `cd export`、两条 `cd read --smiles` 同时跑，结果与逐个跑一致
（图逐字节相同、元素计数各自正确），COM 给每个进程自己的文档。没测出问题就不加没验证过的
串行化——这是刻意的取舍，不是遗漏。

## 2026-10-29 · 第二十轮：你自己开着窗口的时候

上一轮修的是「两条命令互抢」。这一轮问：**用户手里已经开着 KingDraw 时会怎样**——
最怕的是把人家正在编辑的文档顶掉。

### 先测会不会毁人家的东西

先 `kd open` 打开咖啡因并留在窗口里，再 `kd export` 葡萄糖：

```
用户窗口 pid=93776, UIA 文档名: ['readback_caffeine.mol']
kd export 葡萄糖 -> rc=0, 454x300, 用的也是 pid 93776
导出后 UIA 文档名: ['readback_caffeine.mol']   # 还是他自己那份
```

同一个进程、新文档开着、导完窗口里仍是用户的文档。工具不关用户窗口（`close_app` 只关
自己启动的实例），也不替换用户文档。这条可以放心写进 README。

### 但发现一个说谎的开关

`--no-reuse` 的帮助写着「不要附加到已在运行的 KingDraw 实例」，而实现里 `reuse` 只被
写进 `reuse_requested` 字段，**没有任何分支读它**。实测：窗口开着时 `kd open B --no-reuse`
与不带该开关完全一样（pid 不变、文件被转交给同一窗口）。

单实例转发绕不过去——真要「另开一个」，只能先关掉用户窗口，那是更坏的行为。所以这里
不改行为，改**承诺**：

- 结果里加 `reuse_honored`（`import` 时无实例 → `true`；有实例却要求不复用 → `false`）；
- 没兑现时附一条警告，说明文件去了哪个窗口、用户的东西没被动、也没被关；
- CLI 帮助改成说实话：请求全新实例，做不到，结果里会写 `reuse_honored: false`。

### 验证

```
A 无实例 + --no-reuse  : reuse_honored=True  warnings=0
B 有实例 + --no-reuse  : reuse_honored=False warnings=2
                          警告原文: "--no-reuse could not be honoured: KingDraw is a
                          single-instance application, so the file went to the window
                          that was already open (pid 93776). Nothing of yours was
                          closed and no document of yours was replaced."
C 有实例 + 默认        : reuse_requested=True reuse_honored=True
```

`test_kd_open.py` 加一条 `test_no_reuse_is_reported_instead_of_granted`（并把「首次启动
时 `reuse_honored` 为 true」写进原有断言）：10 passed / 0 failed / 22.7 s。

顺手记一笔判断标准：**空转的开关比缺功能更坏**——缺功能时报错，空转时用户以为自己被保护了。

## 2026-10-29 · 第二十一轮：会改文档的那条命令

上一轮问 KingDraw（只读导出）。这一轮问 ChemDraw，因为 `cd draw` 是**会改文档**的命令：
如果你手里开着自己的 ChemDraw 文档，它会不会画进你那一页？

### 证据从哪来

第一次尝试是数 `Documents.Count`，结果**一直是 0**（应用明明有一页 14 个原子的图）。
这台 build 上 COM 的这个属性不可信——和它已经把 `document.Close()` 记成 no-op 是同一类
毛病。差点就把它当结论写进 README。

换成两个能测的量：

- `draw_smiles` 结果里的 `atoms_before`：如果画进已有页面，这个数就该 > 0；
- 通道自己持有的 `_doc` 句柄：别的调用方关掉它的文档后，这一页的原子数变没变。

### 结果

```
A: 应用里开着一页 13 个原子（阿司匹林）
B: 另一个通道画苯酚 -> atoms_before=0, atoms_after=7, roundtrip=exact
B 关闭自己的文档后, A 那页原子数 = 13   # 没被写入，也没被清空
```

原因是实现里用的是 `Documents.Add()`，不是 `ActiveDocument`。这条已经是既有的正确做法，
但它一直**没有测试钉住**——所以我补了
`test_17_a_second_caller_does_not_draw_into_the_first_ones_page`：断言 `atoms_before == 0`
与关闭后第一页原子数不变。哪天有人把实现换成 `ActiveDocument`（代码更短、看起来更自然），
这条会挂。

顺便记一个实测到的边界：`cd read` 不带 `--smiles` 时，新进程读不到已开的页面，返回
`the drawing is empty`——已写进 README 的已知限制。

### 本轮数字

| 项 | 结果 |
|---|---|
| test_cd_adapter | 17 → **18 passed, 0 failed** |
| `Documents.Count` | 不可信（恒 0），不作为证据 |
| 第二调用方 vs 用户页 | atoms_before=0；关闭后用户页仍 13 个原子 |

## 2026-10-29 · 第二十二轮：终端窄下来的时候

前面几轮问的是「真实使用」，这一轮把终端真的压窄：40 / 60 / 80 / 120 列各跑十条命令，
逐行量显示宽度。

### 复现

```
COLUMNS=40  kd doctor（子命令拼错）-> 172 列的一行
chem-draw-tool kd: error: argument <command>: invalid choice: 'doctor'
  (choose from 'mol', 'smiles', 'formula', 'king', 'match', 'to3d', 'layout', ...)
COLUMNS=60  crosscheck --help       -> 一行 64 列
```

其余九条命令（doctor / identity / capabilities / 缺文件 / 坏 SMILES / 各种 --help）在四个宽度下
全部 0 溢出——表格、失败块、JSON 都对。所以问题不在渲染层，**在 argparse 自己那条路**：
`parser.error()` 把消息整行打印，从不换行。

### 为什么既有测试没抓到

`test_presentation.py` 里已经有 `test_no_human_line_is_wider_than_the_terminal_at_40` 和
`test_every_leaf_help_fits_forty_columns`——但它们喂的都是 `cli._render*` 的 payload，
**从没跑过 parser 的错误路径**。渲染层被测穿了，入口层没人看。补测试比修代码更重要。

### 修法

- `_WidthParser`：`error()` 走 `_wrap()`；宽度不够时前缀单独一行、正文缩进两列
  （40 列下 23 列前缀只剩 17 列，两词都放不下，会变成一行一个词）；
- `_WidthFormatter`：`usage`/`help` 用同一个宽度数，不再让 argparse 自己算；
- `print_usage()` 也过 `_wrap()`：32 列时 argparse 的 25 列悬挂缩进本身就放不下
  （实测 34 列 > 32 列预算），并保留 `usage: ` 悬挂以免续行跑到最左边。

### 验证

```
32 列: usage 正常悬挂，error 三行以内，--help 最长行 32    ← 恰好等于预算
40/60/80/120 列: 四条错误路径 + 十条正常命令 + 三层 --help，0 溢出
test_presentation: 21 -> 22 passed, 0 failed
```

### 一个不修的

SMILES 拼错时 RDKit 自己往 stderr 打 4–5 行（一行 93 列）。那是第三方 logger 直写，
终端软换行不会错位也不会丢字；我们的 `--json` 里 `detail` 是整理过的版本。把它改成捕获再
重排，等于替第三方决定怎么表达它自己的诊断——不值。写进 README 说明，而不是悄悄吞掉。

## 2026-10-29 · 第二十三轮：跑完全套之后，桌面留下什么

每轮都在跑测试，那跑完之后机器上剩什么？实测一轮全量：进程 0 个（干净），但 `%TEMP%` 里
留下 6 个 `kd_export_*` 目录。

### 定位

清空后逐个套件跑，只有 `test_misuse` 从 0 变 1 —— 正是那条「export 跑到第 4 秒 SIGTERM」的
测试。Windows 的 `terminate()` 是 TerminateProcess，**被杀掉的进程不会执行 finally**，所以那个
目录根本没有机会被删。这不是漏写清理，是这一层的物理极限。

顺带确认：单独跑 `test_kd_export` 是 0 残留——上一轮加的「重试删除」是有效的，剩下这一个
完全来自「进程被处死」。

### 修法：下一次运行给上一次收尸

`kd export` 拿到应用锁**之后**扫一遍 `%TEMP%`，删掉超过 5 分钟的 `kd_export_*` 目录。
放在锁内是因为那时不可能有别的 export 在跑（锁保证），年龄门槛只是第二道保险。带 `.kdx` 的
目录跳过——那是 `--keep-kdx` 特意留下的证物。删掉的会写进 warning：

```
removed 1 temporary folder(s) an interrupted run could not clean up: kd_export_dead_probe
```

### 验证

| 项 | 结果 |
|---|---|
| 单元：20 分钟前的空目录 + 新建目录 | 旧的删掉，新的留着 |
| 单元：旧目录里放一个 `.kdx` | 原样保留 |
| 端到端：造一个 20 分钟前的尸骸，跑真 export | 尸骸消失并出现在 warning 里，归档目录保留 |

test_kd_export 4 → 5 passed。

### 值得记的一句

「崩溃后自清理」不能靠崩溃的那个进程，只能靠**下一个**进程。这条在 Windows 上尤其硬：
没有 signal handler 能救回一个被 TerminateProcess 的进程，只有事后打扫。

## 2026-10-29 · 第二十四轮：陌生人打开这个仓库

换个视角：一个从没见过这个项目的人，clone 下来会先做什么？大概三件事——看 README、试着
`pip install .`、看有没有 CI。三件都实测了一遍。

### 一、`pip install .` 到底行不行

`pyproject.toml` 里写着 `[project.scripts] chemdraw-tool = chemdraw_tool.cli:main`，那就得验。
用 `--no-deps --target` 装到一个无关目录，再从 `/tmp` 调用：

```
identity CCO   -> LFQSCWFLJHTTHZ-UHFFFAOYSA-N   （正常）
doctor kd      -> E04 + 「This checkout has no 32-bit runtime yet: run install.ps1 ...」
```

前半是好消息。后半是个**不诚实的提示**：装好的包里根本没有 `install.ps1`，却叫用户去跑它——
和当初「新克隆叫你跑 runtime/py32/python.exe」是同一类错误，只是换了个方向。

修法：`bitness_hint()` 先看根目录有没有 `install.ps1`，有才给检出目录那句话；没有就给装机版
的话：「这个 build 没有 32 位运行时，把 CHEMTOOL_PYTHON32 指向一个 32 位 python.exe（KingDraw
是 x86 DLL，64 位解释器加载不了）」。实测装机版现在输出后者。

### 二、CI

仓库里没有 `.github/`，也就是说 GitHub 上会显示「没有检查」。补一个 `ci.yml`：仓库卫生、文档
渲染、所有不需要外部应用的套件、打包承诺，四步。runner 上没有 ChemDraw / KingDraw——这正是
设计：`run_all.py` 会探测并报 SKIP，而不是失败。

顺手发现一个坑：`pip install .` 会在检出目录里留一个 `build/`，`git add -A` 一口气把 9.6k 行
的 `core/` 副本加进了索引。已把 `build/`、`dist/` 写进 `.gitignore`，并加 `.gitattributes`
（Windows 优先的仓库，Linux 上 clone 不能拿到 CRLF 的 shell 脚本）。

### 三、根目录长什么样

18 个顶层条目，`tests/`、`dsh/`、`mcp/`、`runtime/` 这些看着可疑的目录**都没被跟踪**；真正
跟着走的只有 `core/ bin/ test/ docs/ examples/ tools/ scripts/ dsh-plugin/` 加几个文档。
陌生人看到的是这个形状，干净。

### 四、这条 CI 真跑一遍

往 `git clone` 出来的干净目录里跑 ci.yml 的全部四步（干净克隆没有 `runtime/`，与 runner 一致）：

```
preflight        -> tracked files: 157 | checks: 11 | failures: 0
md_render_check  -> 0 finding(s)
run_all          -> 12 passed, 0 failed, 7 skipped in 73.0s
pip --target .   -> identity CCO -> LFQSCWFLJHTTHZ-UHFFFAOYSA-N, exit 0
```

7 个 SKIP 全是需要 ChemDraw / KingDraw / 32 位运行时的套件，报的是
`the py32 interpreter is not available` 这类具体原因，不是静默跳过。

## 2026-10-29 · 第二十五轮：路径长一点，工具就开始撒谎

挑了个 Windows 特有的老坑试水：超过 260 字符的路径。本来是打算「验一遍、写进文档」就完事，
结果挖出一个真 bug，还顺出一个缺失的命令。

### 一、298 字符的路径：窗口起来了，文档没有

同一个苯酚 `.mol`，两个位置：

```
62 字符  -> document_confirmed=True   uia names=['short_caffeine.mol']
           verified_by=['window-title:app-name', 'uia:document-tab']
298 字符 -> document_confirmed=False  uia names=[]
           verified_by=[..., 'uia:no-document-tab']
           ok=True  degraded=False      <- 这是谎
```

KingDraw 把路径直接交给 Win32，过了上限就安静地不加载，什么错也不报；而我们的判定是「窗口标题
匹配就算成功」，于是报了干净的 ok。对一个以「不撒谎」为卖点的工具，这是最糟糕的一类错。

修法两条：

1. **绕开**：超过 250 字符的输入先复制到临时短路径再交给应用（输出侧本来就这么做 `SaveAs`）。
   结果里 `staged_from` = 你要的路径，`opened_path` = 实际打开的那份，附一条说明。实测冷启动
   下 `document_confirmed=True`、文档标签就是 `far_away.mol`——暂存的那份确实被应用加载了。
2. **说实话**：拿不到文档标签就不再算成功。`degraded=true`，理由分两种写法——根本读不到标签，
   和读到了但名字不是你要的那个。

临时副本不能立刻删：应用还开着那份文档时删掉，等于删了它手里拿着的文件。所以留 5 分钟给下一次
运行收（和 `kd export` 的残骸同规矩）。

### 二、顺手挖出第二个：窗口里已有文档时，转交的文件标签不更新

修完一半先跑套件，长路径那条测试却挂在「名字对不上」。追下去发现是另一件事：窗口里已有
`phenol.mol` 时再转交 `far_away.mol`，应用**开出了第二个标签，但两个标签都还写着 `phenol.mol`**。
短路径同样如此（`first_file.mol` → 再转交 `second_file.mol`，标签仍是 `first_file.mol`），
冷启动再开 `second_file.mol` 就正常了。

所以「名字对不上」不等于「文件没打开」——这两种情况我起先当成一种，写了个会误导人的理由
（说「读不到文档标签」，其实读到了）。现在分开写：`the window reports document 'x', not 'y' ...`。

也顺手做了对照：`kd export` 连续导出两个不同分子，图**不一样**（37269 / 35507 字节）——因为
导出走的是 `reuse=False` 的冷路径，所以导出没被这个坑波及。

### 三、多了一个命令：`kd close`

「请关掉那个窗口再开」这种提示，在这个工具里原本没有出路——没有关闭命令。补上：

```
chemdraw-tool kd close           # 工具能看到的每个窗口
chemdraw-tool kd close --pid N   # 只关一个
```

走 `WM_CLOSE` 不杀进程；有未保存内容时应用会弹自己的对话框，窗口留着不关，命令报 E05 并说明
对话框在等你。实测空跑：`ok: true`、`targets: []`、附 `no KingDraw window was running`。

### 四、套件

`test_kd_open` 从 10 条变 11 条，41.3 s 超了原来 40 s 的预算——长路径那条要关应用、冷开、
热开、恢复现场，等于多两次启动。预算提到 70 s，并在注释里写明为什么。全套另跑（见下）。

## 2026-10-29 · 第二十六轮：中文路径，与两个信封缺口

中文路径是中文用户第一件会撞的事。长路径那轮之后顺手验了它，结论是好消息，但也逼出两个
信封不一致。

### 一、中文路径全通（实测）

```
kd open  测试目录/苯酚.mol  -> ok=True  document_confirmed=True  uia names=['苯酚.mol']
kd export 同一份            -> ok=True  37269 字节
kd save   同一份            -> ok=True  344 字节 .king
cd export 测试目录/结构.cdxml -> ok=True 4137 字节 + 「经由 ASCII 暂存目录」说明
cd figure 测试目录/图2.png   -> ok=True 111521 字节
```

ChemDraw 的 `SaveAs` 静默无视非 ASCII 路径（前几轮已知），所以导出走 ASCII 暂存再搬回，并明说；
KingDraw 侧不需要。

### 二、`cd export --format mol` 会去读 DPI 标签

实测输出：`ok: true` 旁边挂着 `the dpi tag could not be read: ... UnidentifiedImageError`。
一份 mol 文件当然没有 DPI 标签——这条提示读起来像导出失败了。改成只有位图格式才去读标签
（`RASTER_EXTENSIONS`），结构化格式直接 `dpi_tag: null`、无提示。

新测试 `test_18_a_structural_export_asks_for_no_dpi_tag` 连测 mol / cdxml / svg 三种格式：
文件真写出来（1307 / 5483 / 4012 字节），`dpi_tag` 与 `dpi_tag_error` 都是 None，警告里不许出现
那句话。

### 三、`cd draw --out` 写了文件却不报路径

实测 `cd draw 'c1ccccc1O' --out 图.png`：PNG 真在（8762 字节），但顶层 `path` 是 null——路径只
藏在嵌套的 `data['export']['data']['path']` 里。`cd export` 与 `kd export` 都在顶层报 `path`，
同一套键名应当处处一致，否则脚本得按命令分叉。`cd draw` 与 `cd modify` 都补上顶层
`path` / `bytes` / `format`。

测试：`test_01_cli_draw_writes_a_png` 现在断言顶层三键与嵌套那份逐一对上（顺带发现
`format` 在这条路径上是个格式描述字典而不是字符串，所以断言写成「与嵌套一致」而不是「等于
'png'」）。

### 四、我自己踩的两个参数坑（记下来，免得下次又踩）

`cd draw` 的 SMILES 是**位置参数**（`cd draw 'CCO' --out x.png`），写成 `--smiles` 是 argparse
错误 rc=2；`cd read` 根本不收文件路径，它读的是应用里当前那页。这两个都是我探针写错，不是工具
的问题——但说明文档里「cd read 读的是当前页」这句还得再显眼些，已写进 README。

### 五、结果

`test_cd_adapter` 18 → 19 条，`test_cd_cli_mcp` 11 条全过。

## 2026-10-29 · 第二十七轮：新命令的边角，与环境变量设错

上一轮刚加的 `kd close` 还没被人乱用过——那就自己乱用一遍。顺手也试了「环境变量填错」这类
最常见的自伤配置。

### 一、`kd close --pid 999999`：光秃秃的 ok

实测：`rc=0, ok=true`，一句提示都没有，`results` 里却是 `closed: true`。原因是 `close_app` 对
一个不在 `list_pids()` 里的 pid 直接返回 `already_gone: true`（本来也没什么可失败的）——这层
意义是对的，但命令层把 `already_gone` 吞了，读起来就成了「我关掉了 pid 999999」。

现在：`ok: true` + 一条 `no process with pid 999999 was running: there was nothing to close`，
`results` 里 `already_gone: true` 原样保留。

### 二、`--pid 0` 会关掉所有窗口

我写的是 `targets = [args.pid] if args.pid else kd_open.list_pids()`。Python 里 0 是假值，于是
`--pid 0` 悄悄变成了「关掉工具能看到的每一个窗口」——一个明确的参数被替换成完全不同的动作，
正是这个项目一直在修的那类问题。改成 `args.pid is not None`，并且测试钉住：`--pid 0` 的
`targets` 必须就是 `[0]`。

### 三、`CHEMTOOL_PYTHON32` 填错时没人说

`find_python32()` 会跳过不是文件的条目、继续找下一个（这是对的，bundled 运行时能用就没事）。
但什么都没找到时，提示只说「这个 build 没有 32 位运行时」——用户会去怀疑机器，而真正要改的
是他自己设的那一行。

新增 `models.unusable_python32_env()`，在提示后面点名：
`note: CHEMTOOL_PYTHON32 is set to …\typo.exe, which is not a file`。指向真实文件时不加这句。

### 四、测试

- `test_contract_sync` 15 → 16 条（`test_15_an_unusable_env_variable_is_named`）。
- `test_misuse` 14 → 15 条（`test_close_reports_that_nothing_was_there`，两条断言都是纯 CLI、
  不需要任何外部应用）。

### 五、另一个发现：我的探针把 `kd close` 跑在 py64 上也能过

两条新断言都跑在 `py64` 上，说明 `kd close` 不依赖 32 位运行时（它只是往窗口投 `WM_CLOSE`）。
这是好事：谁都能用它关窗口，不需要为了关一个窗口去凑 32 位解释器。

## 2026-10-29 · 第二十八轮：doctor 的退出码与它自己的注释矛盾

想给陌生人看「第一条命令长什么样」，顺手量了每条命令的耗时，结果发现 `doctor` 的退出码
和它自己的 docstring 打架。

### 一、`doctor` 永远返回 1

`_doctor_status()` 的注释写得很清楚：两条通道只要一条能用就算健康（64 位够不着 KingDraw，
32 位够不着 ChemDraw，取最坏会让健康安装从两边都报失败）。但打印循环里还有一句
`rc = max(rc, _emit(p, False))`——任何一条通道失败就把整体拉到 1。实测：

```
py32 doctor -> 1     py64 doctor -> 1        （注释说应该是 0）
py32 doctor kd -> 0  py64 doctor cd -> 0     （单通道是对的）
```

也就是说在这台机器上 `doctor` **永远**返回 1，脚本拿它当健康检查会一直红。规则收到一处：
退出码只由 `_doctor_status()` 决定，打印不再改它。

顺带补 `--strict`（要求每条请求的通道都可用）——CI 里想断言「这台机器两条都行」的用它，
默认仍然是「一条能用就够」。实测八种组合全部符合规则：

```
py32 doctor 0 / --strict 1 / doctor cd 1 / doctor kd 0
py64 doctor 0 / --strict 1 / doctor cd 0 / doctor kd 1
```

新测试 `test_doctor_exit_code_follows_its_own_rule` 不写死期望值，而是**从信封算出期望码**再比对，
所以在一条通道都没装的机器上同样成立。

### 二、一次调用要多久（实测表）

```
kd mol     20 ms        cd draw     228 ms        kd open   1437 ms
kd save    62 ms        cd figure   341 ms        kd export 13405 ms
identity   0.2 s wall   cd export   119 ms        kd close  0.8 s wall
```

分界线很清楚：不碰 GUI 的是毫秒级，一碰 GUI 就是秒级。`kd export` 那 13 秒几乎全在等 KingDraw
自己开文档、写 `.kdx`——那是应用的节奏，工具能做的是不浪费它（应用锁、残骸清扫、超时边界），
README 里现在有这张表。

### 三、顺手：`crosscheck` 的 SMILES 也是位置参数

我先写成 `crosscheck --smiles CCO` 拿了 rc=2（argparse）。这类「哪个命令用位置参数」的记忆负担
确实存在，但已经在 `test_contract_sync` 的契约里（每个 --flag 都必须落到真实子命令），不再加
别名——两种写法都收会让帮助文本自相矛盾。

## 2026-10-29 · 第二十九轮：README 门面，与三处自相矛盾的文字

一个画分子的仓库在 GitHub 上没有图、文档里还留着上一轮改掉的旧规则——这一类「门面」问题不会
让测试挂，但会让第一次看的人摇头。

### 一、README 说 `doctor all` 退出码是 1

上一轮刚刚把规则改成「至少一条通道可用就是 0」，而 README 顶部那段还写着「64 位解释器跑这条时
kd 那一半会报位宽不可用、**退出码是 1**——那是预期值」。这正是这个项目一直在修的那类问题：
代码改了，说明书没改，读者照着说明书判断就会误判。已改成新规则，并补上 `--strict` 的说明。

### 二、苯酚那两张图的尺寸是错的

README 里写着「1922×1302，矢量级线宽」，而 `docs/img/phenol-chemdraw.png` 实际是 **640×433**。
1922 是 `cd figure` 在本机能出的上限（那条被测过的警告里写着 about 1922 px），不是仓库里那张图
的尺寸。改成实测值，并把「上限」这个词说清楚。

顺手核对了同一段里的身份断言：`identity c1ccccc1O` → `ISWSIDIOOBJBQZ-UHFFFAOYSA-N`、`C6H6O`；
`crosscheck c1ccccc1O` 三个引擎（rdkit / kingdraw / chemdraw）全部 agree。这两句是对的。

### 三、我差点自己加出一份重复的图块

我插入图片块时没先看 README 已有内容，结果「## 两个通道」前后出现了两份同一组图。写完 `grep`
才发现，删掉了自己那份——原始那组更好（带尺寸与 InChIKey 对账）。教训：**先 grep 再加内容**。

### 四、文档索引里的套件数

`docs/index.md` 写「17 个套件一条命令」，实际已经 19 个（新增 `test_applock`）。改成 19。

### 五、结果

`md_render_check` 0 finding（其中一次是因为我那条表格行 116 列超了 100 的预算，缩到 90 以内）；
`preflight` 11/11；全量套件见下。

## 2026-10-29 · 第三十轮：`.king` 存不住的东西，之前一声不吭

挑最危险的一类问题下手：静默丢化学信息。做法是把九种「难画」的分子过一遍两条通道，每一步都用
RDKit 的 InChIKey 对账。

### 一、先纠正我自己的一个错误结论

第一版探针只看 `.king` 里的 `nodes/bonds/texts` 计数，看到同位素和自由基都是「一个裸 C、没有
文本」，就准备断言「写的时候丢了」。再往下看才发现两件事：

1. 电荷其实**保住了**，只是写成了标签：`Label=NH4+`、`Label=O-`。计数里看不到，因为那不是
   `texts` 对象。
2. `kd mol`（SMILES → molfile）是**忠实的**：`[NH4+]`、`CC(=O)[O-]`、`[13CH3]C`、`[CH3]`、
   两性离子五种，molfile 的 InChIKey 与输入逐一相同。molfile 是 V3000，`CHG=` / `MASS=` /
   `RAD=` 都在原子属性里，没有 `M  CHG` 那种老式行——所以「找不到 M 行」不等于「丢了」。

### 二、真问题：同位素与自由基进 .king 后消失且不报

`kd save` 对这两样东西原本一句话都没有：`ok: true`、`degraded: false`。屏幕上就是一个普通的
碳原子——「少了一点点看不出来的东西」，正是最难被发现的那种丢失。

补上：`unrepresentable_atoms()` 读 molfile（V3000 看 `MASS=` / `RAD=`，V2000 看 `M  ISO` /
`M  RAD` 与原子块的同位素列），结果里给 `isotopes_not_carried` / `radicals_not_carried` 数量，
并加警告 + `degraded`，理由写明「要这个细节就保留 .mol」。电荷不在此列——它能写进标签，不该被
污蔑成丢失。

实测（同一份 molfile 前后对比）：

```
iso.mol -> iso.king   degraded: 1 isotope label(s) dropped
rad.mol -> rad.king   degraded: 1 radical(s) dropped
cat.mol -> cat.king   （无 degraded：Label=NH4+ 保住了电荷）
```

### 三、测试

`test_kd_save` 10 → 11 条：`test_an_isotope_or_a_radical_is_named_as_lost`。它做三件事——
① 函数层面对三种 molfile 计数（同位素 1、自由基 1、带电荷 0）；
② 真的写一遍 `.king` 并断言 `degraded` 与警告都在；
③ 打开写出的文件确认里面**确实**没有 `MASS`/`RAD`（证明「丢了」这句不是空话）。

### 四、这轮的边界

没有去动 `.king` 的写入格式——那是厂商格式，加字段的风险是 KingDraw 打不开自己的文件。工具能做
的是「做不到就说做不到」，这一轮做的就是这个。

## 2026-10-29 · 第三十一轮：`kd close` 只加了一层

上一轮之前加的 `kd close` 只落在命令行。这个项目有三层交付（CLI、MCP、DSH 插件），于是出现一个
很典型的不一致：**工具在结果里建议「关掉那个窗口再开」，而 agent 手里没有能关窗口的动作**。

### 一、补 MCP

`kingdraw_close`：参数 `pid`（默认关掉工具能看到的每个窗口）、`timeout`；不杀进程，走 `WM_CLOSE`，
有未保存内容时应用弹自己的对话框、窗口留着不关，结果里 `still_running` + E05 说明。

实测（真的起一个 stdio MCP server 走一遍 JSON-RPC）：

```
tools/call kingdraw_close {pid: 999999}
  -> ok: true
     data: targets [999999], results [{closed: true}], nothing_was_running [999999]
```

### 二、补插件

`kingdraw_close` 同样注册进 DSH 插件，转发到 `kd close`。`test_plugin_tools` 的工具数 14 → 15，
KingDraw 那一组 6 → 7。

### 三、契约表也要跟上

`tools/contract_sync.py` 里有一张 `MCP_TO_CLI` 表，声明「每个 MCP 工具对应哪条 CLI 路径与哪个 flag」。
新工具一落地它就报 `unmapped: mcp/kingdraw_close`——这正是它该做的事：三层之间不许有没人认领的
接口。补上 `('kd close', {'pid': '--pid', 'timeout': '--timeout'})` 后契约回到「no drift」。

### 四、顺手改掉两处旧数字

主 README 写 MCP 暴露 15 个工具、插件 README 写「14 个工具全部注册」与「17 个套件」——都过期了。
现在是 16 个 MCP 工具、15 个插件工具、19 个套件。

### 五、我自己这轮犯的低级错

两次把中文长句直接拆成多行写进 `description`，JS 与 Python 都炸（未闭合字符串）。改成就地拼接
（JS 用 `+`，Python 用括号隐式拼接）才对。教训：**多行中文描述不要跨行裸写**。

## 2026-10-29 · 第三十二轮：把「文档里的数字」交给机器守

这类问题我已经撞了三次：主 README 写 MCP 暴露 15 个工具（实际 16）、`docs/index.md` 写 17 个套件
（实际 19）、`PROGRESS.md` 头部写 17 个套件 + 168 秒。每次都是**读的时候发现的**，所以每次都会回来。

这次不修句子，改修成因：`tools/preflight.py` 增加第 12 项检查 `documented counts match the code`。

做法：它先数真实数量——`test/run_all.py` 里的 `('test_...` 行数、`dsh-plugin/lib/index.js` 里的
`name: '...'` 个数、`mcp_server.py` 里 `'name': '` 的个数——再拿这些数去核对文档里那句话：

```
README.md            暴露 **N 个工具**  -> MCP 工具数
README.md + docs/index.md  N 个套件      -> 套件数
dsh-plugin/README.md N 个工具           -> 插件工具数
PROGRESS.md 头部     MCP server（N 个工具）/ DSH 插件（N 个工具）/ 全部 N 个套件
```

刚加完就抓到 4 处：`PROGRESS.md says 14 mcp, there are 16`、`says 14 plugin, there are 15`、
`says 15 mcp`、`says 17 suite`。改完 PASS。

### 两个自己给自己挖的坑（都留在注释里了）

**一、范围切错了，检查穿到历史里去了。** 我本来想「只查头部、不查历史条目」，写的是
`body.split('## [BEGIN]')[0]`——但本账本的条目开头是日期（`## 2026-10-29 · …`），根本没有 `[BEGIN]`
这个词，`split` 什么都没切掉，于是整本历史都被当成「当前状态」扫了一遍，报出 14 个工具十一次。
改成 `body.split('\n## ')[0]`：第一个二级标题之前的才是当前状态。

**二、一条匹配不到任何东西的规则会永远 PASS。** 这才是这类检查真正的死法。加了一条：每条声明
规则必须至少命中一次，否则报 `no longer states its … count in a shape this check can read`。
它当场抓到我瞎猜的 `(\d+) 个 tools`（README 里没这种写法），删掉。

### 顺带

`README.md` 的「本机实测 18 个套件全过」→ 19；`PROGRESS.md` 头部的 MCP 工具 15 → 16、插件工具
14 → 15、套件 17 → 19、耗时 168 秒 → 约 212 秒。

preflight 现在 12 项检查 / 157 个跟踪文件 / 0 failures。

## 2026-10-29 · 第三十三轮：20 条命令里 18 条同形，例外是最先被跑的两条

上一轮做文档数字检查时顺手量了一次信封形状，量出一个真的不一致：

```
identity        data=False  keys=canonical_smiles,evidence,formula,inchikey,input,note,ok
doctor kd       data=False  keys=available,capabilities,channel,details,version
crosscheck      data=True   keys=channel,data,degrade_reason,degraded,elapsed_ms,...
cd capabilities data=True   ...
kd king missing data=True   ...
```

21 条叶子命令里 19 条是 `{ok, channel, data, failure, degraded, elapsed_ms, warnings}`，`identity` 与
`doctor` 是扁平对象，**没有 `data`**。再加上 MCP 的 `chem_identity`（它直接调适配器、不走命令行）
也是扁平的——一共三个位置。而这三处恰好是新人最先跑的：`identity` 是零依赖的第一条命令，

（更正，第三十五轮：上面这两个数字原来写的是 20 / 18，是把 `kd`、`cd` 两个组命令也当成叶子数错了。
真实的叶子是 21 条——`contract_sync.cli_surface()` 数出来的。结论不变，只改计数。）

`doctor` 是「为什么不能用」的第一站，`chem_identity` 是插件里的第一个工具。

于是「读 `payload['data']`」这条每个其他命令都在教的规则，在这三处正好抛 KeyError。审计文档里
把这记成了「认知负担」——它有名字，叫缺陷。

### 改法：加法，不是重排

`models.as_envelope(body, channel, ok, elapsed_ms)`：把扁平体原样留在顶层，另加信封键，
`data` 取扁平体去掉 `ok`/`failure`/`evidence` 之后的那部分。

```
identity --json  ->  ok=True channel=rdkit data=True elapsed_ms=46
                     inchikey 仍然是 LFQSCWFLJHTTHZ-UHFFFAOYSA-N（顶层与 data 里都有）
doctor all --json ->  数组，每项都有 data，ok 等于该项的 available
MCP chem_identity ->  has data: True，inchikey 仍在顶层
```

`doctor` 的 `ok` 由 `available` 传进去，不能默认成 true——那会把「没装」报成成功。

### 两条新断言

`test_contract_sync` 新增 `Envelope` 三条：identity 成功体有全套信封键且扁平键不动、坏 SMILES 时
`ok=False` 且 `failure` 在、`doctor` 单通道与双通道（`--no-start`，0.3 秒）都带 `data` 且 `ok == available`。

写这三条时自己绊了一下：`ROOT` 是 str 不是 Path，`ROOT / 'bin'` 抛 TypeError，报出来像 CLI 崩了。

### 收益

脚本侧从「18 条一个形状、2 条另一个形状」变成「20 条一个形状」；README 里那段「两个例外」的说明
换成了「读 `data` 就够了」。全量 19 passed / 0 failed / 0 skipped / 213.7s。

## 2026-10-29 · 第三十四轮：README 收尾（结构 + 授权）

两件事，都很小，但都是「别人第一次打开这个仓库」会碰到的。

### 一、`已知限制` 的列表被一句话劈成两半

原文是这样的：

```
- cd read 不带 --smiles 时读不到已经开着的那一页：……
  （这一段有两个子弹的间距）
见 PLAN.md 的风险账本与 PROGRESS.md 的失败记录。……   ← 夹在列表中间
  （又一个间距）
- .king 装不下立体键。……                              ← 列表继续
```

一个句号夹在两条 `-` 之间，GitHub 上会把第一颗子弹和后面的整段并成一段，读起来像列表断了。
把这句话挪到列表之后。

### 二、没有「授权」

仓库根有 `LICENSE`（MIT），`pyproject.toml` 也写了 `license = { text = "MIT" }`，但 README 一个字没提。
补一节，写清楚两件容易误会的事：

- 仓库里没有厂商软件。`kd` / `cd` 调的是你自己机器上装的那一份，本项目的授权范围不涉及它们。
- 代码按「现在的样子」给。它在两台机器上跑过（本机 Windows 11 + ChemDraw 26 + KingDraw，
  以及 CI 的 windows-latest），除此之外没有验证过。

### 顺手确认过、没改的

根目录只留 `.gitattributes`、`.gitignore`、`LICENSE`、三个 `PLAN*.md`、`PROGRESS.md`、`README.md`、
`install.ps1`、`pyproject.toml`、`requirements.txt`——`PLAN.md` 是风险账本，被 README 与多份审计文档
引用，`PLAN-v1/v2` 是它的历史版本；把它们挪进子目录会让那些审计文档里的行号引用全部失效。根目录
保持现状。
### 第二轮验证

清干净桌面后全量：**17 passed, 0 failed, 0 skipped in 167.9s**；脏桌面下的那次红有完整日志
（`test/out/order.log`）和四条失败原文。
## 2026-10-27 — v2 M1：任务级接口跑通（status / draw / close）

v1 归档到标签 `archive/v1-engine-layer`（说明见 `ARCHIVE.md`），v2 按 `docs/v2/requirements.md` 重做暴露面。

- `core/chemdraw_tool/v2/` 四个模块：`route.py`（双轨能力表 + 不启动任何程序的可用性探测）、
  `geometry.py`（CDXML → 键长像素 → 可读性判据与分级）、`session.py`（常驻会话：GetActiveObject 复用已有实例，
  仅当实例由我们启动时才隐藏，断开只丢 COM 引用**不 Quit**）、`tasks.py`（status/draw/close + 信封）。
- `bin/v2.py`：三个动词，一次调用一个 JSON 信封。
- 实测（本机 ChemDraw 25）：咖啡因 **0.61 s**（页面 14/14 与输入一致，预览 39.7 KB）；阿司匹林 13/13，
  InChIKey `BSYNRYMUTXBXSQ-UHFFFAOYSA-N`，预览 1000×832 / 32.4 KB，median bond 231.8 px（可读）。
- 常驻实测：第二个进程 `attached=True`，机器上只有一个 ChemDraw 进程；断开后自动化文档自动消失，不累积。
- 零干扰实测：连续 5 次 `draw`，新增可见顶层窗口 **0**、前台窗口未变。
- 复杂分子（需求 §16）：120 原子插入 0.10 s / 导出 2.30 s；400 原子插入 0.27 s / 导出 5.29 s，
  且 400 原子导出字节数反而更小——可读性问题，已由 `draw` 自动加宽画布 + 警告处理（FR-D12）。
- 单测 `test/test_v2_surface.py` 14 项（几何、输入识别、路由、status 形状），已登记进 `run_all.py`（现 20 个套件）。
- 未做：名称解析（M4）、批量（M2）、命令面 3D/NMR/计量（M3）、OCR（M4）、教学（M5）。
## 2026-10-27 — v2 M2 + M3：批量/出图/转换/性质表；命令面改为可算的自己算

**M2（提交 d266343）**：`v2/figure.py` 期刊预设（中文 8 cm / 图式 17 cm / ACS / RSC / Nature / web）、
`v2/props.py` 性质表与格式写出；`tasks.figure_export` 不偷加宽（放不下就报 readable_at_preset=false）；
`tasks.batch` 按**共同键长**归一化拼联系表；`tasks.convert`（sdf/mol/smiles/inchi/csv）；
`tasks.analyze`（CSV + markdown 表）。`bin/v2.py` 扩到 7 个动词。

**M3（本轮）**：新增 `checks.py`（价键/电荷/碎片/未定立体 + 原子重叠）、`stoich.py`（当量与投料量）、
`geom3d.py`（ETKDGv3 + MMFF94 → .mol/.xyz）；对应三个动词 `check` / `stoich` / `3d`。

**命令面实测结论（写进需求 §17）**：

- UIA `expand()` 能展开菜单，但条目 `invoke()` 无该模式、`click_input()` 后页面哈希不变 → 命令没生效；
- UIA 与 COM 混在同一进程会段错误（exit 139），ChemDraw 进程存活；
- 纯键盘加速键（Alt+S / T / Enter）同样不生效；
- `WM_COMMAND` 会打死应用（先前已记）。

所以命令面**不作为产品能力**，`v2/command.py` 仅保留为实验工具；3D/体检/计量改用确定性实现。
NMR 仍不实现，并在能力目录里写清原因。

测试：`test/test_v2_surface.py` 31 项全过（新增体检 4、计量 2、3D 2）。
## 2026-10-27 — v2 M4：名称/CAS 解析与图像识别投票

新增 `v2/resolve.py`（本地名称表 ~40 条中英双语、本地 CAS 表、PubChem REST 兜底，返回 source/tried）
与 `v2/ocr.py`（读者可插拔：MolScribe/DECIMER/OSRA/MolVec + 调用方的 llm_hint；RDKit 淘汰非法结构；
按 InChIKey 合并投票；单来源只作候选并标 needs_confirmation）。

任务动词：`resolve_name`（别名 resolve）与 `ocr`；CLI 增 `resolve`（含 `--offline`）与 `ocr`（含 `--llm-hint`）。

实测：

- `resolve 咖啡因` → 本地命中，InChIKey RYYVLZVUVIJVGH-UHFFFAOYSA-N；
- `resolve 64-17-5` → 本地 CAS 命中，C2H6O；
- `ocr <png> --llm-hint OCCO` → best LYCAIKOWRPUZTN-UHFFFAOYSA-N，needs_confirmation=true，
  engines 四项全 false（诚实报告未安装）。

修掉两个真实缺陷：`rdkit.Chem.rdMolDescriptors` 未导入导致 OCR 整条链路抛异常；
`tried.append(a, b)` 应为 `extend`。

测试：`test/test_v2_surface.py` 39 项全过（新增名称 3、投票 5）。
## 2026-10-27 — v2 M5：批量批改与出题变体

新增 `v2/grade.py`（InChIKey 判定 + 骨架/立体/分子式/官能团差异解释）与 `v2/variants.py`
（RDKit ReplaceSubstructs 把骨架 [*] 换成取代基，产物带 InChIKey，重复自动合并）。

任务动词 grade / variants；CLI 增 `grade --answer ... subs...` 与 `variants scaffold subs...`。

实测教学链路：苯骨架 + 4 取代基 → 4 变体 → batch 出联系表 → 批改 3 份答卷得到
correct / different（分子式 C7H6O2 vs C9H8O4）/ isomer（对位取代，同分异构）。

测试：`test/test_v2_surface.py` 46 项全过（新增批改 4、变体 3）。
## 2026-10-27 — v2 暴露面：14 个任务级 MCP 工具

新增 `core/chemdraw_tool/mcp_tasks.py`：把 v2 的 14 个任务动词包成 MCP 工具，每个调用派发到
`bin/v2.py` 的**子进程**执行——厂商程序崩了只损失一次调用，不会带走 server。子进程固定 `PYTHONIOENCODING=utf-8`
（否则中文名如「咖啡因」回传成乱码）。

`bin/mcp.py` 增加 `--surface tasks` 开关；默认仍是 v1 的 16 个动作级工具，两套暴露面互不干扰。

工具表：chem_status / chem_draw / chem_figure / chem_batch / chem_convert / chem_analyze / chem_check /
chem_stoich / chem_3d / chem_resolve / chem_ocr / chem_grade / chem_variants / chem_close。

新增 `test/test_mcp_tasks.py`（6 项）：initialize/tools/list 握手、通知不应答、chem_check 信封、
chem_resolve 离线命中、未知工具报错不崩、缺参数点名问题。

修掉两个真实缺陷：`ROOT` 少算一层导致 CLI 路径变成 `core/bin/v2.py`；子进程编码导致中文查询失败。

文档：README 增「v2 任务级接口」一节；docs/index.md 增入口；需求 §7 工具表改为已实现的 14 个；
套件计数 20 → 21 全库同步（README / docs/index.md / dsh-plugin/README.md / PROGRESS 头部 / 需求）。
## 2026-10-27 — v2 任务级工具进 DSH 插件（15 → 29）

`dsh-plugin/lib/index.js` 新增 14 个任务级工具（`chem_status`/`chem_draw`/…/`chem_close`），与 v1 的 15 个
动作级工具并存，名字不重叠。`bridge.js` 抽出 `execJson()`，新增 `spawnV2()`：v2 只要求 64 位解释器，
通道选择与 `chemdraw_*`/`kingdraw_*` 互不干扰。

两个门禁因此要认第二棵树，否则「新增能力」会被当成契约漂移：

- `tools/plugin_contract.mjs` 增加 `spawnV2` 桩，把它们的 argv 记为 `channel='v2'`。
- `tools/contract_sync.py` 把 `cli_surface()` 拆出 `_walk_parser()`，新增 `v2_surface()`（走 `bin/v2.py`
  的 `build_parser()`）；按 channel 选对应 argparse 树做校验，参数覆盖也用它。
- `tools/preflight.py` 的插件计数原来只认 `name: '...'`，改用 `task('...'` 的 14 个会被漏掉，两种形状都数。

参数命名踩了一次真坑：`layout`/`optimize`/`hint` 分别对应的 CLI flag 是 `--with-layout`/`--no-optimize`/
`--llm-hint`，静态对账认不出来。改成 `withLayout`/`noOptimize`/`llmHint` 后 kebab 名与 dest 都能对上。

`test_plugin_tools.mjs`：工具数 15 → 29，新增 14 个任务工具存在性检查与一次真实 `chem_check` 调用；
`test_contract_sync.py` 的 surfaces 夹具补上 `v2`。

文档：`dsh-plugin/README.md` 增「v2：任务级工具」表（14 行）、注册面 15 → 29；`docs/agent-interface.md`、
`PROGRESS.md` 头部同步。
## 2026-10-27 — 需求 §9 的八个验收剧本（可复跑）+ 修掉体检的真实缺陷

新增 `tools/acceptance_v2.py`：按 agent 的方式跑 §9 八个剧本，只读信封，记录 CLI 调用次数、
耗时与实测值，生成 `docs/v2/acceptance.md`。实测 8 个剧本 **10 次调用、13.0 秒**，
6 个 PASS、2 个 PARTIAL（如实记录，见下）。

- 阿司匹林 80 mm：1.43 s，median bond 218.2 px，`verified=True`。
- 8 个分子一张作业图：8.03 s，8 项全部画出，联系表落盘。
- 酯化 10 mmol：乙醇 460.69 mg（理论 460.7，误差 0.010 mg），满足 §9 的 ≤0.1 mg 判据。
- 64-19-7：解析出乙酸并画出，InChIKey `QTBSBXVTEAMEQO-UHFFFAOYSA-N`。
- 批 10 份：10 份全部判定，出现 correct / stereo / different / unreadable 四类。
- **PARTIAL 5**：本地没有装任何识别引擎，`ocr` 无 hint 时拒答并列出缺哪个；不猜。
- **PARTIAL 7**：反应条件文字标注未实现（计量表能出，条件标不上去）。

修掉两个真缺陷（验收跑出来的，不是想出来的）：

1. **五价碳报成「解析失败」**。`_read_molblock` 只做 `sanitize=True`，而送检的畸形结构恰恰过不了
   sanitization，于是学生只得到 E06「读不出」，不知道错在哪。改为先 sanitized、失败再
   `sanitize=False` 回落；`checks.inspect` 增加显式价键审计（按元素上限算真实键级和），
   现在直接说「atom 1 (C) carries 5 bond orders, the limit is 4」。
2. **结构类动词不认文件路径**。学生交的是文件，`check`/`analyze` 却只收 SMILES 文本。
   在 `_read_source` 统一解析路径，四个动词一起受益。

顺带把 `checks.inspect` 里几处会在未 sanitize 分子上抛异常的地方加了兜底（立体中心、分子式），
否则修好一条报告路径会换来一次崩溃。
## 2026-10-27 — 两条硬指标的实测：C129 复杂分子、三项干扰为零

**复杂分子**：从 PubChem 取岩沙海葵毒素（palytoxin），分子式 C129H223N3O54，186 个重原子、
64 个手性中心、SMILES 长 642 字符。一次 `draw --width-mm 170` 走完插入 + 导出 + 读回核对：
**2.45 秒**，170 mm@300 dpi，61.9 KB，median bond 36.5 px，`readable=true`，`tier=medium`。
这条回答了「能不能处理岩沙海葵毒素那种分子」——能，而且一次调用跑完。

**零干扰**：先 `close --quit` 退出应用，再连续交付 3 张图（4.09 s，含冷启动）。
按**窗口类名**统计（不是标题）：`windows_before=[]`、`windows_after=[]`、新增可见窗口 **0**、
前台窗口未变。三项指标全 0。

统计口径本身踩过坑：第一版按标题匹配 'chemdraw'，把本会话的 DSH 窗口
（标题含「AI 对接 ChemDraw 与 KingDraw」）算了进去，基线变成 1，看起来像有残留窗口。
改成按窗口类名匹配后，基线确实是 0。

**干净克隆演练**：`git clone --no-hardlinks` 到临时目录 → `tools/preflight.py` 12 项 0 失败、
`bin/v2.py check CCO` 正常返回 → 删除临时目录。181 个受版本控制的文件自成一体。
## 2026-10-29 — 更正日期口径；补双轨隔离的断言

前面三条记录（v2 暴露面、插件 29 工具、验收剧本、C129 与零干扰）标题写的是 2026-10-27，
本机日期实际是 **2026-10-29**。条目按追加原则保留原文，此处更正：那几条都发生在 2026-10-29。

补 `RouteIsolation` 三项断言（`test_v2_surface.py`）：两条通道的锁名不同、每个任务的路线都真实存在、
两条通道各自都有被优先选中的任务——「双轨」不是文案，是表结构。

README 状态段改写：先讲 v2 任务级接口与三种用法，再给实测数字（C129 2.45 s、新增窗口 0、
八剧本 13 秒），最后写明唯一不交付项 NMR。
## 2026-10-29 — 收尾核对：算完成的与没完成的，逐条写清

本轮把「可交付」拆成可测的六条，逐条核对：

| 目标 | 证据 | 状态 |
|---|---|---|
| M1–M5 任务级接口 | 五个里程碑提交 + 14 个动词 + 三处暴露面 | 完成 |
| 复杂分子 C129 | palytoxin C129H223N3O54，186 重原子，2.45 s，readable | 完成 |
| 双轨隔离 | 锁名分离 + 路线表各自可首选 + `RouteIsolation` 三项断言 | 完成 |
| 交付后零干扰 | 3 次交付，新增可见窗口 0、前台未变 | 完成 |
| 门禁 | 21 套件 253.5 s 全过、preflight 12 项 0 失败、md 0 finding | 完成 |
| 工作树与历史 | 62 次提交、181 个受控文件、干净、`archive/v1-engine-layer` 标签 | 完成 |

**没完成的两条，写进需求 §12，不算完成**：

1. **FR-D6 反应式**：箭头、条件文字、原子映射编号都没有；现在只有计量表。
   缺版面（多结构排一页）、条件标注、映射编号三件事，映射算法本身 RDKit 能做。
2. **NMR（FR-V4）**：明确不交付。

另有两条按实测记为 PARTIAL：OCR 无本地识别引擎（拒答并列出缺什么）、条件标注同上。
这三条都在验收表里，没有一条被写成通过。
## 2026-10-29 — FR-D6 反应式：映射、RXN、整页渲染（条件文字仍未画进图）

新增 `reaction` 动词（CLI / MCP 15 个任务工具 / 插件 30 个工具三处可见），实现三件事：

1. **原子映射**：按「元素+电荷+氢数+度数+邻接元素+芳香性」签名做精确匹配，不确定的按
   「元素+电荷+邻接」回落，仍不唯一的标 `created`。酯化实测：7 个产物原子 5 精确、2 新建。
2. **RXN 块**：把映射号写进 molblock 原子列，$RXN 头 + 两侧 $MOL。
3. **整页渲染**：RXN 由 `Objects.Data('chemical/x-mdl-rxnfile')` 插入，ChemDraw 自己排
   「反应物 + 加号 + 箭头 + 产物 + 上标映射号」。实测一次调用 1.5 s，可读性按页面原子中心
   最近邻距离换算（median bond 154.8 px @170 mm）。

**没做成的一条**：条件文字画不进图。CDXML `<t p="x y">` 插入被接受但坐标被忽略——
换了两个 y 得到字节完全相同的 PNG，文字永远压在箭头和产物上。自绘 `<graphic>` 箭头也试过：
简单页面上能画（已复现），换成多片段页后就消失。最终选择让厂商排 RXN，条件只走返回值。

门禁：v2 套件 53 项、插件 30 项、MCP 6 项、契约 19 项全过；preflight 12 项 0 失败，md 0 finding。
验收表第 7 项从「计量表」改成真实的反应式，判定仍是 PARTIAL（条件未画）。
## 2026-10-29 — 条件文字进图：厂商画不到，就由合成器叠（机制写明）

把「条件文字」这条从缺口补成可用，过程是三次失败换一个确定性方案：

1. **CDXML `<t p="x y">`**：插入被接受，坐标被忽略——两个完全不同的 y 得到字节相同的 PNG。
2. **带 Text 标签的伪原子**：坐标被尊重（这条是新发现，单独一页里文本能精确落位），
   但与结构放在同一个 payload 时**箭头消失**；分两个 payload 时，第二个又被丢到内容中心。
   实测三次：`TOP-20`/`MID-90`/`TOPBOX` 三个 y 全部叠在同一处。
3. **合成器**：ChemDraw 画反应式（反应物 + 加号 + 箭头 + 产物 + 上标映射号），
   导出的 PNG 顶部叠一条白带写条件。返回里明写 
   「conditions are composited onto the figure by this tool」，不假装是 ChemDraw 文本。

产物：`reaction "CCO.CC(=O)O>>CC(=O)OCC.O" --conditions "H2SO4, 80 C"` 一次调用 3.0 s，
图里箭头、映射号、条件三样齐全；`page.annotations` 记 0（合成器不往页面里加原子）。

验收表第 7 项由 PARTIAL 转为 PASS，只剩 OCR（缺本地识别引擎）一条 PARTIAL。
v2 套件 53 → 55 项（新增合成器两条断言）。

## 2026-10-29 — 图像识别装好两个引擎：MolVec + DECIMER，各 6/6

目标是把「看图读结构」从「框架就绪、引擎为空」变成有真实读者的东西。四个引擎的依赖互相打架，
所以走「一个引擎一个环境 + 子进程调用」：主进程不 import torch / TensorFlow。

- **MolVec 0.9.8**（Java，1.3 MB jar，Maven Central）→ 6/6 命中，1.2 s/图。
- **DECIMER 2.8**（独立 venv：TF 2.15.1 + Keras 2.15；权重 298 MB 手动取，PYSTOW_HOME 指过去）
  → 6/6 命中，批量 8.5 s/图。
- **MolScribe**：依赖与 1.1 GB 权重都装好、import 通过，卡在 OpenNMT-py 2.x 的 attention API。
  探针因此报能力不满足而不是「缺失」。
- **OSRA**：只有源码包，没有 Windows 二进制。

回归集 `tools/ocr_regression.py` 自带答案：本工具画已知分子 → 引擎读回 → 比 InChIKey。
6 个分子含手性 (S)-布洛芬，两个引擎都给出正确立体；两引擎一致时 votes=2 / confidence=high。

顺手修的 bug：MolVec 的 molfile 首行是空标题，`.strip()` 把计数行挪位 → RDKit 读出空结构。
改成不 strip 并写成回归测试。

新增 `chem_ocr --probe`（逐引擎给「不可用的原因」）、`chem_status` 里的 `ocr_engines`、
以及识别后的重画图（`redrawn` / `compare`）：读对没读对，两张图并排比置信度数字可靠。

验收：八个剧本 8/8 PASS（第 5 项由 PARTIAL 转 PASS）。文档 `docs/ocr-engines.md`。