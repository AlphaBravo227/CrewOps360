# modules/track_bidding.py
"""
Track Bidding module — lets staff bid on shifts for a future track cycle.
Admin controls: create bid tracks, toggle bidding, set capacity, manage per-staff
bid access, add/update/remove bids on staff members' behalf, promote to active.
"""

import streamlit as st
import pandas as pd
import altair as alt
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
    get_bid_access,
    set_bid_access,
    get_all_bid_access_configs,
    log_bid_progression_event,
    get_bid_progression_log,
)
from modules.security import check_admin_access
from modules.shift_definitions import day_shifts, night_shifts


# ──────────────────────────────────────────────
# Shared data loading (staff roster + Excel files used by the bidding editor)
# ──────────────────────────────────────────────

def _get_preassignment_day_columns(path):
    """
    Read the ordered list of day-pattern columns (e.g. "Sun A 1" ... "Sat C 6")
    straight from the preassignments file's header row.

    Read independently of load_preassignments() (which may collapse the file into
    a plain dict when duplicate staff names are present) so the day schema is
    always derived directly from the file's own columns, never from Tracks.xlsx.
    """
    header_df = pd.read_excel(path, nrows=0)
    cols = list(header_df.columns)
    staff_col = cols[0]
    for col in cols:
        if isinstance(col, str) and "name" in col.lower() and "staff" in col.lower():
            staff_col = col
            break
    return [c for c in cols if c != staff_col]


def _load_bidding_data_files():
    """
    Load and column-map the Excel data files used by the bidding interface
    (same files/pattern as the clinical track hub). Shared by the staff-facing
    flow and the admin "Add/Update Selection" / "Manage Bid Access" tabs.

    Returns:
        tuple: (ctx, error) — ctx is a dict with everything the bidding staff
        interface needs (minus the selected staff and track-specific capacity),
        or None if a required file/column is missing, in which case error is a
        message describing what's wrong.
    """
    import os
    from modules.column_mapper import auto_detect_columns
    from modules.track_management.preassignment import load_preassignments

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
        return None, "Preferences file not found in 'upload files' folder."

    if not excel_files['current_tracks']:
        return None, "Current tracks file not found in 'upload files' folder."

    if not excel_files['preassignments']:
        return None, "Preassignments file not found in 'upload files' folder."

    def load_excel(path):
        return pd.read_excel(path) if path else None

    preferences_df = load_excel(excel_files['preferences'])
    current_tracks_df = load_excel(excel_files['current_tracks'])
    requirements_df = load_excel(excel_files['requirements'])

    # NOTE: preassignments must be loaded via load_preassignments() rather than a bare
    # load_excel() — get_staff_preassignments() looks staff up via
    # preassignment_df.loc[staff_name], which requires the staff-name index (and
    # duplicate-row handling) that only load_preassignments() sets up.
    preassignment_df = load_preassignments()

    if preferences_df is None:
        return None, "Could not load preferences file."

    # Detect columns
    detection = auto_detect_columns(preferences_df, current_tracks_df)
    mappings = detection['column_mappings']
    staff_col_prefs = mappings['staff_col_prefs']
    staff_col_tracks = mappings.get('staff_col_tracks')
    role_col = mappings['role_col']
    # The bid cycle's day schema comes from Preassignments.xlsx (the file authored
    # per bid cycle), not from Tracks.xlsx (last cycle's active roster) — Tracks.xlsx
    # is still used below only as reference data (capacity/options + "Your Active
    # Track" comparison), never as the source of which day columns exist.
    days = _get_preassignment_day_columns(excel_files['preassignments'])
    no_matrix_col = mappings.get('no_matrix_col')
    reduced_rest_col = mappings.get('reduced_rest_col')
    seniority_col = mappings.get('seniority_col')

    if not staff_col_prefs or not days:
        return None, "Could not detect required columns."

    staff_names = sorted(preferences_df[staff_col_prefs].dropna().unique().tolist())

    role_mapping = {}
    seniority_mapping = {}
    no_matrix_mapping = {}
    for _, row in preferences_df.iterrows():
        name = row.get(staff_col_prefs)
        if pd.notna(name):
            name = str(name).strip()
            if role_col:
                role_mapping[name] = row.get(role_col, 'Unknown')
            if seniority_col:
                seniority_val = row.get(seniority_col)
                try:
                    seniority_mapping[name] = int(seniority_val)
                except (TypeError, ValueError):
                    seniority_mapping[name] = seniority_val
            if no_matrix_col:
                try:
                    no_matrix_mapping[name] = int(row.get(no_matrix_col)) == 1
                except (TypeError, ValueError):
                    no_matrix_mapping[name] = False

    return {
        'preferences_df': preferences_df,
        'current_tracks_df': current_tracks_df,
        'requirements_df': requirements_df,
        'preassignment_df': preassignment_df,
        'days': days,
        'staff_col_prefs': staff_col_prefs,
        'staff_col_tracks': staff_col_tracks,
        'role_col': role_col,
        'no_matrix_col': no_matrix_col,
        'reduced_rest_col': reduced_rest_col,
        'seniority_col': seniority_col,
        'staff_names': staff_names,
        'role_mapping': role_mapping,
        'seniority_mapping': seniority_mapping,
        'no_matrix_mapping': no_matrix_mapping,
    }, None


# ──────────────────────────────────────────────
# Automatic Bid Access & Notification — when enabled for a track cycle, submitting a
# bid grants bid access to the next staff member in seniority rank order (same role)
# and emails them that their bid is now open, instead of an admin doing it by hand.
# ──────────────────────────────────────────────

def _load_requirements_map(requirements_df):
    """
    Parse Requirements.xlsx into {staff_name: {shifts_per_pay_period, night_minimum,
    weekend_minimum, weekend_group, email}}.

    Column layout is positional (STAFF NAME, SHIFTS PER PAY PERIOD, NIGHT MINIMUM,
    WEEKEND MINIMUM, WEEKEND GROUP, EMAIL), matching the per-staff parsing in
    _display_bidding_staff_interface. Staff with a blank SHIFTS PER PAY PERIOD are
    management who don't bid on tracks — shifts_per_pay_period stays None for them,
    which is what callers use to exclude them from the bidding roster.
    """
    result = {}
    if requirements_df is None or requirements_df.empty:
        return result

    cols = requirements_df.columns
    name_col = cols[0]
    for _, row in requirements_df.iterrows():
        name = row.get(name_col)
        if pd.isna(name):
            continue
        name = str(name).strip()

        entry = {
            'shifts_per_pay_period': None,
            'night_minimum': None,
            'weekend_minimum': None,
            'weekend_group': None,
            'email': None,
        }
        if len(cols) >= 2 and pd.notna(row.iloc[1]):
            entry['shifts_per_pay_period'] = int(float(row.iloc[1]))
        if len(cols) >= 3 and pd.notna(row.iloc[2]):
            entry['night_minimum'] = int(float(row.iloc[2]))
        if len(cols) >= 4 and pd.notna(row.iloc[3]):
            entry['weekend_minimum'] = int(float(row.iloc[3]))
        if len(cols) >= 5 and pd.notna(row.iloc[4]):
            wg = str(row.iloc[4]).strip().upper()
            if wg in ['A', 'B', 'C', 'D', 'E']:
                entry['weekend_group'] = wg
        if len(cols) >= 6 and pd.notna(row.iloc[5]):
            email = str(row.iloc[5]).strip()
            if email:
                entry['email'] = email

        result[name] = entry
    return result


def _bidding_role_bucket(role):
    """Collapse a raw role string to 'medic' or 'nurse' (nurse bucket includes dual) —
    mirrors the Nurse/Medic split used by the Manage Bid Access tables."""
    return 'medic' if str(role).strip().lower() == 'medic' else 'nurse'


def _ordered_bidding_roster(staff_names, role_mapping, seniority_mapping, requirements_map, bucket):
    """
    Seniority-ascending (most senior first) list of staff in one role bucket ('nurse'
    or 'medic'), excluding anyone with no SHIFTS PER PAY PERIOD on file in
    Requirements.xlsx — those are management/non-bidding staff and are skipped.
    """
    def _seniority_key(name):
        try:
            return (0, float(seniority_mapping.get(name)))
        except (TypeError, ValueError):
            return (1, 0)

    eligible = [
        name for name in staff_names
        if _bidding_role_bucket(role_mapping.get(name, '')) == bucket
        and requirements_map.get(name, {}).get('shifts_per_pay_period') is not None
    ]
    return sorted(eligible, key=_seniority_key)


def _next_staff_in_rank(staff_name, staff_names, role_mapping, seniority_mapping, requirements_map):
    """Return the next staff member after staff_name in seniority rank order within
    staff_name's own role bucket (nurse incl. dual, or medic), or None if staff_name
    is last in that bucket, isn't in it (e.g. management), or the bucket is empty."""
    bucket = _bidding_role_bucket(role_mapping.get(staff_name, ''))
    roster = _ordered_bidding_roster(staff_names, role_mapping, seniority_mapping, requirements_map, bucket)
    if staff_name not in roster:
        return None
    idx = roster.index(staff_name)
    if idx + 1 < len(roster):
        return roster[idx + 1]
    return None


def _run_auto_bid_progression(staff_name, bid_track_name):
    """
    After staff_name's bid is saved, if automatic bid access & notification is turned
    on for bid_track_name: find the next staff member in seniority rank order (same
    role bucket), grant them bid access, and email them (+ admins) that their bid is
    open. If that staff member has no email on file, access is left untouched and the
    admins are emailed to enable/notify manually instead.

    Every outcome reached after the feature-enabled check is written to the
    bid_progression_log table (Manage Bid Access tab's notification log), whether or
    not an email actually went out.

    Returns:
        tuple (level, message) for display next to the existing bid-submission notice
        — level is one of 'success', 'warning', 'info' — or None if the feature is off.
    """
    cfg = get_track_config_by_name(bid_track_name)
    if not cfg or not cfg.get('auto_bid_progression'):
        return None

    def _log(next_staff, level, message, notified_email=None):
        log_bid_progression_event(bid_track_name, staff_name, next_staff, level, message, notified_email)
        return (level, message)

    try:
        ctx, roster_error = _load_bidding_data_files()
        if ctx is None:
            return _log(None, "warning", f"Automatic bid progression could not load roster data: {roster_error}")

        requirements_map = _load_requirements_map(ctx['requirements_df'])
        next_staff = _next_staff_in_rank(
            staff_name, ctx['staff_names'], ctx['role_mapping'], ctx['seniority_mapping'], requirements_map
        )
        if not next_staff:
            return _log(None, "info",
                        f"{staff_name} is last in seniority rank order — no next staff member to advance to.")

        next_requirements = requirements_map.get(next_staff, {})
        next_email = next_requirements.get('email')

        from modules.email_notifications import send_bid_access_opened_notification, send_missing_bidder_email_alert

        if not next_email:
            alert_ok, alert_msg = send_missing_bidder_email_alert(next_staff, bid_track_name)
            note = ("Admins have been emailed to enable access and notify them manually."
                    if alert_ok else f"The admin alert email also failed to send: {alert_msg}")
            return _log(next_staff, "warning",
                        f"{next_staff} is next in rank, but has no email on file in Requirements.xlsx — "
                        f"bid access was NOT automatically enabled. {note}")

        ok, _ = set_bid_access(next_staff, bid_track_name, True)
        if not ok:
            return _log(next_staff, "warning", f"{next_staff} is next in rank, but enabling their bid access failed.")

        sent_ok, sent_msg = send_bid_access_opened_notification(
            next_staff, next_email, bid_track_name, next_requirements)
        if sent_ok:
            return _log(next_staff, "success",
                        f"Bid access enabled for {next_staff} (next in rank) and notified at {next_email}.",
                        notified_email=next_email)
        else:
            return _log(next_staff, "warning",
                        f"Bid access enabled for {next_staff}, but the notification email failed: {sent_msg}")
    except Exception as e:
        return _log(None, "warning", f"Automatic bid progression failed unexpectedly: {e}")


def _send_manual_bid_notification(staff_name, manual_email, bid_track_name):
    """
    Admin-triggered "your bid is open" notification, for the fallback case where
    automatic progression couldn't send one itself (no email on file) or an admin
    otherwise wants to notify someone by hand.

    Unlike the automatic cascade, the recipient address is whatever the admin types
    in — never looked up from Requirements.xlsx — and bid access is left untouched
    (use Toggle Access below for that). Always logged, with trigger_type='manual' so
    it's distinguishable from automatic events in the notification log.

    Returns:
        tuple (level, message) — level is 'success' or 'warning'.
    """
    manual_email = (manual_email or "").strip()
    if not manual_email:
        return ("warning", "Enter an email address before sending.")

    ctx, _ = _load_bidding_data_files()
    requirements = {}
    if ctx is not None:
        requirements = _load_requirements_map(ctx['requirements_df']).get(staff_name, {})

    from modules.email_notifications import send_bid_access_opened_notification
    sent_ok, sent_msg = send_bid_access_opened_notification(staff_name, manual_email, bid_track_name, requirements)

    level = "success" if sent_ok else "warning"
    message = (f"Manually notified {staff_name} at {manual_email}."
               if sent_ok else f"Manual notification to {staff_name} at {manual_email} failed: {sent_msg}")
    log_bid_progression_event(
        bid_track_name, "Manual Send", staff_name, level, message,
        notified_email=manual_email if sent_ok else None, trigger_type='manual'
    )
    return (level, message)


# ──────────────────────────────────────────────
# Bid Analysis tab — per-day Nurse/Medic/Dual/Senior demand from submitted bids,
# mirroring the FY26 Track Analysis workbook's manual roll-up.
# ──────────────────────────────────────────────

# Categorical hues validated with the dataviz skill's palette checker
# (node scripts/validate_palette.js) — keep any new series color in that set.
_ROLE_COLORS = {'Nurse': '#2a78d6', 'Medic': '#1baf7a', 'Dual': '#eda100'}
_PERIOD_COLORS = {'Day': '#2a78d6', 'Night': '#4a3aa7'}
_SHIFT_COLORS = {'D': '#2a78d6', 'N': '#4a3aa7', 'AT': '#898781', 'Off': '#f0efec'}


def _bid_role_and_senior(bid, role_mapping, no_matrix_mapping):
    """Resolve (effective role string, is_senior bool) for one submitted bid."""
    name = bid['staff_name']
    role = role_mapping.get(name)
    if not role or str(role).strip().lower() == 'unknown':
        role = (bid.get('metadata') or {}).get('original_role') or 'nurse'
    role = str(role).strip().lower()
    is_senior = bool(no_matrix_mapping.get(name))
    return role, is_senior


def _max_possible_shifts(nurse_n, medic_n, dual_n, senior_n):
    """
    Largest number of complete Nurse+Medic crews that day's bidders could staff.

    Dual-credentialed staff (already counted in nurse_n) can flex to the medic
    side; this tries every split and keeps the best pairing, then caps the
    result at how many no-matrix/senior staff bid that day. Direct translation
    of the LET() formula in rows 99/104 of the FY26 Track Analysis workbook.
    """
    best = max(min(nurse_n - x, medic_n + x) for x in range(dual_n + 1))
    return max(0, min(senior_n, best))


def _compute_bid_day_stats(days, bids, role_mapping, no_matrix_mapping):
    """One row per bid day with Nurse/Medic/Dual/Senior counts and Max Shifts, Day and Night."""
    resolved = [(_bid_role_and_senior(b, role_mapping, no_matrix_mapping), b) for b in bids]

    rows = []
    for i, day in enumerate(days, start=1):
        counts = {'day_label': day, 'day_index': i, 'weekday': day.split(' ')[0]}
        for period, code in (('day', 'D'), ('night', 'N')):
            nurse = medic = dual = senior = 0
            for (role, is_senior), b in resolved:
                if (b['track_data'] or {}).get(day) != code:
                    continue
                if role == 'medic':
                    medic += 1
                else:
                    nurse += 1
                    if role == 'dual':
                        dual += 1
                if is_senior:
                    senior += 1
            counts[f'{period}_nurse'] = nurse
            counts[f'{period}_medic'] = medic
            counts[f'{period}_dual'] = dual
            counts[f'{period}_senior'] = senior
            counts[f'{period}_max_shifts'] = _max_possible_shifts(nurse, medic, dual, senior)
        rows.append(counts)
    return pd.DataFrame(rows)


def _build_bid_heatmap(days, bids, role_mapping, no_matrix_mapping):
    """Staff x day grid (nurses A-Z, then medics A-Z) colored by submitted shift code."""
    role_of = {}
    for b in bids:
        role, _ = _bid_role_and_senior(b, role_mapping, no_matrix_mapping)
        role_of[b['staff_name']] = role
    staff_order = sorted(role_of.keys(), key=lambda n: (0 if role_of[n] != 'medic' else 1, n))

    rows = []
    for b in bids:
        name = b['staff_name']
        td = b['track_data'] or {}
        for day in days:
            code = td.get(day) or ''
            code = code if code in ('D', 'N', 'AT') else 'Off'
            rows.append({'staff': name, 'role': role_of[name], 'day_label': day, 'shift': code})
    df = pd.DataFrame(rows)

    color_scale = alt.Scale(domain=list(_SHIFT_COLORS.keys()), range=list(_SHIFT_COLORS.values()))
    return alt.Chart(df).mark_rect().encode(
        x=alt.X('day_label:N', sort=days, title=None,
                axis=alt.Axis(labelAngle=-90, labelFontSize=8, labelOverlap=False)),
        y=alt.Y('staff:N', sort=staff_order, title=None, axis=alt.Axis(labelFontSize=9)),
        color=alt.Color('shift:N', scale=color_scale, legend=alt.Legend(title='Shift')),
        tooltip=[alt.Tooltip('staff:N', title='Staff'), alt.Tooltip('role:N', title='Role'),
                 alt.Tooltip('day_label:N', title='Day'), alt.Tooltip('shift:N', title='Shift')],
    ).properties(height=max(300, 15 * len(staff_order)))


def _build_composition_chart(day_stats, period):
    """Stacked bar of Nurse(non-dual)/Dual/Medic bid counts across the 42 days, one shift period."""
    prefix = 'day_' if period == 'Day' else 'night_'
    df = day_stats[['day_label', f'{prefix}nurse', f'{prefix}dual', f'{prefix}medic']].copy()
    df['Nurse'] = df[f'{prefix}nurse'] - df[f'{prefix}dual']
    df['Dual'] = df[f'{prefix}dual']
    df['Medic'] = df[f'{prefix}medic']
    long_df = df.melt(id_vars=['day_label'], value_vars=['Nurse', 'Dual', 'Medic'],
                       var_name='Category', value_name='Count')

    color_scale = alt.Scale(domain=list(_ROLE_COLORS.keys()), range=list(_ROLE_COLORS.values()))
    order = day_stats['day_label'].tolist()
    return alt.Chart(long_df).mark_bar().encode(
        x=alt.X('day_label:N', sort=order, title=None,
                axis=alt.Axis(labelAngle=-90, labelFontSize=8, labelOverlap=False)),
        y=alt.Y('Count:Q', title='Staff bidding'),
        color=alt.Color('Category:N', scale=color_scale, legend=alt.Legend(title=None)),
        order=alt.Order('Category:N'),
        tooltip=['day_label:N', 'Category:N', 'Count:Q'],
    ).properties(title=f'{period} Shift — Bid Composition', height=220)


def _build_demand_vs_cap_chart(day_stats, period, role):
    """One role's bid count vs. its configured cap, across the 42 days."""
    prefix = 'day_' if period == 'Day' else 'night_'
    cap_prefix = 'day_cap_' if period == 'Day' else 'night_cap_'
    field, cap_field = f'{prefix}{role.lower()}', f'{cap_prefix}{role.lower()}'
    hue = _ROLE_COLORS[role]
    order = day_stats['day_label'].tolist()
    df = day_stats[['day_label', field, cap_field]].rename(columns={field: 'Bids', cap_field: 'Cap'})

    bars = alt.Chart(df).mark_bar(color=hue).encode(
        x=alt.X('day_label:N', sort=order, title=None,
                axis=alt.Axis(labelAngle=-90, labelFontSize=7, labelOverlap=True)),
        y=alt.Y('Bids:Q', title='Staff bidding'),
        tooltip=[alt.Tooltip('day_label:N', title='Day'), alt.Tooltip('Bids:Q', title='Bids'),
                 alt.Tooltip('Cap:Q', title='Cap')],
    )
    cap_line = alt.Chart(df).mark_line(strokeDash=[4, 3], strokeWidth=2, color=hue).encode(
        x=alt.X('day_label:N', sort=order), y='Cap:Q',
    )
    return (bars + cap_line).properties(title=f'{period} · {role} (dashed = cap)', height=180)


def _build_max_shifts_chart(day_stats):
    """Max achievable Day/Night crews (see _max_possible_shifts) across the 42 days."""
    long_df = day_stats.melt(id_vars=['day_label'], value_vars=['day_max_shifts', 'night_max_shifts'],
                              var_name='Period', value_name='Max Crews')
    long_df['Period'] = long_df['Period'].map({'day_max_shifts': 'Day', 'night_max_shifts': 'Night'})

    color_scale = alt.Scale(domain=list(_PERIOD_COLORS.keys()), range=list(_PERIOD_COLORS.values()))
    order = day_stats['day_label'].tolist()
    return alt.Chart(long_df).mark_line(strokeWidth=2, point=True).encode(
        x=alt.X('day_label:N', sort=order, title=None,
                axis=alt.Axis(labelAngle=-90, labelFontSize=8, labelOverlap=False)),
        y=alt.Y('Max Crews:Q'),
        color=alt.Color('Period:N', scale=color_scale, legend=alt.Legend(title=None)),
        tooltip=['day_label:N', 'Period:N', 'Max Crews:Q'],
    ).properties(height=240)


def _build_bid_summary_table(day_stats):
    """Wide Max Shifts/Senior/Nurse/Dual/Medic x Day/Night table, days as columns (Excel-replica)."""
    idx = day_stats.set_index('day_label')
    row_order = [
        ('Max DAY Shifts', idx['day_max_shifts']),
        ('Day — Senior', idx['day_senior']),
        ('Day — Nurse', idx['day_nurse']),
        ('Day — Dual (counts as RN)', idx['day_dual']),
        ('Day — Medic', idx['day_medic']),
        ('Max NIGHT Shifts', idx['night_max_shifts']),
        ('Night — Senior', idx['night_senior']),
        ('Night — Nurse', idx['night_nurse']),
        ('Night — Dual (counts as RN)', idx['night_dual']),
        ('Night — Medic', idx['night_medic']),
    ]
    table = pd.DataFrame({label: series for label, series in row_order}).T
    table = table.reindex(columns=day_stats['day_label'].tolist())
    table.index.name = None
    return table


def _render_bid_analysis_tab(config_names, default_track_index):
    """Visual + tabular breakdown of submitted bids across the 42-day cycle, for tuning bid caps."""
    st.markdown("### Bid Analysis")

    if not config_names:
        st.info("No track cycles exist yet. Create one in the Track Configs tab.")
        return

    analysis_track = st.selectbox(
        "Track Cycle:", config_names, index=default_track_index, key="analysis_track_select")

    ctx, roster_error = _load_bidding_data_files()
    if ctx is None:
        st.error(roster_error)
        return

    ok, bids_raw = get_all_bid_tracks(analysis_track)
    bids = bids_raw if ok else []
    if not bids:
        st.info(f"No bids submitted yet for {analysis_track}.")
        return

    days = ctx['days']
    role_mapping = ctx['role_mapping']
    no_matrix_mapping = ctx['no_matrix_mapping']
    staff_names = ctx['staff_names']

    submitted_names = {b['staff_name'] for b in bids}
    missing = sorted(n for n in staff_names if n not in submitted_names)
    m1, m2 = st.columns(2)
    m1.metric("Bids Submitted", f"{len(bids)} / {len(staff_names)}")
    m2.metric("Roster Staff Missing a Bid", len(missing))
    if missing:
        with st.expander(f"{len(missing)} staff without a submitted bid"):
            st.write(", ".join(missing))
    st.caption("Figures below reflect submitted bids only, and will shift as more staff submit.")

    day_stats = _compute_bid_day_stats(days, bids, role_mapping, no_matrix_mapping)
    weekday_caps = get_track_capacity_by_weekday(analysis_track)
    for period, cap_key_prefix in (('day', 'max_day_'), ('night', 'max_night_')):
        for role in ('nurse', 'medic'):
            # get_track_capacity_by_weekday() keys are plural: max_day_nurses/max_day_medics/...
            day_stats[f'{period}_cap_{role}'] = day_stats['weekday'].map(
                lambda w: weekday_caps.get(w, {}).get(f'{cap_key_prefix}{role}s', 0))

    st.markdown("#### Where Staff Are Bidding")
    st.caption("One row per staff member (nurses A–Z, then medics A–Z), one column per bid day.")
    st.altair_chart(_build_bid_heatmap(days, bids, role_mapping, no_matrix_mapping), use_container_width=True)

    st.markdown("#### Bid Composition by Day")
    st.altair_chart(_build_composition_chart(day_stats, 'Day'), use_container_width=True)
    st.altair_chart(_build_composition_chart(day_stats, 'Night'), use_container_width=True)

    st.markdown("#### Bid Demand vs. Configured Cap")
    st.caption("Solid bars are submitted bids; the dashed line is the current cap. "
               "A bar above the dashed line means more staff bid than there's room for.")
    dcol1, dcol2 = st.columns(2)
    with dcol1:
        st.altair_chart(_build_demand_vs_cap_chart(day_stats, 'Day', 'Nurse'), use_container_width=True)
        st.altair_chart(_build_demand_vs_cap_chart(day_stats, 'Night', 'Nurse'), use_container_width=True)
    with dcol2:
        st.altair_chart(_build_demand_vs_cap_chart(day_stats, 'Day', 'Medic'), use_container_width=True)
        st.altair_chart(_build_demand_vs_cap_chart(day_stats, 'Night', 'Medic'), use_container_width=True)

    st.markdown("#### Maximum Achievable Crews per Day")
    st.caption("The most complete Nurse+Medic crews that day's bidders could staff — letting dual-credentialed "
               "staff flex to whichever side is short, capped by how many no-matrix/senior staff bid that day.")
    st.altair_chart(_build_max_shifts_chart(day_stats), use_container_width=True)

    with st.expander("Full Day/Night breakdown table (Max Shifts / Senior / Nurse / Dual / Medic)"):
        st.dataframe(_build_bid_summary_table(day_stats), use_container_width=True)


# ──────────────────────────────────────────────
# Admin mode toggle (small sidebar gate) + full-page admin dashboard
# ──────────────────────────────────────────────

def _render_admin_mode_toggle():
    """Render the sidebar password gate that flips the page into full admin mode."""
    if 'track_bidding_admin_mode' not in st.session_state:
        st.session_state.track_bidding_admin_mode = False

    with st.sidebar:
        st.markdown("## Track Bidding Admin")
        password = st.text_input("Enter admin password:", type="password", key="bid_admin_pw")

        if check_admin_access(password) and not st.session_state.track_bidding_admin_mode:
            if st.button("🔧 Enter Admin Mode", key="bid_enter_admin_mode", use_container_width=True):
                st.session_state.track_bidding_admin_mode = True
                st.rerun()

        if st.session_state.track_bidding_admin_mode:
            st.success("✅ Admin Mode Active")
            if st.button("👤 Switch to Staff View", key="bid_exit_admin_mode", use_container_width=True):
                st.session_state.track_bidding_admin_mode = False
                st.rerun()


def display_bidding_admin_interface():
    """Full-page Track Bidding admin dashboard (mirrors the Summer Leave admin page)."""
    st.header("🔧 Track Bidding Administration")
    st.markdown("---")

    all_configs = get_all_track_configs()
    bid_cfg = get_bidding_track_config()
    config_names = [c['track_name'] for c in all_configs]
    default_track_index = (
        config_names.index(bid_cfg['track_name'])
        if bid_cfg and bid_cfg['track_name'] in config_names else 0
    )

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Overview", "🛠️ Track Configs", "👥 Manage Bid Access", "➕ Add/Remove Selection", "📈 Bid Analysis"
    ])

    # ── Tab 1: Overview ──
    with tab1:
        st.markdown("### Bid Tracks Summary")

        if not all_configs:
            st.info("No track cycles exist yet. Create one in the Track Configs tab.")
        else:
            stats_rows = []
            for cfg in all_configs:
                tn = cfg['track_name']
                ok, bids = get_all_bid_tracks(tn)
                bid_count = len(bids) if ok else 0
                access_count = sum(1 for v in get_all_bid_access_configs(tn).values() if v)
                status = 'Active' if cfg['is_active'] else ('Bidding Open' if cfg['is_bidding_open'] else 'Inactive')
                stats_rows.append({
                    'Track': tn,
                    'Status': status,
                    'Bids Submitted': bid_count,
                    'Staff w/ Access Enabled': access_count,
                    'Max Day Nurses': cfg['max_day_nurses'],
                    'Max Day Medics': cfg['max_day_medics'],
                    'Max Night Nurses': cfg['max_night_nurses'],
                    'Max Night Medics': cfg['max_night_medics'],
                })
            st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("### Bids by Track")
            for cfg in all_configs:
                tn = cfg['track_name']
                ok, bids = get_all_bid_tracks(tn)
                bids = bids if ok else []
                if bids:
                    with st.expander(f"📅 {tn} ({len(bids)} bids submitted)"):
                        for b in bids:
                            role = b['metadata'].get('effective_role', '?')
                            st.markdown(f"- {b['staff_name']} (v{b['version']}, {role}, submitted {b['submission_date']})")

    # ── Tab 2: Track Configs ──
    with tab2:
        # ── Section 1: create a new bid track ──
        st.markdown("### Create New Bid Track")
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

        if not all_configs:
            st.info("No track configs yet.")

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

                # Bid count (individual bids are managed in the Add/Remove Selection tab)
                st.markdown("---")
                bid_tracks_result = get_all_bid_tracks(tn)
                bid_list = bid_tracks_result[1] if bid_tracks_result[0] else []
                bid_count = len(bid_list) if isinstance(bid_list, list) else 0
                st.markdown(f"**Bids submitted:** {bid_count}")
                st.caption("Manage individual bids in the Add/Remove Selection tab.")

                if bid_count > 0:
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

    # ── Tab 3: Manage Bid Access ──
    with tab3:
        st.markdown("### Manage Bid Access")

        if not config_names:
            st.info("No track cycles exist yet. Create one in the Track Configs tab.")
        else:
            access_track = st.selectbox(
                "Track Cycle:", config_names, index=default_track_index, key="access_track_select")

            ctx, roster_error = _load_bidding_data_files()
            if ctx is None:
                st.error(roster_error)
            else:
                staff_names = ctx['staff_names']
                role_mapping = ctx['role_mapping']
                seniority_mapping = ctx['seniority_mapping']
                access_configs = get_all_bid_access_configs(access_track)
                ok, bids = get_all_bid_tracks(access_track)
                bids_lookup = {b['staff_name']: b for b in bids} if ok else {}

                staff_data = []
                for staff_name in staff_names:
                    role = role_mapping.get(staff_name, 'Unknown')
                    seniority = seniority_mapping.get(staff_name, '')
                    access = access_configs.get(staff_name, False)
                    bid = bids_lookup.get(staff_name)
                    staff_data.append({
                        'Staff Name': staff_name,
                        'Role': role,
                        'Seniority': seniority,
                        'Bid Access': '✅' if access else '❌',
                        'Has Bid': '✅' if bid else '❌',
                        'Version': bid['version'] if bid else '',
                        'Submitted': bid['submission_date'] if bid else '',
                    })

                def _seniority_key(row):
                    # Most-senior-first; blank/non-numeric seniority sorts last.
                    try:
                        return (0, float(row['Seniority']))
                    except (TypeError, ValueError):
                        return (1, 0)

                display_cols = ['Staff Name', 'Seniority', 'Bid Access', 'Has Bid', 'Version', 'Submitted']
                nurse_data = sorted(
                    (d for d in staff_data if str(d['Role']).strip().lower() != 'medic'),
                    key=_seniority_key)
                medic_data = sorted(
                    (d for d in staff_data if str(d['Role']).strip().lower() == 'medic'),
                    key=_seniority_key)

                col_nurse, col_medic = st.columns(2)
                with col_nurse:
                    st.markdown(f"##### Nurses ({len(nurse_data)})")
                    st.dataframe(
                        pd.DataFrame(nurse_data, columns=display_cols),
                        use_container_width=True, hide_index=True)
                with col_medic:
                    st.markdown(f"##### Medics ({len(medic_data)})")
                    st.dataframe(
                        pd.DataFrame(medic_data, columns=display_cols),
                        use_container_width=True, hide_index=True)

                st.markdown("---")
                st.markdown("### Automatic Bid Access & Notification")
                st.caption(
                    "When enabled, submitting a bid automatically grants bid access to the next "
                    "staff member in seniority rank order (same role — Nurse/Dual or Medic) and "
                    "emails them that their bid is now open, along with the admins. Staff with a "
                    "blank **SHIFTS PER PAY PERIOD** in Requirements.xlsx are management, not "
                    "bidding on tracks, and are skipped."
                )
                track_cfg = get_track_config_by_name(access_track)
                auto_progression_on = bool(track_cfg.get('auto_bid_progression')) if track_cfg else False
                new_auto_progression_on = st.checkbox(
                    f"Enable automatic bid access & notification for {access_track}",
                    value=auto_progression_on, key=f"auto_progression_{access_track}")
                if new_auto_progression_on != auto_progression_on:
                    update_track_config(access_track, auto_bid_progression=1 if new_auto_progression_on else 0)
                    st.rerun()

                st.markdown("##### Manually Send Bid Notification")
                st.caption(
                    "Send the \"your bid is open\" notification to a specific staff member right "
                    "now, using an email address you enter below (not looked up from "
                    "Requirements.xlsx). This does not change their bid access — use "
                    "**Toggle Access** below for that."
                )
                manual_col1, manual_col2 = st.columns(2)
                with manual_col1:
                    manual_notify_staff = st.selectbox(
                        "Staff Member:", staff_names, key=f"manual_notify_staff_{access_track}")
                with manual_col2:
                    manual_notify_email = st.text_input(
                        "Send to email:", key=f"manual_notify_email_{access_track}",
                        placeholder="name@example.com")
                if st.button("Send Notification", key=f"manual_notify_send_{access_track}"):
                    level, message = _send_manual_bid_notification(
                        manual_notify_staff, manual_notify_email, access_track)
                    (st.success if level == "success" else st.warning)(message)

                st.markdown("##### Notification Log")
                progression_log = get_bid_progression_log(access_track, limit=100)
                if not progression_log:
                    st.caption(f"No bid-progression events yet for {access_track}.")
                else:
                    level_icon = {'success': '✅', 'warning': '⚠️', 'info': 'ℹ️'}
                    trigger_label = {'auto': 'Auto', 'manual': 'Manual'}
                    log_rows = [{
                        'Date/Time': entry['event_date'],
                        'Trigger': trigger_label.get(entry.get('trigger_type'), 'Auto'),
                        'Status': f"{level_icon.get(entry['level'], '')} {entry['level'].title()}".strip(),
                        'Submitted By': entry['submitted_by'],
                        'Next Staff': entry['next_staff'] or '—',
                        'Notified Email': entry['notified_email'] or '—',
                        'Details': entry['message'],
                    } for entry in progression_log]
                    st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)
                    st.caption(f"Showing the {len(progression_log)} most recent event(s) for {access_track}.")

                st.markdown("---")
                st.markdown("### Toggle Access")

                selected_staff_access = st.selectbox(
                    "Select Staff Member:", staff_names, key="toggle_access_staff")

                if selected_staff_access:
                    current_status = access_configs.get(selected_staff_access, False)
                    staff_role = role_mapping.get(selected_staff_access, 'Unknown')

                    st.info(f"**{selected_staff_access}** ({staff_role}) - Bid Access: "
                            f"**{'Yes' if current_status else 'No'}**")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✅ Enable Bid Access", key="enable_access_btn", use_container_width=True):
                            ok, msg = set_bid_access(selected_staff_access, access_track, True)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                    with col2:
                        if st.button("❌ Disable Bid Access", key="disable_access_btn", use_container_width=True):
                            ok, msg = set_bid_access(selected_staff_access, access_track, False)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

                # Bulk enable/disable
                st.markdown("---")
                st.markdown("### Bulk Operations")

                col3, col4 = st.columns(2)
                with col3:
                    if st.button("✅ Enable All Staff", key="enable_all_access_btn", use_container_width=True):
                        count = 0
                        for staff in staff_names:
                            ok, _ = set_bid_access(staff, access_track, True)
                            if ok:
                                count += 1
                        st.success(f"Enabled bid access for {count} staff members")
                        st.rerun()

                with col4:
                    if st.button("❌ Disable All Staff", key="disable_all_access_btn", use_container_width=True):
                        count = 0
                        for staff in staff_names:
                            ok, _ = set_bid_access(staff, access_track, False)
                            if ok:
                                count += 1
                        st.success(f"Disabled bid access for {count} staff members")
                        st.rerun()

    # ── Tab 4: Add/Remove Selection ──
    with tab4:
        st.markdown("### Add or Remove Selection")

        if not config_names:
            st.info("No track cycles exist yet. Create one in the Track Configs tab.")
        else:
            sel_track = st.selectbox(
                "Track Cycle:", config_names, index=default_track_index, key="admin_sel_track")

            ctx, roster_error = _load_bidding_data_files()
            if ctx is None:
                st.error(roster_error)
            else:
                staff_names = ctx['staff_names']
                role_mapping = ctx['role_mapping']

                admin_selected_staff = st.selectbox(
                    "Select Staff Member:", staff_names, key="admin_staff_select_bid")

                if admin_selected_staff:
                    staff_role = role_mapping.get(admin_selected_staff, 'Unknown')
                    st.info(f"**{admin_selected_staff}** ({staff_role})")

                    bid_result = get_bid_track_from_db(admin_selected_staff, sel_track)
                    has_bid = bid_result[0]

                    if has_bid:
                        b = bid_result[1]
                        st.success(f"Current bid: version {b['version']}, submitted {b['submission_date']}")

                        from modules.track_management.display import display_schedule_by_blocks
                        with st.expander("View submitted schedule"):
                            display_schedule_by_blocks(b['track_data'], ctx['days'], {})

                        if st.button("❌ Remove This Selection", key="remove_bid_btn"):
                            st.session_state['confirm_remove_bid'] = True

                        if st.session_state.get('confirm_remove_bid', False):
                            st.warning(f"Delete bid for **{admin_selected_staff}**? This cannot be undone.")
                            rc1, rc2 = st.columns(2)
                            with rc1:
                                if st.button("Yes, Delete", key="confirm_remove_bid_yes"):
                                    ok, msg = delete_bid(admin_selected_staff, sel_track)
                                    st.session_state['confirm_remove_bid'] = False
                                    if ok:
                                        st.success(msg)
                                    else:
                                        st.error(msg)
                                    st.rerun()
                            with rc2:
                                if st.button("Cancel", key="confirm_remove_bid_no"):
                                    st.session_state['confirm_remove_bid'] = False
                                    st.rerun()
                    else:
                        st.info(f"{admin_selected_staff} has not submitted a bid for {sel_track} yet.")

                    st.markdown("---")
                    st.markdown("### Add/Update Selection")
                    st.caption(
                        "Builds or edits a bid on this staff member's behalf using the same editor "
                        "staff use — Track Selection, Validation, and Submission included. Unlike the "
                        "staff-facing view, this never locks: saving here always creates a new version."
                    )

                    # The full editor re-runs schedule-competition calculations, which are expensive.
                    # Streamlit re-executes every tab's code on any admin-dashboard interaction, so the
                    # editor is gated behind an explicit open/close action — otherwise every click on
                    # Overview/Track Configs/Manage Bid Access would silently pay for recomputing it too.
                    editor_key = f'show_admin_bid_editor_{sel_track}_{admin_selected_staff}'
                    if not st.session_state.get(editor_key, False):
                        if st.button(f"📝 Open Bid Editor for {admin_selected_staff}",
                                     key="open_admin_editor_btn", type="primary", use_container_width=True):
                            st.session_state[editor_key] = True
                            st.rerun()
                    else:
                        if st.button("Close Editor", key="close_admin_editor_btn"):
                            st.session_state[editor_key] = False
                            st.rerun()

                        cap_for_track = get_track_capacity(sel_track)
                        st.session_state['preferences_df'] = ctx['preferences_df']
                        st.session_state['staff_col_prefs'] = ctx['staff_col_prefs']
                        st.session_state['role_col'] = ctx['role_col']

                        _display_bidding_staff_interface(
                            admin_selected_staff, ctx['preferences_df'], ctx['current_tracks_df'], ctx['requirements_df'],
                            ctx['days'], ctx['staff_col_prefs'], ctx['staff_col_tracks'], ctx['role_col'],
                            ctx['no_matrix_col'], ctx['reduced_rest_col'], ctx['seniority_col'],
                            ctx['preassignment_df'], sel_track, cap_for_track, is_admin=True
                        )

    # ── Tab 5: Bid Analysis ──
    with tab5:
        _render_bid_analysis_tab(config_names, default_track_index)


# ──────────────────────────────────────────────
# Main bidding page (staff-facing)
# ──────────────────────────────────────────────

def _render_bidding_instructions():
    """
    Full step-by-step bidding walkthrough, shown at the top of the staff-facing
    Track Bidding page. This is the page the "bid access opened" notification
    email points to ("Detailed instructions are found linked at the top in the
    Track Bidding module.") — keep the tab names/emoji below in sync with the
    tab_labels in _display_bidding_staff_interface if those ever change.
    """
    with st.expander("📖 **Bidding Instructions — click to view the full step-by-step guide**"):
        st.markdown("""
1. **Select your name** from the dropdown to begin. The page will show the maximum staffing capacities (per day/night), your individual shift requirements based on years of service per the CBA, and a snapshot of your current active track for reference.

2. **Make sure your base preferences (rankings) are up to date before bidding.** No preferences entered means the system doesn't know where you want to work.
   - Check your **⚙️ Preferences** tab and, if needed, update them in **🛠️ Edit Preferences**.
   - Each base gets a 1-5 ranking for DAYS and a 1-3 ranking for NIGHTS (1 = first choice, most desired).
   - Confirm your current Zip Code (where you commute from), and choose whether to enroll in:
     - **Reduced Rest OK** — pre-approve getting scheduled for 10 hours between shifts when needed, to increase the likelihood of a shift at your preferred base.
     - **N to D Flex** — when drafting a schedule, do you want to be flexed to a DAY shift on the same date instead of a track NIGHT shift when staffing needs allow it? Includes a "Maybe" option where schedulers will ask first, but this might limit availability.

3. **Go to 🔄 Track Selection to begin bidding.**
   - The schedule tracks follow a 6-week rotation, with 3 pay periods (Blocks A, B, C) and corresponding week numbers (e.g. "Wed B4" = Block B, the second Wednesday of that pay period, which is the 4th week of the 6-week track).
   - If your role gets AT days, those are already pre-assigned to align with your position's scheduling needs and are built into your track as day shifts. Unlike a Night shift, which needs 2 days off before another day shift, only 1 day off is required after a Night → AT.

4. **Fill in Track Selection, one block/week at a time.**
   - Days highlighted in green are where your role is currently needed; a "Day Need" or "Night Need" count and a hypothetical base assignment appear under each day as a preview.
   - Select **"🔍 Validate and Save Block"** before moving on to the next block — this is important. This button sits between week 1 and week 2 of every block and stores your selections.

5. **Scheduler logic.** Under every day in Track Selection, and in full on the **🔮 Hypothetical Schedule** tab, CrewOps360 runs a live simulation of the upcoming competition: it sorts everyone bidding a given day/shift by seniority (nurses and medics separately — dual-trained staff compete as nurses), then hands out base seats one person at a time, most senior first, with each person getting their highest-ranked base that still has room.
   - **Choices disappear once a shift is full.** Each day/shift combination has a cap, shown in the header above. Once enough people have bid that shift to hit the cap, the D or N button for that day is dropped as an option.
   - **"Need exists but all named shifts are filled"** means all the named shifts are spoken for (ex. there are only 4 night shifts but the bid cap = 6). You can still take that D or N, but your location can't be accurately calculated — the beauty of the bid: do you value LOCATION or SCHEDULE?

6. **🔍 Validation tab.** Once all three blocks are filled, open Validation for a full pass against every rule, all in one place. Anything unmet is called out individually so you know exactly what to fix and where.

7. **📤 Submission.** Review the full six-week preview, then select **Submit Bid**. You'll have the option to download and/or email a PDF of your Bid Summary for your records — you can always come back and do this later.

8. **Communications.** We'll send a text message to notify you when it's your turn to bid, but we kindly ask that all schedule-related questions be sent via email to Matt, Aaron, and Jen. This helps consolidate responses, provide consistent information, and better manage communications when we're away from work.

Happy bidding!

~Charlie, Jen, Matt & Aaron
""")


def display_track_bidding():
    """Main entry point for the Track Bidding section."""
    st.markdown("")
    st.markdown("")

    if st.button("← Back to CrewOps360", key="back_from_bidding"):
        st.session_state.selected_module = None
        st.rerun()

    st.markdown("# Track Bidding")

    # Render admin sidebar (password gate -> full-page admin mode)
    _render_admin_mode_toggle()

    if st.session_state.get('track_bidding_admin_mode'):
        display_bidding_admin_interface()
        return

    _render_bidding_instructions()

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
    ctx, error = _load_bidding_data_files()
    if ctx is None:
        st.error(error)
        return

    st.markdown("---")
    selected_staff = st.selectbox("Select Your Name", [""] + ctx['staff_names'], key="bid_staff_select")

    if not selected_staff:
        st.info("Please select your name to begin.")
        return

    # Per-staff bidding access gate — mirrors Summer Leave's "LT Access" toggle.
    # Once an admin has locked this down, staff can't self-serve without being enabled.
    if not get_bid_access(selected_staff, bid_track_name):
        st.warning("⚠️ Bidding access is not available for you at this time.")
        st.info("Please contact your supervisor if you believe this is an error.")
        return

    # Store for submission access
    st.session_state['preferences_df'] = ctx['preferences_df']
    st.session_state['staff_col_prefs'] = ctx['staff_col_prefs']
    st.session_state['role_col'] = ctx['role_col']

    # Run the bidding staff interface
    _display_bidding_staff_interface(
        selected_staff, ctx['preferences_df'], ctx['current_tracks_df'], ctx['requirements_df'],
        ctx['days'], ctx['staff_col_prefs'], ctx['staff_col_tracks'], ctx['role_col'],
        ctx['no_matrix_col'], ctx['reduced_rest_col'], ctx['seniority_col'],
        ctx['preassignment_df'], bid_track_name, capacity, is_admin=False
    )


def _display_bidding_staff_interface(
    selected_staff, preferences_df, current_tracks_df, requirements_df,
    days, staff_col_prefs, staff_col_tracks, role_col,
    no_matrix_col, reduced_rest_col, seniority_col,
    preassignment_df, bid_track_name, capacity, is_admin=False
):
    """Render the tabbed bidding interface for a single staff member.

    When is_admin is True (called from the admin "Add/Update Selection" tab),
    the Submission tab never locks — an admin can always build or revise a bid
    on the selected staff member's behalf, regardless of what's already on file.
    """
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
    if is_admin:
        st.caption(f"🔧 Admin Mode — building/editing this bid on behalf of **{selected_staff}**.")

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
    st.caption("Clears your working selections below — does not delete a bid you've already submitted.")

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
            preferences_df, staff_col_prefs, role_col, is_admin=is_admin
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
    preferences_df, staff_col_prefs, role_col, is_admin=False
):
    """Handle bid submission.

    Once a bid exists in the database for a staff member, that staff member can no
    longer resubmit it themselves — the view becomes read-only (download/email the
    PDF only), matching Summer Leave's "contact your supervisor to make changes"
    lock. "Already submitted" is read straight from the database (not a per-session
    flag), so the lock holds even across a fresh browser session. Admins bypass the
    lock entirely (used by the Add/Update Selection admin tab) so they can build or
    revise a bid on a staff member's behalf.
    """
    from modules.enhanced_track_validator import validate_track_comprehensive
    from modules.pdf_generator import generate_bid_summary_pdf
    from modules.email_notifications import send_bid_submission_notification, send_bid_summary_email

    st.subheader(f"Submit Bid for {selected_staff}")

    existing = get_bid_track_from_db(selected_staff, bid_track_name)
    has_existing_bid = existing[0]

    admin_notice_key = f'bid_admin_notice_{bid_track_name}_{selected_staff}'
    progression_notice_key = f'bid_progression_notice_{bid_track_name}_{selected_staff}'
    email_result_key = f'bid_email_result_{bid_track_name}_{selected_staff}'

    # Shown regardless of admin/staff path or lock state, so both a staff member
    # submitting their own bid and an admin submitting on their behalf see the
    # outcome of the admin notification and the automatic bid-progression attempt.
    _notice_fn = {"success": st.success, "warning": st.warning, "info": st.info}
    if admin_notice_key in st.session_state:
        notice_type, notice_msg = st.session_state[admin_notice_key]
        _notice_fn.get(notice_type, st.warning)(notice_msg)
    if progression_notice_key in st.session_state:
        notice_type, notice_msg = st.session_state[progression_notice_key]
        _notice_fn.get(notice_type, st.warning)(notice_msg)

    if has_existing_bid and not is_admin:
        # Locked: staff can't resubmit once a bid is on file for this cycle.
        saved_bid = existing[1]
        st.success(
            f"Your bid for **{bid_track_name}** has been submitted "
            f"(version {saved_bid['version']}, submitted {saved_bid['submission_date']})."
        )
        st.info("This bid is locked. Please contact your supervisor if you need to make changes.")

        weekend_group = st.session_state.get('weekend_group')
        validation_result = validate_track_comprehensive(
            saved_bid['track_data'], shifts_per_pay_period, night_minimum,
            weekend_minimum, preassignments, days, weekend_group,
            staff_name=selected_staff
        )
        pdf_bytes, pdf_filename = generate_bid_summary_pdf(
            selected_staff, saved_bid['track_data'], days, bid_track_name,
            saved_bid['version'], saved_bid['submission_date'],
            shifts_per_pay_period, night_minimum, weekend_minimum,
            preassignments, validation_result, weekend_group
        )

        st.markdown("### Bid Summary PDF")
        dl_col, email_col = st.columns(2)

        with dl_col:
            st.download_button(
                "Download Bid Summary PDF", data=pdf_bytes, file_name=pdf_filename,
                mime="application/pdf", use_container_width=True,
                key=f"download_bid_pdf_{bid_track_name}_{selected_staff}"
            )

        with email_col:
            with st.form(key=f"bid_email_form_{bid_track_name}_{selected_staff}"):
                email_addr = st.text_input("Email this summary to:", placeholder="you@example.com")
                send_clicked = st.form_submit_button("Send PDF to Email", use_container_width=True)
            if send_clicked:
                send_ok, send_msg = send_bid_summary_email(
                    email_addr, selected_staff, bid_track_name, pdf_bytes, pdf_filename
                )
                st.session_state[email_result_key] = ("success", send_msg) if send_ok else ("error", send_msg)

            if email_result_key in st.session_state:
                result_type, result_msg = st.session_state[email_result_key]
                (st.success if result_type == "success" else st.error)(result_msg)
        return

    # ── Editable flow: no bid yet, or an admin building/revising one on staff's behalf ──
    if is_admin and has_existing_bid:
        saved_bid = existing[1]
        st.info(
            f"**{selected_staff}** already has a bid on file (version {saved_bid['version']}, "
            f"submitted {saved_bid['submission_date']}). Saving below will create version "
            f"{saved_bid['version'] + 1}."
        )
    elif is_admin:
        st.info(f"**{selected_staff}** has not submitted a bid yet. Building a new bid on their behalf.")
    else:
        st.info(f"Submitting bid for **{bid_track_name}**.")

    modified_track = st.session_state.track_changes.get(selected_staff, {})
    valid = st.session_state.modified_track.get('valid', False)

    if valid:
        st.success("This bid meets all requirements and is ready to submit.")
    else:
        st.error("This bid has validation issues. Please fix them in Track Selection before submitting.")

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

    if not valid:
        st.error("Cannot submit — fix validation issues first.")
        return

    button_label = "Update Bid" if (is_admin and has_existing_bid) else "Submit Bid"
    if st.button(button_label, use_container_width=True, type="primary",
                 key=f"submit_bid_{bid_track_name}_{selected_staff}"):
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
                # Notify the admin recipients with bid summary statistics (sent from the admin account)
                try:
                    bid_result = get_bid_track_from_db(selected_staff, bid_track_name)
                    if bid_result[0]:
                        saved_bid = bid_result[1]
                        weekend_group = st.session_state.get('weekend_group')
                        validation_result = validate_track_comprehensive(
                            saved_bid['track_data'], shifts_per_pay_period, night_minimum,
                            weekend_minimum, preassignments, days, weekend_group,
                            staff_name=selected_staff
                        )
                        admin_ok, admin_msg = send_bid_submission_notification(
                            selected_staff, bid_track_name, saved_bid['track_data'],
                            saved_bid['version'], saved_bid['submission_date'], validation_result
                        )
                        st.session_state[admin_notice_key] = ("success", admin_msg) if admin_ok else ("warning", admin_msg)
                except Exception as e:
                    st.session_state[admin_notice_key] = ("warning", f"Admin notification failed: {e}")

                # Automatic bid access & notification: hand bid access to the next
                # staff member in seniority rank order, if the feature is turned on.
                try:
                    progression_result = _run_auto_bid_progression(selected_staff, bid_track_name)
                    if progression_result:
                        st.session_state[progression_notice_key] = progression_result
                    else:
                        st.session_state.pop(progression_notice_key, None)
                except Exception as e:
                    st.session_state[progression_notice_key] = ("warning", f"Automatic bid progression failed: {e}")

                st.success(f"Bid saved successfully! {msg}")
                if not is_admin:
                    st.balloons()
                st.rerun()
            else:
                st.error(f"Error: {msg}")


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
