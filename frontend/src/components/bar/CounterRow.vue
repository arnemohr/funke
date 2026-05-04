<template>
  <div class="counter-row">
    <div class="counter-row__main">
      <div class="counter-row__name">{{ name }}</div>
      <div class="counter-row__meta">
        {{ servingUnit }}<template v-if="note"> · {{ note }}</template>
      </div>
      <div v-if="qty > 0" class="counter-row__subtotal">
        € {{ (qty * price).toFixed(2) }}
      </div>
    </div>
    <div class="counter-row__price" :class="{ 'counter-row__price--crew': emphasis === 'crew' }">
      <div class="counter-row__price-label">{{ priceLabel }}</div>
      <div class="counter-row__price-value">€ {{ Number(price).toFixed(2) }}</div>
      <div v-if="secondaryLabel" class="counter-row__price-secondary">{{ secondaryLabel }}</div>
    </div>
    <div class="counter-row__counter">
      <button type="button" class="cbtn cbtn--minus" :disabled="qty <= 0" @click="$emit('decrement')">−</button>
      <span class="cval" :class="{ 'cval--nonzero': qty > 0 }">{{ qty }}</span>
      <button type="button" class="cbtn cbtn--plus" @click="$emit('increment')">+</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  name: { type: String, required: true },
  servingUnit: { type: String, default: '' },
  note: { type: String, default: '' },
  price: { type: [Number, String], default: 0 },
  priceLabel: { type: String, default: '' },
  secondaryLabel: { type: String, default: '' },
  qty: { type: Number, default: 0 },
  emphasis: { type: String, default: 'kiosk' }, // 'kiosk' | 'crew' | 'admin'
})
defineEmits(['increment', 'decrement'])
</script>

<style scoped>
.counter-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 8px;
  align-items: center;
  background: var(--color-surface-raised);
  border: 1.5px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  margin-bottom: 4px;
}
.counter-row__name { font-size: 14px; font-weight: 600; line-height: 1.3; }
.counter-row__meta { font-size: 11px; color: var(--color-text-muted); margin-top: 2px; }
.counter-row__subtotal {
  font-size: 12px;
  color: var(--color-brand, #2d8c7c);
  font-weight: 700;
  margin-top: 2px;
}
.counter-row__price { text-align: right; min-width: 70px; }
.counter-row__price-label { font-size: 10px; color: var(--color-text-muted); }
.counter-row__price-value {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-brand, #2d8c7c);
}
.counter-row__price--crew .counter-row__price-value {
  color: var(--color-danger-text, #c0392b);
}
.counter-row__price-secondary {
  font-size: 10px;
  color: var(--color-text-muted);
}
.counter-row__counter { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

/* Explicit reset so Pico CSS button defaults (padding, min-width, auto
   height) don't stretch these circles into ovals. */
.cbtn {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 36px;
  height: 36px;
  min-width: 36px;
  padding: 0;
  margin: 0;
  border: 1.5px solid var(--color-border);
  background: var(--color-surface-raised);
  border-radius: 50%;
  font-family: inherit;
  font-size: 20px;
  font-weight: 600;
  line-height: 1;
  color: var(--color-text);
  cursor: pointer;
  user-select: none;
  transition: transform .1s, background .12s, border-color .12s;
  -webkit-tap-highlight-color: transparent;
}
.cbtn:hover:not(:disabled) { background: var(--color-bg-muted); }
.cbtn:active:not(:disabled) { transform: scale(.92); }
.cbtn:focus-visible { outline: 2px solid var(--color-brand); outline-offset: 2px; }
.cbtn:disabled { opacity: 0.35; cursor: not-allowed; }

.cbtn--minus { color: var(--color-danger-text); border-color: var(--color-danger-text); }
.cbtn--minus:hover:not(:disabled) { background: var(--color-danger-bg); border-color: var(--color-danger-text); }
.cbtn--plus { color: var(--color-success-text); border-color: var(--color-success-text); }
.cbtn--plus:hover:not(:disabled) { background: var(--color-success-bg); border-color: var(--color-success-text); }

.cval {
  min-width: 28px;
  text-align: center;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}
.cval--nonzero { color: var(--color-brand, #2d8c7c); }
</style>
