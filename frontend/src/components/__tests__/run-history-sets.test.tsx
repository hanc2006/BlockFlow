/**
 * Artifacts × Sets: the `set` URL param drives the runs query, the picker writes
 * it back, and Clear removes it. URL-state routing is the repo convention, so the
 * filter has to survive a reload.
 */
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const replaceMock = vi.fn()
let searchParams = new URLSearchParams()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => '/artifacts',
  useSearchParams: () => searchParams,
}))

const useRunsArgs: unknown[][] = []
vi.mock('@/lib/hooks', () => ({
  useRuns: (...args: unknown[]) => {
    useRunsArgs.push(args)
    return { runs: [], total: 0, isLoading: false, error: null, mutate: vi.fn() }
  },
  useMcpJobs: () => ({ jobs: [], mutate: vi.fn() }),
  useMcpStream: () => {},
  useSets: () => ({
    sets: [
      { id: 'set-1', name: 'Summer drop', created_at: '2026-07-31T10:00:00Z', item_count: 4 },
      { id: 'set-2', name: 'Winter teasers', created_at: '2026-07-30T10:00:00Z', item_count: 1 },
    ],
    mutate: vi.fn(),
  }),
}))

vi.mock('@/components/run-card', () => ({
  RunCard: () => <div>run-card</div>,
  findPrimaryArtifact: () => null,
  looksLikeTrainedLora: () => false,
}))
vi.mock('@/components/dataset-card', () => ({ DatasetCard: () => <div>dataset-card</div> }))
vi.mock('@/components/lora-card', () => ({ LoraCard: () => <div>lora-card</div> }))

import { RunHistory } from '../run-history'

/** useRuns(limit, offset, favorited, mediaKind, promptQuery, hidePartial, source, setId) */
const SET_ID_ARG = 7

beforeEach(() => {
  replaceMock.mockClear()
  useRunsArgs.length = 0
  searchParams = new URLSearchParams()
})

describe('RunHistory set filter', () => {
  test('no set param means no set filter on the query', () => {
    render(<RunHistory />)
    expect(useRunsArgs[0][SET_ID_ARG]).toBeNull()
  })

  test('a set param is forwarded to the runs query', () => {
    searchParams = new URLSearchParams('set=set-2')
    render(<RunHistory />)
    expect(useRunsArgs[0][SET_ID_ARG]).toBe('set-2')
  })

  test('the trigger reflects the set named in the URL', () => {
    searchParams = new URLSearchParams('set=set-2')
    render(<RunHistory />)
    expect(screen.getByRole('button', { name: /winter teasers/i })).toBeInTheDocument()
  })

  test('picking a set writes it to the URL and resets the page', async () => {
    const user = userEvent.setup()
    searchParams = new URLSearchParams('page=3')
    render(<RunHistory />)

    await user.click(screen.getByRole('button', { name: /^set$/i }))
    await user.click(screen.getByText('Summer drop'))

    const url = replaceMock.mock.calls.at(-1)![0] as string
    expect(url).toContain('set=set-1')
    expect(url).not.toContain('page=3')
  })

  test('choosing All sets drops the param', async () => {
    const user = userEvent.setup()
    searchParams = new URLSearchParams('set=set-1')
    render(<RunHistory />)

    await user.click(screen.getByRole('button', { name: /summer drop/i }))
    await user.click(screen.getByText(/all sets/i))

    expect(replaceMock.mock.calls.at(-1)![0]).not.toContain('set=')
  })

  test('a set filter counts as an active filter and Clear removes it', async () => {
    const user = userEvent.setup()
    searchParams = new URLSearchParams('set=set-1')
    render(<RunHistory />)

    const clear = screen.getByRole('button', { name: /^clear$/i })
    await user.click(clear)
    expect(replaceMock.mock.calls.at(-1)![0]).not.toContain('set=')
  })
})
