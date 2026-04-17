<template>
  <section class="container">
    <PageHeader :title="isNew ? 'Neues Getränk' : item?.name || 'Getränk'" back="/admin/bar" />
    <article v-if="loading" aria-busy="true">Laden…</article>
    <form v-else class="form" @submit.prevent="save">
      <label>Name
        <input v-model="form.name" type="text" required />
      </label>
      <label>Kategorie
        <select v-model="form.category" required>
          <option v-for="c in categories" :key="c" :value="c">{{ formatBarCategory(c) }}</option>
        </select>
      </label>
      <label>Ausgabe-Einheit (serving)
        <input v-model="form.serving_unit" type="text" required placeholder="z.B. Becher 0,4l" />
      </label>
      <div class="row">
        <label>Gebinde-Einheit (package, optional)
          <input v-model="form.package_unit" type="text" placeholder="z.B. Kiste" />
        </label>
        <label v-if="form.package_unit">Servings pro Gebinde
          <input v-model.number="form.servings_per_package" type="number" min="1" />
        </label>
      </div>
      <div class="row">
        <label>EK / Serving (€)
          <input v-model="form.ek" type="number" min="0" step="0.01" required />
        </label>
        <label>Kiosk / Serving (€)
          <input v-model="form.kb" type="number" min="0" step="0.01" required />
        </label>
      </div>
      <div class="row">
        <label>Soll-Bestand (Servings)
          <input v-model.number="form.expected_amount" type="number" min="0" />
        </label>
        <label>Ist-Bestand (Servings)
          <input v-model.number="form.current_amount" type="number" />
        </label>
      </div>
      <label class="row-flat">
        <input v-model="form.active" type="checkbox" />
        <span>Aktiv (sichtbar in Fahrbericht-Listen)</span>
      </label>
      <label>Notiz
        <input v-model="form.note" type="text" />
      </label>

      <div class="actions">
        <button class="primary" type="submit" :disabled="saving">
          {{ saving ? 'Wird gespeichert…' : 'Speichern' }}
        </button>
        <button v-if="!isNew" class="danger" type="button" @click="remove">Löschen</button>
      </div>
    </form>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import { adminApi } from '../../services/api'
import { formatBarCategory } from '../../utils/formatters'
import { showToast } from '../../composables/useToast'

const route = useRoute()
const router = useRouter()
const isNew = route.params.id === 'new'

const loading = ref(true)
const saving = ref(false)
const item = ref(null)

const categories = ['BIER_FASS', 'BIER_FLASCHE', 'ALKOHOLFREI', 'SEKT_WEIN', 'SOFTES', 'HARTES', 'SHOTS']

const form = reactive({
  name: '',
  category: 'BIER_FLASCHE',
  serving_unit: '',
  package_unit: '',
  servings_per_package: null,
  ek: '0.00',
  kb: '0.00',
  expected_amount: 0,
  current_amount: 0,
  active: true,
  note: '',
})

async function load() {
  loading.value = true
  if (isNew) {
    loading.value = false
    return
  }
  try {
    const data = await adminApi.bar.get(route.params.id)
    item.value = data
    Object.assign(form, {
      name: data.name,
      category: data.category,
      serving_unit: data.serving_unit,
      package_unit: data.package_unit || '',
      servings_per_package: data.servings_per_package,
      ek: data.ek,
      kb: data.kb,
      expected_amount: data.expected_amount,
      current_amount: data.current_amount,
      active: data.active,
      note: data.note || '',
    })
  } catch (e) {
    showToast(e?.message || 'Nicht gefunden', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const body = { ...form }
    if (!body.package_unit) {
      body.package_unit = null
      body.servings_per_package = null
    }
    if (!body.note) body.note = null
    body.ek = String(body.ek)
    body.kb = String(body.kb)
    if (isNew) {
      const created = await adminApi.bar.create(body)
      router.replace(`/admin/bar/${created.id}`)
    } else {
      item.value = await adminApi.bar.patch(route.params.id, body)
    }
    showToast('Gespeichert', 'success')
  } catch (e) {
    showToast(e?.message || 'Speichern fehlgeschlagen', 'error')
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!confirm('Getränk löschen?')) return
  try {
    await adminApi.bar.delete(route.params.id)
    router.replace('/admin/bar')
  } catch (e) {
    showToast(e?.message || 'Löschen fehlgeschlagen', 'error')
  }
}

onMounted(load)
</script>

<style scoped>
.container { max-width: 640px; margin: 0 auto; padding: var(--space-4); }
.form { display: flex; flex-direction: column; gap: var(--space-3); }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
input, select { padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
.row-flat { flex-direction: row; align-items: center; gap: 8px; }
.row-flat input { width: auto; }
.actions { display: flex; gap: 8px; margin-top: var(--space-3); }
.primary { flex: 1; padding: 12px; border-radius: var(--radius-md); border: none; background: var(--color-brand); color: #fff; font-weight: 600; cursor: pointer; }
.danger { padding: 12px; border-radius: var(--radius-md); border: none; background: var(--color-danger-text, #c0392b); color: #fff; font-weight: 600; cursor: pointer; }
@media (max-width: 520px) { .row { grid-template-columns: 1fr; } }
</style>
