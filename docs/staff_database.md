# Staff Database

The staff roster and its attributes live in the application database, not in a
spreadsheet. This document covers what is stored, how it got there, how to maintain it,
and what still reads from Excel.

## Why

Staff identity and attributes used to be re-read from Excel uploads on every page load:

| Spreadsheet | Supplied |
| --- | --- |
| `upload files/Preferences v6.xlsx` | `STAFF NAME`, `ROLE`, `No Matrix`, `Seniority` |
| `training/upload/MASTER Education Classes Roster.xlsx` (`Class_Enrollment`) | `STAFF NAME`, `Role`, `MGMT`, `DUAL`, `Educator AT` |

Those attributes now come from the `staff` table. A staff member can be added, edited,
deactivated, renamed or removed in the app, and the change takes effect everywhere at
once.

## What is stored

Table `staff` (in `data/medflight_tracks.db`):

| Column | Meaning |
| --- | --- |
| `staff_name` | The name every other table joins on. Unique, case-insensitive. |
| `role` | Base role: `NURSE`, `MEDIC`, `COMMS`, `CCEMT`, `ATP`, `AMT` (or `UNASSIGNED`, see below). |
| `is_management` | The roster's `MGMT` checkbox. |
| `is_dual` | The roster's `DUAL` checkbox — a nurse who also works as a medic. |
| `is_educator_at` | The roster's `Educator AT` checkbox: may sign up to teach. |
| `no_matrix` | Preferences v6's `No Matrix` flag. |
| `seniority` | Rank, 1 = most senior. Unique across the roster. `NULL` for staff who don't bid. |
| `is_active` | Inactive staff keep their history but disappear from staff pickers. |
| `notes`, `created_date`, `modified_date` | Housekeeping. |

Two supporting tables record changes: `staff_audit_log` (every add/update/activate/
deactivate/rename/delete, with a JSON diff) and `staff_name_history` (name changes and
which tables they rewrote).

### Role vs. dual

The education roster carries a base `Role` plus a separate `DUAL` checkbox.
Preferences v6 collapsed the two into a single `nurse`/`medic`/`dual` value, which is
what most of the track code wants. That collapsed value is derived, not stored:

```
clinical_role  = 'dual' if is_dual else role.lower()   # nurse / medic / dual
effective_role = 'medic' if clinical_role == 'medic' else 'nurse'
```

`effective_role` is the staffing bucket — dual providers count as nurses.

### `UNASSIGNED`

A staff member imported from `Tracks.xlsx` / `Requirements.xlsx` /
`Preassignments.xlsx` who is not on the education roster has no role on file. Rather
than guess one, the import stores `UNASSIGNED` and the admin page lists them for someone
to resolve. Four such names exist today: Chaber, DiNardo, Noland, Shewan.

## Maintaining the roster

Clinical Track Hub → sidebar **Admin Area** → **Manage Staff Database**, or navigate to
the `staff_database` module directly. The page is admin-password gated and has five tabs:

- **Roster** — filter by name/role/active/management, and download as CSV.
- **Add Staff** — new hires.
- **Edit / Rename / Remove** — attributes, active status, name changes, deletion.
- **Import from Excel** — first-time seed and later refreshes.
- **History** — the audit log and past name changes.

### Someone leaves

Mark them **inactive**. They drop out of every staff picker (track management, bidding,
class enrollment, summer leave, location preferences) while their tracks, bids and
enrollments stay intact. Deleting is refused while other records reference the name,
precisely so history isn't orphaned.

### Someone changes their name

Use **Change Name** on the Edit tab. Because the staff name is the join key, the rename
updates the roster row *and* every staff-name reference in the database in one
transaction — tracks, track history, bid drafts, bid access, preassignments, swaps,
location and shift preferences, summer leave, training enrollments and educator signups.
The Edit tab shows how many rows are filed under the current name before you commit, and
the result reports what it rewrote.

Columns treated as staff names: `staff_name`, `requester_name`, `other_member_name`,
`submitted_by`, `next_staff` (see `STAFF_NAME_COLUMNS` in `modules/staff_database.py`).
They are discovered against the live schema, so a new table with a `staff_name` column
gets rename support without code changes.

### Seniority

Ranks must be unique — a duplicate makes bid ordering ambiguous, so the form rejects it
and the admin page flags any duplicates that got in another way. Nurses and medics
without a rank are skipped when the bid order is built, and are listed on the admin page
for that reason.

## Importing / re-importing

From the admin page, or on the command line:

```bash
python scripts/seed_staff_database.py --dry-run     # report only
python scripts/seed_staff_database.py               # first-time seed
python scripts/seed_staff_database.py --update-existing   # let the spreadsheets win
```

Behavior worth knowing:

- **Idempotent.** Staff already on the roster are left alone unless
  `--update-existing` is passed, so a re-import never silently overwrites an admin's
  edits. Differences are reported instead.
- **Conflicts are reported.** Where the two spreadsheets disagree, `is_dual` is the union
  of both sources (Preferences v6 lists Puopolo as dual while the roster's DUAL box is
  unchecked — dropping the flag would change how they're counted for staffing).
- **Shift preferences are carried over.** Each staff member's Preferences v6 base-shift
  scores, `Reduced Rest OK` and `N to D Flex` are seeded into the tables the in-app
  preference editor reads (`user_preferences`, `user_boolean_preferences`), so nothing is
  lost when the spreadsheet stops being consulted. Preferences a staff member has
  already saved in the app are not touched unless `--overwrite-preferences` is passed.

## Reading the roster in code

```python
from modules.staff_database import (
    get_staff, get_all_staff, get_staff_names,
    get_role, get_clinical_role, get_effective_role,
    is_management, is_dual, is_educator_at, get_no_matrix, get_seniority,
    get_role_mapping, get_seniority_mapping, get_no_matrix_mapping,
    build_preferences_df,
)
```

`build_preferences_df()` returns a DataFrame with Preferences v6's exact column layout,
built from the database. It is what `app.py` and `modules/track_bidding.py` hand to the
validators, the PDF generator, the hypothetical scheduler and the admin exports, so none
of that code had to change.

Reads are cached in-process and the cache is invalidated on every mutation, and whenever
the database file changes underneath (for example a restore from backup).

## Still Excel-driven

This change covers staff identity and the six attributes listed above. These remain
Excel uploads:

| File | Still supplies |
| --- | --- |
| `training/upload/MASTER Education Classes Roster.xlsx` | Classes, class dates, per-staff class assignments, educator requirements (planned to move later) |
| `upload files/Tracks.xlsx` | The active 42-day track grid and the CCEMT tab |
| `upload files/Requirements.xlsx` | Shifts per pay period, night/weekend minimums, weekend group, email |
| `upload files/Preassignments.xlsx` | Per-cycle AT preassignments and the bid cycle's day schema |

`upload files/Preferences v6.xlsx` is no longer read at runtime — only when an import is
run from the admin page or the seed script.

## Checking it

```bash
python scripts/check_staff_database.py
```

Imports both spreadsheets into a throwaway database and verifies that every attribute
round-trips identically, that `build_preferences_df()` matches the spreadsheet's layout
and values, and that add/update/activate/rename/delete behave — including that a rename
follows the staff member into other tables.
