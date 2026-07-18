<template>
  <div class="panel">
    <div class="section-title">Fahrinfo</div>
    <div class="row">
      <div class="readonly-field">
        <label>Datum</label>
        <div class="readonly-value">{{ formatEventDate(event?.start_at) || '—' }}</div>
      </div>
      <div class="readonly-field">
        <label>Veranstaltung</label>
        <div class="readonly-value">{{ event?.name || '—' }}</div>
      </div>
    </div>
    <div class="row">
      <label>Fahrdauer (h)
        <input v-model.number="berichtModel.duration_hours" type="number" step="0.5" @change="emit('save')" />
      </label>
      <label>Anzahl Gäste
        <input v-model.number="berichtModel.guest_count" type="number" @change="emit('save')" />
      </label>
    </div>
    <div class="row">
      <label>Umlage Boarding (€)
        <input v-model.number="berichtModel.boarding_fee" type="number" step="0.01" @change="emit('save')" />
      </label>
      <div class="readonly-field">
        <label>Umlage Bar (€)</label>
        <div class="readonly-value">€ {{ fmtSurcharge(barSurcharge) }}</div>
        <small class="hint">= Kiosk + Crew, automatisch aus Strichliste</small>
      </div>
    </div>
    <label>Charterer / Veranstalter
      <input v-model="berichtModel.charterer" type="text" @change="emit('save')" />
    </label>

    <div class="section-title">Crew</div>
    <label class="field-label">Funker*in</label>
    <CrewRefInput
      :model-value="berichtModel.funker"
      role-filter="FUNKER"
      placeholder="Funker*in"
      @update:modelValue="val => { berichtModel.funker = val; emit('save') }"
    />
    <label class="field-label">Skipper</label>
    <CrewRefInput
      :model-value="berichtModel.skipper"
      role-filter="SKIPPER"
      placeholder="Skipper"
      @update:modelValue="val => { berichtModel.skipper = val; emit('save') }"
    />
    <label class="field-label">Weitere Crew</label>
    <div v-for="(c, idx) in (berichtModel.crew || [])" :key="idx" class="crew-row">
      <CrewRefInput
        :model-value="c"
        placeholder="Crew-Mitglied"
        @update:modelValue="val => onCrewUpdate(idx, val)"
      />
      <button type="button" class="icon-btn" @click="removeCrew(idx)">×</button>
    </div>
    <button type="button" class="ghost" @click="addCrew">+ Crew hinzufügen</button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CrewRefInput from '../../../components/tour/CrewRefInput.vue'
import { formatDate } from '../../../utils/formatters'

const props = defineProps({
  bericht: { type: Object, required: true },
  event: { type: Object, default: null },
})
const emit = defineEmits(['update:bericht', 'save'])

const berichtModel = computed({
  get: () => props.bericht,
  set: v => emit('update:bericht', v),
})

const barSurcharge = computed(() => Number(props.bericht?.computed?.bar_surcharge || 0))

function fmtSurcharge(n) {
  return Number(n || 0).toFixed(2)
}

function formatEventDate(dateStr) {
  return formatDate(dateStr, '—')
}

function onCrewUpdate(idx, val) {
  const crew = [...(berichtModel.value.crew || [])]
  if (val) crew[idx] = val
  else crew.splice(idx, 1)
  berichtModel.value = { ...berichtModel.value, crew }
  emit('save')
}

function removeCrew(idx) {
  const crew = [...(berichtModel.value.crew || [])]
  crew.splice(idx, 1)
  berichtModel.value = { ...berichtModel.value, crew }
  emit('save')
}

function addCrew() {
  berichtModel.value = {
    ...berichtModel.value,
    crew: [...(berichtModel.value.crew || []), { display_name: '', admin_user_id: null }],
  }
}
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: var(--space-3); }
.section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: var(--color-brand); padding: var(--space-3) 0 4px; border-bottom: 2px solid var(--color-brand); margin-bottom: 6px; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
input { padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); }
.readonly-field { display: flex; flex-direction: column; gap: 4px; }
.readonly-field label { font-size: var(--text-sm); color: var(--color-text-muted); }
.readonly-value { padding: 10px 12px; border-radius: var(--radius-md); background: var(--color-bg-muted); font-size: var(--text-base); font-weight: 500; }
.hint { font-size: 11px; color: var(--color-text-muted); }
.field-label { margin-top: 4px; }
.crew-row { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.icon-btn { background: transparent; border: none; color: var(--color-danger-text, #c0392b); cursor: pointer; font-size: 18px; }
.ghost { background: transparent; border: 1.5px dashed var(--color-border); padding: 10px; border-radius: var(--radius-md); cursor: pointer; color: var(--color-text-muted); }
@media (max-width: 520px) { .row { grid-template-columns: 1fr; } }
</style>
