# Spec 025 — Chartervertrag

## Problem

Wer die Schaluppe chartert, unterschreibt einen vierseitigen Chartervertrag:
Charterzeit, Chartergebühr, Kaution, Chartergebiet, Schiffsführer mit
Führerscheinnummern, siebzehn Klauseln, drei Unterschriftsfelder. Heute
entsteht dieses Dokument in Word. Jemand kopiert die Datei vom letzten Mal,
überschreibt Namen und Datum, exportiert ein PDF, schickt es per Mail — und
danach lebt der Vertrag in einem Downloads-Ordner.

Daraus folgen drei Fehler, die alle schon passiert sind:

1. **Falsch ausgefüllt.** Das Datum der letzten Charter bleibt stehen, die
   Gebühr stimmt nicht, die Führerscheinnummer fehlt.
2. **Zu spät.** Der Vertrag wird am Steg gesucht statt vorher unterschrieben.
3. **Nicht auffindbar.** Zwei Jahre später weiß niemand, ob es zu einer
   bestimmten Fahrt überhaupt einen unterschriebenen Vertrag gab — und genau
   dann braucht man ihn, weil etwas kaputtgegangen ist oder das Finanzamt
   fragt.

Gebraucht wird: ein korrekt ausgefülltes Vertrags-PDF aus den Daten, die
Funke ohnehin hat, und ein belastbarer Nachweis, dass der unterschriebene
Vertrag existiert — auffindbar am Event, nicht in einem Postfach.

## Warum nicht Google eSignature

Der Wunsch war, über die eSignature-Funktion des Google-Workspace-Kontos zu
unterschreiben. Die Recherche hat das erledigt, aus zwei unabhängigen Gründen:

**Es gibt keine API.** Google Docs eSignature ist eine reine
Oberflächenfunktion. Signaturanfragen lassen sich nicht programmatisch
erzeugen, nicht verfolgen und nicht abschließen. Bestätigt durch einen
Google-Entwickler im offiziellen Entwicklerforum („As of right now there is no
API for eSignature", 22.07.2025), durch das Fehlen jeder Signatur-Ressource in
der Drive-API v3 (`about`, `accessproposals`, `approvals`, `apps`, `changes`,
`channels`, `comments`, `drives`, `files`, `operations`, `permissions`,
`replies`, `revisions` — mehr gibt es nicht), und durch das Fehlen von
eSignature im Google Workspace Developer Preview Program. Der öffentliche
Feature-Request (issuetracker 239527000) ist offen.

**Es ist im NGO-Tarif nicht enthalten.** Die unterstützten Editionen sind
Business Standard/Plus, Enterprise Starter/Standard/Plus, Enterprise
Essentials/Plus, Education Plus und Workspace Individual. Das kostenlose
„Google Workspace for Nonprofits" ist nicht darunter, und in der
Admin-Konsole existiert auf diesem Tarif kein Schalter. Drei
Google-Quellen sagen dasselbe, das ist kein Dokumentationsrückstand.

Der Tarif ließe sich für ~40 €/Jahr/Platz nachkaufen. Die fehlende API nicht.
Bliebe ein Ablauf, in dem die Orga jedes Mal von Hand acht bis zwölf
Signaturfelder über vier Seiten platziert, drei Adressen tippt und abschickt,
während Funke danach einen Drive-Ordner pollt und rät, wie Google die fertige
Datei benennt. Das ist mehr Handarbeit als heute, nicht weniger — und es hängt
an einem bezahlten Platz, einem OAuth-Refresh-Token in einer Lambda-Umgebungs-
variable, zwei Dokumentvorlagen und zwei Feldvorlagen, die alle über einen
Hamburger Winter hinweg funktionsfähig bleiben müssen.

Dazu kommt: Google eSignature kennt **keine Reihenfolge**. Alle Unterzeichner
werden gleichzeitig benachrichtigt. „Der Vercharterer gegenzeichnet zuletzt"
ist damit nicht abbildbar.

Rechtlich gewinnt man nichts. Ein Chartervertrag ist **formfrei** — weder
§ 126a noch § 126b BGB greifen. Google eSignature erzeugt eine *einfache*
elektronische Signatur (SES), genau wie ein Kugelschreiber auf Papier oder ein
gemaltes Feld im Browser. Alle drei landen in derselben freien Beweiswürdigung
nach § 286 ZPO. Es gibt hier keine Signaturstufe zu gewinnen, nur Maschinerie
zu bezahlen.

**Deshalb: kein Google.** Das steht hier ausdrücklich, damit es nicht im
nächsten Frühjahr erneut verhandelt wird.

## Zielbild in einem Satz

Funke füllt den Chartervertrag aus und erzeugt das PDF; unterschrieben wird
im Browser oder mit einem Stift; das fertige Dokument wird versiegelt und hängt
unlöschbar am Event.

Die Anforderung lautet „ausgefüllt und unterschrieben vor Fahrtantritt". Was
Funke beiträgt, ist das, was heute tatsächlich schiefgeht: Korrektheit,
Rechtzeitigkeit, Auffindbarkeit — und seit dem Nachtrag vom 27.08. auch
Unverfälschtheit.

Zwei Wege führen zur Unterschrift, und beide bleiben: die **Token-Seite**, auf
der der Charterer selbst zeichnet, und der **Papierweg** über Ausdruck und
hochgeladenen Scan. Bei ~20 Chartern im Jahr, bei denen sich die Parteien zur
Übergabe ohnehin am Steg treffen, ist der Stift oft noch das schnellste
Verfahren — er darf nur nicht der einzige sein, weil der Scan sonst nach der
Fahrt liegen bleibt.

## Nicht-Ziele

> **Nachtrag 27.08.2026 — eine Kehrtwende, ausdrücklich.** Die erste Fassung
> dieses Specs schloss eine Signaturseite für Gäste aus („kein öffentlicher
> Endpunkt … eine Entscheidung, keine Auslassung"). Diese Entscheidung ist
> zurückgenommen: es gibt jetzt eine öffentliche Token-Seite, auf der der
> Charterer selbst unterschreibt, und das fertige Dokument wird kryptografisch
> versiegelt. Warum die Umkehr — siehe „Unterschreiben in Funke". Der Papierweg
> bleibt vollständig erhalten; die neue Seite ist ein zweiter Weg, kein Ersatz.

Kein Object Lock, keine eigene Audit-Tabelle, kein Aufbewahrungs-Löschjob
(gebraucht 2036, nicht 2026), kein neuer Bucket.

Keine QES und keine AES. Das Siegel belegt **Unverfälschtheit**, nicht die
Identität des Unterzeichners; die Unterschrift des Charterers bleibt eine
einfache elektronische Signatur. Für einen formfreien Vertrag ist das die
richtige Stufe — mehr wäre pro Unterschrift zu bezahlen und juristisch
gleichwertig.

Keine Zahlungsabwicklung. Chartergebühr und Kaution stehen im Vertrag; ob und
wann sie eingegangen sind, bleibt außerhalb.

## Datenmodell

**Eine** Singleton-Zeile in der bestehenden `{prefix}-events`-Tabelle, unter
der Partition des Events — dieselbe Bauform wie `FAHRBERICHT`, `LNF#CONFIG`
und `PHOTOS#CONFIG`:

```
pk = EVENT#{event_id}
sk = CHARTER
```

Neue Konstante in `backend/app/services/config.py` neben
`EVENT_SK_FAHRBERICHT`:

```python
EVENT_SK_CHARTER = "CHARTER"   # Spec 025, Singleton wie FAHRBERICHT
```

Ein nacktes Singleton, kein Präfix: ein Floß, eine Fahrt, ein Vertrag. Ein
Ersatzvertrag ist ein neuer Render derselben Zeile, keine zweite Zeile.

| Feld | Typ | Anmerkung |
|---|---|---|
| `entity_type` | `"charter_contract"` | |
| `status` | `draft` \| `sent` \| `signed` | `CharterStatus`, str-Enum |
| `template_version` | str | z. B. `"2026-01"`, aus dem Renderer; damit ein Leser 2033 weiß, welcher Klauselstand das PDF erzeugt hat |
| `document_version` | int | 0 bis zum ersten Render |
| `charterer_name` | str ≤200 | |
| `charterer_address` | str ≤400 | mehrzeilig; die erste Postanschrift in der Domäne |
| `charterer_email` | EmailStr \| None | nur fürs Verschicken nötig |
| `charterer_phone` | str \| None | |
| `sondervereinbarungen` | str \| None ≤500 | |
| `uebergabe_at` | datetime | tz-aware, UTC gespeichert, Europe/Berlin gerendert |
| `rueckgabe_at` | datetime | **nicht** aus `end_at` abgeleitet — das ist bei SINGLE `None` und bedeutet ohnehin etwas anderes |
| `chartergebuehr` | Decimal(2) | |
| `sonderleistungen` | list[ExpenseLine] | aus `models/fahrbericht.py:26` (**nicht** die gleichnamige Klasse in `models/report.py:31`), keine zweite Geldform erfinden |
| `kaution` | Decimal(2) | |
| `gesamtbetrag` | Decimal(2) | vom Renderer geschrieben: Chartergebühr + Σ Sonderleistungen. **Kaution bewusst nicht enthalten** — sie ist erstattungsfähig |
| `personen_ohne_skipper` | int 0..12 | |
| `skipper_name` | str ≤200 | |
| `skipper_is_charterer` | bool, Vorgabe **`true`** | der Normalfall (siehe unten). Steuert zwei statt drei Unterschriftsblöcke |
| `sbfs_number` / `sbfs_issued_on` | str ≤50 \| None / date \| None | |
| `sbfb_number` / `sbfb_issued_on` | str ≤50 \| None / date \| None | |
| `document_key` | str \| None | `contracts/{event_id}/v{n}.pdf` |
| `document_sha256` | str \| None | |
| `rendered_at` | datetime \| None | |
| `sent_at` / `sent_to` | datetime \| None / str \| None | |
| `signed_on` | date \| None | was die Menschen aufs Papier geschrieben haben |
| `signed_recorded_at` | datetime \| None | wann Funke davon erfahren hat |
| `signed_by_admin` | str \| None | wer es bestätigt hat |
| `signed_document_key` | str \| None | `contracts/{event_id}/v{n}-signiert.pdf` |
| `signed_document_sha256` | str \| None | |
| `signed_document_bytes` | int \| None | |
| `countersigned_on` | date \| None | Gegenzeichnung des Vercharterers — **optional**, siehe unten. Blockiert nichts und darf jederzeit nachgetragen werden |
| `countersigned_by` | str \| None | wer gegengezeichnet hat |
| `fahrbericht_override_by` | str \| None | wer den Fahrbericht ohne Vertrag abgegeben hat |
| `fahrbericht_override_at` | datetime \| None | wann |
| `sign_token` | str \| None | `secrets.token_urlsafe(32)`, entsteht beim Rendern, stirbt bei jedem neuen Render |
| `signatures` | list[CharterSignature] | siehe unten; leer bis zur ersten Unterschrift |
| `sealed_document_key` | str \| None | `contracts/{event_id}/v{n}-gesiegelt.pdf` |
| `sealed_document_sha256` | str \| None | Hash der versiegelten Bytes |
| `sealed_at` | datetime \| None | |
| `seal_key_id` | str \| None | die benutzte KMS-Key-ARN, damit 2033 nachvollziehbar ist, womit gesiegelt wurde |
| `seal_timestamped` | bool | RFC-3161-Zeitstempel vorhanden (PAdES B-T) oder nicht (B-B) |

`CharterSignature` — eine Zeile je Unterschrift, eingebettet in die
Vertragszeile (es sind höchstens drei, eine eigene Partition wäre Overkill):

| Feld | Typ | Anmerkung |
|---|---|---|
| `role` | `charterer` \| `skipper` \| `vercharterer` | |
| `signed_name` | str | getippter Name, immer gesetzt — auch wenn gezeichnet wurde |
| `image_key` | str \| None | `contracts/{event_id}/sig-{role}.png`, fehlt bei reiner Tippunterschrift |
| `signed_at` | datetime | |
| `document_sha256` | str | Hash **des vorgelegten Renders** — der Beweis, welche Fassung die Person sah |
| `signer_ip` | str \| None | nur beim öffentlichen Weg; `None`, wenn im Admin gezeichnet |
| `signer_user_agent` | str \| None | dito, auf 200 Zeichen gekürzt |
| `by_admin` | str \| None | gesetzt, wenn ein eingeloggter Mensch gezeichnet hat |
| `superseded_signed_keys` | list[str] | wächst beim Verwerfen; aus S3 wird nie etwas gelöscht |
| `retention_until` | date | 31.12. des Jahres von `uebergabe_at` + 10. **Beim Rendern berechnet**, nicht beim Speichern — im Entwurf darf `uebergabe_at` noch wandern |
| `created_at` / `updated_at` | datetime | |

`retention_until` ist bewusst **eine** Frist statt drei sauber getrennter
steuer- und handelsrechtlicher Klassen. Ein vierseitiges PDF kostet nichts,
eine Fehlklassifikation schon.

Pydantic v2, `model_copy(update={...})` für jede Mutation, `Decimal` statt
`float` (DynamoDB lehnt float ab), `datetime.now(timezone.utc)` durchgängig.
Singleton-Service `backend/app/services/charter_service.py` mit dem üblichen
`_service = None; def get_charter_service()`.

**Kein neuer `EventType`.** Die Existenz der `CHARTER`-Zeile *ist* die
Tatsache, dass diese Fahrt gechartert ist. Ein `EventType.CHARTER` wäre teuer
und gefährlich: `create_event` erzeugt für jeden Typ außer FESTIVAL einen
`registration_link_token` (`event_service.py:279`), und der öffentliche
Anmeldepfad weist nur FESTIVAL ab (`registration_service.py:597`) — ein
Charter-Event wäre ab Anlage öffentlich buchbar, und neun weitere
`!= FESTIVAL`-Stellen änderten still ihr Verhalten.

**Nur SINGLE.** Ein Chartervertrag ist ein Gegenüber, ein Floß, ein Tag; ein
FESTIVAL ist viele Gäste über mehrere Tage mit Einladungen und Gate. `PUT`
antwortet auf einem FESTIVAL-Event mit 409 `charter_nur_fuer_einzelfahrten`.
Das ist eine Entscheidung, keine technische Schranke — die Zeile läge unter
einem FESTIVAL genauso gut. Sollte je ein Festivaltag verchartert werden, ist
es eine Zeile weniger.

## Zwei oder drei Unterschriften

Das Original hat drei Blöcke: Charterer, Schiffsführer, Vercharterer.

**Der Normalfall sind zwei.** Der Charterer ist in aller Regel selbst
Crewmitglied und fährt an diesem Tag als Schiffsführer; unterschrieben wird am
Fahrttag. `skipper_is_charterer` ist deshalb mit **`true`** vorbelegt, und der
Renderer setzt dann **zwei** Blöcke, den ersten beschriftet „Datum /
Unterschrift – Charterer und Schiffsführer". Das vorliegende Muster (Charterer
ein externer Charterer, Schiffsführer ein Vereinsmitglied) ist die Ausnahme, nicht die
Regel — sie muss funktionieren, aber sie ist nicht der Pfad, für den optimiert
wird.

Das bleibt eine Eigenschaft des erzeugten Dokuments, keine Zustandsmaschine:
zwei Blöcke oder drei, entschieden beim Rendern. Kein bedingtes Feld, keine
zwei Vorlagen, die auseinanderlaufen können.

**Die Gegenzeichnung des Vercharterers ist optional.** Sie darf leer bleiben
und jederzeit nachgetragen werden. Der Block wird immer gedruckt, aber
`status = signed` hängt **nicht** an ihm — ein Vertrag gilt als
unterschrieben, sobald Charterer und (falls abweichend) Schiffsführer
gezeichnet haben. Das entspricht der gelebten Praxis: im Muster ist die
Vercharterer-Zeile blank. Wird später doch gegengezeichnet, trägt
`POST .../gegenzeichnung` nur `countersigned_on` und `countersigned_by` nach,
ohne Status, Dokument oder Hash anzufassen.

Eine Unterschriftsreihenfolge kennt dieser Spec nicht. Alle Anwesenden zeichnen
dasselbe Blatt, meist gleichzeitig am Steg.

## Das PDF: fpdf2, kein Formular

Das vorliegende Vertrags-PDF ist **flach**: kein AcroForm, keine Formular-
felder (geprüft). Es gibt keinen Ausfüllpfad. `pypdf` zu ergänzen hilft nicht —
es gibt nichts zu füllen.

Der Vertrag wird deshalb mit **fpdf2** neu gesetzt, wie der Boardingzettel
(`backend/app/api/admin/events.py:1145-1290`): Klauseln 1–17, Vereinsanschrift,
GLS-IBAN, Kennzeichen HH-AD-666 und die Chartergebiets-Definition als
Konstanten-Block in `backend/app/services/charter_template.py`, dazu eine
Layout-Funktion mit `multi_cell(..., align="J")` für die Blocksatz-Absätze und
umrandeten Zellen für die Datum/Unterschrift-Blöcke.

**Maßstab ist der Wortlaut, nicht das Aussehen.** Der Text ist Klausel für
Klausel identisch mit dem Original; das Layout ist, was fpdf2 gut kann —
Seitenumbrüche, Zeilenabstände und die Länge der Unterstrich-Linien dürfen
abweichen. Das hält das Abtippen kurz und richtet den Korrekturgang auf das,
was rechtlich trägt: die Wörter.

Das ist kein technisches Risiko, sondern sorgfältiges Abtippen — **plus ein
Korrekturgang durch ein Vorstandsmitglied, ausdrücklich nicht durch die Person,
die abtippt**, Klausel für Klausel gegen das rechtlich geprüfte Original, vor
der ersten Verwendung. Diese Stunde muss eingeplant werden, nicht entdeckt.

**Schrift:** eine Unicode-TTF (DejaVuSans) wird unter `backend/app/` abgelegt
und per `pdf.add_font()` registriert. Die Kernschriften von fpdf2 können `€`,
Gedankenstrich und deutsche Anführungszeichen nicht darstellen und werfen,
statt zu ersetzen. Die `_ascii()`-Transliteration aus
`report_service.py:938` ist für einen internen Finanzbericht in Ordnung und
für einen Vertrag nicht: ein Dokument, das „EUR" druckt, wo das Original „€"
sagt, ist nicht dasselbe Dokument. Das ist eine Bundle-Ergänzung, keine neue
Abhängigkeit — `fonttools==4.62.1` liegt bereits in `backend/requirements.txt`.

**Provenienz in jeder Fußzeile:** `template_version`, `document_version` und
die ersten 12 Hex-Zeichen des Render-Hashes. Das macht einen später
hochgeladenen *Scan* selbstbeschreibend und beantwortet die Frage „ist das ein
Foto von genau diesem Blatt?".

## Ablage: der bestehende reports-Bucket

Kein neuer Bucket. Die Objekte liegen im vorhandenen
`funke-{env}-reports` unter einem `contracts/`-Präfix, analog zu dessen
eigenem `reports/{id}/v{n}.pdf`:

```
contracts/{event_id}/v{n}.pdf
contracts/{event_id}/v{n}-signiert.pdf
```

Dieser Bucket hat bereits, was gebraucht wird (`api_stack.py:129-139`):
`BLOCK_ALL`, Verschlüsselung, `RemovalPolicy.RETAIN` außerhalb dev,
Versionierung außerhalb dev, **keine Lifecycle-Regel**, und Lese-/Schreibrecht
für API- und Worker-Lambda. Null CDK-Änderung an der Ablage.

**Verboten sind `funke-{env}-lostfound` und `funke-{env}-eventphotos.`** Beide
tragen `expiration=Duration.days(400)` (`api_stack.py:187` und `:245`) und
würden einen aufbewahrungspflichtigen Datensatz stillschweigend löschen. Das
steht hier, weil beide Buckets existieren, privat und verschlüsselt sind und
genau das sind, wonach jemand greift, der „irgendwo privat ein PDF ablegen"
will.

Die einzige nötige CDK-Änderung ist eine **CORS-Regel** (POST) auf dem
reports-Bucket für den Direktupload, kopiert von der lostfound-Regel
(`api_stack.py:162-191`). Der presignende S3-Client muss mit dem
angehefteten Regional-Endpunkt + `s3v4` + Virtual Addressing aus
`event_photo_service.py:452-472` gebaut werden — `report_service`'s schlichtes
`boto3.client("s3")` genügt für serverseitiges Put/Get und **nicht** für
Browser-Presigns.

**Manipulationsschutz, bewusst bescheiden:** SHA-256 der exakt gespeicherten
Bytes auf der Zeile, S3-Versionierung in prod, und `superseded_signed_keys`,
aus dem nichts verschwindet. Kein Object Lock. Der Spec sagt ausdrücklich, was
das leistet und was nicht: es schützt gegen Versehen und Bugs, **nicht** gegen
den Verein selbst — der Hash steht in einer Zeile, die dieselbe Admin-API
schreiben kann, und GOVERNANCE-mode Object Lock wäre vom Kontoinhaber ohnehin
umgehbar. Das echte Beweismittel ist das unterschriebene Papier; das stärkste
verfügbare digitale Gegengewicht ist, dass **der Charterer eine eigene Kopie
hat** (siehe unten).

## Ablauf

1. Orga legt ein gewöhnliches Event an.
2. Auf `EventDetailPage` erscheint ein Abschnitt **Chartervertrag** — ohne
   Zeile: „Kein Vertrag angelegt" + „Vertrag anlegen".
3. Orga füllt das Formular unter `/admin/events/{eventId}/chartervertrag`.
   `PUT` speichert in jedem Vollständigkeitsgrad; Status bleibt `draft`.
4. **„PDF erzeugen".** Server prüft den Pflichtsatz (Name, Anschrift, beide
   Termine, Chartergebühr, Kaution, Personenzahl, Schiffsführer, und — außer
   bei Personengleichheit — mindestens einen Führerschein), rendert, erhöht
   `document_version`, legt `v{n}.pdf` ab, speichert Key + SHA-256. Es wird
   **nie überschrieben**; jeder Render ist ein neues `n`.
5. **Zustellung.** Entweder „PDF herunterladen" (900-s-Presign, zweimal
   ausdrucken für den Steg) oder **„An Charterer senden"** — Direktversand per
   SMTP mit dem PDF als Anhang, nach dem Dreiweg-Muster aus `report_service`
   (`ValueError` → skipped, Exception → failed, sonst sent). Das ist zugleich
   die Textform-Kopie auf dauerhaftem Datenträger nach § 312f Abs. 2 BGB —
   deshalb das PDF selbst und kein Link. Status → `sent`.

   **Bei externen Charterern vorher senden.** Die Klauseln 1–17 sind AGB:
   vorformulierte Bedingungen, die für eine Vielzahl von Verträgen verwendet
   werden. § 305 Abs. 2 BGB verlangt, dass die Gegenseite vor Vertragsschluss
   zumutbar Kenntnis nehmen kann; vier Seiten am Steg zu unterschreiben,
   während die Gäste warten, ist genau die Konstellation, in der das kippt —
   und überraschende Klauseln (die 200 € Vertragsstrafe in § 5, die doppelte
   Gebühr in § 8) sind die, die dann nach § 305c fallen. Beim üblichen Fall
   — Charterer ist Crewmitglied und kennt die Bedingungen — ist das
   entspannt; bei einem externen Charterer ist der Vorabversand der Schritt,
   der die AGB überhaupt wirksam einbezieht. Die Seite weist darauf hin, sie
   erzwingt es nicht.
6. **Unterschrieben wird außerhalb von Funke.** Auf Papier bei der Übergabe,
   oder der Charterer druckt, unterschreibt, fotografiert und mailt zurück.
   Funke hat dazu keine Meinung und keine Integration.
7. **„Unterschriebenen Vertrag hochladen".** Presigned POST auf genau einen
   Key, Content-Type angeheftet, `content-length-range` 1..15 MB, 900 s;
   der Browser lädt direkt zu S3 über den vorhandenen
   `postPresignedForm(target, blob)`. Danach ein Confirm mit `signed_on` (dem
   Datum auf dem Papier) und der Pflicht-Checkbox „Charterer hat
   unterschrieben" — bzw. „Charterer und Schiffsführer haben unterschrieben",
   wenn die beiden nicht personengleich sind. Die Gegenzeichnung des
   Vercharterers wird hier **nicht** abgefragt. Der Server `head_object`t,
   streamt einmal für den Hash und setzt `status = signed`.
8. Der Chip am Event springt von `Entwurf` / `Verschickt` (amber) auf
   `Signiert am 14.06.2026` (grün).
9. **Nach der Unterschrift ist gesperrt.** `PUT` antwortet 409, solange
   `signed`. Korrigieren geht nur über „Unterschrift verwerfen" — das alte
   Objekt bleibt in S3 und sein Key wandert nach `superseded_signed_keys`. Der
   Präzedenzfall aus Spec 020 (QR-Codes heilen sich still bei Umbenennung)
   wird hier **bewusst umgekehrt**: bei einem unterschriebenen Vertrag *sind*
   die Bytes die Vereinbarung.

## Unterschreiben in Funke

Der Papierweg oben bleibt. Daneben tritt ein zweiter: der Charterer
unterschreibt auf einer Token-Seite im Browser, und Funke setzt die
Unterschrift ins PDF.

**Warum die Kehrtwende.** Die erste Fassung argumentierte: die Parteien treffen
sich ohnehin am Steg, ein Stift ist billiger als jede Maschinerie. Das stimmt
weiter für den Normalfall. Zwei Dinge sprechen trotzdem dafür:

1. Der Papierweg hängt daran, dass **nach** der Fahrt jemand einen Scan
   hochlädt — zu einem Zeitpunkt, an dem der Vertrag niemanden mehr
   interessiert. Das ist die Lücke, die diese Fassung schließt.
2. Ein externer Charterer, der Wochen vorher zusagt, kann so unterschreiben,
   bevor irgendwer am Steg steht — und bekommt damit die AGB rechtzeitig zur
   Kenntnis (§ 305 Abs. 2 BGB), statt vier Seiten zwischen Tür und Angel.

### Wer unterschreibt wo

| Rolle | Weg |
|---|---|
| Charterer | öffentliche Token-Seite `/vertrag/{event_id}/{sign_token}` |
| Schiffsführer (nur wenn abweichend) | Adminoberfläche — es ist ein Crewmitglied und hat ohnehin einen Login |
| Vercharterer | Adminoberfläche, weiterhin **optional** |

Das erspart einen zweiten öffentlichen Token für den Schiffsführer. Im
Normalfall (personengleich) gibt es genau eine Unterschrift und genau einen
Link.

### Was unterschrieben wird

Die Unterschrift muss das Dokument decken, das die Person **gesehen** hat —
sonst ist sie wertlos. Deshalb:

- Der Link entsteht erst, wenn ein PDF gerendert ist. Die Signaturseite zeigt
  genau dieses `v{n}.pdf` (Presigned GET, im `<iframe>` eingebettet), nicht eine
  Zusammenfassung. Dazu **immer** ein sichtbarer „PDF herunterladen"-Knopf: iOS
  Safari rendert PDFs in einem `<iframe>` unzuverlässig, und ohne den Knopf
  hätte ein Teil der Charterer nichts zu lesen.
- Mit jeder Unterschrift wird `document_sha256` des gezeigten Renders
  mitgeschrieben. Später lässt sich beweisen, welche Fassung vorlag.
- **Jeder neue Render entwertet Token und Unterschriften.** `POST /render`
  wirft einen frischen `sign_token`, löscht gesammelte Unterschriften und
  setzt den Status auf `draft` zurück. Das ist die Umkehrung des Spec-020-
  Präzedenzfalls (QR-Codes heilen sich still) und hier zwingend: ein Vertrag,
  dessen Text sich nach der Unterschrift ändert, ist kein unterschriebener
  Vertrag. Die Oberfläche warnt vor dem Rendern, wenn bereits jemand
  gezeichnet hat.

### Die Unterschrift selbst

Ein `<canvas>` mit Zeichnen per Finger oder Maus, plus ein Textfeld „Name in
Druckbuchstaben" als Fallback für Geräte, auf denen Zeichnen nicht geht. Beides
zusammen wird als PNG mit transparentem Hintergrund abgelegt
(`contracts/{event_id}/sig-{index}.png`) und beim Zusammenbau ins PDF gesetzt.

Erfasst wird zusätzlich, was den Beweiswert ausmacht: Zeitpunkt, IP,
User-Agent, und der Hash des vorgelegten Dokuments. Das ist eine einfache
elektronische Signatur (SES) — dieselbe Stufe wie ein Kugelschreiber und
dieselbe wie Google eSignature, also nichts verloren.

### Ablauf

1. Organisation rendert das PDF und klickt „Signaturlink an Charterer
   senden". Funke mailt den Link (und weiterhin das PDF im Anhang, § 312f).
2. Charterer öffnet den Link, liest das PDF, zeichnet, bestätigt.
3. Ist ein abweichender Schiffsführer eingetragen, zeichnet dieser in der
   Adminoberfläche.
4. Sobald alle **erforderlichen** Unterschriften vorliegen, baut Funke das
   Enddokument: Unterschriftsbilder an ihre Stellen, dann versiegeln.
5. Die Gegenzeichnung des Vercharterers bleibt optional und kann danach
   nachgetragen werden — sie erzeugt eine neue versiegelte Fassung, die alte
   bleibt liegen.
6. **Das versiegelte PDF geht automatisch raus**: an den Charterer und an
   `settings.finance_report_inbox` (die Adresse, die schon den Finanzbericht
   bekommt — keine zweite Einstellung, keine Adresse im Code). Dass die
   Gegenseite eine eigene Kopie hält, ist das stärkste verfügbare
   Manipulationsargument — stärker als das Siegel, weil es ein Nachweis ist,
   den der Verein nicht nachträglich ändern kann. Zugleich § 312f Abs. 2.

   **Achtung Betrieb:** `FINANCE_REPORT_INBOX` ist in der Produktion aktuell
   **leer**; der Finanzbericht wird deshalb seit immer als
   `SKIPPED_NO_RECIPIENT` verbucht (`report_service.py:314`). Solange die
   Variable leer ist, geht auch der Vertrag nur an den Charterer.

## Siegel: pyHanko + KMS

Das fertige Dokument wird kryptografisch versiegelt. Das schließt die Lücke,
die die Prüfung dieses Specs benannt hat: bisher stehen Hash und Audit-Zeilen
in Tabellen, die dieselbe Admin-API beschreiben kann — der Verein konnte sein
eigenes Dokument nachträglich ändern, ohne dass es auffiel.

**Bibliothek: [pyHanko](https://github.com/MatthiasValvekens/pyHanko)**, MIT,
Python 3.10+, PAdES B-B bis B-LTA. Praktisch verifiziert: Signieren des
gerenderten Chartervertrags funktioniert, und ein einziges gekipptes Byte
liefert bei der Prüfung `intact=False`.

**Schlüssel: AWS KMS, asymmetrisch (`SIGN_VERIFY`, RSA_2048).** Der private
Schlüssel entsteht im HSM und ist **nicht exportierbar** — es gibt ihn nirgends
im Stack. Das ist der Grund für KMS und nicht für eine `.p12`-Datei: Secrets
erreichen die Lambda heute als **Klartext-Umgebungsvariablen**
(`api_stack.py:50`), sichtbar im CloudFormation-Template. Ein Signaturschlüssel
gehört dort nicht hin, und mit KMS gibt es schlicht keinen zu lagern. Wer
signieren darf, entscheidet IAM; jede Signatur steht in CloudTrail.

pyHanko unterstützt das über einen externen Signer, der `kms:Sign` aufruft
(offizielles Beispiel in der pyHanko-Dokumentation).

**Zertifikat: selbstsigniert**, um den öffentlichen KMS-Schlüssel gewickelt —
und zwar **vom KMS-Schlüssel selbst signiert**. Das geht mit gewöhnlichem
Werkzeug nicht: `cryptography`s `CertificateBuilder.sign()` braucht einen
lokalen privaten Schlüssel, und den gibt es hier per Konstruktion nicht. Das
Zertifikat wird deshalb einmalig mit `asn1crypto` zusammengebaut und seine
Signatur per `kms:Sign` erzeugt (`app/scripts/charter_seal_bootstrap.py`).
Verifiziert: das Ergebnis trägt den öffentlichen KMS-Schlüssel, die EKU
`1.3.6.1.5.5.7.3.36` (Dokumentsignatur — genau das, was Let's Encrypt und ACM
nicht ausstellen können), zehn Jahre Laufzeit, und lässt sich mit
Standardwerkzeug lesen.

Läuft das Zertifikat ab, scheitern **neue** Siegel; bereits gesiegelte
Dokumente bleiben gültig, weil der RFC-3161-Zeitstempel belegt, dass das Siegel
vor dem Ablauf entstand.

**Ablage des Zertifikats: S3**, im bestehenden reports-Bucket unter
`contracts/_seal/cert.pem`, beim Cold Start gelesen. Nicht als
Umgebungsvariable, obwohl der Platz reichte (30 Variablen, 1109 von 4096 Bytes;
das PEM sind 1253) — sondern weil so **ein** Deploy genügt statt zwei
(Schlüssel anlegen → Zertifikat erzeugen → Zertifikat einsetzen) und ein
späterer Zertifikatstausch ohne Deploy möglich bleibt.

Verworfen wurden:

- **Let's Encrypt** — stellt nur TLS-Zertifikate aus (`serverAuth`, CN = eine
  Domain, 90 Tage). Kein Dokument-Signatur-Produkt, in keiner Trust-Liste für
  Dokumente, und es wäre der Schlüssel, der HTTPS terminiert. Gegenüber
  selbstsigniert **schlechter**, nicht besser: dieselbe Vertrauensstufe im
  Reader, dazu falsche EKU und Schlüssel-Doppelnutzung.
- **ACM (öffentlich)** — dieselbe Sackgasse, TLS-Zertifikate.
- **AWS Private CA** — kann beliebige EKUs, hängt aber an einer privaten
  Wurzel, der niemand sonst vertraut. 400 $/Monat (50 $ im Kurzläufer-Modus)
  für exakt die Vertrauensstufe, die selbstsigniert gratis liefert.

Was das Siegel leistet und was nicht, in einem Satz: es beweist, dass **diese
Bytes seit dem Siegeln unverändert** sind. Es beweist nicht, wer unterschrieben
hat, und es hindert niemanden mit `kms:Sign` daran, ein anderes Dokument zu
versiegeln — aber der Schlüssel lässt sich nicht mehr stehlen und jede
Benutzung steht im Log.

**Zeitstempel.** Zusätzlich ein RFC-3161-Zeitstempel eines freien TSA
(PAdES B-T). Ein Dritter bezeugt damit, dass der Hash zu diesem Zeitpunkt
existierte — unabhängig vom Verein und wertvoller als das Siegel allein. Ist
der TSA nicht erreichbar, wird ohne Zeitstempel gesiegelt (B-B) und
`seal_timestamped = false` vermerkt; ein fehlender Zeitstempel darf die
Unterschrift nicht blockieren.

**Kosten:** 1 $/Monat für den KMS-Schlüssel, 0,03 $ je 10 000 Signaturen. Bei
~20 Verträgen im Jahr rund **12 $/Jahr**.

**Bundle:** pyHanko zieht netto ~27 MB (überwiegend `lxml`; `cryptography`,
`requests`, `urllib3`, `certifi`, `cffi` liegen schon in
`requirements.txt`). Das Lambda-Paket wächst damit von 59 MB auf ~86 MB, weit
unter dem 250-MB-Limit. `backend/requirements.txt` muss nach der Aufnahme per
`uv export` neu erzeugt werden, sonst antwortet jede Route mit 500.

## „Vor Fahrtantritt" — was durchsetzbar ist

Ehrlich: nichts im System beobachtet `start_at`. Der Worker führt sieben
Aufgaben aus und keine davon fasst den Event-Status an
(`handler.py:1034-1048`). Es gibt keinen Moment, in dem die Software etwas
blockieren *könnte*, weil es keinen Moment gibt, in dem sie etwas bemerkt. Und
die Check-in-PWA bootet aus dem localStorage — eine Sperre dort wäre durch
Ausschalten des WLANs umgehbar.

Statt Durchsetzungstheater also zwei Dinge, die an bestehenden Gewohnheiten
hängen:

**Vor der Fahrt — ein Banner.** Ein rotes `role="status"`-Banner auf
`EventDetailPage`, Geschwister des vorhandenen Anonymisierungs-Hinweises:
„Chartervertrag ist noch nicht unterschrieben — Übergabe am 14.06. um 10:00."
Sichtbar, sobald eine Vertragszeile existiert, unsigniert ist und
`uebergabe_at` in ≤14 Tagen liegt. Kein zweiter Chip im Header-Slot: der
rendert eine Plakette, und zwei machen den Status mehrdeutig.

**Nach der Fahrt — Kopplung an den Fahrbericht.** Der Scan wird erfahrungs-
gemäß nach der Fahrt hochgeladen, wenn der Vertrag niemanden mehr
interessiert; ein eigener Nag-Job wäre ein rostendes Asset (365 Läufe im Jahr
für 20 Events). Stattdessen hängt die Erinnerung an der einen Gewohnheit, die
ohnehin nach jeder Fahrt greift, weil der Finanzbericht daran hängt: der
Fahrbericht-Abgabe.

`POST /api/admin/events/{event_id}/fahrbericht/submit`
(`api/admin/fahrbericht.py:73`) nimmt einen neuen, optionalen Body:

```json
{ "ohne_vertrag_abgeben": false }
```

Der Ablauf:

- Existiert für das Event **keine** `CHARTER`-Zeile, ändert sich nichts. Nicht
  jede Fahrt ist eine Charter, und der Normalfall darf nicht teurer werden.
- Existiert eine, ist aber `signed_document_key` leer, und ist das Flag
  `false` → **409 `chartervertrag_fehlt`**, mit dem Hinweis „Für diese Fahrt
  ist kein unterschriebener Chartervertrag hinterlegt."
- Mit `true` läuft die Abgabe durch und stempelt auf die `CHARTER`-Zeile
  `fahrbericht_override_by` (die abgebende Person) und
  `fahrbericht_override_at`. Nichts wird stillschweigend übergangen: die
  Vertragsseite zeigt danach „Fahrbericht ohne Vertrag abgegeben von … am …".

Das fängt den Vergesslichkeitsfall — den häufigen — und sperrt niemanden aus,
der an diesem Tag schlicht keinen Scan produzieren kann. Wichtig ist die
Asymmetrie: der Finanzbericht hängt am Fahrbericht, also darf ein fehlendes PDF
die Buchhaltung nicht dauerhaft blockieren; er darf nur nicht **unbemerkt**
fehlen.

**Kein neuer EventBridge-Task in v1.**

## Aufbewahrung

Ein unterschriebener Chartervertrag mit Gebühr und Kaution ist
buchhaltungsrelevant. `retention_until` = 31.12. des Übergabejahres + 10 Jahre.

`delete_event` (`event_service.py:1049`) und `delete_festival_event`
(`:1146`) **verweigern**, solange eine `CHARTER`-Zeile mit Status `signed` und
`retention_until` in der Zukunft existiert — in der Form der bestehenden
`lostfound_not_deleted`-Sperre.

Diese Sperre ist nicht optional, und der Grund ist schlimmer als „das Dokument
wäre weg": `delete_event` löscht **genau ein** Item
(`pk=ORG#{org_id}, sk=EVENT#{event_id}`). Vertragszeilen liegen unter
`pk=EVENT#{event_id}` — einer anderen Partition. Sie überleben das Löschen
also und werden zu einem **verwaisten Datensatz**, der Name, Anschrift und
zwei Führerscheinnummern trägt, über keine Adminroute mehr erreichbar ist und
keine Frist mehr hat. Das ist schlechter als Löschen, nicht besser.
`delete_festival_event` räumt `INVITE#`/`REG#`/`SCAN#`/`MSG#` per Präfix ab und
ließe `CHARTER` im selben verwaisten Zustand zurück.

## Verhältnis zu Spec 022 (Anonymisierung)

`anonymize_event` zählt genau vier Scrub-Durchläufe auf —
`_anonymize_registrations`, `_anonymize_scans`, `_anonymize_invites`,
`_anonymize_messages` — plus `_delete_lost_and_found` und
`_delete_event_photos`. Es gibt **keinen generischen Präfix-Scrub**. Eine
`CHARTER`-Zeile überlebt den Sweep also von selbst.

Das ist hier das gewünschte Verhalten und muss deshalb *festgeschrieben*
werden, nicht bloß zufällig eintreten:

- Spec 025 bringt einen **Regressionstest** mit, der behauptet: nach
  `anonymize_event` sind `charterer_name`, `charterer_address` und die
  Führerscheinnummern unverändert.
- Die Vertragszeile trägt eine **eigene, denormalisierte Kopie** von Name und
  Anschrift. Damit kann die Pseudonymisierung der `REG#`-Zeile sie nicht
  aushöhlen.
- Spec 022 bekommt **einen Satz** in seinem Abschnitt *Nicht abgedeckt*, damit
  die Ausnahme dort steht, wo der nächste Leser von 022 sie sucht.

**Kein `_restrict_charter`-Hook in `anonymize_event`.** Er würde nie feuern —
siehe nächster Abschnitt.

## Eine Lücke, die dieser Spec sichtbar macht

`ANONYMIZABLE_STATUSES` ist `{COMPLETED, CANCELLED}`
(`anonymization_service.py:159`). `COMPLETED` ist ausschließlich aus
`CONFIRMED` erreichbar (`EVENT_STATUS_TRANSITIONS`, `models/event.py`). Und
`CONFIRMED` erreicht man nur über `mark_confirmed_after_lottery`, dessen
einziger Aufrufer im gesamten Backend `lottery_service.py:372` ist. Für
FESTIVAL gibt es einen generischen Status-Endpunkt
(`api/admin/festival.py:275-311`); für SINGLE gibt es keinen.

Eine gecharterte Fahrt läuft keine Verlosung. Sie bliebe damit für immer in
`REGISTRATION_CLOSED` stehen, wäre nie abschließbar und würde folglich **nie
anonymisiert** — Anmeldungen, Scans, Einladungen und Nachrichten inklusive.

Das ist eine Ein-Endpunkt-Änderung (generischer Statuswechsel für SINGLE, nach
dem Vorbild von `festival.py:275-311`, der `REGISTRATION_CLOSED → CONFIRMED`
ohne Verlosung erlaubt). Sie gehört **nicht** in diesen Spec — sie berührt
SINGLE-Events allgemein und sollte getrennt geliefert werden. Sie ist aber
Voraussetzung dafür, dass Charter-Events datenschutzrechtlich sauber
auslaufen, und deshalb hier notiert.

Nicht in `EVENT_STATUS_TRANSITIONS` eine Kante `REGISTRATION_CLOSED →
COMPLETED` ergänzen: die Tabelle ist mit SINGLE und FESTIVAL geteilt und würde
jedem Event erlauben, die Bestätigung zu überspringen.

## Endpunkte

Neuer Router `backend/app/api/admin/charter.py`, in `main.py` unter
`prefix="/api/admin/events"` montiert wie `admin_lost_and_found` und
`admin_event_photos`, mit dem modul-lokalen `_get_event_or_404` fürs
Org-Scoping. **Keine öffentliche Route.**

**Rollen.** `CurrentUser` (`services/auth.py:208`) prüft nur das Token; die
Rollenprüfung ist ein separates, freiwilliges `Depends(require_role([...]))`.
Jede Route hier bekommt es explizit:

- **Lesend** (`GET` auf Vertrag und PDF): `OWNER, ADMIN, VIEWER`
- **Alles andere** (`PUT`, `render`, `senden`, `upload`, `signiert`,
  `gegenzeichnung`, `unsign`, `DELETE`): `OWNER, ADMIN`

Das entspricht `AdminUser.can_edit_events()` (`models/admin.py:57`), das VIEWER
ausschließt, und dem Muster in `admin/events.py:149`. Anders als bei
`lost_and_found.py` und `event_photos.py` wird hier **nichts ungeschützt
gelassen** — siehe die Notiz unten.

| Route | Zweck |
|---|---|
| `GET .../{event_id}/chartervertrag` | Vertrag oder 404. Liefert `gesamtbetrag` live berechnet, `download_url`, `signed_download_url`, `can_edit` |
| `PUT .../{event_id}/chartervertrag` | Upsert des Entwurfs, idempotent, teilbefüllt erlaubt. 409 `vertrag_bereits_unterschrieben` bei `signed` |
| `POST .../{event_id}/chartervertrag/render` | Pflichtsatz prüfen, rendern, ablegen. 422 mit deutscher Feldliste |
| `GET .../{event_id}/chartervertrag/pdf` | 302 auf Presign (`?variant=signiert` für den Scan) |
| `POST .../{event_id}/chartervertrag/senden` | Direktversand als Anhang. 409 ohne Render/Adresse, 503 `smtp_nicht_konfiguriert` |
| `POST .../{event_id}/chartervertrag/upload` | Presigned POST für `v{n}-signiert.pdf`. 409 ohne Render |
| `POST .../{event_id}/chartervertrag/signiert` | Bestätigung: `signed_on` + `alle_parteien_unterschrieben`. Hasht das Objekt |
| `POST .../{event_id}/chartervertrag/signaturlink` | Mailt dem Charterer den Signaturlink (plus PDF im Anhang). 409 ohne Render oder ohne Adresse |
| `POST .../{event_id}/chartervertrag/unterschreiben` | Admin-seitige Unterschrift für `skipper` oder `vercharterer`. Body: `{role, signed_name, image_b64?}` |
| `POST .../{event_id}/chartervertrag/gegenzeichnung` | Trägt `countersigned_on` + `countersigned_by` nach. Ändert **nicht** Status, Dokument oder Hash. Jederzeit erlaubt, auch Jahre später |
| `POST .../{event_id}/chartervertrag/unsign` | Unterschrift verwerfen, alten Key aufheben, → `draft` |
| `DELETE .../{event_id}/chartervertrag` | Nur solange `draft` **und** ohne Render; sonst 409 |

Einzige Änderung an einem bestehenden Endpunkt: `GET /api/admin/events/{id}`
liefert zusätzlich einen kleinen Block `charter_contract`
`{status, uebergabe_at, signed_on}`, damit Abschnitt und Banner ohne zweiten
Request rendern.

### Öffentlich (Token ist die Berechtigung, kein `authGuard`)

Neuer Router `backend/app/api/public/charter.py`, montiert unter
`/api/public/vertrag`. Der Token wird mit `secrets.compare_digest` gegen die
Zeile geprüft — dasselbe Muster wie `/lostfound/{event_id}/{token}` (Spec 023).
Die `event_id` steht wie dort bewusst im Pfad und ist kein Geheimnis.

| Route | Zweck |
|---|---|
| `GET /api/public/vertrag/{event_id}/{token}` | Was die Signaturseite braucht: Eventname, Übergabe/Rückgabe, Beträge, Charterer- und Schiffsführername, ob schon gezeichnet wurde, und ein 900-s-Presigned-GET auf das vorgelegte PDF. **Keine** Führerscheinnummern, keine Anschrift, keine internen Felder |
| `POST /api/public/vertrag/{event_id}/{token}` | Die Unterschrift: `{signed_name, image_b64?, document_sha256}`. Der mitgeschickte Hash muss dem aktuellen Render entsprechen — sonst 409 `vertrag_wurde_geaendert`, weil die Person eine veraltete Fassung vor sich hat |

Beide sind bewusst schmal: der Charterer sieht seinen Vertrag und
unterschreibt, mehr nicht. Kein Bearbeiten, kein Stornieren, kein Zugriff auf
andere Events.

Der Token stirbt bei jedem `render`. Ein alter Link antwortet danach 404 — die
gleiche Notbremse wie `rotate-token` bei Spec 023, nur automatisch.

## Fehler

Kennung als `detail`, deutscher Text fürs UI — wie in 023/024.

| Kennung | HTTP | Text |
|---|---|---|
| `charter_nur_fuer_einzelfahrten` | 409 | „Ein Chartervertrag kann nur zu einer Einzelfahrt angelegt werden." |
| `vertrag_bereits_unterschrieben` | 409 | „Ein unterschriebener Vertrag kann nicht geändert werden. Zum Korrigieren zuerst die Unterschrift verwerfen." |
| `vertrag_unvollstaendig` | 422 | „Es fehlen noch Angaben: {Feldliste}." — die Liste nennt deutsche Feldnamen, nicht Attributnamen |
| `vertrag_nicht_erzeugt` | 409 | „Es gibt noch kein PDF. Bitte zuerst „PDF erzeugen"." |
| `keine_charterer_adresse` | 409 | „Für den Versand fehlt die E-Mail-Adresse des Charterers." |
| `smtp_nicht_konfiguriert` | 503 | „Der Mailversand ist nicht eingerichtet. Bitte das PDF herunterladen und selbst verschicken." |
| `datei_nicht_hochgeladen` | 404 | „Die hochgeladene Datei ist nicht angekommen. Bitte den Upload wiederholen." |
| `vertrag_nicht_unterschrieben` | 409 | „Dieser Vertrag ist nicht als unterschrieben markiert." — bei `unsign` |
| `vertrag_bereits_erzeugt` | 409 | „Ein Vertrag mit erzeugtem PDF kann nicht gelöscht werden." |
| `chartervertrag_fehlt` | 409 | „Für diese Fahrt ist kein unterschriebener Chartervertrag hinterlegt." — bei der Fahrbericht-Abgabe |
| `charter_not_deleted` | 409 | „Das Event hat einen unterschriebenen Chartervertrag und kann bis {Jahr} nicht gelöscht werden." |
| `vertrag_wurde_geaendert` | 409 | „Der Vertrag wurde inzwischen geändert. Bitte lade die Seite neu und prüfe die neue Fassung." |
| `bereits_unterschrieben` | 409 | „Für diese Rolle liegt bereits eine Unterschrift vor." |
| `siegel_fehlgeschlagen` | 503 | „Das Dokument konnte nicht versiegelt werden. Die Unterschrift ist gespeichert; bitte später erneut versiegeln." |

Die Feldliste bei `vertrag_unvollstaendig` deckt: Name, Anschrift, Übergabe,
Rückgabe, Chartergebühr, Kaution, Personenzahl, Schiffsführer und — nur wenn
Charterer und Schiffsführer verschieden sind — mindestens einen Führerschein.

## Adminansicht

`EventDetailPage.vue` bekommt einen Abschnitt **Chartervertrag** direkt nach
dem Fahrbericht-Block, in dessen eigener Drei-Zustands-Form (kein Vertrag /
Entwurf bzw. verschickt / signiert), mit Chevron und `#detail`-Unterzeile wie
die Einträge *Fundsachen* und *Fotos*. Dazu das oben beschriebene Banner.

Eine neue Seite `CharterContractPage.vue`, geroutet auf
`/admin/events/:eventId/chartervertrag`, mit `authGuard`, in fünf Feldgruppen:
*Charterer* (Name, Anschrift, E-Mail, Telefon) · *Zeitraum* (Übergabe und
Rückgabe je Datum + Uhrzeit, beim ersten Öffnen aus `event.start_at`
vorbelegt) · *Kosten* (Chartergebühr, wiederholbare Sonderleistungs-Zeilen im
`ExpenseLine`-Muster des Fahrberichtsformulars, Kaution, dazu ein
schreibgeschützter **Gesamtbetrag** mit der Bildunterschrift „ohne Kaution") ·
*Schiffsführer* (Checkbox „Charterer und Schiffsführer sind dieselbe Person" —
**vorbelegt aktiv**; ist sie gesetzt, spiegelt das Namensfeld den Charterer und
der Vorschau-Hinweis zeigt zwei statt drei Blöcken. Dazu SBFS und SBFB je Nr. +
Datum und die Personenzahl ohne Skipper) · *Sondervereinbarungen*.

Weil der Charterer normalerweise Crewmitglied ist, hängt die `datalist` aus der
Crewliste (gefiltert auf `CrewRole.SKIPPER`) an **beiden** Namensfeldern, nicht
nur am Schiffsführer.

Aktionsleiste: „Speichern" · „PDF erzeugen" · „An Charterer senden" ·
Dateifeld + „Unterschrieben am" + „Als unterschrieben markieren" ·
„Gegenzeichnung nachtragen" (immer verfügbar, auch nach Jahren) ·
„Unterschrift verwerfen". Nach der Unterschrift sind alle Eingaben `disabled`
mit dem Hinweis „Ein unterschriebener Vertrag kann nicht geändert werden. Zum
Korrigieren zuerst die Unterschrift verwerfen." — die Gegenzeichnung
ausgenommen, die bleibt bedienbar.

In `api.js` sieben dünne Methoden plus die unveränderte Wiederverwendung von
`postPresignedForm`. **Keine neue Komponente**, kein Upload-Composable — es ist
eine Datei, kein Pool.

Nebengewinn: existiert ein Vertrag, wird `Fahrbericht.charterer` daraus
vorbelegt. Das Freitextfeld wird dann nicht mehr zweimal getippt und
widerspricht dem Vertrag nicht mehr.

## Testabdeckung

- Rendern erzeugt zwei Unterschriftsblöcke bei Personengleichheit (Vorgabe),
  drei sonst.
- `signed` wird auch ohne Gegenzeichnung erreicht.
- `PUT` auf ein FESTIVAL-Event → 409 `charter_nur_fuer_einzelfahrten`.
- Ein VIEWER-Token bekommt auf `GET` 200 und auf jeder schreibenden Route 403.
- Fahrbericht-Abgabe: ohne Vertragszeile unverändert; mit unsigniertem Vertrag
  409; mit `ohne_vertrag_abgeben: true` erfolgreich **und** `override`-Felder
  gesetzt.
- `gegenzeichnung` nach `signed` ändert weder `status` noch
  `signed_document_sha256`.
- `gesamtbetrag` = Chartergebühr + Σ Sonderleistungen, **ohne** Kaution.
- `render` bei unvollständigem Pflichtsatz → 422 mit Feldliste.
- Zweiter Render überschreibt nicht, sondern erzeugt `v2`.
- `PUT` auf einen signierten Vertrag → 409.
- `unsign` hebt den alten Key in `superseded_signed_keys` und löscht nichts.
- `signiert` ohne vorhandenes S3-Objekt → 404.
- **`anonymize_event` lässt Name, Anschrift und Führerscheinnummern intakt.**
- `delete_event` und `delete_festival_event` verweigern bei signiertem Vertrag
  innerhalb der Frist.
- Der Renderer wirft nicht bei `€`, `–` und `„…"`.
- Presign-Bedingungen: exakter Key, angehefteter Content-Type, Größenfenster.

Für Unterschrift und Siegel zusätzlich:

- Ein `render` entwertet Token **und** gesammelte Unterschriften und setzt den
  Status auf `draft` zurück.
- Ein alter `sign_token` antwortet nach einem Render mit 404.
- Ein falscher Token für die richtige `event_id` → 404 (nicht 403: die Existenz
  eines Vertrags ist selbst eine Information).
- `POST` mit einem veralteten `document_sha256` → 409 `vertrag_wurde_geaendert`.
- Zweimal dieselbe Rolle → 409 `bereits_unterschrieben`.
- Die öffentliche `GET`-Antwort enthält **keine** Führerscheinnummern und
  **keine** Anschrift — ein Regressionstest auf die Feldliste, nicht auf
  einzelne Werte.
- Sind alle erforderlichen Unterschriften da, wird gesiegelt; das Ergebnis
  validiert mit `intact=True`.
- Ein gekipptes Byte im versiegelten PDF → `intact=False`.
- Ist der TSA nicht erreichbar, entsteht trotzdem ein Siegel, und
  `seal_timestamped` ist `false`.
- Bei personengleichem Schiffsführer genügt **eine** Unterschrift zum Siegeln;
  die Gegenzeichnung ist nie Voraussetzung.
- Ein VIEWER bekommt auf `signaturlink` und `unterschreiben` 403.
- Das versiegelte PDF geht an Charterer **und** `finance_report_inbox`.
- Fällt der Mailversand aus, bleibt der Vertrag trotzdem unterschrieben und
  abgelegt — eine Kopie darf verloren gehen, eine Unterschrift nicht.
- Ein Bild, das kein PNG ist, und eines über 500 kB werden abgewiesen.
- Das Bootstrap-Skript nennt den Deploy-Schritt, wenn der Schlüssel fehlt.
- Fehlt das Zertifikat, verweigert das Siegel sauber statt zu krachen — das ist
  der Zustand zwischen `cdk deploy` und dem Bootstrap.

## Getroffene Entscheidungen (27.08.2026)

1. **Unterschriftsweg: Papier am Fahrttag.** Der Charterer ist normalerweise
   selbst Crewmitglied und fährt an diesem Tag als Schiffsführer; unterschrieben
   wird an Bord bzw. am Steg. ~~Keine Signaturseite, kein Token, kein
   öffentlicher Endpunkt in v1.~~ — **noch am selben Tag durch Punkt 11
   überholt**: die Signaturseite kommt doch, der Papierweg bleibt daneben.
2. **Klauseltext als Code.** Die Klauseln 1–17 liegen als Python-Konstanten in
   `charter_template.py` mit einer `TEMPLATE_VERSION`. Jede Wortänderung
   durchläuft damit Review und Deploy — bei einem Vertragstext ist dieses
   Nadelöhr Merkmal, nicht Mangel.
3. **Gegenzeichnung optional.** Die Vercharterer-Zeile darf leer bleiben und
   jederzeit nachgetragen werden; sie blockiert weder `signed` noch die
   Übergabe.
4. **Korrekturgang durch ein Vorstandsmitglied**, ausdrücklich nicht durch die
   Person, die den Text abtippt. Eine Stunde, gebucht vor der ersten
   Verwendung.

5. **Nur SINGLE-Events.** Ein FESTIVAL kann keinen Vertrag tragen; `PUT`
   antwortet dort 409.
6. **PDF-Treue: Wortlaut, nicht Aussehen.** Text klauselgleich, Layout frei.
7. **Rollenlücke separat.** Sechs bestehende Adminrouter
   (`event_photos`, `lost_and_found`, `fahrbericht`, `ship`, `bar_items`,
   `reports`, zusammen 45 Routen) haben **kein** `require_role` und lassen
   damit einen VIEWER schreiben, obwohl `can_edit_events()` ihn ausschließt.
   Das ist eine eingeladene, authentifizierte Person, die ihre Rolle
   überschreitet — kein offener Zugang von außen. Wird als eigener,
   mechanischer Fix nachgezogen, **nicht** in 025. Spec 025 gated seine
   eigenen Routen von Anfang an vollständig.

Ohne Rückfrage entschieden, weil folgenlos umkehrbar:

8. **Aufbewahrung pauschal zehn Jahre.** Keine Aufteilung in sechs- und
   zehnjährige Klassen — ein vierseitiges PDF kostet nichts, eine
   Fehlklassifikation schon.
9. **`ExpenseLine`** kommt aus `models/fahrbericht.py`, nicht aus
   `models/report.py`. **`retention_until`** wird beim Rendern berechnet. Der
   `charter_contract`-Block hängt an der eigenen `EventResponse` in
   `api/admin/events.py:62`, nicht an der in `models/`.

Nachtrag 27.08.2026:

11. **In-App-Unterschrift und Siegel** kommen dazu (Kehrtwende gegenüber den
    Nicht-Zielen der ersten Fassung). Der Papierweg bleibt daneben bestehen.
12. **Siegelschlüssel in AWS KMS**, asymmetrisch, nicht exportierbar — weil
    Secrets hier sonst als Klartext-Umgebungsvariable enden würden.
    ~12 $/Jahr.
13. **Selbstsigniertes Zertifikat**, aus der Konfiguration geladen und damit
    später austauschbar. Let's Encrypt und ACM können keine
    Dokumentzertifikate; AWS Private CA kostet 400 $/Monat für dieselbe
    Vertrauensstufe, die selbstsigniert gratis liefert.

Bewusst in Kauf genommen:

10. **Kein Schutz gegen gleichzeitiges Rendern.** `document_version` wird
    lesend-schreibend erhöht; zwei parallele Renders könnten dasselbe `n`
    vergeben und der spätere den früheren überschreiben — entgegen der
    Zusage weiter oben, dass nie überschrieben wird. Akzeptiert, weil in
    der Praxis genau eine Person Verträge anfasst. **Sobald zwei Menschen
    das tun, muss hier ein bedingtes Update hin.**

## Vorschlag, nicht Teil von v1

`AdminUser` (`backend/app/models/admin.py`) kennt `crew_roles`, aber **keine
Führerscheindaten**. Da der Charterer meist Crewmitglied ist und dieselbe
Handvoll Schiffsführer wiederkehrt, würden vier Felder auf `AdminUser` —
`sbfs_number`, `sbfs_issued_on`, `sbfb_number`, `sbfb_issued_on`, gepflegt auf
der Profilseite — das Abtippen der Nummern pro Vertrag beenden. Das trifft
Problem 1 („falsch ausgefüllt") direkt, ist rund ein halber Tag und hängt an
nichts anderem in diesem Spec. Bewusst **nicht** eingeplant: es erweitert ein
Modell, das dieser Spec sonst nicht anfasst. Wenn es gewollt ist, als eigener
kleiner Schritt vor oder nach 025.

## Fluchtwege

- **Selbst-Signieren in Funke** war hier als Fluchtweg notiert und ist am
  27.08.2026 gegangen worden — siehe „Unterschreiben in Funke".
- **Ein echtes Siegelzertifikat** ersetzt das selbstsignierte durch Austausch
  von `CHARTER_SEAL_CERT_PEM`. Der KMS-Schlüssel bleibt, der Code bleibt; nur
  Reader zeigen dann ein grünes Häkchen statt „Gültigkeit unbekannt".
- **Falls je Schriftform gefordert ist**, ist der Weg eine echte QES —
  praktisch Skribble (~4,50 €/Signatur, Schweiz, Angemessenheitsbeschluss,
  dokumentierte REST-API). Nicht Google: das kann QES zu keinem Preis.

## Bewusst offen gelassen

Kein Mahnlauf, keine Zahlungsverfolgung für Gebühr und Kaution, keine
Serienverträge über mehrere Events, keine Vertragsvorlage pro Boot (es gibt
ein Floß), keine Mehrsprachigkeit, kein Export der Vertragsliste. Wenn der
Verein irgendwann ein zweites Fahrzeug chartert, wird `charter_template.py`
parametrisiert — nicht vorher.
