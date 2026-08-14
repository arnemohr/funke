import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../services/api'
import { showToast } from './useToast.js'
import { berlinToUTCISO } from '../utils/formatters.js'

/**
 * Composable encapsulating all event action handlers and their associated state.
 *
 * @param {object} options
 * @param {import('vue').Ref} options.event - Reactive ref to the current event object
 * @param {import('vue').Ref} options.registrations - Reactive ref to the array of registrations
 * @param {Function} options.refreshEvent - Async function to reload event data
 * @param {Function} options.refreshRegistrations - Async function to reload registrations
 */
export function useEventActions({ event, registrations, refreshEvent, refreshRegistrations }) {
  const router = useRouter()

  // --- Loading states ---
  const publishing = ref(false)
  const closingRegistration = ref(false)
  const reopeningRegistration = ref(false)
  const completing = ref(false)
  const togglingPromotedId = ref(null)

  // --- Clone modal (stays a modal — one field) ---
  const cloneEvent = ref(null)
  const cloneStartAt = ref('')
  const cloning = ref(false)
  const cloneError = ref(null)

  // --- Cancel modal (stays a modal — confirmation only) ---
  const cancelEventData = ref(null)
  const cancelConfirmation = ref('')
  const cancelling = ref(false)
  const cancelError = ref(null)

  // --- Delete event modal (stays a modal — confirmation only) ---
  const deleteEventData = ref(null)
  const deleting = ref(false)
  const deleteError = ref(null)

  // --- Delete registration modal ---
  const deleteRegData = ref(null)

  // --- Capacity warning ---
  const capacityWarning = ref(null)

  // --- Messaging ---
  const showMessageComposer = ref(false)

  // --- Action handlers ---

  async function publishEvent(evt) {
    publishing.value = true
    try {
      const updated = await adminApi.publishEvent(evt.id)
      event.value = updated
      showToast('Veranstaltung veröffentlicht', 'success')
    } catch (err) {
      showToast(err.message || 'Veröffentlichung fehlgeschlagen', 'error')
    } finally {
      publishing.value = false
    }
  }

  async function closeRegistration(evt) {
    closingRegistration.value = true
    try {
      const updated = await adminApi.closeRegistration(evt.id)
      event.value = updated
      showToast('Anmeldung geschlossen', 'success')
    } catch (err) {
      showToast(err.message || 'Anmeldung konnte nicht geschlossen werden', 'error')
    } finally {
      closingRegistration.value = false
    }
  }

  async function reopenRegistration(evt) {
    reopeningRegistration.value = true
    try {
      const updated = await adminApi.reopenRegistration(evt.id)
      event.value = updated
      showToast('Anmeldung wieder geöffnet', 'success')
    } catch (err) {
      showToast(err.message || 'Anmeldung konnte nicht wieder geöffnet werden', 'error')
    } finally {
      reopeningRegistration.value = false
    }
  }

  async function completeEvent(evt) {
    // Same one-way door as the festival page's COMPLETED transition — and the
    // sibling action („Absagen") already demands a typed confirmation, so this
    // one firing straight off the click was an inconsistency, not a decision.
    const ok = window.confirm(
      'Veranstaltung wirklich abschließen?\n\n' +
        'Anmeldungen lassen sich danach nicht mehr bearbeiten.\n\n' +
        'Das lässt sich nicht rückgängig machen.',
    )
    if (!ok) return

    completing.value = true
    try {
      const updated = await adminApi.completeEvent(evt.id)
      event.value = updated
      showToast('Veranstaltung abgeschlossen', 'success')
    } catch (err) {
      showToast(err.message || 'Abschließen fehlgeschlagen', 'error')
    } finally {
      completing.value = false
    }
  }

  function showCloneModal(evt) {
    cloneEvent.value = evt
    cloneStartAt.value = ''
    cloneError.value = null
  }

  async function handleClone() {
    cloning.value = true
    cloneError.value = null
    try {
      const cloned = await adminApi.cloneEvent(cloneEvent.value.id, berlinToUTCISO(cloneStartAt.value))
      cloneEvent.value = null
      router.push('/admin/events/' + cloned.id)
    } catch (err) {
      cloneError.value = err.message || 'Duplizieren fehlgeschlagen'
    } finally {
      cloning.value = false
    }
  }

  function copyRegistrationLink(evt) {
    const link = `${window.location.origin}/register/${evt.registration_link_token}`
    navigator.clipboard.writeText(link).then(
      () => showToast('Anmeldelink wurde kopiert!', 'success'),
      () => prompt('Kopiere diesen Link:', link),
    )
  }

  function copyInviteText(evt) {
    const link = `${window.location.origin}/register/${evt.registration_link_token}`
    const date = new Date(evt.start_at)
    const dateStr = date.toLocaleDateString('de-DE', {
      timeZone: 'Europe/Berlin',
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
    const timeStr = date.toLocaleTimeString('de-DE', {
      timeZone: 'Europe/Berlin',
      hour: '2-digit',
      minute: '2-digit',
    })

    let text = `⛵ ${evt.name}\n\n`
    if (evt.description) {
      text += `${evt.description}\n\n`
    }
    text += `📅 ${dateStr} um ${timeStr} Uhr\n`
    if (evt.location) {
      text += `📍 ${evt.location}\n`
    }
    text += `👥 ${evt.capacity} Plätze\n`
    text += `\n🔗 Jetzt anmelden: ${link}`

    navigator.clipboard.writeText(text).then(
      () => showToast('Einladungstext wurde kopiert!', 'success'),
      () => prompt('Kopiere diesen Text:', text),
    )
  }

  function goToLottery(evt) {
    router.push({ name: 'admin-event-lottery', params: { eventId: evt.id } })
  }

  function goToEdit(evt) {
    router.push({ name: 'admin-event-edit', params: { eventId: evt.id } })
  }

  function goToDiscard(evt) {
    router.push({ name: 'admin-event-discard', params: { eventId: evt.id } })
  }

  function showCancelEventModal(evt) {
    cancelEventData.value = evt
    cancelConfirmation.value = ''
    cancelError.value = null
  }

  async function handleCancelEvent() {
    if (cancelConfirmation.value !== 'absagen') return
    cancelling.value = true
    cancelError.value = null
    try {
      const updated = await adminApi.cancelEvent(cancelEventData.value.id)
      event.value = updated
      cancelEventData.value = null
    } catch (err) {
      cancelError.value = err.message || 'Absage fehlgeschlagen'
    } finally {
      cancelling.value = false
    }
  }

  function showDeleteModal(evt) {
    deleteEventData.value = evt
    deleteError.value = null
  }

  async function handleDelete() {
    deleting.value = true
    deleteError.value = null
    try {
      await adminApi.deleteEvent(deleteEventData.value.id)
      deleteEventData.value = null
      router.push('/admin/events')
    } catch (err) {
      deleteError.value = err.message || 'Veranstaltung konnte nicht gelöscht werden'
    } finally {
      deleting.value = false
    }
  }

  async function handleExportPdf() {
    try {
      await adminApi.exportBoardingPdf(event.value.id)
    } catch (err) {
      showToast(err.message || 'Boardingzettel konnte nicht erstellt werden', 'error')
    }
  }

  async function handleTogglePromoted({ registrationId, promoted }) {
    if (!event.value) return
    togglingPromotedId.value = registrationId
    try {
      await adminApi.togglePromoted(event.value.id, registrationId, promoted)
      await Promise.all([refreshRegistrations(), refreshEvent()])
    } catch (err) {
      showToast(err.message || 'Bevorzugung konnte nicht geändert werden', 'error')
    } finally {
      togglingPromotedId.value = null
    }
  }

  async function handlePromoteWaitlisted({ registrationId, targetStatus }) {
    if (!event.value) return

    const reg = registrations.value.find(r => r.id === registrationId)
    if (reg) {
      const confirmedSpots = registrations.value
        .filter(r => ['CONFIRMED', 'PARTICIPATING'].includes(r.status))
        .reduce((sum, r) => sum + r.group_size, 0)
      const remaining = event.value.capacity - confirmedSpots
      if (reg.group_size > remaining) {
        capacityWarning.value = {
          needed: reg.group_size,
          remaining,
          name: reg.name,
        }
        return
      }
    }

    try {
      await adminApi.promoteFromWaitlist(event.value.id, registrationId, targetStatus)
      await Promise.all([refreshRegistrations(), refreshEvent()])
    } catch (err) {
      showToast(err.message || 'Nachrücken fehlgeschlagen', 'error')
    }
  }

  function handleDeleteRegistration({ registrationId, name }) {
    if (!event.value) return
    deleteRegData.value = { registrationId, name }
  }

  async function confirmDeleteRegistration() {
    if (!event.value || !deleteRegData.value) return
    const { registrationId } = deleteRegData.value
    deleteRegData.value = null
    try {
      await adminApi.deleteRegistration(event.value.id, registrationId)
      await Promise.all([refreshRegistrations(), refreshEvent()])
    } catch (err) {
      showToast(err.message || 'Löschen fehlgeschlagen', 'error')
    }
  }

  return {
    // Loading states
    publishing,
    closingRegistration,
    reopeningRegistration,
    completing,
    togglingPromotedId,

    // Clone modal
    cloneEvent,
    cloneStartAt,
    cloning,
    cloneError,

    // Cancel modal
    cancelEventData,
    cancelConfirmation,
    cancelling,
    cancelError,

    // Delete event modal
    deleteEventData,
    deleting,
    deleteError,

    // Delete registration modal
    deleteRegData,

    // Capacity warning
    capacityWarning,

    // Messaging
    showMessageComposer,

    // Handlers
    publishEvent,
    closeRegistration,
    reopenRegistration,
    completeEvent,
    showCloneModal,
    handleClone,
    copyRegistrationLink,
    copyInviteText,
    goToLottery,
    goToEdit,
    goToDiscard,
    showCancelEventModal,
    handleCancelEvent,
    showDeleteModal,
    handleDelete,
    handleExportPdf,
    handleTogglePromoted,
    handlePromoteWaitlisted,
    handleDeleteRegistration,
    confirmDeleteRegistration,
  }
}
