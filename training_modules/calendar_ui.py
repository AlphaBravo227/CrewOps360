# training_modules/calendar_ui.py
"""
The two calendar screens: a staff member's combined track-and-training calendar, and
the company-wide training calendar.

Both are the same screen wearing different hats — pick a span, look at the months,
take away a file — so the month grid, the detail table and the four download buttons
are written once here and both screens call them. What differs is only where the
events come from, which `schedule_calendar` answers.

Files are built when the buttons are drawn rather than behind a "prepare" click,
because a download button has to have its bytes in hand before it can be pressed. A
small per-span cache keeps that from re-rendering a year of PDF on every checkbox.
"""

import hashlib
import html
from datetime import date as date_type, datetime, timedelta

import pandas as pd
import streamlit as st

from modules.calendar_formats import (
    WEEKDAY_HEADINGS,
    SUNDAY_FIRST,
    events_in_range,
    sort_events,
    style_for,
    time_label,
    to_google_csv,
    to_ics,
    to_outlook_csv,
    to_pdf,
)

CACHE_KEY = 'calendar_export_cache'

# How many files are kept built at once. Each is a few hundred kilobytes at most and
# this only has to outlast the checkbox someone is toggling.
CACHE_LIMIT = 8


def _cached(signature, build):
    """`build()`'s result, remembered against `signature` for this session.

    A download button needs its bytes before it is clicked, so every rerun of the tab
    would otherwise rebuild a year of PDF to draw a button nobody presses.
    """
    cache = st.session_state.setdefault(CACHE_KEY, {})
    key = hashlib.md5(str(signature).encode('utf-8')).hexdigest()
    if key not in cache:
        if len(cache) >= CACHE_LIMIT:
            cache.clear()
        cache[key] = build()
    return cache[key]


def _signature(events, *extra):
    """A stable fingerprint of an event list, for the cache above."""
    return (tuple(sorted(
        (event['date'].isoformat(), event['title'], event['category'],
         str(event.get('start_time')), str(event.get('end_time')),
         event.get('location', ''), event.get('description', ''))
        for event in events)), extra)


def months_in(start, end):
    """The first day of every month the span touches, in order."""
    months = []
    cursor = date_type(start.year, start.month, 1)
    last = date_type(end.year, end.month, 1)
    while cursor <= last:
        months.append(cursor)
        cursor = date_type(cursor.year + (cursor.month == 12),
                           (cursor.month % 12) + 1, 1)
    return months


# --------------------------------------------------------------------------
# on-screen views
# --------------------------------------------------------------------------

_GRID_CSS = """
<style>
.crewops-cal {width:100%; border-collapse:collapse; table-layout:fixed;
              font-size:0.78rem;}
.crewops-cal th {background:#374151; color:#fff; font-weight:600; padding:6px 4px;
                 text-align:center; border:1px solid #4b5563;}
.crewops-cal td {border:1px solid #d1d5db; vertical-align:top; height:92px;
                 padding:3px; width:14.28%;}
.crewops-cal td.outside {background:#f6f7f9;}
.crewops-cal .daynum {font-weight:700; color:#374151; font-size:0.72rem;
                      display:block; margin-bottom:2px;}
.crewops-cal td.outside .daynum {color:#b6bcc4;}
.crewops-cal .chip {display:block; border-radius:3px; padding:1px 4px;
                    margin-bottom:2px; font-size:0.66rem; line-height:1.25;
                    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.crewops-legend {margin:4px 0 8px 0; font-size:0.74rem;}
.crewops-legend span {display:inline-block; margin-right:14px;}
.crewops-legend i {display:inline-block; width:10px; height:10px; border-radius:2px;
                   margin-right:5px; vertical-align:-1px;}
</style>
"""


def _rgb(colour):
    return 'rgb(%d,%d,%d)' % tuple(colour)


def _legend_html(categories):
    parts = []
    for category in categories:
        style = style_for(category)
        parts.append(
            f"<span><i style=\"background:{_rgb(style['fill'])};"
            f"border:1px solid {_rgb(style['text'])}\"></i>"
            f"{html.escape(style['label'])}</span>")
    return f"<div class='crewops-legend'>{''.join(parts)}</div>" if parts else ''


def _chip_html(event):
    style = style_for(event['category'])
    start = event.get('start_time')
    if start:
        hour, minute = start
        clock = f"{hour % 12 or 12}{'' if minute == 0 else ':%02d' % minute}"
        clock += 'a' if hour < 12 else 'p'
        label = f"{clock} {event.get('code') or event['title']}"
    else:
        label = event.get('code') or event['title']
    tooltip = ' - '.join(part for part in (
        event['title'], time_label(event), event.get('location', ''),
        event.get('description', '')) if part)
    return (f"<span class='chip' title=\"{html.escape(tooltip)}\" "
            f"style=\"background:{_rgb(style['fill'])};color:{_rgb(style['text'])}\">"
            f"{html.escape(label)}</span>")


def render_month_grid(events, month_start):
    """One month drawn as a calendar, with a coloured chip per event."""
    by_day = {}
    for event in sort_events(events):
        by_day.setdefault(event['date'], []).append(event)

    categories = []
    for event in events:
        if event['category'] not in categories:
            categories.append(event['category'])

    rows = []
    for week in SUNDAY_FIRST.monthdatescalendar(month_start.year, month_start.month):
        cells = []
        for day in week:
            outside = day.month != month_start.month
            chips = '' if outside else ''.join(
                _chip_html(event) for event in by_day.get(day, []))
            cells.append(f"<td class='{'outside' if outside else ''}'>"
                         f"<span class='daynum'>{day.day}</span>{chips}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    header = ''.join(f"<th>{name}</th>" for name in WEEKDAY_HEADINGS)
    st.markdown(
        _GRID_CSS + _legend_html(categories) +
        f"<table class='crewops-cal'><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>",
        unsafe_allow_html=True)


def render_agenda(events):
    """The same events as a sortable table, for the people who would rather read a list."""
    if not events:
        st.info("Nothing scheduled in this range.")
        return
    frame = pd.DataFrame([{
        'Date': event['date'].strftime('%d %b %Y'),
        'Day': event['date'].strftime('%a'),
        'Time': time_label(event),
        'Event': event['title'],
        'Type': style_for(event['category'])['label'],
        'Location': event.get('location', ''),
        'Notes': event.get('description', ''),
    } for event in sort_events(events)])
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_calendar(events, start, end, key_prefix):
    """The month-by-month view, with a month picker when the span covers several."""
    months = months_in(start, end)
    if not months:
        st.info("Pick a start date on or before the end date.")
        return

    view = st.radio("View", options=['Month grid', 'List'], horizontal=True,
                    key=f"{key_prefix}_view")

    if view == 'List':
        render_agenda(events)
        return

    if len(months) > 1:
        labels = [month.strftime('%B %Y') for month in months]
        # Open on the month the span starts in rather than today's, which may not be
        # in the range at all.
        default = 0
        today = date_type.today()
        for index, month in enumerate(months):
            if (month.year, month.month) == (today.year, today.month):
                default = index
                break
        choice = st.select_slider("Month", options=labels, value=labels[default],
                                  key=f"{key_prefix}_month")
        month_start = months[labels.index(choice)]
    else:
        month_start = months[0]

    render_month_grid(events, month_start)

    shown = sum(1 for event in events if event['date'].month == month_start.month
                and event['date'].year == month_start.year)
    st.caption(f"{shown} item(s) in {month_start.strftime('%B %Y')}; "
               f"{len(events)} across the whole range.")


# --------------------------------------------------------------------------
# downloads
# --------------------------------------------------------------------------

def render_downloads(events, basename, title, subtitle, start, end, key_prefix,
                     note='', include_agenda=True):
    """The four take-away files, and how to get each one into a calendar."""
    if not events:
        st.info("There is nothing to export in this range yet.")
        return

    signature = _signature(events, title, subtitle, str(start), str(end),
                           note, include_agenda)
    stamp = datetime.now().strftime('%Y%m%d')
    safe = ''.join(char if char.isalnum() or char in '-_' else '_'
                   for char in basename).strip('_') or 'calendar'

    with st.spinner("Building your calendar files..."):
        pdf_bytes = _cached(('pdf',) + signature, lambda: to_pdf(
            events, title, subtitle=subtitle, start=start, end=end, note=note,
            include_agenda=include_agenda))
        ics_text = _cached(('ics',) + signature, lambda: to_ics(events, title))
        google_csv = _cached(('google',) + signature, lambda: to_google_csv(events))
        outlook_csv = _cached(('outlook',) + signature,
                              lambda: to_outlook_csv(events))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.download_button("📄 PDF", data=pdf_bytes,
                           file_name=f"{safe}_{stamp}.pdf", mime='application/pdf',
                           use_container_width=True, key=f"{key_prefix}_pdf")
    with col2:
        st.download_button("📅 iCal (.ics)", data=ics_text,
                           file_name=f"{safe}_{stamp}.ics", mime='text/calendar',
                           use_container_width=True, key=f"{key_prefix}_ics")
    with col3:
        st.download_button("🗓️ Google CSV", data=google_csv,
                           file_name=f"{safe}_google_{stamp}.csv", mime='text/csv',
                           use_container_width=True, key=f"{key_prefix}_google")
    with col4:
        st.download_button("📧 Outlook CSV", data=outlook_csv,
                           file_name=f"{safe}_outlook_{stamp}.csv", mime='text/csv',
                           use_container_width=True, key=f"{key_prefix}_outlook")

    st.caption(f"{len(events)} event(s) - "
               f"{start.strftime('%d %b %Y')} through {end.strftime('%d %b %Y')}")

    with st.expander("📖 How to import these", expanded=False):
        st.markdown("""
**The .ics file works everywhere and is the one to reach for first.**

**Google Calendar**
- *.ics:* Settings (⚙️) → *Import & export* → *Import* → choose the file → pick the
  calendar to add to.
- *Google CSV:* the same *Import* screen accepts it. Use this one if the .ics import
  is refused.

**Outlook (desktop)**
- *.ics:* double-click the file, or *File → Open & Export → Import/Export → Import an
  iCalendar (.ics) or vCalendar file*.
- *Outlook CSV:* *File → Open & Export → Import/Export → Import from another program
  or file → Comma Separated Values*, then pick your Calendar folder.

**Outlook on the web / Microsoft 365**
- *Add calendar → Upload from file*, then choose the .ics file.

**Apple Calendar**
- Double-click the .ics file, or *File → Import*.

A tip worth taking: import into a **new, separate calendar** rather than your main
one. These events are a snapshot, not a live feed — if your track or your enrollments
change, re-export and re-import. Having them in their own calendar means you can
delete the old copy in one go instead of hunting down duplicates.
""")


# --------------------------------------------------------------------------
# span pickers
# --------------------------------------------------------------------------

_PRESETS = {
    'Next 3 months': 90,
    'Next 6 months': 182,
    'Next 12 months': 365,
}


def pick_span(default_start, default_end, key_prefix, label="Date range"):
    """A preset-or-custom span picker, clamped to what the year actually covers.

    Returns:
        tuple: (start date, end date)
    """
    today = date_type.today()
    # Somebody looking at a year that has not started yet, or one that finished, gets
    # that year's own span rather than an empty window around today.
    anchor = min(max(today, default_start), default_end)

    options = ['Whole training year'] + list(_PRESETS) + ['Custom']
    choice = st.radio(label, options=options, horizontal=True,
                      key=f"{key_prefix}_preset")

    if choice == 'Whole training year':
        return default_start, default_end
    if choice == 'Custom':
        col1, col2 = st.columns(2)
        with col1:
            start = st.date_input("From", value=anchor, key=f"{key_prefix}_from")
        with col2:
            end = st.date_input("To", value=min(anchor + timedelta(days=90),
                                                default_end),
                                key=f"{key_prefix}_to")
        if end < start:
            st.warning("The end date is before the start date; showing one day.")
            end = start
        return start, end

    return anchor, min(anchor + timedelta(days=_PRESETS[choice]), default_end)


# --------------------------------------------------------------------------
# the two screens
# --------------------------------------------------------------------------

def overlapping_pairs(events):
    """Pairs of events that share time on the clock and aren't the same kind of thing.

    Two shifts on one day are the track's business and two classes at once is the
    enrollment screen's; what a combined calendar is for is the commitments from
    different places that land on top of each other — a shift running into a class, a
    class you are booked on the day you agreed to teach. All-day events have no hours
    to overlap, so they are left out rather than flagged against everything sharing
    their date.
    """
    from modules.calendar_formats import event_bounds

    timed = [event for event in sort_events(events) if event.get('start_time')]
    clashes = []
    for index, first in enumerate(timed):
        first_start, first_end = event_bounds(first)
        for second in timed[index + 1:]:
            second_start, second_end = event_bounds(second)
            if second_start >= first_end:
                # Sorted by start, so nothing later can overlap this one either.
                break
            if first['category'] == second['category']:
                continue
            if second_start < first_end and first_start < second_end:
                clashes.append((first, second))
    return clashes


def _render_conflicts(events):
    clashes = overlapping_pairs(events)
    if not clashes:
        return
    with st.expander(f"⚠️ {len(clashes)} overlap(s) on your calendar", expanded=False):
        st.caption("Commitments whose hours run into each other. An overlap here is "
                   "not necessarily a problem - a class you were released for still "
                   "shows against the shift you would otherwise have worked - but it "
                   "is worth a look.")
        for first, second in clashes:
            st.markdown(
                f"- **{first['date'].strftime('%a %d %b %Y')}** - "
                f"{first['title']} ({time_label(first)}) overlaps "
                f"{second['title']} ({time_label(second)})")


def render_my_calendar_tab(staff_name, track_manager=None, enrollment_manager=None,
                           educator_manager=None, catalog=None, year_row=None,
                           year_label='', is_educator_authorized=False):
    """A staff member's shifts and training on one calendar, with the files to take away."""
    from .schedule_calendar import personal_calendar, training_year_span

    st.header("📅 My Calendar")
    if not staff_name:
        st.info("Select your name above to see your calendar.")
        return

    st.caption("Your track shifts and your training commitments on one calendar - "
               "to look at, to print, or to load into Google Calendar, Outlook or "
               "Apple Calendar.")

    try:
        has_track = bool(track_manager and track_manager.has_track_data(staff_name))
    except Exception as e:
        # A calendar that cannot read a track is still a useful calendar of training.
        print(f"Could not check track data for {staff_name}: {e}")
        has_track = False
    if not has_track:
        st.warning("No track schedule was found for you in this year's cohort, so "
                   "only your training shows below.")

    year_start, year_end = training_year_span(year_row)
    start, end = pick_span(year_start, year_end, key_prefix='my_cal')

    columns = st.columns(3)
    with columns[0]:
        include_shifts = st.checkbox("Track shifts", value=has_track,
                                     disabled=not has_track, key='my_cal_shifts')
    with columns[1]:
        include_training = st.checkbox("My training", value=True,
                                       key='my_cal_training')
    with columns[2]:
        include_teaching = st.checkbox("Teaching days", value=is_educator_authorized,
                                       disabled=not is_educator_authorized,
                                       key='my_cal_teaching')

    events = personal_calendar(
        staff_name, start, end,
        track_manager=track_manager if has_track else None,
        enrollment_manager=enrollment_manager,
        educator_manager=educator_manager if is_educator_authorized else None,
        catalog=catalog,
        include_shifts=include_shifts,
        include_training=include_training,
        include_teaching=include_teaching)

    counts = {'shift': 0, 'training': 0, 'educator': 0}
    for event in events:
        counts[event['category']] = counts.get(event['category'], 0) + 1
    metrics = st.columns(3)
    metrics[0].metric("Shifts", counts.get('shift', 0))
    metrics[1].metric("Training days", counts.get('training', 0))
    metrics[2].metric("Teaching days", counts.get('educator', 0))

    _render_conflicts(events)

    st.markdown("---")
    render_calendar(events, start, end, key_prefix='my_cal')

    st.markdown("---")
    st.markdown("### 📥 Download & export")
    render_downloads(
        events,
        basename=f"{staff_name}_calendar",
        title=f"{staff_name} - Schedule",
        subtitle=' | '.join(part for part in (
            year_label, "Track shifts and training") if part),
        start=start, end=end, key_prefix='my_cal',
        note="Snapshot from CrewOps360 - re-export if your track or enrollments change.")


def render_company_calendar_tab(catalog=None, year_row=None, year_label='',
                                enrollment_manager=None, key_prefix='company_cal'):
    """Every class the training year runs, over whatever span is asked for."""
    from .schedule_calendar import company_training_calendar, training_year_span

    st.header("🏢 Company Training Calendar")
    if not catalog:
        st.warning("No class catalog is loaded for this training year.")
        return

    st.caption("Every class in the system over the period you choose - to look at, "
               "to print, or to load into Google Calendar or Outlook.")

    year_start, year_end = training_year_span(year_row)
    start, end = pick_span(year_start, year_end, key_prefix=key_prefix)

    try:
        all_classes = catalog.get_all_classes() or []
    except Exception as e:
        st.error(f"Could not list this year's classes: {e}")
        return

    if not all_classes:
        st.info(f"{year_label or 'This training year'} has no classes yet.")
        return

    chosen = st.multiselect(
        "Classes", options=all_classes, default=[],
        help="Leave empty for every class in the year.",
        key=f"{key_prefix}_classes")

    show_seats = st.checkbox(
        "Show how full each session is", value=True, key=f"{key_prefix}_seats",
        help="Reads the enrollment count for every session in the range; turn it off "
             "if a long range feels slow.")

    with st.spinner("Reading the training schedule..."):
        events = company_training_calendar(
            catalog, start, end, class_names=chosen or None,
            enrollment_manager=enrollment_manager if show_seats else None,
            include_seats=show_seats)

    locations = sorted({event['location'] for event in events if event['location']})
    if locations:
        picked = st.multiselect("Locations", options=locations, default=[],
                                help="Leave empty for every location.",
                                key=f"{key_prefix}_locations")
        if picked:
            events = [event for event in events if event['location'] in picked]

    metrics = st.columns(3)
    metrics[0].metric("Sessions", len(events))
    metrics[1].metric("Classes", len({event['title'].split(' (Day ')[0]
                                      for event in events}))
    metrics[2].metric("Days with training", len({event['date'] for event in events}))

    st.markdown("---")
    render_calendar(events, start, end, key_prefix=key_prefix)

    st.markdown("---")
    st.markdown("### 📥 Download & export")
    render_downloads(
        events,
        basename=f"{year_label or 'training'}_training_calendar",
        title=f"{year_label + ' ' if year_label else ''}Training Calendar".strip(),
        subtitle="All scheduled classes",
        start=start, end=end, key_prefix=key_prefix,
        note="Snapshot from CrewOps360 - re-export when the schedule changes.")
