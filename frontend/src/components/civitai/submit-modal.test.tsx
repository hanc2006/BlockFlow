import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type { RunEntry } from '@/lib/types'

vi.mock('@/lib/settings/client', () => ({
  getCredential: vi.fn(),
}))

import { getCredential } from '@/lib/settings/client'
import { SubmitToCivitaiModal } from './submit-modal'

function makeShareableRun(): RunEntry {
  return {
    id: 'run-1',
    name: 'Shareable run',
    status: 'completed',
    duration_ms: 1000,
    flow_snapshot: { blocks: [] },
    block_results: [
      {
        block_index: 0,
        block_type: 'comfy_gen',
        block_label: 'ComfyUI Gen',
        status: 'completed',
        outputs: {
          image: { kind: 'image', value: '/outputs/shareable.png' },
          metadata: { kind: 'metadata', value: { prompt: 'prompt' } },
        },
      },
    ],
    created_at: '2026-05-30T00:00:00Z',
  }
}

beforeEach(() => {
  const store = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: vi.fn((key: string) => store.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => store.set(key, value)),
      removeItem: vi.fn((key: string) => store.delete(key)),
      clear: vi.fn(() => store.clear()),
    },
  })
  vi.mocked(getCredential).mockReset()
})

describe('SubmitToCivitaiModal credentials', () => {
  test('uses the saved Settings CivitAI API key when localStorage is empty', async () => {
    vi.mocked(getCredential).mockResolvedValue({
      name: 'civitai_api_key',
      value: 'civ_saved',
      updated_at: '2026-05-30T00:00:00Z',
    })

    render(
      <SubmitToCivitaiModal
        run={makeShareableRun()}
        open
        onOpenChange={() => {}}
      />,
    )

    await waitFor(() => {
      expect(getCredential).toHaveBeenCalledWith('civitai_api_key')
    })

    expect(await screen.findByDisplayValue('civ_saved')).toBeInTheDocument()
    expect(screen.queryByText(/CIVITAI_API_KEY missing/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue \(1\)/i })).toBeEnabled()
  })
})
