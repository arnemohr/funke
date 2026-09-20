"""Queue one mail per recipient in DynamoDB and let the worker send it.

The mail takes the normal route: a `MSG#` row per recipient with
``status=queued``, then `process_email_queue` picks them up, sends via SMTP and
writes back `sent`/`failed`. Nothing here reimplements the send path, so what
this script proves also holds for mail the app sends by itself.

Usage:
    # the Fundsachen announcement
    direnv exec . uv run python scripts/send_mail.py \\
        --event-id bef2746b-1b15-4b48-acaf-0b44ece4ee9f \\
        --lostfound-url https://funke.mobilemachenschaften.de/lostfound/…/… \\
        --to arne+1@example.com --to arne+2@example.com

    # the post-festival thank-you (bare --photos-url uses the hardcoded page)
    direnv exec . uv run python scripts/send_mail.py \\
        --event-id bef2746b-1b15-4b48-acaf-0b44ece4ee9f \\
        --photos-url \\
        --to-file ../test.txt

    # anything else
    ... --subject "Betreff" --text-file body.txt [--html-file body.html]

    # look before you leap
    ... --dry-run          # render and print, touch nothing
    ... --queue-only       # write the rows, do not send

`direnv exec .` matters: without SMTP_USERNAME/PASSWORD/SENDER_EMAIL in the
environment the worker treats the run as local dev and marks every message as
sent WITHOUT sending it. This script refuses to send in that state rather than
report a success nobody received.
"""

import argparse
import asyncio
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.config import get_messages_table, get_settings  # noqa: E402
from app.services.email_client import get_email_settings  # noqa: E402
from app.workers.handler import process_email_queue  # noqa: E402

LOSTFOUND_SUBJECT = "Eure Fundsachen vom Dockfestival"

# Above this, --yes is required. A file of guest addresses is one keystroke away
# from a send that cannot be recalled, so the threshold is deliberately tiny:
# a handful of test recipients still runs unattended, a real list never does.
BULK_CONFIRM_THRESHOLD = 5

# What one drain pass costs. The worker takes 20 per run and paces sends 4-10 s
# apart, so the wall-clock of a big list is dominated by that pacing, not by us.
WORKER_BATCH = 20
SECONDS_PER_MAIL = 7  # midpoint of the worker's random 4-10 s delay

_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def lostfound_bodies(url: str) -> tuple[str, str]:
    """The Fundsachen announcement as (text, html).

    Inline styles and one container, like the templates in `email_service.py` —
    a mail client is not a browser, and a linked stylesheet would arrive naked.
    """
    text = f"""Moini!

vielen Dank euch allen für das letzte Wochenende! Wir sind noch immer dabei,
dieses unglaubliche Miteinander zu verarbeiten und werden uns die Tage
ausführlicher bei euch melden.

In der Zwischenzeit wollen wir euch aber gern dabei unterstützen, die ganzen
schönen Dinge, die ihr bei uns in der Werft vergessen habt, wiederzufinden.

Hierfür könnt ihr euch unter

{url}

einen Überblick darüber verschaffen, was bei uns in der Fundgrube aufgetaucht ist.

Viele Grüße

Euer Orga Team
"""

    html = f"""<html>
<body style="margin: 0; padding: 0; background: #f4f4f5;">
  <div style="max-width: 560px; margin: 0 auto; padding: 32px 24px;
              font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
              font-size: 16px; line-height: 1.6; color: #333;">

    <h2 style="margin: 0 0 24px; color: #2563eb; font-size: 24px;">Moini!</h2>

    <p style="margin: 0 0 16px;">
      vielen Dank euch allen für das letzte Wochenende! Wir sind noch immer dabei, dieses
      unglaubliche Miteinander zu verarbeiten und werden uns die Tage ausführlicher bei euch
      melden.
    </p>

    <p style="margin: 0 0 16px;">
      In der Zwischenzeit wollen wir euch aber gern dabei unterstützen, die ganzen schönen
      Dinge, die ihr bei uns in der Werft vergessen habt, wiederzufinden.
    </p>

    <p style="margin: 0 0 24px;">
      Hierfür könnt ihr euch hier einen Überblick darüber verschaffen, was bei uns in der
      Fundgrube aufgetaucht ist:
    </p>

    <p style="margin: 0 0 24px; text-align: center;">
      <a href="{url}"
         style="display: inline-block; padding: 14px 28px; background: #2563eb; color: #ffffff;
                text-decoration: none; border-radius: 6px; font-weight: 600;">
        Zur Fundgrube
      </a>
    </p>

    <p style="margin: 0 0 24px; font-size: 13px; color: #6b7280; word-break: break-all;">
      Falls der Knopf nicht funktioniert:<br>
      <a href="{url}" style="color: #6b7280;">{url}</a>
    </p>

    <p style="margin: 0 0 4px;">Viele Grüße</p>
    <p style="margin: 0; font-weight: 600;">Euer Orga Team</p>
  </div>
</body>
</html>"""

    return text, html


THANKYOU_SUBJECT = "Dockfestival // Ein dickes Danke!!"

# Every act, in the order the crew wrote them down. Kept as a list rather than
# one long string so the HTML can put a separator between them without a
# fragile split, and so a correction is a one-line diff.
ACTS = [
    "LESS", "Clarks Planet", "Tentacle Barbers", "E Gerät", "Sutsche", "JMK",
    "Herr Konrad", "Brudi und Spargel", "Til von Push", "Miklosch",
    "Afterhourservice", "Bibis Bänger Bingo", "Mikki Minx",
    "This Is Why We Do Things", "Who Nose", "Milena Schwenkenberg", "H.B.T.",
    "Paul Prime", "Serene & Philiosofiesta", "Cpt. Zeitziehing",
    "Elysium Transit", "Lynx Rouge b2b Rapakivi", "Marisespunkt", "Nuschka",
    "Batte", "Tilonaut", "5 Mark DJ Team", "Crew Ombrelle", "E_Lane", "[Äis]",
    "Janitha",
]

BRACKWASSER_URL = "https://www.instagram.com/brackwasseraudio/"

# The live photo-upload page for the 2026 festival — `--photos-url` without a
# value falls back to this, so the send command needs no copy-pasted token.
PHOTOS_URL = (
    "https://funke.mobilemachenschaften.de/fotos/"
    "bef2746b-1b15-4b48-acaf-0b44ece4ee9f/"
    "qz6iX0gxplQhDecMdxM8qmNgAr2GiICoghf_b4H0blU"
)

# The three projects the door donations go to. (name, place, blurb, url).
DONATIONS = [
    (
        "Die Schaluppe wird 10 – Verein für mobile Machenschaften e.V.",
        "Hamburg-Wilhelmsburg",
        "Seit zehn Jahren schippert das selbstgebaute Floß als nichtkommerzieller "
        "Kultur- und Möglichkeitsraum über Hamburgs Kanäle. Konzerte, Theater, Ideen, "
        "die sonst keinen Platz haben – und die Wasserdemos gegen rechts. Dieses "
        "Wochenende lag sie gedockt mitten auf der Werft, mit eigener Bühne.",
        "https://mobilemachenschaften.de",
    ),
    (
        "forma_te e.V.",
        "Teterow in Mecklenburg-Vorpommern",
        "Baut einen ehemaligen DDR-Industriekomplex zu einem Kulturzentrum für Jung "
        "und Alt um: Werkstätten, offene Ateliers, Jugendarbeit. Demokratische Räume "
        "gegen rechts, genau da, wo sie am dringendsten gebraucht werden.",
        "https://forma-te.org",
    ),
    (
        "Quietjes e.V.",
        "Wasdow in Mecklenburg-Vorpommern",
        "Seit 2013 freie Kunst-, Kultur- und Bildungsprojekte im ländlichen Raum, für "
        "alle zugänglich: Ferienprojekte für Kinder, Medien-, Umwelt- und "
        "Integrationswerkstätten, Begleitung geflüchteter Familien, der Aufbau des "
        "LandKulturbetriebs Q54. Basisdemokratisch und solidarisch.",
        "https://quietjes.de",
    ),
]


def _wrap(text: str, width: int = 78) -> str:
    """Hard-wrap one paragraph for the plain-text part.

    Mail clients that show `text/plain` do not reflow reliably, and an
    800-character line arrives as a single unreadable ribbon.
    """
    import textwrap  # noqa: PLC0415 — only the text part needs it

    return "\n".join(textwrap.wrap(" ".join(text.split()), width=width))


def thankyou_bodies(photos_url: str) -> tuple[str, str]:
    """The post-festival thank-you as (text, html).

    Same shape as `lostfound_bodies`: inline styles, one 560px container, every
    link also spelled out in the text part, because a mail client is not a
    browser and an HTML-only link is invisible to anyone reading plain text.
    """
    acts_text = _wrap(" · ".join(ACTS))

    donations_text = "\n\n".join(
        f"{name}, {place}.\n{_wrap(blurb)}\n→ {url}" for name, place, blurb, url in DONATIONS
    )

    text = f"""Hallo ihr,

wir sind immer noch am Runterkommen.

{_wrap(
    "Es war persönlich, es war liebevoll, es war völlig ausgelassen – und das lag "
    "an euch. An der Art, wie ihr miteinander umgegangen seid und wie wenig wir "
    "eingreifen mussten. So ein Wochenende kann man nicht planen. Man kann nur die "
    "Bedingungen dafür schaffen und hoffen, dass die richtigen Leute kommen. YES! :)"
)}

{_wrap(
    "Gefeiert haben wir zehn Jahre Schaluppe und ein Jahr Werft. Dass daraus eine "
    "so runde Veranstaltung wurde, hätten wir nicht zu träumen gewagt."
)}


DIE ACTS

Drei Tage Programm auf Dock, Beach und in der Kneipe:

{acts_text}

{_wrap(
    "Danke, dass ihr gekommen seid, gespielt, jongliert, in der Luft gehangen und "
    "Nasenflöte gespielt habt. Folgt ihnen, bucht sie, geht zu ihren Gigs!"
)}


TON UND LICHT

{_wrap(
    "Ton und Licht kamen von Brackwasser. Dass es an allen drei Orten so gut klang "
    "und aussah, war kein Zufall, sondern deren Arbeit: @brackwasseraudio"
)}
{BRACKWASSER_URL}


UND ALLE ANDEREN

{_wrap(
    "Bar, Küche, Einlass, Auf- und Abbau, Awareness, Müll sammeln am Ende: Alle, "
    "die dieses Wochenende möglich gemacht haben, waren ehrenamtlich da. Niemand "
    "hat daran verdient. Das macht den Vibe aus."
)}


EINE KLEINE BITTE

{_wrap(
    "Das Gelände hat eine feste Kapazitätsgrenze, mehr Leute dürfen wir nicht "
    "reinlassen. Eine Anmeldung ist deshalb schon eine Zusage – überlegt euch "
    "vorher, ob ihr wirklich kommt. Diesmal sind ziemlich viele angemeldete Plätze "
    "ungenutzt geblieben, und weil wir davon nichts wussten, mussten andere draußen "
    "bleiben. Und wenn doch etwas dazwischenkommt: sagt Bescheid, auch kurzfristig "
    "noch. Dann rückt jemand nach."
)}


WOHIN EURE SPENDEN GEHEN

{donations_text}


BILDER

Schickt uns Fotos oder ladet sie hier hoch:

{photos_url}

{_wrap(
    "Und wenn ihr etwas loswerden wollt – was gut war, was nervte, was nächstes "
    "Mal anders sein sollte – dann schreibt es uns."
)}

Tragt die Liebe raus in die Welt. Ahoi!

Eure Dockfestival-Crew
"""

    acts_html = " &middot; ".join(
        f'<span style="white-space: nowrap;">{act}</span>' for act in ACTS
    )

    donations_html = "".join(
        f"""
    <div style="margin: 0 0 20px; padding: 16px 18px; background: #ffffff;
                border-left: 3px solid #2563eb; border-radius: 4px;">
      <p style="margin: 0 0 6px; font-weight: 600;">{name}</p>
      <p style="margin: 0 0 8px; font-size: 13px; color: #6b7280;">{place}</p>
      <p style="margin: 0 0 10px; font-size: 15px;">{blurb}</p>
      <p style="margin: 0;">
        <a href="{url}" style="color: #2563eb; text-decoration: none; font-weight: 600;">
          {url.replace("https://", "")}
        </a>
      </p>
    </div>"""
        for name, place, blurb, url in DONATIONS
    )

    html = f"""<html>
<body style="margin: 0; padding: 0; background: #f4f4f5;">
  <div style="max-width: 560px; margin: 0 auto; padding: 32px 24px;
              font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
              font-size: 16px; line-height: 1.6; color: #333;">

    <h2 style="margin: 0 0 24px; color: #2563eb; font-size: 24px;">Hallo ihr,</h2>

    <p style="margin: 0 0 16px;">wir sind immer noch am Runterkommen.</p>

    <p style="margin: 0 0 16px;">
      Es war persönlich, es war liebevoll, es war völlig ausgelassen – und das lag an euch.
      An der Art, wie ihr miteinander umgegangen seid und wie wenig wir eingreifen mussten.
      So ein Wochenende kann man nicht planen. Man kann nur die Bedingungen dafür schaffen
      und hoffen, dass die richtigen Leute kommen. YES! :)
    </p>

    <p style="margin: 0 0 28px;">
      Gefeiert haben wir zehn Jahre Schaluppe und ein Jahr Werft. Dass daraus eine so runde
      Veranstaltung wurde, hätten wir nicht zu träumen gewagt.
    </p>

    <h3 style="margin: 0 0 8px; color: #2563eb; font-size: 18px;">Die Acts</h3>
    <p style="margin: 0 0 14px;">Drei Tage Programm auf Dock, Beach und in der Kneipe:</p>

    <p style="margin: 0 0 18px; padding: 18px 20px; background: #ffffff; border-radius: 6px;
              text-align: center; line-height: 2; font-size: 15px;">
      {acts_html}
    </p>

    <p style="margin: 0 0 28px;">
      Danke, dass ihr gekommen seid, gespielt, jongliert, in der Luft gehangen und Nasenflöte
      gespielt habt. Folgt ihnen, bucht sie, geht zu ihren Gigs!
    </p>

    <h3 style="margin: 0 0 8px; color: #2563eb; font-size: 18px;">Ton und Licht</h3>
    <p style="margin: 0 0 28px;">
      Ton und Licht kamen von Brackwasser. Dass es an allen drei Orten so gut klang und
      aussah, war kein Zufall, sondern deren Arbeit:
      <a href="{BRACKWASSER_URL}"
         style="color: #2563eb; text-decoration: none; font-weight: 600;">@brackwasseraudio</a>
    </p>

    <h3 style="margin: 0 0 8px; color: #2563eb; font-size: 18px;">Und alle anderen</h3>
    <p style="margin: 0 0 28px;">
      Bar, Küche, Einlass, Auf- und Abbau, Awareness, Müll sammeln am Ende: Alle, die dieses
      Wochenende möglich gemacht haben, waren ehrenamtlich da. Niemand hat daran verdient.
      Das macht den Vibe aus.
    </p>

    <h3 style="margin: 0 0 8px; color: #2563eb; font-size: 18px;">Eine kleine Bitte</h3>
    <p style="margin: 0 0 28px;">
      Das Gelände hat eine feste Kapazitätsgrenze, mehr Leute dürfen wir nicht reinlassen.
      Eine Anmeldung ist deshalb schon eine Zusage – überlegt euch vorher, ob ihr wirklich
      kommt. Diesmal sind ziemlich viele angemeldete Plätze ungenutzt geblieben, und weil wir
      davon nichts wussten, mussten andere draußen bleiben. Und wenn doch etwas
      dazwischenkommt: sagt Bescheid, auch kurzfristig noch. Dann rückt jemand nach.
    </p>

    <h3 style="margin: 0 0 14px; color: #2563eb; font-size: 18px;">Wohin eure Spenden gehen</h3>
{donations_html}

    <h3 style="margin: 28px 0 8px; color: #2563eb; font-size: 18px;">Bilder</h3>
    <p style="margin: 0 0 18px;">Schickt uns Fotos oder ladet sie hier hoch:</p>

    <p style="margin: 0 0 18px; text-align: center;">
      <a href="{photos_url}"
         style="display: inline-block; padding: 14px 28px; background: #2563eb; color: #ffffff;
                text-decoration: none; border-radius: 6px; font-weight: 600;">
        Fotos hochladen
      </a>
    </p>

    <p style="margin: 0 0 28px; font-size: 13px; color: #6b7280; word-break: break-all;">
      Falls der Knopf nicht funktioniert:<br>
      <a href="{photos_url}" style="color: #6b7280;">{photos_url}</a>
    </p>

    <p style="margin: 0 0 24px;">
      Und wenn ihr etwas loswerden wollt – was gut war, was nervte, was nächstes Mal anders
      sein sollte – dann schreibt es uns.
    </p>

    <p style="margin: 0 0 4px;">Tragt die Liebe raus in die Welt. Ahoi!</p>
    <p style="margin: 0; font-weight: 600;">Eure Dockfestival-Crew</p>
  </div>
</body>
</html>"""

    return text, html


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--to",
        action="append",
        default=[],
        metavar="ADDRESS",
        help="recipient; repeat for more than one (one row and one mail each)",
    )
    parser.add_argument(
        "--to-file",
        type=Path,
        metavar="PATH",
        help="address export: one address per line. Blank lines and lines "
        "starting with # are ignored, malformed ones are reported and skipped. "
        "Combines with --to.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="only take the first N recipients — for a trial run off the real list",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=f"confirm sending to more than {BULK_CONFIRM_THRESHOLD} recipients",
    )
    parser.add_argument(
        "--resend",
        action="store_true",
        help="also mail recipients who already have this subject on this event "
        "(default is to skip them, so an interrupted run can be resumed)",
    )
    parser.add_argument(
        "--no-list-unsubscribe",
        action="store_true",
        help="omit the List-Unsubscribe header that bulk sends get by default",
    )
    parser.add_argument(
        "--event-id",
        required=True,
        help="event the mail belongs to — it becomes the row's partition key, "
        "so the mail shows up in that event's message history",
    )
    parser.add_argument(
        "--subject",
        help=f"defaults: --lostfound-url {LOSTFOUND_SUBJECT!r}, "
        f"--photos-url {THANKYOU_SUBJECT!r}",
    )
    parser.add_argument("--lostfound-url", help="render the Fundsachen announcement for this link")
    parser.add_argument(
        "--photos-url",
        nargs="?",
        const=PHOTOS_URL,
        help="render the post-festival thank-you, linking this photo-upload page "
        "(without a value: the hardcoded 2026 upload page)",
    )
    parser.add_argument("--text-file", type=Path, help="plain-text body")
    parser.add_argument("--html-file", type=Path, help="HTML body (optional)")
    parser.add_argument("--dry-run", action="store_true", help="render and print, write nothing")
    parser.add_argument(
        "--queue-only",
        action="store_true",
        help="write the rows and stop, without checking whether anything can send them",
    )
    parser.add_argument(
        "--drain",
        action="store_true",
        help="send from here instead of leaving it to the scheduled worker "
        "(loops until done; needs the SMTP variables in the environment)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="queue even though the deployed worker looks unable to send",
    )
    parser.add_argument(
        "--allow-foreign-queue",
        action="store_true",
        help="send even though unrelated messages are waiting — they WILL go out too",
    )
    args = parser.parse_args()

    if not args.to and not args.to_file:
        parser.error("give at least one --to, or a --to-file")
    modes = [bool(args.lostfound_url), bool(args.photos_url), bool(args.text_file)]
    if not any(modes):
        parser.error("give one of --lostfound-url, --photos-url or --text-file")
    if sum(modes) > 1:
        parser.error("--lostfound-url, --photos-url and --text-file are mutually exclusive")
    if args.text_file and not args.subject:
        parser.error("--subject is required with --text-file")
    return args


def read_recipients(path: Path) -> list[str]:
    """One address per line, comments and blanks skipped, malformed reported.

    A bad line is never silently dropped: a typo in an export is a guest who
    does not get their mail, and finding that out later means diffing 850 lines
    by hand.
    """
    good: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _ADDRESS.match(line):
            print(f"skip    : line {number} is not an address: {line[:60]!r}", file=sys.stderr)
            continue
        good.append(line)
    return good


def resolve_bodies(args: argparse.Namespace) -> tuple[str, str, str | None]:
    """Return (subject, text, html)."""
    if args.lostfound_url:
        text, html = lostfound_bodies(args.lostfound_url)
        return args.subject or LOSTFOUND_SUBJECT, text, html

    if args.photos_url:
        text, html = thankyou_bodies(args.photos_url)
        return args.subject or THANKYOU_SUBJECT, text, html

    text = args.text_file.read_text(encoding="utf-8")
    html = args.html_file.read_text(encoding="utf-8") if args.html_file else None
    return args.subject, text, html


def foreign_queued(table, own_keys: set[str]) -> list[str]:
    """Addresses of queued messages this run did not create.

    `process_email_queue` sends everything it finds (up to its batch size), so a
    stray row from an earlier failed run would ride along with this send. Better
    to stop and say so than to mail a guest by accident.
    """
    scan = table.scan(
        FilterExpression="#s = :q",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":q": "queued"},
        ProjectionExpression="sk, recipient_email",
    )
    items = scan.get("Items", [])
    while "LastEvaluatedKey" in scan:
        scan = table.scan(
            FilterExpression="#s = :q",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":q": "queued"},
            ProjectionExpression="sk, recipient_email",
            ExclusiveStartKey=scan["LastEvaluatedKey"],
        )
        items.extend(scan.get("Items", []))

    return [i.get("recipient_email", "?") for i in items if i["sk"] not in own_keys]


def deployed_worker_smtp() -> str:
    """Whether the deployed worker Lambda can actually send.

    Returns "configured", "empty", or "unknown" when the check itself failed
    (no permission, no such function). "unknown" is not treated as fine — the
    caller refuses and asks for an explicit override.
    """
    import boto3  # noqa: PLC0415 — only needed on this path

    settings = get_settings()
    name = f"{settings.dynamodb_table_prefix}-worker"  # funke-dev -> funke-dev-worker
    try:
        env = (
            boto3.client("lambda", region_name=settings.aws_region)
            .get_function_configuration(FunctionName=name)
            .get("Environment", {})
            .get("Variables", {})
        )
    except Exception as e:  # noqa: BLE001 — any failure means "cannot tell"
        return f"unknown ({type(e).__name__})"

    missing = [
        key
        for key in ("SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_SENDER_EMAIL")
        if not env.get(key)
    ]
    return "configured" if not missing else f"empty ({', '.join(missing)})"


def already_handled(table, event_id: str, subject: str) -> set[str]:
    """Lowercased addresses that already have this subject on this event.

    An 850-address list is ~43 worker passes and well over an hour; anything
    can interrupt that. Without this the obvious recovery — run it again —
    mails everyone who already got it a second time.
    """
    seen: set[str] = set()
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :msg)",
        "ExpressionAttributeValues": {":pk": f"EVENT#{event_id}", ":msg": "MSG#"},
        "ProjectionExpression": "recipient_email, subject, #s",
        "ExpressionAttributeNames": {"#s": "status"},
    }
    while True:
        page = table.query(**kwargs)
        for item in page.get("Items", []):
            # `failed` is deliberately not here: a failure should be retried.
            if item.get("subject") == subject and item.get("status") in {
                "queued",
                "sending",
                "sent",
            }:
                seen.add(str(item.get("recipient_email", "")).lower())
        if "LastEvaluatedKey" not in page:
            return seen
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def drain(table, event_id: str, own_keys: set[str]) -> tuple[int, int]:
    """Run the worker until this run's rows are all out of the queue.

    The worker takes `WORKER_BATCH` per invocation, so a long list needs many
    passes. Returns (sent, not_sent).
    """
    passes = 0
    while True:
        pending = [
            sk
            for sk in own_keys
            if (
                table.get_item(
                    Key={"pk": f"EVENT#{event_id}", "sk": sk},
                    ProjectionExpression="#s",
                    ExpressionAttributeNames={"#s": "status"},
                )
                .get("Item", {})
                .get("status")
            )
            in {"queued", "sending"}
        ]
        if not pending:
            break

        passes += 1
        print(f"pass {passes:>3}: {len(pending)} still waiting …", flush=True)
        result = asyncio.run(process_email_queue())
        if result.get("sent", 0) == 0 and result.get("failed", 0) == 0:
            print("pass    : the worker moved nothing — stopping to avoid a spin", file=sys.stderr)
            break

    sent = failed = 0
    for sk in own_keys:
        status = (
            table.get_item(
                Key={"pk": f"EVENT#{event_id}", "sk": sk},
                ProjectionExpression="#s",
                ExpressionAttributeNames={"#s": "status"},
            )
            .get("Item", {})
            .get("status")
        )
        if status == "sent":
            sent += 1
        else:
            failed += 1
    return sent, failed


def main() -> int:
    args = parse_args()
    subject, text, html = resolve_bodies(args)

    recipients = list(args.to)
    if args.to_file:
        recipients += read_recipients(args.to_file)

    # De-duplicate case-insensitively but keep the original spelling and order.
    seen_lower: set[str] = set()
    deduped: list[str] = []
    for address in recipients:
        if address.lower() not in seen_lower:
            seen_lower.add(address.lower())
            deduped.append(address)
    if len(deduped) != len(recipients):
        print(f"note    : {len(recipients) - len(deduped)} duplicate address(es) dropped")
    recipients = deduped

    if args.limit is not None:
        if args.limit < len(recipients):
            print(f"note    : --limit {args.limit} of {len(recipients)} recipients")
        recipients = recipients[: args.limit]

    print(f"subject : {subject}")
    print(f"event   : {args.event_id}")
    print(f"bodies  : text {len(text)} chars, html {len(html) if html else 0} chars")
    if len(recipients) <= BULK_CONFIRM_THRESHOLD:
        print(f"to      : {', '.join(recipients)}")
    else:
        print(
            f"to      : {len(recipients)} recipients "
            f"({', '.join(recipients[:2])}, … , {recipients[-1]})",
        )
        minutes = round(len(recipients) * SECONDS_PER_MAIL / 60)
        passes = -(-len(recipients) // WORKER_BATCH)
        print(f"estimate: ~{passes} worker passes, ~{minutes} min (the worker paces its sends)")

    if args.dry_run:
        print("\n--- text ---")
        print(text)
        print("--- dry run: nothing written, nothing sent ---")
        return 0

    if len(recipients) > BULK_CONFIRM_THRESHOLD and not args.yes:
        print(
            f"\nABORT: {len(recipients)} recipients is more than "
            f"{BULK_CONFIRM_THRESHOLD}. Re-run with --yes once the list is the one "
            "you mean. --dry-run prints the mail, --limit N sends a trial slice.",
            file=sys.stderr,
        )
        return 1

    settings = get_email_settings()
    local_credentials = all(
        [settings.smtp_username, settings.smtp_password, settings.smtp_sender_email],
    )
    print(f"sender  : {settings.smtp_sender_name} <{settings.smtp_sender_email or '?'}>")

    if args.drain and not local_credentials:
        print(
            "\nABORT: --drain sends from here, but there are no SMTP credentials in "
            "the environment. The worker would mark these messages as sent WITHOUT "
            "sending them.\nRun under `direnv exec .`, or drop --drain and let the "
            "scheduled worker do it.",
            file=sys.stderr,
        )
        return 1

    if not args.drain and not args.queue_only:
        # Queueing hands the mails to a Lambda that fires every minute. If that
        # Lambda has no credentials it does not fail — it marks every message
        # as sent without sending it, and 850 mails are gone in under an hour
        # with nothing left to retry. Exactly what happened on 2026-08-20.
        state = deployed_worker_smtp()
        print(f"worker  : deployed SMTP {state}")
        if state != "configured" and not args.force:
            print(
                "\nABORT: the deployed worker cannot send. Queued rows would be "
                "silently marked as sent within the minute.\n"
                "Fix: deploy with the SMTP variables in the environment. "
                "Or use --drain to send from here, --queue-only to write the rows "
                "deliberately anyway, or --force to override this check.",
                file=sys.stderr,
            )
            return 1

    table = get_messages_table()

    if not args.resend:
        handled = already_handled(table, args.event_id, subject)
        before = len(recipients)
        recipients = [r for r in recipients if r.lower() not in handled]
        if before != len(recipients):
            print(
                f"skip    : {before - len(recipients)} recipient(s) already have this "
                "subject on this event (--resend to mail them again)",
            )
        if not recipients:
            print("\nNothing left to send — every recipient already had it.")
            return 0

    # Bulk mail without an unsubscribe route is what spam filters are for. The
    # address is the sender's own, per RFC 2369, so replies land where the rest
    # of the Fundsachen traffic does.
    unsubscribe = None
    if len(recipients) > BULK_CONFIRM_THRESHOLD and not args.no_list_unsubscribe:
        unsubscribe = f"<mailto:{settings.smtp_sender_email}?subject=unsubscribe>"

    now = datetime.now(timezone.utc)
    own_keys: set[str] = set()

    for recipient in recipients:
        message_id = uuid.uuid4()
        sk = f"MSG#{message_id}"
        table.put_item(
            Item={
                "pk": f"EVENT#{args.event_id}",
                "sk": sk,
                "id": str(message_id),
                "event_id": args.event_id,
                "type": "custom",
                "direction": "outbound",
                "status": "queued",
                "recipient_email": recipient,
                "subject": subject,
                "body": text,
                **({"body_html": html} if html else {}),
                **({"list_unsubscribe": unsubscribe} if unsubscribe else {}),
                "retry_count": 0,
                "created_at": now.isoformat(),
            },
        )
        own_keys.add(sk)
        if len(recipients) <= BULK_CONFIRM_THRESHOLD:
            print(f"queued  : {recipient}  {sk}")
    if len(recipients) > BULK_CONFIRM_THRESHOLD:
        print(f"queued  : {len(own_keys)} rows written")

    if args.queue_only:
        print(
            f"\n--queue-only: {len(own_keys)} row(s) written. NOTE: the scheduled "
            "worker runs every minute, so these go out anyway unless you delete them.",
        )
        return 0

    if not args.drain:
        minutes = max(1, -(-len(own_keys) // WORKER_BATCH))
        print(
            f"\nHanded over: {len(own_keys)} row(s) queued. The scheduled worker runs "
            f"every minute and takes {WORKER_BATCH} per pass, so this should be through "
            f"in roughly {minutes} minute(s) — no need to keep this shell open.\n"
            "Watch the backlog shrink with:\n"
            f"  aws dynamodb scan --table-name {get_settings().dynamodb_table_prefix}"
            '-messages --filter-expression "#s = :q" '
            "--expression-attribute-names '{\"#s\":\"status\"}' "
            "--expression-attribute-values '{\":q\":{\"S\":\"queued\"}}' --select COUNT",
        )
        return 0

    strangers = foreign_queued(table, own_keys)
    if strangers and not args.allow_foreign_queue:
        print(
            f"\nABORT: {len(strangers)} unrelated message(s) are also queued "
            f"({', '.join(strangers[:5])}) and the worker would send them too.\n"
            "The rows for this run are written and stay queued. Deal with the "
            "others, then re-run with --queue-only omitted, or pass "
            "--allow-foreign-queue to send everything.",
            file=sys.stderr,
        )
        return 1

    sent, failed = drain(table, args.event_id, own_keys)
    print(f"\nresult  : {sent} sent, {failed} not sent")

    if failed:
        for sk in sorted(own_keys):
            item = table.get_item(Key={"pk": f"EVENT#{args.event_id}", "sk": sk}).get("Item", {})
            if item.get("status") != "sent":
                print(
                    f"  failed: {item.get('recipient_email', '?')} "
                    f"status={item.get('status', '?')} {item.get('error_message', '')}",
                )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
