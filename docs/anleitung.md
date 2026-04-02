# Funke – Anleitung für alle, die mitmachen

> **Funke** hilft euch dabei, Events mit begrenzten Plätzen fair und unkompliziert zu organisieren – von der Anmeldung über die Verlosung bis zur Boarding-Liste. Ohne Stress, ohne Chaos, ohne dass jemand leer ausgeht, der nicht leer ausgehen muss.

## Für Admins

Du organisierst Events und möchtest Funke nutzen? Hier erfährst du, wie du alles im Griff behältst.

### Einloggen

Der Admin-Bereich ist über Auth0 geschützt. Nach dem Login siehst du oben rechts deine E-Mail-Adresse und kannst loslegen.

Es gibt drei Rollen:

| Rolle | Was darf ich? |
|-------|--------------|
| **Owner** | Alles – inklusive andere Admins verwalten |
| **Admin** | Events erstellen, bearbeiten, Anmeldungen verwalten, E-Mails senden, Check-in |
| **Viewer** | Nur lesen – Events und Anmeldungen ansehen |

> 📸 **Screenshot einfügen:** Admin-Dashboard / Event-Übersicht nach dem Login

### Event erstellen

Über die Event-Übersicht legst du ein neues Event an. Im Formular gibst du an:

| Feld | Pflicht? | Hinweis |
|------|----------|---------|
| **Name** | Ja | Max. 200 Zeichen |
| **Beschreibung** | Nein | Max. 2000 Zeichen – worum geht's? |
| **Ort** | Nein | Max. 500 Zeichen |
| **Datum & Uhrzeit** | Ja | Muss in der Zukunft liegen |
| **Kapazität** | Ja | 1–500 Plätze (Standard: 100) |
| **Anmeldeschluss** | Ja | Muss vor dem Eventdatum liegen |
| **Erinnerungen** | Optional | Standard: 7, 3 und 1 Tag vorher |
| **Automatisch nachrücken** | Optional | Warteliste rückt bei Absagen automatisch nach |

Das Event startet im Status **Entwurf** – es ist also noch nicht sichtbar für die Außenwelt.

> 📸 **Screenshot einfügen:** Event-Erstellungsformular / Modal mit allen Feldern

### Event veröffentlichen

Wenn alles passt, veröffentlichst du das Event mit einem Klick auf **„Veröffentlichen"**. Das Event wechselt von **Entwurf** zu **Offen** und ist ab jetzt über den öffentlichen Anmeldelink erreichbar.

> **Tipp:** Den Anmeldelink findest du in den Event-Details. Einfach kopieren und an eure Community verteilen.

> 📸 **Screenshot einfügen:** Event-Detailansicht mit Status "Offen" und sichtbarem Anmeldelink

### Anmeldungen im Blick behalten

In der Registrierungstabelle siehst du alle Anmeldungen auf einen Blick:

- **Name, E-Mail, Telefon, Gruppengröße** – die Basics
- **Status** – farblich markiert, damit du sofort siehst, wer wo steht
- **Anmeldedatum und Bestätigungsdatum**
- **Gruppenmitglieder** – aufklappbar, direkt editierbar
- **Promoted-Status** – ob jemand bei der Verlosung bevorzugt wird

Du kannst nach Status filtern, nach Name oder E-Mail suchen und nach Spalten sortieren.

> 📸 **Screenshot einfügen:** Registrierungstabelle mit verschiedenen Status-Badges, Suchfeld und Filtern

**Aktionen pro Anmeldung:**

- Details ansehen
- Gruppenmitglieder bearbeiten
- Von der Warteliste hochstufen (manuell)
- Individuelle Nachricht senden
- Einchecken
- Löschen

> 📸 **Screenshot einfügen:** Registrierungs-Detailmodal mit Kommunikationsverlauf

### Personen bevorzugen (Promoted)

Manchmal gibt es gute Gründe, bestimmten Personen einen Platz zu garantieren – zum Beispiel Helfer:innen oder Ehrengäste. Dafür gibt es den **Promoted-Status**.

Solange das Event **offen** ist oder die **Registrierung geschlossen** wurde (aber vor der Verlosung), kannst du bei einzelnen Anmeldungen den Promoted-Schalter aktivieren. Diese Personen bekommen bei der Verlosung **garantiert einen Platz**.

> **Achtung:** Wenn die Summe der Promoted-Plätze die Kapazität übersteigt, zeigt Funke eine Warnung an – und die Verlosung kann nicht durchgeführt werden.

Nach der Verlosung wird der Promoted-Status als Badge angezeigt, ist aber nicht mehr änderbar.

> 📸 **Screenshot einfügen:** Registrierungstabelle mit Promoted-Toggle und Tooltip "garantierte Verlosung"

### Die Verlosung

Das Herzstück von Funke. Wenn die Anmeldephase vorbei ist und es mehr Anmeldungen als Plätze gibt, entscheidet eine faire Verlosung, wer dabei ist.

**So geht's:**

1. **Anmeldung schließen** – Wechselt den Event-Status und verhindert neue Anmeldungen
2. **Verlosungsseite öffnen** – Dort siehst du eine Übersicht: Kapazität, Anmeldungen, Promoted-Plätze
3. **„Verlosung durchführen"** klicken – Funke mischt alle Anmeldungen zufällig durch
4. **Ergebnis prüfen** – Du siehst, wer gewonnen hat und wer auf der Warteliste landet
5. **Nicht zufrieden?** – Mit **„Neu mischen"** wird nochmal gewürfelt (neuer Zufalls-Seed)
6. **„Finalisieren & Benachrichtigen"** – Ergebnis wird übernommen, alle bekommen eine E-Mail

**So funktioniert die Verlosung im Detail:**

- Promoted-Personen bekommen immer einen Platz
- Gruppen werden als Ganzes berücksichtigt – entweder alle oder niemand
- Die Reihenfolge ist kryptografisch zufällig und reproduzierbar (über den Seed nachvollziehbar)
- Gewinner:innen bekommen den Status **CONFIRMED** und eine E-Mail zum Bestätigen
- Alle anderen bekommen den Status **WAITLISTED** und eine Info-E-Mail

> 📸 **Screenshot einfügen:** Verlosungsseite mit Event-Zusammenfassung (Kapazität, Anmeldungen, Promoted)

> 📸 **Screenshot einfügen:** Verlosungsergebnis – Gewinner-Liste und Warteliste mit Gruppengrößen

### Unbestätigte Anmeldungen verwerfen

Nach der Verlosung müssen Gewinner:innen ihren Platz bestätigen. Wenn jemand das nicht tut, kannst du unbestätigte Anmeldungen verwerfen – damit die Plätze für die Warteliste frei werden.

Im Dialog siehst du alle unbestätigten Anmeldungen mit Checkboxen. Du kannst einzelne auswählen oder alle markieren. Dazu gibt's ein Textfeld mit einer vorformulierten, freundlichen Nachricht, die du anpassen kannst.

Nach dem Verwerfen rücken automatisch Personen von der Warteliste nach.

> 📸 **Screenshot einfügen:** Modal "Unbestätigte Anmeldungen verwerfen" – Checkboxen, Nachrichtenfeld, roter Button

### Warteliste und Nachrücken

Funke kümmert sich darum, dass frei gewordene Plätze nicht verloren gehen:

**Automatisch:**

- Wenn jemand komplett absagt: sofortiges Nachrücken (älteste Anmeldung auf der Warteliste zuerst)
- Wenn jemand die Gruppengröße verkleinert: Nachrücken gebündelt um 12:00 Uhr mittags

**Manuell:**

- Du kannst auch selbst Personen von der Warteliste hochstufen
- Dabei wählst du, ob die Person direkt **teilnimmt** oder erst noch **bestätigen** muss
- Funke prüft automatisch, ob genug Plätze frei sind

> 📸 **Screenshot einfügen:** Manuelle Promotion von der Warteliste – Statusauswahl und Kapazitätsprüfung

### Boarding-Liste erstellen

Kurz vor dem Event kannst du eine **Boarding-Liste als PDF** exportieren – den sogenannten **Boardingzettel**. Er enthält alle Personen mit Status **Teilnehmend** in einer übersichtlichen Tabelle:

| # | Name | Unterschrift |
|---|------|-------------|
| 1 | Max Mustermann | _____________ |
| 2 | Erika Beispiel | _____________ |

Im Header stehen Event-Name, Datum, Ort und die Gesamtzahl der Mitfahrenden. Perfekt zum Ausdrucken und Abhaken am Einlass.

> 📸 **Screenshot einfügen:** Beispiel des PDF-Boardingzettels (oder der Export-Button in der Event-Ansicht)

### Event abschließen oder absagen

**Abschließen:** Wenn das Event vorbei ist, kannst du es auf **Abgeschlossen** setzen. Damit ist klar: Dieses Event ist gelaufen.

**Absagen:** Falls ein Event doch nicht stattfinden kann, setzt du es auf **Abgesagt**. Alle aktiven Teilnehmenden werden automatisch per E-Mail informiert. Ein abgesagtes Event kann anschließend gelöscht werden.

**Klonen:** Du möchtest ein ähnliches Event nochmal veranstalten? Mit der Klonen-Funktion erstellst du eine Kopie mit neuem Datum – alle Einstellungen werden übernommen.

> 📸 **Screenshot einfügen:** Event-Aktionen (Abschließen, Absagen, Klonen) in der Event-Detailansicht

---

## Für Teilnehmende

Du hast einen Link zu einem Event bekommen und möchtest dich anmelden? Wunderbar – hier erfährst du, wie das geht und was danach passiert.

### Anmelden

Über den Anmeldelink landest du direkt auf der Event-Seite. Dort siehst du alle wichtigen Infos: **Name, Beschreibung, Datum, Ort, verfügbare Plätze und Anmeldeschluss.**

Um dich anzumelden, füllst du einfach das Formular aus:

| Feld | Pflicht? | Hinweis |
|------|----------|---------|
| **Name** | Ja | Dein vollständiger Name |
| **E-Mail** | Ja | Pro Event nur eine Anmeldung je E-Mail-Adresse |
| **Telefon** | Nein | Falls wir dich kurzfristig erreichen müssen |
| **Gruppengröße** | Ja | Wie viele Personen (inkl. dir) – maximal 10 |
| **Anmerkungen** | Nein | Platz für Besonderheiten, max. 500 Zeichen |

Abschicken, fertig. Du bekommst direkt eine Bestätigungsmail.

> **Gut zu wissen:** Wenn der Anmeldeschluss schon vorbei ist, kannst du dich trotzdem anmelden – du landest dann allerdings direkt auf der Warteliste.

> 📸 **Screenshot einfügen:** Öffentliche Anmeldeseite mit ausgefülltem Formular

### Was passiert nach der Anmeldung?

Erstmal: Durchatmen. Deine Anmeldung ist eingegangen und du bekommst eine E-Mail mit einem persönlichen Link. Über diesen Link kannst du jederzeit den **Status deiner Anmeldung** einsehen und Änderungen vornehmen.

Dein Status ist zunächst **„Anmeldung eingegangen"** – das bedeutet, die Verlosung hat noch nicht stattgefunden. Sobald es soweit ist, wirst du per E-Mail informiert.

> 📸 **Screenshot einfügen:** Verwaltungsseite im Status REGISTERED (grauer Banner "Anmeldung eingegangen")

### Du hast einen Platz bekommen

Herzlichen Glückwunsch! Du bekommst eine E-Mail mit der frohen Botschaft und einem Link zu deiner Verwaltungsseite. Dort wartet eine wichtige Aufgabe auf dich:

**Du musst deinen Platz bestätigen** – und dabei die Namen aller Mitfahrenden eintragen.

- Dein eigener Name ist schon vorausgefüllt (du kannst ihn aber ändern)
- Für jede weitere Person in deiner Gruppe gibt es ein Namensfeld
- Alle Felder müssen ausgefüllt sein, bevor du bestätigen kannst
- Du kannst die Gruppengröße verkleinern, indem du Felder entfernst – frei gewordene Plätze gehen an die Warteliste

Erst wenn du bestätigt hast, bist du wirklich dabei.

> 📸 **Screenshot einfügen:** Verwaltungsseite im Status CONFIRMED – grüner Banner "Du hast einen Platz bekommen!", Namensfelder für Gruppenmitglieder sichtbar

Nach der Bestätigung siehst du den Status **„Du bist dabei!"** und kannst:

- **Namen ändern** – Tippfehler? Jemand anderes kommt mit? Einfach anpassen und speichern.
- **Gruppenmitglieder entfernen** – Frei gewordene Plätze rücken automatisch nach.
- **Absagen** – Falls doch etwas dazwischen kommt (dazu gleich mehr).

> **Wichtig:** Deinen eigenen Namen kannst du nicht einzeln entfernen. Wenn du selbst nicht mehr dabei sein willst, musst du die gesamte Anmeldung stornieren.

> 📸 **Screenshot einfügen:** Verwaltungsseite im Status PARTICIPATING – grüner Banner "Du bist dabei!", editierbare Namensliste

### Du stehst auf der Warteliste

Nicht jede Anmeldung kann berücksichtigt werden – das kennt ihr. Wenn die Verlosung nicht zu deinen Gunsten ausgefallen ist, landest du auf der Warteliste. Dein Status zeigt dann **„Du stehst auf der Warteliste"**.

Das heißt aber nicht, dass es vorbei ist: Wenn jemand absagt oder die Gruppe verkleinert, rückst du automatisch nach und bekommst eine E-Mail.

> 📸 **Screenshot einfügen:** Verwaltungsseite im Status WAITLISTED – grauer Banner "Du stehst auf der Warteliste"

### Absagen und Änderungen

Das Leben ist manchmal unberechenbar. Kein Problem – auf deiner Verwaltungsseite findest du jederzeit einen **Absage-Button**. Nach der Stornierung bekommst du eine Bestätigungsmail, und dein Platz wird für jemanden auf der Warteliste frei.

> **Bitte beachten:** Eine Stornierung ist endgültig. Du kannst dich danach nicht erneut über denselben Link anmelden.

> 📸 **Screenshot einfügen:** Verwaltungsseite im Status CANCELLED – roter Banner "Deine Anmeldung wurde storniert"

### Am Tag des Events

Wenn du eingecheckt wirst, wechselt dein Status auf **„Du bist eingecheckt. Viel Spaß!"** – und dann kann's losgehen.

> 📸 **Screenshot einfügen:** Verwaltungsseite im Status CHECKED_IN – grüner Banner mit Gruppenmitgliederliste (read-only)

---

## Der Lebenszyklus eines Events

Jedes Event durchläuft verschiedene Phasen. Hier der Überblick:

**Entwurf → Offen → Anmeldung geschlossen → Verlosung ausstehend → Bestätigt → Abgeschlossen**

Jeder Status kann jederzeit zu **Abgesagt** wechseln.

| Status | Was passiert? |
|--------|--------------|
| **Entwurf** | Event wird vorbereitet, noch nicht sichtbar |
| **Offen** | Anmeldungen laufen, Link ist aktiv |
| **Anmeldung geschlossen** | Keine neuen Anmeldungen mehr möglich |
| **Verlosung ausstehend** | Bereit für die Verlosung |
| **Bestätigt** | Verlosung gelaufen, Teilnehmende bestätigen ihre Plätze |
| **Abgeschlossen** | Event ist vorbei |
| **Abgesagt** | Event findet nicht statt, alle werden informiert |

---

## E-Mails, die Funke verschickt

Funke kommuniziert automatisch per E-Mail – damit niemand etwas verpasst und ihr euch auf die Organisation konzentrieren könnt.

| E-Mail | Wann? | An wen? |
|--------|-------|---------|
| **Anmeldebestätigung** | Sofort nach Anmeldung | Alle Angemeldeten |
| **Verlosungsergebnis: Gewonnen** | Nach Finalisierung | Gewinner:innen |
| **Verlosungsergebnis: Warteliste** | Nach Finalisierung | Alle auf der Warteliste |
| **Nachrücken von der Warteliste** | Bei frei gewordenen Plätzen | Nachgerückte Person |
| **Stornierungsbestätigung** | Nach Absage | Abgesagte Person |
| **Event abgesagt** | Bei Event-Absage | Alle aktiven Teilnehmenden |
| **Erinnerung** | Konfigurierbar (z.B. 7, 3, 1 Tag vorher) | Alle Teilnehmenden |

Alle E-Mails sind auf Deutsch und enthalten einen Link zur persönlichen Verwaltungsseite.

---

## Häufige Fragen

### Brauche ich einen Account, um mich anzumelden?
Nein. Die Anmeldung läuft komplett ohne Login – du brauchst nur den Anmeldelink und eine E-Mail-Adresse.

### Kann ich mich mehrfach anmelden?
Nein, pro Event ist nur eine Anmeldung je E-Mail-Adresse möglich.

### Ich habe meine Bestätigungsmail nicht bekommen – was tun?
Schau in deinen Spam-Ordner. Falls du dort auch nichts findest, melde dich bei den Organisator:innen.

### Kann ich meine Gruppengröße nachträglich erhöhen?
Nein, du kannst die Gruppe nur verkleinern. Wenn mehr Leute mitkommen wollen, müssen sie sich separat anmelden.

### Was passiert, wenn ich meinen Platz nicht bestätige?
Die Organisator:innen können unbestätigte Anmeldungen nach einer angemessenen Frist verwerfen. Dein Platz geht dann an jemanden auf der Warteliste.

### Wie fair ist die Verlosung?
Die Verlosung nutzt einen kryptografisch sicheren Zufallsgenerator. Der Seed wird gespeichert, damit das Ergebnis jederzeit nachvollziehbar ist. Gruppen werden dabei als Ganzes berücksichtigt – es wird also niemand von seinen Leuten getrennt.

### Kann ich mich nach einer Stornierung erneut anmelden?
Nicht über denselben Link. Wende dich an die Organisator:innen, falls du dich neu anmelden möchtest.

---

> **Bei Fragen, einfach melden.** Funke ist dafür da, dass ihr euch auf das konzentrieren könnt, was zählt: gemeinsam eine gute Zeit haben.
