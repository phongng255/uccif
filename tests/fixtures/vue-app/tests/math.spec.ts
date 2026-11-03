import { describe, it, expect } from 'vitest'
import { sumAmounts } from '@/utils/math'
import { formatMoney } from '@/utils'

describe('math', () => {
  it('sums', () => expect(sumAmounts([1, 2])).toBe(3))
  it('formats', () => expect(formatMoney(1)).toBe('฿1.00'))
})
