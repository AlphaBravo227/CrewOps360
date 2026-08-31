# modules/educational_groupings.py
"""
The educational groupings, and seeding them onto the staff roster.

Two placements per staff member decide what education they are scheduled for:

    education_group   the cohort they attend education with:  1, 2, 3, 4
    or_group          how many OR rotations they hold:        0 ("No OR"), 2, 3, 4

Both live on the `staff` table (see modules/staff_database.py) and are maintained on the
Staff Database admin page from then on. This module holds their initial source and the
seeding logic behind both entry points — the Import tab's "Seed educational groupings"
button, and scripts/seed_educational_groupings.py.

Why the placements are transcribed here
---------------------------------------
The two placement sheets are flat columns of names under a heading, with no staff key of
their own: a name in a column is the whole record. There is nothing to key an import on
and nothing to re-read later, so the sheets are transcribed once, here, where the name
mismatches they carry can be resolved deliberately rather than guessed at on every run.

Seeding rule
------------
A placement already on file is reported rather than overwritten unless `overwrite` is
passed — the same rule the staff roster import follows, so a re-seed never quietly
undoes an admin's edit.
"""

import unicodedata

from . import staff_database as staffdb


# Sheet 1 — "Group 1" … "Group 4", one column per cohort.
EDUCATION_GROUP_SHEET = {
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
OR_GROUP_SHEET = {
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

# The two sheets, paired with the staff field each one fills.
SHEETS = (
    ('Group', 'education_group', EDUCATION_GROUP_SHEET),
    ('OR', 'or_group', OR_GROUP_SHEET),
)

# Where a sheet spells a name differently from the roster. Case, spacing and
# punctuation are already folded away by fold(), so this only covers the spellings that
# genuinely differ — a shortened surname, a dropped initial, a mis-keyed letter.
ALIASES = {
    'Hanley': 'Hanley-McCarthy',
    'Steck': 'Steckevicz',
    'Steckewicz': 'Steckevicz',
    'Murphy E': 'Murphy',
    'Parkas': 'Farkas',
}


def fold(name):
    """
    A name reduced to what identifies it: lowercase letters and digits only.

    Folds away the differences that are not differences — the roster's curly apostrophe
    in O'Donnell against the sheet's straight one, VanderKooi against Vanderkooi, and
    any stray spacing.
    """
    text = unicodedata.normalize('NFKD', str(name)).replace('’', "'")
    return ''.join(ch for ch in text.lower() if ch.isalnum())


def build_index():
    """{folded name: roster name} for the whole roster, inactive staff included."""
    return {fold(name): name
            for name in staffdb.get_staff_names(include_inactive=True)}


def resolve(name, index):
    """The roster name a sheet entry refers to, or None when nothing matches."""
    match = index.get(fold(name))
    if match is not None:
        return match
    alias = ALIASES.get(name)
    return index.get(fold(alias)) if alias else None


def collect(index=None):
    """
    Read both sheets into {roster name: {'education_group': …, 'or_group': …}}.

    Returns:
        tuple: (placements, unmatched, duplicated) — unmatched is [(sheet, column,
        name)] for entries with no roster row, duplicated is [(sheet, name, [columns])]
        for a name listed in more than one column of the same sheet.
    """
    if index is None:
        index = build_index()

    placements = {}
    unmatched = []
    duplicated = []

    for sheet, field, columns in SHEETS:
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
    """How a placement reads in a report."""
    if value is None:
        return '—'
    return 'No OR' if field == 'or_group' and value == 0 else str(value)


def apply_placements(placements, overwrite=False, dry_run=False, changed_by=None):
    """
    Write the placements onto the roster.

    Returns:
        dict: 'changes' [(name, field, before, after)], 'conflicts' [(name, field,
        on_file, sheet_value)], 'unchanged' (count) and 'errors'.
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


def find_gaps(placements):
    """
    Staff the sheets do not fully place, split by how much it matters.

    Blank groupings are normal for the non-clinical roles and for management, so the
    roster's own definition of "works tracks" (a clinical role with a shift requirement
    on file) is what separates a real gap from an expected blank.

    Returns:
        tuple: (partial, working_unplaced) — partial is [(name, education, or_group,
        works_tracks)] for staff on one sheet but not the other, working_unplaced is
        the names on neither sheet that nonetheless work tracks.
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


def seed_groupings(overwrite=False, dry_run=False, changed_by=None):
    """
    Seed both placement sheets onto the roster and report everything that did not
    line up.

    Args:
        overwrite (bool): let the sheets win over a placement already on file.
        dry_run (bool): report what would change without writing.

    Returns:
        dict: the keys of apply_placements(), plus 'listed' (sheet entries read),
        'matched' (staff the sheets resolved to), 'unmatched', 'duplicated', 'partial',
        'working_unplaced' and 'dry_run'. 'errors' is the only key that means something
        went wrong — the rest are for an admin to read.
    """
    staffdb.initialize_staff_tables()

    report = {
        'listed': sum(len(names) for _, _, columns in SHEETS
                      for names in columns.values()),
        'matched': 0,
        'changes': [], 'conflicts': [], 'unchanged': 0, 'errors': [],
        'unmatched': [], 'duplicated': [], 'partial': [], 'working_unplaced': [],
        'dry_run': dry_run,
    }

    if staffdb.staff_count() == 0:
        report['errors'].append(
            "The staff roster is empty — import it from the Excel sources first.")
        return report

    placements, unmatched, duplicated = collect()
    report['matched'] = len(placements)
    report['unmatched'] = unmatched
    report['duplicated'] = duplicated

    report.update(apply_placements(placements, overwrite=overwrite, dry_run=dry_run,
                                   changed_by=changed_by))

    report['partial'], report['working_unplaced'] = find_gaps(placements)
    return report


def format_seed_report(report):
    """The seed report as lines of text, for the CLI and the admin page alike."""
    verb = 'to set' if report['dry_run'] else 'set'
    lines = [
        f"Sheet entries read: {report['listed']}",
        f"Staff matched: {report['matched']}",
        f"Placements {verb}: {len(report['changes'])}",
        f"Placements already correct: {report['unchanged']}",
    ]

    if report['changes']:
        lines.append('')
        lines.append(f"Placements {verb}:")
        for name, field, before, after in report['changes']:
            lines.append(f"  {name:<20} {field:<16} {describe(field, before)} -> "
                         f"{describe(field, after)}")

    if report['conflicts']:
        lines.append('')
        lines.append("Already on file and different — left alone "
                     "(re-run with overwrite to change):")
        for name, field, current, value in report['conflicts']:
            lines.append(f"  {name:<20} {field:<16} on file {describe(field, current)}, "
                         f"sheet says {describe(field, value)}")

    if report['unmatched']:
        lines.append('')
        lines.append("On a sheet but NOT on the staff roster:")
        for sheet, column, name in report['unmatched']:
            lines.append(f"  {sheet} {column}: {name}")

    if report['duplicated']:
        lines.append('')
        lines.append("Listed in more than one column of the same sheet:")
        for sheet, name, columns in report['duplicated']:
            lines.append(f"  {sheet}: {name} in {', '.join(str(c) for c in columns)}")

    if report['working_unplaced']:
        lines.append('')
        lines.append("Works tracks but on neither sheet:")
        lines.extend(f"  {name}" for name in report['working_unplaced'])

    if report['partial']:
        lines.append('')
        lines.append("On one sheet but not the other:")
        for name, education, or_group, works_tracks in report['partial']:
            note = '' if works_tracks else '   (does not work tracks)'
            lines.append(f"  {name:<20} "
                         f"group {describe('education_group', education):<6} "
                         f"OR {describe('or_group', or_group)}{note}")

    if report['errors']:
        lines.append('')
        lines.append("Errors:")
        lines.extend(f"  {error}" for error in report['errors'])

    return lines
