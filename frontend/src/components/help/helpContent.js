/**
 * Contextual help content for all screens and modals.
 * Each key maps to a screen/state and contains concise German help text
 * adapted from docs/anleitung.md.
 */
export default {
  'registration-page': {
    title: 'Anmeldung',
    sections: [
      {
        html: '<p>Fülle das Formular aus, um dich für dieses Event anzumelden. <strong>Name</strong>, <strong>E-Mail</strong> und <strong>Gruppengröße</strong> sind Pflichtfelder.</p>'
      },
      {
        html: '<p>Pro Event ist nur <strong>eine Anmeldung je E-Mail-Adresse</strong> möglich. Die Gruppengröße umfasst dich selbst plus deine Begleitung (max. 10).</p>'
      },
      {
        html: '<p>Nach dem Absenden bekommst du eine Bestätigungsmail mit einem persönlichen Link, über den du deine Anmeldung jederzeit verwalten kannst.</p>'
      },
      {
        heading: 'Nach Anmeldeschluss',
        html: '<p>Du kannst dich auch nach dem Anmeldeschluss noch eintragen — du landest dann direkt auf der Warteliste.</p>'
      }
    ]
  },

  'manage-registered': {
    title: 'Anmeldung eingegangen',
    sections: [
      {
        html: '<p>Deine Anmeldung ist gespeichert. Die Verlosung hat noch nicht stattgefunden — sobald es soweit ist, wirst du per E-Mail informiert.</p>'
      },
      {
        html: '<p>Über diese Seite kannst du deine Anmeldung jederzeit <strong>stornieren</strong>, falls du doch nicht teilnehmen möchtest.</p>'
      }
    ]
  },

  'manage-confirmed': {
    title: 'Platz bestätigen',
    sections: [
      {
        html: '<p>Du hast bei der Verlosung einen Platz bekommen! Jetzt musst du deine Teilnahme <strong>bestätigen</strong> und die <strong>Namen aller Mitfahrenden</strong> eintragen.</p>'
      },
      {
        html: '<p>Dein Name ist schon vorausgefüllt (du kannst ihn ändern). Für jede weitere Person gibt es ein eigenes Feld. Alle Felder müssen ausgefüllt sein.</p>'
      },
      {
        html: '<p>Du kannst die <strong>Gruppengröße verkleinern</strong>, indem du Felder entfernst — frei werdende Plätze gehen an die Warteliste. Vergrößern geht nicht.</p>'
      }
    ]
  },

  'manage-participating': {
    title: 'Du bist dabei!',
    sections: [
      {
        html: '<p>Deine Teilnahme ist bestätigt. Hier kannst du die <strong>Namen deiner Mitfahrenden</strong> jederzeit ändern oder Personen entfernen.</p>'
      },
      {
        html: '<p>Entfernte Plätze werden automatisch an Personen auf der Warteliste vergeben.</p>'
      },
      {
        heading: 'Absagen',
        html: '<p>Falls du doch nicht kannst: Über den Absage-Button stornierst du deine gesamte Anmeldung. <strong>Eine Stornierung ist endgültig.</strong></p>'
      }
    ]
  },

  'manage-waitlisted': {
    title: 'Warteliste',
    sections: [
      {
        html: '<p>Du stehst auf der Warteliste. Wenn jemand absagt oder die Gruppengröße verkleinert, rückst du automatisch nach und bekommst eine E-Mail.</p>'
      },
      {
        html: '<p>Du kannst deine Anmeldung jederzeit <strong>stornieren</strong>, falls du nicht mehr nachrücken möchtest.</p>'
      }
    ]
  },

  'manage-cancelled': {
    title: 'Storniert',
    sections: [
      {
        html: '<p>Deine Anmeldung wurde storniert. Eine erneute Anmeldung über diesen Link ist nicht möglich.</p>'
      },
      {
        html: '<p>Falls du dich doch noch anmelden möchtest, wende dich an die Organisator:innen.</p>'
      }
    ]
  },

  'manage-checked_in': {
    title: 'Eingecheckt',
    sections: [
      {
        html: '<p>Du bist eingecheckt — viel Spaß! Hier siehst du die vollständige Passagierliste deiner Gruppe.</p>'
      }
    ]
  },

  'admin-events': {
    title: 'Veranstaltungen verwalten',
    sections: [
      {
        heading: 'Rollen',
        html: '<p><strong>Owner</strong> können alles, inkl. andere Admins verwalten. <strong>Admins</strong> erstellen und verwalten Events. <strong>Viewer</strong> haben nur Lesezugriff.</p>'
      },
      {
        heading: 'Lebenszyklus',
        html: '<p>Jedes Event durchläuft diese Phasen:</p><p><strong>Entwurf</strong> → <strong>Offen</strong> → <strong>Anmeldung geschlossen</strong> → <strong>Verlosung</strong> → <strong>Bestätigt</strong> → <strong>Abgeschlossen</strong></p><p>Jedes Event kann jederzeit <strong>abgesagt</strong> werden.</p>'
      },
      {
        heading: 'Filter',
        html: '<p>Nutze die Tabs oben, um nach Event-Status zu filtern. Klicke auf ein Event, um die Anmeldungen zu sehen.</p>'
      }
    ]
  },

  'event-detail': {
    title: 'Anmeldungen verwalten',
    sections: [
      {
        html: '<p>Hier siehst du alle Anmeldungen mit Status, Gruppengröße und Kontaktdaten. Du kannst nach Name oder E-Mail suchen und nach Status filtern.</p>'
      },
      {
        heading: 'Bevorzugte Plätze',
        html: '<p>Mit dem <strong>Promoted-Schalter</strong> garantierst du einzelnen Personen einen Platz bei der Verlosung (z.B. Helfer:innen). Nur vor der Verlosung änderbar.</p>'
      },
      {
        heading: 'Aktionen',
        html: '<p>Je nach Event-Status stehen dir verschiedene Aktionen zur Verfügung: Veröffentlichen, Anmeldung schließen, Verlosung starten, Nachrichten senden, Boardingzettel exportieren und mehr.</p>'
      }
    ]
  },

  'event-form': {
    title: 'Event erstellen / bearbeiten',
    sections: [
      {
        html: '<p><strong>Name</strong>, <strong>Datum</strong>, <strong>Kapazität</strong> und <strong>Anmeldeschluss</strong> sind Pflichtfelder. Der Anmeldeschluss muss vor dem Eventdatum liegen.</p>'
      },
      {
        heading: 'Erinnerungen',
        html: '<p>Standardmäßig werden Erinnerungen 7, 3 und 1 Tag vor dem Event verschickt. Du kannst die Tage anpassen.</p>'
      },
      {
        heading: 'Automatisch nachrücken',
        html: '<p>Wenn aktiviert, rücken Personen von der Warteliste automatisch nach, sobald Plätze frei werden.</p>'
      }
    ]
  },

  'clone-event': {
    title: 'Event duplizieren',
    sections: [
      {
        html: '<p>Erstellt eine Kopie dieses Events mit neuem Datum. Alle Einstellungen (Kapazität, Beschreibung, Ort, Erinnerungen) werden übernommen.</p>'
      },
      {
        html: '<p>Das duplizierte Event startet im Status <strong>Entwurf</strong> und muss separat veröffentlicht werden.</p>'
      }
    ]
  },

  'lottery': {
    title: 'Verlosung',
    sections: [
      {
        heading: 'Ablauf',
        html: '<ol><li><strong>Verlosung durchführen</strong> — mischt alle Anmeldungen zufällig</li><li><strong>Ergebnis prüfen</strong> — sieh dir Gewinner:innen und Warteliste an</li><li><strong>Neu mischen</strong> — falls das Ergebnis nicht passt</li><li><strong>Finalisieren & Benachrichtigen</strong> — Ergebnis wird übernommen, alle bekommen eine E-Mail</li></ol>'
      },
      {
        heading: 'Fairness',
        html: '<p>Bevorzugte Personen (Promoted) bekommen immer einen Platz. Gruppen werden als Ganzes berücksichtigt — alle oder niemand. Der Zufalls-Seed wird gespeichert und ist nachvollziehbar.</p>'
      }
    ]
  },

  'discard-modal': {
    title: 'Unbestätigte verwerfen',
    sections: [
      {
        html: '<p>Hier kannst du Anmeldungen verwerfen, deren Gewinner:innen ihren Platz nicht bestätigt haben. Wähle einzelne oder alle aus.</p>'
      },
      {
        html: '<p>Du kannst die vorformulierte Nachricht anpassen. Nach dem Verwerfen rücken automatisch Personen von der Warteliste nach.</p>'
      }
    ]
  },

  'message-composer': {
    title: 'Nachricht senden',
    sections: [
      {
        html: '<p>Sende eine E-Mail an ausgewählte Teilnehmende. Du kannst nach Status filtern und einzelne Empfänger:innen auswählen.</p>'
      },
      {
        heading: 'Automatische E-Mails',
        html: '<p>Funke verschickt außerdem automatisch: Anmeldebestätigung, Verlosungsergebnis, Wartelisten-Nachrücker, Stornierungsbestätigung, Event-Absage und Erinnerungen.</p>'
      }
    ]
  }
}
