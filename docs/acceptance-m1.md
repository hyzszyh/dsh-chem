# M1 双通道验收记录（ChemDraw + KingDraw）

- 验收对象：`core/chemdraw_tool/adapters/cd_com.py`、`core/chemdraw_tool/adapters/kd_native.py`
- 验收脚本：`test/acceptance_m1.py`（本次新增，未改任何生产代码）
- 机器：ChemDraw 26（ProgID `ChemDraw_x64.Application`）、KingDraw home `D:\tool\KingDraw`（GRDKitDll.dll，x86）
- 实测时间：2026-10-29T01:06:41 → 01:06:43（脚本自计 3.6 s）
- 原始记录：`test/out/acceptance_m1/acceptance_m1.json`（含每项全部字段、警告、子进程 stderr 尾部）

## 一条命令跑完

    cd "$REPO"
    export PYTHONIOENCODING=utf-8
    "<user-home>/AppData/Local/Programs/Python/Python311/python.exe" test/acceptance_m1.py
    # -> 5/5 criteria passed ; exit 0

为什么主脚本用 64 位解释器：rdkit 与 pywin32 只装在 64 位解释器里，ChemDraw COM 也是 x64。
KingDraw 的 DLL 是 x86，因此 KingDraw 那一腿由脚本用 `runtime/py32/python.exe` 起子进程执行
（`test/acceptance_m1.py --leg kingdraw`，只打印一行 `M1_KD_JSON:` 前缀的 JSON），
父进程负责解析并与 rdkit 算出的 InChIKey / 分子式比对。两条通道用的都是真实原生调用，没有一条是伪造或缓存。

## 结果总表

**1**

- **验收项**：分子身份一致：同一分子两条通道 InChIKey 相同
- **命令**：`python test/acceptance_m1.py`（第 1 项）
- **实际输出（实测摘录）**：苯酚 `ISWSIDIOOBJBQZ-UHFFFAOYSA-N`（kd = cd = rdkit）；阿司匹林 `BSYNRYMUTXBXSQ-UHFFFAOYSA-N`（三者相同）；咖啡因 `RYYVLZVUVIJVGH-UHFFFAOYSA-N`（三者相同）
- **结论**：通过

**2**

- **验收项**：KingDraw：smiles→molfile→smiles 往返一致，getFormula 与 rdkit 相同
- **命令**：同上（第 2 项）
- **实际输出（实测摘录）**：三个分子 canonical 完全相等：`Oc1ccccc1` / `CC(=O)Oc1ccccc1C(=O)O` / `Cn1c(=O)c2c(ncn2C)n(C)c1=O`；getFormula 与 getMolFormula 均为 `C6H6O` / `C9H8O4` / `C8H10N4O2`，与 rdkit 一致
- **结论**：通过

**3**

- **验收项**：ChemDraw：draw_smiles 后 Atoms/Bonds > 0，导出 PNG 存在且 > 1KB
- **命令**：同上（第 3 项）
- **实际输出（实测摘录）**：苯酚 7/7、阿司匹林 13/13、咖啡因 14/15 原子/键；PNG 8339 / 15729 / 18320 字节，401×270 / 550×458 / 528×508 px
- **结论**：通过

**4**

- **验收项**：非法 SMILES 两条通道均返回结构化 Failure（带 ErrorCode），无未捕获异常
- **命令**：同上（第 4 项）
- **实际输出（实测摘录）**：KingDraw `raised=None code=E06`；ChemDraw `raised=None code=E06`；另加一条通道自身插入守卫的探针：`E06 / Atoms.Count stayed at 0`
- **结论**：通过

**5**

- **验收项**：进程卫生：跑完 tasklist 无残留 ChemDraw.exe
- **命令**：同上（第 5 项）
- **实际输出（实测摘录）**：运行前 `pids=[]`，close() 报 `quit=True`，运行后 `pids=[]`、`residual=[]`（Quit 后约 1 s 进程退出）
- **结论**：通过


## 逐项证据

### 1. 分子身份一致（InChIKey）

三处 SMILES 都由通道自己读回，InChIKey 统一由 `core/chemdraw_tool/identity.py`（rdkit）在父进程计算：

    phenol   ref=ISWSIDIOOBJBQZ-UHFFFAOYSA-N
             kd =ISWSIDIOOBJBQZ-UHFFFAOYSA-N   (smiles Oc1ccccc1)
             cd =ISWSIDIOOBJBQZ-UHFFFAOYSA-N   (smiles Oc1ccccc1)
    aspirin  ref=BSYNRYMUTXBXSQ-UHFFFAOYSA-N
             kd =BSYNRYMUTXBXSQ-UHFFFAOYSA-N   (smiles CC(=O)Oc1ccccc1C(=O)O)
             cd =BSYNRYMUTXBXSQ-UHFFFAOYSA-N   (smiles CC(Oc1c(C(O)=O)cccc1)=O)
    caffeine ref=RYYVLZVUVIJVGH-UHFFFAOYSA-N
             kd =RYYVLZVUVIJVGH-UHFFFAOYSA-N   (smiles Cn1c(=O)c2c(ncn2C)n(C)c1=O)
             cd =RYYVLZVUVIJVGH-UHFFFAOYSA-N   (smiles Cn(c(=O)c1n(C)cnc1n2C)c2=O)

注意阿司匹林与咖啡因读回的 SMILES 写法与输入不同（ChemDraw 会重排字面量），但 InChIKey 相同，
说明身份判断没有被"字面量不同"误伤 —— 这正是用 InChIKey 而不是字符串比对的原因。

### 2. KingDraw 往返与分子式

    phenol   back=Oc1ccccc1                    canonical_match=True
             formula rdkit=C6H6O  getFormula=C6H6O  getMolFormula=C6H6O   molblock=497 chars
    aspirin  back=CC(=O)Oc1ccccc1C(=O)O        canonical_match=True
             formula rdkit=C9H8O4 getFormula=C9H8O4 getMolFormula=C9H8O4  molblock=774 chars
    caffeine back=Cn1c(=O)c2c(ncn2C)n(C)c1=O   canonical_match=True
             formula rdkit=C8H10N4O2 getFormula=C8H10N4O2 getMolFormula=C8H10N4O2  molblock=903 chars

`smilesToMol` 回的是 V3000 molblock（497/774/903 字符），`molToSmiles` 能把它读回，
`getFormula`（走 SMILES）与 `getMolFormula`（走 molblock）两种输入都给出与 rdkit 相同的分子式。
往返比的是 rdkit canonical SMILES：三个分子都是严格相等，不是"同分子式即可"。

KingDraw 腿部实测元数据：`exports_bound` 12/12、`pointer_bits=32`、`home=D:\tool\KingDraw`、子进程退出码 0。

### 3. ChemDraw 绘图与导出

| 分子 | 原子 | 键 | 读回 SMILES | PNG 字节 | 像素 |
|---|---|---|---|---|---|
| 苯酚 | 7 | 7 | `Oc1ccccc1` | 8339 | 401×270 |
| 阿司匹林 | 13 | 13 | `CC(Oc1c(C(O)=O)cccc1)=O` | 15729 | 550×458 |
| 咖啡因 | 14 | 15 | `Cn(c(=O)c1n(C)cnc1n2C)c2=O` | 18320 | 528×508 |

三个 PNG 都落在项目自己的中文路径下（`<workdir>\...\test\out\acceptance_m1\`），
导出走的是适配器内置的 ASCII 暂存目录再拷贝，结果带警告
`exported through an ASCII staging directory: SaveAs ignores non-ASCII paths`、`staged=true`。
这一点不是验收项，但顺带证明中文路径的绕行仍然有效。

### 4. 失败路径

    input='C1CC('          kingdraw: raised=None code=E06 msg=smilesToMol returned nothing
    input='C1CC('          chemdraw: raised=None code=E06 msg=The structure could not be parsed
    input='not_a_smiles'   kingdraw: raised=None code=E06 msg=smilesToMol returned nothing
    input='not_a_smiles'   chemdraw: raised=None code=E06 msg=The structure could not be parsed
    input='<empty smiles>' kingdraw: raised=None code=None msg=not applicable to this probe
    input='<empty smiles>' chemdraw: raised=None code=E06 msg=ChemDraw accepted the call but inserted no atoms

两个非法 SMILES 在 ChemDraw 通道上是被 rdkit 预解析挡下的（返回 E06 结构化 Failure，没有抛异常），
也就是说这一条只证明了"信封 + 不抛"，还没有证明 ChemDraw 自己会拒绝垃圾输入。
所以额外加了一条只对 ChemDraw 的探针：空 SMILES 能通过 rdkit 预解析但插入 0 个原子，
此时 `_guarded_insert` 必须自己给出 Failure：

    code=E06  message=ChemDraw accepted the call but inserted no atoms
    detail=Atoms.Count stayed at 0 after Objects.Data('chemical/x-daylight-smiles'); the call returned S_OK and inserted nothing

这条是补强证据、不计入合同项（报告里标了 `scope=chemdraw insert guard only`）。KingDraw 侧的两个
非法输入走的本来就是真实原生调用（DLL 返回空串 → E06），不需要补强。

### 5. 进程卫生

    baseline pids=[]  final pids=[]  residual=[]  quit=True  waited_seconds=1
    tasklist: （空 —— "No tasks are running which match the specified criteria."）

`connect()` 的数据：`attached=false, started_by_us=true, documents_open=0`，
即验收自起一个实例、`close()` 走 `Application.Quit()`（`quit=true`），
Quit 后约 1 s 进程消失、没有残留。

## 未验证 / 已知边界（不做修饰）

1. 进程卫生只覆盖"自己起的实例"。本次运行前机器上没有 ChemDraw.exe（`baseline_pids=[]`），
   所以验的是干净场景。若用户本来开着 ChemDraw，适配器按设计 attach 而不 Quit，那种场景下第 5 项不会通过 ——
   脚本会打印基线 PID 并把残留单独列出来，属于设计选择，但本次没有实测 attach 场景的残留表现。
2. 本轮没有重跑 t3 的其它插入路线（molblock / cdxml / paste / objects 各 13/13）。本验收只按合同要求跑默认
   `smiles` 路线，其余路线的证据仍只有 `test/test_cd_adapter.py` 那一份。
3. KingDraw 的 .king 读取（`supKingToJson` / `kingCleanUp`）没有纳入本验收：合同只要求
   smiles/molfile 往返与分子式，`kingCleanUp` 的输入形态在 t2 里仍未定论。
4. 本验收不覆盖 CDXML 最小子集、图幅几何、出图上限，那些在 `docs/cdxml-minimal.md`、
   `docs/journal-artwork.md` 与 t3 的适配器测试里。
5. 子进程 stderr 里有 rdkit 自己打的 `SMILES Parse Error` 文本（第 4 项故意喂非法 SMILES 引起），
   属预期噪声，不影响判定；完整 stderr 尾部存在 JSON 记录里。

## 复现与判据

- 判定逻辑写在脚本里，不看日志猜：第 1 项要求 `ref == kd == cd` 且三者非空；第 2 项要求
  canonical SMILES 严格相等且两个分子式接口都与 rdkit 相同；第 3 项要求 `atoms>0 and bonds>0` 且
  PNG 存在且 `bytes>1024`；第 4 项要求 `raised is None and ok is False and code in 已知错误码`；
  第 5 项要求"最终 PID 集合减去基线 PID 集合为空"。
- 任一项失败 → 该行 `FAIL`、末行打印 `n/5 criteria passed`、退出码 1；脚本不隐藏失败、不降级为警告。
- 本次实测末行：`5/5 criteria passed`，退出码 `0`。
