<template>
  <form class="expense-form" @submit.prevent="submit()">
    <input v-model="title" />
    <input v-model.number="amount" type="number" />
    <BaseButton label="Add" @click="submit()" />
  </form>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { newId } from '@/utils'
import type { Expense } from '@/types/trip'

const emit = defineEmits<{ (e: 'save', expense: Expense): void }>()
const title = ref('')
const amount = ref(0)

function submit() {
  emit('save', { id: newId(), title: title.value, amount: amount.value })
  title.value = ''
  amount.value = 0
}
</script>

<style scoped>
.expense-form { border: 1px solid var(--border); }
</style>
