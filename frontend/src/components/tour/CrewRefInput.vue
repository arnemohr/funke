<template>
  <div class="crewref" :class="{ 'crewref--open': showMenu }">
    <div class="crewref__field">
      <input
        ref="inputEl"
        type="text"
        :value="modelValue?.display_name ?? ''"
        :placeholder="placeholder"
        @focus="openMenu"
        @input="onTyped($event.target.value)"
        @blur="onBlur"
      />
      <span v-if="modelValue?.admin_user_id" class="crewref__chip" title="Mit Profil verlinkt">
        <Link :size="12" aria-hidden="true" /> verlinkt
      </span>
      <button
        v-if="modelValue?.display_name"
        type="button"
        class="crewref__clear"
        aria-label="Leeren"
        @mousedown.prevent="clear"
      >×</button>
    </div>
    <ul v-if="showMenu && suggestions.length" class="crewref__menu">
      <li
        v-for="s in suggestions"
        :key="s.admin_user_id"
        class="crewref__opt"
        @mousedown.prevent="pick(s)"
      >
        <span class="crewref__opt-name">{{ s.display_name }}</span>
        <span class="crewref__opt-sub">
          {{ s.crew_roles?.length ? s.crew_roles.map(r => formatCrewRole(r)).join(' · ') : s.email }}
        </span>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Link } from 'lucide-vue-next'
import { adminApi } from '../../services/api'
import { formatCrewRole } from '../../utils/formatters'

const props = defineProps({
  modelValue: { type: Object, default: null },
  roleFilter: { type: String, default: null },
  placeholder: { type: String, default: 'Name eingeben' },
})
const emit = defineEmits(['update:modelValue'])

const inputEl = ref(null)
const showMenu = ref(false)
const suggestions = ref([])
let debounceTimer = null

async function fetchSuggestions(q) {
  try {
    const params = { q, limit: 6 }
    if (props.roleFilter) params.role = props.roleFilter
    const res = await adminApi.listCrewSuggestions(params)
    suggestions.value = res.items || []
  } catch {
    suggestions.value = []
  }
}

function openMenu() {
  showMenu.value = true
  fetchSuggestions(props.modelValue?.display_name || '')
}

function onTyped(v) {
  emit('update:modelValue', v ? { display_name: v, admin_user_id: null } : null)
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => fetchSuggestions(v), 200)
}

function pick(s) {
  emit('update:modelValue', {
    display_name: s.display_name,
    admin_user_id: s.admin_user_id,
  })
  showMenu.value = false
}

function clear() {
  emit('update:modelValue', null)
  showMenu.value = false
}

function onBlur() {
  // Defer so mousedown on menu items still fires.
  setTimeout(() => { showMenu.value = false }, 150)
}

watch(() => props.roleFilter, () => {
  if (showMenu.value) fetchSuggestions(props.modelValue?.display_name || '')
})
</script>

<style scoped>
.crewref { position: relative; }
.crewref__field {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border: 1.5px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 0 var(--space-2);
  background: var(--color-surface-raised);
  min-height: 44px;
}
.crewref__field input {
  flex: 1;
  border: none;
  outline: none;
  font-size: var(--text-base);
  padding: var(--space-2) 0;
  background: transparent;
}
.crewref__chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: var(--color-brand);
  background: var(--color-info-bg, #e8f5f2);
  padding: 2px 6px;
  border-radius: 999px;
}
.crewref__clear {
  background: none;
  border: none;
  font-size: 18px;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0 6px;
}
.crewref__menu {
  position: absolute;
  inset-inline: 0;
  top: calc(100% + 4px);
  z-index: 50;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 18px rgba(0,0,0,.08);
  max-height: 240px;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 4px 0;
}
.crewref__opt {
  display: flex;
  flex-direction: column;
  padding: 8px 12px;
  cursor: pointer;
}
.crewref__opt:hover { background: var(--color-bg-muted); }
.crewref__opt-name { font-weight: 600; font-size: var(--text-base); }
.crewref__opt-sub { font-size: 12px; color: var(--color-text-muted); }
</style>
