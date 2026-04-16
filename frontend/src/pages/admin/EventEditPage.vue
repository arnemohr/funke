<template>
  <article class="event-edit-page">
    <PageHeader
      :back="backTarget"
      back-label="Zurück"
    >
      <template #title>{{ isNew ? 'Neue Veranstaltung' : 'Veranstaltung bearbeiten' }}</template>
    </PageHeader>

    <div v-if="loading" aria-busy="true">
      Veranstaltung wird geladen…
    </div>

    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <EventForm
      v-else
      :event="event"
      :disabled="submitting"
      :error="submitError"
      :submit-label="isNew ? 'Erstellen' : 'Speichern'"
      :submit-busy-label="isNew ? 'Wird erstellt…' : 'Wird gespeichert…'"
      @submit="handleSubmit"
      @cancel="handleCancel"
    />
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../../services/api'
import EventForm from '../../components/EventForm.vue'
import PageHeader from '../../components/PageHeader.vue'
import { showToast } from '../../composables/useToast.js'

const props = defineProps({
  eventId: { type: String, default: null },
})

const router = useRouter()

const event = ref(null)
const loading = ref(false)
const loadError = ref(null)
const submitting = ref(false)
const submitError = ref(null)

const isNew = computed(() => !props.eventId)

const backTarget = computed(() =>
  isNew.value ? '/admin/events' : `/admin/events/${props.eventId}`,
)

onMounted(async () => {
  if (isNew.value) return
  loading.value = true
  try {
    event.value = await adminApi.getEvent(props.eventId)
  } catch (err) {
    loadError.value = err.message || 'Veranstaltung konnte nicht geladen werden'
  } finally {
    loading.value = false
  }
})

async function handleSubmit(formData) {
  submitting.value = true
  submitError.value = null
  try {
    if (isNew.value) {
      const created = await adminApi.createEvent(formData)
      showToast('Veranstaltung erstellt', 'success')
      router.replace(`/admin/events/${created.id}`)
    } else {
      await adminApi.updateEvent(props.eventId, formData)
      showToast('Änderungen gespeichert', 'success')
      router.replace(`/admin/events/${props.eventId}`)
    }
  } catch (err) {
    submitError.value = err.message || 'Speichern fehlgeschlagen'
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  router.push(backTarget.value)
}
</script>

<style scoped>
.event-edit-page {
  padding-bottom: 2rem;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}
</style>
