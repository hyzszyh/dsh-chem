// W8 gate: the panel's loopback bridge really forwards to the 15 registered tools,
// and refuses anything else. Runs on plain node against the real engine.
import { mkdirSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

import { startBridge, TOOLS } from '../dsh-plugin/lib/sidebar-bridge.js'

const results = []
const check = (label, ok, detail = '') => results.push({ label, ok: Boolean(ok), detail })
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const bridge = startBridge({ logger: { info() {}, warn() {} } })
await sleep(400)
const base = 'http://127.0.0.1:' + bridge.port()

async function post(path, body) {
  const response = await fetch(base + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  return { status: response.status, body: await response.json() }
}

try {
  const health = await (await fetch(base + '/health')).json()
  check('health answers with the plugin id', health.ok === true && health.plugin === 'dsh-chem', JSON.stringify(health))

  const state = await (await fetch(base + '/state')).json()
  check('state lists 15 tools', Array.isArray(state.tools) && state.tools.length === 15, String((state.tools || []).length))
  check('state reports the runtime', state.runtime && typeof state.runtime.ok === 'boolean', JSON.stringify(state.runtime || {}).slice(0, 90))

  const props = await post('/call', { tool: 'chem_props', args: { smiles: 'CCO' } })
  check('call chem_props returns MW 46.069', props.body.ok === true && Math.abs(props.body.data.mw - 46.069) < 1e-6, String((props.body.data || {}).mw))
  check('call reports elapsed time', typeof props.body.elapsed_ms === 'number', String(props.body.elapsed_ms))

  const outDir = join(process.env.TEMP || '.', 'dsh-chem-bridge')
  mkdirSync(outDir, { recursive: true })
  const figure = await post('/call', { tool: 'chem_draw', args: { smiles: 'CCO', format: 'svg', out: join(outDir, 'bridge.svg') } })
  check('call chem_draw writes a file', figure.body.ok === true && existsSync(join(outDir, 'bridge.svg')), String((figure.body.data || {}).path))

  const bare = await post('/call', { tool: 'draw', args: { smiles: 'CCO' } })
  check('bare verb is promoted to chem_draw', bare.body.ok === true && bare.body.tool === 'chem_draw', String(bare.body.tool))

  const rejected = await post('/call', { tool: 'os_shell', args: { cmd: 'dir' } })
  check('unknown tool is refused', rejected.status === 400 && rejected.body.ok === false, String(rejected.status))
  check('refusal lists the allowed tools', Array.isArray(rejected.body.failure.known) && rejected.body.failure.known.length === 15, String((rejected.body.failure.known || []).length))

  const clean = await post('/call', { tool: 'chem_clean', args: { smiles: 'CC(=O)[O-].[Na+]', action: 'fix' } })
  check('call chem_clean fixes a salt', clean.body.ok === true && clean.body.data.after === 'CC(=O)O', JSON.stringify(clean.body.data || {}).slice(0, 80))

  const unknownPath = await (await fetch(base + '/nope')).json()
  check('unknown route is 404', unknownPath.ok === false)

  // /artifacts reads the shared artifact root, which the agent also writes to.
  const root = join(process.env.LOCALAPPDATA || '', 'dsh-chem', 'artifacts', 'bridge-smoke')
  mkdirSync(root, { recursive: true })
  writeFileSync(join(root, 'probe.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47]))
  const listing = await (await fetch(base + '/artifacts')).json()
  check('artifacts lists the probe', listing.items.some((row) => row.name === 'probe.png'), String(listing.total))
  const raw = await fetch(base + '/artifact?task=bridge-smoke&name=probe.png')
  check('artifact bytes are served', raw.status === 200 && (await raw.arrayBuffer()).byteLength === 4, String(raw.status))
  const traversal = await fetch(base + '/artifact?task=..&name=secret.png')
  check('path traversal refused', traversal.status === 400, String(traversal.status))
  rmSync(root, { recursive: true, force: true })
} finally {
  bridge.close()
}

let failed = 0
for (const row of results) {
  if (!row.ok) failed += 1
  console.log((row.ok ? 'PASS  ' : 'FAIL  ') + row.label + (row.detail ? '  [' + row.detail + ']' : ''))
}
console.log('')
console.log(failed === 0
  ? 'W8 bridge: ' + results.length + '/' + results.length + ' PASS'
  : 'W8 bridge: ' + (results.length - failed) + '/' + results.length + ' PASS, ' + failed + ' FAIL')
process.exit(failed === 0 ? 0 : 1)
