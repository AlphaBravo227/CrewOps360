#!/usr/bin/env python3
"""
Seed the educational groupings on the staff roster from the placement sheets.

Two placements per staff member, both consumed by the Training & Events module when
classes are scheduled:

    education_group   the cohort they attend education with:  1, 2, 3, 4
    or_group          how many OR rotations they hold:        0 ("No OR"), 2, 3, 4

The placements below are transcribed from the two grouping sheets. They are held here
rather than read from a workbook because the sheets are two flat columns-of-names with
no staff key of their own — a name in a column is the whole record. Once the app owns
the groupings, they are maintained on the Staff Database admin page and this script is
only needed to re-seed a fresh database.

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
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import staff_database as staffdb  # noqa: E402


# Sheet 1 — "Group 1" … "Group 4", one column per cohort.
EDUCATION_GROUPS = {
    '1': [
        'Ahlstedt', 'Bell', 'Bowman', 'Denison', 'Estanislao', 'Gallagher', 'Holst',
        'Kelley', 'Laterion', 'Lewis', 'McNulty', 'Mee', 'Moore', 'Moreau', 'Moynihan',
        'Pepin', 'Ravenelle', 'Saia', 'Wallace',
    ],
    '2': [
        'Boomhower', 'Cowart', 'Ender', 'Gittleson', 'Graham', 'Horan', 'Hourihan',
        'Lane', 'McKinnon', 'Montano', 'Phillips R.', 'Phillips K.', 'Powers', 'Romano',
        'Sacco', 'Shelanskas', 'Vescuso', 'Wyzansky',
    ],
    '3': [
        'Bach', 'Boege', 'Boutilier', 'Dinardo', 'Dunn', 'Fielding', 'Grant', 'Gibbs',
        'Hanley', 'Kilduff', 'King', 'McGrath', 'Murphy', 'Neimann', 'Seyoum', 'Payton',
        'Sheary', 'Steckewicz', 'Walker',
    ],
    '4': [
        'Carchia', 'Charest', 'Clark', 'Creekmuir', 'Doherty', 'Eastman', 'Kraby',
        'Machado', 'Marcosa', "O'Donnell", 'Puopolo', 'Rabickow', 'Sammon', 'Saraceno',
        'Sturtevant', 'Timm', 'Worsman', 'Young',
    ],
}

# Sheet 2 — "No OR", "2 OR", "3 OR", "4 OR", one column per placement. The four
# highlighted names at the foot of the "2 OR" column (Rabickow, Worsman, Charest,
# Eastman) are placed with the rest of that column; the highlight marks them as
# recently moved, not as a separate placement.
OR_GROUPS = {
    0: ['Ahlstedt', 'Parkas', 'Frakes', 'Holst', 'Muszalski', 'Wallace', 'Wheeler'],
    2: [
        'Bell', 'Boege', 'Boomhower', 'Denison', 'Dinardo', 'Dunn', 'Ender',
        'Estanislao', 'Gallagher', 'Gibbs', 'Hanley', 'Hourihan', 'Kilduff', 'Lewis',
        'McKinnon', 'Moreau', 'Pepin', 'Phillips R.', 'Puopolo', 'Saia', 'Steck',
        'Sturtevant', 'Rabickow', 'Worsman', 'Charest', 'Eastman',
    ],
    3: [
        'Bowman', 'Gittleson', 'Graham', 'Horan', 'King', 'McGrath', 'McNulty', 'Mee',
        'Montano', 'Moynihan', 'Murphy E', 'Neimann', 'Seyoum', 'Phillips K.', 'Vescuso',
    ],
    4: [
        'Bach', 'Boutilier', 'Carchia', 'Clark', 'Cowart', 'Creekmuir', 'Doherty',
        'Fielding', 'Grant', 'Grotton', 'Kelley', 'Kraby', 'Lane', 'Laterion', 'Lurie',
        'Machado', 'Marcosa', 'McWeeney', 'Moore', "O'Donnell", "O'Flaherty", 'Payton',
        'Phelan', 'Ravenelle', 'Romano', 'Sacco', 'Sammon', 'Saraceno', 'Sheary',
        'Shelanskas', 'Timm', 'Vanderkooi', 'Walker', 'Wyzansky', 'Young',
    ],
}

# Where a sheet spells a name differently from the roster. Case, spacing and
# punctuation are already folded away by _fold(), so this only covers the spellings
# that genuinely differ — a shortened surname, a dropped initial, a mis-keyed letter.
ALIASES = {
    'Hanley': 'Hanley-McCarthy',
    'Steck': 'Steckevicz',
    'Steckewicz': 'Steckevicz',
    'Murphy E': 'Murphy',
    'Parkas': 'Farkas',
}


def _fold(name):
    """
    A name reduced to what identifies it: lowercase letters and digits only.

    Folds away the differences that are not differences — the roster's curly
    apostrophe in O'Donnell against the sheet's straight one, VanderKooi against
    Vanderkooi, and any stray spacing.
    """
    text = unicodedata.normalize('NFKD', str(name)).replace('’', "'")
    return ''.join(ch for ch in text.lower() if ch.isalnum())


def build_index():
    """{folded name: roster name} for the whole roster, inactive staff included."""
    index = {}
    for name in staffdb.get_staff_names(include_inactive=True):
        index[_fold(name)] = name
    return index


def resolve(name, index):
    """The roster name a sheet entry refers to, or None when nothing matches."""
    match = index.get(_fold(name))
    if match is not None:
        return match
    alias = ALIASES.get(name)
    return index.get(_fold(alias)) if alias else None


def collect(index):
    """
    Read both sheets into {roster name: {'education_group': …, 'or_group': …}}.

    Returns:
        tuple: (placements, unmatched, duplicated) — unmatched is [(sheet, column,
        name)] for entries with no roster row, duplicated is [(sheet, name, [columns])]
        for a name listed in more than one column of the same sheet.
    """
    placements = {}
    unmatched = []
    duplicated = []

    for sheet, field, columns in (
        ('Group', 'education_group', EDUCATION_GROUPS),
        ('OR', 'or_group', OR_GROUPS),
    ):
        seen = {}
        for column, names in columns.items():
            for name in names:
                resolved = resolve(name, index)
                if resolved is None:
                    unmatched.append((sheet, column, name))
                    continue
                seen.setdefault(resolved, []).append(column)
                placements.setdefault(resolved, {})[field] = column
        duplicated.extend((sheet, name, columns_seen)
                          for name, columns_seen in sorted(seen.items())
                          if len(columns_seen) > 1)

    return placements, unmatched, duplicated


def describe(field, value):
    """How a placement reads in the report."""
    if value is None:
        return '—'
    return 'No OR' if field == 'or_group' and value == 0 else str(value)


def apply(placements, overwrite=False, dry_run=False, changed_by=None):
    """
    Write the placements onto the roster.

    A placement already on file is left alone (and reported as a conflict when it
    disagrees) unless overwrite is set — the same rule the staff roster import follows,
    so re-running this never quietly undoes an admin's edit.

    Returns:
        dict: counts plus 'changes' [(name, field, before, after)], 'conflicts'
        [(name, field, on_file, sheet_value)] and 'errors'.
    """
    result = {'changes': [], 'conflicts': [], 'unchanged': 0, 'errors': []}

    for name in sorted(placements):
        record = staffdb.get_staff(name)
        if not record:
            result['errors'].append(f"{name} left the roster mid-run.")
            continue

        updates = {}
        for field, value in placements[name].items():
            current = record[field]
            if current == value:
                result['unchanged'] += 1
                continue
            if current is not None and not overwrite:
                result['conflicts'].append((name, field, current, value))
                continue
            updates[field] = value
            result['changes'].append((name, field, current, value))

        if updates and not dry_run:
            success, message = staffdb.update_staff(name, changed_by=changed_by,
                                                    **updates)
            if not success:
                result['errors'].append(f"{name}: {message}")

    return result


def report_gaps(placements):
    """
    Staff the sheets do not fully place, split by how much it matters.

    Blank groupings are normal for the non-clinical roles and for management, so the
    roster's own definition of "works tracks" (a clinical role with a shift requirement
    on file) is what separates a real gap from an expected blank.
    """
    partial = []
    working_unplaced = []

    for record in staffdb.get_all_staff(include_inactive=True):
        name = record['staff_name']
        placed = placements.get(name, {})
        education = placed.get('education_group', record['education_group'])
        or_group = placed.get('or_group', record['or_group'])

        works_tracks = (staffdb.canonical_role(record['role']) in staffdb.CLINICAL_ROLES
                        and record['shifts_per_pay_period'] is not None)

        if education is None and or_group is None:
            if works_tracks:
                working_unplaced.append(name)
        elif education is None or or_group is None:
            partial.append((name, education, or_group, works_tracks))

    return partial, working_unplaced


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

    staffdb.initialize_staff_tables()
    if staffdb.staff_count() == 0:
        print("The staff roster is empty — run scripts/seed_staff_database.py first.")
        return 1

    index = build_index()
    placements, unmatched, duplicated = collect(index)
    outcome = apply(placements, overwrite=args.overwrite, dry_run=args.dry_run,
                    changed_by='seed_educational_groupings.py')
    partial, working_unplaced = report_gaps(placements)

    listed = sum(len(names) for names in EDUCATION_GROUPS.values()) \
        + sum(len(names) for names in OR_GROUPS.values())
    print()
    print(f"Sheet entries read: {listed}")
    print(f"Staff matched: {len(placements)}")
    print(f"Placements {'to set' if args.dry_run else 'set'}: {len(outcome['changes'])}")
    print(f"Placements already correct: {outcome['unchanged']}")

    if outcome['changes']:
        print()
        print("Placements " + ("to set:" if args.dry_run else "set:"))
        for name, field, before, after in outcome['changes']:
            print(f"  {name:<20} {field:<16} {describe(field, before)} -> "
                  f"{describe(field, after)}")

    if outcome['conflicts']:
        print()
        print("Already on file and different — left alone (pass --overwrite to change):")
        for name, field, current, value in outcome['conflicts']:
            print(f"  {name:<20} {field:<16} on file {describe(field, current)}, "
                  f"sheet says {describe(field, value)}")

    if unmatched:
        print()
        print("On a sheet but NOT on the staff roster:")
        for sheet, column, name in unmatched:
            print(f"  {sheet} {column}: {name}")

    if duplicated:
        print()
        print("Listed in more than one column of the same sheet:")
        for sheet, name, columns in duplicated:
            print(f"  {sheet}: {name} in {', '.join(str(c) for c in columns)}")

    if working_unplaced:
        print()
        print("Works tracks but on neither sheet:")
        for name in working_unplaced:
            print(f"  {name}")

    if partial:
        print()
        print("On one sheet but not the other:")
        for name, education, or_group, works_tracks in partial:
            note = '' if works_tracks else '   (does not work tracks)'
            print(f"  {name:<20} group {describe('education_group', education):<6} "
                  f"OR {describe('or_group', or_group)}{note}")

    if outcome['errors']:
        print()
        print("Errors:")
        for error in outcome['errors']:
            print(f"  {error}")

    if args.dry_run:
        print()
        print("Dry run — nothing was written.")

    return 1 if outcome['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
