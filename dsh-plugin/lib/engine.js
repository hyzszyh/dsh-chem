// dsh-chem engine bridge: one tool call = one python subprocess = one JSON.
//
// The venv lives outside the repo (see docs/GOALS.md §2); this module is the
// only place that knows how to find it. Nothing化学 here: all chemistry is in
// bin/chem.py and core/chem/, so a Python fix never needs a plugin reload.

import { spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))

// Two layouts, one file. In the checkout the engine sits two levels up
// (<repo>/bin/chem.py); installed it travels inside the plugin folder
// (<plugin>/engine/bin/chem.py), because the plugin has to keep working after
// the source workspace is gone. DSH_CHEM_ENGINE wins over both for odd set-ups.
function resolveEntry() {
  const candidates = [
    process.env.DSH_CHEM_ENGINE ? join(process.env.DSH_CHEM_ENGINE, 'bin', 'chem.py') : null,
    join(HERE, '..', 'engine', 'bin', 'chem.py'),
    join(HERE, '..', '..', 'bin', 'chem.py'),
  ].filter(Boolean)
  for (const candidate of candidates) if (existsSync(candidate)) return candidate
  return candidates[candidates.length - 1]
}

export const ENTRY = resolveEntry()
export const REPO = dirname(dirname(ENTRY))

function localAppData() {
  return process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local')
}

export function runtimeMeta() {
  const file = join(localAppData(), 'dsh-chem', 'runtime.json')
  if (!existsSync(file)) return null
  try { return JSON.parse(readFileSync(file, 'utf8')) } catch { return null }
}

// Resolution order is deliberate: an explicit override wins, then the venv
// recorded in runtime.json, then the venv's default location. Never fall back
// to a bare `python` from PATH -- that silently uses a different RDKit and
// makes numbers irreproducible, which is the one thing this plugin promises.
export function pythonPath() {
  if (process.env.DSH_CHEM_PYTHON) return process.env.DSH_CHEM_PYTHON
  const meta = runtimeMeta()
  if (meta && meta.venv) {
    const candidate = join(meta.venv, 'Scripts', 'python.exe')
    if (existsSync(candidate)) return candidate
  }
  const fallback = join(localAppData(), 'dsh-chem', 'runtime', 'Scripts', 'python.exe')
  return existsSync(fallback) ? fallback : null
}

export function status() {
  const python = pythonPath()
  const meta = runtimeMeta()
  return {
    ready: Boolean(python),
    python,
    repo: REPO,
    entry: ENTRY,
    entryExists: existsSync(ENTRY),
    packages: meta ? meta.packages : null,
    hint: python ? null : '运行 python bin/setup.py 建运行时（见 docs/GOALS.md §2）',
  }
}

// The last line of stdout is always the JSON object (bin/chem.py contract);
// everything above it is library noise and is kept only for failure reports.
function lastJson(text) {
  const lines = String(text || '').trim().split(/\r?\n/).reverse()
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) continue
    try { return JSON.parse(trimmed) } catch { continue }
  }
  return null
}

export function call(tool, args = {}, options = {}) {
  const timeoutMs = options.timeoutMs || 180000
  const python = pythonPath()
  if (!python) {
    return Promise.resolve({
      ok: false,
      failure: { code: 'no-runtime', message: '找不到 Python 运行时', hint: status().hint },
    })
  }
  return new Promise((resolve) => {
    let child
    try {
      child = spawn(python, [ENTRY, tool, '--json', JSON.stringify(args)], {
        cwd: REPO,
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      })
    } catch (err) {
      resolve({ ok: false, failure: { code: 'spawn-failed', message: String(err && err.message) } })
      return
    }
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => {
      try { child.kill() } catch { /* already gone */ }
      resolve({ ok: false, failure: { code: 'timeout', message: `超过 ${timeoutMs} ms 未返回`, tool } })
    }, timeoutMs)
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('error', (err) => {
      clearTimeout(timer)
      resolve({ ok: false, failure: { code: 'spawn-error', message: String(err && err.message) } })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      const payload = lastJson(stdout)
      if (payload) {
        if (payload.ok === false && !payload.failure) {
          payload.failure = { code: 'tool-failed', message: String(payload.error || 'unknown') }
        }
        resolve(payload)
        return
      }
      resolve({
        ok: false,
        failure: {
          code: 'no-json',
          message: `exit ${code}，输出里没有 JSON`,
          stdoutTail: stdout.slice(-600),
          stderrTail: stderr.slice(-600),
        },
      })
    })
  })
}