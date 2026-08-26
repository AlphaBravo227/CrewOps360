# Training Roster Upload Folder

This folder holds the Excel roster file(s) that drive the Training & Events
module (class assignments, enrollment, educator signups). One workbook per
fiscal year, each registered in **Training Admin → Training Years** — the app
reads the file that year's entry names, and does not automatically pick up a
file just because it's dropped in here.

## Starting a new fiscal year (e.g. FY26 → FY27)

1. Build the new year's roster in the same format as the current file (see
   "Excel format" below), and save it here as:

   ```
   FY27 Education Classes Roster.xlsx
   ```

   (Match the pattern `FY<year> Education Classes Roster.xlsx`. The exact
   filename doesn't have to follow this pattern, but keeping it consistent
   makes it obvious at a glance which file belongs to which year.)

2. **Do not delete or overwrite the previous year's file** (e.g. `FY26
   Education Classes Roster.xlsx`). Class detail lookups
   (location, time, session count) for existing enrollment records are read
   live from the Excel file, not stored in the database — if the old file
   disappears, historical enrollments from that year can no longer show
   their class details.

3. In the app, go to **Training & Events → Training Admin → Training Years**
   and click **Create New Training Year**:
   - **Year label**: `FY27`
   - **Roster filename**: `FY27 Education Classes Roster.xlsx` (must match
     the filename in this folder exactly, including spaces/capitalization)
   - **Linked track cohort**: the matching Track Bidding cohort. Set this —
     it's what schedule-conflict checking runs against. Without it, a class
     in this year is checked against whichever cohort is active *today*,
     which is the wrong one once the year has closed.
   - **Pattern start date**: the date that cohort's 42-day track pattern
     counts as "Sun A 1". **Verify this against the bid grid** — a wrong
     anchor shifts every conflict check by a few days and reports nothing.
     Leave blank to inherit FY26's anchor (2025-09-14).
   - **Start/end date**: the fiscal year's span. The end date is what
     closes the year automatically (see step 5), so it's worth filling in.

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
| B1:B14 | Class dates (up to 14 sessions; row 15 must stay blank — it's the end-of-list marker) |
| C1:C14 | "LIVE" option available for that date? (checkbox, staff meetings only) |
| D1:D14 | Can staff work the night before this date? (checkbox) |
| E1:E14 | Location for that date |
| B16 | Students per class (capacity) |
| B17 | Nurses/Medics enrolled separately? (checkbox) |
| B18 | Classes per day |
| B19 | Is this a two-day class? (checkbox) |
| B20:B27 | Time slots 1–4, start/end pairs (e.g. B20=session 1 start, B21=session 1 end, …) |
| B28 | Instructors needed per day |

If a class's sheet is missing, or has no dates in rows 1–14, the app treats
it as unconfigured (shows a warning to staff rather than crashing).

## Questions / issues

If a roster doesn't load, check the in-app error message first — it names
the exact file path the app tried to open, which usually means either the
filename doesn't match what's set in Training Admin → Training Years, or the
file isn't in this folder.
