#!/usr/bin/env python3
"""
Self-check for bridging fiscal years in the Clinical Track Hub.

A fiscal-year cutover is an overlap, not a switch: FY27's tracks are promoted months
before FY26's last shift is worked, and promotion clears is_active on FY26's rows.
This verifies that the outgoing year stays visible and readable, that reading a year
by name gets that year's tracks rather than the live one's, that each year is
projected over its own calendar span, and that a year past its end date retires itself
from the picker.

Usage:
    python scripts/check_track_years.py
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


def seed():
    """FY26 active and being worked, FY27 out to bid with submitted bids."""
    from modules import db_utils
    db_utils.initialize_database()
    conn = db_utils.get_db_connection()
    cursor = conn.cursor()

    # FY26: the live cohort.
    for staff, code in (('Annie Nurse', 'D'), ('Andy Medic', 'N')):
        cursor.execute(
            """INSERT INTO tracks (staff_name, track_data, submission_date, version,
                                   is_active, track_name, effective_role)
               VALUES (?, ?, '', 1, 1, 'FY26', 'nurse')""",
            (staff, json.dumps({'Sun A 1': code})))

    # FY27: submitted bids, not yet promoted. Different shifts, so reading the wrong
    # cohort is visible rather than coincidental.
    db_utils.create_track_config('FY27', start_date='2026-09-27',
                                 end_date='2027-09-25',
                                 pattern_start_date='2026-09-27')
    for staff, code in (('Annie Nurse', 'N'), ('Andy Medic', 'D')):
        cursor.execute(
            """INSERT INTO tracks (staff_name, track_data, submission_date, version,
                                   is_active, track_name, effective_role)
               VALUES (?, ?, '', 1, 0, 'FY27', 'nurse')""",
            (staff, json.dumps({'Sun A 1': code})))
    conn.commit()


def check_before_promotion():
    print("\nBefore the cutover")
    from modules.db_utils import TRACK_YEAR_DRAFT, get_track_config_by_name
    from modules.track_year import get_hub_track_years

    years = get_hub_track_years()
    check("only the live cohort is offered while the next one is out to bid",
          [y['track_name'] for y in years] == ['FY26'],
          str([y['track_name'] for y in years]))
    check("a cohort out to bid is a draft, not something staff can pick",
          (get_track_config_by_name('FY27') or {}).get('status') == TRACK_YEAR_DRAFT,
          str((get_track_config_by_name('FY27') or {}).get('status')))
    check("the live cohort accepts track changes",
          years and years[0]['is_writable'])


def check_after_promotion():
    print("\nAfter the cutover")
    from modules.db_utils import (
        TRACK_YEAR_OPEN, TRACK_YEAR_READONLY, get_track_config_by_name,
        is_track_year_writable, promote_bid_to_active,
    )
    from modules.track_year import get_hub_track_years, resolve_selected_year

    ok, msg = promote_bid_to_active('FY27')
    check("promotion succeeds", ok, msg)

    fy26 = get_track_config_by_name('FY26') or {}
    fy27 = get_track_config_by_name('FY27') or {}
    check("the outgoing cohort goes read-only rather than out of sight",
          fy26.get('status') == TRACK_YEAR_READONLY and not fy26.get('is_active'),
          f"{fy26.get('status')} / is_active={fy26.get('is_active')}")
    check("the promoted cohort is open and active",
          fy27.get('status') == TRACK_YEAR_OPEN and fy27.get('is_active'),
          f"{fy27.get('status')} / is_active={fy27.get('is_active')}")

    names = [y['track_name'] for y in get_hub_track_years()]
    check("both fiscal years are offered in the hub, live year first",
          names == ['FY27', 'FY26'], str(names))

    labels = {y['track_name']: y['label'] for y in get_hub_track_years()}
    check("the picker names the active track and leaves the other year bare",
          labels == {'FY27': 'FY27 (active)', 'FY26': 'FY26'}, str(labels))

    writable = {y['track_name']: y['is_writable'] for y in get_hub_track_years()}
    check("only the live year accepts track changes",
          writable == {'FY27': True, 'FY26': False}, str(writable))
    check("is_track_year_writable agrees",
          is_track_year_writable('FY27') and not is_track_year_writable('FY26'))

    years = get_hub_track_years()
    check("with nothing picked, the hub opens on the live year",
          resolve_selected_year(years, 'FY27')[0] == 'FY27')
    check("an explicit pick of the outgoing year is honoured",
          resolve_selected_year(years, 'FY27', 'FY26')[0] == 'FY26')
    label, dropped = resolve_selected_year(years, 'FY27', 'FY25')
    check("a pick for a year that is no longer offered is dropped, not kept",
          label == 'FY27' and dropped, f"{label} / dropped={dropped}")


def check_reads_follow_the_year():
    print("\nReads follow the year being viewed")
    from modules.db_utils import get_all_active_tracks
    from modules.track_roster import build_current_tracks_df, get_active_track_rows

    fy26 = get_active_track_rows('FY26', include_retired=True)
    check("the outgoing year's tracks are still readable by name",
          fy26.get('Annie Nurse') == {'Sun A 1': 'D'}, str(fy26))
    check("without include_retired the outgoing year reads as empty, as it did before",
          get_active_track_rows('FY26') == {})
    check("the live year reads its own tracks",
          get_active_track_rows('FY27').get('Annie Nurse') == {'Sun A 1': 'N'})

    grid = build_current_tracks_df(track_name='FY26', include_retired=True,
                                   days=['Sun A 1'])
    row = grid[grid['STAFF NAME'] == 'Annie Nurse']
    check("the track grid can be built for the outgoing year",
          not row.empty and row.iloc[0]['Sun A 1'] == 'D',
          grid.to_dict('records').__str__())

    ok, tracks = get_all_active_tracks('FY26')
    by_staff = {t['staff_name']: t['track_data'] for t in tracks} if ok else {}
    check("the track viewer's reader can be pointed at the outgoing year",
          by_staff.get('Annie Nurse') == {'Sun A 1': 'D'}, str(by_staff))
    ok, live = get_all_active_tracks()
    live_by_staff = {t['staff_name']: t['track_data'] for t in live} if ok else {}
    check("naming no cohort still reads the live one",
          live_by_staff.get('Annie Nurse') == {'Sun A 1': 'N'}, str(live_by_staff))


def check_spans():
    print("\nEach year is projected over its own span")
    from modules.calendar_export import get_fiscal_year_info
    from modules.track_year import get_track_year_dates, us_holidays_between

    fy26 = get_track_year_dates('FY26')
    check("FY26 keeps the span the code used to carry hardcoded",
          fy26['start'] == datetime(2025, 9, 28)
          and fy26['end'] == datetime(2026, 9, 26)
          and fy26['pattern_start'] == datetime(2025, 9, 14),
          str(fy26))
    check("FY26's fiscal year still starts 14 days into the pattern (Sun B 3)",
          fy26['offset'] == 14, str(fy26['offset']))

    fy27 = get_track_year_dates('FY27')
    check("FY27 gets its own span",
          fy27['start'] == datetime(2026, 9, 27) and fy27['end'] == datetime(2027, 9, 25),
          str(fy27))
    check("a year anchored on its own first day starts at pattern day 0",
          fy27['offset'] == 0, str(fy27['offset']))

    check("an unknown cohort falls back to FY26's dates rather than failing",
          get_track_year_dates('FY99')['start'] == datetime(2025, 9, 28))

    info = get_fiscal_year_info('FY26')
    check("the calendar export reports FY26's start as Sun B 3",
          info['fiscal_year_start_name'] == 'Sun B 3', info['fiscal_year_start_name'])
    check("the calendar export reports FY27's start as Sun A 1",
          get_fiscal_year_info('FY27')['fiscal_year_start_name'] == 'Sun A 1')

    holidays = us_holidays_between(datetime(2025, 9, 28), datetime(2026, 9, 26))
    check("the generated holidays reproduce FY26's hardcoded list exactly",
          holidays == {
              datetime(2025, 11, 27): "Thanksgiving",
              datetime(2025, 12, 24): "Christmas Eve",
              datetime(2025, 12, 25): "Christmas",
              datetime(2026, 1, 1): "New Year's Day",
              datetime(2026, 1, 19): "MLK Jr. Day",
              datetime(2026, 2, 16): "Presidents' Day",
              datetime(2026, 5, 25): "Memorial Day",
              datetime(2026, 6, 19): "Juneteenth",
              datetime(2026, 7, 4): "Independence Day",
              datetime(2026, 9, 7): "Labor Day",
          }, str(sorted(holidays.items())))
    check("FY27's span gets its own holidays",
          us_holidays_between(datetime(2026, 9, 27), datetime(2027, 9, 25))
          .get(datetime(2026, 11, 26)) == "Thanksgiving")


def check_admin_export_years():
    print("\nWhat an admin can export")
    from modules.track_year import get_exportable_track_years

    years = get_exportable_track_years()
    names = [y['track_name'] for y in years]
    check("every cohort is exportable, live year first",
          names == ['FY27', 'FY26'], str(names))
    check("a closed year is offered even though staff can't write to it",
          'FY26' in names)
    counts = {y['track_name']: y['track_count'] for y in years}
    check("each year reports how many tracks it holds",
          counts == {'FY26': 2, 'FY27': 2}, str(counts))
    labels = {y['track_name']: y['label'] for y in years}
    check("the live year is labelled as the active one",
          labels.get('FY27') == 'FY27 (active) — 2 tracks', labels.get('FY27'))
    check("a retired year is labelled with its status, not left bare",
          labels.get('FY26') == 'FY26 (readonly) — 2 tracks', labels.get('FY26'))


def check_calendar_export():
    print("\nCalendar export")
    from modules.calendar_export import generate_google_calendar
    from modules.track_year import get_track_year_dates

    # 42-day pattern with a single day shift on Sun B 3, the day FY26 starts.
    schedule = [(datetime(2025, 9, 14), '')] * 42
    schedule[14] = (datetime(2025, 9, 28), 'D')

    fy26 = get_track_year_dates('FY26')
    csv_text, filename = generate_google_calendar(
        'Annie Nurse', schedule, fy26['start'], fy26['end'],
        fiscal_year_start=fy26['start'], pattern_start=fy26['pattern_start'])
    check("FY26's first day picks up the shift stored on Sun B 3",
          '09/28/2025' in csv_text, csv_text[:200])
    check("the export is named for the year it covers",
          filename == 'Annie Nurse_schedule_20250928.csv', filename)

    fy27 = get_track_year_dates('FY27')
    csv27, filename27 = generate_google_calendar(
        'Annie Nurse', schedule, fy27['start'], fy27['end'],
        fiscal_year_start=fy27['start'], pattern_start=fy27['pattern_start'])
    check("FY27 starts on Sun A 1, so the same pattern lands on a different date",
          '09/28/2025' not in csv27 and '10/11/2026' in csv27,
          csv27[:300])
    check("FY27's export is named for FY27",
          filename27 == 'Annie Nurse_schedule_20260927.csv', filename27)


def check_auto_retire():
    print("\nA year past its last day retires itself")
    from modules import db_utils
    from modules.db_utils import (
        TRACK_YEAR_ARCHIVED, get_db_connection, get_track_config_by_name,
    )
    from modules.track_year import get_hub_track_years

    cursor = get_db_connection().cursor()
    cursor.execute("UPDATE track_configs SET end_date = '2020-01-01' "
                   "WHERE track_name = 'FY26'")
    get_db_connection().commit()

    names = [y['track_name'] for y in get_hub_track_years()]
    check("an expired year drops out of the hub's fiscal-year picker",
          names == ['FY27'], str(names))
    check("it is archived rather than deleted",
          (get_track_config_by_name('FY26') or {}).get('status') == TRACK_YEAR_ARCHIVED,
          str((get_track_config_by_name('FY26') or {}).get('status')))

    # The live cohort is never retired out from under staff, even past its end date.
    cursor.execute("UPDATE track_configs SET end_date = '2020-01-01' "
                   "WHERE track_name = 'FY27'")
    get_db_connection().commit()
    names = [y['track_name'] for y in get_hub_track_years()]
    check("the live year stays offered even once its end date has passed",
          names == ['FY27'], str(names))

    ok, msg = db_utils.set_track_config_status('FY27', TRACK_YEAR_ARCHIVED)
    check("the live year cannot be hidden while it is still the live one",
          not ok, msg)


def check_upgrade_of_an_existing_install(db_path):
    """An install that has already been through a cutover keeps its outgoing year.

    Migrating a pre-feature database is the one chance to get this right: the outgoing
    cohort is exactly the year the hub is meant to keep showing, so it has to come out
    of the migration visible, not archived.
    """
    print("\nUpgrading a database that predates the feature")
    import sqlite3

    from modules import db_utils

    # A track_configs table as it looked before cohorts carried a status or dates:
    # FY27 already promoted, FY26 retired behind it, FY25 finished long ago.
    raw = sqlite3.connect(db_path)
    raw.execute("""
        CREATE TABLE track_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL UNIQUE,
            is_active INTEGER DEFAULT 0,
            is_bidding_open INTEGER DEFAULT 0,
            max_day_nurses INTEGER DEFAULT 11,
            max_day_medics INTEGER DEFAULT 11,
            max_night_nurses INTEGER DEFAULT 5,
            max_night_medics INTEGER DEFAULT 5,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL
        )""")
    for name, active in (('FY25', 0), ('FY26', 0), ('FY27', 1)):
        raw.execute("INSERT INTO track_configs (track_name, is_active, created_date, "
                    "modified_date) VALUES (?, ?, '', '')", (name, active))
    raw.commit()
    raw.close()

    db_utils.close_all_connections()
    db_utils.initialize_database()

    from modules.db_utils import (
        TRACK_YEAR_ARCHIVED, TRACK_YEAR_OPEN, TRACK_YEAR_READONLY,
        get_track_config_by_name,
    )
    from modules.track_year import get_hub_track_years

    check("the promoted year comes out of the migration as the live one",
          (get_track_config_by_name('FY27') or {}).get('status') == TRACK_YEAR_OPEN,
          str((get_track_config_by_name('FY27') or {}).get('status')))
    check("the outgoing year survives the upgrade visible, not archived",
          (get_track_config_by_name('FY26') or {}).get('status') == TRACK_YEAR_READONLY,
          str((get_track_config_by_name('FY26') or {}).get('status')))
    check("FY26's backfilled dates are the ones the code used to hardcode",
          (get_track_config_by_name('FY26') or {}).get('end_date') == '2026-09-26',
          str((get_track_config_by_name('FY26') or {}).get('end_date')))

    names = [y['track_name'] for y in get_hub_track_years()]
    check("the hub offers the live year and the year still being worked",
          names == ['FY27', 'FY26'], str(names))
    check("an older finished year is archived rather than filling up the picker",
          (get_track_config_by_name('FY25') or {}).get('status') == TRACK_YEAR_ARCHIVED,
          str((get_track_config_by_name('FY25') or {}).get('status')))

    ok, msg = db_utils.set_track_config_status('FY26', TRACK_YEAR_ARCHIVED)
    check("an admin can archive the outgoing year in one step", ok, msg)
    check("archiving takes it out of the picker",
          'FY26' not in [y['track_name'] for y in get_hub_track_years()])


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, 'track_years_check.db')
        upgrade_db_path = os.path.join(tmpdir, 'track_years_upgrade.db')

        # db_utils reaches the database by a fixed path, so point it at the throwaway
        # file for the duration of the check.
        from modules import db_utils
        db_utils.close_all_connections()
        original_connect = db_utils.sqlite3.connect
        current_db = {'path': db_path}
        db_utils.sqlite3.connect = lambda *args, **kwargs: original_connect(
            current_db['path'], *args[1:], **kwargs)

        # calendar_export and fiscal_year open the database by path of their own.
        import modules.calendar_export as calendar_export
        original_get_path = calendar_export.get_database_path
        calendar_export.get_database_path = lambda: current_db['path']

        print(f"Temporary database: {db_path}")
        try:
            seed()
            check_before_promotion()
            check_after_promotion()
            check_reads_follow_the_year()
            check_spans()
            check_calendar_export()
            check_admin_export_years()
            check_auto_retire()

            # A second throwaway database, shaped the way an install looked before
            # cohorts carried a status at all.
            db_utils.close_all_connections()
            current_db['path'] = upgrade_db_path
            check_upgrade_of_an_existing_install(upgrade_db_path)
        finally:
            db_utils.close_all_connections()
            db_utils.sqlite3.connect = original_connect
            calendar_export.get_database_path = original_get_path

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("Failed: " + ", ".join(_failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
