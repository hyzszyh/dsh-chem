# 归档说明：v1 = 引擎驱动层

标签：`archive/v1-engine-layer`。这是一个**可以回到的完整状态**，不是删除：

```
git checkout archive/v1-engine-layer     # 回到 v1 看代码或跑测试
git checkout main                        # 回到 v2 开发线
```

## v1 是什么

把本机已安装的 ChemDraw（COM）与 KingDraw（x86 DLL + 32 位解释器）驱动起来，做成三端一致的
**动作级**接口：21 条 CLI 叶子命令、16 个 MCP 工具、15 个 DSH 插件工具，19 个测试套件，CI 与契约对账。

它擅长的是「一个动作一次调用」：画一个结构、导出一次图、转一次格式、读一次页面、核对一次身份。
它的设计前提是「调用者是人，会自己把动作拼成任务」——**这个前提在 v2 变了**。

## 为什么归档

v2 的调用者是 agent：它每一步都要读返回再决策，调用轮次是成本；它看不见屏幕，画完必须能自检；
它只会说人话（「阿司匹林」），不会说 SMILES。动作级接口在这三条上全都吃亏，所以要换暴露面。

## 可以继续用（v2 的实现层）

- `core/chemdraw_tool/adapters/cd_com.py`：ChemDraw COM 通道（画、导出、回读、图片裁边、dpi 处理、
  长路径暂存、应用锁包装）。这是最贵的资产，v2 直接复用。
- `core/chemdraw_tool/adapters/kd_*.py`：KingDraw 一侧（转换、公式、`.king` 读写、UIA 打开确认）。
- `core/chemdraw_tool/applock.py`：跨进程命名互斥锁。agent 会并发调用，这个必须有。
- `core/chemdraw_tool/models.py`：信封、失败码 E01–E10/E99、证据等级 A/B/C、`as_envelope`。
- `test/`：19 个套件的回归网；`tools/contract_sync.py` 的三端契约对账；`.github/workflows/ci.yml`。
- `install.ps1` / `scripts/fetch_runtime.py`：取 32 位运行时的安装路径。
- `docs/cdxml-minimal.md`、`docs/architecture-audit.md` 等实测记录：CDXML 插入、SaveAs 格式取法、
  GetData 回读、DPI 标签行为——这些踩坑结论 v2 不必重踩。

## 在 v2 里被替换的部分

- **对外暴露面**：16 个 MCP 工具 / 15 个插件工具（动作级）→ v2 的任务级工具（见 `docs/v2/requirements.md`）。
  旧工具保留在实现层，不删，但不再作为 agent 的默认入口。
- **面向终端人的排版**：终端宽度预算、摘要渲染等只服务于「人看终端」，agent 不读终端。相关代码留着，
  优先级下降。
- **文档数字门禁**（`tools/preflight.py` 的 documented counts 检查）：保留，但只对新文档生效。

## v1 的已知边界（v2 要正面解决的）

- 没有预览反馈：agent 画完只有一个文件路径。
- 没有状态查询：agent 不知道当前开着哪个文档、页面多大、锁在谁手里。
- 没有名称/CAS 入口：学生只会说「阿司匹林」。
- 3D、NMR、计量表、Markush 展开、结构检查这些软件里有的能力，COM 没有对象，v1 完全没碰。
- 图像识别完全没有。

## 复现 v1 的全部验证

```
python tools/preflight.py && python bin/md_render_check.py && python test/run_all.py
```

v1 最后一次全量：19 passed / 0 failed / 0 skipped / 213.7 s（本机，装有两个厂商程序）。