import { watch } from 'vue'
import { useTripStore } from '@/stores/trip'
import { saveTrip } from '@/utils/firebase'

export function useSync() {
  const store = useTripStore()

  async function sync() {
    await saveTrip(store.$state)
  }

  function start() {
    watch(() => store.expenses, sync, { deep: true })
  }

  return { sync, start }
}
