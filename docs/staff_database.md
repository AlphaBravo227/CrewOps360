# Staff Database

The staff roster and its attributes live in the application database, not in a
spreadsheet. This document covers what is stored, how it got there, and how to maintain
it. For the schedule data that also moved out of Excel — preassignments, CCEMT schedules
and the 42-day track grid — see [track_data.md](track_data.md).

## Why

Staff identity and attributes used to be re-read from Excel uploads on every page load:

| Spreadsheet | Supplied |
| --- | --- |
| `upload files/Preferences v6.xlsx` | `STAFF NAME`, `ROLE`, `No Matrix`, `Seniority` |
| `upload files/Requirements.xlsx` | `SHIFTS PER PAY PERIOD`, `NIGHT MINIMUM`, `WEEKEND MINIMUM`, `WEEKEND GROUP`, `EMAIL` |
| `training/upload/FY26 Education Classes Roster.xlsx` (`Class_Enrollment`) | `STAFF NAME`, `Role`, `MGMT`, `DUAL`, `Educator AT` |

All of it now comes from the `staff` table. A staff member can be added, edited,
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
| `shifts_per_pay_period` | Required shifts per 14-day period. `NULL` marks non-bidding staff. |
| `night_minimum` | Minimum night shifts per cycle. |
| `weekend_minimum` | Minimum weekend shifts per cycle. |
| `weekend_group` | Weekend group A–E, or `NULL`. |
| `education_group` | Educational cohort `1`–`4`, or `NULL` when unplaced. |
| `or_group` | OR classes required for the year: `0` ("No OR"), `2`, `3` or `4`, or `NULL` when unplaced. |
| `email` | Used for bid notifications and confirmations. |
| `is_active` | Inactive staff keep their history but disappear from staff pickers. |
| `notes`, `created_date`, `modified_date` | Housekeeping. |

Two supporting tables record changes: `staff_audit_log` (every add/update/activate/
deactivate/rename/delete, with a JSON diff) and `staff_name_history` (name changes and
which tables they rewrote).

### Blank is not zero

For `shifts_per_pay_period` (and the two minimums) a blank value means something
different from `0`, and both are preserved:

- **Blank** — this staff member has no shift requirement on file. That is how management
  and other non-bidding staff are marked, and it is what keeps them out of the bid order.
- **0** — a real requirement of zero shifts, carried by probationary staff who work no
  track shifts yet.

Because a number input cannot express "empty", these three fields are typed as text in
the admin form and parsed on save. A value that is neither blank nor a number is
rejected rather than silently clearing the field.

### Educational groupings

Two placements decide which education a staff member is scheduled for, and they are
independent of each other:

- **`education_group`** — the cohort they attend recurring education with: group 1, 2, 3
  or 4. Stored as a label rather than a count.
- **`or_group`** — how many OR classes they have to sign up for over the year: 0
  ("No OR"), 2, 3 or 4. It is a count of required signups, not a cohort label: a 2 signs
  up for two OR classes, a 4 for four, and a 0 for none. A staff member on 0 should not
  see the OR class among the ones they need, and it should add nothing to their yearly
  class total.

Both are `NULL` until someone is placed. For the OR grouping the blank-is-not-zero rule
above applies again, and matters more here than anywhere else: `0` means *placed, and
required to sign up for none*, while `NULL` means *nobody has placed them yet*.

That distinction is the one thing to get right when class generation reads this field.
Test for placement against `None`, and use the value itself as the count — testing it
for truthiness silently treats a required count of zero as an unplaced staff member:

```python
required = staffdb.get_or_group(name)
if required is None:
    ...                  # nobody has placed them — a gap to flag, not a zero
else:
    ...                  # they sign up for exactly `required` OR classes; 0 means none
```

They are read back either per staff member or as whole cohorts:

```python
staffdb.get_education_group('Bach')            # '3'
staffdb.get_or_group('Ahlstedt')               # 0

staffdb.get_education_group_members('Group 1') # the cohort, in roster order
staffdb.get_or_group_members('No OR')          # same, by OR placement
staffdb.get_education_group_mapping()          # {name: group} for everyone placed
staffdb.get_or_group_mapping()
```

The membership helpers and the normalizers accept the placement sheets' own spellings
("Group 1", "No OR", "2 OR") as well as plain values, so a heading can be passed
straight through.

Only clinical staff are placed. Management, the non-clinical roles (COMMS, CCEMT, ATP,
AMT) and the newest hires are expected blanks, so the admin page and
`get_roster_issues()` flag an unplaced staff member only when they actually work tracks
— a clinical role with a shift requirement on file.

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

A staff member imported from a track file who is not on the education roster has no role
on file. Rather than guess one, the import stores `UNASSIGNED` and the admin page lists
them for someone to resolve. Four such names exist today: Chaber, DiNardo, Noland,
Shewan.

## Maintaining the roster

Clinical Track Hub → sidebar **Admin Area** → **Manage Staff Database**. The page is
admin-password gated and has five tabs:

- **Roster** — filter by name/role/active/management/educational grouping, and download
  as CSV.
- **Add Staff** — new hires, including their shift requirements.
- **Edit / Rename / Remove** — attributes, requirements, active status, name changes,
  deletion.
- **Import from Excel** — first-time seed and later refreshes, plus seeding the
  educational groupings.
- **History** — the audit log and past name changes.

The page also flags anything needing attention: staff with no role, clinical staff with
no seniority, duplicate seniority ranks, non-management clinical staff with no shift
requirement, bidding staff with no email, and track-working staff with no educational
grouping.

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

- **Blanks are filled, values are not overwritten.** A field the roster has nothing for
  yet is always filled in from the spreadsheet — that is how an existing database picks
  up new columns without losing anything. A field that is already set and disagrees with
  the spreadsheet is left alone and reported, unless `--update-existing` is passed.
- **Conflicts are reported.** Where the two spreadsheets disagree, `is_dual` is the union
  of both sources (Preferences v6 lists Puopolo as dual while the roster's DUAL box is
  unchecked — dropping the flag would change how they're counted for staffing).
- **Shift preferences are carried over.** Each staff member's Preferences v6 base-shift
  scores, `Reduced Rest OK` and `N to D Flex` are seeded into the tables the in-app
  preference editor reads (`user_preferences`, `user_boolean_preferences`), so nothing is
  lost when the spreadsheet stops being consulted. Preferences a staff member has
  already saved in the app are not touched unless `--overwrite-preferences` is passed.

### Seeding the educational groupings

The two placement sheets are two flat columns-of-names with no staff key of their own —
there is nothing to key an import on and nothing to re-read later — so they are
transcribed into `modules/educational_groupings.py` rather than read from a workbook.
Seeding them places everyone the sheets name in one pass, so the groupings never have
to be entered by hand.

Once the roster exists, from the admin page: **Import from Excel** tab →
**Seed Educational Groupings**. *Preview* reports what would change without writing;
*Seed groupings* applies it. Or on the command line:

```bash
python scripts/seed_educational_groupings.py --dry-run    # report only
python scripts/seed_educational_groupings.py              # apply
python scripts/seed_educational_groupings.py --overwrite  # let the sheets win
```

Both run the same `seed_groupings()`, and neither needs the app to be stopped.

Like the roster import, a placement already on file is reported rather than overwritten
unless overwrite is asked for, so a re-seed never quietly undoes an edit made on the
Edit tab. The report names every entry that does not line up: sheet names with no roster
row, names listed in two columns of the same sheet, staff who work tracks but appear on
neither sheet, and staff on one sheet but not the other.

As transcribed, against the FY27 roster, that is:

| | |
| --- | --- |
| On a sheet, not on the roster | `Wheeler` (No OR) — no such staff member exists in any source |
| Works tracks, on neither sheet | `Johnson` |
| OR placement but no cohort | `Farkas`, `Frakes`, `Muszalski` (management); `Grotton`, `Lurie`, `McWeeney` (new hires); `O'Flaherty`, `Phelan`, `VanderKooi` (0 shifts) |
| Cohort but no OR placement | `Powers` (management) |

Five sheet spellings, covering four staff members, differ from the roster and are
mapped in the script's `ALIASES`: `Hanley` → `Hanley-McCarthy`, `Steck`/`Steckewicz` → `Steckevicz`,
`Murphy E` → `Murphy`, `Parkas` → `Farkas`. Case, spacing and punctuation are folded
away separately, which is what lets the sheets' `O'Donnell` and `Vanderkooi` reach the
roster's `O’Donnell` and `VanderKooi`.

Everything left over is a decision rather than data entry, and belongs on the **Edit**
tab: `Wheeler`, `Johnson`, and whichever of the partly-placed staff should hold the
other placement.

## Reading the roster in code

```python
from modules.staff_database import (
    get_staff, get_all_staff, get_staff_names,
    get_role, get_clinical_role, get_effective_role,
    is_management, is_dual, is_educator_at, get_no_matrix, get_seniority,
    get_shifts_per_pay_period, get_night_minimum, get_weekend_minimum,
    get_weekend_group, get_email, get_education_group, get_or_group,
    get_education_group_members, get_or_group_members,
    get_role_mapping, get_seniority_mapping, get_no_matrix_mapping,
    get_requirements_map, get_education_group_mapping, get_or_group_mapping,
    build_preferences_df, build_requirements_df,
)
```

`build_preferences_df()` and `build_requirements_df()` return DataFrames with
Preferences v6's and Requirements' exact column layouts, built from the database. They
are what `app.py` and `modules/track_bidding.py` hand to the validators, the PDF
generator, the hypothetical scheduler and the admin exports, so none of that code had to
change.

Reads are cached in-process and the cache is invalidated on every mutation, and whenever
the database file changes underneath (for example a restore from backup).

## Still Excel-driven

One file remains: `training/upload/FY26 Education Classes Roster.xlsx` still supplies
**classes, class dates, per-staff class assignments and educator requirements** to the
Training & Events module. Its staff columns (Role, MGMT, DUAL, Educator AT) are no longer
read at runtime — only when an import is run.

Nothing in `upload files/` is read at runtime any more.

## Checking it

```bash
python scripts/check_staff_database.py
```

Imports the spreadsheets into a throwaway database and verifies that every attribute
round-trips identically, that `build_preferences_df()` and `build_requirements_df()`
match the spreadsheets' layouts and values (including blank-vs-zero), and that
add/update/activate/rename/delete behave — including that a rename follows the staff
member into other tables. It also seeds the educational groupings and checks that every
column places the staff it lists, that a `No OR` placement survives as `0` rather than
collapsing into "unplaced", and that the sheets' name mismatches are still the ones
listed above.
