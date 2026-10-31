// Checks the plugin's wiring without a DSH host: that all tools register, that
// each one declares a usable schema, and that a real call reaches the CLI and
// comes back with an envelope.
//
//     node test/test_plugin_tools.mjs
//
// This is the layer that used to be unverified: the bundle could load, but
// nothing proved the tools actually ran.

import { apply } from '../dsh-plugin/lib/index.js'

const registered = new Map()
const ctx = {
  tools: {
    register(tool) {
      if (registered.has(tool.name)) throw new Error('duplicate tool name: ' + tool.name)
      registered.set(tool.name, tool)
    },
  },
}

apply(ctx)

let failures = 0
function check(name, condition, detail) {
  if (condition) {
    console.log('  PASS ' + name)
  } else {
    failures += 1
    console.log('  FAIL ' + name + (detail ? ' -- ' + detail : ''))
  }
}

console.log('registered tools: ' + registered.size)

// 15 atomic tools (v1) plus 14 task tools (v2), since the plugin now carries
// both surfaces: the atomic ones when a caller wants one step, the task ones
// when it wants a finished artefact. They never share a tool name.
check('tool count is 30', registered.size === 30, 'got ' + registered.size)

for (const [name, tool] of registered) {
  check(name + ' has a description', typeof tool.description === 'string' && tool.description.length > 40)
  check(name + ' declares parameters', tool.parameters !== undefined)
  check(name + ' has an execute', typeof tool.execute === 'function')
  check(name + ' has an output renderer', tool.output && typeof tool.output.render === 'function')
}

const names = [...registered.keys()].sort()
console.log('names: ' + names.join(', '))

// Two channels must both be represented, and no tool may live in neither.
const chemdraw = names.filter(n => n.startsWith('chemdraw_'))
const kingdraw = names.filter(n => n.startsWith('kingdraw_'))
const shared = names.filter(n => n.startsWith('chem_'))
check('chemdraw channel has 5 tools', chemdraw.length === 5, chemdraw.join(','))
check('kingdraw channel has 7 tools', kingdraw.length === 7, kingdraw.join(','))
const SHARED = ['chem_crosscheck', 'chem_doctor', 'chem_identity']
const sharedMissing = SHARED.filter(n => !registered.has(n))
check('shared v1 tools exist', sharedMissing.length === 0, sharedMissing.join(','))
check('no chem_ tool is unclaimed', shared.length === 18, shared.length)

// v2 task tools: one call, one finished task.
const TASKS = ['chem_analyze', 'chem_batch', 'chem_check', 'chem_close',
  'chem_convert', 'chem_draw', 'chem_figure', 'chem_3d', 'chem_grade',
  'chem_ocr', 'chem_reaction', 'chem_resolve', 'chem_status', 'chem_stoich',
  'chem_variants']
const missing = TASKS.filter(n => !registered.has(n))
check('14 task tools are registered', missing.length === 0, missing.join(','))

// A real round trip: this goes through bridge.js, config.js and the Python CLI.
console.log('')
console.log('live call: chem_identity')
const identity = registered.get('chem_identity')
const raw = await identity.execute({ smiles: 'c1ccccc1O' })
let payload = null
try { payload = JSON.parse(raw) } catch { }
check('chem_identity returns JSON', payload !== null)
check('chem_identity succeeds', payload && payload.ok === true, raw.slice(0, 160))
check('chem_identity got the right InChIKey',
  payload && payload.inchikey === 'ISWSIDIOOBJBQZ-UHFFFAOYSA-N',
  payload && payload.inchikey)
check('chem_identity reports the formula', payload && payload.formula === 'C6H6O', payload && payload.formula)

// The failure path matters as much: an unparseable structure must come back as
// a structured failure, not as a thrown error or a silent success.
console.log('live call: chem_identity (bad input)')
const bad = await registered.get('chem_identity').execute({ smiles: 'this-is-not-smiles' })
const badPayload = JSON.parse(bad)
check('bad input does not throw', true)
check('bad input is reported as failure', badPayload.ok === false, bad.slice(0, 160))
check('bad input carries an error code', Boolean(badPayload.failure && badPayload.failure.code))

// The task surface has to reach the CLI too, not just be declared.
console.log('live call: chem_check')
const checkRaw = await registered.get('chem_check').execute({ source: 'CCO' })
let checkPayload = null
try { checkPayload = JSON.parse(checkRaw) } catch { }
check('chem_check returns JSON', checkPayload !== null)
check('chem_check succeeds', checkPayload && checkPayload.ok === true,
  String(checkRaw).slice(0, 160))
check('chem_check saw the formula',
  checkPayload && checkPayload.data && checkPayload.data.summary.formula === 'C2H6O',
  checkPayload && checkPayload.data && checkPayload.data.summary.formula)

console.log('')
if (failures) {
  console.log(failures + ' check(s) failed')
  process.exit(1)
}
console.log('all checks passed')