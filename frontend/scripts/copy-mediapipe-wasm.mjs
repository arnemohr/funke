/**
 * Copy MediaPipe's vision WASM runtime into `public/` so the face detector is
 * served from our own origin (spec 024 § Unkenntlich machen).
 *
 * Why not the CDN: the editor runs on an admin page that handles photographs of
 * guests' faces. No byte of a photo leaves the browser, and a third-party
 * script tag on that page would be the one moving part that could change that
 * without us noticing. Self-hosting also keeps the page working offline, which
 * the PWA otherwise promises.
 *
 * Why copied at build time instead of committed: it is 22 MB of generated
 * binaries that belong to a pinned dependency, so `node_modules` is their
 * source of truth. `public/mediapipe/` is gitignored; npm runs this via the
 * `prebuild`/`predev` hooks, so a plain `npm run build` is enough.
 *
 * Only the two SIMD/no-SIMD pairs are copied. `FilesetResolver.forVisionTasks`
 * probes for SIMD and asks for exactly one of them; the `_module_` variants
 * are for a loading mode we do not use.
 */
import { copyFile, mkdir, stat } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const from = join(here, '..', 'node_modules', '@mediapipe', 'tasks-vision', 'wasm')
const to = join(here, '..', 'public', 'mediapipe', 'wasm')

const FILES = [
  'vision_wasm_internal.js',
  'vision_wasm_internal.wasm',
  'vision_wasm_nosimd_internal.js',
  'vision_wasm_nosimd_internal.wasm',
]

await mkdir(to, { recursive: true })

for (const name of FILES) {
  const source = join(from, name)
  const target = join(to, name)

  // Skip an unchanged file: this runs before every dev server start, and
  // copying 22 MB each time is a needless second of startup.
  try {
    const [a, b] = await Promise.all([stat(source), stat(target)])
    if (a.size === b.size && b.mtimeMs >= a.mtimeMs) continue
  } catch {
    // Target missing — fall through and copy.
  }

  await copyFile(source, target)
  process.stdout.write(`mediapipe: ${name}\n`)
}
