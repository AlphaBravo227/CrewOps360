#!/usr/bin/env python3
"""
Self-check for the database-backed track data: the 42-day pattern, the active track grid,
per-cycle preassignments and CCEMT schedules.

Runs against a throwaway database and verifies that what the app now reads from the
database matches what it used to read from Tracks.xlsx and Preassignments.xlsx, and that
the editors behave.

Usage:
    python scripts/check_track_data.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from modules import ccemt_schedule as ccemt  # noqa: E402
from modules import preassignment_db as preassign  # noqa: E402
from modules import staff_database as staffdb  # noqa: E402
from modules import track_roster  # noqa: E402
from modules.day_pattern import (  # noqa: E402
    PATTERN_DAYS,
    PATTERN_LENGTH,
    days_by_week,
    is_weekend_day,
    pattern_day_sort_key,
    sort_pattern_days,
)

TRACKS_PATH = 'upload files/Tracks.xlsx'
PREASSIGNMENTS_PATH = 'upload files/Preassignments.xlsx'
TRACK = 'FY26'

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


def check_day_pattern():
    print("\nDay pattern")
    check("42 days are generated", len(PATTERN_DAYS) == PATTERN_LENGTH == 42)
    check("labels match the Tracks.xlsx header exactly",
          PATTERN_DAYS == list(pd.read_excel(TRACKS_PATH, nrows=0).columns)[1:43])
    check("days are unique", len(set(PATTERN_DAYS)) == len(PATTERN_DAYS))
    check("weeks are seven days each",
          all(len(week) == 7 for week in days_by_week()) and len(days_by_week()) == 6)
    check("chronological sort puts week 2 before week 3",
          sort_pattern_days(['Mon B 3', 'Tue A 2'])[0] == 'Tue A 2')
    check("already-ordered pattern is stable under sorting",
          sort_pattern_days(PATTERN_DAYS) == PATTERN_DAYS)
    check("weekend days are Saturdays and Sundays",
          [day for day in PATTERN_DAYS if is_weekend_day(day)][:3]
          == ['Sun A 1', 'Sat A 1', 'Sun A 2'])
    check("an unparseable label sorts last", pattern_day_sort_key('nonsense')[0] == 999)


def seed_tracks_from_spreadsheet(conn):
    """Load the legacy grid into the tracks table so the builder has data to shape."""
    df = pd.read_excel(TRACKS_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, staff_name TEXT NOT NULL,
        track_data TEXT NOT NULL, submission_date TEXT NOT NULL,
        is_approved INTEGER DEFAULT 0, version INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1, track_name TEXT DEFAULT 'FY26')''')
    for _, row in df.iterrows():
        name = row[df.columns[0]]
        if pd.isna(name):
            continue
        track_data = {}
        for day in PATTERN_DAYS:
            value = row[day]
            track_data[day] = '' if pd.isna(value) else str(value).strip()
        cursor.execute("""INSERT INTO tracks (staff_name, track_data, submission_date,
                          is_approved, version, is_active, track_name)
                          VALUES (?, ?, '', 1, 1, 1, ?)""",
                       (str(name).strip(), json.dumps(track_data), TRACK))
    conn.commit()
    return df


def check_track_roster(spreadsheet):
    print("\nActive track grid")
    built = track_roster.build_current_tracks_df()
    check("column layout matches Tracks.xlsx",
          list(built.columns) == list(spreadsheet.columns),
          f"got {list(built.columns)[:3]}…")

    original = spreadsheet.set_index(spreadsheet[spreadsheet.columns[0]]
                                    .astype(str).str.strip())
    rebuilt = built.set_index(track_roster.STAFF_NAME_COLUMN)

    missing = sorted(set(original.index) - set(rebuilt.index))
    check("every staff member in the spreadsheet is in the grid", not missing,
          f"missing: {missing[:5]}")

    differences = []
    for name in original.index:
        for day in PATTERN_DAYS:
            expected = original.loc[name, day]
            expected = '' if pd.isna(expected) else str(expected).strip()
            actual = str(rebuilt.loc[name, day]).strip()
            if expected != actual:
                differences.append((name, day, expected, actual))
    check("every assignment matches the spreadsheet", not differences,
          f"{differences[:3]}")

    roster_only = sorted(set(rebuilt.index) - set(original.index))
    check("clinical staff with no track still get a row",
          all(all(str(rebuilt.loc[name, day]).strip() == '' for day in PATTERN_DAYS)
              for name in roster_only),
          f"{roster_only[:5]}")

    day_staff = track_roster.get_staff_on_shift('Sun A 1', 'D')
    expected_day_staff = sorted(
        name for name in original.index
        if str(original.loc[name, 'Sun A 1']).strip().upper() == 'D')
    check("get_staff_on_shift matches the spreadsheet for one day",
          day_staff == expected_day_staff,
          f"{len(day_staff)} vs {len(expected_day_staff)}")

    check("active_track_count counts the imported tracks",
          track_roster.active_track_count() == len(original))


def check_preassignments():
    print("\nPreassignments")
    from modules.track_management.preassignment import (
        get_staff_preassignments,
        has_preassignment,
    )

    report = preassign.import_preassignments_from_excel(PREASSIGNMENTS_PATH, TRACK,
                                                        dry_run=True)
    check("a dry-run import writes nothing",
          report['staff_imported'] > 0 and not preassign.get_preassignments(TRACK),
          str(report['errors']))

    report = preassign.import_preassignments_from_excel(PREASSIGNMENTS_PATH, TRACK)
    check("import reports no errors", not report['errors'], str(report['errors']))
    check("every column was a recognized pattern day", not report['unknown_days'],
          str(report['unknown_days']))

    original = pd.read_excel(PREASSIGNMENTS_PATH)
    original = original.set_index(original[original.columns[0]].astype(str).str.strip())
    built = preassign.build_preassignment_df(TRACK)
    check("the built frame is indexed by staff name",
          built is not None and built.index.name == preassign.STAFF_NAME_COLUMN)

    differences = []
    for name in original.index:
        expected = {day: str(original.loc[name, day]).strip() for day in PATTERN_DAYS
                    if pd.notna(original.loc[name, day])
                    and str(original.loc[name, day]).strip()}
        actual = get_staff_preassignments(name, built, PATTERN_DAYS)
        if expected != actual:
            differences.append((name, expected, actual))
    check("every staff member's preassignments match the spreadsheet", not differences,
          f"{differences[:2]}")

    sample_name = built.index[0]
    sample_day = next(day for day in PATTERN_DAYS
                      if str(built.loc[sample_name, day]).strip())
    check("has_preassignment finds a preassigned day",
          has_preassignment(sample_name, sample_day, built))
    check("has_preassignment is false for an unassigned name",
          not has_preassignment('Nobody At All', sample_day, built))

    check("a re-import without overwrite is refused",
          bool(preassign.import_preassignments_from_excel(
              PREASSIGNMENTS_PATH, TRACK)['errors']))

    # Editing one staff member.
    ok, message = preassign.set_staff_preassignments(TRACK, sample_name,
                                                     {'Sun A 1': 'CLASS'})
    check("editing replaces that staff member's days",
          ok and preassign.get_staff_preassignments(sample_name, TRACK) == {'Sun A 1': 'CLASS'},
          message)

    ok, message = preassign.set_preassignment(TRACK, sample_name, 'Mon A 1', 'AT')
    check("setting one day adds it",
          ok and preassign.get_staff_preassignments(sample_name, TRACK).get('Mon A 1') == 'AT',
          message)

    ok, _ = preassign.set_preassignment(TRACK, sample_name, 'Mon A 1', '')
    check("clearing one day removes it",
          ok and 'Mon A 1' not in preassign.get_staff_preassignments(sample_name, TRACK))

    # Per-cycle isolation and copying.
    check("another cycle starts empty", not preassign.get_preassignments('FY27'))
    ok, message = preassign.copy_preassignments(TRACK, 'FY27')
    check("copying to a new cycle brings everything over",
          ok and preassign.get_preassignments('FY27') == preassign.get_preassignments(TRACK),
          message)
    ok, message = preassign.copy_preassignments(TRACK, 'FY27')
    check("copying onto a populated cycle is refused without overwrite", not ok, message)
    ok, message = preassign.copy_preassignments(TRACK, 'FY27', overwrite=True)
    check("copying with overwrite succeeds", ok, message)

    ok, deleted = preassign.delete_preassignments('FY27')
    check("clearing a cycle leaves the other alone",
          ok and deleted > 0 and not preassign.get_preassignments('FY27')
          and preassign.get_preassignments(TRACK))

    summary = {row['track_name']: row['staff_count']
               for row in preassign.get_preassignment_summary()}
    check("the summary reports the remaining cycle", TRACK in summary, str(summary))


def check_ccemt():
    print("\nCCEMT schedules")
    report = ccemt.import_from_excel(TRACKS_PATH, dry_run=True)
    check("a dry-run import writes nothing",
          report['staff_imported'] > 0 and not ccemt.get_schedules(),
          str(report['errors']))

    report = ccemt.import_from_excel(TRACKS_PATH)
    check("import reports no errors", not report['errors'], str(report['errors']))

    workbook_rows = pd.read_excel(TRACKS_PATH, sheet_name='CCEMT', header=None)
    schedules = ccemt.get_schedules()

    differences = []
    for _, row in workbook_rows.iloc[1:].iterrows():
        name = row.iloc[0]
        if pd.isna(name):
            continue
        name = str(name).strip()
        expected = {}
        for day_index in range(ccemt.PATTERN_LENGTH):
            value = row.iloc[day_index + 1]
            if pd.isna(value):
                continue
            code = str(value).strip().upper()
            if code:
                expected[day_index] = code
        actual = schedules.get(name, {})
        if expected != actual:
            differences.append((name, len(expected), len(actual)))
    check("every CCEMT pattern matches the workbook", not differences,
          f"{differences[:3]}")

    check("night codes classify as N", ccemt.classify_shift_code('NG') == 'N')
    check("day codes classify as D", ccemt.classify_shift_code('GR') == 'D')
    check("blank codes classify as blank", ccemt.classify_shift_code('') == '')

    classified = ccemt.get_classified_schedules()
    check("classified patterns cover the same staff",
          set(classified) == set(schedules))

    check("28 day labels are produced, week-qualified",
          len(ccemt.day_labels()) == 28 and ccemt.day_labels()[0] == 'Wk1 Sun')

    check("a re-import without overwrite is refused",
          bool(ccemt.import_from_excel(TRACKS_PATH)['errors']))

    name = sorted(schedules)[0]
    ok, message = ccemt.set_staff_schedule(name, {0: 'gr', 1: 'NG'})
    check("editing a pattern replaces it and upper-cases codes",
          ok and ccemt.get_staff_schedule(name) == {0: 'GR', 1: 'NG'}, message)

    ok, message = ccemt.set_staff_schedule(name, {99: 'GR'})
    check("a day outside the pattern is rejected", not ok, message)

    ok, message = ccemt.delete_staff_schedule(name)
    check("removing a staff member clears their pattern",
          ok and not ccemt.get_staff_schedule(name), message)

    check("the default start date is the pattern's first Sunday",
          ccemt.get_pattern_start_date().strftime('%Y-%m-%d') == ccemt.DEFAULT_START_DATE)
    ok, message = ccemt.set_pattern_start_date('2026-03-02')
    check("a start date that isn't a Sunday is rejected", not ok, message)
    ok, message = ccemt.set_pattern_start_date('2026-03-01')
    check("a Sunday start date is accepted and read back",
          ok and ccemt.get_pattern_start_date().strftime('%Y-%m-%d') == '2026-03-01',
          message)


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, 'track_data_check.db')

        # Both modules reach the database through db_utils, so point that at the
        # throwaway file for the duration of the check.
        from modules import db_utils
        db_utils.close_all_connections()
        original_connect = db_utils.sqlite3.connect
        db_utils.sqlite3.connect = lambda *args, **kwargs: original_connect(
            db_path, *args[1:], **kwargs)
        staffdb.set_db_path(db_path)
        print(f"Temporary database: {db_path}")

        try:
            staffdb.initialize_staff_tables()
            preassign.initialize_preassignment_tables()
            ccemt.initialize_ccemt_tables()

            from modules.staff_import import import_staff_roster
            import_staff_roster(changed_by='self-check')

            check_day_pattern()
            spreadsheet = seed_tracks_from_spreadsheet(db_utils.get_db_connection())
            check_track_roster(spreadsheet)
            check_preassignments()
            check_ccemt()
        finally:
            db_utils.close_all_connections()
            db_utils.sqlite3.connect = original_connect
            staffdb.set_db_path(None)

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("Failed: " + ", ".join(_failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
