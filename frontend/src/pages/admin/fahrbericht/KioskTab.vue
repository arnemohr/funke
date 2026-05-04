<template>
  <div class="panel">
    <div class="infobox">
      🛒 <strong>Selbstbedienungs-Kiosk:</strong> Wie viele Einheiten haben Gäste entnommen? Summe = Soll-Betrag im Kassenbuch.
    </div>
    <p class="section-total">Kiosk Soll: <strong>€ {{ total.toFixed(2) }}</strong></p>
    <template v-for="group in grouped" :key="group.category">
      <h3 class="cat-label">{{ formatBarCategory(group.category) }}</h3>
      <CounterRow
        v-for="item in group.items"
        :key="item.id"
        :name="item.name"
        :serving-unit="item.serving_unit"
        :note="item.note"
        :price="Number(item.kb)"
        price-label="Kiosk"
        :secondary-label="'EK € ' + Number(item.ek).toFixed(2)"
        :qty="qty(item.id)"
        emphasis="kiosk"
        @increment="change(item.id, 1)"
        @decrement="change(item.id, -1)"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CounterRow from '../../../components/bar/CounterRow.vue'
import { formatBarCategory } from '../../../utils/formatters'

const props = defineProps({
  bericht: { type: Object, required: true },
  catalog: { type: Array, required: true },
})
const emit = defineEmits(['update:bericht', 'save'])

const grouped = computed(() => {
  const groups = new Map()
  for (const item of props.catalog) {
    if (!groups.has(item.category)) groups.set(item.category, [])
    groups.get(item.category).push(item)
  }
  return [...groups.entries()].map(([category, items]) => ({ category, items }))
})

const total = computed(() => {
  let t = 0
  for (const [bid, q] of Object.entries(props.bericht.kiosk_tally || {})) {
    const bar = props.catalog.find(b => b.id === bid)
    if (bar) t += q * Number(bar.kb)
  }
  return t
})

function qty(id) {
  return (props.bericht.kiosk_tally || {})[id] || 0
}

function change(id, delta) {
  const tally = { ...(props.bericht.kiosk_tally || {}) }
  tally[id] = Math.max(0, (tally[id] || 0) + delta)
  if (!tally[id]) delete tally[id]
  emit('update:bericht', { ...props.bericht, kiosk_tally: tally })
  emit('save')
}
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: var(--space-2); }
.infobox { background: var(--color-info-subtle-bg); border-left: 3px solid var(--color-brand); padding: 10px 13px; border-radius: 0 8px 8px 0; font-size: 13px; color: var(--color-info-subtle-text); margin-bottom: 8px; line-height: 1.5; }
.section-total { text-align: right; font-size: var(--text-sm); color: var(--color-text-muted); }
.cat-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--color-text-muted); padding: 12px 0 6px; margin: 0; }
</style>
