<template>
  <div class="panel">
    <div class="section-title">Fahrinfo</div>
    <div class="row">
      <label>Datum
        <input v-model="tourModel.date" type="date" @change="saveTour({ date: tourModel.date })" />
      </label>
      <label>Fahrdauer (h)
        <input v-model.number="tourModel.duration_hours" type="number" step="0.5" @change="saveTour({ duration_hours: tourModel.duration_hours })" />
      </label>
    </div>
    <div class="row">
      <label>Veranstaltungsname
        <input v-model="tourModel.name" type="text" @change="saveTour({ name: tourModel.name })" />
      </label>
      <label>Anzahl Gäste
        <input v-model.number="tourModel.guest_count" type="number" @change="saveTour({ guest_count: tourModel.guest_count })" />
      </label>
    </div>
    <div class="row">
      <label>Umlage Boarding (€)
        <input v-model.number="berichtModel.boarding_fee" type="number" step="0.01" @change="emit('save')" />
      </label>
      <label>Umlage Bar (€)
        <input v-model.number="berichtModel.bar_surcharge" type="number" step="0.01" @change="emit('save')" />
      </label>
    </div>
    <label>Charterer / Veranstalter
      <input v-model="tourModel.charterer" type="text" @change="saveTour({ charterer: tourModel.charterer })" />
    </label>

    <div class="section-title">Crew</div>
    <label class="field-label">Funker*in</label>
    <CrewRefInput v-model="tourModel.funker" role-filter="FUNKER" placeholder="Funker*in" @update:modelValue="saveTour({ funker: $event })" />
    <label class="field-label">Skipper</label>
    <CrewRefInput v-model="tourModel.skipper" role-filter="SKIPPER" placeholder="Skipper" @update:modelValue="saveTour({ skipper: $event })" />
    <label class="field-label">Weitere Crew</label>
    <div v-for="(c, idx) in tourModel.crew" :key="idx" class="crew-row">
      <CrewRefInput :model-value="c" placeholder="Crew-Mitglied" @update:modelValue="val => onCrewUpdate(idx, val)" />
      <button type="button" class="icon-btn" @click="removeCrew(idx)">×</button>
    </div>
    <button type="button" class="ghost" @click="addCrew">+ Crew hinzufügen</button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CrewRefInput from '../../../components/tour/CrewRefInput.vue'

const props = defineProps({
  bericht: { type: Object, required: true },
  tour: { type: Object, required: true },
})
const emit = defineEmits(['update:bericht', 'update:tour', 'save', 'save-tour'])

const berichtModel = computed({
  get: () => props.bericht,
  set: v => emit('update:bericht', v),
})
const tourModel = computed({
  get: () => props.tour,
  set: v => emit('update:tour', v),
})

function saveTour(patch) {
  emit('save-tour', patch)
}

function onCrewUpdate(idx, val) {
  const crew = [...(tourModel.value.crew || [])]
  if (val) crew[idx] = val
  else crew.splice(idx, 1)
  tourModel.value = { ...tourModel.value, crew }
  saveTour({ crew })
}

function removeCrew(idx) {
  const crew = [...(tourModel.value.crew || [])]
  crew.splice(idx, 1)
  tourModel.value = { ...tourModel.value, crew }
  saveTour({ crew })
}

function addCrew() {
  tourModel.value = { ...tourModel.value, crew: [...(tourModel.value.crew || []), { display_name: '', admin_user_id: null }] }
}
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: var(--space-3); }
.section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: var(--color-brand); padding: var(--space-3) 0 4px; border-bottom: 2px solid var(--color-brand); margin-bottom: 6px; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
input { padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); }
.field-label { margin-top: 4px; }
.crew-row { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.icon-btn { background: transparent; border: none; color: var(--color-danger-text, #c0392b); cursor: pointer; font-size: 18px; }
.ghost { background: transparent; border: 1.5px dashed var(--color-border); padding: 10px; border-radius: var(--radius-md); cursor: pointer; color: var(--color-text-muted); }
@media (max-width: 520px) { .row { grid-template-columns: 1fr; } }
</style>
