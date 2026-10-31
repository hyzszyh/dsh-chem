# 示例

三个脚本，按「需要装什么」从少到多排列。每个都能单独跑，跑不通时会**说明缺什么**而不是抛 traceback。

**`batch_identity.py`**

- **需要**：只要 `pip install rdkit`
- **干什么**：SMILES 批量转 InChIKey / 分子式 / 规范式

**`draw_figure.py`**

- **需要**：再加 ChemDraw + `pywin32` + `pillow`
- **干什么**：在 ChemDraw 里画一个分子，按 ACS 单栏规格出图

**`crosscheck_batch.py`**

- **需要**：再加 32 位运行时（`scripts/fetch_runtime.py`）
- **干什么**：同一批分子过三个引擎，用 InChIKey 对账


```bash
python examples/batch_identity.py
python examples/draw_figure.py
python examples/crosscheck_batch.py
```

## 为什么示例里没有「读 API 文档」这一步

这三个脚本就是 API 的用法说明。要看全部能力，用 `python bin/cli.py --help` 与 `python bin/cli.py cd --help`；要看这台机器现在能干什么，用 `python bin/cli.py doctor all`。

## 一个和直觉相反的地方

`crosscheck_batch.py` 只比 InChIKey，不比 SMILES 字符串。ChemDraw 会把喂进去的结构重排（阿司匹林读回来是 `CC(Oc1c(C(O)=O)cccc1)=O`），字面量对不上但分子是同一个。**凡是跨引擎比对，一律走 InChIKey。**
