# modules/staff_admin_ui.py
"""
Staff Database admin interface.

Everything an admin needs to keep the roster current without touching a spreadsheet:
add a new hire, change attributes, mark someone inactive when they leave, rename them
when their name changes, and re-import from the Excel sources.

Rendered by app.py as its own full-width page (selected_module == "staff_database").
"""

import io
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

from . import staff_database as staffdb
from . import staff_groupings
from .security import check_admin_access
from .staff_import import (
    DEFAULT_PREFERENCES_PATH,
    DEFAULT_REQUIREMENTS_PATH,
    DEFAULT_ROSTER_PATH,
    format_import_report,
    import_staff_roster,
)

_eastern_tz = pytz.timezone('America/New_York')

_ROLE_HELP = ("Base role from the education roster. Dual providers are NURSE with the "
              "dual flag set — that combination is what the track system reads as the "
              "'dual' role.")

_SHIFTS_HELP = ("Required shifts per 14-day pay period. Leave blank for management and "
                "anyone else who doesn't bid a track — blank is what keeps them out of "
                "the bid order, and is different from 0.")

_EMAIL_HELP = ("Used to notify this staff member when their bid opens, and to send bid "
               "confirmations.")

_GROUPING_HELP = ("The named lists of staff this person belongs to. Training classes "
                  "are assigned by grouping, so this is what decides which classes "
                  "reach them. Someone can be in as many as makes sense, or none.")

# Bumped whenever a grouping or its membership is written, so the widgets on the
# Groupings tab re-read the database instead of returning the value the browser still
# holds from before the save. Same problem — and same fix — as the class editor's
# widget token.
_GROUPING_NONCE = 'staff_db_grouping_nonce'


def _grouping_key(name, *parts):
    """A session key for a Groupings-tab widget, under the current nonce."""
    suffix = '_'.join(str(part) for part in parts)
    nonce = st.session_state.get(_GROUPING_NONCE, 0)
    return f"staff_db_grouping_{name}_{suffix}_{nonce}" if suffix \
        else f"staff_db_grouping_{name}_{nonce}"


def _grouping_changed():
    """Re-key the Groupings tab's widgets after a write."""
    st.session_state[_GROUPING_NONCE] = st.session_state.get(_GROUPING_NONCE, 0) + 1


def _grouping_label(grouping):
    """How a grouping reads in a picker — archived ones say so."""
    return grouping['name'] if grouping['is_active'] \
        else f"{grouping['name']} (archived)"


def _grouping_options(include_archived=True, with_counts=False):
    """({id: grouping}, [ids in picker order]) for building a selectbox."""
    groupings = staff_groupings.get_groupings(include_archived=include_archived,
                                              with_counts=with_counts)
    return {g['id']: g for g in groupings}, [g['id'] for g in groupings]


def _optional_number_input(label, value, key, help_text=None, placeholder="blank"):
    """
    Text input for a number that may legitimately be blank.

    A blank requirement means something different from 0 (blank marks a staff member as
    non-bidding; 0 is a real requirement), and a number input cannot express "empty", so
    these are typed as text and parsed on save.
    """
    return st.text_input(
        label,
        value='' if value is None else str(value),
        key=key,
        help=help_text,
        placeholder=placeholder,
    )


def _parse_optional_number(text):
    """
    Parse an optional-number field.

    Returns:
        tuple: (value, ok) — value is an int or None; ok is False when the text was
        neither blank nor a number.
    """
    raw = (text or '').strip()
    if not raw:
        return None, True
    try:
        return int(float(raw)), True
    except ValueError:
        return None, False


def _require_admin():
    """
    Gate the page behind the admin password. Returns True when authenticated.
    """
    if st.session_state.get('admin_authenticated'):
        return True

    st.warning("🔒 Admin access required to manage the staff database.")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("staff_db_admin_login"):
            password = st.text_input("Admin password", type="password",
                                     key="staff_db_admin_password")
            submitted = st.form_submit_button("Unlock", use_container_width=True,
                                              type="primary")
        if submitted:
            if check_admin_access(password):
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


def _display_summary():
    """Roster counts and anything needing attention."""
    total = staffdb.staff_count()
    active = staffdb.staff_count(include_inactive=False)
    records = staffdb.get_all_staff(include_inactive=True)

    cols = st.columns(5)
    cols[0].metric("Staff on roster", total)
    cols[1].metric("Active", active)
    cols[2].metric("Inactive", total - active)
    cols[3].metric("Management", sum(1 for r in records if r['is_management'] and r['is_active']))
    cols[4].metric("Educators", sum(1 for r in records if r['is_educator_at'] and r['is_active']))

    role_counts = {}
    for record in records:
        if record['is_active']:
            role_counts[record['role']] = role_counts.get(record['role'], 0) + 1
    if role_counts:
        st.caption("Active by role: " + " · ".join(
            f"**{role}** {count}" for role, count in sorted(role_counts.items())))

    issues = staffdb.get_roster_issues()
    if issues['unassigned_role']:
        st.warning(
            f"⚠️ {len(issues['unassigned_role'])} staff member(s) have no role set: "
            f"{', '.join(issues['unassigned_role'])}. They were imported from the track "
            "files but are not on the Education Classes Roster — set a role on the Edit "
            "tab, or mark them inactive if they have left.")
    if issues['missing_seniority']:
        st.info(
            f"ℹ️ No seniority rank on file for: {', '.join(issues['missing_seniority'])}. "
            "Nurses and medics without a rank are skipped when the bid order is built.")
    if issues['duplicate_seniority']:
        detail = '; '.join(f"rank {rank}: {', '.join(names)}"
                           for rank, names in issues['duplicate_seniority'].items())
        st.error(f"❌ Duplicate seniority ranks — bid ordering will be ambiguous ({detail}).")
    if issues['missing_requirements']:
        st.warning(
            f"⚠️ No shifts per pay period on file for: "
            f"{', '.join(issues['missing_requirements'])}. Non-management clinical staff "
            "without it are treated as non-bidding and are left out of the bid order.")
    if issues['missing_email']:
        st.info(
            f"ℹ️ No email on file for: {', '.join(issues['missing_email'])}. "
            "They cannot be auto-notified when their bid opens.")
    if issues['missing_grouping']:
        st.info(
            f"ℹ️ In no grouping: {', '.join(issues['missing_grouping'])}. "
            "Training classes are assigned by grouping, so staff who work tracks "
            "without one get nothing assigned.")


def _roster_tab():
    """Filterable roster table plus CSV export."""
    st.markdown("#### Staff Roster")

    filter_cols = st.columns([2, 2, 1, 1])
    with filter_cols[0]:
        search = st.text_input("Search by name", key="staff_db_search",
                               placeholder="Start typing a name…")
    with filter_cols[1]:
        roles = st.multiselect("Role", options=staffdb.STAFF_ROLES + [staffdb.UNASSIGNED_ROLE],
                               key="staff_db_role_filter")
    with filter_cols[2]:
        show_inactive = st.checkbox("Include inactive", value=False,
                                    key="staff_db_show_inactive")
    with filter_cols[3]:
        management_only = st.checkbox("Management only", value=False,
                                      key="staff_db_mgmt_only")

    by_id, option_ids = _grouping_options()
    grouping_filter = st.multiselect(
        "Grouping", options=option_ids,
        format_func=lambda g: _grouping_label(by_id[g]),
        key="staff_db_grouping_filter",
        help="Show only staff in one of these groupings.")

    records = staffdb.get_all_staff(include_inactive=show_inactive,
                                    roles=roles or None,
                                    management_only=management_only)
    if search:
        needle = search.strip().lower()
        records = [r for r in records if needle in r['staff_name'].lower()]
    if grouping_filter:
        in_filter = {name.lower() for name in
                     staff_groupings.get_members_of_many(grouping_filter,
                                                         include_inactive=True)}
        records = [r for r in records if r['staff_name'].lower() in in_filter]

    if not records:
        st.info("No staff match these filters.")
        return

    memberships = staff_groupings.get_grouping_mapping(include_inactive=True)
    table = pd.DataFrame([{
        'Staff Name': r['staff_name'],
        'Role': r['role'],
        # The nurse/medic/dual value the track system reads. Only meaningful for
        # clinical staff, so it is left blank for everyone else.
        'Track Role': (r['clinical_role']
                       if r['role'] in staffdb.CLINICAL_ROLES else ''),
        'MGMT': r['is_management'],
        'Dual': r['is_dual'],
        'Educator AT': r['is_educator_at'],
        'No Matrix': r['no_matrix'],
        'Seniority': r['seniority'],
        'Shifts/Pay Period': r['shifts_per_pay_period'],
        'Night Min': r['night_minimum'],
        'Weekend Min': r['weekend_minimum'],
        'Weekend Group': r['weekend_group'] or '',
        'Groupings': ', '.join(memberships.get(r['staff_name'], [])),
        'Email': r['email'] or '',
        'Active': r['is_active'],
        'Notes': r['notes'] or '',
        'Last Modified': r['modified_date'],
    } for r in records])

    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"{len(table)} staff shown.")

    buffer = io.StringIO()
    table.to_csv(buffer, index=False)
    st.download_button(
        "📥 Download roster (CSV)",
        data=buffer.getvalue(),
        file_name=f"staff_roster_{datetime.now(_eastern_tz).strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


def _groupings_tab():
    """Create groupings, and decide who is in them."""
    st.markdown("#### Staff Groupings")
    st.caption(
        "A grouping is a named list of staff — an education cohort, the people who owe "
        "four OR days, a class of new hires. Training classes are assigned by "
        "grouping, so this is where you decide who a class reaches. A staff member can "
        "be in as many groupings as makes sense, and a grouping can be edited at any "
        "time: classes already built keep the staff list they were saved with.")

    staff_groupings.initialize_grouping_tables()
    groupings = staff_groupings.get_groupings(include_archived=True, with_counts=True)

    _grouping_create_form()

    if not groupings:
        st.info("No groupings yet. Create the first one above.")
        return

    st.markdown("---")
    _grouping_overview(groupings)

    st.markdown("---")
    _grouping_editor(groupings)


def _grouping_create_form():
    """Create a grouping, optionally seeded from a role."""
    with st.expander("➕ Create a grouping", expanded=False):
        with st.form("staff_db_grouping_create", clear_on_submit=True):
            name = st.text_input(
                "Grouping name *", placeholder="e.g. Group 1, 4 OR, New Hires 2027",
                help="What this grouping is called everywhere else in the app — the "
                     "class editor's picker, the roster table.")
            description = st.text_input(
                "Description", placeholder="Optional — what this grouping is for.")
            seed_roles = st.multiselect(
                "Start it with everyone in these roles", options=_selectable_roles(),
                help="Optional shortcut. You can add and remove individuals "
                     "afterwards; nothing is locked to the role.")
            created = st.form_submit_button("Create grouping", type="primary",
                                            use_container_width=True)

        if created:
            members = (staffdb.get_staff_names(roles=list(seed_roles))
                       if seed_roles else None)
            success, message, _ = staff_groupings.create_grouping(
                name, description=description, members=members, changed_by='admin')
            if success:
                _grouping_changed()
                st.success(f"✅ {message}")
                st.rerun()
            else:
                st.error(f"❌ {message}")


def _selectable_roles():
    """The roles a grouping can be seeded from — every role on the roster."""
    return staffdb.STAFF_ROLES + [staffdb.UNASSIGNED_ROLE]


def _grouping_overview(groupings):
    """Every grouping, its size and its state, plus who is in none of them."""
    st.markdown("##### All groupings")
    table = pd.DataFrame([{
        'Grouping': g['name'],
        'Members': g.get('member_count', 0),
        'Status': 'Active' if g['is_active'] else 'Archived',
        'Description': g['description'] or '',
        'Last Modified': g['modified_date'],
    } for g in groupings])
    st.dataframe(table, use_container_width=True, hide_index=True)

    active = [g for g in groupings if g['is_active']]
    st.caption(f"{len(active)} active grouping(s), "
               f"{len(groupings) - len(active)} archived.")

    # Staff in no grouping at all see no class that is assigned by grouping, which is
    # the failure this page exists to make visible.
    ungrouped = staff_groupings.get_ungrouped_staff()
    if ungrouped:
        with st.expander(f"⚠️ {len(ungrouped)} active staff are in no grouping"):
            st.write(", ".join(ungrouped))
            st.caption("Normal for management and the non-clinical roles. Anyone else "
                       "here gets no class assigned by grouping.")


def _grouping_editor(groupings):
    """Membership, then the grouping's own name and state."""
    st.markdown("##### Edit a grouping")

    by_id = {g['id']: g for g in groupings}
    chosen_id = st.selectbox(
        "Grouping", options=list(by_id),
        format_func=lambda g: (f"{_grouping_label(by_id[g])} — "
                               f"{by_id[g].get('member_count', 0)} member(s)"),
        key="staff_db_grouping_choice")
    grouping = by_id[chosen_id]

    if not grouping['is_active']:
        st.info("This grouping is archived. It keeps its membership and stays readable "
                "on the classes that used it, but it is not offered when a class is "
                "assigned. Restore it below to use it again.")

    _grouping_membership_editor(grouping)
    st.markdown("---")
    _grouping_settings_editor(grouping)


def _grouping_membership_editor(grouping):
    """Who is in one grouping."""
    st.markdown(f"**Members of {grouping['name']}**")

    current = staff_groupings.get_members(grouping['id'], include_inactive=True)
    # Inactive members stay in the options: dropping them would silently remove
    # somebody from the grouping the next time anybody pressed Save.
    options = sorted(dict.fromkeys(list(staffdb.get_staff_names()) + list(current)))

    role_columns = st.columns([3, 2])
    with role_columns[0]:
        roles = st.multiselect(
            "Add everyone in these roles", options=_selectable_roles(),
            key=_grouping_key('roles', grouping['id']),
            help="A shortcut for filling the list. The staff are copied in — nothing "
                 "stays tied to the role afterwards.")
    with role_columns[1]:
        st.write("")
        if st.button("➕ Add them", use_container_width=True, disabled=not roles,
                     key=_grouping_key('add_roles', grouping['id'])):
            success, message = staff_groupings.add_members(
                grouping['id'], staffdb.get_staff_names(roles=list(roles)),
                changed_by='admin')
            _grouping_changed()
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
            st.rerun()

    members = st.multiselect(
        f"Staff in this grouping ({len(current)})",
        options=options,
        default=current,
        key=_grouping_key('members', grouping['id']))

    save_columns = st.columns([2, 2, 3])
    with save_columns[0]:
        if st.button("💾 Save membership", type="primary", use_container_width=True,
                     key=_grouping_key('save_members', grouping['id'])):
            success, message = staff_groupings.set_members(
                grouping['id'], members, changed_by='admin')
            _grouping_changed()
            if success:
                st.success(f"✅ {message}")
                st.rerun()
            else:
                st.error(f"❌ {message}")
    with save_columns[1]:
        if st.button("🧹 Empty the grouping", use_container_width=True,
                     disabled=not current,
                     key=_grouping_key('clear_members', grouping['id'])):
            success, message = staff_groupings.set_members(grouping['id'], [],
                                                           changed_by='admin')
            _grouping_changed()
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
            st.rerun()
    with save_columns[2]:
        st.caption("Membership changes take effect for classes assigned from now on. "
                   "A class already saved keeps the staff list it was built with.")


def _grouping_settings_editor(grouping):
    """The grouping's name, description, order and archived state — and deleting it."""
    st.markdown(f"**Settings for {grouping['name']}**")

    with st.form(_grouping_key('settings', grouping['id'])):
        setting_columns = st.columns([3, 3, 1])
        with setting_columns[0]:
            name = st.text_input("Name", value=grouping['name'])
        with setting_columns[1]:
            description = st.text_input("Description",
                                        value=grouping['description'] or '')
        with setting_columns[2]:
            sort_order = st.number_input(
                "Order", value=int(grouping['sort_order']), step=10,
                help="Where this grouping sits in the pickers. Lower comes first.")
        saved = st.form_submit_button("💾 Save settings", use_container_width=True)

    if saved:
        success, message = staff_groupings.update_grouping(
            grouping['id'], name=name, description=description,
            sort_order=sort_order, changed_by='admin')
        _grouping_changed()
        if success:
            st.success(f"✅ {message}")
            st.rerun()
        else:
            st.error(f"❌ {message}")

    state_columns = st.columns(2)
    with state_columns[0]:
        if grouping['is_active']:
            if st.button(f"📦 Archive {grouping['name']}", use_container_width=True,
                         key=_grouping_key('archive', grouping['id'])):
                success, message = staff_groupings.update_grouping(
                    grouping['id'], is_active=False, changed_by='admin')
                _grouping_changed()
                if success:
                    st.success(f"✅ {message}")
                else:
                    st.error(f"❌ {message}")
                st.rerun()
            st.caption("Archiving keeps the membership and takes the grouping out of "
                       "the class editor's picker. This is the right way to retire a "
                       "cohort that has been superseded.")
        else:
            if st.button(f"♻️ Restore {grouping['name']}", use_container_width=True,
                         key=_grouping_key('restore', grouping['id'])):
                success, message = staff_groupings.update_grouping(
                    grouping['id'], is_active=True, changed_by='admin')
                _grouping_changed()
                if success:
                    st.success(f"✅ {message}")
                else:
                    st.error(f"❌ {message}")
                st.rerun()

    with state_columns[1]:
        confirm = st.checkbox(
            f"Yes, delete {grouping['name']} permanently",
            key=_grouping_key('confirm_delete', grouping['id']))
        if st.button(f"🗑️ Delete {grouping['name']}", use_container_width=True,
                     disabled=not confirm,
                     key=_grouping_key('delete', grouping['id'])):
            success, message = staff_groupings.delete_grouping(grouping['id'],
                                                               changed_by='admin')
            _grouping_changed()
            if success:
                st.success(f"✅ {message}")
                st.rerun()
            else:
                st.error(f"❌ {message}")
        st.caption("Deleting loses the record of who was in it. Archive instead unless "
                   "the grouping was a mistake.")


def _add_tab():
    """Add a staff member."""
    st.markdown("#### Add a Staff Member")
    st.caption("New hires go here. Everything except the name and role can be changed "
               "later.")

    with st.form("staff_db_add_form"):
        cols = st.columns(2)
        with cols[0]:
            name = st.text_input("Staff name *",
                                 help="Exactly as it should appear everywhere in the "
                                      "app — track displays, class rosters, bid lists.")
            role = st.selectbox("Role *", options=staffdb.STAFF_ROLES, help=_ROLE_HELP)
            seniority = st.number_input(
                "Seniority rank", min_value=0, max_value=9999, value=0, step=1,
                help="1 = most senior. Leave at 0 for staff who do not bid (ranks must "
                     "be unique).")
        with cols[1]:
            is_management = st.checkbox("Management (MGMT)")
            is_dual = st.checkbox("Dual provider (DUAL)")
            is_educator_at = st.checkbox("Educator AT (may sign up to teach)")
            no_matrix = st.checkbox("No Matrix")
            is_active = st.checkbox("Active", value=True)

        st.markdown("**Shift Requirements**")
        req_cols = st.columns(4)
        with req_cols[0]:
            shifts_text = _optional_number_input("Shifts per pay period", None,
                                                 "staff_db_add_shifts", _SHIFTS_HELP)
        with req_cols[1]:
            nights_text = _optional_number_input("Night minimum", None,
                                                 "staff_db_add_nights")
        with req_cols[2]:
            weekends_text = _optional_number_input("Weekend minimum", None,
                                                   "staff_db_add_weekends")
        with req_cols[3]:
            weekend_group = st.selectbox("Weekend group",
                                        options=[''] + staffdb.WEEKEND_GROUPS,
                                        key="staff_db_add_group")

        add_by_id, add_option_ids = _grouping_options(include_archived=False)
        add_groupings = st.multiselect(
            "Groupings", options=add_option_ids,
            format_func=lambda g: add_by_id[g]['name'],
            key="staff_db_add_groupings", help=_GROUPING_HELP)

        email = st.text_input("Email", key="staff_db_add_email", help=_EMAIL_HELP)
        notes = st.text_input("Notes", placeholder="Optional")

        submitted = st.form_submit_button("➕ Add staff member", type="primary",
                                          use_container_width=True)

    if submitted:
        shifts, shifts_ok = _parse_optional_number(shifts_text)
        nights, nights_ok = _parse_optional_number(nights_text)
        weekends, weekends_ok = _parse_optional_number(weekends_text)

        if not (shifts_ok and nights_ok and weekends_ok):
            st.error("❌ Shift requirements must be whole numbers, or left blank.")
            return

        success, message = staffdb.add_staff(
            staff_name=name,
            role=role,
            is_management=is_management,
            is_dual=is_dual,
            is_educator_at=is_educator_at,
            no_matrix=no_matrix,
            seniority=seniority if seniority else None,
            shifts_per_pay_period=shifts,
            night_minimum=nights,
            weekend_minimum=weekends,
            weekend_group=weekend_group or None,
            email=email or None,
            is_active=is_active,
            notes=notes or None,
            changed_by='admin',
        )
        if success and add_groupings:
            placed, grouping_message = staff_groupings.set_groupings_for_staff(
                name, add_groupings, changed_by='admin')
            message = f"{message} {grouping_message}" if placed \
                else f"{message} (groupings not saved: {grouping_message})"
        if success:
            st.success(f"✅ {message}")
        else:
            st.error(f"❌ {message}")


def _edit_tab():
    """Edit attributes, activate/deactivate, rename or delete one staff member."""
    st.markdown("#### Edit a Staff Member")

    # A rename or delete leaves the picker holding a name that no longer exists, so the
    # selection is cleared here — before the widget is created, which is the only point
    # Streamlit allows its key to be written.
    if st.session_state.pop('staff_db_clear_selection', False):
        st.session_state['staff_db_edit_select'] = ''

    # Outcome of a rename or delete that cleared the selection on the previous run.
    rename_result = st.session_state.pop('staff_db_rename_result', None)
    if rename_result:
        message, rows = rename_result
        st.success(f"✅ {message}")
        if rows:
            st.markdown("**Rows updated:**")
            for key, count in sorted(rows.items()):
                st.markdown(f"- `{key}`: {count}")

    delete_result = st.session_state.pop('staff_db_delete_result', None)
    if delete_result:
        st.success(f"✅ {delete_result}")

    names = staffdb.get_staff_names(include_inactive=True)
    if not names:
        st.info("The roster is empty — import it from the Excel sources first.")
        return

    selected = st.selectbox("Staff member", options=[''] + names,
                            format_func=lambda n: "-- Select a staff member --" if n == '' else n,
                            key="staff_db_edit_select")
    if not selected:
        return

    record = staffdb.get_staff(selected)
    if not record:
        st.error("That staff member is no longer on the roster.")
        return

    if not record['is_active']:
        st.warning(f"{record['staff_name']} is currently **inactive** and is hidden from "
                   "staff pickers throughout the app.")

    # ── Attributes ──
    role_options = list(staffdb.STAFF_ROLES)
    current_role = staffdb.canonical_role(record['role'])
    if current_role not in role_options:
        role_options.insert(0, current_role)

    with st.form("staff_db_edit_form"):
        cols = st.columns(2)
        with cols[0]:
            role = st.selectbox("Role", options=role_options,
                                index=role_options.index(current_role), help=_ROLE_HELP)
            seniority = st.number_input(
                "Seniority rank", min_value=0, max_value=9999,
                value=int(record['seniority']) if record['seniority'] else 0, step=1,
                help="1 = most senior. 0 clears the rank.")
        with cols[1]:
            is_management = st.checkbox("Management (MGMT)", value=record['is_management'])
            is_dual = st.checkbox("Dual provider (DUAL)", value=record['is_dual'])
            is_educator_at = st.checkbox("Educator AT (may sign up to teach)",
                                         value=record['is_educator_at'])
            no_matrix = st.checkbox("No Matrix", value=record['no_matrix'])

        st.markdown("**Shift Requirements**")
        req_cols = st.columns(4)
        with req_cols[0]:
            shifts_text = _optional_number_input(
                "Shifts per pay period", record['shifts_per_pay_period'],
                "staff_db_edit_shifts", _SHIFTS_HELP)
        with req_cols[1]:
            nights_text = _optional_number_input(
                "Night minimum", record['night_minimum'], "staff_db_edit_nights")
        with req_cols[2]:
            weekends_text = _optional_number_input(
                "Weekend minimum", record['weekend_minimum'], "staff_db_edit_weekends")
        with req_cols[3]:
            group_options = [''] + staffdb.WEEKEND_GROUPS
            current_group = record['weekend_group'] or ''
            if current_group not in group_options:
                group_options.append(current_group)
            weekend_group = st.selectbox(
                "Weekend group", options=group_options,
                index=group_options.index(current_group), key="staff_db_edit_group")

        # Only the groupings a picker can offer are editable here; an archived
        # grouping this staff member is still in is listed underneath instead, since
        # its absence from the picker is not a request to take them out of it.
        edit_by_id, edit_option_ids = _grouping_options(include_archived=False)
        held = [g['id'] for g in staff_groupings.get_groupings_for_staff(
            record['staff_name'])]
        edit_groupings = st.multiselect(
            "Groupings", options=edit_option_ids,
            default=[g for g in held if g in edit_by_id],
            format_func=lambda g: edit_by_id[g]['name'],
            key=f"staff_db_edit_groupings_{record['id']}", help=_GROUPING_HELP)
        archived_held = [g['name'] for g in staff_groupings.get_groupings_for_staff(
            record['staff_name']) if not g['is_active']]
        if archived_held:
            st.caption("Also in archived grouping(s): " + ", ".join(archived_held))

        email = st.text_input("Email", value=record['email'] or '',
                              key="staff_db_edit_email", help=_EMAIL_HELP)
        notes = st.text_input("Notes", value=record['notes'] or '')

        saved = st.form_submit_button("💾 Save changes", type="primary",
                                      use_container_width=True)

    if saved:
        shifts, shifts_ok = _parse_optional_number(shifts_text)
        nights, nights_ok = _parse_optional_number(nights_text)
        weekends, weekends_ok = _parse_optional_number(weekends_text)

        if not (shifts_ok and nights_ok and weekends_ok):
            st.error("❌ Shift requirements must be whole numbers, or left blank.")
            return

        success, message = staffdb.update_staff(
            record['staff_name'],
            role=role,
            is_management=is_management,
            is_dual=is_dual,
            is_educator_at=is_educator_at,
            no_matrix=no_matrix,
            seniority=seniority if seniority else None,
            shifts_per_pay_period=shifts,
            night_minimum=nights,
            weekend_minimum=weekends,
            weekend_group=weekend_group or None,
            email=email or None,
            notes=notes,
            changed_by='admin',
        )
        # Groupings are saved whether or not any other field changed — update_staff()
        # reports "no changes" for an edit that only moved somebody between groupings,
        # and that must not read as a failure.
        placed, grouping_message = staff_groupings.set_groupings_for_staff(
            record['staff_name'], edit_groupings, changed_by='admin')
        if success and placed:
            st.success(f"✅ {message} {grouping_message}")
            st.rerun()
        elif success:
            st.warning(f"⚠️ {message} The groupings were not saved: {grouping_message}")
        else:
            st.error(f"❌ {message}")

    st.markdown("---")

    # ── Active status ──
    st.markdown("##### Active Status")
    st.caption("Inactive staff keep all their history — tracks, bids, class enrollments "
               "— but disappear from every staff picker. This is the right way to handle "
               "someone leaving.")
    if record['is_active']:
        if st.button(f"🚫 Mark {record['staff_name']} inactive",
                     key="staff_db_deactivate", use_container_width=True):
            success, message = staffdb.set_staff_active(record['staff_name'], False,
                                                        changed_by='admin')
            st.success(message) if success else st.error(message)
            st.rerun()
    else:
        if st.button(f"✅ Mark {record['staff_name']} active",
                     key="staff_db_activate", use_container_width=True):
            success, message = staffdb.set_staff_active(record['staff_name'], True,
                                                        changed_by='admin')
            st.success(message) if success else st.error(message)
            st.rerun()

    st.markdown("---")

    # ── Rename ──
    st.markdown("##### Change Name")
    st.caption("For a married name or a correction. The staff name is the key every "
               "other record joins on, so the change is applied to the roster and to "
               "every related record in the same step.")

    references = staffdb.count_staff_references(record['staff_name'])
    if references:
        with st.expander(f"Records currently filed under '{record['staff_name']}' "
                         f"({sum(references.values())})"):
            for key, count in sorted(references.items()):
                st.markdown(f"- `{key}`: {count} row(s)")
    else:
        st.caption("No other records reference this name yet.")

    with st.form("staff_db_rename_form"):
        new_name = st.text_input("New name", placeholder=record['staff_name'])
        propagate = st.checkbox(
            "Update all related records too (recommended)", value=True,
            help="Leave this on. Turning it off renames only the roster entry and "
                 "leaves tracks, bids and enrollments filed under the old name.")
        confirm = st.checkbox(f"I want to rename '{record['staff_name']}'")
        renamed = st.form_submit_button("✏️ Apply name change", use_container_width=True)

    if renamed:
        if not confirm:
            st.error("❌ Tick the confirmation box to apply a name change.")
        else:
            success, message, rows = staffdb.rename_staff(
                record['staff_name'], new_name, changed_by='admin', propagate=propagate)
            if success:
                st.session_state['staff_db_rename_result'] = (message, rows)
                st.session_state['staff_db_clear_selection'] = True
                st.rerun()
            else:
                st.error(f"❌ {message}")

    st.markdown("---")

    # ── Delete ──
    st.markdown("##### Delete from Roster")
    st.caption("Deleting removes the roster entry outright. Prefer marking someone "
               "inactive — a delete is refused while other records still reference the "
               "name, because those records would be orphaned.")

    with st.expander("🗑️ Delete this staff member"):
        st.error(f"This removes **{record['staff_name']}** from the staff roster.")
        force = False
        if references:
            st.warning(f"{sum(references.values())} related record(s) exist. A normal "
                       "delete will be refused.")
            force = st.checkbox(
                "Delete anyway and leave those records in place (not recommended)",
                key="staff_db_force_delete")
        confirm_delete = st.checkbox(f"I understand and want to delete "
                                     f"{record['staff_name']}",
                                     key="staff_db_confirm_delete")
        if st.button("🗑️ Delete permanently", key="staff_db_delete",
                     use_container_width=True):
            if not confirm_delete:
                st.error("❌ Tick the confirmation box first.")
            else:
                success, message = staffdb.delete_staff(record['staff_name'],
                                                        changed_by='admin', force=force)
                if success:
                    st.session_state['staff_db_delete_result'] = message
                    st.session_state['staff_db_clear_selection'] = True
                    st.rerun()
                else:
                    st.error(f"❌ {message}")


def _import_tab():
    """Import or refresh the roster from the Excel sources."""
    st.markdown("#### Import from Excel")
    st.markdown(
        "The roster's baseline comes from the **Education Classes Roster** "
        "(`Class_Enrollment` sheet): staff names plus Role, MGMT, DUAL and Educator AT. "
        "**No Matrix** and **Seniority** come from **Preferences v6**, along with each "
        "staff member's saved base-shift preference scores. **Shifts per pay period, "
        "night and weekend minimums, weekend group and email** come from "
        "**Requirements**. "
        "Once imported, the app reads all of this from the database — these files are "
        "only re-read when you run an import here."
    )

    cols = st.columns(3)
    with cols[0]:
        roster_path = st.text_input("Education Classes Roster", value=DEFAULT_ROSTER_PATH,
                                    key="staff_db_import_roster")
    with cols[1]:
        preferences_path = st.text_input("Preferences v6", value=DEFAULT_PREFERENCES_PATH,
                                         key="staff_db_import_prefs")
    with cols[2]:
        requirements_path = st.text_input("Requirements", value=DEFAULT_REQUIREMENTS_PATH,
                                          key="staff_db_import_reqs")

    option_cols = st.columns(2)
    with option_cols[0]:
        include_secondary = st.checkbox(
            "Also add staff found only in Tracks / Requirements / Preassignments",
            value=True, key="staff_db_import_secondary",
            help="Catches staff the app already references who were never added to the "
                 "education roster. They are imported with no role for you to set.")
        update_existing = st.checkbox(
            "Update staff already on the roster", value=False,
            key="staff_db_import_update",
            help="Fields the roster has nothing for yet are always filled in. This "
                 "additionally lets the spreadsheets overwrite values that are already "
                 "set and disagree — off by default so your edits stand.")
    with option_cols[1]:
        seed_preferences = st.checkbox(
            "Seed base-shift preferences from Preferences v6", value=True,
            key="staff_db_import_seed_prefs")
        overwrite_preferences = st.checkbox(
            "Overwrite preferences staff have already saved in the app", value=False,
            key="staff_db_import_overwrite_prefs")

    action_cols = st.columns(2)
    run_preview = action_cols[0].button("🔍 Preview (no changes)", use_container_width=True)
    run_import = action_cols[1].button("📥 Run import", type="primary",
                                       use_container_width=True)

    if run_preview or run_import:
        with st.spinner("Reading the Excel sources…"):
            report = import_staff_roster(
                roster_path=roster_path,
                preferences_path=preferences_path,
                requirements_path=requirements_path,
                include_secondary_names=include_secondary,
                update_existing=update_existing,
                seed_shift_preferences=seed_preferences,
                overwrite_shift_preferences=overwrite_preferences,
                dry_run=run_preview,
                changed_by='admin',
            )

        if report['errors']:
            st.error("❌ The import reported errors — see the details below.")
        elif run_preview:
            st.info("🔍 Preview only — nothing was written.")
        else:
            st.success("✅ Import complete.")

        metric_cols = st.columns(4)
        metric_cols[0].metric("Added", len(report['added']))
        metric_cols[1].metric("Updated", len(report['updated']))
        metric_cols[2].metric("Unchanged", len(report['unchanged']))
        metric_cols[3].metric("Left alone", len(report['skipped']))

        with st.expander("Import details", expanded=bool(report['errors']
                                                          or report['conflicts']
                                                          or report['skipped'])):
            st.code("\n".join(format_import_report(report)), language=None)


def _history_tab():
    """Audit log and name-change history."""
    st.markdown("#### Change History")

    name_history = staffdb.get_name_history(limit=50)
    st.markdown("##### Name Changes")
    if name_history:
        st.dataframe(pd.DataFrame([{
            'When': entry['changed_date'],
            'From': entry['old_name'],
            'To': entry['new_name'],
            'Related rows updated': sum(entry['rows_updated'].values()),
            'By': entry['changed_by'],
        } for entry in name_history]), use_container_width=True, hide_index=True)
    else:
        st.caption("No name changes recorded.")

    st.markdown("##### All Roster Changes")
    log = staffdb.get_audit_log(limit=200)
    if log:
        st.dataframe(pd.DataFrame([{
            'When': entry['changed_date'],
            'Staff': entry['staff_name'],
            'Action': entry['action'],
            'Details': _format_changes(entry['changes']),
            'By': entry['changed_by'],
        } for entry in log]), use_container_width=True, hide_index=True)
    else:
        st.caption("No changes recorded yet.")


def _format_changes(changes):
    """Render an audit entry's JSON diff as a short readable string."""
    if not changes:
        return ''
    if isinstance(changes, dict) and 'before' in changes and 'after' in changes:
        return '; '.join(
            f"{field}: {changes['before'].get(field)} → {value}"
            for field, value in changes['after'].items())
    if isinstance(changes, dict):
        return '; '.join(f"{key}: {value}" for key, value in changes.items()
                         if key not in ('rows_updated', 'record'))
    return str(changes)


def display_staff_database_admin():
    """
    Render the Staff Database admin page.

    Admin-gated; safe to call from anywhere in the app.
    """
    st.markdown("")
    if st.button("← Back to CrewOps360", key="staff_db_back"):
        st.session_state.selected_module = None
        st.rerun()

    st.markdown("""
    <div style="text-align: center; padding: 1rem;">
        <h1 style="color: #00695C;">👥 Staff Database</h1>
        <p style="color: #666; font-size: 1.1rem;">
            The roster and staff attributes the whole system reads from
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    if not _require_admin():
        return

    staffdb.initialize_staff_tables()

    if staffdb.staff_count() == 0:
        st.info(
            "The staff database is empty. Use the **Import from Excel** tab below to "
            "build the roster from the Education Classes Roster and Preferences v6 — "
            "after that, the app reads staff attributes from the database and those "
            "spreadsheets are no longer consulted."
        )
    else:
        _display_summary()

    st.markdown("---")

    roster_tab, groupings_tab, add_tab, edit_tab, import_tab, history_tab = st.tabs(
        ["📋 Roster", "👪 Groupings", "➕ Add Staff", "✏️ Edit / Rename / Remove",
         "📥 Import from Excel", "🕓 History"])

    with roster_tab:
        _roster_tab()
    with groupings_tab:
        _groupings_tab()
    with add_tab:
        _add_tab()
    with edit_tab:
        _edit_tab()
    with import_tab:
        _import_tab()
    with history_tab:
        _history_tab()
