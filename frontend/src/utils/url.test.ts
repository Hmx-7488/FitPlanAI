import { describe, expect, it } from 'vitest'

import { safeExternalUrl } from './url'

describe('safeExternalUrl', () => {
  it('allows only absolute http and https links', () => {
    expect(safeExternalUrl('https://example.com/source')).toBe('https://example.com/source')
    expect(safeExternalUrl('http://example.com/source')).toBe('http://example.com/source')
    expect(safeExternalUrl('javascript:alert(1)')).toBeUndefined()
    expect(safeExternalUrl('/relative/source')).toBeUndefined()
  })
})
