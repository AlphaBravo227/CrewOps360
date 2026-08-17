#!/usr/bin/env python3
"""
Seed the track data that used to live in Excel: preassignments, CCEMT schedules and —
if the tracks table is empty — the 42-day track grid.

The same imports the Track Data admin page offers, available from the command line for a
one-time migration.

Examples:
    # See what would be imported, without writing
    python scripts/seed_track_data.py --dry-run

    # Import preassignments into the FY26 cycle plus the CCEMT pattern
    python scripts/seed_track_data.py --track FY26

    # Also load the legacy 42-day grid into the tracks table (only if it is empty)
    python scripts/seed_track_data.py --track FY26 --import-tracks
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import pytz  # noqa: E402

from modules import ccemt_schedule as ccemt  # noqa: E402
from modules import preassignment_db as preassign  # noqa: E402
from modules.day_pattern import PATTERN_DAYS  # noqa: E402
from modules.db_utils import get_active_track_config, get_db_connection, initialize_database  # noqa: E402
from modules.track_roster import active_track_count  # noqa: E402

_eastern_tz = pytz.timezone('America/New_York')

DEFAULT_TRACKS_PATH = 'upload files/Tracks.xlsx'
DEFAULT_PREASSIGNMENTS_PATH = 'upload files/Preassignments.xlsx'


def import_tracks_from_excel(path, track_name, dry_run=False, force=False):
    """
    Load the legacy 42-day grid into the tracks table.

    Only for an install whose tracks table is empty — tracks are submitted through the app
    now, and overwriting live tracks with a spreadsheet copy would lose approvals and
    history. Pass force to import anyway.

    Returns:
        tuple: (imported_count, message)
    """
    if not os.path.exists(path):
        return 0, f"Tracks workbook not found: {path}"

    existing = active_track_count()
    if existing and not force:
        return 0, (f"The tracks table already holds {existing} active track(s) — "
                   "skipping. Use --force-tracks only if you mean to replace them.")

    try:
        df = pd.read_excel(path)
    except Exception as e:
        return 0, f"Could not read {path}: {e}"

    if df.empty:
        return 0, f"{path} has no rows."

    staff_col = df.columns[0]
    day_columns = [col for col in df.columns[1:] if str(col) in set(PATTERN_DAYS)]
    if len(day_columns) < len(PATTERN_DAYS):
        return 0, (f"{path} has {len(day_columns)} of the {len(PATTERN_DAYS)} expected "
                   "day columns — not importing a partial grid.")

    rows = []
    for _, row in df.iterrows():
        name = row[staff_col]
        if pd.isna(name):
            continue
        name = str(name).strip()
        if not name or name.lower() in ('nan', 'none', 'staff name'):
            continue
        track_data = {}
        for day in day_columns:
            value = row[day]
            track_data[str(day)] = '' if pd.isna(value) else str(value).strip()
        rows.append((name, track_data))

    if dry_run:
        return len(rows), f"Would import {len(rows)} track(s) from {path}."

    initialize_database()
    conn = get_db_connection()
    cursor = conn.cursor()
    submission_date = datetime.now(_eastern_tz).strftime('%Y-%m-%d %H:%M:%S')

    if existing and force:
        cursor.execute("UPDATE tracks SET is_active = 0 WHERE is_active = 1")

    from modules.staff_database import get_clinical_role, get_effective_role

    for name, track_data in rows:
        # Store the role metadata the app's own submissions record, so the track
        # displays and staffing analytics don't have to resolve it per read.
        cursor.execute('''
            INSERT INTO tracks (staff_name, track_data, submission_date, is_approved,
                                version, is_active, original_role, effective_role,
                                track_source, has_preassignments,
                                preassignment_count, track_name)
            VALUES (?, ?, ?, 1, 1, 1, ?, ?, 'Preferred Track', 0, 0, ?)
        ''', (name, json.dumps(track_data), submission_date,
              get_clinical_role(name, 'nurse'), get_effective_role(name, 'nurse'),
              track_name))
        track_id = cursor.lastrowid
        cursor.execute('''
            INSERT INTO track_history (track_id, staff_name, track_data, submission_date,
                                       status)
            VALUES (?, ?, ?, ?, 'Imported from spreadsheet')
        ''', (track_id, name, json.dumps(track_data), submission_date))

    conn.commit()
    return len(rows), f"Imported {len(rows)} track(s) from {path} into {track_name}."


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--track', default=None,
                        help='Track cycle to import preassignments (and tracks) into. '
                             'Defaults to the active cycle.')
    parser.add_argument('--preassignments', default=DEFAULT_PREASSIGNMENTS_PATH,
                        help='Path to the Preassignments workbook.')
    parser.add_argument('--tracks', default=DEFAULT_TRACKS_PATH,
                        help='Path to the Tracks workbook (holds the CCEMT tab).')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would be imported without writing anything.')
    parser.add_argument('--overwrite', action='store_true',
                        help='Replace preassignments and CCEMT schemas already on file.')
    parser.add_argument('--skip-preassignments', action='store_true')
    parser.add_argument('--skip-ccemt', action='store_true')
    parser.add_argument('--import-tracks', action='store_true',
                        help='Also load the legacy 42-day grid into the tracks table '
                             '(only when it is empty).')
    parser.add_argument('--force-tracks', action='store_true',
                        help='Import the 42-day grid even if active tracks already exist, '
                             'retiring the current ones. Destructive.')
    args = parser.parse_args()

    initialize_database()
    preassign.initialize_preassignment_tables()
    ccemt.initialize_ccemt_tables()

    active = get_active_track_config()
    track_name = args.track or (active['track_name'] if active else None)
    if not track_name:
        print("No track cycle given and no active cycle configured — pass --track.")
        return 1

    print(f"Track cycle: {track_name}")
    if args.dry_run:
        print("DRY RUN — nothing will be written.\n")

    failures = 0

    if not args.skip_preassignments:
        print("Preassignments")
        report = preassign.import_preassignments_from_excel(
            args.preassignments, track_name, overwrite=args.overwrite,
            dry_run=args.dry_run)
        print(f"  staff: {report['staff_imported']}  days: {report['days_imported']}")
        if report['unknown_days']:
            print(f"  columns outside the 42-day pattern: {', '.join(report['unknown_days'])}")
        if report['unknown_staff']:
            print("  names not on the staff roster: "
                  f"{', '.join(sorted(set(report['unknown_staff'])))}")
        for error in report['errors']:
            print(f"  ERROR: {error}")
            failures += 1
        print()

    if not args.skip_ccemt:
        print("CCEMT schedules")
        report = ccemt.import_from_excel(args.tracks, overwrite=args.overwrite,
                                         dry_run=args.dry_run)
        print(f"  staff: {report['staff_imported']}  days: {report['days_imported']}")
        if report['skipped']:
            print(f"  rows with no shift codes, skipped: {', '.join(report['skipped'])}")
        for error in report['errors']:
            print(f"  ERROR: {error}")
            failures += 1
        print()

    if args.import_tracks:
        print("Track grid")
        count, message = import_tracks_from_excel(args.tracks, track_name,
                                                  dry_run=args.dry_run,
                                                  force=args.force_tracks)
        print(f"  {message}")
        print()

    print(f"Active tracks in the database: {active_track_count()}")
    print(f"Preassignment cycles on file: {preassign.get_preassignment_summary()}")
    print(f"CCEMT staff scheduled: {len(ccemt.get_schedules())}")

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
