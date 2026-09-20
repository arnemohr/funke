<template>
  <article class="charter-page">
    <PageHeader back back-label="Zurück" :subtitle="eventName">
      <template #title>Chartervertrag</template>
      <template #chip>
        <span v-if="exists" class="status-badge" :class="statusClass">{{ statusLabel }}</span>
      </template>
    </PageHeader>

    <div v-if="loading" aria-busy="true">Chartervertrag wird geladen ...</div>

    <div v-else-if="loadError" role="alert" class="error">{{ loadError }}</div>

    <template v-else>
      <p v-if="!exists" class="hint-box">
        Für diese Fahrt gibt es noch keinen Vertrag. Fülle aus, was du weißt — „Speichern" legt den
        Entwurf an, auch halb ausgefüllt. Das PDF entsteht erst später.
      </p>

      <!-- Nach der Unterschrift sind die Bytes die Vereinbarung, nicht die Zeile
           daneben. Der Hinweistext ist der aus Spec 025 und steht wörtlich auch
           im 409 des Servers. -->
      <p v-if="locked" role="status" class="locked-note">
        Ein unterschriebener Vertrag kann nicht geändert werden. Zum Korrigieren zuerst die
        Unterschrift verwerfen.
      </p>

      <p v-if="contract?.fahrbericht_override_by" class="warning-box">
        Fahrbericht ohne Vertrag abgegeben von {{ contract.fahrbericht_override_by }}
        <template v-if="contract.fahrbericht_override_at">
          am {{ formatDateTime(contract.fahrbericht_override_at) }}</template
        >.
      </p>

      <form @submit.prevent="save">
        <!-- ------------------------------------------------------ Charterer -->
        <div class="section-heading"><h3>Charterer</h3></div>
        <section class="surface surface-padded">
          <label for="chartererName">
            Name
            <input
              id="chartererName"
              v-model.trim="form.charterer_name"
              type="text"
              list="crewNames"
              autocomplete="off"
              placeholder="Vor- und Nachname"
              :disabled="inputsDisabled"
            />
            <small>
              Steht so im Vertrag. Ist der Charterer Crewmitglied, schlägt das Feld die
              Skipper*innen des Vereins vor.
            </small>
          </label>

          <label for="chartererAddress">
            Anschrift
            <textarea
              id="chartererAddress"
              v-model="form.charterer_address"
              rows="3"
              placeholder="Straße Hausnummer&#10;PLZ Ort"
              :disabled="inputsDisabled"
            ></textarea>
            <small>Mehrzeilig, so wie sie auf einen Briefumschlag gehört.</small>
          </label>

          <div class="grid-2">
            <label for="chartererEmail">
              E-Mail
              <input
                id="chartererEmail"
                v-model.trim="form.charterer_email"
                type="email"
                placeholder="name@example.de"
                :disabled="inputsDisabled"
              />
              <small>Nur fürs Verschicken nötig — ohne sie geht „An Charterer senden" nicht.</small>
            </label>

            <label for="chartererPhone">
              Telefon
              <input
                id="chartererPhone"
                v-model.trim="form.charterer_phone"
                type="tel"
                placeholder="0170 1234567"
                :disabled="inputsDisabled"
              />
            </label>
          </div>
        </section>

        <!-- -------------------------------------------------------- Zeitraum -->
        <div class="section-heading"><h3>Zeitraum</h3></div>
        <section class="surface surface-padded">
          <div class="grid-2">
            <label for="uebergabe">
              Übergabe
              <input
                id="uebergabe"
                v-model="form.uebergabe_at"
                type="datetime-local"
                :disabled="inputsDisabled"
              />
            </label>

            <label for="rueckgabe">
              Rückgabe
              <input
                id="rueckgabe"
                v-model="form.rueckgabe_at"
                type="datetime-local"
                :disabled="inputsDisabled"
              />
            </label>
          </div>
          <small class="hint-text">
            Ortszeit Hamburg. Beide Termine stehen im Vertrag und sind Pflicht fürs PDF; die
            Aufbewahrungsfrist rechnet ab dem Übergabejahr.
          </small>
        </section>

        <!-- ---------------------------------------------------------- Kosten -->
        <div class="section-heading"><h3>Kosten</h3></div>
        <section class="surface surface-padded">
          <label for="chartergebuehr">
            Chartergebühr (€)
            <input
              id="chartergebuehr"
              v-model="form.chartergebuehr"
              type="number"
              min="0"
              step="0.01"
              inputmode="decimal"
              placeholder="250.00"
              :disabled="inputsDisabled"
            />
          </label>

          <fieldset class="expenses">
            <legend>Sonderleistungen</legend>
            <div v-for="(line, idx) in form.sonderleistungen" :key="idx" class="expense-row">
              <input
                v-model.trim="line.description"
                type="text"
                placeholder="Beschreibung"
                :aria-label="`Sonderleistung ${idx + 1} — Beschreibung`"
                :disabled="inputsDisabled"
              />
              <input
                v-model="line.amount"
                type="number"
                min="0"
                step="0.01"
                inputmode="decimal"
                placeholder="€"
                :aria-label="`Sonderleistung ${idx + 1} — Betrag`"
                :disabled="inputsDisabled"
              />
              <button
                type="button"
                class="row-remove"
                :aria-label="`Sonderleistung ${idx + 1} entfernen`"
                :disabled="inputsDisabled"
                @click="removeExpense(idx)"
              >
                ×
              </button>
            </div>
            <button type="button" class="row-add" :disabled="inputsDisabled" @click="addExpense">
              + Sonderleistung hinzufügen
            </button>
            <small>
              Zeilen ohne Beschreibung werden beim Speichern verworfen — so bleibt eine
              versehentlich leere Zeile ohne Folgen.
            </small>
          </fieldset>

          <label for="kaution">
            Kaution (€)
            <input
              id="kaution"
              v-model="form.kaution"
              type="number"
              min="0"
              step="0.01"
              inputmode="decimal"
              placeholder="100.00"
              :disabled="inputsDisabled"
            />
          </label>

          <label for="gesamtbetrag">
            Gesamtbetrag
            <input id="gesamtbetrag" :value="gesamtbetragLabel" type="text" readonly />
            <small>ohne Kaution</small>
          </label>
        </section>

        <!-- --------------------------------------------------- Schiffsführer -->
        <div class="section-heading"><h3>Schiffsführer</h3></div>
        <section class="surface surface-padded">
          <label for="skipperSame" class="checkbox-row">
            <input
              id="skipperSame"
              v-model="form.skipper_is_charterer"
              type="checkbox"
              role="switch"
              :disabled="inputsDisabled"
            />
            Charterer und Schiffsführer sind dieselbe Person
          </label>
          <p class="hint-text">
            {{
              form.skipper_is_charterer
                ? 'Das PDF bekommt zwei Unterschriftsblöcke: „Charterer und Schiffsführer" und „Vercharterer".'
                : 'Das PDF bekommt drei Unterschriftsblöcke: Charterer, Schiffsführer und Vercharterer.'
            }}
          </p>

          <label for="skipperName">
            Name des Schiffsführers
            <input
              id="skipperName"
              v-model.trim="form.skipper_name"
              type="text"
              list="crewNames"
              autocomplete="off"
              placeholder="Vor- und Nachname"
              :disabled="inputsDisabled || form.skipper_is_charterer"
            />
            <small v-if="form.skipper_is_charterer">
              Spiegelt den Charterer, solange die Checkbox gesetzt ist.
            </small>
          </label>

          <div class="grid-2">
            <label for="sbfsNumber">
              SBFS — Nummer
              <input
                id="sbfsNumber"
                v-model.trim="form.sbfs_number"
                type="text"
                placeholder="S190168991"
                :disabled="inputsDisabled"
              />
            </label>
            <label for="sbfsIssued">
              SBFS — ausgestellt am
              <input
                id="sbfsIssued"
                v-model="form.sbfs_issued_on"
                type="date"
                :disabled="inputsDisabled"
              />
            </label>
          </div>

          <div class="grid-2">
            <label for="sbfbNumber">
              SBFB — Nummer
              <input
                id="sbfbNumber"
                v-model.trim="form.sbfb_number"
                type="text"
                :disabled="inputsDisabled"
              />
            </label>
            <label for="sbfbIssued">
              SBFB — ausgestellt am
              <input
                id="sbfbIssued"
                v-model="form.sbfb_issued_on"
                type="date"
                :disabled="inputsDisabled"
              />
            </label>
          </div>
          <small class="hint-text">
            Sind Charterer und Schiffsführer verschiedene Personen, verlangt das PDF mindestens
            einen der beiden Führerscheine.
          </small>

          <label for="personen">
            Personen an Bord ohne Skipper
            <input
              id="personen"
              v-model="form.personen_ohne_skipper"
              type="number"
              min="0"
              max="12"
              step="1"
              inputmode="numeric"
              :disabled="inputsDisabled"
            />
            <small>Höchstens 12.</small>
          </label>
        </section>

        <!-- ------------------------------------------- Sondervereinbarungen -->
        <div class="section-heading"><h3>Sondervereinbarungen</h3></div>
        <section class="surface surface-padded">
          <label for="sonderv" class="sr-label">
            Sondervereinbarungen
            <textarea
              id="sonderv"
              v-model="form.sondervereinbarungen"
              rows="3"
              maxlength="500"
              placeholder="Abweichendes zum Standardvertrag — höchstens 500 Zeichen."
              :disabled="inputsDisabled"
            ></textarea>
            <small>Steht als eigener Absatz im Vertrag. Leer lassen ist der Normalfall.</small>
          </label>
        </section>

        <div v-if="saveError" role="alert" class="error">{{ saveError }}</div>
      </form>

      <!-- Eine datalist statt CrewRefInput: die Vertragszeile speichert Namen
           als Text, keine `CrewRef` mit `admin_user_id`. Gefüttert wird sie aus
           derselben Quelle wie der Crew-Picker im Fahrbericht. -->
      <datalist id="crewNames">
        <option v-for="name in crewNames" :key="name" :value="name"></option>
      </datalist>

      <!-- --------------------------------------------------------- Aktionen -->
      <div class="section-heading"><h3>Aktionen</h3></div>
      <section class="surface surface-padded actions">
        <div class="action-row">
          <button type="button" :disabled="locked || saving" :aria-busy="saving" @click="save">
            {{ saving ? 'Wird gespeichert ...' : 'Speichern' }}
          </button>
          <button
            type="button"
            class="outline"
            :disabled="locked || !exists || rendering"
            :aria-busy="rendering"
            @click="renderPdf"
          >
            {{ rendering ? 'PDF wird erzeugt ...' : 'PDF erzeugen' }}
          </button>
          <a
            v-if="contract?.download_url"
            role="button"
            class="outline secondary"
            :href="contract.download_url"
            target="_blank"
            rel="noopener"
          >
            PDF herunterladen
          </a>
        </div>
        <p class="hint-text">
          Ungespeicherte Änderungen gehen nicht ins PDF — erst speichern, dann erzeugen. Jeder
          Durchlauf erzeugt eine neue Fassung; nichts wird überschrieben.
          <template v-if="renderInfo"> Aktuell: {{ renderInfo }}.</template>
        </p>

        <hr />

        <div class="action-row">
          <button
            type="button"
            class="outline"
            :disabled="locked || !hasPdf || !form.charterer_email || sending"
            :aria-busy="sending"
            @click="sendToCharterer"
          >
            {{ sending ? 'Wird verschickt ...' : 'An Charterer senden' }}
          </button>
          <label class="checkbox-inline">
            <input v-model="ccSelf" type="checkbox" :disabled="locked || sending" />
            Kopie an mich
          </label>
        </div>
        <p class="hint-text">
          Verschickt das PDF als Anhang — das ist zugleich die Kopie auf dauerhaftem Datenträger.
          <strong>Bei externen Charterern vorher senden:</strong> die Klauseln 1–17 sind AGB, und §
          305 Abs. 2 BGB verlangt, dass die Gegenseite sie vor Vertragsschluss in Ruhe lesen kann.
          Vier Seiten am Steg, während die Gäste warten, ist genau der Fall, in dem das kippt.
          <template v-if="contract?.sent_at">
            Zuletzt verschickt am {{ formatDateTime(contract.sent_at) }}
            <template v-if="contract.sent_to"> an {{ contract.sent_to }}</template
            >.
          </template>
        </p>

        <hr />

        <!-- Online-Weg (Spec 025, Nachtrag). Steht bewusst VOR dem Papierweg:
             er schließt die Lücke, dass der Scan erst nach der Fahrt käme,
             wenn der Vertrag niemanden mehr interessiert. -->
        <template v-if="!isSigned">
          <h4>Online unterschreiben lassen</h4>
          <div class="action-row">
            <button
              type="button"
              class="outline"
              :disabled="locked || !hasPdf || !form.charterer_email || sendingLink"
              :aria-busy="sendingLink"
              @click="sendSigningLink"
            >
              {{ sendingLink ? 'Wird verschickt ...' : 'Signaturlink an Charterer senden' }}
            </button>
          </div>
          <p class="hint-text">
            Der Charterer öffnet den Link, liest das PDF und zeichnet im Browser. Danach wird der
            Vertrag automatisch gesiegelt und als fertiges Dokument an Charterer und Buchhaltung
            verschickt.
            <strong>Jedes neue „PDF erzeugen" entwertet den Link</strong> und löscht bereits
            gesammelte Unterschriften — ein Link darf den Text nicht überleben, den er gezeigt hat.
          </p>
          <ul v-if="signatures.length" class="signature-list">
            <li v-for="sig in signatures" :key="sig.role">
              {{ roleLabel(sig.role) }}: <strong>{{ sig.signed_name }}</strong>
              am {{ formatDateTime(sig.signed_at) }}
              <template v-if="sig.by_admin"> (im Admin gezeichnet)</template>
            </li>
          </ul>
          <hr />

          <!-- Vor Ort unterschreiben. Der häufige Fall laut Orga: der Charterer
               ist selbst Crewmitglied und fährt an diesem Tag, unterschrieben
               wird am Steg. Ein Link auf ein anderes Gerät hilft da nicht. -->
          <h4>Vor Ort unterschreiben</h4>
          <p class="hint-text">
            Für den Fall, dass alle zusammen am Steg stehen. Erst den Vertrag zeigen (oben „PDF
            herunterladen“), dann hier zeichnen.
            <strong>Diese Unterschriften werden als „im Admin gezeichnet“ vermerkt</strong> und
            tragen keine eigene IP der unterzeichnenden Person — der Nachweis ist damit schwächer
            als beim Signaturlink, und der Vertrag sagt das auch.
          </p>

          <div v-if="openRoles.length === 0" class="hint-text">
            Alle erforderlichen Unterschriften liegen vor.
          </div>

          <div v-for="role in openRoles" :key="role" class="inperson-row">
            <label :for="`sign-${role}`">
              {{ roleLabel(role) }} — Name
              <input
                :id="`sign-${role}`"
                v-model="inPersonNames[role]"
                type="text"
                :disabled="locked || !hasPdf || adminSigning"
                :placeholder="defaultNameFor(role)"
              />
            </label>
            <SignaturePad
              :ref="(el) => setPad(role, el)"
              :label="`Unterschriftfeld ${roleLabel(role)}`"
              @change="(data) => (inPersonImages[role] = data)"
            />
            <div class="action-row">
              <button
                type="button"
                class="outline"
                :disabled="locked || !hasPdf || adminSigning || !canSignInPerson(role)"
                :aria-busy="adminSigning"
                @click="signInPerson(role)"
              >
                {{ roleLabel(role) }} unterschreibt jetzt
              </button>
            </div>
          </div>

          <hr />

          <h4>Oder auf Papier</h4>
          <p class="hint-text">
            Lade den Scan oder das Foto als PDF hoch und trag ein, was auf dem Blatt steht.
          </p>
          <div class="action-row">
            <input
              ref="fileInput"
              type="file"
              accept="application/pdf,.pdf"
              :disabled="!hasPdf || confirming"
              @change="onFilePicked"
            />
          </div>
          <div class="action-row">
            <label for="signedOn" class="inline-field">
              Unterschrieben am
              <input
                id="signedOn"
                v-model="signedOn"
                type="date"
                :disabled="!hasPdf || confirming"
              />
            </label>
          </div>
          <label class="checkbox-inline">
            <input
              v-model="alleParteienUnterschrieben"
              type="checkbox"
              :disabled="!hasPdf || confirming"
            />
            {{ signatureConfirmLabel }}
          </label>
          <div class="action-row">
            <button
              type="button"
              :disabled="!canConfirmSigned"
              :aria-busy="confirming"
              @click="markAsSigned"
            >
              {{ confirming ? 'Wird hochgeladen ...' : 'Als unterschrieben markieren' }}
            </button>
          </div>
          <p v-if="!hasPdf" class="hint-text">
            Erst wenn ein PDF erzeugt ist, gibt es ein Dokument, das unterschrieben zurückkommen
            kann.
          </p>
        </template>

        <template v-else>
          <p class="signed-note">
            Unterschrieben am {{ formatDateOnly(contract.signed_on)
            }}<template v-if="contract.signed_by_admin">
              — bestätigt von {{ contract.signed_by_admin }}</template
            >.
          </p>
          <div class="action-row">
            <a
              v-if="contract.signed_download_url"
              role="button"
              class="outline"
              :href="contract.signed_download_url"
              target="_blank"
              rel="noopener"
            >
              Unterschriebenen Vertrag ansehen
            </a>
            <button
              type="button"
              class="outline btn-danger"
              :disabled="unsigning"
              :aria-busy="unsigning"
              @click="discardSignature"
            >
              Unterschrift verwerfen
            </button>
          </div>
          <p class="hint-text">
            „Unterschrift verwerfen" gibt das Formular wieder frei. Das hochgeladene Dokument bleibt
            gespeichert, es wandert nur aus der Rolle des gültigen Vertrags.
          </p>
        </template>

        <hr />

        <!-- Die Gegenzeichnung ist optional, blockiert nichts und bleibt auch
             nach der Unterschrift bedienbar — sie darf Jahre später nachgetragen
             werden. -->
        <p v-if="contract?.countersigned_on" class="hint-text">
          Gegengezeichnet am {{ formatDateOnly(contract.countersigned_on) }}
          <template v-if="contract.countersigned_by"> von {{ contract.countersigned_by }}</template
          >.
        </p>
        <div class="action-row">
          <label for="countersignedOn" class="inline-field">
            Gegenzeichnung des Vercharterers am
            <input
              id="countersignedOn"
              v-model="countersignedOn"
              type="date"
              :disabled="!exists || countersigning"
            />
          </label>
          <button
            type="button"
            class="outline"
            :disabled="!exists || !countersignedOn || countersigning"
            :aria-busy="countersigning"
            @click="recordCountersign"
          >
            Gegenzeichnung nachtragen
          </button>
        </div>
        <p class="hint-text">
          Optional. Ein Vertrag gilt als unterschrieben, sobald Charterer und — falls abweichend —
          Schiffsführer gezeichnet haben; die Gegenzeichnung ändert weder Status noch Dokument.
        </p>

        <template v-if="canDelete">
          <hr />
          <div class="action-row">
            <button
              type="button"
              class="outline btn-danger"
              :disabled="deleting"
              :aria-busy="deleting"
              @click="deleteContract"
            >
              Vertragsentwurf löschen
            </button>
          </div>
          <p class="hint-text">
            Geht nur, solange kein PDF erzeugt wurde. Danach bleibt der Vertrag am Event.
          </p>
        </template>
      </section>
    </template>
  </article>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi, postPresignedForm } from '../../services/api'
import PageHeader from '../../components/PageHeader.vue'
import SignaturePad from '../../components/SignaturePad.vue'
import {
  berlinToUTCISO,
  formatDateOnly,
  formatDateTime,
  formatDateTimeLocal,
} from '../../utils/formatters.js'
import { showToast } from '../../composables/useToast.js'

// Der Presign hängt an genau einem Key mit `.pdf` und einem angehefteten
// Content-Type — ein JPEG dort hochzuladen ergibt ein Bild, das PDF heißt.
const SIGNED_CONTENT_TYPE = 'application/pdf'
// Serverseitiges `content-length-range` ist 1..15 MB; hier nur, damit ein zu
// großes Foto nicht erst nach dem Upload an S3 scheitert.
const MAX_UPLOAD_BYTES = 15 * 1024 * 1024

const props = defineProps({
  eventId: { type: String, required: true },
})

const router = useRouter()

const loading = ref(true)
const loadError = ref(null)
const eventName = ref('')

// Die Zeile, wie der Server sie zuletzt geliefert hat — Quelle für alles
// Serverseitige (Status, Versionen, Links). Das Formular daneben ist die
// Tippfläche und kann davon abweichen.
const contract = ref(null)
const exists = ref(false)

const form = reactive({
  charterer_name: '',
  charterer_address: '',
  charterer_email: '',
  charterer_phone: '',
  uebergabe_at: '',
  rueckgabe_at: '',
  chartergebuehr: '',
  sonderleistungen: [],
  kaution: '',
  personen_ohne_skipper: '',
  skipper_name: '',
  skipper_is_charterer: true,
  sbfs_number: '',
  sbfs_issued_on: '',
  sbfb_number: '',
  sbfb_issued_on: '',
  sondervereinbarungen: '',
})

const crewNames = ref([])

const saving = ref(false)
const saveError = ref(null)
const rendering = ref(false)
const sending = ref(false)
const sendingLink = ref(false)
const adminSigning = ref(false)
const inPersonNames = reactive({})
const inPersonImages = reactive({})
const pads = {}
const ccSelf = ref(false)
const confirming = ref(false)
const unsigning = ref(false)
const countersigning = ref(false)
const deleting = ref(false)

const fileInput = ref(null)
const signedFile = ref(null)
const signedOn = ref('')
const alleParteienUnterschrieben = ref(false)
const countersignedOn = ref('')

const isSigned = computed(() => contract.value?.status === 'signed')
// `can_edit` kommt vom Server; solange keine Zeile existiert, ist alles offen.
const locked = computed(() => (contract.value ? contract.value.can_edit === false : false))
const inputsDisabled = computed(() => locked.value || saving.value)
const hasPdf = computed(() => (contract.value?.document_version || 0) > 0)
const canDelete = computed(() => exists.value && !hasPdf.value && !isSigned.value)

const statusLabel = computed(() => {
  const status = contract.value?.status
  if (status === 'signed') {
    return contract.value.signed_on
      ? `Signiert am ${formatDateOnly(contract.value.signed_on)}`
      : 'Signiert'
  }
  if (status === 'sent') return 'Verschickt'
  return 'Entwurf'
})

const statusClass = computed(() => {
  const status = contract.value?.status
  if (status === 'signed') return 'status-participating'
  if (status === 'sent') return 'status-registration_closed'
  return 'status-draft'
})

const renderInfo = computed(() => {
  if (!hasPdf.value) return ''
  const parts = [`Fassung v${contract.value.document_version}`]
  if (contract.value.rendered_at) parts.push(`vom ${formatDateTime(contract.value.rendered_at)}`)
  if (contract.value.template_version) parts.push(`Vorlage ${contract.value.template_version}`)
  return parts.join(' · ')
})

const signatureConfirmLabel = computed(() =>
  form.skipper_is_charterer
    ? 'Charterer hat unterschrieben'
    : 'Charterer und Schiffsführer haben unterschrieben',
)

const canConfirmSigned = computed(
  () =>
    hasPdf.value &&
    !confirming.value &&
    Boolean(signedFile.value) &&
    Boolean(signedOn.value) &&
    alleParteienUnterschrieben.value,
)

function toNumber(value) {
  const raw = String(value ?? '')
    .trim()
    .replace(',', '.')
  if (raw === '') return 0
  const num = Number(raw)
  return Number.isFinite(num) ? num : 0
}

const gesamtbetrag = computed(() => {
  let total = toNumber(form.chartergebuehr)
  for (const line of form.sonderleistungen) total += toNumber(line.amount)
  return total
})

const gesamtbetragLabel = computed(() =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(gesamtbetrag.value),
)

// Solange die Checkbox steht, ist der Schiffsführer der Charterer — auch
// während getippt wird, damit das Feld nicht mit einem alten Namen stehen
// bleibt, wenn der Charterer korrigiert wird.
watch(
  () => [form.skipper_is_charterer, form.charterer_name],
  () => {
    if (form.skipper_is_charterer) form.skipper_name = form.charterer_name
  },
)

function applyContract(payload) {
  contract.value = payload
  exists.value = true
  form.charterer_name = payload.charterer_name || ''
  form.charterer_address = payload.charterer_address || ''
  form.charterer_email = payload.charterer_email || ''
  form.charterer_phone = payload.charterer_phone || ''
  form.uebergabe_at = payload.uebergabe_at ? formatDateTimeLocal(payload.uebergabe_at) : ''
  form.rueckgabe_at = payload.rueckgabe_at ? formatDateTimeLocal(payload.rueckgabe_at) : ''
  form.chartergebuehr = payload.chartergebuehr ?? ''
  form.sonderleistungen = (payload.sonderleistungen || []).map((line) => ({
    description: line.description || '',
    amount: line.amount ?? '',
  }))
  form.kaution = payload.kaution ?? ''
  form.personen_ohne_skipper = payload.personen_ohne_skipper ?? ''
  form.skipper_name = payload.skipper_name || ''
  form.skipper_is_charterer = payload.skipper_is_charterer !== false
  form.sbfs_number = payload.sbfs_number || ''
  form.sbfs_issued_on = payload.sbfs_issued_on || ''
  form.sbfb_number = payload.sbfb_number || ''
  form.sbfb_issued_on = payload.sbfb_issued_on || ''
  form.sondervereinbarungen = payload.sondervereinbarungen || ''
  // Das Datum auf dem Papier ist die einzige Eingabe, die nach einem erneuten
  // Laden wieder sichtbar sein soll; die Datei selbst kann der Browser nicht
  // zurückgeben.
  signedOn.value = payload.signed_on || ''
  countersignedOn.value = payload.countersigned_on || ''
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const [payload, event] = await Promise.all([
      // Ohne Vertragszeile antwortet die Route mit 404 — das ist der
      // Normalfall beim ersten Öffnen, kein Fehler.
      adminApi.getCharterContract(props.eventId).catch((err) => {
        if (err.status === 404) return null
        throw err
      }),
      adminApi.getEvent(props.eventId).catch(() => null),
    ])
    eventName.value = event?.name || ''
    if (payload) {
      applyContract(payload)
    } else if (event?.start_at) {
      // Vorbelegung nur beim ersten Öffnen: der Fahrttag ist fast immer auch
      // der Übergabetag, die Uhrzeiten korrigiert die Orga von Hand.
      const local = formatDateTimeLocal(event.start_at)
      form.uebergabe_at = local
      form.rueckgabe_at = local
    }
  } catch (err) {
    loadError.value = err.message || 'Chartervertrag konnte nicht geladen werden'
  } finally {
    loading.value = false
  }
}

async function loadCrewNames() {
  try {
    // Dieselbe Quelle wie der Crew-Picker im Fahrbericht; der Charterer ist in
    // aller Regel selbst Skipper*in, deshalb hängt die Liste an beiden
    // Namensfeldern.
    const res = await adminApi.listCrewSuggestions({ role: 'SKIPPER', limit: 50 })
    crewNames.value = [...new Set((res?.items || []).map((item) => item.display_name))]
  } catch {
    // Eine fehlende Vorschlagsliste macht das Formular nicht unbrauchbar.
    crewNames.value = []
  }
}

function addExpense() {
  form.sonderleistungen.push({ description: '', amount: '' })
}

function removeExpense(idx) {
  form.sonderleistungen.splice(idx, 1)
}

// Geld als String, nicht als JSON-Zahl: pydantic baut den `Decimal` dann aus
// genau den getippten Ziffern, statt aus einem Float mit Nachkommarauschen.
function moneyOrNull(value) {
  const raw = String(value ?? '')
    .trim()
    .replace(',', '.')
  if (raw === '') return null
  return Number.isFinite(Number(raw)) ? raw : null
}

function buildPayload() {
  return {
    charterer_name: form.charterer_name,
    charterer_address: form.charterer_address,
    charterer_email: form.charterer_email || null,
    charterer_phone: form.charterer_phone || null,
    sondervereinbarungen: form.sondervereinbarungen || null,
    uebergabe_at: form.uebergabe_at ? berlinToUTCISO(form.uebergabe_at) : null,
    rueckgabe_at: form.rueckgabe_at ? berlinToUTCISO(form.rueckgabe_at) : null,
    chartergebuehr: moneyOrNull(form.chartergebuehr),
    // `ExpenseLine.description` verlangt mindestens ein Zeichen — eine leere
    // Zeile würde die ganze Speicherung mit einem 422 abweisen.
    sonderleistungen: form.sonderleistungen
      .filter((line) => line.description.trim() !== '')
      .map((line) => ({
        description: line.description.trim(),
        amount: moneyOrNull(line.amount) ?? '0',
      })),
    kaution: moneyOrNull(form.kaution),
    personen_ohne_skipper:
      String(form.personen_ohne_skipper).trim() === '' ? null : Number(form.personen_ohne_skipper),
    skipper_name: form.skipper_is_charterer ? form.charterer_name : form.skipper_name,
    skipper_is_charterer: form.skipper_is_charterer,
    sbfs_number: form.sbfs_number || null,
    sbfs_issued_on: form.sbfs_issued_on || null,
    sbfb_number: form.sbfb_number || null,
    sbfb_issued_on: form.sbfb_issued_on || null,
  }
}

async function save() {
  if (locked.value) return
  saving.value = true
  saveError.value = null
  try {
    const payload = await adminApi.saveCharterContract(props.eventId, buildPayload())
    applyContract(payload)
    showToast('Gespeichert', 'success')
  } catch (err) {
    saveError.value = err.message || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

async function renderPdf() {
  rendering.value = true
  saveError.value = null
  try {
    const payload = await adminApi.renderCharterContract(props.eventId)
    applyContract(payload)
    showToast(`PDF erzeugt — Fassung v${payload.document_version}`, 'success')
  } catch (err) {
    // Der Pflichtsatz-422 nennt die fehlenden Felder auf Deutsch; der gehört
    // an den Anfang der Seite, nicht in einen Toast, der wegläuft.
    saveError.value = err.message || 'PDF konnte nicht erzeugt werden'
    showToast(err.message || 'PDF konnte nicht erzeugt werden', 'error')
  } finally {
    rendering.value = false
  }
}

async function sendToCharterer() {
  sending.value = true
  try {
    const payload = await adminApi.sendCharterContract(props.eventId, { cc_self: ccSelf.value })
    applyContract(payload)
    showToast('Vertrag verschickt', 'success')
  } catch (err) {
    showToast(err.message || 'Versand fehlgeschlagen', 'error')
  } finally {
    sending.value = false
  }
}

function onFilePicked(event) {
  const file = event.target.files?.[0] || null
  if (!file) {
    signedFile.value = null
    return
  }
  if (file.type && file.type !== SIGNED_CONTENT_TYPE) {
    signedFile.value = null
    event.target.value = ''
    showToast('Bitte ein PDF hochladen — ein Foto vorher als PDF speichern.', 'error')
    return
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    signedFile.value = null
    event.target.value = ''
    showToast('Die Datei ist größer als 15 MB.', 'error')
    return
  }
  signedFile.value = file
}

async function markAsSigned() {
  if (!canConfirmSigned.value) return
  confirming.value = true
  try {
    const target = await adminApi.requestCharterUpload(props.eventId, {
      content_type: SIGNED_CONTENT_TYPE,
    })
    await postPresignedForm(target, signedFile.value)
    const payload = await adminApi.confirmCharterSigned(props.eventId, {
      signed_on: signedOn.value,
      alle_parteien_unterschrieben: true,
    })
    applyContract(payload)
    signedFile.value = null
    alleParteienUnterschrieben.value = false
    if (fileInput.value) fileInput.value.value = ''
    showToast('Als unterschrieben markiert', 'success')
  } catch (err) {
    showToast(err.message || 'Upload fehlgeschlagen', 'error')
  } finally {
    confirming.value = false
  }
}

async function recordCountersign() {
  if (!countersignedOn.value) return
  countersigning.value = true
  try {
    // Wer gegengezeichnet hat, nimmt der Server aus dem Token — hier wird nur
    // das Datum nachgetragen.
    const payload = await adminApi.recordCharterCountersign(props.eventId, {
      countersigned_on: countersignedOn.value,
    })
    applyContract(payload)
    showToast('Gegenzeichnung nachgetragen', 'success')
  } catch (err) {
    showToast(err.message || 'Gegenzeichnung konnte nicht nachgetragen werden', 'error')
  } finally {
    countersigning.value = false
  }
}

async function discardSignature() {
  const ok = window.confirm(
    'Unterschrift verwerfen? Der Vertrag wird wieder zum Entwurf und lässt sich ändern. ' +
      'Das hochgeladene Dokument bleibt gespeichert, gilt aber nicht mehr als der ' +
      'unterschriebene Vertrag.',
  )
  if (!ok) return
  unsigning.value = true
  try {
    const payload = await adminApi.unsignCharterContract(props.eventId)
    applyContract(payload)
    showToast('Unterschrift verworfen', 'success')
  } catch (err) {
    showToast(err.message || 'Unterschrift konnte nicht verworfen werden', 'error')
  } finally {
    unsigning.value = false
  }
}

async function deleteContract() {
  const ok = window.confirm('Vertragsentwurf löschen? Alle eingetragenen Angaben sind danach weg.')
  if (!ok) return
  deleting.value = true
  try {
    await adminApi.deleteCharterContract(props.eventId)
    showToast('Vertragsentwurf gelöscht', 'success')
    router.push(`/admin/events/${props.eventId}`)
  } catch (err) {
    showToast(err.message || 'Löschen fehlgeschlagen', 'error')
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  load()
  loadCrewNames()
})
const signatures = computed(() => contract.value?.signatures || [])

// Roles that still need a signature, in the order they appear on the sheet.
// The Vercharterer is included: countersigning is optional, but if it IS going
// to happen the pontoon is the moment, and the API accepts the role.
const openRoles = computed(() => {
  const c = contract.value
  if (!c) return []
  const signed = new Set(signatures.value.map((s) => s.role))
  const wanted = ['charterer']
  if (!c.skipper_is_charterer) wanted.push('skipper')
  wanted.push('vercharterer')
  return wanted.filter((r) => !signed.has(r))
})

function setPad(role, el) {
  if (el) pads[role] = el
  else delete pads[role]
}

function defaultNameFor(role) {
  if (role === 'charterer') return form.charterer_name || ''
  if (role === 'skipper') return form.skipper_name || ''
  return ''
}

function canSignInPerson(role) {
  const typed = (inPersonNames[role] ?? defaultNameFor(role)).trim()
  return typed.length > 2
}

async function signInPerson(role) {
  const name = (inPersonNames[role] ?? defaultNameFor(role)).trim()
  adminSigning.value = true
  try {
    contract.value = await adminApi.signCharterAsAdmin(props.eventId, {
      role,
      signed_name: name,
      image_b64: inPersonImages[role] || null,
    })
    pads[role]?.clear?.()
    delete inPersonImages[role]
    delete inPersonNames[role]
    showToast(`${roleLabel(role)} hat unterschrieben`, 'success')
  } catch (err) {
    showToast(err.message || 'Unterschrift fehlgeschlagen', 'error')
  } finally {
    adminSigning.value = false
  }
}

const ROLE_LABELS = {
  charterer: 'Charterer',
  skipper: 'Schiffsführer',
  vercharterer: 'Vercharterer',
}

function roleLabel(role) {
  return ROLE_LABELS[role] || role
}

async function sendSigningLink() {
  sendingLink.value = true
  try {
    contract.value = await adminApi.sendCharterSigningLink(props.eventId)
    showToast('Signaturlink verschickt', 'success')
  } catch (err) {
    showToast(err.message || 'Signaturlink konnte nicht verschickt werden', 'error')
  } finally {
    sendingLink.value = false
  }
}
</script>

<style scoped>
.inperson-row {
  padding: var(--space-3, 0.75rem) 0;
  border-top: 1px solid var(--muted-border-color, #e2e8f0);
}

.inperson-row:first-of-type {
  border-top: none;
}

.signature-list {
  margin: var(--space-2, 0.5rem) 0;
  padding-left: 1.1rem;
  font-size: var(--text-sm, 0.875rem);
  color: var(--color-text-muted, #64748b);
}

.error {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
}

.hint-box {
  background: var(--color-info-subtle-bg);
  color: var(--color-info-subtle-text);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
}

.locked-note {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
}

.warning-box {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  padding: 0.75rem;
  border-radius: var(--radius-md);
  font-size: 0.9em;
}

.hint-text {
  font-size: 0.875rem;
  color: var(--color-text-muted);
  margin-bottom: 0;
}

.signed-note {
  font-weight: 600;
  margin-bottom: var(--space-3);
}

.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.expenses {
  margin-bottom: var(--space-3);
}

.expense-row {
  display: grid;
  grid-template-columns: 1fr 8rem auto;
  gap: 0.4rem;
  align-items: center;
  margin-bottom: 0.4rem;
}

.expense-row input {
  margin: 0;
}

.row-remove {
  width: auto;
  margin: 0;
  min-height: 44px;
  padding: 0 0.8rem;
  background: transparent;
  border: none;
  color: var(--color-danger-text);
  font-size: 1.2rem;
}

.row-add {
  width: 100%;
  margin: 0 0 var(--space-2);
  min-height: 44px;
  background: transparent;
  border: 1.5px dashed var(--color-border);
  color: var(--color-text-muted);
}

#gesamtbetrag {
  font-weight: 700;
}

.checkbox-row {
  margin-bottom: 0.25rem;
}

.checkbox-inline {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0 0 var(--space-2);
  font-size: 0.875rem;
}

.checkbox-inline input {
  margin: 0;
}

.inline-field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 0.875rem;
}

.inline-field input {
  margin: 0;
  width: auto;
}

.actions hr {
  margin: var(--space-4) 0;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: var(--space-2);
}

.action-row button,
.action-row a[role='button'] {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.action-row input[type='file'] {
  margin: 0;
}

.sr-label {
  margin-bottom: 0;
}

@media (max-width: 520px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
