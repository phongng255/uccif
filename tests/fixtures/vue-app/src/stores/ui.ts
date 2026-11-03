import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const dark = ref(false)
  function toggle() {
    dark.value = !dark.value
  }
  return { dark, toggle }
})
