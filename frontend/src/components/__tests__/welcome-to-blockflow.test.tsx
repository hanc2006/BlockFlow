import { beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  WELCOME_STORAGE_KEY,
  WelcomeToBlockFlow,
  hasSeenBlockFlowWelcome,
} from '../welcome-to-blockflow'

function installLocalStorageStub() {
  const store = new Map<string, string>()
  const storage = {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key)
    }),
    clear: vi.fn(() => {
      store.clear()
    }),
  }
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: storage,
  })
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: storage,
  })
}

describe('WelcomeToBlockFlow', () => {
  beforeEach(() => {
    installLocalStorageStub()
    localStorage.clear()
  })

  test('renders the first-run choices for ComfyGen and non-ComfyGen blocks', () => {
    render(
      <WelcomeToBlockFlow
        open
        onSetUpComfyGen={() => {}}
        onOpenCredentials={() => {}}
        onDismiss={() => {}}
      />,
    )

    expect(screen.getByRole('heading', { name: /welcome to blockflow/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /set up comfygen/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start without comfygen/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open credentials/i })).toBeInTheDocument()
    expect(screen.getByText(/provider blocks/i)).toBeInTheDocument()
  })

  test('does not render when closed', () => {
    render(
      <WelcomeToBlockFlow
        open={false}
        onSetUpComfyGen={() => {}}
        onOpenCredentials={() => {}}
        onDismiss={() => {}}
      />,
    )

    expect(screen.queryByRole('heading', { name: /welcome to blockflow/i })).not.toBeInTheDocument()
  })

  test('Set up ComfyGen marks the welcome seen and opens setup', async () => {
    const user = userEvent.setup()
    const onSetUpComfyGen = vi.fn()

    render(
      <WelcomeToBlockFlow
        open
        onSetUpComfyGen={onSetUpComfyGen}
        onOpenCredentials={() => {}}
        onDismiss={() => {}}
      />,
    )

    await user.click(screen.getByRole('button', { name: /set up comfygen/i }))

    expect(onSetUpComfyGen).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(WELCOME_STORAGE_KEY)).toBe('1')
    expect(hasSeenBlockFlowWelcome()).toBe(true)
  })

  test('Start without ComfyGen marks the welcome seen and dismisses it', async () => {
    const user = userEvent.setup()
    const onDismiss = vi.fn()

    render(
      <WelcomeToBlockFlow
        open
        onSetUpComfyGen={() => {}}
        onOpenCredentials={() => {}}
        onDismiss={onDismiss}
      />,
    )

    await user.click(screen.getByRole('button', { name: /start without comfygen/i }))

    expect(onDismiss).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(WELCOME_STORAGE_KEY)).toBe('1')
  })

  test('Open Credentials marks the welcome seen and opens credentials settings', async () => {
    const user = userEvent.setup()
    const onOpenCredentials = vi.fn()

    render(
      <WelcomeToBlockFlow
        open
        onSetUpComfyGen={() => {}}
        onOpenCredentials={onOpenCredentials}
        onDismiss={() => {}}
      />,
    )

    await user.click(screen.getByRole('button', { name: /open credentials/i }))

    expect(onOpenCredentials).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(WELCOME_STORAGE_KEY)).toBe('1')
  })
})
