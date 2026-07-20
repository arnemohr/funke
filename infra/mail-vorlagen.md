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
| `{Schlafplatz}` | Festival: Übernachtungswunsch – „Nein“ / „Zelt — angefragt“ / „Zelt — zugesagt“ / „Camper — angefragt“ / „Camper — zugesagt“. Die Zusage wird telefonisch abgestimmt, es gibt keine automatische Freigabe-Mail |
| `{EinladungsLink}` | Festival: persönlicher oder Kontingent-Link zur Anmeldung |
| `{KontaktAdresse}` | Festival: die hinterlegte Kontaktadresse für Rückfragen |
| `{MitmachHinweis}` | Festival: der konfigurierte Mitmach-Hinweis inkl. Schichtplan-Link (nur wenn hinterlegt) |

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

**Betreff:** wird vom Admin geschrieben.

**Aufbau der E-Mail:**
```
{Vom Admin geschriebener Text}

---
Anmeldung verwalten: {Verwaltungslink}

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
