# Das Festival-Werkzeug — einfach erklärt

**Für wen ist dieser Text?** Für alle im Orga-Team und alle Helfer:innen, die kein Technik-Wissen haben.
Der Text erklärt, was das neue Festival-Werkzeug kann und wie wir es benutzen.
(Die technische Fassung für die Entwicklung steht in `spec.md`.)

---

## Worum geht es?

Wir feiern die **Betriebsfeier der Julius Grube Schiffswerft**: **Freitag, 14. August bis Sonntag, 16. August 2026.**
Es sollen nie mehr als etwa **1000 Menschen gleichzeitig** auf dem Gelände sein — das behalten wir über unsere Zahlen im Blick, nicht über Kontrollen.
(Der Aufbau ab Mittwoch, 12. August wird separat geplant — er läuft **nicht** über dieses Werkzeug.)

**Das ist eine Mitmachfeier** — es gibt viele Schichten zu besetzen. Wer eine Schicht macht, trägt sich im Schichtplan ein (Link steht auf der Anmelde-Seite) und meldet sich bei **Aline** — sie koordiniert das und braucht deinen Kontakt.

Damit das klappt, müssen wir drei Dinge wissen:

1. **Wie viele Menschen sind wann da?** Und wie viele schlafen bei uns?
2. **Wer kommt wann?**
3. **Wer darf sich überhaupt anmelden?** Das wollen wir steuern — Schritt für Schritt.

Genau dafür bauen wir das Festival-Werkzeug. Es ist ein Teil unserer Schaluppe-Anmelde-Seite.

---

## Die wichtigste Idee: Einladungs-Links

Es gibt **keine offene Anmeldung**. Man kann sich nur anmelden, wenn man einen **Einladungs-Link** bekommen hat.

Ein Einladungs-Link ist eine Internet-Adresse, die wir per Telegram oder E-Mail verschicken.
Jeder Link hat zwei Einstellungen:

- **Wie oft darf der Link benutzt werden?**
  Ein persönlicher Link geht nur **einmal**. Wenn er in einer Telegram-Gruppe landet, ist er nach der ersten Anmeldung wertlos.
  Ein geteilter Link geht **mehrmals** — zum Beispiel 100-mal für eine befreundete Community. Danach ist er automatisch zu.
- **Wie viele Menschen darf man mitbringen?**
  Zum Beispiel: Anna darf eine Person mitbringen. Ihre Anmeldung gilt dann für zwei.

Wir verschicken die Links in **vier Wellen**:

1. **Zuerst die Werft-Angestellten.** Jede:r bekommt einen persönlichen Link und darf **eine Person mitbringen** (+1).
2. **Dann die Helfer:innen** (etwa 70 bis 80 Menschen). Jede:r bekommt einen persönlichen Link.
3. **Dann unsere Mitglieder** (mobile machenschaften / Schaluppe). Auch persönliche Links.
4. **Zuletzt die Gästeliste.** Hier gibt es zwei Wege:
   - Geteilte Links für ganze Gruppen oder Kanäle ("dieser Link gilt 100-mal").
   - Oder: Eine vertraute Person bekommt einen Link, der zum Beispiel 10-mal gilt. Sie gibt ihn an ihre Freund:innen weiter. So hat sie **10 Gästelisten-Plätze**.

Eine Gruppe von Links mit gleichen Regeln nennen wir **Kontingent** — zum Beispiel „Welle 1 – Werft" oder „Gästeliste von X".

**Wichtig:** Wir verhindern das Weitergeben nicht komplett. Aber jeder Link hat einen Deckel, und wir sehen genau, welcher Link wie oft benutzt wurde. Läuft etwas aus dem Ruder, machen wir den Link einfach zu.

---

## So läuft es für die Gäste

1. Du bekommst einen Einladungs-Link — per Telegram oder E-Mail.
2. Du öffnest den Link. Die Seite erklärt das Festival.
3. Du meldest dich an. Du gibst an:
   - deinen **vollen Namen (Vor- und Nachname)** und deine E-Mail-Adresse — Spitznamen reichen nicht,
   - wen du mitbringst (auch mit **Vor- und Nachnamen**),
   - **an welchen Tagen du kommst** — Kästchen zum Ankreuzen: **Freitag / Samstag / Sonntag**,
   - ob du **übernachtest** — trag ein, **wie viele Zelte und/oder Camper/Wohnwagen** ihr mitbringt (beides möglich, wenn ihr z. B. mit Zelt *und* Camper kommt). Gezählt werden die Zelte/Fahrzeuge, nicht die Personen — die Stellplätze sind knapp. Nichts eintragen = keine Übernachtung. Deine Angabe ist eine **Anfrage**, keine Zusage — wir melden uns bei dir.
4. Danach bekommst du eine Bestätigungs-E-Mail. Darin steht alles noch einmal — und ein **Verwaltungs-Link**.
5. Mit dem Verwaltungs-Link kannst du deine Angaben **jederzeit selbst ändern** — die Anmeldung läuft bis zum letzten Festival-Tag, auch während des Festivals.
6. **Absagen geht immer.** Bitte sag ab, wenn du nicht kommst — dann stimmen unsere Zahlen fürs Essen und die Stellplätze.
7. Auf der Verwaltungs-Seite findest du später auch die **Eintritts-Codes** (QR-Codes) für dich und deine Begleitungen. Bitte leite die Codes an deine Begleitungen weiter.
8. Beim **ersten Ankommen**: Code am Eingang zeigen (oder einfach deinen Namen nennen) → du bekommst dein **Festival-Bändchen**. Danach reicht das Bändchen — für rein und raus, an allen Tagen.

**Niemand wird abgewiesen, weil ein Zeitfenster „voll" ist.** Die Angaben sind für unsere Planung, nicht zum Aussperren.
**Aber:** Ohne Anmeldung kommt niemand rein. Es gibt keine spontane Anmeldung am Eingang — jede:r braucht vorher einen Link.

---

## So läuft es für die Orga

Im Admin-Bereich gibt es einen neuen Bereich **„Festival"**. Er ist von den normalen Veranstaltungen getrennt. Dort kann man:

1. **Das Festival anlegen**: Name („Betriebsfeier Julius Grube Schiffswerft"), Zeitraum, die Tage zum Ankreuzen (Freitag / Samstag / Sonntag), Kontakt-Adresse für Fragen, und der Mitmach-Hinweis mit dem Schichtplan-Link. Die Anmeldung läuft bis zum letzten Festival-Tag.
2. **Kontingente anlegen**: Namensliste einfügen — das Werkzeug macht aus jeder Zeile einen persönlichen Link. Links kann man einzeln kopieren (für Telegram) oder direkt als E-Mail verschicken.
3. **Nachfassen**: Eine Liste zeigt für jeden Link, ob er verschickt und ob er benutzt wurde. So sehen wir, wen wir erinnern müssen, bevor die nächste Welle rausgeht.
4. **Planen mit „Wer kommt wann"**: Die Übersicht zeigt für jeden Tag, wie viele Menschen kommen — getrennt nach Gruppen (Werft-Angestellte, Helfer:innen, Mitglieder, Gäste). So behalten wir die 1000er-Grenze im Blick.
5. **Eingangs-Liste ausdrucken** (eine Zeile pro Person, alphabetisch). Weil die Anmeldung weiterläuft, drucken wir sie an jedem Festival-Abend neu. Die Essens-Zahlen fürs Küchen-Team lesen wir direkt aus „Wer kommt wann" ab.

---

## So läuft es am Eingang

- Die Tor-Schicht bekommt einen **Tor-Link**. Den öffnet man auf dem Handy — fertig. Kein Konto, kein Passwort. Der Link funktioniert auf beliebig vielen Handys gleichzeitig.
- **Jede Person wird genau einmal gescannt — beim ersten Ankommen.** Das Handy scannt den QR-Code und zeigt: Name und Gruppe. Bestätigen → die Person bekommt ihr **Festival-Bändchen**.
- **Danach zählt nur das Bändchen.** Wer rein und raus geht, zeigt das Bändchen — kein Scan mehr nötig.
- Die angekreuzten Zeitfenster sind **nur für unsere Planung**. Am Eingang wird nicht geprüft, für welche Zeiten sich jemand angemeldet hat.
- **Ampel-Regel:**
  - 🟢 Gültiger Code, noch nicht eingecheckt → Bändchen ausgeben. (Ein Tippen macht den Scan rückgängig, falls man sich vertan hat.)
  - 🟡 Code wurde schon benutzt → kein zweites Bändchen. Sagt jemand „Bändchen verloren", entscheidet die Schicht-Leitung.
  - 🔴 Code ungültig oder Anmeldung storniert → Namen suchen, sonst die Orga rufen.
- **Kein QR-Code dabei?** Namen ins Suchfeld tippen, Person finden, abhaken, Bändchen ausgeben.
- **Kein Netz?** Der Scanner funktioniert trotzdem: Er erkennt echte Tickets auch ohne Internet und trägt die Scans später nach.
- **Sicherheits-Netz:** An jeder Spur liegt trotzdem die **gedruckte Liste mit Stift**. Papier geht immer.
- Am **Montag, 10. August** testen wir den Scanner mit echten Tor-Leuten. Klappt es nicht gut, machen wir das Tor komplett mit Papier — auch okay.

---

## Welche E-Mails verschickt das Werkzeug?

Alle E-Mails klingen wie immer bei uns („Moin …", freundlich, auf Deutsch):

1. **Einladung** — mit deinem persönlichen Link.
2. **Bestätigung** — nach der Anmeldung: deine Tage, Begleitungen, dein Verwaltungs-Link und der Mitmach-Hinweis mit dem Schichtplan-Link.
3. **Änderungs-Bestätigung** — wenn du etwas geändert hast.
4. **Absage-Bestätigung** — wenn du abgesagt hast.

---

## Der Zeitplan

| Wann | Was passiert |
|---|---|
| **bis 26. Juli** | Die Anmeldung wird gebaut. Am Ende der Woche gehen die **Einladungen an die Werft-Angestellten und die Helfer:innen** raus. |
| **27. Juli – 2. August** | Die „Wer kommt wann"-Übersicht kommt dazu. Wenn die Zahlen gut aussehen: **Einladungen an die Mitglieder**. |
| **3. – 9. August** | **Gästeliste öffnet** (geteilte Links). Der Eingangs-Scanner wird gebaut. |
| **Montag, 10. August** | **Essens-Stichtag**: Die Zahlen aus „Wer kommt wann" gehen an das Küchen-Team (die Anmeldung läuft trotzdem weiter). Außerdem: Scanner-Test, Listen drucken. |
| **14. – 16. August** | **Festival!** Die Anmeldung bleibt bis zum letzten Tag offen; die Eingangs-Liste wird jeden Abend neu gedruckt. |

---

## Was das Werkzeug absichtlich NICHT macht

- **Kein Losverfahren, keine Warteliste.** Wer einen gültigen Link hat, ist drin. Wir steuern über die Anzahl der Links, die wir rausgeben.
- **Kein hartes „Ausverkauft".** Volle Zeitfenster zeigen wir der Orga an — aber niemand wird blockiert. Es gibt keine amtliche Höchstgrenze für unser Gelände.
- **Kein Geld.** Das Festival kostet keinen Eintritt, also gibt es keine Bezahlung im Werkzeug.
- **Keine Essens-Abfrage** (vorerst). Falls das Küchen-Team es braucht, reden wir nochmal.
- **Keine spontanen Gäste.** Wer keinen Einladungs-Link hat und nicht angemeldet ist, kommt nicht rein. Es gibt keine Anmeldung am Eingang.
- **Übernachtung ist eine Anfrage, keine Zusage.** Wir fragen Zelt/Camper und wie viele Zelte/Camper ihr mitbringt; die Orga sagt Stellplätze manuell zu (nach Telefon-Absprache). Es gibt keine automatische Zusage-Mail.
- **Kein Aufbau-Plan.** Aufbau und Abbau werden woanders organisiert — dieses Werkzeug kümmert sich nur um die Festival-Tage.

---

## Kleines Wörterbuch

| Wort | Bedeutung |
|---|---|
| **Einladungs-Link** | Internet-Adresse, mit der man sich anmelden kann. Ohne Link keine Anmeldung. |
| **Zeitfenster** | Die Tage zum Ankreuzen bei der Anmeldung: Freitag, Samstag, Sonntag. (Die Orga könnte auch feinere Fenster einstellen — aktuell sind es die drei Tage.) |
| **Kontingent** | Ein Stapel von Links mit gleichen Regeln, z. B. „Welle 2 – Helfer:innen". |
| **Verwaltungs-Link** | Dein persönlicher Link nach der Anmeldung. Damit änderst du deine Angaben oder sagst ab. |
| **„Wer kommt wann"** | Die Übersicht für die Orga: wie viele Menschen an welchem Tag da sind. |
| **QR-Code / Eintritts-Code** | Ein kleines Quadrat-Muster auf deinem Handy. Das Tor scannt es einmal, beim ersten Ankommen — wie eine Eintrittskarte. |
| **Festival-Bändchen** | Das Armband, das du beim ersten Ankommen gegen deinen QR-Code bekommst. Damit kommst du danach immer rein und raus. |
| **Tor-Link** | Der Link, mit dem die Tor-Schicht den Scanner auf dem Handy öffnet. |
| **Gate-Liste** | Die gedruckte Namensliste am Eingang — unser Sicherheits-Netz, falls Technik streikt. |
| **Essens-Stichtag** | Montag, 10. August. An diesem Tag bekommt das Küchen-Team unsere Zahlen. Anmelden und Ändern geht danach trotzdem weiter — bis zum letzten Festival-Tag. |

---

**Fragen?** Melde dich bei der Orga (Kontakt-Adresse steht in jeder E-Mail).
