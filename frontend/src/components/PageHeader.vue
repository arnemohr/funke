<template>
  <header class="page-header">
    <div class="header-top">
      <a
        v-if="back"
        href="#"
        class="back-link"
        :aria-label="backLabel || 'Zurück'"
        @click.prevent="handleBack"
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="15 18 9 12 15 6" />
        </svg>
        <span v-if="backLabel">{{ backLabel }}</span>
      </a>
      <div class="header-actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="header-title">
      <h2>
        <slot name="title">{{ title }}</slot>
      </h2>
      <slot name="chip" />
    </div>
    <p v-if="subtitle || $slots.subtitle" class="subtitle">
      <slot name="subtitle">{{ subtitle }}</slot>
    </p>
  </header>
</template>

<script setup>
import { useRouter } from 'vue-router'

const props = defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  back: { type: [Boolean, String], default: false },
  backLabel: { type: String, default: '' },
})

const router = useRouter()

function handleBack() {
  if (typeof props.back === 'string') {
    router.push(props.back)
    return
  }
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/')
  }
}
</script>

<style scoped>
.page-header {
  margin-bottom: 1rem;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 2.25rem;
  margin-bottom: 0.5rem;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  min-height: 44px;
  padding: 0.25rem 0.5rem;
  margin-left: -0.5rem;
  color: var(--color-text-muted, #5C6470);
  text-decoration: none;
  font-size: var(--text-sm, 0.875rem);
  font-weight: 500;
  border-radius: var(--pico-border-radius);
}

.back-link:hover,
.back-link:focus-visible {
  color: var(--color-brand, #0C1E3C);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.header-title h2 {
  margin: 0;
  font-size: 1.5rem;
  line-height: 1.2;
}

.subtitle {
  margin: 0.25rem 0 0;
  color: var(--color-text-muted, #5C6470);
  font-size: var(--text-sm, 0.875rem);
}
</style>
