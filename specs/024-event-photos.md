# Spec 024 — Eventfotos (Foto-Upload pro Event)

## Problem

Nach jedem Event liegen die Fotos auf vierzig Handys. Was davon zusammenkommt,
kommt über WhatsApp — auf 200 kB heruntergerechnet, in willkürlicher Reihenfolge,
verteilt über drei Gruppen. Wer es besser machen will, teilt einen Drive-Ordner,
den nach zwei Wochen niemand mehr findet und in den die Hälfte der Gäste sich
nicht einloggen kann. Am Ende hat die Orga von ihrem eigenen Event fünf Bilder.

Gebraucht wird pro Event — Einzelfahrt wie Festival — eine Seite, auf der Gäste
ihre Fotos abgeben können, ohne Account, ohne App, in einem Rutsch vom Handy.

Und die Gegenrichtung muss zu bleiben. Ein Foto von jemandem, der um vier Uhr
morgens auf einem Tisch tanzt, gehört nicht auf eine Seite, die aufmacht, wer
den Link in die Hände bekommt. Wer hochlädt, sieht nichts.

## Zielbild in einem Satz

Eine Einbahnstraße mit Rückweg: **Gäste laden hoch und sehen nichts. Das
Orga-Team sieht alles, sortiert, macht Gesichter unkenntlich — und gibt daraus
später eine kuratierte Fotostrecke zurück.**

Das ist der Punkt, an dem sich das Feature erklärt, und er muss auf der Seite
stehen. Eine Einbahnstraße ohne genannten Zweck sieht aus wie eine Sammelstelle,
die nichts hergibt; mit ihm ist sie eine Vorstufe. Wer weiß, dass am Ende eine
Strecke steht, in der die eigenen Fotos auch vorkommen, lädt hoch.

## Nicht-Ziele

- **Keine öffentliche Galerie.** Kein Lesepfad für Gäste, in keiner Ausbaustufe
  dieser Spec. Das ist die eine Anforderung, aus der alles andere folgt.
- Kein Like, kein Kommentar, kein Teilen-Button, keine Albumfunktion.
- **Keine automatische Gesichtserkennung.** Rekognition würde Gästegesichter an
  einen weiteren Dienst schicken, und eine Trefferquote von „meistens" ist für
  Anonymisierung wertlos: das eine übersehene Gesicht ist genau der Schaden, den
  man vermeiden wollte. Rechtecke von Hand sind ehrlicher.
- **Kein Löschen durch Gäste.** Stattdessen wird vor dem Upload ausgewählt (die
  Vorschau ist lokal, das Abwählen kostet nichts) und auf der Seite steht, an
  wen man sich wendet, um ein Foto wieder rauszubekommen.
- Kein ZIP-Download durch das Lambda (siehe § Downloadliste).
- **Keine Videos.** Ein Handyvideo ist 200 MB, der Browser kann es nicht
  umrechnen, und die Sammlung wäre in einem Rutsch unbezahlbar. Die Grenze steht
  in der Upload-Policy (`image/jpeg`), nicht nur in der Oberfläche.

## Die Einbahnstraße

Das ist eine Invariante, keine Voreinstellung:

> Die öffentliche Antwort dieses Features enthält **kein Feld, das eine
> Bild-URL, einen S3-Key oder eine `photo_id` tragen kann.**

Was sie enthält: Eventname, Datum, Einleitungstext, ob offen ist und bis wann,
die Grenzen (Dateien pro Stapel, Maximalgröße), die Aufbewahrungsfrist, den
Kontakt — und eine **Gesamtzahl**. Die Zahl ist die einzige Auskunft über
Inhalte, und zwar eine aggregierte: „bisher 143 Fotos" verrät kein Bild, keinen
Namen und keinen Zeitpunkt, motiviert aber messbar zum Mitmachen. Alles darüber
hinaus wäre ein Lesepfad.

Drei Dinge tragen diese Invariante:

1. Ein presigned **POST** ist ein Schreibrecht auf genau einen Key. Er erlaubt
   kein `GetObject`, auch nicht auf den Key, den man selbst gerade beschrieben
   hat.
2. Der Bucket ist `BlockPublicAccess.BLOCK_ALL`. Es gibt keine anonyme
   Leseberechtigung, die man vergessen haben könnte.
3. Die Vorschau im Upload-Formular ist `URL.createObjectURL(file)` — die eigene
   Datei aus dem eigenen Speicher, ohne einen Server zu fragen. Deshalb fühlt
   sich die Seite trotzdem nicht kaputt an.

## Sichtbarkeit

```
/fotos/{event_id}/{upload_token}
```

`upload_token` ist `secrets.token_urlsafe(32)`, erzeugt beim ersten Speichern.
Kein Login — der Token **ist** die Berechtigung, wie beim Gate und bei der
Fundsachen-Seite (Spec 023). Die `event_id` daneben ist bewusst kein Geheimnis:
mit ihr wird die Konfigurationszeile per `GetItem` geholt, statt einen weiteren
GSI zu bezahlen, und sie öffnet allein nichts.

Der deutsche Pfad ist Absicht: dieser Link steht auf einem gedruckten Zettel am
Ausgang und wird von Gästen gelesen. Die API-Pfade bleiben englisch wie alle
anderen.

Verglichen wird mit `secrets.compare_digest`, und **vorher** mit
`page_token.isascii()` — `compare_digest` wirft bei Nicht-ASCII `TypeError`, und
ein 500 statt eines 404 wäre ein Orakel dafür, dass die Seite existiert. Das ist
der Fehler aus Spec 023, hier von Anfang an vermieden.

Drei Schalter, absteigend nach Endgültigkeit:

| Schalter | Wirkung |
|---|---|
| `upload_open` | Sofort dicht bzw. offen, ohne den Link zu entwerten. |
| `closes_at` | Automatisches Zumachen, Default 21 Tage nach Eventende. |
| `rotate-token` | Entwertet jeden gedruckten Zettel. Die Notbremse. |

Der Token ist erst nach dem ersten Speichern gültig, und ohne Kontakt gibt es
kein erstes Speichern (siehe § Kontakt). Eine halbfertige Seite ist damit nie
öffentlich erreichbar.

## Datenmodell

Drei Zeilenarten in der `events`-Tabelle, alle unter `pk = EVENT#{event_id}`:

| `sk` | Inhalt |
|---|---|
| `PHOTOS#CONFIG` | `upload_token`, `contact_email`, `contact_telegram_url`, `contact_name`, `intro_text`, `upload_open`, `closes_at`, `retention_days`, `photo_count`, `created_at`, `updated_at` |
| `PHOTOS#ITEM#{photo_id}` | `state`, `s3_key_full`, `s3_key_thumb`, `width`, `height`, `bytes`, `uploader_name`, `note`, `captured_at_hint`, `uploaded_at`, `starred`, `edited_at`, `uploader_ip_hash` |
| `PHOTOS#QUOTA#{YYYYMMDDHH}` | `minted`, `ttl` |

**Keine Nummern.** Anders als bei den Fundsachen zitiert niemand ein Foto in
einer Mail, also braucht keines eine stabile Kennung nach außen. Sortiert wird
chronologisch.

**Kein GSI und kein Zeitstempel im Sortierschlüssel.** Die Sammlung ist bei
`MAX_PHOTOS = 2000` gedeckelt; 2000 Zeilen à ~300 Byte sind ~600 kB und passen
in eine einzige Query-Seite. Einmal `Query` mit `begins_with(sk, 'PHOTOS#ITEM#')`
und die Sortierung im Speicher ist billiger als jede Indexvariante — und
`photo_id` bleibt eine UUID, mit der `GetItem`, `PATCH` und `DELETE` direkt
arbeiten.

**`photo_count` ist ein Reservierungszähler**, kein Statistikfeld: hochgezählt
beim Ausstellen der Upload-Erlaubnis (`ADD photo_count :n`), heruntergezählt bei
jedem Löschen einer Zeile — auch beim Aufräumen abgebrochener Uploads. Damit
zählen laufende Uploads gegen die Obergrenze, und der Mint-Pfad muss nie Zeilen
zählen. Öffentlich wird die Zahl als „ca." gezeigt, weil sie unbestätigte
Uploads mitzählt.

### `state`

`PENDING` beim Ausstellen der Upload-Erlaubnis, `READY` nach bestätigtem Upload.
Es gibt keinen dritten Zustand: nichts ist öffentlich, also hat „verstecken"
keine Bedeutung — was weg soll, wird gelöscht. Ein `PENDING` älter als 24 h ist
ein abgebrochener Upload und wird mit seinen Objekten abgeräumt.

### Kontakt

Wie bei Spec 023: **einer von beiden ist Pflicht, welcher ist frei.**
`contact_email` oder `contact_telegram_url`, gern beide, der letzte verbleibende
lässt sich nicht löschen (`contact_required`). Hier ist die Pflicht sogar
zwingender als dort — auf einer Seite, auf der Menschen Fotos von anderen
Menschen abgeben, muss stehen, an wen man sich wendet, um eines wieder
loszuwerden.

`normalize_telegram_url` samt Mustern zieht dafür aus
`app/models/lost_and_found.py` nach `app/models/contact.py` um und wird dort
importiert weiter re-exportiert, damit bestehende Importe und Tests unverändert
laufen. Zwei Features, die denselben `href` auf eine öffentliche Seite schreiben,
dürfen nicht zwei Prüfungen dafür haben.

## Ordnerstruktur

```
eventphotos/{event_id}/{photo_id}/full.jpg
eventphotos/{event_id}/{photo_id}/thumb.jpg
```

- **Event zuerst**, weil eine ganze Sammlung an einem Präfix hängt: Löschen und
  Nachzählen sind ein `list_objects_v2(Prefix=…)`, kein Abgleich über Zeilen.
- **Ein Ordner pro Foto**, weil zwei Varianten daran hängen und eine dritte
  dazukommen könnte, ohne die Keys der bestehenden zu wandern.
- **Kein Uploader im Pfad.** Ein Key ist der einzige Teil des presigned POST, der
  festgenagelt wird; ein Segment, das aus einer Eingabe kommt, wäre eine
  Injektionsfläche. Und ein Pfad ist kein Ort für personenbezogene Daten — er
  taucht in Zugriffslogs auf, die anders aufbewahrt werden als die Zeile.
- **`full`, nicht `original`.** Es *ist* nicht das Kameraoriginal (siehe
  § Skalieren), und ein Name, der etwas anderes behauptet, führt später zu einer
  falschen Annahme.

Neuer Bucket `funke-{env}-eventphotos`: `BlockPublicAccess.BLOCK_ALL`,
`S3_MANAGED`, **nicht versioniert**, CORS `POST` von der Frontend-Origin plus
`http://localhost:5173`, Lifecycle-Regel „400 Tage".

Die fehlende Versionierung ist hier keine Sparmaßnahme, sondern die Bedingung
dafür, dass § Unkenntlich machen funktioniert: eine noncurrent Version des
unverpixelten Bildes würde jedes Überschreiben zur Attrappe machen.

Ein **eigener** Bucket, nicht der von Spec 023 — andere Aufbewahrung, andere
Zugriffsrichtung, andere Schadensreichweite. Ein durchgereichtes Schreibrecht
auf diesen Bucket darf nicht in der Nähe der Fundsachenfotos liegen.

## Hochladen

Zwei Lambda-Aufrufe pro Stapel, egal wie groß er ist:

```
POST /api/public/photos/{event_id}/{upload_token}/uploads   {"count": 12, …}
   -> 12 x {photo_id, full: presigned POST, thumb: presigned POST}
   ... Browser lädt direkt zu S3, maximal 4 gleichzeitig ...
POST /api/public/photos/{event_id}/{upload_token}/confirm    [{photo_id, width, …}]
```

Die Policy jedes presigned POST nagelt fest:

- `content-length-range` — 1 Byte bis **6 MB** (`full`) bzw. **400 kB** (`thumb`),
- `Content-Type` exakt `image/jpeg`,
- den exakten Key,
- Ablauf nach 15 Minuten.

Ein presigned **PUT** wäre ein Schreibrecht ohne Größen- und Typgrenze; nur die
POST-Policy kann Bedingungen erzwingen. Bei einem Endpunkt, den jeder mit dem
Link aufrufen darf, ist das kein Detail.

Der S3-Client zeigt auf den **regionalen** Endpunkt
(`https://s3.{region}.amazonaws.com`, `addressing_style: virtual`). Der globale
Endpunkt antwortet für Buckets außerhalb `us-east-1` mit 307, und ein Browser
wiederholt einen cross-origin Multipart-POST nicht über eine Weiterleitung — der
Upload stirbt mit einem nichtssagenden Netzwerkfehler. Derselbe Fehler wie in
Spec 023, hier von Anfang an richtig.

`confirm` ist der einzige Weg von `PENDING` nach `READY` und nimmt nur, was der
Browser wissen kann: `photo_id`, Pixelmaße, `bytes`, `captured_at_hint`. Eine
`photo_id` aus einem anderen Event ist ein 404, weil die Zeile unter
`EVENT#{event_id}` gesucht wird.

### Skalieren im Browser

`createImageBitmap(file, { imageOrientation: 'from-image' })` und ein `<canvas>`:

| Variante | längste Kante | JPEG-Qualität | Zweck |
|---|---|---|---|
| `full` | 2560 px | 0,85 | Bildschirm, Beamer, brauchbarer Druck |
| `thumb` | 400 px | 0,7 | Raster in der Adminansicht |

2560 px sind eine Entscheidung gegen das Kameraoriginal: 12-MP-HEIC-Dateien à
5 MB über Festival-WLAN hochzuladen ist der schnellste Weg zu einem Stapel, den
niemand zu Ende bringt, und für alles außer Großformatdruck reicht diese Kante.

Der Canvas-Umweg **entfernt sämtliche EXIF-Daten**, inklusive GPS. Für Fotos aus
einem Zeltlager ist das erwünscht; der Preis ist, dass auch die Aufnahmezeit
verloren geht. Ersatz ohne neue Abhängigkeit: `file.lastModified` wird als
`captured_at_hint` mitgeschickt. Auf Handys ist das die Aufnahmezeit, bei einer
weitergeleiteten Datei die Speicherzeit — deshalb ein *Hinweis*, nach dem
sortiert wird, wenn er plausibel ist (nicht in der Zukunft, nicht vor dem
Eventbeginn minus einen Tag), und sonst wird `uploaded_at` genommen.

**Grenze:** Was der Browser nicht dekodieren kann, wird nicht hochgeladen — in
der Praxis HEIC unter Chrome und Firefox (Safari und iOS können es über das
System). Solche Dateien werden namentlich gemeldet („Dieses Format kann dein
Browser nicht lesen — bitte als JPEG teilen"), der Rest des Stapels läuft durch.
**Ein Stapel scheitert nie als Ganzes** — das ist bei 40 Fotos über Mobilfunk die
wichtigste Eigenschaft der Seite.

Maximal 4 parallele Uploads, wie in Spec 023: mehr davon lässt auf schlechten
Verbindungen reihenweise Requests in Timeouts laufen.

## Missbrauch — was hier anders ist als bei Spec 023

Bei den Fundsachen lädt nur die Orga hoch. Hier darf **jeder mit dem Link in
unseren Bucket schreiben.** Das ist die eigentliche neue Angriffsfläche, und sie
wird auf fünf Ebenen begrenzt:

1. **Das Fenster.** `closes_at` (Default: Eventende + 21 Tage) und
   `upload_open` sind die stärkste Kontrolle, weil sie das Schreibrecht zeitlich
   auf die Wochen begrenzen, in denen es überhaupt einen Zweck hat. Ein Zettel,
   der ein Jahr später abfotografiert wird, öffnet nichts.
2. **Die Policy.** Größe, Typ und Key pro Objekt, 15 Minuten Gültigkeit.
3. **Die Deckel.** 30 Fotos pro Stapel, 2000 pro Sammlung (`photo_count`, siehe
   § Datenmodell). Bei 2000 antwortet der Mint-Pfad mit „Diese Sammlung ist
   voll" statt mit Signaturen.
4. **Das Stundenkontingent.** 300 ausgestellte Erlaubnisse pro Seite und Stunde,
   durchgesetzt mit einem bedingten `ADD minted :n` auf
   `PHOTOS#QUOTA#{YYYYMMDDHH}` (`ConditionExpression: attribute_not_exists(minted)
   OR minted <= :ceiling`). Eine Zeile, ein Round-Trip, und sie räumt sich per
   DynamoDB-TTL selbst weg. Antwort: **429** mit „Gerade laden zu viele Leute
   hoch — bitte in ein paar Minuten nochmal." Erst *nach* erfolgreichem
   Tokenvergleich, also kein Orakel.
5. **Die Notbremse.** `rotate-token` entwertet alles Gedruckte, `upload_open`
   macht sofort zu, `DELETE` löscht die Sammlung.

Was strukturell nicht angreifbar ist:

- **Kein Bild geht durch das Lambda.** Es gibt keinen Bild-Parser im Backend, auf
  den man ein präpariertes JPEG richten könnte. Pillow liegt über `qrcode[pil]`
  im Bundle und wird hier bewusst nicht angefasst.
- **Kein Content-Sniffing.** Wer die Signatur missbraucht und HTML unter
  `image/jpeg` ablegt, erreicht nichts: der presigned GET der Adminansicht setzt
  `ResponseContentType: image/jpeg` und `ResponseContentDisposition: inline`, und
  die S3-Origin ist nicht die Origin der App — Tokens und `localStorage` liegen
  außerhalb der Reichweite.
- **Keine Aufzählbarkeit.** `photo_id` ist eine UUID4; eine fremde
  `PENDING`-Zeile zu erraten, um sie zu bestätigen, ist nicht praktikabel.
- **Keine Rechteausweitung über `confirm`.** Der Endpunkt setzt ausschließlich
  Maße, Bytes und den Zeithinweis, niemals `state` auf etwas anderes als `READY`,
  niemals `starred`, niemals Keys.

`uploader_ip_hash` ist `HMAC-SHA256(pepper, ip)`, auf 16 Hex-Zeichen gekürzt, und
existiert für genau einen Zweck: erkennen, ob 400 Fotos von 30 Leuten oder von
einer Person kommen. Gehasht, weil die Antwort auf diese Frage keine gespeicherte
IP braucht; mit Pepper, weil ein blanker Hash über einen IPv4-Raum in Sekunden
rückrechenbar ist. Der Pepper ist eine eigene Einstellung
(`PHOTO_IP_PEPPER`) — **ist sie nicht gesetzt, wird kein Hash gespeichert.** Bei
Datenschutzfeldern ist die sichere Voreinstellung „nichts", nicht „notfalls
unverpeppert". Der Wert stirbt mit der Zeile.

## Adminansicht

`/admin/events/:eventId/fotos`, dieselbe Seite für SINGLE und FESTIVAL,
verlinkt neben „Fundsachen" aus `EventDetailPage.vue` und `FestivalPage.vue`.

Oben die Konfiguration: Kontakt, Name, Einleitungstext, Aufbewahrung,
Offen-Schalter, `closes_at`, der Link mit Kopierknopf, ein **QR-Code** zum
Ausdrucken oder Beamen (`qrcode` liegt schon im Frontend, siehe
`PersonTicketPage.vue`), und die Token-Rotation im gefährlichen Teil.

Darunter die Sammlung:

- Raster aus Thumbnails, chronologisch nach `captured_at_hint || uploaded_at`,
  mit einer Tages-Zwischenzeile („Samstag, 12. Juli").
- Pro Kachel: der Name des Uploaders, wenn er einen angegeben hat, ein Stern für
  „Favorit", und eine Markierung, wenn das Bild bearbeitet wurde.
- Filter: alle / nur Favoriten / nur unbearbeitete.
- Auswahlmodus mit Mehrfachauswahl und **Sammellöschen** — 300 Fotos einzeln zu
  löschen ist kein Werkzeug.
- Lightbox auf die `full`-Variante, mit Vor/Zurück per Tastatur, Stern,
  „Herunterladen" (presigned GET mit `attachment`), „Unkenntlich machen",
  „Löschen".
- Der Notizzettel des Uploaders (`note`) steht in der Lightbox, nicht auf der
  Kachel.

Die Antwortliste enthält pro Foto zwei presigned GETs (15 Minuten) und wird bei
sichtbarem Tab kurz vor Ablauf nachgeladen, plus ein `onerror` am `<img>` als
zweiter Griff — dieselbe Mechanik wie auf der Fundsachen-Seite, aus demselben
Grund.

## Unkenntlich machen

Der Grund, warum das Feature überhaupt eine Bearbeitung braucht: die Orga will
Fotos weitergeben, auf denen Gäste erkennbar sind, die dem nicht zugestimmt
haben.

Ablauf, wieder ohne Lambda im Byte-Pfad:

1. Der Browser lädt `full` über den presigned GET auf ein `<canvas>`.
2. Die Orga zieht Rechtecke über Gesichter (Touch und Maus).
3. Beim Speichern wird jede Region **verpixelt**, nicht weichgezeichnet: die
   Region wird stark verkleinert und mit `imageSmoothingEnabled = false` wieder
   aufgezogen. Ein Mosaik mit groben Blöcken lässt sich nicht zurückrechnen, ein
   Gaußfilter unter Umständen teilweise doch. Deshalb ein Modus, nicht zwei.
4. Das Ergebnis wird als `full` **und** neues `thumb` über zwei frische presigned
   POSTs auf **dieselben Keys** geschrieben. Beides, weil ein Thumbnail mit
   unverpixeltem Gesicht die ganze Übung erledigen würde.
5. `POST .../edit-confirm` setzt `edited_at` und die neuen Maße.

Das ist **endgültig**, und der Knopf sagt das: „Unkenntlich machen — das Original
wird ersetzt". Alles andere wäre Theater: ein aufbewahrtes Original ist genau das
Bild, das nicht mehr existieren soll. Der Bucket ist unversioniert, damit auch S3
keine Kopie behält.

Ehrliche Grenze: Was vor der Bearbeitung heruntergeladen wurde, holt das nicht
zurück. Die Bearbeitung schützt, was aus *unserer* Sammlung herausgeht.

Cache ist kein Problem: jeder presigned GET trägt ein frisches `X-Amz-Date`, ist
also eine andere URL, und der Browser hat nichts, was er wiederverwenden könnte.

## Downloadliste

`GET .../photos/download-manifest?filter=all|starred` liefert eine Textdatei mit
einer presigned GET-URL pro Zeile (`full`, `attachment`, Dateiname
`{index}_{photo_id[:8]}.jpg`), gültig **eine Stunde**, dazu in der Oberfläche die
Einzeiler:

```
xargs -n1 -P4 curl -sOJ < fotos.txt
```

Kein ZIP: API Gateway begrenzt die Antwort auf 10 MB und schneidet nach 29
Sekunden ab — eine Sammlung ist zwei Größenordnungen darüber. Und keine längere
Gültigkeit: eine presigned URL überlebt die temporären Anmeldedaten des Lambdas
nicht, auf die sie signiert ist. Eine Stunde ist konservativ und die Liste ist
umsonst neu erzeugt.

Das ist bewusst der Weg für eine Person, die einmal pro Event zehn Minuten Zeit
hat, und nicht der bequemste denkbare. Die Alternative wäre eine Batch-Job- oder
Step-Functions-Maschinerie für einen Knopf, der pro Event einmal gedrückt wird.

## Aufbewahrung

Neue Einstellung `EVENT_PHOTO_RETENTION_DAYS`, Default 90, pro Sammlung
überschreibbar (`retention_days`, 7–365).

Gezählt wird ab dem späteren von **Eventende** (`event_finished_at` aus Spec 023,
also `cancelled_at`, sonst `end_at`/`start_at`) und **Anlegen der Sammlung** —
dieselbe Regel und derselbe Helfer wie dort, aus demselben Grund: eine Sammlung,
die spät entsteht, wäre mit dem Event als einzigem Anker in der Nacht danach
wieder weg.

Die Sammlung ist ausdrücklich eine **Umschlagstelle, kein Archiv**. Was die Orga
behalten will, holt sie sich in den 90 Tagen heraus; Gästefotos auf Dauer in
unserem Bucket zu halten, ist eine Haftung ohne Gegenwert. Das steht auch so auf
der öffentlichen Seite.

Täglicher Task `expire_event_photos` im Worker:

- Sammlungen außerhalb ihres Fensters vollständig löschen (Konfiguration,
  Zeilen, Objekte),
- `PENDING`-Zeilen älter als 24 h samt Objekten, mit `photo_count`-Korrektur,
- `PHOTOS#QUOTA#`-Reste, falls die TTL hinterherhängt.

Eigene EventBridge-Regel `funke-{env}-photos-expiry`, täglich, weil eine Regel
genau eine Task-Nutzlast trägt. Als Netz trägt der Bucket zusätzlich eine
Lifecycle-Regel „400 Tage" — sie greift nie, solange der Task läuft, verhindert
aber, dass ein stiller Ausfall Personenfotos für Jahre liegen lässt.

## Verhältnis zu Spec 022 (Anonymisierung)

Ein Foto von einem Gast ist ein personenbezogenes Datum, und `uploader_name` und
`note` sind es auch. Die Anonymisierung eines Events **löscht die Sammlung, die
es zu diesem Zeitpunkt gibt, vollständig** — Konfiguration, Zeilen, Objekte —
statt sie zu pseudonymisieren. Ein Gesicht lässt sich nicht pseudonymisieren.

**Danach ist eine Sammlung wieder anlegbar**, wie bei Spec 023 und aus demselben
Grund: eine späte „schickt uns doch noch eure Fotos"-Runde ist genau der
Anwendungsfall. `anonymized_at` ist kein 404-Grund und kein Ablauf-Auslöser;
gelöscht wird nur nach Fenster.

## Verhältnis zu Spec 023 (Fundsachen)

Die beiden Features sehen sich zum Verwechseln ähnlich und sind **entgegengesetzt**:
023 ist öffentliches Lesen, 024 ist öffentliches Schreiben. Sie werden nicht
zusammengelegt, und der Bucket wird nicht geteilt.

Geteilt wird trotzdem, was geteilt gehört:

- `normalize_telegram_url` und die Muster ziehen nach `app/models/contact.py`.
- `event_finished_at` und `_as_utc` werden aus dem Fundsachen-Service importiert
  (bereits als importierbare Helfer angelegt), damit beide Sweeps von derselben
  Sekunde an zählen.
- Die Muster für presigned POST/GET, den regionalen Endpunkt, das
  Nachladen kurz vor Ablauf und den Umgang mit HEIC übernimmt der neue Code
  wortgleich — inklusive der Fehler, die dort schon behoben wurden.

Nicht geteilt: Token, Bucket, Aufbewahrungsschraube, Nummerierung (die es hier
nicht gibt), Worker-Task.

## Der Text auf der Upload-Seite

Standardcopy, deutsch. `{event}` ist der Eventname, `{contact}` der Name oder die
Adresse, `{retention_days}` die Frist:

> ### Fotos vom {event}
>
> *(1)* Du hast Fotos vom {event}? Her damit. Wir sammeln sie ein, damit nicht
> alles auf vierzig Handys liegen bleibt.
>
> *(2)* Aus allem, was zusammenkommt, wollen wir eine richtige Fotostrecke bauen
> — eine, die man sich in zwei Jahren nochmal anschaut. Dafür brauchen wir euer
> Bildmaterial, und zwar möglichst viel davon.
>
> *(3)* **Warum du hier nichts zu sehen bekommst:** Auf Eventfotos sind Leute
> drauf, die nie gefragt wurden, ob sie irgendwo auftauchen. Das Recht am eigenen
> Bild und der Datenschutz sind für uns keine Formalie — deshalb sieht die
> gemeinsame Sammlung vorerst nur das Orga-Team. Wir sortieren, machen Gesichter
> unkenntlich, wo es nötig ist, und stellen daraus später eine kuratierte Auswahl
> bereit. Diese Seite ist wirklich nur ein Zwischenschritt: hier entsteht die
> Sammlung, mehr passiert hier nicht. Auch deine eigenen Fotos sind hier weg,
> sobald sie hochgeladen sind.
>
> *(4)* — als kompakte Drei-Punkt-Liste mit Symbolen, nicht als Absatz:
> - 🔒 **Verschlüsselt gespeichert**, nicht öffentlich abrufbar.
> - 👁 **Sichtbar nur für das Orga-Team.**
> - 🗑 **Spätestens nach {retention_days} Tagen automatisch gelöscht.**
>
> *(5)* Lade bitte nur Fotos hoch, mit denen die Abgebildeten einverstanden sind.
> Wenn ein Foto von dir raus soll oder du eines aus Versehen hochgeladen hast:
> {contact} — dann nehmen wir es raus.
>
> ☐ Ich habe das gelesen und lade nur Fotos hoch, mit denen die Abgebildeten
>   einverstanden sind.

Absatz *(3)* ist der wichtigste auf der Seite und trägt drei Dinge auf einmal:
das Versprechen (die Sammlung bleibt beim Orga-Team), den Grund dafür (Recht am
eigenen Bild, Datenschutz) und den Rückweg (kuratierte Auswahl später). Ohne den
Grund liest sich die Einbahnstraße wie eine technische Einschränkung oder wie
Geheimniskrämerei; mit ihm ist sie das, was sie ist — eine Zusage. Und ohne den
Rückweg fehlt die Antwort auf „was habe ich davon", die auf einer Seite ohne
Login und ohne Gegenleistung die einzige Motivation ist.

Deshalb steht dort **kein** „aus rechtlichen Gründen" und **kein** Verweis auf
eine Datenschutzerklärung: beides verschiebt eine Zusage in eine Pflichtübung.
Es steht auch nicht „wir prüfen die Fotos" — geprüft klingt nach Zensur,
sortiert nach Arbeit, die jemand sich macht.

*(4)* ist bewusst eine Liste und kein Absatz. Es sind die drei Tatsachen, die ein
misstrauischer Mensch sucht — wo liegt das, wer kommt dran, wann ist es weg — und
als Aufzählung mit Symbolen sind sie in zwei Sekunden erfasst, während derselbe
Inhalt als Prosa nach Kleingedrucktem aussieht und übersprungen wird. „Automatisch
gelöscht" ist wörtlich zu nehmen und deshalb so formuliert: es räumt ein
täglicher Job auf (§Aufbewahrung), nicht jemand, der daran denkt.

Die Checkbox ist eine, nicht drei, und sie schaltet den Upload-Knopf frei.
Überschreibbar ist **nur Absatz (1)** — die freundliche Ansprache. (2) bis (5)
sind **nie** überschreibbar: `intro_text` gehört dem Orga-Team, aber die Zusage,
dass hier niemand Fotos anschaut, ist keine Formulierung, die sich
wegkonfigurieren lassen darf — sie ist der Grund, warum jemand hochlädt.
Zusätzlich steht die Regel dauerhaft direkt über dem Upload-Knopf, wo sie kein
Text verdrängt.

Die Frist steht in (4) und **nicht** neben der Zustimmung in (5), weil (2) eine
Strecke für die Zukunft versprochen hat und „wir löschen alles nach 90 Tagen"
daneben wie ein Widerspruch klingt. Gelöscht wird die Umschlagstelle, nicht das,
was das Orga-Team daraus gemacht hat — und genau dafür steht das Wort
„Zwischenschritt" in (3).

Nach dem Upload: „12 Fotos angekommen. Danke!" samt der Zeile, dass sie jetzt
beim Orga-Team liegen, hier nicht mehr auftauchen — und dass daraus die
kuratierte Strecke wird. Der Rückweg wird genau dort wiederholt, wo jemand gerade
etwas hergegeben hat. Ist geschlossen: „Der Upload für das {event} ist zu. Wenn du
noch Fotos hast, schreib an {contact}."

## Endpunkte

| Methode | Pfad | Rolle |
|---|---|---|
| `GET` | `/api/admin/events/{event_id}/photos/config` | Viewer |
| `PUT` | `/api/admin/events/{event_id}/photos/config` | Admin |
| `POST` | `/api/admin/events/{event_id}/photos/rotate-token` | Admin |
| `GET` | `/api/admin/events/{event_id}/photos` | Viewer |
| `PATCH` | `/api/admin/events/{event_id}/photos/{photo_id}` | Admin |
| `DELETE` | `/api/admin/events/{event_id}/photos/{photo_id}` | Admin |
| `POST` | `/api/admin/events/{event_id}/photos/bulk-delete` | Admin |
| `POST` | `/api/admin/events/{event_id}/photos/{photo_id}/edit-uploads` | Admin |
| `POST` | `/api/admin/events/{event_id}/photos/{photo_id}/edit-confirm` | Admin |
| `GET` | `/api/admin/events/{event_id}/photos/download-manifest` | Admin |
| `DELETE` | `/api/admin/events/{event_id}/photos` | Admin |
| `GET` | `/api/public/photos/{event_id}/{upload_token}` | — |
| `POST` | `/api/public/photos/{event_id}/{upload_token}/uploads` | — |
| `POST` | `/api/public/photos/{event_id}/{upload_token}/confirm` | — |

Die öffentlichen Endpunkte antworten **404** auf jede Abweisung, die vor dem
Tokenvergleich fällt oder ihn betrifft — falscher Token, unbekanntes Event, keine
Sammlung. Erst *danach* gibt es unterscheidbare Antworten, weil sie nichts mehr
verraten: **409** für „geschlossen", **429** für das Stundenkontingent, **409**
für „Sammlung voll".

`DELETE .../photos` löscht Konfiguration, alle Zeilen und alle Objekte, in
Paketen von 1000 (`delete_objects`), und antwortet bei Zeitnot `completed: false`
zum erneuten Aufruf — dasselbe Muster wie Spec 022 und 023. Ein `completed:
false` blockiert das Löschen des Events, statt Objekte verwaist zurückzulassen.

## Testabdeckung

- **Einbahnstraße:** Die öffentliche Antwort enthält weder `photo_id` noch
  Bild-URL noch S3-Key — als Test über das Antwortschema, nicht über eine
  Beispielantwort, damit ein später hinzugefügtes Feld auffällt.
- **Token:** falscher Token 404t, Nicht-ASCII-Token 404t (kein 500), Rotation
  entwertet den alten, `compare_digest` wird benutzt.
- **Fenster:** `upload_open=false` und `closes_at` in der Vergangenheit lehnen
  `uploads` ab (409), lassen `GET` aber mit `upload_open: false` antworten.
- **Kontakt:** erstes Speichern ohne beides 400t, nur Telegram genügt, der letzte
  Kontakt lässt sich nicht löschen, `javascript:` wird 422t.
- **Upload-Policy:** Bedingungen enthalten Größengrenze, `image/jpeg` und
  exakten Key; regionaler Endpunkt in der URL; Ablauf nach 15 Minuten.
- **Deckel:** Stapel > 30 400t, Sammlung bei `MAX_PHOTOS` 409t, Stundenkontingent
  429t und ist in der nächsten Stunde wieder offen.
- **`photo_count`:** steigt beim Minten, fällt beim Löschen, fällt beim Aufräumen
  abgebrochener Uploads, wird nicht negativ.
- **`state`:** `confirm` schaltet auf `READY`, `confirm` einer fremden
  `photo_id` 404t, `confirm` kann `starred`/Keys/`state` nicht setzen.
- **`captured_at_hint`:** ein Wert in der Zukunft und einer weit vor dem Event
  werden verworfen, sonst wird nach ihm sortiert.
- **Bearbeiten:** `edit-confirm` setzt `edited_at` und neue Maße, die Keys
  bleiben dieselben, `edit-uploads` einer fremden `photo_id` 404t.
- **Adminansicht:** presigned GETs setzen `ResponseContentType` und
  `ResponseContentDisposition`; Fremdorganisation findet die Sammlung nicht.
- **Manifest:** eine Zeile pro Foto, `filter=starred` filtert, `attachment` ist
  gesetzt.
- **Löschen:** Zeilen und Objekte verschwinden, doppeltes Löschen ist idempotent,
  ein fehlgeschlagener Objektlöschvorgang lässt die Zeilen stehen und meldet
  `completed: false`.
- **Sweep:** innerhalb des Fensters bleibt, außerhalb verschwindet,
  `retention_days`-Override greift, `PENDING` > 24 h fällt weg, Quotazeilen
  fallen weg.
- **Anonymisierung:** löscht die Sammlung mit; danach ist jeder Schreibweg wieder
  offen und die neue Sammlung überlebt den Sweep in der Nacht darauf.
- **IP-Hash:** ohne `PHOTO_IP_PEPPER` wird kein Hash gespeichert, mit Pepper ist
  er stabil und nicht die IP.
- S3 in Tests über `moto`s `mock_aws`.

## Bewusst offen gelassen

- **Videos** — braucht einen anderen Speicher- und Transkodierpfad.
- **Automatische Gesichtserkennung** — siehe Nicht-Ziele.
- **Selbstlöschung durch Gäste** — bräuchte ein Geheimnis pro Upload und damit
  einen zweiten Berechtigungsbegriff auf einer Seite, deren Reiz die
  Voraussetzungslosigkeit ist. Der Kontakt auf der Seite ist der Weg.
- **Der Link in der Nach-Event-Mail** oder auf der Ticketseite — naheliegend und
  eine Zeile, aber eine Änderung an Spec 020 und dem Mailversand. Erst wenn die
  Seite steht.
