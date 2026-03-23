# 005 — Registration Management Page & Group Member Names

## Summary

Replace the separate confirmation and cancellation pages with a single **registration management page**. This page is the user's central hub for all post-registration actions: confirming participation, providing group member names, adjusting group size, and cancelling. All emails link to this one page instead of separate confirm/cancel URLs.

Additionally, collect the **full names of all group members** upon confirmation to satisfy the passenger list requirement.

## Problem

1. Organizers need a complete passenger list with names of all individuals — not just the person who registered. Group registrations currently only capture one name.
2. Groups may partially shrink after confirmation. Currently, the only option is to cancel the entire registration.
3. Users have separate links for confirming and cancelling, which is confusing. A single management page is simpler.

## Registration Management Page

### Single Entry Point

- URL: `/registration/{registrationId}?token={token}`
- Replaces both `/confirm/{registrationId}` and `/cancel/{registrationId}`
- All emails (registration confirmation, lottery result, promotion, reminders) link here
- The old `/confirm` and `/cancel` routes redirect to the new management page for backward compatibility

### Page Layout

The page follows a consistent visual hierarchy across all states:

1. **Status banner** (full-width, color-coded) — tells the user where they stand at a glance
2. **Primary action area** — the one thing the system needs from them right now
3. **Secondary actions** (visually de-emphasized, bottom of page) — cancel, edit names when not the primary task

### UI States

- **Loading**: "Anmeldung wird geladen..." with spinner
- **Saving** (name edits, member removal): Button shows "Wird gespeichert..." with disabled state
- **Cancelling**: Button shows "Wird storniert..." with disabled state
- **Error**: Inline error message in context of the failed action

### State-Dependent Views

**REGISTERED** (pre-lottery)
- Status banner (gray): "Deine Anmeldung ist eingegangen. Nach Anmeldeschluss wird per Los entschieden."
- Show registration details (name, email, group size)
- Cancel button available (secondary area)

**CONFIRMED** (lottery winner, awaiting acknowledgement)
- Status banner (green): "Du hast einen Platz bekommen!"
- Confirmation form (primary action):
  - "Bitte trage die Namen aller Mitfahrenden ein"
  - Name fields equal to `group_size` — first field pre-filled with registrant's name (editable)
  - All name fields are **required** to confirm
  - User may reduce group size by removing name fields (minimum 1). Freed spots accumulate for batch waitlist promotion (see below).
  - User may **not** increase group size beyond the original registration.
  - Submit confirms participation → status transitions to `PARTICIPATING`
- For **solo registrations** (group_size=1): the single name field is pre-filled. The form is minimal — essentially just a confirm button with the pre-filled name visible.
- Cancel button available (secondary area)

**PARTICIPATING** (confirmed attendance)
- Status banner (green): "Du bist dabei!"
- Group member list (primary area):
  - All names are editable (including the registrant's own name). Name changes save immediately.
  - Additional members (not the registrant) have a remove button. Removal saves immediately.
  - The registrant (first entry) **cannot** be removed — to leave entirely, they must cancel the whole registration.
  - Minimum group size is 1 (the registrant alone).
  - No email is sent on member removal or name change — on-screen confirmation only.
- Cancel button (secondary area, visually de-emphasized):
  - Triggers a **two-button confirmation dialog** with warning: "Du hast deinen Platz über die Verlosung bekommen. Eine Stornierung ist endgültig und kann nicht rückgängig gemacht werden."
  - Buttons: "Abbrechen" / "Endgültig stornieren"
  - On confirm → status transitions to `CANCELLED`

**WAITLISTED** (lottery loser)
- Status banner (gray): "Du stehst auf der Warteliste. Sobald ein Platz frei wird, wirst du benachrichtigt."
- No waitlist position shown (per spec 004)
- Cancel button available (secondary area)

**CANCELLED**
- Status banner (red): "Deine Anmeldung wurde storniert."
- No actions available. Re-confirmation is forbidden.
- Brief message: "Eine erneute Anmeldung ist über diese Reservierung nicht möglich."

**CHECKED_IN**
- Status banner (green): "Du bist eingecheckt. Viel Spaß!"
- Show group member list (read-only)
- No actions available

## Group Member Names

### Data Model
- Each registration stores a list of group member names: `group_members: list[str] | None`
- When populated, the list length must equal `group_size`
- The first entry is the registrant's own name (pre-filled, editable)
- Group members are stored as simple strings (full names), no separate email/contact per member

### Collection Flow
- Group member names are **required** when confirming participation (CONFIRMED → PARTICIPATING)
- All name fields must be filled to submit the confirmation
- For solo registrations (group_size=1), the name is pre-filled — the user just confirms
- After confirmation, names can be edited at any time while PARTICIPATING
- The group member list can be modified after confirmation: names can be changed and members can be removed

### Group Size Reduction
- A user may remove group members from the management page (PARTICIPATING state)
- The registrant (first entry) cannot be removed — only additional members
- Removing a member decreases `group_size` by 1 and removes the name from `group_members`
- Removal saves immediately to the database
- Freed spots are **not** immediately promoted from the waitlist — they accumulate and are filled via a daily batch job (see Waitlist Promotion below)
- No email notification is sent to the registrant on member removal — on-screen confirmation only
- Increasing group size is never allowed — it would bypass the lottery

### Waitlist Promotion for Freed Spots
- Spots freed by group size reductions are **not** promoted immediately. Immediate promotion would unfairly favor solo registrants over groups on the waitlist.
- Instead, a **daily batch job runs at 12:00 (noon)** to promote waitlisted registrations into accumulated freed spots.
- The batch job considers group sizes: a group of 3 on the waitlist is only promoted if 3+ spots are available.
- Full cancellations (entire registration cancelled) continue to trigger immediate waitlist promotion as before — this behavior is unchanged.

## Cancellation Rules

- Cancellation is allowed from: `REGISTERED`, `CONFIRMED`, `WAITLISTED`, `PARTICIPATING`
- Cancellation is **one-time and irreversible**
- A cancelled registration cannot be re-confirmed under any circumstances
- After cancellation, the management page shows the cancelled state with no available actions
- Cancellation from `PARTICIPATING` requires an explicit two-button confirmation dialog (see state-dependent views above)
- Cancellation from `REGISTERED`, `CONFIRMED`, or `WAITLISTED` uses a simpler single-step confirmation (lower stakes)
- Freed spots from full cancellation trigger **immediate** waitlist promotion (existing behavior, unchanged)

## Email Changes

- All emails replace the separate confirm/cancel links with a single link to the management page
- Link text: "Anmeldung verwalten" (manage registration)
- The lottery winner email links to the management page where the user confirms and enters group names
- The auto-confirm URL parameter (`?response=yes`) is removed — confirmation now requires entering group member names, so it cannot be a one-click action
- Reminder emails for PARTICIPATING registrations with incomplete group member names include: "Bitte trage noch die Namen aller Mitfahrenden ein"

## Admin Visibility

- The admin registration table shows group member names (expandable row or tooltip for groups)
- Admins can **edit group member names** directly in the admin UI (e.g., to correct typos or enter legal names for the passenger list)
- The existing CSV export is extended with a "Mitfahrende" column containing all group member names (comma-separated)
- If `group_members` is incomplete (fewer names than `group_size`), the admin UI shows a hint: "X von Y Namen eingetragen"

## Backward Compatibility

The system is live with open events and existing registrations. All changes must be non-breaking.

### URL Migration
- Existing `/confirm/{id}?token={token}` URLs redirect to `/registration/{id}?token={token}`
- Existing `/cancel/{id}?token={token}` URLs redirect to `/registration/{id}?token={token}`
- The `?response=yes|no` query parameter is silently ignored on the new page but does not cause errors
- Links already sent in previous emails must continue to work

### Data Model Migration
- **No DynamoDB schema migration is needed.** The new `group_members` field is added with a runtime default.
- Deserialization: `group_members = item.get("group_members", None)`
- When `group_members` is `None` (existing registrations), the system derives it as `[registration.name]` — the registrant's name is treated as the sole known group member.
- The `group_size` field remains the authoritative count for capacity calculations. `group_members` is informational (passenger list). If `len(group_members) < group_size`, the admin UI shows a hint that not all names have been provided yet.
- New registrations created after deployment will also start with `group_members = None` — names are only collected at confirmation time, not at registration time.

### Existing Registrations in Active Events
- **REGISTERED**: No impact. They will see the new management page when they next click a link.
- **CONFIRMED** (awaiting acknowledgement): When they visit the management page, they are prompted to enter group member names as part of confirmation. This is new behavior but not disruptive — they haven't confirmed yet.
- **PARTICIPATING** (already confirmed before this feature): Their `group_members` is `None`, derived as `[name]`. They can visit the management page to add the remaining names. Admins can also nudge them via a custom message with the management link.
- **WAITLISTED / CANCELLED**: No impact.

### Transition Period
- For the currently active event, some users may have already confirmed (PARTICIPATING) without providing group member names. The admin passenger list will show incomplete data for these registrations, clearly marked as "X von Y Namen eingetragen".
- Admins can send a custom message to all PARTICIPATING users asking them to visit the management page and fill in group member names.
