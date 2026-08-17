# modules/track_data_admin_ui.py
"""
Track Data admin — the editors for the two schedule datasets that used to be Excel tabs:

- **Preassignments**, per bid cycle: the days a staff member is already committed
  elsewhere before bidding opens. Authored per cycle, so a new cycle starts empty (or
  copied from the last one).
- **CCEMT schedules**: the 28-day repeating pattern the CCEMT group works instead of
  bidding a 42-day track.

Rendered by app.py as its own full-width page (selected_module == "track_data"). The
preassignment editor is also embedded in the Track Bidding admin, where a cycle is
created.
"""

import io
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

from . import ccemt_schedule as ccemt
from . import preassignment_db as preassign
from .day_pattern import PATTERN_DAYS, days_by_week
from .security import check_admin_access

_eastern_tz = pytz.timezone('America/New_York')


def _require_admin(form_key):
    """Gate a page behind the admin password. Returns True when authenticated."""
    if st.session_state.get('admin_authenticated'):
        return True

    st.warning("🔒 Admin access required.")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form(form_key):
            password = st.text_input("Admin password", type="password",
                                     key=f"{form_key}_password")
            submitted = st.form_submit_button("Unlock", use_container_width=True,
                                              type="primary")
        if submitted:
            if check_admin_access(password):
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


def _track_cycle_names():
    """Every configured track cycle, most relevant first."""
    from .db_utils import get_all_track_configs
    configs = get_all_track_configs() or []
    bidding = [c['track_name'] for c in configs if c['is_bidding_open']]
    active = [c['track_name'] for c in configs if c['is_active']
              and c['track_name'] not in bidding]
    others = [c['track_name'] for c in configs
              if c['track_name'] not in bidding + active]
    return bidding + active + others


def _cycle_selector(key, label="Track cycle"):
    """Pick a track cycle. Returns the selected name, or None when none exist."""
    names = _track_cycle_names()
    if not names:
        st.info("No track cycles exist yet. Create one in Track Bidding → "
                "Administration → Track Configs.")
        return None
    return st.selectbox(label, options=names, key=key)


# ──────────────────────────────────────────────
# Preassignments
# ──────────────────────────────────────────────

def display_preassignment_editor(track_name=None, key_prefix="preassign"):
    """
    Editor for one cycle's preassignments.

    Args:
        track_name (str, optional): edit this cycle without showing the picker — used
            when embedding in a page that has already chosen a cycle.
        key_prefix (str): widget key namespace, so the editor can appear on two pages.
    """
    preassign.initialize_preassignment_tables()

    cycle = track_name or _cycle_selector(f"{key_prefix}_cycle")
    if not cycle:
        return

    preassignments = preassign.get_preassignments(cycle)
    total_days = sum(len(days) for days in preassignments.values())

    cols = st.columns(3)
    cols[0].metric("Staff with preassignments", len(preassignments))
    cols[1].metric("Preassigned days", total_days)
    cols[2].metric("Cycle", cycle)

    st.caption("Preassignments count as day shifts, are locked in the track editors, and "
               "apply only to the cycle shown here.")

    tab_edit, tab_grid, tab_copy = st.tabs(
        ["✏️ Edit a Staff Member", "📋 All Preassignments", "📄 Copy / Import"])

    with tab_edit:
        _preassignment_staff_editor(cycle, key_prefix)

    with tab_grid:
        _preassignment_grid(cycle, preassignments, key_prefix)

    with tab_copy:
        _preassignment_copy_import(cycle, key_prefix)


def _staff_options():
    """Active clinical staff, for the preassignment picker."""
    try:
        from .staff_database import get_staff_names
        return get_staff_names(clinical_only=True)
    except Exception as e:
        st.error(f"Could not read the staff roster: {e}")
        return []


def _preassignment_staff_editor(cycle, key_prefix):
    """Set one staff member's preassigned days for a cycle."""
    staff_options = _staff_options()
    existing = preassign.get_preassignments(cycle)

    # Staff who already have preassignments but are no longer active clinical staff still
    # need to be editable, so they're kept in the list.
    for name in existing:
        if name not in staff_options:
            staff_options.append(name)
    staff_options.sort(key=str.lower)

    if not staff_options:
        st.info("No staff on the roster yet — import the staff database first.")
        return

    selected = st.selectbox(
        "Staff member", options=[''] + staff_options,
        format_func=lambda n: "-- Select a staff member --" if n == '' else n,
        key=f"{key_prefix}_staff")
    if not selected:
        return

    current = existing.get(selected, {})
    if current:
        st.caption(f"{selected} currently has {len(current)} preassigned day(s) on {cycle}.")
    else:
        st.caption(f"{selected} has no preassignments on {cycle}.")

    with st.form(f"{key_prefix}_staff_form"):
        st.markdown("Set an activity against each day. Clearing a day removes its "
                    "preassignment.")
        updated = {}
        for week_index, week in enumerate(days_by_week(), start=1):
            st.markdown(f"**Week {week_index}**")
            day_columns = st.columns(7)
            for column, day in zip(day_columns, week):
                with column:
                    updated[day] = st.text_input(
                        day.split()[0],  # weekday; the full label is in the tooltip
                        value=current.get(day, ''),
                        key=f"{key_prefix}_{selected}_{day}",
                        help=day,
                        placeholder="—",
                    )
        saved = st.form_submit_button(f"💾 Save {selected}'s preassignments",
                                     type="primary", use_container_width=True)

    if saved:
        success, message = preassign.set_staff_preassignments(cycle, selected, updated)
        if success:
            st.success(f"✅ {message}")
            st.rerun()
        else:
            st.error(f"❌ {message}")

    if current:
        if st.button(f"🗑️ Clear all of {selected}'s preassignments",
                     key=f"{key_prefix}_clear_{selected}", use_container_width=True):
            success, deleted = preassign.delete_preassignments(cycle, selected)
            if success:
                st.success(f"✅ Cleared {deleted} preassigned day(s) for {selected}.")
                st.rerun()
            else:
                st.error("❌ Could not clear those preassignments.")


def _preassignment_grid(cycle, preassignments, key_prefix):
    """Read-only grid of every preassignment in a cycle, plus a CSV export."""
    if not preassignments:
        st.info(f"No preassignments configured for {cycle}.")
        return

    rows = []
    for staff_name in sorted(preassignments, key=str.lower):
        row = {'Staff Name': staff_name}
        staff_days = preassignments[staff_name]
        for day in PATTERN_DAYS:
            row[day] = staff_days.get(day, '')
        row['Total'] = len(staff_days)
        rows.append(row)

    table = pd.DataFrame(rows)
    st.dataframe(table, use_container_width=True, hide_index=True)

    buffer = io.StringIO()
    table.to_csv(buffer, index=False)
    st.download_button(
        "📥 Download preassignments (CSV)",
        data=buffer.getvalue(),
        file_name=f"preassignments_{cycle}_"
                  f"{datetime.now(_eastern_tz).strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key=f"{key_prefix}_download",
    )

    with st.expander("🗑️ Clear every preassignment in this cycle"):
        st.error(f"This removes all {sum(len(d) for d in preassignments.values())} "
                 f"preassigned day(s) from {cycle}.")
        confirm = st.checkbox(f"I want to clear {cycle}'s preassignments",
                             key=f"{key_prefix}_confirm_clear_all")
        if st.button("Clear all", key=f"{key_prefix}_clear_all",
                     use_container_width=True):
            if not confirm:
                st.error("❌ Tick the confirmation box first.")
            else:
                success, deleted = preassign.delete_preassignments(cycle)
                if success:
                    st.success(f"✅ Cleared {deleted} preassigned day(s).")
                    st.rerun()
                else:
                    st.error("❌ Could not clear the preassignments.")


def _preassignment_copy_import(cycle, key_prefix):
    """Copy another cycle's preassignments in, or import a legacy spreadsheet once."""
    st.markdown("##### Copy from another cycle")
    st.caption("The usual way to start a new bid cycle: bring last cycle's standing "
               "commitments over, then edit the exceptions.")

    others = [name for name in _track_cycle_names() if name != cycle]
    if others:
        source = st.selectbox("Copy from", options=others, key=f"{key_prefix}_copy_from")
        overwrite = st.checkbox("Replace any preassignments already in this cycle",
                               key=f"{key_prefix}_copy_overwrite")
        if st.button(f"📄 Copy {source} → {cycle}", key=f"{key_prefix}_copy_btn",
                     use_container_width=True):
            success, message = preassign.copy_preassignments(source, cycle,
                                                             overwrite=overwrite)
            if success:
                st.success(f"✅ {message}")
                st.rerun()
            else:
                st.error(f"❌ {message}")
    else:
        st.info("No other track cycle to copy from.")

    st.markdown("---")
    st.markdown("##### Import a Preassignments spreadsheet")
    st.caption("One-time migration for a cycle that was authored in Excel. After this, "
               "preassignments are maintained here.")

    path = st.text_input("Spreadsheet path", value="upload files/Preassignments.xlsx",
                         key=f"{key_prefix}_import_path")
    import_overwrite = st.checkbox("Replace any preassignments already in this cycle",
                                  key=f"{key_prefix}_import_overwrite")

    action_cols = st.columns(2)
    preview = action_cols[0].button("🔍 Preview", key=f"{key_prefix}_import_preview",
                                   use_container_width=True)
    run = action_cols[1].button("📥 Import", key=f"{key_prefix}_import_run",
                                type="primary", use_container_width=True)

    if preview or run:
        report = preassign.import_preassignments_from_excel(
            path, cycle, overwrite=import_overwrite, dry_run=preview)

        if report['errors']:
            for error in report['errors']:
                st.error(f"❌ {error}")
        elif preview:
            st.info(f"🔍 Preview: {report['staff_imported']} staff member(s), "
                    f"{report['days_imported']} preassigned day(s) would be imported.")
        else:
            st.success(f"✅ Imported {report['days_imported']} preassigned day(s) for "
                       f"{report['staff_imported']} staff member(s).")

        if report['unknown_days']:
            st.warning("Columns that are not one of the 42 pattern days (imported as "
                       f"given): {', '.join(report['unknown_days'])}")
        if report['unknown_staff']:
            st.warning("Names not on the staff roster (imported as given): "
                       f"{', '.join(sorted(set(report['unknown_staff'])))}")
        if run and not report['errors']:
            st.rerun()


# ──────────────────────────────────────────────
# CCEMT schedules
# ──────────────────────────────────────────────

def _display_ccemt_editor():
    """Editor for the CCEMT group's 28-day repeating pattern."""
    ccemt.initialize_ccemt_tables()

    schedules = ccemt.get_schedules()
    start_date = ccemt.get_pattern_start_date()

    cols = st.columns(3)
    cols[0].metric("CCEMT staff scheduled", len(schedules))
    cols[1].metric("Scheduled days", sum(len(days) for days in schedules.values()))
    cols[2].metric("Pattern starts", start_date.strftime('%Y-%m-%d'))

    st.caption("CCEMT staff work a fixed 28-day pattern that repeats from the start date "
               "rather than bidding a 42-day track. Codes are free text — anything "
               "starting with N counts as a night shift, everything else as a day shift.")

    tab_edit, tab_grid, tab_settings = st.tabs(
        ["✏️ Edit a Staff Member", "📋 Full Pattern", "⚙️ Pattern Start / Import"])

    with tab_edit:
        _ccemt_staff_editor(schedules)

    with tab_grid:
        _ccemt_grid(schedules)

    with tab_settings:
        _ccemt_settings(start_date)


def _ccemt_staff_editor(schedules):
    """Set one CCEMT staff member's 28-day pattern."""
    options = sorted(schedules.keys(), key=str.lower)
    try:
        from .staff_database import get_staff_names
        roster = get_staff_names(roles=['CCEMT'])
    except Exception as e:
        st.error(f"Could not read the staff roster: {e}")
        roster = []
    for name in roster:
        if name not in options:
            options.append(name)
    options.sort(key=str.lower)

    if not options:
        st.info("No CCEMT staff on the roster yet.")
        return

    selected = st.selectbox(
        "CCEMT staff member", options=[''] + options,
        format_func=lambda n: "-- Select a staff member --" if n == '' else n,
        key="ccemt_staff")
    if not selected:
        return

    current = ccemt.get_staff_schedule(selected)
    labels = ccemt.day_labels()

    with st.form("ccemt_staff_form"):
        st.markdown("Enter the shift code worked on each day of the pattern. Leave a day "
                    "blank for a day off.")
        updated = {}
        for week in range(ccemt.PATTERN_WEEKS):
            st.markdown(f"**Week {week + 1}**")
            day_columns = st.columns(7)
            for offset, column in enumerate(day_columns):
                day_index = week * 7 + offset
                with column:
                    updated[day_index] = st.text_input(
                        labels[day_index].split(' ', 1)[1],
                        value=current.get(day_index, ''),
                        key=f"ccemt_{selected}_{day_index}",
                        help=labels[day_index],
                        placeholder="—",
                    )
        saved = st.form_submit_button(f"💾 Save {selected}'s pattern", type="primary",
                                     use_container_width=True)

    if saved:
        success, message = ccemt.set_staff_schedule(selected, updated)
        if success:
            st.success(f"✅ {message}")
            st.rerun()
        else:
            st.error(f"❌ {message}")

    if current:
        with st.expander(f"🗑️ Remove {selected} from the CCEMT schedule"):
            confirm = st.checkbox(f"I want to remove {selected}'s pattern",
                                  key="ccemt_confirm_delete")
            if st.button("Remove", key="ccemt_delete", use_container_width=True):
                if not confirm:
                    st.error("❌ Tick the confirmation box first.")
                else:
                    success, message = ccemt.delete_staff_schedule(selected)
                    if success:
                        st.success(f"✅ {message}")
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")


def _ccemt_grid(schedules):
    """Read-only view of every CCEMT pattern, plus a CSV export."""
    if not schedules:
        st.info("No CCEMT schedules on file. Import the CCEMT tab on the "
                "Pattern Start / Import tab, or add a staff member's pattern by hand.")
        return

    labels = ccemt.day_labels()
    rows = []
    for staff_name in sorted(schedules, key=str.lower):
        pattern = schedules[staff_name]
        row = {'Staff Name': staff_name}
        for day_index, label in enumerate(labels):
            row[label] = pattern.get(day_index, '')
        row['Days'] = len(pattern)
        row['Nights'] = sum(1 for code in pattern.values()
                            if ccemt.classify_shift_code(code) == 'N')
        rows.append(row)

    table = pd.DataFrame(rows)
    st.dataframe(table, use_container_width=True, hide_index=True)

    buffer = io.StringIO()
    table.to_csv(buffer, index=False)
    st.download_button(
        "📥 Download CCEMT schedules (CSV)",
        data=buffer.getvalue(),
        file_name=f"ccemt_schedules_"
                  f"{datetime.now(_eastern_tz).strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


def _ccemt_settings(start_date):
    """The pattern's start date, and the one-time import of the CCEMT tab."""
    st.markdown("##### Pattern start date")
    st.caption("The date the pattern's first column falls on. It anchors every CCEMT "
               "staff member's schedule to the calendar, so it must be a Sunday — moving "
               "it shifts everyone's schedule.")

    with st.form("ccemt_start_form"):
        new_start = st.date_input("First Sunday of the pattern", value=start_date.date(),
                                  key="ccemt_start_date")
        saved = st.form_submit_button("💾 Save start date", use_container_width=True)
    if saved:
        success, message = ccemt.set_pattern_start_date(new_start)
        if success:
            st.success(f"✅ {message}")
            st.rerun()
        else:
            st.error(f"❌ {message}")

    st.markdown("---")
    st.markdown("##### Import the CCEMT tab")
    st.caption("One-time migration from the CCEMT tab of a Tracks workbook. After this, "
               "the pattern is maintained here.")

    path = st.text_input("Tracks workbook path", value="upload files/Tracks.xlsx",
                         key="ccemt_import_path")
    sheet = st.text_input("Tab name", value="CCEMT", key="ccemt_import_sheet")
    overwrite = st.checkbox("Replace the CCEMT schedules already on file",
                            key="ccemt_import_overwrite")

    action_cols = st.columns(2)
    preview = action_cols[0].button("🔍 Preview", key="ccemt_import_preview",
                                    use_container_width=True)
    run = action_cols[1].button("📥 Import", key="ccemt_import_run", type="primary",
                                use_container_width=True)

    if preview or run:
        report = ccemt.import_from_excel(path, sheet, overwrite=overwrite,
                                         dry_run=preview)
        if report['errors']:
            for error in report['errors']:
                st.error(f"❌ {error}")
        elif preview:
            st.info(f"🔍 Preview: {report['staff_imported']} staff member(s), "
                    f"{report['days_imported']} scheduled day(s) would be imported.")
        else:
            st.success(f"✅ Imported {report['days_imported']} scheduled day(s) for "
                       f"{report['staff_imported']} staff member(s).")

        if report['skipped']:
            st.warning("Rows with no shift codes at all, skipped: "
                       f"{', '.join(report['skipped'])}")
        if run and not report['errors']:
            st.rerun()


# ──────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────

def display_track_data_admin():
    """
    Render the Track Data admin page: preassignments and CCEMT schedules.

    Admin-gated; safe to call from anywhere in the app.
    """
    st.markdown("")
    if st.button("← Back to CrewOps360", key="track_data_back"):
        st.session_state.selected_module = None
        st.rerun()

    st.markdown("""
    <div style="text-align: center; padding: 1rem;">
        <h1 style="color: #4527A0;">📌 Track Data</h1>
        <p style="color: #666; font-size: 1.1rem;">
            Preassignments and CCEMT schedules, per cycle
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    if not _require_admin("track_data_admin_login"):
        return

    preassignment_tab, ccemt_tab = st.tabs(["📌 Preassignments", "🚑 CCEMT Schedules"])

    with preassignment_tab:
        display_preassignment_editor(key_prefix="track_data_preassign")

    with ccemt_tab:
        _display_ccemt_editor()
