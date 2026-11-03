<template>
  <div class="app" :class="{ dark: ui.dark }">
    <AppHeader :title="trip.name" @toggle-theme="ui.toggle()" />
    <nav class="tabs">
      <button v-for="t in tabs" :key="t" :class="{ active: tab === t }" @click="select(t)">{{ t }}</button>
    </nav>
    <section v-show="tab === 'Expenses'"><ExpenseList /></section>
    <section v-show="tab === 'Itinerary'"><RouterView /></section>
    <BaseButton label="Sync" @click="sync()" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import ExpenseList from '@/components/ExpenseList.vue'
import { useTripStore } from '@/stores/trip'
import { useUiStore } from '@/stores/ui'
import { useSync } from '@/composables/useSync'

const trip = useTripStore()
const ui = useUiStore()
const { sync, start } = useSync()
const tabs = ['Expenses', 'Itinerary']
const tab = ref('Expenses')

function select(t: string) {
  tab.value = t
}

onMounted(start)
</script>

<style scoped>
.app { background: var(--bg); color: var(--text); }
.tabs button.active { color: var(--brand-color); }
</style>
