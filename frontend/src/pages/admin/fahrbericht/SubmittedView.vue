<template>
  <article class="submitted">
    <h3>Fahrbericht eingereicht — Version {{ bericht.version }}</h3>
    <p class="muted">Eingereicht am {{ submittedAt }} von {{ bericht.submitted_by || '—' }}</p>

    <div v-if="warnings.length" class="warnings">
      <strong>Hinweise:</strong>
      <ul><li v-for="(w, i) in warnings" :key="i">{{ w }}</li></ul>
      <button class="ghost" type="button" @click="$emit('reapply')">Seiteneffekte erneut anwenden</button>
    </div>

    <div class="grid">
      <div class="tile"><div class="k">Datum</div><div class="v">{{ dateLabel }}</div></div>
      <div class="tile"><div class="k">Veranstaltung</div><div class="v">{{ event?.name || '—' }}</div></div>
      <div class="tile"><div class="k">Gäste</div><div class="v">{{ bericht.guest_count ?? '—' }}</div></div>
      <div class="tile"><div class="k">Soll Umschlag</div><div class="v">€ {{ fmt(bericht.computed?.soll) }}</div></div>
      <div class="tile"><div class="k">Ist Umschlag</div><div class="v">€ {{ fmt(bericht.cash_amount) }}</div></div>
      <div class="tile"><div class="k">Differenz</div><div class="v">€ {{ fmt(bericht.computed?.cash_diff) }}</div></div>
    </div>

    <div class="actions">
      <button class="primary" type="button" @click="$emit('reopen')">Bearbeiten</button>
      <a v-if="report" class="ghost-btn" :href="pdfUrl" target="_blank" rel="noopener">PDF öffnen</a>
      <router-link v-if="report" class="ghost-btn" :to="`/admin/reports/${report.id}`">Bericht ansehen</router-link>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { adminApi } from '../../../services/api'

const props = defineProps({
  event: { type: Object, default: null },
  bericht: { type: Object, required: true },
  report: { type: Object, default: null },
  warnings: { type: Array, default: () => [] },
})
defineEmits(['reopen', 'reapply'])

const submittedAt = computed(
  () => props.bericht.submitted_at?.slice(0, 16).replace('T', ' ') || '—',
)

const dateLabel = computed(() => {
  if (!props.event?.start_at) return '—'
  return String(props.event.start_at).slice(0, 10)
})

const pdfUrl = computed(
  () => (props.report ? adminApi.reports.pdfUrl(props.report.id) : ''),
)

function fmt(n) { return Number(n || 0).toFixed(2) }
</script>

<style scoped>
.submitted { padding: var(--space-4); background: #fff; border: 1.5px solid var(--color-border); border-radius: var(--radius-md); }
.muted { color: var(--color-text-muted); margin: 0 0 var(--space-3); }
.warnings { background: #fdf6e3; border-left: 4px solid #e8a020; padding: 12px; border-radius: 8px; margin-bottom: var(--space-3); }
.warnings ul { margin: 4px 0 var(--space-2); padding-left: 20px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); margin-bottom: var(--space-3); }
.tile { background: var(--color-bg-muted); padding: 10px; border-radius: 8px; }
.k { font-size: 11px; text-transform: uppercase; color: var(--color-text-muted); }
.v { font-size: 16px; font-weight: 700; margin-top: 2px; }
.actions { display: flex; gap: 8px; margin-top: var(--space-3); flex-wrap: wrap; }
.primary { padding: 12px 18px; border: none; background: var(--color-brand); color: #fff; border-radius: var(--radius-md); font-weight: 600; cursor: pointer; }
.ghost, .ghost-btn { padding: 12px 18px; border: 1.5px solid var(--color-border); background: transparent; border-radius: var(--radius-md); cursor: pointer; text-decoration: none; color: var(--color-text); font-weight: 600; }
</style>
