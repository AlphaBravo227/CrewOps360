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
  - A shift they can **give up** must still hold that period's configured crew
    floor (needs_swap_min_day / needs_swap_min_night, default 7 Day / 5 Night)
    once they're removed from it — i.e. genuinely overstaffed, and never itself
    a need. Those floors are set apart from the cycle's own minimums, which are
    what decide whether a shift counts as a need at all.
  - Every (need, give-up) pairing is run through validate_track_comprehensive()
    on the resulting hypothetical track, plus cycle_wrap_issues() for the rest and
    consecutive-shift rules across the Block C → Block A seam, which that validator
    walks past (see its docstring). What blocks a swap is ENFORCED_RULES only:
    shifts per pay period, the per-person weekly limit (weekly_shift_limit), rest,
    consecutive shifts and the cycle seam. Night minimum, weekend minimum and
    weekend group are ADVISORY_RULES — a volunteer is explicitly allowed to drop
    below those to cover a need, and is told what it costs rather than being
    silently excluded.

Staffing Rebalance's admin candidate table runs the same two functions
(surplus_shifts and validate_swap), so the two views cannot disagree about who is
eligible for what.
"""

import html

import pandas as pd
import streamlit as st

from modules.db_utils import (
    get_bid_track_from_db,
    get_need_swap_offers,
    get_needs_swap_track_config,
    get_track_config_by_name,
    save_bid_track_to_db,
    restore_superseded_need_offers,
    save_need_swap_offers,
    set_requirement_override,
    supersede_sibling_need_offers,
    update_need_swap_offer_status,
    update_track_config,
)
from modules.nondisplacing_assignment import draft_assignment, nondisplacing_bases, rank_options
from modules.staffing_rebalance import _excel_download_button, find_shortfalls, load_report_context
from modules.track_bidding import (_bid_role_and_senior, _bidding_role_bucket,
                                   _max_possible_shifts, clear_bidding_caches)

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

DEFAULT_SWAP_FLOORS = {'Day': 7, 'Night': 5}


def needs_swap_floors(cfg):
    """
    The crew floors a shift has to keep to be given up, per period, from a track
    config. Set separately from the cycle's own min_day_staff/min_night_staff, which
    decide what counts as a *need* — the two answer different questions, and the
    floor for leaving a shift is usually the stricter of the pair.
    """
    return {
        'Day': (cfg or {}).get('needs_swap_min_day') or DEFAULT_SWAP_FLOORS['Day'],
        'Night': (cfg or {}).get('needs_swap_min_night') or DEFAULT_SWAP_FLOORS['Night'],
    }


def surplus_shifts(staff_name, report_ctx, floors=None):
    """
    Every shift in this staff member's bid track that they'd be allowed to come off
    of: a D or N day (never a preassignment) whose achievable crews stay at or above
    that period's floor (see needs_swap_floors) once they're removed.

    Returns a list of dicts: day_label, period, code, before, after, minimum — where
    'minimum' is the floor actually applied, so what the staff member is shown is the
    number the decision was made on.
    """
    bid = report_ctx['bids_by_name'].get(staff_name)
    if not bid:
        return []

    floors = floors or DEFAULT_SWAP_FLOORS
    role, is_senior = _bid_role_and_senior(
        bid, report_ctx['ctx']['role_mapping'], report_ctx['ctx']['no_matrix_mapping'])
    preassignments = _staff_preassignments(staff_name, report_ctx)
    by_label = _day_stats_by_label(report_ctx)

    shifts = []
    for day, code in (bid['track_data'] or {}).items():
        if code not in _CODE_PERIOD or day in preassignments:
            continue
        row = by_label.get(day)
        if row is None:
            continue
        period = _CODE_PERIOD[code]
        floor = floors.get(period, DEFAULT_SWAP_FLOORS[period])
        before, after = achievable_change(row, period, role, is_senior, -1)
        if after < floor:
            continue  # not enough left behind — losing them would leave this shift short
        shifts.append({
            'day_label': day, 'period': period, 'code': code,
            'before': before, 'after': after, 'minimum': floor,
        })

    day_order = {d: i for i, d in enumerate(report_ctx['days'])}
    shifts.sort(key=lambda s: day_order.get(s['day_label'], 999))
    return shifts


def _day_stats_by_label(report_ctx):
    """{day_label: day_stats row}, from the context when it was precomputed there."""
    cached = report_ctx.get('day_stats_by_label')
    if cached is not None:
        return cached
    return report_ctx['day_stats'].set_index('day_label').to_dict('index')


def _staff_preassignments(staff_name, report_ctx):
    cached = report_ctx.get('preassignments_by_name')
    if cached is not None and staff_name in cached:
        return cached[staff_name]

    from modules.track_management.preassignment import get_staff_preassignments
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


# Rules a swap must satisfy to be offered at all. Everything here is either a hard
# safety limit or the thing that keeps a swap net-zero within a pay period.
ENFORCED_RULES = ('shifts_per_pay_period', 'shifts_per_week', 'rest_requirements',
                  'consecutive_shifts', 'cycle_wrap')

# Rules deliberately NOT enforced here, though a bid had to satisfy them. Covering a
# need is worth giving up a night or a weekend for, so a volunteer is allowed to drop
# below these — the whole point is to free them to move. They're still evaluated and
# reported, so nobody gives one up without being told.
ADVISORY_RULES = ('night_minimum', 'weekend_minimum', 'weekend_group_assignment')

_ADVISORY_TEXT = {
    'night_minimum': 'drops you below your night requirement',
    'weekend_minimum': 'drops you below your weekend requirement',
    'weekend_group_assignment': 'leaves one of your weekend-group periods short',
}


def weekly_shift_limit(shifts_per_pay_period):
    """
    The most shifts one 7-day week may hold, derived from the staff member's own
    shifts-per-pay-period requirement: a pay period is two weeks, so the split is
    `spp / 2`.

    Returns None when no weekly limit applies:
      - odd `spp` can't be split evenly across the two weeks of a pay period, so
        either week is allowed to carry the extra shift;
      - a blank or zero `spp` (management, and anyone with no numeric requirement)
        has no pay-period requirement to divide in the first place.

    Deliberately kept here rather than in enhanced_track_validator, whose
    validate_shifts_per_week_limit() hard-codes "fewer than 4 per week" for
    everyone. That function still gates bid submission, the Admin Track Editor and
    the PDF/email reports, and is left exactly as it is — this stricter,
    per-person rule applies only to swap availability.
    """
    if not shifts_per_pay_period or shifts_per_pay_period % 2:
        return None
    return shifts_per_pay_period // 2


def validate_weekly_limit(combined_track, days, limit):
    """
    Per-person weekly shift cap, in the same result shape as the other rules so it
    can drop straight into a validate_track_comprehensive() result dict. Passes
    unconditionally when `limit` is None (see weekly_shift_limit).
    """
    result = {'status': True, 'details': '', 'issues': []}

    if limit is None:
        result['details'] = "No weekly limit applies (odd or unset shifts per pay period)"
        return result

    violations = []
    for i in range(0, len(days), 7):
        week_days = days[i:i + 7]
        week_num = (i // 7) + 1
        count = sum(1 for d in week_days if combined_track.get(d, "") in ("D", "N", "AT"))
        if count > limit:
            violations.append({'week': week_num, 'count': count})
            result['issues'].append(f"Week {week_num}: {count} shifts (limit: {limit})")

    if violations:
        result['status'] = False
        result['details'] = ("Weekly limit violations: "
                             + ", ".join(f"Week {v['week']}: {v['count']} shifts" for v in violations))
        result['violations'] = violations
    else:
        result['details'] = f"All weeks are at or under {limit} shifts"
    return result


def failed_rules(validation):
    """The enforced rules a validation result breaks — what actually blocks a swap."""
    return [rule for rule in ENFORCED_RULES
            if rule in validation and not validation[rule]['status']]


def validate_track_for_staff(staff_name, track_data, report_ctx, baseline_track=None,
                              preassignments=None):
    """
    Run the full track validator over `track_data` using this staff member's own
    requirements and preassignments, plus the cycle-wrap check the shared validator
    doesn't cover.

    'overall_valid' is recomputed over ENFORCED_RULES only — night minimum, weekend
    minimum and weekend group are evaluated but never block a swap (see
    ADVISORY_RULES). Anything they'd have blocked is listed under 'advisories'
    instead, for the UI to warn about.

    'shifts_per_week' is likewise replaced with this staff member's own weekly limit
    (weekly_shift_limit) rather than the shared validator's flat "fewer than 4",
    which only happens to be right for the 6-shifts-per-pay-period majority.

    `baseline_track`, when given, is the track this one is a modification of: seam
    issues and advisory shortfalls that were already there are not counted against
    the change. Someone whose bid already sits below a minimum shouldn't be warned
    about a swap that didn't cause it.

    `preassignments`, when given, replaces the staff member's own — used to test a
    hypothetical where a preassignment has moved (see Staffing Rebalance's AT
    relocation), since preassignments are re-applied on top of any track before it
    is validated.

    Returns the validate_track_comprehensive() result dict with extra 'cycle_wrap'
    and 'advisories' entries, or None when the staff member can't be evaluated (no
    numeric requirements — e.g. management).
    """
    from modules.enhanced_track_validator import create_combined_track, validate_track_comprehensive

    req = report_ctx['requirements_map'].get(staff_name)
    if not req or req.get('shifts_per_pay_period') is None:
        return None

    if preassignments is None:
        preassignments = _staff_preassignments(staff_name, report_ctx)
    days = report_ctx['days']
    spp = req.get('shifts_per_pay_period') or 0

    result = validate_track_comprehensive(
        track_data,
        shifts_per_pay_period=spp,
        night_minimum=req.get('night_minimum') or 0,
        weekend_minimum=req.get('weekend_minimum') or 0,
        preassignments=preassignments,
        days=days,
        weekend_group=req.get('weekend_group'),
    )

    # Replace the shared validator's flat "fewer than 4 per week" with this staff
    # member's own limit (see weekly_shift_limit). Only the copy of the rule inside
    # this result dict changes — validate_track_comprehensive() itself, and so every
    # other caller of it, is untouched.
    result['shifts_per_week'] = validate_weekly_limit(
        create_combined_track(track_data, preassignments), days, weekly_shift_limit(spp))

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

    # Advisories: what this swap costs that a bid wouldn't have been allowed to cost.
    # Only ones the swap itself introduces — a bid already sitting below a minimum
    # isn't this move's doing.
    already_short = set()
    if baseline_track is not None:
        base_result = validate_track_comprehensive(
            baseline_track,
            shifts_per_pay_period=req.get('shifts_per_pay_period') or 0,
            night_minimum=req.get('night_minimum') or 0,
            weekend_minimum=req.get('weekend_minimum') or 0,
            preassignments=preassignments,
            days=days,
            weekend_group=req.get('weekend_group'),
        )
        already_short = {rule for rule in ADVISORY_RULES if not base_result[rule]['status']}

    result['advisories'] = [rule for rule in ADVISORY_RULES
                            if not result[rule]['status'] and rule not in already_short]
    result['overall_valid'] = not failed_rules(result)
    return result


def swapped_track(track_data, give_up_day, need_day, need_period):
    """`track_data` with the given-up day cleared and the need day taking its shift code."""
    swapped = dict(track_data or {})
    swapped[give_up_day] = ''
    swapped[need_day] = _PERIOD_CODE[need_period]
    return swapped


def validate_swap(staff_name, give_up_day, need_day, need_period, report_ctx,
                   preassignments=None):
    """
    Would this staff member's track still be valid if they moved off `give_up_day`
    onto `need_day`? Evaluated against the bid as loaded into `report_ctx`.

    `preassignments` overrides the staff member's own, for testing a hypothetical
    where one of them has been moved.

    Returns the validate_track_comprehensive() result dict, or None when the staff
    member can't be evaluated (no bid, or no numeric requirements).
    """
    bid = report_ctx['bids_by_name'].get(staff_name)
    if not bid:
        return None
    return validate_track_for_staff(
        staff_name, swapped_track(bid['track_data'], give_up_day, need_day, need_period),
        report_ctx, baseline_track=bid['track_data'], preassignments=preassignments)


def swap_options_for_staff(staff_name, needs, report_ctx, floors=None):
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
    by_label = _day_stats_by_label(report_ctx)

    give_up_pool = surplus_shifts(staff_name, report_ctx, floors)
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
            # Copied per need — the pool is shared across needs, but what a given
            # swap costs depends on which need it's paired with.
            options.append(dict(shift, advisories=validation.get('advisories', [])))

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

@st.cache_data(ttl=15, show_spinner=False)
def load_swap_context(track_name, min_night_crews_for_sim=None):
    """
    Everything both the staff and admin views need: the Staffing Rebalance report
    context plus per-staff preassignments and the consolidated need list.

    Cached for 15s — this reloads every bid, recomputes day_stats for the full
    42-day cycle, and re-derives every need from scratch, so a pure UI toggle
    (Preview/Hide track, expanding a section) that triggers Streamlit's usual
    whole-script rerun was paying that full cost for no reason every time.
    Anything that actually changes the underlying data (an approval or a
    decline) explicitly clears this cache immediately after, so it's never
    more than one real action stale — see the two call sites in
    _render_needs_swap_admin_tab.

    Returns (context, error). context is None on failure.
    """
    from modules.db_utils import get_track_capacity_by_weekday

    report_ctx, err = load_report_context(track_name)
    if report_ctx is None:
        return None, err

    # 'preassignments_by_name' and 'day_stats_by_label' already come from
    # load_report_context — the admin candidate table needs them too.
    report_ctx['weekday_caps'] = get_track_capacity_by_weekday(track_name)

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

def _night_count(combined_track):
    """Nights in a track, counted the way validate_night_minimum() counts them."""
    return sum(1 for code in combined_track.values() if code == 'N')


def _weekend_count(combined_track):
    """Weekend shifts, counted the way validate_weekend_minimum() counts them:
    a Friday night, or any Saturday/Sunday D, N or AT."""
    total = 0
    for day, code in combined_track.items():
        if not code:
            continue
        weekday = day.split()[0] if day.split() else ''
        if weekday == 'Fri' and code == 'N':
            total += 1
        elif weekday in ('Sat', 'Sun') and code in ('D', 'N', 'AT'):
            total += 1
    return total


def record_minimum_relaxations(staff_name, track_name, track_data, report_ctx,
                                offer_id=None, reviewed_by=None):
    """
    After an approved swap, relax whatever minimums the new track now sits below.

    Covering a need is allowed to cost a night or a weekend — that is the whole point
    of ADVISORY_RULES — but the staff record still holds the original figure, so
    without this the approved track reads as invalid everywhere outside the Needs Swap
    views: the Admin Track Editor, the PDF, the email summaries. The relaxed figure is
    the count the approved track actually holds, so they are exactly at the new
    minimum and can't drop further without another approval.

    Scoped to the track cycle, with the pre-relaxation figure kept alongside, so it
    lapses with the cycle and can always be read back or restored.

    Returns a list of human-readable descriptions of what was relaxed (empty when
    nothing was).
    """
    from modules.enhanced_track_validator import create_combined_track

    req = report_ctx['requirements_map'].get(staff_name) or {}
    combined = create_combined_track(track_data, _staff_preassignments(staff_name, report_ctx))

    fields = {}
    notes = []
    for field, counted, label in (('night_minimum', _night_count(combined), 'night'),
                                   ('weekend_minimum', _weekend_count(combined), 'weekend')):
        required = req.get(field)
        if required and counted < required:
            fields[field] = counted
            notes.append(f"{label} minimum {required} → {counted}")

    if not fields:
        return []

    set_requirement_override(
        track_name, staff_name,
        night_minimum=fields.get('night_minimum'),
        weekend_minimum=fields.get('weekend_minimum'),
        original_night_minimum=req.get('night_minimum'),
        original_weekend_minimum=req.get('weekend_minimum'),
        offer_id=offer_id, created_by=reviewed_by,
    )
    return notes


def _approved_pickup_base(staff_name, offer, report_ctx):
    """
    The hypothetical shift to name in the approval email for the need just picked up
    — best_base_for_need()'s top non-displacing option, the same one the volunteer was
    shown when they offered, so the email can't promise a base they never agreed to.

    Returns (base, rank) — rank being their own 1-5/1-3 ranking for it, or None if they
    never ranked it. (None, None) when no base can be promised on that day, or when it
    can't be computed for any reason: the summary is worth sending either way.
    """
    try:
        option = best_base_for_need(staff_name, offer['need_day'], offer['need_period'], report_ctx)
    except Exception:
        return None, None
    if not option:
        return None, None
    return option['base'], option.get('rank')


def apply_offer(offer, report_ctx, reviewed_by, review_notes=None):
    """
    Approve one offer and write it to the staff member's bid track: the give-up day
    is cleared, the need day takes the need's shift code, and save_bid_track_to_db()
    versions the change into track_history like any other bid revision.

    If the new track falls below the staff member's night or weekend minimum — which a
    volunteer covering a need is allowed to do — that minimum is relaxed for this cycle
    so the approved track reads as valid across the rest of the app too. See
    record_minimum_relaxations().

    The pairing is re-validated against the bid as it stands right now — an offer
    that has gone stale (because the staff member's track or someone else's moved
    since they submitted) is refused rather than applied.

    `review_notes` is the reviewing admin's own note about the decision; it is stored
    after the automatic description of the change, not instead of it.

    Returns (success, message, details). `details` describes what was actually applied
    — the shifts moved, any minimums relaxed, how many sibling offers were superseded —
    for the approval email; it is None when nothing was applied. The admin's note is
    deliberately left out of it: that stays in the admin views.
    """
    staff_name = offer['staff_name']
    track_name = offer['track_name']

    ok, bid = get_bid_track_from_db(staff_name, track_name)
    if not ok:
        return False, f"No bid on file for {staff_name} in {track_name}.", None

    track_data = dict(bid['track_data'] or {})
    if track_data.get(offer['give_up_day']) != _PERIOD_CODE[offer['give_up_period']]:
        return False, (f"{staff_name} is no longer working {offer['give_up_period']} on "
                       f"{offer['give_up_day']} — this offer is out of date."), None
    if track_data.get(offer['need_day']):
        return False, (f"{staff_name} is already assigned on {offer['need_day']} — "
                       "this offer is out of date."), None

    # Validated against the bid exactly as it stands in the database right now, not the
    # snapshot report_ctx was built from — an earlier approval in this same review pass
    # may already have moved this person.
    swapped = swapped_track(track_data, offer['give_up_day'], offer['need_day'], offer['need_period'])
    validation = validate_track_for_staff(staff_name, swapped, report_ctx, baseline_track=track_data)
    if validation is None:
        return False, f"Could not validate a swap for {staff_name} (no requirements on file).", None
    if not validation.get('overall_valid'):
        failed = [rule.replace('_', ' ') for rule in failed_rules(validation)]
        return False, f"Swap would now break {staff_name}'s track ({', '.join(failed)}). Not applied.", None

    saved, save_msg, _ = save_bid_track_to_db(staff_name, swapped, track_name,
                                              metadata=bid.get('metadata'))
    if not saved:
        return False, save_msg, None

    relaxed = record_minimum_relaxations(staff_name, track_name, swapped, report_ctx,
                                          offer_id=offer['id'], reviewed_by=reviewed_by)

    # The automatic description of what was applied is always kept; an admin's own
    # note is appended to it rather than replacing it, so the record of the change
    # survives alongside their reasoning.
    note = (f"Moved {offer['give_up_period']} {offer['give_up_day']} → "
            f"{offer['need_period']} {offer['need_day']}")
    if relaxed:
        note += f" ({'; '.join(relaxed)})"
    if review_notes and review_notes.strip():
        note += f" — {review_notes.strip()}"
    update_need_swap_offer_status(offer['id'], 'approved', reviewed_by, note)
    superseded = supersede_sibling_need_offers(offer['id'])

    message = (f"Applied: {staff_name} moves off {offer['give_up_period']} {offer['give_up_day']} "
               f"onto {offer['need_period']} {offer['need_day']}.")
    if superseded:
        message += f" {superseded} other option{'s' if superseded != 1 else ''} for that need superseded."
    if relaxed:
        message += (f" Relaxed for this cycle: {'; '.join(relaxed)}. The original figures are "
                    "kept and restored when the cycle changes.")

    details = {
        'need_day': offer['need_day'],
        'need_period': offer['need_period'],
        'give_up_day': offer['give_up_day'],
        'give_up_period': offer['give_up_period'],
        'relaxations': relaxed,
        'superseded': superseded,
        'reviewed_by': reviewed_by,
    }
    details['hypothetical_base'], details['hypothetical_base_rank'] = \
        _approved_pickup_base(staff_name, offer, report_ctx)
    return True, message, details


def _restore_minimums_after_rescind(staff_name, track_name, reverted_track, report_ctx,
                                    offer_id):
    """
    Put back whatever this approval relaxed, and no more.

    The relaxation is cleared only when it is this offer's own, or carries no offer at
    all — a figure relaxed by a different approval stays, since that swap still stands.
    Once cleared, the reverted
    track is measured against the pre-relaxation figures again: where an earlier swap
    on this same cycle already put the person below one, the relaxation is re-recorded
    at what they actually hold, so undoing this swap doesn't hand back a minimum the
    other approval had already spent.

    Returns a list of human-readable descriptions of what changed (empty when nothing
    was relaxed in the first place).
    """
    from modules.db_utils import clear_requirement_override, get_requirement_overrides
    from modules.enhanced_track_validator import create_combined_track

    entry = get_requirement_overrides(track_name).get(staff_name)
    if not entry:
        return []
    if entry.get('offer_id') is not None and entry.get('offer_id') != offer_id:
        return ["left the minimum relaxation in place — it was granted by another approval, "
                "not this one"]

    req = report_ctx['requirements_map'].get(staff_name) or {}
    # requirements_map already carries the relaxed figures (build_requirements_df applies
    # the active cycle's overrides), so the pre-relaxation figure is the override row's
    # own original_*; a field that was never relaxed reads true from the map.
    originals = {
        field: (entry.get(f'original_{field}') if entry.get(field) is not None else req.get(field))
        for field in ('night_minimum', 'weekend_minimum')
    }

    clear_requirement_override(track_name, staff_name)

    combined = create_combined_track(reverted_track, _staff_preassignments(staff_name, report_ctx))
    counts = {'night_minimum': _night_count(combined), 'weekend_minimum': _weekend_count(combined)}

    still_short, notes = {}, []
    for field, label in (('night_minimum', 'night'), ('weekend_minimum', 'weekend')):
        required = originals.get(field)
        if required and counts[field] < required:
            still_short[field] = counts[field]
            notes.append(f"{label} minimum still relaxed to {counts[field]} of {required} by an "
                         f"earlier approval")

    if still_short:
        # offer_id is deliberately left empty: the residue belongs to whichever earlier
        # approval spent it, not to the offer being rescinded now, and a relaxation with
        # no offer against it is one a later rescission recomputes rather than skips.
        set_requirement_override(
            track_name, staff_name,
            night_minimum=still_short.get('night_minimum'),
            weekend_minimum=still_short.get('weekend_minimum'),
            original_night_minimum=originals.get('night_minimum'),
            original_weekend_minimum=originals.get('weekend_minimum'),
            offer_id=None,
        )
        return notes

    restored = [f"{label} minimum {originals[field]}" for field, label in
                (('night_minimum', 'night'), ('weekend_minimum', 'weekend'))
                if entry.get(field) is not None and originals.get(field)]
    return [f"restored {', '.join(restored)}"] if restored else []


def rescind_offer(offer, report_ctx, reviewed_by, reason=None):
    """
    Undo a decision on one offer and put it back in the pending queue.

    Rescinding a decline changes nothing but the offer's own status. Rescinding an
    approval also puts the staff member's bid track back the way it was — the need day
    is cleared, the given-up day takes its shift code back, and save_bid_track_to_db()
    versions the reversal into track_history like any other revision — then restores
    whatever minimum this approval relaxed and re-opens the options it superseded.

    The track is only reverted when it still holds exactly what the approval wrote. If
    the staff member has been moved since — by another approval, a re-bid, or an admin
    edit — the reversal is refused rather than guessed at, because clearing the need day
    could then be undoing someone else's change.

    `reason` is the admin's own note about the rescission; like a review note it is kept
    on the offer and never emailed.

    Returns (success, message, details). `details` describes what was put back, for the
    notification email; it is None when nothing was rescinded.
    """
    staff_name = offer['staff_name']
    track_name = offer['track_name']
    previous_status = offer['status']

    if previous_status not in ('approved', 'declined'):
        return False, f"Only an approved or declined offer can be rescinded (this one is {previous_status}).", None

    note = f"Rescinded (was {previous_status}) by {reviewed_by}"
    details = {
        'need_day': offer['need_day'],
        'need_period': offer['need_period'],
        'give_up_day': offer['give_up_day'],
        'give_up_period': offer['give_up_period'],
        'previous_status': previous_status,
        'reverted': False,
        'reviewed_by': reviewed_by,
    }

    if previous_status == 'approved':
        ok, bid = get_bid_track_from_db(staff_name, track_name)
        if not ok:
            return False, f"No bid on file for {staff_name} in {track_name}.", None

        track_data = dict(bid['track_data'] or {})
        if track_data.get(offer['need_day']) != _PERIOD_CODE[offer['need_period']]:
            return False, (f"{staff_name} is no longer working {offer['need_period']} on "
                           f"{offer['need_day']}, so this approval can't be safely reversed — "
                           "their track has changed since it was applied."), None
        if track_data.get(offer['give_up_day']):
            return False, (f"{staff_name} is already assigned again on {offer['give_up_day']}, so "
                           "reversing this approval would double-book them."), None

        reverted = dict(track_data)
        reverted[offer['need_day']] = ''
        reverted[offer['give_up_day']] = _PERIOD_CODE[offer['give_up_period']]

        saved, save_msg, _ = save_bid_track_to_db(staff_name, reverted, track_name,
                                                  metadata=bid.get('metadata'))
        if not saved:
            return False, save_msg, None

        minimum_notes = _restore_minimums_after_rescind(staff_name, track_name, reverted,
                                                        report_ctx, offer['id'])
        reopened = restore_superseded_need_offers(offer['id'])
        details['reverted'] = True
        details['reopened'] = reopened
        if minimum_notes:
            note += f" ({'; '.join(minimum_notes)})"
    else:
        minimum_notes, reopened = [], 0

    if reason and reason.strip():
        note += f" — {reason.strip()}"
    update_need_swap_offer_status(offer['id'], 'pending', None, note)

    message = (f"Rescinded: {staff_name}'s {previous_status} offer for "
               f"{offer['need_period']} {offer['need_day']} is back in the pending queue.")
    if previous_status == 'approved':
        message += (f" Their track is back the way it was — working {offer['give_up_period']} "
                    f"{offer['give_up_day']}, off {offer['need_day']}.")
        if minimum_notes:
            message += f" Minimums: {'; '.join(minimum_notes)}."
        if reopened:
            message += (f" {reopened} superseded option{'s' if reopened != 1 else ''} for that need "
                        "re-opened.")
    return True, message, details


def offers_with_status(track_name, report_ctx):
    """
    All offers for a cycle, each annotated with whether it would still apply cleanly
    right now — so an admin reviewing a queue can tell a live offer from one that
    another approval has already invalidated.

    Adds to each offer dict: still_valid (bool), stale_reason (str or '').
    """
    by_label = _day_stats_by_label(report_ctx)

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
                failed = [rule.replace('_', ' ') for rule in failed_rules(validation)]
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


_WEEKDAY_ORDER = {d: i for i, d in enumerate(['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])}


def _week_key(day_label):
    """(block, week_num) e.g. ('B', '4') from 'Sun B 4' — identifies one Sun-Sat week."""
    parts = day_label.split()
    return (parts[1], parts[2]) if len(parts) == 3 else (day_label, '')


def _week_days(week_key, all_days):
    """Every day_label in `all_days` belonging to one Sun-Sat week, Sun-first."""
    days = [d for d in all_days if _week_key(d) == week_key]
    days.sort(key=lambda d: _WEEKDAY_ORDER.get(d.split()[0], 99))
    return days


def _give_up_summary(options, limit=6):
    """'3 — Sun A1 N, Wed A1 D, Thu B3 D' for the shifts on offer against a need."""
    shown = [_compact_shift(o['day_label'], o['period']) for o in options[:limit]]
    text = f"{len(options)} — " + ", ".join(shown)
    if len(options) > limit:
        text += f", +{len(options) - limit} more"
    return text


def _advisory_text(advisories):
    """'drops you below your night requirement' — what a give-up costs, or '' if nothing."""
    if not advisories:
        return ""
    parts = [_ADVISORY_TEXT[rule] for rule in advisories if rule in _ADVISORY_TEXT]
    if not parts:
        return ""
    text = parts[0]
    for extra in parts[1:]:
        text += "; " + extra
    return text[0].upper() + text[1:]


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


def _render_staff_track_table(staff_name, report_ctx, menu):
    """
    HTML for the staff view's 'Schedule Details': the usual Assignment row —
    each worked D/N now followed by its expected base, from the same per-day
    seniority draft the admin Preview track panel uses — plus a new Open Needs
    row marking any day/period this staff member is eligible to move onto, with
    the hypothetical base and, on hover, the same give-up summary shown in the
    'Needs you could move onto' table below.
    """
    bid = report_ctx['bids_by_name'][staff_name]
    track_data = bid['track_data'] or {}
    preassignments = _staff_preassignments(staff_name, report_ctx)
    role, _is_senior = _bid_role_and_senior(
        bid, report_ctx['ctx']['role_mapping'], report_ctx['ctx']['no_matrix_mapping'])
    role_bucket = _bidding_role_bucket(role)

    need_by_cell = {(m['need']['day_label'], m['need']['period']): m for m in menu}
    days = report_ctx['days']

    parts = [_NSWP_STYLE, '<div class="nswp-track-wrap">']
    for block_idx, block in enumerate(['A', 'B', 'C']):
        block_days = days[block_idx * 14: block_idx * 14 + 14]
        if not block_days:
            continue

        parts.append(f'<div class="nswp-track-block"><div class="nswp-track-block-label">'
                     f'Block {block}</div><div class="nswp-track-grid">')
        parts.append('<div class="nswp-track-rowhead"></div>')
        for i, day in enumerate(block_days):
            day_parts = day.split()
            tag = f"{day_parts[0]} {day_parts[1]}{day_parts[2]}" if len(day_parts) == 3 else day
            parts.append(f'<div class="nswp-track-daylabel" title="{html.escape(day)}">'
                         f'{html.escape(tag)}</div>')

        parts.append('<div class="nswp-track-rowhead">Assignment</div>')
        for day in block_days:
            code = track_data.get(day)
            if code == 'D':
                base = _expected_base_for_day(staff_name, day, 'Day', role_bucket, report_ctx)
                text = f'D ({html.escape(base)})' if base else 'D'
                parts.append(f'<div class="nswp-track-cell day">{text}</div>')
            elif code == 'N':
                base = _expected_base_for_day(staff_name, day, 'Night', role_bucket, report_ctx)
                text = f'N ({html.escape(base)})' if base else 'N'
                parts.append(f'<div class="nswp-track-cell night">{text}</div>')
            elif day in preassignments:
                parts.append(f'<div class="nswp-track-cell pre">Pre: {html.escape(str(preassignments[day]))}</div>')
            else:
                parts.append('<div class="nswp-track-cell"></div>')

        parts.append('<div class="nswp-track-rowhead">Open Needs</div>')
        for i, day in enumerate(block_days):
            m = need_by_cell.get((day, 'Day')) or need_by_cell.get((day, 'Night'))
            if not m:
                parts.append('<div class="nswp-track-cell"></div>')
                continue
            period = m['need']['period']
            code_letter = 'D' if period == 'Day' else 'N'
            base = best_base_for_need(staff_name, day, period, report_ctx)
            text = f'{code_letter} ({html.escape(base["base"])})' if base else code_letter
            give_up_text = html.escape(_give_up_summary(m['options']))
            tip_cls = 'nswp-tooltip-left' if i < 2 else ('nswp-tooltip-right' if i > 11 else '')
            parts.append(
                f'<div class="nswp-cell nswp-track-cell need" tabindex="0">{text}'
                f'<span class="nswp-tooltip {tip_cls}">Shifts you could give up: {give_up_text}</span>'
                f'</div>'
            )
        parts.append('</div></div>')  # .nswp-track-grid, .nswp-track-block

    parts.append('</div>')  # .nswp-track-wrap
    return ''.join(parts)


def _render_staff_current_track(staff_name, report_ctx, menu):
    bid = report_ctx['bids_by_name'][staff_name]
    with st.expander("📍 My current track for this cycle", expanded=True):
        st.caption(f"Submitted {bid['submission_date']} (version {bid['version']}). "
                   "This is the track your swap options are measured against.")
        st.markdown(_render_staff_track_table(staff_name, report_ctx, menu), unsafe_allow_html=True)


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
    floors = needs_swap_floors(cfg)

    # Distinct green banner — this section shares the Track Bidding page with the
    # bid itself (blue), and the two are easy to confuse. Bidding builds a track;
    # this trades a shift on a track that's already bid.
    from modules.ui_components import render_section_banner
    render_section_banner(
        "🔁 Track Needs — Swap Opportunities",
        subtitle=f"Open for {track_name}. Bidding for {track_name} is already done — this is where you "
                 f"volunteer to move onto a shift that came out short, and give up one of your own in "
                 f"exchange. It does not change or replace your bid.",
        eyebrow="Post-bid · volunteer to cover a need",
        accent="#28a745",
        background="#eefaf1",
    )
    with st.expander("📖 How this works"):
        st.markdown(f"""
Some shifts in **{track_name}** came out of bidding below the minimum crew count. Here is a place that you can volunteer to move onto one of those needs, and give up a shift on your own track in exchange.

1. **Pick your name.** You'll see your submitted track for this cycle, and every need you
   personally could move onto.
2. **A need only shows up for you if all of this is true:**
   - You're completely off that day already.
   - Your role is what that shift is actually short of — moving you there raises the number
     of crews it can put in the air.
   - You have at least one shift you could give up in exchange.
3. **A shift only shows up as something you can give up if it's genuinely overstaffed** — it still
   has to hold its staffing level once you come off it. Shifts that are already short, or that your
   leaving would leave short, never appear.
4. **Everything on offer already passes the rules that matter.** Each pairing is checked for
   shifts per pay period, the weekly shift limit, rest, and consecutive shifts — including across
   the point where the track repeats, so a Day at the start of Block A is checked for rest against
   the nights at the end of Block C. Nothing here can put you over a limit.
5. **If you give up a night or a weekend to fill a need, you won't need to make it up elsewhere.**
   Those minimums don't block a swap here — covering the need is worth more. If a particular trade
   would put you under your night or weekend minimum, or leave a weekend-group period short, it's
   flagged in the **Heads up** column so you know what you're giving up before you offer it.
6. **The base you're shown is one you could actually expect.** Volunteering doesn't let you take a
   base off someone who bid that day. You're only shown a base where everyone already working it
   either stays put or moves somewhere *they* rank higher — so if two people are sitting on their
   first choice, that base won't be offered to you no matter how senior you are, and what you see
   instead is what you'd really get.
7. **Choose as many or as few as you like — or none at all.** For each need you're open to, pick
   the shifts you'd be willing to give up and rank them. Ranking 1 is what you'd prefer to give up
   first.

Submitting is an **offer, not a change**. Nothing moves until management approves a specific
pairing, and you'll see the status of each offer here and receive email when one is approved or declined. Approved offers are applied to your track immediately, and supersede any other offers for the same need.
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

    with st.spinner("Working out which needs you could cover..."):
        menu = swap_options_for_staff(selected_staff, needs, report_ctx, floors)

    _render_staff_current_track(selected_staff, report_ctx, menu)
    existing = _render_existing_offers(track_name, selected_staff)

    st.markdown("#### Needs you could move onto")
    if not menu:
        surplus = surplus_shifts(selected_staff, report_ctx, floors)
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
                    'Heads up': _advisory_text(opt.get('advisories')),
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
                    'Heads up': st.column_config.TextColumn(
                        disabled=True, width="medium",
                        help="Giving up this shift is allowed even if it puts you under your "
                             "night or weekend minimum — this just tells you when it does"),
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


# Offer an admin has clicked Approve/Decline on but not yet confirmed a note for.
_ADMIN_REVIEW_ACTION = 'needs_swap_review_action'


def _queue_review_action(offer_id, action):
    """Remember which offer the admin is deciding on, so the note box opens after the rerun."""
    st.session_state[_ADMIN_REVIEW_ACTION] = {'offer_id': offer_id, 'action': action}


def _clear_review_action():
    st.session_state.pop(_ADMIN_REVIEW_ACTION, None)


# Which statuses each action is a legal next step from: approving or declining is
# something you do to an offer nobody has decided yet, rescinding is something you do
# to one somebody has.
_ACTION_STATUSES = {'approve': ('pending',), 'decline': ('pending',),
                    'rescind': ('approved', 'declined')}


def _pending_review_action(offers):
    """
    (offer, 'approve'|'decline'|'rescind') for the decision awaiting a note, or
    (None, None).

    An offer whose status has moved on since the button was pressed — decided in
    another tab, superseded by an approval, already rescinded — drops out of the queue
    rather than reopening the note box against a state that no longer holds.
    """
    queued = st.session_state.get(_ADMIN_REVIEW_ACTION)
    if not queued:
        return None, None
    offer = next((o for o in offers if o['id'] == queued['offer_id']), None)
    if offer is None or offer['status'] not in _ACTION_STATUSES.get(queued['action'], ()):
        _clear_review_action()
        return None, None
    return offer, queued['action']


def _staff_email(staff_name, report_ctx):
    """
    A staff member's email address for a decision notification: the roster figure the
    rest of bidding already notifies on, falling back to the staff database directly.
    None when there is nothing on file.
    """
    email = (report_ctx.get('requirements_map', {}).get(staff_name) or {}).get('email')
    if email:
        return email
    try:
        from modules.staff_database import get_email
        return get_email(staff_name)
    except Exception:
        return None


def _notify_decision(offer, decision, report_ctx, reviewer, details=None):
    """
    Email the staff member and the admin recipients what has happened to this offer —
    a summary of the change that was applied on an approval, a plain note that nothing
    changed on a decline, and what went back on a rescission.

    The admin's review note is never sent; it stays in the admin views for reference.

    The decision is already committed to the database by the time this runs, so a
    failure to send is reported back to the admin rather than raised: an unsent email
    must not look like an unapplied swap.

    Returns a short status sentence to append to the admin's on-screen confirmation.
    """
    details = dict(details or {})
    details.setdefault('need_day', offer['need_day'])
    details.setdefault('need_period', offer['need_period'])
    details.setdefault('give_up_day', offer['give_up_day'])
    details.setdefault('give_up_period', offer['give_up_period'])
    details.setdefault('reviewed_by', reviewer)

    try:
        from modules.email_notifications import send_needs_swap_decision_notification
        sent, msg = send_needs_swap_decision_notification(
            offer['staff_name'], _staff_email(offer['staff_name'], report_ctx),
            offer['track_name'], decision, details)
    except Exception as e:
        return f"⚠️ The notification email failed to send: {e}"
    return f"📧 {msg}" if sent else f"⚠️ {msg}"


def _decision_details_for(offer, report_ctx, offers=None):
    """
    Rebuild the notification details for a decision already on the record, so it can be
    sent again without the original call's return value.

    Everything is read back from live state rather than remembered: the hypothetical
    shift from the same non-displacing calculation, the relaxation from the override row
    this offer wrote, the superseded count from the sibling offers themselves. A resend
    therefore describes the swap as it stands now, which is what the staff member needs.
    """
    from modules.db_utils import get_requirement_overrides

    details = {
        'need_day': offer['need_day'],
        'need_period': offer['need_period'],
        'give_up_day': offer['give_up_day'],
        'give_up_period': offer['give_up_period'],
        'reviewed_by': offer['reviewed_by'],
    }
    if offer['status'] != 'approved':
        return details

    details['hypothetical_base'], details['hypothetical_base_rank'] = \
        _approved_pickup_base(offer['staff_name'], offer, report_ctx)

    entry = get_requirement_overrides(offer['track_name']).get(offer['staff_name']) or {}
    if entry.get('offer_id') == offer['id']:
        details['relaxations'] = [
            f"{label} minimum {entry[f'original_{field}']} → {entry[field]}"
            for field, label in (('night_minimum', 'night'), ('weekend_minimum', 'weekend'))
            if entry.get(field) is not None and entry.get(f'original_{field}') is not None
        ]

    siblings = offers if offers is not None else get_need_swap_offers(
        offer['track_name'], staff_name=offer['staff_name'])
    details['superseded'] = sum(
        1 for o in siblings
        if o['id'] != offer['id'] and o['status'] == 'superseded'
        and o['staff_name'] == offer['staff_name'] and o['need_day'] == offer['need_day']
        and o['need_period'] == offer['need_period'])
    return details


def _resend_decision_notification(offer, report_ctx, offers=None):
    """
    Send the approval or decline notification for this offer again — same message, built
    from where the offer stands now. For when the first one bounced, went to a stale
    address, or the staff member never saw it.

    Returns a status sentence for the admin's confirmation.
    """
    if offer['status'] not in ('approved', 'declined'):
        return "⚠️ Only an approved or declined offer has a notification to resend."
    details = _decision_details_for(offer, report_ctx, offers)
    return _notify_decision(offer, offer['status'], report_ctx,
                            offer['reviewed_by'] or 'Management', details)


def _commit_review_action(offer, action, report_ctx, reviewer, note):
    """Apply, decline or rescind the offer, storing the admin's note with the decision,
    and email the staff member and the admins either way — without the note."""
    note = (note or '').strip() or None
    if action == 'rescind':
        ok, msg, details = rescind_offer(offer, report_ctx, reviewer, reason=note)
        if ok:
            # An approval that was reversed has moved the bid track back, so the
            # day_stats/needs cache is stale in exactly the way an approval leaves it.
            if details.get('reverted'):
                clear_bidding_caches()
            msg += " " + _notify_decision(offer, 'rescinded', report_ctx, reviewer, details)
        _flash(_ADMIN_FLASH, 'success' if ok else 'error', msg)
        _clear_review_action()
        return
    if action == 'approve':
        ok, msg, details = apply_offer(offer, report_ctx, reviewer, review_notes=note)
        if ok:
            clear_bidding_caches()
            msg += " " + _notify_decision(offer, 'approved', report_ctx, reviewer, details)
        _flash(_ADMIN_FLASH, 'success' if ok else 'error', msg)
    else:
        # No cache to clear here — declining only changes the offer's own status
        # (fetched fresh every render regardless), never the bid track the
        # day_stats/needs cache is keyed on.
        ok, msg = update_need_swap_offer_status(offer['id'], 'declined', reviewer, note)
        if ok:
            msg += " " + _notify_decision(offer, 'declined', report_ctx, reviewer)
        _flash(_ADMIN_FLASH, 'info' if ok else 'error', f"{offer['staff_name']} — {msg}")
    _clear_review_action()


_ACTION_WORD = {'approve': 'Approving', 'decline': 'Declining', 'rescind': 'Rescinding'}
_ACTION_BUTTON = {'approve': 'Approve offer', 'decline': 'Decline offer',
                  'rescind': 'Rescind decision'}
_ACTION_PLACEHOLDER = {
    'approve': "Why this one was taken — crew mix, who else offered, anything worth "
               "remembering later.",
    'decline': "Why this one wasn't taken — so the reasoning is on the record.",
    'rescind': "Why the decision is being undone — so the record shows what changed and why.",
}
_ACTION_EMAIL_SUMMARY = {
    'approve': 'a summary of the change applied to their track',
    'decline': 'a note that this option was not selected',
    'rescind': 'a note that the decision was undone, and what went back',
}


def _render_review_note_body(offer, action, report_ctx, reviewer):
    """The note box itself: what is being decided, a place to say why, confirm or cancel."""
    st.markdown(
        f"**{offer['staff_name']}** would move onto "
        f"**{_shift_label(offer['need_day'], offer['need_period'])}** and give up "
        f"**{_shift_label(offer['give_up_day'], offer['give_up_period'])}** "
        f"(their rank {offer['preference_rank']})."
    )
    if offer['staff_notes']:
        st.caption(f"💬 Their note: {offer['staff_notes']}")

    if action == 'rescind':
        if offer['status'] == 'approved':
            st.warning(
                f"This puts {offer['staff_name']}'s track back the way it was — they work "
                f"**{_shift_label(offer['give_up_day'], offer['give_up_period'])}** again and come "
                f"off **{_shift_label(offer['need_day'], offer['need_period'])}**, which goes back "
                "to being an open need. Any minimum this approval relaxed is restored, and the "
                "options it superseded are re-opened."
            )
        else:
            st.info("Nothing changed on their track when this was declined, so nothing is put "
                    "back — the offer simply returns to the pending queue.")
        st.caption("Either way the offer becomes pending again and can be decided afresh.")
    elif not offer['still_valid']:
        st.warning(offer['stale_reason'])

    note = st.text_area(
        "Notes",
        key=f"needs_swap_review_note_{offer['id']}_{action}",
        placeholder=_ACTION_PLACEHOLDER[action],
        help="Optional. Stored with the decision and shown in the All responses table "
             "below. Staff don't see it — it is never included in the notification email.",
    )

    st.caption(
        f"{_ACTION_WORD[action]} emails {offer['staff_name']} and the admin recipients — "
        f"{_ACTION_EMAIL_SUMMARY[action]}. Your note above stays here."
    )

    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button(_ACTION_BUTTON[action],
                          key=f"needs_swap_review_confirm_{offer['id']}_{action}",
                          type="primary", use_container_width=True):
        _commit_review_action(offer, action, report_ctx, reviewer, note)
        st.rerun()
    if cancel_col.button("Cancel", key=f"needs_swap_review_cancel_{offer['id']}_{action}",
                         use_container_width=True):
        _clear_review_action()
        st.rerun()


def _render_review_note_prompt(offers, report_ctx, reviewer):
    """
    Ask for a note before an approve or decline actually happens.

    Shown as a modal where the installed Streamlit has one (st.dialog, or its
    experimental_dialog spelling on older versions); otherwise as a bordered box at
    the top of the queue, which is why it is rendered from the top level of the tab
    rather than from inside the offer's own row.
    """
    offer, action = _pending_review_action(offers)
    if offer is None:
        return

    title = (f"{_ACTION_BUTTON[action].split()[0]} — {offer['staff_name']}, "
             f"{_shift_label(offer['need_day'], offer['need_period'])}")
    dialog = getattr(st, 'dialog', None) or getattr(st, 'experimental_dialog', None)
    if dialog is None:
        try:
            box = st.container(border=True)
        except TypeError:  # border= predates the Streamlit floor this app supports
            box = st.container()
        with box:
            st.markdown(f"#### {title}")
            _render_review_note_body(offer, action, report_ctx, reviewer)
        return

    @dialog(title)
    def _review_note_dialog():
        _render_review_note_body(offer, action, report_ctx, reviewer)

    _review_note_dialog()


def _give_up_impact(offer, report_ctx, by_label):
    """
    (before, after, role) achievable crews for the give-up shift's period if this
    offer's staff member actually comes off it — recomputed against report_ctx's
    live day_stats, not whatever the picture looked like when they submitted, so
    an approval earlier in the same review pass is reflected. None if the staff
    member's bid or the day itself can't be found.
    """
    bid = report_ctx['bids_by_name'].get(offer['staff_name'])
    row = by_label.get(offer['give_up_day'])
    if not bid or row is None:
        return None
    role, is_senior = _bid_role_and_senior(
        bid, report_ctx['ctx']['role_mapping'], report_ctx['ctx']['no_matrix_mapping'])
    before, after = achievable_change(row, offer['give_up_period'], role, is_senior, -1)
    return before, after, role


def _give_up_impact_text(impact):
    """'−1 crew (6 → 5)' or 'No crew lost — extra medic' for a give-up shift's staffing cost."""
    if impact is None:
        return "Unknown"
    before, after, role = impact
    if after < before:
        drop = before - after
        return f"−{drop} crew{'s' if drop != 1 else ''} ({before} → {after})"
    return f"No crew lost — extra {role}"


def _pickup_impact(offer, report_ctx, by_label):
    """(before, after) achievable crews for the need's period if this offer's staff
    member actually moves onto it — the mirror of _give_up_impact for the other side
    of the swap."""
    bid = report_ctx['bids_by_name'].get(offer['staff_name'])
    row = by_label.get(offer['need_day'])
    if not bid or row is None:
        return None
    role, is_senior = _bid_role_and_senior(
        bid, report_ctx['ctx']['role_mapping'], report_ctx['ctx']['no_matrix_mapping'])
    before, after = achievable_change(row, offer['need_period'], role, is_senior, +1)
    return before, after


def _pickup_impact_text(impact):
    """'4 → 5 crews' or 'No change — role isn't the bottleneck' for a pickup's staffing gain."""
    if impact is None:
        return "Unknown"
    before, after = impact
    if after > before:
        return f"{before} → {after} crews"
    return f"No change — role isn't the bottleneck ({before} crews)"


def _expected_base_for_day(staff_name, day_label, period, role_bucket, report_ctx):
    """
    This staff member's expected base for a day/period they're actually working,
    via the same seniority draft Bid Roster and Base Analysis use — cheap because
    it only runs the draft for this one day/period, not the whole cycle.
    """
    roster = day_roster(day_label, period, role_bucket, report_ctx)
    assignment = draft_assignment(roster, period, report_ctx['all_base_prefs'],
                                  report_ctx['base_shift_counts'])
    return (assignment.get(staff_name) or {}).get('base')


_NSWP_STYLE = """
<style>
.nswp-wrap { font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif; }
.nswp-stale {
  font-size: 12px; color: #8a1c12; background: #fdecea; padding: 6px 10px;
  border-radius: 6px; margin-bottom: 10px;
}
.nswp-week { margin-bottom: 14px; }
.nswp-week-label {
  font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  color: #6b7a86; margin-bottom: 6px; font-weight: 600;
}
.nswp-grid { display: grid; grid-template-columns: 42px repeat(7, 1fr); gap: 4px; }
.nswp-grid-wide-label { grid-template-columns: 80px repeat(7, 1fr); }
.nswp-rowhead {
  display: flex; align-items: center; font-size: 10px; letter-spacing: 0.05em;
  text-transform: uppercase; color: #8592a0;
}
.nswp-daylabel { text-align: center; font-size: 11px; font-weight: 600; color: #384552; padding-bottom: 4px; }
.nswp-cell {
  position: relative; min-height: 40px; border-radius: 6px; border: 1px dashed #d7dee3;
  display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 1px;
}
.nswp-code { font-weight: 700; font-size: 16px; line-height: 1; }
.nswp-base { font-size: 8px; opacity: 0.85; }
.nswp-day { background: #66bb6a; color: #12300f; border-color: transparent; }
.nswp-night { background: #1976d2; color: #fff; border-color: transparent; }
.nswp-at { background: #898781; color: #fff; border-color: transparent; }
.nswp-drop {
  opacity: 0.55; border: 1.5px dashed #c9463a !important; cursor: help;
  background-image: repeating-linear-gradient(-45deg, rgba(0,0,0,0.12) 0 6px, transparent 6px 12px);
}
.nswp-drop .nswp-code { text-decoration: line-through; text-decoration-color: #c9463a; text-decoration-thickness: 2px; }
.nswp-pickup { background: rgba(102,187,106,0.14); border: 1.5px dashed #66bb6a; color: #12300f; cursor: help; }
.nswp-pickup .nswp-code::after { content: "+"; margin-left: 1px; }
.nswp-tooltip {
  position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%) translateY(4px);
  width: max-content; max-width: 180px; background: #16232e; color: #eef2f4; font-size: 11px;
  font-weight: 400; line-height: 1.4; text-align: left; padding: 8px 10px; border-radius: 8px;
  box-shadow: 0 8px 24px -8px rgba(0,0,0,0.35); opacity: 0; pointer-events: none;
  transition: opacity 0.12s ease, transform 0.12s ease; z-index: 30;
}
.nswp-tooltip::after {
  content: ""; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
  border: 5px solid transparent; border-top-color: #16232e;
}
.nswp-tooltip-left { left: 0; transform: translateX(0) translateY(4px); }
.nswp-tooltip-left::after { left: 16px; transform: translateX(-50%); }
.nswp-tooltip-right { left: auto; right: 0; transform: translateX(0) translateY(4px); }
.nswp-tooltip-right::after { left: auto; right: 16px; transform: translateX(50%); }
.nswp-cell:hover .nswp-tooltip, .nswp-cell:focus-visible .nswp-tooltip { opacity: 1; transform: translateX(-50%) translateY(0); }
.nswp-cell:hover .nswp-tooltip-left, .nswp-cell:focus-visible .nswp-tooltip-left,
.nswp-cell:hover .nswp-tooltip-right, .nswp-cell:focus-visible .nswp-tooltip-right { transform: translateX(0) translateY(0); }
.nswp-legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; font-size: 11px; color: #6b7a86; }
.nswp-swatch { display: inline-block; width: 11px; height: 11px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }

/* Schedule Details: the staff view's own current-track table (Assignment +
   Open Needs rows). Bordered like the st.dataframe grid it replaces — every
   cell keeps its own 1px border with zero gap between them, the same trick
   an HTML <table> gets for free, so the block still reads as one gridded
   table instead of a row of loose boxes. */
.nswp-track-wrap { font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif; }
.nswp-track-block { margin-bottom: 20px; }
.nswp-track-block-label { font-size: 14px; font-weight: 700; margin: 4px 0 8px; }
.nswp-track-grid {
  display: grid; grid-template-columns: 92px repeat(14, minmax(0, 1fr)); gap: 0;
  border-top: 1px solid #d5d8dc; border-left: 1px solid #d5d8dc;
}
.nswp-track-rowhead, .nswp-track-daylabel, .nswp-track-cell {
  border-right: 1px solid #d5d8dc; border-bottom: 1px solid #d5d8dc; box-sizing: border-box;
}
.nswp-track-rowhead, .nswp-track-daylabel { background: #f0f2f6; }
.nswp-track-rowhead {
  display: flex; align-items: center; font-size: 12px; font-weight: 600; color: #31333f;
  padding: 4px 8px; min-height: 26px;
}
.nswp-track-daylabel {
  text-align: center; font-size: 11px; font-weight: 600; color: #31333f; padding: 5px 2px;
}
.nswp-track-cell {
  min-height: 32px; display: flex; align-items: center; justify-content: center;
  text-align: center; font-size: 11px; padding: 2px; line-height: 1.25; color: #31333f;
}
.nswp-track-cell.day { background: #d4edda; }
.nswp-track-cell.night { background: #cce5ff; }
.nswp-track-cell.pre { background: #e2e3e5; font-weight: 700; }
.nswp-track-cell.need {
  box-shadow: inset 0 0 0 1.5px #e6b800; background: rgba(230, 184, 0, 0.18);
  cursor: help; font-weight: 700; color: #16232e;
}
</style>
"""


def _track_preview_html(offer, report_ctx, by_label):
    """
    HTML for the 'Preview track' panel under one offer: the real Sun-Sat week(s)
    around the swap, the give-up shift struck through, the need shown as a
    hypothetical pickup, and everything else on the staff member's track for
    context — same idea as the Bid Roster grid, scoped to just the days that
    matter for this one offer instead of the whole cycle.
    """
    staff_name = offer['staff_name']
    bid = report_ctx['bids_by_name'].get(staff_name)
    if not bid:
        return "<p>No bid on file for this staff member.</p>"
    track_data = bid['track_data'] or {}
    role, _is_senior = _bid_role_and_senior(
        bid, report_ctx['ctx']['role_mapping'], report_ctx['ctx']['no_matrix_mapping'])
    role_bucket = _bidding_role_bucket(role)

    drop_text = html.escape(_give_up_impact_text(_give_up_impact(offer, report_ctx, by_label)))
    pickup_text = html.escape(_pickup_impact_text(_pickup_impact(offer, report_ctx, by_label)))

    give_up_week = _week_key(offer['give_up_day'])
    need_week = _week_key(offer['need_day'])
    weeks = [give_up_week] if give_up_week == need_week else [give_up_week, need_week]

    def cell(day_label):
        """One cell per day — a person only ever works one period on a given
        day, so Day/Night share a single row instead of each getting their
        own (mostly-empty) row."""
        if day_label == offer['give_up_day']:
            period = offer['give_up_period']
            code_letter = 'D' if period == 'Day' else 'N'
            return (f'<div class="nswp-cell nswp-drop" tabindex="0">'
                    f'<span class="nswp-code">{code_letter}</span>'
                    f'<span class="nswp-tooltip nswp-tooltip-left">Dropping this shift: {drop_text}</span>'
                    f'</div>')
        if day_label == offer['need_day']:
            period = offer['need_period']
            code_letter = 'D' if period == 'Day' else 'N'
            return (f'<div class="nswp-cell nswp-pickup" tabindex="0">'
                    f'<span class="nswp-code">{code_letter}</span>'
                    f'<span class="nswp-tooltip">Picking this up: {pickup_text}</span>'
                    f'</div>')

        code = track_data.get(day_label)
        if code == 'D':
            base = _expected_base_for_day(staff_name, day_label, 'Day', role_bucket, report_ctx)
            base_html = f'<span class="nswp-base">{html.escape(base)}</span>' if base else ''
            return f'<div class="nswp-cell nswp-day"><span class="nswp-code">D</span>{base_html}</div>'
        if code == 'N':
            base = _expected_base_for_day(staff_name, day_label, 'Night', role_bucket, report_ctx)
            base_html = f'<span class="nswp-base">{html.escape(base)}</span>' if base else ''
            return f'<div class="nswp-cell nswp-night"><span class="nswp-code">N</span>{base_html}</div>'
        if code == 'AT':
            return '<div class="nswp-cell nswp-at"><span class="nswp-code">AT</span></div>'
        return '<div class="nswp-cell"></div>'

    parts = [_NSWP_STYLE, '<div class="nswp-wrap">']
    if offer.get('status') == 'pending' and not offer.get('still_valid', True):
        reason = html.escape(offer.get('stale_reason') or "This offer no longer applies cleanly.")
        parts.append(f'<div class="nswp-stale">⚠️ {reason}</div>')

    for wk in weeks:
        week_days = _week_days(wk, report_ctx['days'])
        if not week_days:
            continue
        block, week_num = wk
        parts.append(f'<div class="nswp-week"><div class="nswp-week-label">'
                     f'Week · Block {html.escape(block)}, Week {html.escape(week_num)}</div>')
        parts.append('<div class="nswp-grid nswp-grid-wide-label">')
        parts.append('<div class="nswp-rowhead"></div>')
        for d in week_days:
            d_parts = d.split()
            tag = f"{d_parts[0]} {d_parts[1]}{d_parts[2]}" if len(d_parts) == 3 else d
            parts.append(f'<div class="nswp-daylabel">{html.escape(tag)}</div>')
        parts.append('<div class="nswp-rowhead">Assignment</div>')
        for d in week_days:
            parts.append(cell(d))
        parts.append('</div></div>')

    parts.append(
        '<div class="nswp-legend">'
        '<span><span class="nswp-swatch" style="background:#66bb6a"></span>Working — Day</span>'
        '<span><span class="nswp-swatch" style="background:#1976d2"></span>Working — Night</span>'
        '<span><span class="nswp-swatch" style="border:1px dashed #d7dee3"></span>Off</span>'
        '<span><span class="nswp-swatch" style="border:1.5px dashed #c9463a"></span>Offering to drop</span>'
        '<span><span class="nswp-swatch" style="border:1.5px dashed #66bb6a;background:rgba(102,187,106,0.14)"></span>'
        'Offering to pick up</span>'
        '</div>'
    )
    parts.append('</div>')
    return ''.join(parts)


def _offers_dataframe(offers, report_ctx):
    seniority = report_ctx['ctx']['seniority_mapping']
    roles = report_ctx['ctx']['role_mapping']
    by_label = _day_stats_by_label(report_ctx)

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
        'Give-up impact': _give_up_impact_text(_give_up_impact(o, report_ctx, by_label)),
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
    """Open/close the staff window and set the per-period crew floors for one cycle."""
    tn = cfg['track_name']
    is_open = bool(cfg.get('needs_swap_open'))
    floors = needs_swap_floors(cfg)

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        new_open = st.checkbox("Swap window open to staff", value=is_open, key=f"needs_swap_open_{tn}")
        if new_open != is_open:
            update_track_config(tn, needs_swap_open=1 if new_open else 0)
            st.rerun()
    with c2:
        new_day = st.number_input(
            "Day floor (crews)", min_value=0, max_value=20, value=int(floors['Day']), step=1,
            key=f"needs_swap_min_day_{tn}",
            help="A Day shift is only offered as one a staff member can leave if it still holds "
                 "this many crews once they come off it.")
    with c3:
        new_night = st.number_input(
            "Night floor (crews)", min_value=0, max_value=20, value=int(floors['Night']), step=1,
            key=f"needs_swap_min_night_{tn}",
            help="Same for Night shifts. Usually set above the cycle's own night minimum, so "
                 "nights are harder to leave than they are to flag as a need.")

    if new_day != floors['Day'] or new_night != floors['Night']:
        update_track_config(tn, needs_swap_min_day=int(new_day), needs_swap_min_night=int(new_night))
        st.rerun()

    st.caption(
        f"Staff can come off a Day shift only while it keeps **{floors['Day']}** crews, and off a "
        f"Night only while it keeps **{floors['Night']}**. Separate from this cycle's own minimums "
        f"({cfg.get('min_day_staff')} Day / {cfg.get('min_night_staff')} Night), which decide what "
        "counts as a need in the first place."
    )
    for period, config_min in (('Day', cfg.get('min_day_staff')), ('Night', cfg.get('min_night_staff'))):
        if config_min is not None and floors[period] < config_min:
            st.warning(
                f"The {period} floor ({floors[period]}) is below this cycle's {period.lower()} "
                f"minimum ({config_min}) — staff could come off a {period} shift and leave it "
                "short enough to become a need itself."
            )


def _render_needs_swap_admin_tab(config_names, default_track_index):
    st.markdown("### Needs Swap Requests")
    st.caption(
        "Staff offers to move onto a below-minimum shift. Each row is one pairing — the need "
        "they'd cover and the overstaffed shift they'd give up for it, ranked by their own "
        "preference. Approving a pairing writes it straight to that person's bid track. "
        "Approve and Decline both open a note box first, so you can record what you were "
        "weighing before the decision is applied. A decision can be rescinded or its "
        "notification re-sent further down the page."
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

    _render_review_note_prompt(offers, report_ctx, reviewer)

    st.markdown("#### Pending offers, by need")
    if not pending:
        st.info("Nothing pending — every offer has been decided.")
    else:
        needs_by_key = {(n['day_label'], n['period']): n for n in report_ctx['needs']}
        by_label = _day_stats_by_label(report_ctx)
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
                    cols = st.columns([4, 1.3, 1, 1])
                    role = report_ctx['ctx']['role_mapping'].get(o['staff_name'], 'Unknown')
                    seniority = report_ctx['ctx']['seniority_mapping'].get(o['staff_name'], '?')
                    base = best_base_for_need(o['staff_name'], o['need_day'],
                                               o['need_period'], report_ctx)
                    where = (f"hypothetical shift {base['base']} ({_rank_text(base)})" if base
                             else "no hypothetical shift can be promised")
                    impact_text = _give_up_impact_text(_give_up_impact(o, report_ctx, by_label))
                    line = (f"**{o['staff_name']}** ({role}, seniority {seniority}) — "
                            f"give up {_shift_label(o['give_up_day'], o['give_up_period'])} "
                            f"*({impact_text})* "
                            f"· their rank {o['preference_rank']} · {where}")
                    if not o['still_valid']:
                        line += f"  \n⚠️ {o['stale_reason']}"
                    if o['staff_notes']:
                        line += f"  \n💬 {o['staff_notes']}"
                    cols[0].markdown(line)

                    preview_key = f"needs_swap_preview_open_{o['id']}"
                    preview_open = st.session_state.get(preview_key, False)
                    if cols[1].button("Hide track" if preview_open else "🔍 Preview track",
                                      key=f"needs_swap_preview_btn_{o['id']}", use_container_width=True):
                        st.session_state[preview_key] = not preview_open
                        st.rerun()
                    # Neither button decides anything on its own: both open the note
                    # box, which is where the decision is actually confirmed.
                    if cols[2].button("Approve", key=f"needs_swap_approve_{o['id']}",
                                      disabled=not o['still_valid'], use_container_width=True):
                        _queue_review_action(o['id'], 'approve')
                        st.rerun()
                    if cols[3].button("Decline", key=f"needs_swap_decline_{o['id']}",
                                      use_container_width=True):
                        _queue_review_action(o['id'], 'decline')
                        st.rerun()

                    if preview_open:
                        st.markdown(_track_preview_html(o, report_ctx, by_label), unsafe_allow_html=True)

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

    _render_decided_offer_controls(offers, report_ctx, reviewer)
    _render_minimum_relaxations(track_name)


def _render_decided_offer_controls(offers, report_ctx, reviewer):
    """
    Undo or re-send a decision that has already been made.

    Both belong together and away from the pending queue: they act on offers that are
    off it, and neither is part of the normal review pass. Rescinding re-opens the
    decision (and reverses an approval's write to the bid track); resending puts the
    same notification back in the staff member's inbox without changing anything.
    """
    decided = [o for o in offers if o['status'] in ('approved', 'declined')]
    st.markdown("---")
    st.markdown("#### Undo or re-send a decision")
    if not decided:
        st.caption("Nothing has been approved or declined on this cycle yet.")
        return

    st.caption(
        "**Rescind** puts the offer back in the pending queue to be decided again — and if it "
        "was approved, puts the staff member's track back the way it was, restores any minimum "
        "the approval relaxed, and re-opens the options it superseded. **Re-send** changes "
        "nothing; it just emails the same decision to the staff member and the admins again."
    )

    icon = {'approved': '✅', 'declined': '❌'}
    labels = {
        f"{icon[o['status']]} {o['staff_name']} — {_shift_label(o['need_day'], o['need_period'])} "
        f"(gave up {_compact_shift(o['give_up_day'], o['give_up_period'])}) · "
        f"{_STATUS_LABEL[o['status']]} by {o['reviewed_by'] or 'unknown'}"
        f"{' on ' + o['review_date'] if o['review_date'] else ''}": o
        for o in sorted(decided, key=lambda o: (o['review_date'] or '', o['staff_name']), reverse=True)
    }

    picked = st.selectbox("Decision:", ['—'] + list(labels), key="needs_swap_decided_pick")
    if picked == '—':
        return

    offer = labels[picked]
    if offer['review_notes']:
        st.caption(f"📝 On the record: {offer['review_notes']}")

    rescind_col, resend_col = st.columns(2)
    if rescind_col.button("↩️ Rescind decision", key=f"needs_swap_rescind_{offer['id']}",
                          use_container_width=True):
        # Like Approve and Decline, the button only opens the note box — the reversal
        # itself is confirmed there.
        _queue_review_action(offer['id'], 'rescind')
        st.rerun()
    if resend_col.button("📧 Re-send notification", key=f"needs_swap_resend_{offer['id']}",
                         use_container_width=True):
        status = _resend_decision_notification(offer, report_ctx, offers)
        _flash(_ADMIN_FLASH, 'info', f"{offer['staff_name']} — re-sent. {status}")
        st.rerun()


def _render_minimum_relaxations(track_name):
    """
    Night/weekend minimums relaxed on this cycle by approving a swap, with what each
    one was before. Kept visible and reversible: the relaxation is what lets the rest
    of the app treat the approved track as valid, so an admin needs to be able to see
    who is carrying one and put it back.
    """
    from modules.db_utils import clear_requirement_override, get_requirement_overrides

    overrides = get_requirement_overrides(track_name)
    st.markdown("---")
    st.markdown("#### Minimums relaxed for this cycle")
    if not overrides:
        st.caption("Nobody's night or weekend minimum has been relaxed on this cycle.")
        return

    st.caption(
        "Approving a swap that drops someone below a night or weekend minimum relaxes that "
        "minimum for this cycle, so their track reads as valid everywhere in the app and not "
        "just here. The original figure is kept and applies again on the next cycle."
    )

    def figure(entry, field):
        original = entry.get(f'original_{field}')
        relaxed = entry.get(field)
        if relaxed is None:
            return f"{original if original is not None else '—'} (unchanged)"
        return f"{original if original is not None else '—'} → {relaxed}"

    st.dataframe(pd.DataFrame([{
        'Staff': name,
        'Night minimum': figure(entry, 'night_minimum'),
        'Weekend minimum': figure(entry, 'weekend_minimum'),
        'Approved by': entry.get('created_by') or '—',
        'When': entry.get('modified_date') or '—',
    } for name, entry in sorted(overrides.items())]), use_container_width=True, hide_index=True)

    picked = st.selectbox("Restore someone's own minimums:", ['—'] + sorted(overrides),
                          key="needs_swap_restore_minimum")
    if picked != '—' and st.button(f"Restore {picked}'s minimums", key="needs_swap_restore_btn"):
        ok, msg = clear_requirement_override(track_name, picked)
        clear_bidding_caches()
        _flash(_ADMIN_FLASH, 'success' if ok else 'error', msg)
        st.rerun()
