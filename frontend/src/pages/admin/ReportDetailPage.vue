<template>
  <section class="container">
    <PageHeader title="Fahrbericht" back="/admin/reports">
      <template #chip>
        <span v-if="meta" :class="['badge', badgeClass]">{{ formatEmailStatus(meta.email_status) }}</span>
      </template>
    </PageHeader>

    <article v-if="loading" aria-busy="true">Laden…</article>
    <template v-else-if="meta && version">
      <div class="versions" v-if="meta.versions?.length > 1">
        <label>Version:
          <select v-model="selectedVersion" @change="loadVersion(Number(selectedVersion))">
            <option v-for="v in meta.versions" :key="v" :value="v">v{{ v }}</option>
          </select>
        </label>
        <span v-if="selectedVersion !== meta.current_version" class="muted">
          Ältere Version — aktuell ist v{{ meta.current_version }}.
        </span>
      </div>

      <div v-if="meta.email_status === 'SKIPPED_NO_RECIPIENT'" class="warn-banner">
        Kein Empfänger konfiguriert. Setz <code>FINANCE_REPORT_INBOX</code> im Backend und drück dann „Erneut senden".
      </div>

      <div class="grid">
        <div class="tile"><div class="k">Datum</div><div class="v">{{ version.tour_snapshot?.date }}</div></div>
        <div class="tile"><div class="k">Tour</div><div class="v">{{ version.tour_snapshot?.name || '—' }}</div></div>
        <div class="tile"><div class="k">Empfänger</div><div class="v">{{ meta.finance_recipient || '—' }}</div></div>
        <div class="tile"><div class="k">Soll</div><div class="v">€ {{ fmt(version.totals?.soll) }}</div></div>
        <div class="tile"><div class="k">Ist</div><div class="v">€ {{ fmt(version.totals?.cash_amount) }}</div></div>
        <div class="tile"><div class="k">Differenz</div><div class="v">€ {{ fmt(version.totals?.cash_diff) }}</div></div>
      </div>

      <h3 class="section-title">Buchungstext</h3>
      <pre class="booking">{{ version.booking_text }}</pre>
      <button class="ghost" @click="copyBooking">📋 Text kopieren</button>

      <h3 class="section-title">Kiosk-Einnahmen</h3>
      <table class="table">
        <thead><tr><th>Getränk</th><th>Menge</th><th>Preis</th><th>Summe</th></tr></thead>
        <tbody>
          <tr v-for="(l, i) in version.kiosk_summary" :key="i">
            <td>{{ l.bar_item_name }}</td>
            <td>{{ l.qty }}</td>
            <td>€ {{ fmt(l.unit_price) }}</td>
            <td>€ {{ fmt(l.line_total) }}</td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">Crew-Verköstigung</h3>
      <table class="table">
        <thead><tr><th>Getränk</th><th>Menge</th><th>EK</th><th>Summe</th></tr></thead>
        <tbody>
          <tr v-for="(l, i) in version.crew_summary" :key="i">
            <td>{{ l.bar_item_name }}</td>
            <td>{{ l.qty }}</td>
            <td>€ {{ fmt(l.unit_price) }}</td>
            <td>€ {{ fmt(l.line_total) }}</td>
          </tr>
        </tbody>
      </table>

      <div class="actions">
        <a class="primary" :href="pdfUrl" target="_blank" rel="noopener">PDF öffnen</a>
        <button class="ghost" type="button" :disabled="sending" @click="resend">
          {{ sending ? 'Sende…' : 'Erneut senden' }}
        </button>
        <router-link class="ghost" :to="`/admin/tours/${meta.tour_id}`">Zur Tour</router-link>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import { adminApi } from '../../services/api'
import { formatEmailStatus } from '../../utils/formatters'
import { showToast } from '../../composables/useToast'

const route = useRoute()
const meta = ref(null)
const version = ref(null)
const loading = ref(true)
const sending = ref(false)
const selectedVersion = ref(null)

const badgeClass = computed(() => ({
  SENT: 'badge-ok', PENDING: 'badge-muted', FAILED: 'badge-err', SKIPPED_NO_RECIPIENT: 'badge-warn',
}[meta.value?.email_status] || 'badge-muted'))

const pdfUrl = computed(() => {
  if (!meta.value) return ''
  return selectedVersion.value === meta.value.current_version
    ? adminApi.reports.pdfUrl(meta.value.id)
    : adminApi.reports.versionPdfUrl(meta.value.id, selectedVersion.value)
})

function fmt(n) { return Number(n || 0).toFixed(2) }

async function loadMeta() {
  loading.value = true
  try {
    meta.value = await adminApi.reports.get(route.params.id)
    selectedVersion.value = meta.value.current_version
    await loadVersion(meta.value.current_version)
  } catch (e) {
    showToast(e?.message || 'Laden fehlgeschlagen', 'error')
  } finally {
    loading.value = false
  }
}

async function loadVersion(v) {
  try {
    version.value = await adminApi.reports.getVersion(route.params.id, v)
  } catch (e) {
    showToast(e?.message || 'Version nicht gefunden', 'error')
  }
}

async function resend() {
  sending.value = true
  try {
    meta.value = await adminApi.reports.resend(meta.value.id)
    showToast('Gesendet (siehe Status)', 'success')
  } catch (e) {
    showToast(e?.message || 'Senden fehlgeschlagen', 'error')
  } finally {
    sending.value = false
  }
}

async function copyBooking() {
  try {
    await navigator.clipboard.writeText(version.value.booking_text)
    showToast('Buchungstext kopiert', 'success')
  } catch {
    showToast('Kopieren fehlgeschlagen', 'error')
  }
}

onMounted(loadMeta)
</script>

<style scoped>
.container { max-width: 720px; margin: 0 auto; padding: var(--space-4); }
.versions { display: flex; gap: 8px; align-items: center; margin-bottom: var(--space-2); }
.versions select { padding: 6px 8px; border: 1.5px solid var(--color-border); border-radius: 6px; }
.muted { color: var(--color-text-muted); font-size: var(--text-sm); }
.warn-banner { background: #fef3c7; border-left: 4px solid #e8a020; padding: 10px 14px; border-radius: 8px; margin-bottom: var(--space-3); color: #7a4e00; font-size: var(--text-sm); }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-2); margin-bottom: var(--space-4); }
.tile { background: #fff; border: 1.5px solid var(--color-border); padding: 10px; border-radius: var(--radius-md); }
.k { font-size: 11px; text-transform: uppercase; color: var(--color-text-muted); }
.v { font-size: 16px; font-weight: 700; margin-top: 2px; }
.section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--color-brand); border-bottom: 2px solid var(--color-brand); padding-bottom: 4px; margin: var(--space-4) 0 var(--space-2); }
.booking { background: #1a1a2e; color: #a0f0c0; border-radius: 8px; padding: 14px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.7; white-space: pre-wrap; }
.table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: var(--text-sm); }
.table th, .table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--color-border); }
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: var(--space-4); }
.primary, .ghost { padding: 10px 16px; border-radius: var(--radius-md); text-decoration: none; cursor: pointer; font-weight: 600; }
.primary { background: var(--color-brand); color: #fff; border: none; }
.ghost { background: transparent; border: 1.5px solid var(--color-border); color: var(--color-text); }
.badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.badge-ok { background: #dcfce7; color: #15803d; }
.badge-err { background: #fdecea; color: #922b21; }
.badge-warn { background: #fef3c7; color: #b45309; }
.badge-muted { background: #f5f5f5; color: #6b7280; }
@media (max-width: 520px) { .grid { grid-template-columns: 1fr 1fr; } }
</style>
