# CDXML 最小可打开 / 可插入子集（ChemDraw 26 实测）

> 实测环境：本机 ChemDraw `26.1.0.6327`（x64，ProgID `ChemDraw_x64.Application`），pywin32。
> 全部结论来自 `%TEMP%\cdprobe3.py`…`cdprobe8.py` 的实测输出（脚本未入仓），每条都标了观测值。
> 术语：**「可插入」** = `doc.Objects` 的 `Data("text/xml")` property-put 后 `doc.Atoms.Count` 增大；**「可打开」** = `app.Documents.Open(path)` 后 `Documents.Count` 增加。

## 0. 结论

**最小可用 CDXML 只有 169 字节**，本机「插入」与「打开」两条路都验证通过：

```xml nowrap
<?xml version="1.0" encoding="UTF-8" ?><CDXML><page><fragment><n id="3" p="100 100"/><n id="4" p="114.4 100"/><b id="5" B="3" E="4" Order="1"/></fragment></page></CDXML>
```

- 插入结果：`atoms 0->2  bonds=1  groups=1`；
- 打开结果：`docs 0->1`，新文档 `atoms=2 bonds=1`。
- **必需项**只有 6 个：`<CDXML>` / `<page>` / `<fragment>` / `<n id p>` / `<b id B E>`，以及 `B/E` 指向已存在的原子 `id`。
- **不必要**（逐条实测删掉后照样插入 + 打开）：XML prolog、`<!DOCTYPE>`、`CreationProgram`、`page@id`、`page@BoundingBox`、`fragment@id`、`fragment@BoundingBox`、原子/键的 `Z`、`AtomID`、`AS`、`BS`、`<colortable>`、`<fonttable>`。

> 与上游一致：live-chemdraw-mcp 现成可插入的文本 CDXML 也是这个量级 —— `<?xml …><!DOCTYPE …><CDXML><page><t p=… BoundingBox=…><s font size>…</s></t></page></CDXML>`，连 `id` 都不写（纯文本对象不需要引用）[^1]。

## 1. 逐属性必要性实验（本机，每个变体独立新建文档）

**a**

- **变体差异**：最小 + prolog + `id`
- **插入（`Objects.Data`）**：atoms 0→2, bonds 1
- **打开（`Documents.Open`）**：docs 0→1, atoms=2 bonds=1

**b**

- **变体差异**：加 `Z`/`Element="8"`
- **插入（`Objects.Data`）**：atoms 0→2
- **打开（`Documents.Open`）**：同上 ✅

**c**

- **变体差异**：加 `page@id` + `page@BoundingBox="0 0 540 720"`
- **插入（`Objects.Data`）**：atoms 0→2
- **打开（`Documents.Open`）**：✅

**d**

- **变体差异**：加 `fragment@BoundingBox`
- **插入（`Objects.Data`）**：atoms 0→2
- **打开（`Documents.Open`）**：✅

**e**

- **变体差异**：加 `<!DOCTYPE CDXML SYSTEM "https://static.chemistry.revvitycloud.com/cdxml/CDXML.dtd">`
- **插入（`Objects.Data`）**：atoms 0→2
- **打开（`Documents.Open`）**：✅（**离线无 DTD 也能开**）

**f**

- **变体差异**：加 `CDXML@CreationProgram="chem-draw-tool"`
- **插入（`Objects.Data`）**：atoms 0→2
- **打开（`Documents.Open`）**：✅

**g**

- **变体差异**：ChemDraw 自己导出的整页 CDXML（4 565 字节）
- **插入（`Objects.Data`）**：atoms 0→7 bonds=7
- **打开（`Documents.Open`）**：docs 0→1, atoms=7 bonds=7 ✅

**h**

- **变体差异**：**去掉全部 `id`**，`<b B="0" E="1">`
- **插入（`Objects.Data`）**：**atoms 0→0（静默失败，不抛异常）**
- **打开（`Documents.Open`）**：无新文档


**h 是最容易踩的坑**：`b` 的 `B`/`E` 必须引用真实存在的原子 `id`；不写 `id` 时 ChemDraw 不报错、不插入任何东西。

## 2. 结构编码规则（从 ChemDraw 自己的导回读，权威样例）

ChemDraw 26 导出一个「苯酚（芳香环用圆圈表示）」的整页 CDXML 时，`<page>` 之后是[^2]：

```xml nowrap
<fragment id="17" BoundingBox="245.59 343.12 294.41 376.88" Z="1">
 <n id="1" p="270.83 369.34" Z="2" AS="N" AtomID="1"/>
 ...
 <n id="7" p="283.30 347.74" Z="8" Element="8" NumHydrogens="1" NeedsClean="yes" AS="N" AtomID="7">
   <t p="279.41 351.64" BoundingBox="279.41 343.12 294.41 351.74" LabelJustification="Left" LabelAlignment="Left">
     <s font="3" size="10" color="0" face="96">OH</s></t></n>
 <b id="9" Z="9" B="1" E="2" Order="1.5" BS="N"/>
 ...
 <b id="15" Z="15" B="6" E="7" BS="N"/>
 <graphic id="18" BoundingBox="267.95 362.14 258.36 362.14" Z="16"
   GraphicType="Oval" OvalType="Circle"
   Center3D="258.36 362.14 0" MajorAxisEnd3D="267.95 362.14 0" MinorAxisEnd3D="258.36 371.73 0"/>
</fragment>
```

要点：

- **原子 `<n>`**：`id`（正整数，文档内唯一）、`p="x y"` 坐标。省略 `Element` 即碳；`Element="8"` 为氧（**原子序数，不是符号**）；`NumHydrogens` 显式氢数；`NeedsClean="yes"` 表示「交给 ChemDraw 重排」。
- **化学键 `<b>`**：`id`、`B`（begin，起原子 id）、`E`（end，终原子 id）、`Order`（缺省 = 1 单键）。
- **坐标单位 = point（1/72 in）**，**原点左上角、y 轴向下**：`page BoundingBox="0 0 540 719.75"` 就是 letter 纸在 72 dpi 下的点尺寸；本机导出文档的默认键长常量是 `BondLength="14.40"`（14.4 pt），我构造的六元环也正好用 14.4 pt 边长、一切正常。
- `Z` 只影响绘制/命中顺序（层叠），不影响化学。
- **回读时 ChemDraw 会重写 `id`**：我输入原子 id 1…6、键 id 7…12，回读得到原子 1…6、**键 8…13**（键 id 被上移）。所以生成器**不要**依赖「插入后 id 还是我写的那批」——插入后用 `doc.Atoms.Item(i).ID` / `GetData("text/xml")` 回读真实 id。上游同样记录「CDXML 节点 id 与 COM `Atom.ID` 完全一致」，即回读值就是 COM 侧可用的 id[^3]。

## 3. 芳香键：`Order="1.5"` 单独写会被静默降级

任务里问的「芳香键 B 值」，实测答案分两层：

1. `B` 是**起原子 id**（不是「芳香标记」），与 `E` 成对。
2. 芳香性由 `Order="1.5"` 表达，**但必须与一个 `<graphic GraphicType="Oval" OvalType="Circle">` 圆圈对象成对出现**，否则 ChemDraw 静默把它当单键。

本机 5 组对照（同一六元环，只改属性）：

| 变体 | 输入 | 回读 `GetData("text/xml")` |
|---|---|---|
| 1 | 6 条 `Order="1.5"` | `orders=[]`（**全丢，变单键**），circle=0 |
| 2 | 1 + 全节点 `Z` | `orders=[]`，circle=0 |
| 3 | 1 + 全节点 `Z`+`AtomID` | `orders=[]`，circle=0 |
| 4 | 1 + `fragment@BoundingBox` + 圆圈 `<graphic>` | `orders=['1.5'×6]`，circle=1 ✅ |
| 5 | 1 + `Z` + 圆圈 | `orders=['1.5'×6]`，circle=1 ✅ |

对照组：同一六元环写交替 `Order="2"`（Kekulé 式）→ 回读 `orders=['2','2','2','2','2','2']`，**完整保留**。

**工程建议**：
- 生成 CDXML 时**统一用 Kekulé 显式单/双键（`Order` 1/2）**，不要写 `1.5`；要画圆圈就自己补 `<graphic ... OvalType="Circle">`，否则视觉和化学都会错。
- 更省事的主线：让 RDKit 先 Kekulé 化再走 **molfile**（`chemical/x-mdl-molfile`）插入，ChemDraw 侧必然显式单双键；上游 `insert_structure` 的注释也明确这么做（`validate_smiles` 的输出是 Kekulized、无芳香圆圈）[^4]。
- 注意副作用：上游记录「圆圈式芳香环在 CDXML 里是 `Order=1` 的键 + 一个独立 `doc.Graphics` 圆对象」，做收缩/子结构时要额外处理这个圆[^3]。

## 4. 「打不开 / 插不进」的完整排查表（都实测过）

**`Documents.Open` 不抛错但 `Documents.Count` 不变**

- **根因**：应用当前没有任何文档窗口时的静默无效（本机 6 次连续复现；先 `Documents.Add()` 后同一文件即可打开）
- **处置**：先 `app.Visible = True` + `Documents.Add()`，再 Open；**用 `Documents.Count` 轮询判断成功**，不看返回值

**文件明明是自己刚导出的 CDXML，Open 也没反应**

- **根因**：同一路径已在 ChemDraw 里打开时，Open 只是激活既有文档，计数不变
- **处置**：换路径或先关闭同名文档；或改用 `Objects.Data` 插入

**插入后 `Atoms.Count` 不变**

- **根因**：① mime 字符串写错（返回 S_OK 但什么也不做）② `b` 的 `B/E` 指向不存在的 `id` ③ 原子缺 `id`
- **处置**：断言 `Atoms.Count`；用最小模板逐段加属性二分

**插进去了但分子是错的（芳香环全变单键）**

- **根因**：只写了 `Order="1.5"` 没有圆圈 graphic
- **处置**：见 §3，改用 Kekulé

**中文/特殊字符变 `?`**

- **根因**：payload 传了 `str`，BSTR→cp1252 窄化
- **处置**：`payload.encode("utf-8")` 后再 put；prolog 写 `encoding="UTF-8"`

**图片导出是空白**

- **根因**：对象在页面 `BoundingBox` 之外，`Selection.GetData` 返回合法全白 PNG
- **处置**：先判越界再导出（上游做法）[^5]

**对象插进来位置不对**

- **根因**：CDXML 导入的落点不可信
- **处置**：插入后显式 `Move(dx, dy)` 重排


## 5. 生成器建议（本工具后续实现用）

1. 优先路线：`SMILES → RDKit → Kekulé molblock → Objects.Data("chemical/x-mdl-molfile")`。最少属性、无需拼 XML、芳香性天然显式。
2. 需要精细控制（自定义标记、多片段、注释）时才生成 CDXML，且**只写必要属性**：
   ```xml
   <?xml version="1.0" encoding="UTF-8" ?>
   <CDXML><page><fragment>
     <n id="1" p="100 100"/><n id="2" p="114.4 100" Element="8" NumHydrogens="1"/>
     <b id="3" B="1" E="2" Order="1"/>
   </fragment></page></CDXML>
   ```
3. 生成后**必须**做原子数断言（`atoms_after > atoms_before`），否则静默失败会一路传到导出环节。
4. 落点：`fragment@BoundingBox` 可省，但要保证 `p` 落在 `page BoundingBox`（默认 `0 0 540 720`）之内，否则导图空白。

## 6. 复现

```bash
# 本机实验脚本（未入仓，随时可重跑）
export PYTHONIOENCODING=utf-8
PY="<user-home>/AppData/Local/Programs/Python/Python311/python.exe"
"$PY" "$TEMP/cdprobe3.py"   # 最小变体插入 + Open
"$PY" "$TEMP/cdprobe4.py"   # 逐属性 A/B（Open/Insert 双通道）
"$PY" "$TEMP/cdprobe8.py"   # 芳香 1.5 vs 圆圈 vs Kekulé
```

## 未证实

- `<fragment>` 是否真的必需（未测「`<n>` 直接挂 `<page>`」的写法）；上游文本 CDXML 用 `<t>` 直挂 `<page>` 是可行的，结构节点未经同法验证。
- `Order` 的完整取值域（4=配位键、`Display` 楔形键等）未逐值验证；本文只验证 1、2、1.5。
- `Order="1.5"` + 圆圈在 **molfile/SMILES 输入路径**下是否需要额外处理，未测。
- `Documents.Open` 静默失败的确切内部触发条件未证实（见 `docs/upstream-com-notes.md` §6）。

---

## 脚注来源

[^1]: live-chemdraw-mcp `chemdraw_connector/domain/reagent_text.py` 的 `build_text_cdxml`（可插入的最小 CDXML 实例），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/domain/reagent_text.py
[^2]: 本机 `doc.Objects.GetData("text/xml")` 导出的苯酚整页 CDXML（`%TEMP%\cdprobe_doc.cdxml`，4 159 字节，`CreationProgram="ChemDraw 26.1.0.6327"`）
[^3]: live-chemdraw-mcp `AGENTS.md`「Hard-won ChemDraw COM facts」（CDXML id == `Atom.ID`、圆圈式芳香环结构），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/AGENTS.md
[^4]: live-chemdraw-mcp `chemdraw_connector/bridge/_plumbing.py`（`_validate_input` 对 SMILES 做 Kekulé 化；`_insert_structure_units` 断言原子数），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/bridge/_plumbing.py
[^5]: live-chemdraw-mcp `chemdraw_connector/bridge/_structure_io.py`（`export_image` 的越界检查与空白 PNG 说明），https://github.com/MALeitch/live-chemdraw-mcp/blob/main/chemdraw_connector/bridge/_structure_io.py
