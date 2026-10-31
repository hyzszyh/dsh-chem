// Does the sidebar panel actually render?
//
// The bug this exists for: the client bundle registered its factory fine -- apply()
// ran, the seat showed up -- and then the panel never appeared. Panel() called
// require('react') inside the component, but require only exists inside the
// factory closure, so rendering threw a ReferenceError inside React and the slot
// stayed empty. A registering-only harness passed; only rendering caught it.
//
// So this loads the real installed bundle against a fake host and renders the
// component once, then asserts the visible text.
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import vm from 'node:vm'

const candidates = [
  process.env.CHEM_PLUGIN_CLIENT,
  join(homedir(), '.dsh', 'plugins', 'dsh-chem-draw-tool', 'lib', 'client.js'),
  new URL('../dsh-plugin/lib/client.js', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'),
].filter(Boolean)

let source = null
let used = null
for (const path of candidates) {
  try { source = readFileSync(path, 'utf8'); used = path; break } catch { /* try the next */ }
}
if (!source) { console.log('SKIP  the plugin client bundle is not on disk'); process.exit(0) }

let failures = 0
function check(label, ok) {
  console.log((ok ? '  PASS ' : '  FAIL ') + label)
  if (!ok) failures += 1
}

const slots = {
  registered: [],
  register(spec, Component) {
    if (spec.key !== undefined) {
      const clash = this.registered.find((row) => row.spec.name === spec.name && row.spec.key === spec.key)
      if (clash) throw new Error('duplicate seat ' + spec.name + ' key ' + spec.key)
    }
    this.registered.push({ spec, Component })
    return () => {}
  },
  inject(name, cb) { cb(); return () => {} },
}
const types = []
const react = {
  createElement(type, props, children) { return { type, props: props || {}, children } },
  useState(init) { return [typeof init === 'function' ? init() : init, () => {}] },
  useCallback(fn) { return fn },
  useRef(init) { return { current: typeof init === 'function' ? init() : init } },
  useEffect() {},
}
const sandbox = {
  window: {
    __ModuleLoader__: {
      load({ id, factory }) { sandbox.__plugin = factory((name) => (name === 'react' ? react : {})); sandbox.__id = id },
    },
  },
  console,
  fetch: () => Promise.reject(new Error('offline')),
  AbortSignal: { timeout: () => null },
  setInterval: () => 0,
  clearInterval: () => {},
  navigator: { clipboard: { writeText() {} } },
  encodeURIComponent,
  Date, JSON, String, Number, Object, Array, Math, Promise, Error,
}

console.log('bundle: ' + used)
vm.runInNewContext(source, sandbox)
check('the bundle calls the module loader', !!sandbox.__plugin)
check('the module id is the package name', sandbox.__id === 'dsh-chem-draw-tool')
sandbox.__plugin.apply({
  slots,
  // the right-pane registry and cordis' effect(); registering the tab type is what
  // puts the entry capsule on the right pane's start page.
  sidebarRightTabs: { register(definition) { types.push(definition); return () => {} } },
  // cordis 的嵌套 inject：服务齐了才跑回调。测试里当它立即可用。
  inject(names, cb) { cb(this) },
  effect(fn) { return fn() },
})

const names = slots.registered.map((row) => row.spec.name)
check('it declares a right pane tab type', types.length === 1)
const type = types[0] || {}
check('the tab type is titled in Chinese', typeof type.title === 'function' && type.title() === '化学绘图')
check('the tab type carries a start-page guide entry', Array.isArray(type.guide) && type.guide.length === 1)
check('the guide entry has a description', typeof type.guide?.[0]?.description === 'function' && type.guide[0].description().length > 0)
check('it registers the right pane body under the type id', names.includes('sidebar.right.pane.tab'))
check('the pane body key is the type id', slots.registered.some((row) => row.spec.name === 'sidebar.right.pane.tab' && row.spec.key === type.id))
check('it keeps a settings fallback', names.includes('settings.section'))

function text(node) {
  if (node === null || node === undefined || node === false) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(text).join(' ')
  if (node.children !== undefined) return text(node.children)
  return ''
}

function nodes(node, out = []) {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) { node.forEach((child) => nodes(child, out)); return out }
  out.push(node)
  if (node.children !== undefined) nodes(node.children, out)
  return out
}

let tree = null
let rendered = ''
try {
  tree = slots.registered[0].Component({})
  rendered = text(tree)
} catch (error) {
  console.log('  FAIL rendering threw: ' + (error && error.message))
  failures += 1
}
check('the panel renders a title', rendered.includes('化学面板'))
check('it offers the task buttons', ['体检', '画出来', '投稿图', '3D', '收工关窗'].every((k) => rendered.includes(k)))
const inputs = nodes(tree).filter((node) => node.type === 'input')
check('it offers a width picker', nodes(tree).some((node) => node.type === 'select'))
check('it has a recent-artifacts section', rendered.includes('最近产物'))
check('it can pin the current structure', rendered.includes('★ 收藏'))
check('it can build a contact sheet', rendered.includes('批量'))
check('it can filter artifacts', nodes(tree).some((node) => String((node.props && node.props.placeholder) || '').includes('过滤产物')))
check('it has a structure input', inputs.some((node) => String((node.props && node.props.placeholder) || '').includes('SMILES')))

if (failures) { console.log(failures + ' FAILED'); process.exit(1) }
console.log('all client checks passed')