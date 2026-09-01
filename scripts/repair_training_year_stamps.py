#!/usr/bin/env python3
"""Re-stamp enrollments that were recorded under the wrong training year.

Between the introduction of per-year enrollments and the fix that made writes
follow the year being viewed, a signup was stamped with whichever year was
*active* rather than the year the staff member was looking at. During a cutover
those differ, so the row landed in the wrong year: invisible on the screen that
created it, and -- because the duplicate check ignored the year -- blocking any
attempt to sign up for that session again.

This finds those rows and moves them to the year whose roster actually contains
that class on that date. A row is only moved when the answer is unambiguous:

  * its class/date pair does NOT exist in the roster of the year it is stamped
    with, and
  * it DOES exist in exactly one other configured year's roster.

Anything else is reported and left alone.

Dry run by default:

    python scripts/repair_training_year_stamps.py
    python scripts/repair_training_year_stamps.py --apply
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

TABLES = {
    'training_enrollments': 'enrollment',
    'training_educator_signups': 'educator signup',
}


def load_year_catalog(conn):
    """Map each configured year to the {(class_name, class_date)} it holds.

    Read from the class catalog rather than the year's roster workbook, which the
    app no longer opens - a year whose spreadsheet has been moved or deleted still
    knows its own schedule, and used to be skipped here for want of the file.
    """
    catalog = {}
    rows = conn.execute(
        "SELECT year_label FROM training_years ORDER BY year_label"
    ).fetchall()
    for row in rows:
        label = row['year_label']
        handler = ClassCatalog(label)
        if handler.load_error:
            print(f"  {label}: catalog unavailable ({handler.load_error}) - skipping")
            continue
        pairs = set()
        for class_name in handler.get_all_classes():
            for class_date in handler.get_class_dates(class_name):
                pairs.add((class_name.strip().lower(), str(class_date).strip()))
        if not pairs:
            print(f"  {label}: no classes configured - skipping")
            continue
        catalog[label] = pairs
        print(f"  {label}: {len(pairs)} class/date pairs")
    return catalog


def find_misstamped(conn, catalog):
    """Rows whose class/date belongs to a different year than the one stamped."""
    moves, unclear = [], []
    for table, noun in TABLES.items():
        rows = conn.execute(
            f"SELECT id, staff_name, class_name, class_date, status, "
            f"COALESCE(training_year, '{LEGACY_TRAINING_YEAR}') AS year FROM {table}"
        ).fetchall()
        for row in rows:
            key = (row['class_name'].strip().lower(), str(row['class_date']).strip())
            stamped = row['year']
            if stamped in catalog and key in catalog[stamped]:
                continue  # stamped year genuinely holds this class on this date
            owners = [y for y, pairs in catalog.items() if key in pairs]
            record = (table, noun, row, stamped, owners)
            if len(owners) == 1 and owners[0] != stamped:
                moves.append(record)
            elif owners:
                unclear.append(record)
            # No owner at all: the class or date is gone from every roster. Leave it;
            # deleting someone's history is never this script's call.
    return moves, unclear


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

    print(f"Reading rosters for each configured training year:")
    catalog = load_year_catalog(conn)
    if not catalog:
        print("\nNo year rosters could be read - cannot tell which year a row belongs to.")
        return 1

    moves, unclear = find_misstamped(conn, catalog)

    if unclear:
        print(f"\n{len(unclear)} row(s) match more than one year's roster - left alone:")
        for table, noun, row, stamped, owners in unclear:
            print(f"  [{noun}] {row['staff_name']} / {row['class_name']} / "
                  f"{row['class_date']} stamped {stamped}, also in {', '.join(owners)}")

    if not moves:
        print("\nNothing to re-stamp: every row's class and date belong to the year "
              "it is filed under.")
        return 0

    print(f"\n{len(moves)} row(s) filed under the wrong year:")
    for table, noun, row, stamped, owners in moves:
        state = '' if row['status'] == 'active' else f" [{row['status']}]"
        print(f"  [{noun}] {row['staff_name']} / {row['class_name']} / "
              f"{row['class_date']}{state}: {stamped} -> {owners[0]}")

    if not args.apply:
        print("\nDry run - nothing written. Re-run with --apply to make these changes.")
        return 0

    if not args.no_backup:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = f"{args.db}.{stamp}.bak"
        shutil.copy2(args.db, backup)
        print(f"\nBackup written to {backup}")

    applied = skipped = 0
    for table, noun, row, stamped, owners in moves:
        try:
            conn.execute(f"UPDATE {table} SET training_year = ? WHERE id = ?",
                         (owners[0], row['id']))
            applied += 1
        except sqlite3.IntegrityError:
            # Moving it would collide with a row that already exists in the target
            # year - the staff member is already signed up there, so this one is a
            # leftover rather than the record of record.
            print(f"  skipped {noun} id {row['id']}: {owners[0]} already holds that signup")
            skipped += 1
    conn.commit()
    conn.close()
    print(f"\nRe-stamped {applied} row(s)" + (f", skipped {skipped}" if skipped else ""))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
