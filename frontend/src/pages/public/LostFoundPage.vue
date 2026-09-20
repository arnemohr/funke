<template>
  <article class="lostfound">
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true" class="loading-state">
      Einen Moment — die Fundsachen werden geladen ...
    </div>

    <!-- Gone state: the backend answers one bare 404 to every rejection (falscher
         Token, nicht veröffentlicht, abgelaufen, gelöscht) so this page can't be
         used to probe which events exist. We say just as little. -->
    <div v-else-if="gone" role="alert" class="gone-state">
      <h2>Diese Seite gibt es nicht (mehr).</h2>
      <p>Prüf am besten den Link — oder frag die Leute, von denen du ihn bekommen hast.</p>
    </div>

    <div v-else-if="error" role="alert" class="error-state">
      <h2>Das hat gerade nicht geklappt</h2>
      <p>Die Fundsachen konnten nicht geladen werden. Versuch es in einem Moment nochmal.</p>
      <button type="button" class="outline" @click="load()">Nochmal versuchen</button>
    </div>

    <template v-else-if="page">
      <header class="page-header">
        <p class="eyebrow">Fundsachen</p>
        <h2>Fundsachen — {{ page.event_name }}</h2>
        <p v-if="eventDate" class="event-line">{{ eventDate }}</p>
      </header>

      <section class="intro">
        <p v-if="page.intro_text" class="intro-lead intro-custom">{{ page.intro_text }}</p>
        <p v-else class="intro-lead">
          Nach dem {{ page.event_name }} ist eine ganze Kiste liegengeblieben. Hier ist alles drin,
          was wir eingesammelt haben.
        </p>

        <p>
          <strong>Etwas davon gehört dir?</strong> Schreib an
          <template v-for="(contact, i) in contacts" :key="contact.href"
            ><span v-if="i > 0"> oder </span
            ><a :href="contact.href" target="_blank" rel="noopener noreferrer">{{
              contact.label
            }}</a></template
          > und nenne die Nummer am Foto. Wir
          melden uns und klären, wie du deine Sachen zurückbekommst.
        </p>

        <p>
          <strong>Du hast selbst etwas gefunden?</strong> Auch dann ist
          <template v-for="(contact, i) in contacts" :key="contact.href"
            ><span v-if="i > 0"> oder </span
            ><a :href="contact.href" target="_blank" rel="noopener noreferrer">{{
              contact.label
            }}</a></template
          > die richtige Stelle — dann landet es
          hier auf der Seite und findet zurück.
        </p>

        <p class="retention-note">
          Sachen, die niemand abholt, geben wir nach {{ page.retention_days }} Tagen ab oder
          entsorgen sie.
        </p>
      </section>

      <p v-if="!photos.length" class="empty-hint">
        Hier ist noch nichts eingetragen — schau später nochmal.
      </p>

      <ul v-else class="photo-grid">
        <li v-for="photo in photos" :key="photo.number" class="photo-card">
          <button
            type="button"
            class="photo-tile"
            :aria-label="`Fundsache Nr. ${photo.number} größer ansehen`"
            @click="openLightbox(photo.number)"
          >
            <img
              :src="photo.thumb_url"
              :alt="photoAlt(photo)"
              loading="lazy"
              decoding="async"
              @error="handleImageError"
            />
          </button>

          <!-- Just a label. The number is what a guest quotes in their mail, so
               it has to be legible on the photo — but the mail itself is written
               from the one link at the top of the page, which keeps the tile free
               for the tap that actually matters: enlarging the photo. -->
          <span class="number-badge">Nr. {{ photo.number }}</span>

          <p v-if="photo.caption" class="photo-caption">{{ photo.caption }}</p>
        </li>
      </ul>

      <footer class="page-footer">
        <p>
          Fragen, Hinweise, Fundstücke?
          <template v-for="(contact, i) in contacts" :key="contact.href"
            ><span v-if="i > 0"> oder </span
            ><a :href="contact.href" target="_blank" rel="noopener noreferrer">{{
              contact.label
            }}</a></template
          >
        </p>
      </footer>
    </template>

    <!-- Lightbox — teleported so it is never clipped by the page container. -->
    <Teleport to="body">
      <div
        v-if="activePhoto"
        class="lightbox"
        role="dialog"
        aria-modal="true"
        :aria-label="`Fundsache Nr. ${activePhoto.number}`"
        @click.self="closeLightbox"
      >
        <button type="button" class="lb-close" aria-label="Schließen" @click="closeLightbox">
          <X :size="24" aria-hidden="true" />
        </button>

        <button
          v-if="photos.length > 1"
          type="button"
          class="lb-nav lb-prev"
          aria-label="Vorheriges Foto"
          @click="step(-1)"
        >
          <ChevronLeft :size="32" aria-hidden="true" />
        </button>

        <figure class="lb-figure" @touchstart.passive="onTouchStart" @touchend.passive="onTouchEnd">
          <!-- width/height ship in the payload for exactly this: without them the
               caption and the mail button sit under the close button and get
               pushed down by up to 68vh when the JPEG lands. -->
          <img
            :src="activePhoto.display_url"
            :alt="photoAlt(activePhoto)"
            :width="activePhoto.width || null"
            :height="activePhoto.height || null"
            @error="handleImageError"
          />
          <figcaption class="lb-caption">
            <p class="lb-number">Nr. {{ activePhoto.number }}</p>
            <p v-if="activePhoto.caption" class="lb-text">{{ activePhoto.caption }}</p>
            <p class="lb-count">{{ activeIndex + 1 }} von {{ photos.length }}</p>
          </figcaption>
        </figure>

        <button
          v-if="photos.length > 1"
          type="button"
          class="lb-nav lb-next"
          aria-label="Nächstes Foto"
          @click="step(1)"
        >
          <ChevronRight :size="32" aria-hidden="true" />
        </button>
      </div>
    </Teleport>
  </article>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, X } from 'lucide-vue-next'
import { publicApi } from '../../services/api'
import { formatDateOnly } from '../../utils/formatters'

const props = defineProps({
  eventId: { type: String, default: '' },
  token: { type: String, default: '' },
})

const loading = ref(true)
const gone = ref(false)
const error = ref(false)
const page = ref(null)
const loadedAt = ref(0)

const photos = computed(() => page.value?.photos || [])
/**
 * The ways a guest can reach a human, in the order they are offered. Either
 * form may be missing, never both — the backend refuses a page with no contact
 * at all — so this list always has at least one entry.
 */
const contacts = computed(() => {
  const p = page.value
  if (!p) return []

  const list = []
  if (p.coordinator_email) {
    list.push({
      href: mailtoUrl(),
      label: p.coordinator_name || p.coordinator_email,
    })
  }
  if (p.coordinator_telegram_url) {
    list.push({
      href: p.coordinator_telegram_url,
      // Next to a mail address the word „Telegram" is the useful half; on its
      // own the label has to name *who* is being written to.
      label: list.length ? 'Telegram' : telegramLabel(p),
    })
  }
  return list
})

function telegramLabel(p) {
  if (p.coordinator_name) return `${p.coordinator_name} auf Telegram`
  // A public handle can be shown as @name; an invite link is a group hash that
  // means nothing to a reader, so that gets a generic label.
  const handle = /^https:\/\/(?:t\.me|telegram\.me)\/([A-Za-z0-9_]+)$/.exec(
    p.coordinator_telegram_url || '',
  )
  return handle ? `@${handle[1]} auf Telegram` : 'die Telegram-Gruppe'
}
const eventDate = computed(() => formatDateOnly(page.value?.event_date, ''))

function photoAlt(photo) {
  return photo.caption
    ? `Fundsache Nr. ${photo.number}: ${photo.caption}`
    : `Fundsache Nr. ${photo.number}`
}

function mailtoUrl() {
  // One subject for the whole page: the per-photo mail links are gone, so the
  // guest names the number in the body — which is what the copy asks for.
  const subject = `Fundsache — ${page.value?.event_name || ''}`
  return `mailto:${page.value?.coordinator_email}?subject=${encodeURIComponent(subject)}`
}

/* -------------------------------------------------------------------------
 * Loading and refreshing
 *
 * Every image URL is a presigned GET that dies after url_ttl_seconds (900).
 * A tab left open would show empty frames, so the payload is refetched a
 * minute before the URLs expire — but only while the tab is visible, since a
 * background tab has nobody looking at it.
 * ---------------------------------------------------------------------- */

const refreshMs = computed(() => {
  const ttl = Number(page.value?.url_ttl_seconds) || 900
  return Math.max(60, ttl - 60) * 1000
})

let refreshTimer = null
let inFlight = false
// A photo whose S3 object is genuinely missing errors again after every
// refresh; without a cap that would loop for as long as the tab is open.
let errorRefreshes = 0
const MAX_ERROR_REFRESHES = 3

async function load({ silent = false } = {}) {
  if (inFlight) return
  inFlight = true
  if (!silent) {
    loading.value = true
    error.value = false
    gone.value = false
  }
  try {
    page.value = await publicApi.getLostFound(props.eventId, props.token)
    loadedAt.value = Date.now()
    gone.value = false
    error.value = false
    scheduleRefresh()
  } catch (err) {
    // 404 is the backend's single answer to every rejection (spec 023), so it
    // is the one status this page branches on.
    if (err.status === 404) {
      // Withdrawn, expired or rotated away — also mid-session, so this wins
      // over whatever is currently on screen.
      gone.value = true
      page.value = null
      clearRefresh()
    } else if (!silent) {
      error.value = true
    } else {
      // A hiccup on a silent refresh leaves the stale page standing; the next
      // tick or an image error tries again.
      scheduleRefresh()
    }
  } finally {
    loading.value = false
    inFlight = false
  }
}

function clearRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function scheduleRefresh() {
  clearRefresh()
  if (document.visibilityState !== 'visible') return
  refreshTimer = setTimeout(refreshTick, refreshMs.value)
}

// The refresh replaces every URL in the payload. With the lightbox open that
// means the photo somebody is looking at blanks and re-downloads over mobile
// data, for no reason they can see — so the swap waits for them to close it.
// The URLs are still valid at this point; an <img> that does die meanwhile
// triggers `handleImageError`, which refreshes regardless.
const REFRESH_DEFERRAL_MS = 30000

function refreshTick() {
  if (activePhoto.value) {
    refreshTimer = setTimeout(refreshTick, REFRESH_DEFERRAL_MS)
    return
  }
  load({ silent: true })
}

function handleVisibilityChange() {
  if (document.visibilityState !== 'visible') {
    clearRefresh()
    return
  }
  if (!page.value) return
  if (Date.now() - loadedAt.value >= refreshMs.value) {
    refreshTick()
  } else {
    scheduleRefresh()
  }
}

// One refetch for a whole grid of dead URLs, not one per image.
function handleImageError() {
  if (inFlight || errorRefreshes >= MAX_ERROR_REFRESHES) return
  if (Date.now() - loadedAt.value < 5000) return
  errorRefreshes += 1
  load({ silent: true })
}

/* -------------------------------------------------------------------------
 * Lightbox
 * ---------------------------------------------------------------------- */

// Tracked by number, not index: a refresh can add or drop photos, and the
// number is the stable handle (spec 023 — Nummern werden nie neu vergeben).
const activeNumber = ref(null)

const activeIndex = computed(() => photos.value.findIndex((p) => p.number === activeNumber.value))
const activePhoto = computed(() =>
  activeIndex.value === -1 ? null : photos.value[activeIndex.value],
)

function openLightbox(number) {
  activeNumber.value = number
}

function closeLightbox() {
  activeNumber.value = null
  // The timer may have been re-armed several times while the box was open.
  if (page.value && Date.now() - loadedAt.value >= refreshMs.value) load({ silent: true })
}

function step(delta) {
  const count = photos.value.length
  if (!count || activeIndex.value === -1) return
  const next = (activeIndex.value + delta + count) % count
  activeNumber.value = photos.value[next].number
}

function onKeydown(event) {
  if (!activePhoto.value) return
  if (event.key === 'Escape') {
    closeLightbox()
  } else if (event.key === 'ArrowLeft') {
    step(-1)
  } else if (event.key === 'ArrowRight') {
    step(1)
  } else {
    return
  }
  event.preventDefault()
}

let touchStartX = 0
let touchStartY = 0

function onTouchStart(event) {
  touchStartX = event.changedTouches[0].clientX
  touchStartY = event.changedTouches[0].clientY
}

function onTouchEnd(event) {
  const dx = event.changedTouches[0].clientX - touchStartX
  const dy = event.changedTouches[0].clientY - touchStartY
  if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) step(dx < 0 ? 1 : -1)
}

// Keep the page behind the lightbox from scrolling under the finger.
watch(activePhoto, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('keydown', onKeydown)
  load()
})

onUnmounted(() => {
  clearRefresh()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<style scoped>
.lostfound {
  overflow-x: hidden;
}

.loading-state {
  padding: var(--space-6) var(--space-4);
  text-align: center;
}

.gone-state,
.error-state {
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.gone-state h2,
.error-state h2 {
  font-size: var(--text-xl);
  margin-bottom: var(--space-2);
}

.gone-state p,
.error-state p {
  color: var(--color-text-muted);
  margin-bottom: var(--space-3);
}

.page-header {
  margin-bottom: var(--space-4);
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: 0.15rem;
}

.page-header h2 {
  margin-bottom: 0.25rem;
}

.event-line {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.intro {
  margin-bottom: var(--space-5);
}

.intro p {
  margin-bottom: var(--space-3);
}

.intro-lead {
  font-size: var(--text-lg);
}

/* Organiser text arrives as typed, line breaks included. */
.intro-custom {
  white-space: pre-line;
}

.retention-note {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.empty-hint {
  padding: var(--space-5) var(--space-4);
  text-align: center;
  color: var(--color-text-muted);
  background: var(--color-bg-muted);
  border-radius: var(--radius-lg);
}

.photo-grid {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-3);
}

.photo-card {
  position: relative;
  margin: 0;
}

.photo-tile {
  display: block;
  width: 100%;
  padding: 0;
  margin: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--color-bg-muted);
  cursor: zoom-in;
}

.photo-tile img {
  display: block;
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: cover;
}

/* Sits on the photo, so its colours are fixed rather than themed — it has to
   stay readable over a dark tent and a white sneaker alike. Nothing here is a
   tap target any more, so it is sized to be read, not hit. */
.number-badge {
  position: absolute;
  top: var(--space-2);
  left: var(--space-2);
  padding: 0.1rem 0.45rem;
  border-radius: var(--radius-pill);
  background: rgba(12, 30, 60, 0.88);
  color: #fff;
  font-size: 0.8rem;
  font-weight: 600;
  line-height: 1.5;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  pointer-events: none;
}

.photo-caption {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.page-footer {
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.page-footer p {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

/* Teleported to <body>, but still rendered by this component — scoped styles
   reach it. */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  /* flex-start plus the figure's auto margins: still centred when there is
     room, scrollable instead of clipped when there is not. Centring alone
     hides the overflow above the scroll origin, which on a phone in landscape
     puts the mail button — the one call to action — out of reach. */
  align-items: flex-start;
  justify-content: center;
  overflow-y: auto;
  padding: var(--space-3) 0;
  background: rgba(8, 14, 26, 0.94);
  overscroll-behavior: contain;
}

.lb-figure {
  flex: 1 1 auto;
  min-width: 0;
  margin: auto 0;
  max-width: 900px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}

.lb-figure img {
  display: block;
  max-width: 100%;
  max-height: 68vh;
  width: auto;
  height: auto;
  object-fit: contain;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.06);
}

/* Phone turned sideways to see a wide photo: the caption block alone is ~150 px,
   so the photo has to give way rather than push it off the screen. */
@media (orientation: landscape) and (max-height: 520px) {
  .lb-figure img {
    max-height: 52vh;
  }
}

.lb-caption {
  text-align: center;
  color: #fff;
  padding: 0 var(--space-2);
}

.lb-number {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 700;
}

.lb-text {
  margin: var(--space-1) 0 0;
  color: rgba(255, 255, 255, 0.82);
}


.lb-count {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: rgba(255, 255, 255, 0.6);
}

.lb-close,
.lb-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  background: transparent;
  color: #fff;
  cursor: pointer;
}

.lb-close {
  position: absolute;
  top: var(--space-2);
  right: var(--space-2);
  width: 44px;
  height: 44px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.12);
}

/* Full-height strips beside the photo instead of arrows floating on top of it:
   a thumb-sized target on a phone that can never swallow a tap meant for the
   mail button. The swipe gesture on the image covers the same two directions. */
.lb-nav {
  flex: 0 0 auto;
  align-self: stretch;
  width: 48px;
  border-radius: var(--radius-md);
}

.lb-nav:hover {
  background: rgba(255, 255, 255, 0.08);
}
</style>
