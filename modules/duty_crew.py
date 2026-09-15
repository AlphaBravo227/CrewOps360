# modules/duty_crew.py
"""
Whether the people on a vehicle make a crew.

On the spreadsheet this was done by arithmetic. Sixteen hidden six-row blocks (rows
152–247 of `11 Oct 2026`) counted who was on each vehicle and folded them into one
number — senior RN x9, senior medic x90, junior RN x900, junior medic x9000 — and
about fifty conditional-format rules enumerated the sums that were legal: 99, 990,
9009, 189, 18009 and so on.

It worked, but it could only say *what colour*, never *why*, and the encoding had
started to fray: every reachable total is a multiple of nine, so the rule written for
123 could never fire, and the places collide once counts pass single digits — twelve
senior RNs and "one senior medic plus two senior RNs" are both 108.

Stated plainly, the rule those sums encode is:

    A crew is one RN seat and one medic seat, and at least one of the two is senior.

with three ways to fail it, which are different problems and want different answers:

| Status       | Means                                          | What to do |
| ------------ | ---------------------------------------------- | ---------- |
| `crewed`     | a legal crew                                   | nothing |
| `incomplete` | someone is on it, but not enough of them       | add a person |
| `no_crew`    | enough people, but they don't make a crew      | swap someone |
| `unstaffed`  | nobody on it                                   | fill it |

`no_crew` covers two nurses with neither taking the medic seat, two medics, and a
pairing where both providers are junior. All three have the bodies and still can't
fly, which is why they read differently from `incomplete`.

Two things carry over from the sheet unchanged. Senior/junior is `staff.no_matrix`,
already the rule in `track_bidding.py`. And a nurse can take the *medic* seat when
they are a dual provider — that is what the sheet's `p` suffix (`D7Bp`) meant, and why
its helper counted a nurse on the p-variant toward the medic slot.
"""

from .duty_schedule_db import SEAT_MEDIC, SEAT_RN, SEAT_THIRD

CREWED = 'crewed'
INCOMPLETE = 'incomplete'
NO_CREW = 'no_crew'
UNSTAFFED = 'unstaffed'

# Background and text for each status, in the app's existing Material palette.
STATUS_STYLE = {
    CREWED:     {'label': 'Crewed',     'bg': '#C8E6C9', 'fg': '#1B5E20'},
    INCOMPLETE: {'label': 'Incomplete', 'bg': '#FFF9C4', 'fg': '#827717'},
    NO_CREW:    {'label': 'No crew',    'bg': '#FFE0B2', 'fg': '#E65100'},
    UNSTAFFED:  {'label': 'Unstaffed',  'bg': '#FFCDD2', 'fg': '#B71C1C'},
}

# Worst first, for rolling a day up into one figure.
STATUS_SEVERITY = {UNSTAFFED: 0, NO_CREW: 1, INCOMPLETE: 2, CREWED: 3}


def is_senior(record):
    """
    Senior, in the sense the crew rule means: off the competency matrix.

    `no_matrix` reads backwards at first glance — it is the roster's existing column,
    and `track_bidding._bid_role_and_senior` already treats it this way.
    """
    return bool(record and record.get('no_matrix'))


def is_dual(record):
    """A nurse credentialed to work the medic seat."""
    return bool(record and record.get('is_dual'))


def on_orientation(record):
    """
    Still in orientation, so riding as an uncounted third.

    Absent or 0 means cleared — adding this column to an existing roster must not
    quietly take everybody off the board.
    """
    return bool(record and record.get('on_orientation'))


def base_role(record):
    """'nurse', 'medic' or '' for one staff record."""
    if not record:
        return ''
    role = str(record.get('role') or '').strip().lower()
    if role in ('nurse', 'rn'):
        return 'nurse'
    if role in ('medic', 'paramedic'):
        return 'medic'
    return role


def can_fill_seat(record, seat):
    """
    Whether a staff member is allowed in a seat.

    A medic takes the medic seat; a nurse takes the RN seat; a dual provider takes
    either. The third seat is open to anyone — that is where an orientee rides.
    """
    if seat == SEAT_THIRD:
        return True
    role = base_role(record)
    if seat == SEAT_RN:
        return role == 'nurse'
    if seat == SEAT_MEDIC:
        return role == 'medic' or (role == 'nurse' and is_dual(record))
    return False


def _name_list(people):
    return ', '.join(sorted(p['staff_name'] for p in people))


def crew_status(assigned, staff_lookup, pairs=None):
    """
    Evaluate one vehicle on one date.

    Args:
        assigned (list[dict]): the assignment rows for this vehicle and date — each
            needs `staff_name` and `seat`.
        staff_lookup (callable): staff_name -> staff record dict, or None.
        pairs (list, optional): pre-loaded `get_restricted_pairs()`. Passing it in
            keeps a board of 15 vehicles x 14 dates from re-querying per cell.

    Returns:
        dict: status, reason, and the parts that produced it —
            rn / medic / third (lists of records), seniors (int),
            misseated (list), restricted (list of name pairs).
    """
    from .duty_schedule_db import restricted_partners

    people = []
    for row in assigned or []:
        record = staff_lookup(row['staff_name']) or {}
        people.append({
            'staff_name': row['staff_name'],
            'seat': row.get('seat') or SEAT_RN,
            'record': record,
        })

    # An orientee never counts toward a seat, whichever seat the row says.
    for person in people:
        if on_orientation(person['record']):
            person['seat'] = SEAT_THIRD

    misseated = [p for p in people
                 if p['seat'] != SEAT_THIRD and not can_fill_seat(p['record'], p['seat'])]
    rn = [p for p in people if p['seat'] == SEAT_RN]
    medic = [p for p in people if p['seat'] == SEAT_MEDIC]
    third = [p for p in people if p['seat'] == SEAT_THIRD]
    seniors = [p for p in rn + medic if is_senior(p['record'])]

    # Restricted pairs are a hard block wherever they land, so they are checked
    # before the composition — a legal crew of two people who may not fly together
    # is still not a crew.
    restricted = []
    names = [p['staff_name'] for p in people]
    for index, name in enumerate(names):
        partners = restricted_partners(name, pairs)
        for other in names[index + 1:]:
            if other.strip().lower() in partners:
                restricted.append((name, other))

    result = {
        'status': None, 'reason': '',
        'rn': rn, 'medic': medic, 'third': third,
        'seniors': len(seniors), 'misseated': misseated, 'restricted': restricted,
    }

    if restricted:
        pair_text = '; '.join(f"{a} and {b}" for a, b in restricted)
        result.update(status=NO_CREW, reason=f"{pair_text} may not crew together")
        return result

    if misseated:
        who = _name_list(misseated)
        result.update(status=NO_CREW,
                      reason=f"{who} cannot work the seat assigned")
        return result

    if not people:
        result.update(status=UNSTAFFED, reason='nobody assigned')
        return result

    if not rn and not medic:
        result.update(status=INCOMPLETE,
                      reason='only staff on orientation assigned')
        return result

    if not rn:
        if len(medic) > 1:
            result.update(status=NO_CREW, reason='two medics, no nurse')
        else:
            result.update(status=INCOMPLETE, reason='needs a medic seat filled')
        return result

    if not medic:
        if len(rn) > 1:
            result.update(status=NO_CREW,
                          reason='two nurses, neither in the medic seat')
        else:
            result.update(status=INCOMPLETE, reason='needs a medic')
        return result

    if not seniors:
        result.update(status=NO_CREW, reason='both providers are junior')
        return result

    result.update(status=CREWED, reason='')
    return result


def possible_crews(seniors, nurses, medics, duals):
    """
    How many complete crews a pool of people could form — the sheet's "Poss. shifts".

    Dual providers go to whichever side is short, so the split is chosen to even the
    two sides out; and since every crew needs a senior, the senior count caps it.

    This reproduces the spreadsheet's INT(MIN(...)) at Q20/Q29 exactly, which nested
    the same balancing three levels deep.
    """
    to_nurse_side = max(0, min(duals, (medics - nurses + duals) / 2))
    nurse_side = nurses + to_nurse_side
    medic_side = medics + duals - to_nurse_side
    return int(min(seniors, nurse_side, medic_side))


def pool_counts(records):
    """
    Break a set of staff records into the figures the counter block shows.

    Returns:
        dict: total, seniors, nurses, medics, duals, and the probationary splits —
        `nurses` and `medics` exclude duals, matching rows 21–26 of the sheet.
    """
    counts = {'total': 0, 'seniors': 0, 'nurses': 0, 'medics': 0, 'duals': 0,
              'prob_nurses': 0, 'prob_medics': 0, 'prob_duals': 0}
    for record in records:
        if not record:
            continue
        counts['total'] += 1
        if is_senior(record):
            counts['seniors'] += 1
        orienting = on_orientation(record)
        if is_dual(record):
            counts['duals'] += 1
            if orienting:
                counts['prob_duals'] += 1
        elif base_role(record) == 'medic':
            counts['medics'] += 1
            if orienting:
                counts['prob_medics'] += 1
        elif base_role(record) == 'nurse':
            counts['nurses'] += 1
            if orienting:
                counts['prob_nurses'] += 1
    counts['possible_crews'] = possible_crews(
        counts['seniors'], counts['nurses'], counts['medics'], counts['duals'])
    return counts


def day_status_roll_up(statuses):
    """
    The worst status among a day's vehicles, for a column summary.

    Returns None for an empty list rather than guessing a colour.
    """
    ranked = [s for s in statuses if s in STATUS_SEVERITY]
    if not ranked:
        return None
    return min(ranked, key=lambda s: STATUS_SEVERITY[s])


def shortfall(vehicle_statuses, vehicles):
    """
    Against minimum staffing, what a date is short.

    Args:
        vehicle_statuses (dict): vehicle code -> status.
        vehicles (list[dict]): the inventory rows, for their RW/ground weights.

    Returns:
        dict: rw and gr, the weighted count of crewed vehicles for each.
    """
    rw = gr = 0.0
    for vehicle in vehicles:
        if vehicle_statuses.get(vehicle['code']) == CREWED:
            rw += vehicle.get('rw_weight', 0) or 0
            gr += vehicle.get('gr_weight', 0) or 0
    return {'rw': rw, 'gr': gr}
