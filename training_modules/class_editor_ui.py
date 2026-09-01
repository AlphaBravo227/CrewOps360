# training_modules/class_editor_ui.py
"""
Creating and reconfiguring a training class, in the app.

Classes used to be built in the roster workbook: a column on `Class_Enrollment` and a
detail sheet whose settings sat at fixed cells nobody could see the meaning of without
the README beside them. This is that same set of settings as a form, plus the two things
the sheet could not express — a class with any number of dates, and a date that runs at
more than one location.

The form is deliberately the same for creating and for editing. An existing class loads
its own values in, so reconfiguring is not a second, thinner screen that quietly supports
fewer options than the one that created it.

Date entry is incremental: pick a first date, click "Add another date" for the next. A
date's locations work the same way — one to begin with, "Add another location" for a day
taught at two sites, each with its own time and seat count.
"""

from datetime import date, datetime

import streamlit as st

from training_modules import class_catalog as catalog

try:
    from modules import staff_database as staffdb
except Exception as e:  # pragma: no cover
    staffdb = None
    print(f"Staff database unavailable to the class editor: {e}")


# The working copy of the class being edited. Held in session state because Streamlit
# reruns the script on every click: an "Add another date" that only appended to a local
# list would be gone by the time the page redrew.
DRAFT_KEY = 'training_class_draft'
DRAFT_FOR_KEY = 'training_class_draft_for'


def _blank_option():
    return {'location': '', 'start_time': '', 'end_time': '', 'capacity': None}


def _blank_date():
    return {'class_date': None, 'has_live': False, 'can_work_n_prior': False,
            'options': [_blank_option()]}


def _blank_draft():
    return {
        'class_name': '',
        'settings': {
            'students_per_class': 21,
            'classes_per_day': 1,
            'instructors_per_day': 0,
            'time_1_start': '08:00',
            'time_1_end': '16:00',
            'time_2_start': '', 'time_2_end': '',
            'time_3_start': '', 'time_3_end': '',
            'time_4_start': '', 'time_4_end': '',
            'has_ccemt': False,
            'is_multi_session': False,
            'session_length': None,
            'is_count_exempt': False,
            'nurses_medic_separate': False,
            'is_two_day_class': False,
            'is_staff_meeting': False,
            'notes': '',
        },
        'dates': [_blank_date()],
        'assigned_staff': [],
        'assignment_source': {'education_groups': [], 'or_groups': []},
    }


def _parse_date(value):
    """A stored 'MM/DD/YYYY' as a date object for the picker, or None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%m/%d/%Y').date()
    except (TypeError, ValueError):
        return None


def _draft_from_class(record):
    """Turn a stored class into the working copy the form edits."""
    settings = dict(record['settings'])
    draft = _blank_draft()
    draft['class_name'] = record['class_name']
    draft['assigned_staff'] = list(record['assigned_staff'])
    draft['assignment_source'] = (record.get('assignment_source')
                                  or {'education_groups': [], 'or_groups': []})

    for key in ('students_per_class', 'classes_per_day', 'instructors_per_day',
                'session_length'):
        draft['settings'][key] = settings.get(key)
    for key in ('time_1_start', 'time_1_end', 'time_2_start', 'time_2_end',
                'time_3_start', 'time_3_end', 'time_4_start', 'time_4_end'):
        draft['settings'][key] = settings.get(key) or ''
    for key in ('has_ccemt', 'is_multi_session', 'is_count_exempt',
                'nurses_medic_separate', 'is_two_day_class'):
        draft['settings'][key] = bool(settings.get(key))
    # A NULL is_staff_meeting means "never set" — the name rule decided it. Show the
    # answer that rule would give, so the box reflects how the class actually behaves.
    meeting = settings.get('is_staff_meeting')
    draft['settings']['is_staff_meeting'] = (
        'SM' in record['class_name'].upper() if meeting is None else bool(meeting))
    draft['settings']['notes'] = settings.get('notes') or ''

    draft['dates'] = [{
        'class_date': _parse_date(entry['class_date']),
        'has_live': entry['has_live'],
        'can_work_n_prior': entry['can_work_n_prior'],
        'options': [{'location': option['location'],
                     'start_time': option['start_time'] or '',
                     'end_time': option['end_time'] or '',
                     'capacity': option['capacity']}
                    for option in entry['options']] or [_blank_option()],
    } for entry in record['dates']] or [_blank_date()]
    return draft


def load_draft(training_year, class_name=None, db_path=catalog.DEFAULT_DB_PATH):
    """
    Put the class being worked on into session state, once.

    Reloading it on every rerun would throw away every unsaved edit the moment anyone
    clicked anything, so the draft is rebuilt only when the target changes.
    """
    target = (training_year, class_name)
    if st.session_state.get(DRAFT_FOR_KEY) == target and DRAFT_KEY in st.session_state:
        return st.session_state[DRAFT_KEY]

    if class_name:
        record = catalog.load_class_for_editing(training_year, class_name,
                                                db_path=db_path)
        draft = _draft_from_class(record) if record else _blank_draft()
    else:
        draft = _blank_draft()

    st.session_state[DRAFT_KEY] = draft
    st.session_state[DRAFT_FOR_KEY] = target
    return draft


def clear_draft():
    """Forget the working copy, after saving or cancelling."""
    st.session_state.pop(DRAFT_KEY, None)
    st.session_state.pop(DRAFT_FOR_KEY, None)


# ---------------------------------------------------------------------------
# Staff selection
# ---------------------------------------------------------------------------

def _group_members(education_groups, or_groups):
    """
    Everyone in the chosen education groups and OR groups, as one list.

    The two groupings are independent placements, so picking "Group 2" and "4 OR"
    means everyone in either — a class taught to a cohort plus everyone who owes four
    OR days, not only the people who are both.
    """
    if staffdb is None:
        return []
    names = []
    for group in education_groups:
        try:
            names.extend(staffdb.get_education_group_members(group))
        except Exception as e:
            print(f"Error reading education group {group}: {e}")
    for group in or_groups:
        try:
            names.extend(staffdb.get_or_group_members(group))
        except Exception as e:
            print(f"Error reading OR group {group}: {e}")
    return sorted(dict.fromkeys(names))


def _render_staff_assignment(draft):
    """Who the class is for."""
    st.markdown("#### Assigned staff")
    st.caption(
        "Assigned staff are the people who see this class on their registration "
        "screen. Pick groups to fill the list quickly, then add or remove "
        "individuals — the list below is what gets saved, so a later change to "
        "somebody's group placement leaves this class alone.")

    if staffdb is None:
        st.error("The staff database is unavailable, so staff cannot be assigned.")
        return

    source = draft.get('assignment_source') or {'education_groups': [], 'or_groups': []}

    group_columns = st.columns(2)
    with group_columns[0]:
        education_groups = st.multiselect(
            "Education groups", options=staffdb.EDUCATION_GROUPS,
            default=[g for g in source.get('education_groups', [])
                     if g in staffdb.EDUCATION_GROUPS],
            format_func=lambda g: f"Group {g}",
            key="class_editor_education_groups",
            help="The cohort a staff member attends recurring education with.")
    with group_columns[1]:
        or_groups = st.multiselect(
            "OR groups", options=staffdb.OR_GROUPS,
            default=[g for g in source.get('or_groups', [])
                     if g in staffdb.OR_GROUPS],
            format_func=lambda g: "No OR" if g == 0 else f"{g} OR",
            key="class_editor_or_groups",
            help="How many OR classes a staff member signs up for over the year. "
                 "'No OR' is a real placement — those people are required to take none.")

    draft['assignment_source'] = {'education_groups': education_groups,
                                  'or_groups': or_groups}

    matched = _group_members(education_groups, or_groups)
    if education_groups or or_groups:
        st.caption(f"Those groups hold **{len(matched)}** staff right now.")
        fill_columns = st.columns(2)
        with fill_columns[0]:
            if st.button("➕ Add everyone in those groups", use_container_width=True,
                         key="class_editor_add_groups"):
                draft['assigned_staff'] = sorted(
                    dict.fromkeys(list(draft['assigned_staff']) + matched))
                st.rerun()
        with fill_columns[1]:
            if st.button("➖ Remove everyone in those groups", use_container_width=True,
                         key="class_editor_remove_groups"):
                draft['assigned_staff'] = [name for name in draft['assigned_staff']
                                           if name not in set(matched)]
                st.rerun()

        unplaced = [name for name in matched if name not in set(staffdb.get_staff_names())]
        if unplaced:
            st.caption(f"{len(unplaced)} of them are inactive on the roster.")

    everyone = staffdb.get_staff_names()
    # Somebody assigned to the class who has since been marked inactive still belongs
    # on the list — dropping them from the options would silently unassign them on the
    # next save.
    options = sorted(dict.fromkeys(list(everyone) + list(draft['assigned_staff'])))
    draft['assigned_staff'] = st.multiselect(
        f"Assigned staff ({len(draft['assigned_staff'])})",
        options=options,
        default=[name for name in draft['assigned_staff'] if name in options],
        key="class_editor_assigned_staff")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def _render_dates(draft):
    """The class's dates, and the locations each one runs at."""
    st.markdown("#### Dates")
    st.caption(
        "Add as many dates as the class needs. A date taught at more than one site "
        "gets a location per site: each is bookable separately, with its own times "
        "and its own seat count, and staff pick which one they are attending.")

    is_meeting = draft['settings'].get('is_staff_meeting')
    removing = None

    for index, entry in enumerate(draft['dates']):
        with st.container(border=True):
            header = st.columns([5, 1])
            with header[0]:
                st.markdown(f"**Date {index + 1}**")
            with header[1]:
                # Never offer to remove the only date — a class with no dates shows
                # staff a "not configured" warning, which is not something to reach
                # by clicking a button labelled Remove.
                if len(draft['dates']) > 1:
                    if st.button("Remove", key=f"class_editor_remove_date_{index}",
                                 use_container_width=True):
                        removing = index

            entry['class_date'] = st.date_input(
                "Date", value=entry['class_date'], key=f"class_editor_date_{index}",
                format="MM/DD/YYYY")

            flag_columns = st.columns(2)
            with flag_columns[0]:
                entry['can_work_n_prior'] = st.checkbox(
                    "Staff can work the night before", value=entry['can_work_n_prior'],
                    key=f"class_editor_nprior_{index}",
                    help="Leave unchecked and a night shift the evening before counts "
                         "as a conflict for this date.")
            with flag_columns[1]:
                if is_meeting:
                    entry['has_live'] = st.checkbox(
                        "LIVE option available", value=entry['has_live'],
                        key=f"class_editor_live_{index}",
                        help="Staff meetings only: offers this date as LIVE as well "
                             "as Virtual.")
                else:
                    entry['has_live'] = False

            st.markdown("**Locations**")
            option_removing = None
            for option_index, option in enumerate(entry['options']):
                option_columns = st.columns([3, 2, 2, 2, 1])
                with option_columns[0]:
                    option['location'] = st.text_input(
                        "Location", value=option['location'],
                        key=f"class_editor_loc_{index}_{option_index}",
                        placeholder="KBED")
                with option_columns[1]:
                    option['start_time'] = st.text_input(
                        "Start", value=option['start_time'] or '',
                        key=f"class_editor_start_{index}_{option_index}",
                        placeholder=draft['settings'].get('time_1_start') or '08:00')
                with option_columns[2]:
                    option['end_time'] = st.text_input(
                        "End", value=option['end_time'] or '',
                        key=f"class_editor_end_{index}_{option_index}",
                        placeholder=draft['settings'].get('time_1_end') or '16:00')
                with option_columns[3]:
                    capacity = st.text_input(
                        "Seats", value=('' if option['capacity'] is None
                                        else str(option['capacity'])),
                        key=f"class_editor_cap_{index}_{option_index}",
                        placeholder=str(draft['settings'].get('students_per_class')
                                        or 21))
                    option['capacity'] = catalog.parse_int(capacity)
                with option_columns[4]:
                    st.write("")
                    if len(entry['options']) > 1:
                        if st.button("✕", key=f"class_editor_rmloc_{index}_{option_index}",
                                     help="Remove this location"):
                            option_removing = option_index

            if option_removing is not None:
                entry['options'].pop(option_removing)
                st.rerun()

            st.caption("Times and seats left blank fall back to the class settings "
                       "below, which is what a class taught at one site wants.")

            if st.button("➕ Add another location", key=f"class_editor_addloc_{index}"):
                entry['options'].append(_blank_option())
                st.rerun()

    if removing is not None:
        draft['dates'].pop(removing)
        st.rerun()

    if st.button("➕ Add another date", key="class_editor_add_date",
                 use_container_width=True):
        draft['dates'].append(_blank_date())
        st.rerun()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _render_settings(draft):
    """Everything the class's detail sheet used to carry at a fixed cell."""
    settings = draft['settings']

    st.markdown("#### Class settings")
    columns = st.columns(3)
    with columns[0]:
        settings['students_per_class'] = st.number_input(
            "Students per class", min_value=1, max_value=500,
            value=int(settings.get('students_per_class') or 21),
            key="class_editor_students",
            help="The seat count a date uses when its locations don't set their own.")
    with columns[1]:
        settings['classes_per_day'] = st.number_input(
            "Classes per day", min_value=1, max_value=4,
            value=int(settings.get('classes_per_day') or 1),
            key="class_editor_per_day",
            help="More than one runs the class several times a day, using the time "
                 "slots below.")
    with columns[2]:
        settings['instructors_per_day'] = st.number_input(
            "Instructors needed per day", min_value=0, max_value=20,
            value=int(settings.get('instructors_per_day') or 0),
            key="class_editor_instructors",
            help="Zero means the class takes no educator signups.")

    flag_columns = st.columns(3)
    with flag_columns[0]:
        settings['is_staff_meeting'] = st.checkbox(
            "Staff meeting", value=bool(settings.get('is_staff_meeting')),
            key="class_editor_is_meeting",
            help="Staff meetings are booked as LIVE or Virtual and count towards the "
                 "meeting requirement. This used to be inferred from 'SM' appearing "
                 "in the class name.")
        settings['nurses_medic_separate'] = st.checkbox(
            "Nurses and medics enrolled separately",
            value=bool(settings.get('nurses_medic_separate')),
            key="class_editor_nm_separate",
            help="Splits each session's seats between the two roles.")
    with flag_columns[1]:
        settings['has_ccemt'] = st.checkbox(
            "CCEMT role split", value=bool(settings.get('has_ccemt')),
            key="class_editor_ccemt",
            help="With nurse/medic separation on, gives each session one nurse, one "
                 "medic and one CCEMT seat.")
        settings['is_two_day_class'] = st.checkbox(
            "Two-day class", value=bool(settings.get('is_two_day_class')),
            key="class_editor_two_day",
            help="Each date covers that day and the next. Staff enroll once for both.")
    with flag_columns[2]:
        settings['is_count_exempt'] = st.checkbox(
            "Count-exempt", value=bool(settings.get('is_count_exempt')),
            key="class_editor_count_exempt",
            help="Lets a non-management medic take a second class in the same week.")
        settings['is_multi_session'] = st.checkbox(
            "Multi-session", value=bool(settings.get('is_multi_session')),
            key="class_editor_multi_session",
            help="Splits the day into back-to-back sessions of the length below, "
                 "between the Time 1 start and end.")

    if settings['is_multi_session']:
        settings['session_length'] = st.number_input(
            "Session length (minutes)", min_value=5, max_value=600,
            value=int(settings.get('session_length') or 60),
            key="class_editor_session_length")
    else:
        settings['session_length'] = None

    st.markdown("**Time slots**")
    st.caption("Slot 1 is the class's ordinary day, and is what a date's locations "
               "fall back to. Slots 2-4 are used when a class runs more than once a "
               "day.")
    slots = int(settings.get('classes_per_day') or 1)
    for slot in range(1, 5):
        if slot > 1 and slot > slots:
            settings[f'time_{slot}_start'] = ''
            settings[f'time_{slot}_end'] = ''
            continue
        time_columns = st.columns(2)
        with time_columns[0]:
            settings[f'time_{slot}_start'] = st.text_input(
                f"Time {slot} start", value=settings.get(f'time_{slot}_start') or '',
                key=f"class_editor_t{slot}s", placeholder="08:00")
        with time_columns[1]:
            settings[f'time_{slot}_end'] = st.text_input(
                f"Time {slot} end", value=settings.get(f'time_{slot}_end') or '',
                key=f"class_editor_t{slot}e", placeholder="16:00")

    settings['notes'] = st.text_area(
        "Notes (admin only)", value=settings.get('notes') or '',
        key="class_editor_notes",
        help="Not shown to staff. Somewhere to record why the class is set up as it is.")


# ---------------------------------------------------------------------------
# Validation and saving
# ---------------------------------------------------------------------------

def _validate(draft, training_year, original_name, db_path):
    """What is wrong with the draft, as a list of messages. Empty means it will save."""
    problems = []

    name = (draft['class_name'] or '').strip()
    if not name:
        problems.append("The class needs a name.")
    elif name != (original_name or ''):
        if name in catalog.get_class_names(training_year, db_path=db_path):
            problems.append(f"{training_year} already has a class called '{name}'.")

    entered = [entry for entry in draft['dates'] if entry.get('class_date')]
    if not entered:
        problems.append("The class needs at least one date. A class with no dates "
                        "shows staff a 'not configured' warning instead of a schedule.")

    seen = set()
    for entry in entered:
        stamp = entry['class_date'].strftime('%m/%d/%Y')
        if stamp in seen:
            problems.append(f"{stamp} is listed twice. Add a second location to that "
                            f"date rather than a second copy of the date.")
        seen.add(stamp)

        locations = [(option.get('location') or '').strip() for option in entry['options']]
        named = [location for location in locations if location]
        if len(locations) > 1 and len(named) < len(locations):
            problems.append(f"Every location on {stamp} needs a name — that is what "
                            f"staff pick between.")
        if len(named) != len(set(named)):
            problems.append(f"{stamp} lists the same location twice.")

        for option in entry['options']:
            for field, label in (('start_time', 'start'), ('end_time', 'end')):
                raw = (option.get(field) or '').strip()
                if raw and not catalog.parse_time(raw):
                    problems.append(
                        f"'{raw}' on {stamp} isn't a time the app can read. "
                        f"Use HH:MM, like 08:00.")

    for slot in range(1, 5):
        for field in ('start', 'end'):
            raw = (draft['settings'].get(f'time_{slot}_{field}') or '').strip()
            if raw and not catalog.parse_time(raw):
                problems.append(f"Time {slot} {field} '{raw}' isn't a time the app "
                                f"can read. Use HH:MM, like 08:00.")

    if draft['settings'].get('has_ccemt') and not draft['settings'].get(
            'nurses_medic_separate'):
        problems.append("The CCEMT role split only applies when nurses and medics "
                        "are enrolled separately.")

    if not draft['assigned_staff']:
        problems.append("Nobody is assigned to the class, so nobody would see it. "
                        "Assign at least one staff member.")

    return problems


def _save(draft, training_year, original_name, db_path):
    """Write the draft to the catalog. Returns (ok, message)."""
    name = draft['class_name'].strip()
    dates = [{
        'class_date': entry['class_date'].strftime('%m/%d/%Y'),
        'has_live': entry['has_live'],
        'can_work_n_prior': entry['can_work_n_prior'],
        'options': [{'location': (option.get('location') or '').strip(),
                     'start_time': (option.get('start_time') or '').strip(),
                     'end_time': (option.get('end_time') or '').strip(),
                     'capacity': option.get('capacity')}
                    for option in entry['options']],
    } for entry in draft['dates'] if entry.get('class_date')]

    try:
        # Renaming first, so the class's enrollments and educator signups travel with
        # it. Saving under the new name alone would leave them pointing at a class
        # that no longer exists.
        if original_name and name != original_name:
            catalog.rename_class(training_year, original_name, name, db_path=db_path)

        record = catalog.get_class_row(training_year, name, db_path=db_path)
        catalog.save_class(
            training_year, name,
            settings=draft['settings'], dates=dates,
            assigned_staff=draft['assigned_staff'],
            class_id=record['id'] if record else None,
            source=(record or {}).get('source') or 'app',
            assignment_source=draft.get('assignment_source'),
            db_path=db_path)
        return True, f"Saved **{name}** — {len(dates)} date(s), " \
                     f"{len(draft['assigned_staff'])} staff assigned."
    except Exception as e:
        return False, f"Could not save the class: {e}"


# ---------------------------------------------------------------------------
# The form
# ---------------------------------------------------------------------------

def render_class_form(training_year, class_name=None, db_path=catalog.DEFAULT_DB_PATH,
                      on_saved=None):
    """
    The create/edit form for one class.

    `class_name` None creates a new class; a name loads that one for reconfiguring.
    `on_saved` is called after a successful save, for the caller to leave the form.
    """
    draft = load_draft(training_year, class_name, db_path=db_path)

    draft['class_name'] = st.text_input(
        "Class name", value=draft['class_name'], key="class_editor_name",
        help="What staff see, and what enrollments are recorded against. Renaming an "
             "existing class carries its enrollments and educator signups with it.")

    _render_settings(draft)
    st.markdown("---")
    _render_dates(draft)
    st.markdown("---")
    _render_staff_assignment(draft)
    st.markdown("---")

    problems = _validate(draft, training_year, class_name, db_path)
    if problems:
        st.warning("**Before this can be saved:**\n\n"
                   + "\n".join(f"- {problem}" for problem in problems))

    action_columns = st.columns([2, 2, 6])
    with action_columns[0]:
        if st.button("💾 Save class", type="primary", disabled=bool(problems),
                     use_container_width=True, key="class_editor_save"):
            saved, message = _save(draft, training_year, class_name, db_path)
            if saved:
                clear_draft()
                st.success(message)
                if on_saved:
                    on_saved()
                st.rerun()
            else:
                st.error(message)
    with action_columns[1]:
        if st.button("Cancel", use_container_width=True, key="class_editor_cancel"):
            clear_draft()
            if on_saved:
                on_saved()
            st.rerun()
