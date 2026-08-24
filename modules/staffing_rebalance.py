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


def candidate_pool(shortfall, report_ctx, floors):
    """
    {candidate_name: [(give_up_day, period), ...]} for a shortfall: staff working
    elsewhere in the same week, who aren't scheduled at all (Day or Night) on the
    shortfall's own day, paired with *every* day that week they'd be allowed to come
    off of. Staff preassigned AT on the shortfall day map to an empty list — they
    have nothing to give up, because covering the day converts their AT in place.

    "Allowed to come off of" is surplus_shifts() — the same needs_swap_min_day /
    needs_swap_min_night floors, applied at role level, that the staff-facing Needs
    Swap view uses. Two things follow from sharing that function: a day only counts
    as extra if the shift still holds its floor once *this particular person* is
    removed from it (not merely because the day as a whole sits above the cycle
    minimum), and preassigned days are never offered as give-ups, since clearing one
    doesn't actually free the person up.

    Returning every candidate day rather than the first one matters: the first extra
    day of a week is often a Sunday, and a Sunday give-up is the one most likely to
    trip a weekend advisory. Picking it and stopping used to drop people who had a
    perfectly good midweek shift to trade instead.

    The give-up doesn't have to be the same period as the need — a Night that week is
    a valid thing to trade for a Day shortfall, since the swap is net-zero either way.
    The staff view has always allowed that, so this does too.

    Probationary staff (_BID_INELIGIBLE_STAFF) are skipped: they hold weekend
    assignments rather than a bid track, so there is no track to rearrange. They also
    carry no shifts-per-pay-period, which would otherwise make every rule that keys
    off it pass vacuously and put them at the top of every list.
    """
    from modules.track_bidding import _BID_INELIGIBLE_STAFF
    from modules.track_needs_swap import surplus_shifts

    target_day, week = shortfall['day_label'], shortfall['week']
    roster_index = report_ctx['roster_index']
    week_days = set(week) - {target_day}

    working_target_day = set(roster_index.get((target_day, 'Day'), [])) | \
        set(roster_index.get((target_day, 'Night'), []))

    names = {name
             for d in week_days
             for p in ('Day', 'Night')
             for name in roster_index.get((d, p), [])}

    # Anyone on AT that day is a candidate whether or not they work elsewhere in the
    # week: covering the shift converts their AT in place, so they need nothing to
    # trade and may well have nothing to trade.
    on_at = {name for name, pre in report_ctx['preassignments_by_name'].items()
             if pre.get(target_day) == 'AT'}

    candidates = {}
    for name in sorted((names | on_at) - working_target_day - _BID_INELIGIBLE_STAFF):
        if name in on_at:
            candidates[name] = []
            continue
        give_ups = [s for s in surplus_shifts(name, report_ctx, floors)
                    if s['day_label'] in week_days]
        if give_ups:
            candidates[name] = [(s['day_label'], s['period']) for s in give_ups]
    return candidates


def validate_candidate_swap(name, source_day, target_day, period, report_ctx):
    """
    Would name's own track still be valid if they swapped `source_day` for
    `target_day` (same period, net-zero shift count)?

    Delegates to the Needs Swap validator so this table and the staff-facing view
    apply one rule set. In particular that means night minimum, weekend minimum and
    weekend group do NOT block a candidate — someone covering a need is allowed to
    drop below those, so they come back as 'advisories' to show the admin instead of
    quietly removing the person. It also adds the Block C → Block A cycle-seam check,
    which the shared validator can't see, and measures advisories against the
    candidate's own bid so a track that was already short isn't blamed on this move.

    Returns the validation result dict, or None if this candidate can't be evaluated
    (no bid on file, or no numeric requirements — e.g. management).
    """
    from modules.track_needs_swap import validate_swap

    return validate_swap(name, source_day, target_day, period, report_ctx)


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
    from modules.track_management.preassignment import get_staff_preassignments

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
    bids_by_name = {b['staff_name']: b for b in bids}

    return {
        'ctx': ctx,
        'cfg': cfg,
        'bids': bids,
        'bids_by_name': bids_by_name,
        'roster_index': _build_roster_index(bids),
        'day_stats': day_stats,
        # Both derived once here rather than per lookup: the candidate table now runs
        # surplus_shifts() and validate_swap() for every name in a week, and each of
        # those otherwise re-indexed day_stats and re-parsed the preassignment frame.
        'day_stats_by_label': day_stats.set_index('day_label').to_dict('index'),
        'preassignments_by_name': {
            name: get_staff_preassignments(name, ctx['preassignment_df'], days)
            for name in bids_by_name
        },
        'days': days,
        'min_day': min_day,
        'min_night': min_night,
        'requirements_map': _load_requirements_map(ctx['requirements_df']),
        'all_base_prefs': _load_all_base_preferences(),
        'base_shift_counts': get_base_shift_counts(track_name),
    }, None


def is_at_on(name, day_label, report_ctx):
    """Is this staff member preassigned AT on that day?"""
    return report_ctx['preassignments_by_name'].get(name, {}).get(day_label) == 'AT'


def validate_at_conversion(name, need_day, period, report_ctx):
    """
    Someone already preassigned AT on a short day can just cover it — the AT becomes
    the shift. AT already counts toward their shifts per pay period and per week, so
    converting it in place is net-zero and they give nothing up in exchange.

    The conversion is still validated, because AT and a worked shift don't carry the
    same rest cost: AT needs only one free day after a night, a D needs two, so a
    track that was legal with AT on that day can be illegal with a D on it.

    Returns the validation result, or None if they can't be evaluated.
    """
    from modules.track_needs_swap import validate_track_for_staff, _PERIOD_CODE

    bid = report_ctx['bids_by_name'].get(name)
    if not bid:
        return None

    track_data = bid['track_data'] or {}
    converted = dict(track_data)
    converted[need_day] = _PERIOD_CODE[period]

    preassignments = dict(report_ctx['preassignments_by_name'].get(name, {}))
    preassignments.pop(need_day, None)

    return validate_track_for_staff(name, converted, report_ctx, baseline_track=track_data,
                                     preassignments=preassignments)


def candidates_for_shortfall(shortfall, report_ctx, track_name):
    """
    Full candidate table for one shortfall: pool -> validate every give-up day that
    person has this week -> rank (hypothetical assignment).

    A candidate survives if *any* of their give-up days validates, and the ones that
    do are all reported — an admin asking someone to move should be able to see which
    of their shifts is actually free to trade, not just that one of them is. Give-ups
    that would only cost an advisory (a night, a weekend, a weekend-group period) are
    kept and labelled, since dropping below those to cover a need is allowed.

    Someone already preassigned AT on the need day is handled separately: they can
    cover it outright, converting their AT into the shift, so they appear with nothing
    to give up (see validate_at_conversion).

    Candidates whose arrival wouldn't raise that shift's achievable crews are left
    out entirely: a nurse is no use to a day held back by a medic shortage, and
    nobody is any use to a day capped by its no-matrix headcount. Dual-credentialed
    staff count toward a medic shortfall — _max_possible_shifts() flexes them to the
    medic side, so achievable_change() credits them for it.

    Every give-up also carries what surrendering that particular shift would do to
    it — achievable crews and the headcount left in the candidate's own role bucket
    — so the cost of the move is visible next to the move itself (see
    _give_up_cells).

    Returns a list of dicts; sort in the caller if a particular order is wanted.
    """
    from modules.track_needs_swap import achievable_change, needs_swap_floors
    from modules.track_bidding import _bid_role_and_senior

    ctx = report_ctx['ctx']
    need_day, period = shortfall['day_label'], shortfall['period']
    floors = needs_swap_floors(report_ctx.get('cfg'))
    pool = candidate_pool(shortfall, report_ctx, floors)
    row = report_ctx['day_stats_by_label'][need_day]

    rows = []
    for name, give_ups in pool.items():
        role, is_senior = _bid_role_and_senior(
            report_ctx['bids_by_name'][name], ctx['role_mapping'], ctx['no_matrix_mapping'])
        before, after = achievable_change(row, period, role, is_senior, +1)
        if after <= before:
            continue  # their role isn't what's holding this shift back

        on_at = is_at_on(name, need_day, report_ctx)

        if on_at:
            # They're already scheduled to be there on AT. Covering the shift converts
            # that AT in place — net-zero on their shift count, so nothing is given up.
            validation = validate_at_conversion(name, need_day, period, report_ctx)
            if validation is None or not validation.get('overall_valid'):
                continue
            usable = [(None, None, set(validation.get('advisories', [])))]
        else:
            usable = []
            for source_day, source_period in give_ups:
                validation = validate_candidate_swap(
                    name, source_day, need_day, period, report_ctx)
                if validation is None or not validation.get('overall_valid'):
                    continue  # can't evaluate them, or this give-up would break their track
                usable.append((source_day, source_period, set(validation.get('advisories', []))))

        if not usable:
            continue

        # Cheapest trade first, and the Trade-off column reports only what they'd pay
        # whichever shift they gave up — a Sunday that costs a weekend shift shouldn't
        # make the candidate look expensive when they also have a free midweek day to
        # trade. Per-give-up costs stay on their own give-up, in its own column pair.
        usable.sort(key=lambda opt: len(opt[2]))
        unavoidable = set.intersection(*(adv for _, _, adv in usable))

        hypo = rank_candidate(
            name, need_day, period,
            ctx['preferences_df'], ctx['staff_col_prefs'], ctx['role_col'], ctx['seniority_col'],
            report_ctx['all_base_prefs'], track_name, report_ctx['base_shift_counts'],
        )

        candidate = {
            'Name': name,
            'Role': ctx['role_mapping'].get(name, 'Unknown'),
            'Seniority': ctx['seniority_mapping'].get(name),
            'No Matrix': ctx['no_matrix_mapping'].get(name, False),
        }
        candidate.update(_give_up_cells(usable, name, role, is_senior, report_ctx))
        candidate.update({
            'Crews here': f"{before} → {after}",
            'On AT here': "Yes" if on_at else "—",
            'Trade-off': _advisory_summary(unavoidable),
            'Hypothetical base': hypo['assignment'],
            'Base preference rank': hypo['preference_score'],
            'Competition rank': hypo.get('competition_rank'),
            'Competitors': hypo.get('total_competitors'),
            'Why': hypo['reason'],
        })
        rows.append(candidate)
    return rows


# One "Could give up (X)" / "Impact (X)" pair per shift a candidate could trade. Three
# slots are always rendered — the most anyone works in a week — and the letters run
# further only if some candidate on that shortfall really does have more.
_GIVE_UP_SLOTS = "ABCDEFG"
_MIN_GIVE_UP_SLOTS = 3

_CANDIDATE_LEAD_COLUMNS = ['Name', 'Role', 'Seniority', 'No Matrix']
_CANDIDATE_TAIL_COLUMNS = ['Crews here', 'On AT here', 'Trade-off', 'Hypothetical base',
                            'Base preference rank', 'Competition rank', 'Competitors', 'Why']


def _give_up_cells(usable, name, role, is_senior, report_ctx):
    """
    {'Could give up (A)': 'Wed A 1 D', 'Impact (A)': '−1 crew (7 → 6) · nurses 9 → 8', ...}
    — each shift this candidate could trade, paired with what that shift would be left
    with if they did.

    The impact is the same shift_impact() the Needs Swap review uses on a submitted
    offer, so a give-up costed here reads identically once the person actually offers
    it. Someone converting an AT in place gives nothing up, so their single slot says
    so and carries no impact.
    """
    from modules.track_needs_swap import shift_impact, give_up_impact_text

    by_label = report_ctx['day_stats_by_label']
    cells = {}
    for slot, (source_day, source_period, advisories) in zip(_GIVE_UP_SLOTS, usable):
        if source_day is None:
            cells[f'Could give up ({slot})'] = "AT converts in place"
            cells[f'Impact ({slot})'] = "Nothing given up"
            continue
        label = f"{source_day} {'D' if source_period == 'Day' else 'N'}"
        cells[f'Could give up ({slot})'] = _give_up_label(label, advisories)

        row = by_label.get(source_day)
        impact = (shift_impact(row, source_period, role, is_senior, -1)
                  if row is not None else None)
        cells[f'Impact ({slot})'] = give_up_impact_text(impact)
    return cells


def candidates_dataframe(rows):
    """
    Candidate rows as a DataFrame with a stable column order: the give-up/impact pairs
    sit together in the middle, and every table keeps at least A/B/C so shortfalls
    stay comparable side by side even when nobody on one of them has three shifts to
    trade. Unfilled slots read empty rather than NaN.
    """
    filled = max((i for i, slot in enumerate(_GIVE_UP_SLOTS, start=1)
                  if any(f'Could give up ({slot})' in r for r in rows)), default=0)
    slots = _GIVE_UP_SLOTS[:max(_MIN_GIVE_UP_SLOTS, filled)]

    give_up_columns = [f'{kind} ({slot})' for slot in slots
                       for kind in ('Could give up', 'Impact')]
    df = pd.DataFrame(rows, columns=_CANDIDATE_LEAD_COLUMNS + give_up_columns
                      + _CANDIDATE_TAIL_COLUMNS)
    df[give_up_columns] = df[give_up_columns].fillna('')
    return df


_INVALID_SHEET_CHARS = set("[]:*?/" + "\\")  # Excel forbids these in a sheet name

_NO_CANDIDATES_NOTE = (
    "No one available elsewhere in the same week would raise this shift's achievable "
    "crews and has a shift they could give up without breaking their own "
    "shifts-per-pay-period, weekly, rest, consecutive-shift or cycle-seam rules."
)


def candidate_sort_key(row):
    """People who'd actually land a base first, then by how they'd place in the bid."""
    return (row['Hypothetical base'] is None, row['Competition rank'] or 999)


def distinct_shift_shortfalls(shortfalls):
    """
    One entry per (day, period), keeping the first — which is the worst, since
    find_shortfalls() emits the raw Day case before the post-flex one.

    A Day that is short both before and after the N-to-D flex simulation appears
    twice, but candidates_for_shortfall() reads only the day, the period and the week
    those give — never the mode, the deficit or the achievable count — so the two
    would produce identical candidate tables. Reporting on them separately is worth
    it in the shortfall summary, where the numbers differ; in the candidate workbook
    it is just the same tab twice.
    """
    seen, distinct = set(), []
    for s in shortfalls:
        key = (s['day_label'], s['period'])
        if key not in seen:
            seen.add(key)
            distinct.append(s)
    return distinct


def sheet_names_for(shortfalls):
    """
    One Excel tab name per shortfall, in the same order: "Fri A 1 - Day".

    The mode is left out — an admin reading the tab strip wants the day and period,
    and distinct_shift_shortfalls() has already collapsed the modes that would share
    a name. Names are stripped of the characters Excel forbids in a sheet name,
    capped at its 31-character limit, and suffixed if that truncation happens to
    collide with a name already used.
    """
    names, used = [], set()
    for s in shortfalls:
        base = f"{s['day_label']} - {s['period']}"
        base = ''.join(c for c in base if c not in _INVALID_SHEET_CHARS)[:31] or "Shortfall"

        name, n = base, 2
        while name.lower() in used:
            suffix = f" ({n})"
            name = base[:31 - len(suffix)] + suffix
            n += 1
        used.add(name.lower())
        names.append(name)
    return names


def candidates_workbook(shortfalls, report_ctx, track_name, on_progress=None):
    """
    Every below-minimum shift's candidate table in one workbook, a sheet apiece, in
    shortfall order — one tab per day and period, since the pre- and post-flex forms
    of the same Day shortfall have the same candidates (distinct_shift_shortfalls).
    A shift nobody can cover still gets its sheet, carrying the same note the
    on-screen table shows, rather than being silently skipped.

    on_progress(index, shortfall), if given, is called before each shift is computed:
    this re-runs the full eligibility check per shift, so the UI drives a progress bar
    off it.

    Returns the workbook bytes.
    """
    shortfalls = distinct_shift_shortfalls(shortfalls)
    names = sheet_names_for(shortfalls)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        for i, (shortfall, sheet_name) in enumerate(zip(shortfalls, names)):
            if on_progress:
                on_progress(i, shortfall)
            rows = candidates_for_shortfall(shortfall, report_ctx, track_name)
            if rows:
                rows.sort(key=candidate_sort_key)
                df = candidates_dataframe(rows)
            else:
                df = pd.DataFrame([{'Note': _NO_CANDIDATES_NOTE}])
            _write_excel_sheet(writer, df, sheet_name)
    return buffer.getvalue()


_ADVISORY_SUMMARY = {
    'night_minimum': 'below night minimum',
    'weekend_minimum': 'below weekend minimum',
    'weekend_group_assignment': 'weekend group short',
}


def _advisory_summary(advisories):
    """What moving this candidate would cost them, beyond the rules that block a swap."""
    from modules.track_needs_swap import ADVISORY_RULES

    hit = [_ADVISORY_SUMMARY[r] for r in ADVISORY_RULES if r in advisories]
    return ", ".join(hit) if hit else "—"


def _give_up_label(day, advisories):
    """One give-up day, tagged with what trading that particular shift would cost."""
    return day if not advisories else f"{day} ({_advisory_summary(advisories)})"


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


def _write_excel_sheet(writer, df, sheet_name):
    """One auto-width worksheet — same sizing the Bid Analysis exports use."""
    from openpyxl.utils import get_column_letter

    df.to_excel(writer, sheet_name=sheet_name, index=False)
    ws = writer.sheets[sheet_name]
    for col_idx, col in enumerate(df.columns, start=1):
        # fillna first: a column that is entirely empty (e.g. no base preference on
        # file for any candidate) stays None through astype(str), and len(None) fails.
        content_width = (int(df[col].fillna('').astype(str).map(len).max())
                         if len(df) else 0)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(40, max(10, content_width + 2, len(str(col)) + 2))


def _excel_filename(prefix):
    from modules.track_bidding import _eastern_tz

    return f"{_safe_filename_part(prefix)}_{datetime.now(_eastern_tz).strftime('%Y%m%d%H%M%S')}.xlsx"


_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _excel_download_button(df, label, file_prefix, key, sheet_name="Sheet1"):
    """'Download as Excel' button for a DataFrame — same ExcelWriter+download_button
    pattern as the Bid Analysis tab's Day/Night breakdown export."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        _write_excel_sheet(writer, df, sheet_name)
    buffer.seek(0)

    st.download_button(
        label, data=buffer, file_name=_excel_filename(file_prefix),
        mime=_EXCEL_MIME, key=key,
    )


def _render_staffing_rebalance_tab(config_names, default_track_index):
    st.markdown("### Staffing Rebalance")
    st.caption(
        "For every below-minimum Day/Night shift in a track cycle: the crew mix that would "
        "close the gap, and who — within that same week — could be asked to move to cover it. "
        "Eligibility is exactly what the staff-facing **Needs Swap Requests** tab shows those "
        "same people: shifts per pay period, the weekly limit, rest, consecutive shifts and the "
        "cycle seam all have to hold, but night and weekend minimums do not — someone covering a "
        "need is allowed to drop below those, and the Trade-off column says when they would. "
        "Only people whose arrival would actually raise that shift's achievable crews are listed "
        "(duals count toward a medic shortfall). Anyone already on AT that day can simply cover "
        "it — their AT becomes the shift and they give nothing up. Each shift someone could "
        "trade gets a **Could give up** column and an **Impact** column beside it: what that "
        "shift would be left with — achievable crews, then the headcount in their own role "
        "bucket (nurse counts include duals) — if they came off it. Recommendations only; "
        "nothing here changes the schedule."
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

    if rows:
        rows.sort(key=candidate_sort_key)
        st.dataframe(candidates_dataframe(rows), use_container_width=True, hide_index=True)
    else:
        st.warning(_NO_CANDIDATES_NOTE)

    _render_all_candidates_download(shortfalls, report_ctx, track_name, min_night_crews_for_sim)


def _render_all_candidates_download(shortfalls, report_ctx, track_name, min_night_crews_for_sim):
    """
    The Excel export covers every shortfall, not just the one picked above — one tab
    per below-minimum shift, named for its day and period.

    It's built on an explicit click rather than on every render: the workbook re-runs
    the whole eligibility check once per shortfall, which is far too slow to sit in
    the render path of a tab that recomputes on every interaction anywhere on the
    page. The finished bytes are held in session_state under a key carrying the
    inputs that determine them, so changing track cycle or the night-minimum
    simulation retires the old workbook instead of handing out a stale one.
    """
    state_key = f"rebalance_all_candidates_{track_name}_{min_night_crews_for_sim}"
    shifts = distinct_shift_shortfalls(shortfalls)

    st.markdown("#### Download every shortfall's candidates")
    st.caption(
        f"One workbook, one tab per below-minimum shift (all {len(shifts)} of them), each "
        "named for its day and period — not just the shortfall picked above. A Day that is "
        "short both before and after the flex simulation gets one tab, not two: the "
        "candidates are the same either way. Building it re-checks every shift, so it takes "
        "a moment."
    )

    if st.button("🛠️ Build candidate workbook", key="build_rebalance_all_candidates"):
        progress = st.progress(0.0, text="Checking candidates...")

        def on_progress(i, shortfall):
            progress.progress(i / len(shifts),
                              text=f"Checking {_format_shortfall_label(shortfall)}...")

        try:
            st.session_state[state_key] = candidates_workbook(
                shortfalls, report_ctx, track_name, on_progress=on_progress)
        finally:
            progress.empty()

    workbook = st.session_state.get(state_key)
    if workbook:
        st.download_button(
            "📥 Download candidates as Excel", data=workbook,
            file_name=_excel_filename(f"{track_name}_all_shortfall_candidates"),
            mime=_EXCEL_MIME, key="download_rebalance_all_candidates",
        )
