#!/usr/bin/env python3
"""
Seed the educational groupings on the staff roster from the placement sheets.

Two placements per staff member, both consumed when classes are scheduled:

    education_group   the cohort they attend education with:  1, 2, 3, 4
    or_group          how many OR rotations they hold:        0 ("No OR"), 2, 3, 4

The placements themselves, and everything this does with them, live in
modules/educational_groupings.py — the Staff Database admin page's Import tab runs the
same seed from a button. This is the command-line way in, for seeding a database before
the app is started.

Examples:
    # Report what would change, and every name that does not line up, without writing
    python scripts/seed_educational_groupings.py --dry-run

    # Apply, leaving any placement already on file alone
    python scripts/seed_educational_groupings.py

    # Apply, letting the sheets win over placements already on file
    python scripts/seed_educational_groupings.py --overwrite
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import staff_database as staffdb  # noqa: E402
from modules.educational_groupings import format_seed_report, seed_groupings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', default=None,
                        help='Database file to write (default: data/medflight_tracks.db).')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would change without writing anything.')
    parser.add_argument('--overwrite', action='store_true',
                        help='Let the sheets win over placements already on file.')
    args = parser.parse_args()

    if args.db:
        staffdb.set_db_path(args.db)
    print(f"Database: {staffdb.get_db_path()}")

    report = seed_groupings(overwrite=args.overwrite, dry_run=args.dry_run,
                            changed_by='seed_educational_groupings.py')

    print()
    for line in format_seed_report(report):
        print(line)

    if args.dry_run:
        print()
        print("Dry run — nothing was written.")

    return 1 if report['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
