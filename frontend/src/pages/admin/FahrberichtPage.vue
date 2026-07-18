<template>
  <section class="container">
    <PageHeader :title="pageTitle" :back="`/admin/events/${eventId}`">
      <template #chip>
        <span v-if="bericht" :class="['chip', statusClass]">
          {{ bericht.status === 'DRAFT' ? 'Entwurf' : 'Eingereicht v' + bericht.version }}
        </span>
      </template>
      <template #actions>
        <span v-if="saveStatus" class="save-indicator" :class="saveStatus">{{ saveLabel }}</span>
      </template>
    </PageHeader>

    <article v-if="loading" aria-busy="true">Laden…</article>
    <template v-else-if="bericht && isReadOnly">
      <SubmittedView
        :event="event"
        :bericht="bericht"
        :report="report"
        :warnings="submitWarnings"
        @reopen="reopen"
        @reapply="reapply"
      />
    </template>
    <template v-else-if="bericht">
      <nav class="tab-nav">
        <button
          v-for="t in tabs"
          :key="t.value"
          :class="['tab', { active: activeTab === t.value }]"
          type="button"
          @click="activeTab = t.value"
        >{{ t.label }}</button>
      </nav>

      <FahrtTab v-show="activeTab === 'fahrt'" v-model:bericht="bericht" :event="event" @save="scheduleSave" />
      <KioskTab v-show="activeTab === 'kiosk'" v-model:bericht="bericht" :catalog="catalog" @save="scheduleSave" />
      <CrewTab v-show="activeTab === 'crew'" v-model:bericht="bericht" :catalog="catalog" @save="scheduleSave" />
      <SchiffTab v-show="activeTab === 'schiff'" v-model:bericht="bericht" @save="scheduleSave" />
      <AbschlussTab
        v-show="activeTab === 'abschluss'"
        v-model:bericht="bericht"
        :event="event"
        :catalog="catalog"
        :catalog-map="catalogMap"
        @save="scheduleSave"
        @submit="submit"
      />

      <TotalBar :kiosk-total="computed.kiosk_total" :crew-cost="computed.crew_cost" :cash-amount="bericht.cash_amount" />
    </template>
  </section>
</template>

<script setup>
import { computed as vueComputed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import FahrtTab from './fahrbericht/FahrtTab.vue'
import KioskTab from './fahrbericht/KioskTab.vue'
import CrewTab from './fahrbericht/CrewTab.vue'
import SchiffTab from './fahrbericht/SchiffTab.vue'
import AbschlussTab from './fahrbericht/AbschlussTab.vue'
import SubmittedView from './fahrbericht/SubmittedView.vue'
import TotalBar from '../../components/fahrbericht/TotalBar.vue'
import { adminApi } from '../../services/api'
import { showToast } from '../../composables/useToast'

const route = useRoute()
const eventId = route.params.eventId

const tabs = [
  { value: 'fahrt', label: 'Fahrt' },
  { value: 'kiosk', label: 'Kiosk' },
  { value: 'crew', label: 'Crew' },
  { value: 'schiff', label: 'Schiff' },
  { value: 'abschluss', label: 'Abschluss' },
]
const activeTab = ref('fahrt')

const bericht = ref(null)
const event = ref(null)
const catalog = ref([])
const report = ref(null)
const submitWarnings = ref([])
const loading = ref(true)
const saveStatus = ref('') // '', 'saving', 'saved', 'error'
let saveTimer = null

const catalogMap = vueComputed(() => Object.fromEntries(catalog.value.map(b => [b.id, b])))

const isReadOnly = vueComputed(() => bericht.value?.status === 'SUBMITTED')
const statusClass = vueComputed(() => (bericht.value?.status === 'SUBMITTED' ? 'chip-ok' : 'chip-muted'))
const pageTitle = vueComputed(() => event.value?.name || 'Fahrbericht')

const computed = vueComputed(() => bericht.value?.computed || {
  kiosk_total: 0, crew_cost: 0, expenses_total: 0, soll: 0, cash_diff: 0,
})

const saveLabel = vueComputed(() => {
  if (saveStatus.value === 'saving') return 'Speichere…'
  if (saveStatus.value === 'saved') return 'Gespeichert'
  if (saveStatus.value === 'error') return 'Fehler'
  return ''
})

async function load() {
  loading.value = true
  try {
    event.value = await adminApi.getEvent(eventId)
    catalog.value = (await adminApi.bar.list({ active: true })).items || []
    try {
      bericht.value = await adminApi.fahrbericht.get(eventId)
    } catch {
      bericht.value = await adminApi.fahrbericht.createDraft(eventId)
    }
    try {
      report.value = await adminApi.reports.getForEvent(eventId)
    } catch {
      report.value = null
    }
  } catch (e) {
    showToast(e?.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

function scheduleSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(flushSave, 800)
}

async function flushSave() {
  if (!bericht.value || bericht.value.status !== 'DRAFT') return
  saveStatus.value = 'saving'
  try {
    const patch = {
      boarding_fee: String(bericht.value.boarding_fee || '0'),
      kiosk_tally: bericht.value.kiosk_tally,
      crew_tally: bericht.value.crew_tally,
      ship_status: bericht.value.ship_status,
      new_notes: bericht.value.new_notes,
      new_todos: bericht.value.new_todos,
      cash_amount: bericht.value.cash_amount != null ? String(bericht.value.cash_amount) : null,
      cash_handed_to: bericht.value.cash_handed_to,
      expenses: bericht.value.expenses,
      duration_hours: bericht.value.duration_hours != null ? String(bericht.value.duration_hours) : null,
      guest_count: bericht.value.guest_count,
      charterer: bericht.value.charterer,
      funker: bericht.value.funker,
      skipper: bericht.value.skipper,
      crew: bericht.value.crew,
    }
    bericht.value = await adminApi.fahrbericht.put(eventId, patch)
    saveStatus.value = 'saved'
    setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = '' }, 2500)
  } catch (e) {
    saveStatus.value = 'error'
    showToast(e?.message || 'Autosave fehlgeschlagen', 'error')
  }
}

async function submit() {
  await flushSave()
  if (!confirm('Fahrbericht einreichen? Dies aktualisiert Bar-Bestand und Schiff-Status und verschickt den Bericht an Finance.')) return
  try {
    const result = await adminApi.fahrbericht.submit(eventId)
    bericht.value = result.fahrbericht
    submitWarnings.value = result.warnings || []
    if (submitWarnings.value.length) {
      submitWarnings.value.forEach(w => showToast(w, 'error'))
    } else {
      showToast('Fahrbericht erfolgreich eingereicht', 'success')
    }
    try {
      report.value = await adminApi.reports.getForEvent(eventId)
    } catch {
      report.value = null
    }
  } catch (e) {
    showToast(e?.message || 'Einreichen fehlgeschlagen', 'error')
  }
}

async function reopen() {
  try {
    bericht.value = await adminApi.fahrbericht.reopen(eventId)
    activeTab.value = 'fahrt'
  } catch (e) {
    showToast(e?.message || 'Wieder öffnen fehlgeschlagen', 'error')
  }
}

async function reapply() {
  try {
    const result = await adminApi.fahrbericht.reapply(eventId)
    submitWarnings.value = result.warnings || []
    if (!submitWarnings.value.length) {
      showToast('Seiteneffekte erneut angewendet', 'success')
    }
    report.value = await adminApi.reports.getForEvent(eventId)
  } catch (e) {
    showToast(e?.message || 'Fehler', 'error')
  }
}

onMounted(load)
onUnmounted(() => clearTimeout(saveTimer))
</script>

<style scoped>
.container { max-width: 720px; margin: 0 auto; padding: var(--space-4) var(--space-4) 100px; }
.tab-nav { display: flex; gap: 4px; overflow-x: auto; border-bottom: 1px solid var(--color-border); margin-bottom: var(--space-4); }
.tab { padding: 10px 14px; border: none; background: transparent; cursor: pointer; color: var(--color-text-muted); border-bottom: 3px solid transparent; font-size: var(--text-sm); white-space: nowrap; }
.tab.active { color: var(--color-brand); border-bottom-color: var(--color-brand); font-weight: 600; }
.chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.chip-ok { background: var(--color-success-bg); color: var(--color-success-text); }
.chip-muted { background: var(--color-neutral-bg); color: var(--color-neutral-text); }
.save-indicator { font-size: 11px; color: var(--color-text-muted); padding: 2px 8px; border-radius: 999px; background: var(--color-neutral-bg); }
.save-indicator.saving { color: var(--color-text-muted); }
.save-indicator.saved { color: var(--color-success-text); background: var(--color-success-bg); }
.save-indicator.error { color: var(--color-danger-text); background: var(--color-danger-bg); }
</style>
