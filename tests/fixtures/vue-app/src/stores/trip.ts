import { defineStore } from 'pinia'
import type { Expense } from '@/types/trip'
import { sumAmounts } from '@/utils/math'

export const useTripStore = defineStore('trip', {
  state: () => ({ name: 'Thailand', expenses: [] as Expense[] }),
  getters: {
    total: (s) => sumAmounts(s.expenses.map((e) => e.amount)),
  },
  actions: {
    addExpense(e: Expense) {
      this.expenses.push(e)
    },
    removeExpense(id: string) {
      this.expenses = this.expenses.filter((e) => e.id !== id)
    },
  },
})
