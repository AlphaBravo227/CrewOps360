# The Training Admin dashboard across fiscal years

Enrollments have been scoped to a training year for a while: the year is chosen when
the training app loads, and every read and write goes through managers pinned to it.
The admin side inherited that year but never said which one it was, and could only
reach the years staff were allowed to see. During a cutover — when the outgoing year
is still being taught and the incoming one is taking signups — that meant an admin
looking at a compliance report with no way to tell which year it covered.

| What | Where it comes from |
| --- | --- |
| The year every admin screen reports on | `training_enrollment_manager.training_year` |
| Which years an admin may pick | `get_admin_visible_training_years()` — all of them |
| Which years staff may pick | `get_staff_visible_training_years()` — open and read-only |
| The span a report opens on | that year's `start_date` / `end_date` |

## Which years an admin can reach

Staff get the years they can act in. An admin gets every year there is, for the same
reason the Clinical Track Hub's export offers every cohort: building next year's
roster means reporting on a draft before anyone else may see it, and answering a
question about a finished year means reading one that has been archived.

The widening is tied to an authenticated admin session, so logging out drops a pick
staff can't see and the screen falls back to the active year — the same thing that
already happened to a pick that was archived out from under it.

Each option is labelled with its own state and enrollment count
(`FY28 (draft) — 0 enrollments`), so a year that will report nothing is visibly a
dead end rather than a report that comes back mysteriously empty.

## Saying which year is on screen

The admin dashboard renders and returns before the staff year selector is ever drawn,
so the dashboard carries its own. It sits under the session bar, above every
function, and names the year, its status, its span and its roster file. Changing it
there writes the same `training_selected_year` session key the staff screen reads, so
the choice holds when the admin leaves the dashboard, and `app.py` rebuilds the
roster, track manager and enrollment managers for the new year on the next run.

Individual screens repeat the year where it changes what the numbers mean —
compliance is per-year, the roster workbook is per-year, an export is per-year.

## Date ranges

The schedule report and the availability analyser both used to open on today. A
closed year's classes are all in the past and a draft year's are all in the future,
so "today plus thirty days" found nothing in either and read as an empty roster
rather than an out-of-range window. Both now open on the year being viewed — today
if the year is running, its own start otherwise — and say so when the range picked
falls outside the year entirely.

The date pickers are Streamlit widgets, so their state survives a year switch. The
year-signature reset in `app.py` drops them along with the cached managers, which is
what lets them re-default.

## Telling two years' exports apart

Every admin download is prefixed with its year (`FY27_compliance_report_…`), and
workbooks record it inside as well — the schedule report in its title, the rest on a
`Report Info` sheet. A workbook gets renamed, mailed on and opened months later, and
two years' reports are otherwise identical.

The year label is admin-entered free text, so it is sanitised before it goes into a
filename.

## The audit trail

`training_enrollment_audit` and `training_educator_audit` carried no year at all, so
an entry reading "cancelled — Jane Doe — Airway Lab" had nothing to say which year it
belonged to. Both tables now carry `training_year`, stamped at every insert. Rows
written before the column existed backfill to FY26, the only cohort that existed
while they were written.

## Data health

Database Maintenance runs the checks that only matter once more than one year exists.
Each was harmless with a single year and becomes a wrong number with two:

- **Unstamped rows** — read as FY26 by every query, so they appear in that year
  whatever year they belong to. `scripts/repair_training_year_stamps.py` re-stamps
  the ones whose class belongs to another year's roster.
- **Orphaned years** — enrollments stamped with a year that has no Training Years
  row. Nobody can see or manage them until the year is created.
- **Enrollments outside their year's span** — either the year's dates are wrong or
  the enrollment belongs to the neighbouring year. A cutover makes the second easy:
  the year selected is not necessarily the year the class belongs to.

System Statistics shows the selected year on its own and every year side by side,
because a single year's total can't say whether the outgoing year's tail or the
incoming year's opening is what moved.

## The three screens that weren't there

Data Export, System Statistics and Database Maintenance were on the admin menu and
dispatched in `_render_admin_function`, but none of the three had an implementation —
opening any of them raised `AttributeError`. They are implemented here, year-scoped
from the start.

## Checking it

```bash
python scripts/check_training_admin_years.py
```

Verifies against a throwaway database that staff see only the years they can act in
while an admin sees all four, that each option is labelled with its state and count,
that a write lands in the year it was made for and a read-only or draft year refuses
it, that audit rows are filed under their own year, that per-year statistics separate
the years and the all-years total still works, that the health checks catch an
enrollment outside its span, a year with no config row and an unstamped row, and that
an export carries its year on every line and in its filename.
