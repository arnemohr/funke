<template>
  <section class="container">
    <PageHeader :title="pageTitle" back="/admin/tours">
      <template #chip>
        <span v-if="tour" :class="['status-badge', `status-${tour.status.toLowerCase()}`]">
          {{ formatTourStatus(tour.status) }}
        </span>
      </template>
    </PageHeader>

    <article v-if="loading" aria-busy="true">Laden…</article>
    <article v-else-if="!tour">Tour nicht gefunden.</article>
    <template v-else>
      <nav class="tabs">
        <button
          v-for="t in tabs"
          :key="t.value"
          :class="['tab', { active: activeTab === t.value }]"
          type="button"
          @click="activeTab = t.value"
        >{{ t.label }}</button>
      </nav>

      <!-- Details -->
      <div v-show="activeTab === 'details'" class="panel">
        <div class="form">
          <label>Name
            <input v-model="tour.name" type="text" @change="savePatch({ name: tour.name })" />
          </label>
          <div class="row">
            <label>Datum
              <input v-model="tour.date" type="date" @change="savePatch({ date: tour.date })" />
            </label>
            <label>Dauer (h)
              <input v-model.number="tour.duration_hours" type="number" step="0.5" @change="savePatch({ duration_hours: tour.duration_hours })" />
            </label>
          </div>
          <div class="row">
            <label>Gäste
              <input v-model.number="tour.guest_count" type="number" @change="savePatch({ guest_count: tour.guest_count })" />
            </label>
            <label>Charterer
              <input v-model="tour.charterer" type="text" @change="savePatch({ charterer: tour.charterer })" />
            </label>
          </div>
          <div class="row">
            <label>Status
              <select v-model="tour.status" @change="savePatch({ status: tour.status })">
                <option v-for="s in allStatuses" :key="s" :value="s">{{ formatTourStatus(s) }}</option>
              </select>
            </label>
          </div>
          <button class="danger" type="button" @click="remove">Tour löschen</button>
        </div>
      </div>

      <!-- Crew -->
      <div v-show="activeTab === 'crew'" class="panel">
        <label class="field-label">Funker*in</label>
        <CrewRefInput v-model="tour.funker" role-filter="FUNKER" placeholder="Funker*in auswählen oder eintragen" @update:modelValue="savePatch({ funker: $event })" />

        <label class="field-label">Skipper</label>
        <CrewRefInput v-model="tour.skipper" role-filter="SKIPPER" placeholder="Skipper auswählen oder eintragen" @update:modelValue="savePatch({ skipper: $event })" />

        <label class="field-label">Weitere Crew</label>
        <div class="crew-list">
          <div v-for="(c, idx) in tour.crew" :key="idx" class="crew-row">
            <CrewRefInput
              :model-value="c"
              placeholder="Crew-Mitglied"
              @update:modelValue="val => updateCrew(idx, val)"
            />
            <button type="button" class="icon-btn" @click="removeCrew(idx)" aria-label="Entfernen">
              <Trash2 :size="16" />
            </button>
          </div>
          <button type="button" class="ghost" @click="addCrew">+ Crew hinzufügen</button>
        </div>
      </div>

      <!-- Fahrbericht -->
      <div v-show="activeTab === 'fahrbericht'" class="panel">
        <div v-if="fahrberichtLoading" aria-busy="true">Laden…</div>
        <div v-else-if="fahrbericht" class="fahrbericht-summary">
          <p class="muted">Status: <strong>{{ formatFahrberichtStatus(fahrbericht.status) }}</strong> · Version {{ fahrbericht.version }}</p>
          <button class="primary" @click="goFahrbericht">Bericht öffnen</button>
          <button v-if="report" class="ghost" @click="goReport">Bericht ansehen (PDF)</button>
        </div>
        <div v-else>
          <p class="muted">Für diese Tour existiert noch kein Fahrbericht.</p>
          <button class="primary" @click="startFahrbericht">Bericht starten</button>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Trash2 } from 'lucide-vue-next'
import PageHeader from '../../components/PageHeader.vue'
import CrewRefInput from '../../components/tour/CrewRefInput.vue'
import { adminApi } from '../../services/api'
import { formatTourStatus, formatFahrberichtStatus } from '../../utils/formatters'
import { showToast } from '../../composables/useToast'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()

const tour = ref(null)
const fahrbericht = ref(null)
const report = ref(null)
const loading = ref(true)
const fahrberichtLoading = ref(false)
const activeTab = ref('details')
const tabs = [
  { value: 'details', label: 'Details' },
  { value: 'crew', label: 'Crew' },
  { value: 'fahrbericht', label: 'Fahrbericht' },
]
const allStatuses = ['PLANNED', 'IN_PROGRESS', 'COMPLETED', 'ARCHIVED']

const pageTitle = computed(() => tour.value?.name || 'Tour')

async function load() {
  loading.value = true
  try {
    tour.value = await adminApi.tours.get(props.id)
  } catch (e) {
    showToast(e?.message || 'Tour nicht gefunden', 'error')
  } finally {
    loading.value = false
  }
}

async function loadFahrbericht() {
  fahrberichtLoading.value = true
  try {
    fahrbericht.value = await adminApi.fahrbericht.get(props.id)
  } catch {
    fahrbericht.value = null
  } finally {
    fahrberichtLoading.value = false
  }
  try {
    report.value = await adminApi.reports.getForTour(props.id)
  } catch {
    report.value = null
  }
}

async function savePatch(patch) {
  try {
    tour.value = await adminApi.tours.patch(props.id, patch)
  } catch (e) {
    showToast(e?.message || 'Speichern fehlgeschlagen', 'error')
  }
}

function updateCrew(idx, val) {
  const crew = [...(tour.value.crew || [])]
  if (val) crew[idx] = val
  else crew.splice(idx, 1)
  tour.value.crew = crew
  savePatch({ crew })
}

function removeCrew(idx) {
  const crew = [...(tour.value.crew || [])]
  crew.splice(idx, 1)
  tour.value.crew = crew
  savePatch({ crew })
}

function addCrew() {
  tour.value.crew = [...(tour.value.crew || []), { display_name: '', admin_user_id: null }]
}

async function remove() {
  if (!confirm('Tour wirklich löschen?')) return
  try {
    await adminApi.tours.delete(props.id)
    router.replace('/admin/tours')
  } catch (e) {
    showToast(e?.message || 'Löschen fehlgeschlagen', 'error')
  }
}

async function startFahrbericht() {
  try {
    await adminApi.fahrbericht.createDraft(props.id)
    goFahrbericht()
  } catch (e) {
    showToast(e?.message || 'Anlegen fehlgeschlagen', 'error')
  }
}

function goFahrbericht() {
  router.push(`/admin/tours/${props.id}/fahrbericht`)
}

function goReport() {
  if (report.value?.id) router.push(`/admin/reports/${report.value.id}`)
}

onMounted(async () => {
  await load()
  await loadFahrbericht()
})
</script>

<style scoped>
.container { max-width: 720px; margin: 0 auto; padding: var(--space-4); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--color-border); margin-bottom: var(--space-3); }
.tab { padding: 8px 14px; border: none; background: transparent; cursor: pointer; color: var(--color-text-muted); border-bottom: 2px solid transparent; }
.tab.active { color: var(--color-brand); border-bottom-color: var(--color-brand); font-weight: 600; }
.panel { margin-bottom: var(--space-6); }
.form { display: flex; flex-direction: column; gap: var(--space-3); }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
input, select { padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
.field-label { margin-top: var(--space-3); display: block; font-size: var(--text-sm); color: var(--color-text-muted); }
.crew-list { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-1); }
.crew-row { display: flex; gap: var(--space-2); align-items: center; }
.icon-btn { background: transparent; border: none; color: var(--color-danger-text, #c0392b); cursor: pointer; padding: 6px; }
.ghost { background: transparent; border: 1.5px dashed var(--color-border); padding: 10px; border-radius: var(--radius-md); cursor: pointer; color: var(--color-text-muted); }
.danger { background: var(--color-danger-text, #c0392b); color: #fff; border: none; border-radius: var(--radius-md); padding: 10px; cursor: pointer; }
.status-badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.status-planned { background: #e5e7eb; color: #4b5563; }
.status-in_progress { background: #dbeafe; color: #1d4ed8; }
.status-completed { background: #dcfce7; color: #15803d; }
.status-archived { background: #f5f5f5; color: #9ca3af; }
.fahrbericht-summary { display: flex; flex-direction: column; gap: var(--space-2); align-items: flex-start; }
.muted { color: var(--color-text-muted); }
@media (max-width: 520px) { .row { grid-template-columns: 1fr; } }
</style>
