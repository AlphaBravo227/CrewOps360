# modules/calendar_formats.py
"""
Turning a list of calendar events into the files people take away: an .ics any
calendar imports, the CSVs Google Calendar and Outlook import, and a printable
month-grid PDF.

Nothing here knows what a shift or a class is. An event is one calendar day with an
optional pair of times, and every producer in the app builds that same shape — a
staff member's combined track-and-training calendar and the company-wide training
calendar both hand over the same dictionaries — which is what lets one PDF layout and
one .ics writer serve both.

A timed event whose end time is at or before its start time runs past midnight. A
night shift is why that case exists, and every writer here resolves it by carrying the
end into the next day rather than emitting an event of negative length.

Times are written without a timezone — a shift that starts at 19:00 starts at 19:00
wherever the calendar is being read, which is the right answer for people who all
report to the same bases, and avoids shipping a VTIMEZONE block that some importers
mishandle. The calendar is tagged Eastern so an importer that wants to resolve them
has something to resolve against.
"""

import csv
import io
import uuid
from calendar import Calendar as _MonthCalendar
from datetime import date as date_type, datetime, timedelta, timezone

from icalendar import Calendar, Event

from .pdf_generator import sanitize_text_for_pdf

# Weeks start on Sunday here, as they do on the 42-day track pattern and on every
# grid the app already draws.
SUNDAY_FIRST = _MonthCalendar(firstweekday=6)

WEEKDAY_HEADINGS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

# How each kind of event is drawn and described. A category the caller invents still
# renders — it just falls back to the neutral style — so adding a new kind of event is
# not a change to this module.
CATEGORY_STYLES = {
    'shift': {'fill': (219, 234, 254), 'text': (23, 49, 117), 'label': 'Track shift'},
    'training': {'fill': (209, 250, 229), 'text': (6, 78, 59), 'label': 'Training'},
    'educator': {'fill': (254, 240, 199), 'text': (120, 53, 15), 'label': 'Teaching'},
    'class': {'fill': (233, 213, 255), 'text': (76, 29, 149), 'label': 'Class session'},
}
_DEFAULT_STYLE = {'fill': (233, 236, 239), 'text': (40, 40, 40), 'label': 'Other'}

# Long enough to be worth spelling out, short enough that a 12-hour night shift
# doesn't swallow the following day on a calendar that draws all-day events first.
_DEFAULT_TIMED_HOURS = 12


def style_for(category):
    """The fill colour, text colour and legend label one category draws with."""
    return CATEGORY_STYLES.get((category or '').strip().lower(), _DEFAULT_STYLE)


def parse_time(value):
    """A time written any of the ways this app stores one, as a `(hour, minute)`.

    Class times come out of the catalog as 'HH:MM', shift start times out of
    shift_definitions as 'HHMM', and a session picked on the enrollment screen can
    carry either. None means "no time recorded", which every writer renders as an
    all-day event rather than guessing an hour.
    """
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    meridiem = None
    for suffix in ('AM', 'PM'):
        if text.endswith(suffix):
            meridiem = suffix
            text = text[:-len(suffix)].strip()
            break
    try:
        if ':' in text:
            hour_text, minute_text = text.split(':', 1)
            hour, minute = int(hour_text), int(minute_text[:2])
        elif len(text) == 4 and text.isdigit():
            hour, minute = int(text[:2]), int(text[2:])
        elif text.isdigit():
            hour, minute = int(text), 0
        else:
            return None
    except (TypeError, ValueError):
        return None

    if meridiem == 'PM' and hour < 12:
        hour += 12
    elif meridiem == 'AM' and hour == 12:
        hour = 0

    if not (0 <= hour <= 24 and 0 <= minute <= 59):
        return None
    # 24:00 is a legitimate way to write the end of a day, and midnight is what it is.
    return (0, minute) if hour == 24 else (hour, minute)


def make_event(date, title, category='', start_time=None, end_time=None,
               location='', description='', code=''):
    """One event on one calendar day, in the shape every writer in this module takes.

    Args:
        date: The day the event happens, as a `date` or `datetime`.
        title: What the event is called in a calendar and on the PDF.
        category: Which of CATEGORY_STYLES draws it; anything unknown draws neutral.
        start_time / end_time: 'HH:MM' or 'HHMM'. Leave both out for an all-day event.
            An end at or before the start means the event runs past midnight.
        location: Free text; empty when there is nothing to say.
        description: The detail line calendars show when an event is opened.
        code: A short label the month grid prefers over `title` when it has one,
            because a grid cell fits "N7B" and does not fit a class's full name.

    Returns:
        dict: The event.
    """
    if isinstance(date, datetime):
        day = date.date()
    elif isinstance(date, date_type):
        day = date
    else:
        raise TypeError(f"An event needs a date, not {type(date).__name__}")

    start = parse_time(start_time)
    end = parse_time(end_time)
    # A time recorded at one end only is not enough to place an event in a day's grid,
    # and half a timed event imports as a mystery. Fall back to all-day.
    if not start:
        start = end = None

    return {
        'date': day,
        'title': str(title or '').strip(),
        'category': (category or '').strip().lower(),
        'start_time': start,
        'end_time': end,
        'location': str(location or '').strip(),
        'description': str(description or '').strip(),
        'code': str(code or '').strip(),
    }


def event_bounds(event):
    """An event's start and end as datetimes, all-day events included.

    An all-day event runs midnight to midnight. A timed event that ends at or before
    it starts crosses midnight, and its end lands on the following day — which is what
    keeps a 19:00 night shift twelve hours long instead of minus twelve.
    """
    day = event['date']
    start = event.get('start_time')
    end = event.get('end_time')

    if not start:
        begin = datetime(day.year, day.month, day.day)
        return begin, begin + timedelta(days=1)

    begin = datetime(day.year, day.month, day.day, start[0], start[1])
    if not end:
        return begin, begin + timedelta(hours=_DEFAULT_TIMED_HOURS)

    finish = datetime(day.year, day.month, day.day, end[0], end[1])
    if finish <= begin:
        finish += timedelta(days=1)
    return begin, finish


def sort_events(events):
    """Events in the order a person reads them: by day, all-day first, then by time."""
    def key(event):
        start = event.get('start_time')
        return (event['date'], 0 if not start else 1, start or (0, 0),
                event.get('title', ''))
    return sorted(events, key=key)


def events_in_range(events, start, end):
    """Only the events falling within [start, end], inclusive of both ends."""
    first = start.date() if isinstance(start, datetime) else start
    last = end.date() if isinstance(end, datetime) else end
    return [event for event in events if first <= event['date'] <= last]


def time_label(event):
    """How an event's hours read on the page: 'All day', or '7:00 AM - 7:00 PM'."""
    start = event.get('start_time')
    if not start:
        return 'All day'
    begin, finish = event_bounds(event)
    label = (f"{begin.strftime('%I:%M %p').lstrip('0')} - "
             f"{finish.strftime('%I:%M %p').lstrip('0')}")
    if finish.date() != begin.date():
        label += ' (next day)'
    return label


# --------------------------------------------------------------------------
# iCalendar (.ics) — Google Calendar, Outlook, Apple Calendar, anything else
# --------------------------------------------------------------------------

def to_ics(events, calendar_name='Schedule'):
    """The events as an .ics document.

    One file covers every calendar people here actually use, which is why it is the
    export offered first; the CSVs below exist for Google's and Outlook's own import
    screens, which some people reach for before the .ics one.
    """
    cal = Calendar()
    cal.add('prodid', '-//CrewOps360//Calendar Export//EN')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', calendar_name)
    cal.add('x-wr-timezone', 'America/New_York')

    stamp = datetime.now(timezone.utc)

    for event in sort_events(events):
        entry = Event()
        entry.add('summary', event['title'])
        entry.add('uid', str(uuid.uuid4()))
        entry.add('dtstamp', stamp)

        if event.get('start_time'):
            begin, finish = event_bounds(event)
            entry.add('dtstart', begin)
            entry.add('dtend', finish)
        else:
            day = event['date']
            # An all-day event's DTEND is exclusive, so a single day ends on the next.
            entry.add('dtstart', day)
            entry.add('dtend', day + timedelta(days=1))
            entry.add('X-MICROSOFT-CDO-ALLDAYEVENT', 'TRUE')

        if event.get('description'):
            entry.add('description', event['description'])
        if event.get('location'):
            entry.add('location', event['location'])
        if event.get('category'):
            entry.add('categories', [style_for(event['category'])['label']])
        # Nothing exported here is an invitation, and a calendar that treats it as one
        # starts mailing the owner about shifts they already work.
        entry.add('transp', 'TRANSPARENT')
        entry.add('status', 'CONFIRMED')

        cal.add_component(entry)

    return cal.to_ical().decode('utf-8')


# --------------------------------------------------------------------------
# CSV — Google Calendar's and Outlook's import screens
# --------------------------------------------------------------------------

_GOOGLE_HEADERS = ['Subject', 'Start Date', 'Start Time', 'End Date', 'End Time',
                   'All Day Event', 'Description', 'Location', 'Private']

# Outlook's classic CSV import matches on header text and is fussy about the casing
# of "All day event"; Google's is not. They are otherwise the same columns.
_OUTLOOK_HEADERS = ['Subject', 'Start Date', 'Start Time', 'End Date', 'End Time',
                    'All day event', 'Description', 'Location', 'Private']


def _csv_rows(events):
    """The shared body of both CSV exports: one row per event, dates as MM/DD/YYYY."""
    rows = []
    for event in sort_events(events):
        if event.get('start_time'):
            begin, finish = event_bounds(event)
            rows.append([
                event['title'],
                begin.strftime('%m/%d/%Y'),
                begin.strftime('%I:%M %p').lstrip('0'),
                finish.strftime('%m/%d/%Y'),
                finish.strftime('%I:%M %p').lstrip('0'),
                'False',
                event.get('description', ''),
                event.get('location', ''),
                'True',
            ])
        else:
            day = event['date'].strftime('%m/%d/%Y')
            # Both importers read an all-day row's end date as inclusive, unlike the
            # .ics above, so a one-day event starts and ends on the same date.
            rows.append([event['title'], day, '', day, '', 'True',
                         event.get('description', ''), event.get('location', ''),
                         'True'])
    return rows


def _write_csv(headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def to_google_csv(events):
    """The events as a CSV for Google Calendar's Import screen."""
    return _write_csv(_GOOGLE_HEADERS, _csv_rows(events))


def to_outlook_csv(events):
    """The events as a CSV for Outlook's Import and Export wizard."""
    return _write_csv(_OUTLOOK_HEADERS, _csv_rows(events))


# --------------------------------------------------------------------------
# PDF — a month grid per month, then an agenda
# --------------------------------------------------------------------------

def _months_between(start, end):
    """The first day of every month the span touches, in order."""
    months = []
    cursor = date_type(start.year, start.month, 1)
    last = date_type(end.year, end.month, 1)
    while cursor <= last:
        months.append(cursor)
        cursor = date_type(cursor.year + (cursor.month == 12),
                           (cursor.month % 12) + 1, 1)
    return months


def _group_by_day(events):
    grouped = {}
    for event in sort_events(events):
        grouped.setdefault(event['date'], []).append(event)
    return grouped


def _grid_label(event):
    """What one event reads as inside a month cell, where there is room for very little."""
    label = event.get('code') or event.get('title') or ''
    start = event.get('start_time')
    if start:
        hour, minute = start
        suffix = 'a' if hour < 12 else 'p'
        clock = f"{hour % 12 or 12}{'' if minute == 0 else ':%02d' % minute}{suffix}"
        return f"{clock} {label}".strip()
    return label


class _CalendarPDF:
    """The month-grid document, built around an fpdf2 page.

    Kept as a plain class rather than an FPDF subclass because the title block
    changes per month and a header() hook would have to be told which month it is
    drawing — which is most of what the hook saves you.
    """

    def __init__(self, title, subtitle=''):
        from fpdf import FPDF

        self.title = sanitize_text_for_pdf(title)
        self.subtitle = sanitize_text_for_pdf(subtitle)
        self.pdf = FPDF(orientation='L', unit='mm', format='Letter')
        self.pdf.set_auto_page_break(auto=False)
        self.pdf.set_margins(10, 10, 10)
        self.pdf.set_title(self.title)

    # -- page furniture ----------------------------------------------------

    @property
    def width(self):
        return self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def _text(self, x, y, width, height, text, align='L', border=0, fill=False):
        self.pdf.set_xy(x, y)
        self.pdf.cell(width, height, sanitize_text_for_pdf(text), border=border,
                      align=align, fill=fill)

    def _page_header(self, heading):
        pdf = self.pdf
        pdf.set_xy(pdf.l_margin, pdf.t_margin)
        pdf.set_text_color(20, 20, 20)
        pdf.set_font('Helvetica', 'B', 15)
        pdf.cell(self.width, 7, sanitize_text_for_pdf(self.title), align='L')

        pdf.set_xy(pdf.l_margin, pdf.t_margin)
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(self.width, 7,
                 f"Generated {datetime.now().strftime('%d %b %Y')}", align='R')

        y = pdf.t_margin + 7
        if self.subtitle:
            pdf.set_xy(pdf.l_margin, y)
            pdf.set_font('Helvetica', '', 9)
            pdf.cell(self.width, 5, self.subtitle, align='L')
            y += 5

        pdf.set_xy(pdf.l_margin, y)
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(self.width, 7, sanitize_text_for_pdf(heading), align='L')
        return y + 8

    def _footer(self, note=''):
        pdf = self.pdf
        pdf.set_xy(pdf.l_margin, pdf.h - 12)
        pdf.set_font('Helvetica', 'I', 7)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(self.width / 2, 5, sanitize_text_for_pdf(note), align='L')
        pdf.set_xy(pdf.l_margin + self.width / 2, pdf.h - 12)
        pdf.cell(self.width / 2, 5, f"Page {pdf.page_no()}", align='R')

    def _legend(self, y, categories):
        pdf = self.pdf
        pdf.set_font('Helvetica', '', 7)
        x = pdf.l_margin
        for category in categories:
            style = style_for(category)
            pdf.set_fill_color(*style['fill'])
            pdf.set_draw_color(190, 190, 190)
            pdf.rect(x, y, 3.5, 3.5, style='DF')
            pdf.set_text_color(70, 70, 70)
            pdf.set_xy(x + 4.5, y - 0.6)
            pdf.cell(28, 4.5, style['label'], align='L')
            x += 34
        return y + 6

    # -- the grid ----------------------------------------------------------

    def add_month(self, month_start, events_by_day, categories, note=''):
        pdf = self.pdf
        pdf.add_page()
        heading = month_start.strftime('%B %Y')
        y = self._page_header(heading)
        y = self._legend(y, categories)

        weeks = SUNDAY_FIRST.monthdatescalendar(month_start.year, month_start.month)
        column = self.width / 7
        header_height = 6
        bottom = pdf.h - 16
        row_height = (bottom - (y + header_height)) / len(weeks)

        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_fill_color(55, 65, 81)
        pdf.set_text_color(255, 255, 255)
        for index, name in enumerate(WEEKDAY_HEADINGS):
            self._text(pdf.l_margin + index * column, y, column, header_height,
                       name, align='C', border=1, fill=True)

        top = y + header_height
        for week_index, week in enumerate(weeks):
            row_y = top + week_index * row_height
            for day_index, day in enumerate(week):
                self._draw_day(pdf.l_margin + day_index * column, row_y, column,
                               row_height, day, month_start.month,
                               events_by_day.get(day, []))

        self._footer(note)

    def _draw_day(self, x, y, width, height, day, month, events):
        pdf = self.pdf
        in_month = day.month == month

        pdf.set_draw_color(170, 170, 170)
        pdf.set_fill_color(*((255, 255, 255) if in_month else (245, 245, 245)))
        pdf.rect(x, y, width, height, style='DF')

        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_text_color(*((60, 60, 60) if in_month else (170, 170, 170)))
        self._text(x + 1, y + 0.5, width - 2, 4, str(day.day), align='L')

        if not in_month or not events:
            return

        # Chips fill downward from under the day number. What doesn't fit is counted
        # rather than dropped — a cell that silently loses a class reads as a free day.
        chip_height = 4.2
        chip_gap = 0.6
        cursor = y + 5
        limit = y + height - 1.5
        drawn = 0

        for event in events:
            if cursor + chip_height > limit:
                break
            style = style_for(event['category'])
            pdf.set_fill_color(*style['fill'])
            pdf.set_draw_color(*style['fill'])
            pdf.rect(x + 0.8, cursor, width - 1.6, chip_height, style='DF')
            pdf.set_text_color(*style['text'])
            pdf.set_font('Helvetica', '', 5.5)
            self._text(x + 1.4, cursor - 0.2, width - 2.8, chip_height + 0.4,
                       _fit(pdf, _grid_label(event), width - 2.8), align='L')
            cursor += chip_height + chip_gap
            drawn += 1

        remaining = len(events) - drawn
        if remaining > 0:
            pdf.set_font('Helvetica', 'I', 5)
            pdf.set_text_color(110, 110, 110)
            self._text(x + 1.4, min(cursor, limit - 3) - 0.3, width - 2.8, 3.5,
                       f"+{remaining} more", align='L')

    # -- the agenda --------------------------------------------------------

    def add_agenda(self, events, note=''):
        pdf = self.pdf
        pdf.add_page()
        y = self._page_header('Detail')

        columns = [('Date', 28), ('Day', 14), ('Time', 42), ('Event', 88),
                   ('Location', 32), ('Notes', 0)]
        widths = [width or (self.width - sum(w for _, w in columns[:-1]))
                  for _, width in columns]

        def heading_row(y):
            pdf.set_font('Helvetica', 'B', 8)
            pdf.set_fill_color(55, 65, 81)
            pdf.set_text_color(255, 255, 255)
            x = pdf.l_margin
            for (name, _), width in zip(columns, widths):
                self._text(x, y, width, 6, name, align='L', border=1, fill=True)
                x += width
            return y + 6

        y = heading_row(y)
        bottom = pdf.h - 16
        row_height = 5
        shade = False

        for event in sort_events(events):
            if y + row_height > bottom:
                self._footer(note)
                pdf.add_page()
                y = heading_row(self._page_header('Detail (continued)'))
                shade = False

            # Rows alternate a neutral tint for readability, and carry the event's
            # category as a stripe down their left edge. Tinting the whole row by
            # category instead made every other row a different colour from the one
            # above it for two unrelated reasons at once.
            style = style_for(event['category'])
            pdf.set_fill_color(*((248, 249, 250) if shade else (255, 255, 255)))
            pdf.set_draw_color(215, 215, 215)
            pdf.rect(pdf.l_margin, y, self.width, row_height, style='DF')
            pdf.set_fill_color(*style['text'])
            pdf.rect(pdf.l_margin, y, 1.2, row_height, style='F')

            pdf.set_text_color(35, 35, 35)
            pdf.set_font('Helvetica', '', 7)
            cells = [
                event['date'].strftime('%d %b %Y'),
                event['date'].strftime('%a'),
                time_label(event),
                event['title'],
                event.get('location', ''),
                event.get('description', ''),
            ]
            x = pdf.l_margin
            for index, (text, width) in enumerate(zip(cells, widths)):
                # The first column starts past the category stripe.
                offset = 1.2 if index == 0 else 0
                usable = width - 2 - offset
                self._text(x + 1 + offset, y, usable, row_height,
                           _fit(pdf, text, usable), align='L')
                x += width

            y += row_height
            shade = not shade

        self._footer(note)

    def output(self):
        return bytes(self.pdf.output())


def _fit(pdf, text, max_width):
    """`text` shortened until it fits `max_width`, with an ellipsis when it was cut."""
    text = sanitize_text_for_pdf(str(text or ''))
    if pdf.get_string_width(text) <= max_width:
        return text
    while text and pdf.get_string_width(text + '...') > max_width:
        text = text[:-1]
    return (text + '...') if text else ''


def to_pdf(events, title, subtitle='', start=None, end=None, note='',
           include_agenda=True):
    """The events as a printable PDF: a month grid per month, then a detail table.

    Args:
        events: The events to draw. Anything outside [start, end] is dropped, so a
            caller can hand over a whole year and print one month of it.
        title: The heading on every page.
        subtitle: The line under it — who or what the calendar is for.
        start / end: The span to print. Defaults to the span the events cover; a span
            with no events at all still prints its months, empty, rather than
            producing a document with no pages.
        note: The footer line, for the caveat a particular calendar needs.
        include_agenda: Whether to append the detail table after the grids.

    Returns:
        bytes: The PDF.
    """
    events = list(events or [])
    days = [event['date'] for event in events]

    first = start.date() if isinstance(start, datetime) else start
    last = end.date() if isinstance(end, datetime) else end
    first = first or (min(days) if days else date_type.today())
    last = last or (max(days) if days else first)
    if last < first:
        first, last = last, first

    events = events_in_range(events, first, last)
    by_day = _group_by_day(events)
    categories = []
    for event in events:
        if event['category'] not in categories:
            categories.append(event['category'])

    document = _CalendarPDF(title, subtitle)
    for month_start in _months_between(first, last):
        document.add_month(month_start, by_day, categories, note=note)
    if include_agenda and events:
        document.add_agenda(events, note=note)
    return document.output()
