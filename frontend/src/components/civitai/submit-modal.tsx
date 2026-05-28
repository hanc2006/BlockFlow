'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApprovalGate, type GateResolvedRow, type GateManualResource } from './approval-gate'
import {
  BLOCKFLOW_DESCRIPTION,
  CIVITAI_TOKEN_KEY,
  RESOLVE_HASHES_ENDPOINT,
  RESOLVE_RESOURCE_ENDPOINT,
  SHARE_ENDPOINT,
} from './constants'
import {
  extractShareableArtifact,
  pickShareMeta,
  hasResolvableHashes,
  type ShareableArtifact,
} from './extract-shareable'
import type { RunEntry } from '@/lib/types'

type ModalStep =
  | { kind: 'picker' }
  | { kind: 'resolving' }
  | { kind: 'gate'; resolved: GateResolvedRow[]; warning?: string }
  | { kind: 'submitting' }
  | { kind: 'done'; postUrl: string; imageCount: number }
  | { kind: 'error'; message: string }

interface SubmitToCivitaiModalProps {
  run: RunEntry
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SubmitToCivitaiModal({ run, open, onOpenChange }: SubmitToCivitaiModalProps) {
  // Memo'd so the picker doesn't churn while the modal is open. Recomputes
  // when the user opens it on a different run.
  const artifact: ShareableArtifact | null = useMemo(
    () => extractShareableArtifact(run),
    [run],
  )

  // Picker state
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [title, setTitle] = useState('')
  const [tagsInput, setTagsInput] = useState('')

  // Token
  const [token, setTokenRaw] = useState(() => {
    if (typeof window === 'undefined') return ''
    return localStorage.getItem(CIVITAI_TOKEN_KEY) ?? ''
  })
  const setToken = useCallback((v: string) => {
    setTokenRaw(v)
    if (typeof window !== 'undefined') localStorage.setItem(CIVITAI_TOKEN_KEY, v)
  }, [])

  // Manual resources (per-share, no persistence)
  const [manualResources, setManualResources] = useState<GateManualResource[]>([])
  const [resourceInput, setResourceInput] = useState('')
  const [resourceError, setResourceError] = useState('')
  const [resourceLoading, setResourceLoading] = useState(false)

  // Gate / submit state
  const [step, setStep] = useState<ModalStep>({ kind: 'picker' })
  const [nsfw, setNsfw] = useState(true)

  // Reset on open. Without this the next opening of the modal would still
  // carry the prior submission's "done" state.
  useEffect(() => {
    if (open) {
      setStep({ kind: 'picker' })
      // Default-select all images in the primary block — the most common
      // case is "publish the whole batch". User can deselect to make a
      // subset.
      if (artifact) {
        const all = new Set<number>(artifact.urls.map((_, i) => i))
        setSelected(all)
      } else {
        setSelected(new Set())
      }
      setManualResources([])
      setResourceInput('')
      setResourceError('')
    }
  }, [open, artifact])

  const toggleIndex = useCallback((i: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }, [])

  const selectAll = useCallback(() => {
    if (!artifact) return
    setSelected(new Set(artifact.urls.map((_, i) => i)))
  }, [artifact])

  const selectNone = useCallback(() => setSelected(new Set()), [])

  const addManualResource = useCallback(async () => {
    if (!resourceInput.trim()) return
    setResourceLoading(true)
    setResourceError('')
    try {
      const res = await fetch(RESOLVE_RESOURCE_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: resourceInput.trim() }),
      })
      const data = await res.json()
      if (!data.ok) {
        setResourceError(data.error || 'Failed to resolve resource')
        return
      }
      const r = data.resource as GateManualResource
      if (manualResources.some((x) => x.modelVersionId === r.modelVersionId)) {
        setResourceError('Already added')
        return
      }
      setManualResources([...manualResources, r])
      setResourceInput('')
    } catch (e) {
      setResourceError(e instanceof Error ? e.message : String(e))
    } finally {
      setResourceLoading(false)
    }
  }, [resourceInput, manualResources])

  const removeManualResource = useCallback(
    (modelVersionId: number) => {
      setManualResources(manualResources.filter((r) => r.modelVersionId !== modelVersionId))
    },
    [manualResources],
  )

  const proceedToGate = useCallback(async () => {
    if (!artifact || selected.size === 0 || !token) return

    setStep({ kind: 'resolving' })

    const selectedIndices = Array.from(selected).sort((a, b) => a - b)
    const shareMeta = pickShareMeta(artifact.metadata, selectedIndices)
    const warning = hasResolvableHashes(shareMeta)
      ? undefined
      : 'No model hashes — post will not link to any CivitAI model.'

    // Build resolve-hashes request from the chosen metadata.
    const modelHashes = (shareMeta.model_hashes || {}) as Record<
      string,
      { sha256?: string; strength?: number }
    >
    const loraHashes = (shareMeta.lora_hashes || {}) as Record<string, string>
    const loras = (shareMeta.loras || []) as Array<{ name: string; strength?: number }>

    const requests: Array<{ filename: string; sha256: string; strength?: number }> = []
    for (const [filename, info] of Object.entries(modelHashes)) {
      if (!info?.sha256) continue
      requests.push({ filename, sha256: info.sha256, strength: info.strength })
    }
    if (requests.length === 0) {
      for (const [filename, sha] of Object.entries(loraHashes)) {
        const matched = loras.find((l) => l.name === filename)
        requests.push({ filename, sha256: sha, strength: matched?.strength ?? 1.0 })
      }
    }

    let resolved: GateResolvedRow[] = []
    if (requests.length > 0) {
      try {
        const res = await fetch(RESOLVE_HASHES_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            hashes: requests.map((r) => ({ filename: r.filename, sha256: r.sha256 })),
          }),
        })
        const data = await res.json()
        if (data.ok) {
          const rows = data.resolved as Array<Omit<GateResolvedRow, 'strength'>>
          resolved = rows.map((row, i) => ({ ...row, strength: requests[i].strength }))
        } else {
          setStep({ kind: 'error', message: data.error || 'Failed to resolve hashes' })
          return
        }
      } catch (e) {
        setStep({ kind: 'error', message: e instanceof Error ? e.message : String(e) })
        return
      }
    }

    setStep({ kind: 'gate', resolved, warning })
  }, [artifact, selected, token])

  const submitToCivitai = useCallback(
    async (gateState: { resolved: GateResolvedRow[] }) => {
      if (!artifact) return
      setStep({ kind: 'submitting' })

      const selectedIndices = Array.from(selected).sort((a, b) => a - b)
      const selectedUrls = selectedIndices.map((i) => artifact.urls[i])
      const shareMeta = pickShareMeta(artifact.metadata, selectedIndices)
      const tagList = tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)

      try {
        const res = await fetch(SHARE_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token,
            media_urls: selectedUrls,
            title:
              title ||
              `${(shareMeta.task_type as string) || 'Generation'} ${new Date().toLocaleDateString()}`,
            description: BLOCKFLOW_DESCRIPTION,
            tags: tagList,
            nsfw,
            publish: true,
            meta: shareMeta,
            manual_resources: manualResources,
          }),
        })
        const data = await res.json()
        if (data.ok) {
          setStep({ kind: 'done', postUrl: data.post_url, imageCount: data.image_count })
        } else {
          setStep({ kind: 'error', message: data.error || 'Share failed' })
        }
        // Reference resolved to avoid React lint flagging the unused param;
        // resolved is currently only used by the gate component above.
        void gateState
      } catch (e) {
        setStep({ kind: 'error', message: e instanceof Error ? e.message : String(e) })
      }
    },
    [artifact, selected, tagsInput, title, token, nsfw, manualResources],
  )

  // ---- Renders ----

  if (!artifact) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Submit to CivitAI</DialogTitle>
            <DialogDescription>This run has no shareable image or video output.</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Submit to CivitAI</DialogTitle>
          <DialogDescription>
            From &ldquo;{artifact.blockLabel}&rdquo; — pick which {artifact.kind}s to publish.
          </DialogDescription>
        </DialogHeader>

        {step.kind === 'picker' && (
          <div className="space-y-3">
            {/* Token */}
            {!token && (
              <p className="text-xs text-yellow-500">
                CIVITAI_API_KEY missing — enter it below or set it in your .env.
              </p>
            )}
            <div className="space-y-1">
              <Label className="text-xs">CivitAI API Key</Label>
              <Input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Your CivitAI API key"
                className="h-8 text-xs"
              />
            </div>

            {/* Selection grid */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs">
                  Select {artifact.kind}s ({selected.size}/{artifact.urls.length})
                </Label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="text-[10px] text-muted-foreground hover:text-foreground"
                    onClick={selectAll}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    className="text-[10px] text-muted-foreground hover:text-foreground"
                    onClick={selectNone}
                  >
                    None
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-4 gap-1.5">
                {artifact.urls.map((url, i) => (
                  <button
                    key={url}
                    type="button"
                    onClick={() => toggleIndex(i)}
                    className={`relative aspect-square rounded overflow-hidden border-2 transition-colors ${
                      selected.has(i)
                        ? 'border-emerald-500'
                        : 'border-border/40 opacity-60 hover:opacity-100'
                    }`}
                  >
                    {artifact.kind === 'video' ? (
                      // No autoplay; just show the URL as a thumbnail
                      // placeholder. Real video preview not worth the perf
                      // cost in a picker grid.
                      <div className="flex h-full w-full items-center justify-center bg-muted text-[9px] text-muted-foreground">
                        video
                      </div>
                    ) : (
                      // eslint-disable-next-line @next/next/no-img-element -- /outputs/ paths aren't statically optimisable
                      <img src={url} alt="" className="h-full w-full object-cover" />
                    )}
                    {selected.has(i) && (
                      <div className="absolute top-1 right-1 size-4 rounded-full bg-emerald-500 flex items-center justify-center">
                        <svg viewBox="0 0 12 12" className="size-2.5 text-white" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M2 6l3 3 5-6" />
                        </svg>
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Title + tags */}
            <div className="space-y-1">
              <Label className="text-xs">Post Title (optional)</Label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Auto-generated if empty"
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Tags (comma-separated)</Label>
              <Input
                value={tagsInput}
                onChange={(e) => setTagsInput(e.target.value)}
                placeholder="tag1, tag2, tag3"
                className="h-8 text-xs"
              />
            </div>

            {/* Manual resources */}
            <div className="space-y-1">
              <Label className="text-xs">Linked resources (optional)</Label>
              <div className="flex gap-1">
                <Input
                  value={resourceInput}
                  onChange={(e) => {
                    setResourceInput(e.target.value)
                    setResourceError('')
                  }}
                  placeholder="civitai.com/models/12345 or version ID"
                  className="h-8 text-xs flex-1"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addManualResource()
                    }
                  }}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 px-2 text-xs"
                  disabled={resourceLoading || !resourceInput.trim()}
                  onClick={addManualResource}
                >
                  {resourceLoading ? '...' : 'Add'}
                </Button>
              </div>
              {resourceError && <p className="text-[10px] text-red-400">{resourceError}</p>}
              {manualResources.length > 0 && (
                <div className="space-y-0.5">
                  {manualResources.map((r) => (
                    <div
                      key={r.modelVersionId}
                      className="flex items-center justify-between rounded border border-border/40 px-1.5 py-0.5"
                    >
                      <span className="text-[10px] flex-1 min-w-0 truncate">
                        {r.name || `v${r.modelVersionId}`}
                        {r.versionName && r.versionName !== r.name && (
                          <span className="text-muted-foreground"> ({r.versionName})</span>
                        )}
                      </span>
                      {r.type && (
                        <span className="text-[9px] text-muted-foreground mx-1.5 shrink-0">
                          {r.type}
                        </span>
                      )}
                      <button
                        type="button"
                        className="text-[10px] text-red-400 hover:text-red-300 shrink-0"
                        onClick={() => removeManualResource(r.modelVersionId)}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={proceedToGate} disabled={selected.size === 0 || !token}>
                Continue ({selected.size})
              </Button>
            </div>
          </div>
        )}

        {step.kind === 'resolving' && (
          <p className="text-xs text-muted-foreground">Resolving CivitAI resources…</p>
        )}

        {step.kind === 'gate' && (
          <ApprovalGate
            resolved={step.resolved}
            manualResources={manualResources}
            mediaCount={selected.size}
            promptPreview={
              (pickShareMeta(artifact.metadata, Array.from(selected)).prompt as string) || ''
            }
            tags={tagsInput
              .split(',')
              .map((t) => t.trim())
              .filter(Boolean)}
            nsfw={nsfw}
            onNsfwChange={setNsfw}
            onApprove={() => submitToCivitai({ resolved: step.resolved })}
            onCancel={() => setStep({ kind: 'picker' })}
            warning={step.warning}
          />
        )}

        {step.kind === 'submitting' && (
          <p className="text-xs text-muted-foreground">Uploading to CivitAI…</p>
        )}

        {step.kind === 'done' && (
          <div className="space-y-3">
            <p className="text-xs text-emerald-400">
              ✓ Posted {step.imageCount} file{step.imageCount === 1 ? '' : 's'} to CivitAI.
            </p>
            <a
              href={step.postUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300 underline break-all"
            >
              {step.postUrl}
            </a>
            <div className="flex justify-end">
              <Button onClick={() => onOpenChange(false)}>Close</Button>
            </div>
          </div>
        )}

        {step.kind === 'error' && (
          <div className="space-y-3">
            <p className="text-xs text-red-400">Failed: {step.message}</p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setStep({ kind: 'picker' })}>
                Back
              </Button>
              <Button onClick={() => onOpenChange(false)}>Close</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
