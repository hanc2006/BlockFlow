'use client'

import { ArrowRight, KeyRound, Server, X } from 'lucide-react'

export const WELCOME_STORAGE_KEY = 'blockflow_welcome_seen'

export function hasSeenBlockFlowWelcome(): boolean {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(WELCOME_STORAGE_KEY) === '1'
}

function markBlockFlowWelcomeSeen() {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(WELCOME_STORAGE_KEY, '1')
}

interface Props {
  open: boolean
  onSetUpComfyGen: () => void
  onOpenCredentials: () => void
  onDismiss: () => void
}

export function WelcomeToBlockFlow({
  open,
  onSetUpComfyGen,
  onOpenCredentials,
  onDismiss,
}: Props) {
  if (!open) return null

  const dismiss = () => {
    markBlockFlowWelcomeSeen()
    onDismiss()
  }

  const setUpComfyGen = () => {
    markBlockFlowWelcomeSeen()
    onSetUpComfyGen()
  }

  const openCredentials = () => {
    markBlockFlowWelcomeSeen()
    onOpenCredentials()
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/65 px-4">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="blockflow-welcome-title"
        className="w-full max-w-2xl overflow-hidden rounded-lg border border-border/60 bg-card shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-border/50 p-5">
          <div className="space-y-1">
            <p className="text-xs font-medium uppercase tracking-normal text-muted-foreground">
              First run
            </p>
            <h2 id="blockflow-welcome-title" className="text-xl font-semibold">
              Welcome to BlockFlow
            </h2>
          </div>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Close welcome"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="space-y-5 p-6">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-md border border-border/60 bg-background/60 p-4">
              <div className="mb-3 flex size-9 items-center justify-center rounded-md bg-primary/15 text-primary">
                <Server className="size-4" />
              </div>
              <h3 className="text-sm font-semibold">ComfyGen endpoint</h3>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                ComfyUI-backed generation with RunPod workers. Scale parallel pipelines by raising worker count.
              </p>
            </div>

            <div className="rounded-md border border-border/60 bg-background/60 p-4">
              <div className="mb-3 flex size-9 items-center justify-center rounded-md bg-emerald-500/15 text-emerald-400">
                <ArrowRight className="size-4" />
              </div>
              <h3 className="text-sm font-semibold">Provider blocks</h3>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Use PiAPI, Nano Banana, Seedance, GPT Image, prompt, media, and utility blocks without ComfyGen.
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={setUpComfyGen}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              <Server className="size-4" />
              Set up ComfyGen
            </button>
            <button
              type="button"
              onClick={dismiss}
              className="inline-flex items-center justify-center rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-accent/50"
            >
              Start without ComfyGen
            </button>
            <button
              type="button"
              onClick={openCredentials}
              className="inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent/50 hover:text-foreground"
            >
              <KeyRound className="size-4" />
              Open Credentials
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
