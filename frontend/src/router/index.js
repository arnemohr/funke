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
    path: '/admin/events/new',
    name: 'admin-event-new',
    component: () => import('../pages/admin/EventEditPage.vue'),
    beforeEnter: authGuard,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/events/:eventId',
    name: 'admin-event-detail',
    component: () => import('../pages/admin/EventDetailPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/events/:eventId/edit',
    name: 'admin-event-edit',
    component: () => import('../pages/admin/EventEditPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/events/:eventId/discard',
    name: 'admin-event-discard',
    component: () => import('../pages/admin/EventDiscardPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/events/:eventId/lottery',
    name: 'admin-event-lottery',
    component: () => import('../pages/admin/events/[eventId]/lottery.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/settings',
    name: 'admin-settings',
    component: () => import('../pages/admin/SettingsPage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/debug',
    name: 'admin-debug',
    component: () => import('../pages/admin/DebugPage.vue'),
    beforeEnter: authGuard,
  },
  // Schaluppe Fahrbericht (specs 010-013)
  {
    path: '/admin/profile',
    name: 'admin-profile',
    component: () => import('../pages/admin/ProfilePage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/tours',
    name: 'admin-tours',
    component: () => import('../pages/admin/TourListPage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/tours/new',
    name: 'admin-tour-new',
    component: () => import('../pages/admin/TourCreatePage.vue'),
    beforeEnter: authGuard,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/tours/:id',
    name: 'admin-tour-detail',
    component: () => import('../pages/admin/TourDetailPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/tours/:tourId/fahrbericht',
    name: 'admin-fahrbericht',
    component: () => import('../pages/admin/FahrberichtPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/bar',
    name: 'admin-bar',
    component: () => import('../pages/admin/BarCatalogPage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/bar/:id',
    name: 'admin-bar-item',
    component: () => import('../pages/admin/BarItemFormPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/ship',
    name: 'admin-ship',
    component: () => import('../pages/admin/ShipStatePage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/reports',
    name: 'admin-reports',
    component: () => import('../pages/admin/ReportsListPage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/reports/:id',
    name: 'admin-report-detail',
    component: () => import('../pages/admin/ReportDetailPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, saved) {
    return saved || { top: 0 }
  },
})
