import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdir, rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const backendRoot = resolve(frontendRoot, '../backend')
const testDataDir = resolve(backendRoot, '.playwright-data', String(Date.now()))
const python = process.env.AIBI_TEST_PYTHON || 'D:/PY/python.exe'
const children = []

function start(command, args, cwd, env = {}) {
  const child = spawn(command, args, {
    cwd, env: { ...process.env, ...env }, windowsHide: true, stdio: 'inherit',
  })
  children.push(child)
  return child
}

async function waitFor(url) {
  for (let attempt = 0; attempt < 150; attempt += 1) {
    try {
      if ((await fetch(url)).ok) return
    } catch { /* server is still starting */ }
    await new Promise(resolveWait => setTimeout(resolveWait, 200))
  }
  throw new Error(`测试服务未就绪：${url}`)
}

async function stop(child) {
  if (child.exitCode !== null) return
  child.kill()
  await Promise.race([once(child, 'exit'), new Promise(resolveWait => setTimeout(resolveWait, 3000))])
}

await mkdir(testDataDir, { recursive: true })
let exitCode = 1
try {
  start(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8011'], backendRoot, {
    AIBI_DATA_DIR: testDataDir,
  })
  start(process.execPath, ['./node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5176'], frontendRoot, {
    VITE_API_TARGET: 'http://127.0.0.1:8011',
  })
  await Promise.all([
    waitFor('http://127.0.0.1:8011/api/v1/health'),
    waitFor('http://127.0.0.1:5176'),
  ])
  const runner = start(
    process.execPath, ['./node_modules/@playwright/test/cli.js', 'test'], frontendRoot,
  )
  ;[exitCode] = await once(runner, 'exit')
} finally {
  await Promise.all(children.slice(0, 2).map(stop))
  await rm(testDataDir, { recursive: true, force: true })
}
process.exitCode = exitCode ?? 1
