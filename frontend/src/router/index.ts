import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
    },
    {
      path: '/profile',
      name: 'profile',
      component: () => import('../views/ProfileView.vue'),
    },
    {
      path: '/plan',
      name: 'plan',
      component: () => import('../views/PlanView.vue'),
    },
    {
      path: '/analysis',
      name: 'analysis',
      component: () => import('../views/AnalysisView.vue'),
    },
    {
      path: '/checkin',
      name: 'checkin',
      component: () => import('../views/CheckinView.vue'),
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('../views/HistoryView.vue'),
    },
    {
      path: '/food',
      name: 'food',
      component: () => import('../views/FoodView.vue'),
    },
    {
      path: '/body-photo',
      name: 'body-photo',
      component: () => import('../views/BodyPhotoView.vue'),
    },
    {
      path: '/pose',
      name: 'pose',
      component: () => import('../views/PoseView.vue'),
    },
    {
      path: '/meal',
      name: 'meal',
      component: () => import('../views/MealView.vue'),
    },
    {
      path: '/daily',
      name: 'daily',
      component: () => import('../views/DailyView.vue'),
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('../views/ChatView.vue'),
    },
  ],
})

export default router
