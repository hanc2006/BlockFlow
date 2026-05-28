/**
 * Tests for the pure helpers that pull shareable media + per-image metadata
 * out of saved runs.
 *
 * The artifacts-page "Submit to CivitAI" flow depends on this layer being
 * correct: if metadata gets cross-attributed across images (e.g. picking
 * image 3 but submitting image 1's model_hashes), the resulting CivitAI
 * post will misattribute resources. So we cover:
 *   - single-image batch (metadata as one object, not array)
 *   - multi-image batch (metadata as array, parallel indices)
 *   - subset selection by index
 *   - empty / missing metadata fallback
 *   - hash-present detection
 *   - last-block-wins selection (video > image)
 */
import { describe, expect, it } from 'vitest'
import type { RunEntry } from '@/lib/types'
import {
  extractShareableArtifact,
  pickShareMeta,
  hasResolvableHashes,
  type PerImageMeta,
} from './extract-shareable'

function makeRun(blocks: RunEntry['block_results']): RunEntry {
  return {
    id: 'run-1',
    name: 'Test',
    status: 'completed',
    duration_ms: 1000,
    flow_snapshot: {},
    block_results: blocks,
    created_at: new Date().toISOString(),
  }
}

describe('extractShareableArtifact', () => {
  it('returns null when no block emits image or video', () => {
    const run = makeRun([
      {
        block_index: 0,
        block_type: 'prompt_writer',
        block_label: 'Prompt Writer',
        status: 'completed',
        outputs: { prompt: { kind: 'prompt', value: 'a cat' } },
      },
    ])
    expect(extractShareableArtifact(run)).toBeNull()
  })

  it('returns urls + per-index metadata for a multi-image batch', () => {
    const meta: PerImageMeta[] = [
      { prompt: 'p0', seed: 1, model_hashes: { 'a.safetensors': { sha256: 'aa' } } },
      { prompt: 'p1', seed: 2, model_hashes: { 'a.safetensors': { sha256: 'aa' } } },
      { prompt: 'p2', seed: 3, model_hashes: { 'a.safetensors': { sha256: 'aa' } } },
    ]
    const run = makeRun([
      {
        block_index: 0,
        block_type: 'comfy_gen',
        block_label: 'ComfyUI Gen',
        status: 'completed',
        outputs: {
          image: { kind: 'image', value: ['/outputs/a.png', '/outputs/b.png', '/outputs/c.png'] },
          metadata: { kind: 'metadata', value: meta },
        },
      },
    ])
    const out = extractShareableArtifact(run)
    expect(out?.kind).toBe('image')
    expect(out?.urls).toEqual(['/outputs/a.png', '/outputs/b.png', '/outputs/c.png'])
    expect(out?.metadata).toEqual(meta)
    expect(out?.blockLabel).toBe('ComfyUI Gen')
  })

  it('normalises single-image batch (string url, object metadata) into arrays', () => {
    // comfy_gen emits scalars for batch=1; we still want arrays downstream
    // so the picker / metadata indexing logic is uniform.
    const run = makeRun([
      {
        block_index: 0,
        block_type: 'comfy_gen',
        block_label: 'ComfyUI Gen',
        status: 'completed',
        outputs: {
          image: { kind: 'image', value: '/outputs/only.png' },
          metadata: { kind: 'metadata', value: { prompt: 'p', seed: 42 } },
        },
      },
    ])
    const out = extractShareableArtifact(run)
    expect(out?.urls).toEqual(['/outputs/only.png'])
    expect(out?.metadata).toHaveLength(1)
    expect(out?.metadata[0]?.seed).toBe(42)
  })

  it('pads metadata with empty objects when out of sync (older runs)', () => {
    // Older runs may not have saved metadata; we still want to render
    // the picker and submit, just with no model link.
    const run = makeRun([
      {
        block_index: 0,
        block_type: 'comfy_gen',
        block_label: 'Gen',
        status: 'completed',
        outputs: {
          image: { kind: 'image', value: ['/outputs/a.png', '/outputs/b.png'] },
          // metadata missing entirely
        },
      },
    ])
    const out = extractShareableArtifact(run)
    expect(out?.urls).toHaveLength(2)
    expect(out?.metadata).toEqual([{}, {}])
  })

  it('video supersedes image when both exist in different blocks', () => {
    // Same precedence the live pipeline uses. A video extract block after
    // an image gen means the user's "primary artifact" is the video.
    const run = makeRun([
      {
        block_index: 0,
        block_type: 'comfy_gen',
        block_label: 'Gen',
        status: 'completed',
        outputs: { image: { kind: 'image', value: '/outputs/img.png' } },
      },
      {
        block_index: 1,
        block_type: 'video_stitcher',
        block_label: 'Video',
        status: 'completed',
        outputs: { video: { kind: 'video', value: '/outputs/vid.mp4' } },
      },
    ])
    const out = extractShareableArtifact(run)
    expect(out?.kind).toBe('video')
    expect(out?.urls).toEqual(['/outputs/vid.mp4'])
  })

  it('picks the latest block when multiple emit the same kind', () => {
    // An upscale after a gen → the upscaled images are the user's
    // "primary" share, not the raw gens.
    const run = makeRun([
      {
        block_index: 0,
        block_type: 'comfy_gen',
        block_label: 'Gen',
        status: 'completed',
        outputs: { image: { kind: 'image', value: '/outputs/raw.png' } },
      },
      {
        block_index: 1,
        block_type: 'image_upscale',
        block_label: 'Upscale',
        status: 'completed',
        outputs: { image: { kind: 'image', value: '/outputs/up.png' } },
      },
    ])
    const out = extractShareableArtifact(run)
    expect(out?.urls).toEqual(['/outputs/up.png'])
    expect(out?.blockLabel).toBe('Upscale')
  })

  it('skips a block whose image output is empty/missing', () => {
    const run = makeRun([
      {
        block_index: 0,
        block_type: 'comfy_gen',
        block_label: 'Gen A',
        status: 'completed',
        outputs: { image: { kind: 'image', value: '/outputs/a.png' } },
      },
      {
        block_index: 1,
        block_type: 'comfy_gen',
        block_label: 'Gen B',
        status: 'completed',
        outputs: { image: { kind: 'image', value: [] } },
      },
    ])
    const out = extractShareableArtifact(run)
    expect(out?.blockLabel).toBe('Gen A')
  })
})

describe('pickShareMeta', () => {
  const meta: PerImageMeta[] = [
    {},
    { prompt: 'second', model_hashes: { 'b.safetensors': { sha256: 'bb' } } },
    { prompt: 'third' },
  ]

  it('returns the first SELECTED entry that has fields', () => {
    // selectedIndices=[1] → meta[1]; the gate uses this to populate the
    // shared meta sent to /share.
    expect(pickShareMeta(meta, [1])).toEqual(meta[1])
  })

  it('falls back through later indices when the first is empty', () => {
    // selectedIndices=[0,2] → first non-empty is meta[2]
    expect(pickShareMeta(meta, [0, 2])).toEqual(meta[2])
  })

  it('returns {} when nothing is selected', () => {
    expect(pickShareMeta(meta, [])).toEqual({})
  })

  it('returns {} when every selected entry is empty', () => {
    expect(pickShareMeta([{}, {}], [0, 1])).toEqual({})
  })
})

describe('hasResolvableHashes', () => {
  it('true when model_hashes has at least one entry with sha256', () => {
    expect(
      hasResolvableHashes({ model_hashes: { 'a.safetensors': { sha256: 'aa' } } }),
    ).toBe(true)
  })

  it('true on lora_hashes fallback', () => {
    expect(hasResolvableHashes({ lora_hashes: { 'l.safetensors': 'aabbccdd' } })).toBe(true)
  })

  it('false when both maps are empty/missing', () => {
    expect(hasResolvableHashes({})).toBe(false)
    expect(hasResolvableHashes({ model_hashes: {}, lora_hashes: {} })).toBe(false)
  })

  it('false when model_hashes entries have no sha256 field', () => {
    expect(hasResolvableHashes({ model_hashes: { 'a.safetensors': { strength: 1.0 } } })).toBe(false)
  })
})
