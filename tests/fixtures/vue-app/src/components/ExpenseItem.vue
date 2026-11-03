<template>
  <li class="expense-item">
    <span>{{ expense.title }}</span>
    <span>{{ formatMoney(expense.amount) }}</span>
    <BaseButton label="x" @click="$emit('remove', expense.id)" />
  </li>
</template>

<script setup lang="ts">
import { formatMoney } from '@/utils/format'
import type { Expense } from '@/types/trip'

defineProps<{ expense: Expense }>()
defineEmits<{ (e: 'remove', id: string): void }>()
</script>

<style scoped>
.expense-item { border-bottom: 1px solid var(--border); }
</style>
