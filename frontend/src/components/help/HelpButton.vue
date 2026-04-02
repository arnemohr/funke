<template>
  <button
    class="help-button outline"
    aria-label="Hilfe"
    title="Hilfe"
    @click.prevent.stop="$emit('click')"
  >?</button>
</template>

<script setup>
defineEmits(['click'])
</script>

<style scoped>
.help-button {
  width: 2rem;
  height: 2rem;
  min-width: 2rem;
  border-radius: 50%;
  padding: 0;
  font-size: 0.9rem;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  flex-shrink: 0;
}
</style>
