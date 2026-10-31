// Harvest the plugin's declared tools and the CLI argv each one builds.
//
// The plugin is an ES module that imports the DSH SDK, which is not installed in
// a bare checkout. So we load a *transformed copy*: import lines are replaced by
// stubs, and every tool is executed with sentinel arguments, which lets us read
// the argv it hands to spawnCli without running the CLI at all.
//
// Output: JSON on stdout, one object per tool:
//   {name, params:{key:{type,required}}, calls:[{channel, argv}], problems:[...]}
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const ROOT = path.resolve(process.argv[2] || '.')
const SRC = path.join(ROOT, 'dsh-plugin', 'lib', 'index.js')

const STUBS = [
  'const defineTool = (spec) => spec',
  'let __recorder = []',
  'function __record(channel, argv) {',
  '  __recorder.push({ channel: String(channel), argv: argv.map(String) })',
  '}',
  'export function __setRecorder(bucket) { __recorder = bucket }',
  'async function spawnCli(channel, args) {',
  '  __record(channel, args)',
  '  return { ok: true, data: null }',
  '}',
  'async function spawnV2(args) {',
  '  __record("v2", args)',
  '  return { ok: true, data: null }',
  '}',
  'async function doctor() {',
  '  __record("cd", ["doctor", "cd", "--json"])',
  '  __record("kd", ["doctor", "kd", "--json"])',
  '  return { ok: true, data: { available: [] } }',
  '}',
  // The host half opens a loopback bridge for the sidebar panel; the harness has no
  // sockets, so it records the intent and hands back a closer.
  'const __bridges = []',
  'function startBridge(ctx, run) {',
  '  __bridges.push({ ctx, run })',
  '  return { close: () => {}, port: () => 0 }',
  '}',
  'export function __bridgesStarted() { return __bridges.length }',
  'function describe() {',
  '  return {',
  '    root: process.env.__PROBE_ROOT,',
  '    cli: "cli.py",',
  '    python64: "py64",',
  '    python32: "py32",',
  '    configPath: "cfg",',
  '  }',
  '}',
].join('\n')

function transform(source) {
  const body = source
    .split(/\r?\n/)
    .filter((line) => !/^\s*import\s/.test(line))
    .join('\n')
  return STUBS + '\n' + body
}

const dir = mkdtempSync(path.join(tmpdir(), 'cdt-plugin-'))
try {
  const probeRoot = path.join(dir, 'fake-root')
  mkdirSync(probeRoot, { recursive: true })
  process.env.__PROBE_ROOT = probeRoot

  const target = path.join(dir, 'index.probe.mjs')
  writeFileSync(target, transform(readFileSync(SRC, 'utf8')), 'utf8')
  const mod = await import(pathToFileURL(target).href)

  const bucket = []
  mod.__setRecorder(bucket)
  const specs = []
  const ctx = { tools: { register: (spec) => { specs.push(spec); return spec } } }
  mod.apply(ctx)

  const out = []
  for (const spec of specs) {
    const params = {}
    for (const [key, value] of Object.entries(spec.parameters || {})) {
      params[key] = {
        type: (value && value.type) || 'unknown',
        required: Boolean(value && value.required),
      }
    }
    const problems = []
    const calls = []
    // Three passes, because a tool can branch: required-only, all parameters,
    // then each optional parameter alone. kingdraw_convert is the reason for the
    // third one - it takes a different CLI path depending on which input it got.
    const required = Object.fromEntries(Object.entries(params)
      .filter(([, p]) => p.required)
      .map(([k]) => [k, '__SENT_' + k + '__']))
    const everything = Object.fromEntries(Object.keys(params).map((k) => [k, '__SENT_' + k + '__']))
    const passes = [required, everything]
    for (const key of Object.keys(params)) {
      passes.push({ ...required, [key]: '__SENT_' + key + '__' })
    }
    for (const args of passes) {
      bucket.length = 0
      try {
        await spec.execute(args)
      } catch (exc) {
        problems.push('execute threw: ' + (exc && exc.message ? exc.message : String(exc)))
      }
      for (const call of bucket) {
        const key = call.channel + '|' + call.argv.join('\u0000')
        if (!calls.some((c) => c.channel + '|' + c.argv.join('\u0000') === key)) {
          calls.push(call)
        }
      }
    }
    out.push({ name: spec.name, params, calls, problems })
  }
  process.stdout.write(JSON.stringify(out, null, 2))
} finally {
  rmSync(dir, { recursive: true, force: true })
}
