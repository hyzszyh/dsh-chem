# ChemDraw 26 COM 通道：插入结构与导出图片的可行方案

> 调研对象：上游开源项目 [MALeitch/live-chemdraw-mcp](https://github.com/MALeitch/live-chemdraw-mcp)（MIT，pywin32）+ 本机 ChemDraw 26 实测。
> 实测环境：本机 ChemDraw `26.1.0.6327`（CDXML 头 `CreationProgram="ChemDraw 26.1.0.6327"`），COM 类型库标示 `CS ChemDraw 64-bit 22.0 Object Library`，ProgID `ChemDraw_x64.Application`。
> 上游自述验证版本：ChemDraw Professional `26.0.0.6141`，与本机同一大版本，结论可平移。
> 本文只记录「怎么把分子放进去 / 怎么把图拿出来」这两条链路的实证结论；本地实验脚本均在 `%TEMP%\cdprobe*.py`，未写入项目。

## 0. 结论速览

**插入分子**

- **唯一可靠通路**：`doc.Objects` 的参数化属性 `Data`，用 **raw IDispatch Invoke 做 property-put**
- **关键点**：传 **MIME 字符串 + bytes**；**不走剪贴板、不走 Paste、不走 DataObject**

**导出图片（生产）**

- **唯一可靠通路**：`doc.SaveAs(path, IChemDrawDataType, resolution, W, H)`
- **关键点**：`Format` 从 `Application.ExportDataTypes` 里按 `Extension` 挑，**不是**传字符串

**导出图片（预览/内存）**

- **唯一可靠通路**：`doc.Objects.GetData("image/png", n)`
- **关键点**：返回 `memoryview`；**本机 n 完全无效**，永远 106×76 缩略图

**导出 CDXML**

- **唯一可靠通路**：`doc.Objects.GetData("text/xml")`
- **关键点**：返回整页完整 CDXML（含 colortable/fonttable），可直接落盘

**读回结构文本**

- **唯一可靠通路**：`GetData("chemical/x-mdl-molfile")` / `("chemical/x-daylight-smiles")`
- **关键点**：实测均可用

**打开 .cdxml 文件**

- **唯一可靠通路**：`Documents.Open(path)`
- **关键点**：**会静默失败**（不抛错、文档数不变），详见 §6


上游**完全不用** `Paste`、`Clipboard`、`DataObject` 这些对象来插结构；`Document.Paste()` 在它的代码里一次都没被调用（全仓搜索仅有 `Selection.Objects.Copy()` 这一处剪贴板用法，用于把选区复制给用户手工粘贴）[^1][^2]。

---

## 1. 插结构：完整调用序列

### 1.1 代码原文（上游 `bridge/_plumbing.py` 的 `_insert_raw`）[^1]

```python
    @staticmethod
    def _insert_raw(objs, mime, payload):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        raw = objs._oleobj_
        dispid = raw.GetIDsOfNames(0, "Data")
        raw.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, mime, payload)
```

### 1.2 调用序列（可直接照抄）

1. `app = win32com.client.GetActiveObject("ChemDraw_x64.Application")`（上游明确要求：**不要用 `Dispatch()`**，会另起一个 ChemDraw 进程和用户已开的窗口并存）[^3]。
2. `doc = app.Documents.Add()`（或现有文档）——**先有文档窗口**，见 §6。
3. `raw = doc.Objects._oleobj_`；`dispid = raw.GetIDsOfNames(0, "Data")`。
4. `raw.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, mime, payload)`，其中 `mime` 是字符串，`payload` 是 **bytes**。
5. **必须校验** `doc.Atoms.Count` 在调用后变大（见 1.4 坑 1）。
6. 新结构以 **Group** 形式出现：`doc.Groups.Item(i)`（1-based）就是可寻址实体；需要定位就 `group.Move(dx, dy)`。

pywin32 的 raw `Invoke` 会在内部把参数顺序反转成 DISPPARAMS 的 `rgvarg`，所以源码里写作 `(mime, payload)` 对应 VB 侧的 `Objects.Data(mime) = payload`。本机同样的一段逻辑实测可用（见 §1.3 实测）。

### 1.3 本机实测（2026 年，ChemDraw 26.1.0.6327）

```nowrap
doc = Documents.Add(); raw.Invoke(dispid, 0, DISPATCH_PROPERTYPUT, 0, "chemical/x-daylight-smiles", b"c1ccccc1O")
-> atoms 0->7  bonds 0->7  groups 0->1
GetData("chemical/x-mdl-molfile")            -> 735 bytes
GetData("chemical/x-daylight-smiles")        -> 9 bytes  ("Oc1ccccc1")
GetData("chemical/x-mdl-molfile")  头两行      -> "ChemDraw10292600352D"
```

### 1.4 必须知道的坑（上游用血换的，原文照抄要点）[^2]

1. **错误的 mime 字符串返回 S_OK 但什么也不插** → 「always verify atom count after」。上游因此在 `_insert_structure_units` 里直接抛错：
   `raise InvalidInputError(f"ChemDraw did not insert anything for the given {fmt} input ...")`。
2. **payload 必须是 bytes，不能是 str**：传 `str` 时 pywin32 按 BSTR(UTF-16)  marshalling，ChemDraw 的 `Data` setter 会先把 BSTR 窄化到**系统 ANSI 代码页**（cp1252）再交给 CDXML 解析器 —— `U+2192`（→）当场变成 `?`，**不可逆**；度数符号 `U+00B0` 因为在 cp1252 里所以完好，正好坐实机制。传 bytes 走 byte-array VARIANT，才是无损路径。
3. **一次 Data 插入产生一个 Group**；Group 是唯一可靠的地址句柄（`grp.Objects` 把 GetData/Formula/Move 限定在它范围内）。
4. **断开片段（盐、离子）会多出一个「包装 Group」**：`"[Na+].[OH-]"` 插入后 `doc.Groups` 里出现 **3** 个 Group（一个 HNaO 包住两个离子）。上游用「包围盒严格包含」判定包装组，并把它们从可定位列表里剔除，否则父组和子片段会被同一个位移搬两次。
5. **CDXML 导入时的落点不可信**：插入后位置要显式 `Move()` 重排。
6. 插入后要显式让窗口前台化（`nudge.bring_to_foreground(hwnd)`），否则紧跟的查询可能读到**上一轮**的 Groups/Atoms 计数。

---

## 2. MIME 字符串表（上游 `com/types.py` 的 `FORMAT_MIME`，原文）[^4]

```python
FORMAT_MIME = {
    "smiles": "chemical/x-daylight-smiles",
    "molfile": "chemical/x-mdl-molfile",
    "molfile-v3000": "chemical/x-mdl-molfile-v3000",
    "inchi": "chemical/x-inchi",
    "inchikey": "chemical/x-inchikey",
    "name": "chemical/x-name",
    "htmlname": "chemical/x-htmlname",
    "cdxml": "text/xml",
    "cdx": "chemical/x-cdx",
    "cml": "chemical/x-cml",
    "helm": "chemical/x-helm",
    "png": "image/png",
    "svg": "image/svg+xml",
    "emf": "image/x-emf",
}
```

本机 `Application.ExportDataTypes / ImportDataTypes / IODataTypes` 枚举结果与上表一致，并且暴露出**成对写法**（`chemical/x-*` 与 `chemical/*` 各一条），见 §3.1。

---

## 3. 导出图片：`Format` 到底怎么拿

关键认知：**Format 对象只在 `SaveAs`/`Open` 这类「文件 + 类型」接口里需要；`GetData`/`Data` 用的是 MIME 字符串。** 两条路互不复用同一套取值方式。

### 3.1 `IChemDrawDataType` 的取法（本机实测）

`Application.ExportDataTypes` 是一个 1-based 集合：`Count=54`，只能 `Item(i)` 逐条取，**没有 `Name` 属性**，只有 `MIME / Extension / Valid` 三个（与 `docs/com_item_document.txt` 一致）。`Valid` 在本机 54 项全为 `True`。

按扩展名挑 Format 的写法（实测可用）：

```python
def by_ext(ext):
    coll = app.ExportDataTypes
    for i in range(1, coll.Count + 1):
        it = coll.Item(i)
        if (it.Extension or "").lower() == ext and it.Valid:
            return it
    return None
```

本机 `ExportDataTypes` 的 54 项（按 `Item(i)` 顺序，`MIME / Extension`）：

| i | MIME | Ext | | i | MIME | Ext |
|---|---|---|---|---|---|---|
| 1 | chemical/x-cdx | cdx | | 28 | chemical/smd | smd |
| 2 | chemical/cdx | cdx | | 29 | chemical/x-ct | ct |
| 3 | **text/xml** | **cdxml** | | 30 | chemical/ct | ct |
| 4 | chemical/x-chemdraw | chm | | 31 | chemical/x-cml | cml |
| 5 | chemical/x-mdl-molfile | mol | | 32 | chemical/cml | cml |
| 6 | chemical/mdl-molfile | mol | | 33 | chemical/x-inchi | (空) |
| 7 | chemical/x-mdl-molfile-v3000 | mol | | 34 | chemical/inchi | (空) |
| 8 | chemical/mdl-molfile-v3000 | mol | | 35 | chemical/x-inchikey | (空) |
| 9 | chemical/x-daylight-smiles | (空) | | 36 | chemical/inchikey | (空) |
| 10 | chemical/daylight-smiles | (空) | | 37 | chemical/x-name | (空) |
| 11 | chemical/x-smiles | (空) | | 38 | chemical/x-htmlname | (空) |
| 12 | chemical/smiles | (空) | | 39 | chemical/x-helm | (空) |
| 13 | chemical/x-mdl-rxn | rxn | | 40 | image/x-wmf | wmf |
| 14 | chemical/mdl-rxn | rxn | | 41 | image/wmf | wmf |
| 15 | chemical/x-mdl-rxn-v3000 | rxn | | 42 | image/x-wmfs | wmf |
| 16 | chemical/mdl-rxn-v3000 | rxn | | 43 | image/x-emf | emf |
| 17 | chemical/x-mdl-sdfile | sd | | 44 | image/emf | emf |
| 18 | chemical/mdl-sdfile | sd | | 45 | image/bmp | bmp |
| 19 | chemical/x-mdl-sdfile-v3000 | sd | | 46 | image/jpeg | jpg |
| 20 | chemical/mdl-sdfile-v3000 | sd | | 47 | **image/svg+xml** | **svg** |
| 21 | chemical/x-mdl-tgf | tgf | | 48 | image/gif | gif |
| 22 | chemical/mdl-tgf | tgf | | 49 | image/x-png | png |
| 23 | chemical/x-mdl-isis | skc | | 50 | **image/png** | **png** |
| 24 | chemical/mdl-isis | skc | | 51 | image/tiff | tif |
| 25 | chemical/x-msi-molfile | msm | | 52 | application/postscript | eps |
| 26 | chemical/msi-molfile | msm | | 53 | application/x-postscript-preview | eps |
| 27 | chemical/x-smd | smd | | 54 | chemical/x-fasta | (空) |

`ImportDataTypes` = 45 项，`IODataTypes` = 36 项，三者顺序/取值同族；**按 `Extension` 挑 Format 时注意 png 有 49/50 两条、mol 有 5..8 四条、eps 有 52/53 两条 —— 取第一条命中的即可（本机实测 `image/x-png` 与 `image/png` 都能存出合法 PNG）。**

### 3.2 `SaveAs` 实测（本机，含 resolution/W/H 的真实语义）

`doc.SaveAs(Filename, Format, resolution, Width, Height)`，Format 传 `by_ext("png")` 得到的对象：

| resolution | W | H | 产物字节 | 实际像素 |
|---|---|---|---|---|
| 150 | 600 | 450 | 22 635 | 2518×1893 |
| 300 | 600 | 450 | 83 321 | 5034×3784 |
| 300 | 1200 | 900 | 304 066 | 10034×7534 |
| 600 | 600 | 450 | 318 413 | 10068×7568 |
| 300 | 0 | 0 | 7 770 | 442×316 |
| 0 | 0 | 0 | 7 770 | 442×316 |

从这 6 组数据能反推出本机 ChemDraw 的实际换算：**像素宽 ≈ W × resolution / 36**（=2×「W 按点、resolution 按 dpi」的直觉值），高度同理；**W/H 不是像素、也不是点**。想得到目标像素宽度 P（dpi=D）：`W = P × 36 / D`。这条关系 ChemDraw 官方没写，属于本机反推，**标为反推结论而非文档事实**（见 §8）。

SVG 同样参数（res=300, W=600, H=450）产出 1 987 字节，`<svg width="1208px" height="909px">` —— **SVG 忽略 resolution，尺寸 ≈ 2×W + 8px**。

### 3.3 `GetData` 实测（内存 / 预览）

```nowrap
GetData("image/png",  N)   N=0,1,72,150,300,600,1200 -> 全部 1648 bytes, 106×76 px
GetData("image/png")       (不给第二参)               -> 同样 1648 bytes, 106×76 px
GetData("image/svg+xml", 300) -> 1998 bytes, 以 "<?xml version=\"1.0\" standalone=\"no\" ?>\r\n" 开头
GetData("image/x-emf", 300)   -> 6084 bytes
Selection.Objects.GetData("image/png", 150) -> 305 bytes
```

**结论：本机 `GetData` 的第二参数（上游传 dpi）完全无效**，输出是固定尺度缩略图；上游自己也只把它用于 `_preview_png`（96「dpi」）这类视觉预览，正式落盘走 `SaveAs`。另外上游记录了一个静默坑：**对位于页面外的对象，`Selection.GetData` 会返回一张合法但全白的 PNG**（无异常、数据非空），所以它先做页面越界检查再导出[^2]。

---

## 4. 其余导出（结构文本 / CDXML）

- 整页 CDXML：`doc.Objects.GetData("text/xml")` → `memoryview` → `.tobytes().decode("utf-8", "replace")`。本机实测 4 140 字节，含 `<colortable>`/`<fonttable>`/`<page>`，可直接落盘成合法 .cdxml[^5]。
- 选区 CDXML：`doc.Selection.Objects.GetData("text/xml")`。
- 上游的 `export_structure(fmt)` 走的是 **单元级** `targets.unit_objects(u).GetData(mime)`，即按 Group 范围取；整篇导出用整页那条[^6]。
- **CDXML 里节点 `id` 与 COM `Atom.ID` 完全一致**，且被 contracted 的 nickname 保持单节点；而 molfile 导出会**静默展开** nickname 成全部原子 —— 做子结构/高亮必须用 CDXML[^2]。

---

## 5. 本机没有验证的两件事（避免下游误判）

1. `Documents.Open` 打不开 CDXML 的**确切触发条件**未证实，只证实了「有时静默无效」与「先建文档后再 Open 就成功」两种状态，见 §6。
2. `IChemDrawDataType` 是否可构造（`Dispatch("...")）未知，本机一律从集合里取对象复用。

---

## 6. `Documents.Open` 的静默失败（我们团队踩的坑，已定位到症状）

本机实测两轮互相矛盾的记录，合起来才解释得通：

```
A 轮（应用已有文档窗口）: Documents.Open(p)  -> docs 0->1, 新文档 atoms=2 bonds=1（成功）
B 轮（应用无任何文档）   : Documents.Open(p)  -> docs 0->0, 不抛异常, 无新文档（静默无效）
                          同一轮里连续 6 个不同 .cdxml 全部 0->0
C 轮（无文档，且这次连 Visible=True 也设过了）: 依然 0->0
C 轮随后 Documents.Add() + Objects.Data 插入 -> 成功；此后 Open 恢复可用
```

**可操作的结论（不猜测内部机制）**：
- `Documents.Open` 失败时**不抛异常、返回值仍是 `IChemDrawDocument`**，所以「用返回值判断成功」是错的；必须**轮询 `Documents.Count`** 确认。
- 稳妥顺序：`app.Visible = True` → `doc = app.Documents.Add()`（先让应用有文档窗口）→ 再 `Documents.Open(path)`。
- **更好的做法：根本不用 Open 装载我们生成的 CDXML，改用 `Objects.Data("text/xml")` 直接插入** —— 本机 6 种最小 CDXML 变体全部一次插入成功（见 `docs/cdxml-minimal.md`），且是同步的、可立即用 `Atoms.Count` 断言。
- 顺带记录：`Documents.Open(path)` 不带 Format、带 Format 对象两种调用都能成功打开 .cdxml，**Format 不是必需参数**；团队此前「Format 是 IChemDrawDataType 对象，所以 Open 无效」的推测不成立，真正的分界是上面那个状态问题。

---

## 7. 移植到我们项目时建议照抄的 COM 细节

**插入 = `Objects.Data` 参数化属性 put（raw Invoke），不是 Paste/剪贴板**

- **出处**：[^1]

**错误 mime 静默成功；必须断言 `Atoms.Count` 变化**

- **出处**：[^2]

**payload 用 bytes，不要 str（cp1252 窄化丢字符）**

- **出处**：[^1]

**一次插入一个 Group；Group 是寻址句柄；`Selection.Objects.Add` 是**静默 no-op**，要 `doc.Objects.Unselect()` + 逐个 `obj.Selected = True`**

- **出处**：[^2]

****绝不能对组范围内的 `Atoms`/`Bonds` 调 `.Item()`**，会让 ChemDraw 进程硬崩**

- **出处**：[^2]

**`app.ActiveDocument` 会间歇性返回 `None`，应按 `doc.name` 跟踪工作文档**

- **出处**：[^2]

**`Document.Undo()/Redo()` 对 COM 发起的编辑**返回 S_OK 但什么也不做****

- **出处**：[^2]

**逐个 `.Select()` 会**替换**选区而不是追加；多目标导出应 `Unselect()` 后逐单位 `Selected = True`**

- **出处**：[^1]


---

## 8. 未证实 / 待验证清单

- SaveAs 的 `W×resolution/36` 换算是**本机反推**（6 组采样自洽），不是 ChemDraw 文档语义；上线前应对目标版本再采一次点。
- `GetData` 第二参数无效果：可能是本机 26.1.0.6327 的行为，26.0.0.6141 是否相同未测。
- `Documents.Open` 静默失败的**根因**（无文档窗口 / 应用隐藏 / 其他模态状态）未证实；只证实了症状与「先 Add 再 Open」的可用性。
- 32 位 KingDraw 通道与本文无关，未涉及。

---

## 脚注来源

[^1]: `chemdraw_connector/bridge/_plumbing.py`（`_insert_raw`、`_insert_structure_units`），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/bridge/_plumbing.py （经 raw 读取，2026 年本次调研）
[^2]: `AGENTS.md`「Hard-won ChemDraw COM facts」节，https://github.com/MALeitch/live-chemdraw-mcp/blob/main/AGENTS.md
[^3]: `docs/com_typelib/README.md`（「never `Dispatch()`」的说明与 ChemDraw Professional 26.0.0.6141 验证版本），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/docs/com_typelib/README.md
[^4]: `chemdraw_connector/com/types.py`（`FORMAT_MIME`），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/com/types.py
[^5]: `chemdraw_connector/snapshots.py`（`export_cdxml_text`），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/snapshots.py
[^6]: `chemdraw_connector/bridge/_structure_io.py`（`insert_structure` / `export_image` / `export_cdxml` / `copy_to_clipboard`），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/bridge/_structure_io.py
[^7]: `chemdraw_connector/domain/reagent_text.py`（`build_text_cdxml`，最小可插入 CDXML 的现成范例），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/domain/reagent_text.py
[^8]: 本机实验脚本 `%TEMP%\cdprobe_types.py`、`cdprobe2.py`、`cdprobe9.py`、`cdprobe10.py`（未纳入仓库；数据全部抄自其 stdout）
