/**
 * Nav-icon tests (sgs-ui-eqc.3).
 *
 * - Presets entry renders the new "Presets & Models" label (was icon-only)
 * - LoRAs entry exists, links to /loras, active state highlights on /loras
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockPathname = vi.fn<() => string>()
vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname(),
}))

import { LorasNavIcon } from '../loras-nav-icon'
import { PresetsNavIcon } from '@/components/presets/presets-nav-icon'

beforeEach(() => {
  mockPathname.mockReset()
})

describe('PresetsNavIcon — new text+icon style', () => {
  test('renders the "Presets & Models" label (no longer icon-only)', () => {
    mockPathname.mockReturnValue('/')
    render(<PresetsNavIcon />)
    expect(screen.getByText('Presets & Models')).toBeInTheDocument()
    expect(screen.getByRole('link')).toHaveAttribute('href', '/presets')
  })

  test('active on /presets', () => {
    mockPathname.mockReturnValue('/presets')
    render(<PresetsNavIcon />)
    expect(screen.getByRole('link')).toHaveAttribute('aria-current', 'page')
  })

  test('active on nested /presets/* path', () => {
    mockPathname.mockReturnValue('/presets/some-id')
    render(<PresetsNavIcon />)
    expect(screen.getByRole('link')).toHaveAttribute('aria-current', 'page')
  })

  test('inactive on /loras', () => {
    mockPathname.mockReturnValue('/loras')
    render(<PresetsNavIcon />)
    expect(screen.getByRole('link')).not.toHaveAttribute('aria-current')
  })
})

describe('LorasNavIcon', () => {
  test('renders label and links to /loras', () => {
    mockPathname.mockReturnValue('/')
    render(<LorasNavIcon />)
    expect(screen.getByText('LoRAs')).toBeInTheDocument()
    expect(screen.getByRole('link')).toHaveAttribute('href', '/loras')
  })

  test('active on /loras', () => {
    mockPathname.mockReturnValue('/loras')
    render(<LorasNavIcon />)
    expect(screen.getByRole('link')).toHaveAttribute('aria-current', 'page')
  })

  test('inactive on /presets (does not match)', () => {
    mockPathname.mockReturnValue('/presets')
    render(<LorasNavIcon />)
    expect(screen.getByRole('link')).not.toHaveAttribute('aria-current')
  })
})
