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

  // Public festival invite route (spec 019 — festival sidetrack)
  {
    path: '/invite/:inviteToken',
    name: 'festival-invite',
    component: () => import('../pages/registration/FestivalRegistrationPage.vue'),
    props: true,
  },

  // Public guestlist view for a contingent invite link (owner sees their
  // allotment fill up; same token as the invite itself).
  {
    path: '/invite/:inviteToken/liste',
    name: 'festival-invite-guestlist',
    component: () => import('../pages/registration/GuestlistPage.vue'),
    props: true,
  },

  // Companion's read-only personal ticket page (spec 020) — no authGuard, the
  // per-person token in the query string IS the auth. Read-only by
  // construction: no endpoint accepts that token for a write.
  {
    path: '/ticket/:eventId/:registrationId/:personIndex',
    name: 'person-ticket',
    component: () => import('../pages/registration/PersonTicketPage.vue'),
    props: true,
  },

  // Public lost & found gallery (spec 023) — no authGuard, the page token in
  // the path IS the auth. The event id next to it is deliberately not secret.
  {
    path: '/lostfound/:eventId/:token',
    name: 'lost-and-found',
    component: () => import('../pages/public/LostFoundPage.vue'),
    props: true,
    meta: { hideTabBar: true },
  },

  // Public photo upload (spec 024) — no authGuard, the upload token in the
  // path IS the auth, exactly as for the Fundsachen page above. The German
  // path is deliberate: this link goes on a printed sheet at the exit.
  //
  // The opposite direction of /lostfound: this route is **write-only**. There
  // is no read path for guests here, not even to their own upload, and the
  // public payload carries no photo id, key or image URL that could become
  // one.
  {
    path: '/fotos/:eventId/:token',
    name: 'photo-upload',
    component: () => import('../pages/public/PhotoUploadPage.vue'),
    props: true,
    meta: { hideTabBar: true },
  },

  // Scanner gate check-in (spec 019 §P3) — no authGuard, the gate token IS
  // the auth (spec.md:336).
  {
    path: '/checkin/:gateToken',
    name: 'checkin-scanner',
    component: () => import('../pages/checkin/ScannerPage.vue'),
    props: true,
    meta: { hideTabBar: true },
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
  // Fundsachen admin (spec 023) — same page for SINGLE and FESTIVAL events.
  {
    path: '/admin/events/:eventId/lostfound',
    name: 'admin-lost-and-found',
    component: () => import('../pages/admin/LostFoundAdminPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  // Eventfotos admin (spec 024) — same page for SINGLE and FESTIVAL events.
  {
    path: '/admin/events/:eventId/fotos',
    name: 'admin-event-photos',
    component: () => import('../pages/admin/EventPhotosAdminPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  // Public charter signing (spec 025 addendum) — no authGuard: the sign_token
  // in the path IS the credential, as for /lostfound and the gate. The token
  // dies on every re-render, so a link never outlives the text it showed.
  {
    path: '/vertrag/:eventId/:token',
    name: 'charter-sign',
    component: () => import('../pages/public/CharterSignPage.vue'),
    props: true,
    meta: { hideTabBar: true },
  },
  // Chartervertrag (spec 025) — SINGLE events only; one contract per event.
  {
    path: '/admin/events/:eventId/chartervertrag',
    name: 'admin-charter-contract',
    component: () => import('../pages/admin/CharterContractPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/events/:eventId/registrations/:registrationId',
    name: 'admin-registration-detail',
    component: () => import('../pages/admin/RegistrationDetailPage.vue'),
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
  // Schaluppe Fahrbericht (specs 010-014)
  {
    path: '/admin/profile',
    name: 'admin-profile',
    component: () => import('../pages/admin/ProfilePage.vue'),
    beforeEnter: authGuard,
  },
  {
    path: '/admin/events/:eventId/fahrbericht',
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
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/schaluppe',
    name: 'admin-schaluppe',
    component: () => import('../pages/admin/ShipStatePage.vue'),
    beforeEnter: authGuard,
  },
  // Legacy — keep for stale bookmarks until staff migrate.
  {
    path: '/admin/ship',
    redirect: '/admin/schaluppe',
  },
  {
    path: '/admin/reports/:id',
    name: 'admin-report-detail',
    component: () => import('../pages/admin/ReportDetailPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  // Festival admin (spec 019 — festival sidetrack)
  {
    path: '/admin/festival',
    name: 'admin-festival',
    component: () => import('../pages/admin/festival/FestivalListPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/festival/new',
    name: 'admin-festival-new',
    component: () => import('../pages/admin/festival/FestivalCreatePage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/festival/:eventId',
    name: 'admin-festival-detail',
    component: () => import('../pages/admin/festival/FestivalPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/festival/:eventId/invites',
    name: 'admin-festival-invites',
    component: () => import('../pages/admin/festival/InvitesPage.vue'),
    beforeEnter: authGuard,
    props: true,
  },
  {
    path: '/admin/festival/:eventId/headcount',
    name: 'admin-festival-headcount',
    component: () => import('../pages/admin/festival/HeadcountPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
  {
    path: '/admin/festival/:eventId/registrations',
    name: 'admin-festival-registrations',
    component: () => import('../pages/admin/festival/FestivalRegistrationsPage.vue'),
    beforeEnter: authGuard,
    props: true,
    meta: { hideTabBar: true },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, saved) {
    return saved || { top: 0 }
  },
})
