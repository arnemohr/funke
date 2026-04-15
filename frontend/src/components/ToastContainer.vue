<template>
  <div class="toast-container" v-if="toasts.length > 0">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      :class="['toast', `toast-${toast.type}`]"
    >
      <span>{{ toast.message }}</span>
      <button class="toast-close" @click="dismissToast(toast.id)" aria-label="Schließen">&times;</button>
    </div>
  </div>
</template>

<script setup>
import { useToast } from '../composables/useToast.js'

const { toasts, dismissToast } = useToast()
</script>
