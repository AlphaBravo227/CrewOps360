# training_modules/schedule_calendar.py
"""
Building calendars out of what the app already knows: a staff member's track shifts
and the training they are booked on, and the company-wide schedule of every class in
a training year.

The two live together because they answer the same question from opposite ends. A
staff member wants one calendar showing the shifts they work and the classes they owe
— the conflicts between those are the whole point, and two separate exports hide them.
An educator or a manager wants the class schedule itself, over a span they choose,
without a person attached.

Both produce the plain event dictionaries in `modules.calendar_formats`, so the .ics,
the two CSVs and the PDF are written once and serve both.

Dates arrive here in the two formats the app stores: a class date is MM/DD/YYYY text
from the catalog, a track date is a `datetime` off the 42-day pattern. `parse_class_date`
is the one place that difference is resolved.
"""

from datetime import date as date_type, datetime, timedelta

from modules.calendar_formats import make_event, sort_events
from modules.shift_definitions import day_shifts, night_shifts

from . import two_day

CLASS_DATE_FORMAT = '%m/%d/%Y'

# How long a track shift runs. Every shift on the board is twelve hours; the code only
# records when it starts, so this is what turns a start time into a span.
SHIFT_HOURS = 12


def parse_class_date(value):
    """A stored class date as a `date`, or None if it isn't one.

    Accepts the MM/DD/YYYY the catalog stores, and the ISO form a date picker hands
    back, so a caller never has to know which end a date came from.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in (CLASS_DATE_FORMAT, '%Y-%m-%d', '%m/%d/%y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def format_class_date(value):
    """A date as the MM/DD/YYYY text the catalog and the enrollment tables store."""
    parsed = parse_class_date(value)
    return parsed.strftime(CLASS_DATE_FORMAT) if parsed else ''


def shift_times(shift_code):
    """A shift code's start and end as ('HH:MM', 'HH:MM'), or (None, None).

    A code nobody has defined hours for — a CCEMT code the schedule carries, a legacy
    letter — comes back empty and its event is drawn all-day, which is what the
    track-only export has always done. Guessing hours for it would put a made-up
    conflict on someone's calendar.
    """
    code = str(shift_code or '').strip()
    if not code:
        return None, None
    definition = day_shifts.get(code) or night_shifts.get(code)
    if not definition:
        return None, None
    start = definition.get('start_time')
    if not start or len(start) != 4 or not start.isdigit():
        return None, None
    hour, minute = int(start[:2]), int(start[2:])
    end_hour = (hour + SHIFT_HOURS) % 24
    return f"{hour:02d}:{minute:02d}", f"{end_hour:02d}:{minute:02d}"


def shift_kind(shift_code):
    """'Day' or 'Night' for a code the app defines, '' for one it doesn't."""
    code = str(shift_code or '').strip()
    if code in day_shifts:
        return 'Day'
    if code in night_shifts:
        return 'Night'
    return ''


def daterange(start, end):
    """Every day from `start` to `end`, both included."""
    first = parse_class_date(start)
    last = parse_class_date(end)
    if not first or not last or last < first:
        return
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


# --------------------------------------------------------------------------
# One person's calendar
# --------------------------------------------------------------------------

def track_shift_events(staff_name, track_manager, start, end):
    """The shifts a staff member works between two dates, as events.

    Reads through the track manager rather than the tracks table directly, because it
    is the thing that already knows a CCEMT schedule runs on a 28-day cycle while a
    regular track runs on 42, and which cohort's pattern anchor this training year is
    checked against.
    """
    if not track_manager or not staff_name:
        return []

    events = []
    for day in daterange(start, end):
        as_datetime = datetime(day.year, day.month, day.day)
        try:
            code = track_manager.get_staff_raw_shift(staff_name, as_datetime)
        except Exception as e:
            print(f"Could not read {staff_name}'s shift for {day}: {e}")
            continue
        code = str(code or '').strip()
        if not code:
            continue

        start_time, end_time = shift_times(code)
        kind = shift_kind(code)
        detail = f"{kind} shift" if kind else 'Scheduled shift'
        events.append(make_event(
            day,
            f"Shift: {code}",
            category='shift',
            start_time=start_time,
            end_time=end_time,
            description=f"{detail} - {staff_name}",
            code=code,
        ))
    return events


def resolve_session_times(catalog, class_name, class_date, session_time=None,
                          location=None):
    """When one booking actually runs, as ('HH:MM', 'HH:MM') or (None, None).

    A session the person picked says so outright and wins. Otherwise the class runs a
    single block that day, and on a date taught at several sites each site keeps its
    own hours — so the booked site's hours are the answer, and the class-level time is
    what a site without its own already resolves to. The same order the enrollment
    notifications use, because a calendar entry disagreeing with the email about when
    to turn up is worse than either being slightly wrong.
    """
    if session_time:
        text = str(session_time).strip()
        for separator in (' - ', '-', ' to ', '–'):
            if separator in text:
                first, _, second = text.partition(separator)
                if first.strip() and second.strip():
                    return first.strip(), second.strip()
        if text:
            return text, None

    if not catalog:
        return None, None

    start = end = None
    try:
        options = catalog.get_date_options(class_name, format_class_date(class_date)) or []
    except Exception as e:
        print(f"Could not read options for {class_name} on {class_date}: {e}")
        options = []

    booked = None
    if location:
        booked = next((option for option in options
                       if (option.get('location') or '') == location), None)
    elif len(options) == 1:
        # One site, so there is nothing to tell apart — a booking carrying no location
        # is still asking about that one.
        booked = options[0]
    if booked:
        start, end = booked.get('start_time'), booked.get('end_time')

    if not (start and end):
        try:
            details = catalog.get_class_details(class_name) or {}
        except Exception:
            details = {}
        start = start or details.get('time_1_start')
        end = end or details.get('time_1_end')

    return start, end


def _class_details(catalog, class_name, cache):
    if class_name in cache:
        return cache[class_name]
    try:
        details = catalog.get_class_details(class_name) if catalog else {}
    except Exception as e:
        print(f"Could not read details for {class_name}: {e}")
        details = {}
    cache[class_name] = details or {}
    return cache[class_name]


def enrollment_events(staff_name, enrollment_manager, catalog, start=None, end=None):
    """The classes a staff member is booked on, as events — one per day taught.

    Two things have to happen in order here, and the order is the whole trick.

    Each row's stored date is first resolved back to the day its session starts on,
    because booking a two-day class writes a row for *each* day and the day-2 row's
    date is not a date the class is configured to run on. Resolving first is what
    keeps the times and the location on both days reading off the same configured
    session; expanding a day-2 row directly instead produced an event with no location
    and, for a date the class does not run on at all, a day 3.

    The resolved session is then deduplicated. A two-day booking's two rows both
    resolve to the same session and both expand to the same two days, so without this
    every two-day class appeared on the calendar twice. Which row survives is decided
    by whichever carries a location, since only one of a pair may.
    """
    if not enrollment_manager or not staff_name:
        return []

    try:
        enrollments = enrollment_manager.get_staff_enrollments(staff_name) or []
    except Exception as e:
        print(f"Could not read {staff_name}'s enrollments: {e}")
        return []

    cache = {}
    # Keyed the way the enrollments table's own UNIQUE constraint is, minus the date,
    # which the expansion above is what varies: one session per person, class, meeting
    # type and session time.
    sessions = {}
    for enrollment in enrollments:
        class_name = enrollment.get('class_name') or 'Class'
        stored = enrollment.get('class_date')
        if not stored:
            continue
        details = _class_details(catalog, class_name, cache)
        anchor = two_day.anchor_of(details, stored) if details else None
        anchor = anchor or stored
        location = (enrollment.get('location') or '').strip()

        key = (class_name, anchor, enrollment.get('meeting_type') or '',
               enrollment.get('session_time') or '')
        existing = sessions.get(key)
        if existing and not (location and not existing['location']):
            continue
        sessions[key] = {'class_name': class_name, 'anchor': anchor,
                         'details': details, 'location': location,
                         'enrollment': enrollment}

    events = []
    for session in sessions.values():
        class_name = session['class_name']
        anchor = session['anchor']
        details = session['details']
        location = session['location']
        enrollment = session['enrollment']

        start_time, end_time = resolve_session_times(
            catalog, class_name, anchor, enrollment.get('session_time'), location)

        days = two_day.session_days(details, anchor) if details else [anchor]
        for index, day_text in enumerate(days, start=1):
            day = parse_class_date(day_text)
            if not day:
                continue
            label = f" (Day {index} of {len(days)})" if len(days) > 1 else ''
            notes = []
            if enrollment.get('meeting_type'):
                notes.append(str(enrollment['meeting_type']))
            if enrollment.get('role') and enrollment['role'] != 'General':
                notes.append(str(enrollment['role']))
            if enrollment.get('conflict_override'):
                notes.append('Enrolled over a track conflict')
            events.append(make_event(
                day,
                f"{class_name}{label}",
                category='training',
                start_time=start_time,
                end_time=end_time,
                location=location or _date_location(catalog, class_name, anchor),
                description=' | '.join(['Enrolled'] + notes),
                code=_short_label(catalog, class_name, cache),
            ))

    return _clip(events, start, end)


def educator_events(staff_name, educator_manager, catalog, start=None, end=None):
    """The days a staff member has signed up to teach, as events.

    Educator signups are already stored one row per teaching day — both days of a
    two-day class are signed up for separately — so unlike an enrollment there is
    nothing to expand here.
    """
    if not educator_manager or not staff_name:
        return []

    try:
        signups = educator_manager.get_staff_educator_signups(staff_name) or []
    except Exception as e:
        print(f"Could not read {staff_name}'s educator signups: {e}")
        return []

    cache = {}
    events = []
    for signup in signups:
        class_name = signup.get('class_name') or 'Class'
        stored = signup.get('class_date')
        day = parse_class_date(stored)
        if not day:
            continue
        # Day 2 of a two-day class is a teaching day but not a configured class date,
        # so its times and location have to be read off the day the session starts on.
        details = _class_details(catalog, class_name, cache)
        anchor = (two_day.anchor_of(details, stored) if details else None) or stored
        start_time, end_time = resolve_session_times(
            catalog, class_name, anchor, None, None)
        short = _short_label(catalog, class_name, cache)
        events.append(make_event(
            day,
            f"Teaching: {class_name}",
            category='educator',
            start_time=start_time,
            end_time=end_time,
            location=_date_location(catalog, class_name, anchor),
            description='Signed up as an educator',
            code=f"Teach {short}" if short else 'Teaching',
        ))

    return _clip(events, start, end)


def personal_calendar(staff_name, start, end, track_manager=None,
                      enrollment_manager=None, educator_manager=None, catalog=None,
                      include_shifts=True, include_training=True,
                      include_teaching=True):
    """One staff member's combined calendar for a span, sorted.

    Every source is optional and every source is independently switchable, because the
    screen offering this has to work for a person with no track loaded, and for one
    who only wants to export their training.
    """
    events = []
    if include_shifts:
        events.extend(track_shift_events(staff_name, track_manager, start, end))
    if include_training:
        events.extend(enrollment_events(staff_name, enrollment_manager, catalog,
                                        start, end))
    if include_teaching:
        events.extend(educator_events(staff_name, educator_manager, catalog,
                                      start, end))
    return sort_events(events)


# --------------------------------------------------------------------------
# The company training calendar
# --------------------------------------------------------------------------

def company_training_calendar(catalog, start, end, class_names=None,
                              enrollment_manager=None, include_seats=True):
    """Every class session the training year runs between two dates.

    One event per class, per date, per location — a date taught at two sites is two
    sessions and two rooms to be in, and collapsing them into one line is how a
    calendar ends up claiming a class is somewhere it isn't.

    Args:
        catalog: The ClassCatalog for the training year being shown.
        start / end: The span to cover.
        class_names: Only these classes, or None for every class in the year.
        enrollment_manager: Read seat counts through this when seats are wanted.
        include_seats: Whether to look up how full each session is. It is a query per
            session, so the caller can turn it off for a long span.

    Returns:
        list: The events, sorted.
    """
    if not catalog:
        return []

    try:
        names = list(class_names) if class_names else (catalog.get_all_classes() or [])
    except Exception as e:
        print(f"Could not list classes: {e}")
        return []

    events = []
    for class_name in names:
        try:
            details = catalog.get_class_details(class_name) or {}
        except Exception as e:
            print(f"Could not read details for {class_name}: {e}")
            continue
        if details.get('_missing_sheet') or details.get('_missing_dates') or details.get('_error'):
            continue

        short = (details.get('calendar_display') or '').strip() or class_name
        is_two_day = two_day.is_two_day(details)

        for index in range(1, (details.get('date_count') or 0) + 1):
            anchor = details.get(f'date_{index}')
            if not anchor:
                continue
            options = details.get(f'date_{index}_options') or [{}]
            days = two_day.days_from_anchor(anchor) if is_two_day else [anchor]

            for option in options:
                location = (option.get('location') or '').strip()
                start_time = option.get('start_time') or details.get('time_1_start')
                end_time = option.get('end_time') or details.get('time_1_end')
                # Only a date with more than one site is counted per site. On a
                # single-site date the rows written before locations were bookable
                # carry none, and filtering on one would report the room empty.
                seat_location = location if len(options) > 1 else None
                seats = _seat_note(enrollment_manager, class_name, anchor,
                                   seat_location, option, details) if include_seats else ''

                for day_number, day_text in enumerate(days, start=1):
                    day = parse_class_date(day_text)
                    if not day:
                        continue
                    label = f" (Day {day_number} of {len(days)})" if len(days) > 1 else ''
                    notes = [note for note in (
                        'LIVE option available' if details.get(f'date_{index}_has_live') else '',
                        seats,
                    ) if note]
                    events.append(make_event(
                        day,
                        f"{class_name}{label}",
                        category='class',
                        start_time=start_time,
                        end_time=end_time,
                        location=location,
                        description=' | '.join(notes),
                        code=f"{short}{f' ({location})' if location else ''}",
                    ))

    return sort_events(_clip(events, start, end))


def training_year_span(year_row, fallback_days=365):
    """A training year's start and end as dates, with a sane fallback.

    A year row whose dates nobody filled in would otherwise produce a calendar with no
    span at all, so it falls back to a year from today — which is visibly a default
    rather than an empty screen.
    """
    start = parse_class_date((year_row or {}).get('start_date'))
    end = parse_class_date((year_row or {}).get('end_date'))
    if not start:
        start = date_type.today()
    if not end or end < start:
        end = start + timedelta(days=fallback_days)
    return start, end


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _clip(events, start, end):
    """Only the events inside [start, end]; an open end means no limit there."""
    first = parse_class_date(start)
    last = parse_class_date(end)
    return [event for event in events
            if (first is None or event['date'] >= first)
            and (last is None or event['date'] <= last)]


def _short_label(catalog, class_name, cache):
    """The short name a class shows in a month-grid cell, or its full name."""
    details = _class_details(catalog, class_name, cache)
    return (details.get('calendar_display') or '').strip() or class_name


def _date_location(catalog, class_name, class_date):
    """The location text for one date of a class, as the catalog records it."""
    if not catalog or not hasattr(catalog, 'get_date_attributes'):
        return ''
    try:
        attributes = catalog.get_date_attributes(class_name,
                                                 format_class_date(class_date))
    except Exception:
        return ''
    return (attributes or {}).get('location', '') or ''


def _seat_note(enrollment_manager, class_name, class_date, location, option, details):
    """"12/21 enrolled" for one session, or '' when the count can't be read."""
    if not enrollment_manager:
        return ''
    try:
        capacity = option.get('capacity')
        if not capacity:
            from .class_catalog import parse_int
            capacity = parse_int(details.get('students_per_class'), 0) or 0
        count = enrollment_manager.get_date_enrollment_count(
            class_name, format_class_date(class_date), location=location or None)
    except Exception as e:
        print(f"Could not count enrollments for {class_name} on {class_date}: {e}")
        return ''
    return f"{count}/{capacity} enrolled" if capacity else f"{count} enrolled"
