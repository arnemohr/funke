import { ref } from 'vue'

const KEY = 'funke:theme'
const VALID = ['auto', 'light', 'dark']

function readMode() {
  const v = localStorage.getItem(KEY)
  return VALID.includes(v) ? v : 'auto'
}

function systemPrefersDark() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function resolve(m) {
  if (m === 'dark') return 'dark'
  if (m === 'light') return 'light'
  return systemPrefersDark() ? 'dark' : 'light'
}

const mode = ref(readMode())
const resolved = ref(resolve(mode.value))

let initialized = false

function updateMetaThemeColor(theme) {
  if (typeof document === 'undefined') return
  const meta = document.querySelector('meta[name="theme-color"]:not([media])')
  if (!meta) return
  // Match --color-surface in design-tokens.css
  meta.setAttribute('content', theme === 'dark' ? '#0F1B2D' : '#FAFAF8')
}

function apply(nextMode, { animate = true } = {}) {
  const next = resolve(nextMode)
  resolved.value = next
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (!animate) {
    root.classList.add('theme-transitions-off')
  }
  root.setAttribute('data-theme', next)
  updateMetaThemeColor(next)
  if (!animate) {
    // Flush styles, then re-enable transitions on next frame.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        root.classList.remove('theme-transitions-off')
      })
    })
  }
}

export function initTheme() {
  if (initialized) return
  initialized = true
  if (typeof window === 'undefined') return

  // The pre-paint inline script in index.html already set data-theme and
  // added .theme-transitions-off. Just sync refs and wire listeners.
  apply(mode.value, { animate: false })

  // React to OS scheme changes (only relevant when mode === 'auto').
  const mql = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    if (mode.value === 'auto') apply('auto')
  }
  if (mql.addEventListener) mql.addEventListener('change', onChange)
  else if (mql.addListener) mql.addListener(onChange)

  // Cross-tab sync.
  window.addEventListener('storage', (e) => {
    if (e.key === KEY) {
      mode.value = readMode()
      apply(mode.value)
    }
  })
}

export function useTheme() {
  function setMode(next) {
    if (!VALID.includes(next)) return
    mode.value = next
    if (next === 'auto') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, next)
    apply(next)
  }
  return { mode, resolved, setMode }
}
