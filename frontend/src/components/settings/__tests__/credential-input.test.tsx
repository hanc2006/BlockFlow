/**
 * Tests for the <CredentialInput> component (sgs-ui-wisp-las.1 Stage 4).
 *
 * The input owns its lifecycle for one credential:
 *   - Loads the stored value on mount (GET via client)
 *   - Tracks an editable draft separately from the stored value
 *   - Save calls the client; on success, draft becomes the new stored value
 *   - Show/hide toggle reveals the value (input.type = password ↔ text)
 *   - If a validator service is supplied, surfaces a Validate button
 *     that calls validateService and shows ok/error
 *
 * Tests mock the BOUNDARY (the client module). The component's state
 * machine + DOM behavior runs for real.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/settings/client', () => ({
  getCredential: vi.fn(),
  setCredential: vi.fn(),
  validateService: vi.fn(),
}))

import * as client from '@/lib/settings/client'
import { CredentialInput } from '../credential-input'

beforeEach(() => {
  vi.mocked(client.getCredential).mockReset()
  vi.mocked(client.setCredential).mockReset()
  vi.mocked(client.validateService).mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CredentialInput — load', () => {
  test('on mount, fetches the stored value via getCredential', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({
      name: 'runpod_api_key',
      value: 'rpa_stored',
      updated_at: '2026-05-21T10:00:00Z',
    })

    render(<CredentialInput name="runpod_api_key" label="RunPod API Key" />)

    await waitFor(() => {
      expect(client.getCredential).toHaveBeenCalledWith('runpod_api_key')
    })
    expect(await screen.findByDisplayValue('rpa_stored')).toBeInTheDocument()
  })

  test('unset credential renders empty value (no crash on null)', async () => {
    vi.mocked(client.getCredential).mockResolvedValue(null)

    render(<CredentialInput name="never_set" label="Never Set" />)

    await waitFor(() => {
      expect(client.getCredential).toHaveBeenCalled()
    })
    const input = screen.getByLabelText('Never Set')
    expect(input).toHaveValue('')
  })
})

describe('CredentialInput — show/hide toggle', () => {
  test('defaults to masked (type="password")', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({ name: 'k', value: 'secret', updated_at: null })
    render(<CredentialInput name="k" label="K" />)
    const input = await screen.findByLabelText('K')
    expect(input).toHaveAttribute('type', 'password')
  })

  test('clicking show reveals; clicking hide masks again', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({ name: 'k', value: 'secret', updated_at: null })
    const user = userEvent.setup()
    render(<CredentialInput name="k" label="K" />)
    const input = await screen.findByLabelText('K')

    await user.click(screen.getByRole('button', { name: /show/i }))
    expect(input).toHaveAttribute('type', 'text')

    await user.click(screen.getByRole('button', { name: /hide/i }))
    expect(input).toHaveAttribute('type', 'password')
  })
})

describe('CredentialInput — save', () => {
  test('Save button is disabled when draft equals stored value (no-op state)', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({ name: 'k', value: 'rpa_x', updated_at: null })
    render(<CredentialInput name="k" label="K" />)

    const saveBtn = await screen.findByRole('button', { name: /save/i })
    await waitFor(() => expect(saveBtn).toBeDisabled())
  })

  test('typing into the input enables Save', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({ name: 'k', value: 'rpa_x', updated_at: null })
    const user = userEvent.setup()
    render(<CredentialInput name="k" label="K" />)
    const input = await screen.findByLabelText('K')
    const saveBtn = screen.getByRole('button', { name: /save/i })
    await waitFor(() => expect(saveBtn).toBeDisabled())

    await user.type(input, '_changed')

    expect(saveBtn).not.toBeDisabled()
  })

  test('Save calls setCredential with the actual draft value', async () => {
    vi.mocked(client.getCredential).mockResolvedValue(null)
    vi.mocked(client.setCredential).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<CredentialInput name="runpod_api_key" label="RunPod" />)
    const input = await screen.findByLabelText('RunPod')

    await user.type(input, 'rpa_new')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(client.setCredential).toHaveBeenCalledWith('runpod_api_key', 'rpa_new')
    })
  })

  test('after successful save, Save button becomes disabled (draft now matches stored)', async () => {
    vi.mocked(client.getCredential).mockResolvedValue(null)
    vi.mocked(client.setCredential).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<CredentialInput name="k" label="K" />)
    const input = await screen.findByLabelText('K')

    await user.type(input, 'new_value')
    await user.click(screen.getByRole('button', { name: /save/i }))

    const saveBtn = screen.getByRole('button', { name: /save/i })
    await waitFor(() => expect(saveBtn).toBeDisabled())
  })

  test('save failure surfaces the error message', async () => {
    vi.mocked(client.getCredential).mockResolvedValue(null)
    vi.mocked(client.setCredential).mockRejectedValue(new Error('forbidden: write disabled'))
    const user = userEvent.setup()
    render(<CredentialInput name="k" label="K" />)
    const input = await screen.findByLabelText('K')

    await user.type(input, 'x')
    await user.click(screen.getByRole('button', { name: /save/i }))

    expect(await screen.findByText(/forbidden: write disabled/i)).toBeInTheDocument()
  })
})

describe('CredentialInput — validate', () => {
  test('with no validator prop, no Validate button renders', async () => {
    vi.mocked(client.getCredential).mockResolvedValue(null)
    render(<CredentialInput name="k" label="K" />)
    await screen.findByLabelText('K')
    expect(screen.queryByRole('button', { name: /validate/i })).not.toBeInTheDocument()
  })

  test('with validator prop, Validate button calls validateService(service)', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({ name: 'rp', value: 'rpa_x', updated_at: null })
    vi.mocked(client.validateService).mockResolvedValue({ ok: true, error: null, info: { gpu_types_visible: 12 } })
    const user = userEvent.setup()
    render(<CredentialInput name="rp" label="RunPod" validator="runpod" />)

    await screen.findByLabelText('RunPod')
    await user.click(screen.getByRole('button', { name: /validate/i }))

    await waitFor(() => {
      expect(client.validateService).toHaveBeenCalledWith('runpod')
    })
  })

  test('successful validation shows a success indicator', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({ name: 'k', value: 'x', updated_at: null })
    vi.mocked(client.validateService).mockResolvedValue({ ok: true, error: null, info: null })
    const user = userEvent.setup()
    render(<CredentialInput name="k" label="K" validator="runpod" />)

    await screen.findByLabelText('K')
    await user.click(screen.getByRole('button', { name: /validate/i }))

    // Use a more specific marker than /valid/i (which collides with the
    // "Validate" button text). The success row has a check + "Valid".
    expect(await screen.findByText('✓ Valid')).toBeInTheDocument()
  })

  test('failed validation shows the error string', async () => {
    vi.mocked(client.getCredential).mockResolvedValue({ name: 'k', value: 'x', updated_at: null })
    vi.mocked(client.validateService).mockResolvedValue({
      ok: false,
      error: 'HTTP 401: invalid api key',
      info: null,
    })
    const user = userEvent.setup()
    render(<CredentialInput name="k" label="K" validator="runpod" />)

    await screen.findByLabelText('K')
    await user.click(screen.getByRole('button', { name: /validate/i }))

    expect(await screen.findByText(/HTTP 401/)).toBeInTheDocument()
  })

  test('validation throw (e.g. credential not configured) surfaces error', async () => {
    vi.mocked(client.getCredential).mockResolvedValue(null)
    vi.mocked(client.validateService).mockRejectedValue(new Error('runpod_api_key not configured'))
    const user = userEvent.setup()
    render(<CredentialInput name="k" label="K" validator="runpod" />)

    await screen.findByLabelText('K')
    await user.click(screen.getByRole('button', { name: /validate/i }))

    expect(await screen.findByText(/not configured/)).toBeInTheDocument()
  })
})
