<template>
  <section class="container">
    <PageHeader title="Schaluppe" />
    <article v-if="loading" aria-busy="true">Laden…</article>
    <template v-else-if="state">
      <div class="tiles">
        <div class="tile"><div class="k">Tank 1</div><div class="v">{{ state.tank1_pct ?? '—' }}<span v-if="state.tank1_pct != null">%</span></div>
          <input type="number" min="0" max="100" :value="state.tank1_pct" @change="patch({ tank1_pct: $event.target.value === '' ? null : Number($event.target.value) })" />
        </div>
        <div class="tile"><div class="k">Tank 2</div><div class="v">{{ state.tank2_pct ?? '—' }}<span v-if="state.tank2_pct != null">%</span></div>
          <input type="number" min="0" max="100" :value="state.tank2_pct" @change="patch({ tank2_pct: $event.target.value === '' ? null : Number($event.target.value) })" />
        </div>
        <div class="tile"><div class="k">Kanister an Bord</div><div class="v">{{ state.kanister_aboard ?? '—' }}</div>
          <input type="number" min="0" :value="state.kanister_aboard" @change="patch({ kanister_aboard: $event.target.value === '' ? null : Number($event.target.value) })" />
        </div>
        <div class="tile"><div class="k">Kanister Garage</div><div class="v">{{ state.kanister_garage ?? '—' }}</div>
          <input type="number" min="0" :value="state.kanister_garage" @change="patch({ kanister_garage: $event.target.value === '' ? null : Number($event.target.value) })" />
        </div>
        <div class="tile"><div class="k">Wassertank gefüllt</div><div class="v">{{ state.water_filled_at ?? '—' }}</div>
          <input type="date" :value="state.water_filled_at" @change="patch({ water_filled_at: $event.target.value || null })" />
        </div>
        <div class="tile"><div class="k">CO₂</div><div class="v">{{ state.co2_level ?? '—' }}</div>
          <select :value="state.co2_level || ''" @change="patch({ co2_level: $event.target.value || null })">
            <option value="">—</option>
            <option v-for="l in co2Levels" :key="l" :value="l">{{ l }}</option>
          </select>
        </div>
        <div class="tile"><div class="k">Batterie</div><div class="v">{{ state.battery_pct ?? '—' }}<span v-if="state.battery_pct != null">%</span></div>
          <input type="number" min="0" max="100" :value="state.battery_pct" @change="patch({ battery_pct: $event.target.value === '' ? null : Number($event.target.value) })" />
        </div>
        <div class="tile"><div class="k">Klo 1</div><div class="v">{{ state.klo1_level ?? '—' }}</div>
          <select :value="state.klo1_level || ''" @change="patch({ klo1_level: $event.target.value || null })">
            <option value="">—</option>
            <option v-for="l in kloLevels" :key="l" :value="l">{{ l }}</option>
          </select>
        </div>
        <div class="tile"><div class="k">Klo 2</div><div class="v">{{ state.klo2_level ?? '—' }}</div>
          <select :value="state.klo2_level || ''" @change="patch({ klo2_level: $event.target.value || null })">
            <option value="">—</option>
            <option v-for="l in kloLevels" :key="l" :value="l">{{ l }}</option>
          </select>
        </div>
        <div class="tile"><div class="k">Persennig</div><div class="v">{{ state.persennig_status ?? '—' }}</div>
          <select :value="state.persennig_status || ''" @change="patch({ persennig_status: $event.target.value || null })">
            <option value="">—</option>
            <option v-for="l in persennigLevels" :key="l" :value="l">{{ l }}</option>
          </select>
        </div>
      </div>

      <h3 class="section-title">Offene Todos</h3>
      <div v-if="!state.open_todos.length" class="empty">Alles abgehakt. Gute Fahrt!</div>
      <div v-else class="list-group">
        <div v-for="todo in state.open_todos" :key="todo.id" class="todo-row">
          <input type="checkbox" :checked="todo.done" @change="toggleTodo(todo.id, $event.target.checked)" />
          <span :class="{ done: todo.done }">{{ todo.text }}</span>
          <button class="icon-btn" @click="removeTodo(todo.id)" aria-label="Entfernen"><Trash2 :size="16" /></button>
        </div>
      </div>
      <div class="row-add">
        <input v-model="newTodo" placeholder="Neuer Todo-Eintrag" @keydown.enter.prevent="addTodo" />
        <button class="primary-sm" type="button" @click="addTodo">Hinzufügen</button>
      </div>

      <h3 class="section-title">Notizen</h3>
      <div v-if="!state.general_notes.length" class="empty">Keine Notizen.</div>
      <div v-else class="list-group">
        <div v-for="note in sortedNotes" :key="note.id" class="todo-row">
          <span>{{ note.text }}</span>
          <span class="muted">{{ note.created_at?.slice(0,10) }}</span>
          <button class="icon-btn" @click="removeNote(note.id)" aria-label="Entfernen"><Trash2 :size="16" /></button>
        </div>
      </div>
      <div class="row-add">
        <input v-model="newNote" placeholder="Neue Notiz" @keydown.enter.prevent="addNote" />
        <button class="primary-sm" type="button" @click="addNote">Hinzufügen</button>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Trash2 } from 'lucide-vue-next'
import PageHeader from '../../components/PageHeader.vue'
import { adminApi } from '../../services/api'
import { showToast } from '../../composables/useToast'

const state = ref(null)
const loading = ref(true)
const newTodo = ref('')
const newNote = ref('')

const co2Levels = ['VOLL', 'DREIVIERTEL', 'HALB', 'VIERTEL', 'LEER']
const kloLevels = ['LEER', 'VIERTEL', 'HALB', 'DREIVIERTEL', 'VOLL']
const persennigLevels = ['VOLLSTAENDIG', 'TEILWEISE', 'OFFEN']

const sortedNotes = computed(() => {
  return [...(state.value?.general_notes || [])].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at),
  )
})

async function load() {
  loading.value = true
  try {
    state.value = await adminApi.ship.getState()
  } catch (e) {
    showToast(e?.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

async function patch(fields) {
  try {
    state.value = await adminApi.ship.patchState(fields)
  } catch (e) {
    showToast(e?.message || 'Speichern fehlgeschlagen', 'error')
  }
}

async function addTodo() {
  if (!newTodo.value.trim()) return
  try {
    state.value = await adminApi.ship.addTodo(newTodo.value.trim())
    newTodo.value = ''
  } catch (e) {
    showToast(e?.message || 'Fehler', 'error')
  }
}

async function toggleTodo(id, done) {
  try {
    state.value = await adminApi.ship.patchTodo(id, { done })
  } catch (e) {
    showToast(e?.message || 'Fehler', 'error')
  }
}

async function removeTodo(id) {
  try {
    await adminApi.ship.removeTodo(id)
    await load()
  } catch (e) {
    showToast(e?.message || 'Fehler', 'error')
  }
}

async function addNote() {
  if (!newNote.value.trim()) return
  try {
    state.value = await adminApi.ship.addNote(newNote.value.trim())
    newNote.value = ''
  } catch (e) {
    showToast(e?.message || 'Fehler', 'error')
  }
}

async function removeNote(id) {
  try {
    await adminApi.ship.removeNote(id)
    await load()
  } catch (e) {
    showToast(e?.message || 'Fehler', 'error')
  }
}

onMounted(load)
</script>

<style scoped>
.container { max-width: 720px; margin: 0 auto; padding: var(--space-4); }
.tiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-2); }
.tile { border: 1.5px solid var(--color-border); background: var(--color-surface-raised); border-radius: var(--radius-md); padding: 10px; }
.k { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--color-text-muted); }
.v { font-size: 18px; font-weight: 700; margin: 2px 0 6px; }
.tile input, .tile select { width: 100%; padding: 6px 8px; border: 1px solid var(--color-border); border-radius: 6px; font-size: var(--text-sm); }
.section-title { font-size: var(--text-sm); text-transform: uppercase; color: var(--color-text-muted); margin: var(--space-5) 0 var(--space-2); }
.empty { color: var(--color-text-muted); padding: var(--space-3); text-align: center; }
.todo-row { display: flex; gap: 8px; align-items: center; padding: 8px; background: var(--color-surface-raised); border: 1px solid var(--color-border); border-radius: var(--radius-md); margin-bottom: 4px; }
.todo-row span.done { text-decoration: line-through; color: var(--color-text-muted); }
.muted { color: var(--color-text-muted); font-size: var(--text-sm); margin-left: auto; }
.row-add { display: flex; gap: 8px; margin-top: var(--space-2); }
.row-add input { flex: 1; padding: 10px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); }
.primary-sm { padding: 8px 12px; border: none; background: var(--color-brand); color: #fff; border-radius: var(--radius-md); cursor: pointer; }
.icon-btn { background: transparent; border: none; color: var(--color-danger-text, #c0392b); cursor: pointer; padding: 4px; }
</style>
