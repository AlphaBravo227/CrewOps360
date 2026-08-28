#!/usr/bin/env python3
"""
Self-check for the training admin functions across multiple fiscal years.

The staff side of the training app was scoped to a training year first; the admin
side inherited that year without ever naming it, and was limited to the years staff
could see. This verifies against a throwaway database that an admin can reach every
year rather than only the open ones, that reports, exports and audit rows carry the
year they came from, and that the integrity checks catch the mistakes that only
become possible once two years overlap.

Usage:
    python scripts/check_training_admin_years.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training_modules.unified_database import (  # noqa: E402
    UnifiedDatabase,
    YEAR_STATUS_ARCHIVED,
    YEAR_STATUS_DRAFT,
    YEAR_STATUS_OPEN,
    YEAR_STATUS_READONLY,
)
from training_modules.admin_excel_functions import year_filename_prefix  # noqa: E402

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


def seed(db_path):
    """The mid-cutover shape an admin actually faces.

    FY25 finished and archived, FY26 still being taught but read-only, FY27 active
    and open, FY28 a draft being built. Only FY26 and FY27 are visible to staff;
    an admin has business with all four.
    """
    db = UnifiedDatabase(db_path)
    db.initialize_training_tables()

    db.update_training_year('FY26', start_date='2025-10-01', end_date='2026-09-30')
    db.create_training_year('FY25', roster_filename='FY25 Roster.xlsx',
                            start_date='2024-10-01', end_date='2025-09-30',
                            status=YEAR_STATUS_ARCHIVED)
    db.create_training_year('FY27', roster_filename='FY27 Roster.xlsx',
                            linked_track_name='FY27', start_date='2026-10-01',
                            end_date='2027-09-30', status=YEAR_STATUS_OPEN)
    db.create_training_year('FY28', roster_filename='FY28 Roster.xlsx',
                            start_date='2027-10-01', end_date='2028-09-30',
                            status=YEAR_STATUS_DRAFT)
    # Promoting FY27 clears is_active on FY26; setting FY26 read-only is the second
    # half of a cutover - the outgoing year stays visible while its last classes are
    # taught, but stops taking signups.
    db.promote_training_year_to_active('FY27')
    db.set_training_year_status('FY26', YEAR_STATUS_READONLY)
    return db


def check_admin_year_list(db):
    print("\nWhich years an admin can work in")
    staff = [y['year_label'] for y in db.get_staff_visible_training_years()]
    admin = [y['year_label'] for y in db.get_admin_visible_training_years()]

    check("staff see only the years they can act in",
          set(staff) == {'FY26', 'FY27'}, str(staff))
    check("an admin sees every year, drafts and archives included",
          set(admin) == {'FY25', 'FY26', 'FY27', 'FY28'}, str(admin))
    check("the live year comes first", admin[0] == 'FY27', str(admin))

    rows = {y['year_label']: y for y in db.get_admin_visible_training_years()}
    check("each option is labelled with its own state",
          'draft' in rows['FY28']['label'] and 'archived' in rows['FY25']['label'],
          f"{rows['FY28']['label']} / {rows['FY25']['label']}")
    check("each option carries its enrollment count",
          'enrollment' in rows['FY27']['label'], rows['FY27']['label'])


def check_writes_stay_in_their_year(db):
    print("\nWrites, and the year they land in")
    # The active year takes signups; the year being viewed is what decides where a
    # row lands, which is the whole point during a cutover.
    check("an enrollment in the open year is accepted",
          db.add_enrollment('Casey Nurse', 'Airway Lab', '11/12/2026',
                            training_year='FY27') is True)
    check("a read-only year refuses new enrollments",
          db.add_enrollment('Casey Nurse', 'Airway Lab', '11/13/2025',
                            training_year='FY26') is False)
    check("a draft year refuses new enrollments",
          db.add_enrollment('Casey Nurse', 'Airway Lab', '11/12/2027',
                            training_year='FY28') is False)

    fy27 = db.get_staff_enrollments('Casey Nurse', training_year='FY27')
    fy26 = db.get_staff_enrollments('Casey Nurse', training_year='FY26')
    check("the row is filed under the year it was written for",
          len(fy27) == 1 and len(fy26) == 0, f"FY27={len(fy27)} FY26={len(fy26)}")


def check_audit_rows_name_their_year(db):
    print("\nThe audit trail")
    trail = db.get_year_audit_trail('FY27')
    check("an enrollment writes an audit row in its own year",
          any(e['staff_name'] == 'Casey Nurse' and e['action'] == 'enrolled'
              for e in trail), str(trail))
    check("another year's audit trail doesn't pick it up",
          not any(e['staff_name'] == 'Casey Nurse'
                  for e in db.get_year_audit_trail('FY26')))

    db.add_educator_signup('Dana Educator', 'Airway Lab', '11/12/2026',
                           training_year='FY27')
    trail = db.get_year_audit_trail('FY27')
    check("an educator signup is audited under its year too",
          any(e['staff_name'] == 'Dana Educator' for e in trail))


def check_cross_year_statistics(db):
    print("\nStatistics")
    one_year = db.get_enrollment_stats('FY27')
    check("a year's stats count only that year",
          one_year['total_enrollments'] == 1
          and one_year['training_year'] == 'FY27', str(one_year))

    db.add_enrollment('Jamie Medic', 'Trauma Day', '11/20/2026', training_year='FY27')
    per_year = {r['training_year']: r for r in db.get_enrollment_stats_by_year()}
    check("the breakdown separates the years",
          per_year['FY27']['enrollments'] == 2, str(per_year.get('FY27')))
    check("the breakdown marks which year is live",
          per_year['FY27']['is_active'] and per_year['FY27']['status'] == YEAR_STATUS_OPEN)
    check("every year at once is still available",
          db.get_enrollment_stats('')['total_enrollments'] == 2)


def check_data_health(db):
    print("\nData health checks")
    report = db.get_training_year_data_health('FY27')
    check("a clean year reports nothing to fix",
          report['unstamped_enrollments'] == 0
          and not report['orphaned_years']
          and not report['out_of_span'], str(report))

    # An enrollment stamped FY27 but taught during FY26 - the mistake a cutover
    # makes easy, because the year selected is not the year the class belongs to.
    db.connect()
    db.cursor.execute(
        "INSERT INTO training_enrollments (staff_name, class_name, class_date, "
        "status, training_year) VALUES ('Wrong Year Wanda', 'Airway Lab', "
        "'11/13/2025', 'active', 'FY27')")
    # A row belonging to a year nobody configured.
    db.cursor.execute(
        "INSERT INTO training_enrollments (staff_name, class_name, class_date, "
        "status, training_year) VALUES ('Orphan Olly', 'Airway Lab', "
        "'11/12/2026', 'active', 'FY99')")
    # A row nobody stamped at all.
    db.cursor.execute(
        "INSERT INTO training_enrollments (staff_name, class_name, class_date, "
        "status, training_year) VALUES ('Unstamped Uma', 'Airway Lab', "
        "'11/12/2026', 'active', NULL)")
    db.conn.commit()
    db.disconnect()

    report = db.get_training_year_data_health('FY27')
    check("a readable span is reported as such", report['span_readable'] is True)
    check("an enrollment outside the year's span is reported",
          [r['staff_name'] for r in report['out_of_span']] == ['Wrong Year Wanda'],
          str(report['out_of_span']))
    check("a year with no config row of its own is reported",
          report['orphaned_years'].get('FY99') == 1, str(report['orphaned_years']))
    check("an unstamped row is reported",
          report['unstamped_enrollments'] == 1, str(report['unstamped_enrollments']))


def check_unreadable_span(db):
    print("\nA span nobody can read")
    # An end date typed as free text used to make every enrollment in the year look
    # misfiled, because a comparison against an unparseable string answers no for
    # all of them. Reporting nothing is the better answer.
    db.update_training_year('FY27', end_date='end of September')
    report = db.get_training_year_data_health('FY27')
    check("an unreadable span turns the span check off rather than failing everything",
          report['span_readable'] is False and report['out_of_span'] == [],
          str(report['out_of_span']))

    # A span written the American way still reads, and still catches the misfiled row.
    db.update_training_year('FY27', end_date='09/30/2027')
    report = db.get_training_year_data_health('FY27')
    check("a span in MM/DD/YYYY is still compared rather than given up on",
          report['span_readable'] is True
          and [r['staff_name'] for r in report['out_of_span']] == ['Wrong Year Wanda'],
          str(report['out_of_span']))
    db.update_training_year('FY27', end_date='2027-09-30')


def check_export_rows(db):
    print("\nExports")
    enrollments, signups = db.get_year_export_rows('FY27')
    names = sorted(e['staff_name'] for e in enrollments)
    check("an export covers one year only",
          'Casey Nurse' in names and 'Wrong Year Wanda' in names,
          str(names))
    check("every exported row names its year",
          all(e['training_year'] == 'FY27' for e in enrollments), str(enrollments))
    check("educator signups export alongside", len(signups) == 1, str(signups))

    check("an export filename is prefixed with its year",
          year_filename_prefix('FY27') == 'FY27_')
    check("no year means no prefix rather than a broken name",
          year_filename_prefix(None) == '')
    check("a label that isn't filename-safe is sanitised",
          year_filename_prefix('FY 27/draft') == 'FY_27_draft_',
          year_filename_prefix('FY 27/draft'))


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, 'training_admin_years_check.db')
        print(f"Temporary database: {db_path}")
        db = seed(db_path)
        check_admin_year_list(db)
        check_writes_stay_in_their_year(db)
        check_audit_rows_name_their_year(db)
        check_cross_year_statistics(db)
        check_data_health(db)
        check_unreadable_span(db)
        check_export_rows(db)

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("Failed: " + ", ".join(_failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
