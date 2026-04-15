<template>
  <div v-if="open && content" class="help-backdrop" @click="$emit('close')"></div>
  <transition name="help-slide">
    <aside v-if="open && content" class="help-panel" ref="panel">
      <header class="help-panel-header">
        <strong>{{ content.title }}</strong>
        <button
          class="help-panel-close"
          aria-label="Schließen"
          @click.prevent="$emit('close')"
        >&times;</button>
      </header>
      <div class="help-panel-body">
        <div v-for="(section, i) in content.sections" :key="i" class="help-section">
          <h4 v-if="section.heading">{{ section.heading }}</h4>
          <div v-html="section.html"></div>
        </div>
      </div>
    </aside>
  </transition>
</template>

<script setup>
import { computed } from 'vue'
import helpContent from './helpContent.js'

const props = defineProps({
  helpKey: { type: String, default: null },
  open: { type: Boolean, default: false }
})

defineEmits(['close'])

const content = computed(() => {
  if (!props.helpKey) return null
  return helpContent[props.helpKey] || null
})
</script>

<style scoped>
.help-panel {
  position: absolute;
  top: 0;
  right: 0;
  width: min(320px, calc(100vw - 2rem));
  max-height: 70vh;
  overflow-y: auto;
  background: var(--pico-background-color, #fff);
  border: 1px solid var(--pico-muted-border-color, #e2e8f0);
  border-radius: var(--pico-border-radius, 0.375rem);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
  z-index: 100;
}

.help-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--pico-muted-border-color, #e2e8f0);
  position: sticky;
  top: 0;
  background: var(--pico-background-color, #fff);
}

.help-panel-header strong {
  font-size: 0.95rem;
}

.help-panel-close {
  background: none;
  border: none;
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 0.25rem;
  color: var(--pico-muted-color, #64748b);
  width: auto;
  margin: 0;
}

.help-panel-close:hover {
  color: var(--pico-color, #1e293b);
}

.help-panel-body {
  padding: 0.75rem 1rem;
}

.help-section + .help-section {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--pico-muted-border-color, #e2e8f0);
}

.help-section h4 {
  font-size: 0.85rem;
  font-weight: 600;
  margin: 0 0 0.35rem 0;
  color: var(--pico-muted-color, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.help-section :deep(p) {
  font-size: 0.875rem;
  line-height: 1.5;
  margin: 0 0 0.4rem 0;
}

.help-section :deep(p:last-child) {
  margin-bottom: 0;
}

.help-section :deep(ol) {
  font-size: 0.875rem;
  line-height: 1.5;
  padding-left: 1.25rem;
  margin: 0;
}

.help-section :deep(ol li) {
  margin-bottom: 0.25rem;
}

/* Slide-in transition */
.help-slide-enter-active,
.help-slide-leave-active {
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.help-slide-enter-from,
.help-slide-leave-to {
  transform: translateX(20px);
  opacity: 0;
}

.help-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.2);
  z-index: 99;
}

/* Responsive: bottom sheet on mobile */
@media (max-width: 640px) {
  .help-panel {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    top: auto;
    width: 100%;
    max-height: 60vh;
    border-radius: var(--pico-border-radius) var(--pico-border-radius) 0 0;
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
  }
  .help-slide-enter-from,
  .help-slide-leave-to {
    transform: translateY(100%);
    opacity: 0;
  }
  .help-backdrop {
    position: fixed;
    inset: 0;
    z-index: 99;
    background: rgba(0, 0, 0, 0.4);
  }
}
</style>
