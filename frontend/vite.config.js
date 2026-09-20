import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const pkg = JSON.parse(readFileSync(resolve(__dirname, 'package.json'), 'utf-8'))

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [
    vue(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.js',
      registerType: 'autoUpdate',
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        // The face detector's runtime is 22 MB of WASM plus a 1 MB model and is
        // used by a handful of organisers on the pixelate screen. Precaching it
        // would make every guest's first visit pay for it, so it is fetched on
        // demand instead — the `.js` glue matches the pattern above, hence the
        // explicit exclusion (spec 024 § Unkenntlich machen).
        // `vision_bundle-*.js` is Rollup's chunk for the dynamically imported
        // MediaPipe SDK. It lands in assets/ like any other chunk and matches
        // the `**/*.js` pattern above, so it needs naming explicitly — without
        // this line the precache silently grows by 125 kB for every visitor.
        globIgnores: ['**/mediapipe/**', '**/models/*.tflite', '**/vision_bundle*.js'],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
      },
      manifest: {
        name: 'Funke – Verein für mobile Machenschaften',
        short_name: 'Funke',
        description: 'Veranstaltungsmanagement für den Verein für mobile Machenschaften e.V.',
        theme_color: '#0C1E3C',
        background_color: '#FAFAF8',
        display: 'standalone',
        scope: '/',
        start_url: '/',
        lang: 'de',
        icons: [
          {
            src: '/icons/icon-192x192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/icons/icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
          },
          {
            src: '/icons/icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
  },
})
