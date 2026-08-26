#!/usr/bin/env python3
"""
Seed (or refresh) the staff database from the Excel sources.

The same import the Staff Database admin page runs, available from the command line so
the roster can be built before the app is started for the first time.

Examples:
    # See what would happen, without writing
    python scripts/seed_staff_database.py --dry-run

    # First-time seed
    python scripts/seed_staff_database.py

    # Re-import and let the spreadsheets win over existing roster attributes
    python scripts/seed_staff_database.py --update-existing
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import staff_database as staffdb  # noqa: E402
from modules.staff_import import (  # noqa: E402
    DEFAULT_PREFERENCES_PATH,
    DEFAULT_ROSTER_PATH,
    format_import_report,
    import_staff_roster,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--roster', default=DEFAULT_ROSTER_PATH,
                        help='Path to the Education Classes Roster workbook.')
    parser.add_argument('--preferences', default=DEFAULT_PREFERENCES_PATH,
                        help='Path to the Preferences v6 workbook.')
    parser.add_argument('--db', default=None,
                        help='Database file to write (default: data/medflight_tracks.db).')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would change without writing anything.')
    parser.add_argument('--update-existing', action='store_true',
                        help='Overwrite attributes of staff already on the roster.')
    parser.add_argument('--roster-only', action='store_true',
                        help='Do not add names found only in Tracks/Requirements/'
                             'Preassignments.')
    parser.add_argument('--no-preference-seed', action='store_true',
                        help='Skip copying Preferences v6 shift scores into the '
                             'in-app preference tables.')
    parser.add_argument('--overwrite-preferences', action='store_true',
                        help='Replace shift preferences staff have already saved in '
                             'the app with the spreadsheet values.')
    args = parser.parse_args()

    if args.db:
        staffdb.set_db_path(args.db)
    print(f"Database: {staffdb.get_db_path()}")

    report = import_staff_roster(
        roster_path=args.roster,
        preferences_path=args.preferences,
        include_secondary_names=not args.roster_only,
        update_existing=args.update_existing,
        seed_shift_preferences=not args.no_preference_seed,
        overwrite_shift_preferences=args.overwrite_preferences,
        dry_run=args.dry_run,
        changed_by='seed_staff_database.py',
    )

    print()
    for line in format_import_report(report):
        print(line)
    print()
    print(f"Roster now holds {staffdb.staff_count()} staff "
          f"({staffdb.staff_count(include_inactive=False)} active).")

    return 1 if report['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
