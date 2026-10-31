# dsh-chem 0.2.0 发布说明

发布日期：2026-10-30　|　上一版：0.1.0（本次是首次对外发布）

## 这一版有什么

15 个 `chem_*` 工具，全部带自动化断言，覆盖「结构识别 → 体检 → 出图 → 性质 → 批量表 → 本地库 →
建模 → 逆合成 → 谱图核对 → 教学批改 → Word/PPT 交付 → 厂商通道」。

装法变了：从「工作区里 link 一份源码」改成**自包含复制**——`tools/install_plugin.py` 把引擎、
插件 JS、依赖桩一起复制进 `~/.dsh/plugins/dsh-chem`，运行时数据放在 `%LOCALAPPDATA%\dsh-chem`。
工作区清空后仍然可用（实测：把 `bin/`、`core/`、`dsh-plugin/` 三个目录改名移走后，15 个工具照样 17/17 通过）。

## 这一版修了什么（都是「工具面参数名 ≠ 引擎参数名」这一类静默失败）

| 症状 | 原因 | 现在的行为 |
|---|---|---|
| 面板一直显示「ChemDraw 不可用」 | 面板读的是桥根本没发的 `state.channels`；旧逻辑还指向已删除的 `bin/cli.py` | 面板重写，只读桥真实发出的字段，徽章改报引擎状态 |
| `chem_vendor` 任何动作都返回 `no-such-file` | 工具面发 `do`，引擎只认 `action`，一律落到默认 `info` | 加别名；`do=probe` 实测探测 ProgID |
| EPS / 预览「需要 ChemDraw」其实装好了 | 探测只认 32 位 `ChemDraw.Application` | 认 `ChemDraw_x64.Application`，实测 EPS 5 038 B、预览 3 096 B |
| `chem_office target=pptx` 出来是 Word | 引擎只认 `action`，默认 `docx` | 认 `target`；文档不再落进插件目录 |
| `chem_parse` 把 aspirin 当成 7 残基肽 | 自动判定先试残基串再查名字 | 顺序改为 SMILES → 名字 → 残基串；字典补 27 组常用名 |
| `CCO` 这种 SMILES 被判成「查不到这个名字」 | SMILES 自动识别要求含 c/n/o/s/p | 放宽到任意 ASCII token 交给 RDKit 试解析 |

## 验证数字（本机：Windows 11 x64、Python 3.13.5、RDKit 2026.09.1、ChemDraw 26.1.0.6327）

| 层 | 结果 |
|---|---|
| 引擎套件 | 15/15，364 条断言 |
| 用户场景 | 9 个场景 / 32 条检查 |
| 插件契约 | 94/94 |
| 面板桥 / 接线 / 面板契约 / 安装副本 | 14 / 10 / 14 / 10 |
| 仓库体检 | 12 项 0 失败（245 个 tracked 文件） |
| 脱敏扫描 | tracked 文件 0 命中 |

## 已知限制

- 二进制 `.cdx` 写不出（ChemDraw 26.1 的 `SaveAs` 对 cdx 静默空操作），会明确返回失败并建议 cdxml。
- Word/PPT 里没有可编辑的 ChemDraw OLE 对象，目前是 600 dpi PNG + 图注。
- NMR 是规则估算（1H ±0.3 ppm，13C 只给区间），输出里每次都写明。
- 逆合成是 13 条教学级断键模板，不是全合成搜索。
- MolVec 在本工具自绘 PNG 上会崩，所以单引擎结果一律标「需人工确认」。
- KingDraw 通道能探测但未接通（本机没有可验证的 ProgID）。
- 装完或升级后要重开 DSH，客户端面板才刷新。

## 升级注意

从 0.1.0 起的旧接线（`link:` 指向工作区）需要换掉：先 `python tools/install_plugin.py --remove`，
再 `python tools/install_plugin.py`，最后确认 `~/.dsh/profiles/desktop/node_modules/dsh-chem` 存在。
