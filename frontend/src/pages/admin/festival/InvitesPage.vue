<template>
  <article style="position: relative;">
    <PageHeader :back="`/admin/festival/${eventId}`" back-label="Zurück" :subtitle="event?.name || ''">
      <template #title>Gästelisten</template>
    </PageHeader>

    <FestivalHelp title="So funktionieren Gästelisten">
      <p>Neue Gästeliste anlegen: der <strong>+ Knopf unten rechts</strong>. Jede verantwortliche Person auf der Liste bekommt ihren eigenen Einladungslink — für sich selbst oder zum Weiterverteilen.</p>
      <p>Typischer Einsatz: <strong>eine Liste pro verantwortlicher Person</strong> als Ticket-Kontingent — z.B. „Micha“ mit 10 Anmeldungen × 2 Personen. Micha gibt seinen Link weiter, die Leute melden sich selbst damit an.</p>
      <p>Über „Liste“ (oder den Link in der Einladungs-Mail) sieht Micha seine eigene Gästeliste: wie viele Anmeldungen noch frei sind und wer schon dabei ist.</p>
      <p>Ein persönlicher Link (1 × 1) geht genau einmal. Ein geteilter Link geht öfter — bis sein Deckel voll ist.</p>
      <p>Hast du eine E-Mail-Adresse eingetragen, kannst du die Einladung direkt hier verschicken („E-Mail senden"). Sonst: „Kopieren" und den Link selbst teilen, z.B. per Telegram.</p>
      <p>Kopieren und Mailen merken wir uns als „verschickt". Steht bei jemandem noch „offen"? Einfach nochmal anschreiben.</p>
      <p>Neue Links erst rausgeben, wenn oben noch Luft ist — sonst wird's voller als geplant.</p>
    </FestivalHelp>

    <!-- Loading -->
    <div v-if="loading" aria-busy="true">
      Gästelisten werden geladen...
    </div>

    <!-- Error -->
    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <template v-else>
      <!-- Empty state -->
      <article v-if="groups.length === 0" class="empty-state">
        <p>Noch keine Gästeliste — leg die erste an.</p>
        <button @click="showBatchModal = true">Gästeliste anlegen</button>
      </article>

      <template v-else>
        <!-- Page-top total bar (T209): the same three numbers summed across
             all Kontingente, against the overall cap. Soft-cap warning only
             (never blocking) — issuing fewer links is the control lever. -->
        <p class="totals-bar">
          ausgegeben <strong>{{ totals.issuedSeats }}</strong>
          · angemeldet <strong>{{ totals.registered }}</strong>
          · maximal noch zu erwarten
          <strong :class="{ 'totals-warning': totalsOverCap }">{{ totals.maxExpected }}</strong>
          — Cap {{ event?.capacity ?? '–' }}
        </p>

        <div v-for="group in groups" :key="group.label" class="kontingent-group">
          <div class="kontingent-header">
            <h3>
              {{ group.label }}
              <span v-if="group.collapsible" class="group-count">({{ group.items.length }})</span>
            </h3>
            <!-- „Späte Fische" are single-use links created one at a time during
                 the festival, so they would bury the ~22 planned Kontingente
                 this page exists for. Collapsed by default; their home is the
                 registrations page. -->
            <button
              v-if="group.collapsible"
              type="button"
              class="outline"
              @click="toggleGroup(group.label)"
            >
              {{ isCollapsed(group.label) ? 'Aufklappen' : 'Zuklappen' }}
            </button>
            <button
              v-if="!isCollapsed(group.label)"
              type="button"
              class="outline"
              @click="copyAllInBatch(group.items)"
            >
              Alle kopieren
            </button>
          </div>

          <p v-if="!isCollapsed(group.label)" class="kontingent-summary">
            <strong>{{ group.issuedSeats }}</strong> Plätze vergeben (Kapazität: {{ event?.capacity ?? '–' }})
            · <strong>{{ group.registered }}</strong> angemeldet
            · max. noch <strong>{{ group.maxExpected }}</strong> zu erwarten
          </p>

          <table v-if="!isCollapsed(group.label)" class="mobile-card-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Kategorie</th>
                <th>Status</th>
                <th>Aktionen</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="invite in group.items" :key="invite.id">
                <td data-label="Name">
                  <strong>{{ invite.label }}</strong>
                  <template v-if="invite.email">
                    <br />
                    <small>{{ invite.email }}</small>
                  </template>
                </td>
                <td data-label="Kategorie">{{ formatTier(invite.tier) }}</td>
                <td data-label="Status">
                  <span :class="['status-badge', statusChip(invite).cls]">{{ statusChip(invite).text }}</span>
                  <!-- The clamp is temporary: show what the list was, so „86/89"
                       never reads as if the 200-seat Kontingent had shrunk. -->
                  <small v-if="invite.original_max_uses" class="original-allowance">
                    ursprünglich {{ invite.original_max_uses }} Plätze
                  </small>
                </td>
                <td data-label="Aktionen" class="invite-actions">
                  <button type="button" class="outline" title="Kopiert eine fertige Moin-Nachricht mit dem Link" @click="copyRow(invite)">
                    Kopieren
                  </button>
                  <a
                    v-if="invite.max_uses > 1"
                    role="button"
                    class="outline"
                    title="Öffnet die Gästeliste zu diesem Link — wer sich schon angemeldet hat"
                    :href="`${invite.url}/liste`"
                    target="_blank"
                    rel="noopener"
                  >
                    Liste
                  </a>
                  <button
                    v-if="invite.email"
                    type="button"
                    class="outline"
                    :disabled="sendingId === invite.id"
                    :aria-busy="sendingId === invite.id"
                    @click="sendEmail(invite)"
                  >
                    E-Mail senden
                  </button>
                  <!-- Override: reopen ONE list after registration closed.
                       Reopening never restores the original allowance — it
                       clamps `max_uses` to what is used plus the few seats you
                       grant here. This list has 786 unused seats spread over 22
                       links that are already circulating in group chats; giving
                       one back its full remainder with a misclick is exactly
                       what this avoids. -->
                  <button
                    v-if="!invite.revoked_at && !invite.late_entry"
                    type="button"
                    class="outline"
                    title="Diese Liste nach Anmeldeschluss für einzelne Plätze wieder öffnen"
                    @click="askReopen(invite)"
                  >
                    Wieder öffnen
                  </button>
                  <button
                    v-if="!invite.revoked_at && invite.late_entry"
                    type="button"
                    class="outline"
                    :disabled="closingId === invite.id"
                    :aria-busy="closingId === invite.id"
                    title="Diese Liste sofort wieder schließen"
                    @click="closeList(invite)"
                  >
                    Wieder schließen
                  </button>
                  <button
                    v-if="!invite.revoked_at"
                    type="button"
                    class="outline secondary"
                    @click="askRevoke(invite)"
                  >
                    Widerrufen
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="hint-text">
          Link nochmal schicken? „Kopieren" legt eine fertige Moin-Nachricht in die Zwischenablage —
          einfach per Telegram oder Mail rausschicken.
        </p>
      </template>
    </template>

    <!-- Floating action button — create Gästeliste -->
    <button
      v-if="!loading && !loadError && groups.length > 0"
      type="button"
      class="fab"
      aria-label="Gästeliste anlegen"
      title="Gästeliste anlegen"
      @click="showBatchModal = true"
    >
      <Plus :size="24" aria-hidden="true" />
    </button>

    <InviteBatchModal
      :open="showBatchModal"
      :event-id="eventId"
      @close="showBatchModal = false"
      @created="handleBatchCreated"
    />

    <!-- Revoke confirmation dialog -->
    <!-- Override: reopen one list for a COUNTED number of seats. The count is
         the whole point — this event has 786 unused seats across 22 links that
         are already out in group chats, so „wieder öffnen" must never mean
         „gib den Rest frei". -->
    <dialog :open="reopenTarget ? true : undefined">
      <article style="max-width: 500px;">
        <header>
          <button @click="reopenTarget = null" aria-label="Schließen" rel="prev"></button>
          <h3>Liste wieder öffnen</h3>
        </header>

        <p>
          <strong>„{{ reopenTarget?.label }}"</strong> hat
          {{ reopenTarget?.use_count }} von {{ reopenTarget?.max_uses }} Plätzen genutzt.
        </p>
        <p>Wie viele Plätze soll diese Liste jetzt noch bekommen?</p>

        <div class="reopen-choices">
          <button
            v-for="n in [1, 2, 3, 5]"
            :key="n"
            type="button"
            :class="reopenCount === n ? '' : 'outline'"
            @click="reopenCount = n"
          >
            +{{ n }}
          </button>
        </div>

        <p class="reopen-effect">
          Danach: <strong>{{ reopenCount }}</strong>
          {{ reopenCount === 1 ? 'weitere Person' : 'weitere Personen' }} kann sich anmelden,
          dann ist die Liste automatisch wieder zu.
          Der bestehende Link funktioniert dafür weiter.
        </p>

        <div v-if="reopenError" role="alert" class="error">{{ reopenError }}</div>

        <footer>
          <button @click="reopenTarget = null" class="secondary">Abbrechen</button>
          <button @click="confirmReopen" :disabled="reopening" :aria-busy="reopening">
            {{ reopening ? 'Wird geöffnet…' : `${reopenCount} Plätze freigeben` }}
          </button>
        </footer>
      </article>
    </dialog>

    <dialog :open="revokeTarget ? true : undefined">
      <article style="max-width: 500px;">
        <header>
          <button @click="revokeTarget = null" aria-label="Schließen" rel="prev"></button>
          <h3>Einladung widerrufen?</h3>
        </header>

        <p class="warning-box">
          „{{ revokeTarget?.label }}" kann den Link danach nicht mehr benutzen. Das lässt sich nicht rückgängig machen.
        </p>

        <div v-if="revokeError" role="alert" class="error">{{ revokeError }}</div>

        <footer>
          <button @click="revokeTarget = null" class="secondary">Abbrechen</button>
          <button
            @click="confirmRevoke"
            :disabled="revoking"
            :aria-busy="revoking"
            class="cancel-confirm-btn"
          >
            {{ revoking ? 'Wird widerrufen...' : 'Ja, widerrufen' }}
          </button>
        </footer>
      </article>
    </dialog>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Plus } from 'lucide-vue-next'
import { adminApi } from '../../../services/api'
import PageHeader from '../../../components/PageHeader.vue'
import FestivalHelp from '../../../components/help/FestivalHelp.vue'
import InviteBatchModal from './InviteBatchModal.vue'
import { showToast } from '../../../composables/useToast.js'

const props = defineProps({
  eventId: { type: String, default: null },
})

const loading = ref(true)
const loadError = ref(null)
const event = ref(null)
const invites = ref([])
const showBatchModal = ref(false)
const sendingId = ref(null)
const reopenTarget = ref(null)
const reopenCount = ref(1)
const reopenError = ref(null)
const reopening = ref(false)
const closingId = ref(null)

const revokeTarget = ref(null)
const revoking = ref(false)
const revokeError = ref(null)

const TIER_LABELS = {
  werft: 'Werft',
  volunteer: 'Helfer:in',
  org: 'Organisation',
  open: 'Offen',
}

function formatTier(tier) {
  return TIER_LABELS[tier] || tier
}

// Status chips are derived client-side (Ä7): widerrufen > abgelaufen > angemeldet
// (multi-use shows "2/5 angemeldet") > verschickt > offen.
function statusChip(invite) {
  if (invite.revoked_at) return { text: 'widerrufen', cls: 'status-cancelled' }
  if (invite.expired) return { text: 'abgelaufen', cls: 'status-cancelled' }
  // A reopened list must be recognisable at a glance — it is the one row on
  // this page that still accepts registrations after everything else closed.
  if (invite.late_entry) {
    const free = Math.max(0, invite.max_uses - invite.use_count)
    return {
      text: free > 0 ? `offen für ${free}` : 'offen, aufgebraucht',
      cls: free > 0 ? 'status-participating' : 'status-draft',
    }
  }
  if (invite.use_count >= 1) {
    return {
      text: invite.max_uses > 1 ? `${invite.use_count}/${invite.max_uses} angemeldet` : 'angemeldet',
      cls: 'status-participating',
    }
  }
  if (invite.sent_at) return { text: 'verschickt', cls: 'status-sent' }
  return { text: 'offen', cls: 'status-draft' }
}

// Grouped by Kontingent (batch_label), "Ohne Kontingent" sorted last (T209).
// "maximal noch zu erwarten" is people-dimensioned — Σ (max_uses − use_count)
// × max_group_size over non-revoked, non-expired invites (identical formula
// to T119); a plain "issued − registered" would subtract registrations from
// people. Note: "angemeldet" counts registrations, not people — people
// totals live on the headcount board (deliberate separation, no hard
// Kontingent entity per the challenge round).
const UNGROUPED_LABEL = 'Ohne Liste'
// Must match the batch_label the „Späten Fisch einladen" button writes.
const LATE_FISH_LABEL = 'Späte Fische'

// Collapsed by default — the planning view should stay at its ~25 rows even
// after a busy Saturday of late arrivals.
const collapsedGroups = ref(new Set([LATE_FISH_LABEL]))

function isCollapsed(label) {
  return collapsedGroups.value.has(label)
}

function toggleGroup(label) {
  const next = new Set(collapsedGroups.value)
  if (next.has(label)) next.delete(label)
  else next.add(label)
  collapsedGroups.value = next
}

const groups = computed(() => {
  const map = new Map()
  for (const invite of invites.value) {
    const label = invite.batch_label || UNGROUPED_LABEL
    if (!map.has(label)) map.set(label, [])
    map.get(label).push(invite)
  }
  const entries = Array.from(map.entries())
  // Stable sort: only bubble the ungrouped bucket to the end, keep the
  // relative order of named Kontingente as returned by the API.
  entries.sort((a, b) => {
    if (a[0] === UNGROUPED_LABEL && b[0] !== UNGROUPED_LABEL) return 1
    if (b[0] === UNGROUPED_LABEL && a[0] !== UNGROUPED_LABEL) return -1
    return 0
  })
  return entries.map(([label, items]) => ({
    label,
    items,
    collapsible: label === LATE_FISH_LABEL,
    issuedSeats: items.filter((i) => !i.revoked_at).reduce((sum, i) => sum + i.max_uses * i.max_group_size, 0),
    registered: items.reduce((sum, i) => sum + i.use_count, 0),
    maxExpected: items
      .filter((i) => !i.revoked_at && !i.expired)
      .reduce((sum, i) => sum + (i.max_uses - i.use_count) * i.max_group_size, 0),
  }))
})

// Page-top total bar (T209): the same three numbers summed across all
// Kontingente, rendered against the overall event cap.
const totals = computed(() => ({
  issuedSeats: groups.value.reduce((sum, g) => sum + g.issuedSeats, 0),
  registered: groups.value.reduce((sum, g) => sum + g.registered, 0),
  maxExpected: groups.value.reduce((sum, g) => sum + g.maxExpected, 0),
}))

// Soft-cap warning only (never blocking) — the control lever is issuing
// fewer links, not blocking anything here.
const totalsOverCap = computed(() => {
  const cap = event.value?.capacity
  return cap != null && totals.value.registered + totals.value.maxExpected > cap
})

function updateInviteInPlace(updated) {
  const idx = invites.value.findIndex((i) => i.id === updated.id)
  if (idx !== -1) invites.value.splice(idx, 1, updated)
}

async function loadInvites() {
  loading.value = true
  loadError.value = null
  try {
    const [eventResult, invitesResult] = await Promise.all([
      adminApi.festival.getEvent(props.eventId),
      adminApi.festival.listInvites(props.eventId),
    ])
    event.value = eventResult
    invites.value = invitesResult.items
  } catch (err) {
    loadError.value = err.message || 'Gästelisten konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
}

// Copy-row (Ä7): clipboard success stamps sent_at (idempotent) and flips the
// chip offen→verschickt without reloading the page; clipboard failure falls
// back to a prompt() (pattern: useEventActions.js copyRegistrationLink).
// Contingent links (max_uses > 1) get their numbers and the guestlist link
// spelled out — same content as the F1 email.
function copyRow(invite) {
  let text = `Moin ${invite.label}! Hier ist dein Einladungslink für ${event.value?.name}: ${invite.url}`
  if (invite.max_uses > 1) {
    const perReg = invite.max_group_size > 1 ? ` (je bis zu ${invite.max_group_size} Personen)` : ''
    text += `\nDu kannst den Link weitergeben — er gilt für bis zu ${invite.max_uses} Anmeldungen${perReg}.`
    text += `\nWer sich schon angemeldet hat, siehst du hier: ${invite.url}/liste`
  }
  navigator.clipboard.writeText(text).then(
    async () => {
      try {
        const updated = await adminApi.festival.markInviteSent(props.eventId, invite.id)
        updateInviteInPlace(updated)
        showToast('Link kopiert!', 'success')
      } catch (err) {
        showToast(err.message || 'Als verschickt markieren fehlgeschlagen', 'error')
      }
    },
    () => prompt('Kopiere diesen Link:', invite.url),
  )
}

// Copy all (per Kontingent): one "Name: URL" line per invite. The spec does not
// mandate sent_at stamping for copy-all, but we stamp each row anyway (idempotent)
// to keep the chase list honest.
function copyAllInBatch(items) {
  const lines = items.map((invite) => `${invite.label}: ${invite.url}`).join('\n')
  navigator.clipboard.writeText(lines).then(
    async () => {
      showToast('Alle Links kopiert!', 'success')
      await Promise.all(
        items.map((invite) =>
          adminApi.festival.markInviteSent(props.eventId, invite.id).catch(() => null),
        ),
      )
      await loadInvites()
    },
    () => prompt('Kopiere diese Links:', lines),
  )
}

async function sendEmail(invite) {
  sendingId.value = invite.id
  try {
    const updated = await adminApi.festival.sendInviteEmail(props.eventId, invite.id)
    updateInviteInPlace(updated)
    showToast('E-Mail versendet', 'success')
  } catch (err) {
    showToast(err.message || 'E-Mail-Versand fehlgeschlagen', 'error')
  } finally {
    sendingId.value = null
  }
}

function askReopen(invite) {
  reopenTarget.value = invite
  reopenCount.value = 1
  reopenError.value = null
}

// Reopening clamps `max_uses` to `use_count + n` instead of restoring the
// original allowance, and sets `late_entry` so the link survives the closed
// registration. Both in one patch, so the list can never be late-open with its
// full remainder live.
async function confirmReopen() {
  const invite = reopenTarget.value
  if (!invite) return
  reopening.value = true
  reopenError.value = null
  try {
    await adminApi.festival.patchInvite(props.eventId, invite.id, {
      late_entry: true,
      max_uses: invite.use_count + reopenCount.value,
    })
    showToast(`„${invite.label}" ist für ${reopenCount.value} Plätze offen`, 'success')
    reopenTarget.value = null
    await loadInvites()
  } catch (err) {
    reopenError.value = err.message || 'Öffnen fehlgeschlagen'
    showToast(reopenError.value, 'error')
  } finally {
    reopening.value = false
  }
}

// Closing leaves `max_uses` where it is: restoring the original allowance on
// close would quietly re-arm the link for its whole remainder.
async function closeList(invite) {
  closingId.value = invite.id
  try {
    await adminApi.festival.patchInvite(props.eventId, invite.id, { late_entry: false })
    showToast(`„${invite.label}" ist wieder zu`, 'success')
    await loadInvites()
  } catch (err) {
    showToast(err.message || 'Schließen fehlgeschlagen', 'error')
  } finally {
    closingId.value = null
  }
}

function askRevoke(invite) {
  revokeTarget.value = invite
  revokeError.value = null
}

async function confirmRevoke() {
  if (!revokeTarget.value) return
  revoking.value = true
  revokeError.value = null
  try {
    const updated = await adminApi.festival.patchInvite(props.eventId, revokeTarget.value.id, { revoked: true })
    updateInviteInPlace(updated)
    showToast('Einladung widerrufen', 'success')
    revokeTarget.value = null
  } catch (err) {
    revokeError.value = err.message || 'Widerruf fehlgeschlagen'
  } finally {
    revoking.value = false
  }
}

function handleBatchCreated(result) {
  showBatchModal.value = false
  const n = result.items.length
  const base =
    n === 1 ? 'Gästeliste mit 1 verantwortlichen Person angelegt' : `Gästeliste mit ${n} Verantwortlichen angelegt`
  const emailed = result.emailed_count || 0
  const suffix = emailed === 1 ? ' · 1 Einladung verschickt' : emailed > 1 ? ` · ${emailed} Einladungen verschickt` : ''
  showToast(base + suffix, 'success')
  loadInvites()
}

onMounted(loadInvites)
</script>

<style scoped>
.original-allowance {
  display: block;
  color: var(--color-text-muted);
}

.reopen-choices {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.reopen-choices button {
  width: auto;
  margin: 0;
  min-height: 44px;
  flex: 1;
}

.reopen-effect {
  font-size: 0.9em;
  color: var(--color-text-muted);
}

.error {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
}

.empty-state {
  text-align: center;
  padding: var(--space-6) var(--space-4);
}

.empty-state button {
  width: auto;
  min-height: 44px;
}

.totals-bar {
  font-size: var(--text-sm);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  margin-bottom: 1.25rem;
}

.totals-warning {
  color: var(--color-warning-text);
  background: var(--color-warning-bg);
  padding: 0.05rem 0.35rem;
  border-radius: var(--pico-border-radius);
}

.kontingent-group {
  margin-bottom: 2rem;
}

.kontingent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.25rem;
}

.kontingent-header h3 {
  margin: 0;
}

.kontingent-summary {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  margin-bottom: 0.75rem;
}

.invite-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.invite-actions button,
.invite-actions a[role="button"] {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.hint-text {
  font-size: 0.875rem;
  color: var(--color-text-muted);
}

.warning-box {
  background: var(--color-warning-bg);
  padding: 0.75rem;
  border-radius: var(--pico-border-radius);
  color: var(--color-warning-text);
  font-size: 0.9em;
}

.cancel-confirm-btn {
  --pico-primary: #dc2626;
  --pico-primary-hover: #b91c1c;
  --pico-primary-focus: rgba(220, 38, 38, 0.25);
}

/* Floating action button — create Kontingent (pattern: EventsPage.vue) */
.fab {
  position: fixed;
  right: var(--space-4);
  bottom: calc(3.5rem + var(--space-4) + env(safe-area-inset-bottom, 0));
  z-index: 40;
  width: 56px;
  height: 56px;
  padding: 0;
  margin: 0;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--color-brand);
  color: white;
  border: none;
  border-radius: var(--radius-pill);
  box-shadow: var(--shadow-fab);
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease, background 0.12s ease;
  -webkit-tap-highlight-color: transparent;
}

.fab:hover,
.fab:focus-visible {
  background: var(--color-brand-light);
  transform: translateY(-1px);
  outline: none;
}

.fab:active {
  transform: translateY(0);
}

@media (max-width: 640px) {
  tbody td[data-label="Status"]::before {
    display: none;
  }
}
</style>
