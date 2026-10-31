// dsh-chem — 面板与宿主之间的回环桥。
//
// 面板跑在浏览器里：它不能 spawn Python，也不该假装能。宿主半开一条只绑
// 127.0.0.1 的 HTTP 桥，面板 POST 到这里，宿主用和工具调用完全相同的
// engine.call() 去跑 bin/chem.py —— 面板里看到的结果，就是 agent 拿到的那份。
//
// 不鉴权是刻意的：能连上这个回环端口的进程，本来就能直接调用 CLI。
// 桥只转发 15 个已注册工具名，不提供 shell，不浏览文件系统。

import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { basename, join } from 'node:path'

import { call, status } from './engine.js'

export const PLUGIN_ID = 'dsh-chem'
const PORTS = [37373, 37374, 37375, 37376]

// The whitelist is the tool table, not a second invention: if a name is not a
// registered chem_* tool, the bridge has no business forwarding it.
export const TOOLS = new Set([
  'chem_parse', 'chem_clean', 'chem_draw', 'chem_props', 'chem_calc',
  'chem_compare', 'chem_table', 'chem_db', 'chem_ml', 'chem_enum',
  'chem_retro', 'chem_spectra', 'chem_exam', 'chem_office', 'chem_vendor',
])

function artifactRoot() {
  const base = process.env.LOCALAPPDATA || ''
  if (!base) return null
  return join(base, 'dsh-chem', 'artifacts')
}

function newestPng(folder) {
  if (!folder || !existsSync(folder)) return null
  let best = null
  let bestTime = 0
  const walk = (dir, depth) => {
    if (depth > 3) return
    let entries = []
    try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const entry of entries) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) { walk(full, depth + 1); continue }
      if (!/\.(png|jpe?g)$/i.test(entry.name)) continue
      let stat = null
      try { stat = statSync(full) } catch { continue }
      if (stat.mtimeMs > bestTime) { bestTime = stat.mtimeMs; best = full }
    }
  }
  walk(folder, 0)
  return best
}

function readBody(request) {
  return new Promise((resolve) => {
    let raw = ''
    request.on('data', (chunk) => {
      raw += chunk
      if (raw.length > 2_000_000) request.destroy()
    })
    request.on('end', () => resolve(raw))
    request.on('error', () => resolve(raw))
  })
}

export function startBridge(ctx) {
  let clientMountedAt = 0
  let clientReport = null

  const answer = (response, statusCode, body, type = 'application/json') => {
    response.writeHead(statusCode, {
      'content-type': type,
      'access-control-allow-origin': '*',
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'GET,POST,OPTIONS',
      'cache-control': 'no-store',
    })
    response.end(body)
  }

  const server = createServer(async (request, response) => {
    if (request.method === 'OPTIONS') { answer(response, 204, ''); return }
    const url = new URL(request.url || '/', 'http://127.0.0.1')

    if (url.pathname === '/health') {
      answer(response, 200, JSON.stringify({ ok: true, plugin: PLUGIN_ID }))
      return
    }
    if (url.pathname === '/state') {
      const info = status()
      const latest = newestPng(artifactRoot())
      answer(response, 200, JSON.stringify({
        plugin: PLUGIN_ID,
        runtime: { ok: info.ready, python: info.python, packages: info.packages },
        tools: Array.from(TOOLS),
        artifacts: latest ? 1 : 0,
        latest: latest ? basename(latest) : null,
        client_mounted: clientMountedAt ? new Date(clientMountedAt).toISOString() : null,
        client_report: clientReport,
      }))
      return
    }
    if (url.pathname === '/client-mounted') {
      clientMountedAt = Date.now()
      const steps = url.searchParams.get('steps')
      if (steps) {
        clientReport = { at: new Date(clientMountedAt).toISOString(), steps: steps.slice(0, 4000) }
        try {
          const dir = join(process.env.LOCALAPPDATA || '', 'dsh-chem', 'logs')
          mkdirSync(dir, { recursive: true })
          appendFileSync(join(dir, 'panel.log'),
                         new Date(clientMountedAt).toISOString() + ' ' + steps + '\n')
        } catch (error) { /* 日志写不进不该影响面板 */ }
      }
      answer(response, 200, JSON.stringify({ ok: true, at: clientMountedAt }))
      return
    }
    if (url.pathname === '/latest.png' || url.pathname === '/artifact') {
      let target = null
      if (url.pathname === '/latest.png') {
        target = newestPng(artifactRoot())
      } else {
        const root = artifactRoot()
        const task = String(url.searchParams.get('task') || '')
        const name = String(url.searchParams.get('name') || '')
        if (!root || task.includes('..') || name.includes('..')
            || !/^[\w.\-]+$/.test(task) || !/^[\w.\-]+\.(png|jpe?g)$/i.test(name)) {
          answer(response, 400, 'bad artifact name', 'text/plain')
          return
        }
        target = join(root, task, name)
      }
      if (!target) { answer(response, 404, 'no artifact yet', 'text/plain'); return }
      try {
        answer(response, 200, readFileSync(target), 'image/png')
      } catch (error) {
        answer(response, 404, 'no such artifact', 'text/plain')
      }
      return
    }
    if (url.pathname === '/artifacts') {
      const root = artifactRoot()
      const limit = Math.min(40, Number(url.searchParams.get('limit')) || 12)
      const rows = []
      if (root && existsSync(root)) {
        for (const task of readdirSync(root)) {
          let stat
          try { stat = statSync(join(root, task)) } catch (error) { continue }
          if (!stat.isDirectory()) continue
          for (const name of readdirSync(join(root, task))) {
            if (!/\.(png|jpe?g|docx|pptx|xlsx|pdf|cdxml|sdf|mol|xyz)$/i.test(name)) continue
            const full = join(root, task, name)
            let info
            try { info = statSync(full) } catch (error) { continue }
            rows.push({ task, name, path: full, bytes: info.size, mtime: info.mtimeMs })
          }
        }
      }
      rows.sort((a, b) => b.mtime - a.mtime)
      answer(response, 200, JSON.stringify({ ok: true, total: rows.length, items: rows.slice(0, limit) }))
      return
    }
    if (url.pathname === '/call' && request.method === 'POST') {
      const raw = await readBody(request)
      let payload = {}
      try { payload = JSON.parse(raw) } catch { payload = {} }
      const tool = String(payload.tool || payload.verb || '')
      const args = (payload.args && typeof payload.args === 'object') ? payload.args : {}
      const name = tool.startsWith('chem_') ? tool : 'chem_' + tool
      if (!TOOLS.has(name)) {
        answer(response, 400, JSON.stringify({ ok: false, failure: {
          code: 'E01', message: '面板只能调用已注册的 chem_* 工具', tool,
          known: Array.from(TOOLS) } }))
        return
      }
      const started = Date.now()
      // bin/chem.py takes the bare subcommand ("props"), while the tool surface is
      // "chem_props"; forwarding the prefixed name returned "unknown subcommand".
      const verb = name.replace(/^chem_/, '')
      const result = await call(verb, args, { timeoutMs: Number(payload.timeoutMs) || 180000 })
      answer(response, 200, JSON.stringify({ ...result, tool: name, elapsed_ms: Date.now() - started }))
      return
    }
    answer(response, 404, JSON.stringify({ ok: false, message: 'not found' }))
  })

  let attempt = 0
  const listen = () => {
    if (attempt >= PORTS.length) {
      ctx?.logger?.warn?.('[dsh-chem] the panel bridge could not bind any port')
      return
    }
    const port = PORTS[attempt]
    server.once('error', () => { attempt += 1; listen() })
    server.listen(port, '127.0.0.1', () => {
      ctx?.logger?.info?.('[dsh-chem] panel bridge on ' + port)
    })
  }
  listen()
  return { close: () => server.close(), port: () => PORTS[attempt] }
}
