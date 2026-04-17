<template>
  <section class="container">
    <PageHeader title="Mein Profil" back />
    <article v-if="loading" aria-busy="true">Laden…</article>
    <template v-else-if="profile">
      <form class="form" @submit.prevent="save">
        <label>Anzeigename
          <input v-model="profile.display_name" type="text" placeholder="Wie soll dein Name im Fahrbericht erscheinen?" />
        </label>
        <fieldset>
          <legend>Ich kann an Bord:</legend>
          <label v-for="role in allRoles" :key="role" class="checkbox">
            <input type="checkbox" :checked="profile.crew_roles.includes(role)" @change="toggleRole(role, $event.target.checked)" />
            <span>{{ formatCrewRole(role) }}</span>
          </label>
        </fieldset>
        <button class="primary" type="submit" :disabled="saving">
          {{ saving ? 'Wird gespeichert…' : 'Speichern' }}
        </button>
      </form>
    </template>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import { adminApi } from '../../services/api'
import { formatCrewRole } from '../../utils/formatters'
import { showToast } from '../../composables/useToast'

const loading = ref(true)
const saving = ref(false)
const profile = ref(null)
const allRoles = ['FUNKER', 'SKIPPER', 'BARCREW', 'BOARDING', 'ALLROUNDER']

async function load() {
  loading.value = true
  try {
    profile.value = await adminApi.getProfile()
    if (!profile.value.crew_roles) profile.value.crew_roles = []
  } catch (e) {
    showToast(e?.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

function toggleRole(role, checked) {
  const set = new Set(profile.value.crew_roles)
  if (checked) set.add(role)
  else set.delete(role)
  profile.value.crew_roles = [...set]
}

async function save() {
  saving.value = true
  try {
    profile.value = await adminApi.updateProfile({
      display_name: profile.value.display_name,
      crew_roles: profile.value.crew_roles,
    })
    showToast('Profil gespeichert', 'success')
  } catch (e) {
    showToast(e?.message || 'Fehler beim Speichern', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.container { max-width: 560px; margin: 0 auto; padding: var(--space-4); }
.form { display: flex; flex-direction: column; gap: var(--space-3); }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
input[type="text"] { padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); }
fieldset { border: 1.5px solid var(--color-border); border-radius: var(--radius-md); padding: 12px; display: flex; flex-direction: column; gap: 8px; }
legend { font-size: var(--text-sm); color: var(--color-text-muted); padding: 0 4px; }
.checkbox { display: flex; align-items: center; gap: 8px; flex-direction: row; color: var(--color-text); }
.primary { padding: 12px; border-radius: var(--radius-md); border: none; background: var(--color-brand); color: #fff; font-weight: 600; cursor: pointer; }
</style>
