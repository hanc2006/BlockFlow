import { afterEach, describe, expect, test, vi } from 'vitest'
import { directBackendUrl } from './backend-url'

function openedAt(href: string) {
  const url = new URL(href)
  vi.stubGlobal('window', { location: { protocol: url.protocol, hostname: url.hostname } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('directBackendUrl', () => {
  test('local app talks to FastAPI on :8000 directly (bypasses the Next.js proxy limits)', () => {
    openedAt('http://localhost:3000/generate')
    expect(directBackendUrl('/api/blocks/video_loader/upload')).toBe(
      'http://localhost:8000/api/blocks/video_loader/upload',
    )
    openedAt('http://127.0.0.1:3000/generate')
    expect(directBackendUrl('/api/x')).toBe('http://127.0.0.1:8000/api/x')
    openedAt('http://[::1]:3000/generate')
    expect(directBackendUrl('/api/x')).toBe('http://[::1]:8000/api/x')
  })

  test('remote access (e.g. a RunPod proxy URL) stays on the page origin', () => {
    // https://<pod>-3200.proxy.runpod.net:8000 does not exist, and FastAPI only
    // listens on 127.0.0.1 inside the pod: go through the UI's /api proxy.
    openedAt('https://lg9gwugd0jw2lp-3200.proxy.runpod.net/generate')
    expect(directBackendUrl('/api/blocks/video_loader/upload')).toBe('/api/blocks/video_loader/upload')
    openedAt('http://192.168.1.20:3200/generate')
    expect(directBackendUrl('/api/x')).toBe('/api/x')
  })

  test('server-side rendering keeps the relative path', () => {
    vi.stubGlobal('window', undefined)
    expect(directBackendUrl('/api/x')).toBe('/api/x')
  })
})
