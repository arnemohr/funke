<template>
  <div class="scanner-page">
    <!-- Boot loading -->
    <div v-if="booting" aria-busy="true" class="boot-state">
      Scanner wird geladen...
    </div>

    <!-- Boot error (404 / 410 / no cache offline) -->
    <div v-else-if="bootError" role="alert" class="boot-error">
      <h2>Scanner nicht verfügbar</h2>
      <p>{{ bootError }}</p>
    </div>

    <template v-else>
      <!-- Offline banner (T311, Risk 5: degraded, not blind) -->
      <div v-if="offlineMode" class="offline-banner" role="status">
        Offline — eingeschränkte Prüfung. Gruppenstatus, Stornos und Doppel-Scans
        sind nicht sichtbar. Papierliste bleibt die Referenz.
      </div>

      <header class="scanner-header">
        <div class="scanner-header-text">
          <strong>{{ boot.event_name }}</strong>
          <span class="scanner-header-sub">Einlass-Scanner</span>
        </div>
        <button
          v-if="checkinQueue.queueCount.value > 0"
          type="button"
          class="queue-badge"
          :aria-busy="checkinQueue.syncing.value"
          @click="checkinQueue.flush()"
        >
          {{ checkinQueue.queueCount.value }} {{ checkinQueue.queueCount.value === 1 ? 'Scan' : 'Scans' }}
          warten auf Sync
          <span class="queue-badge-action">Jetzt synchronisieren</span>
        </button>
      </header>

      <FestivalHelp v-show="!card" title="Kurz erklärt">
        <p>Einmal scannen, Bändchen dran — fertig. Wer wieder reinkommt, zeigt einfach das Bändchen.</p>
        <p>Kein Code? Unten nach dem Namen suchen. Kein Netz? Weiterscannen — im Zweifel gilt die Papierliste.</p>
      </FestivalHelp>

      <!-- Camera -->
      <div v-show="!card" class="camera-area">
        <video ref="videoEl" class="camera-video" playsinline muted></video>
        <div v-if="cameraError" role="alert" class="camera-error">
          {{ cameraError }}
        </div>
        <p class="camera-hint">QR-Code vor die Kamera halten.</p>
      </div>

      <!-- Name search (no-QR fallback) -->
      <section v-show="!card" class="search-section">
        <button type="button" class="search-toggle touch-target" @click="toggleSearch">
          {{ searchOpen ? 'Namenssuche schließen' : '🔍 Namenssuche' }}
        </button>

        <div v-if="searchOpen" class="search-panel">
          <input
            ref="searchInputEl"
            v-model="searchQuery"
            type="search"
            placeholder="Name eingeben (mind. 2 Zeichen)"
            class="search-input"
            autocomplete="off"
          />
          <p v-if="searching" aria-busy="true">Suche läuft...</p>
          <p v-else-if="searchError" role="alert" class="search-error">{{ searchError }}</p>
          <p v-else-if="searchQuery.trim().length >= 2 && searchResults.length === 0" class="search-empty">
            Keine Treffer.
          </p>

          <ul v-if="searchResults.length" class="search-results">
            <li
              v-for="match in searchResults"
              :key="`${match.registration_id}-${match.person_index}`"
              class="search-result-row touch-target"
              @click="checkinFromSearch(match)"
            >
              <div class="search-result-main">
                <strong>{{ match.person_name }}</strong>
                <span v-if="match.person_index !== 0" class="search-result-context">
                  bei {{ match.contact_name }}
                </span>
              </div>
              <div class="search-result-meta">
                <span>Gruppe {{ match.group_size }}</span>
                <span v-if="match.invite_label">· {{ match.invite_label }}</span>
                <span v-if="match.tier">· {{ match.tier }}</span>
                <span class="status-chip" :class="match.checked_in ? 'chip-checked' : 'chip-open'">
                  {{ match.checked_in ? 'eingecheckt' : 'offen' }}
                </span>
              </div>
            </li>
          </ul>
        </div>
      </section>
    </template>

    <!-- Traffic-light result card (Ä13, spec.md:59) -->
    <Teleport to="body">
      <div v-if="card" class="scan-card" :class="`scan-card-${card.type}`" role="dialog" aria-modal="true">
        <!-- 🟢 Green: accepted (online or offline-degraded) -->
        <template v-if="card.type === 'green'">
          <p v-if="card.offline" class="scan-card-degraded-note">
            Offline-Scan — Gruppenstatus &amp; Doppel-Scans nicht geprüft, wird synchronisiert.
          </p>
          <p class="scan-card-glyph" aria-hidden="true">✓</p>
          <h1 class="scan-card-headline">Eingecheckt — Bändchen ausgeben</h1>
          <p class="scan-card-name">{{ card.personName }}</p>
          <p v-if="card.contactName && card.contactName !== card.personName" class="scan-card-sub">
            bei {{ card.contactName }}
          </p>

          <p v-if="OVERNIGHT_ENABLED" class="scan-card-overnight">
            <span aria-hidden="true">{{ card.overnight.icon }}</span>
            {{ card.overnight.text }}
          </p>

          <div v-if="card.slotLabelsList.length" class="scan-card-slots">
            <p class="scan-card-slots-label">Zeitfenster (nur Info):</p>
            <ul class="scan-card-list">
              <li v-for="label in card.slotLabelsList" :key="label" class="scan-card-list-row">
                <span class="scan-card-row-text">{{ label }}</span>
              </li>
            </ul>
          </div>

          <div v-if="card.group && card.group.length" class="scan-card-group">
            <p class="scan-card-slots-label">Gruppe:</p>
            <ul class="scan-card-list">
              <li
                v-for="member in card.group"
                :key="member.person_index"
                class="scan-card-list-row"
                :class="{ 'is-current': member.person_index === card.personIndex }"
              >
                <span class="scan-card-row-state" aria-hidden="true">{{ member.checked_in ? '✓' : '○' }}</span>
                <span class="scan-card-row-text">{{ member.name }}</span>
                <span class="visually-hidden">{{ member.checked_in ? 'eingecheckt' : 'noch nicht eingecheckt' }}</span>
              </li>
            </ul>
          </div>

          <button
            v-if="card.scanId && undoSecondsLeft > 0 && !card.undoFailed"
            type="button"
            class="scan-card-undo touch-target"
            @click="handleUndo"
          >
            Rückgängig ({{ undoSecondsLeft }})
          </button>
          <p v-else-if="card.undoFailed" class="scan-card-undo-failed">
            Rückgängig nicht mehr möglich
          </p>

          <button type="button" class="scan-card-continue touch-target" @click="continueScanning">
            Weiter scannen
          </button>
        </template>

        <!-- 🟡 Yellow: already checked in -->
        <template v-else-if="card.type === 'yellow'">
          <p class="scan-card-glyph" aria-hidden="true">⚠</p>
          <h1 class="scan-card-headline">Bereits eingecheckt</h1>
          <p class="scan-card-name">{{ card.personName }}</p>
          <p v-if="card.contactName && card.contactName !== card.personName" class="scan-card-sub">
            bei {{ card.contactName }}
          </p>
          <p class="scan-card-sub">Bändchen verloren? Ihr entscheidet vor Ort.</p>

          <p v-if="OVERNIGHT_ENABLED" class="scan-card-overnight">
            <span aria-hidden="true">{{ card.overnight.icon }}</span>
            {{ card.overnight.text }}
          </p>

          <div v-if="card.slotLabelsList.length" class="scan-card-slots">
            <p class="scan-card-slots-label">Zeitfenster (nur Info):</p>
            <ul class="scan-card-list">
              <li v-for="label in card.slotLabelsList" :key="label" class="scan-card-list-row">
                <span class="scan-card-row-text">{{ label }}</span>
              </li>
            </ul>
          </div>

          <div v-if="card.group && card.group.length" class="scan-card-group">
            <p class="scan-card-slots-label">Gruppe:</p>
            <ul class="scan-card-list">
              <li
                v-for="member in card.group"
                :key="member.person_index"
                class="scan-card-list-row"
                :class="{ 'is-current': member.person_index === card.personIndex }"
              >
                <span class="scan-card-row-state" aria-hidden="true">{{ member.checked_in ? '✓' : '○' }}</span>
                <span class="scan-card-row-text">{{ member.name }}</span>
                <span class="visually-hidden">{{ member.checked_in ? 'eingecheckt' : 'noch nicht eingecheckt' }}</span>
              </li>
            </ul>
          </div>

          <p v-if="card.overrideError" role="alert" class="scan-card-inline-error">
            {{ card.overrideError }}
          </p>

          <button
            type="button"
            class="scan-card-override touch-target"
            :aria-busy="overriding"
            @click="handleOverrideYellow"
          >
            Trotzdem einchecken
          </button>

          <button type="button" class="scan-card-continue touch-target" @click="continueScanning">
            Weiter scannen
          </button>
        </template>

        <!-- 🔴 Red: rejected -->
        <template v-else-if="card.type === 'red'">
          <p class="scan-card-glyph" aria-hidden="true">✕</p>
          <h1 class="scan-card-headline">{{ card.message }}</h1>

          <button type="button" class="scan-card-search-shortcut touch-target" @click="openSearchFromCard">
            Namenssuche
          </button>

          <button type="button" class="scan-card-continue touch-target" @click="continueScanning">
            Weiter scannen
          </button>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import QrScanner from 'qr-scanner'
import { checkinApi } from '../../services/api'
import { OVERNIGHT_ENABLED } from '../../config/festival.js'
import FestivalHelp from '../../components/help/FestivalHelp.vue'
import { useCheckinQueue } from '../../composables/useCheckinQueue'
import { verifyTicketLocal } from '../../utils/ticketVerify'

const props = defineProps({
  gateToken: { type: String, required: true },
})

const checkinQueue = useCheckinQueue(props.gateToken)

// -- boot state -------------------------------------------------------------

const booting = ref(true)
const bootError = ref(null)
const boot = ref(null)
const offlineMode = ref(false)

const RED_MESSAGES = {
  invalid_signature: 'Ungültiger Code',
  cancelled: 'Anmeldung storniert',
  stale_ticket: 'Ticket veraltet — bitte Namenssuche',
  unknown_registration: 'Anmeldung nicht gefunden',
}

function bootCacheKey() {
  return `checkin-boot-${props.gateToken}`
}

function persistBootCache(data) {
  try {
    localStorage.setItem(bootCacheKey(), JSON.stringify(data))
  } catch {
    // Best effort — offline fallback just won't have a cache next time.
  }
}

function loadBootCache() {
  try {
    const raw = localStorage.getItem(bootCacheKey())
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

// -- camera / QR scanning ----------------------------------------------------

const videoEl = ref(null)
const cameraError = ref(null)
const paused = ref(false)
let scannerInstance = null
let lastCode = null
let lastCodeAt = 0

// -- result card + undo -------------------------------------------------------

const card = ref(null)
const undoSecondsLeft = ref(0)
const overriding = ref(false)
let undoInterval = null
let undoDeadline = 0

// -- name search --------------------------------------------------------------

const searchOpen = ref(false)
const searchQuery = ref('')
const searchResults = ref([])
const searching = ref(false)
const searchError = ref(null)
const searchInputEl = ref(null)
let searchDebounceTimer = null

// -- computed -------------------------------------------------------------

const slotLabelMap = computed(() => {
  const map = {}
  for (const slot of boot.value?.festival_slots || []) map[slot.key] = slot.label
  return map
})

// -- helpers ----------------------------------------------------------------

function isNetworkError(err) {
  // Every browser throws a TypeError from fetch() itself on a network
  // failure ("Failed to fetch" / "Load failed" / "NetworkError..."), as
  // opposed to the Error our api.js `request()` throws (with `.status`)
  // for a real HTTP error response.
  return err instanceof TypeError
}

function slotLabels(keys) {
  return (keys || []).map((k) => slotLabelMap.value[k] || k)
}

// Ä21: render tent/camper counts as "2 Zelte, 1 Camper" (empty when none).
function overnightUnitsLabel(tentCount, camperCount) {
  const parts = []
  if (tentCount) parts.push(`${tentCount} ${tentCount === 1 ? 'Zelt' : 'Zelte'}`)
  if (camperCount) parts.push(`${camperCount} Camper`)
  return parts.join(', ')
}

// Overnight state as a subtle info line (two states only): approved =
// "✅ Übernachtung", anything else = "⛔ Keine Übernachtung". The emoji carries
// the state; the box blends with the card colour rather than shouting.
// Ä21: the tent/camper counts are appended (e.g. "Übernachtung · 2 Zelte,
// 1 Camper") so the crew can verify pitches/vehicles against the Stellplätze.
function buildOvernightLine(overnightStatus, tentCount, camperCount) {
  const label = overnightUnitsLabel(tentCount, camperCount)
  if (overnightStatus === 'approved') {
    return { text: `Übernachtung${label ? ` · ${label}` : ''}`, icon: '✅' }
  }
  return { text: 'Keine Übernachtung', icon: '⛔' }
}

// Ä17, offline: the ticket's `o` snapshot may be stale, but we keep the same
// two-state model — flag true = Übernachtung, anything else = keine. Gate-safe
// by default; online is authoritative.
function buildOfflineOvernightLine(oFlag) {
  if (oFlag) return { text: 'Übernachtung', icon: '✅' }
  return { text: 'Keine Übernachtung', icon: '⛔' }
}

// -- boot ---------------------------------------------------------------

async function bootScanner() {
  booting.value = true
  bootError.value = null
  offlineMode.value = false
  try {
    const response = await checkinApi.boot(props.gateToken)
    boot.value = response
    persistBootCache(response)
  } catch (err) {
    if (isNetworkError(err)) {
      const cached = loadBootCache()
      if (cached) {
        boot.value = cached
        offlineMode.value = true
      } else {
        bootError.value = 'Offline und noch kein Cache vorhanden — bitte einmal mit Netzverbindung öffnen.'
      }
    } else if (err.status === 404) {
      bootError.value = 'Ungültiger Scanner-Link.'
    } else if (err.status === 410) {
      bootError.value = 'Der Einlass ist für dieses Event nicht aktiv.'
    } else {
      bootError.value = err.message || 'Unbekannter Fehler beim Laden.'
    }
  } finally {
    booting.value = false
  }
}

// -- camera control -------------------------------------------------------

function initCamera() {
  if (!videoEl.value) return
  scannerInstance = new QrScanner(videoEl.value, handleDecode, {
    returnDetailedScanResult: true,
    highlightScanRegion: true,
    highlightCodeOutline: true,
    preferredCamera: 'environment',
  })
  scannerInstance.start().catch(() => {
    cameraError.value = 'Kein Kamerazugriff — nutze die Namenssuche.'
  })
}

function pauseScanning() {
  paused.value = true
  scannerInstance?.stop()
}

function resumeScanning() {
  paused.value = false
  scannerInstance?.start().catch(() => {
    cameraError.value = 'Kamera konnte nicht gestartet werden — nutze die Namenssuche.'
  })
}

function handleDecode(result) {
  if (paused.value) return
  const text = result.data
  const now = Date.now()
  // Debounce identical consecutive decodes (the same code can be reported
  // multiple times per second while it's held in front of the camera).
  if (text === lastCode && now - lastCodeAt < 2000) return
  lastCode = text
  lastCodeAt = now
  pauseScanning()
  processCode(text)
}

// -- scan / override orchestration -----------------------------------------

function showRedCard(reason, code) {
  card.value = {
    type: 'red',
    reason,
    message: RED_MESSAGES[reason] || 'Scan fehlgeschlagen — bitte erneut versuchen.',
    code,
  }
}

function showYellowCard(response, code) {
  const c = response.card
  card.value = {
    type: 'yellow',
    code,
    personName: c.person_name,
    contactName: c.contact_name,
    personIndex: c.person_index,
    // Same registration info box as the green card — the crew needs the
    // group state and overnight decision even on a repeat scan.
    group: (c.group || []).filter((m) => m && m.name),
    slotLabelsList: slotLabels(c.attendance_slots),
    overnight: buildOvernightLine(c.overnight_status, c.tent_count, c.camper_count),
    overrideError: null,
  }
}

function showGreenCard(response) {
  const c = response.card
  card.value = {
    type: 'green',
    offline: false,
    scanId: response.scan_id || null,
    personIndex: c.person_index,
    personName: c.person_name,
    contactName: c.contact_name,
    // Display-only: skip tombstoned/removed members (null names, T109) so
    // they never render as empty rows on the card.
    group: (c.group || []).filter((m) => m && m.name),
    slotLabelsList: slotLabels(c.attendance_slots),
    overnight: buildOvernightLine(c.overnight_status, c.tent_count, c.camper_count),
    undoFailed: false,
  }
  if (card.value.scanId) startUndoCountdown()
}

function showDegradedGreenCard(payload) {
  card.value = {
    type: 'green',
    offline: true,
    scanId: null,
    personIndex: payload.p,
    personName: payload.n,
    contactName: null,
    group: null,
    slotLabelsList: slotLabels(payload.s),
    overnight: buildOfflineOvernightLine(payload.o),
    undoFailed: false,
  }
  // No undo offline — nothing has round-tripped to the server yet.
}

function renderScanResponse(response, code) {
  if (response.result === 'invalid') {
    showRedCard(response.reason, code)
    return
  }
  // result === 'green': no scan_id + already_checked_in means nothing was
  // written (needs override) -> yellow. Anything with a scan_id (fresh or
  // overridden) -> green.
  if (!response.scan_id && response.already_checked_in) {
    showYellowCard(response, code)
  } else {
    showGreenCard(response)
  }
}

async function handleOfflineScan(code) {
  // Surface the degraded-mode banner as soon as we detect we're offline,
  // even if the initial boot succeeded (airplane mode mid-session) — not
  // just when the boot fetch itself failed.
  offlineMode.value = true
  const secret = boot.value?.verification_secret
  if (!secret) {
    showRedCard('invalid_signature', code)
    return
  }
  const payload = await verifyTicketLocal(secret, code)
  if (!payload) {
    showRedCard('invalid_signature', code)
    return
  }
  showDegradedGreenCard(payload)
  checkinQueue.enqueue(code)
}

async function processCode(code) {
  try {
    const response = await checkinApi.scan(props.gateToken, code)
    renderScanResponse(response, code)
  } catch (err) {
    if (isNetworkError(err)) {
      await handleOfflineScan(code)
    } else {
      showRedCard('request_failed', code)
    }
  }
}

async function handleOverrideYellow() {
  const code = card.value?.code
  if (!code) return
  overriding.value = true
  try {
    const response = await checkinApi.override(props.gateToken, { code })
    renderScanResponse(response, code)
  } catch (err) {
    if (isNetworkError(err)) {
      // The retry queue only ever re-posts plain /scan codes — an override
      // needs the server's override=True path, so it can't be queued the
      // same way. Ask the crew to retry once back online.
      card.value = { ...card.value, overrideError: 'Offline — Override erst mit Netzverbindung möglich.' }
    } else {
      card.value = { ...card.value, overrideError: 'Einchecken fehlgeschlagen — bitte erneut versuchen.' }
    }
  } finally {
    overriding.value = false
  }
}

// -- undo ---------------------------------------------------------------

function clearUndoTimer() {
  if (undoInterval) {
    clearInterval(undoInterval)
    undoInterval = null
  }
  undoSecondsLeft.value = 0
}

// 30s grace period at the gate — long enough for the crew to notice a
// mis-scan and react. The backend undo window (UNDO_WINDOW = 60s) is the
// hard limit; keep this comfortably under it.
const UNDO_GRACE_SECONDS = 30

function startUndoCountdown() {
  clearUndoTimer()
  undoDeadline = Date.now() + UNDO_GRACE_SECONDS * 1000
  undoSecondsLeft.value = UNDO_GRACE_SECONDS
  undoInterval = setInterval(() => {
    const remaining = Math.ceil((undoDeadline - Date.now()) / 1000)
    undoSecondsLeft.value = Math.max(remaining, 0)
    if (undoSecondsLeft.value <= 0) clearUndoTimer()
  }, 200)
}

async function handleUndo() {
  if (!card.value?.scanId) return
  const scanId = card.value.scanId
  clearUndoTimer()
  try {
    const res = await checkinApi.undo(props.gateToken, scanId)
    if (res.ok) {
      continueScanning()
    } else {
      card.value = { ...card.value, undoFailed: true }
    }
  } catch {
    card.value = { ...card.value, undoFailed: true }
  }
}

// -- resume / continue ----------------------------------------------------

function continueScanning() {
  card.value = null
  clearUndoTimer()
  overriding.value = false
  // Reset the debounce so an immediate re-scan of the same code (e.g.
  // right after an undo) isn't swallowed.
  lastCode = null
  lastCodeAt = 0
  resumeScanning()
}

function openSearchFromCard() {
  card.value = null
  clearUndoTimer()
  searchOpen.value = true
  nextTick(() => searchInputEl.value?.focus())
}

// -- name search ------------------------------------------------------------

function toggleSearch() {
  searchOpen.value = !searchOpen.value
  if (searchOpen.value) {
    pauseScanning()
    nextTick(() => searchInputEl.value?.focus())
  } else {
    resumeScanning()
  }
}

async function runSearch(q) {
  searching.value = true
  searchError.value = null
  try {
    const res = await checkinApi.search(props.gateToken, q)
    searchResults.value = res.matches || []
  } catch {
    searchError.value = 'Suche fehlgeschlagen — offline ist die Namenssuche nicht verfügbar.'
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

watch(searchQuery, (q) => {
  clearTimeout(searchDebounceTimer)
  const trimmed = q.trim()
  if (trimmed.length < 2) {
    searchResults.value = []
    searchError.value = null
    return
  }
  searchDebounceTimer = setTimeout(() => runSearch(trimmed), 300)
})

async function checkinFromSearch(match) {
  try {
    const response = await checkinApi.override(props.gateToken, {
      registration_id: match.registration_id,
      person_index: match.person_index,
    })
    searchOpen.value = false
    searchQuery.value = ''
    searchResults.value = []
    renderScanResponse(response)
  } catch (err) {
    searchError.value = isNetworkError(err)
      ? 'Offline — Einchecken per Namenssuche braucht Netzverbindung.'
      : 'Einchecken fehlgeschlagen — bitte erneut versuchen.'
  }
}

// -- lifecycle ----------------------------------------------------------

onMounted(async () => {
  await bootScanner()
  if (bootError.value) return
  await nextTick()
  initCamera()
})

onUnmounted(() => {
  scannerInstance?.destroy()
  scannerInstance = null
  clearUndoTimer()
  clearTimeout(searchDebounceTimer)
})
</script>

<style scoped>
.scanner-page {
  padding: var(--space-3);
  max-width: 480px;
  margin: 0 auto;
}

.boot-state,
.boot-error {
  padding: var(--space-5) var(--space-3);
  text-align: center;
}

.offline-banner {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  font-weight: 500;
}

.scanner-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.scanner-header-text {
  display: flex;
  flex-direction: column;
}

.scanner-header-sub {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.queue-badge {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  border: none;
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  font-weight: 600;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  cursor: pointer;
  width: auto;
  margin: 0;
}

.queue-badge-action {
  text-decoration: underline;
  font-weight: 500;
}

.camera-area {
  position: relative;
  background: #000;
  border-radius: var(--radius-lg);
  overflow: hidden;
  aspect-ratio: 3 / 4;
}

.camera-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.camera-error {
  position: absolute;
  inset: auto var(--space-2) var(--space-2) var(--space-2);
  background: var(--color-danger-bg);
  color: var(--color-danger-text);
  padding: var(--space-2);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  text-align: center;
}

.camera-hint {
  text-align: center;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  margin-top: var(--space-2);
}

.search-section {
  margin-top: var(--space-4);
}

.search-toggle {
  width: 100%;
  min-height: 52px;
  background: var(--color-bg-muted);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: var(--text-lg);
  cursor: pointer;
}

.search-panel {
  margin-top: var(--space-3);
}

.search-input {
  width: 100%;
  min-height: 52px;
  font-size: var(--text-lg);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.search-error {
  color: var(--color-danger-text);
}

.search-empty {
  color: var(--color-text-muted);
}

.search-results {
  list-style: none;
  padding: 0;
  margin: 0;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--color-border);
}

.search-result-row {
  list-style: none; /* Pico puts square markers on the li itself */
  padding: var(--space-3);
  background: var(--color-surface-raised);
  border-bottom: 1px solid var(--color-border);
  cursor: pointer;
  min-height: 56px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  justify-content: center;
}

.search-result-main {
  overflow-wrap: anywhere;
}

.search-result-row:last-child {
  border-bottom: none;
}

.search-result-row:hover,
.search-result-row:active {
  background: var(--color-bg-muted);
}

.search-result-context {
  color: var(--color-text-muted);
  font-weight: 400;
  margin-left: 4px;
}

.search-result-meta {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.status-chip {
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 600;
}

.chip-checked {
  background: var(--color-success-bg);
  color: var(--color-success-text);
}

.chip-open {
  background: var(--color-neutral-bg);
  color: var(--color-neutral-text);
}

/* === Full-screen traffic-light result card === */
.scan-card {
  position: fixed;
  inset: 0;
  z-index: 3000;
  overflow-y: auto;
  padding: var(--space-6) var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  color: #fff;
}

/* Pico sets `color: var(--pico-color)` directly on p/ul/h1 — a direct rule
   beats inheritance, so without this the card text renders Pico-gray on the
   full-colour background instead of white. */
.scan-card h1,
.scan-card p,
.scan-card ul,
.scan-card li {
  color: inherit;
}

.scan-card-green {
  background: #15803d;
}

.scan-card-yellow {
  background: #b45309;
}

.scan-card-red {
  background: #b91c1c;
}

.scan-card-degraded-note {
  background: rgba(0, 0, 0, 0.25);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  margin-bottom: var(--space-3);
}

/* Giant state glyph — the state must read from a metre away in the dark,
   before any text does. */
.scan-card-glyph {
  font-size: 4.5rem;
  line-height: 1;
  font-weight: 700;
  margin: 0;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
}

.scan-card-headline {
  font-size: 1.6rem;
  line-height: 1.25;
  font-weight: 700;
  margin: var(--space-3) 0;
}

.scan-card-name {
  font-size: 1.9rem;
  font-weight: 700;
  margin: var(--space-2) 0 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.scan-card-sub {
  font-size: var(--text-lg);
  opacity: 0.9;
  margin: 4px 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

/* Subtle info line — blends with the card colour (like the slots/group
   boxes); the ✅/⛔ emoji carries the state, no loud fill. */
.scan-card-overnight {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  max-width: 360px;
  font-size: var(--text-lg);
  font-weight: 600;
  margin: var(--space-3) 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: rgba(0, 0, 0, 0.15);
}

.scan-card-slots,
.scan-card-group {
  width: 100%;
  max-width: 360px;
  margin-bottom: var(--space-4);
  background: rgba(0, 0, 0, 0.15);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}

.scan-card-slots-label {
  font-weight: 600;
  margin: 0 0 var(--space-1);
  opacity: 0.85;
}

/* Pico styles `ul li { list-style: square }` directly on the li — a direct
   rule beats inheritance, so `list-style: none` must sit on the rows
   themselves or the markers render outside the padded box. */
.scan-card-list {
  list-style: none;
  padding: 0;
  margin: 0;
  text-align: left;
}

.scan-card-list-row {
  list-style: none;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-1) 0;
  line-height: 1.5;
  min-width: 0;
}

.scan-card-row-state {
  flex-shrink: 0;
  width: 1.2em;
  text-align: center;
  font-weight: 700;
}

.scan-card-row-text {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.scan-card-list-row.is-current {
  font-weight: 700;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.scan-card-undo {
  min-height: 64px;
  width: 100%;
  max-width: 360px;
  font-size: 1.2rem;
  font-weight: 700;
  background: rgba(0, 0, 0, 0.25);
  color: #fff;
  border: 2px solid #fff;
  border-radius: var(--radius-md);
  margin-top: var(--space-2);
  cursor: pointer;
}

.scan-card-undo-failed {
  font-size: var(--text-lg);
  opacity: 0.9;
  margin-top: var(--space-2);
}

.scan-card-override,
.scan-card-search-shortcut {
  min-height: 60px;
  width: 100%;
  max-width: 360px;
  font-size: 1.15rem;
  font-weight: 700;
  background: #fff;
  color: #1a1a1a;
  border: none;
  border-radius: var(--radius-md);
  margin-top: var(--space-4);
  cursor: pointer;
}

.scan-card-inline-error {
  background: rgba(0, 0, 0, 0.2);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  margin-top: var(--space-2);
}

.scan-card-continue {
  min-height: 56px;
  width: 100%;
  max-width: 360px;
  font-size: 1.05rem;
  font-weight: 600;
  background: transparent;
  color: #fff;
  border: 2px solid rgba(255, 255, 255, 0.7);
  border-radius: var(--radius-md);
  margin-top: var(--space-5);
  padding-top: var(--space-2);
  padding-bottom: var(--space-2);
  cursor: pointer;
}
</style>
