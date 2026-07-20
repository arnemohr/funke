/* eslint-env serviceworker */
import { precacheAndRoute, cleanupOutdatedCaches } from 'workbox-precaching'
import { registerRoute } from 'workbox-routing'
import { NetworkOnly } from 'workbox-strategies'

// Precache all build assets (injected by vite-plugin-pwa)
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// API calls: network only (online-only app, never cache API responses).
// The scanner's offline check-in mode (spec 019 §P3, T311) is handled at
// the APP level instead — boot payload + verification secret in
// localStorage, local WebCrypto HMAC verify, scan retry queue — never via
// SW response caching. Do not "fix" this by adding a cache strategy for
// `/api/public/checkin/*`: this rule intentionally stands.
registerRoute(
  ({ url }) => url.pathname.startsWith('/api/'),
  new NetworkOnly()
)

// Auth0: never cache, never intercept
registerRoute(
  ({ url }) => url.hostname.endsWith('.auth0.com'),
  new NetworkOnly()
)

// Push notification handler
self.addEventListener('push', (event) => {
  if (!event.data) return

  const data = event.data.json()
  const title = data.title || 'Funke'
  const options = {
    body: data.body || '',
    icon: '/icons/icon-192x192.png',
    badge: '/icons/icon-192x192.png',
    data: { url: data.url || '/' },
    tag: 'funke-notification',
    renotify: true,
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

// Notification click: focus existing tab or open new window
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification.data?.url || '/'

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(url)
          return client.focus()
        }
      }
      return clients.openWindow(url)
    })
  )
})

// Auto-update: skip waiting when new SW is ready
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting()
  }
})
