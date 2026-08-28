# Track Data

The three schedule datasets that used to be Excel uploads — the 42-day track grid,
per-cycle preassignments, and the CCEMT group's repeating pattern — now live in the
database. See [staff_database.md](staff_database.md) for staff identity and attributes,
and [track_years.md](track_years.md) for how a track cycle becomes a fiscal year the
Clinical Track Hub can show alongside the live one.

| Was | Now |
| --- | --- |
| `upload files/Tracks.xlsx` sheet 1 (42-day grid) | Built from the `tracks` table — tracks are submitted and approved in the app, so the sheet was a stale copy |
| `upload files/Tracks.xlsx` `CCEMT` tab | `ccemt_schedules` table, editable in Track Data admin |
| `upload files/Preassignments.xlsx` | `track_preassignments` table, per bid cycle |
| Day column headers in both files | Generated — the 42-day pattern is fixed |

## The 42-day pattern

`modules/day_pattern.py` generates the canonical day labels: six weeks, weekdays Sun–Sat,
weeks 1–6, grouped into blocks A (weeks 1–2), B (3–4) and C (5–6) — `"Sun A 1"` through
`"Sat C 6"`. Tracks.xlsx and Preassignments.xlsx carried identical headers, so the schema
was never per-file; it is generated now, and neither spreadsheet is needed to know what
the days are.

```python
from modules.day_pattern import PATTERN_DAYS, days_by_week, is_weekend_day, sort_pattern_days
```

`sort_pattern_days()` orders labels chronologically — a plain string sort puts
`"Mon B 3"` before `"Tue A 2"` even though week 2 comes first.

## Active track grid

`modules/track_roster.py` shapes the `tracks` table like the old spreadsheet:

```python
from modules.track_roster import build_current_tracks_df, get_active_track_rows, get_staff_on_shift

current_tracks_df = build_current_tracks_df()   # STAFF NAME + 42 day columns
```

Every active clinical staff member gets a row whether or not they have submitted a track
— staff without one get a blank row, which is what the editors expect when creating a
track from scratch. (Under the spreadsheet, a staff member missing from the file could
not be selected at all.) Anyone holding an active track who is no longer active clinical
staff is kept in the grid too, and flagged in the Clinical Track Hub admin sidebar.

Track rows submitted before role metadata was recorded have their role resolved from the
staff roster on read, so callers never see a missing role.

## Preassignments

A preassignment is a day a staff member is committed to something other than a normal
shift before bidding starts. They count as day shifts and are locked in the editors.

They are stored per bid cycle in `track_preassignments` (`track_name`, `staff_name`,
`day`, `activity`), so each cycle is authored independently and last cycle's commitments
can be copied forward.

**Where:** Track Bidding → Administration → **Preassignments**, alongside where a bid
cycle is created. The same editor is on the Track Data admin page (Clinical Track Hub →
Admin Area → **Manage Track Data**).

- **Edit a Staff Member** — a six-week grid of activity boxes; clearing a box removes
  that day.
- **All Preassignments** — every staff member's days for the cycle, with a CSV export.
- **Copy / Import** — copy another cycle's preassignments in (the usual way to start a
  new cycle), or import a legacy `Preassignments.xlsx` once.

Reading them in code is unchanged — `load_preassignments()` now reads the database and
returns the same staff-indexed DataFrame, so `get_staff_preassignments()` and
`has_preassignment()` work as before:

```python
from modules.track_management.preassignment import load_preassignments, get_staff_preassignments

preassignment_df = load_preassignments()            # active/bidding cycle
preassignment_df = load_preassignments('FY27')      # a specific cycle
```

Direct access is in `modules/preassignment_db.py` (`get_preassignments`,
`set_staff_preassignments`, `set_preassignment`, `copy_preassignments`,
`delete_preassignments`, `import_preassignments_from_excel`).

## CCEMT schedules

The CCEMT group doesn't bid a 42-day track — they work a fixed **28-day (4-week)** pattern
that repeats from a start date. `ccemt_schedules` holds one row per staff member per day
of the pattern; `ccemt_schedule_config` holds the start date.

**Where:** Track Data admin → **CCEMT Schedules**.

- **Edit a Staff Member** — four weeks of shift-code boxes.
- **Full Pattern** — everyone's pattern in one grid, with a CSV export.
- **Pattern Start / Import** — the start date, and a one-time import of the CCEMT tab.

Shift codes are free text (`GR`, `NG`, `PG`, `LG`, `NL`, `MG`, `NP`, `SIM`, …) and are
classified the way the spreadsheet reader did it: a code starting with `N` is a night
shift, anything else is a day shift.

The start date anchors pattern day 0 to the calendar, so it must be a Sunday — the editor
rejects anything else, since moving it shifts every CCEMT staff member's schedule.
`TrainingTrackManager` reads both the pattern and the start date from the database,
falling back to a Tracks workbook only if the database has no schedules at all.

```python
from modules.ccemt_schedule import get_schedules, get_classified_schedules, get_pattern_start_date
```

## Migrating an existing install

```bash
python scripts/seed_track_data.py --dry-run          # report only
python scripts/seed_track_data.py --track FY26       # preassignments + CCEMT
python scripts/seed_track_data.py --track FY26 --import-tracks   # also the 42-day grid
```

`--import-tracks` loads the legacy grid into the `tracks` table and is refused when
active tracks already exist — tracks are submitted through the app, and overwriting live
ones with a spreadsheet copy would lose approvals and history. `--force-tracks` overrides
that, retiring the current tracks first.

Preassignments and CCEMT schedules likewise refuse to import over existing data unless
`--overwrite` is passed.

## Checking it

```bash
python scripts/check_track_data.py
```

Verifies against a throwaway database that the generated day pattern matches the old
spreadsheet headers exactly, that the built track grid reproduces every cell of
Tracks.xlsx, that preassignments and CCEMT patterns round-trip identically, and that the
editors (set, clear, copy between cycles, delete, start-date validation) behave.
