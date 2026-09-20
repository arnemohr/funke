<template>
  <article class="event-detail-page">
    <PageHeader back="/admin/events" back-label="Events">
      <template #title>
        <span v-if="event">{{ event.name }}</span>
        <span v-else-if="loading" class="skeleton skeleton-title" />
      </template>
      <template #chip>
        <span
          v-if="event"
          :class="['status-badge', `status-${event.status.toLowerCase()}`]"
        >
          {{ formatEventStatus(event.status) }}
        </span>
      </template>
      <template #actions>
        <IconButton
          :icon="HelpCircle"
          label="Hilfe"
          @click="help.toggle(activeHelpKey)"
        />
      </template>
    </PageHeader>

    <HelpPanel
      :help-key="help.helpKey.value"
      :open="help.isOpen.value"
      ref="helpPanelRef"
      @close="help.close()"
    />

    <!-- Spec 022: explains why every name on this page is a pseudonym. -->
    <p v-if="isAnonymized" role="status" class="anonymized-notice">
      <small>
        Personendaten anonymisiert am {{ formatDate(event.anonymized_at) }} —
        Namen und Adressen wurden entfernt, Zahlen und Auswertungen bleiben
        erhalten. E-Mails können nicht mehr verschickt werden.
      </small>
    </p>

    <!-- Spec 025: the only nag before a trip. Deliberately no second chip in
         the header slot — that slot renders a single badge, and two of them
         make the status ambiguous. -->
    <p v-if="charterHandoverDue" role="status" class="charter-notice">
      <small>
        Chartervertrag ist noch nicht unterschrieben — Übergabe am
        {{ charterHandoverLabel }}.
      </small>
    </p>

    <!-- Skeleton while loading -->
    <div v-if="loading" class="skeleton-container" aria-busy="true" aria-label="Veranstaltung wird geladen">
      <div class="skeleton skeleton-tab-row" />
      <div class="skeleton-card">
        <div class="skeleton skeleton-row" />
        <div class="skeleton skeleton-row short" />
        <div class="skeleton skeleton-row" />
        <div class="skeleton skeleton-row short" />
      </div>
    </div>

    <div v-else-if="loadError" role="alert" class="error-message">
      {{ loadError }}
    </div>

    <template v-else-if="event">
      <!-- Tabs -->
      <nav class="tab-nav" aria-label="Tabs">
        <ul class="tab-list">
          <li>
            <a
              href="#"
              :class="{ active: activeTab === 'details' }"
              :aria-current="activeTab === 'details' ? 'page' : undefined"
              @click.prevent="activeTab = 'details'"
            >
              Details
            </a>
          </li>
          <li>
            <a
              href="#"
              :class="{ active: activeTab === 'registrations' }"
              :aria-current="activeTab === 'registrations' ? 'page' : undefined"
              @click.prevent="activeTab = 'registrations'"
            >
              Anmeldungen
              <span v-if="registrations.length" class="tab-badge">{{ registrations.length }}</span>
            </a>
          </li>
          <li>
            <a
              href="#"
              :class="{ active: activeTab === 'messages' }"
              :aria-current="activeTab === 'messages' ? 'page' : undefined"
              @click.prevent="activeTab = 'messages'"
            >
              Nachrichten
            </a>
          </li>
        </ul>
      </nav>

      <!-- Details tab -->
      <div v-show="activeTab === 'details'" class="tab-content">
        <!-- Informationen surface -->
        <div class="section-heading">
          <h3>Informationen</h3>
          <button
            type="button"
            class="section-action"
            @click="actions.goToEdit(event)"
          >
            Bearbeiten
          </button>
        </div>

        <section class="surface surface-padded">
          <dl class="event-info">
            <dt>Datum</dt>
            <dd>{{ formatDate(event.start_at) }}</dd>

            <dt>Ort</dt>
            <dd>{{ event.location || 'Kein Ort angegeben' }}</dd>

            <dt>Kapazität</dt>
            <dd>{{ participatingSpots }} / {{ event.capacity }} bestätigt, {{ pendingSpots }} ausstehend</dd>

            <dt>Warteliste</dt>
            <dd>{{ event.waitlist_spots || 0 }} Personen ({{ event.waitlist_count || 0 }} Buchungen)</dd>

            <dt>Bevorzugt</dt>
            <dd>{{ event.promoted_count || 0 }} Anmeldungen ({{ event.promoted_spots || 0 }} Plätze)</dd>

            <dt>Erinnerungen</dt>
            <dd>{{ event.reminder_schedule_days?.join(', ') || 'Keine' }} Tage vorher</dd>

            <dt v-if="event.description">Beschreibung</dt>
            <dd v-if="event.description" class="event-description">{{ event.description }}</dd>
          </dl>
        </section>

        <!-- Fahrbericht (spec 014) -->
        <div class="section-heading">
          <h3>Fahrbericht</h3>
        </div>
        <div class="list-group actions-list">
          <template v-if="!fahrbericht">
            <ListItemButton :icon="ClipboardList" chevron @click="startFahrbericht">
              Fahrbericht starten
              <template #detail>
                <span>Crew, Kiosk, Schiff &amp; Kassenabschluss erfassen</span>
              </template>
            </ListItemButton>
          </template>
          <template v-else-if="fahrbericht.status === 'DRAFT'">
            <ListItemButton :icon="ClipboardList" chevron @click="openFahrbericht">
              Fahrbericht bearbeiten
              <template #trailing>
                <span class="fb-chip fb-chip--draft">Entwurf</span>
              </template>
            </ListItemButton>
          </template>
          <template v-else>
            <ListItemButton :icon="ClipboardList" chevron @click="openFahrbericht">
              Fahrbericht ansehen
              <template #trailing>
                <span class="fb-chip fb-chip--sent">Eingereicht v{{ fahrbericht.version }}</span>
              </template>
            </ListItemButton>
            <ListItemButton v-if="report" :icon="FileDown" @click="openPdf">
              PDF öffnen
            </ListItemButton>
            <ListItemButton v-if="report" :icon="Mail" @click="resendReport">
              Bericht erneut senden
              <template v-if="report.email_status" #trailing>
                <span class="fb-chip" :class="emailStatusClass">{{ emailStatusLabel }}</span>
              </template>
            </ListItemButton>
          </template>
        </div>

        <!-- Chartervertrag (spec 025) — SINGLE only; the backend rejects a
             contract on a FESTIVAL with 409 charter_nur_fuer_einzelfahrten. -->
        <template v-if="showCharterSection">
          <div class="section-heading">
            <h3>Chartervertrag</h3>
          </div>
          <div class="list-group actions-list">
            <ListItemButton
              :icon="FileSignature"
              chevron
              @click="goToCharterContract"
            >
              {{ charterEntryLabel }}
              <template #detail>
                <span>Charterer, Zeitraum, Gebühren — als PDF zum Unterschreiben</span>
              </template>
              <template v-if="charterChip" #trailing>
                <span class="fb-chip" :class="charterChip.class">{{ charterChip.label }}</span>
              </template>
            </ListItemButton>
          </div>
        </template>

        <!-- Actions group -->
        <div class="list-group actions-list">
          <ListItemButton
            :icon="Link2"
            @click="handleCopyLink"
          >
            Link kopieren
            <template v-if="linkCopied" #trailing>
              <Check :size="18" class="success-check" aria-hidden="true" />
            </template>
          </ListItemButton>
          <ListItemButton
            :icon="Send"
            @click="handleCopyInvite"
          >
            Einladungstext
            <template v-if="inviteCopied" #trailing>
              <Check :size="18" class="success-check" aria-hidden="true" />
            </template>
          </ListItemButton>
          <ListItemButton
            :icon="Copy"
            @click="actions.showCloneModal(event)"
            chevron
          >
            Duplizieren
          </ListItemButton>
          <ListItemButton
            :icon="FileDown"
            @click="actions.handleExportPdf()"
          >
            Boardingzettel PDF
          </ListItemButton>
          <ListItemButton
            :icon="PackageSearch"
            chevron
            @click="goToLostFound"
          >
            Fundsachen
            <template #detail>
              <span>Fotos der liegengebliebenen Sachen als öffentliche Seite</span>
            </template>
          </ListItemButton>
          <ListItemButton
            :icon="Images"
            chevron
            @click="goToEventPhotos"
          >
            Fotos
            <template #detail>
              <span>Gäste laden ihre Fotos hoch — sehen aber keine</span>
            </template>
          </ListItemButton>
          <ListItemButton
            :icon="MoreHorizontal"
            chevron
            @click="dangerSheetOpen = true"
          >
            Mehr
          </ListItemButton>
        </div>
      </div>

      <!-- Registrations tab -->
      <div v-show="activeTab === 'registrations'" class="tab-content">
        <RegistrationTable
          :registrations="registrations"
          :event-id="props.eventId"
          :event-status="event.status"
          :loading="loadingRegistrations"
          :error="registrationsError"
          :toggling-id="actions.togglingPromotedId.value"
          @toggle-promoted="actions.handleTogglePromoted"
          @promote-waitlisted="actions.handlePromoteWaitlisted"
          @delete-registration="actions.handleDeleteRegistration"
        />
      </div>

      <!-- Messages tab -->
      <div v-show="activeTab === 'messages'" class="tab-content">
        <div class="messages-tab-header">
          <!-- Anonymised events have no addresses left; the backend 409s. -->
          <button :disabled="isAnonymized" @click="actions.showMessageComposer.value = true">
            Nachricht senden
          </button>
        </div>
        <MessageLog mode="inline" :event-id="props.eventId" />
      </div>

      <!-- Sticky primary CTA -->
      <div v-if="primaryCta" class="sticky-cta">
        <button
          :disabled="primaryCta.busy"
          :aria-busy="primaryCta.busy"
          @click="primaryCta.run"
        >
          {{ primaryCta.busy ? primaryCta.busyLabel : primaryCta.label }}
        </button>
      </div>
    </template>

    <!-- Danger zone action sheet -->
    <ActionSheet
      v-if="event"
      :open="dangerSheetOpen"
      title="Weitere Aktionen"
      @close="dangerSheetOpen = false"
    >
      <div class="sheet-list">
        <ListItemButton
          v-if="event.status === 'REGISTRATION_CLOSED'"
          :icon="RotateCcw"
          :disabled="actions.reopeningRegistration.value"
          @click="() => { dangerSheetOpen = false; actions.reopenRegistration(event) }"
        >
          Anmeldung wieder öffnen
          <template #detail>Zurück zu OPEN, falls versehentlich geschlossen</template>
        </ListItemButton>
        <ListItemButton
          v-if="event.status === 'CONFIRMED'"
          :icon="UserMinus"
          variant="danger"
          chevron
          @click="() => { dangerSheetOpen = false; actions.goToDiscard(event) }"
        >
          Unbestätigte verwerfen
          <template #detail>Absage an Teilnehmer ohne Rückmeldung</template>
        </ListItemButton>
        <ListItemButton
          v-if="!['CANCELLED', 'COMPLETED'].includes(event.status)"
          :icon="XCircle"
          variant="danger"
          @click="() => { dangerSheetOpen = false; actions.showCancelEventModal(event) }"
        >
          Veranstaltung absagen
          <template #detail>Alle Angemeldeten werden benachrichtigt</template>
        </ListItemButton>
        <ListItemButton
          v-if="canAnonymize"
          :icon="EyeOff"
          variant="danger"
          @click="() => { dangerSheetOpen = false; actions.showAnonymizeModal(event) }"
        >
          Personendaten anonymisieren
          <template #detail>Namen und Adressen entfernen, Zahlen behalten</template>
        </ListItemButton>
        <ListItemButton
          :icon="Trash2"
          variant="danger"
          @click="() => { dangerSheetOpen = false; actions.showDeleteModal(event) }"
        >
          Veranstaltung löschen
          <template #detail>Endgültig, nicht wiederherstellbar</template>
        </ListItemButton>
      </div>
    </ActionSheet>

    <!-- Clone modal -->
    <dialog :open="actions.cloneEvent.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.cloneEvent.value = null" />
          <h3>Veranstaltung duplizieren</h3>
        </header>
        <p>Erstelle eine Kopie von "{{ actions.cloneEvent.value?.name }}" mit neuem Datum.</p>
        <form @submit.prevent="actions.handleClone">
          <label for="cloneStartAt">
            Neues Datum &amp; Uhrzeit *
            <input id="cloneStartAt" v-model="actions.cloneStartAt.value" type="datetime-local" required :disabled="actions.cloning.value" />
          </label>
          <div v-if="actions.cloneError.value" role="alert" class="error-message">{{ actions.cloneError.value }}</div>
          <footer>
            <button type="button" class="secondary" @click="actions.cloneEvent.value = null" :disabled="actions.cloning.value">Abbrechen</button>
            <button type="submit" :disabled="actions.cloning.value" :aria-busy="actions.cloning.value">
              {{ actions.cloning.value ? 'Wird dupliziert...' : 'Duplizieren' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Cancel modal -->
    <dialog :open="actions.cancelEventData.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.cancelEventData.value = null" />
          <h3>Veranstaltung absagen</h3>
        </header>
        <div class="cancel-warning">
          <p><strong>Achtung:</strong> Diese Aktion kann nicht rückgängig gemacht werden.</p>
          <p>Wenn du "{{ actions.cancelEventData.value?.name }}" absagst:</p>
          <ul>
            <li>Wird der Status auf ABGESAGT gesetzt</li>
            <li>Werden alle Angemeldeten benachrichtigt</li>
            <li>Sind keine weiteren Anmeldungen möglich</li>
          </ul>
        </div>
        <form @submit.prevent="actions.handleCancelEvent">
          <label for="cancelConfirmation">
            Tippe <strong>absagen</strong> zur Bestätigung:
            <input id="cancelConfirmation" v-model="actions.cancelConfirmation.value" type="text" placeholder="absagen" autocomplete="off" :disabled="actions.cancelling.value" />
          </label>
          <div v-if="actions.cancelError.value" role="alert" class="error-message">{{ actions.cancelError.value }}</div>
          <footer>
            <button type="button" class="secondary" @click="actions.cancelEventData.value = null" :disabled="actions.cancelling.value">Zurück</button>
            <button type="submit" class="btn-danger" :disabled="actions.cancelConfirmation.value !== 'absagen' || actions.cancelling.value" :aria-busy="actions.cancelling.value">
              {{ actions.cancelling.value ? 'Wird abgesagt...' : 'Absage bestätigen' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Delete modal -->
    <dialog :open="actions.deleteEventData.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.deleteEventData.value = null" />
          <h3>Veranstaltung löschen</h3>
        </header>
        <p>Möchtest du "{{ actions.deleteEventData.value?.name }}" wirklich endgültig löschen?</p>
        <p><small>Diese Aktion kann nicht rückgängig gemacht werden.</small></p>
        <div v-if="actions.deleteError.value" role="alert" class="error-message">{{ actions.deleteError.value }}</div>
        <footer>
          <button type="button" class="secondary" @click="actions.deleteEventData.value = null" :disabled="actions.deleting.value">Abbrechen</button>
          <button @click="actions.handleDelete" class="btn-danger" :disabled="actions.deleting.value" :aria-busy="actions.deleting.value">
            {{ actions.deleting.value ? 'Wird gelöscht...' : 'Löschen' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- Anonymize modal (spec 022) -->
    <dialog :open="actions.anonymizeEventData.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.anonymizeEventData.value = null" />
          <h3>Personendaten anonymisieren</h3>
        </header>
        <p>
          Namen, E-Mail-Adressen, Telefonnummern, Anmerkungen und alle
          verschickten Mails von "{{ actions.anonymizeEventData.value?.name }}"
          werden unwiderruflich durch Pseudonyme ersetzt.
        </p>
        <p>
          <strong>Erhalten bleiben:</strong> Gruppengrößen, Status, Warteliste
          und alle Auswertungen.
        </p>
        <p>
          <small>
            Alle bereits verschickten Verwaltungslinks hören danach auf zu
            funktionieren. Diese Aktion kann nicht rückgängig gemacht werden.
          </small>
        </p>
        <div v-if="actions.anonymizeError.value" role="alert" class="error-message">
          {{ actions.anonymizeError.value }}
        </div>
        <!-- Große Events brauchen mehrere Durchläufe — Fortschritt statt Stillstand. -->
        <p v-else-if="actions.anonymizing.value && actions.anonymizeProgress.value" role="status">
          <small>{{ actions.anonymizeProgress.value }} Datensätze bereinigt...</small>
        </p>
        <footer>
          <button
            type="button"
            class="secondary"
            :disabled="actions.anonymizing.value"
            @click="actions.anonymizeEventData.value = null"
          >
            Abbrechen
          </button>
          <button
            class="btn-danger"
            :disabled="actions.anonymizing.value"
            :aria-busy="actions.anonymizing.value"
            @click="actions.handleAnonymize"
          >
            {{ actions.anonymizing.value ? 'Wird anonymisiert...' : 'Anonymisieren' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- Capacity warning -->
    <dialog :open="!!actions.capacityWarning.value">
      <article v-if="actions.capacityWarning.value">
        <header>
          <button aria-label="Schließen" rel="prev" @click="actions.capacityWarning.value = null"></button>
          <h3>Kapazität überschritten</h3>
        </header>
        <p>
          <strong>{{ actions.capacityWarning.value.name }}</strong> benötigt {{ actions.capacityWarning.value.needed }}
          {{ actions.capacityWarning.value.needed === 1 ? 'Platz' : 'Plätze' }}, aber nur
          {{ actions.capacityWarning.value.remaining <= 0 ? 'keine' : actions.capacityWarning.value.remaining }}
          {{ actions.capacityWarning.value.remaining === 1 ? 'Platz ist' : 'Plätze sind' }} frei.
        </p>
        <footer>
          <button @click="actions.capacityWarning.value = null">Verstanden</button>
        </footer>
      </article>
    </dialog>

    <!-- Delete registration -->
    <dialog :open="actions.deleteRegData.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.deleteRegData.value = null" />
          <h3>Anmeldung löschen</h3>
        </header>
        <p>Anmeldung von "{{ actions.deleteRegData.value?.name }}" unwiderruflich löschen?</p>
        <footer>
          <button type="button" class="secondary" @click="actions.deleteRegData.value = null">Abbrechen</button>
          <button class="btn-danger" @click="actions.confirmDeleteRegistration">Löschen</button>
        </footer>
      </article>
    </dialog>

    <!-- Message Composer -->
    <MessageComposer
      :open="actions.showMessageComposer.value"
      :event-id="props.eventId"
      :registrations="registrations"
      @close="actions.showMessageComposer.value = false"
      @sent="onMessageSent"
    />
  </article>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  HelpCircle, Link2, Send, Copy, FileDown, MoreHorizontal,
  UserMinus, XCircle, Trash2, Check, ClipboardList, Mail, RotateCcw, EyeOff,
  PackageSearch, Images, FileSignature,
} from 'lucide-vue-next'
import { adminApi } from '../../services/api'
import { useEventActions } from '../../composables/useEventActions.js'
import { useHelp } from '../../components/help/useHelp.js'
import { formatDate, formatDateOnly, formatEventStatus } from '../../utils/formatters.js'
import { showToast } from '../../composables/useToast.js'
import PageHeader from '../../components/PageHeader.vue'
import IconButton from '../../components/IconButton.vue'
import ListItemButton from '../../components/ListItemButton.vue'
import ActionSheet from '../../components/ActionSheet.vue'
import RegistrationTable from '../../components/RegistrationTable.vue'
import MessageComposer from '../../components/MessageComposer.vue'
import MessageLog from '../../components/MessageLog.vue'
import HelpPanel from '../../components/help/HelpPanel.vue'

const props = defineProps({
  eventId: { type: String, required: true },
})

const router = useRouter()

const event = ref(null)
const registrations = ref([])
const fahrbericht = ref(null)
const report = ref(null)
const loading = ref(true)
const loadError = ref(null)
const loadingRegistrations = ref(false)
const registrationsError = ref(null)
const activeTab = ref('details')
const dangerSheetOpen = ref(false)

const EMAIL_STATUS_LABELS = {
  PENDING: 'Wird versendet',
  SENT: 'Versendet',
  FAILED: 'Fehler',
  SKIPPED_NO_RECIPIENT: 'Kein Empfänger',
}
const emailStatusLabel = computed(
  () => EMAIL_STATUS_LABELS[report.value?.email_status] || '',
)
const emailStatusClass = computed(() => ({
  'fb-chip--sent': report.value?.email_status === 'SENT',
  'fb-chip--err': report.value?.email_status === 'FAILED',
  'fb-chip--warn': report.value?.email_status === 'SKIPPED_NO_RECIPIENT',
  'fb-chip--muted': report.value?.email_status === 'PENDING',
}))

async function refreshFahrbericht() {
  try {
    fahrbericht.value = await adminApi.fahrbericht.get(props.eventId)
  } catch {
    fahrbericht.value = null
  }
  if (fahrbericht.value) {
    try {
      report.value = await adminApi.reports.getForEvent(props.eventId)
    } catch {
      report.value = null
    }
  } else {
    report.value = null
  }
}

async function startFahrbericht() {
  try {
    await adminApi.fahrbericht.createDraft(props.eventId)
    openFahrbericht()
  } catch (err) {
    showToast(err?.message || 'Fahrbericht anlegen fehlgeschlagen', 'error')
  }
}

// Spec 023 — same page for SINGLE and FESTIVAL, so it is addressed by name.
function goToLostFound() {
  router.push({ name: 'admin-lost-and-found', params: { eventId: props.eventId } })
}

// Spec 024 — likewise shared between SINGLE and FESTIVAL, likewise by name.
function goToEventPhotos() {
  router.push({ name: 'admin-event-photos', params: { eventId: props.eventId } })
}

// Spec 025 — SINGLE events only, so the guard sits on the entry, not here.
function goToCharterContract() {
  router.push({ name: 'admin-charter-contract', params: { eventId: props.eventId } })
}

function openFahrbericht() {
  window.location.href = `/admin/events/${props.eventId}/fahrbericht`
}

function openPdf() {
  if (!report.value) return
  window.open(adminApi.reports.pdfUrl(report.value.id), '_blank', 'noopener')
}

async function resendReport() {
  if (!report.value) return
  try {
    report.value = await adminApi.reports.resend(report.value.id)
    showToast('Bericht versendet', 'success')
  } catch (err) {
    showToast(err?.message || 'Senden fehlgeschlagen', 'error')
  }
}

// Micro-interaction: brief checkmark after successful copy
const linkCopied = ref(false)
const inviteCopied = ref(false)

const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

const activeHelpKey = computed(() => {
  if (actions.cloneEvent.value) return 'clone-event'
  if (actions.showMessageComposer.value) return 'message-composer'
  return 'event-detail'
})

async function refreshEvent() {
  try {
    event.value = await adminApi.getEvent(props.eventId)
  } catch (err) {
    loadError.value = err.message || 'Veranstaltung konnte nicht geladen werden'
  }
}

async function refreshRegistrations() {
  try {
    registrations.value = (await adminApi.listRegistrations(props.eventId)).items
  } catch (err) {
    registrationsError.value = err.message || 'Anmeldungen konnten nicht geladen werden'
  }
}

const actions = useEventActions({ event, registrations, refreshEvent, refreshRegistrations })

function spotsBy(status) {
  return registrations.value.filter(r => r.status === status).reduce((sum, r) => sum + r.group_size, 0)
}
const participatingSpots = computed(() => spotsBy('PARTICIPATING'))
const pendingSpots = computed(() => spotsBy('CONFIRMED'))

const isAnonymized = computed(() => Boolean(event.value?.anonymized_at))

// Spec 025 — the summary block {status, uebergabe_at, signed_on} that
// GET /api/admin/events/{id} hangs off the event. Read defensively: the page
// has to keep rendering against an API that has not deployed it yet.
const charterContract = computed(() => event.value?.charter_contract || null)

// CharterStatus serialises lowercase (unlike the uppercase enums elsewhere),
// so normalise rather than trusting the case.
const charterStatus = computed(() => (charterContract.value?.status || '').toLowerCase())

const showCharterSection = computed(
  () => Boolean(event.value) && event.value.event_type !== 'FESTIVAL',
)

const charterEntryLabel = computed(() => {
  if (!charterContract.value) return 'Vertrag anlegen'
  return charterStatus.value === 'signed' ? 'Vertrag ansehen' : 'Vertrag bearbeiten'
})

const charterChip = computed(() => {
  switch (charterStatus.value) {
    case 'draft':
      return { class: 'fb-chip--warn', label: 'Entwurf' }
    case 'sent':
      return { class: 'fb-chip--warn', label: 'Verschickt' }
    case 'signed':
      return {
        class: 'fb-chip--sent',
        label: `Signiert am ${formatDateOnly(charterContract.value.signed_on)}`,
      }
    default:
      // No row yet, or a status this build does not know: no chip.
      return null
  }
})

const CHARTER_NAG_WINDOW_MS = 14 * 24 * 60 * 60 * 1000

// „Übergabe am 14.06. um 10:00" — day and time only, Berlin, matching the
// wording of the banner rather than the app's usual formatDate.
const charterHandoverLabel = computed(() => {
  const iso = charterContract.value?.uebergabe_at
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const tz = { timeZone: 'Europe/Berlin' }
  const day = d.toLocaleDateString('de-DE', { ...tz, day: '2-digit', month: '2-digit' })
  const time = d.toLocaleTimeString('de-DE', { ...tz, hour: '2-digit', minute: '2-digit' })
  return `${day} um ${time}`
})

const charterHandoverDue = computed(() => {
  if (!showCharterSection.value || !charterContract.value) return false
  if (charterStatus.value === 'signed') return false
  const iso = charterContract.value.uebergabe_at
  if (!iso) return false
  const handover = new Date(iso).getTime()
  if (isNaN(handover)) return false
  const now = Date.now()
  // Upper bound is the spec's 14 days. The lower bound runs a day past the
  // handover instead of stopping at it: an unsigned contract is at its most
  // urgent on the morning of the trip, and the page is opened that day.
  return handover <= now + CHARTER_NAG_WINDOW_MS && handover > now - 24 * 60 * 60 * 1000
})

// Mirrors the backend guard (ANONYMIZABLE_STATUSES): a live event still has to
// be able to mail its participants. Hidden once done, so the entry cannot be
// pressed twice.
const canAnonymize = computed(
  () => !isAnonymized.value && ['COMPLETED', 'CANCELLED'].includes(event.value?.status),
)

const primaryCta = computed(() => {
  if (!event.value) return null
  const e = event.value
  if (e.status === 'DRAFT') {
    return {
      label: 'Veröffentlichen',
      busyLabel: 'Wird veröffentlicht…',
      busy: actions.publishing.value,
      run: () => actions.publishEvent(e),
    }
  }
  if (e.status === 'OPEN') {
    return {
      label: 'Anmeldung schließen',
      busyLabel: 'Wird geschlossen…',
      busy: actions.closingRegistration.value,
      run: () => actions.closeRegistration(e),
    }
  }
  if (e.status === 'REGISTRATION_CLOSED' || e.status === 'LOTTERY_PENDING') {
    return {
      label: 'Verlosung',
      busyLabel: '',
      busy: false,
      run: () => actions.goToLottery(e),
    }
  }
  if (e.status === 'CONFIRMED') {
    return {
      label: 'Abschließen',
      busyLabel: 'Wird abgeschlossen…',
      busy: actions.completing.value,
      run: () => actions.completeEvent(e),
    }
  }
  return null
})

function flashCopy(flag) {
  flag.value = true
  setTimeout(() => { flag.value = false }, 1200)
}

function handleCopyLink() {
  actions.copyRegistrationLink(event.value)
  flashCopy(linkCopied)
}

function handleCopyInvite() {
  actions.copyInviteText(event.value)
  flashCopy(inviteCopied)
}

function onMessageSent() {
  showToast('Nachricht wurde gesendet', 'success')
  refreshRegistrations()
}

onMounted(async () => {
  loading.value = true
  loadError.value = null
  try {
    const [evt, regs] = await Promise.all([
      adminApi.getEvent(props.eventId),
      adminApi.listRegistrations(props.eventId),
    ])
    event.value = evt
    registrations.value = regs.items
    refreshFahrbericht()
  } catch (err) {
    loadError.value = err.message || 'Daten konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.event-detail-page {
  /* Containing block for HelpPanel's absolutely-positioned panel. Without it
     the panel anchors to the document origin and lands off-screen. */
  position: relative;
  padding-bottom: 8rem;
  /* Height of .sticky-cta (12px + 48px + 12px + 1px border), rounded up.
     Read by the registrations list's context menu so it opens clear of the
     „Abschließen" bar instead of behind it. */
  --bottom-obstruction: 4.5rem;
}

.event-description {
  white-space: pre-line;
}

.anonymized-notice {
  margin-bottom: var(--space-4);
  padding: var(--space-3);
  border-left: 3px solid var(--muted-border-color);
  background: var(--card-sectioning-background-color);
}

/* Spec 025 — same shape as the anonymisation notice, but red: this one is a
   thing to act on, not a thing to know. */
.charter-notice {
  margin-bottom: var(--space-4);
  padding: var(--space-3);
  border-left: 3px solid var(--color-danger-text);
  background: var(--color-danger-bg);
  color: var(--color-danger-text);
}

/* Tabs */
.tab-nav {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: var(--space-4);
}

.tab-list {
  display: flex;
  gap: var(--space-2);
  white-space: nowrap;
  list-style: none;
  padding: 0;
  margin: 0;
  border-bottom: 1px solid var(--color-border);
}

.tab-list a {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  min-height: 44px;
  text-decoration: none;
  color: var(--color-text-muted);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color 0.15s, border-color 0.15s;
}

.tab-list a.active {
  border-bottom-color: var(--color-brand);
  color: var(--color-brand);
  font-weight: 600;
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.25rem;
  height: 1.25rem;
  padding: 0 var(--space-1);
  background: var(--color-border);
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-brand);
}

.tab-list a.active .tab-badge {
  background: var(--color-brand);
  color: white;
}

/* Info dl */
.event-info {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-2) var(--space-4);
  margin: 0;
}

.event-info dt {
  font-weight: 500;
  color: var(--color-text-muted);
  font-size: var(--text-base);
}

.event-info dd {
  margin: 0;
  font-size: var(--text-base);
}

/* Actions list — sits under Info card */
.actions-list {
  margin-top: var(--space-4);
}

.success-check {
  color: var(--color-success-text);
}

/* Messages tab */
.messages-tab-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--space-4);
}

.messages-tab-header button {
  width: auto;
}

/* Sticky CTA — sits above the bottom tab bar */
.sticky-cta {
  position: fixed;
  bottom: calc(3.5rem + env(safe-area-inset-bottom, 0));
  left: 0;
  right: 0;
  z-index: 50;
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-raised);
  border-top: 1px solid var(--color-border);
  box-shadow: var(--shadow-sticky);
}

.sticky-cta button {
  width: 100%;
  margin: 0;
  min-height: 48px;
  font-weight: 600;
}

/* Sheet content */
.sheet-list {
  padding: var(--space-2) 0;
}

/* Skeleton */
.skeleton-container {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.skeleton {
  background: linear-gradient(90deg, #eee 25%, #f5f5f5 50%, #eee 75%);
  background-size: 200% 100%;
  border-radius: var(--radius-sm);
  animation: skeleton-shimmer 1.5s infinite;
}

.skeleton-title {
  display: inline-block;
  width: 12rem;
  height: 1.5rem;
  vertical-align: middle;
}

.skeleton-tab-row {
  height: 44px;
  width: 100%;
  max-width: 24rem;
}

.skeleton-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skeleton-row {
  height: 1rem;
  width: 100%;
}

.skeleton-row.short {
  width: 60%;
}

@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.cancel-warning {
  background: var(--color-danger-bg);
  border: 1px solid var(--color-danger-text);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  margin-bottom: var(--space-4);
}

.cancel-warning p { margin-bottom: var(--space-2); }
.cancel-warning ul { margin: var(--space-2) 0 0 var(--space-6); padding: 0; }

dialog article { max-width: min(600px, calc(100vw - 2rem)); }

dialog footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-4);
  margin-top: var(--space-4);
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .event-info {
    grid-template-columns: 1fr;
    gap: var(--space-1);
  }

  .event-info dt {
    margin-top: var(--space-2);
  }
}

/* Fahrbericht status chips (spec 014) */
.fb-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.fb-chip--draft { background: var(--color-neutral-bg); color: var(--color-neutral-text); }
.fb-chip--sent { background: var(--color-success-bg); color: var(--color-success-text); }
.fb-chip--err { background: var(--color-danger-bg); color: var(--color-danger-text); }
.fb-chip--warn { background: var(--color-warning-bg); color: var(--color-warning-text); }
.fb-chip--muted { background: var(--color-neutral-bg); color: var(--color-neutral-text); }
</style>
