# modules/nondisplacing_assignment.py
"""
Non-displacing base assignment — which base a volunteer could realistically expect
on a day they didn't bid, without anyone already on that day dropping to a
worse-ranked base than the one they'd have had.

The app's normal hypothetical assignment (hypothetical_scheduler_new.
calculate_hypothetical_assignment) runs a pure seniority draft: sort everyone
bidding the day by seniority, most senior first takes their highest-ranked base
still open. That's the right model for bidding, where everyone is competing on
equal footing. It's the wrong model for a volunteer stepping onto someone else's
day: a senior volunteer would show up holding a base that, in the draft, he only
gets by pushing a less-senior person who *bid* that day down to a worse base.

So a base is only offered to the volunteer if the rest of that day can be
re-arranged with every one of them keeping — or improving on — their baseline
rank. Concretely, for each base:

  1. Work out the baseline: the normal draft, run without the volunteer. That's
     the assignment the people who actually bid this day have earned.
  2. Give everyone the set of bases they'd accept — anything they rank at least
     as highly as their baseline base. (Someone whose baseline base was unranked
     has nothing to protect, so any base counts.)
  3. Pin the volunteer to the base in question and ask whether the others can
     still all be seated inside their own accepted sets. That's a bipartite
     matching, solved exactly, so a base is offered only when a concrete
     arrangement exists — not merely when one seems plausible.

Step 3 is what lets a volunteer take a base someone is currently sitting on, but
only when that person can move somewhere they like *better*: a medic parked on
his 3rd-choice base can slide to his 2nd choice to free it up, and both people
come out ahead. A base held by someone already on their 1st choice can never be
freed, because no move improves on it.
"""

from modules.hypothetical_scheduler_new import _build_available_slots

_LOCATION_KEY = {'Day': 'day_locations', 'Night': 'night_locations'}


def _base_rank(staff_name, base, period, all_base_prefs):
    """This staff member's 1-5 (day) / 1-3 (night) ranking for a base, or None."""
    row = (all_base_prefs or {}).get(staff_name)
    if not row:
        return None
    return (row.get(_LOCATION_KEY[period]) or {}).get(base)


def draft_assignment(roster, period, all_base_prefs, base_shift_counts):
    """
    The app's normal seniority draft for one day/period/role bucket.

    `roster` is a list of (staff_name, seniority) already ordered most-senior-first.
    Mirrors calculate_hypothetical_assignment's inner loop exactly, including its
    tie-break (the earliest still-open slot wins) and its fallback of handing an
    arbitrary open slot to anyone whose preferred bases are gone.

    Returns {staff_name: {'slot': str, 'base': str, 'rank': int or None}} for the
    staff who got a slot; anyone the day had no room for is simply absent.
    """
    available, slot_to_base = _build_available_slots(
        'day' if period == 'Day' else 'night', base_shift_counts)

    assignment = {}
    for staff_name, _seniority in roster:
        if not available:
            break

        best_slot, best_rank = None, None
        for slot in available:
            rank = _base_rank(staff_name, slot_to_base[slot], period, all_base_prefs)
            if rank is None:
                continue
            if best_rank is None or rank < best_rank:
                best_slot, best_rank = slot, rank

        if best_slot is None:
            best_slot, best_rank = available[0], None

        assignment[staff_name] = {'slot': best_slot, 'base': slot_to_base[best_slot],
                                  'rank': best_rank}
        available.remove(best_slot)
    return assignment


def acceptable_slots(staff_name, baseline_rank, slots, slot_to_base, period, all_base_prefs):
    """
    The slots this staff member could be moved to without going backwards: bases
    they rank at least as highly as their baseline. A baseline rank of None means
    they landed somewhere they hadn't ranked at all, so nothing is being protected
    and every slot qualifies.
    """
    if baseline_rank is None:
        return list(slots)
    keep = []
    for slot in slots:
        rank = _base_rank(staff_name, slot_to_base[slot], period, all_base_prefs)
        if rank is not None and rank <= baseline_rank:
            keep.append(slot)
    return keep


def _matches_everyone(people, acceptable_by_person, slot_count):
    """
    Can every person be seated in a distinct slot drawn from their own acceptable
    list? Kuhn's augmenting-path algorithm — exact, and trivially fast at the sizes
    here (at most a dozen people against nine slots).
    """
    if len(people) > slot_count:
        return False

    slot_holder = {}

    def seat(person, tried):
        for slot in acceptable_by_person[person]:
            if slot in tried:
                continue
            tried.add(slot)
            if slot not in slot_holder or seat(slot_holder[slot], tried):
                slot_holder[slot] = person
                return True
        return False

    return all(seat(person, set()) for person in people)


def nondisplacing_bases(roster, period, all_base_prefs, base_shift_counts):
    """
    Every base a volunteer could be added to on this day without anyone already on
    it ending up worse off.

    `roster` is the day's staff in the volunteer's own role bucket (nurses compete
    with nurses, medics with medics, exactly as the draft does), as (name, seniority)
    pairs ordered most-senior-first, and must not include the volunteer.

    Which bases survive doesn't depend on who the volunteer is — only on what the
    people already there would accept — so the result can be computed once per
    day/period/role bucket and reused for every volunteer. The caller attaches the
    volunteer's own ranking (see rank_options).

    Returns (options, baseline, blocked) where:
      options  — [{'base', 'moves': [{'staff', 'from', 'to', 'from_rank',
                 'to_rank'}]}] in slot order; 'moves' lists who shifts base to make
                 room, always to something they rank at least as highly
      baseline — the draft assignment the options are measured against
      blocked  — bases ruled out, as {base: reason}
    """
    slots, slot_to_base = _build_available_slots(
        'day' if period == 'Day' else 'night', base_shift_counts)
    bases = []
    for slot in slots:
        if slot_to_base[slot] not in bases:
            bases.append(slot_to_base[slot])

    baseline = draft_assignment(roster, period, all_base_prefs, base_shift_counts)
    seated = [name for name, _ in roster if name in baseline]

    if len(seated) + 1 > len(slots):
        return [], baseline, {base: 'Every base on this day is already spoken for' for base in bases}

    acceptable = {
        name: acceptable_slots(name, baseline[name]['rank'], slots, slot_to_base,
                               period, all_base_prefs)
        for name in seated
    }

    options, blocked = [], {}
    for base in bases:
        pinned = next(slot for slot in slots if slot_to_base[slot] == base)
        remaining = [slot for slot in slots if slot != pinned]
        trimmed = {name: [s for s in acceptable[name] if s != pinned] for name in seated}

        if not _matches_everyone(seated, trimmed, len(remaining)):
            blocked[base] = (f"Taking {base} would move someone already on this day to a "
                             "base they rank lower")
            continue

        options.append({
            'base': base,
            'moves': _describe_moves(seated, trimmed, remaining, baseline, slot_to_base,
                                     period, all_base_prefs),
        })

    return options, baseline, blocked


def rank_options(volunteer, options, period, all_base_prefs):
    """
    Attach the volunteer's own ranking to each offerable base and order them the way
    they'd care about — their top-ranked base first, bases they never ranked last.
    """
    ranked = [dict(o, rank=_base_rank(volunteer, o['base'], period, all_base_prefs))
              for o in options]
    ranked.sort(key=lambda o: (o['rank'] is None, o['rank'] or 0, o['base']))
    return ranked


def _describe_moves(seated, acceptable_by_person, remaining, baseline, slot_to_base,
                    period, all_base_prefs):
    """
    Who has to move for this base to open up, and where they land. Re-runs the
    matching keeping people where they already are wherever possible, so the moves
    reported are the smallest set that makes the arrangement work.
    """
    stay_first = {
        name: ([baseline[name]['slot']] if baseline[name]['slot'] in acceptable_by_person[name]
               else []) + [s for s in acceptable_by_person[name] if s != baseline[name]['slot']]
        for name in seated
    }

    slot_holder = {}

    def seat(person, tried):
        for slot in stay_first[person]:
            if slot in tried:
                continue
            tried.add(slot)
            if slot not in slot_holder or seat(slot_holder[slot], tried):
                slot_holder[slot] = person
                return True
        return False

    for person in seated:
        seat(person, set())

    moves = []
    for slot, person in slot_holder.items():
        was = baseline[person]['base']
        now = slot_to_base[slot]
        if was == now:
            continue
        moves.append({
            'staff': person, 'from': was, 'to': now,
            'from_rank': baseline[person]['rank'],
            'to_rank': _base_rank(person, now, period, all_base_prefs),
        })
    return sorted(moves, key=lambda m: m['staff'])
