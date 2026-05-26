import { describe, it, expect } from 'vitest'
import { dropHidden, hiddenSetFrom } from './hide-nodes'

describe('dropHidden', () => {
  it('filters out items whose node_id is in the hidden set', () => {
    const arr = [{ node_id: '1' }, { node_id: '2' }, { node_id: '3' }]
    expect(dropHidden(arr, new Set(['2']))).toEqual([{ node_id: '1' }, { node_id: '3' }])
  })

  it('returns the input unchanged when the hidden set is empty', () => {
    const arr = [{ node_id: '1' }, { node_id: '2' }]
    expect(dropHidden(arr, new Set())).toEqual(arr)
  })

  it('treats unknown ids in the hidden set as no-ops (silent ignore)', () => {
    const arr = [{ node_id: '1' }, { node_id: '2' }]
    expect(dropHidden(arr, new Set(['999']))).toEqual(arr)
  })

  it('coerces numeric node_id values to strings before comparing', () => {
    // ComfyUI workflow JSON keys are stringly-typed but some detection
    // arrays carry numerics through. Coercion matters: Set.has(2) ≠ Set.has("2").
    const arr = [{ node_id: 2 as unknown as string }, { node_id: '3' }]
    expect(dropHidden(arr, new Set(['2']))).toEqual([{ node_id: '3' }])
  })

  it('preserves extra properties on each item (only filters, never mutates)', () => {
    const arr = [
      { node_id: '1', extra: 'a' },
      { node_id: '2', extra: 'b' },
    ]
    expect(dropHidden(arr, new Set(['1']))).toEqual([{ node_id: '2', extra: 'b' }])
  })
})

describe('hiddenSetFrom', () => {
  it('returns an empty set when input is undefined', () => {
    expect(hiddenSetFrom(undefined).size).toBe(0)
  })

  it('returns an empty set when input is an empty array', () => {
    expect(hiddenSetFrom([]).size).toBe(0)
  })

  it('builds a set of stringified ids', () => {
    const s = hiddenSetFrom(['77', '123'])
    expect(s.has('77')).toBe(true)
    expect(s.has('123')).toBe(true)
    expect(s.size).toBe(2)
  })
})
