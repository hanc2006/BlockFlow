#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function defaultHome() {
  if (process.env.BLOCKFLOW_HOME) return path.resolve(process.env.BLOCKFLOW_HOME)
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'BlockFlow')
  }
  if (process.platform === 'win32') {
    return path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'BlockFlow')
  }
  return path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local', 'share'), 'blockflow')
}

function exe(name) {
  return process.platform === 'win32' ? `${name}.exe` : name
}

function commandExists(command) {
  const probe = process.platform === 'win32'
    ? spawnSync('where', [command], { stdio: 'ignore' })
    : spawnSync(`command -v ${command}`, { shell: true, stdio: 'ignore' })
  return probe.status === 0
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} exited with code ${result.status}`)
  }
}

function windowsUvAssetName() {
  if (process.arch === 'x64') return 'uv-x86_64-pc-windows-msvc.zip'
  if (process.arch === 'arm64') return 'uv-aarch64-pc-windows-msvc.zip'
  if (process.arch === 'ia32') return 'uv-i686-pc-windows-msvc.zip'
  throw new Error(`unsupported Windows architecture for uv bootstrap: ${process.arch}`)
}

function findFile(dir, filename) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const candidate = path.join(dir, entry.name)
    if (entry.isFile() && entry.name.toLowerCase() === filename.toLowerCase()) {
      return candidate
    }
    if (entry.isDirectory()) {
      const found = findFile(candidate, filename)
      if (found) return found
    }
  }
  return null
}

function installUvFromWindowsArchive(installDir) {
  const asset = windowsUvAssetName()
  const url = `https://github.com/astral-sh/uv/releases/latest/download/${asset}`
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'blockflow-uv-'))
  const archive = path.join(tmp, asset)
  const extracted = path.join(tmp, 'extract')
  fs.mkdirSync(extracted, { recursive: true })

  try {
    console.error(`[blockflow] downloading uv release archive ${url}`)
    run('curl.exe', ['-L', '--fail', '--retry', '3', '-o', archive, url])
    run('tar.exe', ['-xf', archive, '-C', extracted])

    const uv = findFile(extracted, 'uv.exe')
    if (!uv) throw new Error(`uv.exe not found in ${asset}`)
    fs.copyFileSync(uv, path.join(installDir, 'uv.exe'))

    const uvx = findFile(extracted, 'uvx.exe')
    if (uvx) fs.copyFileSync(uvx, path.join(installDir, 'uvx.exe'))
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
}

function installUv(installDir) {
  fs.mkdirSync(installDir, { recursive: true })
  console.error(`[blockflow] uv not found; installing uv into ${installDir}`)

  if (process.platform === 'win32') {
    try {
      run('powershell.exe', [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-Command',
        `$env:UV_INSTALL_DIR=${JSON.stringify(installDir)}; irm https://astral.sh/uv/install.ps1 | iex`,
      ])
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      console.error(`[blockflow] uv PowerShell installer failed; falling back to direct release archive: ${message}`)
      installUvFromWindowsArchive(installDir)
    }
  } else {
    run('sh', [
      '-c',
      `curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=${JSON.stringify(installDir)} sh`,
    ])
  }
}

function resolveUv(home) {
  if (commandExists('uv')) return 'uv'

  const installDir = path.join(home, 'runtime', 'uv-bin')
  const installed = path.join(installDir, exe('uv'))
  if (!fs.existsSync(installed)) installUv(installDir)
  if (!fs.existsSync(installed)) {
    throw new Error(`uv installer finished but ${installed} does not exist`)
  }
  return installed
}

function main() {
  const home = defaultHome()
  fs.mkdirSync(home, { recursive: true })
  const uv = resolveUv(home)
  const venv = path.join(home, 'runtime', 'venv')
  fs.mkdirSync(path.dirname(venv), { recursive: true })

  const env = {
    ...process.env,
    BLOCKFLOW_HOME: home,
    BLOCKFLOW_PACKAGED: '1',
    BLOCKFLOW_COMFY_GEN_VENV: venv,
    UV_PROJECT_ENVIRONMENT: venv,
  }

  const args = [
    'run',
    '--project',
    packageRoot,
    '--no-dev',
    'python',
    path.join(packageRoot, 'app.py'),
    '--packaged',
    ...process.argv.slice(2),
  ]

  console.error(`[blockflow] starting from ${packageRoot}`)
  const child = spawn(uv, args, {
    cwd: packageRoot,
    env,
    stdio: 'inherit',
  })

  const forward = (signal) => {
    if (!child.killed) child.kill(signal)
  }
  process.on('SIGINT', () => forward('SIGINT'))
  process.on('SIGTERM', () => forward('SIGTERM'))

  child.on('exit', (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal)
      return
    }
    process.exit(code ?? 0)
  })
}

try {
  main()
} catch (err) {
  console.error(`[blockflow] ${err instanceof Error ? err.message : String(err)}`)
  process.exit(1)
}
