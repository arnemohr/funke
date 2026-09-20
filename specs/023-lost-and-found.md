# Spec 023 — Fundsachen-Seite

## Problem

Nach jedem Event — Einzelfahrt wie Festival — bleibt eine Kiste voller Sachen
übrig: Jacken, Ladekabel, ein einzelner Schuh, Autoschlüssel. Bisher passiert
damit das Übliche: jemand macht Fotos, postet sie irgendwo, und drei Wochen
später weiß niemand mehr, wer die Kiste hat. Umgekehrt wissen Gäste, die
selbst etwas gefunden haben, nicht, wohin damit.

Gebraucht wird pro Event eine öffentliche Seite, die

1. alle Fundsachen als **durchnummerierte** Fotos zeigt,
2. **eine** verantwortliche Person nennt, an die sich beide Seiten wenden —
   wer etwas verloren *und* wer etwas gefunden hat,
3. nicht auffindbar ist, ohne den Link zu kennen,
4. nicht ewig lebt.

## Nicht-Ziele

Kein Rückgabe-Workflow, keine Reservierungen, kein „ist meins"-Button, keine
Kommentare. Die Seite ist ein Schaufenster mit einer Mailadresse darunter; die
Klärung läuft per Mail zwischen Gast und Koordination. Und keine Uploads durch
Gäste — was auf die Seite kommt, entscheidet die Orga.

## Sichtbarkeit

Der Link lautet

```
/lostfound/{event_id}/{page_token}
```

`page_token` ist `secrets.token_urlsafe(32)` (43 Zeichen), erzeugt beim ersten
Speichern der Seite. Kein Login, kein `authGuard` — der Token **ist** die
Berechtigung, wie beim Gate (`/checkin/:gateToken`) und beim persönlichen
Ticket (`/ticket/...`).

Die `event_id` steht bewusst im Pfad und ist bewusst **kein** Geheimnis: sie
erspart einen fünften GSI auf der `events`-Tabelle. Mit ihr wird die
Konfigurationszeile direkt per `GetItem` geholt und der mitgelieferte Token
per `secrets.compare_digest` gegen den gespeicherten geprüft — statt wie bei
`registration_link_token`/`gate_token` über einen Token-Index zu queryen. Eine
`event_id` allein öffnet nichts.

Eine Seite ist erst erreichbar, wenn `published` gesetzt ist. Vorher darf die
Orga schon Fotos hochladen und Text schreiben; öffentlich 404t der Token bis
zum Freischalten. Umgekehrt macht „Veröffentlichung zurücknehmen" die Seite
sofort wieder dicht, ohne die Fotos zu verlieren.

`POST .../lostfound/rotate-token` erzeugt einen frischen Token und entwertet
damit jeden verschickten Link — die Notbremse, falls der Link in einer
Facebook-Gruppe landet.

## Datenmodell

Zwei neue Zeilenarten in der `events`-Tabelle, beide unter der Partition des
Events (`pk = EVENT#{event_id}`), analog zu `INVITE#` (Spec 019):

| `sk` | Inhalt |
|---|---|
| `LNF#CONFIG` | `page_token`, `coordinator_name`, `coordinator_email`, `coordinator_telegram_url`, `intro_text`, `published`, `retention_days`, `next_number`, `created_at`, `updated_at` |
| `LNF#PHOTO#{photo_id}` | `number`, `caption`, `state`, `s3_key_display`, `s3_key_thumb`, `width`, `height`, `uploaded_at` |

**Ein Kontakt ist Pflicht, welcher ist frei.** Eine Fundsachen-Seite ohne
Ansprechpartner ist wertlos, aber nicht jedes Orga-Team arbeitet über Mail:
`coordinator_email` **oder** `coordinator_telegram_url` muss gesetzt sein,
beides zusammen geht auch. Der letzte verbleibende Kontakt lässt sich nicht
löschen (`contact_required`).

`coordinator_telegram_url` nimmt, was ein Mensch tippt — `@fundsachen`,
`t.me/fundsachen`, ein Einladungslink `https://t.me/+Hash` — und speichert
daraus genau eine kanonische `https://t.me/…`-URL. Was das Muster nicht
trifft, wird abgelehnt (422), und zwar ohne Ausnahme: der Wert landet als
`href` auf einer öffentlichen Seite, und ein `javascript:`- oder
`data:`-Schema darf dort nie ankommen. Ein Einladungslink wird nie
umgeschrieben — der Hash *ist* die Adresse der Gruppe.

`coordinator_name` ist optional (Default: der Kontakt zeigt sich selbst — die
Adresse, `@handle auf Telegram`, oder „die Telegram-Gruppe" bei einem
Einladungslink, dessen Hash für Lesende nichts bedeutet). `intro_text` ist optional und überschreibt nur den ersten Absatz des
Standardtexts (siehe unten); die Handlungsanweisung darunter wird nie
überschrieben, damit keine Seite entsteht, auf der nicht steht, was man tun
soll.

### Nummern

Die Nummer ist das, was ein Gast in seine Mail schreibt („Nummer 14"). Sie
muss deshalb stabil sein:

- Vergeben wird sie beim Anlegen der Foto-Zeile, aus dem Zähler
  `next_number` der CONFIG-Zeile (`ADD next_number :n` mit
  `ReturnValues=UPDATED_NEW` — ein Batch von 12 Fotos zieht 12 Nummern in
  einem Round-Trip).
- **Nie neu vergeben.** Wird Foto 14 gelöscht, bleibt 14 leer und das nächste
  neue Foto bekommt die nächsthöhere Nummer. Lücken sind harmlos,
  Neunummerierung ist es nicht: ein Gast, der auf eine drei Tage alte Mail
  antwortet, meint noch die alte 14.
- Angezeigt wird nach Nummer aufsteigend, was der Upload-Reihenfolge
  entspricht.

### `state`

`PENDING` beim Minten der Upload-Erlaubnis, `READY` nach bestätigtem Upload.
Öffentlich sichtbar sind ausschließlich `READY`-Zeilen. `PENDING`-Zeilen, die
älter als 24 h sind, räumt der Sweep weg — sie entstehen, wenn ein Upload
abbricht.

## Bilder: privater Bucket, Lambda nie im Byte-Pfad

Ein neuer Bucket `funke-{env}-lostfound`, `BlockPublicAccess.BLOCK_ALL`,
`S3_MANAGED`-Verschlüsselung. Nichts daran ist öffentlich lesbar.

```
Browser --canvas-Downscale--> presigned POST --> S3 (privat)
                                                  |
öffentliche Seite <---- presigned GET (15 min) ----+

Lambda: stellt URLs aus und schreibt Metadaten — nie ein Bild-Byte.
```

**Warum nicht durch das Lambda:** API Gateway begrenzt Request und Response
auf 10 MB (Base64-aufgebläht real ~6 MB) und kappt nach 29 s. 50 Handyfotos
durch diesen Trichter zu schicken bedeutet Timeouts beim Upload und ein
OOM-Risiko beim Ausliefern. Direkt-zu-S3 hat keine dieser Grenzen.

### Hochladen

`POST /api/admin/events/{event_id}/lostfound/uploads` mit `{"count": 12}`
liefert 12 Einträge `{photo_id, number, display: {...}, thumb: {...}}`, jeder
ein **presigned POST** (kein presigned PUT). Der Unterschied ist wichtig: nur
die POST-Policy kann Bedingungen erzwingen —

- `content-length-range` 1 Byte … 3 MB,
- `Content-Type` exakt `image/jpeg`,
- exakter Key.

Ein presigned PUT wäre ein Schreibrecht ohne Größen- und Typgrenze. Die
Signatur läuft nach 15 Minuten ab.

Keys:

```
lostfound/{event_id}/{photo_id}/display.jpg
lostfound/{event_id}/{photo_id}/thumb.jpg
```

Danach ein einziger `POST .../lostfound/photos/confirm` mit den IDs, die
durchgekommen sind, plus deren Pixelmaßen. Ein Bulk-Upload von 50 Fotos kostet
damit genau zwei Lambda-Aufrufe.

### Skalieren im Browser

Vor dem Upload rechnet der Browser jedes Foto zweimal um, über
`createImageBitmap(file, { imageOrientation: 'from-image' })` und ein
`<canvas>`:

| Variante | längste Kante | JPEG-Qualität |
|---|---|---|
| `display` | 1600 px | 0,82 |
| `thumb` | 400 px | 0,7 |

Das hat drei Effekte, von denen zwei Nebenwirkungen sind: die Galerie bleibt
über Mobilfunk benutzbar, `imageOrientation: 'from-image'` dreht
Hochkant-Fotos richtig — und der Canvas-Umweg **entfernt sämtliche
EXIF-Daten**, inklusive GPS-Koordinaten. Für Fotos, die eine fremde Jacke in
einem Zelt zeigen, ist genau das erwünscht.

Bewusst nicht serverseitig mit Pillow (das über `qrcode[pil]` längst im Bundle
liegt): das würde die Originale durchs Lambda ziehen und einen Retry-Pfad für
fehlgeschlagene Konvertierungen brauchen, für null sichtbaren Gewinn.

**Grenze:** Was der Browser nicht dekodieren kann, wird nicht hochgeladen —
betrifft in der Praxis HEIC unter Chrome/Firefox (Safari und iOS können es
über das System). Solche Dateien werden namentlich mit „Dieses Format kann
der Browser nicht lesen — bitte als JPEG exportieren" gemeldet, der Rest des
Stapels läuft durch. Ein Stapel scheitert nie als Ganzes.

### Ausliefern

Die öffentliche Antwort enthält pro Foto zwei presigned GET-URLs (Thumb und
Display), gültig 15 Minuten, mit
`ResponseContentDisposition: inline` und auf `image/jpeg` festgenagelter
Antwort-Content-Type.

Kurzlebige URLs heißen: eine offene Tab-Sitzung zeigt irgendwann leere Bilder.
Dagegen zwei Griffe — die Seite lädt ihre URLs alle 14 Minuten nach, solange
das Tab sichtbar ist (`visibilitychange`), und ein `onerror` an einem `<img>`
löst ein sofortiges Nachladen aus. Weitergegebene Bild-URLs verfallen damit
schnell; weitergegeben werden soll ohnehin der Seitenlink.

### CORS

Der Bucket braucht eine CORS-Regel, sonst blockt der Browser den POST:
`AllowedMethods` `POST`, `AllowedOrigins` die CloudFront-Domain der Umgebung
plus `http://localhost:5173`, `AllowedHeaders` `*`. Für die `<img>`-GETs ist
keine CORS-Regel nötig.

## Der Text auf der Seite

Standardcopy, deutsch, freundlich, ohne Amtston. `{event}` ist der
Eventname, `{coordinator}` der Name oder die Adresse:

> ### Fundsachen — {event}
>
> Nach dem {event} ist eine ganze Kiste liegengeblieben. Hier ist alles drin,
> was wir eingesammelt haben.
>
> **Etwas davon gehört dir?** Schreib an {coordinator} und nenne die Nummer
> unter dem Foto. Wir melden uns und klären, wie du deine Sachen
> zurückbekommst.
>
> **Du hast selbst etwas gefunden?** Auch dann ist {coordinator} die richtige
> Adresse — dann landet es hier auf der Seite und findet zurück.
>
> Sachen, die niemand abholt, geben wir nach {retention_days} Tagen ab oder
> entsorgen sie.

Nur der zweite Absatz ist über `intro_text` überschreibbar. Der Kontakt steht
als Link — `mailto:` mit vorbefülltem Betreff „Fundsache — {event}", oder die
Telegram-URL; sind beide gesetzt, stehen beide da, getrennt durch „oder" —
**einmal oben im Text und einmal im Fuß, nicht an jedem Foto.** Ein Mail-Button
pro Kachel war der erste Entwurf und ist wieder rausgeflogen: er machte die
Kacheln laut, und der Tap, der auf einem Foto zählt, ist „größer ansehen".
Die Nummer nennt der Gast in der Mail selbst, deshalb steht sie ohne
vorbefüllte Nummer im Betreff. Adresse im Klartext statt Kontaktformular: die
Seite ist unlisted, und ein Formular verschiebt nur den Spam von einem
Postfach in ein anderes.

## Darstellung

Öffentlich (`LostFoundPage.vue`): responsives Karten-Grid, pro Karte das
Thumbnail, ein kleines Nummern-Badge in der Ecke (`pointer-events: none` — ein
Label, kein Ziel), darunter die optionale Beschriftung. Klick öffnet die
Display-Variante als Lightbox mit Vor/Zurück. Kopfbereich mit dem Text von oben, Fuß mit der Adresse. Leere
Seite (Seite freigeschaltet, noch keine Fotos): „Hier ist noch nichts
eingetragen — schau später nochmal."

Admin (`LostFoundAdminPage.vue`, `/admin/events/:eventId/lostfound`, dieselbe
Seite für SINGLE und FESTIVAL): Konfigurationsformular oben (Adresse, Name,
Text, Aufbewahrung, Veröffentlichen-Schalter, Link mit Kopier-Button,
Token-Rotation), darunter eine Drop-Zone samt Mehrfachauswahl mit
Fortschrittsanzeige pro Datei, darunter das Foto-Raster mit Beschriftungsfeld
und Löschen je Foto. Verlinkt aus dem Danger-freien Teil von
`EventDetailPage.vue` und aus `FestivalPage.vue`.

Uploads laufen mit maximal 4 gleichzeitig — Handy-Uploads über
Festival-WLAN gehen sonst reihenweise in Timeouts.

## Endpunkte

| Methode | Pfad | Rolle |
|---|---|---|
| `GET` | `/api/admin/events/{event_id}/lostfound` | Viewer |
| `PUT` | `/api/admin/events/{event_id}/lostfound` | Admin |
| `DELETE` | `/api/admin/events/{event_id}/lostfound` | Admin |
| `POST` | `/api/admin/events/{event_id}/lostfound/rotate-token` | Admin |
| `POST` | `/api/admin/events/{event_id}/lostfound/uploads` | Admin |
| `POST` | `/api/admin/events/{event_id}/lostfound/photos/confirm` | Admin |
| `PATCH` | `/api/admin/events/{event_id}/lostfound/photos/{photo_id}` | Admin |
| `DELETE` | `/api/admin/events/{event_id}/lostfound/photos/{photo_id}` | Admin |
| `GET` | `/api/public/lostfound/{event_id}/{page_token}` | — |

Der öffentliche Endpunkt antwortet **404** auf jede Abweisung — falscher
Token, unbekanntes Event, nicht veröffentlicht, abgelaufen, anonymisiert. Ein
403 würde bestätigen, dass es die Seite gibt.

`DELETE .../lostfound` löscht Konfiguration, alle Foto-Zeilen und alle
S3-Objekte. Das Löschen der Objekte läuft in Paketen von 1000
(`delete_objects`); bleibt eine Seite über der Zeit, gilt dasselbe Muster wie
bei Spec 022 — `completed: false` und erneut aufrufen.

## Aufbewahrung

Neue Einstellung `LOST_AND_FOUND_RETENTION_DAYS`, Default 90 — gleicher Wert
wie `ANONYMIZATION_RETENTION_DAYS`, aber eine eigene Schraube, weil eine
Fundsachen-Kiste einem anderen Rhythmus folgt als eine
Datenschutz-Aufbewahrungsfrist. Pro Seite überschreibbar (`retention_days`,
7–365), weil manche Events die Kiste zwei Wochen und manche ein halbes Jahr
halten.

Gezählt wird ab dem tatsächlichen Ende des Events — über denselben Helfer
`_event_finished_at` wie der Anonymisierungs-Sweep (`cancelled_at`, sonst
`end_at`/`start_at`) — **oder ab dem Anlegen der Seite, wenn das später liegt.**
Der Eventschluss ist der natürliche Anker: die Kiste füllt sich, während das
Event endet. Eine Seite darf aber lange danach entstehen, und mit dem Event als
einzigem Anker wäre so eine Seite in der Nacht nach dem Anlegen wieder weg,
bevor sie jemand öffnen konnte. Der spätere der beiden Zeitpunkte gewinnt, damit
das Fenster immer die vollen `retention_days` ab Existenz der Seite umfasst.

Abgeräumt wird von einem neuen Task `expire_lost_and_found` im täglichen
Worker: Seiten außerhalb ihres Fensters werden vollständig gelöscht (Zeilen
und S3-Objekte), ebenso `PENDING`-Zeilen älter als 24 h. Als Netz, falls der
Sweep je stillstehen sollte, trägt der Bucket zusätzlich eine
Lifecycle-Regel, die Objekte nach 400 Tagen verfallen lässt — sie greift nie,
solange der Task läuft, verhindert aber, dass ein stiller Ausfall
Personenfotos für Jahre liegen lässt.

## Verhältnis zu Spec 022

Fotos einer fremden Jacke sind personenbezogene Daten, und Beschriftungen wie
„Handy von Lena, am Bühnenrand" sind es erst recht. Die Anonymisierung eines
Events **löscht deshalb die Fundsachen-Seite, die es zu diesem Zeitpunkt gibt,
vollständig** — Konfiguration, Foto-Zeilen, S3-Objekte — statt sie zu
pseudonymisieren. Ein Foto lässt sich nicht sinnvoll pseudonymisieren.

**Danach ist die Seite aber wieder anlegbar.** Eine Fundsachenkiste wird
regelmäßig erst Monate später aufgeräumt — und nach 90 Tagen ist das Event
längst anonymisiert. Ein Verbot würde genau den Anwendungsfall treffen, für den
die Seite gedacht ist. Deshalb:

- Jeder Schreibweg (`PUT`, `uploads`, `confirm`, `PATCH` Beschriftung) steht
  einem anonymisierten Event offen; es gibt keinen 409.
- Die öffentliche Seite eines anonymisierten Events ist erreichbar wie jede
  andere — `anonymized_at` ist kein 404-Grund.
- `anonymized_at` ist **kein** Ablauf-Auslöser im Sweep. Gelöscht wird nur nach
  Fenster (siehe § Aufbewahrung), und weil der Anker der spätere von
  Eventschluss und Anlegen ist, bekommt eine nachträglich angelegte Seite ihr
  vollständiges Fenster.

Der Preis dieser Entscheidung ist bewusst in Kauf genommen: eine Seite, die die
Anonymisierung wegen eines S3-Ausfalls nicht löschen konnte, wird jetzt nicht
mehr in der nächsten Nacht abgeräumt, sondern erst am Ende ihres Fensters. Die
Alternative — `anonymized_at` weiter als Ablauf zu behandeln — würde die
nachträglich angelegten Seiten sofort mitlöschen und damit den Zweck der
Freigabe zerstören.

Fachlich passt das zusammen: die neuen Fotos sind eine eigene, spätere Erhebung
und keine Daten, die die Anonymisierung entfernt haben sollte. Und
`coordinator_email` ist eine Orga-Adresse, kein Gastdatum — sie taucht in
keiner Pseudonymisierungstabelle auf.

## Testabdeckung

- Kontakt: erster Speichern-Vorgang ohne beides 400t; nur Telegram genügt;
  `@name`/`t.me/name` werden normalisiert, Einladungslinks nicht angetastet;
  `javascript:`, ein Fremdhost mit `t.me` im Pfad und ein leerer Handle werden
  422t; die Mail lässt sich löschen, sobald Telegram steht, der jeweils letzte
  Kontakt nicht.
- Token: falscher Token 404t, `compare_digest`-Vergleich, Rotation entwertet
  den alten Token, nicht veröffentlichte Seite 404t.
- Nummern: Batch zieht einen zusammenhängenden Block, Löschen vergibt keine
  Nummer neu, gleichzeitige Batches überschneiden sich nicht.
- Upload-Policy: Bedingungen enthalten Größengrenze, `image/jpeg` und exakten
  Key; abgelaufene Signatur.
- `state`: `PENDING` ist öffentlich unsichtbar, `confirm` schaltet auf
  `READY`, `confirm` einer fremden `photo_id` 404t.
- Löschen: Zeilen und Objekte verschwinden, doppeltes Löschen ist idempotent.
- Sweep: Seite innerhalb des Fensters bleibt, außerhalb verschwindet,
  `retention_days`-Override greift, `PENDING`-Reste älter als 24 h fallen weg.
- Anonymisierung: `anonymize_event` löscht die vorhandene Seite mit. Danach ist
  jeder Schreibweg wieder offen (`200`, kein 409), die neu angelegte Seite ist
  öffentlich erreichbar, und sie überlebt den Sweep in der Nacht darauf, weil
  ihr Fenster ab dem Anlegen zählt.
- S3 in Tests über `moto`s `mock_aws` (bereits Testabhängigkeit).
