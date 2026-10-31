// W11 install proof: the copy under <DSH_HOME>/plugins/dsh-chem has to work on its
// own. The unit tests load the checkout; this one loads the install exactly the way
// the host will, from a neutral working directory, and calls the engine through it.
//
// Skipped (exit 0) when nothing is installed: a fresh clone should not fail for
// having no local install yet, but a machine that has one should be able to prove it.
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const home = process.env.DSH_HOME || join(homedir(), '.dsh')
const installed = join(home, 'plugins', 'dsh-chem')
const entry = join(installed, 'lib', 'index.js')

if (!existsSync(entry)) {
  console.log('W11 install: SKIP (nothing installed at ' + installed + ')')
  process.exit(0)
}

const rows = []
const check = (ok, label, detail) => rows.push({ ok: Boolean(ok), label, detail: detail || '' })

process.chdir(homedir())   // neutral cwd: nothing may depend on being in the checkout
const mod = await import(pathToFileURL(entry).href)
const registered = []
const result = mod.apply({ tools: { register: (s) => registered.push(s) }, logger: { info() {}, warn() {} }, effect() {} })

const status = result.runtime || {}
check(registered.length === 15, 'installed copy registers 15 tools', String(registered.length))
check(String(status.entry || '').includes('dsh-chem'), 'engine entry resolves inside the plugin', String(status.entry))
check(!String(status.entry || '').startsWith('D:'), 'engine entry is not the source checkout', String(status.entry))
check(existsSync(join(installed, 'engine', 'bin', 'chem.py')), 'engine/bin/chem.py shipped with the plugin')
check(existsSync(join(installed, 'engine', 'core', 'chem', 'draw.py')), 'engine/core/chem shipped with the plugin')
check(existsSync(join(installed, 'node_modules', '@deepseek-ai', 'dsh-tools')), 'module stub shipped with the plugin')
check(existsSync(join(installed, 'PATCH.md')) && existsSync(join(installed, 'install.json')), 'install records its provenance')

const props = registered.find((s) => s.name === 'chem_props')
const value = await props.execute({ smiles: 'CCO' })
const text = JSON.stringify(value)
check(/46\.069/.test(text), 'installed engine answers a real call', text.slice(0, 60))

// The host resolves bundles out of profiles/desktop/node_modules, not out of the
// plugins folder. A missing entry there breaks the plugin even when the folder is
// perfect - the manager shows 'cannot resolve profile bundle "dsh-chem"'.
const profile = join(home, 'profiles', 'desktop')
if (existsSync(profile)) {
  const link = join(profile, 'node_modules', 'dsh-chem')
  check(existsSync(link), 'profile node_modules has dsh-chem', link)
  let resolvedName = null
  try {
    resolvedName = execFileSync(process.execPath,
      ['--input-type=module', '-e', "const m = await import('dsh-chem'); console.log(m.name)"],
      { cwd: profile, encoding: 'utf8' }).trim()
  } catch (error) {
    resolvedName = 'resolve-failed: ' + String(error.stderr || error).slice(0, 80)
  }
  check(resolvedName === 'dsh-chem', 'profile resolves dsh-chem by package name', resolvedName)
}

result.closeBridge()
let failed = 0
for (const row of rows) {
  if (!row.ok) failed += 1
  console.log((row.ok ? 'PASS  ' : 'FAIL  ') + row.label + (row.detail ? '  [' + row.detail + ']' : ''))
}
console.log('')
console.log('W11 install: ' + (rows.length - failed) + '/' + rows.length + (failed ? ' FAIL' : ' PASS'))
process.exit(failed ? 1 : 0)
