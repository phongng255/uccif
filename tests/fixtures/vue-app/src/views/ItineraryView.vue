<template>
  <div class="itinerary">
    <RouterLink to="/expenses">Expenses</RouterLink>
    <p>{{ label }}</p>
  </div>
</template>

<script setup lang="ts">
import { useMoney } from '@/composables/useMoney'

const { label } = useMoney()
</script>
