import { createRouter, createWebHistory } from 'vue-router'
import { authGuard } from '@auth0/auth0-vue'

const routes = [
  {
    path: '/',
    name: 'landing',
    component: () => import('../pages/LandingPage.vue'),
  },

  // Auth routes
  {
    path: '/login',
    name: 'login',
    component: () => import('../pages/auth/LoginPage.vue'),
  },
  {
    path: '/callback',
    name: 'callback',
    component: () => import('../pages/auth/CallbackPage.vue'),
  },

  // Public registration route
  {
    path: '/register/:token',
    name: 'register',
    component: () => import('../pages/registration/RegistrationPage.vue'),
  },

  // Registration management page (replaces separate confirm/cancel pages)
  {
    path: '/registration/:registrationId',
    name: 'registration-manage',
    component: () => import('../pages/registration/RegistrationManagePage.vue'),
  },

  // Legacy redirects — old email links still work
  {
    path: '/cancel/:registrationId',
    redirect: to => ({
      path: `/registration/${to.params.registrationId}`,
      query: { token: to.query.token },
    }),
  },
  {
    path: '/confirm/:registrationId',
    redirect: to => ({
      path: `/registration/${to.params.registrationId}`,
      query: { token: to.query.token },
    }),
  },

  // Admin routes (protected)
  {
    path: '/admin',
    redirect: '/admin/events',
  },
  {
    path: '/admin/events',
    name: 'admin-events',
    component: () => import('../pages/admin/EventsPage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/events/:eventId/lottery',
    name: 'admin-event-lottery',
    component: () => import('../pages/admin/events/[eventId]/lottery.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/debug',
    name: 'admin-debug',
    component: () => import('../pages/admin/DebugPage.vue'),
    beforeEnter: authGuard,
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
