# 图像识别引擎：装在哪、怎么验、怎么拆

结构式图片转结构这件事，单靠大模型视觉不可靠，单靠一个专用引擎在版式复杂时也不可靠。
所以本工具用**多读者 + 化学裁决**：每个引擎各出一份候选，RDKit 淘汰不合格的，InChIKey 一致才算高置信。

关键设计：**引擎之间不共享运行时**。MolVec 是 Java、OSRA 是原生可执行、MolScribe 要 torch 加旧版
albumentations、DECIMER 钉 TensorFlow 2.15 / Keras 2。它们各自一个环境，由 `core/chemdraw_tool/v2/ocr.py`
用子进程调用。主进程（驱动 ChemDraw 的那个）不 import 任何深度学习框架，所以识别不会拖慢绘图、
也不会抢 ChemDraw 的会话锁。

## 本机现状（2026-10-29 实测）

| 引擎 | 形态 | 命中 | 单图耗时 |
|---|---|---|---|
| MolVec 0.9.8 | Java jar 1.3 MB | 6/6 | 1.2 s |
| DECIMER 2.8 | 独立 venv，权重 298 MB | 6/6 | 8.5 s |
| MolScribe 1.1.1 | venv 与权重都就位 | 不可用 | — |
| OSRA | 只有源码包，无 Windows 二进制 | 未装 | — |

安装位置统一在 `%LOCALAPPDATA%\chem-draw-tool\engines\<名字>\`，权重在
`%LOCALAPPDATA%\chem-draw-tool\models\`。删掉某个目录就退回「没有这个读者」。

回归集自带答案：先用本工具把已知 SMILES 画成图，再让引擎读回来，最后比 InChIKey。
含手性分子 (S)-布洛芬，两个引擎都读出了正确立体。

```bash
python bin/v2.py ocr --probe                      # 每个引擎：能用吗，不能用的原因是什么
python bin/v2.py ocr 图.png --engines molvec      # 快的那个，1.2 秒
python bin/v2.py ocr 图.png                       # 全部可用引擎投票
python tools/ocr_regression.py                    # 重跑回归集，出命中表
```

`--probe` 的答案不是布尔值，而是「不可用的原因」——agent 拿到 `molscribe: no interpreter for
this engine` 能行动，拿到 `false` 不能。

## 单点安装 / 单点回退

每个引擎独立，删掉对应目录就退回「没有这个读者」，不影响其余：

**MolVec（Java）**

```bash
mkdir -p "$LOCALAPPDATA/chem-draw-tool/engines/molvec"
BASE=https://repo1.maven.org/maven2/gov/nih/ncats/molvec/0.9.8
JAR=molvec-0.9.8-jar-with-dependencies.jar
curl -L -o "$LOCALAPPDATA/chem-draw-tool/engines/molvec/molvec.jar" \
  "$BASE/$JAR"
```

**DECIMER（独立 venv）**

```bash
PY=python; ENG="$LOCALAPPDATA/chem-draw-tool/engines/decimer"
"$PY" -m venv "$ENG"
"$ENG/Scripts/python.exe" -m pip install \
  "tensorflow==2.15.1" "keras==2.15.0" decimer pillow
```

权重（Zenodo，两个 zip 各约 298 MB）解到 `%LOCALAPPDATA%\chem-draw-tool\models\decimer\pystow\DECIMER-V2\`，
再写两个 `.model_url` 文件让 DECIMER 跳过下载：

```bash
A=https://zenodo.org/record/8300489/files/models.zip
B=https://zenodo.org/records/10781330/files/DECIMER_HandDrawn_model.zip
echo "$A" > .../DECIMER_model/.model_url
echo "$B" > .../DECIMER_HandDrawn_model/.model_url
```

运行期 `ocr.py` 会把 `PYSTOW_HOME` 指到该目录（可用 `CHEM_OCR_PYSTOW` 覆盖）。

**路径覆盖**：`CHEM_DRAW_TOOL_ENGINES` 换引擎根目录，`CHEM_OCR_TIMEOUT` 换超时（默认 600 s）。

## 踩过的坑（都是真的）

| 现象 | 原因 | 处置 |
|---|---|---|
| pip 装 molscribe 失败 | 钉 `torch<2.0`，py3.11 无轮子 | `--no-deps` 后补 timm |
| 找不到 `safe_rotate_*` | albumentations 版本错 | 钉 1.1.0 + timm 0.4.12 |
| DECIMER 报 `BadZipFile` | Zenodo 权重下载被截断 | 手动下 zip 解到 pystow |
| DECIMER 初始化报错 | 主环境 TF 2.20 + Keras 3 | 单独 venv 钉 2.15 |
| MolVec 读出来是空的 | molfile 首行空标题被 strip | 解析不 strip（有测试） |
| MolScribe 报 `layer_cache` | 要 onmt 2.x 注意力 API | 3.x 无此 API；2.3 要旧 torchtext |

## MolScribe 为什么停在这里

venv、`molscribe` 1.1.1、`SmilesPE`、`timm 0.4.12`、`albumentations 1.1.0`、`pyonmttok`、
torch 2.3.1 + torchvision 0.18.1、1.1 GB 权重全部装好，`import molscribe` 通过。卡在推理：

- 它的解码器调用 `MultiHeadedAttention(..., layer_cache=..., step=..., attn_type=...)`，这是
  OpenNMT-py 2.x 的签名；3.5.1 改成无缓存版本，丢掉这些关键字后张量形状对不上
  （`expanded size of the tensor (-1)`）。
- 退回 2.3.0 也没用：它 `import torchtext.data.Field`，要 torchtext 0.5，而 0.5 只支持 Python ≤3.7。

所以探针不报「缺失」，报的是能力不满足：`molscribe needs the OpenNMT-py 2.x attention API`。
要真把它跑起来，得单独配一个 Python 3.8 环境，代价是一整套旧运行时——本机判断不值得，
因为 MolVec + DECIMER 已经双路互证。

## 返回值里能看出谁读错了

`chem_ocr` 不只有一个 `best`：

- `readers`：每个引擎自己读出的 SMILES、它的 InChIKey、`agrees`（是否与最优相同）。
- `differing`：与最优不同的那些，外加一条 warning 直接写「谁读成了什么」。
- `rejected`：RDKit 都读不出来的原始串（引擎崩了才出现在这里）。
- `redrawn` / `compare`：把最优结构用同一条绘制管线重画，和原图并排。

两个引擎给出不同结构时，`votes` 只是 1:1，谁对谁错它不说；并排两张图 + 每个引擎的
原始串才说得清。

## 已知边界

- DECIMER 单个进程启动要几十秒（加载 298 MB 权重）。批量走 `read_batch`：一次加载、多图推理，8.5 s/图。
  交互时优先 `--engines molvec`（1.2 s）。
- 四个引擎对「反应式 + 条件文字」这种混排图都不可靠：箭头、加号、条件会被当成结构的一部分。
  这类图先 `chem_reaction` 重新生成，别指望 OCR 读回来。
