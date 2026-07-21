<template>
  <article style="position: relative;">
    <PageHeader :back="`/admin/festival/${eventId}`" back-label="Zurück">
      <template #title>Wer kommt wann</template>
      <template #actions>
        <button
          type="button"
          class="outline"
          :disabled="loading"
          :aria-busy="loading"
          @click="loadHeadcount"
        >
          Aktualisieren
        </button>
      </template>
    </PageHeader>

    <FestivalHelp title="Was die Zahlen bedeuten">
      <p>Das sind die Planzahlen aus den Anmeldungen. Sie blocken nichts — niemand wird abgewiesen.</p>
      <p>Wird ein Tag zu voll? Dann einfach weniger neue Links rausgeben. Absagen musst du niemandem.</p>
      <p>Die wichtigste Zahl ist die Spitze — mehr als grob 1000 gleichzeitig soll's nicht werden.</p>
      <p>„Angekommen" zählt, wer wirklich da war (vom Scanner am Eingang) — nicht, wer gerade auf dem Gelände ist.</p>
    </FestivalHelp>

    <!-- Loading -->
    <div v-if="loading && !headcount" aria-busy="true">
      Zahlen werden geladen …
    </div>

    <!-- Error (only blocks the view on the initial load; a failed refresh
         keeps showing the last-loaded board and relies on the toast) -->
    <div v-else-if="error && !headcount" role="alert" class="error">
      {{ error }}
    </div>

    <template v-else-if="headcount">
      <!-- Overall soft-cap banner (Ä4/Ä8: informational, nothing is blocked) -->
      <p v-if="headcount.overall_overbooked" class="overbooked-banner">
        Spitze {{ headcount.peak_total }} über Gesamt-Cap {{ headcount.overall_cap }} — weiche Grenze, nichts ist blockiert.
      </p>

      <!-- Summary header -->
      <p class="summary-line">
        <strong>{{ headcount.total_people }}</strong> Personen ·
        <strong>{{ headcount.total_registrations }}</strong> Anmeldungen ·
        Spitze <strong>{{ headcount.peak_total }}</strong>
        <span v-if="headcount.registrations_without_slots > 0" class="chip chip-warn">
          {{ headcount.registrations_without_slots }} Anmeldungen ohne Zeitfenster
        </span>
      </p>

      <!-- Unbekannte Zeitfenster warning card -->
      <article v-if="unknownSlotEntries.length > 0" class="unknown-slots-card">
        <h4>Unbekannte Zeitfenster</h4>
        <p class="hint-text">
          Diese Zeitfenster-Schlüssel stecken noch in Anmeldungen, tauchen in der aktuellen
          Konfiguration aber nicht mehr auf (vermutlich nach einer Bearbeitung) — wir zeigen
          sie weiter an, damit nichts verloren geht.
        </p>
        <ul>
          <li v-for="[key, count] in unknownSlotEntries" :key="key">
            <code>{{ key }}</code>: {{ count }} Personen
          </li>
        </ul>
      </article>

      <!-- Slot x Tier matrix -->
      <div class="table-scroll">
        <table class="mobile-card-table">
          <thead>
            <tr>
              <th>Zeitfenster</th>
              <th v-for="tier in tierColumns" :key="tier">{{ tierLabel(tier) }}</th>
              <th v-if="OVERNIGHT_ENABLED">Übernachtung</th>
              <th>Gesamt</th>
              <th>Cap</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="slot in headcount.slots" :key="slot.key">
              <td data-label="Zeitfenster">
                <strong>{{ slot.label }}</strong>
                <br />
                <small>{{ formatDateOnly(slot.date) }}</small>
              </td>
              <td v-for="tier in tierColumns" :key="tier" :data-label="tierLabel(tier)">
                {{ slot.by_tier[tier] || 0 }}
              </td>
              <td v-if="OVERNIGHT_ENABLED" data-label="Übernachtung">{{ slot.overnight }}</td>
              <td data-label="Gesamt" :class="{ 'overbooked-cell': slot.overbooked }">
                {{ slot.total }}
                <span v-if="slot.overbooked" class="chip chip-danger">überbucht</span>
              </td>
              <td data-label="Cap">{{ slot.cap ?? '–' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Übernachtung card (Ä15/Ä17/Ä21) — counts are UNITS (Zelte/Camper =
           the real Stellplatz demand). A group may bring both; people who
           sleep over are counted once, separately. -->
      <article v-if="OVERNIGHT_ENABLED" class="accommodation-card">
        <h4>Übernachtung</h4>
        <p>
          Zelte: <strong>{{ headcount.accommodation_totals.TENT.approved_units }}</strong> zugesagt /
          {{ headcount.accommodation_totals.TENT.requested_units }} angefragt
          ·
          Camper: <strong>{{ headcount.accommodation_totals.CAMPER.approved_units }}</strong> zugesagt /
          {{ headcount.accommodation_totals.CAMPER.requested_units }} angefragt
        </p>
        <p class="hint-text">
          Personen mit Übernachtung: {{ headcount.overnight_people.approved }} zugesagt /
          {{ headcount.overnight_people.requested }} angefragt.
          Die zugesagt-Zahlen sind die reale Stellplatz-Nachfrage (Zelte/Camper, inkl. Begleitungen). Zusagen erteilst du auf der Anmeldungs-Übersicht.
        </p>
      </article>

      <!-- Angekommen (Erst-Check-ins) — T313: arrival numbers from the gate
           check-in log, not a live headcount (who's currently here). Only
           rendered when the check-in log has at least one scan. -->
      <article v-if="hasArrivals" class="arrivals-card">
        <h4>Angekommen (Erst-Check-ins)</h4>
        <p>
          <strong>{{ headcount.arrivals.total }}</strong> insgesamt angekommen
        </p>
        <p class="arrivals-chips">
          <span v-for="[day, count] in arrivalsPerDayEntries" :key="day" class="chip chip-neutral">
            {{ formatDateOnly(day) }}: {{ count }}
          </span>
        </p>
        <p class="hint-text">
          Das sind Ankunftszahlen aus dem Einlass-Scan (wer tatsächlich da war), keine tagesaktuelle Anwesenheit.
        </p>
      </article>
    </template>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '../../../services/api'
import { OVERNIGHT_ENABLED } from '../../../config/festival.js'
import PageHeader from '../../../components/PageHeader.vue'
import FestivalHelp from '../../../components/help/FestivalHelp.vue'
import { showToast } from '../../../composables/useToast.js'
import { formatDateOnly } from '../../../utils/formatters.js'

const props = defineProps({
  eventId: { type: String, default: null },
})

const loading = ref(true)
const error = ref(null)
const headcount = ref(null)

// Column order: werft, volunteer, org, open, then other tiers alphabetically,
// unknown last (T207) — mirrors InvitesPage's TIER_LABELS map.
const TIER_ORDER = ['werft', 'volunteer', 'org', 'open']
const TIER_LABELS = {
  werft: 'Werft',
  volunteer: 'Helfer:in',
  org: 'Organisation',
  open: 'Offen',
  unknown: 'ohne Tier',
}

function tierLabel(tier) {
  return TIER_LABELS[tier] || tier
}

const tierColumns = computed(() => {
  if (!headcount.value) return []
  const seen = new Set()
  for (const slot of headcount.value.slots) {
    for (const tier of Object.keys(slot.by_tier || {})) seen.add(tier)
  }
  const known = TIER_ORDER.filter((t) => seen.has(t))
  const rest = [...seen].filter((t) => !TIER_ORDER.includes(t) && t !== 'unknown').sort()
  const unknown = seen.has('unknown') ? ['unknown'] : []
  return [...known, ...rest, ...unknown]
})

const unknownSlotEntries = computed(() => {
  if (!headcount.value) return []
  return Object.entries(headcount.value.unknown_slots || {})
})

// T313: only rendered when the backend actually includes the arrivals
// block (it's omitted when the check-in log is empty).
const hasArrivals = computed(() => !!headcount.value?.arrivals?.total)

const arrivalsPerDayEntries = computed(() => {
  if (!headcount.value?.arrivals) return []
  return Object.entries(headcount.value.arrivals.per_day || {})
})

async function loadHeadcount() {
  loading.value = true
  error.value = null
  try {
    headcount.value = await adminApi.festival.headcount(props.eventId)
  } catch (err) {
    error.value = err.message || 'Laden fehlgeschlagen'
    showToast(err.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

onMounted(loadHeadcount)
</script>

<style scoped>
.error {
  color: var(--color-danger-text);
  padding: 1rem;
  background: var(--color-danger-bg);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.overbooked-banner {
  background: var(--color-danger-bg);
  border-left: 4px solid var(--color-danger-text);
  color: var(--color-danger-text);
  padding: 0.75rem 1rem;
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
}

.summary-line {
  margin-bottom: 1rem;
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.chip {
  display: inline-block;
  margin-left: 0.5rem;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

.chip-warn {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
}

.chip-danger {
  background: var(--color-danger-bg);
  color: var(--color-danger-text);
}

.unknown-slots-card {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  border-radius: var(--radius-md);
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}

.unknown-slots-card h4 {
  margin: 0 0 0.5rem;
}

.unknown-slots-card ul {
  margin: 0.5rem 0 0;
}

.hint-text {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.table-scroll {
  overflow-x: auto;
  margin-bottom: 1.5rem;
}

.overbooked-cell {
  background: var(--color-danger-bg);
  color: var(--color-danger-text);
  font-weight: 600;
}

.accommodation-card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 1rem;
}

.accommodation-card h4 {
  margin: 0 0 0.5rem;
}

.arrivals-card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 1rem;
  margin-top: 1rem;
}

.arrivals-card h4 {
  margin: 0 0 0.5rem;
}

.arrivals-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0.5rem 0;
}

.chip-neutral {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  margin-left: 0;
}
</style>
