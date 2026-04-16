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
        <ChevronLeft :size="20" aria-hidden="true" />
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
import { ChevronLeft } from 'lucide-vue-next'

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
  margin-bottom: var(--space-4);
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 2.25rem;
  margin-bottom: var(--space-2);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-height: 44px;
  padding: var(--space-1) var(--space-2);
  margin-left: calc(var(--space-2) * -1);
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: var(--text-base);
  font-weight: 500;
  border-radius: var(--radius-md);
}

.back-link:hover,
.back-link:focus-visible {
  color: var(--color-brand);
  background: var(--color-bg-muted);
  outline: none;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin-left: auto;
}

.header-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.header-title h2 {
  margin: 0;
  font-size: var(--text-xl);
  line-height: 1.2;
  font-weight: 600;
}

.subtitle {
  margin: var(--space-1) 0 0;
  color: var(--color-text-muted);
  font-size: var(--text-base);
}
</style>
