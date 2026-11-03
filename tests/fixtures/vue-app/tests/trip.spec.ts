import { setActivePinia, createPinia } from 'pinia'
import { useTripStore } from '@/stores/trip'

it('adds an expense', () => {
  setActivePinia(createPinia())
  const s = useTripStore()
  s.addExpense({ id: '1', title: 'a', amount: 5 })
  expect(s.total).toBe(5)
})
