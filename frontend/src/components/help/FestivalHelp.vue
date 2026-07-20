<template>
  <details class="festival-help">
    <summary class="festival-help-summary">
      <span class="festival-help-icon" aria-hidden="true">ⓘ</span>
      <span>{{ title }}</span>
    </summary>
    <div class="festival-help-body">
      <slot />
    </div>
  </details>
</template>

<script setup>
// Subtle, collapsed-by-default flow explainer for the festival surfaces
// (spec 019). One per page, placed right under the page header — the
// heavier HelpButton/HelpPanel overlay (spec 007) stays reserved for the
// status-keyed guest manage page.
defineProps({
  title: { type: String, default: 'So funktioniert’s' },
})
</script>

<style scoped>
.festival-help {
  margin-bottom: var(--space-4);
  padding: 0;
  border: none;
}

.festival-help-summary {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 44px;
  padding: var(--space-1) var(--space-2);
  margin-left: calc(var(--space-2) * -1);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  font-weight: 500;
  line-height: 1.2;
  cursor: pointer;
  border-radius: var(--radius-md);
  list-style: none;
}

.festival-help-summary::-webkit-details-marker {
  display: none;
}

/* Neutralise Pico's accordion chevron — the ⓘ is the affordance. */
.festival-help-summary::after {
  display: none;
}

.festival-help-summary:hover,
.festival-help-summary:focus-visible {
  color: var(--color-brand);
  background: var(--color-bg-muted);
  outline: none;
}

.festival-help[open] .festival-help-summary {
  color: var(--color-brand);
}

.festival-help-icon {
  font-size: 1rem;
  line-height: 1;
}

.festival-help-body {
  background: var(--color-info-bg);
  border-left: 4px solid var(--color-info-text);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-top: var(--space-1);
}

.festival-help-body :deep(p) {
  color: var(--color-info-text);
  font-size: var(--text-sm);
  line-height: 1.5;
  margin: 0 0 var(--space-2);
}

.festival-help-body :deep(p:last-child) {
  margin-bottom: 0;
}
</style>
