# modules/staffing_rebalance.py
"""
Staffing Rebalance — turns the Bid Analysis "Maximum Achievable Crews" chart into an
actionable report: for every below-minimum Day/Night shift in a track cycle, what crew
mix would close the gap, and who (within that same week, validly) could be asked to
move to cover it.

Read-only recommendations only — nothing here writes to the tracks table. An admin
reviews this, then makes the actual offer and applies the change by hand in the
existing Admin Track Editor.
"""

import io
from datetime import datetime

import streamlit as st
import pandas as pd

from modules.db_utils import (
    get_all_bid_tracks,
    get_bidding_track_config,
    get_track_config_by_name,
    get_base_shift_counts,
)
from modules.track_bidding import (
    _compute_bid_day_stats,
    _max_possible_shifts,
    _simulate_day_flex,
    _load_bidding_data_files,
    _load_requirements_map,
)


# ──────────────────────────────────────────────
# Pure logic — no Streamlit, no I/O beyond what's passed in. Kept separate from the
# render function so it can be exercised from a standalone script against a real DB.
# ──────────────────────────────────────────────

def _crew_deficit(nurse, medic, dual, senior, target):
    """
    Minimal extra (nurse, medic, senior) bodies needed so achievable crews
    (_max_possible_shifts) reach `target`, searching the same dual-split space
    _max_possible_shifts itself does. New bodies are assumed plain nurse/medic, not
    dual — Δsenior can be satisfied by any of them, it isn't a separate person.

    Returns None if already at/above target, else {'nurse': int, 'medic': int, 'senior': int}.
    """
    if _max_possible_shifts(nurse, medic, dual, senior) >= target:
        return None
    best = None
    for x in range(dual + 1):
        eff_nurse = nurse - x
        eff_medic = medic + x
        d_nurse = max(0, target - eff_nurse)
        d_medic = max(0, target - eff_medic)
        total = d_nurse + d_medic
        if best is None or total < best[0]:
            best = (total, d_nurse, d_medic)
    _, d_nurse, d_medic = best
    d_senior = max(0, target - senior)
    return {'nurse': d_nurse, 'medic': d_medic, 'senior': d_senior}


def _week_chunks(days):
    """42 canonical day labels -> six consecutive 7-day (Sun-Sat) weeks."""
    return [days[i:i + 7] for i in range(0, len(days), 7)]


def _build_roster_index(bids):
    """{(day_label, 'Day'|'Night'): [staff_name, ...]} from submitted bids' track_data."""
    index = {}
    for b in bids:
        for day, code in (b['track_data'] or {}).items():
            if code == 'D':
                index.setdefault((day, 'Day'), []).append(b['staff_name'])
            elif code == 'N':
                index.setdefault((day, 'Night'), []).append(b['staff_name'])
    return index


def find_shortfalls(days, day_stats, min_day, min_night, min_night_crews_for_sim):
    """
    Every below-minimum (day_label, period) triple, in three flavors:
      - Day, raw (no flex)
      - Day, after N-to-D flex simulation
      - Night (flex never lowers Night below the floor, so raw is the only case)

    Returns a list of dicts: day_label, period, mode ('raw'/'flex'/'night'), week
    (the 7-day list this day belongs to), achievable, deficit (from _crew_deficit,
    against the post-flex nurse/medic counts when mode='flex').
    """
    by_label = day_stats.set_index('day_label').to_dict('index')
    weeks = _week_chunks(days)
    week_of = {d: w for w in weeks for d in w}

    shortfalls = []
    for d in days:
        row = by_label[d]

        raw_day = row['day_max_shifts']
        if raw_day < min_day:
            deficit = _crew_deficit(row['day_nurse'], row['day_medic'], row['day_dual'],
                                     row['day_senior'], min_day)
            shortfalls.append({'day_label': d, 'period': 'Day', 'mode': 'raw',
                                'week': week_of[d], 'minimum': min_day,
                                'achievable': raw_day, 'deficit': deficit})

        sim = _simulate_day_flex(row['day_nurse'], row['day_medic'], row['day_dual'], row['day_senior'],
                                  row['night_nurse'], row['night_medic'], row['night_dual'], row['night_senior'],
                                  min_night_crews_for_sim)
        sim_day_max, _sim_night_max, _sac, sim_day_nurse, sim_day_medic, _sn, _sm = sim
        if sim_day_max < min_day:
            deficit = _crew_deficit(sim_day_nurse, sim_day_medic, row['day_dual'], row['day_senior'], min_day)
            shortfalls.append({'day_label': d, 'period': 'Day', 'mode': 'flex',
                                'week': week_of[d], 'minimum': min_day,
                                'achievable': sim_day_max, 'deficit': deficit})

        raw_night = row['night_max_shifts']
        if raw_night < min_night:
            deficit = _crew_deficit(row['night_nurse'], row['night_medic'], row['night_dual'],
                                     row['night_senior'], min_night)
            shortfalls.append({'day_label': d, 'period': 'Night', 'mode': 'night',
                                'week': week_of[d], 'minimum': min_night,
                                'achievable': raw_night, 'deficit': deficit})

    return shortfalls


def candidate_pool(shortfall, day_stats, roster_index, min_for_period):
    """
    {candidate_name: source_day} for a shortfall: staff working `period` on another
    day in the same week whose achievable crews for that period exceed the minimum
    (i.e. genuinely extra, not just "also scheduled"), who aren't scheduled at all
    (Day or Night) on the shortfall's own day.
    """
    target_day, period, week = shortfall['day_label'], shortfall['period'], shortfall['week']
    by_label = day_stats.set_index('day_label').to_dict('index')

    working_target_day = set(roster_index.get((target_day, 'Day'), [])) | \
        set(roster_index.get((target_day, 'Night'), []))

    candidates = {}
    for d in week:
        if d == target_day:
            continue
        row = by_label.get(d)
        if row is None:
            continue
        achievable = row['day_max_shifts'] if period == 'Day' else row['night_max_shifts']
        if achievable <= min_for_period:
            continue  # not actually extra on this day
        for name in roster_index.get((d, period), []):
            if name in working_target_day or name in candidates:
                continue
            candidates[name] = d
    return candidates


def validate_candidate_swap(name, source_day, target_day, period, bids_by_name, requirements_map,
                             preassignment_df, days):
    """
    Would name's own track still be valid if they swapped `source_day` for
    `target_day` (same period, net-zero shift count)? Returns the
    validate_track_comprehensive() result dict, or None if this candidate can't be
    evaluated (no bid on file, or no numeric requirements — e.g. management).
    """
    from modules.enhanced_track_validator import validate_track_comprehensive
    from modules.track_management.preassignment import get_staff_preassignments

    req = requirements_map.get(name)
    if not req or req.get('shifts_per_pay_period') is None:
        return None

    bid = bids_by_name.get(name)
    if not bid:
        return None

    code = 'D' if period == 'Day' else 'N'
    hypothetical = dict(bid['track_data'] or {})
    hypothetical[source_day] = ''
    hypothetical[target_day] = code

    preassignments = get_staff_preassignments(name, preassignment_df, days)

    return validate_track_comprehensive(
        hypothetical,
        shifts_per_pay_period=req.get('shifts_per_pay_period') or 0,
        night_minimum=req.get('night_minimum') or 0,
        weekend_minimum=req.get('weekend_minimum') or 0,
        preassignments=preassignments,
        days=days,
        weekend_group=req.get('weekend_group'),
    )


def rank_candidate(name, target_day, period, preferences_df, staff_col_prefs, role_col, seniority_col,
                    all_base_prefs, track_name, base_shift_counts):
    """
    What would name's hypothetical assignment be if they picked up `period` on
    `target_day`? Thin wrapper around the same seniority + base-preference
    competition simulator the app's own Hypothetical Schedule tab uses.
    """
    from modules.hypothetical_scheduler_new import calculate_hypothetical_assignment
    shift_type = 'day' if period == 'Day' else 'night'
    return calculate_hypothetical_assignment(
        name, target_day, shift_type, preferences_df, None,
        staff_col_prefs, None, role_col, seniority_col, True,
        all_base_prefs=all_base_prefs, bid_track_name=track_name, base_shift_counts=base_shift_counts,
    )


@st.cache_data(ttl=15, show_spinner=False)
def load_report_context(track_name):
    """
    Everything needed to compute shortfalls and, later, candidates for one track
    cycle. Loaded once per render (or once per standalone script run) and reused —
    each candidate lookup is cheap in-memory work after this.

    Cached for 15s: every one of the Track Bidding admin's tabs runs its full
    Python on every single interaction anywhere on the page — that's how
    st.tabs() works, it's not lazy about the hidden ones — and this function
    (loading every bid, recomputing day_stats for the full 42-day cycle) is
    the single most expensive shared step, called separately by Staffing
    Rebalance and (via load_swap_context) Needs Swap Requests. Anywhere that
    actually changes bid data clears this cache immediately after — see
    save_bid_track_to_db()'s callers and the approve/decline handlers in
    track_needs_swap.py — so it's never more than one real edit stale.

    Returns (context_dict, error_message). context_dict is None on failure.
    """
    from modules.hypothetical_scheduler_new import _load_all_base_preferences

    ctx, err = _load_bidding_data_files()
    if ctx is None:
        return None, err

    ok, bids = get_all_bid_tracks(track_name)
    if not ok:
        return None, f"No submitted bids found for {track_name}: {bids}"

    cfg = get_track_config_by_name(track_name) or {}
    min_day = cfg.get('min_day_staff') or 7
    min_night = cfg.get('min_night_staff') or 4

    days = ctx['days']
    day_stats = _compute_bid_day_stats(days, bids, ctx['role_mapping'], ctx['no_matrix_mapping'])

    return {
        'ctx': ctx,
        'bids': bids,
        'bids_by_name': {b['staff_name']: b for b in bids},
        'roster_index': _build_roster_index(bids),
        'day_stats': day_stats,
        'days': days,
        'min_day': min_day,
        'min_night': min_night,
        'requirements_map': _load_requirements_map(ctx['requirements_df']),
        'all_base_prefs': _load_all_base_preferences(),
        'base_shift_counts': get_base_shift_counts(track_name),
    }, None


def candidates_for_shortfall(shortfall, report_ctx, track_name):
    """
    Full candidate table for one shortfall: pool -> validate (filters out anyone
    whose swap would break their own track) -> rank (hypothetical assignment).
    Returns a list of dicts, most-senior/best-ranked first isn't guaranteed by this
    function — sort in the caller if a particular order is wanted.
    """
    ctx = report_ctx['ctx']
    min_for_period = report_ctx['min_day'] if shortfall['period'] == 'Day' else report_ctx['min_night']

    pool = candidate_pool(shortfall, report_ctx['day_stats'], report_ctx['roster_index'], min_for_period)

    rows = []
    for name, source_day in pool.items():
        validation = validate_candidate_swap(
            name, source_day, shortfall['day_label'], shortfall['period'],
            report_ctx['bids_by_name'], report_ctx['requirements_map'],
            ctx['preassignment_df'], report_ctx['days'],
        )
        if validation is None or not validation.get('overall_valid'):
            continue  # can't evaluate them, or the swap would break their own track

        hypo = rank_candidate(
            name, shortfall['day_label'], shortfall['period'],
            ctx['preferences_df'], ctx['staff_col_prefs'], ctx['role_col'], ctx['seniority_col'],
            report_ctx['all_base_prefs'], track_name, report_ctx['base_shift_counts'],
        )

        rows.append({
            'Name': name,
            'Role': ctx['role_mapping'].get(name, 'Unknown'),
            'Seniority': ctx['seniority_mapping'].get(name),
            'No Matrix': ctx['no_matrix_mapping'].get(name, False),
            'Currently extra on': source_day,
            'Would get a shift?': hypo['assignment'] is not None,
            'Hypothetical base': hypo['assignment'],
            'Base preference rank': hypo['preference_score'],
            'Competition rank': hypo.get('competition_rank'),
            'Competitors': hypo.get('total_competitors'),
            'Why': hypo['reason'],
        })
    return rows


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

def _format_shortfall_label(s):
    mode_label = {'raw': 'Day, no flex', 'flex': 'Day, with N-to-D flex', 'night': 'Night'}[s['mode']]
    return f"{s['day_label']} — {mode_label} — {s['achievable']}/{s['minimum']}"


def _format_deficit(deficit):
    if not deficit:
        return ""
    parts = [f"{deficit[k]} {k}" for k in ('nurse', 'medic', 'senior') if deficit[k]]
    return " + ".join(parts) if parts else "0 (senior cap only)"


def _safe_filename_part(text):
    return ''.join(c if c.isalnum() else '_' for c in text)


def _excel_download_button(df, label, file_prefix, key, sheet_name="Sheet1"):
    """'Download as Excel' button for a DataFrame — same ExcelWriter+download_button
    pattern as the Bid Analysis tab's Day/Night breakdown export."""
    from openpyxl.utils import get_column_letter
    from modules.track_bidding import _eastern_tz

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]
        for col_idx, col in enumerate(df.columns, start=1):
            content_width = int(df[col].astype(str).map(len).max()) if len(df) else 0
            ws.column_dimensions[get_column_letter(col_idx)].width = min(40, max(10, content_width + 2, len(str(col)) + 2))
    buffer.seek(0)

    st.download_button(
        label, data=buffer,
        file_name=f"{_safe_filename_part(file_prefix)}_{datetime.now(_eastern_tz).strftime('%Y%m%d%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )


def _render_staffing_rebalance_tab(config_names, default_track_index):
    st.markdown("### Staffing Rebalance")
    st.caption(
        "For every below-minimum Day/Night shift in a track cycle: the crew mix that would "
        "close the gap, and who — within that same week, and only if it wouldn't break their "
        "own track's validation rules — could be asked to move to cover it. Recommendations "
        "only; nothing here changes the schedule. To ask staff to volunteer for these same "
        "shifts instead of picking people yourself, open the swap window in the "
        "**Needs Swap Requests** tab."
    )

    if not config_names:
        st.info("No track cycles exist yet. Create one in the Track Configs tab.")
        return

    track_name = st.selectbox(
        "Track Cycle:", config_names, index=default_track_index, key="rebalance_track_select")

    with st.spinner("Loading roster and preferences..."):
        report_ctx, err = load_report_context(track_name)
    if report_ctx is None:
        st.error(err)
        return

    min_night_crews_for_sim = st.selectbox(
        "Minimum Night Crews (for the N-to-D flex simulation):", list(range(10)),
        index=min(report_ctx['min_night'], 9), key="rebalance_min_night_crews")

    shortfalls = find_shortfalls(
        report_ctx['days'], report_ctx['day_stats'],
        report_ctx['min_day'], report_ctx['min_night'], min_night_crews_for_sim,
    )

    if not shortfalls:
        st.success(f"No below-minimum Day or Night shifts found for {track_name}.")
        return

    summary_df = pd.DataFrame([{
        'Day': s['day_label'],
        'Mode': {'raw': 'Day (no flex)', 'flex': 'Day (with flex)', 'night': 'Night'}[s['mode']],
        'Minimum': s['minimum'],
        'Achievable': s['achievable'],
        'Short by': s['minimum'] - s['achievable'],
        'Crew mix needed': _format_deficit(s['deficit']),
    } for s in shortfalls])
    st.markdown(f"#### {len(shortfalls)} below-minimum shifts")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    _excel_download_button(
        summary_df, "📥 Download shortfalls as Excel",
        f"{track_name}_staffing_rebalance_shortfalls", key="download_rebalance_shortfalls",
        sheet_name="Shortfalls",
    )

    st.markdown("#### Who could cover a specific shortfall")
    labels = [_format_shortfall_label(s) for s in shortfalls]
    picked_label = st.selectbox("Pick a shortfall:", labels, key="rebalance_pick_shortfall")
    shortfall = shortfalls[labels.index(picked_label)]

    st.info(f"**Crew mix needed:** {_format_deficit(shortfall['deficit']) or 'none — senior cap only'}")

    with st.spinner("Checking who's extra elsewhere this week and whether they'd still pass validation..."):
        rows = candidates_for_shortfall(shortfall, report_ctx, track_name)

    if not rows:
        st.warning(
            "No one working this period elsewhere in the same week, who's off this day, "
            "can be moved here without breaking their own track's validation rules."
        )
        return

    rows.sort(key=lambda r: (not r['Would get a shift?'], r['Competition rank'] or 999))
    candidates_df = pd.DataFrame(rows)
    st.dataframe(candidates_df, use_container_width=True, hide_index=True)
    _excel_download_button(
        candidates_df, "📥 Download candidates as Excel",
        f"{track_name}_{shortfall['day_label']}_{shortfall['period']}_{shortfall['mode']}_candidates",
        key=f"download_rebalance_candidates_{picked_label}", sheet_name="Candidates",
    )
