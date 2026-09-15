#!/usr/bin/env python3
"""
Self-check for the base registry: bases as rows rather than as columns.

A base used to be eight columns on two tables and a hardcoded list in five modules,
with "Manchester has no night shift" written into get_base_shift_counts() as a
literal. This verifies the replacement behaves — including the part that matters, a
sixth base needing no schema change — and that nothing the bidding screens read
through changed shape.

Usage:
    python scripts/check_bases.py
"""

import os
import sys
import tempfile

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
    workspace = tempfile.mkdtemp(prefix='bases-check-')
    os.chdir(workspace)
    os.makedirs('data', exist_ok=True)

    from modules import bases
    from modules import db_utils
    from modules import duty_schedule_db as ddb
    from modules import staff_database as sdb
    from modules.hypothetical_scheduler_new import (
        _DEFAULT_BASE_SHIFT_COUNTS, _bases_for, _build_available_slots)

    sdb.set_db_path(os.path.join(workspace, 'data/medflight_tracks.db'))
    db_utils.initialize_database()
    sdb.initialize_staff_tables()
    ddb.initialize_duty_tables()

    section("The registry")
    check("base tables initialize", bases.initialize_base_tables())
    codes = [b['code'] for b in bases.get_bases()]
    check("the five bases are seeded, in editor order",
          codes == ['KBED', 'KMHT', 'KLWM', 'KPYM', '1B9'], str(codes))
    check("labels come with them",
          bases.base_labels().get('1B9') == 'Mansfield')

    section("Counts derive from the fleet, not from a literal")
    # The point worth proving: the historical hardcoded defaults were never anything
    # but a count of where the vehicles are.
    derived = bases.base_shift_counts()
    check("derived counts equal the historical hardcoded defaults",
          derived == _DEFAULT_BASE_SHIFT_COUNTS,
          f"derived {derived} vs {_DEFAULT_BASE_SHIFT_COUNTS}")
    check("a base with no night vehicle has no night presence",
          derived['KMHT']['night'] == 0 and derived['1B9']['night'] == 0)
    check("night bases are the ones with night vehicles",
          _bases_for('night') == ['KBED', 'KLWM', 'KPYM'], str(_bases_for('night')))
    check("day bases are all five", len(_bases_for('day')) == 5)

    counts = db_utils.get_base_shift_counts('FY26')
    check("get_base_shift_counts answers without a track config",
          counts['KBED']['night'] == 2 and counts['KMHT']['night'] == 0, str(counts))
    slots, _ = _build_available_slots('night', counts)
    check("slot building is unchanged in shape", len(slots) == 5, str(slots))

    section("A sixth base needs no schema change")
    bases.set_base('KORH', 'Worcester', sort_order=6)
    ddb.set_vehicle('D11W', label='Day 1100 Worcester', shift_kind=ddb.DAY,
                    priority=11, base='KORH', rw_weight=1.0, gr_weight=0.0)
    check("the base joins the registry", 'KORH' in [b['code'] for b in bases.get_bases()])
    check("its counts derive from the vehicle put there",
          bases.base_shift_counts()['KORH'] == {'day': 1, 'night': 0},
          str(bases.base_shift_counts().get('KORH')))
    check("it appears for days and not for nights",
          'KORH' in _bases_for('day') and 'KORH' not in _bases_for('night'))

    section("Preferences round-trip through the interface callers already had")
    sdb.add_staff('Bell', 'NURSE', seniority=1)
    ok, message = db_utils.save_location_preferences_to_db(
        'Bell',
        {'KBED': 3, 'KMHT': 5, 'KLWM': 4, 'KPYM': 1, '1B9': 2, 'KORH': 6},
        {'KBED': 2, 'KLWM': 3, 'KPYM': 1},
        '02420', True, 'Yes')
    check("saving succeeds", ok, str(message))

    ok, prefs = db_utils.get_location_preferences_from_db('Bell')
    check("reading back succeeds", ok, str(prefs))
    check("the sixth base survives — the columns could not have held it",
          prefs['day_locations'].get('KORH') == 6, str(prefs['day_locations']))
    check("the five originals are unchanged",
          prefs['day_locations']['KPYM'] == 1
          and prefs['night_locations'] == {'KBED': 2, 'KLWM': 3, 'KPYM': 1})
    check("the rest of the row is untouched",
          prefs['zip_code'] == '02420' and prefs['reduced_rest_ok'] is True
          and prefs['n_to_d_flex'] == 'Yes')

    ok, everyone = db_utils.get_all_location_preferences()
    check("get_all_location_preferences carries it too",
          ok and everyone[0]['day_locations'].get('KORH') == 6)

    cursor = db_utils.get_db_connection().cursor()
    cursor.execute("""SELECT day_kpym, night_kbed FROM user_location_preferences
                      WHERE staff_name = 'Bell'""")
    check("the legacy columns are still written for the five they can name",
          cursor.fetchone() == (1, 2))

    section("Migrating the old columns into rows")
    cursor.execute("DELETE FROM staff_base_preferences")
    db_utils.get_db_connection().commit()
    moved = bases.migrate_legacy_columns()
    check("the migration lifts every column value it can", moved == 8, str(moved))
    after = bases.get_preferences('Bell')
    check("day and night both come across",
          after['day']['KPYM'] == 1 and after['night']['KBED'] == 2, str(after))
    check("a base the columns never held does not appear",
          'KORH' not in after['day'])

    bases.set_preferences('Bell', day_locations={'KBED': 1})
    check("re-running it does not resurrect old values",
          bases.migrate_legacy_columns() == 0
          and bases.get_preferences('Bell')['day'] == {'KBED': 1},
          str(bases.get_preferences('Bell')['day']))

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("\nFailed:")
        for failure in _failures:
            print(f"  - {failure}")
        return 1
    print("A base is a row. Adding one is data entry.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
