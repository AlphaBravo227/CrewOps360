# Fiscal years in the Clinical Track Hub

A track cohort — `track_configs.track_name`, "FY26", "FY27" — is one fiscal year's worth
of 42-day tracks. A cutover isn't a switch, it's an overlap: FY27's bids are promoted
months before FY26's last shift is worked. Promotion clears `is_active` on FY26's `tracks`
rows, and everything the hub showed was scoped to `is_active = 1`, so the year people
were still working vanished from the hub the day the next one went live.

Each cohort now carries its own lifecycle and its own calendar span, and the hub asks
which fiscal year you want before it loads anything.

| Setting | What it controls |
| --- | --- |
| `status` | Whether the cohort appears in the hub's fiscal-year picker |
| `start_date` / `end_date` | The calendar span its 42-day pattern is projected over |
| `pattern_start_date` | Which calendar date is that cohort's `Sun A 1` |

## The lifecycle

`is_active` still marks the one live cohort — the one every track change is written to.
`status` is separate, and says what the hub does with the cohort:

| Status | In the hub |
| --- | --- |
| `draft` | Hidden. A cohort being built or out to bid has partial data by definition. |
| `open` | Shown, and accepting track changes. Only the live cohort is ever `open`. |
| `readonly` | Shown and fully readable — the year still being worked after a cutover. |
| `archived` | Out of the picker. |

Promoting FY27 moves FY26 to `readonly` rather than out of sight, and FY27 to `open`.
FY26 archives itself once its `end_date` passes, since clearing out last year is exactly
the chore that gets forgotten in the weeks after a cutover. The live cohort is never
retired automatically and can't be frozen or hidden by hand — if its end date has passed
and nothing has been promoted, staff still need somewhere to look.

## Upgrading an install that has already cut over

On a database that predates this, the active cohort becomes `open` and a cohort out to
bid stays `draft`. Among the retired cohorts, the most recently created one becomes
`readonly` — that is the outgoing year, the one the hub exists to keep showing — and
anything older is archived rather than filling the picker with finished years. FY26's
span and anchor are backfilled with the dates the code used to carry hardcoded, and any
cohort already past its end date is retired on the spot.

## What follows the choice, and what doesn't

Picking a year scopes every read: the track grid, the Preferred Track Display, the
fiscal-year monthly display and its Excel export, the calendar export (Google/iCal), the
preassignments the grid is drawn with, and the admin export in the sidebar.

Writes don't move. Track modifications, swap requests and the approval queue all read and
write `tracks` rows with `is_active = 1`, so they belong to the live cohort. On a closed
year the hub drops those controls and says why, rather than offering buttons that would
land on the wrong fiscal year — and a session that switches years mid-edit is dropped
back to the landing page instead of editing one year's grid into another year's rows.

## The span, and why it matters

The fiscal-year display and the calendar export used to carry FY26's dates as literals:
28 Sept 2025 to 26 Sept 2026, with `Sun A 1` on 14 Sept 2025 and the fiscal year starting
14 days into the pattern (`Sun B 3`). Those are FY26's row now, and the offset is derived
from the anchor rather than hardcoded, so a cohort that starts on its own `Sun A 1` gets
an offset of 0 and lands on the right days.

Holidays are generated from the span (the usual ten, by rule rather than by date), which
reproduces FY26's list exactly and keeps working for every year after it.

A cohort with no dates set falls back to FY26's, which is what the code assumed before
cohorts had dates at all.

## Setting it

Track Bidding → **Track Configs**, in each cohort's panel:

- **Fiscal Year Span** — first day, last day and the `Sun A 1` anchor, as `YYYY-MM-DD`.
- **Clinical Track Hub visibility** — the status, for any cohort that isn't the live one.

The Overview tab lists every cohort's hub visibility and span alongside its bid counts.

## Checking it

```bash
python scripts/check_track_years.py
```

Verifies against a throwaway database that a cohort out to bid stays out of the picker,
that promotion leaves the outgoing year visible and read-only while only the live year
accepts changes, that reading a year by name gets that year's tracks rather than the live
one's, that FY26 keeps the exact span, pattern offset and holiday list the code used to
carry hardcoded while another year gets its own, that a year past its last day retires
itself while the live year never does, and that upgrading a pre-feature database leaves
the outgoing year visible rather than archiving it.
