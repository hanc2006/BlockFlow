/**
 * SetFilter — the Artifacts control that picks which Set to filter by.
 * Sets are user-named collections, so the list is type-to-narrow and shows how
 * many items each holds.
 */
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { SetFilter } from '../set-filter'
import type { MediaSet } from '@/lib/api'

const SETS: MediaSet[] = [
  { id: 'set-1', name: 'Summer drop', created_at: '2026-07-31T10:00:00Z', item_count: 12 },
  { id: 'set-2', name: 'Winter teasers', created_at: '2026-07-30T10:00:00Z', item_count: 3 },
  { id: 'set-3', name: 'Nicole raw', created_at: '2026-07-29T10:00:00Z', item_count: 0 },
]

const onChange = vi.fn()

beforeEach(() => onChange.mockClear())

async function openMenu(user: ReturnType<typeof userEvent.setup>, trigger: RegExp = /^set$/i) {
  await user.click(screen.getByRole('button', { name: trigger }))
}

describe('SetFilter', () => {
  test('trigger reads "Set" when nothing is selected', () => {
    render(<SetFilter sets={SETS} selectedId={null} onChange={onChange} />)
    expect(screen.getByRole('button', { name: /^set$/i })).toBeInTheDocument()
  })

  test('trigger shows the selected set name', () => {
    render(<SetFilter sets={SETS} selectedId="set-2" onChange={onChange} />)
    expect(screen.getByRole('button', { name: /winter teasers/i })).toBeInTheDocument()
  })

  test('falls back to the plain label when the selected set no longer exists', () => {
    render(<SetFilter sets={SETS} selectedId="set-gone" onChange={onChange} />)
    expect(screen.getByRole('button', { name: /^set$/i })).toBeInTheDocument()
  })

  test('lists every set with its item count', async () => {
    const user = userEvent.setup()
    render(<SetFilter sets={SETS} selectedId={null} onChange={onChange} />)
    await openMenu(user)

    expect(screen.getByText('Summer drop')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('Winter teasers')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('Nicole raw')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  test('typing narrows the list by name, case-insensitively', async () => {
    const user = userEvent.setup()
    render(<SetFilter sets={SETS} selectedId={null} onChange={onChange} />)
    await openMenu(user)

    await user.type(screen.getByPlaceholderText(/search sets/i), 'WINTER')
    expect(screen.getByText('Winter teasers')).toBeInTheDocument()
    expect(screen.queryByText('Summer drop')).not.toBeInTheDocument()
    expect(screen.queryByText('Nicole raw')).not.toBeInTheDocument()
  })

  test('a search matching nothing says so', async () => {
    const user = userEvent.setup()
    render(<SetFilter sets={SETS} selectedId={null} onChange={onChange} />)
    await openMenu(user)

    await user.type(screen.getByPlaceholderText(/search sets/i), 'zzz')
    expect(screen.getByText(/no sets match/i)).toBeInTheDocument()
  })

  test('choosing a set reports its id', async () => {
    const user = userEvent.setup()
    render(<SetFilter sets={SETS} selectedId={null} onChange={onChange} />)
    await openMenu(user)

    await user.click(screen.getByText('Summer drop'))
    expect(onChange).toHaveBeenCalledWith('set-1')
  })

  test('choosing "All sets" clears the filter', async () => {
    const user = userEvent.setup()
    render(<SetFilter sets={SETS} selectedId="set-1" onChange={onChange} />)
    await openMenu(user, /summer drop/i)

    await user.click(screen.getByText(/all sets/i))
    expect(onChange).toHaveBeenCalledWith(null)
  })

  test('says so when no sets exist yet', async () => {
    const user = userEvent.setup()
    render(<SetFilter sets={[]} selectedId={null} onChange={onChange} />)
    await openMenu(user)
    expect(screen.getByText(/no sets yet/i)).toBeInTheDocument()
  })
})
