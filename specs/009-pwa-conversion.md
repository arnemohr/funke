# spec 009: PWA Conversion

## Summary

Convert the Funke Vue 3 SPA into a Progressive Web App installable on iOS and Android devices. Add Web Push notifications (VAPID) for admin users, auto-update on deploy, and ensure Auth0 token persistence across PWA restarts.

## Requirements

1. **Installable PWA** on iOS (home screen) and Android (install prompt)
2. **Same backend integration** — keep existing Auth0 + Fetch API
3. **Identity stored on device** — Auth0 tokens in localStorage persist across PWA restarts
4. **Token refresh** — Auth0 refresh tokens (already enabled) work through service worker
5. **Push notifications** — Web Push with VAPID keys, admin users only, pywebpush on backend
6. **Test trigger** — push notification when an event is deleted (proof of concept)
7. **Dual mode** — works as website in browser AND installed on device
8. **Auto-update** — service worker detects new version, waits for idle, auto-reloads

## Technical Decisions

- **Push provider**: Web Push with VAPID keys (no external service, zero cost)
- **SW strategy**: `injectManifest` via `vite-plugin-pwa` for custom push handling
- **Caching**: Precache app shell, `NetworkOnly` for API + Auth0
- **Update UX**: Auto-reload after brief "Neue Version wird geladen..." toast
- **DynamoDB**: Push subscriptions in admins table (`pk=ORG#{org_id}`, `sk=PUSH#{admin_sub}`)
- **Icons**: Generated from anchor emoji on navy background

## iOS Notes

- Web Push only works in installed PWA (home screen), not Safari browser — iOS 16.4+
- No `beforeinstallprompt` event — manual "Add to Home Screen" hint needed
- No badge API support
