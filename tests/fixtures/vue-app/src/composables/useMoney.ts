import { computed } from 'vue'
import { useTripStore } from '@/stores/trip'
import { formatMoney } from '@/utils'

export function useMoney() {
  const store = useTripStore()
  const label = computed(() => formatMoney(store.total))
  return { label }
}
