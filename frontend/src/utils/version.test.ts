import { describe, expect, it } from 'vitest'
import { formatVersion } from './version'

describe('formatVersion', () => {
  it.each([
    ['v1', 'v1'],
    ['V2', 'V2'],
    ['1.0.0', 'v1.0.0'],
    [3, 'v3'],
    ['', ''],
    [null, ''],
    [undefined, ''],
  ])('%s -> %s', (input, out) => {
    expect(formatVersion(input as string | number | null | undefined)).toBe(out)
  })
})
