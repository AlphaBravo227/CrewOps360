# modules/track_needs_swap.py
"""
Track Needs Swap — the staff-facing other half of Staffing Rebalance.

Staffing Rebalance answers the admin's question ("this Friday night is short — who
could cover it?"). This module answers the staff member's ("here are the needs I
could move onto, and the shifts I'd be allowed to give up to do it"), collects
their ranked offers, and gives admins a review queue where approving an offer
applies it to that person's bid track.

The eligibility rules, in one place:
  - A **need** is a below-minimum Day/Night shift from find_shortfalls().
  - A staff member can move onto a need only if they're completely off that day
    and the move would actually raise that shift's achievable crews.
  - A shift they can **give up** must stay at or above the minimum (plus the
    cycle's surplus buffer) once they're removed from it — i.e. genuinely
    overstaffed, and never itself a need.
  - Every (need, give-up) pairing is run through validate_track_comprehensive()
    on the resulting hypothetical track, so nothing on offer can break the staff
    member's own shifts/rest/weekend rules — plus cycle_wrap_issues() for the rest
    and consecutive-shift rules across the Block C → Block A seam, which that
    validator walks past (see its docstring).
"""

import pandas as pd
import streamlit as st

from modules.db_utils import (
    get_bid_track_from_db,
    get_need_swap_offers,
    get_needs_swap_track_config,
    get_track_config_by_name,
    save_bid_track_to_db,
    save_need_swap_offers,
    supersede_sibling_need_offers,
    update_need_swap_offer_status,
    update_track_config,
)
from modules.nondisplacing_assignment import nondisplacing_bases, rank_options
from modules.staffing_rebalance import _excel_download_button, find_shortfalls, load_report_context
from modules.track_bidding import _bid_role_and_senior, _bidding_role_bucket, _max_possible_shifts

_PERIOD_CODE = {'Day': 'D', 'Night': 'N'}
_CODE_PERIOD = {'D': 'Day', 'N': 'Night'}


# ──────────────────────────────────────────────
# Needs
# ──────────────────────────────────────────────

def consolidate_needs(shortfalls):
    """
    Collapse find_shortfalls()' three flavors (Day raw / Day post-flex / Night) into
    one entry per (day_label, period), which is what a staff member should see —
    "Fri A 2 Night is short", not the same day listed twice under two simulation
    modes.

    Each entry carries both numbers so the size of the need stays honest:
      short_raw   — how short it is with no N-to-D flex at all
      short_flex  — how short it's still expected to be after the flex simulation
                    (0 for a Day shift that flexing fully covers; None for Night,
                    where flex never applies)

    Returns entries sorted worst-first (post-flex shortfall, then raw shortfall).
    """
    by_key = {}
    for s in shortfalls:
        key = (s['day_label'], s['period'])
        entry = by_key.setdefault(key, {
            'day_label': s['day_label'],
            'period': s['period'],
            'week': s['week'],
            'minimum': s['minimum'],
            'achievable': s['achievable'],
            'short_raw': 0,
            'short_flex': None if s['period'] == 'Night' else 0,
            'deficit': s['deficit'],
        })
        short = s['minimum'] - s['achievable']
        if s['mode'] == 'flex':
            entry['short_flex'] = short
            # The post-flex picture is the one that still needs a body, so its crew
            # mix and crew count are the ones worth showing.
            entry['deficit'] = s['deficit']
            entry['achievable'] = s['achievable']
        else:
            entry['short_raw'] = short  # 'raw' (Day, no flex) and 'night'

    needs = list(by_key.values())
    needs.sort(key=lambda n: (-(n['short_flex'] or 0), -n['short_raw'], n['day_label']))
    return needs


def _period_counts(row, period):
    """(nurse, medic, dual, senior) for one day_stats row and period."""
    p = 'day' if period == 'Day' else 'night'
    return row[f'{p}_nurse'], row[f'{p}_medic'], row[f'{p}_dual'], row[f'{p}_senior']


def _adjust_counts(counts, role, is_senior, delta):
    """Apply one body of `role` joining (delta=+1) or leaving (delta=-1) a shift."""
    nurse, medic, dual, senior = counts
    if role == 'medic':
        medic += delta
    else:
        nurse += delta
        if role == 'dual':
            dual += delta
    if is_senior:
        senior += delta
    return max(0, nurse), max(0, medic), max(0, dual), max(0, senior)


def has_capacity_room(row, period, role, weekday_caps):
    """
    Is there still a seat for one more of this role on that day/period under the
    cycle's bid caps (including any day-of-week overrides)? The same ceiling the
    Track Selection editor enforces while bidding — a need being short of crews
    doesn't automatically mean the *role* moving in has room.
    """
    bucket = 'medic' if str(role).strip().lower() == 'medic' else 'nurse'
    p = 'day' if period == 'Day' else 'night'
    cap = (weekday_caps or {}).get(row['weekday'], {}).get(f'max_{p}_{bucket}s')
    if cap is None:
        return True
    return row[f'{p}_{bucket}'] + 1 <= cap


def achievable_change(row, period, role, is_senior, delta):
    """
    (before, after) achievable crews for a day/period when this staff member joins
    or leaves it. Uses the same _max_possible_shifts model as the Bid Analysis
    "Maximum Achievable Crews" chart, so the numbers a staff member sees here match
    what the admin sees there.
    """
    counts = _period_counts(row, period)
    before = _max_possible_shifts(*counts)
    after = _max_possible_shifts(*_adjust_counts(counts, role, is_senior, delta))
    return before, after


# ──────────────────────────────────────────────
# Per-staff eligibility
# ──────────────────────────────────────────────

def surplus_shifts(staff_name, report_ctx, surplus_buffer=0):
    """
    Every shift in this staff member's bid track that they'd be allowed to come off
    of: a D or N day (never a preassignment) whose achievable crews stay at or above
    that period's minimum plus `surplus_buffer` once they're removed.

    Returns a list of dicts: day_label, period, code, before, after, minimum.
    """
    bid = report_ctx['bids_by_name'].get(staff_name)
    if not bid:
        return []

    role, is_senior = _bid_role_and_senior(
        bid, report_ctx['ctx']['role_mapping'], report_ctx['ctx']['no_matrix_mapping'])
    preassignments = _staff_preassignments(staff_name, report_ctx)
    by_label = report_ctx['day_stats'].set_index('day_label').to_dict('index')

    shifts = []
    for day, code in (bid['track_data'] or {}).items():
        if code not in _CODE_PERIOD or day in preassignments:
            continue
        row = by_label.get(day)
        if row is None:
            continue
        period = _CODE_PERIOD[code]
        minimum = report_ctx['min_day'] if period == 'Day' else report_ctx['min_night']
        before, after = achievable_change(row, period, role, is_senior, -1)
        if after < minimum + surplus_buffer:
            continue  # this shift isn't overstaffed — losing them would make it a need
        shifts.append({
            'day_label': day, 'period': period, 'code': code,
            'before': before, 'after': after, 'minimum': minimum,
        })

    day_order = {d: i for i, d in enumerate(report_ctx['days'])}
    shifts.sort(key=lambda s: day_order.get(s['day_label'], 999))
    return shifts


def _staff_preassignments(staff_name, report_ctx):
    from modules.track_management.preassignment import get_staff_preassignments

    cached = report_ctx.get('preassignments_by_name')
    if cached is not None and staff_name in cached:
        return cached[staff_name]
    return get_staff_preassignments(staff_name, report_ctx['ctx']['preassignment_df'],
                                     report_ctx['days'])


# The seam sits between the last day of Block C and the first day of Block A. Rotating
# the day list by any amount that keeps both sides of the seam well inside the rotated
# list moves it somewhere a linear scan will look; half a cycle is the safe choice.
_WRAP_ROTATION = 21


def _spans_seam(violation, index_of):
    """Does this violation pair a late-cycle day with an earlier-cycle one (i.e. wrap)?"""
    for first, second in (('night_day', 'next_shift_day'), ('current_day', 'next_day'),
                          ('start_day', 'end_day')):
        if first in violation and second in violation:
            return index_of[violation[second]] < index_of[violation[first]]
    return False


def cycle_wrap_issues(track_data, preassignments, days):
    """
    Rest and consecutive-shift violations that only exist because the 42-day track
    repeats — the ones validate_track_comprehensive() structurally cannot see.

    That validator walks the cycle as a flat list, so the last days of Block C are
    never compared with the first days of Block A even though they run back-to-back
    every time the track cycles: a Night on Sat C 6 followed by a Day on Sun A 1 is
    0 days of rest in real life and invisible to a linear scan.

    Re-running the two order-sensitive rules over a rotated day list closes that gap —
    rotating puts the seam in the middle of the list, where the same scan does check
    it, and the one adjacency the rotation breaks (days[20] → days[21]) is one the
    unrotated pass already checked. Only violations that actually cross the seam are
    returned, so nothing the normal validator already reports is duplicated here.

    Returns a list of description strings (empty when the seam is clean).
    """
    from modules.enhanced_track_validator import (
        create_combined_track, validate_consecutive_shifts_limit,
        validate_rest_requirements_enhanced,
    )

    combined = create_combined_track(track_data, preassignments)
    rotated = days[_WRAP_ROTATION:] + days[:_WRAP_ROTATION]
    index_of = {day: i for i, day in enumerate(days)}

    rest = validate_rest_requirements_enhanced(combined, preassignments, rotated)
    consecutive = validate_consecutive_shifts_limit(combined, rotated)

    return [v['description']
            for v in list(rest.get('violations', [])) + list(consecutive.get('violations', []))
            if _spans_seam(v, index_of)]


def validate_track_for_staff(staff_name, track_data, report_ctx, baseline_track=None):
    """
    Run the full track validator over `track_data` using this staff member's own
    requirements and preassignments, plus the cycle-wrap check the shared validator
    doesn't cover.

    `baseline_track`, when given, is the track this one is a modification of: seam
    issues that were already there are not counted against the change. A bid that
    was submitted with a wrap-around rest problem (nothing checked for one at bid
    time) shouldn't leave that person unable to volunteer for anything.

    Returns the validate_track_comprehensive() result dict with an extra
    'cycle_wrap' entry folded into 'overall_valid', or None when the staff member
    can't be evaluated (no numeric requirements — e.g. management).
    """
    from modules.enhanced_track_validator import validate_track_comprehensive

    req = report_ctx['requirements_map'].get(staff_name)
    if not req or req.get('shifts_per_pay_period') is None:
        return None

    preassignments = _staff_preassignments(staff_name, report_ctx)
    days = report_ctx['days']

    result = validate_track_comprehensive(
        track_data,
        shifts_per_pay_period=req.get('shifts_per_pay_period') or 0,
        night_minimum=req.get('night_minimum') or 0,
        weekend_minimum=req.get('weekend_minimum') or 0,
        preassignments=preassignments,
        days=days,
        weekend_group=req.get('weekend_group'),
    )

    issues = cycle_wrap_issues(track_data, preassignments, days)
    if baseline_track is not None:
        already = set(cycle_wrap_issues(baseline_track, preassignments, days))
        issues = [i for i in issues if i not in already]

    result['cycle_wrap'] = {
        'status': not issues,
        'details': ("Rest and consecutive-shift rules hold across the Block C → Block A "
                    "wrap" if not issues else f"{len(issues)} violation(s) where the cycle repeats"),
        'issues': issues,
    }
    result['overall_valid'] = result['overall_valid'] and not issues
    return result


def swapped_track(track_data, give_up_day, need_day, need_period):
    """`track_data` with the given-up day cleared and the need day taking its shift code."""
    swapped = dict(track_data or {})
    swapped[give_up_day] = ''
    swapped[need_day] = _PERIOD_CODE[need_period]
    return swapped


def validate_swap(staff_name, give_up_day, need_day, need_period, report_ctx):
    """
    Would this staff member's track still be valid if they moved off `give_up_day`
    onto `need_day`? Evaluated against the bid as loaded into `report_ctx`.

    Returns the validate_track_comprehensive() result dict, or None when the staff
    member can't be evaluated (no bid, or no numeric requirements).
    """
    bid = report_ctx['bids_by_name'].get(staff_name)
    if not bid:
        return None
    return validate_track_for_staff(
        staff_name, swapped_track(bid['track_data'], give_up_day, need_day, need_period),
        report_ctx, baseline_track=bid['track_data'])


def swap_options_for_staff(staff_name, needs, report_ctx, surplus_buffer=0):
    """
    The staff member's whole menu: every need they could move onto, each with the
    ranked-able list of shifts they could give up to do it.

    A need is included only when the staff member is off that day, their move would
    actually raise that shift's achievable crews, and at least one give-up pairing
    passes validation. Returns a list of dicts:

        {need: <need dict>, before: int, after: int, options: [
            {day_label, period, code, before, after, minimum}, ...]}

    ordered worst-need-first (the order consolidate_needs() produced).
    """
    bid = report_ctx['bids_by_name'].get(staff_name)
    if not bid:
        return []

    role, is_senior = _bid_role_and_senior(
        bid, report_ctx['ctx']['role_mapping'], report_ctx['ctx']['no_matrix_mapping'])
    track_data = bid['track_data'] or {}
    preassignments = _staff_preassignments(staff_name, report_ctx)
    by_label = report_ctx['day_stats'].set_index('day_label').to_dict('index')

    give_up_pool = surplus_shifts(staff_name, report_ctx, surplus_buffer)
    if not give_up_pool:
        return []

    results = []
    for need in needs:
        need_day, period = need['day_label'], need['period']
        if track_data.get(need_day) or need_day in preassignments:
            continue  # already working (or preassigned) that day
        row = by_label.get(need_day)
        if row is None:
            continue

        before, after = achievable_change(row, period, role, is_senior, +1)
        if after <= before:
            continue  # their role isn't what's holding this shift back
        if not has_capacity_room(row, period, role, report_ctx.get('weekday_caps')):
            continue  # that day is already at its bid cap for their role

        options = []
        for shift in give_up_pool:
            if shift['day_label'] == need_day:
                continue
            validation = validate_swap(staff_name, shift['day_label'], need_day, period, report_ctx)
            if validation is None or not validation.get('overall_valid'):
                continue
            options.append(shift)

        if options:
            results.append({'need': need, 'before': before, 'after': after, 'options': options})

    return results


# ──────────────────────────────────────────────
# Where a volunteer would actually work
# ──────────────────────────────────────────────

def _seniority_of(staff_name, report_ctx):
    try:
        return int(report_ctx['ctx']['seniority_mapping'].get(staff_name))
    except (TypeError, ValueError):
        return 999


def day_roster(day_label, period, role_bucket, report_ctx, exclude=None):
    """
    Everyone bidding this day/period in one role bucket, most senior first — the
    people a volunteer would be joining, and whose base assignments the
    non-displacing rule protects.
    """
    code = _PERIOD_CODE[period]
    roster = [
        (name, _seniority_of(name, report_ctx))
        for name, bid in report_ctx['bids_by_name'].items()
        if name != exclude and (bid['track_data'] or {}).get(day_label) == code
        and _bidding_role_bucket(
            _bid_role_and_senior(bid, report_ctx['ctx']['role_mapping'],
                                 report_ctx['ctx']['no_matrix_mapping'])[0]) == role_bucket
    ]
    roster.sort(key=lambda pair: (pair[1], pair[0]))
    return roster


def base_options_for_need(staff_name, day_label, period, report_ctx):
    """
    The bases this volunteer could be shown for a need — only those where everyone
    already on that day keeps or improves their own ranked base (see
    modules/nondisplacing_assignment.py).

    Returns (options, blocked): options is [{'base', 'rank', 'moves'}] best-rank
    first, blocked is {base: reason} for the ones deliberately withheld.
    """
    bid = report_ctx['bids_by_name'].get(staff_name)
    if not bid:
        return [], {}

    role, _ = _bid_role_and_senior(bid, report_ctx['ctx']['role_mapping'],
                                   report_ctx['ctx']['no_matrix_mapping'])
    bucket = _bidding_role_bucket(role)

    def compute():
        roster = day_roster(day_label, period, bucket, report_ctx, exclude=staff_name)
        options, _baseline, blocked = nondisplacing_bases(
            roster, period, report_ctx['all_base_prefs'], report_ctx['base_shift_counts'])
        return options, blocked

    # Which bases survive depends only on the people already on the day, not on who
    # the volunteer is, so it's computed once per day/period/role bucket and reused.
    # A volunteer is off the need day by definition; the only way that isn't true is
    # a stale offer, and then the roster really is different, so skip the cache.
    if (bid['track_data'] or {}).get(day_label):
        options, blocked = compute()
    else:
        cache = report_ctx.setdefault('_base_options_cache', {})
        key = (day_label, period, bucket)
        if key not in cache:
            cache[key] = compute()
        options, blocked = cache[key]

    return rank_options(staff_name, options, period, report_ctx['all_base_prefs']), blocked


def best_base_for_need(staff_name, day_label, period, report_ctx):
    """The single base to show a volunteer for a need, or None if none can be promised."""
    options, _blocked = base_options_for_need(staff_name, day_label, period, report_ctx)
    return options[0] if options else None


# ──────────────────────────────────────────────
# Shared context
# ──────────────────────────────────────────────

def load_swap_context(track_name, min_night_crews_for_sim=None):
    """
    Everything both the staff and admin views need: the Staffing Rebalance report
    context plus per-staff preassignments and the consolidated need list.

    Returns (context, error). context is None on failure.
    """
    from modules.db_utils import get_track_capacity_by_weekday
    from modules.track_management.preassignment import get_staff_preassignments

    report_ctx, err = load_report_context(track_name)
    if report_ctx is None:
        return None, err

    report_ctx['weekday_caps'] = get_track_capacity_by_weekday(track_name)
    report_ctx['preassignments_by_name'] = {
        name: get_staff_preassignments(name, report_ctx['ctx']['preassignment_df'], report_ctx['days'])
        for name in report_ctx['bids_by_name']
    }

    sim_floor = report_ctx['min_night'] if min_night_crews_for_sim is None else min_night_crews_for_sim
    shortfalls = find_shortfalls(
        report_ctx['days'], report_ctx['day_stats'],
        report_ctx['min_day'], report_ctx['min_night'], sim_floor,
    )
    report_ctx['needs'] = consolidate_needs(shortfalls)
    return report_ctx, None


# ──────────────────────────────────────────────
# Applying an approved offer
# ──────────────────────────────────────────────

def apply_offer(offer, report_ctx, reviewed_by, review_notes=None):
    """
    Approve one offer and write it to the staff member's bid track: the give-up day
    is cleared, the need day takes the need's shift code, and save_bid_track_to_db()
    versions the change into track_history like any other bid revision.

    The pairing is re-validated against the bid as it stands right now — an offer
    that has gone stale (because the staff member's track or someone else's moved
    since they submitted) is refused rather than applied.

    Returns (success, message).
    """
    staff_name = offer['staff_name']
    track_name = offer['track_name']

    ok, bid = get_bid_track_from_db(staff_name, track_name)
    if not ok:
        return False, f"No bid on file for {staff_name} in {track_name}."

    track_data = dict(bid['track_data'] or {})
    if track_data.get(offer['give_up_day']) != _PERIOD_CODE[offer['give_up_period']]:
        return False, (f"{staff_name} is no longer working {offer['give_up_period']} on "
                       f"{offer['give_up_day']} — this offer is out of date.")
    if track_data.get(offer['need_day']):
        return False, (f"{staff_name} is already assigned on {offer['need_day']} — "
                       "this offer is out of date.")

    # Validated against the bid exactly as it stands in the database right now, not the
    # snapshot report_ctx was built from — an earlier approval in this same review pass
    # may already have moved this person.
    swapped = swapped_track(track_data, offer['give_up_day'], offer['need_day'], offer['need_period'])
    validation = validate_track_for_staff(staff_name, swapped, report_ctx, baseline_track=track_data)
    if validation is None:
        return False, f"Could not validate a swap for {staff_name} (no requirements on file)."
    if not validation.get('overall_valid'):
        failed = [k.replace('_', ' ') for k, v in validation.items()
                  if k != 'overall_valid' and not v['status']]
        return False, f"Swap would now break {staff_name}'s track ({', '.join(failed)}). Not applied."

    saved, save_msg, _ = save_bid_track_to_db(staff_name, swapped, track_name,
                                              metadata=bid.get('metadata'))
    if not saved:
        return False, save_msg

    note = review_notes or (f"Moved {offer['give_up_period']} {offer['give_up_day']} → "
                            f"{offer['need_period']} {offer['need_day']}")
    update_need_swap_offer_status(offer['id'], 'approved', reviewed_by, note)
    superseded = supersede_sibling_need_offers(offer['id'])

    message = (f"Applied: {staff_name} moves off {offer['give_up_period']} {offer['give_up_day']} "
               f"onto {offer['need_period']} {offer['need_day']}.")
    if superseded:
        message += f" {superseded} other option{'s' if superseded != 1 else ''} for that need superseded."
    return True, message


def offers_with_status(track_name, report_ctx):
    """
    All offers for a cycle, each annotated with whether it would still apply cleanly
    right now — so an admin reviewing a queue can tell a live offer from one that
    another approval has already invalidated.

    Adds to each offer dict: still_valid (bool), stale_reason (str or '').
    """
    by_label = report_ctx['day_stats'].set_index('day_label').to_dict('index')

    annotated = []
    for offer in get_need_swap_offers(track_name):
        if offer['status'] != 'pending':
            annotated.append({**offer, 'still_valid': False, 'stale_reason': ''})
            continue

        bid = report_ctx['bids_by_name'].get(offer['staff_name'])
        reason = ''
        if not bid:
            reason = 'No bid on file'
        elif (bid['track_data'] or {}).get(offer['give_up_day']) != _PERIOD_CODE[offer['give_up_period']]:
            reason = f"No longer working {offer['give_up_period']} on {offer['give_up_day']}"
        elif (bid['track_data'] or {}).get(offer['need_day']):
            reason = f"Already assigned on {offer['need_day']}"
        elif not has_capacity_room(
                by_label[offer['need_day']], offer['need_period'],
                _bid_role_and_senior(bid, report_ctx['ctx']['role_mapping'],
                                     report_ctx['ctx']['no_matrix_mapping'])[0],
                report_ctx.get('weekday_caps')):
            reason = f"{offer['need_day']} is now at its bid cap for their role"
        else:
            validation = validate_swap(offer['staff_name'], offer['give_up_day'],
                                       offer['need_day'], offer['need_period'], report_ctx)
            if validation is None:
                reason = 'Cannot be validated'
            elif not validation.get('overall_valid'):
                failed = [k.replace('_', ' ') for k, v in validation.items()
                          if k != 'overall_valid' and not v['status']]
                reason = 'Would now break: ' + ', '.join(failed)

        annotated.append({**offer, 'still_valid': not reason, 'stale_reason': reason})
    return annotated


# ──────────────────────────────────────────────
# Streamlit UI — staff view
# ──────────────────────────────────────────────

_STAFF_FLASH = 'needs_swap_staff_flash'
_ADMIN_FLASH = 'needs_swap_admin_flash'


def _flash(key, level, message):
    """Stash a message that should survive the st.rerun() which follows an action."""
    st.session_state[key] = (level, message)


def _render_flash(key):
    """Show and clear a message stashed by _flash() before the last rerun."""
    stashed = st.session_state.pop(key, None)
    if not stashed:
        return
    level, message = stashed
    {'success': st.success, 'error': st.error, 'info': st.info}.get(level, st.info)(message)


def _shift_label(day_label, period):
    return f"{day_label} — {period}"


def _need_headline(need):
    """One-line description of a need, in the terms staff already know from bidding."""
    short = need['short_flex'] if need['short_flex'] is not None else need['short_raw']
    text = (f"{_PRIORITY_LABEL[need_priority(need)]} · "
            f"**{_shift_label(need['day_label'], need['period'])}** — "
            f"{need['achievable']} of {need['minimum']} crews")
    if short:
        text += f", short by {short}"
    if need['period'] == 'Day' and need['short_flex'] == 0 and need['short_raw']:
        text += " (covered only if night staff get flexed to days)"
    return text


# Priority is what a staff member sees instead of raw crew counts: how badly this
# shift needs a body, on a three-step scale. Colors carry the meaning, so each one
# is paired with a word for anyone who can't rely on them.
_PRIORITY_LABEL = {'high': '🔴 High', 'medium': '🟡 Medium', 'low': '🟢 Low'}
_PRIORITY_STYLE = {
    '🔴 High':   'background-color: #fdecea; color: #8a1c12; font-weight: 600',
    '🟡 Medium': 'background-color: #fff4d6; color: #7a5200; font-weight: 600',
    '🟢 Low':    'background-color: #e8f5e9; color: #1b5e20; font-weight: 600',
}


def need_priority(need):
    """
    'high' / 'medium' / 'low' for one need, from how many crews it's still short
    once the N-to-D flex simulation has done what it can (for a Night, where flex
    never applies, that's simply how short it is).

    Low means the gap closes only if schedulers flex night staff over to days —
    real, but the softest of the three.
    """
    short = need['short_flex'] if need['short_flex'] is not None else need['short_raw']
    if short >= 2:
        return 'high'
    if short == 1:
        return 'medium'
    return 'low'


def _compact_shift(day_label, period):
    """'Sun A 1' + 'Night' -> 'Sun A1 N', short enough to list several in one cell."""
    code = _PERIOD_CODE[period]
    parts = day_label.split()
    if len(parts) == 3:
        return f"{parts[0]} {parts[1]}{parts[2]} {code}"
    return f"{day_label} {code}"


def _give_up_summary(options, limit=6):
    """'3 — Sun A1 N, Wed A1 D, Thu B3 D' for the shifts on offer against a need."""
    shown = [_compact_shift(o['day_label'], o['period']) for o in options[:limit]]
    text = f"{len(options)} — " + ", ".join(shown)
    if len(options) > limit:
        text += f", +{len(options) - limit} more"
    return text


def _rank_text(option):
    """'#2' / 'unranked' / '—' for a base option the volunteer might be shown."""
    if not option:
        return "—"
    return f"#{option['rank']}" if option['rank'] is not None else "unranked"


def _render_base_outlook(staff_name, need, report_ctx):
    """Where a volunteer would land on this need's day, and what's deliberately withheld."""
    options, blocked = base_options_for_need(staff_name, need['day_label'], need['period'], report_ctx)

    if not options:
        full = any('spoken for' in reason for reason in blocked.values())
        why = ("Every base slot on this day is already taken." if full else
               "Every base is held by someone who ranks it at least as highly as anywhere "
               "else they could move to, so none can be freed up without setting someone back.")
        st.warning(
            f"**No base can be promised on this day.** {why} You can still offer to move here "
            "to cover the need — the shift counts either way — but your location can't be "
            "predicted in advance."
        )
    else:
        best = options[0]
        moves = best['moves']
        line = f"**Hypothetical Shift: {best['base']}** ({_rank_text(best)} on your list)"
        if moves:
            line += " — " + "; ".join(
                f"{m['staff']} shifts {m['from']} → {m['to']}, which they rank higher"
                if (m['to_rank'] is not None and m['from_rank'] is not None and m['to_rank'] < m['from_rank'])
                else f"{m['staff']} shifts {m['from']} → {m['to']}, no worse for them"
                for m in moves)
        st.markdown(line)

        others = options[1:]
        if others:
            st.caption("Also open to you: " +
                       ", ".join(f"{o['base']} ({_rank_text(o)})" for o in others))

    if blocked:
        st.caption("Not offered: " + ", ".join(sorted(blocked)) +
                   " — taking those would move someone already on this day to a base they rank lower.")


def _deficit_text(deficit):
    if not deficit:
        return ""
    parts = [f"{deficit[k]} {k}" for k in ('nurse', 'medic', 'senior') if deficit.get(k)]
    return " + ".join(parts)


def offers_from_editor(edited, need, options):
    """
    Turn one need's edited option grid into offer rows: keep the ticked ones, order
    them by the rank the staff member typed, and renumber 1..n so the stored ranks
    are always a clean sequence no matter what they typed (ties, gaps, blanks).
    """
    ticked = edited[edited['Offer this'].fillna(False).astype(bool)]
    ticked = ticked.sort_values('Rank', kind='stable', na_position='last')
    option_by_label = {_shift_label(o['day_label'], o['period']): o for o in options}

    offers = []
    for rank, (_, row) in enumerate(ticked.iterrows(), start=1):
        option = option_by_label.get(row['Give up'])
        if option is None:
            continue
        offers.append({
            'need_day': need['day_label'], 'need_period': need['period'],
            'give_up_day': option['day_label'], 'give_up_period': option['period'],
            'preference_rank': rank,
        })
    return offers


def _render_staff_current_track(staff_name, report_ctx):
    from modules.track_management.display import display_schedule_by_blocks

    bid = report_ctx['bids_by_name'][staff_name]
    with st.expander("📍 My current track for this cycle", expanded=False):
        st.caption(f"Submitted {bid['submission_date']} (version {bid['version']}). "
                   "This is the track your swap options are measured against.")
        display_schedule_by_blocks(bid['track_data'], report_ctx['days'],
                                   _staff_preassignments(staff_name, report_ctx))


def _render_existing_offers(track_name, staff_name):
    """The staff member's own submitted offers and where each one stands."""
    offers = get_need_swap_offers(track_name, staff_name=staff_name)
    if not offers:
        return offers

    status_icon = {'pending': '⏳ Waiting on review', 'approved': '✅ Approved — applied to your track',
                   'declined': '❌ Not selected', 'superseded': '➖ Another option was used instead'}
    st.markdown("#### What you've already submitted")
    st.dataframe(pd.DataFrame([{
        'Move onto': _shift_label(o['need_day'], o['need_period']),
        'Give up': _shift_label(o['give_up_day'], o['give_up_period']),
        'Your rank': o['preference_rank'],
        'Status': status_icon.get(o['status'], o['status']),
        'Submitted': o['submission_date'],
    } for o in offers]), use_container_width=True, hide_index=True)
    return offers


def display_staff_needs_swap(track_name=None):
    """
    Staff-facing "swap onto a need" page: pick your name, see the needs you could
    move onto, choose and rank the shifts you'd give up, and submit.
    """
    cfg = get_needs_swap_track_config() if track_name is None else get_track_config_by_name(track_name)
    if not cfg or not cfg.get('needs_swap_open'):
        return False

    track_name = cfg['track_name']
    surplus_buffer = cfg.get('needs_swap_surplus_buffer') or 0

    st.markdown("## 🔁 Track Needs — Swap Opportunities")
    st.markdown(f"**Open for: {track_name}**")
    with st.expander("📖 How this works"):
        st.markdown(f"""
Some shifts in **{track_name}** came out of bidding below the minimum crew count. Rather than
assign people to them, we're asking first.

1. **Pick your name.** You'll see your submitted track for this cycle, and every need you
   personally could move onto.
2. **A need only shows up for you if all of this is true:**
   - You're completely off that day already.
   - Your role is what that shift is actually short of — moving you there raises the number
     of crews it can put in the air.
   - You have at least one shift you could give up in exchange.
3. **A shift only shows up as something you can give up if it's genuinely overstaffed** — it
   stays at or above its own minimum{f' plus {surplus_buffer}' if surplus_buffer else ''} once you come off it. Shifts that are
   themselves short never appear.
4. **Everything on offer already passes validation.** Each pairing has been run through the same
   rules your bid was checked against — shifts per pay period, night and weekend minimums, rest,
   consecutive shifts, weekend group — and, on top of that, across the point where the track
   repeats: a Day at the start of Block A is checked for rest against the nights at the end of
   Block C. Nothing here can break your track.
5. **The base you're shown is one you could actually expect.** Volunteering doesn't let you take a
   base off someone who bid that day. You're only shown a base where everyone already working it
   either stays put or moves somewhere *they* rank higher — so if two people are sitting on their
   first choice, that base won't be offered to you no matter how senior you are, and what you see
   instead is what you'd really get.
6. **Choose as many or as few as you like — or none at all.** For each need you're open to, pick
   the shifts you'd be willing to give up and rank them. Ranking 1 is what you'd prefer to give up
   first.

Submitting is an **offer, not a change**. Nothing moves until an administrator approves a specific
pairing, and you'll see the status of each offer here.
""")

    with st.spinner("Loading needs and your track..."):
        report_ctx, err = load_swap_context(track_name)
    if report_ctx is None:
        st.error(err)
        return True

    needs = report_ctx['needs']
    if not needs:
        st.success(f"No below-minimum Day or Night shifts in {track_name} right now — nothing to swap onto.")
        return True

    staff_names = sorted(report_ctx['bids_by_name'].keys())
    selected_staff = st.selectbox("Select Your Name to see your swap options",
                                   [""] + staff_names, key="needs_swap_staff_select")
    if not selected_staff:
        st.info(f"{len(needs)} shift(s) are currently below minimum. Select your name to see which ones you could move onto.")
        return True

    _render_flash(_STAFF_FLASH)
    _render_staff_current_track(selected_staff, report_ctx)
    existing = _render_existing_offers(track_name, selected_staff)

    with st.spinner("Working out which needs you could cover..."):
        menu = swap_options_for_staff(selected_staff, needs, report_ctx, surplus_buffer)

    st.markdown("#### Needs you could move onto")
    if not menu:
        surplus = surplus_shifts(selected_staff, report_ctx, surplus_buffer)
        if not surplus:
            st.info(
                "None of the shifts on your track can be given up right now — every one of them "
                "would drop to or below its own minimum without you. Nothing for you to do here."
            )
        else:
            st.info(
                "There's nothing you can move onto at the moment. Either you're already working "
                "the days that are short, your role isn't what those shifts are missing, or no "
                "swap would keep your own track valid."
            )
            with st.expander("Shifts you could have given up, if a need had matched"):
                st.dataframe(pd.DataFrame([{
                    'Shift': _shift_label(s['day_label'], s['period']),
                    'Crews now': s['before'],
                    'Crews without you': s['after'],
                    'Minimum': s['minimum'],
                } for s in surplus]), use_container_width=True, hide_index=True)
        return True

    st.caption(f"{len(menu)} of the {len(needs)} open need(s) are ones you could fill.")
    for m in menu:
        m['base'] = best_base_for_need(selected_staff, m['need']['day_label'],
                                        m['need']['period'], report_ctx)

    table = pd.DataFrame([{
        'Need': _shift_label(m['need']['day_label'], m['need']['period']),
        'Priority': _PRIORITY_LABEL[need_priority(m['need'])],
        'Hypothetical Shift': m['base']['base'] if m['base'] else 'Not guaranteed',
        'Your ranking there': _rank_text(m['base']),
        'Shifts you could give up': _give_up_summary(m['options']),
    } for m in menu])

    st.dataframe(
        table.style.map(lambda v: _PRIORITY_STYLE.get(v, ''), subset=['Priority']),
        use_container_width=True, hide_index=True,
        column_config={
            'Priority': st.column_config.TextColumn(
                help="How short this shift still is once schedulers have flexed what they can. "
                     "Red needs the most help."),
            'Shifts you could give up': st.column_config.TextColumn(width="large"),
        },
    )
    st.caption(
        "**Priority** is where the help is needed most — red first. **Hypothetical Shift** is the "
        "base you could expect to work if you moved onto that day. It only ever shows a base you "
        "could take without pushing anyone already on that day onto a base they rank lower — so "
        "it isn't the base a straight seniority draft would hand you, it's one you could "
        "realistically hold."
    )

    # ── Build the offer ──
    st.markdown("#### Build your offer")
    st.caption("Pick the needs you'd consider. For each one, tick the shifts you'd be willing to "
               "give up and rank them — 1 is your first choice to give up.")

    labels = {_shift_label(m['need']['day_label'], m['need']['period']): m for m in menu}
    already = {(o['need_day'], o['need_period']) for o in existing if o['status'] == 'pending'}
    default_labels = [lbl for lbl, m in labels.items()
                      if (m['need']['day_label'], m['need']['period']) in already]

    picked = st.multiselect("Needs you'd consider moving onto:", list(labels.keys()),
                            default=default_labels, key="needs_swap_picked")

    prior_ranks = {(o['need_day'], o['need_period'], o['give_up_day'], o['give_up_period']): o['preference_rank']
                   for o in existing if o['status'] == 'pending'}

    editors = {}
    for label in picked:
        m = labels[label]
        need = m['need']
        with st.expander(f"🔁 {label}", expanded=True):
            st.markdown(_need_headline(need))
            _render_base_outlook(selected_staff, need, report_ctx)
            st.markdown("**Which of your shifts would you give up for it?**")
            rows = []
            for i, opt in enumerate(m['options'], start=1):
                key = (need['day_label'], need['period'], opt['day_label'], opt['period'])
                rows.append({
                    'Give up': _shift_label(opt['day_label'], opt['period']),
                    'Crews now': opt['before'],
                    'Crews without you': opt['after'],
                    'Minimum': opt['minimum'],
                    'Offer this': key in prior_ranks,
                    'Rank': prior_ranks.get(key, i),
                })
            editors[label] = st.data_editor(
                pd.DataFrame(rows), hide_index=True, use_container_width=True,
                key=f"needs_swap_editor_{label}",
                column_config={
                    'Give up': st.column_config.TextColumn(disabled=True, help="A shift on your track with room to spare"),
                    'Crews now': st.column_config.NumberColumn(disabled=True),
                    'Crews without you': st.column_config.NumberColumn(disabled=True, help="Stays at or above the minimum — that's why it's offered"),
                    'Minimum': st.column_config.NumberColumn(disabled=True),
                    'Offer this': st.column_config.CheckboxColumn(help="Tick to offer this shift in exchange"),
                    'Rank': st.column_config.NumberColumn(min_value=1, max_value=99, step=1, help="1 = you'd give this one up first"),
                },
            )

    notes = st.text_area("Anything you want the schedulers to know (optional):",
                         key="needs_swap_notes", max_chars=500)

    submit_col, withdraw_col = st.columns(2)
    with submit_col:
        if st.button("📤 Submit my swap offers", key="needs_swap_submit",
                     type="primary", use_container_width=True):
            offers = []
            for label in picked:
                m = labels[label]
                offers.extend(offers_from_editor(editors[label], m['need'], m['options']))

            if picked and not offers:
                st.warning(
                    "You picked a need but didn't tick any shift to give up for it, so there was "
                    "nothing to submit. Tick at least one row under each need you want — or use "
                    "**Withdraw my pending offers** if you meant to take yourself out."
                )
            else:
                ok, msg = save_need_swap_offers(track_name, selected_staff, offers, notes or None)
                _flash(_STAFF_FLASH, 'success' if ok else 'error', msg)
                st.rerun()

    with withdraw_col:
        if st.button("↩️ Withdraw my pending offers", key="needs_swap_withdraw",
                     use_container_width=True):
            ok, msg = save_need_swap_offers(track_name, selected_staff, [], None)
            _flash(_STAFF_FLASH, 'success' if ok else 'error', msg)
            st.rerun()

    return True


# ──────────────────────────────────────────────
# Streamlit UI — admin review queue
# ──────────────────────────────────────────────

_STATUS_LABEL = {'pending': 'Pending', 'approved': 'Approved',
                 'declined': 'Declined', 'superseded': 'Superseded'}


def _offers_dataframe(offers, report_ctx):
    seniority = report_ctx['ctx']['seniority_mapping']
    roles = report_ctx['ctx']['role_mapping']

    def where(offer):
        base = best_base_for_need(offer['staff_name'], offer['need_day'],
                                   offer['need_period'], report_ctx)
        return f"{base['base']} ({_rank_text(base)})" if base else "Not guaranteed"

    return pd.DataFrame([{
        'Need': _shift_label(o['need_day'], o['need_period']),
        'Staff': o['staff_name'],
        'Role': roles.get(o['staff_name'], 'Unknown'),
        'Seniority': seniority.get(o['staff_name']),
        'Would give up': _shift_label(o['give_up_day'], o['give_up_period']),
        'Their rank': o['preference_rank'],
        'Hypothetical Shift': where(o),
        'Status': _STATUS_LABEL.get(o['status'], o['status']),
        'Still applies': '' if o['status'] != 'pending' else ('Yes' if o['still_valid'] else o['stale_reason']),
        'Notes': o['staff_notes'] or '',
        'Submitted': o['submission_date'],
        'Reviewed by': o['reviewed_by'] or '',
        'Review notes': o['review_notes'] or '',
    } for o in offers])


def _render_needs_swap_window_controls(cfg):
    """Open/close the staff window and set the surplus buffer for one track cycle."""
    tn = cfg['track_name']
    is_open = bool(cfg.get('needs_swap_open'))
    buffer_now = cfg.get('needs_swap_surplus_buffer') or 0

    c1, c2 = st.columns([1, 2])
    with c1:
        new_open = st.checkbox("Swap window open to staff", value=is_open, key=f"needs_swap_open_{tn}")
        if new_open != is_open:
            update_track_config(tn, needs_swap_open=1 if new_open else 0)
            st.rerun()
    with c2:
        new_buffer = st.number_input(
            "Surplus buffer (crews above minimum)", min_value=0, max_value=5,
            value=int(buffer_now), step=1, key=f"needs_swap_buffer_{tn}",
            help="How much cushion a shift must keep to be offered as one a staff member can "
                 "leave. 0 means it only has to stay at its minimum without them; 1 means it "
                 "must stay a full crew above it.")
        if new_buffer != buffer_now:
            update_track_config(tn, needs_swap_surplus_buffer=int(new_buffer))
            st.rerun()


def _render_needs_swap_admin_tab(config_names, default_track_index):
    st.markdown("### Needs Swap Requests")
    st.caption(
        "Staff offers to move onto a below-minimum shift. Each row is one pairing — the need "
        "they'd cover and the overstaffed shift they'd give up for it, ranked by their own "
        "preference. Approving a pairing writes it straight to that person's bid track."
    )

    if not config_names:
        st.info("No track cycles exist yet. Create one in the Track Configs tab.")
        return

    track_name = st.selectbox("Track Cycle:", config_names, index=default_track_index,
                              key="needs_swap_admin_track")
    cfg = get_track_config_by_name(track_name) or {}

    _render_flash(_ADMIN_FLASH)
    _render_needs_swap_window_controls(cfg)
    st.markdown("---")

    with st.spinner("Loading bids, needs and offers..."):
        report_ctx, err = load_swap_context(track_name)
        if report_ctx is None:
            st.error(err)
            return
        offers = offers_with_status(track_name, report_ctx)

    if not offers:
        st.info(f"No staff have submitted swap offers for {track_name} yet.")
        return

    pending = [o for o in offers if o['status'] == 'pending']
    approved = [o for o in offers if o['status'] == 'approved']

    m = st.columns(4)
    m[0].metric("Staff responded", len({o['staff_name'] for o in offers}))
    m[1].metric("Pending pairings", len(pending))
    m[2].metric("Approved", len(approved))
    m[3].metric("Needs still open", len(report_ctx['needs']))

    reviewer = st.text_input("Reviewed by:", value=st.session_state.get('needs_swap_reviewer', 'Admin'),
                             key="needs_swap_reviewer")

    st.markdown("#### Pending offers, by need")
    if not pending:
        st.info("Nothing pending — every offer has been decided.")
    else:
        needs_by_key = {(n['day_label'], n['period']): n for n in report_ctx['needs']}
        by_need = {}
        for o in pending:
            by_need.setdefault((o['need_day'], o['need_period']), []).append(o)

        for key, group in sorted(by_need.items(), key=lambda kv: -len(kv[1])):
            need = needs_by_key.get(key)
            label = _shift_label(*key)
            headline = _need_headline(need) if need else f"**{label}** — no longer below minimum"
            with st.expander(f"{label} — {len(group)} offer(s)", expanded=True):
                st.markdown(headline)
                if need and need['deficit']:
                    st.caption(f"Crew mix needed: {_deficit_text(need['deficit']) or 'senior cap only'}")
                if not need:
                    st.warning("This shift is no longer below minimum — approving here would "
                               "overstaff it. Decline these unless you have another reason.")

                group.sort(key=lambda o: (o['staff_name'], o['preference_rank']))
                for o in group:
                    cols = st.columns([5, 1, 1])
                    role = report_ctx['ctx']['role_mapping'].get(o['staff_name'], 'Unknown')
                    seniority = report_ctx['ctx']['seniority_mapping'].get(o['staff_name'], '?')
                    base = best_base_for_need(o['staff_name'], o['need_day'],
                                               o['need_period'], report_ctx)
                    where = (f"hypothetical shift {base['base']} ({_rank_text(base)})" if base
                             else "no hypothetical shift can be promised")
                    line = (f"**{o['staff_name']}** ({role}, seniority {seniority}) — "
                            f"give up {_shift_label(o['give_up_day'], o['give_up_period'])} "
                            f"· their rank {o['preference_rank']} · {where}")
                    if not o['still_valid']:
                        line += f"  \n⚠️ {o['stale_reason']}"
                    if o['staff_notes']:
                        line += f"  \n💬 {o['staff_notes']}"
                    cols[0].markdown(line)
                    if cols[1].button("Approve", key=f"needs_swap_approve_{o['id']}",
                                      disabled=not o['still_valid'], use_container_width=True):
                        ok, msg = apply_offer(o, report_ctx, reviewer)
                        _flash(_ADMIN_FLASH, 'success' if ok else 'error', msg)
                        st.rerun()
                    if cols[2].button("Decline", key=f"needs_swap_decline_{o['id']}",
                                      use_container_width=True):
                        ok, msg = update_need_swap_offer_status(o['id'], 'declined', reviewer)
                        _flash(_ADMIN_FLASH, 'info' if ok else 'error',
                               f"{o['staff_name']} — {msg}")
                        st.rerun()

    uncovered = [n for n in report_ctx['needs']
                 if not any(o['status'] == 'pending' and o['need_day'] == n['day_label']
                            and o['need_period'] == n['period'] for o in offers)]
    if uncovered:
        st.markdown("#### Still-open needs nobody has offered to cover")
        st.caption("Use the Staffing Rebalance tab to see who could be asked directly.")
        st.dataframe(pd.DataFrame([{
            'Need': _shift_label(n['day_label'], n['period']),
            'Achievable': n['achievable'],
            'Minimum': n['minimum'],
            'Crew mix needed': _deficit_text(n['deficit']),
        } for n in uncovered]), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### All responses")
    all_df = _offers_dataframe(offers, report_ctx)
    st.dataframe(all_df, use_container_width=True, hide_index=True)
    _excel_download_button(all_df, "📥 Download responses as Excel",
                           f"{track_name}_needs_swap_responses",
                           key="download_needs_swap_responses", sheet_name="Swap Offers")
