<template>
  <section class="container">
    <PageHeader title="Neue Tour" back />
    <form class="form" @submit.prevent="submit">
      <label>Name
        <input v-model="form.name" type="text" :placeholder="eventName || 'z.B. Private Charter'" />
      </label>
      <div class="row">
        <label>Datum
          <input v-model="form.date" type="date" required />
        </label>
        <label>Dauer (h)
          <input v-model.number="form.duration_hours" type="number" min="0" step="0.5" />
        </label>
      </div>
      <div class="row">
        <label>Gäste
          <input v-model.number="form.guest_count" type="number" min="0" />
        </label>
        <label>Charterer
          <input v-model="form.charterer" type="text" placeholder="optional" />
        </label>
      </div>
      <button type="submit" class="primary" :disabled="saving">
        {{ saving ? 'Wird gespeichert…' : 'Tour anlegen' }}
      </button>
    </form>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import { adminApi } from '../../services/api'
import { showToast } from '../../composables/useToast'

const router = useRouter()
const route = useRoute()
const saving = ref(false)
const eventName = ref(null)

const form = reactive({
  event_id: route.query.event_id || null,
  name: '',
  date: new Date().toISOString().slice(0, 10),
  duration_hours: null,
  guest_count: null,
  charterer: '',
})

async function submit() {
  saving.value = true
  try {
    const body = { ...form }
    if (!body.name) delete body.name
    if (!body.duration_hours) delete body.duration_hours
    if (!body.guest_count && body.guest_count !== 0) delete body.guest_count
    if (!body.charterer) delete body.charterer
    if (!body.event_id) delete body.event_id
    const created = await adminApi.tours.create(body)
    router.replace(`/admin/tours/${created.id}`)
  } catch (e) {
    showToast(e?.message || 'Fehler beim Anlegen', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  // If event_id was passed, prefill name/date from the Event.
  if (form.event_id) {
    try {
      const ev = await adminApi.getEvent(form.event_id)
      eventName.value = ev?.name
      if (!form.name) form.name = ev?.name || ''
      if (ev?.start_at) form.date = ev.start_at.slice(0, 10)
    } catch {
      /* non-fatal */
    }
  }
})
</script>

<style scoped>
.container { max-width: 640px; margin: 0 auto; padding: var(--space-4); }
.form { display: flex; flex-direction: column; gap: var(--space-3); }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
input { padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
.primary { margin-top: var(--space-3); }
@media (max-width: 520px) { .row { grid-template-columns: 1fr; } }
</style>
