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
from .educational_groupings import format_seed_report, seed_groupings
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

_EDUCATION_GROUP_HELP = ("Education cohort 1-4. Classes are scheduled against these "
                         "groupings. Leave blank for staff who are not placed.")

_OR_GROUP_HELP = ("How many OR classes this staff member has to sign up for over the "
                  "year. \"No OR\" means none are required — the class will not appear "
                  "for them at all. That is a real placement, and is different from "
                  "blank, which means they have not been placed yet.")

# The OR grouping is an int where 0 is meaningful, so it is carried through the widgets
# as the sheet's own labels — '' for unplaced, 'No OR' for 0 — and parsed back on save.
# Keeping every cell a string also keeps the roster table Arrow-serializable, which a
# column mixing '' with ints is not.
_OR_GROUP_UNPLACED = ''
_OR_GROUP_NO_OR = 'No OR'


def _or_group_options():
    return [_OR_GROUP_UNPLACED] + [_OR_GROUP_NO_OR if g == 0 else str(g)
                                   for g in staffdb.OR_GROUPS]


def _or_group_label(value):
    """Selectbox label for a stored OR grouping (None -> unplaced)."""
    if value is None:
        return _OR_GROUP_UNPLACED
    return _OR_GROUP_NO_OR if int(value) == 0 else str(int(value))


def _parse_or_group(label):
    """Selectbox label back to a stored OR grouping, or None when unplaced."""
    if not label:
        return None
    return 0 if label == _OR_GROUP_NO_OR else int(label)


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
    unplaced = sorted(set(issues['missing_education_group'])
                      | set(issues['missing_or_group']))
    if unplaced:
        st.info(
            f"ℹ️ No educational grouping on file for: {', '.join(unplaced)}. "
            "Classes are scheduled against the education and OR groupings, so staff "
            "who work tracks without one get nothing assigned.")


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

    group_cols = st.columns([2, 2])
    with group_cols[0]:
        education_groups = st.multiselect(
            "Educational group", options=staffdb.EDUCATION_GROUPS,
            key="staff_db_education_group_filter",
            help="Who attends education with which cohort.")
    with group_cols[1]:
        or_groups = st.multiselect(
            "OR grouping", options=_or_group_options()[1:],
            key="staff_db_or_group_filter",
            help="How many OR classes each staff member has to sign up for.")

    records = staffdb.get_all_staff(include_inactive=show_inactive,
                                    roles=roles or None,
                                    management_only=management_only)
    if search:
        needle = search.strip().lower()
        records = [r for r in records if needle in r['staff_name'].lower()]
    if education_groups:
        records = [r for r in records if r['education_group'] in education_groups]
    if or_groups:
        wanted = {_parse_or_group(label) for label in or_groups}
        records = [r for r in records if r['or_group'] in wanted]

    if not records:
        st.info("No staff match these filters.")
        return

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
        'Education Group': r['education_group'] or '',
        # Blank means unplaced; 0 is the "No OR" placement, so it must still print.
        'OR Group': _or_group_label(r['or_group']),
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

        st.markdown("**Educational Groupings**")
        edu_cols = st.columns(2)
        with edu_cols[0]:
            education_group = st.selectbox(
                "Educational group", options=[''] + staffdb.EDUCATION_GROUPS,
                key="staff_db_add_education_group", help=_EDUCATION_GROUP_HELP)
        with edu_cols[1]:
            or_group_label = st.selectbox(
                "OR grouping", options=_or_group_options(),
                key="staff_db_add_or_group", help=_OR_GROUP_HELP)

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
            education_group=education_group or None,
            or_group=_parse_or_group(or_group_label),
            email=email or None,
            is_active=is_active,
            notes=notes or None,
            changed_by='admin',
        )
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

        st.markdown("**Educational Groupings**")
        edu_cols = st.columns(2)
        with edu_cols[0]:
            education_options = [''] + staffdb.EDUCATION_GROUPS
            current_education = record['education_group'] or ''
            if current_education not in education_options:
                education_options.append(current_education)
            education_group = st.selectbox(
                "Educational group", options=education_options,
                index=education_options.index(current_education),
                key="staff_db_edit_education_group", help=_EDUCATION_GROUP_HELP)
        with edu_cols[1]:
            or_options = _or_group_options()
            current_or = _or_group_label(record['or_group'])
            if current_or not in or_options:
                or_options.append(current_or)
            or_group_label = st.selectbox(
                "OR grouping", options=or_options,
                index=or_options.index(current_or),
                key="staff_db_edit_or_group", help=_OR_GROUP_HELP)

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
            education_group=education_group or None,
            or_group=_parse_or_group(or_group_label),
            email=email or None,
            notes=notes,
            changed_by='admin',
        )
        if success:
            st.success(f"✅ {message}")
            st.rerun()
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

    st.markdown("---")
    _groupings_seed_section()


def _groupings_seed_section():
    """Seed the educational groupings onto the roster from the placement sheets."""
    st.markdown("#### Seed Educational Groupings")
    st.markdown(
        "The **education cohort** (1-4) and the **OR grouping** (No OR, 2, 3, 4) come "
        "from two placement sheets that are flat columns of names — there is no staff "
        "key to import on, so they are transcribed in "
        "`modules/educational_groupings.py`. This places everyone the sheets name in "
        "one pass, so the groupings do not have to be entered by hand. Afterwards they "
        "are maintained per staff member on the **Edit** tab."
    )

    overwrite = st.checkbox(
        "Let the sheets overwrite placements already on file", value=False,
        key="staff_db_groupings_overwrite",
        help="Off by default, so a re-seed never undoes an edit made on the Edit tab. "
             "Placements that disagree are reported either way.")

    action_cols = st.columns(2)
    preview = action_cols[0].button("🔍 Preview groupings (no changes)",
                                    use_container_width=True,
                                    key="staff_db_groupings_preview")
    apply_seed = action_cols[1].button("🎓 Seed groupings", type="primary",
                                       use_container_width=True,
                                       key="staff_db_groupings_apply")

    if not (preview or apply_seed):
        return

    with st.spinner("Placing staff into their groupings…"):
        report = seed_groupings(overwrite=overwrite, dry_run=preview,
                                changed_by='admin')

    if report['errors']:
        st.error("❌ The seed reported errors — see the details below.")
    elif preview:
        st.info("🔍 Preview only — nothing was written.")
    else:
        st.success("✅ Groupings seeded.")

    metric_cols = st.columns(4)
    metric_cols[0].metric("Placements " + ("to set" if preview else "set"),
                          len(report['changes']))
    metric_cols[1].metric("Already correct", report['unchanged'])
    metric_cols[2].metric("Left alone", len(report['conflicts']))
    # Names on a sheet with no roster row, and staff who work tracks but appear on
    # neither sheet — the two that need a person to decide something.
    metric_cols[3].metric("Need attention",
                          len(report['unmatched']) + len(report['working_unplaced']))

    # Anything a person has to act on opens the details by default; a clean run does not.
    needs_attention = bool(report['errors'] or report['unmatched']
                           or report['duplicated'] or report['conflicts']
                           or report['working_unplaced'])
    with st.expander("Seed details", expanded=needs_attention):
        st.code("\n".join(format_seed_report(report)), language=None)


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

    roster_tab, add_tab, edit_tab, import_tab, history_tab = st.tabs(
        ["📋 Roster", "➕ Add Staff", "✏️ Edit / Rename / Remove", "📥 Import from Excel",
         "🕓 History"])

    with roster_tab:
        _roster_tab()
    with add_tab:
        _add_tab()
    with edit_tab:
        _edit_tab()
    with import_tab:
        _import_tab()
    with history_tab:
        _history_tab()
