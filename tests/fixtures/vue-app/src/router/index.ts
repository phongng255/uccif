import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'itinerary', component: () => import('@/views/ItineraryView.vue') },
    { path: '/expenses', name: 'expenses', component: () => import('@/views/ExpensesView.vue') },
  ],
})

export default router
