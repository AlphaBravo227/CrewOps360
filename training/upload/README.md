# Training Roster Upload Folder

This folder holds the Excel roster file(s) that drive the Training & Events
module (class assignments, enrollment, educator signups). The app reads
whichever file is currently marked **active** in **Training Admin → Training
Years** — it does not automatically pick up a file just because it's dropped
in here.

## Starting a new fiscal year (e.g. FY26 → FY27)

1. Build the new year's roster in the same format as the current file (see
   "Excel format" below), and save it here as:

   ```
   FY27 Education Classes Roster.xlsx
   ```

   (Match the pattern `FY<year> Education Classes Roster.xlsx`. The exact
   filename doesn't have to follow this pattern, but keeping it consistent
   makes it obvious at a glance which file belongs to which year.)

2. **Do not delete or overwrite the previous year's file** (e.g. `MASTER
   Education Classes Roster.xlsx` / FY26's file). Class detail lookups
   (location, time, session count) for existing enrollment records are read
   live from the Excel file, not stored in the database — if the old file
   disappears, historical enrollments from that year can no longer show
   their class details.

3. In the app, go to **Training & Events → Training Admin → Training Years**
   and click **Create New Training Year**:
   - **Year label**: `FY27`
   - **Roster filename**: `FY27 Education Classes Roster.xlsx` (must match
     the filename in this folder exactly, including spaces/capitalization)
   - **Linked track cohort**: optional — the matching Track Bidding cohort
     name, for reference only
   - **Start/end date**: optional, for reference only

4. When you're ready to cut over, open the FY27 entry and click **Promote to
   Active**. This immediately switches what every staff member sees on the
   registration screen to the FY27 roster. The previous year's config and
   file are left in place — nothing is deleted.

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
