import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from '@/router'
import BaseButton from '@/components/BaseButton.vue'
import '@/styles/tokens.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.component('BaseButton', BaseButton)
app.mount('#app')
