# Spec 022 — Anonymisierung von Personendaten

## Problem

Nach einem Event liegen Namen, E-Mail-Adressen, Telefonnummern, Freitext-
Anmerkungen und komplette Mail-Bodies unbegrenzt in DynamoDB. Der bisherige
Mechanismus — der tägliche Worker `cleanup_expired_data` — hat 90 Tage nach
`start_at` eines COMPLETED-Events dessen Anmeldungen und Nachrichten **hart
gelöscht**. Das hatte drei Probleme:

1. Mit den Personendaten verschwanden auch alle Auswertungen (Kopfzahlen,
   Tier-Verteilung, Check-in-Quoten, Übernachtungsbedarf).
2. Einladungen (`INVITE#`) und das Check-in-Protokoll (`SCAN#`) wurden gar
   nicht angefasst — Namen überlebten an zwei Stellen, die der Sweep nicht
   kannte.
3. CANCELLED-Events wurden nie bereinigt, obwohl sie sämtliche vor der Absage
   erhobenen Adressen halten.

## Lösung

Statt zu löschen wird **pseudonymisiert**: jede Zeile bleibt stehen, jedes
personenbezogene Feld wird überschrieben.

### Was ersetzt wird

| Tabelle / Zeile | Felder |
|---|---|
| `registrations` / `REG#` | `name`, `email`, `phone`, `notes`, `group_members[]`, `group_member_emails[]`, `invite_label`, `registration_token` |
| `registrations` / `SCAN#` | `person_name` |
| `events` / `INVITE#` | `label`, `email`, `invite_token` (+ `revoked_at`) |
| `messages` / `MSG#` | `subject`, `body`, `body_html`, `inline_images`, `recipient_email`, `list_unsubscribe` |
| `events` / `EVENT#` | `registration_link_token`, `gate_token`, `ticket_secret` |

### Was bleibt

`group_size`, `status`, `tier`, `attendance_slots`, `member_slots`, Zelt-/
Camper-Zahlen, `overnight_approved`, sämtliche Zeitstempel, `batch_label` und
die Kontingent-Zähler der Einladung, sowie `type`/`direction`/`status` jeder
Nachricht. Damit bleiben Kopfzahl-Board, Gate-Auswertung und Statusverteilung
vollständig erhalten.

`batch_label` ist bewusst dabei: es ist eine vom Orga-Team vergebene
Gruppierung („Werft 2026"), nichts, was bei einem Gast erhoben wurde — und
ohne sie sind die überlebenden Nutzungszahlen nicht mehr lesbar.

### Pseudonyme

Eine Person wird zu `Gast a3f2c1` — den ersten sechs Hex-Stellen von
`sha256("{registration_id}:{person_index}")`.

- **Deterministisch ohne Nachschlagetabelle.** `SCAN#`-Zeilen speichern nur
  einen Namen, tragen aber `registration_id` und `person_index` im Sort-Key.
  Das Gate-Protokoll lässt sich deshalb auf exakt denselben String bringen wie
  die Anmeldung, ohne die beiden Tabellen zu joinen — und ein zweiter Lauf
  kann für dieselbe Person nie einen zweiten Namen erfinden.
- **Nicht umkehrbar.** Der Digest läuft über IDs, die ohnehin im Klartext in
  der Zeile stehen, nie über Name oder Adresse.
- **Zweiwortig.** `FestivalAttendancePatch` lehnt einwortige Namen ab; ein
  einwortiges Pseudonym würde eine anonymisierte Anmeldung unpatchbar machen.

Tombstones (`None` in `group_members`) bleiben Tombstones — QR-`person_index`
ist positionsabhängig.

### Adressen

`Registration.email` ist ein einfacher `str` und wird zu
`anonym-a3f2c1@invalid` (RFC 2606, per Definition nicht auflösbar).
`group_member_emails` ist `EmailStr`, und pydantics Validator **lehnt**
reservierte TLDs ab — diese Einträge werden deshalb auf `None` gesetzt. Beides
ist gleich tot; nur die Kontaktadresse behält eine sichtbare Form, damit man
„anonymisiert" von „hatte nie eine Adresse" unterscheiden kann.

### Tokens

`registration_token` und `invite_token` sind GSI-Keys und müssen existieren
bleiben — sie werden auf frische Zufallswerte rotiert (Präfix `anon-`) statt
entfernt. Jeder bereits verschickte Verwaltungs-, Ticket- und Einladungslink
hört damit auf zu funktionieren. `ticket_secret` verschwindet ganz, kein QR
dieses Events validiert je wieder.

## Auslöser

**Button.** `POST /api/admin/events/{event_id}/anonymize` (OWNER/ADMIN).
Bedient SINGLE- und FESTIVAL-Events gleichermaßen — die Arbeit ist identisch.
Nur COMPLETED und CANCELLED; alles andere 409t. In der UI: „Gefahrenzone" auf
`FestivalPage.vue`, Danger-Sheet auf `EventDetailPage.vue`.

**Sweep.** Der tägliche Worker heißt jetzt `anonymize_expired_data` und
anonymisiert COMPLETED- **und** CANCELLED-Events außerhalb des
Aufbewahrungsfensters (`ANONYMIZATION_RETENTION_DAYS`, Default 90). Gemessen
wird ab dem tatsächlichen Ende: `cancelled_at` bei einer Absage, sonst
`end_at` (Festival) bzw. `start_at` (Einzelevent). Der Task löscht nichts mehr.

## Große Events: Durchläufe statt 504

Jede Zeile braucht ein eigenes `update_item` — ein Teil-Update in Bulk gibt es
in DynamoDB nicht. Ein Festival mit tausenden Gästen, Scans und verschickten
Mails sind also tausende Round-Trips, und die passen nicht in ein Request-
Fenster: API Gateway kappt bei 29 s, das Lambda stirbt bei 30 s — der Button
lieferte einen **504**. Drei Änderungen:

1. **Gestreamt und projiziert gelesen.** Seiten werden einzeln verarbeitet und
   nur die Attribute geholt, die der Rewrite braucht. `MSG#`-Zeilen tragen die
   QR-PNGs in `inline_images`; allein die komplett zu puffern hat das
   512-MB-API-Lambda ins OOM geschoben.
2. **Parallel geschrieben.** `WRITE_CONCURRENCY` (12) Updates gleichzeitig —
   bewusst nicht mehr, weil alle Zeilen unter einer `EVENT#`-Partition liegen
   und die bei etwa 1000 Write-Units/s dicht macht.
3. **Deadline.** Der Aufrufer gibt eine mit (API: 20 s; Worker: Restlaufzeit
   des Lambdas minus Reserve). Läuft sie ab, hört der Durchlauf zwischen zwei
   Zeilen auf, antwortet `completed: false` und lässt `anonymized_at`
   ungesetzt.

Weitergemacht wird durch erneutes Aufrufen: das Frontend (`adminApi.anonymizeEvent`)
schleift die Aufrufe und zählt die bereinigten Zeilen im Modal hoch, der Sweep
nimmt das Event in der nächsten Nacht wieder mit (`events_unfinished` im
Task-Ergebnis). Ein fortgesetzter Durchlauf liest die bereits erledigten Zeilen
erneut — dank Projektion billig — und **überspringt** sie: „diese Zeile enthält
schon genau den String, den ich schreiben wollte" ist ein verlässliches
Fertig-Merkmal, das keinen Cursor und keine Buchhaltungszeile braucht. Damit
werden auch rotierte Tokens nicht ein zweites Mal rotiert.

## Invarianten

- **Idempotent.** `Event.anonymized_at` ist das Flag; ein zweiter Lauf ist ein
  No-op (`already_anonymized`), insbesondere werden Tokens kein zweites Mal
  rotiert. Innerhalb eines unfertigen Events leistet dasselbe der
  Fertig-Merkmal-Vergleich pro Zeile.
- **Retrybar.** Die co-lokalisierten Zeilen werden vor dem `EVENT#`-Item
  gestempelt. Ein Abbruch mittendrin lässt `anonymized_at` ungesetzt, der
  nächste Lauf holt es nach — nie „sauber gemeldet, halb bereinigt". Das gilt
  auch für den geplanten Abbruch an der Deadline: `completed: false` ist die
  Aufforderung, nochmal zu rufen.
- **Reihenfolge im Durchlauf.** Anmeldungen zuerst, dann Scans, Einladungen,
  Nachrichten. Ein abgeschnittener Durchlauf hat damit die Zeilen erwischt, in
  denen die Namen und Adressen stehen.
- **Kein Versand danach.** Nicht-SENT-Nachrichten werden auf FAILED mit
  `error_code="anonymized"` und `retry_count=99` gesetzt; `recipient_email`
  ist weg. `process_email_queue` nimmt nur QUEUED, `retry_failed_emails`
  braucht Adresse und `retry_count < 3`. Zusätzlich 409en die Admin-Routen
  „Rundmail", „Einladung senden", „Einladungen anlegen",
  „Übernachtungs-Benachrichtigungen" und „Anmeldung stornieren".

## Deploy-Reihenfolge

Der EventBridge-Task heißt in `scheduler_stack.py` jetzt
`anonymize_expired_data`; `handler.py` mappt den alten Namen
`cleanup_expired_data` als Alias auf dieselbe Funktion. Damit sind Lambda und
Rule in beliebiger Reihenfolge deploybar. **Der Alias kann entfernt werden,
sobald der Scheduler-Stack ausgerollt ist.**

## Nicht abgedeckt

Ausserhalb von DynamoDB liegende Kopien: der Gmail-Postausgang, PDF-Anhänge im
Reports-S3-Bucket und CloudWatch-Logs (`log_admin_action` schreibt
Admin-Adressen). Admin-Konten in der `admins`-Tabelle sind bewusst
ausgenommen — das sind Mitarbeiterkonten, keine Gästedaten.
