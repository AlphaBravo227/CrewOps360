#!/usr/bin/env python3
"""Clean up enrollments whose meeting type is not a meeting type.

Two ways a row ended up with the wrong value in that column:

  * The public enrollment screen passed the location where the meeting type goes,
    on the multi-session classes (the SIMs, the labs). The seat counting - which
    ignores the meeting type when it is not asked for one - counted the booking,
    while the session roster - which lists only rows carrying no meeting type -
    did not. The session read "No one enrolled yet" and then refused the next
    person for want of a slot.

  * The admin "Add Student" form decided a class was a staff meeting by looking
    for "Staff Meeting" in its name, which none of them are called, so it never
    asked for the meeting type. The row was written with none, and the public
    view - which lists the LIVE and Virtual sessions separately - had nowhere to
    put it.

For a class that is not a staff meeting, a meeting type is stray: it is cleared,
and where it names one of that date's locations and the row has no location
recorded, it is moved into the location column where it belonged.

For a staff meeting, a row with no meeting type is only filled in when the date
offers a single one (Virtual, on a date with no LIVE option). Where the date
offers both, the answer is not in the data - those rows are reported for an
administrator to set from the class admin screen.

Dry run by default:

    python scripts/repair_enrollment_meeting_types.py
    python scripts/repair_enrollment_meeting_types.py --apply
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training_modules.class_catalog import ClassCatalog  # noqa: E402
from training_modules.unified_database import LEGACY_TRAINING_YEAR  # noqa: E402

DEFAULT_DB = 'data/medflight_tracks.db'

MEETING_TYPES = ('LIVE', 'Virtual')


def catalog_for(year, cache, db_path):
    """The class catalog for one training year, read once per year.

    Out of the same database the enrollments came from: the catalog otherwise
    reads its own default path, and a run against a copy or a backup would have
    judged those rows against whatever schedule happened to be live.
    """
    if year not in cache:
        catalog = ClassCatalog(year, db_path=db_path)
        cache[year] = None if catalog.load_error else catalog
        if catalog.load_error:
            print(f"  {year}: catalog unavailable ({catalog.load_error}) - skipping")
    return cache[year]


def plan_repairs(conn, db_path):
    """What to change, and what needs a human.

    Returns (repairs, unclear). A repair is (row, new_meeting_type, new_location,
    reason); new_location is None when the location column is left as it is.
    """
    repairs, unclear = [], []
    cache = {}

    # A database the app has not opened since locations became bookable has no
    # location column yet - the app adds it on startup. The meeting type half of
    # this repair is what matters there and works the same, so read what the table
    # actually has rather than refusing the run.
    columns = [column[1] for column in
               conn.execute("PRAGMA table_info(training_enrollments)").fetchall()]
    if not columns:
        print("  no training_enrollments table in this database")
        return repairs, unclear
    has_location = 'location' in columns
    if not has_location:
        print("  no location column yet (the app adds it on startup) - meeting types "
              "will be cleared, but a location cannot be restored from one")

    location_select = 'location' if has_location else "NULL AS location"
    rows = conn.execute(
        f"SELECT id, staff_name, class_name, class_date, meeting_type, "
        f"{location_select}, session_time, status, "
        f"COALESCE(training_year, '{LEGACY_TRAINING_YEAR}') AS year "
        f"FROM training_enrollments"
    ).fetchall()

    for row in rows:
        catalog = catalog_for(row['year'], cache, db_path)
        if catalog is None:
            continue

        meeting_type = (row['meeting_type'] or '').strip()
        is_meeting = catalog.is_staff_meeting(row['class_name'])

        if not is_meeting:
            if not meeting_type:
                continue
            # A class with no meeting types at all should carry none. If the value
            # names one of that date's locations, that is where it was headed.
            locations = [option.get('location') for option
                         in catalog.get_date_options(row['class_name'], row['class_date'])
                         if option.get('location')]
            new_location = None
            reason = "not a staff meeting"
            if has_location and meeting_type in locations and not (row['location'] or '').strip():
                new_location = meeting_type
                reason = "location recorded as a meeting type"
            repairs.append((row, None, new_location, reason))
            continue

        # A staff meeting with a meeting type already set is correct as it stands.
        if meeting_type in MEETING_TYPES:
            continue

        attributes = catalog.get_date_attributes(row['class_name'], row['class_date'])
        if meeting_type:
            # Something else entirely in the column of a meeting - a location, most
            # likely, from the same slid argument. Nothing here can say which
            # session the person is in.
            unclear.append((row, f"meeting type reads '{meeting_type}'"))
        elif attributes.get('has_live'):
            unclear.append((row, "date offers both LIVE and Virtual"))
        else:
            repairs.append((row, 'Virtual', None,
                            "staff meeting with no meeting type; date is Virtual only"))

    return repairs, unclear


def describe(row):
    state = '' if row['status'] == 'active' else f" [{row['status']}]"
    session = f" {row['session_time']}" if row['session_time'] else ''
    return f"{row['staff_name']} / {row['class_name']} / {row['class_date']}{session}{state}"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', default=DEFAULT_DB, help=f'Database file (default: {DEFAULT_DB})')
    parser.add_argument('--apply', action='store_true',
                        help='Write the changes. Without this nothing is modified.')
    parser.add_argument('--no-backup', action='store_true',
                        help='Skip the backup copy taken before writing.')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    print("Reading the class catalog for each training year:")
    repairs, unclear = plan_repairs(conn, args.db)

    if unclear:
        print(f"\n{len(unclear)} staff meeting enrollment(s) need a meeting type set by "
              f"hand - which session they attended is not recorded anywhere:")
        for row, reason in unclear:
            print(f"  {describe(row)}: {reason}")

    if not repairs:
        print("\nNothing to repair: every enrollment's meeting type belongs to it.")
        return 0

    print(f"\n{len(repairs)} enrollment(s) to repair:")
    for row, new_meeting_type, new_location, reason in repairs:
        change = f"meeting_type {row['meeting_type']!r} -> {new_meeting_type!r}"
        if new_location:
            change += f", location {row['location']!r} -> {new_location!r}"
        print(f"  {describe(row)}: {change} ({reason})")

    if not args.apply:
        print("\nDry run - nothing written. Re-run with --apply to make these changes.")
        return 0

    if not args.no_backup:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = f"{args.db}.{stamp}.bak"
        shutil.copy2(args.db, backup)
        print(f"\nBackup written to {backup}")

    applied = skipped = 0
    for row, new_meeting_type, new_location, reason in repairs:
        try:
            if new_location:
                conn.execute(
                    "UPDATE training_enrollments SET meeting_type = ?, location = ? "
                    "WHERE id = ?", (new_meeting_type, new_location, row['id']))
            else:
                conn.execute(
                    "UPDATE training_enrollments SET meeting_type = ? WHERE id = ?",
                    (new_meeting_type, row['id']))
            applied += 1
        except sqlite3.IntegrityError:
            # The repaired row would duplicate one that already exists: the person is
            # already recorded in that session, so this one is the leftover.
            print(f"  skipped id {row['id']}: that signup already exists")
            skipped += 1
    conn.commit()
    conn.close()
    print(f"\nRepaired {applied} enrollment(s)" + (f", skipped {skipped}" if skipped else ""))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
