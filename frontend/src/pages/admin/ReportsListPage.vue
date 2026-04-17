<template>
  <section class="container">
    <PageHeader title="Fahrberichte" back />

    <nav class="tab-nav">
      <button v-for="f in filters" :key="f.value || 'all'" type="button" :class="['tab', { active: filter === f.value }]" @click="filter = f.value">
        {{ f.label }}
      </button>
    </nav>

    <article v-if="loading" aria-busy="true">Laden…</article>
    <article v-else-if="!filtered.length" class="empty">
      Noch keine Berichte. Der erste wird nach Abschluss einer Fahrt hier auftauchen.
    </article>
    <ListItemButton v-for="r in filtered" v-else :key="r.id" chevron @click="goDetail(r.id)">
      <span>v{{ r.current_version }} · {{ r.finance_recipient || 'kein Empfänger' }}</span>
      <template #detail>
        <span>{{ r.updated_at?.slice(0, 10) }}</span>
      </template>
      <template #trailing>
        <span :class="['badge', badgeClass(r.email_status)]">{{ formatEmailStatus(r.email_status) }}</span>
      </template>
    </ListItemButton>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import ListItemButton from '../../components/ListItemButton.vue'
import { adminApi } from '../../services/api'
import { formatEmailStatus } from '../../utils/formatters'
import { showToast } from '../../composables/useToast'

const router = useRouter()
const reports = ref([])
const loading = ref(true)
const filter = ref(null)

const filters = [
  { value: null, label: 'Alle' },
  { value: 'SENT', label: 'Versendet' },
  { value: 'FAILED', label: 'Fehler' },
  { value: 'SKIPPED_NO_RECIPIENT', label: 'Ohne Empfänger' },
]

const filtered = computed(() => {
  if (!filter.value) return reports.value
  return reports.value.filter(r => r.email_status === filter.value)
})

function badgeClass(s) {
  return {
    SENT: 'badge-ok',
    PENDING: 'badge-muted',
    FAILED: 'badge-err',
    SKIPPED_NO_RECIPIENT: 'badge-warn',
  }[s] || 'badge-muted'
}

async function load() {
  loading.value = true
  try {
    const res = await adminApi.reports.list({ limit: 100 })
    reports.value = res.items || []
  } catch (e) {
    showToast(e?.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

function goDetail(id) { router.push(`/admin/reports/${id}`) }

onMounted(load)
</script>

<style scoped>
.container { max-width: 720px; margin: 0 auto; padding: var(--space-4); }
.tab-nav { display: flex; gap: 4px; overflow-x: auto; margin-bottom: var(--space-3); }
.tab { padding: 8px 12px; border: none; background: transparent; cursor: pointer; color: var(--color-text-muted); border-bottom: 2px solid transparent; white-space: nowrap; }
.tab.active { color: var(--color-brand); border-bottom-color: var(--color-brand); font-weight: 600; }
.empty { text-align: center; color: var(--color-text-muted); padding: var(--space-6); }
.badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.badge-ok { background: #dcfce7; color: #15803d; }
.badge-err { background: #fdecea; color: #922b21; }
.badge-warn { background: #fef3c7; color: #b45309; }
.badge-muted { background: #f5f5f5; color: #6b7280; }
</style>
