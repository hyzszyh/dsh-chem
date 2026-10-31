// dsh-chem — 右栏「化学绘图」面板。
//
// 这个面板不是遥控器，是工作台：
//   1) 看得见 agent 干了什么 —— 轮询产物目录，画完的图自己冒出来；
//   2) 一句话就能动手 —— 结构粘进去、宽度选好、点一下；
//   3) 看得见结果好坏 —— 引擎状态、字节数、键长与留白，不用切回聊天里问。
//
// 数据全部来自宿主半的本地回环桥（127.0.0.1），面板自己不碰 COM、不碰 Python。
// 它读的每个字段都必须真的出现在桥的 /state 里：上一版面板还在问 v2 时代的
// channels / session，新桥不发了，于是两个通道徽章一起红、写着「会话未连接」。

const PLUGIN_ID = 'dsh-chem'
const PORTS = [37373, 37374, 37375, 37376]
const WIDTHS = [60, 85, 120, 170]
const POLL_MS = 4000

let cachedBase = null

// 端口从 37373 起试，宿主只会占一个；先 /health 认门牌再说话。
async function discover() {
  if (cachedBase) return cachedBase
  for (const port of PORTS) {
    const base = 'http://127.0.0.1:' + port
    try {
      const response = await fetch(base + '/health', { signal: AbortSignal.timeout(1200) })
      if (!response.ok) continue
      const body = await response.json()
      if (body && body.plugin === PLUGIN_ID) { cachedBase = base; return base }
    } catch (error) { /* 这个端口不是我们的 */ }
  }
  return null
}

async function callBridge(path, options) {
  const base = await discover()
  if (!base) throw new Error('本地桥没有响应：宿主插件没加载，或端口被占用')
  const response = await fetch(base + path, {
    ...options,
    headers: { 'content-type': 'application/json', ...(options && options.headers) },
  })
  return response.json()
}

// 装没装上不该靠猜：模块执行时报一次，apply 走完再报一次，带每个坐席的结果。
// 桥那边的 /client-mounted 与 logs/panel.log 都留着，面板不出现时能分清是
// 「客户端没加载」「服务拿不到」还是「坐席注册被拒」。
async function report(steps) {
  try {
    const base = await discover()
    if (!base) return false
    const query = '?steps=' + encodeURIComponent(JSON.stringify(steps))
    await fetch(base + '/client-mounted' + query, { method: 'POST' })
    return true
  } catch (error) {
    return false
  }
}

const S = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 10, padding: '10px 12px', height: '100%', overflowY: 'auto' },
  row: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' },
  spread: { display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'space-between' },
  chip: (ok) => ({
    fontSize: 11, padding: '2px 8px', borderRadius: 10,
    background: ok ? 'rgba(46,160,67,0.18)' : 'rgba(248,81,73,0.16)',
    color: ok ? '#3fb950' : '#f85149', border: '1px solid currentColor',
  }),
  badge: {
    fontSize: 10, padding: '1px 6px', borderRadius: 8, marginLeft: 6,
    background: 'rgba(88,166,255,0.2)', color: '#58a6ff', border: '1px solid currentColor',
  },
  button: {
    fontSize: 12, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
    background: 'rgba(255,255,255,0.06)', color: 'inherit',
    border: '1px solid rgba(255,255,255,0.14)',
  },
  buttonOn: {
    fontSize: 12, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
    background: 'rgba(88,166,255,0.18)', color: 'inherit',
    border: '1px solid rgba(88,166,255,0.55)',
  },
  select: {
    fontSize: 12, padding: '5px 6px', borderRadius: 6, color: 'inherit',
    background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.14)',
  },
  input: {
    width: '100%', fontSize: 12, padding: '6px 8px', borderRadius: 6, color: 'inherit',
    background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.14)',
    boxSizing: 'border-box',
  },
  thumbGrid: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 },
  thumb: (active) => ({
    padding: 4, borderRadius: 6, cursor: 'pointer', lineHeight: 0,
    background: active ? 'rgba(88,166,255,0.16)' : 'rgba(255,255,255,0.04)',
    border: '1px solid ' + (active ? 'rgba(88,166,255,0.55)' : 'rgba(255,255,255,0.12)'),
  }),
  thumbImg: { width: '100%', height: 46, objectFit: 'contain', display: 'block', background: '#fff', borderRadius: 3 },
  shotBox: {
    width: '100%', maxWidth: 360, margin: '0 auto', boxSizing: 'border-box',
    background: '#fff', borderRadius: 6, padding: '12px 14px',
    display: 'flex', justifyContent: 'center', alignItems: 'center',
  },
  img: { maxWidth: '100%', maxHeight: 96, objectFit: 'contain', display: 'block' },
  pin: { display: 'inline-flex', alignItems: 'center', gap: 2, borderRadius: 10,
    background: 'rgba(88,166,255,0.12)', border: '1px solid rgba(88,166,255,0.35)' },
  pinBtn: { fontSize: 11, padding: '2px 6px', background: 'transparent', color: 'inherit',
    border: 'none', cursor: 'pointer' },
  pinX: { fontSize: 11, padding: '2px 5px', background: 'transparent', color: 'inherit',
    border: 'none', cursor: 'pointer', opacity: 0.55 },
  pre: {
    fontSize: 11, lineHeight: 1.45, margin: 0, padding: 8, borderRadius: 6,
    background: 'rgba(0,0,0,0.28)', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
  },
  hint: { fontSize: 11, opacity: 0.62, lineHeight: 1.5 },
  section: { fontSize: 11, opacity: 0.72, marginTop: 2 },
}

const message = (error) => String((error && error.message) || error)

// 人话摘要：一次画图的关键数字，比整段 JSON 有用得多。
function summarize(envelope) {
  if (!envelope || !envelope.ok) return null
  const data = envelope.data || {}
  if (typeof data.widthPx === 'number' && data.bonds && typeof data.bonds === 'object') {
    const margin = data.padding && typeof data.padding.ratio === 'number'
      ? Math.round(data.padding.ratio * 100) + '%' : '—'
    return data.widthPx + '×' + data.heightPx + ' px · 键长 ' +
      Math.round(data.bonds.median_px) + ' px · 留白 ' + margin + ' · ' + data.bytes + ' B'
  }
  if (data.formula) return data.formula + ' · MW ' + data.mw
  if (data.issues) return (data.issues.length || 0) + ' 个问题'
  return null
}

void report(['module'])

window.__ModuleLoader__.load({
  id: PLUGIN_ID,
  factory: (require) => {
    // 宿主注入的 require 只在这个闭包里；组件也必须在里面，否则渲染时找不到 React。
    const React = require('react')
    const h = React.createElement

    function Panel() {
      const [state, setState] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [smiles, setSmiles] = React.useState('')
      const [widthMm, setWidthMm] = React.useState(85)
      const [note, setNote] = React.useState('正在连本地桥…')
      const [envelope, setEnvelope] = React.useState(null)
      const [items, setItems] = React.useState([])
      const [fresh, setFresh] = React.useState(0)
      const [picked, setPicked] = React.useState(null)
      const [showJson, setShowJson] = React.useState(false)
      const [pins, setPins] = React.useState([])
      const [batch, setBatch] = React.useState('')
      const [showBatch, setShowBatch] = React.useState(false)
      const [query, setQuery] = React.useState('')

      const seenAt = React.useRef(0)
      const baseAt = React.useRef('')

      // /state 的真实字段：{ plugin, runtime: { ok, python, packages }, tools, artifacts, latest, client_mounted }
      const loadState = React.useCallback(async () => {
        try {
          const info = await callBridge('/state')
          setState(info)
          const runtime = info.runtime || {}
          const packages = runtime.packages || {}
          const bits = []
          bits.push(runtime.ok ? '引擎就绪' : '引擎不可用')
          if (packages.rdkit) bits.push('RDKit ' + packages.rdkit)
          if (Array.isArray(info.tools)) bits.push(info.tools.length + ' 个工具')
          bits.push('产物 ' + (info.artifacts || 0) + ' 份')
          setNote(bits.join(' · '))
          if (!runtime.ok) setNote('引擎不可用：先跑 python bin/setup.py 建运行时，见 PATCH.md')
        } catch (error) {
          setState(null)
          setNote(message(error))
        }
      }, [])

      // agent 那头画完图，这边自己就会看见：只轮询产物列表，不催任何东西。
      const loadArtifacts = React.useCallback(async () => {
        try {
          const list = await callBridge('/artifacts?limit=9')
          const rows = (list && list.items) || []
          setItems(rows)
          const newest = rows.length ? rows[0].mtime : 0
          if (seenAt.current && newest > seenAt.current) {
            setFresh(rows.filter((row) => row.mtime > seenAt.current).length)
          }
          if (newest > seenAt.current) seenAt.current = newest
        } catch (error) { /* 桥没起来就保持旧列表，别把面板刷空 */ }
      }, [])

      React.useEffect(() => { loadState(); loadArtifacts() }, [loadState, loadArtifacts])

      React.useEffect(() => {
        const timer = setInterval(() => { if (!busy) loadArtifacts() }, POLL_MS)
        return () => clearInterval(timer)
      }, [busy, loadArtifacts])

      const run = React.useCallback(async (verb, args) => {
        setBusy(true)
        setNote(verb + ' 运行中…')
        try {
          // 桥转发 { tool: 'chem_*', args: {...} }，宿主再转成 bin/chem.py 的子命令。
          const answer = await callBridge('/call', {
            method: 'POST',
            body: JSON.stringify({ tool: verb, args }),
          })
          setEnvelope(answer)
          const summary = summarize(answer)
          setNote(answer && answer.ok
            ? verb + ' 完成 · ' + answer.elapsed_ms + ' ms' + (summary ? ' · ' + summary : '')
            : verb + ' 失败：' + ((answer && answer.failure && answer.failure.message) || '未知原因'))
          await loadState()
          await loadArtifacts()
          return answer
        } catch (error) {
          setNote(verb + ' 失败：' + message(error))
          return null
        } finally {
          setBusy(false)
        }
      }, [loadState, loadArtifacts])

      const source = () => smiles.trim() || 'CCO'

      const draw = () => {
        const input = smiles.trim()
        if (!input) { setNote('先填一个结构（SMILES / InChI / molblock）'); return }
        run('chem_draw', { smiles: input, widthMm, dpi: 300 })
      }

      // 点一张旧图 → 认出它是什么。识别结果里的 SMILES 直接回填输入框，
      // 于是「看看上周那张图」变成「接着改」。
      const readBack = async (item) => {
        const answer = await run('chem_parse', { kind: 'image', source: item.path })
        const found = answer && answer.ok && answer.data && answer.data.best
        if (found && found.smiles) setSmiles(found.smiles)
      }

      // 收藏夹落在 localStorage：常用分子不该每次重贴一遍。读写都包着 try，
      // 拿不到存储（隐私模式/沙箱）就当没有收藏，不让面板因此不渲染。
      React.useEffect(() => {
        try {
          const raw = window.localStorage && window.localStorage.getItem('dsh-chem-pins')
          if (raw) setPins(JSON.parse(raw))
        } catch (error) { /* 没有存储 */ }
      }, [])

      const persist = (next) => {
        setPins(next)
        try {
          if (window.localStorage) window.localStorage.setItem('dsh-chem-pins', JSON.stringify(next))
        } catch (error) { /* 存不下就算了 */ }
      }

      const pinCurrent = () => {
        const input = smiles.trim()
        if (!input) { setNote('先填一个结构再收藏'); return }
        if (pins.some((pin) => pin.smiles === input)) { setNote('这个已经收藏过了'); return }
        persist([{ smiles: input, widthMm: widthMm }].concat(pins).slice(0, 8))
        setNote('已收藏 —— 下次点一下就填回来')
      }

      const unpin = (target) => persist(pins.filter((pin) => pin.smiles !== target))

      // 作业图：一行一个结构，一次画成一张统一键长的联系表。
      const batchDraw = () => {
        const sources = batch.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean)
        if (!sources.length) { setNote('批量：一行填一个结构'); return }
        run('chem_draw', { view: 'grid', smilesList: sources.join(','), widthMm, columns: 3 })
      }

      const copyPath = (item) => {
        try { navigator.clipboard.writeText(item.path) } catch (error) { /* 无剪贴板权限就算了 */ }
        setNote('路径已复制：' + item.name)
      }

      const runtime = (state && state.runtime) || {}
      const lines = envelope ? JSON.stringify(envelope, null, 2).split(String.fromCharCode(10)) : []
      const shown = query.trim()
        ? items.filter((item) => (item.task + '/' + item.name).toLowerCase().indexOf(query.trim().toLowerCase()) >= 0)
        : items
      const base = baseAt.current || cachedBase || ''

      return h('div', { style: S.wrap }, [
        h('div', { key: 'head', style: S.row }, [
          h('strong', { key: 't', style: { fontSize: 13 } }, '化学面板'),
          h('span', { key: 'engine', style: S.chip(!!runtime.ok) }, runtime.ok ? '引擎就绪' : '引擎不可用'),
          h('span', { key: 'count', style: S.badge }, '15 个工具'),
        ]),
        h('div', { key: 'note', style: S.hint }, note),
        h('input', {
          key: 'input', style: S.input, value: smiles, spellCheck: false,
          placeholder: 'SMILES / InChI / molblock，例如 CC(=O)Oc1ccccc1C(=O)O',
          onChange: (event) => setSmiles(event.target.value),
          onKeyDown: (event) => { if (event.key === 'Enter') draw() },
        }),
        h('div', { key: 'ctl', style: S.row }, [
          h('select', {
            key: 'w', style: S.select, value: String(widthMm), disabled: busy,
            onChange: (event) => setWidthMm(Number(event.target.value)),
          }, WIDTHS.map((w) => h('option', { key: w, value: String(w) }, String(w) + ' mm'))),
          h('button', { key: 'draw', style: S.buttonOn, disabled: busy, onClick: draw }, '画出来'),
          h('button', { key: 'pin', style: S.button, disabled: busy, onClick: pinCurrent }, '★ 收藏'),
          h('button', { key: 'clean', style: S.button, disabled: busy,
            onClick: () => run('chem_clean', { smiles: source(), action: 'check' }) }, '体检'),
          h('button', { key: 'fig', style: S.button, disabled: busy,
            onClick: () => run('chem_draw', { smiles: source(), preset: 'acs-1col', dpi: 600 }) }, '投稿图'),
          h('button', { key: '3d', style: S.button, disabled: busy,
            onClick: () => run('chem_draw', { smiles: source(), view: '3d' }) }, '3D'),
          h('button', { key: 'props', style: S.button, disabled: busy,
            onClick: () => run('chem_props', { smiles: source() }) }, '性质'),
        ]),
        pins.length ? h('div', { key: 'pins', style: S.row }, pins.map((pin) => h('span', { key: pin.smiles, style: S.pin }, [
          h('button', {
            key: 'b', style: S.pinBtn, disabled: busy, title: pin.smiles,
            onClick: () => { setSmiles(pin.smiles); setWidthMm(pin.widthMm || 85) },
          }, pin.smiles.length > 13 ? pin.smiles.slice(0, 13) + '…' : pin.smiles),
          h('button', { key: 'x', style: S.pinX, onClick: () => unpin(pin.smiles) }, '×'),
        ]))) : null,
        h('div', { key: 'tools2', style: S.row }, [
          h('input', {
            key: 'q', style: S.input, value: query,
            placeholder: '过滤产物：文件名或任务',
            onChange: (event) => setQuery(event.target.value),
          }),
          h('button', {
            key: 'b', style: showBatch ? S.buttonOn : S.button,
            onClick: () => setShowBatch(!showBatch),
          }, showBatch ? '收起批量' : '批量'),
        ]),
        showBatch ? h('textarea', {
          key: 'batch', value: batch, spellCheck: false,
          style: Object.assign({}, S.input, { minHeight: 62, fontFamily: 'inherit', resize: 'vertical' }),
          placeholder: '一行一个结构，拼成一张联系表（作业图）',
          onChange: (event) => setBatch(event.target.value),
        }) : null,
        showBatch ? h('div', { key: 'brow', style: S.row }, [
          h('button', { key: 'go', style: S.buttonOn, disabled: busy, onClick: batchDraw }, '拼成联系表'),
          h('span', { key: 'h', style: S.hint }, '统一键长，横向可比'),
        ]) : null,
        h('div', { key: 'galhead', style: S.spread }, [
          h('span', { key: 'l', style: S.section }, '最近产物'),
          h('span', { key: 'r', style: S.row }, [
            fresh ? h('span', { key: 'f', style: S.badge }, '+' + fresh + ' 新') : null,
            h('button', {
              key: 'r2', style: S.button, disabled: busy,
              onClick: () => { setFresh(0); loadArtifacts() },
            }, '刷新'),
          ]),
        ]),
        shown.length
          ? h('div', { key: 'grid', style: S.thumbGrid }, shown.slice(0, 9).map((item) => h('button', {
              key: item.task + '/' + item.name,
              style: S.thumb(!!picked && picked.path === item.path),
              title: item.task + '/' + item.name,
              onClick: () => { setFresh(0); setPicked(item); baseAt.current = cachedBase || '' },
            }, h('img', {
              style: S.thumbImg,
              src: base + '/artifact?task=' + encodeURIComponent(item.task) + '&name=' + encodeURIComponent(item.name) + '&v=' + Math.round(item.mtime),
              alt: item.name,
            }))))
          : h('div', { key: 'empty', style: S.hint }, '还没有产物。画一张试试，或者等 agent 画完 —— 这里会自己出现。'),
        picked
          ? h('div', { key: 'picked', style: S.wrap }, [
              h('div', { key: 'p', style: S.row }, [
                h('span', { key: 'n', style: S.hint }, picked.task + ' / ' + picked.name),
                h('button', { key: 'o', style: S.button, disabled: busy, onClick: () => readBack(picked) }, '识别这张图'),
                h('button', { key: 'c', style: S.button, disabled: busy, onClick: () => copyPath(picked) }, '复制路径'),
              ]),
              h('div', { key: 'box', style: S.shotBox },
                h('img', {
                  style: S.img,
                  src: base + '/artifact?task=' + encodeURIComponent(picked.task) + '&name=' + encodeURIComponent(picked.name) + '&v=' + Math.round(picked.mtime),
                  alt: picked.name,
                })),
            ])
          : null,
        h('div', { key: 'hint', style: S.hint },
          '面板与 agent 共用同一个引擎（chem.py 的 15 个工具）：这里画出来的，就是 agent 交的那份文件。'),
        h('div', { key: 'jhead', style: S.row }, [
          h('button', { key: 'j', style: S.button, disabled: !envelope, onClick: () => setShowJson(!showJson) },
            showJson ? '收起完整结果' : '看完整结果'),
        ]),
        showJson && lines.length ? h('pre', { key: 'json', style: S.pre }, lines.join(String.fromCharCode(10))) : null,
      ])
    }

    // 右侧栏的 tab 类型。开始页那排胶囊（工作区文件 / 上下文 / 浏览器 …）
    // 就是各插件在 guide 数组里声明的入口，我们照同一条公开路径挂一个。
    const TAB_ID = PLUGIN_ID + '/panel'
    const TAB_KIND = 'chem'

    const plugin = {
      name: PLUGIN_ID,
      inject: ['slots'],
      apply(ctx) {
        const steps = []
        const note = (step) => { steps.push(step); void report(steps) }

        // 类型注册要 sidebarRightTabs 服务；坐席正文要 sidebar.right.pane.tab 槽。
        // 两样都用嵌套 inject：服务/槽缺席时这段不执行，插件本身照样算激活。
        // 不写进顶层 inject —— 那样一处缺席会把整个 apply 挂起，
        // 客户端启动会报「entry did not activate」，连带兜底入口一起没有。
        const declare = (scope) => {
          try {
            scope.effect(() => scope.sidebarRightTabs.register({
              id: TAB_ID,
              kind: TAB_KIND,
              priority: 'builtin',
              title: () => '化学绘图',
              guide: [{
                id: 'panel',
                order: 25,
                title: () => '化学绘图',
                description: () => '画结构、看产物、照图读结构',
              }],
            }))
            note('type:ok')
          } catch (error) {
            note('type:err:' + message(error))
          }
          try {
            scope.slots.inject('sidebar.right.pane.tab', () => scope.slots.register(
              { name: 'sidebar.right.pane.tab', key: TAB_ID },
              Panel,
            ))
            note('pane:ok')
          } catch (error) {
            note('pane:err:' + message(error))
          }
        }

        if (typeof ctx.inject === 'function') {
          try {
            ctx.inject(['sidebarRightTabs'], declare)
            note('inject:queued')
          } catch (error) {
            note('inject:err:' + message(error))
          }
        } else {
          note('inject:missing')
        }

        // 兜底入口：设置页也能打开同一块面板。
        try {
          ctx.slots.inject('settings.section', () => ctx.slots.register(
            { name: 'settings.section', id: PLUGIN_ID, order: 46, label: () => '化学绘图' },
            Panel,
          ))
          note('settings:ok')
        } catch (error) {
          note('settings:err:' + message(error))
        }
      },
    }
    return plugin
  },
})
