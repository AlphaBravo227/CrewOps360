# modules/day_pattern.py
"""
The 42-day track pattern — the canonical day schema every track, bid and
preassignment is keyed by.

A track cycle is six weeks: weekdays Sun..Sat, weeks numbered 1-6, grouped into
blocks A (weeks 1-2), B (weeks 3-4) and C (weeks 5-6), giving labels
"Sun A 1" ... "Sat C 6".

These labels used to be read out of the header row of Tracks.xlsx and
Preassignments.xlsx. Both files carried the identical 42 labels — the schema is fixed,
not per-file — so it is generated here instead, and neither spreadsheet is needed to know
what the days are.
"""

WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# Block letter per week number 1-6.
WEEK_BLOCKS = ["A", "A", "B", "B", "C", "C"]

WEEKS = 6
DAYS_PER_WEEK = 7
PATTERN_LENGTH = WEEKS * DAYS_PER_WEEK  # 42

# Weekdays that count as weekend days for staffing rules.
WEEKEND_WEEKDAYS = {"Sat", "Sun"}

_WEEKDAY_ORDER = {name: index for index, name in enumerate(WEEKDAYS)}


def generate_pattern_days():
    """
    The 42 day labels in chronological order.

    Returns:
        list: ["Sun A 1", "Mon A 1", ..., "Sat C 6"]
    """
    days = []
    for week_index in range(WEEKS):
        block = WEEK_BLOCKS[week_index]
        week_number = week_index + 1
        for weekday in WEEKDAYS:
            days.append(f"{weekday} {block} {week_number}")
    return days


# Materialized once — this never changes at runtime.
PATTERN_DAYS = generate_pattern_days()


def pattern_day_sort_key(day):
    """
    Chronological sort key for a day label.

    Sorting the labels as plain strings puts "Mon B 3" before "Tue A 2" even though
    week 2 comes first, so week number leads the key, then weekday.

    Returns:
        tuple: (week_number, weekday_index) for a parseable label, else (999, label).
    """
    parts = str(day).split()
    if len(parts) >= 3:
        weekday, week_number = parts[0], parts[2]
        try:
            return (int(week_number), _WEEKDAY_ORDER.get(weekday, 7))
        except ValueError:
            pass
    return (999, str(day))


def sort_pattern_days(days):
    """The given day labels in chronological order."""
    return sorted(days, key=pattern_day_sort_key)


def parse_pattern_day(day):
    """
    Split a day label into its parts.

    Returns:
        tuple or None: (weekday, block, week_number) or None if unparseable.
    """
    parts = str(day).strip().split()
    if len(parts) != 3:
        return None
    weekday, block, week_number = parts
    if weekday not in _WEEKDAY_ORDER:
        return None
    try:
        return (weekday, block.upper(), int(week_number))
    except ValueError:
        return None


def is_pattern_day(day):
    """True if the label is one of the 42 canonical days."""
    return str(day).strip() in set(PATTERN_DAYS)


def is_weekend_day(day):
    """True if the day label falls on a Saturday or Sunday."""
    parsed = parse_pattern_day(day)
    return parsed is not None and parsed[0] in WEEKEND_WEEKDAYS


def week_number_of(day):
    """Week number (1-6) for a day label, or None."""
    parsed = parse_pattern_day(day)
    return parsed[2] if parsed else None


def week_days(week_number):
    """The seven day labels of one week (1-6)."""
    if not 1 <= week_number <= WEEKS:
        return []
    start = (week_number - 1) * DAYS_PER_WEEK
    return PATTERN_DAYS[start:start + DAYS_PER_WEEK]


def days_by_week():
    """
    The pattern grouped by week.

    Returns:
        list: six lists of seven day labels.
    """
    return [week_days(week_number) for week_number in range(1, WEEKS + 1)]
