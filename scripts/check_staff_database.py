#!/usr/bin/env python3
"""
Self-check for the staff database.

Runs the Excel import into a throwaway database and verifies two things:

  1. Parity — every attribute the app used to read out of Preferences v6.xlsx and the
     Education Classes Roster comes back identically from the database, so wiring the
     app to the database does not change behavior.
  2. Roster management — add, update, activate/deactivate, rename (including
     propagation of a name change into other tables) and delete all behave.

Usage:
    python scripts/check_staff_database.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from modules import staff_database as staffdb  # noqa: E402
from modules.staff_import import (  # noqa: E402
    DEFAULT_PREFERENCES_PATH,
    DEFAULT_ROSTER_PATH,
    ENROLLMENT_SHEET,
    import_staff_roster,
)

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


def check_parity():
    """Database values match what the spreadsheets said."""
    print("\nParity with the Excel sources")

    roster = pd.read_excel(DEFAULT_ROSTER_PATH, sheet_name=ENROLLMENT_SHEET)
    prefs = pd.read_excel(DEFAULT_PREFERENCES_PATH)

    roster_names = [staffdb.clean_name(n) for n in roster['STAFF NAME'] if staffdb.clean_name(n)]
    db_names = staffdb.get_staff_names(include_inactive=True)

    missing = sorted(set(roster_names) - set(db_names))
    check("every roster name is on the staff roster", not missing, f"missing: {missing}")

    # Roster attributes: Role / MGMT / DUAL / Educator AT
    role_mismatches, mgmt_mismatches, dual_mismatches, educator_mismatches = [], [], [], []
    for _, row in roster.iterrows():
        name = staffdb.clean_name(row['STAFF NAME'])
        if not name:
            continue
        record = staffdb.get_staff(name)
        if record is None:
            continue
        if staffdb.canonical_role(row['Role']) != staffdb.canonical_role(record['role']):
            role_mismatches.append((name, row['Role'], record['role']))
        if bool(staffdb.to_flag(row['MGMT'])) != record['is_management']:
            mgmt_mismatches.append(name)
        # DUAL may be set from Preferences v6 as well, so the database is allowed to be
        # dual where the roster checkbox is blank, but never the other way round.
        if staffdb.to_flag(row['DUAL']) and not record['is_dual']:
            dual_mismatches.append(name)
        if bool(staffdb.to_flag(row['Educator AT'])) != record['is_educator_at']:
            educator_mismatches.append(name)

    check("Role matches the roster for every staff member", not role_mismatches,
          f"{role_mismatches[:5]}")
    check("MGMT matches the roster for every staff member", not mgmt_mismatches,
          f"{mgmt_mismatches[:5]}")
    check("DUAL is set wherever the roster checks it", not dual_mismatches,
          f"{dual_mismatches[:5]}")
    check("Educator AT matches the roster for every staff member", not educator_mismatches,
          f"{educator_mismatches[:5]}")

    # Preferences v6 attributes: No Matrix / Seniority / ROLE
    no_matrix_mismatches, seniority_mismatches, clinical_role_mismatches = [], [], []
    for _, row in prefs.iterrows():
        name = staffdb.clean_name(row['STAFF NAME'])
        if not name:
            continue
        record = staffdb.get_staff(name)
        if record is None:
            continue
        if bool(staffdb.to_flag(row['No Matrix'])) != record['no_matrix']:
            no_matrix_mismatches.append(name)
        if staffdb.to_seniority(row['Seniority']) != record['seniority']:
            seniority_mismatches.append((name, row['Seniority'], record['seniority']))
        if str(row['ROLE']).strip().lower() != record['clinical_role']:
            clinical_role_mismatches.append((name, row['ROLE'], record['clinical_role']))

    check("No Matrix matches Preferences v6", not no_matrix_mismatches,
          f"{no_matrix_mismatches[:5]}")
    check("Seniority matches Preferences v6", not seniority_mismatches,
          f"{seniority_mismatches[:5]}")
    # Puopolo is dual in Preferences v6 with an unchecked roster DUAL box; the import
    # takes the union, so this is the one expected difference.
    unexpected = [m for m in clinical_role_mismatches if m[0] != 'Puopolo']
    check("clinical role (nurse/medic/dual) matches Preferences v6, "
          "apart from the known Puopolo conflict", not unexpected, f"{unexpected[:5]}")

    # build_preferences_df must be a drop-in for pd.read_excel on Preferences v6.
    built = staffdb.build_preferences_df()
    check("build_preferences_df reproduces the Preferences v6 column layout",
          list(built.columns) == list(prefs.columns),
          f"got {list(built.columns)}")

    prefs_names = {staffdb.clean_name(n) for n in prefs['STAFF NAME'] if staffdb.clean_name(n)}
    built_names = set(built['STAFF NAME'])
    check("build_preferences_df covers every staff member Preferences v6 held",
          prefs_names <= built_names, f"missing: {sorted(prefs_names - built_names)[:5]}")
    check("build_preferences_df holds only clinical staff",
          all(staffdb.get_role(n) in ('NURSE', 'MEDIC') for n in built_names))

    built_by_name = built.set_index('STAFF NAME')
    prefs_by_name = prefs.set_index(prefs['STAFF NAME'].map(staffdb.clean_name))
    seniority_diffs = [
        n for n in prefs_names
        if staffdb.to_seniority(prefs_by_name.loc[n, 'Seniority'])
        != staffdb.to_seniority(built_by_name.loc[n, 'Seniority'])
    ]
    check("build_preferences_df carries the same Seniority values", not seniority_diffs,
          f"{seniority_diffs[:5]}")

    # Shift scores seeded from the spreadsheet come back through the built frame.
    shift_diffs = []
    for name in sorted(prefs_names):
        for shift in ('D7B', 'N7B', 'GR', 'PG'):
            expected = staffdb.to_seniority(prefs_by_name.loc[name, shift]) or 0
            actual = staffdb.to_seniority(built_by_name.loc[name, shift]) or 0
            if expected != actual:
                shift_diffs.append((name, shift, expected, actual))
    check("seeded shift preference scores match Preferences v6", not shift_diffs,
          f"{shift_diffs[:5]}")

    # Mapping helpers the track code will use.
    role_mapping = staffdb.get_role_mapping()
    seniority_mapping = staffdb.get_seniority_mapping()
    check("get_role_mapping covers all active staff",
          len(role_mapping) == staffdb.staff_count(include_inactive=False))
    check("get_seniority_mapping returns unique ranks",
          len(set(seniority_mapping.values())) == len(seniority_mapping))
    check("management staff match the roster's MGMT column",
          set(staffdb.get_management_names()) ==
          {staffdb.clean_name(r['STAFF NAME']) for _, r in roster.iterrows()
           if staffdb.to_flag(r['MGMT'])})
    check("educator-authorized staff match the roster's Educator AT column",
          set(staffdb.get_educator_names()) ==
          {staffdb.clean_name(r['STAFF NAME']) for _, r in roster.iterrows()
           if staffdb.to_flag(r['Educator AT'])})


def check_roster_management():
    """Add / update / deactivate / rename / delete behave."""
    print("\nRoster management")

    ok, message = staffdb.add_staff('Testcase Nurse', 'NURSE', seniority=9001,
                                    changed_by='self-check')
    check("add a staff member", ok, message)

    ok, _ = staffdb.add_staff('Testcase Nurse', 'MEDIC', changed_by='self-check')
    check("adding a duplicate name is rejected", not ok)

    ok, _ = staffdb.add_staff('Testcase Nurse Two', 'NURSE', seniority=9001,
                              changed_by='self-check')
    check("a duplicate seniority rank is rejected", not ok)

    ok, _ = staffdb.add_staff('Testcase Bad Role', 'WIZARD', changed_by='self-check')
    check("an unknown role is rejected", not ok)

    ok, message = staffdb.update_staff('Testcase Nurse', is_educator_at=True,
                                       no_matrix=True, changed_by='self-check')
    record = staffdb.get_staff('Testcase Nurse')
    check("update attributes", ok and record['is_educator_at'] and record['no_matrix'],
          message)

    ok, message = staffdb.update_staff('Testcase Nurse', role='dual',
                                       changed_by='self-check')
    record = staffdb.get_staff('Testcase Nurse')
    check("setting role to 'dual' stores NURSE plus the dual flag",
          ok and record['role'] == 'NURSE' and record['is_dual']
          and record['clinical_role'] == 'dual' and record['effective_role'] == 'nurse',
          message)

    ok, message = staffdb.set_staff_active('Testcase Nurse', False, changed_by='self-check')
    check("deactivate hides the staff member from the active roster",
          ok and 'Testcase Nurse' not in staffdb.get_staff_names()
          and 'Testcase Nurse' in staffdb.get_staff_names(include_inactive=True),
          message)

    ok, _ = staffdb.set_staff_active('Testcase Nurse', True, changed_by='self-check')
    check("reactivate puts them back", ok and 'Testcase Nurse' in staffdb.get_staff_names())

    # A name change has to follow the staff member through the rest of the database.
    conn = staffdb._get_conn()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, staff_name TEXT NOT NULL,
        track_data TEXT, submission_date TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS track_swaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT, requester_name TEXT NOT NULL,
        other_member_name TEXT NOT NULL)''')
    cursor.execute("INSERT INTO tracks (staff_name, track_data, submission_date) VALUES (?, '{}', '')",
                   ('Testcase Nurse',))
    cursor.execute("INSERT INTO track_swaps (requester_name, other_member_name) VALUES (?, ?)",
                   ('Testcase Nurse', 'Bell'))
    conn.commit()
    staffdb.invalidate_cache()

    references = staffdb.count_staff_references('Testcase Nurse')
    check("related rows are found before a rename",
          references.get('tracks.staff_name') == 1
          and references.get('track_swaps.requester_name') == 1,
          str(references))

    ok, message, rows = staffdb.rename_staff('Testcase Nurse', 'Testcase Married',
                                             changed_by='self-check')
    cursor.execute("SELECT COUNT(*) FROM tracks WHERE staff_name = 'Testcase Married'")
    renamed_tracks = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM track_swaps WHERE requester_name = 'Testcase Married'")
    renamed_swaps = cursor.fetchone()[0]
    check("rename updates the roster and every related row",
          ok and staffdb.get_staff('Testcase Married') is not None
          and staffdb.get_staff('Testcase Nurse') is None
          and renamed_tracks == 1 and renamed_swaps == 1,
          message)

    ok, _, _ = staffdb.rename_staff('Testcase Married', 'Bell', changed_by='self-check')
    check("renaming onto an existing name is rejected", not ok)

    history = staffdb.get_name_history(limit=5)
    check("the name change is recorded in name history",
          history and history[0]['old_name'] == 'Testcase Nurse'
          and history[0]['new_name'] == 'Testcase Married')

    ok, message = staffdb.delete_staff('Testcase Married', changed_by='self-check')
    check("delete is refused while related rows exist", not ok, message)

    ok, message = staffdb.delete_staff('Testcase Married', changed_by='self-check',
                                       force=True)
    check("a forced delete removes the roster entry",
          ok and staffdb.get_staff('Testcase Married') is None, message)

    log = staffdb.get_audit_log(limit=50)
    actions = {entry['action'] for entry in log}
    check("every change is in the audit log",
          {'added', 'updated', 'activated', 'deactivated', 'renamed', 'deleted'} <= actions,
          str(sorted(actions)))


def check_roster_issues():
    """Rows needing attention are reported rather than guessed at."""
    print("\nRoster issues")
    issues = staffdb.get_roster_issues()
    check("staff imported without a role are flagged",
          set(issues['unassigned_role']) == {'Chaber', 'DiNardo', 'Noland', 'Shewan'},
          str(issues['unassigned_role']))
    check("clinical staff with no seniority are flagged",
          set(issues['missing_seniority']) == {'Farkas', 'Frakes'},
          str(issues['missing_seniority']))
    check("no duplicate seniority ranks were imported",
          not issues['duplicate_seniority'], str(issues['duplicate_seniority']))


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, 'staff_check.db')
        staffdb.set_db_path(db_path)
        print(f"Temporary database: {db_path}")

        # The preference tables normally exist in the app database; create them here so
        # the Preferences v6 shift scores have somewhere to be seeded.
        conn = staffdb._get_conn()
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT, staff_name TEXT NOT NULL,
                shift_name TEXT NOT NULL, preference_score INTEGER NOT NULL,
                shift_type TEXT NOT NULL, created_date TEXT NOT NULL,
                modified_date TEXT NOT NULL, is_active INTEGER DEFAULT 1,
                UNIQUE(staff_name, shift_name));
            CREATE TABLE IF NOT EXISTS user_boolean_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT, staff_name TEXT NOT NULL,
                preference_name TEXT NOT NULL, preference_value TEXT NOT NULL,
                created_date TEXT NOT NULL, modified_date TEXT NOT NULL,
                is_active INTEGER DEFAULT 1, UNIQUE(staff_name, preference_name));
        ''')
        conn.commit()
        staffdb.invalidate_cache()

        report = import_staff_roster(changed_by='self-check')
        print(f"Imported {len(report['added'])} staff, "
              f"{report['preferences_seeded']} preference rows.")
        if report['errors']:
            for error in report['errors']:
                print(f"  IMPORT ERROR: {error}")
            _failures.append('import errors')

        check_parity()
        check_roster_issues()
        check_roster_management()

        # A second import must not disturb what is already there.
        print("\nRe-import")
        before = staffdb.get_all_staff(include_inactive=True)
        second = import_staff_roster(changed_by='self-check')
        after = staffdb.get_all_staff(include_inactive=True)
        check("re-importing changes nothing",
              before == after and not second['added'] and not second['updated'],
              f"added={second['added']}, updated={second['updated']}")

        staffdb.set_db_path(None)

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("Failed: " + ", ".join(_failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
