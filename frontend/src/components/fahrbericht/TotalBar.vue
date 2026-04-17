<template>
  <div class="totalbar">
    <div>
      <div class="t-label">Kiosk Soll</div>
      <div class="t-val">€ {{ fmt(kioskTotal) }}</div>
    </div>
    <div class="t-group">
      <div class="t-label">Crew Kosten</div>
      <div class="t-val">€ {{ fmt(crewCost) }}</div>
    </div>
    <div class="t-group">
      <div class="t-label">Kasse (Ist)</div>
      <div class="t-val">{{ cashAmount != null ? `€ ${fmt(cashAmount)}` : '€ —' }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  kioskTotal: { type: [Number, String], default: 0 },
  crewCost: { type: [Number, String], default: 0 },
  cashAmount: { type: [Number, String], default: null },
})
function fmt(n) { return Number(n || 0).toFixed(2) }
</script>

<style scoped>
.totalbar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #1a2744;
  color: #fff;
  padding: 10px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  z-index: 100;
  box-shadow: 0 -2px 8px rgba(0,0,0,.2);
}
.t-label { font-size: 11px; opacity: 0.65; }
.t-val { font-size: 17px; font-weight: 700; }
.t-group { text-align: right; }
</style>
