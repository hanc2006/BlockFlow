/**
 * Component tests for <LorasPageBody> (sgs-ui-eqc.2).
 *
 * Mocks the loras client at the module boundary. confirm() is stubbed
 * to auto-accept for bulk-delete + delete-single paths.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/loras/client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/loras/client')>('@/lib/loras/client')
  return {
    ...actual,
    listLoras: vi.fn(),
    syncLoras: vi.fn(),
    deleteLoras: vi.fn(),
    downloadLora: vi.fn(),
    setSource: vi.fn(),
  }
})

import * as client from '@/lib/loras/client'
import { LorasPageBody } from '../loras-page-body'

const _row = (overrides: Partial<client.LoraRow> = {}): client.LoraRow => ({
  filename: 'a.safetensors',
  source: 'civitai',
  source_id: '1',
  base_model: 'Flux.1 D',
  trigger_words: [],
  size_bytes: 100_000_000,
  downloaded_at: '2026-05-20T10:00:00Z',
  updated_at: '2026-05-20T10:00:00Z',
  ...overrides,
})

const _listResponse = (loras: client.LoraRow[]): client.LorasListResponse => ({
  loras, pruned: [], fetched_at: Date.now() / 1000, stale: false,
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  // syncLoras is invoked as the background-sync fallback when stale=true;
  // default to a passthrough so it never throws in tests that don't care.
  vi.mocked(client.syncLoras).mockResolvedValue(_listResponse([]))
})

describe('LorasPageBody — empty / endpoint states', () => {
  test('renders no-endpoint CTA when listLoras throws NoEndpointError', async () => {
    vi.mocked(client.listLoras).mockRejectedValue(new client.NoEndpointError())

    render(<LorasPageBody />)

    expect(await screen.findByText(/No ComfyGen endpoint configured/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Configure endpoint/i })).toHaveAttribute('href', '/settings')
  })

  test('renders empty-state copy when endpoint has zero LoRAs', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([]))

    render(<LorasPageBody />)

    expect(await screen.findByText(/No LoRAs on the endpoint yet/i)).toBeInTheDocument()
  })
})

describe('LorasPageBody — list rendering', () => {
  test('renders one row per LoRA with source + base_model + size', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([
      _row({ filename: 'a.safetensors', source: 'civitai', base_model: 'Flux.1 D', size_bytes: 100_000_000 }),
      _row({ filename: 'b.safetensors', source: 'hf', base_model: 'SDXL', size_bytes: 200_000_000 }),
    ]))

    render(<LorasPageBody />)

    const aRow = (await screen.findByText('a.safetensors')).closest('tr')!
    const bRow = screen.getByText('b.safetensors').closest('tr')!
    expect(within(aRow).getByText('CivitAI')).toBeInTheDocument()
    expect(within(aRow).getByText('Flux.1 D')).toBeInTheDocument()
    expect(within(bRow).getByText('HuggingFace')).toBeInTheDocument()
    expect(within(bRow).getByText('SDXL')).toBeInTheDocument()
  })

  test('shows "Set source" affordance only on unknown-source rows', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([
      _row({ filename: 'known.safetensors', source: 'civitai' }),
      _row({ filename: 'legacy.safetensors', source: 'unknown', source_id: null, base_model: null }),
    ]))

    render(<LorasPageBody />)

    await screen.findByText('known.safetensors')
    const setSourceButtons = screen.getAllByRole('button', { name: /Set source/i })
    expect(setSourceButtons).toHaveLength(1)
  })
})

describe('LorasPageBody — filtering', () => {
  test('search filter narrows visible rows by name substring', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([
      _row({ filename: 'character_v2.safetensors' }),
      _row({ filename: 'style_filmgrain.safetensors' }),
      _row({ filename: 'style_anime.safetensors' }),
    ]))

    render(<LorasPageBody />)
    await screen.findByText('character_v2.safetensors')

    await userEvent.type(screen.getByLabelText(/Search LoRAs/i), 'style')

    await waitFor(() => {
      expect(screen.queryByText('character_v2.safetensors')).not.toBeInTheDocument()
    })
    expect(screen.getByText('style_filmgrain.safetensors')).toBeInTheDocument()
    expect(screen.getByText('style_anime.safetensors')).toBeInTheDocument()
  })

  test('base_model filter combines with search', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([
      _row({ filename: 'flux_a.safetensors', base_model: 'Flux.1 D' }),
      _row({ filename: 'sdxl_a.safetensors', base_model: 'SDXL' }),
      _row({ filename: 'flux_b.safetensors', base_model: 'Flux.1 D' }),
    ]))

    render(<LorasPageBody />)
    await screen.findByText('flux_a.safetensors')

    await userEvent.selectOptions(screen.getByLabelText(/Filter by base model/i), 'SDXL')

    await waitFor(() => {
      expect(screen.queryByText('flux_a.safetensors')).not.toBeInTheDocument()
    })
    expect(screen.getByText('sdxl_a.safetensors')).toBeInTheDocument()
  })
})

describe('LorasPageBody — bulk delete', () => {
  test('confirm dialog shows summed size for selected rows', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([
      _row({ filename: 'a.safetensors', size_bytes: 100 * 1024 * 1024 }),
      _row({ filename: 'b.safetensors', size_bytes: 200 * 1024 * 1024 }),
    ]))
    vi.mocked(client.deleteLoras).mockResolvedValue({
      results: [
        { filename: 'a.safetensors', deleted: true, error: null },
        { filename: 'b.safetensors', deleted: true, error: null },
      ],
    })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<LorasPageBody />)
    await screen.findByText('a.safetensors')

    await userEvent.click(screen.getByRole('checkbox', { name: /Select a\.safetensors/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Select b\.safetensors/i }))
    await userEvent.click(screen.getByRole('button', { name: /Delete 2 selected/i }))

    expect(confirmSpy).toHaveBeenCalledOnce()
    const prompt = confirmSpy.mock.calls[0][0]
    expect(prompt).toMatch(/Delete 2 LoRAs/)
    expect(prompt).toMatch(/300\.0 MB/)
  })

  test('partial failure surfaces the failed row in error banner; succeeded rows leave UI', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([
      _row({ filename: 'a.safetensors', size_bytes: 100 }),
      _row({ filename: 'b.safetensors', size_bytes: 100 }),
    ]))
    vi.mocked(client.deleteLoras).mockResolvedValue({
      results: [
        { filename: 'a.safetensors', deleted: true, error: null },
        { filename: 'b.safetensors', deleted: false, error: 'in use' },
      ],
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<LorasPageBody />)
    await screen.findByText('a.safetensors')

    await userEvent.click(screen.getByRole('checkbox', { name: /Select a\.safetensors/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Select b\.safetensors/i }))
    await userEvent.click(screen.getByRole('button', { name: /Delete 2 selected/i }))

    await waitFor(() => {
      expect(screen.queryByText('a.safetensors')).not.toBeInTheDocument()
    })
    expect(screen.getByText('b.safetensors')).toBeInTheDocument()
    expect(screen.getByText(/1 delete\(s\) failed/i)).toBeInTheDocument()
    expect(screen.getByText(/in use/)).toBeInTheDocument()
  })
})

describe('LorasPageBody — download dialog', () => {
  test('rejects empty/unrecognized input', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([]))

    render(<LorasPageBody />)
    await screen.findByText(/No LoRAs/i)

    await userEvent.click(screen.getByRole('button', { name: /Add LoRA/i }))

    const dialog = await screen.findByRole('dialog', { name: /Download LoRA/i })
    const input = within(dialog).getByLabelText(/LoRA source/i)
    await userEvent.type(input, 'gibberish nope')

    expect(within(dialog).getByText(/Unrecognized/i)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Download/i })).toBeDisabled()
  })

  test('accepts civitai full URL and submits with extracted version_id', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([]))
    vi.mocked(client.downloadLora).mockResolvedValue({ ok: true, filename: 'x.safetensors' })

    render(<LorasPageBody />)
    await screen.findByText(/No LoRAs/i)

    await userEvent.click(screen.getByRole('button', { name: /Add LoRA/i }))
    const dialog = await screen.findByRole('dialog', { name: /Download LoRA/i })

    await userEvent.type(
      within(dialog).getByLabelText(/LoRA source/i),
      'https://civitai.com/models/12345?modelVersionId=67890',
    )

    expect(within(dialog).getByText(/version 67890/)).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: /Download/i }))

    await waitFor(() => {
      expect(client.downloadLora).toHaveBeenCalledWith(expect.objectContaining({
        source: 'civitai', version_id: 67890,
      }))
    })
  })

  test('civitai model-only URL is rejected at submit with a corrective hint', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([]))

    render(<LorasPageBody />)
    await screen.findByText(/No LoRAs/i)

    await userEvent.click(screen.getByRole('button', { name: /Add LoRA/i }))
    const dialog = await screen.findByRole('dialog', { name: /Download LoRA/i })
    await userEvent.type(
      within(dialog).getByLabelText(/LoRA source/i),
      'https://civitai.com/models/12345',
    )

    expect(within(dialog).getByText(/no version ID/i)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Download/i })).toBeDisabled()
  })

  test('huggingface URL submits via url source', async () => {
    vi.mocked(client.listLoras).mockResolvedValue(_listResponse([]))
    vi.mocked(client.downloadLora).mockResolvedValue({ ok: true, filename: 'x.safetensors' })

    render(<LorasPageBody />)
    await screen.findByText(/No LoRAs/i)

    await userEvent.click(screen.getByRole('button', { name: /Add LoRA/i }))
    const dialog = await screen.findByRole('dialog', { name: /Download LoRA/i })
    await userEvent.type(
      within(dialog).getByLabelText(/LoRA source/i),
      'https://huggingface.co/foo/bar/resolve/main/x.safetensors',
    )

    expect(within(dialog).getByText(/Detected:/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /Download/i }))

    await waitFor(() => {
      expect(client.downloadLora).toHaveBeenCalledWith(expect.objectContaining({
        source: 'url',
        url: 'https://huggingface.co/foo/bar/resolve/main/x.safetensors',
      }))
    })
  })
})

describe('LorasPageBody — stale-cache UX', () => {
  test('shows stale banner and triggers background sync exactly once', async () => {
    vi.mocked(client.listLoras).mockResolvedValue({
      loras: [_row()], pruned: [], fetched_at: 0, stale: true,
    })
    let resolveSync: (v: client.LorasListResponse) => void = () => {}
    vi.mocked(client.syncLoras).mockReturnValue(
      new Promise((resolve) => { resolveSync = resolve }),
    )

    render(<LorasPageBody />)
    await screen.findByText('a.safetensors')

    // Banner is visible while the background sync is still in flight.
    expect(await screen.findByText(/Showing cached LoRA list/i)).toBeInTheDocument()
    expect(client.syncLoras).toHaveBeenCalledOnce()

    resolveSync({
      loras: [_row({ filename: 'fresh.safetensors' })],
      pruned: [], fetched_at: Date.now() / 1000, stale: false,
    })
    await screen.findByText('fresh.safetensors')
  })
})
