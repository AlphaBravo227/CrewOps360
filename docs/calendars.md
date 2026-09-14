# Calendars

Two screens, and the shared machinery under them.

| Screen | Where | What it shows |
| --- | --- | --- |
| **My Calendar** | Training & Events, second tab | One person's track shifts, the classes they are enrolled on, and the days they have signed up to teach |
| **Training Calendar** | Admin Console > Training & Events > Training Calendar | Every live class in the training year, one entry per class, per date, per location |

Both offer the same four take-aways: a printable PDF, an `.ics` file, a Google Calendar
CSV and an Outlook CSV.

My Calendar sits next to Enroll in Classes on the staff screen: what you have booked and
what you could book are the same errand, and the calendar is where you check the first
before doing the second. The Training Calendar sits with
Enrollment Reports at the top of the training admin dashboard, and reports on the year
named in that page's header like every other section there — so during a cutover it shows
the year the rest of the dashboard is showing, not whichever one happens to be current.

## Why they are one thing

They answer the same question from opposite ends. A staff member wants their shifts and
their classes on **one** calendar — the collisions between the two are the whole point,
and two separate exports hide exactly what somebody opened a calendar to find. An
educator or a manager wants the class schedule itself, over a span they choose, with no
person attached.

So the file writers know nothing about shifts or classes. An event is one calendar day
with an optional pair of times, and both screens build that same shape:

```
modules/calendar_formats.py             events -> .ics, Google CSV, Outlook CSV, PDF
training_modules/schedule_calendar.py   database -> events
training_modules/calendar_ui.py         the two screens
```

`render_my_calendar_tab()` draws the staff tab; `render_training_calendar()` draws the
admin section and no heading of its own, since the dashboard's header block already
names it.

`modules/calendar_export.py` is unchanged and still does what it always did: a
tracks-only export from the Clinical Track Hub, all-day events, no training in it.

## What the events are made of

**Shifts** come through `TrainingTrackManager`, which is the thing that already knows a
CCEMT schedule repeats every 28 days while a regular track repeats every 42, and which
cohort's `Sun A 1` this training year is anchored to. A shift code with defined hours in
`modules/shift_definitions.py` becomes a timed 12-hour event; a code with none becomes an
all-day one, because inventing hours for it would put a made-up conflict on somebody's
calendar.

**Enrollments** resolve their date back to the day its session starts before expanding —
booking a two-day class writes a row for each day, and the day-2 row's date is not a date
the class is configured to run on. Resolving first is what keeps both days reading their
times and location off the same configured session. The two rows of one booking are then
deduplicated, or every two-day class would appear twice.

**Class sessions** on the company calendar are one event per class, per date, per
location. A date taught at two sites is two sessions and two rooms to be in, and
collapsing them into one line is how a calendar ends up claiming a class is somewhere it
isn't. Seat counts are read per location only on a date that has more than one, since
rows written before locations were bookable carry none.

## Times and timezones

Times are written without a timezone. A shift that starts at 19:00 starts at 19:00
wherever the calendar is read, which is the right answer for people who all report to the
same bases, and it avoids shipping a `VTIMEZONE` block that some importers mishandle. The
calendar is tagged `America/New_York` so an importer that wants to resolve them has
something to resolve against.

A night shift's end time is earlier than its start. Every writer carries the end into the
next day rather than emitting an event of negative length.

## A note for the people importing

Import into a **new, separate calendar** rather than a main one. These files are a
snapshot, not a live feed: if a track or an enrollment changes, the fix is to re-export
and re-import. Having the events in their own calendar makes that one delete instead of a
duplicate hunt. The screens say so too.

## Overlaps

My Calendar flags pairs of commitments whose hours run into each other and which came
from different places — a shift running into a class, a class booked on a day somebody
agreed to teach. Two shifts on one day are the track's business and two classes at once is
the enrollment screen's, so those are left alone. All-day events have no hours to overlap
and are not flagged against everything sharing their date.

An overlap is not automatically a problem — a class somebody was released for still shows
against the shift they would otherwise have worked — which is why it is an expander and
not a warning.
