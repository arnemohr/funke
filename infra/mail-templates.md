# Email Templates

All outbound email templates used by the Funke backend.

Sources:
- `backend/app/services/email_service.py` — `EmailTemplates` class + `EmailService.send_custom_message`
- `backend/app/services/report_service.py` — `send_report_email` (Fahrbericht to Finance)
- `backend/app/templates/report.html` — PDF body of the Fahrbericht (attached, not the email body)

Placeholders use `{ctx.…}` (Python f-strings) for the registration emails and `{…}` for the Fahrbericht email.

`EmailContext` fields available to registration templates:

| Field | Notes |
| --- | --- |
| `event_name` | Event title |
| `event_date` | Pre-formatted German long form, e.g. `Samstag, 17. Mai 2026 um 19:00` |
| `event_location` | May be `None` → falls back to "Wird noch bekannt gegeben" |
| `registration_deadline` | German long form, optional |
| `attendee_name` | Recipient name |
| `attendee_email` | Recipient email |
| `group_size` | Integer; templates pluralise "Person"/"Personen" |
| `registration_status` | Enum value |
| `waitlist_position` | Optional |
| `management_url` | Tokenised self-service URL |
| `custom_message` | Used by `registration_cancelled` |

---

## 1. Registration Confirmed

**Trigger:** `EmailService.send_registration_confirmation` — fired when a registration is accepted into the open list (no lottery yet).
**Message type:** `REGISTRATION_CONFIRMATION`

**Subject:**
```
Anmeldung eingegangen: {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

schön, dass du dabei sein willst! Deine Anmeldung für "{ctx.event_name}" ist bei uns eingegangen.

So geht's weiter:
- Bis zum Anmeldeschluss sammeln wir alle Anmeldungen.
- Gibt es mehr Anmeldungen als Plätze, entscheidet das Los.
- Du bekommst danach eine E-Mail, ob du einen Platz hast.

Deine Anmeldung:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}
- Anmeldeschluss: {ctx.registration_deadline or 'Nicht festgelegt'}

Deine Anmeldung verwalten:
{ctx.management_url}

Bei Fragen, einfach melden!

Bis bald,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Anmeldung eingegangen ✓</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>schön, dass du dabei sein willst! Deine Anmeldung für <strong>"{ctx.event_name}"</strong> ist bei uns eingegangen.</p>

    <h3>So geht's weiter</h3>
    <ul>
        <li>Bis zum Anmeldeschluss sammeln wir alle Anmeldungen.</li>
        <li>Gibt es mehr Anmeldungen als Plätze, entscheidet das Los.</li>
        <li>Du bekommst danach eine E-Mail, ob du einen Platz hast.</li>
    </ul>

    <h3>Deine Anmeldung</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
        <li><strong>Anmeldeschluss:</strong> {ctx.registration_deadline or 'Nicht festgelegt'}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>

    <p>Bei Fragen, einfach melden!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 2. Registration Waitlisted

**Trigger:** `EmailService.send_waitlist_notification` — sent when a registration lands directly on the waitlist (event already full at submission time).
**Message type:** `WAITLIST_NOTIFICATION`

**Subject:**
```
Warteliste: {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

Danke für deine Anmeldung zu "{ctx.event_name}".

Du stehst auf der Warteliste. Sobald ein Platz frei wird, rückst du automatisch nach und wir benachrichtigen dich.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Deine Anmeldung verwalten:
{ctx.management_url}

Bis bald,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Du stehst auf der Warteliste</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>

    <p>Du stehst auf der Warteliste. Sobald ein Platz frei wird, rückst du automatisch nach und wir benachrichtigen dich.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>

    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 3. Registration Cancelled

**Trigger:** `EmailService.send_cancellation_confirmation` — sent when an admin (or the user) cancels a registration. The admin can pass a custom `reason` and `subject_override`.
**Message type:** `CANCELLATION`

**Subject (default):**
```
Dein Platz an Bord: {ctx.event_name}
```
*(`subject_override` replaces this string verbatim if provided.)*

**Custom message:** body wraps `ctx.custom_message`; falls back to the default below if not set.

**Default fallback message:**
```
Leider haben wir innerhalb der Frist keine Rückmeldung von dir erhalten, ob du wirklich mit an Bord kommst. Daher mussten wir deinen Platz an einen anderen Fisch aus unserem Schwarm weitergeben.

Falls du beim nächsten Mal wieder anheuern möchtest, freuen wir uns sehr auf dich!
```

**Text body:**
```
Moin {ctx.attendee_name},

{message_body}

Herzliche Grüße,
Deine Crew von der Schaluppe
```

**HTML body:** (`\n` in `message_body` is converted to `<br>`)
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #555;">Info zu deiner Anmeldung</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>{html_message}</p>

    <p>Herzliche Grüße,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 4. Promoted From Waitlist

**Trigger:** `EmailService.send_promotion_notification` — sent when a waitlist entry is auto-promoted to confirmed (someone else dropped out).
**Message type:** `CONFIRMATION_REQUEST`

**Subject:**
```
Platz frei! {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

ein Fisch ist abgesprungen und du rückst nach! Du hast jetzt einen Platz an Bord der Schaluppe für "{ctx.event_name}".

- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:

{ctx.management_url}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Wir freuen uns auf dich!

Liebste Grüße,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Platz frei!</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Ein Fisch ist abgesprungen und du rückst nach! Du hast jetzt einen Platz an Bord der Schaluppe für <strong>"{ctx.event_name}"</strong>.</p>

    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p><strong>Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:</strong></p>

    <p style="margin: 20px 0;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 12px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Anmeldung verwalten</a>
    </p>

    <p style="color: #666; font-size: 0.9em;">
        Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.
    </p>

    <p>Wir freuen uns auf dich!</p>
    <p>Liebste Grüße,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 5. Lottery Winner

**Trigger:** `EmailService.send_lottery_winner` — sent after lottery draw to selected attendees.
**Message type:** `LOTTERY_RESULT`

**Subject:**
```
Platz reserviert — bitte bestätigen: {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

gute Nachrichten: Du wurdest für "{ctx.event_name}" ausgelost und dein Platz ist reserviert!

- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Damit der Platz nicht verfällt, bestätige bitte innerhalb von 24 Stunden:

{ctx.management_url}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Wir freuen uns auf dich!

Liebste Grüße,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #b45309;">🎉 Platz reserviert — bitte bestätigen</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Gute Nachrichten: Du wurdest für <strong>"{ctx.event_name}"</strong> ausgelost und dein Platz ist reserviert!</p>

    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="background: #fffbeb; border: 1px solid #f59e0b; border-radius: 6px; padding: 12px; color: #92400e;">
        <strong>Damit der Platz nicht verfällt, bestätige bitte innerhalb von 24 Stunden:</strong>
    </p>

    <p style="margin: 20px 0;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 12px 24px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Jetzt bestätigen</a>
    </p>

    <p style="color: #666; font-size: 0.9em;">
        Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.
    </p>

    <p>Wir freuen uns auf dich!</p>
    <p>Liebste Grüße,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 6. Lottery Waitlisted

**Trigger:** `EmailService.send_lottery_waitlist` — sent to lottery losers who go onto the waitlist.
**Message type:** `LOTTERY_RESULT`

**Subject:**
```
Verlosung: Warteliste für {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

Danke für deine Anmeldung zu "{ctx.event_name}".

Bei der Verlosung hast du leider keinen Platz bekommen, aber du stehst auf der Warteliste.
Sobald ein Platz frei wird, benachrichtigen wir dich sofort.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Deine Anmeldung verwalten:
{ctx.management_url}

Drück die Daumen!

Bis bald,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Du stehst auf der Warteliste</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>

    <p>Bei der Verlosung hast du leider keinen Platz bekommen, aber du stehst auf der Warteliste.
    Sobald ein Platz frei wird, benachrichtigen wir dich sofort.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>

    <p>Drück die Daumen!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 7. Lottery Rejected (No Waitlist)

**Trigger:** `EmailService.send_lottery_rejection` — sent to lottery losers when the waitlist is closed/full.
**Message type:** `LOTTERY_RESULT`

**Subject:**
```
Verlosung: Leider nicht dabei bei {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

Danke für deine Anmeldung zu "{ctx.event_name}".

Leider hast du bei der Verlosung keinen Platz bekommen.
Die Nachfrage war diesmal einfach zu groß.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Wir hoffen, dich beim nächsten Mal dabei zu haben!

Bis bald,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Verlosungsergebnis</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>
    <p>Leider hast du bei der Verlosung keinen Platz bekommen.
    Die Nachfrage war diesmal einfach zu groß.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p>Wir hoffen, dich beim nächsten Mal dabei zu haben!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 8. Event Cancelled

**Trigger:** `EmailService.send_event_cancellation` — fan-out when admin cancels an entire event.
**Message type:** `CANCELLATION`

**Subject:**
```
Veranstaltung abgesagt: {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

Leider müssen wir dir mitteilen, dass "{ctx.event_name}" abgesagt wurde.

Ursprüngliche Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}

Wir entschuldigen uns für die Unannehmlichkeiten.

Bis bald,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #dc2626;">Veranstaltung abgesagt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Leider müssen wir dir mitteilen, dass <strong>"{ctx.event_name}"</strong> abgesagt wurde.</p>

    <h3>Ursprüngliche Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
    </ul>

    <p>Wir entschuldigen uns für die Unannehmlichkeiten.</p>

    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 9. Confirmation Request

**Trigger:** `EmailService.send_confirmation_request` — reminder X days before the event asking the attendee to confirm.
**Message type:** `CONFIRMATION_REQUEST`

Urgency word depends on `days_until_event`:
- `<= 1` → `morgen`
- `<= 3` → `bald`
- else → `in {days_until_event} Tagen`

**Subject:**
```
Bitte bestätigen: {ctx.event_name} ist {urgency}!
```

**Text body:**
```
Moin {ctx.attendee_name},

"{ctx.event_name}" steht {urgency} an!

- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size}

Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:

{ctx.management_url}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Liebste Grüße,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2563eb;">Bitte bestätige deine Teilnahme</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p><strong>"{ctx.event_name}"</strong> steht {urgency} an!</p>

    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size}</li>
    </ul>

    <p><strong>Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:</strong></p>

    <div style="margin: 20px 0;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 12px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Anmeldung verwalten</a>
    </div>

    <p style="color: #666; font-size: 0.9em;">
        Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.
    </p>

    <p>Liebste Grüße,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 10. Attendance Response Confirmation — YES

**Trigger:** `EmailService.send_attendance_response_confirmation(participating=True)` — receipt after the user clicks "Ja, ich komme".
**Message type:** `CONFIRMATION_REQUEST`

**Subject:**
```
Rückmeldung bestätigt: {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

Danke für deine Rückmeldung! Deine Teilnahme an "{ctx.event_name}" ist bestätigt.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}

Wir freuen uns auf dich!

Bis bald,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Teilnahme bestätigt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Rückmeldung! Deine Teilnahme an <strong>"{ctx.event_name}"</strong> ist bestätigt.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
    </ul>

    <p>Wir freuen uns auf dich!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 11. Attendance Response Confirmation — NO

**Trigger:** `EmailService.send_attendance_response_confirmation(participating=False)` — receipt after the user clicks "Nein".
**Message type:** `CONFIRMATION_REQUEST`

**Subject:**
```
Rückmeldung bestätigt: {ctx.event_name}
```

**Text body:**
```
Moin {ctx.attendee_name},

Deine Absage für "{ctx.event_name}" wurde erfasst. Schade, dass du nicht dabei sein kannst.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}

Vielleicht beim nächsten Mal!

Bis bald,
Deine Crew von der Schaluppe
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Absage bestätigt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Deine Absage für <strong>"{ctx.event_name}"</strong> wurde erfasst. Schade, dass du nicht dabei sein kannst.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
    </ul>

    <p>Vielleicht beim nächsten Mal!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
```

---

## 12. Custom Admin Message

**Trigger:** `EmailService.send_custom_message` — free-form mail composed by an admin in the events admin UI. `include_links=True` appends the management button/link.
**Message type:** `CUSTOM`

**Subject:** provided verbatim by the admin.

**Text body:** the admin-provided `body`, optionally followed by:
```
---
Anmeldung verwalten: {manage_url}
```

**HTML body:**
```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <p>{body with newlines converted to <br>}</p>{html_links}
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
    <p style="color: #666; font-size: 0.9em;">
        Diese Nachricht bezieht sich auf die Veranstaltung "{event.name}".
    </p>
    <p style="color: #666; font-size: 0.9em;">Deine Crew von der Schaluppe</p>
</body>
</html>
```

`html_links` (only when `include_links=True`):
```html
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
    <p style="margin: 10px 0;">
        <a href="{manage_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Anmeldung verwalten</a>
    </p>
```

---

## 13. Fahrbericht to Finance

**Trigger:** `ReportService.send_report_email` — sent to the finance recipient after a Fahrbericht is finalised. Includes the PDF (rendered from `backend/app/templates/report.html`) as an attachment.
**Message type:** plain `EmailMessage` via `gmail_client` (not stored in the `Message` table the same way as registration mails).

**Subject (initial version):**
```
Schaluppe Fahrbericht – {date_str} – {event_name}
```

**Subject (updates, v2+):**
```
Schaluppe Fahrbericht (Aktualisierung v{version}) – {date_str} – {event_name}
```

**Body (initial version):**
```
Hallo Finance-Team,

anbei der Fahrbericht der Schaluppe vom {date_str}.

{booking_text}

— Funke
```

**Body (updates, v2+):**
```
Hallo Finance-Team,

anbei die aktualisierte Version v{version} des Fahrberichts der Schaluppe vom {date_str}.

{booking_text}

— Funke
```

**Attachment:** `fahrbericht-{date_str}-v{version}.pdf` (content type `application/pdf`), rendered from `app/templates/report.html`. That template is the *PDF body*, not the email body; it is reproduced below for completeness.

<details>
<summary><code>app/templates/report.html</code> (Jinja2 source for the attached PDF)</summary>

```html
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Schaluppe Fahrbericht – {{ event.date }}</title>
<style>
  @page { size: A4; margin: 1.6cm 1.4cm 1.8cm 1.4cm; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif; color: #1e1e1e; font-size: 10pt; line-height: 1.45; }
  header { border-bottom: 2px solid #1a2744; padding-bottom: 8pt; margin-bottom: 14pt; }
  header h1 { font-size: 16pt; color: #1a2744; margin: 0; }
  header .sub { font-size: 9pt; color: #666; margin-top: 2pt; }
  h2 { font-size: 10pt; text-transform: uppercase; letter-spacing: 1.2pt; color: #2d8c7c; border-bottom: 1pt solid #2d8c7c; padding-bottom: 2pt; margin-top: 14pt; margin-bottom: 6pt; }
  .meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6pt 14pt; margin-bottom: 8pt; }
  .meta-grid .k { color: #888; font-size: 8.5pt; text-transform: uppercase; letter-spacing: 0.5pt; }
  .meta-grid .v { font-weight: 600; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 4pt 6pt; border-bottom: 1px solid #e0e0d8; }
  th { font-weight: 700; font-size: 9pt; color: #666; text-transform: uppercase; letter-spacing: 0.4pt; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  tr.total td { font-weight: 700; border-top: 2px solid #999; padding-top: 6pt; }
  pre.booking { background: #1a1a2e; color: #a0f0c0; font-family: 'Courier New', Menlo, monospace; font-size: 9pt; padding: 10pt 12pt; border-radius: 4pt; white-space: pre-wrap; line-height: 1.55; }
  .tile-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6pt; margin-top: 4pt; }
  .tile { border: 1px solid #d8d8d0; border-radius: 4pt; padding: 6pt 8pt; }
  .tile .label { font-size: 8pt; color: #888; text-transform: uppercase; letter-spacing: 0.5pt; }
  .tile .value { font-size: 12pt; font-weight: 700; margin-top: 2pt; }
  footer { margin-top: 18pt; padding-top: 8pt; border-top: 1px solid #d8d8d0; font-size: 8pt; color: #888; display: flex; justify-content: space-between; }
  .diff-ok { color: #27ae60; }
  .diff-bad { color: #c0392b; }
</style>
</head>
<body>
<header>
  <h1>⚓ Schaluppe Fahrbericht</h1>
  <div class="sub">Verein für mobile Machenschaften e.V.  ·  Version {{ version }}  ·  generiert {{ generated_at }}</div>
</header>

<h2>Fahrtinfo</h2>
<div class="meta-grid">
  <div><div class="k">Datum</div><div class="v">{{ event.date }}</div></div>
  <div><div class="k">Veranstaltung</div><div class="v">{{ event.name or '—' }}</div></div>
  <div><div class="k">Dauer</div><div class="v">{{ event.duration_hours or '—' }} h</div></div>
  <div><div class="k">Gäste</div><div class="v">{{ event.guest_count if event.guest_count is not none else '—' }}</div></div>
  <div><div class="k">Charterer</div><div class="v">{{ event.charterer or '—' }}</div></div>
  <div><div class="k">Funker*in</div><div class="v">{{ event.funker_name or '—' }}</div></div>
  <div><div class="k">Skipper</div><div class="v">{{ event.skipper_name or '—' }}</div></div>
  <div><div class="k">Crew</div><div class="v">{{ event.crew_names or '—' }}</div></div>
</div>

<h2>Kiosk-Einnahmen (8400 / Erlöse Kiosk)</h2>
{% if kiosk_summary %}
<table>
  <thead><tr><th>Getränk</th><th class="num">Menge</th><th class="num">€ / Einheit</th><th class="num">Summe</th></tr></thead>
  <tbody>
    {% for line in kiosk_summary %}
      <tr><td>{{ line.bar_item_name }}</td><td class="num">{{ line.qty }}</td><td class="num">{{ fmt(line.unit_price) }}</td><td class="num">{{ fmt(line.line_total) }}</td></tr>
    {% endfor %}
    <tr class="total"><td colspan="3">Summe Kiosk</td><td class="num">{{ fmt(totals.kiosk_total) }}</td></tr>
  </tbody>
</table>
{% else %}
<p style="color:#888;">— keine Kiosk-Einnahmen —</p>
{% endif %}

<h2>Crew-Verköstigung (4220 / Wareneinsatz)</h2>
{% if crew_summary %}
<table>
  <thead><tr><th>Getränk</th><th class="num">Menge</th><th class="num">€ / Einheit (EK)</th><th class="num">Summe</th></tr></thead>
  <tbody>
    {% for line in crew_summary %}
      <tr><td>{{ line.bar_item_name }}</td><td class="num">{{ line.qty }}</td><td class="num">{{ fmt(line.unit_price) }}</td><td class="num">{{ fmt(line.line_total) }}</td></tr>
    {% endfor %}
    <tr class="total"><td colspan="3">Crew-Wareneinsatz</td><td class="num">{{ fmt(totals.crew_cost) }}</td></tr>
  </tbody>
</table>
{% else %}
<p style="color:#888;">— keine Crew-Verköstigung —</p>
{% endif %}

{% if expenses_summary %}
<h2>Ausgaben während Fahrt</h2>
<table>
  <thead><tr><th>Beschreibung</th><th class="num">Betrag</th></tr></thead>
  <tbody>
    {% for e in expenses_summary %}
      <tr><td>{{ e.description }}</td><td class="num">{{ fmt(e.amount) }}</td></tr>
    {% endfor %}
    <tr class="total"><td>Summe Ausgaben</td><td class="num">{{ fmt(totals.expenses_total) }}</td></tr>
  </tbody>
</table>
{% endif %}

<h2>Kassenabgleich</h2>
<table>
  <tr><td>Soll (Umlage Boarding + Umlage Bar)</td><td class="num">{{ fmt(totals.soll) }}</td></tr>
  <tr><td>Ist (Bargeld Umschlag)</td><td class="num">{{ fmt(totals.cash_amount) if totals.cash_amount is not none else '—' }}</td></tr>
  <tr class="total">
    <td>Differenz</td>
    <td class="num {{ 'diff-ok' if totals.cash_diff_ok else 'diff-bad' }}">{{ '+' if totals.cash_diff_signed_positive else '' }}{{ fmt(totals.cash_diff) }}</td>
  </tr>
</table>

<h2>Buchungstext</h2>
<pre class="booking">{{ booking_text }}</pre>

<h2>Ship-Status am Ende der Fahrt</h2>
<div class="tile-grid">
  {% for tile in ship_tiles %}
    <div class="tile"><div class="label">{{ tile.label }}</div><div class="value">{{ tile.value }}</div></div>
  {% endfor %}
</div>

{% if new_notes or new_todos %}
<h2>Notizen &amp; Todos</h2>
{% if new_notes %}
<p style="margin-bottom:4pt"><strong>Notizen</strong></p>
<ul>{% for n in new_notes %}<li>{{ n }}</li>{% endfor %}</ul>
{% endif %}
{% if new_todos %}
<p style="margin-bottom:4pt"><strong>Offene Todos</strong></p>
<ul>{% for t in new_todos %}<li>{{ t }}</li>{% endfor %}</ul>
{% endif %}
{% endif %}

<footer>
  <span>Vertraulich — nur für internen Gebrauch</span>
  <span>Report {{ report_id_short }} · v{{ version }}</span>
</footer>
</body>
</html>
```

</details>
