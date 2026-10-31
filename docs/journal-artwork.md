# 化学期刊 artwork 规范 → 可执行出图验收清单

> 抓取日期：全部为 **2026-10-29**（本机 `date` 输出 `2026-10-29 00:47`）。
> 采集方式：PDF 用 curl 下载 + PyMuPDF 抽文本；HTML 用 curl 抓原始页面后在本地正则提取（`pdf_do extract` 对本机这两个 PDF 返回空文本，改用 fitz，见文末复现）。
> 标注约定：**[硬性]** = 期刊明写 required/minimum/must；**[惯例]** = 期刊写 recommend/rule-of-thumb/通常；**[未证实]** = 本次没拿到原文，不做断言。

## 0. 四家一览（先看这张）

**线稿分辨率**

- **ACS**：**1200 dpi** [硬性]
- **RSC**：**≥600 dpi**（TIFF）[硬性]
- **Wiley**：投稿 600 dpi / 录用后 **600–1000 dpi** [硬性]
- **Elsevier**：**1000 dpi**（line art）[硬性]

**灰度图**

- **ACS**：**600 dpi** [硬性]
- **RSC**：未取得
- **Wiley**：300 dpi（images）
- **Elsevier**：300 dpi（halftone）/ 500 dpi（combination）

**彩色图**

- **ACS**：**300 dpi** [硬性]
- **RSC**：未取得
- **Wiley**：**300 dpi** [硬性]
- **Elsevier**：300/500/1000 按图类型

**单栏宽**

- **ACS**：≤**240 pt = 3.33 in** [硬性]
- **RSC**：未取得 [未证实]
- **Wiley**：小图 **80 mm 画布**或 ≥1800 px 宽 [硬性]
- **Elsevier**：**90 mm（255 pt）** [硬性]

**双栏宽**

- **ACS**：**300–504 pt（4.167–7 in）** [硬性]
- **RSC**：未取得 [未证实]
- **Wiley**：大图 **180 mm 画布**或 ≥1800 px 宽 [硬性]
- **Elsevier**：**190 mm（539 pt）**；另有 1.5 栏 **140 mm**、最小 **30 mm** [硬性]

**最大高度**

- **ACS**：**660 pt = 9.167 in**（含图注，每行注留 12 pt）[硬性]
- **RSC**：未取得
- **Wiley**：未写
- **Elsevier**：未写（并列高度上限）

**字体**

- **ACS**：**Helvetica 或 Arial** [硬性]
- **RSC**：**Arial** [硬性]
- **Wiley**：未写（只提「大字号更易读」）[惯例]
- **Elsevier**：未写字体族

**最小字号**

- **ACS**：**≥4.5 pt**（最终印刷尺寸）[硬性]
- **RSC**：未写
- **Wiley**：未写
- **Elsevier**：**7 pt** 正文 / **≥6 pt** 上下标 [惯例（原文自称 rule-of-thumb）]

**线宽**

- **ACS**：**≥0.5 pt** [硬性]
- **RSC**：未写
- **Wiley**：未写
- **Elsevier**：未写

**可接受格式**

- **ACS**：附录 2 未列格式清单 [未证实]
- **RSC**：**TIFF**；录用后补 **EPS/PDF** 原图 [硬性]
- **Wiley**：线稿 **EPS/PDF**；图像 **TIFF/PNG/EPS**；录用后另接受 GIF/JPG/TIF/PNG/WMF/DOC/PPT/PSD/AI/PS
- **Elsevier**：**TIFF/JPEG/EPS/PDF**（+Word/PPT/Excel），彩图优先 **RGB**

**文件命名**

- **ACS**：未写
- **RSC**：未写
- **Wiley**：**`Figure_1.tiff`**（只含 figure+序号，1 文件 1 图）[硬性]
- **Elsevier**：见其 File Naming 指南（本次未抓）

**文件大小**

- **ACS**：未写
- **RSC**：未写
- **Wiley**：**单个 <10 MB**；整包压缩 **<500 MB** [硬性]
- **Elsevier**：未写

**色彩空间**

- **ACS**：若最终黑白/灰度，不要交彩色 [硬性]
- **RSC**：未取得
- **Wiley**：未写
- **Elsevier**：优先 **RGB** [惯例]


---

## 1. ACS（以 JACS 版 Author Guidelines 为准）

来源：`https://researcher-resources.acs.org/publish/author_guidelines/pdf?coden=jacsat`
（PDF 首页脚注 "Last updated: October 05, 2026"；抓取 **2026-10-29**；29 页，本地 `%TEMP%\acs_jacs.pdf` 313 166 字节；**附录 2「Preparing Graphics」在 p27–28**）

原文（p27–28 连读）：

```nowrap
Appendix 2: Preparing Graphics
Resolution
Digital graphics pasted into manuscripts should have the following minimum resolutions:
  Black and white line art, 1200 dpi
  Grayscale art, 600 dpi
  Color art, 300 dpi
Size
Graphics must fit a one- or two-column format. Single-column graphics can be sized up to
240 points wide (3.33 in.) and double-column graphics must be sized between 300 and 504
points (4.167 in. and 7 in.). The maximum depth for all graphics is 660 points (9.167 in.)
including the caption (allow 12 pts. for each line of caption text).
Lettering should be no smaller than 4.5 points in the final published format. The text should
be legible when the graphic is viewed full-size. Helvetica or Arial fonts work well for
lettering. Lines should be no thinner than 0.5 point.
```

补充（p28–29）：彩色仅用于提升可读性；最终黑白/灰度的图**不要**交彩色；对比度建议按 WCAG（文字 4.5:1、非文字 3:1）[惯例]；封面图 ≥300 dpi、7.38 in × 8.13 in（18.73 × 20.64 cm）[硬性，但属于 cover art 不是正文图]。

**注意**：ACS 附录 2 只给分辨率/尺寸/字号/线宽，**没有给文件格式清单**；网上常说的「ACS 只要 TIFF/EPS/PDF」本次未在该 PDF 中找到原文 → 标 **[未证实]**。

## 2. RSC

主站页面 `https://www.rsc.org/journals-books-databases/author-and-reviewer-hub/authors-information/prepare-and-format/` **本次两次抓取均 HTTP 403**（curl 带完整浏览器头 + cookie 罐仍 403，返回体 3 445 B 的拦截页），因此 RSC 的栏宽/最大高度/线宽**没有拿到**，下文只写拿到原文的部分。

可取得的 rsc.org 域原文：`https://www.rsc.org/getContentAsset/4e8d0bf0-…/icm-reviews-guideline-template.docx?language=en`（抓取 **2026-10-29**，4 403 089 字节，Word 模板，`word/document.xml` 抽文本）：

```nowrap
Figures should be supplied as TIFF files, with a resolution of 600 dpi or greater.
For clear printing, please provide the original figures in eps or pdf version after accepted.
The font used in the figures should be Arial. Figure panels should be labeled as:
a b c (in bold), etc. on the top left hand corner; …
```
```
[Graphical abstract] … The figure should be a maximum size of 8 cm wide x 4 cm high,
supplied as TIFF files with a resolution of 600 dpi or greater.
```

即：**[硬性]** TIFF ≥600 dpi、字体 Arial、录用后补 EPS/PDF；**[硬性]** 图形摘要 ≤8 cm × 4 cm @600 dpi。
**单/双栏宽度、最大高度、最小字号、线宽 = [未证实]**（主站 403）。M2 若必须支持 RSC，建议按 600 dpi + 单栏约 8.3 cm 的行业通用值先实现，但**在文档里标为待核对**，不要写进验收判据。

## 3. Wiley

来源：`https://authors.wiley.com/asset/photos/electronic_artwork_guidelines.pdf`
（文档标题 *Guidelines for the Preparation of Figures*，页脚 "Updated 1 September 2016"；抓取 **2026-10-29**；7 页，540 461 字节；该 PDF 文本层可抽，但 `pdf_do extract` 返回空，用 PyMuPDF 抽通）

要点（Peer-Review 段 → Post-Acceptance 段）：

**线稿格式**

- **投稿评审阶段**：**EPS / PDF**（首选），其他标准格式可接受
- **录用后**：同左，另接受 GIF/JPG/TIF/TIFF/PNG/WMF/DOC/PPT/PSD/AI/PS

**图像格式**

- **投稿评审阶段**：**TIFF / PNG / EPS**
- **录用后**：同上

**线稿分辨率**

- **投稿评审阶段**：**600 dpi**
- **录用后**：**600–1000 dpi**（判据：在 80 mm 或 1800 px 宽下不放大仍可读）

**图像分辨率**

- **投稿评审阶段**：**300 dpi**
- **录用后**：**300 dpi**

**尺寸**

- **投稿评审阶段**：小图 **80 mm 画布** 或像素宽 **≥1800 px**；大图 **180 mm 画布** 或 ≥1800 px
- **录用后**：同左（小于此会被排版重排导致画质下降）

**单文件大小**

- **投稿评审阶段**：**<10 MB**
- **录用后**：同左

**整包大小**

- **投稿评审阶段**：压缩后 **<500 MB**
- **录用后**：同左

**命名**

- **投稿评审阶段**：**`Figure_1.tiff`**（只用 figure+序号，一图一文件）
- **录用后**：同左


另有两条实用性硬约束：**「图里同时含线稿与照片时，按线稿标准走」**；投稿阶段「拿不准就交 PDF」。

## 4. Elsevier

来源（两页，均抓取 **2026-10-29**，HTTP 200）：
- `https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing`
- `https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-formats-checklist`

原文（artwork-sizing 表格，逐字）：

```nowrap
Pixels = Resolution (DPI) × Print size (in inches)
300 DPI for halftone images; 500 DPI for combination art; 1000 DPI for line art.
72 points in one inch.

TARGET SIZE        Image width   Image width   Pixels@300dpi  Pixels@500dpi  Pixels@1000dpi
Minimal size       30 mm         85 pt         354            591            1181
Single column      90 mm         255 pt        1063           1772           3543
1.5 column         140 mm        397 pt        1654           2756           5512
Double column      190 mm        539 pt        2244           3740           7480
```

字号（同页，原文自称 rule-of-thumb → **[惯例]**）：「lettering … finished, printed size of **7 pt** for normal text and no smaller than **6 pt** for subscript and superscript」。

格式（artwork-formats-checklist，**[硬性]** 清单式）：TIFF（halftone/bitmap 首选）、JPEG、EPS（矢量首选）、PDF（矢量/文档首选）、Word/Excel/PowerPoint；彩图优先 **RGB** [惯例]；要求「插图为独立文件」「按期刊命名规范」。

**注意**：Elsevier 官网页面本身没有给"最大高度"，只给宽度档位；高度按内容自定，超宽会被缩小。

---

## 5. 硬性 vs 惯例（M2 判据只用「硬性」列）

**线稿 ≥1000 dpi 或矢量**

- **硬性来源**：Elsevier 1000 / ACS 1200
- **建议默认值**：**1200 dpi**（同时满足 ACS/Wiley 上限档）

**彩色 ≥300 dpi**

- **硬性来源**：ACS / Wiley / Elsevier
- **建议默认值**：300 dpi

**灰度 ≥600 dpi**

- **硬性来源**：ACS
- **建议默认值**：600 dpi

**宽度 ∈ {单栏, 双栏} 档位**

- **硬性来源**：ACS 240/300–504 pt；Elsevier 90/140/190 mm；Wiley 80/180 mm
- **建议默认值**：按目标刊取档；结构图默认单栏

**字号 ≥4.5 pt、字体 Arial/Helvetica**

- **硬性来源**：ACS（硬性）；Elsevier 7 pt（惯例）；RSC Arial（硬性）
- **建议默认值**：Arial，最终尺寸 ≥7 pt

**线宽 ≥0.5 pt**

- **硬性来源**：ACS
- **建议默认值**：0.5–0.6 pt（ChemDraw 默认 LineWidth=0.60，实测导出值）

**单文件 <10 MB**

- **硬性来源**：Wiley
- **建议默认值**：超限则降 dpi 或转 SVG/EPS

**命名 `Figure_N`**

- **硬性来源**：Wiley
- **建议默认值**：可配置

**RGB（非 CMYK）、无 alpha**

- **硬性来源**：Elsevier（RGB 惯例）
- **建议默认值**：输出 RGB

**对比度 WCAG 4.5:1**

- **硬性来源**：ACS（惯例/建议）
- **建议默认值**：可选检查


**键盘上要记住的换算**：1 in = 72 pt = 25.4 mm；ACS 单栏 240 pt ↔ 3.33 in ↔ 84.7 mm；Elsevier 单栏 90 mm ↔ 255 pt ↔ 3.54 in。两家单栏并不相同，**不要写死一个数**。

---

## 6. 怎么用已实测的接口满足它

### 6.1 已实测的 SaveAs 语义（来自 t1 的 cdprobe10 实测）

`doc.SaveAs(path, FormatObj, resolution, Width, Height)`，本机 ChemDraw 26.1.0.6327 实测：

- 输出像素宽 **px_w ≈ Width × resolution / 36**，像素高 **px_h ≈ Height × resolution / 36**（6 组采样，误差 <1%：W=1200,res=300 → 10034 实测 vs 10000 预测；W=600,res=150 → 2518 vs 2500；W=600,res=600 → 10068 vs 10000）。
- 输出长宽比 = 传入的 **W:H**（4 组一致），不是页面 540×720 的长宽比。
- **`FormatObj` 从 `Application.ExportDataTypes` 按 `Extension` 取**：`svg`→Item(47) `image/svg+xml`、`png`→Item(49/50)、`tif`→Item(51)、`eps`→Item(52/53)、`emf`→Item(43/44)、`jpg`→Item(46)。
- ⚠️ **本机 54 项导出类型里没有 PDF**（也无 `application/pdf`）→ 「交 PDF」这条路在 ChemDraw COM 上**不成立**，只能交 EPS（矢量）或位图。这是 M2 设计约束。
- ⚠️ **PNG 的 dpi 元数据恒为 144**（Pillow 读出 `(143.99, 143.99)`，与传入 resolution 无关，见 §7 实测表）→ 交稿前必须自己改写元数据，或改用 EPS/SVG。

### 6.2 反解公式（2026-10-29 由 t3 实测修正，旧公式是反的）

> **先读这一段，别用旧公式。** §6.1 的 `px_w ≈ Width × resolution / 36` 只在「页面够大、图形按自然尺寸铺开」时才成立。t3 的实测更严格：图形的尺寸由 `resolution/36` 像素每 point 决定，**`Width` 与 `Height` 只加画布空白**。同一个 66.2 pt 宽的分子，`Width` 传 78.2 / 234.7 / 309，导出**都是 550 px 宽**——分子一点没变大，只是纸变大了。

所以「给定像素反解 Width」方向错了，正确的是先量结构有多宽、再反解分辨率：

```
给定 目标像素宽 px_w、结构包围盒宽 content_width_pt：
    resolution = px_w * 36 / content_width_pt
    canvas_w   = content_width_pt + 2 * margin      # 只给边距，别指望它缩放
    canvas_h   = content_height_pt + 2 * margin
```

代码里已经实现，直接用，不要自己拼 `SaveAs` 参数：`artwork.resolution_for(px_w, content_width_pt)`、`artwork.canvas_pt(...)`、`cd_com.export_figure(width_mm=, dpi=)`。

另有一条硬上限：本机无论传 1500 还是 2183 dpi，导出都止步于 **2637 × 2191 px**（`artwork.MAX_EXPORT_PX`）。因此「1200 dpi 下 85 mm 宽（4016 px）」单次 `SaveAs` 达不到，`export_figure` 撞到上限会 warning 并按实际尺寸返回，不假装成功。

### 6.3 参数组合表（⚠️ 按 §6.2 的旧假设算出，只用来对照像素数量）

> 下表里的 `Width` 列**不要直接拿去用**。按 §6.2 的修正，它只决定画布多大，不决定图形多大；实际出图请用 `cd_com.export_figure(width_mm=, dpi=)`，它会先量结构宽度再反解分辨率。表格保留的价值是「目标像素宽」这一列——那是各刊档位换算出来的硬数字。

**Elsevier 单栏 line art（90 mm @1000 dpi）**

- **目标像素宽**：3543 px
- **res**：1000
- **Width**：**127.5**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：95.6

**Elsevier 单栏 halftone（90 mm @300 dpi）**

- **目标像素宽**：1063 px
- **res**：300
- **Width**：**127.6**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：95.7

**Elsevier 1.5 栏 line art（140 mm @1000）**

- **目标像素宽**：5512 px
- **res**：1000
- **Width**：**198.4**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：148.8

**Elsevier 双栏 line art（190 mm @1000）**

- **目标像素宽**：7480 px
- **res**：1000
- **Width**：**269.3**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：202.0

**ACS 单栏 line art（240 pt = 3.33 in @1200）**

- **目标像素宽**：4000 px
- **res**：1200
- **Width**：**120.0**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：90.0

**ACS 单栏 color（240 pt @300）**

- **目标像素宽**：1000 px
- **res**：300
- **Width**：**120.0**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：90.0

**ACS 双栏 line art（504 pt = 7 in @1200）**

- **目标像素宽**：8400 px
- **res**：1200
- **Width**：**252.0**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：189.0

**Wiley 小图（80 mm @600 dpi）**

- **目标像素宽**：1890 px（或 ≥1800 px）
- **res**：600
- **Width**：**113.4**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：85.0

**Wiley 大图（180 mm @600 dpi）**

- **目标像素宽**：4252 px
- **res**：600
- **Width**：**255.1**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：191.3

**Wiley 大图 line art（180 mm @1000 dpi）**

- **目标像素宽**：7087 px
- **res**：1000
- **Width**：**255.1**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：191.3

**RSC（≥600 dpi，宽度未定 → 先按 90 mm）**

- **目标像素宽**：2126 px
- **res**：600
- **Width**：**127.6**
- **Height（示例：按内容 h/w = 0.75，H = Width×0.75）**：95.7


（calibration 说明：ACS 240 pt 按 72 dpi 换算 = 3.33 in，@1200 dpi = 3.33×1200 = **4000 px** —— 与公式一致；Elsevier 表格自带像素数可直接当 px_w。）

### 6.4 落地要点（M2 实现时照这个顺序）

1. **先把结构单独放进一个干净文档**（`Documents.Add()` 或 scratch 文档），否则 `SaveAs` 导的是整页，长宽比由 W:H 强制拉伸，内容会被压缩变形。
2. 按目标刊取 `(res, Width, Height)`；线条/文字尺寸要在 **ChemDraw 侧按最终 pt 设置**（ACS 4.5 pt 是在最终印刷尺寸下的下限，缩放后字号会变）。
3. 导出后**必须**用 §7 的检查器复核真实像素与通道，必要时用 Pillow 修 dpi 元数据、去 alpha、存 TIFF（`compression="tiff_lzw"`, `dpi=(res,res)`）。
4. 矢量优先：SVG/EPS 交线稿可完全绕开 dpi 问题（ACS 1200 dpi 的本质要求就是"线稿别糊"）。

---

## 7. 怎么验证出图合格（可直接跑）

### 7.1 本机实测：ChemDraw 导出的 PNG 元数据有个坑

用 Pillow 12.3.0 读 t1 留下的 6 个 `SaveAs` 产物：

| 文件 | mode | 像素 | 元数据 dpi |
|---|---|---|---|
| sa_0.png（res=150, W=600） | RGBA | 2518×1893 | **(143.99, 143.99)** |
| sa_1.png（res=300, W=600） | RGBA | 5034×3784 | **(143.99, 143.99)** |
| sa_2.png（res=300, W=1200） | RGBA | 10034×7534 | **(143.99, 143.99)** |
| sa_3.png（res=600, W=600） | RGBA | 10068×7568 | **(143.99, 143.99)** |
| sa_4/5.png（res=300/0, W=H=0） | RGBA | 442×316 | **(143.99, 143.99)** |

结论：**像素随 resolution 变，元数据 dpi 恒为 144**。所以「按 dpi 元数据判合格」的检查器会把 ChemDraw 的直接产物全部判错（10034 px 标 144 dpi ⇒ 按元数据算物理宽 69.7 in）。两条出路：① 以**像素宽度 + 目标 dpi 声明**为判据，交付时用 Pillow 把 dpi 元数据写成真实值；② 交矢量（EPS/SVG）。

### 7.2 检查片段（可直接跑，未进生产代码）

```python
# check_artwork.py —— 出图验收检查器（研究用，不是生产代码）
from PIL import Image

SPECS = {
    # journal: (最低 dpi, 单栏像素宽, 双栏像素宽, 是否禁止 alpha)
    "acs":       dict(dpi=1200, single_px=4000, double_px=8400, allow_alpha=False),
    "rsc":       dict(dpi=600,  single_px=None,
                      double_px=None, allow_alpha=False),  # 栏宽未证实
    "wiley":     dict(dpi=600,  single_px=1800, double_px=None, allow_alpha=False),
    "elsevier":  dict(dpi=1000, single_px=3543, double_px=7480, allow_alpha=False),
}

def check(path, journal, simulate_dpi=None):
    """simulate_dpi：假定该图将按此 dpi 印刷（用于绕开 ChemDraw 恒 144 的元数据）。"""
    spec = SPECS[journal]
    im = Image.open(path)
    px_w, px_h = im.size
    meta_dpi = im.info.get("dpi")
    probe = simulate_dpi or (round(meta_dpi[0]) if meta_dpi else None)
    problems, notes = [], []

    # 1) 有效分辨率：按声明的印刷 dpi 反算物理宽度是否落在栏位
    if probe:
        physical_in = px_w / probe
        notes.append(
            f"按 {probe} dpi 印刷 => 物理宽 {physical_in:.2f} in / "
            f"{physical_in*25.4:.1f} mm")
        if probe < spec["dpi"]:
            problems.append(f"dpi {probe} < 要求 {spec['dpi']}")
        if spec["single_px"] and px_w < spec["single_px"]:
            problems.append(f"像素宽 {px_w} < 单栏最低 {spec['single_px']}")
        if spec["double_px"] and px_w > spec["double_px"]:
            problems.append(f"像素宽 {px_w} > 双栏上限 {spec['double_px']}（会被期刊缩小）")

    # 2) PNG 的 pHYs 元数据是否与目标 dpi 一致（ChemDraw 恒 144，必须自己改写）
    if meta_dpi and abs(meta_dpi[0] - (probe or 0)) > 1:
        problems.append(f"元数据 dpi {meta_dpi[0]:.0f} != 目标 {probe}（需 Pillow 重写）")

    # 3) 通道数：期刊普遍要 RGB、不要 alpha
    if im.mode not in ("RGB", "L") and not spec["allow_alpha"]:
        problems.append(f"mode={im.mode}（含 alpha，应转 RGB）")

    # 4) 长宽比提示：结构图通常一栏宽、纵横比别太怪
    notes.append(f"像素 {px_w}×{px_h}，长宽比 {px_h/px_w:.2f}")

    return {"file": path, "journal": journal, "px": im.size, "mode": im.mode,
            "meta_dpi": meta_dpi, "problems": problems, "notes": notes}

# 交付前修正：写回真实 dpi + 去 alpha + 存 TIFF（Wiley/Elsevier 首选）
def normalize(path, out_tiff, dpi):
    im = Image.open(path).convert("RGB")
    im.save(out_tiff, dpi=(dpi, dpi), compression="tiff_lzw")
    return out_tiff

if __name__ == "__main__":
    for f, journal, sim in [
        # W=1200,res=300 => 10034 px，按 300 dpi 印刷 => 33.4 in，超宽
        ("sa_2.png", "elsevier", 300),
        ("sa_2.png", "acs", 300),
    ]:
        r = check(f, journal, simulate_dpi=sim)
        print(f, journal, "=>", r["problems"] or "PASS(宽度/通道)", r["notes"])
```


**实测运行结果**（`%TEMP%\check_artwork.py`，跑在 t1 留下的真实 SaveAs 产物上）：

```
sa_2.png elsevier => ['dpi 300 < 要求 1000', '像素宽 10034 > 双栏上限 7480',
                      '元数据 dpi 144 != 目标 300（需 Pillow 重写）', 'mode=RGBA（含 alpha，应转 RGB）']
                     ['按 300 dpi 印刷 => 物理宽 33.45 in / 849.5 mm', '像素 10034×7534，长宽比 0.75']
sa_0.png elsevier => ['dpi 150 < 要求 1000', '像素宽 2518 < 单栏最低 3543', …]
normalized: sa_2_fixed.tif RGB (10034, 7534) (300.0, 300.0)   # 1 555 964 字节，dpi 已改写
```

这组输出同时暴露了 SaveAs 的真实语义：**W/resolution 调大只放大像素，不会把物理尺寸"变成一栏"** —— 10034 px 按 300 dpi 印刷是 33.45 in（849 mm），远超任何期刊版面。所以 M2 必须先定「目标像素 = 目标栏宽(mm)×dpi/25.4」，再用 §6.2 的 `Width = px_w × 36 / res` 反解，不能凭感觉给 W。

要点：**判据用「像素宽度 + 打算按多少 dpi 印刷」**，不要只信元数据（ChemDraw 恒 144）；同时检查 `mode`（必须是 RGB/L）与文件大小（Wiley <10 MB）。

### 7.3 还可以叠加的机器检查

- 文件大小：`os.path.getsize(path) < 10 * 1024 * 1024`（Wiley 硬性）。
- 空白边距：Pillow `Image.getbbox()` 判断四周是否被裁到内容（SaveAs 输出常带白边，交稿前裁掉更稳）。
- 矢量通道：SVG/EPS 用文本检查 `<svg width=…>` 或 EPS `%%BoundingBox` 换算 pt→栏宽即可，无 dpi 概念。

---

## 8. 未证实 / 后续要补

1. **RSC 单双栏宽度、最大高度、最小字号、线宽**：主站 prepare-and-format 两次抓取均 403，未取得 → 不要写进验收判据。
2. **ACS 允许的文件格式清单**：附录 2 未列，未证实。
3. **Elsevier 最大高度**：页面只给宽度档位，未给高度上限。
4. **Wiley 字号/线宽下限**：文档未给数值，只有「字要大」。
5. **SaveAs 的 W/H 是否严格"铺满"内容还是"等比留白"**：仅 6 组采样、单一小分子文档，未证实；M2 需在真实结构上再验。
6. **ChemDraw 元数据恒 144 dpi** 只在本机 26.1.0.6327 上验证；其他版本未测。
7. 本机 **ExportDataTypes 无 PDF**，因此「按 Elsevier 首选交 PDF」需另找路径（如 ChemDraw 打印驱动或先出 EPS 再转），未实现也未证实。

---

## 9. 复现命令

```bash nowrap
cd /c/Users/<user>/AppData/Local/Temp
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# ACS JACS 指南 PDF（附录2 在 p27-28）
curl -sSL -A "$UA" -o acs_jacs.pdf "https://researcher-resources.acs.org/publish/author_guidelines/pdf?coden=jacsat"
# Wiley 图形规范 PDF（7 页）
curl -sSL -A "$UA" -o wiley_artwork.pdf "https://authors.wiley.com/asset/photos/electronic_artwork_guidelines.pdf"
# Elsevier 两页（HTML 全文抓下来再正则）
curl -sSL -A "$UA" -o els_sizing.html "https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing"
curl -sSL -A "$UA" -o els_formats.html "https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-formats-checklist"
# RSC（主站 403；用 rsc.org 上的期刊模板 docx）
curl -sSL -A "$UA" -o rsc_template.docx "https://www.rsc.org/getContentAsset/4e8d0bf0-2eb8-4bff-9c6f-d6db33efdfa8/f4c91d86-ac3e-4675-bdf3-f8325ded9710/icm-reviews-guideline-template.docx?language=en"

# PDF 抽文本（pdf_do extract 对这两个 PDF 返回空，改用 PyMuPDF）
export PYTHONIOENCODING=utf-8
"<user-home>/AppData/Local/Programs/Python/Python311/python.exe" -c "
import fitz, re, sys
d = fitz.open('acs_jacs.pdf')
print(re.sub(r'\s+', ' ', d[26].get_text())[-1200:])"
```

## 脚注来源

[^1]: ACS，JACS Author Guidelines（PDF，页脚 `Last updated: October 05, 2026`；附录 2「Preparing Graphics」p27–28），https://researcher-resources.acs.org/publish/author_guidelines/pdf?coden=jacsat ，抓取 2026-10-29
[^2]: RSC 期刊作者模板（ICM Reviews guideline template，`.docx`，rsc.org 域），https://www.rsc.org/getContentAsset/4e8d0bf0-2eb8-4bff-9c6f-d6db33efdfa8/f4c91d86-ac3e-4675-bdf3-f8325ded9710/icm-reviews-guideline-template.docx?language=en ，抓取 2026-10-29；主站 prepare-and-format 页当日两次 403
[^3]: Wiley，*Guidelines for the Preparation of Figures*（页脚 `Updated 1 September 2016`，7 页），https://authors.wiley.com/asset/photos/electronic_artwork_guidelines.pdf ，抓取 2026-10-29
[^4]: Elsevier，Artwork sizing，https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing ，抓取 2026-10-29
[^5]: Elsevier，Artwork formats checklist，https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-formats-checklist ，抓取 2026-10-29
[^6]: 本机实测（t1 交接 + 本次复核）：`doc.SaveAs` 尺寸反推 `px ≈ W × resolution / 36`、`ExportDataTypes` 54 项无 PDF、PNG 元数据恒 144 dpi —— 见 `docs/upstream-com-notes.md` §3 与本次 `%TEMP%\sa_*.png` 的 Pillow 读数
