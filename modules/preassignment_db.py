# modules/preassignment_db.py
"""
Preassignments, per track cycle, in the database.

A preassignment is a day a staff member is committed to something other than a normal
shift (AT, a class, an assignment) before bidding starts. They count as day shifts, are
locked in the editors, and are authored fresh for each bid cycle.

That authoring used to mean editing Preassignments.xlsx and dropping it in the upload
folder. Now they live in `track_preassignments`, keyed by the cycle's track_name, so a
bid cycle's preassignments are configured in the app when the cycle is created — and one
cycle's preassignments can be copied to the next as a starting point.

The read path returns the same DataFrame shape the spreadsheet did (staff names as the
index, day labels as columns) so every existing caller of get_staff_preassignments() is
unaffected.
"""

from datetime import datetime

import pandas as pd
import pytz

from .day_pattern import PATTERN_DAYS, sort_pattern_days

_eastern_tz = pytz.timezone('America/New_York')

STAFF_NAME_COLUMN = 'STAFF NAME'


def _get_conn():
    from .db_utils import get_db_connection
    return get_db_connection()


def _now():
    return datetime.now(_eastern_tz).strftime('%Y-%m-%d %H:%M:%S')


def initialize_preassignment_tables():
    """
    Create the per-cycle preassignment table if it doesn't exist. Safe to call repeatedly.

    Note this is a different table from `preassignments` in db_utils, which is not scoped
    to a track cycle and is left alone.
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS track_preassignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            day TEXT NOT NULL,
            activity TEXT NOT NULL,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            UNIQUE(track_name, staff_name, day)
        )
        ''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_track_preassignments_track
                          ON track_preassignments(track_name)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_track_preassignments_staff
                          ON track_preassignments(track_name, staff_name)''')
        conn.commit()
        return True
    except Exception as e:
        print(f"Error initializing preassignment tables: {e}")
        return False


def _table_exists():
    try:
        cursor = _get_conn().cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' "
                       "AND name='track_preassignments'")
        return cursor.fetchone() is not None
    except Exception:
        return False


def resolve_track_name(track_name=None):
    """
    Which cycle's preassignments to use.

    Falls back to the cycle bidding is open on, then the active cycle — the same
    precedence the bidding views use, so a staff member bidding on FY27 sees FY27's
    preassignments while the clinical hub shows the active cycle's.
    """
    if track_name:
        return track_name
    try:
        from .db_utils import get_active_track_config, get_bidding_track_config
        bidding = get_bidding_track_config()
        if bidding:
            return bidding['track_name']
        active = get_active_track_config()
        if active:
            return active['track_name']
    except Exception as e:
        print(f"Could not resolve the track cycle for preassignments: {e}")
    return None


def get_preassignments(track_name=None):
    """
    Preassignments for one cycle.

    Returns:
        dict: {staff_name: {day: activity}}
    """
    cycle = resolve_track_name(track_name)
    result = {}
    if not cycle or not _table_exists():
        return result
    try:
        cursor = _get_conn().cursor()
        cursor.execute("""
            SELECT staff_name, day, activity FROM track_preassignments
            WHERE track_name = ?
        """, (cycle,))
        for staff_name, day, activity in cursor.fetchall():
            name = str(staff_name).strip()
            if not name:
                continue
            result.setdefault(name, {})[str(day).strip()] = str(activity).strip()
    except Exception as e:
        print(f"Error reading preassignments for {cycle}: {e}")
    return result


def get_staff_preassignments(staff_name, track_name=None):
    """
    One staff member's preassignments for a cycle.

    Returns:
        dict: {day: activity}
    """
    name = str(staff_name or '').strip()
    if not name:
        return {}
    return get_preassignments(track_name).get(name, {})


def build_preassignment_df(track_name=None, days=None):
    """
    Preassignments in the shape Preassignments.xlsx produced once loaded: a DataFrame
    indexed by staff name with one column per day.

    This is what get_staff_preassignments() / has_preassignment() in
    modules/track_management/preassignment.py expect, so it drops straight in.

    Returns:
        DataFrame or None: None when the cycle has no preassignments at all, matching
        the old loader's "no file found" return so callers keep their existing checks.
    """
    preassignments = get_preassignments(track_name)
    if not preassignments:
        return None

    day_columns = list(days) if days is not None else list(PATTERN_DAYS)
    # Days outside the canonical pattern (a renamed cycle, hand-entered labels) are kept
    # rather than dropped, so nothing silently disappears from a staff member's row.
    extra_days = sort_pattern_days({day for staff in preassignments.values()
                                    for day in staff} - set(day_columns))
    day_columns = day_columns + list(extra_days)

    rows = []
    for staff_name in sorted(preassignments):
        row = {STAFF_NAME_COLUMN: staff_name}
        staff_days = preassignments[staff_name]
        for day in day_columns:
            row[day] = staff_days.get(day, '')
        rows.append(row)

    df = pd.DataFrame(rows, columns=[STAFF_NAME_COLUMN] + day_columns)
    return df.set_index(STAFF_NAME_COLUMN)


def set_staff_preassignments(track_name, staff_name, preassignments, changed_by=None):
    """
    Replace one staff member's preassignments for a cycle.

    Args:
        preassignments (dict): {day: activity}. Days with a blank activity are removed,
            so clearing a cell in the editor deletes the preassignment.

    Returns:
        tuple: (success, message)
    """
    cycle = resolve_track_name(track_name)
    if not cycle:
        return False, "No track cycle selected."
    name = str(staff_name or '').strip()
    if not name:
        return False, "Staff name is required."

    initialize_preassignment_tables()
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        now = _now()

        cursor.execute("DELETE FROM track_preassignments WHERE track_name = ? "
                       "AND staff_name = ? COLLATE NOCASE", (cycle, name))

        written = 0
        for day, activity in (preassignments or {}).items():
            label = str(day).strip()
            value = '' if activity is None else str(activity).strip()
            if not label or not value:
                continue
            cursor.execute("""
                INSERT INTO track_preassignments
                (track_name, staff_name, day, activity, created_date, modified_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (cycle, name, label, value, now, now))
            written += 1

        conn.commit()
        if written:
            return True, f"Saved {written} preassignment(s) for {name} on {cycle}."
        return True, f"Cleared all preassignments for {name} on {cycle}."
    except Exception as e:
        return False, f"Error saving preassignments for {name}: {e}"


def set_preassignment(track_name, staff_name, day, activity):
    """
    Set or clear a single day's preassignment.

    Returns:
        tuple: (success, message)
    """
    cycle = resolve_track_name(track_name)
    if not cycle:
        return False, "No track cycle selected."
    name = str(staff_name or '').strip()
    label = str(day or '').strip()
    if not name or not label:
        return False, "Staff name and day are required."

    initialize_preassignment_tables()
    value = '' if activity is None else str(activity).strip()
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        now = _now()
        if not value:
            cursor.execute("""DELETE FROM track_preassignments
                              WHERE track_name = ? AND staff_name = ? COLLATE NOCASE
                              AND day = ?""", (cycle, name, label))
            conn.commit()
            return True, f"Cleared {name} on {label}."
        cursor.execute("""
            INSERT INTO track_preassignments
            (track_name, staff_name, day, activity, created_date, modified_date)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_name, staff_name, day)
            DO UPDATE SET activity = excluded.activity, modified_date = excluded.modified_date
        """, (cycle, name, label, value, now, now))
        conn.commit()
        return True, f"Set {name} on {label} to {value}."
    except Exception as e:
        return False, f"Error saving preassignment: {e}"


def delete_preassignments(track_name, staff_name=None):
    """
    Remove a cycle's preassignments, or just one staff member's.

    Returns:
        tuple: (success, rows deleted)
    """
    cycle = resolve_track_name(track_name)
    if not cycle or not _table_exists():
        return False, 0
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        if staff_name:
            cursor.execute("DELETE FROM track_preassignments WHERE track_name = ? "
                           "AND staff_name = ? COLLATE NOCASE",
                           (cycle, str(staff_name).strip()))
        else:
            cursor.execute("DELETE FROM track_preassignments WHERE track_name = ?",
                           (cycle,))
        deleted = cursor.rowcount
        conn.commit()
        return True, deleted
    except Exception as e:
        print(f"Error deleting preassignments: {e}")
        return False, 0


def copy_preassignments(from_track, to_track, overwrite=False):
    """
    Copy a cycle's preassignments to another cycle — the usual way to start a new bid
    cycle from the last one's standing commitments.

    Args:
        overwrite (bool): replace the target's existing preassignments. When False, the
            copy is refused if the target already has any.

    Returns:
        tuple: (success, message)
    """
    source = str(from_track or '').strip()
    target = str(to_track or '').strip()
    if not source or not target:
        return False, "Both a source and a target track cycle are required."
    if source == target:
        return False, "Source and target track cycles are the same."

    initialize_preassignment_tables()
    existing = get_preassignments(target)
    if existing and not overwrite:
        return False, (f"{target} already has preassignments for {len(existing)} staff "
                       "member(s). Choose to overwrite if you want to replace them.")

    source_rows = get_preassignments(source)
    if not source_rows:
        return False, f"{source} has no preassignments to copy."

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        now = _now()
        if existing:
            cursor.execute("DELETE FROM track_preassignments WHERE track_name = ?",
                           (target,))
        copied = 0
        for staff_name, days in source_rows.items():
            for day, activity in days.items():
                cursor.execute("""
                    INSERT INTO track_preassignments
                    (track_name, staff_name, day, activity, created_date, modified_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (target, staff_name, day, activity, now, now))
                copied += 1
        conn.commit()
        return True, (f"Copied {copied} preassignment(s) for {len(source_rows)} staff "
                      f"member(s) from {source} to {target}.")
    except Exception as e:
        return False, f"Error copying preassignments: {e}"


def get_preassignment_summary():
    """
    Per-cycle counts, for the admin overview.

    Returns:
        list: dicts with track_name, staff_count, day_count.
    """
    if not _table_exists():
        return []
    try:
        cursor = _get_conn().cursor()
        cursor.execute("""
            SELECT track_name, COUNT(DISTINCT staff_name), COUNT(*)
            FROM track_preassignments GROUP BY track_name ORDER BY track_name
        """)
        return [{'track_name': row[0], 'staff_count': row[1], 'day_count': row[2]}
                for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error summarizing preassignments: {e}")
        return []


def import_preassignments_from_excel(path, track_name, overwrite=False,
                                     dry_run=False):
    """
    One-time import of a Preassignments.xlsx file into a cycle.

    Returns:
        dict: report with keys staff_imported, days_imported, unknown_days,
        unknown_staff, errors, dry_run.
    """
    import os

    report = {
        'staff_imported': 0,
        'days_imported': 0,
        'unknown_days': [],
        'unknown_staff': [],
        'errors': [],
        'dry_run': bool(dry_run),
    }

    cycle = resolve_track_name(track_name)
    if not cycle:
        report['errors'].append("No track cycle selected.")
        return report
    if not os.path.exists(path):
        report['errors'].append(f"Preassignments file not found: {path}")
        return report

    try:
        df = pd.read_excel(path)
    except Exception as e:
        report['errors'].append(f"Could not read {path}: {e}")
        return report

    staff_col = next((col for col in df.columns
                      if isinstance(col, str) and 'name' in col.lower()),
                     df.columns[0])
    day_columns = [col for col in df.columns if col != staff_col]

    known_days = set(PATTERN_DAYS)
    report['unknown_days'] = [str(col) for col in day_columns if str(col) not in known_days]

    try:
        from .staff_database import get_staff_names
        roster = {name.lower() for name in get_staff_names(include_inactive=True)}
    except Exception:
        roster = set()

    rows = {}
    for _, row in df.iterrows():
        name = row[staff_col]
        if pd.isna(name):
            continue
        name = str(name).strip()
        if not name or name.upper() == 'STAFF NAME':
            continue
        if roster and name.lower() not in roster:
            report['unknown_staff'].append(name)

        staff_days = {}
        for col in day_columns:
            value = row[col]
            if pd.isna(value):
                continue
            text = str(value).strip()
            if text:
                staff_days[str(col)] = text
        # First row wins for a duplicated staff name, matching the old loader.
        if staff_days and name not in rows:
            rows[name] = staff_days

    report['staff_imported'] = len(rows)
    report['days_imported'] = sum(len(days) for days in rows.values())

    if dry_run:
        return report

    initialize_preassignment_tables()
    existing = get_preassignments(cycle)
    if existing and not overwrite:
        report['errors'].append(
            f"{cycle} already has preassignments for {len(existing)} staff member(s). "
            "Choose to overwrite if you want to replace them.")
        report['staff_imported'] = 0
        report['days_imported'] = 0
        return report

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        now = _now()
        if existing:
            cursor.execute("DELETE FROM track_preassignments WHERE track_name = ?",
                           (cycle,))
        for staff_name, days in rows.items():
            for day, activity in days.items():
                cursor.execute("""
                    INSERT INTO track_preassignments
                    (track_name, staff_name, day, activity, created_date, modified_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (cycle, staff_name, day, activity, now, now))
        conn.commit()
    except Exception as e:
        report['errors'].append(f"Error saving imported preassignments: {e}")

    return report
