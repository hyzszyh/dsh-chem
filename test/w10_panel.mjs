// w10_panel.mjs — the panel is client-side code the test runner never executed.
//
// It shipped once with PLUGIN_ID still set to the pre-rename name while the bridge
// answered 'dsh-chem', so discover() could never match and the panel would have sat
// there failing to find its own backend. Nothing caught it: contract tests covered
// the server side, the bridge test drove HTTP directly, and nobody opened the panel.
// These assertions are the cheap stand-in for that photograph. Paths come from
// this file, so the check travels with the checkout.

import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PLUGIN = join(dirname(fileURLToPath(import.meta.url)), '..', 'dsh-plugin')
const results = []
const check = (ok, label, detail) => results.push({ ok: !!ok, label, detail })

const client = readFileSync(join(PLUGIN, 'lib/client.js'), 'utf8')
const bridge = readFileSync(join(PLUGIN, 'lib/sidebar-bridge.js'), 'utf8')
const index = readFileSync(join(PLUGIN, 'lib/index.js'), 'utf8')
const pkg = JSON.parse(readFileSync(join(PLUGIN, 'package.json'), 'utf8'))

const grab = (source, pattern) => {
  const found = source.match(pattern)
  return found ? found[1] : null
}

// 1. Syntax: a broken client bundle is invisible until the panel is opened.
let parsed = true
try {
  execFileSync(process.execPath, ['--check', join(PLUGIN, 'lib/client.js')], { stdio: 'pipe' })
} catch (error) {
  parsed = false
  check(false, 'client.js parses', String(error.stderr || error).slice(0, 160))
}
if (parsed) check(true, 'client.js parses')

// 2. One name, three places. This is the bug that shipped.
const clientId = grab(client, /const PLUGIN_ID = '([^']+)'/)
const bridgeId = grab(bridge, /export const PLUGIN_ID = '([^']+)'/)
check(clientId === bridgeId, 'panel and bridge agree on the plugin id',
  'client=' + clientId + ' bridge=' + bridgeId)
check(clientId === pkg.name, 'plugin id is the package name',
  'client=' + clientId + ' package=' + pkg.name)
check(!/dsh-chem-draw-tool/.test(client + bridge + index),
  'no pre-rename plugin name left in lib/', 'searched three files')

// 3. The panel only talks to endpoints the bridge actually answers.
const bridgeRoutes = [...bridge.matchAll(/url\.pathname === '([^']+)'/g)].map((m) => m[1])
const clientRoutes = [...client.matchAll(/callBridge\('([^']+)'|fetch\([^)]*\+ '([^']+)'/g)]
  .map((m) => m[1] || m[2])
  .map((route) => (route ? route.split('?')[0] : route))   // '/artifacts?limit=9' is '/artifacts'
  .filter((route) => route && route.startsWith('/'))
const unknown = [...new Set(clientRoutes)].filter((route) => !bridgeRoutes.includes(route))
check(unknown.length === 0, 'every endpoint the panel calls exists in the bridge',
  unknown.length ? 'missing: ' + unknown.join(', ') : bridgeRoutes.length + ' routes declared')

// 4. Every verb the panel can send is a registered tool AND on the bridge whitelist.
const verbs = [...new Set([...client.matchAll(/run\(\s*'([^']+)'/g)].map((m) => m[1]))]
const registered = [...index.matchAll(/name:\s*'(chem_[a-z_]+)'/g)].map((m) => m[1])
const whitelist = [...bridge.matchAll(/'(chem_[a-z_]+)'/g)].map((m) => m[1])
const unregistered = verbs.filter((verb) => !registered.includes(verb))
const unlisted = verbs.filter((verb) => !whitelist.includes(verb))
check(verbs.length >= 4, 'panel exposes the four core verbs', verbs.join(' '))
check(unregistered.length === 0, 'panel verbs are registered tools',
  unregistered.join(', ') || verbs.length + '/' + registered.length)
check(unlisted.length === 0, 'panel verbs pass the bridge whitelist', unlisted.join(', ') || 'ok')

// 5. It has to be mounted somewhere, or it is a file nobody loads.
check(/slots\.inject\('settings\.section'/.test(client), 'panel registers a settings section', null)
check(/TAB_ID/.test(client) && /name: PLUGIN_ID/.test(client), 'panel registers a tab', null)
check(/localStorage/.test(client) && /catch/.test(client), 'pins degrade quietly when storage is blocked', null)

// 6. Fields, not vibes. The panel shipped once still asking for v2-era channels /
// session, which the new bridge never sends: two chips went red and the header said
// '会话未连接' on a perfectly healthy engine. Every field the panel reads has to be
// a field the bridge actually writes.
const stateBlock = bridge.match(/url\.pathname === '\/state'\)[\s\S]*?JSON\.stringify\(\{([\s\S]*?)\n      \}\)\)/)
const bridgeFields = stateBlock
  ? [...stateBlock[1].matchAll(/^\s*([a-z_]+):/gm)].map((m) => m[1])
  : []
const clientFields = [...new Set([...client.matchAll(/\b(?:info|state)\.([a-z_]+)/g)].map((m) => m[1]))]
const unknownFields = clientFields.filter((field) => !bridgeFields.includes(field))
check(bridgeFields.length >= 5, 'bridge state payload is readable', bridgeFields.join(','))
check(unknownFields.length === 0, 'panel only reads fields the bridge sends',
  unknownFields.length ? 'unknown: ' + unknownFields.join(',') : clientFields.join(','))

// 7. The v2-era copy has to be gone, or the panel keeps promising bin/v2.py.
// Code use, not prose: the comment above this file explains the old bug and is
// allowed to name channels; the code reading it is not.
const legacyPatterns = [/v2\.py/, /收工关窗/, /bin\/v2/, /\.channels\b/, /\bstate\.session\b/]
const legacy = legacyPatterns.map(String).filter((pattern) => new RegExp(pattern.slice(1, -1)).test(client))
check(legacy.length === 0, 'no v2-era code left in the panel', legacy.join(',') || 'clean')

const failed = results.filter((r) => !r.ok)
for (const r of results) {
  const detail = r.detail ? '  (' + r.detail + ')' : ''
  console.log((r.ok ? 'PASS  ' : 'FAIL  ') + r.label + detail)
}
console.log('')
console.log('W10 panel: ' + (results.length - failed.length) + '/' + results.length +
  (failed.length ? ' FAIL' : ' PASS'))
process.exit(failed.length ? 1 : 0)
