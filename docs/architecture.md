# 架构与边界：哪里能纯插件内解决，哪里必须调 ChemDraw / KingDraw

写于 2026-10-30。所有"必须/不必须"都附今天在本机跑出来的证据，不靠推测。

---

## 1. 三层架构

```
学生：一句话（中文）
   │
   ▼
DSH 会话 ──► agent（理解意图、选工具、组织回复）
   │  工具调用 chem_*
   ▼
┌─────────────────────────────────────────────────────┐
│ ① 插件层：~/.dsh/plugins/dsh-chem/      ≈ 3–5 MB     │
│    lib/index.js     20 个工具注册 + 参数校验         │
│    lib/bridge.js    本机 loopback 桥（37373-37376）  │
│    lib/client.js    右栏面板（产物画廊/收藏/批量）   │
│    core/chem/*.py   引擎源码（纯文本，跟仓库走）     │
│    data/*.json      规则表（PAINS/BRENK/Lilly/安全） │
│    skills/chem/     给 agent 的使用说明              │
└──────────────────────┬──────────────────────────────┘
                       │ 每次调用 spawn 一次子进程（无状态、可并发）
                       ▼
┌─────────────────────────────────────────────────────┐
│ ② 运行时层：%LOCALAPPDATA%\dsh-chem\runtime\   ≈300 MB │
│    独立 venv（可用 DSH 自带 Python 3.12 建）         │
│    RDKit 2026.09 / sklearn / scipy / PyMuPDF / PIL   │
│    ← 机器本地缓存，可随时删除重建，不进 git          │
└──────────────────────┬──────────────────────────────┘
        ┌──────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼              ▼
   ③a RDKit      ③b 本地 OCSR    ③c ChemDraw      ③d KingDraw
   纯计算/渲染   模型权重在       厂商软件         仅兜底
                 engines/        必需时才启动     默认关闭
```

## 2. 哪些能完全放在插件文件夹里

| 内容 | 位置 | 体量 | 进 git |
|---|---|---|---|
| 全部工具逻辑（JS + Python 源码） | `plugins/dsh-chem/` | ≈ 2 MB | ✅ |
| 规则表、模板、配色、期刊规格 | `plugins/dsh-chem/data/` | < 1 MB | ✅ |
| 面板前端 bundle | `plugins/dsh-chem/lib/client.js` | ≈ 40 KB | ✅ |
| 测试与验收脚本 | `plugins/dsh-chem/test/` | < 1 MB | ✅ |
| 文档与 skill | `plugins/dsh-chem/{docs,skills}/` | < 1 MB | ✅ |
| **Python 运行时（venv）** | `%LOCALAPPDATA%\dsh-chem\runtime\` | ≈ 300 MB | ❌ |
| **OCSR 模型权重** | `%LOCALAPPDATA%\dsh-chem\engines\` | ≈ 200 MB | ❌ |
| 产物（图/表/SDF） | `%LOCALAPPDATA%\dsh-chem\artifacts\` | 持续增长 | ❌ |
| 数据库查询缓存 | `%LOCALAPPDATA%\dsh-chem\cache\` | 小 | ❌ |
| ChemDraw / KingDraw | 用户已安装 | — | — |

**一句话：插件文件夹里放"怎么做"，机器本地放"用什么做"。**
如果把 venv 和模型塞进插件目录，仓库会从 2 MB 变成 500 MB，而且 `dsh plugin add link:` 指向的目录会变成可写状态库——升级、回滚、清理都会出问题。

## 3. 二十个工具 × 引擎

| 工具 | 纯插件内 | 需要厂商软件 |
|---|---|---|
| `parse` 名称→结构 | OPSIN + 内置表 | — |
| `parse` 图片→结构 | 本地 OCSR | — |
| `normalize` / `tautomer` / `check` | RDKit | — |
| `props` / `fingerprint` / `compare` | RDKit | — |
| `sheet` / `enum` / `db` / `table` | RDKit + pandas + SQLite | — |
| `ml` | sklearn 1.9（已装） | — |
| `assay` | scipy（已装） | — |
| `formula` / `stoich` / `characterize` | 纯 Python | — |
| `draw` PNG / SVG / PDF / TIFF | RDKit + PyMuPDF + PIL | — |
| `draw` **EPS** | ⚠️ 需加装 reportlab(2 MB) | 或 ChemDraw |
| `reaction_figure` / `mechanism` | RDKit + 自写 SVG | — |
| `enum` 立体枚举 / 3D | RDKit | — |
| `retro` 单步 | rdchiral（<1 MB） | — |
| `exam` / `office`(docx/xlsx) | python-docx / openpyxl（已装） | — |
| `lookup` | HTTP + 缓存 | —（联网） |
| **`edit`（.cdx / .cdxml）** | ❌ RDKit 无 CDXML 读写器 | **ChemDraw** |
| **`office`（Word/PPT 内嵌可编辑对象）** | ❌ OLE 复合文档 | **ChemDraw** |
| **结构→IUPAC 名** | ❌ 无本地实现 | **ChemDraw**（Name=Struct） |
| `parse` 的 .king/.kdx 读写 | ❌ 专有容器 | **KingDraw** |

## 4. 必须调 ChemDraw 的 5 件事（附依据）

1. **`.cdx` 读写**——二进制专有格式，没有开源解析器。
2. **`.cdxml` 读写**——实测 `hasattr(Chem,'MolToCDXML')` 与 `MolFromCDXML` **均为 False**，RDKit 没有 CDXML 通道。
3. **Word/PPT 里的"可双击编辑的化学对象"**——OLE 复合文档，只有 ChemDraw 注册的对象服务器能做。
4. **结构 → IUPAC 名**——OPSIN 只做名称→结构，反向没有本地开源实现。
5. **EPS 交付**（若期刊硬性要求）——纯本地要加装 reportlab；否则用 ChemDraw 或改用 PDF。

## 5. KingDraw 只做三件兜底

1. 没有 ChemDraw 的机器上读写 `.king` / `.kdx`；
2. 用它的引擎做 SMILES ↔ molfile 互转；
3. 出**预览级**图片（原始 100–300 px，不能投稿）。

其余场景不该调它——它的能力是 RDKit 的子集，但会开窗口。

## 6. 没有 ChemDraw 时怎么降级

| 需求 | 有 ChemDraw | 没有 ChemDraw |
|---|---|---|
| 画分子 | RDKit（默认）或 ChemDraw | RDKit |
| PNG/SVG/PDF/TIFF | 两条路都行 | RDKit + PyMuPDF + PIL |
| EPS | ChemDraw | 装 reportlab，或改交 PDF |
| `.cdx` | ✅ | ❌ 明确报"需要 ChemDraw" |
| Word 内嵌对象 | ✅ | 降级为插入 PNG + 附 SDF |
| 结构→名 | ✅ | 降级为返回 SMILES/InChI |
| 预览 | — | KingDraw（若有） |

## 7. 实测证据（2026-10-30 本机）

| 结论 | 证据 |
|---|---|
| RDKit 的 Cairo 后端**只出 PNG** | 对 `x.pdf/x.ps/x.eps` 三个扩展名写出的都是 7117 字节 PNG，头 `\x89PNG` |
| SVG 可转**向量** PDF，且不需新依赖 | PyMuPDF 1.28（已装）：`fitz.open(stream=svg, filetype='svg')` → 1630 字节 `%PDF`，1 页 400×300 pt，300 dpi 渲染 1667×1250 |
| TIFF 可以带 dpi 元数据 | PIL 12.3：`save(..., dpi=(1200,1200))` → 回读 `(1200.0, 1200.0)` |
| RDKit 无 CDXML | `MolToCDXML / MolFromCDXML` 均为 False |
| sklearn/scipy/PyMuPDF/docx/openpyxl 已装 | 版本实测见 `docs/capability-v3.md` |

## 8. 三种分发形态

| 形态 | 怎么做 | 适合 |
|---|---|---|
| **链接安装（推荐）** | `dsh plugin add link:<仓库路径>` | 开发与本机使用；改代码即生效 |
| 绿色便携包 | 打 zip，含 venv + 模型，解压即用 | 给不会装环境的老师 |
| 市场包 | 只含代码，首次启动自己建 venv | 公开发布 |

三者共用同一份源码，差别只在"运行时从哪来"。

## 9. 四种解法对比：纯 Skill / 纯 MCP / CC-Codex 插件 / 本方案

| 维度 | 纯 Skill | 纯 MCP | CC/Codex 插件+MCP | 本方案（DSH 原生插件） |
|---|---|---|---|---|
| 能真算吗 | ❌ 只能凭记忆 | ✅ | ✅ | ✅ |
| 能出可复现的图吗 | ❌ | ✅ | ✅ | ✅ |
| 能批量 300 个分子吗 | ❌ | ✅ | ✅ | ✅ |
| 跨宿主通用吗 | ✅ | ✅✅ | ✅（CC/Codex 各自适配） | ❌ 只 DSH |
| 需要额外常驻进程吗 | 否 | **是** | **是** | 否 |
| 断网可用吗 | ✅ | 看实现 | 看实现 | ✅ |
| 延迟 | 一次模型调用 | 跨进程/跨网 | 跨进程/跨网 | 进程内，毫秒 |
| 出错定位 | — | 四层链路 | 四层链路 | 一层 |
| 装一次体量 | ~0 | 服务+环境 | 服务+环境（已知有 760 MB 运行时的先例） | ≈300 MB |
| 生态曝光 | 极好（skill 市场） | 极好（官方 registry） | 好（marketplace） | 无（自用/自建） |
| 与界面整合 | 无 | 无 | 部分 | **强**（右栏面板、产物画廊、收藏） |
| 远程/多用户共享 | 否 | ✅ 强 | ✅ 强 | ❌ 单机 |

### 本方案真实的劣势

1. **绑定 DSH**：CC/Codex 用户装不上。要跨宿主，得另写一份 \`plugin.json\`+skill 或 MCP 壳（引擎可复用）。
2. **单机**：多用户/服务器场景，MCP 服务化明显更合适。
3. **无市场曝光**：没有 registry，发现靠人传。
4. **依赖 GUI 程序**：ChemDraw 那 4 个动作无法在无头 Linux 上跑（但目标场景本来就是 Windows 教学机）。

### 本方案真实优势

1. **一个进程**：没有服务要起、没有协议要维护、断网可用。
2. **确定性**：数值与图由 Python 算，不走模型记忆。
3. **界面与工具同栈**：产物目录共享，面板直接画廊预览、收藏、批量，这是 MCP 结构上做不到的。
4. **迁移成本低**：约 80% 代码是 Python 引擎，换宿主只需重写约 300 行胶水。

### 结论

- 目标是**"所有 agent 都能用"** → 选 MCP。
- 目标是**"这台教学机上给学生完整体验"** → 选本方案。
- **两者不互斥**：引擎同一份，MCP 只加一层薄壳即可对外。
