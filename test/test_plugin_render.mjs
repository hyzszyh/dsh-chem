// What the tool card actually shows. The renderer used to hand the whole
// envelope to the host as raw JSON text, so chem_identity showed "ok": true
// and six levels of nesting before the InChIKey anyone actually wanted.
//
//     node test/test_plugin_render.mjs

import { apply } from '../dsh-plugin/lib/index.js'

const registered = new Map()
apply({ tools: { register: (tool) => registered.set(tool.name, tool) } })

let failures = 0
function check(name, condition, detail) {
  if (condition) console.log('  PASS ' + name)
  else { failures += 1; console.log('  FAIL ' + name + (detail ? ' -- ' + detail : '')) }
}

function card(tool, payload) {
  const value = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2)
  const rendered = tool.output.render({}, value)
  return rendered.map((part) => part.text).join('')
}

const identity = registered.get('chem_identity')
const drawing = registered.get('kingdraw_export')

const good = {
  ok: true,
  channel: 'rdkit',
  data: { canonical_smiles: 'Oc1ccccc1', inchikey: 'ISWSIDIOOBJBQZ-UHFFFAOYSA-N', formula: 'C6H6O' },
  evidence: 'A',
  warnings: [],
}
const text = card(identity, good)
const headLines = text.split('\n')
check('starts with a tick, not a brace', headLines[0].startsWith('✓'), headLines[0])
check('InChIKey appears in the headline', headLines.slice(0, 6).join(' ').includes('ISWSIDIOOBJBQZ'))
check('formula appears in the headline', headLines.slice(0, 6).join(' ').includes('C6H6O'))
check('the full envelope is still there', text.includes('"evidence": "A"'))
check('raw JSON is not the first thing shown', !headLines[0].startsWith('{'))

const bad = {
  ok: false,
  data: null,
  failure: {
    code: 'E04', channel: 'kingdraw', stage: 'bitness',
    message: 'KingDraw core library is x86; this interpreter is x64',
    hint: 'Run with runtime/py32/python.exe',
  },
}
const badText = card(identity, bad)
const badHead = badText.split('\n')
check('failure starts with a cross', badHead[0].startsWith('✗'), badHead[0])
check('failure names the code and channel', badHead[0].includes('E04') && badHead[0].includes('kingdraw'))
check('failure shows the message', badText.includes('is x86'))
check('failure shows the fix', badText.includes('runtime/py32/python.exe'))
check('failure keeps the envelope', badText.includes('"stage": "bitness"'))

const degraded = {
  ok: true,
  channel: 'kingdraw',
  data: { degraded: true, out: 'test/out/phenol_kingdraw.png', bytes: 26633 },
}
const degradedText = card(drawing, degraded)
check('a degraded result says it is preview-grade', degradedText.includes('预览级'), degradedText.split('\n')[0])

check('non-JSON output is passed through untouched',
  card(identity, 'Traceback (most recent call last): boom') === 'Traceback (most recent call last): boom')

const big = { ok: true, channel: 'chemdraw', data: { path: 'x'.repeat(400), atoms: 7 } }
const bigText = card(identity, big)
check('a very long value is not dumped into the headline',
  bigText.split('\n')[1].length < 200, bigText.split('\n')[1])
check('but it survives in the envelope', bigText.includes('x'.repeat(400)))

console.log('')
if (failures) { console.log(failures + ' FAILED'); process.exit(1) }
console.log('all render checks passed')