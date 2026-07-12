# modules/track_bidding.py
"""
Track Bidding module — lets staff bid on shifts for a future track cycle.
Admin controls: create bid tracks, toggle bidding, set capacity, promote to active.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import json

_eastern_tz = pytz.timezone('America/New_York')

from modules.db_utils import (
    initialize_database,
    get_active_track_config,
    get_bidding_track_config,
    get_track_config_by_name,
    get_all_track_configs,
    create_track_config,
    update_track_config,
    toggle_bidding,
    get_track_capacity,
    get_track_capacity_by_weekday,
    get_weekday_capacity_overrides,
    set_weekday_capacity_override,
    promote_bid_to_active,
    save_bid_track_to_db,
    get_bid_track_from_db,
    get_all_bid_tracks,
    get_track_from_db,
    delete_track_config,
    delete_bid,
    wipe_all_bids,
)
from modules.security import check_admin_access
from modules.shift_definitions import day_shifts, night_shifts


# ──────────────────────────────────────────────
# Admin sidebar (rendered inside the bidding page)
# ──────────────────────────────────────────────

def _render_bidding_admin_sidebar():
    """Render the Track Bidding admin controls in the sidebar."""
    with st.sidebar:
        st.markdown("## Track Bidding Admin")
        password = st.text_input("Enter admin password:", type="password", key="bid_admin_pw")
        admin_ok = check_admin_access(password)
        if not admin_ok:
            return

        st.success("Admin access granted!")
        all_configs = get_all_track_configs()

        # ── Section 1: create a new bid track ──
        st.markdown("---")
        st.subheader("Create New Bid Track")
        new_name = st.text_input("Track Name (e.g. FY27)", key="new_bid_name")

        st.markdown("**Bid Caps**")
        cap1, cap2 = st.columns(2)
        with cap1:
            dn = st.number_input("Max Day Nurses", 1, 50, 11, key="new_dn")
            nn = st.number_input("Max Night Nurses", 1, 50, 5, key="new_nn")
        with cap2:
            dm = st.number_input("Max Day Medics", 1, 50, 11, key="new_dm")
            nm = st.number_input("Max Night Medics", 1, 50, 5, key="new_nm")

        if st.button("Create Bid Track", key="create_bid_btn", use_container_width=True):
            if not new_name.strip():
                st.error("Please enter a track name.")
            else:
                ok, msg = create_track_config(new_name.strip(), dn, dm, nn, nm)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        # ── Section 2: manage existing track configs ──
        st.markdown("---")
        st.subheader("Manage Track Configs")

        for cfg in all_configs:
            tn = cfg['track_name']
            just_saved = st.session_state.get(f'config_saved_{tn}', False)
            with st.expander(f"{'🟢' if cfg['is_active'] else '🔵' if cfg['is_bidding_open'] else '⚪'} {tn}", expanded=just_saved):
                status_label = 'Active' if cfg['is_active'] else ('Bidding Open' if cfg['is_bidding_open'] else 'Inactive')
                st.markdown(f"**Status:** {status_label}")

                if not cfg['is_active']:
                    new_bid_state = st.checkbox(
                        "Bidding Open", value=bool(cfg['is_bidding_open']),
                        key=f"toggle_bid_{tn}")
                    if new_bid_state != bool(cfg['is_bidding_open']):
                        toggle_bidding(tn, new_bid_state)
                        st.rerun()

                # Editable fields for ALL configs (active and non-active)
                st.markdown("**Bid Caps**")
                uc1, uc2 = st.columns(2)
                with uc1:
                    u_dn = st.number_input("Day Nurses", 1, 50, cfg['max_day_nurses'], key=f"u_dn_{tn}")
                    u_nn = st.number_input("Night Nurses", 1, 50, cfg['max_night_nurses'], key=f"u_nn_{tn}")
                with uc2:
                    u_dm = st.number_input("Day Medics", 1, 50, cfg['max_day_medics'], key=f"u_dm_{tn}")
                    u_nm = st.number_input("Night Medics", 1, 50, cfg['max_night_medics'], key=f"u_nm_{tn}")

                st.markdown("**Day-of-Week Limits** *(optional — further restricts the Bid Caps above on specific weekdays)*")
                use_wd_cap = st.checkbox(
                    "Use day-of-week specific limits", value=bool(cfg.get('use_weekday_capacity', False)),
                    key=f"use_wd_cap_{tn}")
                if use_wd_cap != bool(cfg.get('use_weekday_capacity', False)):
                    update_track_config(tn, use_weekday_capacity=1 if use_wd_cap else 0)
                    st.rerun()

                if use_wd_cap:
                    weekday_order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                    overrides = get_weekday_capacity_overrides(tn)
                    grid_rows = []
                    for wd in weekday_order:
                        ov = overrides.get(wd, {})
                        grid_rows.append({
                            "Day": wd,
                            "Max Day Nurses": ov.get('max_day_nurses') if ov.get('max_day_nurses') is not None else u_dn,
                            "Max Day Medics": ov.get('max_day_medics') if ov.get('max_day_medics') is not None else u_dm,
                            "Max Night Nurses": ov.get('max_night_nurses') if ov.get('max_night_nurses') is not None else u_nn,
                            "Max Night Medics": ov.get('max_night_medics') if ov.get('max_night_medics') is not None else u_nm,
                        })
                    edited_grid = st.data_editor(
                        pd.DataFrame(grid_rows),
                        hide_index=True, use_container_width=True, key=f"wd_grid_{tn}",
                        column_config={
                            "Day": st.column_config.TextColumn(disabled=True),
                            "Max Day Nurses": st.column_config.NumberColumn(min_value=0, max_value=50, step=1),
                            "Max Day Medics": st.column_config.NumberColumn(min_value=0, max_value=50, step=1),
                            "Max Night Nurses": st.column_config.NumberColumn(min_value=0, max_value=50, step=1),
                            "Max Night Medics": st.column_config.NumberColumn(min_value=0, max_value=50, step=1),
                        }
                    )
                    st.caption("Blank/unedited rows use the Bid Caps above. Saving writes all 7 days explicitly, so a later change to Bid Caps won't retroactively change days you've saved here.")
                    if st.button("Save Day-of-Week Limits", key=f"save_wd_cap_{tn}", use_container_width=True):
                        for _, row in edited_grid.iterrows():
                            set_weekday_capacity_override(
                                tn, row["Day"],
                                max_day_nurses=int(row["Max Day Nurses"]),
                                max_day_medics=int(row["Max Day Medics"]),
                                max_night_nurses=int(row["Max Night Nurses"]),
                                max_night_medics=int(row["Max Night Medics"]),
                            )
                        st.session_state[f'wd_cap_saved_{tn}'] = True
                        st.rerun()

                    if st.session_state.pop(f'wd_cap_saved_{tn}', False):
                        st.success(f"Day-of-week limits saved for {tn}")

                st.markdown("**Base Shift Counts** *(day/night shift slots per base, used for hypothetical bid assignments)*")
                bc_day, bc_night = st.columns(2)
                with bc_day:
                    st.caption("Day shifts per base")
                    u_day_kmht = st.number_input("KMHT", 0, 20, cfg.get('day_kmht', 1), key=f"u_day_kmht_{tn}")
                    u_day_klwm = st.number_input("KLWM", 0, 20, cfg.get('day_klwm', 2), key=f"u_day_klwm_{tn}")
                    u_day_kbed = st.number_input("KBED", 0, 20, cfg.get('day_kbed', 2), key=f"u_day_kbed_{tn}")
                    u_day_1b9 = st.number_input("1B9", 0, 20, cfg.get('day_1b9', 2), key=f"u_day_1b9_{tn}")
                    u_day_kpym = st.number_input("KPYM", 0, 20, cfg.get('day_kpym', 2), key=f"u_day_kpym_{tn}")
                with bc_night:
                    st.caption("Night shifts per base")
                    u_night_klwm = st.number_input("KLWM", 0, 20, cfg.get('night_klwm', 1), key=f"u_night_klwm_{tn}")
                    u_night_kbed = st.number_input("KBED", 0, 20, cfg.get('night_kbed', 2), key=f"u_night_kbed_{tn}")
                    u_night_kpym = st.number_input("KPYM", 0, 20, cfg.get('night_kpym', 2), key=f"u_night_kpym_{tn}")
                    st.caption("KMHT and 1B9 have no night shifts")

                if st.button("Save All Settings", key=f"save_cap_{tn}", use_container_width=True):
                    ok, msg = update_track_config(tn,
                                        max_day_nurses=u_dn, max_day_medics=u_dm,
                                        max_night_nurses=u_nn, max_night_medics=u_nm,
                                        day_kmht=u_day_kmht, day_klwm=u_day_klwm,
                                        day_kbed=u_day_kbed, day_1b9=u_day_1b9, day_kpym=u_day_kpym,
                                        night_klwm=u_night_klwm, night_kbed=u_night_kbed,
                                        night_kpym=u_night_kpym)
                    if ok:
                        st.session_state[f'config_saved_{tn}'] = True
                        st.rerun()
                    else:
                        st.error(f"Save failed: {msg}")

                if st.session_state.pop(f'config_saved_{tn}', False):
                    st.success(f"Settings saved for {tn}")

                # Bid count and management
                st.markdown("---")
                bid_tracks_result = get_all_bid_tracks(tn)
                bid_list = bid_tracks_result[1] if bid_tracks_result[0] else []
                bid_count = len(bid_list) if isinstance(bid_list, list) else 0
                st.markdown(f"**Bids submitted:** {bid_count}")

                if bid_count > 0 and isinstance(bid_list, list):
                    for bi, b in enumerate(bid_list):
                        role = b['metadata'].get('effective_role', '?')
                        bkey = f"{tn}_{bi}_{b['staff_name']}"
                        bcol1, bcol2 = st.columns([3, 1])
                        with bcol1:
                            st.markdown(f"- {b['staff_name']} (v{b['version']}, {role})")
                        with bcol2:
                            if st.button("Delete", key=f"del_bid_{bkey}", type="secondary"):
                                st.session_state[f'confirm_del_bid_{bkey}'] = True

                        if st.session_state.get(f'confirm_del_bid_{bkey}', False):
                            st.warning(f"Delete bid for **{b['staff_name']}**?")
                            dc1, dc2 = st.columns(2)
                            with dc1:
                                if st.button("Yes, Delete", key=f"yes_del_bid_{bkey}"):
                                    ok, msg = delete_bid(b['staff_name'], tn)
                                    st.session_state[f'confirm_del_bid_{bkey}'] = False
                                    if ok:
                                        st.success(msg)
                                    else:
                                        st.error(msg)
                                    st.rerun()
                            with dc2:
                                if st.button("Cancel", key=f"no_del_bid_{bkey}"):
                                    st.session_state[f'confirm_del_bid_{bkey}'] = False
                                    st.rerun()

                    # Wipe all bids button
                    if st.button(f"Wipe All Bids for {tn}", key=f"wipe_bids_{tn}", use_container_width=True):
                        st.session_state[f'confirm_wipe_{tn}'] = True

                    if st.session_state.get(f'confirm_wipe_{tn}', False):
                        st.warning(f"This will delete **all {bid_count} bids** for {tn}. This cannot be undone.")
                        wc1, wc2 = st.columns(2)
                        with wc1:
                            if st.button("Yes, Wipe All", key=f"yes_wipe_{tn}"):
                                ok, msg = wipe_all_bids(tn)
                                st.session_state[f'confirm_wipe_{tn}'] = False
                                if ok:
                                    st.success(msg)
                                else:
                                    st.error(msg)
                                st.rerun()
                        with wc2:
                            if st.button("Cancel", key=f"no_wipe_{tn}"):
                                st.session_state[f'confirm_wipe_{tn}'] = False
                                st.rerun()

                if not cfg['is_active']:
                    # Promote to active
                    st.markdown("---")
                    if st.button(f"Promote {tn} to Active", key=f"promote_{tn}",
                                 type="primary", use_container_width=True):
                        st.session_state[f'confirm_promote_{tn}'] = True

                    if st.session_state.get(f'confirm_promote_{tn}', False):
                        st.warning(f"This will deactivate the current active track and make **{tn}** active. Are you sure?")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("Yes, Promote", key=f"confirm_yes_{tn}"):
                                ok, msg = promote_bid_to_active(tn)
                                if ok:
                                    st.success(msg)
                                    st.session_state[f'confirm_promote_{tn}'] = False
                                    st.rerun()
                                else:
                                    st.error(msg)
                        with c2:
                            if st.button("Cancel", key=f"confirm_no_{tn}"):
                                st.session_state[f'confirm_promote_{tn}'] = False
                                st.rerun()

                    # Delete track config
                    st.markdown("---")
                    if st.button(f"Delete {tn}", key=f"delete_cfg_{tn}", use_container_width=True):
                        st.session_state[f'confirm_delete_cfg_{tn}'] = True

                    if st.session_state.get(f'confirm_delete_cfg_{tn}', False):
                        st.error(f"Delete track config **{tn}** and all its bids? This cannot be undone.")
                        d1, d2 = st.columns(2)
                        with d1:
                            if st.button("Yes, Delete", key=f"yes_del_cfg_{tn}"):
                                ok, msg = delete_track_config(tn)
                                st.session_state[f'confirm_delete_cfg_{tn}'] = False
                                if ok:
                                    st.success(msg)
                                else:
                                    st.error(msg)
                                st.rerun()
                        with d2:
                            if st.button("Cancel", key=f"no_del_cfg_{tn}"):
                                st.session_state[f'confirm_delete_cfg_{tn}'] = False
                                st.rerun()

        # ── Section 3: bid submission status ──
        st.markdown("---")
        st.subheader("Bid Submission Status")
        bid_cfg = get_bidding_track_config()
        if bid_cfg:
            tn = bid_cfg['track_name']
            ok, bids = get_all_bid_tracks(tn)
            if ok and bids:
                st.markdown(f"**{tn}**: {len(bids)} bids submitted")
                for b in bids:
                    role = b['metadata'].get('effective_role', '?')
                    st.markdown(f"- {b['staff_name']} (v{b['version']}, {role})")
            else:
                st.info(f"No bids submitted yet for {tn}")
        else:
            st.info("No bidding track is currently open.")


# ──────────────────────────────────────────────
# Main bidding page (staff-facing)
# ──────────────────────────────────────────────

def display_track_bidding():
    """Main entry point for the Track Bidding section."""
    st.markdown("")
    st.markdown("")

    if st.button("← Back to CrewOps360", key="back_from_bidding"):
        st.session_state.selected_module = None
        st.rerun()

    st.markdown("# Track Bidding")

    # Render admin sidebar
    _render_bidding_admin_sidebar()

    # Check if there is an open bidding track
    bid_cfg = get_bidding_track_config()
    active_cfg = get_active_track_config()

    if not bid_cfg:
        st.info("Bidding is currently closed. Check back later for the next bidding cycle.")
        if active_cfg:
            st.markdown(f"**Current active track:** {active_cfg['track_name']}")
        return

    bid_track_name = bid_cfg['track_name']
    st.markdown(f"### Bidding open for: **{bid_track_name}**")

    # Show capacity info
    cap = get_track_capacity(bid_track_name)
    st.markdown("**Staffing Capacity**")
    cap_cols = st.columns(4)
    cap_cols[0].metric("Max Day Nurses", cap['max_day_nurses'])
    cap_cols[1].metric("Max Day Medics", cap['max_day_medics'])
    cap_cols[2].metric("Max Night Nurses", cap['max_night_nurses'])
    cap_cols[3].metric("Max Night Medics", cap['max_night_medics'])

    if cap.get('use_weekday_capacity'):
        with st.expander("Day-of-week limits (in addition to the caps above)"):
            weekday_caps = get_track_capacity_by_weekday(bid_track_name)
            weekday_order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            table = [
                {
                    "Day": wd,
                    "Max Day Nurses": weekday_caps[wd]['max_day_nurses'],
                    "Max Day Medics": weekday_caps[wd]['max_day_medics'],
                    "Max Night Nurses": weekday_caps[wd]['max_night_nurses'],
                    "Max Night Medics": weekday_caps[wd]['max_night_medics'],
                }
                for wd in weekday_order
            ]
            st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    if active_cfg:
        st.markdown(f"*Prior active track: {active_cfg['track_name']}*")

    # ── Load data files (same as clinical track hub) ──
    _run_bidding_interface(bid_track_name, cap)


def _run_bidding_interface(bid_track_name, capacity):
    """Run the bidding interface — mirrors run_clinical_track_hub but for bids."""
    import os
    import glob as glob_mod
    from modules.column_mapper import auto_detect_columns
    from modules.db_utils import get_track_from_db as _get_track

    # Load Excel files (same pattern as clinical track hub)
    excel_files = {
        "preferences": None,
        "current_tracks": None,
        "requirements": None,
        "preassignments": None,
    }
    upload_dir = "upload files"
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            fl = f.lower()
            fp = os.path.join(upload_dir, f)
            if 'preference' in fl and fl.endswith('.xlsx'):
                excel_files['preferences'] = fp
            elif 'track' in fl and fl.endswith('.xlsx'):
                excel_files['current_tracks'] = fp
            elif 'requirement' in fl and fl.endswith('.xlsx'):
                excel_files['requirements'] = fp
            elif 'preassignment' in fl and fl.endswith('.xlsx'):
                excel_files['preassignments'] = fp

    if not excel_files['preferences']:
        st.error("Preferences file not found in 'upload files' folder.")
        return

    if not excel_files['current_tracks']:
        st.error("Current tracks file not found in 'upload files' folder.")
        return

    def load_excel(path):
        return pd.read_excel(path) if path else None

    preferences_df = load_excel(excel_files['preferences'])
    current_tracks_df = load_excel(excel_files['current_tracks'])
    requirements_df = load_excel(excel_files['requirements'])

    # NOTE: preassignments must be loaded via load_preassignments() rather than a bare
    # load_excel() — get_staff_preassignments() looks staff up via
    # preassignment_df.loc[staff_name], which requires the staff-name index (and
    # duplicate-row handling) that only load_preassignments() sets up.
    from modules.track_management.preassignment import load_preassignments
    preassignment_df = load_preassignments() if excel_files['preassignments'] else None

    if preferences_df is None:
        st.error("Could not load preferences file.")
        return

    # Detect columns
    detection = auto_detect_columns(preferences_df, current_tracks_df)
    mappings = detection['column_mappings']
    staff_col_prefs = mappings['staff_col_prefs']
    staff_col_tracks = mappings.get('staff_col_tracks')
    role_col = mappings['role_col']
    days = list(current_tracks_df.columns[1:43])  # 6 weeks = 42 days (mirrors run_clinical_track_hub)
    no_matrix_col = mappings.get('no_matrix_col')
    reduced_rest_col = mappings.get('reduced_rest_col')
    seniority_col = mappings.get('seniority_col')

    if not staff_col_prefs or not days:
        st.error("Could not detect required columns.")
        return

    # Staff selection
    staff_names = sorted(preferences_df[staff_col_prefs].dropna().unique().tolist())

    st.markdown("---")
    selected_staff = st.selectbox("Select Your Name", [""] + staff_names, key="bid_staff_select")

    if not selected_staff:
        st.info("Please select your name to begin.")
        return

    # Store for submission access
    st.session_state['preferences_df'] = preferences_df
    st.session_state['staff_col_prefs'] = staff_col_prefs
    st.session_state['role_col'] = role_col

    # Run the bidding staff interface
    _display_bidding_staff_interface(
        selected_staff, preferences_df, current_tracks_df, requirements_df,
        days, staff_col_prefs, staff_col_tracks, role_col,
        no_matrix_col, reduced_rest_col, seniority_col,
        preassignment_df, bid_track_name, capacity
    )


def _display_bidding_staff_interface(
    selected_staff, preferences_df, current_tracks_df, requirements_df,
    days, staff_col_prefs, staff_col_tracks, role_col,
    no_matrix_col, reduced_rest_col, seniority_col,
    preassignment_df, bid_track_name, capacity
):
    """Render the tabbed bidding interface for a single staff member."""
    from modules.track_management.display import display_schedule_by_blocks
    from modules.track_management.preference_display import display_preferences
    from modules.preference_editor import display_location_preference_editor
    from modules.track_management.preassignment import get_staff_preassignments
    from modules.track_management.utils import reset_track_session_state
    from modules.enhanced_track_validator import validate_track_comprehensive
    from modules.enhanced_validation_display import display_comprehensive_validation
    from modules.track_modification_core import calculate_all_modification_options
    from modules.db_utils import get_location_preferences_from_db

    st.header(f"Track Bidding — {bid_track_name}")

    # ── Extract requirements ──
    shifts_per_pay_period = 0
    night_minimum = 0
    weekend_minimum = 0
    weekend_group = None

    if requirements_df is not None and not requirements_df.empty:
        try:
            staff_req = None
            possible_cols = [requirements_df.columns[0], 'STAFF NAME', 'Staff Name', 'staff name', 'Name', 'NAME']
            for col_name in possible_cols:
                if col_name in requirements_df.columns:
                    staff_req = requirements_df[requirements_df[col_name] == selected_staff]
                    if staff_req.empty:
                        staff_req = requirements_df[requirements_df[col_name].str.lower() == selected_staff.lower()]
                    if not staff_req.empty:
                        break
            if staff_req is not None and not staff_req.empty:
                row = staff_req.iloc[0]
                if len(requirements_df.columns) >= 4:
                    if pd.notna(row.iloc[1]):
                        shifts_per_pay_period = int(float(row.iloc[1]))
                    if pd.notna(row.iloc[2]):
                        night_minimum = int(float(row.iloc[2]))
                    if pd.notna(row.iloc[3]):
                        weekend_minimum = int(float(row.iloc[3]))
                if len(requirements_df.columns) >= 5 and pd.notna(row.iloc[4]):
                    wg = str(row.iloc[4]).strip().upper()
                    if wg in ['A', 'B', 'C', 'D', 'E']:
                        weekend_group = wg
        except Exception as e:
            st.warning(f"Error loading requirements: {e}")

    # Requirements display
    st.markdown("### Staff Requirements")
    rc = st.columns(4)
    rc[0].metric("Shifts per Pay Period", shifts_per_pay_period)
    rc[1].metric("Night Minimum", night_minimum)
    rc[2].metric("Weekend Minimum", weekend_minimum)
    rc[3].metric("Weekend Group", weekend_group or "None")

    # Staff info
    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]

    # Get preassignments
    staff_preassignments = {}
    if preassignment_df is not None:
        staff_preassignments = get_staff_preassignments(selected_staff, preassignment_df, days)

    # Check for existing bid
    bid_result = get_bid_track_from_db(selected_staff, bid_track_name)
    has_bid = bid_result[0]

    # Check for active track (reference)
    active_cfg = get_active_track_config()
    active_track_name = active_cfg['track_name'] if active_cfg else 'FY26'
    active_result = get_track_from_db(selected_staff, active_track_name)
    has_active = active_result[0]

    # Determine starting point for the bid editor: existing bid > blank
    # (never the active track — a fresh bid should start empty, not a copy of last cycle's track)
    if has_bid:
        current_track_data = bid_result[1]['track_data']
    else:
        current_track_data = {day: "" for day in days}

    # Apply preassignments
    if staff_preassignments:
        for day, pa in staff_preassignments.items():
            if day not in current_track_data or not current_track_data[day]:
                current_track_data[day] = pa

    # Store requirements
    st.session_state.shifts_per_pay_period = shifts_per_pay_period
    st.session_state.night_minimum = night_minimum
    st.session_state.weekend_minimum = weekend_minimum
    st.session_state.weekend_group = weekend_group

    # Session state keys for bidding (namespaced to avoid collision with clinical hub)
    bid_changes_key = f'bid_track_changes_{bid_track_name}'
    bid_modified_key = f'bid_modified_track_{bid_track_name}'

    # Clear button
    if st.button("Clear All Shifts", key=f"bid_clear_{selected_staff}_{bid_track_name}", use_container_width=True):
        blank = {day: "" for day in days}
        if staff_preassignments:
            for day, pa in staff_preassignments.items():
                blank[day] = pa
        st.session_state[bid_changes_key] = {selected_staff: blank}
        st.session_state[bid_modified_key] = {
            'staff': selected_staff, 'track': blank.copy(), 'valid': False, 'is_new': True
        }
        st.success("Cleared your in-progress selections below. If you already submitted a bid, it is unchanged until you submit again.")
        st.rerun()
    st.caption("Clears your working selections below — does not delete a bid you've already submitted unless you resubmit afterward.")

    # Initialize session state for bidding track changes
    if bid_changes_key not in st.session_state:
        st.session_state[bid_changes_key] = {}
    if selected_staff not in st.session_state[bid_changes_key]:
        st.session_state[bid_changes_key][selected_staff] = current_track_data.copy()
    if bid_modified_key not in st.session_state or st.session_state[bid_modified_key].get('staff') != selected_staff:
        st.session_state[bid_modified_key] = {
            'staff': selected_staff,
            'track': st.session_state[bid_changes_key][selected_staff].copy(),
            'valid': False,
            'is_new': not has_bid
        }

    # Alias into the main session keys so existing editor/validator modules work
    st.session_state.track_changes = st.session_state[bid_changes_key]
    st.session_state.modified_track = st.session_state[bid_modified_key]

    # ── Tabs ──
    tab_labels = [
        "📍 Current Track", "⚙️ Preferences", "🛠️ Edit Preferences",
        "🔄 Track Selection", "🔍 Validation", "📤 Submission",
        "🔮 Hypothetical Schedule"
    ]
    tabs = st.tabs(tab_labels)

    # Helper to build current track for validation
    def _build_track():
        vt = {day: "" for day in days}
        if selected_staff in st.session_state[bid_changes_key]:
            vt.update(st.session_state[bid_changes_key][selected_staff])
        if staff_preassignments:
            for day, pa in staff_preassignments.items():
                if pa == "AT":
                    vt[day] = "AT"
                elif pa in ["D", "N"]:
                    vt[day] = pa
                else:
                    vt[day] = "D"
        return vt

    # ── Tab 0: Current Track ──
    with tabs[0]:
        st.subheader("Current Track")
        if has_active:
            st.info(f"📊 Your active track: **{active_track_name}**")
            display_schedule_by_blocks(active_result[1]['track_data'], days, staff_preassignments)
        else:
            st.info("You do not have an active track on file yet.")

        st.markdown("---")

        st.subheader("Current Track Bid")
        if has_bid:
            st.info(f"📊 Your submitted bid for **{bid_track_name}** (version {bid_result[1]['version']}, submitted {bid_result[1]['submission_date']}).")
            display_schedule_by_blocks(bid_result[1]['track_data'], days, staff_preassignments)
        else:
            st.info(f"You have not submitted a bid for **{bid_track_name}** yet. Use the **Track Selection** tab to build your bid, then submit it from the **Submission** tab.")

    # ── Tab 1: Preferences ──
    with tabs[1]:
        display_preferences(selected_staff, staff_info, preferences_df)

    # ── Tab 2: Edit Preferences ──
    with tabs[2]:
        display_location_preference_editor(selected_staff)

    # ── Tab 3: Track Selection (the bidding editor) ──
    with tabs[3]:
        _display_track_selection_tab(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
            reduced_rest_col, seniority_col,
            shifts_per_pay_period, night_minimum, weekend_minimum,
            staff_preassignments, weekend_group, requirements_df,
            capacity, bid_track_name, bid_changes_key, bid_modified_key
        )

    # ── Tab 4: Validation ──
    with tabs[4]:
        st.subheader(f"Bid Validation for {selected_staff}")
        current_track = _build_track()
        is_valid = display_comprehensive_validation(
            current_track, days, shifts_per_pay_period, night_minimum,
            weekend_minimum, staff_preassignments, weekend_group,
            requirements_df, selected_staff
        )
        st.session_state[bid_modified_key]['valid'] = is_valid
        st.session_state.modified_track = st.session_state[bid_modified_key]
        if is_valid:
            st.success("Your bid passes all validation requirements! Proceed to Submission.")
        else:
            st.warning("Your bid has validation issues. Review above and adjust in Track Selection.")

    # ── Tab 5: Submission ──
    with tabs[5]:
        _display_bid_submission(
            selected_staff, days, shifts_per_pay_period, night_minimum, weekend_minimum,
            staff_preassignments, bid_track_name, bid_changes_key, bid_modified_key,
            preferences_df, staff_col_prefs, role_col
        )

    # ── Tab 6: Hypothetical Schedule ──
    with tabs[6]:
        _display_bid_hypothetical(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
            reduced_rest_col, seniority_col, capacity, bid_track_name
        )

    # Write back bidding-specific state
    st.session_state[bid_changes_key] = st.session_state.track_changes
    st.session_state[bid_modified_key] = st.session_state.modified_track


# ──────────────────────────────────────────────
# Tab implementations
# ──────────────────────────────────────────────

def _display_track_selection_tab(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
    reduced_rest_col, seniority_col,
    shifts_per_pay_period, night_minimum, weekend_minimum,
    preassignments, weekend_group, requirements_df,
    capacity, bid_track_name, bid_changes_key, bid_modified_key
):
    """Track Selection tab — same as Track Modification but for bidding."""
    from modules.track_management.editor import display_track_modification_interface_enhanced
    from modules.track_modification_core import calculate_all_modification_options

    st.subheader(f"Track Selection for {selected_staff}")

    # Requirements
    st.markdown("### Requirements")
    rc = st.columns(4)
    rc[0].metric("Shifts/Pay Period", shifts_per_pay_period)
    rc[1].metric("Night Min", night_minimum)
    rc[2].metric("Weekend Min", weekend_minimum)
    rc[3].metric("Weekend Group", weekend_group or "None")

    st.info(f"Selecting shifts for **{bid_track_name}** bidding cycle.")

    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
    staff_role = staff_info[role_col]

    max_day_nurses = capacity['max_day_nurses']
    max_day_medics = capacity['max_day_medics']
    max_night_nurses = capacity['max_night_nurses']
    max_night_medics = capacity['max_night_medics']

    with st.spinner("Analyzing schedule needs and preferences..."):
        modification_results = calculate_all_modification_options(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
            reduced_rest_col, seniority_col,
            max_day_nurses=max_day_nurses, max_day_medics=max_day_medics,
            max_night_nurses=max_night_nurses, max_night_medics=max_night_medics,
            bid_track_name=bid_track_name
        )
        options_by_day = modification_results["options_by_day"]
        day_assignments = modification_results["day_assignments"]
        night_assignments = modification_results["night_assignments"]
        assignment_details = modification_results["assignment_details"]

    # Reference track: always the active track — shown for comparison only, never edited
    bid_result = get_bid_track_from_db(selected_staff, bid_track_name)
    has_bid = bid_result[0]
    active_cfg = get_active_track_config()
    active_name = active_cfg['track_name'] if active_cfg else 'FY26'
    active_result = get_track_from_db(selected_staff, active_name)
    has_active = active_result[0]

    if has_active:
        reference_track = active_result[1]['track_data'].copy()
    elif current_tracks_df is not None and staff_col_tracks:
        st_df = current_tracks_df[current_tracks_df[staff_col_tracks] == selected_staff]
        if not st_df.empty:
            reference_track = {day: st_df.iloc[0][day] for day in days}
        else:
            reference_track = {day: "" for day in days}
    else:
        reference_track = {day: "" for day in days}

    # Initialize track changes: existing bid > blank — never a copy of the reference track
    if selected_staff not in st.session_state.track_changes:
        if has_bid:
            track_data = bid_result[1]['track_data'].copy()
        else:
            track_data = {day: "" for day in days}
        if preassignments:
            for day, pa in preassignments.items():
                if pa == "AT":
                    track_data[day] = "AT"
                else:
                    track_data[day] = "D"
        st.session_state.track_changes[selected_staff] = track_data

    if st.session_state.modified_track.get('staff') != selected_staff:
        st.session_state.modified_track = {
            'staff': selected_staff,
            'track': st.session_state.track_changes[selected_staff].copy(),
            'valid': False,
            'is_new': not has_bid
        }

    st.markdown("""
    ### How to Select Your Track

    1. Select days where you want to work by clicking on the radio buttons
    2. Use **"Validate Block"** buttons to check individual 2-week blocks
    3. Preassignments (if any) are shown as selected and locked
    4. Days where your role is needed are highlighted in green
    5. Go to the **Validation tab** to check your complete bid, then proceed to Submission
    """)

    if preassignments:
        from modules.track_management.preassignment import display_preassignments
        display_preassignments(selected_staff, preassignments)

    # Use database logic
    use_database_logic = True
    has_db_track = has_bid

    display_track_modification_interface_enhanced(
        selected_staff, options_by_day, reference_track, days,
        preassignments, use_database_logic, has_db_track, staff_role, weekend_group,
        day_assignments, night_assignments, assignment_details
    )

    # Quick validation
    st.markdown("### Quick Validation Status")
    st.info("For comprehensive results, go to the **Validation tab**.")
    from modules.enhanced_track_validator import validate_track_comprehensive
    vt = {day: "" for day in days}
    if selected_staff in st.session_state.track_changes:
        vt.update(st.session_state.track_changes[selected_staff])
    if preassignments:
        for day, pa in preassignments.items():
            if pa == "AT":
                vt[day] = "AT"
            elif pa in ["D", "N"]:
                vt[day] = pa
            else:
                vt[day] = "D"

    val_result = validate_track_comprehensive(
        vt, shifts_per_pay_period, night_minimum,
        weekend_minimum, preassignments, days, weekend_group,
        requirements_df, selected_staff
    )
    is_valid = val_result['overall_valid']
    st.session_state.modified_track['valid'] = is_valid
    if is_valid:
        st.success("Your bid meets all requirements! Go to Submission to finalize.")
    else:
        total_issues = sum(len(r.get('issues', [])) for k, r in val_result.items()
                          if k != 'overall_valid' and isinstance(r, dict) and not r.get('status', True))
        st.warning(f"Your bid has {total_issues} validation issues. Check the Validation tab.")


def _display_bid_submission(
    selected_staff, days, shifts_per_pay_period, night_minimum, weekend_minimum,
    preassignments, bid_track_name, bid_changes_key, bid_modified_key,
    preferences_df, staff_col_prefs, role_col
):
    """Handle bid submission."""
    st.subheader(f"Submit Bid for {selected_staff}")
    st.info(f"Submitting bid for **{bid_track_name}**.")

    modified_track = st.session_state.track_changes.get(selected_staff, {})
    valid = st.session_state.modified_track.get('valid', False)

    if valid:
        st.success("Your bid meets all requirements and is ready to submit.")
    else:
        st.error("Your bid has validation issues. Please fix them in Track Selection before submitting.")

    # Schedule preview
    st.markdown("### Schedule Preview")
    blocks = ["A", "B", "C"]
    block_tabs = st.tabs([f"Block {b}" for b in blocks])
    for bi, bt in enumerate(block_tabs):
        with bt:
            start = bi * 14
            end = start + 14
            block_days = days[start:end]
            tdata = []
            for day in block_days:
                assignment = modified_track.get(day, "")
                if not assignment and preassignments and day in preassignments:
                    assignment = preassignments[day]
                tdata.append({"Day": day, "Assignment": assignment if assignment else ""})
            st.dataframe(pd.DataFrame(tdata), use_container_width=True, hide_index=True)

    if valid:
        bid_submitted_key = f'bid_submitted_{bid_track_name}_{selected_staff}'
        if not st.session_state.get(bid_submitted_key, False):
            if st.button("Submit Bid", use_container_width=True, type="primary", key=f"submit_bid_{bid_track_name}"):
                with st.spinner("Saving bid..."):
                    # Build track to save
                    track_to_save = modified_track.copy()
                    if preassignments:
                        for day, pa in preassignments.items():
                            if day not in track_to_save or not track_to_save[day]:
                                track_to_save[day] = pa

                    # Get role
                    staff_role = 'nurse'
                    effective_role = 'nurse'
                    if preferences_df is not None and staff_col_prefs and role_col:
                        si = preferences_df[preferences_df[staff_col_prefs] == selected_staff]
                        if not si.empty:
                            staff_role = si.iloc[0][role_col]
                            effective_role = "nurse" if str(staff_role).lower().strip() in ["nurse", "dual"] else "medic"

                    meta = {
                        'original_role': staff_role,
                        'effective_role': effective_role,
                        'track_source': 'Bid',
                        'has_preassignments': bool(preassignments),
                        'preassignment_count': len(preassignments) if preassignments else 0,
                    }

                    ok, msg, tid = save_bid_track_to_db(selected_staff, track_to_save, bid_track_name, meta)
                    if ok:
                        st.session_state[bid_submitted_key] = True
                        st.success(f"Bid submitted successfully! {msg}")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(f"Error: {msg}")
        else:
            st.success(f"Your bid for {bid_track_name} has been submitted.")
            if st.button("Update Bid", use_container_width=True, key=f"update_bid_{bid_track_name}"):
                st.session_state[f'bid_submitted_{bid_track_name}_{selected_staff}'] = False
                st.rerun()
    else:
        st.error("Cannot submit — fix validation issues first.")


def _display_bid_hypothetical(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
    reduced_rest_col, seniority_col, capacity, bid_track_name
):
    """Hypothetical schedule for bidding — uses bid pool for counts."""
    from modules.track_modification_core import calculate_all_modification_options
    from modules.db_utils import get_location_preferences_from_db

    st.subheader(f"Hypothetical Schedule for {selected_staff}")

    max_dn = capacity['max_day_nurses']
    max_dm = capacity['max_day_medics']
    max_nn = capacity['max_night_nurses']
    max_nm = capacity['max_night_medics']

    with st.spinner("Generating hypothetical schedule..."):
        results = calculate_all_modification_options(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
            reduced_rest_col, seniority_col,
            max_day_nurses=max_dn, max_day_medics=max_dm,
            max_night_nurses=max_nn, max_night_medics=max_nm,
            bid_track_name=bid_track_name
        )

    day_assignments = results['day_assignments']
    night_assignments = results['night_assignments']
    assignment_details = results['assignment_details']

    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
    staff_role = staff_info[role_col]
    effective_role = "nurse" if str(staff_role).lower().strip() in ["nurse", "dual"] else "medic"

    has_base_prefs, _ = get_location_preferences_from_db(selected_staff)
    if has_base_prefs:
        st.success("Using your base preferences for this hypothetical schedule.")
    else:
        st.warning("No base preferences found. Set them in Edit Preferences for better results.")

    st.markdown("### Hypothetical Schedule")
    total_day = sum(1 for a in day_assignments.values() if a)
    total_night = sum(1 for a in night_assignments.values() if a)
    sc = st.columns(3)
    sc[0].metric("Total Shifts", total_day + total_night)
    sc[1].metric("Day Shifts", total_day)
    sc[2].metric("Night Shifts", total_night)

    blocks = ["A", "B", "C"]
    block_tabs = st.tabs([f"Block {b}" for b in blocks])
    for bi, bt in enumerate(block_tabs):
        with bt:
            start = bi * 14
            end = start + 14
            block_days = days[start:end]
            table = []
            for day in block_days:
                da = day_assignments.get(day)
                na = night_assignments.get(day)
                dd = assignment_details.get(day, {}).get('day', {})
                nd = assignment_details.get(day, {}).get('night', {})

                day_info = "No assignment"
                if da:
                    pref = dd.get('preference_score')
                    day_info = f"{da} (Rank {pref})" if pref else f"{da}"

                night_info = "No assignment"
                if na:
                    pref = nd.get('preference_score')
                    night_info = f"{na} (Rank {pref})" if pref else f"{na}"

                table.append({"Day": day, "Day Shift": day_info, "Night Shift": night_info})
            st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
