#!/usr/bin/env python3
"""
Self-check for the staff database.

Runs the Excel import into a throwaway database and verifies two things:

  1. Parity — every attribute the app used to read out of Preferences v6.xlsx and the
     Education Classes Roster comes back identically from the database, so wiring the
     app to the database does not change behavior.
  2. Roster management — add, update, activate/deactivate, rename (including
     propagation of a name change into other tables) and delete all behave.
  3. Educational groupings — the placement sheets seed onto the roster, round-trip
     through the getters, and report the same name mismatches they did when they were
     transcribed.

Usage:
    python scripts/check_staff_database.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import seed_educational_groupings as groupings  # noqa: E402

from modules import staff_database as staffdb  # noqa: E402
from modules.staff_import import (  # noqa: E402
    DEFAULT_PREFERENCES_PATH,
    DEFAULT_REQUIREMENTS_PATH,
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


def check_requirements_parity():
    """Requirements values come back exactly as the spreadsheet had them."""
    print("\nParity with Requirements.xlsx")

    original = pd.read_excel(DEFAULT_REQUIREMENTS_PATH)
    built = staffdb.build_requirements_df()

    check("build_requirements_df reproduces the Requirements column layout",
          list(built.columns) == list(original.columns),
          f"got {list(built.columns)}")

    original = original.set_index(original['STAFF NAME'].map(staffdb.clean_name))
    rebuilt = built.set_index('STAFF NAME')

    missing = sorted(set(original.index) - set(rebuilt.index))
    check("every staff member in Requirements is in the frame", not missing,
          f"missing: {missing[:5]}")

    fields = [
        ('SHIFTS PER PAY PERIOD', staffdb.to_optional_int),
        ('NIGHT MINIMUM', staffdb.to_optional_int),
        ('WEEKEND MINIMUM', staffdb.to_optional_int),
        ('WEEKEND GROUP', staffdb.to_weekend_group),
        ('EMAIL', staffdb.to_email),
    ]
    differences = []
    for name in original.index:
        if name not in rebuilt.index:
            continue
        for column, convert in fields:
            expected = convert(original.loc[name, column])
            actual = convert(rebuilt.loc[name, column])
            if expected != actual:
                differences.append((name, column, expected, actual))
    check("every requirements value matches the spreadsheet", not differences,
          f"{differences[:5]}")

    # Blank and 0 mean different things and both have to survive the round trip.
    blank_in_file = [name for name in original.index
                     if staffdb.to_optional_int(
                         original.loc[name, 'SHIFTS PER PAY PERIOD']) is None]
    check("blank shifts-per-pay-period stays blank (marks non-bidding staff)",
          blank_in_file and all(staffdb.get_shifts_per_pay_period(name) is None
                                for name in blank_in_file),
          f"{blank_in_file[:5]}")

    zero_in_file = [name for name in original.index
                    if staffdb.to_optional_int(
                        original.loc[name, 'SHIFTS PER PAY PERIOD']) == 0]
    check("a shifts-per-pay-period of 0 stays 0, not blank",
          zero_in_file and all(staffdb.get_shifts_per_pay_period(name) == 0
                               for name in zero_in_file),
          f"{zero_in_file[:5]}")

    emails = {name: staffdb.to_email(original.loc[name, 'EMAIL'])
              for name in original.index}
    check("emails are readable per staff member",
          all(staffdb.get_email(name) == email for name, email in emails.items()))

    requirements_map = staffdb.get_requirements_map()
    check("get_requirements_map carries all five fields",
          all(set(entry) == {'shifts_per_pay_period', 'night_minimum',
                             'weekend_minimum', 'weekend_group', 'email'}
              for entry in requirements_map.values()))


def check_requirements_editing():
    """Requirements fields validate and clear correctly."""
    print("\nRequirements editing")

    staffdb.add_staff('Testcase Reqs', 'MEDIC', shifts_per_pay_period=6,
                      night_minimum=2, weekend_minimum=5, weekend_group='B',
                      email='testcase.reqs@example.org', changed_by='self-check')
    record = staffdb.get_staff('Testcase Reqs')
    check("requirements save on add",
          record and record['shifts_per_pay_period'] == 6
          and record['night_minimum'] == 2 and record['weekend_minimum'] == 5
          and record['weekend_group'] == 'B'
          and record['email'] == 'testcase.reqs@example.org',
          str(record))

    ok, message = staffdb.update_staff('Testcase Reqs', email='not-an-email',
                                       changed_by='self-check')
    check("an invalid email is rejected", not ok, message)

    ok, message = staffdb.update_staff('Testcase Reqs', weekend_group='Z',
                                       changed_by='self-check')
    check("an unknown weekend group is rejected rather than silently cleared",
          not ok and staffdb.get_weekend_group('Testcase Reqs') == 'B', message)

    ok, message = staffdb.update_staff('Testcase Reqs', night_minimum='abc',
                                       changed_by='self-check')
    check("an unparseable number is rejected rather than silently cleared",
          not ok and staffdb.get_night_minimum('Testcase Reqs') == 2, message)

    ok, message = staffdb.update_staff('Testcase Reqs', weekend_group='',
                                       changed_by='self-check')
    check("a blank weekend group clears it",
          ok and staffdb.get_weekend_group('Testcase Reqs') is None, message)

    ok, message = staffdb.update_staff('Testcase Reqs', shifts_per_pay_period=-1,
                                       changed_by='self-check')
    check("a negative shifts-per-pay-period is rejected", not ok, message)

    ok, message = staffdb.update_staff('Testcase Reqs', night_minimum=99,
                                       changed_by='self-check')
    check("a night minimum beyond the cycle length is rejected", not ok, message)

    ok, message = staffdb.update_staff('Testcase Reqs', shifts_per_pay_period=None,
                                       changed_by='self-check')
    check("clearing shifts-per-pay-period marks them non-bidding",
          ok and staffdb.get_shifts_per_pay_period('Testcase Reqs') is None, message)

    ok, message = staffdb.update_staff('Testcase Reqs', shifts_per_pay_period=0,
                                       changed_by='self-check')
    check("a shifts-per-pay-period of 0 is accepted and distinct from blank",
          ok and staffdb.get_shifts_per_pay_period('Testcase Reqs') == 0, message)

    staffdb.delete_staff('Testcase Reqs', changed_by='self-check', force=True)


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
    check("bidding staff with no email are flagged",
          set(issues['missing_email']) == {'Gallagher', 'Moynihan', 'Saia'},
          str(issues['missing_email']))
    check("management is not flagged for having no shift requirements",
          not issues['missing_requirements'], str(issues['missing_requirements']))


def check_educational_groupings():
    """The placement sheets seed onto the roster and read back unchanged."""
    print("\nEducational groupings")

    index = groupings.build_index()
    placements, unmatched, duplicated = groupings.collect(index)

    check("no name is listed in two columns of the same sheet",
          not duplicated, str(duplicated))

    unmatched_names = [name for _, _, name in unmatched]
    check("Wheeler is on the OR sheet but on no roster",
          'Wheeler' in unmatched_names, str(unmatched_names))
    # Grotton, Lurie and McWeeney joined on the FY27 roster, so they go unmatched when
    # this runs against FY26 — the import default. Anything beyond those four means a
    # sheet name has stopped lining up with the roster.
    check("no other sheet name has come adrift from the roster",
          set(unmatched_names) <= {'Wheeler', 'Grotton', 'Lurie', 'McWeeney'},
          str(unmatched_names))

    outcome = groupings.apply(placements, changed_by='self-check')
    check("seeding the groupings reports no errors", not outcome['errors'],
          str(outcome['errors']))
    check("every matched placement was written",
          outcome['unchanged'] == 0
          and len(outcome['changes']) == sum(len(p) for p in placements.values()),
          f"{len(outcome['changes'])} written, {outcome['unchanged']} unchanged")

    # Every column should hold exactly the staff it listed, less any name the roster
    # this ran against does not carry.
    def missing_from(sheet, column):
        return sum(1 for s, c, _ in unmatched if s == sheet and c == column)

    education_sizes = {group: (len(staffdb.get_education_group_members(
                                   group, include_inactive=True)),
                               len(names) - missing_from('Group', group))
                       for group, names in groupings.EDUCATION_GROUPS.items()}
    or_sizes = {group: (len(staffdb.get_or_group_members(group, include_inactive=True)),
                        len(names) - missing_from('OR', group))
                for group, names in groupings.OR_GROUPS.items()}
    check("every education group holds the staff its column listed",
          all(got == expected for got, expected in education_sizes.values()),
          str(education_sizes))
    check("every OR grouping holds the staff its column listed",
          all(got == expected for got, expected in or_sizes.values()), str(or_sizes))

    # The two placements are independent: more staff hold an OR placement than a
    # cohort, so neither can be derived from the other.
    education = staffdb.get_education_group_mapping(include_inactive=True)
    or_groups = staffdb.get_or_group_mapping(include_inactive=True)
    check("the two groupings are independent of one another",
          len(education) == sum(e for _, e in education_sizes.values())
          and len(or_groups) == sum(e for _, e in or_sizes.values())
          and set(education) != set(or_groups),
          f"{len(education)} in a cohort, {len(or_groups)} with an OR placement")

    # 0 is the "No OR" placement and has to survive the round trip as a value, not as
    # the falsy stand-in for "unplaced".
    check("a No OR placement reads back as 0, not as unplaced",
          staffdb.get_or_group('Ahlstedt') == 0
          and 'Ahlstedt' in staffdb.get_or_group_mapping(include_inactive=True),
          repr(staffdb.get_or_group('Ahlstedt')))
    check("an unplaced staff member reads back as None",
          staffdb.get_or_group('Johnson') is None
          and staffdb.get_education_group('Johnson') is None)
    check("the sheets' own column headings resolve",
          staffdb.get_or_group_members('No OR') == staffdb.get_or_group_members(0)
          and (staffdb.get_education_group_members('Group 1')
               == staffdb.get_education_group_members('1')))

    # The sheets place the clinical roster; management, the non-clinical roles and the
    # newest hires are the expected blanks.
    issues = staffdb.get_roster_issues(include_inactive=True)
    check("only Johnson works tracks with neither placement",
          issues['missing_or_group'] == ['Johnson'], str(issues['missing_or_group']))

    # Re-running must be a no-op, since it is how a re-seed is done.
    again = groupings.apply(placements, changed_by='self-check')
    check("re-seeding the groupings changes nothing",
          not again['changes'] and not again['errors'], str(again['changes']))

    # Placements already on file are not overwritten unless asked.
    staffdb.update_staff('Bach', education_group='1', changed_by='self-check')
    guarded = groupings.apply(placements, changed_by='self-check')
    check("a placement already on file is reported, not overwritten",
          staffdb.get_education_group('Bach') == '1'
          and ('Bach', 'education_group', '1', '3') in guarded['conflicts'],
          str(guarded['conflicts']))
    forced = groupings.apply(placements, overwrite=True, changed_by='self-check')
    check("--overwrite lets the sheet win",
          staffdb.get_education_group('Bach') == '3' and not forced['conflicts'])


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
        check_requirements_parity()
        check_roster_issues()
        check_educational_groupings()
        check_roster_management()
        check_requirements_editing()

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
