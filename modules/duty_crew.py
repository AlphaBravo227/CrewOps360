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

That is one crew among many, so it is **data** rather than something written here: a
vehicle carries a `crew_spec` naming its seats, the roles each accepts, and how many
of the people seated must be senior. `DEFAULT_CREW_SPEC` in duty_schedule_db is the
above; a BLS ambulance crewed by two EMTs with no seniority rule is the same shape
with different values, and nothing in this module knows what an EMT is.

Three ways to fail a spec, which are different problems and want different answers:

| Status       | Means                                          | What to do |
| ------------ | ---------------------------------------------- | ---------- |
| `crewed`     | a legal crew                                   | nothing |
| `incomplete` | someone is on it, but not enough of them       | add a person |
| `no_crew`    | enough people, but they don't make a crew      | swap someone |
| `unstaffed`  | nobody on it                                   | fill it |

`no_crew` covers two nurses with neither taking the medic seat, two medics, and a
pairing where both providers are junior. All three have the bodies and still can't
fly, which is why they read differently from `incomplete`.

The fill was only half of what the sheet said. Its **font** carried a second channel,
and it is the more useful one: blue for a nurse and red for a medic named the role
still wanted, and **bold** meant the provider already aboard is junior — so whoever
fills the other seat has to be the senior of the pair. On a crewed vehicle the same
bold meant every provider aboard is senior. Both survive here as `needs`
(`{'role', 'senior_required'}`) and `both_senior`, so a caller can say *who* is wanted
rather than only that somebody is.

Two things carry over from the sheet unchanged. Senior/junior is `staff.no_matrix`,
already the rule in `track_bidding.py`. And a nurse can take the *medic* seat when
they are a dual provider — that is what the sheet's `p` suffix (`D7Bp`) meant, and why
its helper counted a nurse on the p-variant toward the medic slot. That one lives in
`provider_roles()`: a dual carries both roles, so a seat asking for `['medic']` takes
one without the spec having to know duals exist.
"""

from .duty_schedule_db import (
    DEFAULT_CREW_SPEC,
    SEAT_MEDIC,
    SEAT_RN,
    SEAT_THIRD,
)

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
    and `track_bidding._bid_role_and_senior` already treats it this way. Wrapping it
    here rather than reading the column at each call site is what will make renaming
    it one edit rather than twenty.
    """
    return bool(record and record.get('no_matrix'))


def is_dual(record):
    """A provider credentialed to work a second role's seat."""
    return bool(record and record.get('is_dual'))


def on_orientation(record):
    """
    Still in orientation, so riding as an uncounted third.

    Absent or 0 means cleared — adding this column to an existing roster must not
    quietly take everybody off the board.
    """
    return bool(record and record.get('on_orientation'))


def base_role(record):
    """The one role a staff record is hired into, lowercased."""
    if not record:
        return ''
    role = str(record.get('role') or '').strip().lower()
    if role in ('nurse', 'rn'):
        return 'nurse'
    if role in ('medic', 'paramedic'):
        return 'medic'
    return role


# Which second role a dual credential grants. Keeping it here, as one mapping, is
# what lets a crew spec name plain roles and still get duals for free: a seat asking
# for ['medic'] accepts a dual nurse without knowing duals exist.
DUAL_GRANTS = {'nurse': 'medic'}


def provider_roles(record):
    """
    Every role a person can work.

    A dual nurse carries both, which is why they can take the medic seat — the
    spreadsheet's `p` suffix. Putting this on the person rather than in the seat is
    what keeps a spec readable: seats name roles, people carry them.
    """
    base = base_role(record)
    if not base:
        return set()
    roles = {base}
    granted = DUAL_GRANTS.get(base)
    if granted and is_dual(record):
        roles.add(granted)
    return roles


def seat_accepts(seat, record):
    """Whether a staff record may fill this seat."""
    return bool(set(seat.get('roles') or []) & provider_roles(record))


def can_fill_seat(record, seat_key, spec=None):
    """
    Whether a staff member may take a seat, by key.

    The third seat is open to anyone — that is where an orientee rides.
    """
    if seat_key == SEAT_THIRD:
        return True
    seat = seat_by_key(spec or DEFAULT_CREW_SPEC).get(seat_key)
    return bool(seat) and seat_accepts(seat, record)


def seat_by_key(spec):
    """{key: seat} for a spec."""
    return {seat['key']: seat for seat in spec.get('seats') or []}


def required_seats(spec):
    """The seats that have to be filled for this vehicle to be crewed."""
    return [seat for seat in spec.get('seats') or [] if seat.get('required', True)]


def _best_seating(people, seats):
    """
    Seat as many people as possible, each in a seat they qualify for.

    Kuhn's augmenting path — the same algorithm
    `nondisplacing_assignment._matches_everyone` uses for the volunteer question,
    asking how many seats can be filled rather than whether everyone fits. Exact,
    and trivially fast against a handful of people and a handful of seats.

    Returns:
        dict: seat index -> person index.
    """
    holder = {}

    def place(person, tried):
        for index, seat in enumerate(seats):
            if index in tried or not seat_accepts(seat, people[person]['record']):
                continue
            tried.add(index)
            if index not in holder or place(holder[index], tried):
                holder[index] = person
                return True
        return False

    for person in range(len(people)):
        place(person, set())
    return holder


def _name_list(people):
    return ', '.join(sorted(person['staff_name'] for person in people))


def crew_status(assigned, staff_lookup, pairs=None, spec=None):
    """
    Evaluate one vehicle on one date against its crew spec.

    Args:
        assigned (list[dict]): the assignment rows for this vehicle and date — each
            needs `staff_name` and `seat`.
        staff_lookup (callable): staff_name -> staff record dict, or None.
        pairs (list, optional): pre-loaded `get_restricted_pairs()`. Passing it in
            keeps a board of 15 vehicles x 14 dates from re-querying per cell.
        spec (dict, optional): what makes a crew here. Defaults to the fleet's.

    Returns:
        dict: status, reason, and the parts that produced it — `seated` (seat key ->
        people), `riders`, `seniors`, `misseated`, `restricted`, plus `needs` and
        `both_senior` for the display.
    """
    from .duty_schedule_db import restricted_partners

    spec = spec or DEFAULT_CREW_SPEC
    seats = spec.get('seats') or []
    by_key = seat_by_key(spec)
    wanted = required_seats(spec)
    min_senior = spec.get('min_senior', 0)

    people = []
    for row in assigned or []:
        record = staff_lookup(row['staff_name']) or {}
        people.append({
            'staff_name': row['staff_name'],
            'seat': row.get('seat') or SEAT_THIRD,
            'record': record,
        })

    # An orientee never counts toward a seat, whichever seat the row claims.
    for person in people:
        if on_orientation(person['record']):
            person['seat'] = SEAT_THIRD

    riders = [p for p in people if p['seat'] == SEAT_THIRD]
    providers = [p for p in people if p['seat'] != SEAT_THIRD]
    misseated = [p for p in providers
                 if p['seat'] not in by_key or not seat_accepts(by_key[p['seat']],
                                                                p['record'])]

    seated = {}
    for person in providers:
        if person not in misseated:
            seated.setdefault(person['seat'], []).append(person)

    seniors = [p for p in providers if is_senior(p['record'])]

    result = {
        'status': None, 'reason': '',
        'seated': seated, 'riders': riders, 'providers': providers,
        'seniors': len(seniors), 'misseated': misseated, 'restricted': [],
        'needs': None, 'both_senior': False, 'spec': spec,
    }

    # Restricted pairs are a hard block wherever they land, so they are checked
    # before the composition — a legal crew of two people who may not fly together
    # is still not a crew.
    names = [p['staff_name'] for p in people]
    restricted = []
    for index, name in enumerate(names):
        partners = restricted_partners(name, pairs)
        for other in names[index + 1:]:
            if other.strip().lower() in partners:
                restricted.append((name, other))
    result['restricted'] = restricted

    if restricted:
        pair_text = '; '.join(f"{a} and {b}" for a, b in restricted)
        result.update(status=NO_CREW, reason=f"{pair_text} may not crew together")
        return result

    if misseated:
        result.update(status=NO_CREW,
                      reason=f"{_name_list(misseated)} cannot work the seat assigned")
        return result

    if not people:
        result.update(status=UNSTAFFED, reason='nobody assigned')
        return result

    unfilled = [seat for seat in wanted if not seated.get(seat['key'])]
    senior_short = len(seniors) < min_senior

    if not unfilled and not senior_short:
        result.update(status=CREWED, reason='',
                      both_senior=bool(providers) and len(seniors) == len(providers))
        return result

    if not providers:
        result.update(status=INCOMPLETE,
                      reason='only staff on orientation assigned',
                      needs=_needs(unfilled, senior_short))
        return result

    # Fewer providers than seats to fill means somebody is missing; enough providers
    # and an unfilled seat means the ones here cannot make a crew between them. The
    # two want opposite answers — add a person, or swap one — so they read
    # differently.
    if unfilled and len(providers) < len(wanted):
        result.update(status=INCOMPLETE, needs=_needs(unfilled, senior_short),
                      reason=_wanted_text(unfilled, senior_short))
        return result

    if unfilled:
        # The people are here. Say whether moving them between seats would do it,
        # because "two nurses" and "two nurses, and one of them could take the medic
        # seat" are different amounts of work.
        moved = _best_seating(providers, seats)
        covered = {seats[i]['key'] for i in moved}
        fixable = [seat for seat in wanted if seat['key'] not in covered]
        if not fixable:
            movers = _name_list([providers[moved[i]] for i in moved
                                 if providers[moved[i]]['seat'] != seats[i]['key']])
            result.update(status=NO_CREW,
                          reason=f"seats do not cover the crew — {movers} could move")
        else:
            short = ' and '.join(_seat_phrase(seat) for seat in fixable)
            result.update(status=NO_CREW,
                          reason=f"nobody here can fill the {short} seat")
        return result

    result.update(status=NO_CREW,
                  reason=(f"needs {min_senior} senior provider"
                          f"{'s' if min_senior > 1 else ''}"))
    return result


def _seat_name(seat):
    return seat.get('label') or seat.get('key')


def _needs(unfilled, senior_short):
    """
    Who is still wanted — the sheet's font, as data.

    Colour named the role and bold meant "and they have to be the senior one". Both
    come from the spec's own seat, so a service whose seats are two EMTs gets the
    same treatment without anything here knowing what an EMT is.
    """
    if not unfilled:
        return None
    seat = unfilled[0]
    roles = seat.get('roles') or []
    return {
        'role': roles[0] if roles else '',
        'seat': seat.get('key'),
        'label': _seat_name(seat),
        'short': seat.get('short') or _seat_name(seat),
        'ink': seat.get('ink') or '',
        'senior_required': bool(senior_short),
        'seats': [s.get('key') for s in unfilled],
    }


def _seat_phrase(seat):
    """
    A seat's name as it reads mid-sentence.

    An all-caps label is an acronym and keeps its case — "needs a senior RN", not
    "needs a senior rn" — while "Medic" reads better lowercased.
    """
    name = _seat_name(seat)
    return name if name.isupper() else name.lower()


def _wanted_text(unfilled, senior_short):
    names = ' and '.join(_seat_phrase(seat) for seat in unfilled)
    return f"needs a {'senior ' if senior_short else ''}{names}"


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
