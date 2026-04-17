<template>
  <div class="panel">
    <div class="section-title">Kasse</div>
    <div class="row">
      <label>Bargeld im Umschlag (€)
        <input v-model.number="cashAmount" type="number" step="0.01" @change="emitSave" />
      </label>
      <label>Übergeben an
        <input v-model="cashHandedTo" type="text" @change="emitSave" />
      </label>
    </div>

    <div class="section-title">Ausgaben während Fahrt</div>
    <div v-for="(e, idx) in bericht.expenses" :key="idx" class="expense-row">
      <input v-model="e.description" type="text" placeholder="Beschreibung" @change="emitSave" />
      <input v-model.number="e.amount" type="number" step="0.01" placeholder="€" @change="emitSave" />
      <button type="button" class="icon-btn" @click="removeExpense(idx)">×</button>
    </div>
    <button type="button" class="ghost" @click="addExpense">+ Ausgabe hinzufügen</button>

    <div class="section-title">Zusammenfassung</div>
    <div class="sum-card">
      <div class="sum-line"><span>Kiosk Einnahmen</span><span class="amt">€ {{ fmt(computed.kiosk_total) }}</span></div>
      <div class="sum-line"><span>Umlage Boarding</span><span class="amt">€ {{ fmt(bericht.boarding_fee) }}</span></div>
      <div class="sum-line"><span>Umlage Bar</span><span class="amt">€ {{ fmt(bericht.bar_surcharge) }}</span></div>
      <div class="sum-line total"><span>Soll Umschlag</span><span class="pos">€ {{ fmt(computed.soll) }}</span></div>
      <div class="sum-line"><span>Ist Umschlag</span><span class="amt">€ {{ fmt(bericht.cash_amount) }}</span></div>
      <div class="sum-line total"><span>Differenz</span><span :class="diffClass">€ {{ computed.cash_diff >= 0 ? '+' : '' }}{{ fmt(computed.cash_diff) }} {{ diffBadge }}</span></div>
    </div>
    <div class="sum-card">
      <div class="sum-line"><span>Wareneinsatz Crew</span><span class="neg">€ {{ fmt(computed.crew_cost) }}</span></div>
      <div class="sum-line"><span>Sonstige Ausgaben</span><span class="neg">€ {{ fmt(computed.expenses_total) }}</span></div>
    </div>

    <div class="section-title">Buchungstext für Leasy / NetXp</div>
    <pre class="booking">{{ bookingText }}</pre>
    <button type="button" class="ghost" @click="copyBooking">📋 Text kopieren</button>

    <button class="submit-btn" type="button" @click="$emit('submit')">
      {{ isResubmit ? 'Aktualisierung einreichen' : 'Fahrbericht einreichen' }}
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { buildBookingText } from '../../../utils/bookingText'
import { showToast } from '../../../composables/useToast'

const props = defineProps({
  bericht: { type: Object, required: true },
  tour: { type: Object, required: true },
  catalog: { type: Array, required: true },
  catalogMap: { type: Object, required: true },
})
const emit = defineEmits(['update:bericht', 'save', 'submit'])

const computed_ = computed(() => props.bericht.computed || {
  kiosk_total: 0, crew_cost: 0, expenses_total: 0, soll: 0, cash_diff: 0,
})

const cashAmount = computed({
  get: () => props.bericht.cash_amount,
  set: v => emit('update:bericht', { ...props.bericht, cash_amount: v || null }),
})
const cashHandedTo = computed({
  get: () => props.bericht.cash_handed_to,
  set: v => emit('update:bericht', { ...props.bericht, cash_handed_to: v || null }),
})

const bookingText = computed(() => buildBookingText({
  bericht: props.bericht,
  tour: props.tour,
  catalog: props.catalogMap,
}))

const isResubmit = computed(() => (props.bericht.version || 0) >= 1)

const diffClass = computed(() => {
  const d = Math.abs(Number(computed_.value.cash_diff) || 0)
  if (d < 0.5) return 'pos'
  if (d < 5) return 'warn'
  return 'neg'
})
const diffBadge = computed(() => {
  const d = Number(computed_.value.cash_diff) || 0
  if (Math.abs(d) < 0.5) return '✅ passt'
  if (d > 0) return '⬆️ Überschuss'
  return '⚠️ Fehlbetrag'
})

function fmt(n) { return Number(n || 0).toFixed(2) }

const emitSave = () => emit('save')

function addExpense() {
  emit('update:bericht', {
    ...props.bericht,
    expenses: [...(props.bericht.expenses || []), { description: '', amount: 0 }],
  })
  emit('save')
}

function removeExpense(idx) {
  const expenses = [...(props.bericht.expenses || [])]
  expenses.splice(idx, 1)
  emit('update:bericht', { ...props.bericht, expenses })
  emit('save')
}

async function copyBooking() {
  try {
    await navigator.clipboard.writeText(bookingText.value)
    showToast('Buchungstext kopiert', 'success')
  } catch {
    showToast('Kopieren fehlgeschlagen', 'error')
  }
}

// expose computed totals for parent through v-model side-effect indirectly
defineExpose({ computed: computed_ })
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: var(--space-2); }
.section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: var(--color-brand); padding: var(--space-3) 0 4px; border-bottom: 2px solid var(--color-brand); margin: 10px 0 8px; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-sm); color: var(--color-text-muted); }
input { padding: 10px 12px; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--text-base); }
.expense-row { display: grid; grid-template-columns: 1fr 90px auto; gap: 8px; margin-bottom: 6px; align-items: center; }
.icon-btn { background: transparent; border: none; color: var(--color-danger-text, #c0392b); cursor: pointer; font-size: 18px; }
.ghost { background: transparent; border: 1.5px dashed var(--color-border); padding: 10px; border-radius: var(--radius-md); cursor: pointer; color: var(--color-text-muted); width: 100%; }
.sum-card { background: #fff; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); padding: 14px; margin-bottom: var(--space-2); }
.sum-line { display: flex; justify-content: space-between; padding: 6px 0; font-size: var(--text-base); border-bottom: 1px solid var(--color-bg-muted); }
.sum-line:last-child { border: none; }
.sum-line.total { font-weight: 700; padding-top: 10px; margin-top: 6px; border-top: 2px solid var(--color-border); }
.pos { color: #15803d; font-weight: 700; }
.neg { color: #c0392b; font-weight: 700; }
.warn { color: #d97706; font-weight: 700; }
.booking { background: #1a1a2e; color: #a0f0c0; border-radius: 8px; padding: 14px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.7; white-space: pre-wrap; margin: 8px 0; }
.submit-btn { margin-top: var(--space-4); padding: 14px; background: var(--color-brand); color: #fff; border: none; border-radius: var(--radius-md); font-weight: 700; font-size: var(--text-base); cursor: pointer; }
@media (max-width: 520px) { .row { grid-template-columns: 1fr; } }
</style>
