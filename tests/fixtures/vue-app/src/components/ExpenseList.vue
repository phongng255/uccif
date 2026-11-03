<template>
  <ul class="expense-list">
    <ExpenseItem v-for="e in store.expenses" :key="e.id" :expense="e" @remove="remove" />
    <li class="total">{{ formatMoney(store.total) }}</li>
  </ul>
  <ExpenseForm @save="add" />
</template>

<script setup lang="ts">
import ExpenseItem from './ExpenseItem.vue'
import ExpenseForm from './ExpenseForm.vue'
import { useTripStore } from '@/stores/trip'
import { formatMoney } from '@/utils'
import type { Expense } from '@/types/trip'

const store = useTripStore()

function add(e: Expense) {
  store.addExpense(e)
}

function remove(id: string) {
  store.removeExpense(id)
}
</script>

<style scoped>
.expense-list { color: var(--text); }
.total { font-weight: bold; }
</style>
