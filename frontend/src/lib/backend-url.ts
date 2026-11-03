/**
 * Direct FastAPI URL for endpoints that exceed the Next.js dev proxy's body
 * or socket limits. BlockFlow runs locally through app.py, which launches
 * FastAPI on :8000 and serves CORS-open backend routes.
 *
 * Only when the UI is opened on the same machine (localhost / 127.0.0.1 / ::1)
 * is FastAPI reachable at <host>:8000. Opened remotely (a RunPod proxy URL, a
 * LAN address), <host>:8000 is either not published or FastAPI only listens
 * on 127.0.0.1, so the request stays on the page origin and goes through the
 * UI's /api proxy (next.config.ts, body limit 100 MB) instead.
 */
const LOCAL_HOSTNAMES = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])

export function directBackendUrl(path: string): string {
  if (typeof window === 'undefined' || !window?.location) return path
  const { protocol, hostname } = window.location
  if (!LOCAL_HOSTNAMES.has(hostname)) return path
  return `${protocol}//${hostname}:8000${path}`
}
