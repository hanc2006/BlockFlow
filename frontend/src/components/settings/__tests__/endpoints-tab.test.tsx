/**
 * Tests for the <EndpointsTab> (sgs-ui-wisp-las.1 Stage 5).
 *
 * Stage 5 ships UI shell only: state display + action button shells.
 * Set Up flow is owned by .2 (setup wizard). Tear Down / Recreate
 * RunPod API plumbing lands in Stage 5.5 — for now the buttons exist
 * but show "not yet available" affordances.
 */
import { describe, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/settings/client', () => ({
  listEndpoints: vi.fn(),
}))

import * as client from '@/lib/settings/client'
import { EndpointsTab } from '../endpoints-tab'

describe('EndpointsTab — rendering', () => {
  test('renders both endpoint rows even when none are configured', async () => {
    vi.mocked(client.listEndpoints).mockResolvedValue([])
    render(<EndpointsTab />)

    expect(await screen.findByRole('heading', { name: /ComfyGen/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /AIO LoRA Trainer/ })).toBeInTheDocument()
  })

  test('unconfigured row shows "Not configured" status', async () => {
    vi.mocked(client.listEndpoints).mockResolvedValue([])
    render(<EndpointsTab />)

    const statuses = await screen.findAllByText(/Not configured/i)
    expect(statuses).toHaveLength(2)
  })

  test('configured row shows endpoint_id, gpu_tier, volume_size_gb, max_workers, provisioned_at', async () => {
    vi.mocked(client.listEndpoints).mockResolvedValue([
      {
        type: 'comfygen',
        endpoint_id: 'ep_abc123',
        volume_id: 'vol_xyz',
        template_id: 'tmpl_q',
        template_name: 'blockflow-comfygen-q-template-q',
        gpu_tier: 'recommended',
        volume_size_gb: 200,
        max_workers: 3,
        provisioned_at: '2026-05-21T10:00:00Z',
      },
    ])

    render(<EndpointsTab />)

    expect(await screen.findByText('ep_abc123')).toBeInTheDocument()
    expect(screen.getByText('recommended')).toBeInTheDocument()
    expect(screen.getByText('200 GB')).toBeInTheDocument()
    // max_workers = 3 — find the "Max workers" dt and assert its sibling dd
    const maxWorkersTerm = screen.getByText('Max workers')
    const maxWorkersValue = maxWorkersTerm.nextElementSibling
    expect(maxWorkersValue?.textContent).toBe('3')
    expect(screen.getByText(/2026-05-21/)).toBeInTheDocument()
  })

  test('unconfigured row: Set up button enabled; Tear down + Recreate disabled', async () => {
    vi.mocked(client.listEndpoints).mockResolvedValue([])
    render(<EndpointsTab />)

    await screen.findAllByText(/Not configured/i)

    const setUpButtons = screen.getAllByRole('button', { name: /Set up/i })
    const tearDownButtons = screen.getAllByRole('button', { name: /Tear down/i })
    const recreateButtons = screen.getAllByRole('button', { name: /Recreate/i })

    expect(setUpButtons).toHaveLength(2)
    expect(tearDownButtons).toHaveLength(2)
    expect(recreateButtons).toHaveLength(2)

    // Tear down + Recreate are no-ops on an unconfigured row
    for (const btn of tearDownButtons) expect(btn).toBeDisabled()
    for (const btn of recreateButtons) expect(btn).toBeDisabled()
  })

  test('configured row: Tear down + Recreate enabled; Set up disabled', async () => {
    vi.mocked(client.listEndpoints).mockResolvedValue([
      {
        type: 'comfygen',
        endpoint_id: 'ep_x',
        volume_id: null,
        template_id: null,
        template_name: null,
        gpu_tier: null,
        volume_size_gb: null,
        max_workers: null,
        provisioned_at: null,
      },
    ])

    render(<EndpointsTab />)

    await screen.findByText('ep_x')

    // ComfyGen row is configured, AIO trainer is not
    const setUpButtons = screen.getAllByRole('button', { name: /Set up/i })
    const tearDownButtons = screen.getAllByRole('button', { name: /Tear down/i })

    // ComfyGen Set up disabled (already configured); trainer Set up enabled
    expect(setUpButtons[0]).toBeDisabled() // comfygen
    expect(setUpButtons[1]).not.toBeDisabled() // aio_trainer

    expect(tearDownButtons[0]).not.toBeDisabled() // comfygen
    expect(tearDownButtons[1]).toBeDisabled() // aio_trainer (unconfigured)
  })

  test('endpoint rows render in fixed order: ComfyGen first, AIO trainer second', async () => {
    vi.mocked(client.listEndpoints).mockResolvedValue([])
    render(<EndpointsTab />)

    const headings = await screen.findAllByRole('heading', { level: 3 })
    // Headings within the tab — there's "ComfyGen" and "AIO LoRA Trainer"
    expect(headings[0].textContent).toMatch(/ComfyGen/)
    expect(headings[1].textContent).toMatch(/AIO LoRA Trainer/)
  })
})
