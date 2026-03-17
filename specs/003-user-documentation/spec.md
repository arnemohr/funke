# Spezifikation: Benutzer-Dokumentation für Tester:innen

## Übersicht

Erstellung einer deutschsprachigen Testanleitung für nicht-technische Anwender:innen (Sozialarbeiter:innen, Kreative), die das Funke-System testen möchten.

---

## Zielgruppe

| Merkmal | Beschreibung |
|---------|--------------|
| **Technische Kenntnisse** | Keine bis minimal |
| **Beruflicher Hintergrund** | Sozialarbeit, Kreativbereich, Ehrenamt |
| **Geräte** | Smartphones, Tablets, Laptops |
| **Erwartung** | Schritt-für-Schritt-Anleitungen, keine Fachbegriffe |

---

## Anforderungen

### Inhaltliche Anforderungen

1. **Vollständige Abdeckung aller Benutzerflows**
   - Admin-Login und Navigation
   - Veranstaltung erstellen und veröffentlichen
   - Anmeldeprozess aus Teilnehmer:innen-Sicht
   - Verlosung durchführen
   - Bestätigungsflow (Ja/Nein)
   - Stornierung
   - Veranstaltung absagen

2. **Verständliche Sprache**
   - Einfaches Deutsch (B1-Niveau)
   - Keine englischen Fachbegriffe ohne Erklärung
   - Kurze Sätze
   - Aktive Formulierungen

3. **Visuelle Strukturierung**
   - Nummerierte Schritte
   - Tabellen für Übersichten
   - Checklisten zum Abhaken
   - Klare Überschriften-Hierarchie

4. **Testunterstützung**
   - Checklisten für jeden Bereich
   - Erwartete Ergebnisse beschrieben
   - Hinweise auf häufige Fehler
   - Feedback-Anleitung

### Formale Anforderungen

| Aspekt | Anforderung |
|--------|-------------|
| Sprache | Deutsch |
| Format | Markdown (.md) |
| Speicherort | `docs/TESTANLEITUNG.md` |
| Länge | Ca. 800-1200 Zeilen |
| Gliederung | 10 Hauptteile + Anhänge |

---

## Dokumentstruktur

```
1. Einleitung
   - Was ist Funke?
   - Übersicht: Der Ablauf einer Veranstaltung

2. Teil 1: Als Admin einloggen
3. Teil 2: Eine Veranstaltung erstellen
4. Teil 3: Veranstaltung veröffentlichen
5. Teil 4: Als Teilnehmer:in anmelden
6. Teil 5: Anmeldungen im Admin-Bereich sehen
7. Teil 6: Anmeldung schließen
8. Teil 7: Verlosung durchführen
9. Teil 8: Teilnahme bestätigen
10. Teil 9: Anmeldung stornieren
11. Teil 10: Veranstaltung absagen
12. Debug-Bereich
13. Vollständige Checkliste
14. Häufige Fragen (FAQ)
15. Feedback geben
16. Glossar
```

---

## Stilrichtlinien

### Anrede
- Informelles "Du"
- Geschlechtergerechte Sprache mit Doppelpunkt (Teilnehmer:innen)

### Beispiel für Schreibstil

**Gut:**
> Klicke auf "Neue Veranstaltung". Ein Formular erscheint. Fülle alle Felder mit einem Sternchen (*) aus.

**Schlecht:**
> Um eine neue Veranstaltung zu erstellen, muss der Benutzer auf den entsprechenden Button klicken, woraufhin ein modales Dialogfenster mit einem Formular erscheint.

### Technische Begriffe

| Vermeiden | Stattdessen |
|-----------|-------------|
| Modal | Fenster, Dialogfenster |
| Token | Link, geheimer Code |
| API | - (nicht erwähnen) |
| Frontend/Backend | - (nicht erwähnen) |
| Deployment | - (nicht erwähnen) |
| Endpoint | Link, Adresse |

---

## Status-Erklärungen

Die Dokumentation muss alle Status verständlich erklären:

| Status | Deutsche Erklärung | Farbe |
|--------|-------------------|-------|
| DRAFT | Entwurf – noch nicht veröffentlicht | Grau |
| OPEN | Anmeldung offen | Grün |
| REGISTRATION_CLOSED | Anmeldung geschlossen | Gelb |
| LOTTERY_PENDING | Verlosung steht aus | Lila |
| CONFIRMED | Hat Platz, muss bestätigen | Gelb |
| CANCELLED | Abgesagt | Rot |
| COMPLETED | Abgeschlossen | Blau |

| Anmelde-Status | Deutsche Erklärung |
|----------------|-------------------|
| REGISTERED | Angemeldet, wartet auf Ergebnis |
| CONFIRMED | Hat Platz, muss Teilnahme bestätigen |
| PARTICIPATING | Hat Teilnahme bestätigt |
| WAITLISTED | Auf der Warteliste |
| CANCELLED | Hat abgesagt/storniert |
| CHECKED_IN | Ist erschienen (Zukunft) |

---

## Checklisten-Format

Jeder Abschnitt endet mit einer Checkliste:

```markdown
### Was du überprüfen kannst
- [ ] Erste erwartete Beobachtung
- [ ] Zweite erwartete Beobachtung
- [ ] Dritte erwartete Beobachtung
```

---

## Screenshots (optional, Zukunft)

Falls Screenshots hinzugefügt werden:

| Anforderung | Wert |
|-------------|------|
| Format | PNG oder WebP |
| Maximale Breite | 800px |
| Speicherort | `docs/images/` |
| Benennung | `01-login.png`, `02-create-event.png`, etc. |
| Sprache | Deutsche UI |
| Sensible Daten | Ausblenden/Anonymisieren |

---

## Aktualisierung

Die Dokumentation sollte aktualisiert werden bei:

1. **Neuen Features**
   - Beschreibung der neuen Funktionalität
   - Einordnung in den Gesamtflow

2. **UI-Änderungen**
   - Anpassung der Schritt-für-Schritt-Anleitungen
   - Neue Screenshots (falls vorhanden)

3. **Geändertem Wording**
   - Wenn sich Button-Texte oder Labels ändern
   - Wenn sich Status-Namen ändern

---

## Abnahmekriterien

- [ ] Alle 10 Hauptteile sind vorhanden
- [ ] Jeder Teil enthält Schritte und Checkliste
- [ ] Keine unübersetzten englischen Begriffe (außer im Glossar erklärt)
- [ ] FAQ beantwortet mindestens 4 typische Fragen
- [ ] Glossar enthält alle verwendeten Fachbegriffe
- [ ] Feedback-Prozess ist beschrieben
- [ ] Markdown rendert korrekt in GitHub/GitLab

---

## Lieferobjekt

| Datei | Status |
|-------|--------|
| `docs/TESTANLEITUNG.md` | ✅ Erstellt |

---

## Mögliche Erweiterungen

1. **PDF-Export** – Für Offline-Nutzung
2. **Video-Tutorials** – Für visuelle Lerner:innen
3. **Interaktive Checkliste** – Als Web-App
4. **Mehrsprachigkeit** – Englische Version
5. **Barrierefreiheit** – Screenreader-optimierte Version
