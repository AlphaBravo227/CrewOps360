# modules/admin_console.py
"""
The CrewOps360 Admin Console — one door into every administrative area.

Administration used to be scattered: a password box in the Clinical Track Hub
sidebar, another in Track Bidding, a third in Summer Leave, and a separate PIN
for Training & Events. Signing in was two credentials and finding a tool meant
knowing which module's sidebar it hid in.

This is the replacement. One sign-in (modules.security), one full-width page,
and a card per area. Areas that already have a full-page dashboard of their own
— Training & Events, Summer Leave — are opened rather than re-implemented here;
the rest render inline.
"""

import glob
import os
import shutil
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st

from .security import (
    admin_is_authenticated,
    admin_session_minutes_remaining,
    logout_admin,
    require_admin,
)

_eastern_tz = pytz.timezone('America/New_York')

_DB_PATH = 'data/medflight_tracks.db'
_BACKUP_DIRS = ('backups', 'data')

# Where the console lives, and which card is open inside it.
_MODULE_KEY = 'admin'
_SECTION_KEY = 'admin_console_section'


# ──────────────────────────────────────────────
# Sections
# ──────────────────────────────────────────────
#
# A section is (key, label, description, colour, handoff). A handoff section owns
# a full-page dashboard elsewhere in the app; opening its card navigates there
# instead of rendering inside the console. The colours are the ones each area
# already used for its own page header, so a section still looks like itself.

ADMIN_SECTIONS = [
    ("staff_database", "👥 Staff Database",
     "The roster and staff attributes the whole system reads from",
     "#00695C", False),
    ("track_data", "📌 Track Data",
     "Preassignments and CCEMT schedules, per cycle",
     "#4527A0", False),
    ("track_bidding", "🗳️ Track Bidding",
     "Track configs, bid access, analysis, rosters and needs swaps",
     "#E65100", False),
    ("training", "📚 Training & Events",
     "Enrollment, classes, educators, training years and reporting",
     "#9C27B0", True),
    ("summer_leave", "☀️ Summer Leave",
     "Week allocations, staff selections and the LT schedule report",
     "#FF9800", True),
    ("approvals", "✅ Track Approvals",
     "Modifications to the active track waiting on a decision",
     "#2E7D32", False),
    ("exports", "📤 Exports & Reports",
     "Staff preferences, fiscal-year tracks and database extracts",
     "#1E88E5", False),
    ("system", "🗂️ System & Backups",
     "Roster and track health, database integrity, backups, restore and email",
     "#37474F", False),
]

_SECTION_BY_KEY = {section[0]: section for section in ADMIN_SECTIONS}


def open_console(section=None):
    """Send the app to the console, optionally straight into one section."""
    st.session_state.selected_module = _MODULE_KEY
    st.session_state[_SECTION_KEY] = section


def back_to_console_button(label="← Admin Console", key="back_to_admin_console"):
    """A way back for the dashboards the console hands off to.

    Only drawn for a signed-in admin: a staff member who reached the same page
    on their own has no console to go back to.
    """
    if not admin_is_authenticated():
        return False
    if st.button(label, key=key):
        open_console()
        st.rerun()
        return True
    return False


def render_admin_sidebar_entry(key_suffix=""):
    """The single sidebar door into administration, drawn on every module page.

    Replaces the password boxes that used to sit in four different sidebars.
    Nothing here reveals whether the console exists to someone who isn't an
    admin beyond the button itself — the gate is on the console page.
    """
    with st.sidebar:
        st.markdown("---")
        if admin_is_authenticated():
            st.success("🔓 Signed in as administrator")
            st.caption(f"⏱️ Session: {admin_session_minutes_remaining():.0f} min remaining")
            if st.button("🛠️ Admin Console", use_container_width=True, type="primary",
                         key=f"sidebar_admin_console{key_suffix}"):
                open_console()
                st.rerun()
            if st.button("🔒 Sign out of admin", use_container_width=True,
                         key=f"sidebar_admin_logout{key_suffix}"):
                logout_admin()
                st.rerun()
        else:
            if st.button("🔐 Admin Console", use_container_width=True,
                         key=f"sidebar_admin_login{key_suffix}"):
                open_console()
                st.rerun()


# ──────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────

def display_admin_console():
    """Render the Admin Console. Gated; safe to call from anywhere in the app."""
    st.markdown("")
    if st.button("← Back to CrewOps360", key="admin_console_exit"):
        st.session_state.selected_module = None
        st.session_state.pop(_SECTION_KEY, None)
        st.rerun()

    st.markdown("""
    <div style="text-align: center; padding: 1rem;">
        <h1 style="color: #37474F;">🛠️ Admin Console</h1>
        <p style="color: #666; font-size: 1.1rem;">
            Every administrative area, behind one sign-in
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    if not require_admin("admin_console_login",
                         "🔒 Administrator sign-in required."):
        return

    section_key = st.session_state.get(_SECTION_KEY)
    section = _SECTION_BY_KEY.get(section_key) if section_key else None

    _render_header(section)

    if section:
        _render_section(section)
    elif section_key:
        st.error("Unknown admin section.")
        st.session_state.pop(_SECTION_KEY, None)
    else:
        _render_home()


def _render_header(section=None):
    """Navigation, section title, session status and sign-out.

    The console owns all of this for every section it renders inline, so each
    area draws only its own controls and no page carries two sets of headers.
    """
    nav_cols = st.columns([2, 4, 2])

    with nav_cols[0]:
        if section and st.button("⬅️ Console home", key="admin_console_home",
                                 use_container_width=True):
            st.session_state.pop(_SECTION_KEY, None)
            st.rerun()
    with nav_cols[1]:
        st.caption(f"⏱️ Admin session: {admin_session_minutes_remaining():.0f} min remaining")
    with nav_cols[2]:
        if st.button("🔒 Sign out", key="admin_console_logout", use_container_width=True):
            logout_admin()
            st.rerun()

    if section:
        _, label, description, colour, _handoff = section
        st.markdown(f"""
        <div style="text-align: center; padding: 0.5rem;">
            <h2 style="color: {colour}; margin-bottom: 0.2rem;">{label}</h2>
            <p style="color: #666; font-size: 1.05rem;">{description}</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")


def _render_home():
    """The card grid — the console's front page."""
    st.markdown("### Administrative areas")
    st.caption("One sign-in covers all of these. The session ends when you sign "
               "out, when you log out of CrewOps360, or after an hour idle.")

    columns = st.columns(2)
    for index, (key, label, description, colour, handoff) in enumerate(ADMIN_SECTIONS):
        with columns[index % 2]:
            with st.container(border=True):
                st.markdown(
                    f"<span style='color: {colour}; font-weight: 700;'>{label}</span>",
                    unsafe_allow_html=True)
                st.caption(description)
                st.caption("Opens its own full-page dashboard."
                           if handoff else "&nbsp;", unsafe_allow_html=True)
                if st.button("Open", key=f"admin_console_open_{key}",
                             use_container_width=True):
                    _open_section(key)


def _open_section(key):
    """Enter a section: navigate away for a handoff, otherwise render in place."""
    if key == "training":
        st.session_state.selected_module = "training_events"
        st.session_state.training_admin_current_function = None
        st.session_state.training_admin_show_function = True
    elif key == "summer_leave":
        st.session_state.selected_module = "summer_leave"
        st.session_state.summer_leave_admin_mode = True
    else:
        st.session_state[_SECTION_KEY] = key
    st.rerun()


def _render_section(section):
    """Dispatch to the renderer for the open section."""
    key = section[0]
    if key == "staff_database":
        from .staff_admin_ui import display_staff_database_admin
        display_staff_database_admin()
    elif key == "track_data":
        from .track_data_admin_ui import display_track_data_admin
        display_track_data_admin()
    elif key == "track_bidding":
        from .track_bidding import display_bidding_admin_interface
        display_bidding_admin_interface()
    elif key == "approvals":
        _render_track_approvals()
    elif key == "exports":
        _render_exports()
    elif key == "system":
        _render_system()
    else:
        st.error("Unknown admin section.")


# ──────────────────────────────────────────────
# ✅ Track Approvals
# ──────────────────────────────────────────────

def _render_track_approvals():
    """The queue of track modifications waiting on an approve/reject."""
    from .db_utils import get_active_track_config, get_db_connection

    active_cfg = get_active_track_config()
    active_track = active_cfg['track_name'] if active_cfg else 'FY26'
    st.caption(f"Modifications submitted against the active track, **{active_track}**.")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT id, staff_name, submission_date, version
            FROM tracks WHERE track_name = ? AND is_active = 1 AND is_approved = 0
            ORDER BY submission_date DESC""", (active_track,))
        pending = cursor.fetchall()
    except Exception as e:
        st.error(f"Error loading pending approvals: {e}")
        return

    if not pending:
        st.success("✅ Nothing waiting — there are no pending modifications to review.")
        return

    st.markdown(f"**{len(pending)} pending modification(s):**")
    for track_id, staff_name, submitted, version in pending:
        with st.expander(f"{staff_name} (v{version}, submitted {submitted})"):
            approve_col, reject_col = st.columns(2)
            with approve_col:
                if st.button("Approve", key=f"admin_approve_{track_id}",
                             use_container_width=True, type="primary"):
                    now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        "UPDATE tracks SET is_approved = 1, approved_by = 'admin', "
                        "approval_date = ? WHERE id = ?", (now, track_id))
                    conn.commit()
                    st.success(f"Approved {staff_name}")
                    st.rerun()
            with reject_col:
                notes = st.text_input("Rejection notes", key=f"admin_reject_notes_{track_id}")
                if st.button("Reject", key=f"admin_reject_{track_id}",
                             use_container_width=True):
                    now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        "UPDATE tracks SET is_approved = -1, approved_by = 'admin', "
                        "approval_date = ? WHERE id = ?", (now, track_id))
                    cursor.execute("""INSERT INTO track_history
                        (track_id, staff_name, track_data, submission_date, status)
                        VALUES (?, ?, 'rejected', ?, ?)""",
                        (track_id, staff_name, now, f"rejected: {notes}"))
                    conn.commit()
                    st.warning(f"Rejected {staff_name}")
                    st.rerun()


# ──────────────────────────────────────────────
# 📤 Exports & Reports
# ──────────────────────────────────────────────

def _render_exports():
    """Every way data leaves the system, in one place."""
    prefs_tab, fy_tab, filtered_tab, db_tab = st.tabs([
        "📊 Staff Preferences", "📅 Fiscal Year Tracks", "🎯 Filtered Tracks",
        "🗄️ Database Extracts",
    ])

    with prefs_tab:
        from .admin_export import display_admin_export_section
        from .staff_database import build_preferences_df

        # Built here rather than read out of session state. It used to be
        # available only once the Clinical Track Hub had been opened in the same
        # session, which made an export come and go depending on where the admin
        # had been first; it comes from the roster, so build it from the roster.
        preferences_df = st.session_state.get('preferences_df')
        if preferences_df is None:
            try:
                preferences_df = build_preferences_df()
            except Exception as e:
                st.error(f"Could not build the preferences data: {str(e)}")
                preferences_df = None

        if preferences_df is None or preferences_df.empty:
            st.info("No active clinical staff on the roster yet, so there are no "
                    "preferences to export. Import the roster under **Staff "
                    "Database** first.")
        else:
            display_admin_export_section(preferences_df)

    with fy_tab:
        from .fiscal_year import add_fiscal_year_export_to_admin
        add_fiscal_year_export_to_admin(admin_authenticated=True)

    with filtered_tab:
        _render_filtered_track_export()

    with db_tab:
        _render_database_extracts()


def _render_filtered_track_export():
    """Active tracks narrowed by role and staff member, as a styled workbook.

    track_display has built this workbook for a long time; nothing had called it
    since the admin panel it belonged to stopped being wired up. It is a real
    export an administrator asks for, so it lives here now rather than nowhere.
    """
    from .track_display import (
        export_filtered_tracks_to_excel,
        get_all_active_tracks,
        get_available_staff_by_role,
    )

    success, all_tracks = get_all_active_tracks()
    if not success or not all_tracks:
        st.info("No active tracks in the database to export.")
        return

    role_col, staff_col = st.columns(2)
    with role_col:
        role = st.selectbox("Role", options=['All', 'nurse', 'medic'],
                            key="admin_console_filtered_role")
    with staff_col:
        staff = st.selectbox(
            "Staff member",
            options=['All Staff'] + get_available_staff_by_role(all_tracks, role),
            key="admin_console_filtered_staff")

    if not st.button("Build workbook", use_container_width=True,
                     key="admin_console_filtered_build"):
        return

    file_path, message = export_filtered_tracks_to_excel(role, staff)
    if not file_path:
        st.error(f"❌ {message}")
        return

    # Read the bytes straight into a download button and drop the temp file. The
    # old caller handed the browser a base64 data: URI in an <a> tag instead,
    # which is a page-sized string for a file Streamlit can serve directly.
    try:
        with open(file_path, 'rb') as handle:
            payload = handle.read()
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass

    st.success(f"✅ {message}")
    st.download_button(
        "📥 Download filtered tracks",
        data=payload,
        file_name=f"active_tracks_{datetime.now(_eastern_tz).strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def _render_database_extracts():
    """Excel exports of the track tables, and the raw SQLite file."""
    from .export_utils import export_track_history_to_excel, export_tracks_to_excel

    st.markdown("""
    - **Current Tracks** — every active track in the database (Excel)
    - **Track History** — the complete history of track changes (Excel)
    - **Raw Database** — the whole SQLite file, for a backup or offline analysis
    """)

    export_option = st.radio(
        "Export type",
        options=["Current Tracks", "Track History", "Raw Database", "Both Excel Files"],
        index=0,
        key="admin_console_export_option",
    )

    if not st.button("Generate Export", use_container_width=True,
                     key="admin_console_generate_export"):
        return

    timestamp = datetime.now(_eastern_tz).strftime("%Y%m%d_%H%M%S")

    try:
        if export_option == "Raw Database":
            if not os.path.exists(_DB_PATH):
                st.error("❌ Database file not found.")
                return
            with st.spinner("Preparing database download..."):
                with open(_DB_PATH, 'rb') as handle:
                    payload = handle.read()
            size_mb = len(payload) / (1024 * 1024)
            st.download_button(
                label="📥 Download Database File",
                data=payload,
                file_name=f"medflight_tracks_backup_{timestamp}.db",
                mime="application/octet-stream",
                use_container_width=True,
            )
            st.success(f"✅ Ready for download ({size_mb:.2f} MB)")
            return

        if export_option in ("Current Tracks", "Both Excel Files"):
            with st.spinner("Generating current tracks export..."):
                excel_data = export_tracks_to_excel()
            if excel_data:
                st.download_button(
                    label="📥 Download Current Tracks",
                    data=excel_data,
                    file_name=f"current_tracks_export_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                st.error("❌ Error generating current tracks export")

        if export_option in ("Track History", "Both Excel Files"):
            with st.spinner("Generating track history export..."):
                excel_data = export_track_history_to_excel()
            if excel_data:
                st.download_button(
                    label="📥 Download Track History",
                    data=excel_data,
                    file_name=f"track_history_export_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                st.error("❌ Error generating track history export")
    except Exception as e:
        st.error(f"Error during export: {str(e)}")


# ──────────────────────────────────────────────
# 🗂️ System & Backups
# ──────────────────────────────────────────────

def _render_system():
    """Health, maintenance and delivery settings."""
    health_tab, maintenance_tab, restore_tab, email_tab = st.tabs([
        "📊 Health", "🔧 Maintenance", "🔄 Restore", "📧 Email",
    ])

    with health_tab:
        _render_health()
    with maintenance_tab:
        _render_maintenance()
    with restore_tab:
        _render_restore()
    with email_tab:
        _render_email()


def _render_health():
    """What the rest of the app is reading, and anything that looks wrong."""
    from .db_utils import get_active_track_config, get_track_capacity
    from .preassignment_db import get_preassignments
    from .staff_database import get_staff_names, staff_count
    from .track_roster import active_track_count, get_active_track_rows

    st.markdown("#### Roster and track data")

    cols = st.columns(3)
    total = staff_count()
    active = staff_count(include_inactive=False)
    cols[0].metric("Staff on roster", f"{active} active", f"{total} total",
                   delta_color="off")
    cols[1].metric("Active tracks", active_track_count())
    cols[2].metric("Preassigned staff", len(get_preassignments()))

    if not total:
        st.error("❌ The staff database is empty — import the roster from "
                 "**Staff Database**.")
    st.caption("Role, management, dual, educator, no matrix and seniority all come "
               "from the staff database, not from a spreadsheet. All track data "
               "comes from the database too — there are no spreadsheet uploads "
               "left in these modules.")

    st.markdown("---")
    st.markdown("#### Active track and capacity")

    active_cfg = get_active_track_config()
    if active_cfg:
        st.success(f"**Active track: {active_cfg['track_name']}**")
        capacity = get_track_capacity(active_cfg['track_name'])
        # Without a span of its own a cohort is displayed and exported over FY26's
        # calendar, which is silently wrong for any year but FY26.
        if not (active_cfg.get('start_date') and active_cfg.get('end_date')):
            st.warning(
                f"⚠️ {active_cfg['track_name']} has no fiscal-year dates set, so "
                f"the fiscal-year display and the calendar export are falling back "
                f"to FY26's span. Set them in **Track Bidding → Track Configs**.")
    else:
        st.warning("No active track configured. Showing FY26 values.")
        capacity = get_track_capacity('FY26')

    st.markdown(
        f"**Operational:** {capacity.get('day_vehicles', 9)} day vehicles + "
        f"{capacity.get('day_leave_slots', 2)} leave · "
        f"{capacity.get('night_vehicles', 4)} night vehicles + "
        f"{capacity.get('night_leave_slots', 1)} leave")
    st.markdown(
        f"**Minimum staffing:** day **{capacity.get('min_day_staff', 7)}** · "
        f"night **{capacity.get('min_night_staff', 4)}**")
    st.markdown(
        f"**Maximums:** day nurses **{capacity['max_day_nurses']}** · "
        f"day medics **{capacity['max_day_medics']}** · "
        f"night nurses **{capacity['max_night_nurses']}** · "
        f"night medics **{capacity['max_night_medics']}**")

    st.markdown("---")
    st.markdown("#### Staff / track mismatches")

    # Staff holding an active track who are no longer active clinical staff on the
    # roster, and active clinical staff with no track. Both are worth knowing about:
    # the first is usually someone who left without their track being retired, the
    # second someone who hasn't submitted yet.
    try:
        track_staff = set(get_active_track_rows())
        db_staff = set(get_staff_names(clinical_only=True))

        without_roster = track_staff - db_staff
        without_track = db_staff - track_staff

        if not (without_roster or without_track):
            st.success("✅ Every active clinical staff member has a track, and every "
                       "active track belongs to one.")
        else:
            if without_roster:
                with st.expander(f"Have an active track but are not active clinical "
                                 f"staff ({len(without_roster)})"):
                    st.write(", ".join(sorted(without_roster)))
            if without_track:
                with st.expander(f"Active clinical staff with no track in the "
                                 f"database ({len(without_track)})"):
                    st.write(", ".join(sorted(without_track)))
    except Exception as e:
        st.error(f"Error checking staff/track mismatches: {str(e)}")


def _render_maintenance():
    """Integrity check, on-demand backup, and pruning old ones."""
    from .db_utils import verify_database_integrity

    cols = st.columns(3)

    with cols[0]:
        if st.button("🔄 Verify database integrity", use_container_width=True,
                     key="admin_console_verify_db"):
            try:
                if verify_database_integrity():
                    st.success("✅ Database integrity verified")
                else:
                    st.error("❌ Database integrity check failed")
            except Exception as e:
                st.error(f"❌ Error during integrity check: {str(e)}")

    with cols[1]:
        if st.button("📥 Back up database now", use_container_width=True,
                     key="admin_console_backup_db"):
            try:
                os.makedirs('backups', exist_ok=True)
                timestamp = datetime.now(_eastern_tz).strftime("%Y%m%d_%H%M%S")
                backup_file = f"backups/medflight_tracks_backup_{timestamp}.db"
                if os.path.exists(_DB_PATH):
                    shutil.copy2(_DB_PATH, backup_file)
                    st.success(f"✅ Backed up to `{backup_file}`")
                else:
                    st.error("❌ Database file not found")
            except Exception as e:
                st.error(f"❌ Backup failed: {str(e)}")

    with cols[2]:
        if st.button("🧹 Clean up old backups", use_container_width=True,
                     key="admin_console_cleanup_backups"):
            try:
                cutoff = (datetime.now() - timedelta(days=30)).timestamp()
                deleted = 0
                for path in glob.glob(os.path.join('backups', '*.db')):
                    if os.path.getctime(path) < cutoff:
                        try:
                            os.remove(path)
                            deleted += 1
                        except OSError:
                            continue
                st.success(f"✅ Removed {deleted} backup file(s) older than 30 days")
            except Exception as e:
                st.error(f"❌ Cleanup failed: {str(e)}")

    st.markdown("---")
    st.markdown("#### Backups on disk")

    backups = _list_backups()
    if not backups:
        st.info("No backup files found.")
        return

    st.dataframe(
        pd.DataFrame([{
            'File name': b['name'],
            'Directory': b['directory'],
            'Size (MB)': f"{b['size'] / (1024 * 1024):.2f}",
            'Modified': b['modified'].strftime("%Y-%m-%d %H:%M:%S"),
        } for b in backups]),
        use_container_width=True,
        hide_index=True,
    )


def _list_backups():
    """Every .db backup on disk, newest first."""
    backups = []
    for directory in _BACKUP_DIRS:
        if not os.path.exists(directory):
            continue
        for name in os.listdir(directory):
            if not name.endswith('.db'):
                continue
            path = os.path.join(directory, name)
            stat = os.stat(path)
            backups.append({
                'name': name,
                'path': path,
                'directory': directory,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime),
            })
    backups.sort(key=lambda b: b['modified'], reverse=True)
    return backups


def _render_restore():
    """Replace the live database — from a backup on disk or an uploaded file."""
    from .app_helper import restore_database_from_backup, restore_database_from_upload

    st.error("⚠️ **Danger zone.** Restoring replaces the live database. Take a "
             "backup first (Maintenance tab) so you can undo it.")

    from_disk_tab, from_upload_tab = st.tabs(["From a backup on disk", "From an upload"])

    with from_disk_tab:
        backups = _list_backups()
        if not backups:
            st.info("No backup files found in `backups/` or `data/`.")
        else:
            labels = {
                f"{b['name']} — {b['modified'].strftime('%Y-%m-%d %H:%M:%S')} "
                f"({b['size'] / (1024 * 1024):.2f} MB, {b['directory']}/)": b
                for b in backups
            }
            # A radio list of one-option radios was the old control here, which
            # could never actually deselect and so always reported a selection.
            choice = st.selectbox(
                "Backup to restore",
                options=["— select a backup —"] + list(labels),
                key="admin_console_restore_choice",
            )
            selected = labels.get(choice)
            if selected:
                confirmed = st.checkbox(
                    f"I understand this replaces the live database with "
                    f"{selected['name']}",
                    key="admin_console_confirm_restore_disk",
                )
                if confirmed and st.button("🔄 Restore database", type="primary",
                                           use_container_width=True,
                                           key="admin_console_restore_disk"):
                    ok, message = restore_database_from_backup(selected['path'])
                    if ok:
                        st.success(f"✅ {message}")
                        st.info("🔄 Refresh the page to see the restored data.")
                    else:
                        st.error(f"❌ {message}")

    with from_upload_tab:
        uploaded = st.file_uploader(
            "Backup database file (.db)", type=['db'],
            key="admin_console_restore_upload")
        if uploaded is not None:
            size_mb = len(uploaded.getvalue()) / (1024 * 1024)
            st.success(f"✅ {uploaded.name} ({size_mb:.2f} MB)")
            confirmed = st.checkbox(
                f"I understand this replaces the live database with {uploaded.name}",
                key="admin_console_confirm_restore_upload",
            )
            if confirmed and st.button("🔄 Restore from upload", type="primary",
                                       use_container_width=True,
                                       key="admin_console_restore_upload_btn"):
                ok, message = restore_database_from_upload(uploaded)
                if ok:
                    st.success(f"✅ {message}")
                    st.info("🔄 Refresh the page to see the restored data.")
                else:
                    st.error(f"❌ {message}")


def _render_email():
    """What notifications are actually configured to do, read from the notifier."""
    try:
        from .email_notifications import EmailNotifier
        notifier = EmailNotifier()
    except Exception as e:
        st.error(f"Could not load the email configuration: {str(e)}")
        return

    # Read off the notifier rather than restating it. The static block that used
    # to live in the hub sidebar still described a Gmail SMTP setup this app
    # stopped using when it moved to Resend.
    if getattr(notifier, 'configured', False):
        st.success("✅ Email notifications are configured.")
    else:
        st.warning("⚠️ Email notifications are not configured — no API key found in "
                   "secrets (`email.resend_api_key`) or the environment "
                   "(`RESEND_API_KEY`).")

    recipients = getattr(notifier, 'notification_recipients', []) or []
    st.markdown(f"""
    | Setting | Value |
    | --- | --- |
    | SMTP server | `{notifier.smtp_server}:{notifier.smtp_port}` |
    | Sender | `{notifier.sender_email}` |
    | Reply-to | `{notifier.reply_to}` |
    | Admin address | `{getattr(notifier, 'admin_email', '—')}` |
    | Notification recipients | {', '.join(f'`{r}`' for r in recipients) or '—'} |
    """)

    if st.button("Send a test email", use_container_width=True,
                 key="admin_console_test_email"):
        with st.spinner("Sending test email..."):
            # test_email_configuration() returns (success, message). Unpacking it
            # is the point: the old caller kept the tuple, which is always truthy,
            # so a failed send still reported success.
            success, message = notifier.test_email_configuration()
        if success:
            st.success(f"✅ {message}")
        else:
            st.error(f"❌ {message}")
