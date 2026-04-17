<template>
  <section class="container">
    <PageHeader title="Bar">
      <template #actions>
        <button class="primary" type="button" @click="goNew">Neues Getränk</button>
      </template>
    </PageHeader>

    <div class="toolbar">
      <button v-if="!items.length" class="ghost" type="button" @click="seed">Katalog mit Standardsortiment füllen</button>
      <button class="ghost" type="button" @click="load">Neu laden</button>
    </div>

    <article v-if="loading" aria-busy="true">Laden…</article>
    <article v-else-if="!items.length" class="empty">Noch keine Getränke.</article>
    <template v-else>
      <div v-for="group in grouped" :key="group.category" class="group">
        <h3 class="group-title">{{ formatBarCategory(group.category) }} <span class="group-count">({{ group.items.length }})</span></h3>
        <div class="list-group">
          <ListItemButton v-for="item in group.items" :key="item.id" chevron @click="goEdit(item.id)">
            <span>{{ item.name }}</span>
            <template #detail>
              <span>{{ item.serving_unit }} · EK € {{ Number(item.ek).toFixed(2) }} · Kiosk € {{ Number(item.kb).toFixed(2) }}</span>
              <span class="stock-line">{{ formatStock(item) }}</span>
            </template>
            <template #trailing>
              <span v-if="item.low_stock" class="badge warn">Bestand niedrig</span>
              <span v-if="!item.active" class="badge muted">Inaktiv</span>
            </template>
          </ListItemButton>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import ListItemButton from '../../components/ListItemButton.vue'
import { adminApi } from '../../services/api'
import { formatBarCategory } from '../../utils/formatters'
import { formatStock } from '../../utils/barStock'
import { showToast } from '../../composables/useToast'

const router = useRouter()
const items = ref([])
const loading = ref(true)

const grouped = computed(() => {
  const groups = new Map()
  for (const it of items.value) {
    if (!groups.has(it.category)) groups.set(it.category, [])
    groups.get(it.category).push(it)
  }
  return [...groups.entries()].map(([category, items]) => ({ category, items }))
})

async function load() {
  loading.value = true
  try {
    const res = await adminApi.bar.list()
    items.value = res.items || []
  } catch (e) {
    showToast(e?.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

async function seed() {
  try {
    const res = await adminApi.bar.seed()
    showToast(`${res.inserted} Getränke neu angelegt, ${res.skipped} übersprungen`, 'success')
    await load()
  } catch (e) {
    showToast(e?.message || 'Seed fehlgeschlagen', 'error')
  }
}

function goNew() { router.push('/admin/bar/new') }
function goEdit(id) { router.push(`/admin/bar/${id}`) }

onMounted(load)
</script>

<style scoped>
.container { max-width: 720px; margin: 0 auto; padding: var(--space-4); }
.toolbar { display: flex; gap: 8px; margin-bottom: var(--space-3); }
.group { margin-bottom: var(--space-5); }
.group-title { font-size: var(--text-sm); text-transform: uppercase; letter-spacing: 1px; color: var(--color-text-muted); margin: 0 0 8px; }
.group-count { opacity: 0.6; }
.empty { text-align: center; color: var(--color-text-muted); padding: var(--space-6); }
.stock-line { display: block; margin-top: 2px; font-size: 11px; color: var(--color-text-muted); }
.badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.badge.warn { background: #fef3c7; color: #b45309; }
.badge.muted { background: #f5f5f5; color: #9ca3af; }
.ghost { background: transparent; border: 1.5px dashed var(--color-border); padding: 8px 14px; border-radius: var(--radius-md); cursor: pointer; color: var(--color-text-muted); font-size: var(--text-sm); }
</style>
