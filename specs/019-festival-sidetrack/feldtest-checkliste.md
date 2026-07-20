# Feldtest-Checkliste: QR-Check-in am Einlass

**Termin:** Montag, 10.8.2026 (Testtag), Entscheidung spätestens **Dienstag, 11.8.2026**
**Bezug:** [tasks.md](./tasks.md) T312 · [spec.md](./spec.md) Ä9, Ä13, Ä17 · durchgeführt von echten Einlass-Leuten (nicht Devs)

> Dieser Feldtest ist eine **menschliche Aktivität** — diese Checkliste bereitet ihn vor, ersetzt ihn aber nicht. Alle technischen Voraussetzungen (Tests, Build) sind geprüft und grün (Stand 19.7., siehe Abschnitt „Technischer Stand" unten). Was fehlt, ist der reale Durchlauf mit echten Personen, echten Handys, echtem Netz (oder eben keinem).

---

## 0. Technischer Stand (vor dem Feldtest geprüft)

- [x] Backend-Testsuite grün bis auf die 2 bekannten Baseline-Fehler (`test_registration_cancelled`, `test_format_date_german` — beide vorbestehend, nicht Teil von P3).
- [x] Alle P3-Backend-Tests grün: `test_ticket_signing.py`, `test_checkin_service.py`, `test_festival_checkin.py`, `test_festival_headcount.py` (56 Tests).
- [x] Frontend-Build (`npm run build`) grün, keine Fehler/Warnungen; `ScannerPage` wird gebündelt, Route `/checkin/:gateToken` existiert ohne `authGuard`.
- [x] Offline-Verifikation (`ticketVerify.js`) gegen die Backend-Referenzimplementierung geprüft (Node-`crypto.subtle`-Parity-Fixture im Modul-Docstring dokumentiert — Hinweis: das ist **kein automatisierter Testlauf**, da im Frontend kein Testrunner existiert; es ist eine von-Hand verifizierte Fixture aus der Implementierung).
- [ ] **Nicht automatisierbar / offen:** echter Kamera-Scan bei Tageslicht/Dämmerung, echtes zweites Telefon, echter Flugmodus, echte Einlass-Leute unter Zeitdruck. Das ist genau der Gegenstand des Feldtests unten.

---

## 1. Geräte & Equipment

- [ ] Mind. **3 geladene Smartphones** + **2 Powerbanks** pro Schicht (aus spec.md-Zeitplan übernommen), davon **mind. 1 iPhone/Safari** (WebCrypto- und Kamera-Verhalten unterscheidet sich von Android/Chrome).
- [ ] Dedizierter **mobiler Hotspot** am Einlass (Fallback, falls Veranstaltungsort-WLAN fehlt/schwach ist).
- [ ] **Festival-Bändchen** in ausreichender Zahl (physisches Gegenstück zum „grün"-Ergebnis).
- [ ] **Gate-CSV ausgedruckt** (P1 T113, Ä9-Boden) als Vor-Ort-Backup — alphabetisch, eine Zeile pro Person, inkl. Schlafplatz-Spalte.
- [ ] Papier + Stift an jeder Spur (auch wenn der Scanner läuft — Doppel-Absicherung).
- [ ] Prod-Gate-Link **rotiert** (Admin → Festival → „Einlass" → „Link erneuern") und an **2–3 echte Einlass-Personen** (nicht Entwickler) auf **deren eigenen Handys** verteilt.
- [ ] **2–3 echte Test-Anmeldungen mit Gruppenmitgliedern** angelegt, damit auf der Verwaltungsseite echte QR-Codes existieren (verschiedene Zeitfenster- und Übernachtungs-Kombinationen).
- [ ] Mind. eine Test-Anmeldung mit **Zelt-Wunsch, noch nicht zugesagt** (für den Übernachtungs-Testfall).
- [ ] Zugriff auf die Admin-Oberfläche vor Ort (für den „darf übernachten"-Toggle und die Kontrolle des Angekommen-Zählers auf der Headcount-Seite).

---

## 2. Testfälle

Jeder Testfall wird von einer **echten Einlass-Person unbegleitet** durchgeführt (Devs beobachten nur, greifen nicht ein — außer bei echtem Blocker). Ergebnis pro Fall: **Bestanden / Nicht bestanden**, mit Notiz.

### 2.1 Erstscan → Bändchen
- [ ] Anmeldebestätigung (Verwaltungsseite) auf Handy A öffnen, QR-Code sichtbar.
- [ ] Mit Handy B (Scanner-Link) den QR scannen.
- [ ] **Erwartung:** grüne Karte in einem Tap (Name, Gruppe, Zeitfenster als Info, Übernachtungsstatus), Kopfzeile „✓ Eingecheckt — Bändchen ausgeben". Bändchen wird ausgegeben.
- [ ] Notiz: Zeit vom Scan bis zur sichtbaren Entscheidung (Zielwert: ≤ 10 s).

### 2.2 Doppelscan
- [ ] Dieselbe Person nach dem Erstscan erneut scannen.
- [ ] **Erwartung:** gelbe Karte „Bereits eingecheckt — kein zweites Bändchen", kein neuer Log-Eintrag.

### 2.3 Bändchen-verloren-Override
- [ ] Auf der gelben Karte „Trotzdem einchecken" antippen.
- [ ] **Erwartung:** grüne Karte erscheint, der Vorgang wird mit `override=true` protokolliert (im Admin/Testprotokoll später stichprobenartig prüfbar).

### 2.4 Undo (3-Sekunden-Fenster)
- [ ] Direkt nach einem Erstscan „Rückgängig (3)" antippen, bevor der Countdown abläuft.
- [ ] **Erwartung:** Eintrag verschwindet, erneuter Scan derselben Person zeigt wieder grün (nicht gelb).
- [ ] Nach Ablauf des Countdowns: Rückgängig-Button verschwindet von selbst.

### 2.5 Namenssuche (inkl. Duplikat)
- [ ] Ohne QR: Namenssuche mit mind. 2 Zeichen für einen Namen, der bei mehreren Personen vorkommt (z. B. gleicher Vorname in zwei Gruppen).
- [ ] **Erwartung:** alle Treffer werden mit Unterscheidungsmerkmalen angezeigt (Begleitung/Kontaktperson, Gruppengröße, Kontingent, Check-in-Status).
- [ ] Antippen einer Zeile checkt genau diese eine Person ein (per `registration_id` + `person_index`, nie nur per Name) — im nächsten Suchdurchlauf als „eingecheckt" sichtbar.

### 2.6 Veraltetes Ticket
- [ ] Vor dem Test: ein Gruppenmitglied auf der Verwaltungsseite umbenennen oder entfernen (nachdem der QR-Code schon einmal angezeigt/gespeichert wurde).
- [ ] Den alten (jetzt veralteten) QR-Code scannen.
- [ ] **Erwartung:** rote Karte „Ticket veraltet — bitte Namenssuche", mit Schnellzugriff-Button zur Namenssuche.

### 2.7 Übernachtungs-Status (Ä17): ✓ / ⚠ / —
- [ ] Anmeldung mit Zelt-Wunsch, **noch nicht zugesagt**, scannen.
  - **Erwartung:** Karte zeigt „Übernachtung nur angefragt ⚠ — nicht zugesagt" (auffällig/warnend gestaltet).
- [ ] Danach im Admin-Bereich (FestivalRegistrationsPage) „darf übernachten" für diese Person umschalten (zusagen).
- [ ] Dieselbe Person erneut scannen (oder eine zweite Person derselben Gruppe, falls Erstscan schon verbraucht — Doppelscan ist ok, zeigt aber weiterhin den aktuellen Status).
  - **Erwartung:** Karte zeigt jetzt „Übernachtung zugesagt ✓ (Zelt)" — der Server-Stand gewinnt gegenüber dem im QR gespeicherten Stand.
- [ ] Zur Vollständigkeit (kann am Schreibtisch statt am Gate geprüft werden): eine Anmeldung **ohne** Übernachtungswunsch zeigt „Keine Übernachtung —".

### 2.8 Flugmodus-Scan + Sync
- [ ] Scanner-Seite einmal online öffnen (Boot-Payload wird gecacht).
- [ ] Flugmodus aktivieren.
- [ ] Einen gültigen QR-Code scannen.
  - **Erwartung:** degradierte grüne Karte (nur Name + geplante Zeitfenster aus dem Cache, Übernachtungs-Flag aus dem Ticket selbst, mit Hinweis „Offline — eingeschränkte Prüfung"), Scan wird in die Warteschlange gelegt (Badge zeigt Anzahl wartender Scans).
- [ ] Einen manipulierten/ungültigen Code offline scannen.
  - **Erwartung:** wird lokal als ungültig erkannt (rote Karte), kein stiller Fehler.
- [ ] Flugmodus deaktivieren.
  - **Erwartung:** Warteschlange synchronisiert innerhalb von 30 s (oder per „Jetzt synchronisieren"-Button sofort); im Admin-Bereich (HeadcountPage, „Angekommen") erscheint **genau ein** zusätzlicher Ankunfts-Zähler pro Person — kein Doppelzählen, auch wenn dieselbe Person zwischenzeitlich schon online gescannt wurde.

### 2.9 Mitternachts-Randfall
- [ ] Dieser Fall ist **backend-seitig bereits automatisiert getestet** (`test_checkin_service.py`, Zeitstempel Sa 00:30 CEST → wird korrekt Samstag zugeordnet, nicht Freitag). Am Gate selbst nur relevant, falls der Testtag zufällig über Mitternacht läuft:
  - [ ] Falls am 10.8. tatsächlich ein Scan nach Mitternacht (Berlin-Zeit) stattfindet: im Admin-Bereich prüfen, dass der Ankunfts-Tag korrekt dem **nächsten** Kalendertag zugeordnet wird (Berlin-Ortszeit, nicht UTC).
  - [ ] Falls kein Scan nach Mitternacht stattfindet: als „nicht anwendbar am Testtag, backend-seitig abgedeckt" vermerken — kein Blocker fürs Go/No-Go.

---

## 3. Pass/Fail-Kriterien (alle müssen zutreffen)

- [ ] Eine **Nicht-Entwickler-Person** schafft den Ablauf Scan → Bändchen-Entscheidung in **≤ 10 s pro Person**, ohne Rückfragen an Devs.
- [ ] Kamera-Erkennung funktioniert **draußen und bei Dämmerlicht** auf den eigenen Handys der Crew, inkl. **mindestens einem iPhone/Safari**.
- [ ] Doppelscan zeigt zuverlässig gelb, **nie ein zweites Grün**; Undo funktioniert; Override wird protokolliert (`override=true` sichtbar).
- [ ] Flugmodus-Scan verifiziert lokal + reiht ein, und synchronisiert nach Reconnect zu **genau einem** distinkten Check-in.
- [ ] Namenssuche löst einen Duplikat-Namen über den angezeigten Kontext korrekt zur richtigen Person auf.

Zusätzlich am selben Tag zu prüfen:
- [ ] **Regressionstest**: der reguläre (Nicht-Festival-)Ablauf Erstellen → Anmelden → Lotterie funktioniert in Prod unverändert.

---

## 4. Papier-Fallback-Entscheid

- **Regel (Ä9, spec.md):** Wenn der Feldtest **nicht besteht** und das Problem **nicht noch am selben Tag behoben** werden kann, gilt: **Papier ist Plan of Record.** Die gedruckte Gate-CSV führt den Einlass, der Scanner wird bestenfalls unterstützendes Hilfsmittel.
- **Frist:** Entscheidung spätestens **Dienstag, 11.8.2026**. Nach diesem Datum werden **keine neuen Scanner-Features mehr gebaut** — der Gate-Tag ist nicht mehr probbar.
- **Vorgehen bei Nicht-Bestehen:**
  1. Am Testtag selbst versuchen, den/die fehlgeschlagenen Kriterien zu beheben (nur Bugfixes, keine neuen Features).
  2. Erneuter Kurztest desselben Kriteriums mit denselben Testpersonen, falls Zeit bleibt.
  3. Wenn bis Di 11.8. kein Go erreicht wird: Entscheidung **„Papier ist Plan of Record"** greift automatisch — keine weitere Rückfrage nötig, das ist bereits in spec.md (Ä9) so festgelegt.
- **Dokumentationspflicht:** Das tatsächliche Go/No-Go-Ergebnis (mit Datum, Teilnehmer:innen, welche Kriterien bestanden/nicht bestanden haben) muss **von den Menschen, die den Test durchführen,** in `spec.md` im Entscheidungsjournal („Challenged & decided" / Ä9-Zeile) nachgetragen werden — das ist in dieser Vorbereitung noch **nicht** ausgefüllt, da der Test noch nicht stattgefunden hat.

---

## 5. Was diese Vorbereitung NICHT leisten kann

Diese Checkliste, die Tests und der Build-Check bestätigen, dass die Technik **bereit für den Test** ist. Sie können **nicht** ersetzen:
- den tatsächlichen Kameratest unter echten Lichtbedingungen,
- das Verhalten echter Einlass-Personen unter Zeitdruck ohne Entwickler-Hilfe,
- einen echten Flugmodus-Test auf physischen Geräten,
- die Netzqualität vor Ort am 10.8.

Diese Punkte kann nur der Feldtest am Montag selbst beantworten.
