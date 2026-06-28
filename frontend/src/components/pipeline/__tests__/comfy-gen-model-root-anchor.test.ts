import { describe, it, expect } from 'vitest'
import { findModelRootIds } from '../custom_blocks/generated/comfy_gen'

describe('findModelRootIds (seed anchor for no-LoRA workflows)', () => {
  it('finds a UNETLoader feeding a KSampler', () => {
    const wf = {
      '1': { class_type: 'UNETLoader', inputs: { unet_name: 'krea2.safetensors' } },
      '2': { class_type: 'KSampler', inputs: { model: ['1', 0], seed: 1 } },
    }
    const roots = findModelRootIds(wf)
    expect(roots.get('1')).toBe('UNETLoader')
    expect(roots.size).toBe(1)
  })

  it('excludes nodes that consume a model (LoRA loaders, sampling patches)', () => {
    const wf = {
      '1': { class_type: 'UNETLoader', inputs: { unet_name: 'b.safetensors' } },
      '16': { class_type: 'LoraLoaderModelOnly', inputs: { lora_name: 'a', model: ['1', 0] } },
      '2': { class_type: 'KSampler', inputs: { model: ['16', 0] } },
    }
    const roots = findModelRootIds(wf)
    // only the raw loader is a root; the LoRA loader consumes a model
    expect([...roots.keys()]).toEqual(['1'])
  })

  it('returns empty for a modelless / malformed workflow', () => {
    expect(findModelRootIds({ '9': { class_type: 'SaveImage', inputs: {} } }).size).toBe(0)
    expect(findModelRootIds(null).size).toBe(0)
    expect(findModelRootIds('nope').size).toBe(0)
  })
})
