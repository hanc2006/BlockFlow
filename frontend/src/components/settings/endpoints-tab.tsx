'use client'

import { useEffect, useState } from 'react'

import { listEndpoints, type EndpointRecord } from '@/lib/settings/client'

type EndpointType = 'comfygen' | 'aio_trainer'

const ENDPOINT_DEFINITIONS: { type: EndpointType; label: string; description: string }[] = [
  {
    type: 'comfygen',
    label: 'ComfyGen',
    description: 'Serverless ComfyUI worker for all generation flows.',
  },
  {
    type: 'aio_trainer',
    label: 'AIO LoRA Trainer',
    description: 'Serverless LoRA training worker (multi-GPU capable).',
  },
]

export function EndpointsTab() {
  const [byType, setByType] = useState<Map<EndpointType, EndpointRecord>>(new Map())
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    listEndpoints()
      .then((records) => {
        if (cancelled) return
        const m = new Map<EndpointType, EndpointRecord>()
        for (const r of records) {
          if (r.type === 'comfygen' || r.type === 'aio_trainer') {
            m.set(r.type as EndpointType, r)
          }
        }
        setByType(m)
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="space-y-4">
      {ENDPOINT_DEFINITIONS.map((def) => (
        <EndpointRow
          key={def.type}
          definition={def}
          record={byType.get(def.type) ?? null}
          loaded={loaded}
        />
      ))}
    </div>
  )
}

interface RowProps {
  definition: { type: EndpointType; label: string; description: string }
  record: EndpointRecord | null
  loaded: boolean
}

function EndpointRow({ definition, record, loaded }: RowProps) {
  const configured = record !== null

  return (
    <article className="rounded-lg border border-border/50 bg-card/40 p-5 space-y-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold">{definition.label}</h3>
          <p className="text-xs text-muted-foreground">{definition.description}</p>
        </div>
        <span
          className={`text-xs px-2 py-0.5 rounded ${
            configured ? 'bg-emerald-500/15 text-emerald-400' : 'bg-muted/50 text-muted-foreground'
          }`}
        >
          {loaded ? (configured ? 'Configured' : 'Not configured') : 'Loading…'}
        </span>
      </header>

      {configured && record && (
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <Detail label="Endpoint ID" value={record.endpoint_id} />
          <Detail label="GPU tier" value={record.gpu_tier ?? '—'} />
          <Detail
            label="Volume size"
            value={record.volume_size_gb !== null ? `${record.volume_size_gb} GB` : '—'}
          />
          <Detail
            label="Max workers"
            value={record.max_workers !== null ? String(record.max_workers) : '—'}
          />
          {record.volume_id && <Detail label="Volume ID" value={record.volume_id} />}
          {record.template_id && <Detail label="Template ID" value={record.template_id} />}
          {record.provisioned_at && (
            <Detail
              label="Provisioned"
              value={record.provisioned_at.replace('T', ' ').replace('Z', ' UTC')}
            />
          )}
        </dl>
      )}

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          disabled={configured}
          title={configured ? 'Already configured — tear down to reset' : 'Launch the setup wizard (Stage .2)'}
          className="px-3 py-1.5 text-xs rounded bg-primary text-primary-foreground disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Set up
        </button>
        <button
          type="button"
          disabled={!configured}
          title={
            configured
              ? 'Drain workers, delete endpoint + template + volume (Stage 5.5)'
              : 'Nothing to tear down'
          }
          className="px-3 py-1.5 text-xs rounded border border-destructive/50 text-destructive hover:bg-destructive/10 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Tear down
        </button>
        <button
          type="button"
          disabled={!configured}
          title={
            configured
              ? 'Tear down, then re-launch setup wizard (Stage 5.5 + Stage .2)'
              : 'Nothing to recreate'
          }
          className="px-3 py-1.5 text-xs rounded border border-border hover:bg-accent/50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Recreate
        </button>
      </div>
    </article>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="contents">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono break-all">{value}</dd>
    </div>
  )
}
