<template>
  <button
    type="button"
    class="icon-btn"
    :class="[
      size === 'sm' ? 'icon-btn--sm' : null,
      active ? 'icon-btn--active' : null,
    ]"
    :aria-label="label"
    :aria-pressed="active || undefined"
    :title="label"
    :disabled="disabled || undefined"
    @click="$emit('click', $event)"
  >
    <slot>
      <component v-if="icon" :is="icon" :size="iconSize" aria-hidden="true" />
    </slot>
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  icon: { type: [Object, Function], default: null },
  label: { type: String, required: true },
  active: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  size: { type: String, default: 'md', validator: (v) => ['sm', 'md'].includes(v) },
})

defineEmits(['click'])

const iconSize = computed(() => (props.size === 'sm' ? 18 : 20))
</script>

<style scoped>
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  margin: 0;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-pill);
  color: var(--color-text-muted);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background 0.12s ease, color 0.12s ease;
  flex-shrink: 0;
}

.icon-btn--sm {
  width: 32px;
  height: 32px;
}

.icon-btn:hover,
.icon-btn:focus-visible {
  background: var(--color-bg-muted);
  color: var(--color-brand);
  outline: none;
}

.icon-btn--active {
  background: var(--color-bg-muted);
  color: var(--color-brand);
}

.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
