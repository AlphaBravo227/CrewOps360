# modules/duty_board.py
"""
Assembling a two-week duty board.

What the scheduler works on is one screen with three zones, exactly as the spreadsheet
had them: the vehicles down the left and the dates across the top, coloured by whether
each is crewed; a counter block; and the staff grid underneath, where a track's `D`
becomes `D7B`.

Nothing here decides *who* goes on *what* — that is the scheduler's job, and later an
algorithm's. This module's job is to put everything they need in order to decide in
one place:

* what each person's track has them doing that day, through `TrainingTrackManager`,
  which already knows a regular track repeats every 42 days and a CCEMT one every 28
* what training they are booked on or teaching, through the same event builders the
  calendars use
* what has already been assigned
* which vehicles that leaves uncrewed

The derived half is read live rather than copied into the block, so a track swap shows
on a draft board straight away. That is right for a draft and wrong for a published
one — nobody wants the posted schedule moving under them — so publishing takes a
snapshot into `duty_block_context`, and a published board reads that instead.
"""

from datetime import datetime

from . import duty_crew
from .duty_schedule_db import (
    BLOCK_PUBLISHED,
    DAY,
    LEAD_IN_DAYS,
    MIN_GR_DAY,
    MIN_GR_NIGHT,
    MIN_RW_DAY,
    MIN_RW_NIGHT,
    NIGHT,
    SEAT_MEDIC,
    SEAT_RN,
    SEAT_THIRD,
    block_dates,
    crew_spec_of,
    get_assignments,
    get_block,
    get_block_context,
    get_restricted_pairs,
    get_vehicles,
    set_block_context,
)

# A track cell that starts with N is a night, D is a day. Anything else — AT, LT,
# LOA, a class — is a day already spoken for: the person is committed, but not to a
# vehicle, so they are neither available nor assignable.
NIGHT_PREFIX = 'N'
DAY_PREFIX = 'D'


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d')


def _track_manager(track_cohort=None, pattern_start=None):
    """
    A TrainingTrackManager over the live tracks database.

    Built per board rather than cached: it loads every track once at construction,
    and a stale one would quietly answer with last cycle's schedule.
    """
    from training_modules.track_manager import TrainingTrackManager
    return TrainingTrackManager(
        tracks_db_path='data/medflight_tracks.db',
        track_cohort=track_cohort,
        pattern_start=pattern_start,
    )


def _training_managers():
    """
    The enrollment manager, educator manager and class catalog, or three Nones.

    Training is an overlay. A board is still worth having without it, so a training
    year that isn't set up must not take the whole screen down.
    """
    try:
        from training_modules.class_catalog import ClassCatalog
        from training_modules.educator_manager import EducatorManager
        from training_modules.enrollment_manager import EnrollmentManager
        return EnrollmentManager(), EducatorManager(), ClassCatalog()
    except Exception as e:
        print(f"Training overlay unavailable, carrying on without it: {e}")
        return None, None, None


def clinical_staff():
    """
    Everyone who can be put on a vehicle: active nurses and medics, most senior first.

    Management is excluded — they hold no track and are not crewed. A dual provider
    is a nurse carrying `is_dual`, so nothing special is needed to include them.
    """
    from .staff_database import get_all_staff
    return [record for record in get_all_staff(roles=['NURSE', 'MEDIC'],
                                               sort_by='seniority')
            if not record.get('is_management')]


def shift_kind_of(track_code):
    """
    'day', 'night' or None for a track cell.

    None means the person is not available for a vehicle that date — either they are
    off, or the cell holds a commitment (AT, LT, a class) rather than a shift.
    """
    code = str(track_code or '').strip().upper()
    if not code:
        return None
    if code.startswith(NIGHT_PREFIX):
        return NIGHT
    if code.startswith(DAY_PREFIX):
        return DAY
    return None


def training_by_staff(staff_names, start, end, enrollment_manager=None,
                      educator_manager=None, catalog=None):
    """
    {staff_name: {date: [label, ...]}} for classes booked and days taught.

    Returns what it can rather than failing: a training year that is not set up
    yields an empty overlay, and the board carries on.
    """
    from training_modules.schedule_calendar import educator_events, enrollment_events

    if enrollment_manager is None and educator_manager is None:
        enrollment_manager, educator_manager, catalog = _training_managers()

    overlay = {}
    for name in staff_names:
        days = {}
        sources = (
            (enrollment_events(name, enrollment_manager, catalog, start, end), ''),
            (educator_events(name, educator_manager, catalog, start, end), 'Teaching: '),
        )
        for events, prefix in sources:
            for event in events or []:
                key = event['date'].strftime('%Y-%m-%d')
                label = prefix + (event.get('code') or event.get('title') or 'Class')
                labels = days.setdefault(key, [])
                if label not in labels:
                    labels.append(label)
        if days:
            overlay[name] = days
    return overlay


def default_seat(record, spec=None):
    """
    The seat a person takes unless the scheduler says otherwise.

    The first seat in the spec whose roles match the one role they are hired into —
    so a medic defaults to the medic seat and a nurse to the RN seat. A dual nurse
    matches the RN seat first and is moved across deliberately, which is exactly what
    the spreadsheet's `p` suffix recorded.

    Somebody on orientation always rides third.
    """
    from .duty_schedule_db import DEFAULT_CREW_SPEC

    if duty_crew.on_orientation(record):
        return SEAT_THIRD

    spec = spec or DEFAULT_CREW_SPEC
    base = duty_crew.base_role(record)
    for seat in spec.get('seats') or []:
        if base in (seat.get('roles') or []):
            return seat['key']
    # No seat is hired for this role; fall back to anything they qualify for at all.
    for seat in spec.get('seats') or []:
        if duty_crew.seat_accepts(seat, record):
            return seat['key']
    return SEAT_THIRD


def _derive_context(dates, staff_records, track_cohort, pattern_start,
                    include_training=True):
    """
    Read the tracks and the training calendar for a span.

    Returns:
        dict: {(staff_name, iso_date): {'track_code':, 'training': [...]}}
    """
    manager = _track_manager(track_cohort, pattern_start)
    names = [r['staff_name'] for r in staff_records]

    overlay = {}
    if include_training and dates:
        overlay = training_by_staff(names, _as_datetime(dates[0]),
                                    _as_datetime(dates[-1]))

    context = {}
    for name in names:
        for iso in dates:
            try:
                code = str(manager.get_staff_raw_shift(name, _as_datetime(iso)) or '').strip()
            except Exception as e:
                print(f"Could not read {name}'s shift for {iso}: {e}")
                code = ''
            training = list(overlay.get(name, {}).get(iso, []))
            if code or training:
                context[(name, iso)] = {'track_code': code, 'training': training}
    return context


def build_board(start_date, track_cohort=None, pattern_start=None,
                include_training=True):
    """
    Everything one two-week block's screen needs.

    Returns:
        dict:
            block          the duty_blocks row, or None if it has not been opened
            dates          16 ISO dates — the preceding Fri and Sat, then the 14
            schedule_dates the 14 actually being scheduled
            lead_in_dates  the 2 carried for the rest and turn check
            vehicles       {'day': [...], 'night': [...]}
            staff          one row per clinical staff member, with a `days` map
            grid           {date: {vehicle_code: crew_status result}}
            counters       {date: {'day': pool counts, 'night': pool counts}}
            published      whether the block has been released to staff
            snapshot_missing  published, but with no frozen context behind it, so
                           what it shows can still change under the reader
    """
    block = get_block(start_date)
    dates = block_dates(start_date, include_lead_in=True)
    schedule_dates = dates[LEAD_IN_DAYS:]
    lead_in_dates = dates[:LEAD_IN_DAYS]

    staff_records = clinical_staff()
    by_name = {record['staff_name']: record for record in staff_records}
    lookup = by_name.get

    published = bool(block and block['status'] == BLOCK_PUBLISHED)
    assignments = get_assignments(block['id']) if block else []

    context = {}
    if published:
        context = get_block_context(block['id'])
    # A draft reads live. So does a published block with no snapshot behind it — one
    # published before snapshots existed — which is flagged rather than passed off as
    # frozen, since what it shows can still move.
    snapshot_missing = published and not context
    if not context:
        context = _derive_context(dates, staff_records, track_cohort, pattern_start,
                                  include_training)

    assigned_by = {(row['staff_name'], row['duty_date']): row for row in assignments}

    staff_rows = []
    for record in staff_records:
        name = record['staff_name']
        days = {}
        for iso in dates:
            cell = context.get((name, iso), {})
            track_code = cell.get('track_code', '')
            days[iso] = {
                'track': track_code,
                'shift_kind': shift_kind_of(track_code),
                'training': list(cell.get('training', [])),
                'assignment': assigned_by.get((name, iso)),
            }
        staff_rows.append({**record, 'days': days})

    day_vehicles = get_vehicles(shift_kind=DAY)
    night_vehicles = get_vehicles(shift_kind=NIGHT)
    pairs = get_restricted_pairs()

    grid, counters = {}, {}
    for iso in schedule_dates:
        by_vehicle = {}
        for row in assignments:
            if row['duty_date'] == iso:
                by_vehicle.setdefault(row['vehicle_code'], []).append(row)

        grid[iso] = {
            vehicle['code']: duty_crew.crew_status(
                by_vehicle.get(vehicle['code'], []), lookup, pairs,
                spec=crew_spec_of(vehicle))
            for vehicle in day_vehicles + night_vehicles
        }
        counters[iso] = {
            kind: duty_crew.pool_counts(
                [lookup(row['staff_name']) for row in staff_rows_on(staff_rows, iso, kind)])
            for kind in (DAY, NIGHT)
        }

    return {
        'block': block,
        'dates': dates,
        'schedule_dates': schedule_dates,
        'lead_in_dates': lead_in_dates,
        'vehicles': {DAY: day_vehicles, NIGHT: night_vehicles},
        'staff': staff_rows,
        'grid': grid,
        'counters': counters,
        'published': published,
        'snapshot_missing': snapshot_missing,
    }


def staff_rows_on(staff_rows, iso_date, shift_kind):
    """Whose track has them on a day (or night) shift that date."""
    return [row for row in staff_rows
            if row['days'].get(iso_date, {}).get('shift_kind') == shift_kind]


def available_staff(board, iso_date, shift_kind, unassigned_only=True, spec=None):
    """
    Who the scheduler can still put on a vehicle for this date and shift.

    This is the board's main affordance, and the reason it beats the spreadsheet:
    the sheet could sort its 84 rows, but it could not hide the sixty of them who
    are off that day.

    Args:
        unassigned_only (bool): drop anyone already on a vehicle that date.
        spec (dict, optional): the crew spec the default seat is chosen against.
            None uses the fleet's, which is right until a vehicle is picked.

    Returns:
        list[dict]: staff rows, most senior first, each carrying `seat` — the seat
        they would default to — and `training`, so somebody with a class that day is
        visible rather than merely missing from the list.
    """
    rows = []
    for row in staff_rows_on(board['staff'], iso_date, shift_kind):
        day = row['days'][iso_date]
        if unassigned_only and day.get('assignment'):
            continue
        rows.append({**row, 'seat': default_seat(row, spec),
                     'training': day.get('training', [])})
    rows.sort(key=lambda r: (r['seniority'] is None, r['seniority'] or 0,
                             r['staff_name'].lower()))
    return rows


def block_summary(board):
    """
    A block at a glance.

    Returns:
        dict: a count per status, plus `short_dates` — the dates below minimum
        staffing, which is what a scheduler wants to jump straight to.
    """
    tally = {duty_crew.CREWED: 0, duty_crew.NO_CREW: 0,
             duty_crew.INCOMPLETE: 0, duty_crew.UNSTAFFED: 0}
    short_dates = []

    for iso in board['schedule_dates']:
        statuses = board['grid'].get(iso, {})
        for result in statuses.values():
            tally[result['status']] = tally.get(result['status'], 0) + 1

        by_code = {code: result['status'] for code, result in statuses.items()}
        day = duty_crew.shortfall(by_code, board['vehicles'][DAY])
        night = duty_crew.shortfall(by_code, board['vehicles'][NIGHT])
        if (day['rw'] < MIN_RW_DAY or day['gr'] < MIN_GR_DAY
                or night['rw'] < MIN_RW_NIGHT or night['gr'] < MIN_GR_NIGHT):
            short_dates.append(iso)

    return {**tally, 'short_dates': short_dates}


def snapshot_block(start_date, track_cohort=None, pattern_start=None,
                   include_training=True):
    """
    Freeze what the tracks and the training calendar say, so publishing makes the
    block stop moving.

    Vehicle assignments are already stored in their own table, so this writes only
    the derived context. Without it, a track swap made after publishing would
    silently rewrite a schedule people have already read.

    Returns:
        int: how many context rows were written.
    """
    block = get_block(start_date)
    if not block:
        return 0

    dates = block_dates(start_date, include_lead_in=True)
    context = _derive_context(dates, clinical_staff(), track_cohort, pattern_start,
                              include_training)
    rows = [(name, iso, cell['track_code'], cell['training'])
            for (name, iso), cell in context.items()]
    set_block_context(block['id'], rows)
    return len(rows)
