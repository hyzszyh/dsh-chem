// W9 wiring proof: load the plugin through the exact path the profile links to,
// with a stub host, and check what it would register.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

// Derived from this file, not hardcoded: the profile links to the checkout wherever
// it lives, and a clone anywhere else has to be able to run this proof.
const REPO = join(dirname(fileURLToPath(import.meta.url)), '..')
const PLUGIN = join(REPO, 'dsh-plugin')
const ENTRY = pathToFileURL(join(PLUGIN, 'lib', 'index.js')).href
const registered = []
const ctx = {
  tools: { register: (spec) => { registered.push(spec) } },
  logger: { info() {}, warn() {} },
  effect() {},
}

const mod = await import(ENTRY)
const result = mod.apply(ctx)
const names = registered.map((spec) => spec.name)
const EXPECTED = ['chem_parse', 'chem_clean', 'chem_draw', 'chem_props', 'chem_calc',
  'chem_compare', 'chem_table', 'chem_db', 'chem_ml', 'chem_enum',
  'chem_retro', 'chem_spectra', 'chem_exam', 'chem_office', 'chem_vendor']

const patch = readFileSync(join(PLUGIN, 'cordis.patch.yml'), 'utf8')
const rows = []
const check = (label, ok, detail = '') => rows.push({ label, ok: Boolean(ok), detail })

check('module exports a name', mod.name === 'dsh-chem', String(mod.name))
check('module declares tool injection', Array.isArray(mod.inject) && mod.inject.includes('tools'), JSON.stringify(mod.inject))
check('registers exactly 15 tools', names.length === 15, String(names.length))
check('tool names match the contract', JSON.stringify(names) === JSON.stringify(EXPECTED), names.join(','))
check('every tool has a description', registered.every((s) => typeof s.description === 'string' && s.description.length >= 40), String(Math.min(...registered.map((s) => (s.description || '').length))))
check('every tool has parameters', registered.every((s) => s.parameters && typeof s.parameters === 'object'))
check('runtime reported ready', result.runtime && result.runtime.ready === true, JSON.stringify(result.runtime || {}).slice(0, 60))
check('bridge opened a port', typeof result.bridgePort === 'number' && result.bridgePort > 0, String(result.bridgePort))
check('bundle patch is active', Boolean(mod.name) && /id:\s*dsh-chem/.test(patch), patch.trim().split('\n').slice(0, 2).join(' | '))

// One real call through the registered execute(), i.e. the path a model would take.
const props = registered.find((s) => s.name === 'chem_props')
const answer = await props.execute({ smiles: 'CCO' })
const text = JSON.stringify(answer)
check('registered tool executes for real', text.includes('46.069'), text.slice(0, 120))

result.closeBridge()
let failed = 0
for (const row of rows) {
  if (!row.ok) failed += 1
  console.log((row.ok ? 'PASS  ' : 'FAIL  ') + row.label + (row.detail ? '  [' + row.detail + ']' : ''))
}
console.log('')
console.log(failed === 0 ? 'W9 wiring: ' + rows.length + '/' + rows.length + ' PASS'
  : 'W9 wiring: ' + (rows.length - failed) + '/' + rows.length + ' PASS, ' + failed + ' FAIL')
process.exit(failed === 0 ? 0 : 1)
