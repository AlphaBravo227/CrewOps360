# modules/staff_groupings.py
"""
Named groupings of staff, and who is in them.

A grouping is a list of staff members under a name — "Group 1", "4 OR", "New Hires
2027", "CCEMT Refresher Cohort". It carries no meaning of its own beyond its
membership: nothing in the app derives a requirement, a count or a schedule from a
grouping's name. That is the point. Classes are assigned to groupings, so a new way of
carving up the roster is a row in a table rather than a column, a validator, a picker
and a migration.

    staff_groupings          the grouping: name, description, archived or not
    staff_grouping_members   which staff are in it, one row per membership

Membership is many-to-many and unconstrained: a staff member can be in as many
groupings as makes sense, and being in one says nothing about the others. Groupings are
global rather than per training year — when a cohort reshuffles, edit its membership,
or archive it and make a new one. Archived groupings keep their membership and stay
readable on the classes that used them; they just drop out of the pickers.

Membership is stored by staff name, the same join key the rest of the database uses, so
a rename made on the Staff Database admin page carries into groupings automatically
(see staff_database.STAFF_NAME_COLUMNS).

What this replaced
------------------
Two fixed columns on the `staff` table: `education_group` (cohort 1-4) and `or_group`
(OR classes owed for the year: 0, 2, 3, 4). They were the only groupings the app could
express, they were seeded from name lists transcribed into the source, and adding a
third kind meant another column everywhere. migrate_legacy_groupings() below turns
whatever those columns hold into eight ordinary groupings and then drops them.
"""

import json
import sqlite3

from . import staff_database as staffdb


# The tables this module owns.
GROUPINGS_TABLE = 'staff_groupings'
MEMBERS_TABLE = 'staff_grouping_members'

# Groupings the legacy columns become, in the order they should appear in a picker.
# `education_group` held '1'-'4'; `or_group` held 0, 2, 3 and 4, where 0 was a real
# placement ("required to take no OR classes") and NULL meant nobody had placed them.
LEGACY_EDUCATION_GROUPS = {
    '1': 'Group 1', '2': 'Group 2', '3': 'Group 3', '4': 'Group 4',
}
LEGACY_OR_GROUPS = {
    0: 'No OR', 2: '2 OR', 3: '3 OR', 4: '4 OR',
}

_MIGRATION_KEY = 'legacy_groupings_migrated'


def _conn():
    return staffdb._get_conn()


def _now():
    return staffdb._now()


# ──────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────

def initialize_grouping_tables():
    """Create the grouping tables, and migrate the legacy columns the first time."""
    try:
        conn = _conn()
        cursor = conn.cursor()

        # Names are the grouping's visible identity, so they are UNIQUE and NOCASE —
        # "group 1" and "Group 1" must not be two groupings sitting side by side in a
        # picker. `sort_order` is what the pickers order by, so an admin can keep
        # related groupings together without renaming them into alphabetical order.
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {GROUPINGS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL
        )
        ''')

        # One row per membership. UNIQUE on the pair makes adding somebody twice a
        # no-op rather than a duplicate, which is what every caller wants.
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {MEMBERS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grouping_id INTEGER NOT NULL,
            staff_name TEXT NOT NULL COLLATE NOCASE,
            added_date TEXT NOT NULL,
            UNIQUE(grouping_id, staff_name)
        )
        ''')

        # A small key/value table for the one-time migration marker. It has to survive
        # the case where dropping the legacy columns is not possible (SQLite older than
        # 3.35), so the marker cannot simply be "the columns are gone".
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {GROUPINGS_TABLE}_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        ''')

        cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_grouping_members_grouping '
                       f'ON {MEMBERS_TABLE}(grouping_id)')
        cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_grouping_members_staff '
                       f'ON {MEMBERS_TABLE}(staff_name)')

        conn.commit()

        migrate_legacy_groupings()
        return True

    except Exception as e:
        print(f"Error initializing grouping tables: {e}")
        return False


def grouping_tables_exist():
    try:
        cursor = _conn().cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                       (GROUPINGS_TABLE,))
        return cursor.fetchone() is not None
    except Exception:
        return False


def _get_meta(key):
    try:
        cursor = _conn().cursor()
        cursor.execute(f"SELECT value FROM {GROUPINGS_TABLE}_meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _set_meta(cursor, key, value):
    cursor.execute(
        f"INSERT INTO {GROUPINGS_TABLE}_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


# ──────────────────────────────────────────────
# Reading
# ──────────────────────────────────────────────

def _row_to_grouping(row):
    return {
        'id': row[0],
        'name': row[1],
        'description': row[2],
        'is_active': bool(row[3]),
        'sort_order': row[4],
        'created_date': row[5],
        'modified_date': row[6],
    }


def get_groupings(include_archived=False, with_counts=False):
    """
    Every grouping, in picker order (sort_order, then name).

    Args:
        include_archived (bool): include groupings that have been archived.
        with_counts (bool): add 'member_count' — active staff currently in it.
    """
    if not grouping_tables_exist():
        return []
    try:
        cursor = _conn().cursor()
        clause = '' if include_archived else 'WHERE is_active = 1'
        cursor.execute(f'''
            SELECT id, name, description, is_active, sort_order, created_date,
                   modified_date
            FROM {GROUPINGS_TABLE} {clause}
            ORDER BY sort_order, name COLLATE NOCASE
        ''')
        groupings = [_row_to_grouping(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error reading groupings: {e}")
        return []

    if with_counts:
        counts = member_counts()
        for grouping in groupings:
            grouping['member_count'] = counts.get(grouping['id'], 0)
    return groupings


def get_grouping(grouping_id):
    """One grouping by id, or None."""
    if not grouping_tables_exist():
        return None
    try:
        cursor = _conn().cursor()
        cursor.execute(f'''
            SELECT id, name, description, is_active, sort_order, created_date,
                   modified_date
            FROM {GROUPINGS_TABLE} WHERE id = ?
        ''', (grouping_id,))
        row = cursor.fetchone()
        return _row_to_grouping(row) if row else None
    except Exception as e:
        print(f"Error reading grouping {grouping_id}: {e}")
        return None


def get_grouping_by_name(name):
    """One grouping by name (case-insensitive), or None."""
    if not grouping_tables_exist() or not str(name or '').strip():
        return None
    try:
        cursor = _conn().cursor()
        cursor.execute(f'''
            SELECT id, name, description, is_active, sort_order, created_date,
                   modified_date
            FROM {GROUPINGS_TABLE} WHERE name = ? COLLATE NOCASE
        ''', (str(name).strip(),))
        row = cursor.fetchone()
        return _row_to_grouping(row) if row else None
    except Exception as e:
        print(f"Error reading grouping '{name}': {e}")
        return None


def grouping_names(grouping_ids):
    """The names of the given groupings, in picker order — for describing a selection."""
    wanted = {int(g) for g in grouping_ids if str(g).strip() != ''}
    return [g['name'] for g in get_groupings(include_archived=True)
            if g['id'] in wanted]


def _stored_members(grouping_id):
    """The names on file for a grouping, exactly as stored, without a roster check."""
    try:
        cursor = _conn().cursor()
        cursor.execute(f"SELECT staff_name FROM {MEMBERS_TABLE} WHERE grouping_id = ?",
                       (grouping_id,))
        return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error reading members of grouping {grouping_id}: {e}")
        return []


def get_members(grouping_id, include_inactive=False):
    """
    Names of the staff in one grouping, in roster order.

    Filtered against the roster, so a name that has been deleted from the roster
    outright does not come back, and inactive staff are left out unless asked for —
    somebody who has left should not be pulled into a class by a grouping they are
    still recorded against.
    """
    if not grouping_tables_exist():
        return []
    stored = {staffdb.clean_name(name).lower() for name in _stored_members(grouping_id)}
    if not stored:
        return []
    return [record['staff_name']
            for record in staffdb.get_all_staff(include_inactive=include_inactive)
            if record['staff_name'].lower() in stored]


def get_members_of_many(grouping_ids, include_inactive=False):
    """
    Names in any of the given groupings — the union, in roster order.

    The union is the useful reading: a class taught to "Group 2" and "4 OR" is for
    everyone in either, not only the people in both.
    """
    wanted = set()
    for grouping_id in grouping_ids:
        try:
            wanted.update(name.lower()
                          for name in (staffdb.clean_name(n)
                                       for n in _stored_members(int(grouping_id))))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return []
    return [record['staff_name']
            for record in staffdb.get_all_staff(include_inactive=include_inactive)
            if record['staff_name'].lower() in wanted]


def member_counts(include_inactive=False):
    """{grouping_id: number of members} counting only staff still on the roster."""
    if not grouping_tables_exist():
        return {}
    roster = {record['staff_name'].lower()
              for record in staffdb.get_all_staff(include_inactive=include_inactive)}
    counts = {}
    try:
        cursor = _conn().cursor()
        cursor.execute(f"SELECT grouping_id, staff_name FROM {MEMBERS_TABLE}")
        for grouping_id, staff_name in cursor.fetchall():
            if staffdb.clean_name(staff_name).lower() in roster:
                counts[grouping_id] = counts.get(grouping_id, 0) + 1
    except Exception as e:
        print(f"Error counting grouping members: {e}")
    return counts


def get_groupings_for_staff(staff_name, include_archived=True):
    """The groupings one staff member belongs to, in picker order."""
    if not grouping_tables_exist():
        return []
    name = staffdb.clean_name(staff_name)
    if not name:
        return []
    try:
        cursor = _conn().cursor()
        cursor.execute(f"SELECT grouping_id FROM {MEMBERS_TABLE} "
                       "WHERE staff_name = ? COLLATE NOCASE", (name,))
        held = {row[0] for row in cursor.fetchall()}
    except Exception as e:
        print(f"Error reading groupings for {name}: {e}")
        return []
    return [g for g in get_groupings(include_archived=include_archived)
            if g['id'] in held]


def get_grouping_mapping(include_inactive=False, include_archived=True):
    """{staff_name: [grouping names]} for everyone who is in at least one."""
    if not grouping_tables_exist():
        return {}
    names_by_id = {g['id']: g['name']
                   for g in get_groupings(include_archived=include_archived)}
    roster = {record['staff_name'].lower(): record['staff_name']
              for record in staffdb.get_all_staff(include_inactive=include_inactive)}

    mapping = {}
    try:
        cursor = _conn().cursor()
        cursor.execute(f"SELECT grouping_id, staff_name FROM {MEMBERS_TABLE}")
        for grouping_id, staff_name in cursor.fetchall():
            if grouping_id not in names_by_id:
                continue
            roster_name = roster.get(staffdb.clean_name(staff_name).lower())
            if roster_name:
                mapping.setdefault(roster_name, []).append(names_by_id[grouping_id])
    except Exception as e:
        print(f"Error building the grouping mapping: {e}")
        return {}

    order = [g['name'] for g in get_groupings(include_archived=include_archived)]
    position = {name: index for index, name in enumerate(order)}
    return {name: sorted(groups, key=lambda g: position.get(g, len(position)))
            for name, groups in mapping.items()}


def get_ungrouped_staff(include_inactive=False, include_archived=False):
    """Names on the roster that are in no grouping at all."""
    grouped = set(get_grouping_mapping(include_inactive=include_inactive,
                                       include_archived=include_archived))
    return [record['staff_name']
            for record in staffdb.get_all_staff(include_inactive=include_inactive)
            if record['staff_name'] not in grouped]


# ──────────────────────────────────────────────
# Writing
# ──────────────────────────────────────────────

def validate_grouping_name(name, exclude_id=None):
    """Problems with a proposed grouping name; empty when it is fine."""
    errors = []
    clean = str(name or '').strip()
    if not clean:
        errors.append("A grouping needs a name.")
        return errors
    if len(clean) > 80:
        errors.append("The grouping name is too long (max 80 characters).")
    existing = get_grouping_by_name(clean)
    if existing and existing['id'] != exclude_id:
        errors.append(f"'{existing['name']}' already exists.")
    return errors


def create_grouping(name, description=None, sort_order=None, members=None,
                    changed_by=None):
    """
    Create a grouping, optionally with its members.

    Returns:
        tuple: (success, message, grouping_id)
    """
    initialize_grouping_tables()

    errors = validate_grouping_name(name)
    if errors:
        return False, " ".join(errors), None

    clean = str(name).strip()
    if sort_order is None:
        # New groupings land at the end of the picker rather than in the middle of the
        # order somebody has already arranged.
        existing = get_groupings(include_archived=True)
        sort_order = (max((g['sort_order'] for g in existing), default=0) + 10)

    try:
        conn = _conn()
        cursor = conn.cursor()
        now = _now()
        cursor.execute(f'''
            INSERT INTO {GROUPINGS_TABLE} (name, description, is_active, sort_order,
                                           created_date, modified_date)
            VALUES (?, ?, 1, ?, ?, ?)
        ''', (clean, (description or '').strip() or None, int(sort_order), now, now))
        grouping_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        return False, f"'{clean}' already exists.", None
    except Exception as e:
        return False, f"Error creating the grouping: {e}", None

    if members:
        set_members(grouping_id, members, changed_by=changed_by)
        return True, (f"Created '{clean}' with "
                      f"{len(get_members(grouping_id, include_inactive=True))} member(s)."), grouping_id
    return True, f"Created '{clean}'.", grouping_id


def update_grouping(grouping_id, name=None, description=None, is_active=None,
                    sort_order=None, changed_by=None):
    """
    Rename a grouping, reword it, archive or restore it, or move it in the order.

    Only the arguments passed are changed. Returns (success, message).
    """
    grouping = get_grouping(grouping_id)
    if not grouping:
        return False, "That grouping no longer exists."

    updates = {}
    if name is not None and str(name).strip() != grouping['name']:
        errors = validate_grouping_name(name, exclude_id=grouping_id)
        if errors:
            return False, " ".join(errors)
        updates['name'] = str(name).strip()
    if description is not None:
        cleaned = str(description).strip() or None
        if cleaned != grouping['description']:
            updates['description'] = cleaned
    if is_active is not None and bool(is_active) != grouping['is_active']:
        updates['is_active'] = 1 if is_active else 0
    if sort_order is not None and int(sort_order) != grouping['sort_order']:
        updates['sort_order'] = int(sort_order)

    if not updates:
        return True, f"No changes for '{grouping['name']}'."

    try:
        conn = _conn()
        cursor = conn.cursor()
        assignments = ', '.join(f"{key} = ?" for key in updates)
        cursor.execute(f"UPDATE {GROUPINGS_TABLE} SET {assignments}, modified_date = ? "
                       "WHERE id = ?",
                       list(updates.values()) + [_now(), grouping_id])
        conn.commit()
    except sqlite3.IntegrityError:
        return False, f"'{updates.get('name')}' already exists."
    except Exception as e:
        return False, f"Error updating the grouping: {e}"

    if 'is_active' in updates:
        state = "Restored" if updates['is_active'] else "Archived"
        return True, f"{state} '{updates.get('name', grouping['name'])}'."
    return True, f"Updated '{updates.get('name', grouping['name'])}'."


def delete_grouping(grouping_id, changed_by=None):
    """
    Delete a grouping and its memberships outright.

    Deleting loses the record of who was in it. Archiving (update_grouping with
    is_active=False) keeps the membership and takes the grouping out of the pickers,
    which is what a cohort that has been superseded wants.

    Returns:
        tuple: (success, message)
    """
    grouping = get_grouping(grouping_id)
    if not grouping:
        return False, "That grouping no longer exists."

    members = _stored_members(grouping_id)
    try:
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {MEMBERS_TABLE} WHERE grouping_id = ?",
                       (grouping_id,))
        cursor.execute(f"DELETE FROM {GROUPINGS_TABLE} WHERE id = ?", (grouping_id,))
        for name in members:
            _log_membership(cursor, name, grouping['name'], 'grouping_deleted',
                            changed_by)
        conn.commit()
        return True, (f"Deleted '{grouping['name']}' and its "
                      f"{len(members)} membership(s).")
    except Exception as e:
        return False, f"Error deleting '{grouping['name']}': {e}"


def _log_membership(cursor, staff_name, grouping_name, action, changed_by):
    """Record a membership change against the staff member, for the History tab."""
    staffdb._log_audit(cursor, staff_name, action, {'grouping': grouping_name},
                       changed_by)


def set_members(grouping_id, staff_names, changed_by=None):
    """
    Replace a grouping's membership with exactly these staff.

    Names not on the roster are ignored rather than stored, so a grouping cannot
    accumulate members who do not exist.

    Returns:
        tuple: (success, message)
    """
    grouping = get_grouping(grouping_id)
    if not grouping:
        return False, "That grouping no longer exists."

    roster = {record['staff_name'].lower(): record['staff_name']
              for record in staffdb.get_all_staff(include_inactive=True)}
    wanted = {}
    for name in staff_names or []:
        resolved = roster.get(staffdb.clean_name(name).lower())
        if resolved:
            wanted[resolved.lower()] = resolved

    current = {}
    for name in _stored_members(grouping_id):
        current[staffdb.clean_name(name).lower()] = staffdb.clean_name(name)

    added = [wanted[key] for key in wanted if key not in current]
    removed = [current[key] for key in current if key not in wanted]
    # Names on file that are no longer on the roster are dropped along with the
    # explicit removals — there is nothing left for them to refer to.
    if not added and not removed:
        return True, f"No membership changes for '{grouping['name']}'."

    try:
        conn = _conn()
        cursor = conn.cursor()
        now = _now()
        cursor.execute(f"DELETE FROM {MEMBERS_TABLE} WHERE grouping_id = ?",
                       (grouping_id,))
        cursor.executemany(
            f"INSERT INTO {MEMBERS_TABLE} (grouping_id, staff_name, added_date) "
            "VALUES (?, ?, ?)",
            [(grouping_id, name, now) for name in sorted(wanted.values())])
        for name in added:
            _log_membership(cursor, name, grouping['name'], 'grouping_added', changed_by)
        for name in removed:
            _log_membership(cursor, name, grouping['name'], 'grouping_removed',
                            changed_by)
        conn.commit()
    except Exception as e:
        return False, f"Error saving the membership of '{grouping['name']}': {e}"

    parts = []
    if added:
        parts.append(f"added {len(added)}")
    if removed:
        parts.append(f"removed {len(removed)}")
    return True, f"'{grouping['name']}': {', '.join(parts)}."


def add_members(grouping_id, staff_names, changed_by=None):
    """Add staff to a grouping, leaving the existing membership in place."""
    existing = _stored_members(grouping_id)
    return set_members(grouping_id, list(existing) + list(staff_names or []),
                       changed_by=changed_by)


def remove_members(grouping_id, staff_names, changed_by=None):
    """Remove staff from a grouping, leaving everybody else in place."""
    drop = {staffdb.clean_name(name).lower() for name in staff_names or []}
    keep = [name for name in _stored_members(grouping_id)
            if staffdb.clean_name(name).lower() not in drop]
    return set_members(grouping_id, keep, changed_by=changed_by)


def set_groupings_for_staff(staff_name, grouping_ids, changed_by=None):
    """
    Replace one staff member's groupings with exactly these — the staff-side edit.

    Archived groupings the staff member is already in are left alone: they are not in
    the picker the caller built its list from, so their absence from it is not a
    request to remove them.

    Returns:
        tuple: (success, message)
    """
    initialize_grouping_tables()
    record = staffdb.get_staff(staff_name)
    if not record:
        return False, f"'{staffdb.clean_name(staff_name)}' is not on the staff roster."

    name = record['staff_name']
    selectable = {g['id'] for g in get_groupings()}
    wanted = {int(g) for g in grouping_ids or [] if str(g).strip() != ''} & selectable
    current = {g['id'] for g in get_groupings_for_staff(name, include_archived=False)}

    added = wanted - current
    removed = current - wanted
    if not added and not removed:
        return True, f"No grouping changes for {name}."

    by_id = {g['id']: g['name'] for g in get_groupings(include_archived=True)}
    try:
        conn = _conn()
        cursor = conn.cursor()
        now = _now()
        for grouping_id in sorted(added):
            cursor.execute(
                f"INSERT OR IGNORE INTO {MEMBERS_TABLE} "
                "(grouping_id, staff_name, added_date) VALUES (?, ?, ?)",
                (grouping_id, name, now))
            _log_membership(cursor, name, by_id.get(grouping_id, str(grouping_id)),
                            'grouping_added', changed_by)
        for grouping_id in sorted(removed):
            cursor.execute(f"DELETE FROM {MEMBERS_TABLE} WHERE grouping_id = ? "
                           "AND staff_name = ? COLLATE NOCASE", (grouping_id, name))
            _log_membership(cursor, name, by_id.get(grouping_id, str(grouping_id)),
                            'grouping_removed', changed_by)
        conn.commit()
    except Exception as e:
        return False, f"Error saving groupings for {name}: {e}"

    parts = []
    if added:
        parts.append(f"added to {len(added)}")
    if removed:
        parts.append(f"removed from {len(removed)}")
    return True, f"{name}: {', '.join(parts)} grouping(s)."


def remove_staff_from_all(staff_name, cursor=None):
    """
    Drop every membership held by a staff member — used when they leave the roster
    outright. Takes a cursor so it can join a delete already in progress.
    """
    name = staffdb.clean_name(staff_name)
    if not name or not grouping_tables_exist():
        return 0
    own_cursor = cursor is None
    try:
        conn = _conn()
        cursor = cursor or conn.cursor()
        cursor.execute(f"DELETE FROM {MEMBERS_TABLE} WHERE staff_name = ? COLLATE NOCASE",
                       (name,))
        removed = cursor.rowcount
        if own_cursor:
            conn.commit()
        return removed
    except Exception as e:
        print(f"Error removing {name} from their groupings: {e}")
        return 0


# ──────────────────────────────────────────────
# Migration off the legacy columns
# ──────────────────────────────────────────────

def migrate_legacy_groupings():
    """
    Turn the old `education_group` / `or_group` columns into ordinary groupings, once.

    Three things happen, in one transaction:

      1. Each distinct value in use becomes a grouping — '2' becomes "Group 2", 0
         becomes "No OR" — and the staff who held it become its members.
      2. Saved classes have their `assignment_source` rewritten from the old
         {'education_groups': [...], 'or_groups': [...]} keys to {'groupings': [ids]}.
         Their `assigned_staff` lists are already materialized and are untouched.
      3. The columns and their indexes are dropped.

    A grouping that already exists under the same name is filled rather than
    duplicated, so a half-finished migration can be run again. The marker in
    `staff_groupings_meta` is what stops it running twice; the columns being gone is
    not relied on, because dropping a column needs SQLite 3.35 and this has to be
    correct on an older one too.

    Returns:
        dict: 'ran' (bool), 'groupings' [(name, member count)], 'classes' (sources
        rewritten), 'columns_dropped' (bool) and 'errors'.
    """
    result = {'ran': False, 'groupings': [], 'classes': 0, 'columns_dropped': False,
              'errors': []}

    if _get_meta(_MIGRATION_KEY):
        return result

    try:
        conn = _conn()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(staff)")
        columns = [row[1] for row in cursor.fetchall()]
        legacy = [column for column in ('education_group', 'or_group')
                  if column in columns]

        placements = {}
        if legacy:
            selected = ', '.join(['staff_name'] + legacy)
            cursor.execute(f"SELECT {selected} FROM staff")
            for row in cursor.fetchall():
                staff_name = row[0]
                for column, value in zip(legacy, row[1:]):
                    if value is None or str(value).strip() == '':
                        continue
                    if column == 'education_group':
                        name = LEGACY_EDUCATION_GROUPS.get(str(value).strip())
                    else:
                        try:
                            name = LEGACY_OR_GROUPS.get(int(value))
                        except (TypeError, ValueError):
                            name = None
                    if name:
                        placements.setdefault(name, []).append(staff_name)

        # Created in the order the legacy sheets read, so the picker opens with the
        # education cohorts above the OR groupings rather than in migration order.
        ordered = ([name for name in LEGACY_EDUCATION_GROUPS.values() if name in placements]
                   + [name for name in LEGACY_OR_GROUPS.values() if name in placements])

        now = _now()
        ids_by_name = {}
        for index, name in enumerate(ordered):
            existing = get_grouping_by_name(name)
            if existing:
                grouping_id = existing['id']
            else:
                cursor.execute(f'''
                    INSERT INTO {GROUPINGS_TABLE} (name, description, is_active,
                                                   sort_order, created_date,
                                                   modified_date)
                    VALUES (?, ?, 1, ?, ?, ?)
                ''', (name, 'Carried over from the educational groupings.',
                      (index + 1) * 10, now, now))
                grouping_id = cursor.lastrowid
            ids_by_name[name] = grouping_id

            for staff_name in placements[name]:
                cursor.execute(
                    f"INSERT OR IGNORE INTO {MEMBERS_TABLE} "
                    "(grouping_id, staff_name, added_date) VALUES (?, ?, ?)",
                    (grouping_id, staff_name, now))
            result['groupings'].append((name, len(placements[name])))

        result['classes'] = _migrate_assignment_sources(cursor, ids_by_name)

        # The columns go last, so a failure above leaves them in place to try again.
        if legacy:
            try:
                cursor.execute("DROP INDEX IF EXISTS idx_staff_education_group")
                cursor.execute("DROP INDEX IF EXISTS idx_staff_or_group")
                for column in legacy:
                    cursor.execute(f"ALTER TABLE staff DROP COLUMN {column}")
                result['columns_dropped'] = True
            except sqlite3.OperationalError as e:
                # SQLite before 3.35 cannot drop a column. The columns are harmless
                # once nothing reads them, so this is reported rather than fatal.
                result['errors'].append(
                    f"The legacy grouping columns could not be dropped ({e}). "
                    "They are no longer read and can be left in place.")

        _set_meta(cursor, _MIGRATION_KEY, now)
        conn.commit()
        staffdb.invalidate_cache()
        result['ran'] = True

    except Exception as e:
        try:
            _conn().rollback()
        except Exception:
            pass
        result['errors'].append(f"Error migrating the educational groupings: {e}")

    return result


def _migrate_assignment_sources(cursor, ids_by_name):
    """
    Rewrite saved classes' `assignment_source` from the legacy keys to grouping ids.

    Returns the number of classes rewritten. A class whose source names a grouping the
    roster never used keeps the rest of its selection — the roles in particular, which
    are unaffected by any of this.
    """
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' "
                   "AND name = 'training_classes'")
    if cursor.fetchone() is None:
        return 0

    cursor.execute("PRAGMA table_info(training_classes)")
    if 'assignment_source' not in [row[1] for row in cursor.fetchall()]:
        return 0

    cursor.execute("SELECT id, assignment_source FROM training_classes "
                   "WHERE assignment_source IS NOT NULL AND assignment_source != ''")
    rows = cursor.fetchall()

    rewritten = 0
    for class_id, raw in rows:
        try:
            source = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(source, dict) or 'groupings' in source:
            continue

        grouping_ids = []
        for value in source.get('education_groups') or []:
            name = LEGACY_EDUCATION_GROUPS.get(str(value).strip())
            if name in ids_by_name:
                grouping_ids.append(ids_by_name[name])
        for value in source.get('or_groups') or []:
            try:
                name = LEGACY_OR_GROUPS.get(int(value))
            except (TypeError, ValueError):
                continue
            if name in ids_by_name:
                grouping_ids.append(ids_by_name[name])

        cursor.execute("UPDATE training_classes SET assignment_source = ? WHERE id = ?",
                       (json.dumps({'groupings': sorted(dict.fromkeys(grouping_ids)),
                                    'roles': list(source.get('roles') or [])}),
                        class_id))
        rewritten += 1

    return rewritten
