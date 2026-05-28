'use client'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

/**
 * Resolved CivitAI resource — what /resolve-hashes returns for one hash, with
 * the strength attached from the per-image metadata. The gate only renders
 * these as static rows; the caller is responsible for batching the
 * /resolve-hashes call and threading strengths through.
 */
export interface GateResolvedRow {
  filename: string
  sha256: string
  resolved: boolean
  modelVersionId?: number
  modelId?: number
  /** Model title (preferred display). */
  name?: string
  /** Version label, secondary display. */
  versionName?: string
  /** CivitAI's resource type ("Checkpoint", "LORA", "Workflows", ...). */
  type?: string
  strength?: number
}

/** Manual resource the user pasted by URL/ID — additive credit. */
export interface GateManualResource {
  modelVersionId: number
  modelId: number | null
  name: string
  versionName?: string
  type?: string
}

export interface ApprovalGateProps {
  /** Resolved hash rows from /resolve-hashes. Render order is preserved. */
  resolved: GateResolvedRow[]
  /** Manual-link rows. Read-only here — input lives outside the gate so
   *  the block (per-flow config) and the modal (per-share) can each own
   *  where the input renders. */
  manualResources: GateManualResource[]
  mediaCount: number
  promptPreview: string
  tags: string[]
  nsfw: boolean
  onNsfwChange: (next: boolean) => void
  onApprove: () => void
  onCancel: () => void
  /** Optional warning banner (e.g. "no model hashes — won't link to any model"). */
  warning?: string
}

export function ApprovalGate({
  resolved,
  manualResources,
  mediaCount,
  promptPreview,
  tags,
  nsfw,
  onNsfwChange,
  onApprove,
  onCancel,
  warning,
}: ApprovalGateProps) {
  return (
    <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2">
      <p className="text-[11px] font-medium text-amber-400">Review before posting</p>

      {warning && (
        <p className="text-[10px] text-yellow-400">⚠ {warning}</p>
      )}

      <div className="space-y-1">
        <p className="text-[10px] text-muted-foreground">
          {mediaCount} media file{mediaCount === 1 ? '' : 's'}
        </p>
        {promptPreview && (
          <p className="text-[10px] text-muted-foreground line-clamp-2">
            &quot;{promptPreview}&quot;
          </p>
        )}
        {tags.length > 0 && (
          <p className="text-[10px] text-muted-foreground">Tags: {tags.join(', ')}</p>
        )}
      </div>

      <div className="space-y-0.5">
        <p className="text-[10px] font-medium text-muted-foreground">Detected resources</p>
        {resolved.length === 0 ? (
          <p className="text-[10px] text-muted-foreground italic">None detected</p>
        ) : (
          resolved.map((r, i) => {
            const baseType = (r.type || '').toLowerCase()
            const isLoraFamily =
              baseType === 'lora' || baseType === 'locon' || baseType === 'lycoris'
            const typeLabel = r.type
              ? isLoraFamily && r.strength !== undefined
                ? `${r.type} @ ${r.strength}`
                : r.type
              : r.strength !== undefined
                ? `lora @ ${r.strength}`
                : '—'
            return (
              <div
                key={`${r.sha256}-${i}`}
                className="flex items-center justify-between rounded border border-border/40 px-1.5 py-0.5"
              >
                <span
                  className={`text-[10px] flex-1 min-w-0 truncate ${
                    r.resolved ? 'text-foreground' : 'text-yellow-500 italic'
                  }`}
                >
                  {r.resolved ? (
                    <>
                      {r.name}
                      {r.versionName && r.versionName !== r.name && (
                        <span className="text-muted-foreground"> ({r.versionName})</span>
                      )}
                    </>
                  ) : (
                    `${r.filename} — Unknown, not on CivitAI`
                  )}
                </span>
                <span className="text-[9px] text-muted-foreground ml-2 shrink-0">
                  {typeLabel}
                </span>
              </div>
            )
          })
        )}
      </div>

      {manualResources.length > 0 && (
        <div className="space-y-0.5">
          <p className="text-[10px] font-medium text-muted-foreground">Manual links</p>
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
                <span className="text-[9px] text-muted-foreground ml-2 shrink-0">{r.type}</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Switch checked={nsfw} onCheckedChange={onNsfwChange} />
        <Label className="text-[11px]">NSFW</Label>
      </div>

      <div className="flex gap-1.5 pt-1">
        <Button type="button" size="sm" className="h-7 flex-1 text-xs" onClick={onApprove}>
          Approve &amp; Publish
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 flex-1 text-xs"
          onClick={onCancel}
        >
          Cancel
        </Button>
      </div>
    </div>
  )
}
