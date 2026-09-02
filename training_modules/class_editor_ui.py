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
    from modules import staff_groupings
except Exception as e:  # pragma: no cover
    staffdb = None
    staff_groupings = None
    print(f"Staff database unavailable to the class editor: {e}")


# The working copy of the class being edited. Held in session state because Streamlit
# reruns the script on every click: an "Add another date" that only appended to a local
# list would be gone by the time the page redrew.
DRAFT_KEY = 'training_class_draft'
DRAFT_FOR_KEY = 'training_class_draft_for'

# A keyed Streamlit widget ignores the `value` or `default` it is handed once it has
# state of its own, and returns whatever the browser last had in it. So changing the
# draft in code - filling the staff list from a group, removing a date, loading a
# different class - does not reach the fields: the widget writes its old value straight
# back over the change on the next render, and the form silently disagrees with the
# draft it is supposed to be showing. Deleting the key does not help either, because the
# browser re-sends the value it is still displaying.
#
# So the widgets are keyed with a token that changes whenever the draft changes
# underneath them. New key, new widget, initialized from the draft - which stays the one
# source of truth.
WIDGET_PREFIX = 'class_editor_'
TOKEN_KEY = 'training_class_widget_token'

# How long a calendar display label may be. The schedule report's date columns are
# 15 characters wide, so anything much past this is clipped in the very place the
# field exists to tidy up.
CALENDAR_DISPLAY_MAX = 20


def wkey(name):
    """The session key for one of this form's widgets, under the current token."""
    return f"{WIDGET_PREFIX}{name}_{st.session_state.get(TOKEN_KEY, 0)}"


def reset_widget_state():
    """Re-key every field, so they all re-read the draft on the next render."""
    stale = [key for key in st.session_state if key.startswith(WIDGET_PREFIX)]
    st.session_state[TOKEN_KEY] = st.session_state.get(TOKEN_KEY, 0) + 1
    # The old keys are unreachable now that the token has moved on; dropping them keeps
    # session state from growing by a full form's worth of widgets on every edit.
    for key in stale:
        st.session_state.pop(key, None)


def _blank_option():
    return {'location': '', 'start_time': '', 'end_time': '', 'capacity': None}


def _blank_date():
    return {'class_date': None, 'has_live': False, 'can_work_n_prior': False,
            'options': [_blank_option()]}


def _blank_draft():
    return {
        'class_name': '',
        'settings': {
            'calendar_display': '',
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
        'assignment_source': {'groupings': [], 'roles': []},
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
    # A class saved before roles were selectable carries no 'roles' key. Merged onto
    # the blank shape rather than used as-is, so the picker gets a list either way.
    # Grouping ids come back from JSON as whatever was stored; the picker matches them
    # against the live grouping list, so anything stale simply drops out.
    stored_source = record.get('assignment_source') or {}
    draft['assignment_source'] = {**draft['assignment_source'],
                                  **{key: value for key, value in stored_source.items()
                                     if value is not None}}

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
    draft['settings']['calendar_display'] = settings.get('calendar_display') or ''

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

    # A different class than the form last held. Its fields still carry the previous
    # one's values until their widget state goes.
    reset_widget_state()

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
    """Forget the working copy and the fields showing it, after saving or cancelling."""
    st.session_state.pop(DRAFT_KEY, None)
    st.session_state.pop(DRAFT_FOR_KEY, None)
    reset_widget_state()


# ---------------------------------------------------------------------------
# Staff selection
# ---------------------------------------------------------------------------

def selectable_roles():
    """The roles a class can be picked by, as the staff database spells them.

    Read off the database's own list rather than written out here, so a role added
    there appears in the picker rather than being quietly unselectable. UNASSIGNED is
    included on purpose: those are people on the roster whose role nobody has resolved
    yet, and leaving them out of the picker is how they end up in no class at all.
    """
    if staffdb is None:
        return []
    return list(staffdb.STAFF_ROLES) + [staffdb.UNASSIGNED_ROLE]


def role_label(role):
    """A role as a person would write it.

    Title case suits the roles that are words and mangles the ones that are acronyms:
    CCEMT is not Ccemt. The database spells them all in caps, which is right for a
    stored value and shouty in a picker, so the acronyms are named here and everything
    else is title-cased.
    """
    text = str(role or '').strip()
    if staffdb is not None and text.upper() == staffdb.UNASSIGNED_ROLE:
        return "Unassigned role"
    if text.upper() in ('CCEMT', 'ATP', 'AMT'):
        return text.upper()
    return text.title()


def _members_matching(grouping_ids, roles):
    """
    Who the chosen groupings and roles come to.

    Groupings union: picking "Group 2" and "4 OR" means everyone in either — a class
    taught to a cohort plus everyone who owes four OR days, not only the people in
    both.

    Roles narrow that rather than widening it: "Group 2" and "NURSE" together means
    the nurses in group 2. Narrowing is the useful reading — a class taught to one
    grouping's nurses is a real thing to schedule, where "everyone in group 2, plus
    every nurse in the department" is not. A role on its own selects everyone who
    holds it, which is how a class for all medics gets built.

    Inactive staff are left out. Somebody who has left should not be pulled into a
    class by a grouping they are still recorded against.
    """
    if staffdb is None or staff_groupings is None:
        return []

    try:
        names = staff_groupings.get_members_of_many(grouping_ids)
    except Exception as e:
        print(f"Error reading grouping members: {e}")
        names = []

    if roles:
        try:
            with_role = set(staffdb.get_staff_names(roles=list(roles)))
        except Exception as e:
            print(f"Error reading staff by role: {e}")
            with_role = set()
        # No grouping picked means the roles stand alone and select everyone holding one.
        names = list(with_role) if not grouping_ids else [
            name for name in names if name in with_role]

    try:
        active = set(staffdb.get_staff_names())
    except Exception as e:
        print(f"Error reading the active roster: {e}")
        active = None
    if active is not None:
        names = [name for name in names if name in active]

    return sorted(dict.fromkeys(names))


def _render_staff_assignment(draft):
    """Who the class is for."""
    st.markdown("#### Assigned staff")
    st.caption(
        "Assigned staff are the people who see this class on their registration "
        "screen. Pick groupings or roles to fill the list quickly, then add or remove "
        "individuals — the list below is what gets saved, so a later change to a "
        "grouping's membership or somebody's role leaves this class alone.")

    if staffdb is None:
        st.error("The staff database is unavailable, so staff cannot be assigned.")
        return

    source = draft.get('assignment_source') or {}

    try:
        available = staff_groupings.get_groupings(with_counts=True)
    except Exception as e:
        print(f"Error reading the groupings: {e}")
        available = []
    grouping_names = {g['id']: g['name'] for g in available}
    grouping_counts = {g['id']: g.get('member_count', 0) for g in available}

    if not available:
        st.info(
            "No staff groupings have been set up yet. Create them on the Staff "
            "Database admin page (**Groupings** tab) to assign a class to a cohort "
            "in one click — or pick staff individually below.")

    picker_columns = st.columns(2)
    with picker_columns[0]:
        # Archived groupings are deliberately absent from the options. A class that
        # was built from one keeps its assigned staff either way, since the list below
        # is what gets saved.
        stored_ids = []
        for value in source.get('groupings', []):
            try:
                stored_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        groupings = st.multiselect(
            "Groupings", options=list(grouping_names),
            default=[g for g in stored_ids if g in grouping_names],
            format_func=lambda g: f"{grouping_names[g]} ({grouping_counts.get(g, 0)})",
            key=wkey("groupings"),
            help="A named list of staff, maintained on the Staff Database admin page. "
                 "Picking more than one means everyone in any of them.")
    with picker_columns[1]:
        role_options = selectable_roles()
        roles = st.multiselect(
            "Roles", options=role_options,
            default=[r for r in source.get('roles', []) if r in role_options],
            format_func=role_label,
            key=wkey("roles"),
            help="A role on its own picks everyone who holds it. Combined with a "
                 "grouping it narrows to that grouping's holders of the role — "
                 "'Group 2' and 'Nurse' together means group 2's nurses.")

    draft['assignment_source'] = {'groupings': groupings, 'roles': roles}

    matched = _members_matching(groupings, roles)
    if groupings or roles:
        # Say who that actually is, not just how many. The rule that roles narrow
        # rather than widen is only obvious once you can see the answer it gives.
        criteria = " or ".join(grouping_names[g] for g in groupings
                               if g in grouping_names)
        if roles:
            role_text = " or ".join(role_label(r) for r in sorted(roles))
            criteria = f"{criteria}, limited to {role_text}" if criteria else role_text

        st.caption(f"**{len(matched)}** active staff match {criteria}.")
        if matched:
            with st.expander(f"Show the {len(matched)}"):
                st.write(", ".join(matched))
        else:
            st.caption("Nothing to add — check the combination, since roles narrow "
                       "a grouping rather than adding to it.")

        fill_columns = st.columns(2)
        with fill_columns[0]:
            if st.button("➕ Add all of them", use_container_width=True,
                         disabled=not matched, key=wkey("add_groups")):
                draft['assigned_staff'] = sorted(
                    dict.fromkeys(list(draft['assigned_staff']) + matched))
                reset_widget_state()
                st.rerun()
        with fill_columns[1]:
            if st.button("➖ Remove all of them", use_container_width=True,
                         disabled=not matched, key=wkey("remove_groups")):
                draft['assigned_staff'] = [name for name in draft['assigned_staff']
                                           if name not in set(matched)]
                reset_widget_state()
                st.rerun()

    everyone = staffdb.get_staff_names()
    # Somebody assigned to the class who has since been marked inactive still belongs
    # on the list — dropping them from the options would silently unassign them on the
    # next save.
    options = sorted(dict.fromkeys(list(everyone) + list(draft['assigned_staff'])))
    draft['assigned_staff'] = st.multiselect(
        f"Assigned staff ({len(draft['assigned_staff'])})",
        options=options,
        default=[name for name in draft['assigned_staff'] if name in options],
        key=wkey("assigned_staff"))


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
                    if st.button("Remove", key=wkey(f"remove_date_{index}"),
                                 use_container_width=True):
                        removing = index

            entry['class_date'] = st.date_input(
                "Date", value=entry['class_date'], key=wkey(f"date_{index}"),
                format="MM/DD/YYYY")

            flag_columns = st.columns(2)
            with flag_columns[0]:
                entry['can_work_n_prior'] = st.checkbox(
                    "Staff can work the night before", value=entry['can_work_n_prior'],
                    key=wkey(f"nprior_{index}"),
                    help="Leave unchecked and a night shift the evening before counts "
                         "as a conflict for this date.")
            with flag_columns[1]:
                if is_meeting:
                    entry['has_live'] = st.checkbox(
                        "LIVE option available", value=entry['has_live'],
                        key=wkey(f"live_{index}"),
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
                        key=wkey(f"loc_{index}_{option_index}"),
                        placeholder="KBED")
                with option_columns[1]:
                    option['start_time'] = st.text_input(
                        "Start", value=option['start_time'] or '',
                        key=wkey(f"start_{index}_{option_index}"),
                        placeholder=draft['settings'].get('time_1_start') or '08:00')
                with option_columns[2]:
                    option['end_time'] = st.text_input(
                        "End", value=option['end_time'] or '',
                        key=wkey(f"end_{index}_{option_index}"),
                        placeholder=draft['settings'].get('time_1_end') or '16:00')
                with option_columns[3]:
                    capacity = st.text_input(
                        "Seats", value=('' if option['capacity'] is None
                                        else str(option['capacity'])),
                        key=wkey(f"cap_{index}_{option_index}"),
                        placeholder=str(draft['settings'].get('students_per_class')
                                        or 21))
                    option['capacity'] = catalog.parse_int(capacity)
                with option_columns[4]:
                    st.write("")
                    if len(entry['options']) > 1:
                        if st.button("✕", key=wkey(f"rmloc_{index}_{option_index}"),
                                     help="Remove this location"):
                            option_removing = option_index

            if option_removing is not None:
                entry['options'].pop(option_removing)
                # The locations after it shift down an index, onto the widget keys
                # their neighbours were using.
                reset_widget_state()
                st.rerun()

            st.caption("Times and seats left blank fall back to the class settings "
                       "below, which is what a class taught at one site wants.")

            if st.button("➕ Add another location", key=wkey(f"addloc_{index}")):
                entry['options'].append(_blank_option())
                st.rerun()

    if removing is not None:
        draft['dates'].pop(removing)
        # Same shift as removing a location, over whole dates.
        reset_widget_state()
        st.rerun()

    if st.button("➕ Add another date", key=wkey("add_date"),
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
            key=wkey("students"),
            help="The seat count a date uses when its locations don't set their own.")
    with columns[1]:
        settings['classes_per_day'] = st.number_input(
            "Classes per day", min_value=1, max_value=4,
            value=int(settings.get('classes_per_day') or 1),
            key=wkey("per_day"),
            help="More than one runs the class several times a day, using the time "
                 "slots below.")
    with columns[2]:
        settings['instructors_per_day'] = st.number_input(
            "Instructors needed per day", min_value=0, max_value=20,
            value=int(settings.get('instructors_per_day') or 0),
            key=wkey("instructors"),
            help="Zero means the class takes no educator signups.")

    flag_columns = st.columns(3)
    with flag_columns[0]:
        settings['is_staff_meeting'] = st.checkbox(
            "Staff meeting", value=bool(settings.get('is_staff_meeting')),
            key=wkey("is_meeting"),
            help="Staff meetings are booked as LIVE or Virtual and count towards the "
                 "meeting requirement. This used to be inferred from 'SM' appearing "
                 "in the class name.")
        settings['nurses_medic_separate'] = st.checkbox(
            "Nurses and medics enrolled separately",
            value=bool(settings.get('nurses_medic_separate')),
            key=wkey("nm_separate"),
            help="Splits each session's seats between the two roles.")
    with flag_columns[1]:
        settings['has_ccemt'] = st.checkbox(
            "CCEMT role split", value=bool(settings.get('has_ccemt')),
            key=wkey("ccemt"),
            help="With nurse/medic separation on, gives each session one nurse, one "
                 "medic and one CCEMT seat.")
        settings['is_two_day_class'] = st.checkbox(
            "Two-day class", value=bool(settings.get('is_two_day_class')),
            key=wkey("two_day"),
            help="Each date covers that day and the next. Staff enroll once for both.")
    with flag_columns[2]:
        settings['is_count_exempt'] = st.checkbox(
            "Count-exempt", value=bool(settings.get('is_count_exempt')),
            key=wkey("count_exempt"),
            help="Lets a non-management medic take a second class in the same week.")
        settings['is_multi_session'] = st.checkbox(
            "Multi-session", value=bool(settings.get('is_multi_session')),
            key=wkey("multi_session"),
            help="Splits the day into back-to-back sessions of the length below, "
                 "between the Time 1 start and end.")

    if settings['is_multi_session']:
        settings['session_length'] = st.number_input(
            "Session length (minutes)", min_value=5, max_value=600,
            value=int(settings.get('session_length') or 60),
            key=wkey("session_length"))
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
                key=wkey(f"t{slot}s"), placeholder="08:00")
        with time_columns[1]:
            settings[f'time_{slot}_end'] = st.text_input(
                f"Time {slot} end", value=settings.get(f'time_{slot}_end') or '',
                key=wkey(f"t{slot}e"), placeholder="16:00")

    settings['notes'] = st.text_area(
        "Notes (admin only)", value=settings.get('notes') or '',
        key=wkey("notes"),
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
        "Class name", value=draft['class_name'], key=wkey("name"),
        help="What staff see, and what enrollments are recorded against. Renaming an "
             "existing class carries its enrollments and educator signups with it.")

    # The schedule report puts one cell per staff member per day, so a full class name
    # widens every date column to fit a label nobody reads across. This is the short
    # form printed there instead; the cell's comment still carries the full name, the
    # time and the location, so nothing is lost by shortening it.
    draft['settings']['calendar_display'] = st.text_input(
        "Calendar display", value=draft['settings'].get('calendar_display') or '',
        key=wkey("calendar_display"), max_chars=CALENDAR_DISPLAY_MAX,
        placeholder="e.g. SM (Virtual), SM (LIVE), Clinical",
        help="A short, generic label for this class on the Comprehensive Education "
             "Schedule Report — that report's day cells are narrow, so a full class "
             "name does not fit. The hover note on each cell keeps showing the full "
             "class name, time and location. Leave it blank to print the class name.")

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
                     use_container_width=True, key=wkey("save")):
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
        if st.button("Cancel", use_container_width=True, key=wkey("cancel")):
            clear_draft()
            if on_saved:
                on_saved()
            st.rerun()
