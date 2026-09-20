<template>
  <article class="charter-sign">
    <div v-if="loading" aria-busy="true" class="loading-state">
      Einen Moment — der Vertrag wird geladen ...
    </div>

    <!-- The backend answers one bare 404 to every rejection (wrong token,
         unknown event, contract re-rendered since the link went out), so this
         page cannot be used to probe which events exist. We say just as
         little — but unlike the other public pages there IS something to do
         about it, so we say that much. -->
    <div v-else-if="gone" role="alert" class="gone-state">
      <h2>Diesen Vertrag gibt es nicht (mehr).</h2>
      <p>
        Womöglich wurde der Vertrag geändert — dann ist ein neuer Link
        unterwegs. Prüf am besten deine Mails oder melde dich bei uns.
      </p>
    </div>

    <div v-else-if="loadError" role="alert" class="error-state">
      <h2>Das hat gerade nicht geklappt</h2>
      <p>Der Vertrag konnte nicht geladen werden. Versuch es in einem Moment nochmal.</p>
      <button type="button" class="outline" @click="load()">Nochmal versuchen</button>
    </div>

    <div v-else-if="done" class="done-state">
      <h2>Danke — unterschrieben.</h2>
      <p>
        Wir schicken dir den fertigen, unterschriebenen Vertrag per Mail zu.
        Bewahre die Mail auf: sie ist dein Nachweis über das, was vereinbart
        wurde.
      </p>
    </div>

    <template v-else-if="contract">
      <header class="page-header">
        <h2>Chartervertrag</h2>
        <p class="subtitle">{{ contract.event_name }}</p>
      </header>

      <div v-if="contract.already_signed" role="status" class="already">
        <p>
          Für diesen Vertrag liegt schon eine Unterschrift von dir vor. Du musst
          nichts weiter tun.
        </p>
      </div>

      <template v-else>
        <dl class="terms">
          <dt>Charterer</dt><dd>{{ contract.charterer_name }}</dd>
          <template v-if="!contract.skipper_is_charterer">
            <dt>Schiffsführer</dt><dd>{{ contract.skipper_name }}</dd>
          </template>
          <dt>Übergabe</dt><dd>{{ formatWhen(contract.uebergabe_at) }}</dd>
          <dt>Rückgabe</dt><dd>{{ formatWhen(contract.rueckgabe_at) }}</dd>
          <dt>Chartergebühr</dt><dd>{{ formatMoney(contract.chartergebuehr) }}</dd>
          <dt>Gesamtbetrag</dt>
          <dd>{{ formatMoney(contract.gesamtbetrag) }} <small>ohne Kaution</small></dd>
          <dt>Kaution</dt><dd>{{ formatMoney(contract.kaution) }}</dd>
        </dl>

        <section class="document">
          <h3>Der Vertrag</h3>
          <p>
            <small>
              Bitte lies den Vertrag, bevor du unterschreibst — er enthält die
              Bedingungen, denen du zustimmst.
            </small>
          </p>
          <!-- The embedded view is the convenience; the download link is the
               guarantee. iOS Safari renders PDFs in an iframe unreliably, so
               without the link a share of charterers would have nothing to
               read at all. -->
          <iframe
            :src="contract.document_url"
            class="document-frame"
            title="Chartervertrag als PDF"
          />
          <p class="document-fallback">
            <a :href="contract.document_url" target="_blank" rel="noopener">
              PDF herunterladen bzw. in neuem Tab öffnen
            </a>
          </p>
        </section>

        <section class="sign">
          <h3>Unterschrift</h3>

          <label for="signedName">
            Vor- und Nachname *
            <input
              id="signedName"
              v-model="signedName"
              type="text"
              autocomplete="name"
              :disabled="submitting"
              required
            />
          </label>

          <SignaturePad label="Unterschriftfeld" @change="onSignature" />
          <p class="sign-note">
            <small>
              Der getippte Name genügt. Das Zeichenfeld ist freiwillig — beides
              ist rechtlich eine einfache elektronische Signatur.
            </small>
          </p>

          <div v-if="submitError" role="alert" class="error-message">
            {{ submitError }}
          </div>

          <button
            type="button"
            :disabled="!canSubmit || submitting"
            :aria-busy="submitting"
            @click="submit"
          >
            {{ submitting ? 'Wird gesendet ...' : 'Verbindlich unterschreiben' }}
          </button>
        </section>
      </template>
    </template>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { publicApi } from '../../services/api'
import SignaturePad from '../../components/SignaturePad.vue'

const props = defineProps({
  eventId: { type: String, required: true },
  token: { type: String, required: true },
})

const contract = ref(null)
const loading = ref(true)
const gone = ref(false)
const loadError = ref(null)
const signedName = ref('')
const signatureImage = ref(null)
const submitting = ref(false)
const submitError = ref(null)
const done = ref(false)

const canSubmit = computed(() => signedName.value.trim().length > 2)

function onSignature(dataUrl) {
  signatureImage.value = dataUrl
}

function formatWhen(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('de-DE', {
    timeZone: 'Europe/Berlin',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatMoney(value) {
  if (value === null || value === undefined) return '—'
  return `${Number(value).toFixed(2).replace('.', ',')} €`
}

async function load() {
  loading.value = true
  gone.value = false
  loadError.value = null
  try {
    contract.value = await publicApi.getCharterForSigning(props.eventId, props.token)
    signedName.value = contract.value.charterer_name || ''
  } catch (err) {
    if (err.status === 404 || err.message?.includes('404')) {
      gone.value = true
    } else {
      loadError.value = err.message || 'Laden fehlgeschlagen'
    }
  } finally {
    loading.value = false
  }
}

async function submit() {
  submitting.value = true
  submitError.value = null
  try {
    await publicApi.signCharter(props.eventId, props.token, {
      signed_name: signedName.value.trim(),
      image_b64: signatureImage.value,
      // Pinning the render we were shown. If the organiser re-rendered while
      // this page was open the backend refuses, and it should — otherwise the
      // signature would attach to text nobody read.
      document_sha256: contract.value.document_sha256,
    })
    done.value = true
  } catch (err) {
    submitError.value = err.message || 'Unterschrift fehlgeschlagen'
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.charter-sign {
  padding-bottom: 3rem;
}

.page-header {
  margin-bottom: var(--space-4, 1rem);
}

.subtitle {
  color: var(--color-text-muted, #64748b);
  margin: 0;
}

.terms {
  display: grid;
  grid-template-columns: minmax(8rem, auto) 1fr;
  gap: 0.25rem var(--space-3, 0.75rem);
  margin-bottom: var(--space-4, 1rem);
}

.terms dt {
  color: var(--color-text-muted, #64748b);
  font-size: var(--text-sm, 0.875rem);
}

.terms dd {
  margin: 0;
  font-weight: 500;
}

.document-frame {
  width: 100%;
  height: min(60vh, 520px);
  border: 1px solid var(--muted-border-color, #cbd5e1);
  border-radius: var(--radius-md, 0.375rem);
  background: var(--card-background-color, #fff);
}

.document-fallback {
  margin-top: var(--space-2, 0.5rem);
}

.sign-note,
.already {
  color: var(--color-text-muted, #64748b);
}

.already {
  padding: var(--space-3, 0.75rem);
  border-left: 3px solid var(--muted-border-color, #cbd5e1);
  background: var(--card-sectioning-background-color, #f8fafc);
}

.done-state,
.gone-state,
.error-state {
  padding: var(--space-4, 1rem) 0;
}
</style>
