<template>
  <component
    :is="tag"
    class="li-btn"
    :class="[
      variant !== 'default' ? `li-btn--${variant}` : null,
      { 'li-btn--static': variant === 'static' },
    ]"
    :href="tag === 'a' ? href : undefined"
    :type="tag === 'button' ? 'button' : undefined"
    :disabled="tag === 'button' && disabled ? true : undefined"
    :aria-disabled="disabled || undefined"
    @click="onClick"
  >
    <span v-if="$slots.icon || icon" class="li-btn__icon" aria-hidden="true">
      <slot name="icon">
        <component :is="icon" :size="20" />
      </slot>
    </span>
    <span class="li-btn__label">
      <span class="li-btn__title">
        <slot />
      </span>
      <span v-if="$slots.detail" class="li-btn__detail">
        <slot name="detail" />
      </span>
    </span>
    <span v-if="$slots.trailing || chevron" class="li-btn__trailing">
      <slot name="trailing" />
      <ChevronRight v-if="chevron" :size="18" aria-hidden="true" class="li-btn__chevron" />
    </span>
  </component>
</template>

<script setup>
import { ChevronRight } from 'lucide-vue-next'

const props = defineProps({
  icon: { type: [Object, Function], default: null },
  href: { type: String, default: null },
  chevron: { type: Boolean, default: false },
  // 'default' | 'danger' | 'static' (no hover, for read-only info rows)
  variant: { type: String, default: 'default' },
  disabled: { type: Boolean, default: false },
  tag: { type: String, default: 'button' },
})

const emit = defineEmits(['click'])

function onClick(e) {
  if (props.disabled || props.variant === 'static') {
    e.preventDefault()
    return
  }
  emit('click', e)
}
</script>

<style scoped>
.li-btn {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 52px;
  padding: var(--space-3) var(--space-4);
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  text-align: left;
  text-decoration: none;
  font-size: var(--text-base);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background 0.12s ease;
}

.li-btn:last-child {
  border-bottom: none;
}

.li-btn:hover,
.li-btn:focus-visible {
  background: var(--color-bg-muted);
  outline: none;
}

.li-btn:active {
  background: var(--color-border);
}

.li-btn--static,
.li-btn--static:hover,
.li-btn--static:focus-visible,
.li-btn--static:active {
  cursor: default;
  background: transparent;
}

.li-btn__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.li-btn__label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.li-btn__title {
  font-weight: 500;
  line-height: 1.3;
}

.li-btn__detail {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: 1.3;
}

.li-btn__trailing {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  flex-shrink: 0;
}

.li-btn__chevron {
  color: var(--color-border);
}

.li-btn--danger {
  color: var(--color-danger-text);
}

.li-btn--danger .li-btn__icon {
  color: var(--color-danger-text);
}

.li-btn[disabled],
.li-btn[aria-disabled="true"] {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
