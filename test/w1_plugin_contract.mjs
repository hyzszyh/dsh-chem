// W1 contract test: does the plugin declare exactly the 15 tools, with usable
// schemas, and does the engine bridge actually reach the venv runtime?
//
// Runs on plain node: the repo vendors a stub of @deepseek-ai/dsh-tools under
// dsh-plugin/node_modules, so index.js imports without the host.

import { apply, name, inject } from '../dsh-plugin/lib/index.js'
import { call, status } from '../dsh-plugin/lib/engine.js'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

const OUT = join(process.env.TEMP || process.env.TMPDIR || '.', 'dsh-chem-contract')
mkdirSync(OUT, { recursive: true })
const tmpPath = (file) => join(OUT, file)

const EXPECTED = [
  'chem_parse', 'chem_clean', 'chem_draw', 'chem_props', 'chem_calc',
  'chem_compare', 'chem_table', 'chem_db', 'chem_ml', 'chem_enum',
  'chem_retro', 'chem_spectra', 'chem_exam', 'chem_office', 'chem_vendor',
]

const results = []
const check = (label, ok, detail = '') => results.push({ label, ok, detail })

const registered = []
const fakeCtx = { tools: { register: (tool) => registered.push(tool) } }
const exposed = apply(fakeCtx)

check('plugin name', name === 'dsh-chem', name)
check('inject tools', Array.isArray(inject) && inject.includes('tools'), JSON.stringify(inject))
check('tool count', registered.length === EXPECTED.length, registered.length + ' / ' + EXPECTED.length)

const names = registered.map((t) => t.name)
for (const want of EXPECTED) check('declares ' + want, names.includes(want), names.join(','))
check('no duplicate names', new Set(names).size === names.length)
check('no unexpected names', names.every((n) => EXPECTED.includes(n)), names.filter((n) => !EXPECTED.includes(n)).join(','))

for (const tool of registered) {
  const params = tool.parameters || {}
  const required = Object.values(params).filter((p) => p && p.required).length
  check(tool.name + ' description', typeof tool.description === 'string' && tool.description.length >= 40, (tool.description || '').length + ' chars')
  check(tool.name + ' params object', typeof params === 'object' && params !== null)
  check(tool.name + ' execute fn', typeof tool.execute === 'function')
  check(tool.name + ' output render', Boolean(tool.output && tool.output.render))
  void required
}

const runtime = status()
check('runtime ready', runtime.ready === true, runtime.python || 'missing')

// One real round trip through the exact path every tool uses.
const selfcheck = await call('selfcheck', {})
check('engine selfcheck ok', selfcheck.ok === true, JSON.stringify(selfcheck).slice(0, 200))
const mw = (selfcheck.checks || []).find((c) => c.name === 'mw')
check('selfcheck mw 151.16', Boolean(mw && mw.ok && Math.abs(mw.value - 151.16) < 0.01), mw ? String(mw.value) : 'none')
const pdf = (selfcheck.checks || []).find((c) => c.name === 'svg_to_pdf')
check('selfcheck svg->pdf', Boolean(pdf && pdf.ok), pdf ? pdf.bytes + ' bytes' : 'none')

// Every declared tool is now implemented, so the loud-failure check moves to the
// engine's unknown-tool path: a name nobody registered must not look like success.
const unknown = await call('chemistry_is_not_a_tool', { smiles: 'CCO' })
check('unknown tool fails loudly', unknown.ok === false && Array.isArray(unknown.known) && unknown.known.length >= 15, JSON.stringify(unknown).slice(0, 200))

// A built tool must go all the way through: plugin -> engine -> python -> JSON.
const built = await call('props', { smiles: 'CCO' })
check('built tool props mw 46.069', built.ok === true && Math.abs(built.data.mw - 46.069) < 1e-6, String(built.data && built.data.mw))
const cleaned = await call('clean', { smiles: 'CC(=O)[O-].[Na+]', action: 'fix' })
check('built tool clean fixes salt', cleaned.ok === true && cleaned.data.after === 'CC(=O)O', JSON.stringify(cleaned.data || {}).slice(0, 120))
const figure = await call('draw', { smiles: 'CCO', format: 'svg', widthMm: 85 })
check('built tool draw returns vector svg', figure.ok === true && figure.data.vector === true && figure.data.widthPx === 1004, JSON.stringify({ ok: figure.ok, vector: figure.data && figure.data.vector, px: figure.data && figure.data.widthPx }))
const named = await call('parse', { source: '扑热息痛' })
check('built tool parse resolves chinese name', named.ok === true && named.data.inchikey === 'RZVAJINKPMORJF-UHFFFAOYSA-N', JSON.stringify({ ok: named.ok, ik: named.data && named.data.inchikey }))
const isomers = await call('enum', { mode: 'stereo', smiles: 'CC(Cl)Br' })
check('built tool enum counts stereoisomers', isomers.ok === true && isomers.data.count === 2, JSON.stringify({ ok: isomers.ok, n: isomers.data && isomers.data.count }))
const library = await call('db', { action: 'stats' })
check('built tool db reports stats', library.ok === true && typeof library.data.total === 'number', JSON.stringify(library.data || {}).slice(0, 120))
const models = await call('ml', { action: 'list' })
check('built tool ml lists models', models.ok === true && Array.isArray(models.data.models), JSON.stringify(models.data || {}).slice(0, 120))
const cdxml = await call('vendor', { action: 'write', smiles: 'CCO', out: tmpPath('contract.cdxml') })
check('built tool vendor writes cdxml', cdxml.ok === true && cdxml.data.reread === 1, JSON.stringify({ ok: cdxml.ok, reread: cdxml.data && cdxml.data.reread }))
const graded = await call('exam', { answer: 'CCO', submissions: 'CCO,COC' })
check('built tool exam grades', graded.ok === true && graded.data.score === 50, JSON.stringify({ ok: graded.ok, score: graded.data && graded.data.score }))

let failed = 0
for (const r of results) {
  if (!r.ok) failed++
  console.log((r.ok ? 'PASS  ' : 'FAIL  ') + r.label + (r.detail ? '  [' + r.detail + ']' : ''))
}
console.log('')
console.log(failed === 0 ? 'W1 contract: ' + results.length + '/' + results.length + ' PASS' : 'W1 contract: ' + (results.length - failed) + '/' + results.length + ' PASS, ' + failed + ' FAIL')
process.exit(failed === 0 ? 0 : 1)