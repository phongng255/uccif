<template>
  <header class="header">
    <h1>{{ title }}</h1>
    <BaseButton label="Theme" @click="emit('toggle-theme')" />
  </header>
</template>

<script setup lang="ts">
defineProps<{ title: string }>()
const emit = defineEmits<{ (e: 'toggle-theme'): void }>()
</script>

<style scoped>
.header { background: var(--brand-color); }
</style>
