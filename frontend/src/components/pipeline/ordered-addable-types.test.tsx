import { describe, it, expect } from 'vitest'
import { orderedAddableTypes } from './add-block-button'
import type { NodeTypeDef } from '@/lib/pipeline/registry'

const def = (
  type: string,
  opts: { suggestedUpstream?: string[]; suggestedDownstream?: string[] } = {},
): NodeTypeDef =>
  ({
    type,
    label: type,
    description: '',
    size: 'sm',
    inputs: [],
    outputs: [],
    ...opts,
  }) as unknown as NodeTypeDef

describe('orderedAddableTypes', () => {
  it('ranks types whose suggestedUpstream includes the upstream first', () => {
    const types = [def('a'), def('b', { suggestedUpstream: ['source'] }), def('c')]
    const out = orderedAddableTypes(types, 'source').map((x) => x.def.type)
    expect(out).toEqual(['b', 'a', 'c'])
  })

  it('without upstream, returns original order with suggested=false', () => {
    const types = [def('a'), def('b')]
    const out = orderedAddableTypes(types, undefined)
    expect(out.map((x) => x.def.type)).toEqual(['a', 'b'])
    expect(out.every((x) => x.suggested === false)).toBe(true)
  })

  it('preserves original relative order within suggested and non-suggested groups (stable sort)', () => {
    const types = [
      def('a'),
      def('b', { suggestedUpstream: ['source'] }),
      def('c'),
      def('d', { suggestedUpstream: ['source'] }),
    ]
    const out = orderedAddableTypes(types, 'source').map((x) => x.def.type)
    expect(out).toEqual(['b', 'd', 'a', 'c'])
  })
})
