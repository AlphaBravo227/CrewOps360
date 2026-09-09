# training_modules/two_day.py
"""
The days a two-day class is actually taught.

A two-day class stores one date - the day it starts - and is taught on that day and
the one after. Day 2 has no row of its own, so every screen that needs it derives it,
and this module is the one place that derivation lives.

The trap it exists to close: "day 2 is day 1 plus one" is only true if you already
know you are holding day 1. Nine call sites used to re-derive the pair from whatever
date they happened to have, and when that date *was* day 2 they silently produced a
day 3 - a date the class does not run on. Educators were assigned to it, and
cancelling a booking from its day 2 row cancelled nothing but day 2, leaving day 1
booked and the seat consumed.

So the rule here is that a date is expanded only after being resolved back to the day
its session starts on, and `anchor_of` does the resolving by asking the class which
dates it actually starts on - never by arithmetic alone. Everything else in this
module is built on that.
"""

from datetime import datetime, timedelta

from .class_catalog import date_indices

DATE_FORMAT = '%m/%d/%Y'

# How many days a "two-day" class runs. Named because it appears in the arithmetic
# below and reads as a magic 1 otherwise.
SESSION_LENGTH_DAYS = 2


def is_two_day(class_details):
    """Whether a class runs over two consecutive days.

    Takes the details dict rather than a class name so it can be called in a loop
    that already has them - reading them again per date was most of what the old
    per-module helpers cost.
    """
    if not class_details:
        return False
    value = class_details.get('is_two_day_class', 'No')
    if isinstance(value, str):
        return value.strip().lower() in ('yes', 'true', '1')
    return bool(value)


def _parse(date_str):
    """A class date as a datetime, or None if it isn't one."""
    try:
        return datetime.strptime(str(date_str).strip(), DATE_FORMAT)
    except (ValueError, TypeError, AttributeError):
        return None


def _shift(date_str, days):
    """A class date moved by `days`, in the same string format, or None."""
    parsed = _parse(date_str)
    if parsed is None:
        return None
    return (parsed + timedelta(days=days)).strftime(DATE_FORMAT)


def scheduled_dates(class_details):
    """Every date the class is configured to start on, in configured order.

    These are anchors: for a two-day class the second day is not among them.
    """
    if not class_details:
        return []
    dates = []
    for index in date_indices(class_details):
        value = class_details.get(f'date_{index}')
        if value:
            dates.append(value)
    return dates


def days_from_anchor(anchor):
    """The days a session starting on `anchor` is taught, [day 1, day 2].

    Assumes `anchor` really is a day 1. Call `session_days` instead unless you know
    that - resolving first is the whole point of this module.
    """
    day_2 = _shift(anchor, 1)
    return [anchor, day_2] if day_2 else [anchor]


def anchor_of(class_details, date):
    """The date the session containing `date` starts on, or None.

    `date` may be either day of a two-day class. It is matched against the class's
    configured dates rather than adjusted by arithmetic, so a date the class does not
    run on returns None instead of quietly resolving to a plausible-looking neighbour.

    For a single-day class this is `date` itself when the class runs then.
    """
    if not date:
        return None

    configured = set(scheduled_dates(class_details))
    if date in configured:
        return date

    if not is_two_day(class_details):
        return None

    # `date` is a day 2 if the class starts the day before it.
    previous = _shift(date, -1)
    if previous and previous in configured:
        return previous
    return None


def session_days(class_details, date):
    """Every day of the session that `date` belongs to.

    The safe expansion: resolves `date` back to its anchor first, so passing day 2 of
    a two-day class returns that session's two days rather than day 2 and day 3.

    A single-day class, or a date the class does not run on, gives back `[date]` - the
    caller asked about a day, and that day is the answer.
    """
    if not is_two_day(class_details):
        return [date]

    anchor = anchor_of(class_details, date)
    if anchor is None:
        # Not one of this class's dates. Expanding it would invent a day the class
        # does not run on, which is exactly what this module exists to prevent.
        return [date]
    return days_from_anchor(anchor)


def day_number(class_details, date):
    """1 or 2 for a two-day class, 1 for a single-day one, None if it isn't a class date."""
    anchor = anchor_of(class_details, date)
    if anchor is None:
        return None
    if not is_two_day(class_details):
        return 1
    return 1 if date == anchor else 2


def day_label(class_details, date):
    """"Day 1"/"Day 2" for a two-day class, '' otherwise. For conflict messages."""
    if not is_two_day(class_details):
        return ''
    number = day_number(class_details, date)
    return f"Day {number}" if number else ''


def all_days(class_details):
    """Every day the class is taught across all its dates, in configured order.

    This is what educator signups and per-day rosters iterate: a two-day class has two
    teaching days per configured date, and each is signed up for separately.
    """
    days = []
    two_day = is_two_day(class_details)
    for anchor in scheduled_dates(class_details):
        days.extend(days_from_anchor(anchor) if two_day else [anchor])
    return days


def date_range_label(class_details, date, suffix=' (2-Day Class)'):
    """How a session reads to a person: "10/14/2026 - 10/15/2026 (2-Day Class)".

    Falls back to the date on its own for a single-day class, so callers can format
    every date through here without branching.
    """
    if not is_two_day(class_details):
        return date

    days = session_days(class_details, date)
    if len(days) < SESSION_LENGTH_DAYS:
        return f"{date}{suffix}"
    return f"{days[0]} - {days[1]}{suffix}"
