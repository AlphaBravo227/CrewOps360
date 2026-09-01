# Training Roster Upload Folder

This folder holds roster workbooks that classes can be **imported from**. It is
no longer what the app reads to run.

Classes, their dates and who is assigned to them live in the database, and are
built and edited in **Training Admin → Build Classes**. A workbook is opened in
exactly one place: the **Import from a workbook** tab of that page. Nothing here
is read at startup, and deleting a file from this folder no longer breaks
anything that has already been imported.

Keep the files anyway — they are the record of what a year was imported from,
and the only way back if a year needs re-importing.

## Why the change

The workbook's sheet layout set two limits that had nothing to do with the work:
a class could have at most **14 dates** (rows 1-14 of column B) and each date
exactly **one location** (column E beside it). Neither is true any more. A class
can have as many dates as it needs, and a date can run at several locations,
each bookable separately with its own times and its own seat count — staff pick
which site they are attending, and the roster records it.

## Starting a new fiscal year (e.g. FY26 → FY27)

1. Create the year (step 3 below), then build its classes one of two ways:

   - **In the app** — Training Admin → Build Classes → *Create a new class*.
     This is the way to get a class with more than 14 dates, or a day taught
     at more than one site.
   - **From a workbook** — put it here, then Training Admin → Build Classes →
     *Import from a workbook*. Match the pattern
     `FY<year> Education Classes Roster.xlsx` so it is obvious at a glance
     which file belongs to which year, and see "Excel format" below for what
     the importer expects.

   The two mix freely: import a year's classes from a spreadsheet, then add
   more in the app. Re-importing leaves classes already in the catalog alone
   unless you tick *Replace classes already in FY27*, so a re-import adds what
   the workbook has gained without undoing edits made in the app.

2. Keep the previous year's file. Nothing breaks if it goes — class details for
   old enrollments are in the database now, not read back out of the
   spreadsheet — but it is the only way to re-import that year.

3. In the app, go to **Training & Events → Training Admin → Training Years**
   and click **Create New Training Year**:
   - **Year label**: `FY27`
   - **Roster filename**: `FY27 Education Classes Roster.xlsx` — the file
     Build Classes offers first when importing. It must match the filename in
     this folder exactly, including spaces and capitalization. Nothing reads
     it otherwise, so a year whose classes are built in the app can leave it
     blank.
   - **Linked track cohort**: `FY27` — the matching Track Bidding cohort.
     Set this; it's what schedule-conflict checking runs against. Without
     it, a class in this year is checked against whichever cohort is active
     *today*, which is the wrong one once the year has closed.
   - **Track pattern start ("Sun A 1")**: `2026-09-27`. **Verify against
     the bid grid** — a wrong anchor shifts every conflict check by days
     and reports nothing.
   - **Training year span**: `2026-10-01` to `2027-09-30`. The end date is
     what closes the year automatically (see step 5), so fill it in.

   ### These two dates are not the same thing

   The **training year** runs on the calendar, 10/1 to 9/30. The **track
   cohort** starts on whichever Sunday begins its 42-day pattern — 9/28/25
   for FY26, 9/27/26 for FY27. They differ by a few days at each end, and
   conflating them freezes a training year before its last classes are
   taught. Keep them in their own fields:

   | | FY26 | FY27 |
   |---|---|---|
   | Training year span | 2025-10-01 → 2026-09-30 | 2026-10-01 → 2027-09-30 |
   | Track pattern "Sun A 1" | 2025-09-14 | 2026-09-27 |

   New years are created as a **draft**: admin-visible only, so a
   half-finished roster is never exposed to staff.

4. When you're ready to cut over, open the FY27 entry and click **Promote to
   Active**. FY27 becomes the year the registration screen opens on, and
   both years are now **open**: staff get a year picker and can still cancel
   and re-book their remaining FY26 classes. Nothing is deleted.

   The confirm dialog has a **"make the outgoing year read-only right
   away"** checkbox. Leave it unchecked for a normal cutover — the outgoing
   fiscal year still has months of classes left to run.

5. FY26 closes itself once its **end date** passes: it flips to **read-only**,
   staff can still see what they took but can't enroll or cancel, and the
   requirement counts they see for FY27 start from zero. To close it sooner,
   set its status to Read-only by hand.

## Training year statuses

| Status | Staff see it | Can enroll/cancel | Use it for |
|---|---|---|---|
| **Draft** | No | No | A year you're still building |
| **Open** | Yes | Yes | The current year — and the outgoing one, during a cutover |
| **Read-only** | Yes | No | A finished year staff should still be able to review |
| **Archived** | No | No | Old years you want out of the picker |

More than one year can be **Open** at a time; that overlap is what makes a
cutover work. Everything a staff member sees — enrollments, seat counts,
staff-meeting progress, LIVE-meeting counts — is scoped to the year selected
at the top of the registration screen, so requirements reset cleanly at the
year boundary without anyone deleting last year's records.

## Excel format

What the importer expects. This is the old layout, unchanged — it is what the
existing FY26 and FY27 workbooks are in. Anything it cannot express (a
fifteenth date, a second location on a day) is added in the app after
importing.

The workbook needs:

### A `Class_Enrollment` sheet
- Row 1 is the header row.
- Column A: `STAFF NAME`.
- A few fixed non-class columns: `Role`, `MGMT`, `DUAL`, `Educator AT`
  (checkbox — authorizes that person to sign up as an educator).
- One column per class, header = the exact class name. Each cell below is a
  checkbox: checked = that staff member is assigned to that class.
- Every other column header in this sheet becomes a "class" the app expects
  a matching detail sheet for (see below) — a stray column here with no
  matching sheet will show up as a class with no available dates.

### One detail sheet per class
Sheet name must match the class name used as a column header in
`Class_Enrollment` (case-insensitive). Cell layout is fixed position, not
labeled — get the row/column right or the app will silently fall back to
defaults:

| Cell | Meaning |
|---|---|
| F2 | Has CCEMT role split? (checkbox) |
| G2 | Multi-session class? (checkbox) |
| H2 | Session length |
| I2 | Count-exempt? (checkbox) |
| B1:B14 | Class dates (the importer reads rows 1-14; add further dates in the app) |
| C1:C14 | "LIVE" option available for that date? (checkbox, staff meetings only) |
| D1:D14 | Can staff work the night before this date? (checkbox) |
| E1:E14 | Location for that date (one per date here; add more in the app) |
| B16 | Students per class (capacity) |
| B17 | Nurses/Medics enrolled separately? (checkbox) |
| B18 | Classes per day |
| B19 | Is this a two-day class? (checkbox) |
| B20:B27 | Time slots 1–4, start/end pairs (e.g. B20=session 1 start, B21=session 1 end, …) |
| B28 | Instructors needed per day |

A class whose sheet is missing, or which has no dates in rows 1–14, still
imports — as a class with no dates, which is what the app showed for it before.
The gap is then visible in Build Classes rather than silently dropped, and staff
see a "not configured" warning rather than a crash.

## Questions / issues

If a year's registration screen is empty, check Training Admin → Build Classes:
a year with no classes says so there, and the same warning appears at the top of
the training module. An import that found nothing names what it skipped and why.
