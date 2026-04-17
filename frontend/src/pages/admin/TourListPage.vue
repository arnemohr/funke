<template>
  <section class="container">
    <PageHeader title="Touren">
      <template #actions>
        <button class="primary" type="button" @click="goCreate">Neue Tour</button>
      </template>
    </PageHeader>

    <nav class="tab-nav">
      <button
        v-for="f in filters"
        :key="f.value || 'all'"
        type="button"
        :class="['tab', { active: status === f.value }]"
        @click="status = f.value"
      >{{ f.label }}</button>
    </nav>

    <article v-if="loading" aria-busy="true">Laden…</article>
    <article v-else-if="!filtered.length" class="empty">
      Noch keine Touren. Leg die erste an, sobald die Schaluppe ablegt.
    </article>
    <div v-else class="list-group">
      <ListItemButton
        v-for="t in filtered"
        :key="t.id"
        chevron
        @click="goDetail(t.id)"
      >
        <span>{{ formatLabel(t) }}</span>
        <template #detail>
          <span>{{ t.date }}</span>
          <span v-if="crewSummary(t)"> · {{ crewSummary(t) }}</span>
        </template>
        <template #trailing>
          <span :class="['status-badge', `status-${t.status.toLowerCase()}`]">
            {{ formatTourStatus(t.status) }}
          </span>
        </template>
      </ListItemButton>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import ListItemButton from '../../components/ListItemButton.vue'
import { adminApi } from '../../services/api'
import { formatTourStatus } from '../../utils/formatters'
import { showToast } from '../../composables/useToast'

const router = useRouter()
const tours = ref([])
const loading = ref(true)
const status = ref(null)

const filters = [
  { value: null, label: 'Alle' },
  { value: 'PLANNED', label: 'Geplant' },
  { value: 'IN_PROGRESS', label: 'Läuft' },
  { value: 'COMPLETED', label: 'Abgeschlossen' },
  { value: 'ARCHIVED', label: 'Archiviert' },
]

const filtered = computed(() => {
  if (!status.value) return tours.value
  return tours.value.filter(t => t.status === status.value)
})

function formatLabel(t) {
  return t.name || 'Tour ohne Namen'
}

function crewSummary(t) {
  const parts = []
  if (t.funker?.display_name) parts.push(`${t.funker.display_name} (Funker)`)
  if (t.skipper?.display_name) parts.push(`${t.skipper.display_name} (Skipper)`)
  if (t.crew?.length) parts.push(`+${t.crew.length}`)
  return parts.join(' · ')
}

function goCreate() {
  router.push('/admin/tours/new')
}

function goDetail(id) {
  router.push(`/admin/tours/${id}`)
}

async function load() {
  loading.value = true
  try {
    const res = await adminApi.tours.list({ limit: 100 })
    tours.value = res.items || []
  } catch (e) {
    showToast(e?.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.container { max-width: 720px; margin: 0 auto; padding: var(--space-4); }
.tab-nav { display: flex; gap: 4px; overflow-x: auto; margin-bottom: var(--space-3); }
.tab {
  padding: 8px 12px;
  border: none;
  background: transparent;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  border-bottom: 2px solid transparent;
  cursor: pointer;
  white-space: nowrap;
}
.tab.active { color: var(--color-brand); border-bottom-color: var(--color-brand); font-weight: 600; }
.empty { text-align: center; color: var(--color-text-muted); padding: var(--space-6); }
.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .5px;
}
.status-planned { background: #e5e7eb; color: #4b5563; }
.status-in_progress { background: #dbeafe; color: #1d4ed8; }
.status-completed { background: #dcfce7; color: #15803d; }
.status-archived { background: #f5f5f5; color: #9ca3af; }
</style>
