<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="sheet-root" role="dialog" aria-modal="true" :aria-label="title || 'Aktionen'">
        <div class="sheet-backdrop" @click="$emit('close')" />
        <div class="sheet-panel" role="document">
          <div class="sheet-grabber" aria-hidden="true" />
          <header v-if="title || $slots.header" class="sheet-header">
            <slot name="header">
              <h3>{{ title }}</h3>
            </slot>
          </header>
          <div class="sheet-body">
            <slot />
          </div>
          <div v-if="$slots.footer" class="sheet-footer">
            <slot name="footer" />
          </div>
          <button
            v-else
            type="button"
            class="sheet-cancel"
            @click="$emit('close')"
          >
            Abbrechen
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
})

defineEmits(['close'])

// Lock body scroll while sheet is open
watch(() => props.open, (isOpen) => {
  if (typeof document === 'undefined') return
  document.body.style.overflow = isOpen ? 'hidden' : ''
})
</script>

<style scoped>
.sheet-root {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.sheet-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(12, 30, 60, 0.5);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

.sheet-panel {
  position: relative;
  width: 100%;
  max-width: 560px;
  background: var(--color-surface-raised);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  box-shadow: var(--shadow-sheet);
  padding-bottom: calc(var(--space-3) + env(safe-area-inset-bottom, 0));
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.sheet-grabber {
  width: 36px;
  height: 4px;
  background: var(--color-border);
  border-radius: var(--radius-pill);
  margin: var(--space-2) auto var(--space-2);
  flex-shrink: 0;
}

.sheet-header {
  padding: var(--space-2) var(--space-4) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.sheet-header h3 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
}

.sheet-body {
  flex: 1;
  overflow-y: auto;
}

.sheet-footer {
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--color-border);
}

.sheet-cancel {
  margin: var(--space-3) var(--space-4);
  width: calc(100% - 2 * var(--space-4));
  min-height: 48px;
  background: var(--color-bg-muted);
  color: var(--color-text);
  border: none;
  border-radius: var(--radius-md);
  font-weight: 600;
  cursor: pointer;
}

.sheet-cancel:hover {
  background: var(--color-border);
}

/* Enter/leave: panel slides up, backdrop fades */
.sheet-enter-active,
.sheet-leave-active {
  transition: opacity 0.2s ease;
}

.sheet-enter-active .sheet-panel,
.sheet-leave-active .sheet-panel {
  transition: transform 0.25s cubic-bezier(0.2, 0.9, 0.3, 1);
}

.sheet-enter-from,
.sheet-leave-to {
  opacity: 0;
}

.sheet-enter-from .sheet-panel,
.sheet-leave-to .sheet-panel {
  transform: translateY(100%);
}
</style>
