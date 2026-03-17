# Funke Testanleitung

## Was ist Funke?

Funke ist ein Anmeldesystem für Veranstaltungen. Es hilft dabei:

- **Veranstaltungen anzulegen** (Bootstouren, Workshops, whatever)
- **Anmeldungen zu sammeln** (Online-Anmeldungen ohne Chaos)
- **Bei Überbuchung fair zu entscheiden** (Losverfahren statt First-Come-First-Serve)
- **Automatisch zu kommunizieren** (E-Mails gehen raus, ohne dass du was tun musst)

---

## Ablauf einer Veranstaltung

```
Event erstellen (Draft)
    ↓
Veröffentlichen (Anmeldung offen)
    ↓
Anmeldungen laufen ein
    ↓
Anmeldeschluss
    ↓
Verlosung (falls nötig)
    ↓
Bestätigungsmail vor dem Event
    ↓
Teilnehmer:innen bestätigen/sagen ab
    ↓
Event findet statt
```

---

## 1. Admin-Login

**URL:** `https://funke.mobilemachenschaften.de`

1. Klick auf "Anmelden" (oben rechts)
2. Login mit deinen Zugangsdaten
3. Du landest in der Event-Übersicht

**Check:**
- [ ] Event-Übersicht wird angezeigt
- [ ] Deine E-Mail/Name steht irgendwo oben

---

## 2. Event erstellen

1. **"Neue Veranstaltung"** klicken
2. **Formular ausfüllen:**

   | Feld | Beispiel |
   |------|----------|
   | Name | Schaluppen-Tour Sommer |
   | Ort | Hamburger Hafen |
   | Beschreibung | Gemeinsame Bootstour mit Snacks |
   | Datum & Uhrzeit | 15.01.2025, 14:00 |
   | Plätze | 12 |
   | Anmeldeschluss | 10.01.2025, 18:00 |
   | Erinnerungen | 7, 3, 1 (Tage vor dem Event) |

3. **"Erstellen"** klicken
4. Event erscheint mit Status **"DRAFT"**

**Check:**
- [ ] Formular lässt sich problemlos ausfüllen
- [ ] Event taucht in der Liste auf
- [ ] Status ist "DRAFT"

---

## 3. Event veröffentlichen

Im Draft-Modus ist das Event noch nicht sichtbar für Anmeldungen.

1. **Event in der Liste anklicken**
2. **"Veröffentlichen"** klicken
3. Status wechselt zu **"OPEN"**
4. Button **"Link kopieren"** erscheint

### Anmeldelink

Der Link sieht ungefähr so aus:
```
https://funke.mobilemachenschaften.de/register/abc123xyz...
```

Den kannst du dann teilen (WhatsApp, E-Mail, Insta, whatever).

**Check:**
- [ ] Status wechselt von "DRAFT" zu "OPEN"
- [ ] "Link kopieren" Button ist da
- [ ] Link funktioniert (test in neuem Tab)

---

## 4. Als Teilnehmer:in anmelden

Jetzt wechselst du die Perspektive und testest die Anmeldung.

**Tipp:** Inkognito-Modus oder neue E-Mail-Adresse nutzen, damit du nicht mit deinem Admin-Account kollidierst.

1. **Anmeldelink öffnen**
2. **Event-Details checken** (Name, Datum, Ort, Plätze, Deadline)
3. **Formular ausfüllen:**

   | Feld | Pflicht? |
   |------|----------|
   | Name | Ja |
   | E-Mail | Ja |
   | Telefon | Nein |
   | Gruppengröße | Ja (1-10) |
   | Anmerkungen | Nein |

4. **"Anmelden"** klicken
5. Bestätigungsseite erscheint: "Du stehst auf der Liste!"

**Check:**
- [ ] Event-Details werden korrekt angezeigt
- [ ] Formular funktioniert
- [ ] Bestätigungsseite erscheint
- [ ] Bestätigungs-E-Mail kommt an

---

## 5. Anmeldungen im Admin-Bereich sehen

1. **Zurück zum Admin-Bereich**
2. **Event anklicken**
3. **Anmeldungen checken:**

   | Spalte | Was steht da? |
   |--------|---------------|
   | Name | Wer hat sich angemeldet |
   | E-Mail | Kontakt (klickbar) |
   | Personen | Gruppengröße |
   | Status | REGISTERED, CONFIRMED, PARTICIPATING, etc. |
   | Angemeldet am | Timestamp |

### Status-Übersicht

| Status | Bedeutung |
|--------|-----------|
| REGISTERED | Angemeldet, wartet auf Verlosung |
| CONFIRMED | Hat Platz, muss noch bestätigen |
| PARTICIPATING | Hat zugesagt |
| WAITLISTED | Auf der Warteliste |
| CANCELLED | Hat abgesagt |

**Check:**
- [ ] Deine Test-Anmeldung ist in der Liste
- [ ] Zahlen passen (z.B. "5 Pers. (2 Anm.) · 3 Best. / 12")
- [ ] Status wird korrekt angezeigt

---

## 6. Anmeldung schließen

Nach dem Anmeldeschluss werden keine neuen Anmeldungen mehr akzeptiert.

1. **Event anklicken**
2. **"Anmeldung schließen"** klicken
3. Status wechselt zu **"REGISTRATION_CLOSED"**

**Check:**
- [ ] Status wechselt korrekt
- [ ] Anmeldelink zeigt "Anmeldung geschlossen"
- [ ] Neue Anmeldungen gehen nicht mehr

---

## 7. Verlosung durchführen

Falls mehr Anmeldungen als Plätze da sind, kommt die Verlosung.

**Voraussetzungen:**
- Anmeldungen > Kapazität
- Anmeldung ist geschlossen

### Ablauf

1. **"Verlosung"** klicken
2. **Übersicht checken:**
   - Anzahl Anmeldungen
   - Verfügbare Plätze
   - Überbuchungsquote
3. **"Verlosung starten"** klicken
4. **System lost aus:**
   - Gewinner:innen → Status "CONFIRMED"
   - Alle anderen → Status "WAITLISTED"
5. **E-Mails gehen automatisch raus**

**Check:**
- [ ] Verlosung lässt sich starten
- [ ] Ergebnisse werden angezeigt
- [ ] Status ändern sich korrekt
- [ ] E-Mails kommen an (Check dein Postfach)

---

## 8. Teilnahme bestätigen (als Teilnehmer:in)

Ein paar Tage vor dem Event bekommen alle mit Status "CONFIRMED" eine Bestätigungsmail.

**Mail enthält:**
- Event-Erinnerung
- Zwei Links: "Ja, ich bin dabei!" und "Nein, ich kann nicht"

### Test: Zusagen

1. **E-Mail öffnen** (oder Debug-Bereich nutzen)
2. **"Ja, ich bin dabei!"** klicken
3. Bestätigungsseite: "Du bist dabei!"
4. Status wechselt zu **"PARTICIPATING"**

### Test: Absagen

1. **"Nein, ich kann nicht"** klicken
2. Absageseite: "Schade, dass du nicht dabei sein kannst"
3. Status wechselt zu **"CANCELLED"**
4. **Falls jemand auf der Warteliste steht:** Diese Person rückt automatisch nach und bekommt eine E-Mail

**Check:**
- [ ] Bestätigungslink funktioniert
- [ ] "Ja" → PARTICIPATING
- [ ] "Nein" → CANCELLED
- [ ] Wartelisten-Nachrücken funktioniert

---

## 9. Anmeldung stornieren (als Teilnehmer:in)

Leute können ihre Anmeldung jederzeit selbst stornieren.

1. **Ursprüngliche Bestätigungs-E-Mail öffnen** (die nach der Anmeldung kam)
2. **Stornierungslink klicken**
3. Anmeldedaten werden angezeigt + Warnhinweis
4. **"Anmeldung stornieren"** klicken
5. Bestätigung: "Deine Anmeldung wurde storniert"

**Check:**
- [ ] Stornierungslink funktioniert
- [ ] Daten werden korrekt angezeigt
- [ ] Status ändert sich
- [ ] Bei bestätigten Plätzen rückt Warteliste nach

---

## 10. Event absagen (als Admin)

Falls ein Event nicht stattfinden kann:

1. **Event öffnen**
2. **"Absagen"** klicken
3. **Sicherheitsabfrage bestätigen** ("absagen" eingeben)
4. Alle Teilnehmer:innen werden per E-Mail informiert
5. Status wechselt zu **"CANCELLED"**

**Check:**
- [ ] Sicherheitsabfrage erscheint
- [ ] Status ändert sich
- [ ] Alle bekommen eine E-Mail
- [ ] Event kann gelöscht werden

---

## Debug-Bereich

Es gibt einen Debug-Bereich zum schnellen Testen.

**Wo?** Klick oben auf "Debug"

**Was geht da?**
- Registrierungslinks direkt öffnen
- Stornierungslinks klicken
- Bestätigungslinks testen (Ja/Nein)

**Pro-Tipp:** Wenn du einen Link in einem neuen Tab öffnest und zurückkommst, aktualisiert sich die Seite automatisch.

---

## Vollständiger Test – Checkliste

### Grundfunktionen
- [ ] Admin-Login
- [ ] Event erstellen
- [ ] Event veröffentlichen
- [ ] Anmeldelink teilen

### Anmeldeprozess
- [ ] Formular ausfüllen
- [ ] Bestätigungsseite
- [ ] Bestätigungs-E-Mail
- [ ] Anmeldung im Admin-Bereich sichtbar

### Verlosung
- [ ] Anmeldung schließen
- [ ] Verlosung durchführen
- [ ] Gewinner:innen/Warteliste korrekt
- [ ] E-Mails werden versendet

### Bestätigungsflow
- [ ] Bestätigungsmail
- [ ] "Ja"-Link → PARTICIPATING
- [ ] "Nein"-Link → CANCELLED
- [ ] Warteliste rückt nach

### Stornierung
- [ ] Stornierungslink funktioniert
- [ ] Anmeldung wird storniert
- [ ] Warteliste rückt nach

### Absage
- [ ] Event kann abgesagt werden
- [ ] Alle werden informiert

---

## FAQ

### Warum kann ich keine Verlosung machen?
Verlosung ist nur möglich, wenn:
1. Anmeldung geschlossen wurde
2. Mehr Anmeldungen als Plätze da sind

### Warum bekomme ich keine E-Mails?
- Check deinen Spam-Ordner
- E-Mail-Adresse korrekt?
- Eventuell werden im Testmodus keine echten E-Mails versendet

### Kann ich Anmeldungen manuell ändern?
Aktuell nicht. Teilnehmer:innen können nur selbst stornieren, Admins können Events absagen.

### Was tun bei einem Fehler?
- Screenshot machen
- Notieren, was du gerade gemacht hast
- Fehler mit diesen Infos melden

---

## Feedback geben

**Format:**
1. Was hast du gemacht?
2. Was ist passiert?
3. Was hättest du erwartet?
4. Screenshots (optional)

**Beispiel:**
> "Ich hab auf 'Anmelden' geklickt, aber es ist nichts passiert. Erwartung: Bestätigungsseite. Browser: Safari auf iPhone"

---

## Glossar

| Begriff | Erklärung |
|---------|-----------|
| **Admin** | Verwalter:in der Events |
| **Kapazität** | Max. Anzahl Plätze |
| **Verlosung/Lottery** | Zufallsauswahl bei Überbuchung |
| **Warteliste** | Nachrücker-Pool |
| **Status** | Stand einer Anmeldung |
| **Token** | Geheimer Code in Links (für Identifikation) |
