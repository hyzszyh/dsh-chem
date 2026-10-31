# 把 CC / Codex 的化学生态搬进 DSH：可行性与换乘站设计

写于 2026-10-30。上一份 `docs/prior-art.md` 回答了「别人做到哪了」，这一份回答
「怎么搬过来」。

## 0. 结论

**能搬，而且 DSH 已经把最难的接口留好了。** 三条通道：

| 通道 | DSH 现状 | 搬运成本 |
|---|---|---|
| MCP 服务器 | 内置 `dsh-mcp-client`（stdio / streamable-http，自动重连，工具名 `mcp__<server>__<tool>`） | 一条配置项 |
| Skill | `~/.dsh/skills/<name>/SKILL.md` 目录自动发现 | 复制 + frontmatter 适配 |
| 插件 | `dsh-plugin-market` + 客户端插件市场 UI 已存在 | 需要适配器（commands/agents/hooks 无直接对应） |

所以「全搬」在工程上不是重写，而是**写一个换乘站**：把 CC/Codex 的产物映射到这三条通道上。

## 1. 证据（不是推测）

- `resources/app.asar` 里 307 个 `@deepseek-ai` 包，其中：
  `dsh-mcp-client`、`dsh-mcp-resources`、`dsh-plugin-market`、`dsh-plugin-market-index`、
  `dsh-client-ui-plugin-market`、`dsh-skill`、`dsh-skill-filesystem`、`dsh-tool-skill`。
- `dsh-mcp-client/README.zh.md` 明确写了配置字段：
  `transport`（stdio | streamable-http）、`command`/`args`/`env`/`cwd`、`url`/`headers`、
  `failOnStartupError`、`reconnect.enabled`；工具以 `mcp__<serverName>__<rawName>` 注册到 `ctx.tools`。
- 社区侧已有可直接挂的化学 MCP：`codex-organic-chem`（自带 MCP server）、
  `chemdraw-mcp`（PyPI）、`tandemai-inc/rdkit-mcp-server`、PubChem/ChEMBL 系列 MCP。

## 2. 换乘站设计：三层映射

### L1 MCP —— 主力通道（今天就能用）

任何 CC/Codex 插件只要暴露 MCP server，DSH 就能拿到它的全部工具。要做的只是
**把插件声明里的 `mcpServers` 自动翻译成 `dsh-mcp-client` 的配置项**：

追问是 CC 的 `.mcp.json` / 插件 `plugin.json` 里的
`mcpServers: { name: { command, args, env } }`，
落到 DSH 的 `transport: stdio, command, args, env`。字段几乎一一对应，字段名不同而已。

### L2 Skill —— 知识型产物

CC 的 `.claude/skills/<name>/SKILL.md`、Codex 的 `.agents/skills/<name>/SKILL.md`
与本机 `~/.dsh/skills/<name>/SKILL.md` 都是「frontmatter(name/description) + 正文 + 附属文件」。
适配器要做的事只有三件：

1. frontmatter 规范化（description 长度、触发词）；
2. 正文里的路径引用改写（`.claude/` → `~/.dsh/`，脚本路径指向安装目录）；
3. 附属脚本的依赖检查（uv / python / node），缺的就写进「未满足依赖」而不是静默失败。

### L3 Plugin —— 只有一部分能映射

| CC 插件构件 | DSH 落点 | 判断 |
|---|---|---|
| `skills/` | `~/.dsh/skills/` | 直接可用 |
| `mcpServers` (`.mcp.json`) | `dsh-mcp-client` 配置项 | 直接可用 |
| `agents/`（子代理） | DSH 预设 / 子代理 | 需要一次转换 |
| `commands/`（斜杠命令） | skill 或预设动作 | 需要转换 |
| `hooks/`（生命周期钩子） | cordis 事件插件 | **先不支持**，显式报「这个插件里有 2 个 hook 未移植」 |
| `marketplace.json` | DSH 市场的联邦源 | 需要索引适配器 |

一句话：**L1 + L2 覆盖了化学插件 90% 的价值**（工具能力 + 领域知识），L3 只处理外壳。

## 3. 端到端验证路径（下一步就做这个）

拿 `LaoZhong-Mihari/codex-organic-chem` 当样本，它是 CC + Codex 双技能 + MCP + OCSR 的
最完整形态：

1. `git clone` 到 `D:\...\interop\codex-organic-chem`；
2. `uv sync --extra mcp`（或退化为 venv + pip）；
3. 确认它的 MCP 启动命令（README 给了 `uv run codex-chem ...`，MCP 入口在
   `src/codex_organic_chem`，需查它的 `integrations` 与 `DEPENDENCIES.md`）；
4. 在 DSH 里加一条 `dsh-mcp-client` 配置，重启；
5. 验收：工具列表里出现 `mcp__codexchem__*`，随便调一个（如 normalize）返回真实结果。

这一步跑通，就证明「搬运」不是 PPT：**别人的化学能力当天就能变成你的工具**。

## 4. 可搬的化学资产清单

| 资产 | 形态 | 搬完得到什么 |
|---|---|---|
| codex-organic-chem | MCP + 双 skill | OCSR、归一化、构象、反应合理性、机理草稿 |
| chemdraw-mcp | MCP（PyPI） | 名称/SMILES → 投稿级 2D |
| tandemai-inc/rdkit-mcp-server | MCP | RDKit 全套描述符与反应 |
| chemdraw-skill | Skill + Python toolkit | ChemDraw 原生、Word/PPT 活对象、SAR 面板 |
| dshchem | DSH 原生插件 | 逆合成、对接、ADMET、聚类、MCS |
| PubChem / ChEMBL MCP | MCP | 名称解析、指纹相似、生物活性 |

搬完之后本项目的定位就清楚了：**不做化学院子里的第一，做「厂商原生 + 读图 + 交付体检 + 教学」
这一层的唯一**，其余全走换乘站。

## 5. 风险

- 每条 MCP 都要求本机能起它的解释器/依赖；Windows 上 uv/python 混装是主要坑。
- MCP 工具名会带上服务器前缀，模型选工具时要能分清 `mcp__chem__draw` 与本地 `chem_draw`，
  需要一份「工具名对照」文档，否则会出现两套相似工具互相打架。
- 别把 L3 的 hooks 硬塞进 cordis：那是最容易把 DSH 弄崩的地方（本插件已经崩过一次）。
