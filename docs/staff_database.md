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

### Groupings

Which staff a training class is for does not come from a column on the staff row. It
comes from **groupings**: named lists of staff, kept in their own two tables and
maintained on the admin page's **Groupings** tab.

| Table | Holds |
|---|---|
| `staff_groupings` | The grouping: `name`, `description`, `is_active`, `sort_order`. |
| `staff_grouping_members` | One row per membership: `grouping_id` + `staff_name`. |

A grouping means nothing beyond its membership — nothing derives a requirement, a count
or a schedule from its name. "Group 1", "4 OR", "New Hires 2027" and "CCEMT Refresher"
are all the same kind of object, so a new way of carving up the roster is a row in a
table rather than a column, a validator, a picker and a migration.

Membership is many-to-many and unconstrained: a staff member can be in as many
groupings as makes sense, and being in one says nothing about the others. Groupings are
global rather than per training year. When a cohort reshuffles, edit its membership; when
one is superseded, **archive** it — archived groupings keep their membership and stay
readable on the classes that used them, but drop out of the pickers.

Membership is stored by staff name, the join key the rest of the database uses, so a
rename on the Edit tab carries into groupings automatically. Deleting a staff member
takes their memberships with them, and — unlike a track or an enrollment — being in a
grouping never blocks that delete: membership is part of the roster entry, not a record
of something that happened.

```python
from modules import staff_groupings

staff_groupings.get_groupings(with_counts=True)     # for a picker
staff_groupings.get_members(grouping_id)            # active members, roster order
staff_groupings.get_members_of_many([3, 7])         # the union — what a class picker gets
staff_groupings.get_groupings_for_staff('Bach')     # from the staff side
staff_groupings.get_grouping_mapping()              # {name: [grouping names]}
staff_groupings.get_ungrouped_staff()               # in no grouping at all
```

Reads exclude inactive staff unless `include_inactive=True` is passed, so somebody who
has left is never pulled into a class by a grouping they are still recorded against.

Membership is edited from either side, and both write the same rows:

```python
staff_groupings.set_members(grouping_id, names)          # from the grouping
staff_groupings.add_members(grouping_id, names)
staff_groupings.remove_members(grouping_id, names)
staff_groupings.set_groupings_for_staff(name, ids)       # from the staff member
```

`set_groupings_for_staff()` only touches groupings a picker can offer: an archived
grouping the staff member is in is left alone, since its absence from the caller's list
is not a request to remove them from it. Every membership change is written to
`staff_audit_log` against the staff member, so it shows up on the History tab beside
their other edits.

Being in no grouping is normal for management and the non-clinical roles, so the admin
page and `get_roster_issues()['missing_grouping']` flag it only for staff who actually
work tracks — a clinical role with a shift requirement on file. Those are the people who
would otherwise be assigned no classes at all.

#### What this replaced

Two fixed columns on the `staff` table: `education_group` (cohort `1`–`4`) and
`or_group` (OR classes owed for the year: `0`, `2`, `3`, `4`). They were the only
groupings the app could express, they were seeded from name lists transcribed into the
source, and a third kind of grouping meant another column everywhere.

`staff_groupings.migrate_legacy_groupings()` runs once, the first time the grouping
tables come up, and needs nothing from an admin. It turns each value in use into an
ordinary grouping — `'2'` becomes "Group 2", `0` becomes "No OR" — moves the staff who
held it into that grouping, rewrites saved classes' `assignment_source` from the old
`education_groups` / `or_groups` keys to grouping ids, and then drops the columns and
their indexes. Classes keep their `assigned_staff` lists throughout: those are
materialized at save time and were never derived from the columns.

A marker in `staff_groupings_meta` is what stops it running twice, rather than the
columns being gone — dropping a column needs SQLite 3.35 or newer, and on an older one
the migration still completes and simply leaves the unread columns in place.

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
admin-password gated and has six tabs:

- **Roster** — filter by name/role/active/management/grouping, and download as CSV.
- **Groupings** — create a grouping, decide who is in it, archive or delete it.
- **Add Staff** — new hires, including their shift requirements and groupings.
- **Edit / Rename / Remove** — attributes, requirements, groupings, active status, name
  changes, deletion.
- **Import from Excel** — first-time seed and later refreshes.
- **History** — the audit log and past name changes.

The page also flags anything needing attention: staff with no role, clinical staff with
no seniority, duplicate seniority ranks, non-management clinical staff with no shift
requirement, bidding staff with no email, and track-working staff in no grouping.

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

### Building and editing groupings

Groupings are not imported from anywhere — there is no workbook that describes them, and
they change more often than the roster does. They are built on the admin page's
**Groupings** tab:

- **Create a grouping** — a name, an optional description, and optionally everyone in a
  role or two to start it off. The role is a shortcut for filling the list; nothing
  stays tied to it afterwards.
- **Members** — a picker of the whole active roster, plus an "add everyone in these
  roles" shortcut and an "empty the grouping" button. Staff already in the grouping who
  have since been marked inactive stay in the picker, so saving does not silently
  remove them.
- **Settings** — rename it, reword it, move it in the picker order, archive it, or
  delete it outright. Archiving keeps the membership; deleting loses the record of who
  was in it, so archive unless the grouping was a mistake.

One staff member's groupings are also editable from the **Add Staff** and
**Edit / Rename / Remove** tabs, which is the easier direction for a single new hire.
Both write the same rows.

Editing a grouping's membership does not reach back into classes that have already been
built: a class's assigned staff are materialized when it is saved. Re-open the class in
the class editor and press the grouping's **Add all of them** to pick up a change.

### Assigning a class to a grouping

Training & Events admin → **Build Classes** → the class form's **Assigned staff**
section. Pick any number of **Groupings** and any number of **Roles**:

- Groupings union: "Group 2" and "4 OR" means everyone in either.
- Roles narrow rather than widen: "Group 2" plus "Nurse" means group 2's nurses. A role
  on its own selects everyone who holds it.

The result is listed by name before it is added, and what gets saved on the class is the
staff list itself, plus the picks that produced it (`assignment_source`) so re-opening
the form shows what it was built from.

## Reading the roster in code

```python
from modules.staff_database import (
    get_staff, get_all_staff, get_staff_names,
    get_role, get_clinical_role, get_effective_role,
    is_management, is_dual, is_educator_at, get_no_matrix, get_seniority,
    get_shifts_per_pay_period, get_night_minimum, get_weekend_minimum,
    get_weekend_group, get_email,
    get_role_mapping, get_seniority_mapping, get_no_matrix_mapping,
    get_requirements_map,
    build_preferences_df, build_requirements_df,
)
```

Groupings are read from `modules/staff_groupings.py` rather than from here — see
[Groupings](#groupings) above.

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
member into other tables.

It also exercises the groupings: creating them, filling them from either side, the
union two groupings come to, archiving, and that a rename or a deactivation on the
roster reaches membership. Finally it builds a database the way the previous version of
the app left one — the `education_group` / `or_group` columns, their indexes and a class
assigned from them — and checks that the one-time migration turns all of it into
groupings, rewrites the class, drops the columns, and refuses to run twice.
