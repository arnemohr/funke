# 015 — Preferred Registration (Organiser Link)

**Status:** recommendation, pre-implementation
**Author:** Arne
**Date:** 2026-04-21

## Context

Funke already supports `promoted` — an admin flag on a `Registration` that guarantees placement, consumed by `LotteryService.run_lottery` before the shuffled draw (`backend/app/services/lottery_service.py:132`). Promoted regs are awarded winning slots first; remaining capacity is drawn at random.

We want a self-service version: the event organiser gets their own registration link that auto-promotes anyone who uses it, so they can register themselves and their crew without asking an admin.

## TL;DR recommendation

1. **Reuse `promoted`; do not add a new state or any quota.** Registrations made via the organiser link simply set `promoted=True`.
2. **Auto-promote** (confirmed via lottery's existing promoted-wins-first path, no draw).
3. **One field on `Event`** (`organiser_link_token`). No new entity, no quota, no counting logic.
4. **Trust model:** the organiser is trusted not to share the link publicly. If they do, the admin rotates the token.

## Data model

Add to `Event` (`backend/app/models/event.py`):

| Field | Type | Notes |
|---|---|---|
| `organiser_link_token` | `str \| None` | Opaque URL-safe token. Generated on demand from the admin UI. Separate from `registration_link_token` so it can be rotated/revoked independently. `None` disables the feature for this event. |

That is the entire model change. No `organiser_quota`, no `promotion_source`, no new entity. We can add those later if we need auditability or tighter blast-radius control.

## Registration flow

**Endpoint:** extend `POST /events/{link_token}/registrations` (`backend/app/api/public/registrations.py`) to accept an optional query parameter `?organiser=<organiser_link_token>`.

Service logic:

1. If `organiser` param present and matches `event.organiser_link_token` **and** event status is `OPEN` or `REGISTRATION_CLOSED`: set `promoted=True` on the new registration. Lottery treats as winner.
2. If `organiser` param present but mismatched or event past `REGISTRATION_CLOSED`: treat as normal public registration (don't 404, don't reject — just ignore the param silently, or return a soft notice).
3. If `organiser` param absent: existing public flow, unchanged.

Nothing else changes in the public flow. The public event page keeps showing `capacity` as today.

## Lottery interaction

No new invariants. Walking through `run_lottery` (`lottery_service.py:132`):

- Line 161–169 already validates `len(promoted) ≤ capacity`. If the organiser over-invites, the lottery refuses to run until the admin intervenes — acceptable, and arguably the right behaviour (forces a human decision rather than silently dropping crew).
- Promoted path (winners first, then shuffle the rest into waitlist) handles organiser regs with zero additional code.
- `LotteryRun.promoted_ids` audit trail already captures them.

**Risk — organiser registers post-draw:** if event has advanced past `REGISTRATION_CLOSED`, flipping `promoted=True` is too late. Handling: disable the organiser link once event status passes `REGISTRATION_CLOSED`. Organiser falls back to admin `promote-from-waitlist`.

**Risk — organiser over-invites:** lottery validation blocks the draw with a clear error. Admin resolves by un-promoting some regs or raising capacity. No silent failures.

## UX decision: auto-promote vs. promote-on-draw

**Recommendation: auto-promote.**

**Why:**
- **Organiser mental model.** They're staffing an event. They need to tell their crew "you're in" today, not "you're probably in." Any uncertainty defeats the feature — they'd just ask an admin to promote manually, which is exactly what we're replacing.
- **Consistency with existing feature.** Admin-side `promote` is already auto-promote in spirit — the flag guarantees a slot without a draw. Promote-on-draw would be a third semantic that doesn't match anything we do.
- **Fairness signalling.** Public registrants see the same lottery they always see. Organiser regs ride the existing promoted column in the admin view — no new public-facing concept.

## Emails

Two emails are affected by this feature:

**Registration confirmation (immediate):** needs a variant for orga-crew-link regs. The default copy mentions the lottery and asks the registrant to wait for the draw result — that's misleading for someone who already has a guaranteed slot, and it undermines the value of the link (the crew will ask the organiser "am I really in?"). New variant copy, roughly:

> Hallo [Name], du bist über den Orga-Crew-Link für [Event] angemeldet und hast einen festen Platz. Bitte bestätige deine Teilnahme bis [Bestätigungsdeadline].

No lottery language, no "wait for the draw."

**Lottery outcome email (post-draw):** no change. The existing winner copy ("du hast einen Platz, bitte bestätige deine Teilnahme") is accurate for both lottery winners and promoted regs — promoted regs become `CONFIRMED` in the same finalisation step and receive the same email, which reads correctly in both cases.

Implementation: the email service picks the variant based on `registration.promoted` at send time. One template, one conditional branch — no new email plumbing.

## Admin UX

`frontend/src/components/EventForm.vue`:

- Add an **"Orga-Crew-Link"** section that always shows the current link. The token is generated lazily on first access — the admin never sees a "generate" button. From their perspective the link has always existed.
- Primary action: **copy button** next to the link.
- Secondary action: button labelled **"Orga-Crew-Link erzeugen"** — opens a confirmation dialog:
  > **Neuen Orga-Crew-Link erzeugen?**
  > Der bisherige Link wird dadurch ungültig. Bereits über den alten Link angemeldete Personen behalten ihren Platz, aber der alte Link funktioniert nicht mehr. Teile den neuen Link anschließend mit dem Orga-Crew.
  >
  > [Abbrechen] [Neuen Link erzeugen]
- No "remove link" action in v1. If the organiser should stop using it, just don't share the new link. If it leaked, rotate.

**Backend:** the GET endpoint that loads event admin details generates and persists `organiser_link_token` if it's null at read time. The rotate endpoint always generates a fresh token, overwriting the previous one.

In `RegistrationTable.vue` organiser regs show up in the existing promoted column with the current checkbox/badge — no distinction needed for v1.

## Edge cases

| Case | Handling |
|---|---|
| Organiser registers after `REGISTRATION_CLOSED` | Organiser link is disabled past this status. Admin uses existing promote/promote-from-waitlist flow. |
| Organiser link leaked publicly | Admin rotates the token from the event edit view. Already-promoted regs keep their spot; new uses of the old token are ignored. |
| Organiser over-invites (promoted > capacity) | Lottery refuses to draw with a clear error; admin un-promotes or raises capacity. |
| Organiser registers twice via the link | Same as any duplicate — existing registration flow's duplicate handling applies. |

## Deferred / open questions

- **Quota.** Cap on guaranteed slots per organiser link. Add when we see real misuse or when organisers ask for self-policing. Schema addition only; flow stays the same.
- **`promotion_source` audit field.** Useful to distinguish admin-promoted from organiser-link-promoted in analytics and the registration table. Add when someone asks for it.
- **Organiser "my crew" view.** Scoped page the organiser can visit to see who has used their link. Defer.
- **Email to organiser on use.** Notify organiser when someone registers via their link. Defer.

## Scope of v1

1. `Event.organiser_link_token` (model + migration).
2. Admin event-detail load lazily generates the token if missing; single rotate endpoint overwrites it.
3. `EventForm.vue` "Orga-Crew-Link" section — copy button + "Orga-Crew-Link erzeugen" button with confirmation dialog.
4. Public registration endpoint accepts `?organiser=` and sets `promoted=True` when token matches and event is in an eligible status.
5. Disable the organiser-link effect once event status > `REGISTRATION_CLOSED`.

Out of v1: quota, `promotion_source`, organiser crew view, notifications.
