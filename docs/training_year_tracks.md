# Training years and track cohorts

A training year (Training Admin > Training Years) names the Track Bidding cohort its
classes are checked against for schedule conflicts, plus the date that cohort's 42-day
pattern counts as `Sun A 1`. Both are read when the training subsystem builds its
`TrainingTrackManager`, and both matter during a fiscal-year cutover: FY27's tracks are
promoted to active months before FY26's last classes are taught, so "whichever cohort is
active today" is the wrong answer for at least one of the two open years.

| Setting | What it controls |
| --- | --- |
| Linked track cohort | Which `tracks` rows conflict checking reads (`tracks.track_name`) |
| Track pattern start | Which calendar date is that cohort's `Sun A 1` |
| Roster filename | The workbook the year's classes come from |

## What "linked" can and can't see

Conflict checking reads the `tracks` table. A bid lands there only when the staff member
**submits** it; a bid still being built is a row in `bid_drafts`, which conflict checking
does not read. So linking a year to a cohort whose bid is still in progress is legitimate
but partial:

- **No submitted bids yet** — there is nothing to check against, so `reload_tracks()`
  falls back to the active cohort and flags it (`tracks_fell_back`). The Training Years
  screen warns before you save, and the training app warns admins after.
- **Some submitted** — those staff are checked against their new bid; staff who have not
  submitted have no track in that cohort and get no conflict checking for that year. The
  Training Years screen shows the counts.
- **All submitted / cohort promoted** — full coverage.

The fallback exists so a cohort named but never populated doesn't silently disable
conflict checking altogether. It is deliberately noisy, because the alternative — quietly
checking classes against another fiscal year's schedules — looks like it is working.

## Changing the link

The linked cohort, pattern start and roster are read once, when the cached handlers are
built. `app.py` keys that cache on all four fields of the selected year
(`training_loaded_year_signature`), so saving a change rebuilds the track manager on the
next rerun rather than leaving the session on the settings it started with.

Summer Leave keeps its own handlers (`summer_leave_track_manager`) and always uses the
active cohort — it is not scoped to a training year.

## Checking it

```bash
python scripts/check_training_year_tracks.py
```

Verifies against a throwaway database that a linked cohort loads that cohort's tracks
rather than the active ones, that a staff member with more than one row in a cohort
caches at their newest version, that an empty cohort falls back to the active cohort and
says so, that the coverage counts shown to admins match what conflict checking can see,
and that a per-year pattern anchor moves the whole grid with it.
