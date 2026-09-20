"""Contact details shared by the public event pages (specs 023 + 024).

The lost & found page (023) and the photo upload page (024) both render an
organiser-supplied Telegram link as an ``href`` on a page that anyone holding
the URL can open. Two features writing the same attacker-reachable attribute
must not have two validators for it: the moment they drift, the weaker one
becomes the actual security boundary. So the pattern and the normaliser live
here once, and both feature models import them.

Nothing feature-specific belongs in this module — it exists precisely because
it has no side to take.
"""

import re

# A Telegram handle or invite link, as an alternative to the mail address. The
# value ends up as an `href` on a public page, so it is not stored as typed:
# only `https://t.me/…` survives this pattern, which rules out `javascript:`
# and every other scheme an organiser could paste in by accident or malice.
TELEGRAM_URL_PATTERN = re.compile(
    r"^https://(?:t\.me|telegram\.me)/(?:\+|joinchat/)?[A-Za-z0-9_\-]{4,64}/?$",
)
TELEGRAM_HANDLE_PATTERN = re.compile(r"^@?[A-Za-z0-9_]{4,64}$")


def normalize_telegram_url(value: str | None) -> str | None:
    """Accept what an organiser actually types; store one canonical https URL.

    `@fundsachen`, `t.me/fundsachen` and the full URL all mean the same thing,
    and an invite link (`https://t.me/+AbCd…`) has to survive untouched because
    that hash *is* the address of a private group.

    Raises:
        ValueError: when the result is not a Telegram URL. Never store an
            unrecognised string — it would be rendered as a link.
    """
    if value is None:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    if TELEGRAM_HANDLE_PATTERN.match(candidate):
        candidate = f"https://t.me/{candidate.lstrip('@')}"
    elif candidate.startswith(("t.me/", "telegram.me/")):
        candidate = f"https://{candidate}"
    elif candidate.startswith("http://"):
        # Meaningful for a link, not pedantry: http would send the group hash
        # over the wire in clear.
        candidate = "https" + candidate[4:]

    if not TELEGRAM_URL_PATTERN.match(candidate):
        raise ValueError(
            "Kein Telegram-Link. Erlaubt sind @name, t.me/name oder ein "
            "Einladungslink https://t.me/+…",
        )
    return candidate.rstrip("/")
