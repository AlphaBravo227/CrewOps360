# modules/track_year.py
"""
Fiscal years in the Clinical Track Hub.

A track cohort — `track_configs.track_name`, "FY26", "FY27" — is a fiscal year's worth
of 42-day tracks. A cutover isn't a switch, it's an overlap: FY27's bids are promoted
months before FY26's last shift is worked, and promotion clears `is_active` on FY26's
rows. Everything the hub showed was scoped to `is_active = 1`, so the year still being
worked disappeared the day the next one was promoted.

This module says what a cohort's fiscal year actually is — when it starts, when it
ends, and which calendar date its pattern counts as `Sun A 1` — so the hub can show a
year other than the live one, and answers which years it may offer.

| Setting | What it controls |
| --- | --- |
| `status` | Whether the cohort appears in the hub's fiscal-year picker |
| `start_date` / `end_date` | The calendar span its 42-day pattern is projected over |
| `pattern_start_date` | Which calendar date is that cohort's `Sun A 1` |
"""

from datetime import datetime, timedelta

from .db_utils import (
    FY26_TRACK_PATTERN_START,
    FY26_TRACK_YEAR_END,
    FY26_TRACK_YEAR_START,
    TRACK_YEAR_OPEN,
    get_active_track_config,
    get_hub_visible_track_configs,
    get_track_year_span,
    is_track_year_writable,
)

PATTERN_LENGTH = 42

# Session-state key holding the fiscal year a hub session has explicitly picked.
SELECTED_YEAR_KEY = 'hub_selected_track_year'


def parse_date(value, default=None):
    """A YYYY-MM-DD string as a datetime, or `default` if it isn't one."""
    if isinstance(value, datetime):
        return value
    if not value:
        return default
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d')
    except (TypeError, ValueError):
        return default


def get_track_year_dates(track_name=None):
    """A cohort's fiscal-year span and pattern anchor, as datetimes.

    Falls back to FY26's dates — the ones the fiscal-year display and the calendar
    export used to carry hardcoded — for a cohort whose dates nobody has set. An
    unparseable date falls back the same way rather than taking the whole page down.

    Returns:
        dict: {'track_name', 'start', 'end', 'pattern_start', 'offset'}, where offset
            is how far into the 42-day pattern the fiscal year's first day falls.
    """
    span = get_track_year_span(track_name)
    start = parse_date(span.get('start_date'),
                       parse_date(FY26_TRACK_YEAR_START))
    end = parse_date(span.get('end_date'), parse_date(FY26_TRACK_YEAR_END))
    pattern_start = parse_date(span.get('pattern_start_date'),
                               parse_date(FY26_TRACK_PATTERN_START))

    # An end date before the start would generate no months at all; a year that short
    # is a typo, so fall back to a full year rather than rendering an empty display.
    if end < start:
        end = start + timedelta(days=364)

    return {
        'track_name': span.get('track_name'),
        'start': start,
        'end': end,
        'pattern_start': pattern_start,
        'offset': pattern_offset(start, pattern_start),
    }


def pattern_offset(fiscal_start, pattern_start):
    """Which day of the 42-day pattern the fiscal year's first day is.

    FY26 starts on `Sun B 3`, two weeks into the pattern, which is where the calendar
    export's hardcoded offset of 14 came from. Deriving it from the anchor keeps that
    answer for FY26 and gives the right one for any other cohort.
    """
    return (fiscal_start - pattern_start).days % PATTERN_LENGTH


def _nth_weekday(year, month, weekday, n):
    """The nth (1-based) `weekday` of a month; n = -1 means the last one."""
    if n > 0:
        first = datetime(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    next_month = datetime(year + (month == 12), (month % 12) + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def us_holidays_between(start, end):
    """The observed holidays the schedule marks, for any span.

    The fiscal-year display carried FY26's ten dates as a literal, which went stale
    the moment a second cohort existed. These rules reproduce that list exactly and
    keep working for FY27 and beyond.

    Returns:
        dict: datetime -> holiday name, for dates within [start, end].
    """
    MON, THU = 0, 3
    holidays = {}
    for year in range(start.year, end.year + 1):
        holidays.update({
            datetime(year, 1, 1): "New Year's Day",
            _nth_weekday(year, 1, MON, 3): "MLK Jr. Day",
            _nth_weekday(year, 2, MON, 3): "Presidents' Day",
            _nth_weekday(year, 5, MON, -1): "Memorial Day",
            datetime(year, 6, 19): "Juneteenth",
            datetime(year, 7, 4): "Independence Day",
            _nth_weekday(year, 9, MON, 1): "Labor Day",
            _nth_weekday(year, 11, THU, 4): "Thanksgiving",
            datetime(year, 12, 24): "Christmas Eve",
            datetime(year, 12, 25): "Christmas",
        })
    return {date: name for date, name in holidays.items() if start <= date <= end}


def get_hub_track_years():
    """The fiscal years the Clinical Track Hub may offer, live year first.

    Each entry carries what the picker needs: the cohort's own config row plus
    `is_writable` (whether track changes may be made against it) and a `label` for
    the option list.
    """
    active = get_active_track_config()
    active_name = (active or {}).get('track_name')
    years = []
    for cfg in get_hub_visible_track_configs():
        name = cfg.get('track_name')
        is_live = bool(cfg.get('is_active'))
        years.append({
            **cfg,
            'is_writable': is_live and (cfg.get('status') or '') == TRACK_YEAR_OPEN,
            'label': f"{name} (current)" if is_live else f"{name} (closed)",
        })
    # A hub with no cohort marked visible would have no year to show at all; the live
    # cohort belongs in the picker whatever its status says.
    if active_name and not any(y['track_name'] == active_name for y in years):
        years.insert(0, {
            **active,
            'is_writable': is_track_year_writable(active_name),
            'label': f"{active_name} (current)",
        })
    return years


def resolve_selected_year(visible_years, active_name, remembered=None):
    """Which fiscal year a hub session is looking at.

    Only an explicit pick is remembered. Defaulting used to be remembered too in the
    training screen, which pinned a session opened before a cutover to the outgoing
    year with no sign anything had changed; the same trap applies here.

    Returns:
        tuple: (selected label, whether a stale remembered pick was dropped)
    """
    labels = [y.get('track_name') for y in visible_years]
    dropped = False
    if remembered and remembered not in labels:
        remembered = None
        dropped = True
    if remembered:
        return remembered, dropped
    if active_name and active_name in labels:
        return active_name, dropped
    return (labels[0] if labels else active_name), dropped
