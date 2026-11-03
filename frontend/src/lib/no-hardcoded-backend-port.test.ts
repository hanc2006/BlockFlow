import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, test } from 'vitest'

// Browser code must reach FastAPI through directBackendUrl() (or a relative
// /api path): a hard-coded <host>:8000 URL breaks when BlockFlow is opened
// remotely (e.g. a RunPod proxy URL) or runs FastAPI on another port.
const REPO = resolve(__dirname, '../../..')
const ROOTS = [join(REPO, 'frontend/src'), join(REPO, 'custom_blocks')]
const ALLOWED = new Set(['frontend/src/lib/backend-url.ts'])
const PATTERN = /window\.location\.hostname\}?:8000|location\.hostname\s*\+\s*['"]:8000/

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'generated' || name.startsWith('.')) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p)
  }
  return out
}

describe('no hard-coded FastAPI port in browser code', () => {
  test('only backend-url.ts builds a <host>:<port> backend URL', () => {
    const offenders = ROOTS.flatMap((root) => walk(root))
      .map((file) => relative(REPO, file))
      .filter((rel) => !ALLOWED.has(rel) && PATTERN.test(readFileSync(join(REPO, rel), 'utf8')))
    expect(offenders).toEqual([])
  })
})
