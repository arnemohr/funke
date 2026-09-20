<template>
  <article class="photos-admin">
    <PageHeader back back-label="Zurück" :subtitle="eventName">
      <template #title>Eventfotos</template>
    </PageHeader>

    <div v-if="loading" aria-busy="true">Fotosammlung wird geladen ...</div>

    <div v-else-if="loadError" role="alert" class="error">{{ loadError }}</div>

    <template v-else>
      <p v-if="!configured" class="hint-box">
        Noch keine Fotosammlung. Trag ein, an wen sich Gäste wenden können — damit entsteht die
        Sammlung, ihr Link und der QR-Code. Vorher ist nichts erreichbar.
      </p>

      <!-- Konfiguration -->
      <div class="section-heading">
        <h3>Sammlung einrichten</h3>
      </div>
      <section class="surface surface-padded">
        <form @submit.prevent="saveConfig">
          <label for="photoEmail">
            E-Mail für Rückfragen
            <input
              id="photoEmail"
              v-model.trim="form.contact_email"
              type="email"
              placeholder="fotos@schaluppe.de"
              :disabled="saving"
            />
            <small>
              Hier melden sich Gäste, deren Foto wieder raus soll — das ist der Grund, warum ein
              Kontakt Pflicht ist.
            </small>
          </label>

          <label for="photoTelegram">
            Telegram (Alternative zur E-Mail)
            <input
              id="photoTelegram"
              v-model.trim="form.contact_telegram_url"
              type="text"
              placeholder="@fotos oder https://t.me/+Einladungslink"
              :disabled="saving"
            />
            <small>
              Handle oder Einladungslink. Eines von beiden — E-Mail oder Telegram — muss gesetzt
              sein; beides zusammen geht auch.
            </small>
          </label>

          <label for="photoName">
            Name (optional)
            <input
              id="photoName"
              v-model.trim="form.contact_name"
              type="text"
              placeholder="Micha"
              :disabled="saving"
            />
            <small>Steht auf der Seite statt der nackten Adresse.</small>
          </label>

          <label for="photoIntro">
            Eigener Einleitungstext (optional)
            <textarea
              id="photoIntro"
              v-model="form.intro_text"
              rows="3"
              placeholder="Ihr wart dabei? Her mit den Bildern ..."
              :disabled="saving"
            ></textarea>
            <small>
              Ersetzt nur die Begrüßung. Warum die Sammlung erstmal beim Orga-Team bleibt,
              Verschlüsselung, Löschfrist und Kontakt stehen immer darunter — die kann kein eigener
              Text verdrängen.
            </small>
          </label>

          <label for="photoRetention">
            Aufbewahrung in Tagen
            <input
              id="photoRetention"
              v-model="form.retention_days"
              type="number"
              min="7"
              max="365"
              :placeholder="retentionPlaceholder"
              :disabled="saving"
              @input="retentionTouched = true"
            />
            <small>
              7 bis 365 Tage. Leer heißt: der Standardwert der Anlage gilt. Die Sammlung ist eine
              Umschlagstelle, kein Archiv — danach löscht sie sich mit allen Bildern selbst.
              <template v-if="config?.expires_at">
                Aktuell: bis {{ formatDateOnly(config.expires_at) }}.
              </template>
            </small>
          </label>

          <label for="photoCloses">
            Automatisch zumachen am
            <input
              id="photoCloses"
              v-model="form.closes_at"
              type="datetime-local"
              :disabled="saving"
            />
            <small>
              <template v-if="configured">
                Leer heißt: gar nicht automatisch. Der Schalter unten und „Link neu erzeugen"
                bleiben davon unberührt.
              </template>
              <template v-else> Leer lassen — dann setzen wir 21 Tage nach dem Event. </template>
            </small>
          </label>

          <label for="photoOpen" class="switch-label">
            <input
              id="photoOpen"
              v-model="form.upload_open"
              type="checkbox"
              role="switch"
              :disabled="saving"
            />
            Uploads offen
          </label>
          <p class="hint-text">
            Der schnelle Schalter: aus heißt sofort dicht, ohne den gedruckten Link zu entwerten.
          </p>

          <div v-if="saveError" role="alert" class="error">{{ saveError }}</div>

          <button type="submit" :disabled="saving" :aria-busy="saving">
            {{ saving ? 'Wird gespeichert ...' : 'Speichern' }}
          </button>
        </form>
      </section>

      <template v-if="configured">
        <!-- Der Link zum Ausdrucken -->
        <div class="section-heading">
          <h3>Link & QR-Code</h3>
          <span class="status-badge" :class="config.window_open ? 'status-open' : 'status-draft'">
            {{ config.window_open ? 'Upload offen' : 'Upload zu' }}
          </span>
        </div>
        <section class="surface surface-padded">
          <p v-if="!config.window_open" class="closed-note">{{ closedReason }}</p>

          <code class="public-url">{{ config.public_url }}</code>
          <div class="link-actions">
            <button type="button" class="outline" @click="copyLink">Link kopieren</button>
            <a
              role="button"
              class="outline"
              :href="config.public_url"
              target="_blank"
              rel="noopener"
            >
              Seite ansehen
            </a>
          </div>

          <div class="qr-block">
            <canvas ref="qrCanvas" class="qr-canvas"></canvas>
            <p class="hint-text">
              Zum <strong>Ausdrucken oder Beamen</strong> gedacht: ein Zettel am Ausgang, das Bild
              auf der Leinwand am Ende des Abends. Er zeigt auf denselben Link und ist damit genauso
              lange gültig — bis er neu erzeugt wird.
            </p>
          </div>

          <p class="hint-text">
            Die Sammlung löscht sich am
            <strong>{{ formatDateOnly(config.expires_at) }}</strong> vollständig — Bilder, Zeilen,
            Link. Was ihr behalten wollt, holt euch bis dahin über die Downloadliste raus.
          </p>
        </section>

        <!-- Sammlung -->
        <div class="section-heading">
          <h3>Fotos ({{ total }})</h3>
          <button
            type="button"
            class="section-action"
            :disabled="manifestBusy || total === 0"
            :aria-busy="manifestBusy"
            @click="loadManifest"
          >
            Downloadliste
          </button>
        </div>

        <p v-if="pendingCount > 0" class="hint-text">
          {{ pendingCount }} angefangene Uploads sind noch nicht bestätigt. Die tauchen hier nicht
          auf und werden nach 24 Stunden weggeräumt.
        </p>

        <!-- Downloadliste -->
        <section v-if="manifest" class="surface surface-padded manifest-box">
          <p>
            <strong>{{ manifest.urls.length }} Links</strong> in
            <code>{{ manifest.filename }}</code> — die Datei liegt jetzt in deinen Downloads. Die
            Links darin sind <strong>eine Stunde</strong> gültig; danach einfach eine neue Liste
            holen, das kostet nichts.
          </p>
          <p>Im Terminal, im Ordner mit der Datei:</p>
          <pre class="oneliner">{{ manifest.oneliner }}</pre>
          <div class="link-actions">
            <button type="button" class="outline" @click="copyOneliner">Befehl kopieren</button>
            <button type="button" class="outline secondary" @click="manifest = null">
              Ausblenden
            </button>
          </div>
        </section>

        <!-- Filter + Auswahlmodus -->
        <div class="grid-toolbar">
          <div class="filter-tabs" role="group" aria-label="Filter">
            <button
              v-for="tab in FILTER_TABS"
              :key="tab.value"
              type="button"
              class="outline"
              :class="{ 'filter-active': filter === tab.value }"
              :aria-pressed="filter === tab.value"
              @click="setFilter(tab.value)"
            >
              {{ tab.label }}
            </button>
          </div>

          <div class="select-actions">
            <button type="button" class="outline" @click="toggleSelectionMode">
              {{ selectionMode ? 'Auswahl beenden' : 'Auswählen' }}
            </button>
            <template v-if="selectionMode">
              <button type="button" class="outline" :disabled="!photos.length" @click="selectAll">
                Alle sichtbaren
              </button>
              <button
                type="button"
                class="outline btn-danger"
                :disabled="selectedCount === 0 || bulkDeleting"
                :aria-busy="bulkDeleting"
                @click="bulkDelete"
              >
                {{ selectedCount }} löschen
              </button>
            </template>
          </div>
        </div>

        <div v-if="gridError" role="alert" class="error">{{ gridError }}</div>

        <div v-if="gridLoading" aria-busy="true">Fotos werden geladen ...</div>

        <p v-else-if="!photos.length" class="empty-hint">{{ emptyMessage }}</p>

        <template v-else>
          <section v-for="group in dayGroups" :key="group.key" class="day-group">
            <h4 class="day-divider">{{ group.label }}</h4>
            <div class="photo-grid">
              <article
                v-for="photo in group.photos"
                :key="photo.photo_id"
                class="photo-card"
                :class="{ 'photo-card--selected': selected[photo.photo_id] }"
              >
                <button
                  type="button"
                  class="photo-tile"
                  :aria-label="tileLabel(photo)"
                  @click="onTileClick(photo)"
                >
                  <img
                    v-if="photo.thumb_url"
                    :src="photo.thumb_url"
                    alt=""
                    loading="lazy"
                    decoding="async"
                    @error="handleImageError"
                  />
                  <span v-else class="thumb-missing">kein Bild</span>
                </button>

                <span v-if="selectionMode" class="select-mark" :aria-hidden="true">
                  <Check v-if="selected[photo.photo_id]" :size="16" />
                </span>

                <button
                  type="button"
                  class="star-btn"
                  :class="{ 'star-btn--on': photo.starred }"
                  :aria-label="photo.starred ? 'Favorit entfernen' : 'Als Favorit markieren'"
                  :disabled="starringId === photo.photo_id"
                  @click.stop="toggleStar(photo)"
                >
                  <Star :size="16" :fill="photo.starred ? 'currentColor' : 'none'" />
                </button>

                <!-- „Angesehen" is a toggle, „bearbeitet" is a fact. They sit
                     apart because they answer different questions and because a
                     tile that shows both is the normal case. -->
                <button
                  v-if="!selectionMode"
                  type="button"
                  class="check-btn"
                  :class="{ 'check-btn--on': photo.faces_checked }"
                  :aria-label="
                    photo.faces_checked
                      ? 'Als noch nicht angesehen markieren'
                      : 'Als angesehen markieren'
                  "
                  :title="photo.faces_checked ? 'Angesehen' : 'Noch nicht angesehen'"
                  :disabled="checkingId === photo.photo_id"
                  @click.stop="toggleChecked(photo)"
                >
                  <CheckCheck :size="15" aria-hidden="true" />
                </button>

                <span v-if="photo.edited_at" class="edited-mark" title="Unkenntlich gemacht">
                  <EyeOff :size="14" aria-hidden="true" />
                  bearbeitet
                </span>

                <p v-if="photo.uploader_name" class="uploader-name">{{ photo.uploader_name }}</p>
              </article>
            </div>
          </section>

          <button
            v-if="photos.length < total"
            type="button"
            class="outline load-more"
            :disabled="loadingMore"
            :aria-busy="loadingMore"
            @click="loadMore"
          >
            {{ loadingMore ? 'Wird geladen ...' : `Mehr laden (${total - photos.length} übrig)` }}
          </button>
        </template>

        <!-- Notbremse -->
        <div class="section-heading">
          <h3>Notbremse</h3>
        </div>
        <section class="surface surface-padded danger-zone">
          <p class="hint-text">
            <strong>Link neu erzeugen</strong> entwertet jeden gedruckten Zettel und jeden schon
            verschickten Link. Die Fotos in der Sammlung bleiben.
          </p>
          <p class="hint-text">
            <strong>Sammlung löschen</strong> entfernt Konfiguration, alle Fotos und alle
            Bilddateien. Danach kann eine neue Sammlung angelegt werden.
          </p>
          <div class="link-actions">
            <button
              type="button"
              class="outline btn-danger"
              :disabled="rotating"
              :aria-busy="rotating"
              @click="rotateToken"
            >
              Link neu erzeugen
            </button>
            <button
              type="button"
              class="outline btn-danger"
              :disabled="deleting"
              @click="deleteDialogOpen = true"
            >
              Sammlung löschen
            </button>
          </div>
        </section>
      </template>
    </template>

    <!-- Sammlung löschen -->
    <dialog :open="deleteDialogOpen">
      <article style="max-width: 500px">
        <header>
          <button aria-label="Schließen" rel="prev" @click="closeDeleteDialog"></button>
          <h3>Fotosammlung löschen?</h3>
        </header>
        <p class="warning-box">
          Konfiguration, alle {{ total }} Fotos und die Bilddateien werden endgültig entfernt. Der
          Link ist danach tot. Das lässt sich nicht rückgängig machen — hol dir vorher die
          Downloadliste, wenn ihr etwas behalten wollt.
        </p>
        <p v-if="deleting" aria-busy="true">{{ deleteProgress }} Fotos entfernt ...</p>
        <div v-if="deleteError" role="alert" class="error">{{ deleteError }}</div>
        <footer>
          <button type="button" class="secondary" :disabled="deleting" @click="closeDeleteDialog">
            Abbrechen
          </button>
          <button
            type="button"
            class="btn-danger"
            :disabled="deleting"
            :aria-busy="deleting"
            @click="confirmDeleteCollection"
          >
            {{ deleting ? 'Wird gelöscht ...' : 'Endgültig löschen' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- Lightbox -->
    <Teleport to="body">
      <div
        v-if="activePhoto"
        class="lightbox"
        role="dialog"
        aria-modal="true"
        aria-label="Foto groß"
        @click.self="closeLightbox"
      >
        <button type="button" class="lb-close" aria-label="Schließen" @click="closeLightbox">
          <X :size="24" aria-hidden="true" />
        </button>

        <button
          v-if="photos.length > 1"
          type="button"
          class="lb-nav"
          aria-label="Vorheriges Foto"
          @click="step(-1)"
        >
          <ChevronLeft :size="32" aria-hidden="true" />
        </button>

        <figure class="lb-figure">
          <img
            :src="activePhoto.full_url"
            alt=""
            :width="activePhoto.width || null"
            :height="activePhoto.height || null"
            @error="handleImageError"
          />
          <figcaption class="lb-caption">
            <p class="lb-meta">
              {{ formatDate(activePhoto.taken_at) }}
              <template v-if="activePhoto.uploader_name">
                · von {{ activePhoto.uploader_name }}
              </template>
              <template v-if="activePhoto.edited_at"> · bearbeitet</template>
            </p>
            <!-- Der Notizzettel des Uploaders. Absichtlich nur zu lesen: das ist
                 der einzige Satz, den der Gast zu diesem Foto geschrieben hat,
                 und ein Eingabefeld darauf wäre ein Überschreiben. -->
            <p v-if="activePhoto.note" class="lb-note">„{{ activePhoto.note }}"</p>
            <p class="lb-count">{{ activeIndex + 1 }} von {{ photos.length }}</p>
          </figcaption>

          <div class="lb-actions">
            <button
              type="button"
              class="outline"
              :class="{ 'star-btn--on': activePhoto.starred }"
              @click="toggleStar(activePhoto)"
            >
              <Star :size="16" :fill="activePhoto.starred ? 'currentColor' : 'none'" />
              {{ activePhoto.starred ? 'Favorit entfernen' : 'Als Favorit' }}
            </button>
            <!-- A plain link, not a fetch: the presigned URL is signed with
                 `Content-Disposition: attachment`, which every browser honours
                 cross-origin without any CORS rule being involved. `download`
                 is set for the same-origin day that never comes; the header is
                 what does the work. -->
            <a
              v-if="activePhoto.download_url"
              role="button"
              class="outline"
              :href="activePhoto.download_url"
              :download="`foto-${String(activePhoto.photo_id).slice(0, 8)}.jpg`"
            >
              Herunterladen
            </a>
            <!-- Disabled while the uploader's own presigned POST is still valid
                 for these keys: it would overwrite the pixelated version with
                 the original, and `edited_at` would keep claiming otherwise.
                 The backend refuses it with a 409 either way — this is only so
                 nobody draws rectangles for nothing. -->
            <button
              type="button"
              class="outline"
              :disabled="editLocked"
              @click="openEditor(activePhoto)"
            >
              Unkenntlich machen
            </button>
            <!-- Spelled out, not hidden in a tooltip: the disabled button was
                 being read as a bug, which is what a button without a stated
                 reason always is. -->
            <p v-if="editLocked" class="edit-locked-note">
              Gerade erst hochgeladen. Der Upload-Link des Gasts ist noch bis
              <strong>{{ editUnlocksAt }}</strong> gültig und könnte das Original zurückschreiben —
              ab dann geht es.
            </p>
            <button
              type="button"
              class="outline btn-danger"
              :disabled="deletingPhotoId === activePhoto.photo_id"
              @click="deletePhoto(activePhoto)"
            >
              Löschen
            </button>
          </div>
        </figure>

        <button
          v-if="photos.length > 1"
          type="button"
          class="lb-nav"
          aria-label="Nächstes Foto"
          @click="step(1)"
        >
          <ChevronRight :size="32" aria-hidden="true" />
        </button>
      </div>
    </Teleport>

    <PhotoPixelateEditor
      v-if="editingPhoto"
      :photo="editingPhoto"
      :event-id="props.eventId"
      :max-bytes-full="config?.limits?.max_bytes_full || undefined"
      :max-bytes-thumb="config?.limits?.max_bytes_thumb || undefined"
      @saved="onEdited"
      @cancelled="editingPhoto = null"
    />
  </article>
</template>

<script setup>
/**
 * Adminansicht der Eventfotos (Spec 024).
 *
 * The other half of a one-way street: guests write and see nothing, the
 * organisation sees everything, pixelates faces and pulls the collection out.
 * Structurally the twin of `LostFoundAdminPage.vue` — config form on top,
 * collection below, presigned URLs that expire — and the mechanics that page
 * had to get right (refresh before expiry, one refetch per dead grid, the
 * retention field that must not turn „follows the setting" into an override)
 * are reused here rather than re-derived.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import QRCode from 'qrcode'
import { Check, CheckCheck, ChevronLeft, ChevronRight, EyeOff, Star, X } from 'lucide-vue-next'
import { adminApi } from '../../services/api'
import PageHeader from '../../components/PageHeader.vue'
import PhotoPixelateEditor from '../../components/PhotoPixelateEditor.vue'
import {
  berlinToUTCISO,
  formatDate,
  formatDateOnly,
  formatDateTimeLocal,
} from '../../utils/formatters.js'
import { showToast } from '../../composables/useToast.js'

const FILTER_TABS = [
  { value: 'all', label: 'alle' },
  { value: 'starred', label: 'Favoriten' },
  // „ungeprüft" rather than „unbearbeitet": the question while working through
  // a collection is „was habe ich noch nicht angesehen", and most photos need
  // no pixelation at all, so `edited_at` cannot answer it. The API still knows
  // `unedited` for a spot check of where pixelation actually landed.
  { value: 'unchecked', label: 'ungeprüft' },
]

// One screenful and then some. The backend allows up to 500 per call, but a
// „mehr laden" button that pulls 500 thumbnails at once is a spinner, not a
// page.
const PAGE_SIZE = 120
// A refresh has to replace the URLs of everything already loaded, and it does
// that in as few calls as the endpoint allows.
const REFRESH_CHUNK = 500
// A photo whose object is genuinely gone errors again after every refresh, so
// error-driven refreshes are counted as well as spaced.
const MAX_ERROR_REFRESHES = 3
const ERROR_REFRESH_QUIET_MS = 5000

const props = defineProps({
  eventId: { type: String, required: true },
})

const loading = ref(true)
const loadError = ref(null)
const eventName = ref('')

const config = ref(null)
const configured = computed(() => config.value !== null)

const form = reactive({
  contact_email: '',
  contact_telegram_url: '',
  contact_name: '',
  intro_text: '',
  retention_days: '',
  closes_at: '',
  upload_open: true,
})
const retentionPlaceholder = ref('90')
// Whether somebody actually typed in the retention field since the last load.
const retentionTouched = ref(false)

const saving = ref(false)
const saveError = ref(null)
const rotating = ref(false)

const qrCanvas = ref(null)

const photos = ref([])
const total = ref(0)
const pendingCount = ref(0)
const urlTtlSeconds = ref(900)
const filter = ref('all')
const gridLoading = ref(false)
const gridError = ref(null)
const loadingMore = ref(false)

const selectionMode = ref(false)
const selected = reactive({})
const bulkDeleting = ref(false)
const deletingPhotoId = ref(null)
const starringId = ref(null)
const checkingId = ref(null)

const deleteDialogOpen = ref(false)
const deleting = ref(false)
const deleteError = ref(null)
const deleteProgress = ref(0)

const manifest = ref(null)
const manifestBusy = ref(false)

const activeId = ref(null)
const editingPhoto = ref(null)

// When the currently loaded pages were fetched, and how long their presigned
// URLs have left. Declared up here because `loadPhotos` writes it — the refresh
// machinery that reads it lives further down.
const loadedAt = ref(0)
const refreshMs = computed(() => Math.max(60, urlTtlSeconds.value - 60) * 1000)

const selectedCount = computed(() => Object.keys(selected).length)

const emptyMessage = computed(() => {
  if (filter.value === 'starred') return 'Noch keine Favoriten markiert.'
  if (filter.value === 'unchecked') return 'Alle Fotos sind durchgesehen.'
  return 'Noch keine Fotos. Sobald Gäste hochladen, stehen sie hier — sonst nirgends.'
})

/** Why the window is shut, in the order of finality (spec 024 § Sichtbarkeit). */
const closedReason = computed(() => {
  const c = config.value
  if (!c) return ''
  if (!c.upload_open) return 'Der Schalter „Uploads offen" ist aus — der Link führt auf ein „zu".'
  if (c.closes_at && new Date(c.closes_at) <= new Date()) {
    return `Der Upload hat am ${formatDate(c.closes_at)} automatisch zugemacht.`
  }
  return 'Die Aufbewahrungsfrist der Sammlung ist abgelaufen.'
})

/* -------------------------------------------------------------------------
 * Tagesgruppen
 *
 * Grouped and sorted by `taken_at`, which the backend computed from
 * `captured_at_hint` where that is plausible and `uploaded_at` otherwise. That
 * rule is deliberately not reimplemented here: two implementations of
 * „plausibel" are two different orders for the same collection.
 * ---------------------------------------------------------------------- */

const dayKeyFormat = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Europe/Berlin',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})
const dayLabelFormat = new Intl.DateTimeFormat('de-DE', {
  timeZone: 'Europe/Berlin',
  weekday: 'long',
  day: 'numeric',
  month: 'long',
})

const dayGroups = computed(() => {
  const groups = []
  for (const photo of photos.value) {
    const when = new Date(photo.taken_at)
    const key = isNaN(when.getTime()) ? 'unbekannt' : dayKeyFormat.format(when)
    const label = key === 'unbekannt' ? 'Ohne Datum' : dayLabelFormat.format(when)
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.photos.push(photo)
    else groups.push({ key, label, photos: [photo] })
  }
  return groups
})

const activeIndex = computed(() => photos.value.findIndex((p) => p.photo_id === activeId.value))
const activePhoto = computed(() =>
  activeIndex.value === -1 ? null : photos.value[activeIndex.value],
)

/* -------------------------------------------------------------------------
 * Laden
 * ---------------------------------------------------------------------- */

/**
 * One German line per failure mode. A 404 on the config or the list means „no
 * collection yet" and is handled by the caller, so what is left here is the
 * 503 family — no bucket, unreadable photos, objects that refused to go — plus
 * whatever detail the backend sent.
 */
function describeError(err, fallback) {
  if (err?.status === 503) {
    return err.message || 'Der Fotospeicher ist gerade nicht erreichbar — bitte später nochmal.'
  }
  if (err?.status === 404) {
    return err.message || 'Diese Sammlung gibt es nicht (mehr) — bitte lade die Seite neu.'
  }
  return err?.message || fallback
}

function applyForm(payload) {
  form.contact_email = payload.contact_email || ''
  form.contact_telegram_url = payload.contact_telegram_url || ''
  form.contact_name = payload.contact_name || ''
  form.intro_text = payload.intro_text || ''
  form.upload_open = Boolean(payload.upload_open)
  form.closes_at = payload.closes_at ? formatDateTimeLocal(payload.closes_at) : ''
  // `retention_days` in the response is the value *in force*, so a collection
  // that follows the environment default is indistinguishable from one with an
  // override of the same number. Sending it back on every save would silently
  // turn the first into the second, and a later change to
  // EVENT_PHOTO_RETENTION_DAYS would then miss every collection ever saved
  // twice. Hence: placeholder, not value — and only ever sent once somebody
  // typed in the field.
  // The fallback is the response's own `limits.default_retention_days`, not a
  // literal: EVENT_PHOTO_RETENTION_DAYS is configurable per environment, and a
  // copy of its default here would quietly disagree with the backend.
  retentionPlaceholder.value = String(
    payload.retention_days || payload.limits?.default_retention_days || 90,
  )
  form.retention_days = ''
  retentionTouched.value = false
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const [payload, event] = await Promise.all([
      // 404 here means „no collection yet" — not an error, the empty form. The
      // list endpoint answers the same way, so one branch covers both.
      adminApi.eventPhotos.getConfig(props.eventId).catch((err) => {
        if (err.status === 404) return null
        throw err
      }),
      // Only for the header — a missing event name is not worth failing over.
      adminApi.getEvent(props.eventId).catch(() => null),
    ])
    eventName.value = event?.name || ''
    config.value = payload
    if (payload) {
      applyForm(payload)
      urlTtlSeconds.value = Number(payload.limits?.url_ttl_seconds) || 900
      await loadPhotos({ reset: true })
    }
  } catch (err) {
    loadError.value = describeError(err, 'Fotosammlung konnte nicht geladen werden')
  } finally {
    loading.value = false
  }
}

/**
 * Fetch one page of photos.
 * @param {object} [options]
 * @param {boolean} [options.reset] - Start over at offset 0 (filter change, first load)
 * @param {boolean} [options.silent] - No spinner: a refresh nobody asked for
 */
async function loadPhotos({ reset = false, silent = false } = {}) {
  if (reset) {
    photos.value = []
    clearSelection()
  }
  const offset = photos.value.length
  if (!silent) {
    if (offset === 0) gridLoading.value = true
    else loadingMore.value = true
  }
  gridError.value = null

  try {
    const payload = await adminApi.eventPhotos.listPhotos(props.eventId, {
      filter: filter.value,
      offset,
      limit: PAGE_SIZE,
    })
    photos.value = offset === 0 ? payload.photos : [...photos.value, ...payload.photos]
    total.value = payload.total
    pendingCount.value = payload.pending_count
    urlTtlSeconds.value = Number(payload.url_ttl_seconds) || urlTtlSeconds.value
    loadedAt.value = Date.now()
    scheduleRefresh()
  } catch (err) {
    if (err.status === 404) {
      // The collection was deleted under us — from another tab, or by the
      // anonymisation of the event.
      config.value = null
      photos.value = []
      total.value = 0
      return
    }
    gridError.value = describeError(err, 'Fotos konnten nicht geladen werden')
  } finally {
    gridLoading.value = false
    loadingMore.value = false
  }
}

function loadMore() {
  loadPhotos()
}

function setFilter(value) {
  if (filter.value === value) return
  filter.value = value
  manifest.value = null
  loadPhotos({ reset: true })
}

/* -------------------------------------------------------------------------
 * Nachladen kurz vor Ablauf
 *
 * Every thumb_url and full_url is a presigned GET that dies after
 * `url_ttl_seconds`. A tab left open on the grid would show a wall of broken
 * frames, so the loaded pages are refetched a minute before the URLs expire —
 * only while the tab is visible, because a background tab has nobody looking
 * at it. Same mechanism as `LostFoundPage.vue`, for the same reason.
 * ---------------------------------------------------------------------- */

let refreshTimer = null
let errorRefreshes = 0
let refreshing = false

function clearRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function scheduleRefresh() {
  clearRefresh()
  if (document.visibilityState !== 'visible') return
  refreshTimer = setTimeout(refreshUrls, refreshMs.value)
}

/**
 * Replace the URLs of everything currently loaded, in as few calls as the
 * endpoint allows. Positions can shift if somebody deleted a photo elsewhere
 * in the meantime — that is a redraw, not a defect, and the next tick is
 * consistent again.
 */
async function refreshUrls() {
  clearRefresh()
  if (refreshing || !configured.value) return
  const wanted = photos.value.length
  if (wanted === 0) return

  refreshing = true
  try {
    const fresh = []
    while (fresh.length < wanted) {
      const payload = await adminApi.eventPhotos.listPhotos(props.eventId, {
        filter: filter.value,
        offset: fresh.length,
        limit: Math.min(REFRESH_CHUNK, wanted - fresh.length),
      })
      total.value = payload.total
      pendingCount.value = payload.pending_count
      fresh.push(...payload.photos)
      // Fewer rows than asked for means we have reached the end of a collection
      // that shrank; anything else would loop forever.
      if (payload.photos.length === 0) break
    }
    photos.value = fresh
    loadedAt.value = Date.now()
  } catch {
    // A hiccup leaves the stale grid standing; the timer or an image error
    // tries again.
  } finally {
    refreshing = false
    scheduleRefresh()
  }
}

function handleVisibilityChange() {
  if (document.visibilityState !== 'visible') {
    clearRefresh()
    return
  }
  if (!configured.value) return
  if (Date.now() - loadedAt.value >= refreshMs.value) refreshUrls()
  else scheduleRefresh()
}

/** One refetch for a whole grid of dead URLs, not one per image. */
function handleImageError() {
  if (refreshing || errorRefreshes >= MAX_ERROR_REFRESHES) return
  if (Date.now() - loadedAt.value < ERROR_REFRESH_QUIET_MS) return
  errorRefreshes += 1
  refreshUrls()
}

/* -------------------------------------------------------------------------
 * Konfiguration speichern
 * ---------------------------------------------------------------------- */

async function saveConfig() {
  // The backend refuses this too (400 `contact_required`), but a page whose
  // whole purpose is „if a photo of you must go, write to this person" should
  // not need a round trip to say that nobody has been named.
  if (!form.contact_email && !form.contact_telegram_url) {
    saveError.value =
      'Bitte gib an, wie sich Gäste melden können — eine E-Mail-Adresse oder einen ' +
      'Telegram-Link.'
    return
  }

  saving.value = true
  saveError.value = null
  try {
    const body = {
      // Empty means „no such contact" — null clears it, which the backend
      // refuses when it would leave the collection with no contact at all.
      contact_email: form.contact_email || null,
      contact_telegram_url: form.contact_telegram_url || null,
      contact_name: form.contact_name || null,
      intro_text: form.intro_text || null,
      upload_open: form.upload_open,
    }
    // The backend patches on `exclude_unset`, so an omitted key is „leave it
    // alone" and an explicit null is a decision. On the first save an empty
    // field must therefore stay omitted, so `closes_at` gets its default of
    // event end + 21 days; later on, an emptied field is the organiser saying
    // „nicht automatisch zumachen", which is a null.
    if (form.closes_at) body.closes_at = berlinToUTCISO(form.closes_at)
    else if (configured.value) body.closes_at = null

    if (retentionTouched.value) {
      body.retention_days = form.retention_days === '' ? null : Number(form.retention_days)
    }

    const payload = await adminApi.eventPhotos.saveConfig(props.eventId, body)
    const isFirstSave = !configured.value
    config.value = payload
    applyForm(payload)
    showToast(isFirstSave ? 'Sammlung angelegt — der Link steht' : 'Gespeichert', 'success')
    if (isFirstSave) await loadPhotos({ reset: true })
  } catch (err) {
    saveError.value = describeError(err, 'Speichern fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

function copyLink() {
  const url = config.value?.public_url || ''
  navigator.clipboard.writeText(url).then(
    () => showToast('Link kopiert!', 'success'),
    () => prompt('Kopiere diesen Link:', url),
  )
}

async function rotateToken() {
  const ok = window.confirm(
    'Neuen Link erzeugen? Jeder gedruckte Zettel, jeder QR-Code und jeder schon verschickte ' +
      'Link funktioniert danach nicht mehr — du musst den neuen Link neu verteilen. Die Fotos ' +
      'in der Sammlung bleiben.',
  )
  if (!ok) return
  rotating.value = true
  try {
    config.value = await adminApi.eventPhotos.rotateToken(props.eventId)
    showToast('Neuer Link erzeugt — der alte ist tot', 'success')
  } catch (err) {
    showToast(describeError(err, 'Link konnte nicht erneuert werden'), 'error')
  } finally {
    rotating.value = false
  }
}

/**
 * The QR code is the point of the whole link: it goes on a printed sheet at the
 * exit and on the screen at the end of the night. `public_url` comes assembled
 * from the backend and is encoded verbatim — rebuilding it here is how the
 * printed sheet and the server drift apart.
 */
async function renderQr() {
  await nextTick()
  const url = config.value?.public_url
  if (!qrCanvas.value || !url) return
  try {
    await QRCode.toCanvas(qrCanvas.value, url, { width: 240, margin: 2 })
  } catch {
    // Non-critical: the canvas stays blank and the link above it still works.
  }
}

watch(() => config.value?.public_url, renderQr)

/* -------------------------------------------------------------------------
 * Kacheln: Stern, Auswahl, Löschen
 * ---------------------------------------------------------------------- */

function tileLabel(photo) {
  if (selectionMode.value) return 'Foto auswählen'
  return photo.uploader_name ? `Foto von ${photo.uploader_name} groß ansehen` : 'Foto groß ansehen'
}

function onTileClick(photo) {
  if (selectionMode.value) toggleSelected(photo)
  else activeId.value = photo.photo_id
}

function replacePhoto(updated) {
  photos.value = photos.value.map((p) => (p.photo_id === updated.photo_id ? updated : p))
}

async function toggleChecked(photo) {
  checkingId.value = photo.photo_id
  try {
    const updated = await adminApi.eventPhotos.patchPhoto(props.eventId, photo.photo_id, {
      faces_checked: !photo.faces_checked,
    })
    replacePhoto(updated)
    // „ungeprüft" is a server-side filter, so a photo just ticked off does not
    // belong in this list any more — same bookkeeping as the star.
    if (filter.value === 'unchecked' && updated.faces_checked) {
      stepAwayFrom(updated.photo_id)
      photos.value = photos.value.filter((p) => p.photo_id !== updated.photo_id)
      total.value = Math.max(0, total.value - 1)
    }
  } catch (err) {
    showToast(describeError(err, 'Der Haken konnte nicht gesetzt werden'), 'error')
  } finally {
    checkingId.value = null
  }
}

async function toggleStar(photo) {
  starringId.value = photo.photo_id
  try {
    // Only `starred` is sent: an absent `note` is „leave it alone", so a star
    // toggle can never wipe what the uploader wrote.
    const updated = await adminApi.eventPhotos.patchPhoto(props.eventId, photo.photo_id, {
      starred: !photo.starred,
    })
    // The presigned URLs are not part of a PATCH response's job, but they are
    // in it — so a straight replace keeps the tile showing an image.
    replacePhoto(updated)
    // „Favoriten" is a server-side filter: an unstarred photo does not belong
    // in this list any more, and leaving it there means the next „mehr laden"
    // pages against a different total.
    if (filter.value === 'starred' && !updated.starred) {
      photos.value = photos.value.filter((p) => p.photo_id !== updated.photo_id)
      total.value = Math.max(0, total.value - 1)
      if (activeId.value === updated.photo_id) closeLightbox()
    }
  } catch (err) {
    showToast(describeError(err, 'Der Stern konnte nicht gesetzt werden'), 'error')
  } finally {
    starringId.value = null
  }
}

function toggleSelectionMode() {
  selectionMode.value = !selectionMode.value
  if (!selectionMode.value) clearSelection()
}

function clearSelection() {
  for (const key of Object.keys(selected)) delete selected[key]
}

function toggleSelected(photo) {
  if (selected[photo.photo_id]) delete selected[photo.photo_id]
  else selected[photo.photo_id] = true
}

function selectAll() {
  for (const photo of photos.value) selected[photo.photo_id] = true
}

async function bulkDelete() {
  const ids = Object.keys(selected)
  if (ids.length === 0) return
  const ok = window.confirm(
    `${ids.length} ${ids.length === 1 ? 'Foto' : 'Fotos'} endgültig löschen? ` +
      'Die Bilddateien werden mit entfernt und sind danach weg.',
  )
  if (!ok) return

  bulkDeleting.value = true
  try {
    const result = await adminApi.eventPhotos.bulkDelete(props.eventId, ids)
    const gone = new Set(ids)
    photos.value = photos.value.filter((p) => !gone.has(p.photo_id))
    total.value = Math.max(0, total.value - result.deleted)
    clearSelection()
    if (activeId.value && gone.has(activeId.value)) closeLightbox()
    showToast(`${result.deleted} Fotos gelöscht`, 'success')
  } catch (err) {
    showToast(describeError(err, 'Löschen fehlgeschlagen'), 'error')
    // Whatever survived is still in the collection; a fresh page is the honest
    // state after a partial delete.
    await loadPhotos({ reset: true })
  } finally {
    bulkDeleting.value = false
  }
}

async function deletePhoto(photo) {
  const ok = window.confirm('Dieses Foto endgültig löschen? Die Bilddatei geht mit.')
  if (!ok) return
  deletingPhotoId.value = photo.photo_id
  try {
    await adminApi.eventPhotos.deletePhoto(props.eventId, photo.photo_id)
    stepAwayFrom(photo.photo_id)
    photos.value = photos.value.filter((p) => p.photo_id !== photo.photo_id)
    total.value = Math.max(0, total.value - 1)
    delete selected[photo.photo_id]
    showToast('Foto gelöscht', 'success')
  } catch (err) {
    showToast(describeError(err, 'Foto konnte nicht gelöscht werden'), 'error')
  } finally {
    deletingPhotoId.value = null
  }
}

function closeDeleteDialog() {
  if (deleting.value) return
  deleteDialogOpen.value = false
  deleteError.value = null
  deleteProgress.value = 0
}

async function confirmDeleteCollection() {
  deleting.value = true
  deleteError.value = null
  deleteProgress.value = 0
  try {
    const result = await adminApi.eventPhotos.deleteCollection(props.eventId, {
      onProgress: ({ photos: done }) => {
        deleteProgress.value = done
      },
    })
    deleteDialogOpen.value = false
    showToast(`Sammlung gelöscht — ${result.photos} Fotos entfernt`, 'success')
    await load()
  } catch (err) {
    deleteError.value = describeError(err, 'Löschen fehlgeschlagen')
  } finally {
    deleting.value = false
  }
}

/* -------------------------------------------------------------------------
 * Lightbox
 * ---------------------------------------------------------------------- */

function closeLightbox() {
  activeId.value = null
  // The refresh timer stood still while a photo was open (see refreshTick
  // reasoning in LostFoundPage): catch up if the URLs are due.
  if (configured.value && Date.now() - loadedAt.value >= refreshMs.value) refreshUrls()
}

function step(delta) {
  const count = photos.value.length
  if (!count || activeIndex.value === -1) return
  const next = (activeIndex.value + delta + count) % count
  activeId.value = photos.value[next].photo_id
}

/** Move the lightbox off a photo that is about to disappear from the list. */
function stepAwayFrom(photoId) {
  if (activeId.value !== photoId) return
  if (photos.value.length <= 1) {
    activeId.value = null
    return
  }
  step(1)
}

function onKeydown(event) {
  if (!activePhoto.value || editingPhoto.value) return
  if (event.key === 'Escape') closeLightbox()
  else if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
  else return
  event.preventDefault()
}

/* -------------------------------------------------------------------------
 * Unkenntlich machen
 * ---------------------------------------------------------------------- */

/**
 * While the uploader's own upload permission is still live, „Unkenntlich
 * machen" is held back.
 *
 * A presigned POST is not single-use and is signed for exactly the two keys the
 * edit writes, so pixelating inside that window can be undone by whoever still
 * holds the guest's form — and `edited_at` would go on claiming otherwise. The
 * backend refuses it with a 409 regardless; this is so nobody draws rectangles
 * for nothing.
 *
 * Two things this has to get right, and the first version got neither:
 *
 * - **It must say so where it can be read.** A greyed-out button whose reason
 *   lives in a `title` is a broken button on every touch device, and it was
 *   read as exactly that.
 * - **It must let go by itself.** `Date.now()` in a plain function is not a
 *   reactive dependency, so nothing re-rendered when the window passed and the
 *   button stayed dead until some unrelated state changed. Hence a stored
 *   deadline plus one `setTimeout` that fires exactly when it expires — one
 *   re-render, not a per-second tick through a grid of several hundred tiles.
 */
function lockedUntil(photo) {
  if (!photo?.uploaded_at) return 0
  const minted = new Date(photo.uploaded_at).getTime()
  if (Number.isNaN(minted)) return 0
  const until = minted + urlTtlSeconds.value * 1000
  return until > Date.now() ? until : 0
}

const editLockUntil = ref(0)
let unlockHandle = 0

const editLocked = computed(() => editLockUntil.value > 0)
const editUnlocksAt = computed(() =>
  editLockUntil.value
    ? new Date(editLockUntil.value).toLocaleTimeString('de-DE', {
        hour: '2-digit',
        minute: '2-digit',
      })
    : '',
)

watch(
  activePhoto,
  (photo) => {
    clearTimeout(unlockHandle)
    unlockHandle = 0
    editLockUntil.value = lockedUntil(photo)
    if (editLockUntil.value) {
      unlockHandle = setTimeout(() => {
        editLockUntil.value = 0
      }, editLockUntil.value - Date.now())
    }
  },
  { immediate: true },
)

function openEditor(photo) {
  editingPhoto.value = photo
}

function onEdited(updated) {
  editingPhoto.value = null
  replacePhoto(updated)
  // The keys did not change, so both presigned URLs still point at the objects
  // that were just overwritten — and the browser has the old bytes cached under
  // exactly that URL. A refresh mints new signatures, which are new URLs and
  // therefore a real reload.
  refreshUrls()
  showToast('Bild ersetzt — die Gesichter sind raus', 'success')
  // Pixelating implies a look, and the backend sets `faces_checked` with the
  // same write — so this photo has left both working lists.
  if (filter.value === 'unedited' || filter.value === 'unchecked') {
    stepAwayFrom(updated.photo_id)
    photos.value = photos.value.filter((p) => p.photo_id !== updated.photo_id)
    total.value = Math.max(0, total.value - 1)
  }
}

/* -------------------------------------------------------------------------
 * Downloadliste
 * ---------------------------------------------------------------------- */

async function loadManifest() {
  manifestBusy.value = true
  try {
    // The manifest knows two filters, the grid three: „unbearbeitet" is a
    // working view, not a selection worth exporting, so it falls back to the
    // whole collection.
    const scope = filter.value === 'starred' ? 'starred' : 'all'
    manifest.value = await adminApi.eventPhotos.downloadManifest(props.eventId, scope)
    showToast('Downloadliste gespeichert', 'success')
  } catch (err) {
    showToast(describeError(err, 'Downloadliste konnte nicht geholt werden'), 'error')
  } finally {
    manifestBusy.value = false
  }
}

function copyOneliner() {
  const text = manifest.value?.oneliner || ''
  navigator.clipboard.writeText(text).then(
    () => showToast('Befehl kopiert!', 'success'),
    () => prompt('Kopiere diesen Befehl:', text),
  )
}

/* -------------------------------------------------------------------------
 * Lifecycle
 * ---------------------------------------------------------------------- */

watch(activePhoto, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('keydown', onKeydown)
  load()
})

onBeforeUnmount(() => {
  clearTimeout(unlockHandle)
  clearRefresh()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<style scoped>
.error {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
}

.hint-box {
  background: var(--color-info-subtle-bg);
  color: var(--color-info-subtle-text);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
}

.hint-text {
  font-size: 0.875rem;
  color: var(--color-text-muted);
  margin-bottom: var(--space-2);
}

.switch-label {
  margin-bottom: 0.25rem;
}

.closed-note {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  margin-bottom: var(--space-3);
}

.public-url {
  display: block;
  word-break: break-all;
  margin-bottom: var(--space-3);
}

.link-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: var(--space-3);
}

.link-actions button,
.link-actions a[role='button'] {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.qr-block {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--space-4);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-3);
}

/* White backing regardless of theme: a QR code inverted by dark mode is a code
   no scanner reads, and this one gets photographed off a screen. */
.qr-canvas {
  background: #fff;
  padding: var(--space-2);
  border-radius: var(--radius-md);
  flex: 0 0 auto;
}

.qr-block .hint-text {
  flex: 1 1 16rem;
  margin: 0;
}

.manifest-box code {
  word-break: break-all;
}

.oneliner {
  overflow-x: auto;
  padding: var(--space-3);
  background: var(--color-surface-sunken);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  margin-bottom: var(--space-3);
}

.grid-toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.filter-tabs,
.select-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.filter-tabs button,
.select-actions button {
  width: auto;
  margin: 0;
  min-height: 40px;
  padding: 0.3rem 0.7rem;
  font-size: var(--text-base);
}

.filter-active {
  background: var(--color-brand-subtle);
  font-weight: 700;
}

.empty-hint {
  padding: var(--space-5) var(--space-4);
  text-align: center;
  color: var(--color-text-muted);
  background: var(--color-bg-muted);
  border-radius: var(--radius-lg);
}

.day-group {
  margin-bottom: var(--space-4);
}

.day-divider {
  font-size: var(--text-lg);
  margin: 0 0 var(--space-2);
  padding-bottom: var(--space-1);
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text-muted);
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: var(--space-2);
}

.photo-card {
  position: relative;
  margin: 0;
  padding: 0;
}

.photo-card--selected {
  outline: 3px solid var(--color-accent);
  outline-offset: 2px;
  border-radius: var(--radius-md);
}

.photo-tile {
  display: block;
  width: 100%;
  padding: 0;
  margin: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--color-surface-sunken);
  cursor: zoom-in;
}

.photo-tile img {
  display: block;
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: cover;
}

.thumb-missing {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1 / 1;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* The badges sit on the photo, so their colours are fixed rather than themed —
   they have to stay readable over a dark tent and a white shirt alike. */
.select-mark {
  position: absolute;
  top: var(--space-1);
  left: var(--space-1);
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-pill);
  background: rgba(12, 30, 60, 0.88);
  color: #fff;
  pointer-events: none;
}

/* Same affordance as the star, one notch quieter: the star is a judgement, the
   check is bookkeeping. Green when set, because that is the colour people read
   as „done" without a label. */
.check-btn {
  position: absolute;
  top: 0.35rem;
  left: 0.35rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  min-height: 30px;
  padding: 0;
  margin: 0;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.45);
  color: rgba(255, 255, 255, 0.75);
  cursor: pointer;
}

.check-btn--on {
  background: rgba(30, 122, 62, 0.9);
  color: #fff;
}

.edit-locked-note {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.star-btn {
  position: absolute;
  top: var(--space-1);
  right: var(--space-1);
  width: 32px;
  height: 32px;
  min-height: 32px;
  margin: 0;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-pill);
  background: rgba(12, 30, 60, 0.7);
  color: #fff;
}

.star-btn--on {
  color: #ffc94d;
}

.edited-mark {
  position: absolute;
  bottom: 2.1rem;
  left: var(--space-1);
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.05rem 0.35rem;
  border-radius: var(--radius-sm);
  background: rgba(12, 30, 60, 0.82);
  color: #fff;
  font-size: var(--text-xs);
}

.uploader-name {
  margin: 0.2rem 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.load-more {
  width: auto;
  min-height: 44px;
  margin-bottom: var(--space-4);
}

.danger-zone {
  border-color: var(--color-danger-text);
}

.warning-box {
  background: var(--color-warning-bg);
  padding: 0.75rem;
  border-radius: var(--pico-border-radius);
  color: var(--color-warning-text);
  font-size: 0.9em;
}

/* Teleported to <body>, but still rendered by this component — scoped styles
   reach it. */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
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
  max-height: 62vh;
  width: auto;
  height: auto;
  object-fit: contain;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.06);
}

@media (orientation: landscape) and (max-height: 520px) {
  .lb-figure img {
    max-height: 46vh;
  }
}

.lb-caption {
  text-align: center;
  color: #fff;
  padding: 0 var(--space-2);
}

.lb-meta {
  margin: 0;
  font-size: var(--text-base);
  color: rgba(255, 255, 255, 0.82);
}

.lb-note {
  margin: var(--space-2) 0 0;
  font-size: var(--text-lg);
  color: #fff;
}

.lb-count {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: rgba(255, 255, 255, 0.6);
}

.lb-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.4rem;
  padding: 0 var(--space-2);
}

/* „Herunterladen" is an <a role="button"> rather than a <button>, because the
   presigned URL's `attachment` disposition is what saves the file — so the
   selector has to cover both or that one control loses its styling. */
.lb-actions button,
.lb-actions a[role='button'] {
  width: auto;
  margin: 0;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.35);
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
