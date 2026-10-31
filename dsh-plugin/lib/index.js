// dsh-chem — 15 tools, one engine. Every tool is a thin forwarder: it picks
// arguments, calls bin/chem.py through ./engine.js, and hands back the JSON
// envelope. No chemistry, no COM, no ctypes in this file.
//
// Why so thin: the Python package owns all computation, so a chemistry fix
// never needs a plugin reload, and the same entry point is what the sidebar
// panel and the CLI use -- one code path, one set of numbers.

import { defineTool } from '@deepseek-ai/dsh-tools'

import { startBridge } from './sidebar-bridge.js'
import { call, status } from './engine.js'

export const name = 'dsh-chem'
export const inject = ['tools']

const MAX_INLINE = 100

function headline(payload) {
  const lines = []
  if (payload && payload.ok === false) {
    const failure = payload.failure || {}
    lines.push('✗ ' + (failure.code || 'failed'))
    if (failure.message) lines.push('   ' + failure.message)
    if (failure.hint) lines.push('   修正：' + failure.hint)
    return lines
  }
  lines.push('✓ ' + ((payload && payload.channel) || 'ok'))
  const data = payload && payload.data && typeof payload.data === 'object' ? payload.data : (payload || {})
  for (const [key, value] of Object.entries(data)) {
    if (key === 'ok' || value === null || value === undefined || value === '') continue
    if (typeof value === 'object') continue
    const text = String(value)
    if (text.length > MAX_INLINE) continue
    lines.push('   ' + key + ': ' + text)
  }
  for (const warning of (payload && payload.warnings) || []) {
    lines.push('   ! ' + String(warning).slice(0, MAX_INLINE))
  }
  return lines
}

const OUTPUT = {
  schema: { type: 'string' },
  render: (_args, value) => {
    let payload = null
    try { payload = JSON.parse(value) } catch { /* not ours to format */ }
    if (!payload) return [{ type: 'text', text: value }]
    const head = headline(payload)
    const full = JSON.stringify(payload, null, 2)
    return [{ type: 'text', text: head.length ? head.join('\n') + '\n\n— 完整结果 —\n' + full : full }]
  },
}

const asText = (payload) => JSON.stringify(payload, null, 2)

// Tool table. `description` is the agent-facing contract: first sentence says
// when to reach for it, the rest says what it refuses to guess.
const TOOLS = [
  {
    name: 'chem_parse',
    cmd: 'parse',
    description: '把「名字 / CAS 号 / 缩写 / 截图 / 氨基酸序列」变成结构。凡是用户给的是文字描述或图片而不是 SMILES，先用它。图片识别走本机双引擎投票（molvec + DECIMER，可选 MolScribe 第三票），多候选与置信度一起返回，不会凭记忆编一个结构。',
    parameters: {
      source: { type: 'string', required: true, description: '名称、CAS 号、缩写、图片路径，或序列' },
      kind: { type: 'string', description: 'name | image | seq，留空自动判断' },
    },
  },
  {
    name: 'chem_clean',
    cmd: 'clean',
    description: '结构体检与修好：价键、芳香性、电荷、自由基、断开的片段、未标手性、原子过近，外加去盐/中和/互变异构归一/药化结构警示（PAINS 等）。交作业或入库前跑一遍，比盯图看可靠。',
    parameters: {
      smiles: { type: 'string', required: true, description: 'SMILES 或 molblock' },
      action: { type: 'string', description: 'check（只报）| fix（顺手修）| filter（药化警示），默认 check' },
    },
  },
  {
    name: 'chem_draw',
    cmd: 'draw',
    description: '出图：分子、反应式、机理箭头、联系表。可按期刊宽度与 dpi 出 PNG/SVG/向量 PDF/TIFF，留白与键长有阈值检查。默认不启动 ChemDraw；只有要 .cdx 或 EPS 才升级到厂商通道。',
    parameters: {
      smiles: { type: 'string', description: 'SMILES；view=rxn 时传反应 SMILES' },
      view: { type: 'string', description: 'mol（默认）| rxn | mech | grid' },
      widthMm: { type: 'number', description: '物理宽度（毫米），如 85 / 170' },
      dpi: { type: 'number', description: '分辨率，默认 300' },
      format: { type: 'string', description: 'png | svg | pdf | tif | eps，默认 png' },
      out: { type: 'string', description: '可选：输出文件路径' },
    },
  },
  {
    name: 'chem_props',
    cmd: 'props',
    description: '算性质：分子式、精确质量、分子量、logP、TPSA、氢键给受、可旋转键、环系、Fsp3、QED、复杂度。数值来自本机 RDKit，同一输入永远同一答案，不要自己心算或用模型记忆。',
    parameters: {
      smiles: { type: 'string', required: true, description: 'SMILES 或 molblock' },
      fields: { type: 'string', description: '可选：逗号分隔的字段名，留空返回全套' },
    },
  },
  {
    name: 'chem_calc',
    cmd: 'calc',
    description: '算账：反应配平、当量/投料质量、理论产率、高分辨质谱与元素分析文字、96 孔板加样表与稀释序列。给反应 SMILES 就能用，不猜数字。',
    parameters: {
      kind: { type: 'string', description: 'stoich | hrms | plate，默认 stoich' },
      reaction: { type: 'string', description: '反应 SMILES，如 CC(=O)O.OCC>>CC(=O)OCC.O' },
      smiles: { type: 'string', description: 'kind=hrms 时用' },
      scaleMmol: { type: 'number', description: '投料 mmol，默认 1' },
      yieldPercent: { type: 'number', description: '可选：收率百分比' },
    },
  },
  {
    name: 'chem_compare',
    cmd: 'compare',
    description: '比较：相似性打分（ECFP/MACCS/Tanimoto）、共同骨架 MCS、聚类与代表性挑样、SAR 表。分子库挑候选、问「这两个像不像」、找共同核心时用它。',
    parameters: {
      mode: { type: 'string', description: 'sim（默认）| mcs | cluster | sar' },
      query: { type: 'string', description: '查询分子 SMILES' },
      smilesList: { type: 'string', description: '候选分子，换行或逗号分隔' },
    },
  },
  {
    name: 'chem_table',
    cmd: 'table',
    description: '批量算表与实验数据处理：一批 SMILES → 描述符表 → 条件筛选排序 → CSV；也能做数据清洗与 IC50 四参数拟合。三百个分子的活不要手算。',
    parameters: {
      action: { type: 'string', description: 'matrix（默认）| clean | fit' },
      smilesList: { type: 'string', description: '分子列表，换行或逗号分隔' },
      filter: { type: 'string', description: '可选：筛选表达式，如 MW<250 and HBD<=2' },
      out: { type: 'string', description: '可选：CSV 输出路径' },
    },
  },
  {
    name: 'chem_db',
    cmd: 'db',
    description: '本地小分子库存与检索：导入 SMILES/CSV/SDF、按编号取、子结构查（SMARTS）、相似度查、按 InChIKey 去重。给一批分子建可反复查询的库时用它，不要每次重算。',
    parameters: {
      op: { type: 'string', description: 'import | get | sub | sim | dedupe' },
      db: { type: 'string', description: '库文件路径（.sqlite）' },
      input: { type: 'string', description: 'op=import 时的数据来源（路径或文本）' },
      query: { type: 'string', description: 'op=get 的编号 / op=sub 的 SMARTS / op=sim 的 SMILES' },
      limit: { type: 'number', description: '返回条数上限，默认 20' },
    },
  },
  {
    name: 'chem_ml',
    cmd: 'ml',
    description: '从结构建预测模型：描述符 → 训练 → 骨架切分交叉验证 → 指标 → 对新分子预测。数据量小时不要吹指标，骨架切分不给面子；不适用的场景会明说样本不足。',
    parameters: {
      action: { type: 'string', description: 'train | predict | evaluate' },
      data: { type: 'string', description: 'CSV 路径，含 smiles 与目标列' },
      target: { type: 'string', description: '目标列名' },
      model: { type: 'string', description: 'rf | gb | linear，默认 rf' },
      out: { type: 'string', description: '可选：模型与报告输出目录' },
    },
  },
  {
    name: 'chem_enum',
    cmd: 'enum',
    description: '铺开结构：同系列变体、立体异构枚举、R 基/组合库、互变异构枚举。出题、做库设计、检查有没有漏掉对应异构体时用它。',
    parameters: {
      mode: { type: 'string', description: 'variant | stereo | library | tautomer' },
      scaffold: { type: 'string', description: '带 [*] 的骨架 SMILES' },
      substituents: { type: 'string', description: '取代基 SMILES，换行或逗号分隔' },
      smiles: { type: 'string', description: 'mode=stereo/tautomer 时的输入分子' },
    },
  },
  {
    name: 'chem_retro',
    cmd: 'retro',
    description: '逆合成：单步断键给出可能前体（本地 rdchiral，秒级），可选多步搜索。给目标分子问「这一步怎么做出来」时用它；它不保证路线可采购可行，只给化学上说得通的断键。',
    parameters: {
      smiles: { type: 'string', required: true, description: '目标分子 SMILES' },
      depth: { type: 'number', description: '1（默认，单步）| 2-3（多步，需可选组）' },
    },
  },
  {
    name: 'chem_spectra',
    cmd: 'spectra',
    description: '谱图有关：NMR 原始数据的读取、寻峰与积分，质谱谱库匹配，以及从精确质量反推分子式。没有原始数据文件时不要用它编谱。',
    parameters: {
      kind: { type: 'string', description: 'nmr | ms | formula' },
      input: { type: 'string', description: '文件路径（NMR/质谱）或精确质量数值' },
      smiles: { type: 'string', description: 'kind=ms 时可给理论谱对照分子' },
    },
  },
  {
    name: 'chem_exam',
    cmd: 'exam',
    description: '教学：批改学生答案（结构式/命名/计算题，逐项说明差在哪）、按模板出题变体、生成带断言的答案。判定用 InChIKey 和数值比对，不用眼睛。',
    parameters: {
      action: { type: 'string', description: 'grade | make' },
      answer: { type: 'string', description: '标准答案（SMILES 或数值）' },
      submissions: { type: 'string', description: '学生答案，换行分隔' },
      count: { type: 'number', description: 'action=make 时出题数量' },
    },
  },
  {
    name: 'chem_office',
    cmd: 'office',
    description: '把结构交付到文档里：Word/PPT 中插入可双击编辑的 ChemDraw 对象、生成 SI 三线表、把联系表与反应图排进页。纯图片插入不必用它，直接 chem_draw 即可。',
    parameters: {
      target: { type: 'string', description: 'docx | pptx | si-table' },
      path: { type: 'string', description: '目标文档路径（不存在则新建）' },
      smiles: { type: 'string', description: '要嵌入的分子' },
      imagePath: { type: 'string', description: '已生成的图，可选' },
    },
  },
  {
    name: 'chem_vendor',
    cmd: 'vendor',
    description: '厂商通道：读写在装 ChemDraw/KingDraw 里的文件（.cdx/.cdxml/.king）、合并拆分文档、导出 EPS、出预览图、收工关窗。只有用户明确要厂商格式或期刊强制 EPS 时才用它。',
    parameters: {
      do: { type: 'string', description: 'cdx-read | cdx-write | merge | split | eps | preview | close' },
      path: { type: 'string', description: '文件路径' },
      smiles: { type: 'string', description: '要写进文档的分子，可选' },
    },
  },
]

export function apply(ctx) {
  const runtime = status()
  for (const spec of TOOLS) {
    ctx.tools.register(defineTool({
      name: spec.name,
      description: spec.description,
      parameters: spec.parameters,
      output: OUTPUT,
      async execute(args) {
        if (!runtime.ready) {
          return asText({
            ok: false,
            failure: { code: 'no-runtime', message: '运行时未就绪，工具无法执行', hint: runtime.hint },
          })
        }
        return asText(await call(spec.cmd, args || {}))
      },
    }))
  }
  // The panel cannot spawn Python, so the host half opens a loopback bridge and
  // forwards only the 15 registered names. Started here (not at import time) so a
  // failed bind never takes the tool registration down with it.
  let bridge = null
  try {
    bridge = startBridge(ctx)
  } catch (error) {
    ctx?.logger?.warn?.('[dsh-chem] panel bridge failed to start: ' + String((error && error.message) || error))
  }

  // Exposed for the contract test and for the sidebar panel: one place that
  // knows both the declared tool names and the runtime they will use.
  return {
    tools: TOOLS.map((t) => t.name),
    runtime,
    bridgePort: bridge ? bridge.port() : null,
    closeBridge: () => { try { bridge?.close() } catch (error) { /* already gone */ } },
  }
}