<template>
  <div class="panel">
    <div class="section-title">Kraftstoff</div>
    <div class="tiles">
      <div class="tile">
        <label>Tank 1 vorne (%)</label>
        <input v-model.number="ship.tank1_pct" type="number" min="0" max="100" placeholder="0-100" @change="saveBericht" />
      </div>
      <div class="tile">
        <label>Tank 2 hinten (%)</label>
        <input v-model.number="ship.tank2_pct" type="number" min="0" max="100" @change="saveBericht" />
      </div>
      <div class="tile">
        <label>Volle Kanister an Bord</label>
        <input v-model.number="ship.kanister_aboard" type="number" min="0" @change="saveBericht" />
      </div>
      <div class="tile">
        <label>Volle Kanister Garage</label>
        <input v-model.number="ship.kanister_garage" type="number" min="0" @change="saveBericht" />
      </div>
    </div>

    <div class="section-title">Technik &amp; Sanitär</div>
    <div class="tiles">
      <div class="tile">
        <label>Wassertank gefüllt</label>
        <input type="date" :value="ship.water_filled_at" @change="onWaterChange($event.target.value)" />
      </div>
      <div class="tile">
        <label>CO₂ Stand</label>
        <select v-model="ship.co2_level" @change="saveBericht">
          <option value="">—</option>
          <option v-for="l in co2" :key="l" :value="l">{{ l }}</option>
        </select>
      </div>
      <div class="tile">
        <label>Batterie (%)</label>
        <input v-model.number="ship.battery_pct" type="number" min="0" max="100" @change="saveBericht" />
      </div>
      <div class="tile">
        <label>Klo Tonne 1</label>
        <select v-model="ship.klo1_level" @change="saveBericht">
          <option value="">—</option>
          <option v-for="l in klo" :key="l" :value="l">{{ l }}</option>
        </select>
      </div>
      <div class="tile">
        <label>Klo Tonne 2</label>
        <select v-model="ship.klo2_level" @change="saveBericht">
          <option value="">—</option>
          <option v-for="l in klo" :key="l" :value="l">{{ l }}</option>
        </select>
      </div>
      <div class="tile">
        <label>Persennig</label>
        <select v-model="ship.persennig_status" @change="saveBericht">
          <option value="">—</option>
          <option v-for="l in persennig" :key="l" :value="l">{{ l }}</option>
        </select>
      </div>
    </div>

    <div class="section-title">Anmerkungen</div>
    <label>Schäden / Besonderes / Fehlendes (je Zeile ein Eintrag)
      <textarea :value="notesText" @input="onNotesChange($event.target.value)"></textarea>
    </label>
    <label>Noch zu erledigende Aufgaben (je Zeile ein Eintrag)
      <textarea :value="todosText" @input="onTodosChange($event.target.value)"></textarea>
    </label>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  bericht: { type: Object, required: true },
})
const emit = defineEmits(['update:bericht', 'save'])

const co2 = ['VOLL', 'DREIVIERTEL', 'HALB', 'VIERTEL', 'LEER']
const klo = ['LEER', 'VIERTEL', 'HALB', 'DREIVIERTEL', 'VOLL']
const persennig = ['VOLLSTAENDIG', 'TEILWEISE', 'OFFEN']

const ship = computed(() => props.bericht.ship_status || {})

const notesText = computed(() => (props.bericht.new_notes || []).join('\n'))
const todosText = computed(() => (props.bericht.new_todos || []).join('\n'))

function saveBericht() {
  emit('update:bericht', { ...props.bericht, ship_status: { ...ship.value } })
  emit('save')
}

function onWaterChange(v) {
  emit('update:bericht', {
    ...props.bericht,
    ship_status: { ...ship.value, water_filled_at: v || null },
  })
  emit('save')
}

function onNotesChange(text) {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
  emit('update:bericht', { ...props.bericht, new_notes: lines })
  emit('save')
}

function onTodosChange(text) {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
  emit('update:bericht', { ...props.bericht, new_todos: lines })
  emit('save')
}
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: var(--space-2); }
.section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: var(--color-brand); padding: var(--space-3) 0 4px; border-bottom: 2px solid var(--color-brand); margin: 10px 0 8px; }
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
.tile { border: 1.5px solid var(--color-border); background: var(--color-surface-raised); border-radius: var(--radius-md); padding: 12px; }
.tile label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px; color: var(--color-text-muted); display: block; margin-bottom: 6px; }
.tile input, .tile select { width: 100%; padding: 7px 9px; border: 1px solid var(--color-border); border-radius: 6px; font-size: var(--text-base); }
textarea { width: 100%; min-height: 80px; padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); resize: vertical; }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
</style>
