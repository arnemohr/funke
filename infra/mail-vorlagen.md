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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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

ein Fisch ist abgesprungen und du rückst nach! Du hast jetzt einen Platz an Bord der Schaluppe für "{Veranstaltung}".

- Datum: {Datum}
- Ort: {Ort}
- Personen: {Personen} {Personenwort}

Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:

{Verwaltungslink}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Wir freuen uns auf dich!

Liebste Grüße,
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
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
Deine Crew von der Schaluppe
```

---

## 12. Individuelle Nachricht vom Admin

**Wann?** Wenn ein Admin gezielt eine eigene Nachricht an Angemeldete einer Veranstaltung schickt.
**Hinweis:** Betreff und Text werden vom Admin selbst geschrieben. Wenn die Option „Link zur Anmeldung anhängen“ aktiv ist, wird unten zusätzlich der Verwaltungslink eingefügt.

**Betreff:** wird vom Admin geschrieben.

**Aufbau der E-Mail:**
```
{Vom Admin geschriebener Text}

---
Anmeldung verwalten: {Verwaltungslink}

(Diese Nachricht bezieht sich auf die Veranstaltung "{Veranstaltung}".)
Deine Crew von der Schaluppe
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
