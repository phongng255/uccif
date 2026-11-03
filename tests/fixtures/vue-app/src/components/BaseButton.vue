<template>
  <button class="btn" @click="$emit('click')">{{ label }}</button>
</template>

<script setup lang="ts">
defineProps<{ label: string }>()
defineEmits(['click'])
</script>

<style scoped>
.btn { background: var(--brand-color); border-radius: var(--radius); }
</style>
