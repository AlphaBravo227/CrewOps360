#!/usr/bin/env python3
"""
Self-check for the duty schedule: crew composition, the vehicle inventory, block
publishing, and the board built from tracks.

Runs against a throwaway database and verifies that what the board now computes
matches what `Active 2-Week Template v10.17.25.xlsx` worked out with its digit-sum
conditional formatting — and that the parts the spreadsheet could not do (availability
filtering, restricted pairs as a hard block, freezing a published block) behave.

Usage:
    python scripts/check_duty_schedule.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_failures = []
_checks = 0


def check(label, condition, detail=''):
    global _checks
    _checks += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
        _failures.append(label)


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


def main():
    workspace = tempfile.mkdtemp(prefix='duty-check-')
    os.chdir(workspace)
    os.makedirs('data', exist_ok=True)

    from modules import db_utils
    from modules import duty_board
    from modules import duty_crew as dc
    from modules import duty_schedule_db as ddb
    from modules import staff_database as sdb
    from modules.day_pattern import PATTERN_DAYS

    sdb.set_db_path(os.path.join(workspace, 'data/medflight_tracks.db'))
    db_utils.initialize_database()
    sdb.initialize_staff_tables()

    section("Schema")
    check("duty tables initialize", ddb.initialize_duty_tables())
    vehicles = ddb.get_vehicles()
    check("15 vehicles seeded", len(vehicles) == 15, f"got {len(vehicles)}")
    check("10 day vehicles, in the sheet's priority order",
          [v['code'] for v in ddb.get_vehicles(shift_kind=ddb.DAY)]
          == ['D7B', 'D7P', 'D9L', 'D11M', 'D11H', 'MG', 'GR', 'LG', 'PG', 'FLOAT'])
    check("5 night vehicles, in the sheet's priority order",
          [v['code'] for v in ddb.get_vehicles(shift_kind=ddb.NIGHT)]
          == ['N7B', 'N7P', 'N9L', 'NG', 'NP'])
    half = {v['code']: (v['rw_weight'], v['gr_weight']) for v in vehicles}
    check("D7P, N7P and N9L count half rotor-wing and half ground, as AP39/AQ39 did",
          half['D7P'] == (0.5, 0.5) and half['N7P'] == (0.5, 0.5)
          and half['N9L'] == (0.5, 0.5), str({k: half[k] for k in ('D7P', 'N7P', 'N9L')}))

    section("Staff attributes")
    roster = [
        ('Senior RN', 'NURSE', dict(no_matrix=True)),
        ('Junior RN', 'NURSE', dict(no_matrix=False)),
        ('Senior Medic', 'MEDIC', dict(no_matrix=True)),
        ('Junior Medic', 'MEDIC', dict(no_matrix=False)),
        ('Dual RN', 'NURSE', dict(no_matrix=True, is_dual=True)),
        ('Orientee', 'NURSE', dict(no_matrix=False, on_orientation=True)),
    ]
    for index, (name, role, extra) in enumerate(roster):
        ok, message = sdb.add_staff(name, role, seniority=index + 1,
                                    shifts_per_pay_period=6,
                                    date_of_hire='2020-04-19', **extra)
        if not ok:
            check(f"add {name}", False, message)
    check("date_of_hire round-trips",
          sdb.get_staff('Senior RN')['date_of_hire'] == '2020-04-19')
    check("on_orientation round-trips",
          sdb.get_staff('Orientee')['on_orientation'] is True
          and sdb.get_staff('Senior RN')['on_orientation'] is False)
    check("adding the column leaves everyone else counted",
          not dc.on_orientation(sdb.get_staff('Junior RN')))

    section("Crew composition — what the digit-sum rules encoded")
    look = sdb.get_staff

    def status(*rows):
        return dc.crew_status([{'staff_name': n, 'seat': s} for n, s in rows], look)

    # Each case names the spreadsheet total its conditional format keyed on.
    cases = [
        ("0      nobody", (), dc.UNSTAFFED),
        ("9      one senior RN", (('Senior RN', 'rn'),), dc.INCOMPLETE),
        ("90     one senior medic", (('Senior Medic', 'medic'),), dc.INCOMPLETE),
        ("99     senior RN + senior medic",
         (('Senior RN', 'rn'), ('Senior Medic', 'medic')), dc.CREWED),
        ("990    junior RN + senior medic",
         (('Junior RN', 'rn'), ('Senior Medic', 'medic')), dc.CREWED),
        ("9009   senior RN + junior medic",
         (('Senior RN', 'rn'), ('Junior Medic', 'medic')), dc.CREWED),
        ("9900   two juniors",
         (('Junior RN', 'rn'), ('Junior Medic', 'medic')), dc.NO_CREW),
        ("909    two nurses",
         (('Senior RN', 'rn'), ('Junior RN', 'rn')), dc.NO_CREW),
        ("9090   two medics",
         (('Senior Medic', 'medic'), ('Junior Medic', 'medic')), dc.NO_CREW),
    ]
    for label, rows, want in cases:
        got = status(*rows)
        check(f"{label} -> {want}", got['status'] == want,
              f"got {got['status']} ({got['reason']})")

    section("The p suffix — a dual provider in the medic seat")
    got = status(('Senior RN', 'rn'), ('Dual RN', 'medic'))
    check("two nurses crew when one is a dual in the medic seat",
          got['status'] == dc.CREWED, f"{got['status']} ({got['reason']})")
    got = status(('Senior RN', 'rn'), ('Junior RN', 'medic'))
    check("a nurse who is not dual cannot take the medic seat",
          got['status'] == dc.NO_CREW and 'seat' in got['reason'],
          f"{got['status']} ({got['reason']})")

    section("Orientation")
    got = status(('Senior Medic', 'medic'), ('Orientee', 'rn'))
    check("an orientee does not fill a crew seat", got['status'] == dc.INCOMPLETE,
          f"{got['status']} ({got['reason']})")
    got = status(('Senior RN', 'rn'), ('Senior Medic', 'medic'), ('Orientee', 'third'))
    check("a crew plus an orientee is still a crew", got['status'] == dc.CREWED,
          f"{got['status']} ({got['reason']})")

    section("Restricted pairs")
    ddb.set_restricted_pair('Senior RN', 'Senior Medic', reason='couple')
    got = status(('Senior RN', 'rn'), ('Senior Medic', 'medic'))
    check("a restricted pair blocks an otherwise legal crew",
          got['status'] == dc.NO_CREW and 'may not crew' in got['reason'],
          f"{got['status']} ({got['reason']})")
    check("the restriction reads from either side",
          ddb.restricted_partners('Senior Medic') == {'senior rn'}
          and ddb.restricted_partners('Senior RN') == {'senior medic'},
          str(ddb.restricted_partners('Senior Medic')))
    ddb.delete_restricted_pair('Senior Medic', 'Senior RN')
    check("removing it, added the other way round, clears the block",
          status(('Senior RN', 'rn'), ('Senior Medic', 'medic'))['status'] == dc.CREWED)

    section("Possible crews — the sheet's Q20/Q29 pairing formula")
    check("capped by the senior count", dc.possible_crews(3, 9, 9, 0) == 3)
    check("capped by the short side", dc.possible_crews(99, 4, 8, 0) == 4)
    check("duals fill the short side", dc.possible_crews(99, 4, 8, 2) == 6)
    check("duals split evenly when both sides are short",
          dc.possible_crews(99, 0, 0, 4) == 2)

    section("Blocks and the board")
    conn = db_utils.get_db_connection()
    cursor = conn.cursor()
    for name, _, _ in roster:
        pattern = {day: ('N' if name in ('Junior RN', 'Junior Medic') else 'D')
                   for day in PATTERN_DAYS}
        cursor.execute("""INSERT INTO tracks (staff_name, track_data, submission_date,
                                              is_approved, is_active)
                          VALUES (?, ?, datetime('now'), 1, 1)""",
                       (name, json.dumps(pattern)))
    conn.commit()

    start = '2026-10-11'
    ddb.get_or_create_block(start)
    dates = ddb.block_dates(start, include_lead_in=True)
    check("a block is 14 days plus the preceding Fri and Sat",
          len(dates) == 16 and dates[0] == '2026-10-09' and dates[-1] == '2026-10-24',
          str(dates[:3]))

    board = duty_board.build_board(start, include_training=False)
    check("the board carries every clinical staff member", len(board['staff']) == 6,
          str(len(board['staff'])))
    check("tracks resolve onto real dates",
          any(row['days'][start]['shift_kind'] == ddb.DAY for row in board['staff']))

    free_day = duty_board.available_staff(board, start, ddb.DAY)
    check("availability filters to the day shift only",
          {r['staff_name'] for r in free_day}
          == {'Senior RN', 'Senior Medic', 'Dual RN', 'Orientee'},
          str([r['staff_name'] for r in free_day]))
    check("availability is in seniority order",
          [r['staff_name'] for r in free_day][0] == 'Senior RN')
    check("a medic defaults to the medic seat",
          next(r['seat'] for r in free_day if r['staff_name'] == 'Senior Medic') == 'medic')
    check("a dual defaults to the RN seat, and is moved across deliberately",
          next(r['seat'] for r in free_day if r['staff_name'] == 'Dual RN') == 'rn')

    block = ddb.get_block(start)
    ddb.set_assignment(block['id'], 'Senior RN', start, 'D7B', seat='rn')
    ddb.set_assignment(block['id'], 'Senior Medic', start, 'D7B', seat='medic')
    board = duty_board.build_board(start, include_training=False)
    check("assigning a crew turns the cell green",
          board['grid'][start]['D7B']['status'] == dc.CREWED)
    check("assigned staff leave the available list",
          'Senior RN' not in [r['staff_name']
                              for r in duty_board.available_staff(board, start, ddb.DAY)])
    check("one row per person per date — reassigning moves rather than duplicates",
          (ddb.set_assignment(block['id'], 'Senior RN', start, 'GR', seat='rn')
           or True)
          and len(ddb.get_assignments(block['id'], staff_name='Senior RN')) == 1)

    section("Publishing freezes the derived half")
    written = duty_board.snapshot_block(start, include_training=False)
    check("publishing writes a context snapshot", written > 0, str(written))
    ddb.publish_block(start, published_by='check')
    frozen = duty_board.build_board(start, include_training=False)
    check("a published block reads its snapshot",
          frozen['published'] and not frozen['snapshot_missing'])
    before = [frozen['staff'][0]['days'][d]['track'] for d in frozen['schedule_dates']]

    cursor.execute("UPDATE tracks SET track_data = ? WHERE staff_name = ?",
                   (json.dumps({day: '' for day in PATTERN_DAYS}),
                    frozen['staff'][0]['staff_name']))
    conn.commit()
    after = duty_board.build_board(start, include_training=False)
    check("a track change does not move a published block",
          before == [after['staff'][0]['days'][d]['track']
                     for d in after['schedule_dates']])

    ddb.unpublish_block(start)
    ddb.clear_block_context(block['id'])
    live = duty_board.build_board(start, include_training=False)
    check("a draft picks the change up straight away",
          before != [live['staff'][0]['days'][d]['track']
                     for d in live['schedule_dates']])

    section("Export")
    from modules.duty_board_ui import _fmt, export_frame
    try:
        _fmt('2026-10-04')
        portable = True
    except ValueError:
        portable = False
    check("date headings avoid the non-portable %-d strftime", portable)
    check("date headings read as the sheet's did", _fmt('2026-10-04') == 'Sun 4 Oct',
          _fmt('2026-10-04'))

    ddb.set_assignment(block['id'], 'Dual RN', start, 'GR', seat='medic')
    frame = export_frame(duty_board.build_board(start, include_training=False))
    dual_row = frame[frame['Staff'] == 'Dual RN'].iloc[0]
    check("a dual in the medic seat exports with the p suffix",
          dual_row[start] == 'GRp', repr(dual_row[start]))

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("\nFailed:")
        for failure in _failures:
            print(f"  - {failure}")
        return 1
    print("Everything the spreadsheet did, the board does.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
