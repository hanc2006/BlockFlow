/**
 * Tests for the pure helpers in the loras client (sgs-ui-eqc.2).
 * HTTP wrappers are exercised via the page-body integration tests.
 */
import { describe, expect, test } from 'vitest'

import { detectUrlSource, formatBytes, parseCivitaiInput } from './client'

describe('parseCivitaiInput', () => {
  test('extracts versionId from full civitai URL', () => {
    expect(parseCivitaiInput('https://civitai.com/models/12345?modelVersionId=67890'))
      .toEqual({ versionId: 67890 })
  })

  test('returns needsLatest for model-only URL', () => {
    expect(parseCivitaiInput('https://civitai.com/models/12345'))
      .toEqual({ modelId: 12345, needsLatest: true })
  })

  test('model URL with slug suffix still resolves', () => {
    expect(parseCivitaiInput('https://civitai.com/models/12345/my-lora'))
      .toEqual({ modelId: 12345, needsLatest: true })
  })

  test('bare integer treated as versionId', () => {
    expect(parseCivitaiInput('67890')).toEqual({ versionId: 67890 })
  })

  test('rejects non-civitai host', () => {
    expect(parseCivitaiInput('https://example.com/models/1')).toBeNull()
  })

  test('rejects huggingface URL (handled by URL source)', () => {
    expect(parseCivitaiInput('https://huggingface.co/foo/bar')).toBeNull()
  })

  test('rejects empty', () => {
    expect(parseCivitaiInput('')).toBeNull()
    expect(parseCivitaiInput('   ')).toBeNull()
  })

  test('rejects non-integer model id', () => {
    expect(parseCivitaiInput('https://civitai.com/models/abc')).toBeNull()
  })

  test('rejects zero and negative', () => {
    expect(parseCivitaiInput('0')).toBeNull()
    expect(parseCivitaiInput('-5')).toBeNull()
  })
})

describe('detectUrlSource', () => {
  test('huggingface URL → hf', () => {
    expect(detectUrlSource('https://huggingface.co/foo/bar/resolve/main/a.safetensors')).toBe('hf')
  })

  test('non-huggingface URL → url', () => {
    expect(detectUrlSource('https://example.com/a.safetensors')).toBe('url')
  })

  test('invalid URL → url', () => {
    expect(detectUrlSource('not a url')).toBe('url')
  })
})

describe('formatBytes', () => {
  test('null/undefined → em-dash', () => {
    expect(formatBytes(null)).toBe('—')
  })

  test('formats KB / MB / GB', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(5 * 1024 ** 2)).toBe('5.0 MB')
    expect(formatBytes(2 * 1024 ** 3)).toBe('2.00 GB')
  })
})
