# 误用目录（misuse catalog）

误用注入回归的对象不是"按文档用会不会出错"，而是**人在没读文档时的第一反应**：
空参数、写错路径、把 `kd` 的写法套到 `cd` 上、输入超长、连着跑两次、半路 Ctrl-C。

**判据（本目录里"可接受"的含义）**：退出码非 0；JSON 信封里 `ok=false` 且带错误码与非空
message；全程没有 Python traceback；不留残留进程。**返回 `ok=true` 但其实什么都没做，或让
用户看到 traceback，都算失败。**

一条命令重跑全部用例（14 项，含 cd/kd 两通道，约 35 秒）：

    export PYTHONIOENCODING=utf-8
    cd "$REPO"
    runtime/py32/python.exe test/test_misuse.py

## 总表

<!-- wide-table-ok: 参考表，窄屏横向滚动即可 -->
| # | 误用 | 复现命令（节选） | 修前 | 修后 / 现状 | 判定 | 状态 |
|---|---|---|---|---|---|---|
| 1 | 空 SMILES | `identity '' --json` | `ok:true`、`canonical_smiles:""`、rc=0（**静默成功**） | `E06 empty SMILES`、rc=1 | 修前失败 | 已修 |
| 2 | 空 SMILES 走 KingDraw | `kd mol ''`、`kd formula --smiles ''` | 前者 E06；后者 `TypeError` traceback | 两者都 E06，message 来自引擎 | 修前失败 | 已修 |
| 3 | 完全不给参数 | `kd formula` / `kd to3d` / `kd layout` | `TypeError: expected str, bytes or os.PathLike object, not NoneType`（cli.py:112） | `E06 A molfile path is required` + hint | 修前失败 | 已修 |
| 4 | 非法结构 | `identity hello --json` | E06 | E06 | 可接受 | 现状 |
| 5 | 非法结构（ChemDraw 通道） | `cd draw not-a-smiles` | 无 traceback，stdout 是 `E06 The structure could not be parsed`，rdkit 解析日志走 stderr | 同左 | 可接受（stderr 噪声，不是崩溃） | 现状 |
| 6 | 中文路径 | `kd mol … --out 测试目录/分子.mol`；`kd save … --out 测试目录/分子.king`；`cd draw … --out 测试目录/画.png` | 全部真实落盘（963 B / 963 B / 8339 B） | 同左 | 可接受 | 现状（回归保护） |
| 7 | 指错 KingDraw 目录 | `doctor kd --kingdraw-home D:/nope/nowhere` | **静默回退**到 `D:\tool\KingDraw`，`available:true` | `warning: … no silent fallback`，通道不可用，rc=1 | 修前失败 | 已修 |
| 8 | 缺装软件（32 位跑 cd） | `cd doctor`（py32） | E08，message 说明 32 位 | 同左 | 可接受 | 现状（回归保护） |
| 9 | 位宽误用（64 位跑 kd） | `kd mol c1ccccc1`（py64） | E04，message 说明 x86/x64 | 同左 | 可接受 | 现状（回归保护） |
| 10 | 超长输入（4000 原子 SMILES） | `identity "$(printf 'C%.0s' {1..4000})" --json`；`cd draw` 同上 | **进程被杀**：exit `3221225725`（STATUS_STACK_OVERFLOW），stdout/stderr 全空 | 两通道都 `E06 SMILES is longer than 2000 characters`，rc=1 | 修前失败 | 已修 |
| 11 | 超长文件名 | `kd open test/out/aaa…(200).mol` | E06 不存在 | E06，附带实际路径 | 可接受 | 现状 |
| 12 | 不存在的文件 | `kd king /nope.king`、`kd smiles /nope.mol` | `FileNotFoundError` traceback | `E06 Input file does not exist`，detail 带路径与 git-bash 改写提示 | 修前失败 | 已修 |
| 13 | 参数冲突（无动作） | `cd modify` | 先连 ChemDraw，再答 `E01 There is no document open to edit`（**指错原因**） | `E06 cd modify needs an edit action` + 动作清单，不碰 ChemDraw | 修前失败 | 已修 |
| 14 | 两个入口写法混用 | `cd export --out a.png`（`cd figure` 同） | argparse `unrecognized arguments: --out`，rc=2，不提示位置参数写法 | 两种写法都成功且产物字节数相同；都不给 → `E06 … needs a destination file` | 修前失败 | 已修 |
| 15 | 扩展名省略 | `cd export test/out/noext`；`kd save … --out noext`；`kd export … --out noext` | 两通道都自动补 `.png`/`.king` | 同左（行为一致） | 可接受 | 现状（回归保护） |
| 16 | 重复调用（同路径两次 save） | `kd save x.mol --out 重复.king` ×2 | 两次都 ok，第二次**覆盖**（963 B → 963 B） | 覆盖仍是默认；新增 `--no-overwrite` → `E06 Output already exists` | 可接受（行为已写明） | 已明确 + 增可选参数 |
| 17 | 半路中断（Ctrl-C） | 起 `kd export`，4 秒后 SIGTERM | CLI 死掉后 KingDraw 仍在（GUI 程序不该被连坐），实测可正常关闭，无卡死 | 断言：残留实例可关闭，清理后进程表回到基线 | 可接受（有断言保护） | 现状 |
| 18 | 参数太少（argparse 级） | `kd match a`、`kd smiles` | argparse rc=2 + usage | 同左 | 可接受 | 现状 |

## 逐条：复现命令 + 修前输出 + 修后输出

判据要求"每发现一个问题，必须同时留下复现命令 + 修前输出 + 修后输出"，下面每条按此记录。
修前输出取自注入探针当时的原始回显。

命令写法随记录时代而定：**修前那一侧按当时真实用法写**（那时 `--json` 还不存在，硬加只会得到
`unrecognized arguments`，反而把真正的现场挡住）；**修后要引结果信封的，一律加 `--json`**——
默认输出已是人读摘要（见 presentation-audit.md §9），信封不是默认形态。

### 1. `identity ''` 静默成功

    $ python bin/cli.py identity ''
    {"ok": true, "input": "", "canonical_smiles": "", "inchikey": "", "formula": "", ...}
    rc=0

    $ python bin/cli.py identity '' --json        # 修后
    {"ok": false, "failure": {"code": "E06", "message": "empty SMILES",
     "hint": "Pass a SMILES string, e.g. c1ccccc1O", "detail": "''", ...},
     "canonical_smiles": null, ...}
    rc=1

修法：`identity.identify()` 在交给 rdkit 之前判空。人类可读形态（不带 `--json`）输出
`note : empty input: nothing to identify`。

### 2 & 3. `kd formula` / `kd to3d` / `kd layout` 的 TypeError

    $ runtime/py32/python.exe bin/cli.py kd formula
    Traceback (most recent call last):
      ...
      File "D:\...\core\chemdraw_tool\cli.py", line 112, in cmd_kd
        else kd.get_mol_formula(_read_text(args.mol)))
    TypeError: expected str, bytes or os.PathLike object, not NoneType
    rc=1

根因两处：`_read_text(None)` 无保护；且 `args.smiles` 用真值判断，`--smiles ''` 被当成
"没给"，于是掉进读文件的空路径。修后：

    $ runtime/py32/python.exe bin/cli.py kd formula --json
    {"ok": false, "failure": {"code": "E06", "message": "A molfile path is required",
     "hint": "Give --mol <file.mol>, or --smiles <SMILES>", ...}}
    rc=1

    $ runtime/py32/python.exe bin/cli.py kd formula --smiles '' --json
    {"ok": false, "failure": {"code": "E06", "message": "getFormula returned nothing", ...}}
    rc=1

修法：`cli.py` 新增 `_InputError`，`_read_text`/`_read_bytes` 对其抛错、`cmd_kd` 统一转成
`Result(ok=False)`；`args.smiles is not None` 取代真值判断（空串交给引擎判定）。

### 4 & 5. 非法结构：两通道都给结构化错误

    $ python bin/cli.py identity hello --json
    {"ok": false, "failure": {"code": "E06", "message": "rdkit could not parse this SMILES", ...}}
    rc=1

    $ python bin/cli.py cd draw not-a-smiles --json
    {"ok": false, "failure": {"code": "E06", "stage": "draw",
     "message": "The structure could not be parsed",
     "detail": "RDKit could not parse 'not-a-smiles'", ...}}
    rc=1
    （stderr 上是 rdkit 自己的 "[02:52:53] SMILES Parse Error: …"，不是 traceback）

### 6. 中文路径必须真的落盘

    $ runtime/py32/python.exe bin/cli.py kd save 测试目录/分子.mol --out 测试目录/分子.king --json
    {"ok": true, "data": {"out": "…\测试目录\分子.king", "bytes": 963, "atoms": 7, ...}}
    $ python bin/cli.py cd draw c1ccccc1O --out 测试目录/画.png --json
    {"ok": true, "data": {..., "export": {"data": {"path": "…\测试目录\画.png", "bytes": 8339}}}}
    rc=0

ChemDraw 的 `SaveAs` 对非 ASCII 路径是**静默空操作**（见 `cd_com.py` 顶部第 2 条实测），
所以 `export()` 先落到 ASCII 暂存目录再搬过去并回读确认；`kd save` 则重新读回 `.king` 校验
原子数。两条通道都不靠"调用没报错"来判断成功。

### 7. `--kingdraw-home` 指向不存在的目录

    $ runtime/py32/python.exe bin/cli.py doctor kd --kingdraw-home D:/nope/nowhere   # 修前
    home    : D:\tool\KingDraw
    available: True
    rc=0

    $ runtime/py32/python.exe bin/cli.py doctor kd --kingdraw-home D:/nope/nowhere   # 修后
    warning  : --kingdraw-home 'D:/nope/nowhere' does not contain GRDKitDll.dll; the channel is unavailable (no silent fallback)
    available: False
    rc=1

修法：`doctor/kd.py` 与 `adapters/kd_native.py` 的 `find_home()` 对**显式命名**的目录（参数或
`KINGDRAW_HOME`）只认或不认，不再退回默认安装。"我指了 X 却用了 Y"是最难发现的一类静默错误。

### 10. 4000 原子 SMILES：进程被杀（最严重）

    $ python bin/cli.py identity "$(printf 'C%.0s' {1..4000})"
    （无任何输出）
    rc=3221225725          # 0xC00000FD STATUS_STACK_OVERFLOW

    $ python bin/cli.py cd draw "$(printf 'C%.0s' {1..4000})"
    （无任何输出）
    rc=3221225725

复现矩阵（`test/probe_long_smiles.py`，每档在独立子进程里跑）：

    len=2000  rc=0            atoms 2000 canon 2000
    len=3000  rc=3221225725
    len=4000  rc=3221225725

根因：rdkit 的 canonical SMILES 写出器沿分子图递归，2000–3000 原子之间爆栈；异常抓不到，进程
直接消失——用户连"为什么"都拿不到。修法：`core/chemdraw_tool/limits.py` 定义
`MAX_SMILES_CHARS = 2000`（一个字符最多一个原子）与 `MAX_ATOMS_CANONICAL = 1000`；
`identity.py` 先按长度、再按原子数拒绝，`cd_com.py` 的 `draw_smiles`/`modify --replace`
也在解析前拒绝。修后：

    $ python bin/cli.py identity "$(printf 'C%.0s' {1..4000})" --json
    {"ok": false, "failure": {"code": "E06", "message": "SMILES is longer than 2000 characters",
     "detail": "4000 characters, limit 2000", ...}}
    $ python bin/cli.py cd draw "$(printf 'C%.0s' {1..4000})"
    {"ok": false, "failure": {"code": "E06", "message": "SMILES is longer than 2000 characters", ...}}
    rc=1

代价是千原子以上的分子不再能识别（远超本工具"画结构"的场景），换来的是确定答案而不是消失。

### 12. 不存在的文件

    $ runtime/py32/python.exe bin/cli.py kd king /nope.king          # 修前
    Traceback (most recent call last):
      ...
    FileNotFoundError: [Errno 2] No such file or directory: 'C:/Program Files/Git/nope.king'
    rc=1

    $ runtime/py32/python.exe bin/cli.py kd king /nope.king          # 修后
    {"ok": false, "failure": {"code": "E06", "message": "Input file does not exist",
     "detail": "not a file: /nope.king",
     "hint": "Check the path; on Windows a leading / is rewritten to the git-bash root", ...}}
    rc=1

detail 里写的是**我们实际收到的路径**；`/nope.king` 被 git-bash 改写成
`C:/Program Files/Git/nope.king` 是 shell 行为，hint 直接点出这个坑。

### 13. `cd modify` 不给动作

    $ python bin/cli.py cd modify                                   # 修前
    {"ok": false, "failure": {"code": "E01", "message": "There is no document open to edit",
     "hint": "Draw one first (cd draw), or pass --replace SMILES to set the content"}}
    （并且真的去连了 ChemDraw）

    $ python bin/cli.py cd modify                                   # 修后
    {"ok": false, "failure": {"code": "E06", "message": "cd modify needs an edit action",
     "hint": "Pass --replace SMILES, --clear, --delete-atom N or --delete-object N",
     "detail": "none of --replace/--clear/--delete-atom/--delete-object was given"}}
    （不连 ChemDraw，失败在参数层）

### 14. `cd export --out` 与 `kd export --out` 的两种写法（队长回报）

    $ python bin/cli.py cd export --out test/out/nope.png
    usage: chem-draw-tool cd export [-h] [--smiles SMILES] [--format FORMAT] ...
    chem-draw-tool: error: unrecognized arguments: --out
    rc=2

`kd` 那一半 6 个命令全用 `--out`，`cd` 只有 `draw/read/modify` 用 `--out`，而
`export/figure` 是位置参数；学会了 `kd export --out a.png` 再写 `cd export --out a.png`
必然撞墙，而 argparse 只会说"多了个参数"，不会说"这里要位置参数"。修法（向后兼容，位置参数
仍是文档写法）：

    p_cdexp.add_argument('out', nargs='?', help='destination file; the format extension is added')
    p_cdexp.add_argument('--out', dest='out_flag', metavar='FILE', help='same destination, --out spelling')

`cd figure` 同样处理；两者都不给时给 `E06 cd export needs a destination file` + 两种写法提示。
修后实测产物字节数完全一致：

    cd export pos  -> …\test\out\spell_pos.png   bytes=8339
    cd export flag -> …\test\out\spell_flag.png  bytes=8339
    cd figure pos  -> …\test\out\spell_pos.png   bytes=25855
    cd figure flag -> …\test\out\spell_flag.png  bytes=25855

### 15. 扩展名省略：两通道行为一致

    cd export test/out/noext_cd    --smiles c1ccccc1O -> …\noext_cd.png     8339 B
    kd save  … --out test/out/noext_kdsave            -> …\noext_kdsave.king  963 B
    kd export … --out test/out/noext_kd               -> …\noext_kd.png

两通道都按 `--format` 补扩展名，不存在"一边补一边不补"的坑。

### 16. 同一路径连续两次 `kd save`

    first : ok=true bytes=963 atoms=7
    second: ok=true bytes=963 atoms=7

**默认覆盖**（并回读校验，第二次的结果同样可验）。需要保护时用新增的可选参数：

    $ runtime/py32/python.exe bin/cli.py kd save x.mol --out 重复.king --no-overwrite
    {"ok": false, "failure": {"code": "E06", "message": "Output already exists", ...}}
    rc=1

### 17. 半路中断

`kd export` 进行到第 4 秒被 SIGTERM：CLI 进程退出，KingDraw 仍在（GUI 程序被连坐才是 bug）。
测试断言两件事：残留实例能被正常关闭（不是卡死窗口），清理后进程表回到基线。实测
`KingDraw started=[68112]` → 关闭成功 → `kingdraw pids=[]`。

## 明确不修的现状（附理由）

- **`cd draw not-a-smiles` 的 stderr 上仍有 rdkit 解析日志**：那是库打给 fd2 的说明文字，不是
  traceback；stdout 的 JSON 信封完整。终端里仍能看见语法提示，保留。
- **`kd mol ''`**：直接由引擎回 `E06 smilesToMol returned nothing`，比 CLI 再判一次更准确。
- **10 万字符参数无法通过命令行注入**：Windows 单个参数上限约 32k，更长的实参在 shell 层就被拒
  （git-bash 报 `Argument list too long`）。用例取 4000 字符/4000 原子，已覆盖真正的崩溃点。
- **`cd export` 的中文路径告警走 stderr**（"exported through an ASCII staging directory"）：
  JSON 在 stdout 干净可解析，告警属于人类提示。
- **argparse 级误用**（`kd match a`、`kd smiles` 缺参）保持 rc=2 + usage：标准命令行行为。
- **ChemDraw 只有一个 COM 实例**：并行跑测试会撞（`Documents.Add() failed` / RPC server
  unavailable）。这不是代码缺陷；用例对 E99 原样重试一次，仍失败才算问题。

## 覆盖面与未覆盖

- 已覆盖：CLI 的 kd 原生通道（32 位）、kd 保存/导出、cd 绘制/导出/修改/医生、进程卫生。
- 未覆盖（属其他任务）：MCP 与 DSH 插件层的误用注入（工具名/参数校验）、KingDraw GUI 保存
  对话框的误操作（如点取消）、跨机器可移植性。
