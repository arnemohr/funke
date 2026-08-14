# E-Mail-Vorlagen der Schaluppe

Dies ist eine Übersicht aller automatisch verschickten E-Mails.
Platzhalter stehen in geschweiften Klammern, z. B. `{Name}`, und werden beim Versand automatisch durch echte Werte ersetzt.

## Platzhalter

| Platzhalter | Bedeutung |
| --- | --- |
| `{Name}` | Name der angemeldeten Person |
| `{Veranstaltung}` | Name der Veranstaltung |
| `{Datum}` | Datum und Uhrzeit, z. B. „Samstag, 17. Mai 2026 um 19:00“ |
| `{Ort}` | Veranstaltungsort (oder „Wird noch bekannt gegeben“) |
| `{Personen}` | Anzahl der angemeldeten Personen |
| `{Personenwort}` | „Person“ oder „Personen“ – passend zur Anzahl |
| `{Anmeldeschluss}` | Datum, bis zu dem Anmeldungen möglich sind |
| `{Verwaltungslink}` | Persönlicher Link, um die Anmeldung zu bearbeiten |
| `{NachrichtVomAdmin}` | Vom Admin verfasste Nachricht (nur bei Absagen) |
| `{Dringlichkeit}` | „morgen“, „bald“ oder „in X Tagen“ |
| `{Version}` | Versionsnummer des Fahrberichts |
| `{Buchungstext}` | Der Buchungstext aus dem Fahrbericht |
| `{Zeitfenster}` | Festival: die gewählten Zeitfenster, kommagetrennt, z. B. „Freitag, Samstag“ – nie als Zeitspanne |
| `{Schlafplatz}` | Festival: Übernachtungswunsch plus Antwort – „Nein“ / „2 Zelte — angefragt“ / „2 Zelte — zugesagt“ / „2 Zelte — leider nicht möglich“. In der Zusage-Mail (F8) und der Ablehnungs-Mail (F9) steht nur der Wunsch selbst („2 Zelte, 1 Camper“) ohne Status – die ganze Mail *ist* die Antwort |
| `{EinladungsLink}` | Festival: persönlicher oder Kontingent-Link zur Anmeldung |
| `{KontaktAdresse}` | Festival: die hinterlegte Kontaktadresse für Rückfragen |
| `{MitmachHinweis}` | Festival: der konfigurierte Mitmach-Hinweis inkl. Schichtplan-Link (nur wenn hinterlegt) |
| `{Kontaktperson}` | Festival: Name der Person, die die Anmeldung gemacht hat (nur in den Begleitungs-Mails F5/F6) |
| `{TicketLink}` | Festival: Link zur eigenen Eintritts-Code-Seite einer Begleitung. Dort kann diese Person **nur ihre eigenen Tage** ändern oder sich selbst abmelden — nicht die Anmeldung der Gruppe. Nicht der Verwaltungslink |
| `{Begleitung}` | Festival: Name der Begleitung, die sich selbst abgemeldet hat (nur in F7) |

---

## 1. Anmeldung eingegangen

**Wann?** Direkt nachdem sich jemand für eine Veranstaltung angemeldet hat.

**Betreff:**
```
Anmeldung eingegangen: {Veranstaltung}
```

**Text:**
```
Moin {Name},

schön, dass du dabei sein willst! Deine Anmeldung für "{Veranstaltung}" ist bei uns eingegangen.

So geht's weiter:
- Bis zum Anmeldeschluss sammeln wir alle Anmeldungen.
- Gibt es mehr Anmeldungen als Plätze, entscheidet das Los.
- Du bekommst danach eine E-Mail, ob du einen Platz hast.

Deine Anmeldung:
- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen} {Personenwort}
- Anmeldeschluss: {Anmeldeschluss}

Deine Anmeldung verwalten:
{Verwaltungslink}

Bei Fragen, einfach melden!

Bis bald,
Dein Orga-Team
```

---

## 2. Auf die Warteliste

**Wann?** Wenn jemand sich anmeldet, aber die Veranstaltung schon voll ist.

**Betreff:**
```
Warteliste: {Veranstaltung}
```

**Text:**
```
Moin {Name},

Danke für deine Anmeldung zu "{Veranstaltung}".

Du stehst auf der Warteliste. Sobald ein Platz frei wird, rückst du automatisch nach und wir benachrichtigen dich.

Details:
- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen} {Personenwort}

Deine Anmeldung verwalten:
{Verwaltungslink}

Bis bald,
Dein Orga-Team
```

---

## 3. Anmeldung abgesagt

**Wann?** Wenn ein Admin (oder die Person selbst) die Anmeldung storniert.
**Hinweis:** Der Admin kann statt des Standardtextes eine eigene Nachricht (`{NachrichtVomAdmin}`) und einen eigenen Betreff schreiben.

**Betreff (Standard):**
```
Dein Platz an Bord: {Veranstaltung}
```

**Standardtext (wenn der Admin keine eigene Nachricht schreibt):**
```
Leider haben wir innerhalb der Frist keine Rückmeldung von dir erhalten, ob du wirklich mit an Bord kommst. Daher mussten wir deinen Platz an einen anderen Fisch aus unserem Schwarm weitergeben.

Falls du beim nächsten Mal wieder anheuern möchtest, freuen wir uns sehr auf dich!
```

**Aufbau der E-Mail:**
```
Moin {Name},

{NachrichtVomAdmin}

Herzliche Grüße,
Dein Orga-Team
```

---

## 4. Nachgerückt von der Warteliste

**Wann?** Wenn jemand abspringt und eine Person von der Warteliste einen Platz bekommt.

**Betreff:**
```
Platz frei! {Veranstaltung}
```

**Text:**
```
Moin {Name},

ein Fisch ist abgesprungen und du rückst nach! Du hast jetzt einen Platz für "{Veranstaltung}".

- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen} {Personenwort}

Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:

{Verwaltungslink}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Wir freuen uns auf dich!

Liebste Grüße,
Dein Orga-Team
```

---

## 5. Bei der Verlosung gewonnen

**Wann?** Nach der Verlosung – an alle, die einen Platz bekommen haben.

**Betreff:**
```
Platz reserviert — bitte bestätigen: {Veranstaltung}
```

**Text:**
```
Moin {Name},

gute Nachrichten: Du wurdest für "{Veranstaltung}" ausgelost und dein Platz ist reserviert!

- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen} {Personenwort}

Damit der Platz nicht verfällt, bestätige bitte innerhalb von 24 Stunden:

{Verwaltungslink}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Wir freuen uns auf dich!

Liebste Grüße,
Dein Orga-Team
```

---

## 6. Bei der Verlosung auf der Warteliste

**Wann?** Nach der Verlosung – an alle, die keinen Platz bekommen haben, aber auf der Warteliste landen.

**Betreff:**
```
Verlosung: Warteliste für {Veranstaltung}
```

**Text:**
```
Moin {Name},

Danke für deine Anmeldung zu "{Veranstaltung}".

Bei der Verlosung hast du leider keinen Platz bekommen, aber du stehst auf der Warteliste.
Sobald ein Platz frei wird, benachrichtigen wir dich sofort.

Details:
- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen} {Personenwort}

Deine Anmeldung verwalten:
{Verwaltungslink}

Drück die Daumen!

Bis bald,
Dein Orga-Team
```

---

## 7. Bei der Verlosung leider raus (keine Warteliste)

**Wann?** Nach der Verlosung – an Personen, die weder einen Platz noch einen Wartelistenplatz bekommen haben.

**Betreff:**
```
Verlosung: Leider nicht dabei bei {Veranstaltung}
```

**Text:**
```
Moin {Name},

Danke für deine Anmeldung zu "{Veranstaltung}".

Leider hast du bei der Verlosung keinen Platz bekommen.
Die Nachfrage war diesmal einfach zu groß.

Details:
- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen} {Personenwort}

Wir hoffen, dich beim nächsten Mal dabei zu haben!

Bis bald,
Dein Orga-Team
```

---

## 8. Veranstaltung abgesagt

**Wann?** Wenn ein Admin eine ganze Veranstaltung absagt – wird an alle Angemeldeten geschickt.

**Betreff:**
```
Veranstaltung abgesagt: {Veranstaltung}
```

**Text:**
```
Moin {Name},

Leider müssen wir dir mitteilen, dass "{Veranstaltung}" abgesagt wurde.

Ursprüngliche Details:
- Datum: {Datum}
- Ort: {Ort}

Wir entschuldigen uns für die Unannehmlichkeiten.

Bis bald,
Dein Orga-Team
```

---

## 9. Erinnerung: Bitte Teilnahme bestätigen

**Wann?** Einige Tage vor der Veranstaltung als Erinnerung, die Teilnahme zu bestätigen.
**Hinweis:** `{Dringlichkeit}` wird automatisch ersetzt:
- ein Tag vorher → „morgen“
- zwei bis drei Tage vorher → „bald“
- sonst → „in X Tagen“

**Betreff:**
```
Bitte bestätigen: {Veranstaltung} ist {Dringlichkeit}!
```

**Text:**
```
Moin {Name},

"{Veranstaltung}" steht {Dringlichkeit} an!

- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen}

Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:

{Verwaltungslink}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Liebste Grüße,
Dein Orga-Team
```

---

## 10. Rückmeldung bestätigt – Zusage

**Wann?** Direkt nachdem jemand auf „Ja, ich komme“ geklickt hat.

**Betreff:**
```
Rückmeldung bestätigt: {Veranstaltung}
```

**Text:**
```
Moin {Name},

Danke für deine Rückmeldung! Deine Teilnahme an "{Veranstaltung}" ist bestätigt.

Details:
- Datum: {Datum}
- Ort: {Ort}

Wir freuen uns auf dich!

Bis bald,
Dein Orga-Team
```

---

## 11. Rückmeldung bestätigt – Absage

**Wann?** Direkt nachdem jemand auf „Nein, ich komme nicht“ geklickt hat.

**Betreff:**
```
Rückmeldung bestätigt: {Veranstaltung}
```

**Text:**
```
Moin {Name},

Deine Absage für "{Veranstaltung}" wurde erfasst. Schade, dass du nicht dabei sein kannst.

Details:
- Datum: {Datum}
- Ort: {Ort}

Vielleicht beim nächsten Mal!

Bis bald,
Dein Orga-Team
```

---

## 12. Individuelle Nachricht vom Admin

**Wann?** Wenn ein Admin gezielt eine eigene Nachricht an Angemeldete einer Veranstaltung schickt.
**Hinweis:** Betreff und Text werden vom Admin selbst geschrieben. Wenn die Option „Link zur Anmeldung anhängen“ aktiv ist, wird unten zusätzlich der Verwaltungslink eingefügt.
**Festival (spec 019):** Diese Vorlage funktioniert unverändert auch für Festival-Anmeldungen — verifiziert am Code (`send_custom_message` / `POST /api/admin/events/{event_id}/messages`): sie hängt nur an `event.name` und `registration.id`/`registration_token`/`email`, keine der Werte unterscheidet sich für `event_type=FESTIVAL`. Es gibt bewusst keine neue automatische Vorlage für die Vor-Festival-Erinnerung („Challenged & decided“ im Spec) — dieser manuelle Versandweg ist der vorgesehene. Die Festival-Sektion selbst bekommt ihre eigene Versandoberfläche dafür erst in **T211** (Wiederverwendung des `MessageComposer`s); bis dahin ist der Endpunkt zwar bereits nutzbar, aber ohne dedizierten UI-Einstieg in der Festival-Sektion.

**Begleitungen (spec 020):** Die Rundmail geht standardmäßig **auch an jede Begleitung, für die eine E-Mail-Adresse hinterlegt ist** (Häkchen „Begleitungen mit E-Mail mitschicken“, per Default an). Betreff und Text sind identisch; jede Empfängerin bekommt eine eigene Nachricht und damit einen eigenen Eintrag im Nachrichten-Log. **Unterschied:** Wo die Kontaktperson den `{Verwaltungslink}` bekommt, steht in der Begleitungs-Fassung der `{TicketLink}` — der Verwaltungslink darf niemals an eine Begleitung gehen, weil man damit die ganze Gruppe absagen könnte.

**Betreff:** wird vom Admin geschrieben.

**Aufbau der E-Mail:**
```
{Vom Admin geschriebener Text}

---
Anmeldung verwalten: {Verwaltungslink}

(Diese Nachricht bezieht sich auf die Veranstaltung "{Veranstaltung}".)
Dein Orga-Team
```

**Aufbau bei einer Begleitung:**
```
{Vom Admin geschriebener Text}

---
Dein Eintritts-Code: {TicketLink}

(Diese Nachricht bezieht sich auf die Veranstaltung "{Veranstaltung}".)
Dein Orga-Team
```

---

## 13. Fahrbericht an die Finanzabteilung

**Wann?** Nachdem ein Fahrbericht fertiggestellt wurde – geht an die hinterlegte Finanz-Adresse. Der vollständige Bericht liegt als PDF-Anhang bei.

**Betreff (erste Version):**
```
Schaluppe Fahrbericht – {Datum} – {Veranstaltung}
```

**Betreff (bei Aktualisierungen, Version 2 oder höher):**
```
Schaluppe Fahrbericht (Aktualisierung v{Version}) – {Datum} – {Veranstaltung}
```

**Text (erste Version):**
```
Hallo Finance-Team,

anbei der Fahrbericht der Schaluppe vom {Datum}.

{Buchungstext}

— Funke
```

**Text (bei Aktualisierungen):**
```
Hallo Finance-Team,

anbei die aktualisierte Version v{Version} des Fahrberichts der Schaluppe vom {Datum}.

{Buchungstext}

— Funke
```

**Anhang:** PDF-Datei mit dem Namen `fahrbericht-{Datum}-v{Version}.pdf` – enthält den vollständigen Bericht mit Kiosk-Einnahmen, Crew-Verköstigung, Ausgaben, Kassenabgleich, Buchungstext und Ship-Status.

---

## 14. Festival-Einladung (F1)

**Wann?** Wenn ein Admin für eine Gästelisten-Zeile den Einladungslink verschickt (`send-email`) oder ihn manuell kopiert.
**Hinweis:** Die Begrüßung nutzt immer das Label der Zeile („Moin {Name},") — die Mail geht an die Person, nach der die Zeile benannt ist (persönlicher Gast oder Kontingent-Verantwortliche:r). Die Varianten:
- Persönliche Einladung (`max_uses=1`): Absatz „Der Link ist persönlich für dich — bitte leite ihn nicht weiter." Bei `max_group_size>1` zusätzlich „Du kannst {eine Begleitung | bis zu N Begleitungen} mitbringen."
- Kontingent-Link (`max_uses>1`): stattdessen ein Kontingent-Absatz mit den konkreten Zahlen und dem Link zur öffentlichen Gästelisten-Seite (`{EinladungsLink}/liste`), auf der die verantwortliche Person sieht, wer sich schon angemeldet hat.

**Betreff:**
```
Du bist eingeladen: {Veranstaltung}
```

**Text (persönliche Einladung, `max_uses=1`):** — alle Fakten kommen aus dem Event ({Zeitraum} = `start_at`–`end_at`, z.B. „vom 14. bis 16. August 2026"; „Wo"/„Anmelden bis"/{Beschreibung}/{MitmachHinweis}/{KontaktAdresse} entfallen jeweils, wenn nicht gesetzt):
```
Moin {Name},

wir feiern {Zeitraum} — und du bist eingeladen!

- Was: {Veranstaltung}
- Wo: {Ort}
- Anmelden bis: {Anmeldeschluss}

{Beschreibung}

Hier meldest du dich an:
{EinladungsLink}

Bei der Anmeldung sagst du uns, an welchen Tagen du kommst und wen du mitbringst.

Der Link ist persönlich für dich — bitte leite ihn nicht weiter.

{MitmachHinweis}

Bei Fragen: {KontaktAdresse}

Bis bald,
Dein Orga-Team
```
(Bei `max_group_size>1` zusätzlich nach dem „persönlich"-Absatz: „Du kannst {eine Begleitung | bis zu N Begleitungen} mitbringen.")

**Text (Kontingent-Link, `max_uses>1`):** wie oben, aber statt „Der Link ist persönlich..." stehen diese Absätze:
```
Der Link ist dein Kontingent: Du kannst ihn weitergeben, er gilt für bis
zu {MaxNutzungen} Anmeldungen — jede Anmeldung kann bis zu {MaxGruppe}
Personen umfassen.

Wer sich über deinen Link schon angemeldet hat, siehst du hier:
{EinladungsLink}/liste
```
(Bei `max_group_size=1` lautet der Einschub „— eine Person pro Anmeldung".)

---

## 15. Festival: Anmeldung bestätigt (F2)

**Wann?** Direkt nachdem eine Festival-Anmeldung über den Einladungslink eingegangen ist.
**Hinweis:**
- Der Eintritts-Codes-Absatz erscheint erst ab P3 (Check-in/QR), in P1 immer ausgeblendet.
- Der `{MitmachHinweis}`-Absatz erscheint nur als eigener Absatz, wenn beim Event ein Mitmach-Hinweis hinterlegt ist (Ä16).

**Betreff:**
```
Deine Anmeldung: {Veranstaltung}
```

**Text (P1: ohne Eintritts-Codes-Absatz, ohne Mitmach-Hinweis):**
```
Moin {Name},

schön, dass du dabei bist! Deine Anmeldung für "{Veranstaltung}" steht.

Deine Anmeldung:
- Wann: {Zeitfenster}
- Schlafplatz: {Schlafplatz}
- Personen: {Personen} {Personenwort}

Deine Anmeldung verwalten (Zeiten ändern, Begleitungen, absagen):
{Verwaltungslink}

Ändern kannst du deine Angaben jederzeit über den Link oben.
Bei Fragen: {KontaktAdresse}

Bis bald,
Dein Orga-Team
```

**Ab P3, wenn Eintritts-Codes aktiv sind:** direkt nach dem `{Verwaltungslink}` folgt zusätzlich der Absatz „Auf der Verwaltungsseite findest du auch die Eintritts-Codes für deine ganze Gruppe — bitte leite sie an deine Begleitungen weiter."

**Wenn ein Mitmach-Hinweis hinterlegt ist:** danach folgt als eigener Absatz `{MitmachHinweis}` (z. B. inkl. Schichtplan-Link).

Ändern kannst du deine Angaben jederzeit über den Link oben — daher gibt es hierfür keine separate Freigabe-Mail (Ä14/Ä17).

---

## 16. Festival: Änderung bestätigt (F3)

**Wann?** Nachdem eine Festival-Anmeldung ihre Zeitfenster, Übernachtung oder Begleitungen über die Verwaltungsseite geändert hat.

**Betreff:**
```
Deine Änderung: {Veranstaltung}
```

**Text:**
```
Moin {Name},

alles klar, wir haben deine Änderung gespeichert.

Deine aktuelle Anmeldung:
- Wann: {Zeitfenster}
- Schlafplatz: {Schlafplatz}
- Personen: {Personen} {Personenwort}

Deine Anmeldung verwalten:
{Verwaltungslink}

Bis bald,
Dein Orga-Team
```

---

## 17. Festival: Absage bestätigt (F4)

**Wann?** Wenn eine Festival-Anmeldung storniert wird (Selbstauskunft oder Admin). Eine eigene Vorlage, damit der Verlosungs-Standardtext („...Platz an einen anderen Fisch...") niemals an einen Festival-Gast geht.

**Betreff:**
```
Deine Absage: {Veranstaltung}
```

**Text:**
```
Moin {Name},

schade, dass du nicht dabei bist — deine Anmeldung für "{Veranstaltung}"
ist storniert.

Falls du es dir anders überlegst, schreib uns: {KontaktAdresse}

Bis zum nächsten Mal,
Dein Orga-Team
```

---

## 18. Festival: Eintritts-Code für Begleitung (F5)

**Wann?** Bei der Anmeldung an jede Begleitung, für die eine E-Mail-Adresse eingetragen wurde. Bei einer Selbst-Änderung zusätzlich an jede Begleitung, deren Adresse **neu oder korrigiert** wurde **oder deren Name geändert wurde**.

Warum auch beim Umbenennen: der Name steckt mit im signierten Code, und der Einlass vergleicht ihn mit dem aktuellen Namen. Nach einer Umbenennung wird der QR im Postfach dieser Person als „stale_ticket" abgewiesen — sie braucht einen neuen. **Nicht** bei einer Änderung der Zeitfenster: die Tage im Code sind nur Information und werden am Einlass nie geprüft, der Code bleibt gültig.

Begleitungen **ohne** hinterlegte Adresse sind per Mail nicht erreichbar. Deren Codes holt die Kontaktperson auf ihrer Verwaltungsseite ab — die unterschreibt bei jedem Aufruf neu und zeigt immer gültige Codes für die ganze Gruppe. Umbenennungen über die **Admin**-Bearbeitung lösen bewusst keine Mail aus (dort korrigiert die Orga Daten nach Rücksprache); der QR dieser Person ist danach ebenfalls tot und muss über die Verwaltungsseite neu geholt werden.

**Enthält genau einen QR-Code** — den dieser Person (`cid:qr-{person_index}`). **Kein Verwaltungslink** in keiner der beiden Fassungen: mit diesem Token könnte man die ganze Gruppe ändern oder absagen. Keine Schlafplatz-Zeile — Zelt/Camper ist ein Gruppen-Wunsch, den die Kontaktperson abstimmt.

**Betreff:**
```
Dein Eintritts-Code: {Veranstaltung}
```

**Text:**
```
Moin {Name},

{Kontaktperson} hat dich für "{Veranstaltung}" angemeldet — schön, dass
du dabei bist!

Deine Anmeldung:
- Wann: {Zeitfenster}

Dein Eintritts-Code ist unten in dieser Mail eingebettet — am Einlass
zeigst du ihn einfach vor, ein Screenshot reicht.

Dein Code, immer aktuell:
{TicketLink}

{MitmachHinweis}

Wenn sich etwas ändert — andere Tage, oder du kannst doch nicht — melde
dich bei {Kontaktperson}: die Anmeldung für euch alle läuft dort
zusammen.

Bei Fragen: {KontaktAdresse}

Bis bald,
Dein Orga-Team
```

---

## 19. Festival: Absage-Hinweis an Begleitung (F6)

**Wann?** Wenn eine ganze Festival-Anmeldung storniert wird — also überall, wo auch F4 rausgeht (Selbstauskunft und Admin-Absage). Ohne diese Mail steht die Begleitung am Eingang mit einem Code, der nicht mehr funktioniert.

**Betreff:**
```
Abgesagt: {Veranstaltung}
```

**Text:**
```
Moin {Name},

{Kontaktperson} hat die Anmeldung für "{Veranstaltung}" storniert — für
dich damit auch. Dein Eintritts-Code funktioniert nicht mehr.

Wenn das ein Versehen war, melde dich bei {Kontaktperson} — oder schreib
uns: {KontaktAdresse}

Bis zum nächsten Mal,
Dein Orga-Team
```

---

## 20. Festival: Begleitung hat sich abgemeldet (F7)

**Wann?** Wenn eine Begleitung sich über ihre eigene Eintritts-Code-Seite selbst abmeldet (Spec 021). Die Mail geht an die **Kontaktperson**, nicht an die Begleitung: deren Planungszahlen haben sich ohne ihr Zutun geändert, und sie ist die Person, die die Orga darauf ansprechen wird.

**Betreff:**
```
Änderung bei deiner Anmeldung: {Veranstaltung}
```

**Text:**
```
Moin {Name},

{Begleitung} hat sich von deiner Anmeldung für "{Veranstaltung}"
abgemeldet — der Eintritts-Code dieser Person gilt nicht mehr.

Ihr seid jetzt {Personen} {Personenwort}.

Deine Anmeldung verwalten:
{Verwaltungslink}

Bei Fragen: {KontaktAdresse}

Bis bald,
Dein Orga-Team
```

---

## 21. Festival: Übernachtung zugesagt (F8)

**Wann?** Sobald eine Übernachtungs-Anfrage im Admin freigegeben wird („Darf übernachten“). Die Mail geht an die **angemeldete Person**, nie an Begleitungen — die Übernachtung gehört zur Gruppe, und Änderungen laufen über die Kontaktperson.

Jede Zusage wird nur **einmal** verschickt (festgehalten im Feld `overnight_notified_at`). Wird eine Zusage zurückgenommen, wird die Markierung gelöscht: eine erneute Zusage schickt wieder eine Mail. Für Zusagen aus der Zeit vor dieser Mail — und als Wiederholung nach einem Fehlversand — gibt es im Tab „Übernachtungs-Anfragen“ den Knopf **„Zusagen benachrichtigen“**.

**Betreff:**
```
Übernachtung zugesagt: {Veranstaltung}
```

**Text:**
```
Moin {Name},

gute Nachricht: ihr könnt auf dem Gelände übernachten. Wir haben euren
Schlafplatz fest eingeplant.

Eure Übernachtung:
- Schlafplatz: {Schlafplatz}
- Wann: {Zeitfenster}
- Personen: {Personen} {Personenwort}

Stellplätze sind knapp — wenn sich etwas ändert oder ihr sie nicht braucht,
sag uns bitte möglichst früh Bescheid:
{Verwaltungslink}

Bei Fragen: {KontaktAdresse}

Bis bald,
Dein Orga-Team
```

---

## 22. Festival: Übernachtung abgelehnt (F9)

**Wann?** Wenn eine Übernachtungs-Anfrage im Admin mit „Kann nicht übernachten“ abgelehnt wird. Die Mail geht an die **angemeldete Person**, nie an Begleitungen — genau wie die Zusage F8.

Der Zustand „abgelehnt“ und die Mail sind dasselbe: gespeichert wird der Zeitstempel `overnight_declined_at`, und der wird erst gesetzt, wenn die Mail in der Warteschlange liegt. Eine Anmeldung kann also nie als abgelehnt angezeigt werden, ohne dass die Person Bescheid bekommen hat. Zusage und Ablehnung schließen sich aus — wer zugesagt hat, muss die Zusage erst zurücknehmen.

Der **Übernachtungswunsch bleibt gespeichert**, damit die Zahlen auf der Headcount-Seite weiter zeigen, was angefragt war. Nimmt man die Ablehnung zurück („Ablehnung zurücknehmen“), geht **keine** Mail raus — die Anfrage ist dann wieder offen. Löscht die Person ihren Wunsch selbst, verschwindet die Ablehnung mit: ein neuer Wunsch ist eine neue Anfrage.

**Betreff:**
```
Übernachtung leider nicht möglich: {Veranstaltung}
```

**Text:**
```
Moin {Name},

leider können wir euch keinen Schlafplatz auf dem Gelände zusagen — die
Stellplätze sind vergeben.

Angefragt hattet ihr: {Schlafplatz}.

Ihr seid natürlich trotzdem dabei, euer Eintritts-Code gilt unverändert. Nur
übernachten geht dieses Mal nicht.

Deine Anmeldung verwalten:
{Verwaltungslink}

Bei Fragen: {KontaktAdresse}

Bis bald,
Dein Orga-Team
```
