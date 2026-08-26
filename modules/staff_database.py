# modules/staff_database.py
"""
Staff Database — the single source of truth for the staff roster and the staff
attributes the rest of CrewOps360 depends on.

Before this module, staff identity and attributes were read out of Excel uploads on
every page load:

    - "upload files/Preferences v6.xlsx" -> STAFF NAME, ROLE, No Matrix, Seniority
    - "upload files/Requirements.xlsx" -> SHIFTS PER PAY PERIOD, NIGHT MINIMUM,
      WEEKEND MINIMUM, WEEKEND GROUP, EMAIL
    - "training/upload/FY26 Education Classes Roster.xlsx" (Class_Enrollment sheet)
      -> STAFF NAME, Role, MGMT, DUAL, Educator AT

All three are now imported once (see modules/staff_import.py) into the `staff` table and
read from the database from then on. The Education Classes Roster is still the source
of *classes and enrollment*, but no longer of staff attributes.

Attribute model
---------------
`role` is the base role from the roster: NURSE, MEDIC, COMMS, CCEMT, ATP or AMT.
`is_dual` is a separate flag (a nurse who also works as a medic), matching the roster's
DUAL column. Preferences v6 collapsed those two into one ROLE column of
nurse/medic/dual — that collapsed value is what most of the track code wants, so it is
reproduced here as the *clinical role*:

    clinical_role = 'dual' if is_dual else role.lower()      # nurse / medic / dual
    effective_role = 'nurse' if clinical_role != 'medic'     # staffing bucket

Names are the join key across every other table (tracks, bids, enrollments, …), so
renaming a staff member is a first-class operation: rename_staff() updates the roster
row and every staff-name reference in the database in one transaction, and records what
it touched in `staff_name_history`.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime

import pandas as pd
import pytz

from .day_pattern import PATTERN_LENGTH as PATTERN_DAY_COUNT

_eastern_tz = pytz.timezone('America/New_York')

DEFAULT_DB_PATH = 'data/medflight_tracks.db'

# Base roles as spelled in the Education Classes Roster's Role column.
STAFF_ROLES = ['NURSE', 'MEDIC', 'COMMS', 'CCEMT', 'ATP', 'AMT']

# Placeholder for a staff member imported without a role — someone the app already
# references (they hold a track) who isn't on the education roster. Never guessed at:
# the Staff Database admin page lists these for an admin to resolve.
UNASSIGNED_ROLE = 'UNASSIGNED'

# Roles that hold a clinical track and bid on shifts. Everyone else is on the roster
# for training/enrollment purposes only.
CLINICAL_ROLES = ['NURSE', 'MEDIC']

# Weekend groups as spelled in Requirements.xlsx's WEEKEND GROUP column.
WEEKEND_GROUPS = ['A', 'B', 'C', 'D', 'E']

# Every (table, column) pair in the database that stores a staff name as free text.
# Discovered dynamically against the live schema in _staff_reference_columns() so a new
# table picks up rename support automatically; this list only says which *column names*
# hold a staff name.
STAFF_NAME_COLUMNS = [
    'staff_name',
    'requester_name',
    'other_member_name',
    'submitted_by',
    'next_staff',
]

# Tables owned by this module, excluded from rename propagation (handled explicitly).
_OWN_TABLES = {'staff', 'staff_name_history', 'staff_audit_log'}


# ──────────────────────────────────────────────
# Connection handling
# ──────────────────────────────────────────────

# Set to a path to point this module at a different database (tests, one-off imports).
# When None, the app-wide connection from modules.db_utils is used so the staff tables
# share a connection — and therefore a transaction scope — with everything else.
_db_path_override = None
_own_connections = {}

try:  # pragma: no cover - depends on streamlit being importable
    from .db_utils import get_db_connection as _app_get_db_connection
except Exception:  # pragma: no cover
    _app_get_db_connection = None


def set_db_path(path):
    """Point this module at a specific database file (or None to use the app's)."""
    global _db_path_override, _own_connections
    for conn in _own_connections.values():
        try:
            conn.close()
        except Exception:
            pass
    _own_connections = {}
    _db_path_override = path
    invalidate_cache()


def get_db_path():
    """Path of the database this module reads and writes."""
    return _db_path_override or DEFAULT_DB_PATH


def _get_conn():
    """Connection to the staff database."""
    if _db_path_override is None and _app_get_db_connection is not None:
        return _app_get_db_connection()

    thread_id = threading.get_ident()
    if thread_id in _own_connections:
        return _own_connections[thread_id]

    path = get_db_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path)
    _own_connections[thread_id] = conn
    return conn


def _now():
    return datetime.now(_eastern_tz).strftime('%Y-%m-%d %H:%M:%S')


# ──────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────

def initialize_staff_tables():
    """
    Create the staff roster tables if they don't exist. Safe to call repeatedly.

    Returns:
        bool: True on success.
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        # The roster itself. staff_name is the key other tables join on, so it is
        # UNIQUE and NOCASE — "bell" and "Bell" must not be two people.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            role TEXT NOT NULL,
            is_management INTEGER NOT NULL DEFAULT 0,
            is_dual INTEGER NOT NULL DEFAULT 0,
            is_educator_at INTEGER NOT NULL DEFAULT 0,
            no_matrix INTEGER NOT NULL DEFAULT 0,
            seniority INTEGER,
            shifts_per_pay_period INTEGER,
            night_minimum INTEGER,
            weekend_minimum INTEGER,
            weekend_group TEXT,
            email TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL
        )
        ''')

        # Requirements columns arrived after the first roster import, so add them to an
        # existing staff table. NULL is meaningful for every one of them: a blank
        # shifts-per-pay-period is what marks management as non-bidding, and is not the
        # same as 0 (probationary staff who work no track shifts).
        cursor.execute("PRAGMA table_info(staff)")
        staff_columns = [row[1] for row in cursor.fetchall()]
        for column, definition in (
            ('shifts_per_pay_period', 'INTEGER'),
            ('night_minimum', 'INTEGER'),
            ('weekend_minimum', 'INTEGER'),
            ('weekend_group', 'TEXT'),
            ('email', 'TEXT'),
        ):
            if column not in staff_columns:
                cursor.execute(f"ALTER TABLE staff ADD COLUMN {column} {definition}")

        # Every add/update/delete/activate, with a JSON diff of what changed.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            action TEXT NOT NULL,
            changes TEXT,
            changed_by TEXT,
            changed_date TEXT NOT NULL
        )
        ''')

        # Name changes get their own table because they are the one edit that rewrites
        # rows outside the staff table — this records which ones, for auditing a
        # married-name change months later.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff_name_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER,
            old_name TEXT NOT NULL,
            new_name TEXT NOT NULL,
            rows_updated TEXT,
            changed_by TEXT,
            changed_date TEXT NOT NULL
        )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_staff_active ON staff(is_active)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_staff_role ON staff(role)')

        conn.commit()
        invalidate_cache()
        return True

    except Exception as e:
        print(f"Error initializing staff tables: {e}")
        return False


def staff_table_exists():
    """True if the staff table has been created."""
    try:
        cursor = _get_conn().cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='staff'")
        return cursor.fetchone() is not None
    except Exception:
        return False


def staff_count(include_inactive=True):
    """Number of staff on the roster, 0 if the table doesn't exist yet."""
    if not staff_table_exists():
        return 0
    try:
        cursor = _get_conn().cursor()
        if include_inactive:
            cursor.execute("SELECT COUNT(*) FROM staff")
        else:
            cursor.execute("SELECT COUNT(*) FROM staff WHERE is_active = 1")
        return cursor.fetchone()[0]
    except Exception:
        return 0


# ──────────────────────────────────────────────
# Value normalization
# ──────────────────────────────────────────────

def canonical_role(role):
    """
    Normalize any spelling of a role to its canonical uppercase form.

    Accepts the roster's spellings (NURSE/MEDIC/COMMS/CCEMT/ATP/AMT), the
    Preferences v6 spellings (nurse/medic/dual) and common variants (RN -> NURSE,
    PARAMEDIC -> MEDIC). 'DUAL' maps to NURSE, since dual is a flag, not a base role.

    Returns:
        str: canonical role, or '' when nothing recognizable was passed.
    """
    if role is None:
        return ''
    text = str(role).strip().upper()
    if not text or text in ('NAN', 'NONE'):
        return ''
    aliases = {
        'RN': 'NURSE',
        'NURSE': 'NURSE',
        'DUAL': 'NURSE',
        'PARAMEDIC': 'MEDIC',
        'MEDIC': 'MEDIC',
        'COMM': 'COMMS',
        'COMMS': 'COMMS',
        'CCEMT': 'CCEMT',
        'CCEMTP': 'CCEMT',
        'ATP': 'ATP',
        'PILOT': 'ATP',
        'AMT': 'AMT',
        'MECHANIC': 'AMT',
        UNASSIGNED_ROLE: UNASSIGNED_ROLE,
    }
    return aliases.get(text, text)


def to_flag(value):
    """
    Coerce a checkbox-ish value (Excel True/1/'Yes'/'X', blank, NaN) to 0 or 1.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        try:
            if pd.isna(value):
                return 0
        except (TypeError, ValueError):
            pass
        return 1 if value else 0
    text = str(value).strip().upper()
    if text in ('', 'NAN', 'NONE', 'NO', 'N', 'FALSE', 'F', '0'):
        return 0
    if text in ('YES', 'Y', 'TRUE', 'T', 'X', '✓', '1'):
        return 1
    return 0


def to_seniority(value):
    """Coerce a seniority value to int, or None when blank/unparseable."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.upper() in ('NAN', 'NONE'):
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def to_optional_int(value):
    """
    Coerce a value to int, or None when blank.

    Used for the requirements fields, where blank and 0 mean different things: a blank
    SHIFTS PER PAY PERIOD marks management as non-bidding, while 0 is a real requirement
    for probationary staff who work no track shifts.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.upper() in ('NAN', 'NONE'):
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def to_weekend_group(value):
    """Normalize a weekend group to a single letter A-E, or None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip().upper()
    return text if text in WEEKEND_GROUPS else None


def to_email(value):
    """Trim an email address, or None when blank."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def clean_name(name):
    """Trim a staff name the way every reader of these files does."""
    if name is None:
        return ''
    try:
        if pd.isna(name):
            return ''
    except (TypeError, ValueError):
        pass
    return str(name).strip()


def clinical_role_of(record):
    """
    The nurse/medic/dual value Preferences v6 used to supply, derived from a staff
    record's base role and dual flag.
    """
    if not record:
        return ''
    if record.get('is_dual'):
        return 'dual'
    role = str(record.get('role') or '').strip().lower()
    return role


def effective_role_of(record):
    """
    Staffing bucket for a staff record: 'medic' for medics, 'nurse' for everyone else
    (dual providers count as nurses) — same rule as modules.role_migration.
    """
    return 'medic' if clinical_role_of(record) == 'medic' else 'nurse'


# ──────────────────────────────────────────────
# Read cache
# ──────────────────────────────────────────────
# The roster is small (a few hundred rows) but read in tight loops — per staff member
# per class date in the training views. It is cached in-process and invalidated on
# every mutation here, plus whenever the database file changes underneath us (a restore
# from backup, or another process writing).

_cache = None
_cache_stamp = None


def invalidate_cache():
    """Drop the in-process roster cache."""
    global _cache, _cache_stamp
    _cache = None
    _cache_stamp = None


def _db_stamp():
    try:
        stat = os.stat(get_db_path())
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _select_staff_rows():
    """Every staff row, in the column order _roster() unpacks."""
    cursor = _get_conn().cursor()
    cursor.execute('''
        SELECT id, staff_name, role, is_management, is_dual, is_educator_at,
               no_matrix, seniority, is_active, notes, created_date, modified_date,
               shifts_per_pay_period, night_minimum, weekend_minimum,
               weekend_group, email
        FROM staff
    ''')
    return cursor.fetchall()


def _roster():
    """
    {staff_name: record} for the whole roster, cached. Keys keep their stored casing;
    lookups go through _lookup() which is case-insensitive.
    """
    global _cache, _cache_stamp

    stamp = _db_stamp()
    if _cache is not None and stamp == _cache_stamp:
        return _cache

    roster = {}
    if staff_table_exists():
        try:
            try:
                rows = _select_staff_rows()
            except sqlite3.OperationalError as e:
                # A staff table created by an older version of this module is missing the
                # requirements columns. Run the migration and read again rather than
                # returning an empty roster.
                if 'no such column' not in str(e).lower():
                    raise
                initialize_staff_tables()
                rows = _select_staff_rows()

            for row in rows:
                record = {
                    'id': row[0],
                    'staff_name': row[1],
                    'role': row[2],
                    'is_management': bool(row[3]),
                    'is_dual': bool(row[4]),
                    'is_educator_at': bool(row[5]),
                    'no_matrix': bool(row[6]),
                    'seniority': row[7],
                    'is_active': bool(row[8]),
                    'notes': row[9],
                    'created_date': row[10],
                    'modified_date': row[11],
                    'shifts_per_pay_period': row[12],
                    'night_minimum': row[13],
                    'weekend_minimum': row[14],
                    'weekend_group': row[15],
                    'email': row[16],
                }
                record['clinical_role'] = clinical_role_of(record)
                record['effective_role'] = effective_role_of(record)
                roster[record['staff_name']] = record
        except Exception as e:
            print(f"Error loading staff roster: {e}")
            return {}

    _cache = roster
    _cache_stamp = stamp
    return roster


def _lookup(staff_name):
    """Case-insensitive record lookup, or None."""
    name = clean_name(staff_name)
    if not name:
        return None
    roster = _roster()
    record = roster.get(name)
    if record is not None:
        return record
    lowered = name.lower()
    for key, value in roster.items():
        if key.lower() == lowered:
            return value
    return None


# ──────────────────────────────────────────────
# Queries
# ──────────────────────────────────────────────

def get_staff(staff_name):
    """
    Full record for one staff member.

    Returns:
        dict or None: keys staff_name, role, clinical_role, effective_role,
        is_management, is_dual, is_educator_at, no_matrix, seniority, is_active, notes.
    """
    record = _lookup(staff_name)
    return dict(record) if record else None


def get_all_staff(include_inactive=False, roles=None, management_only=False,
                  sort_by='staff_name'):
    """
    The roster as a list of records.

    Args:
        include_inactive (bool): include staff marked inactive.
        roles (list, optional): keep only these base roles (any spelling).
        management_only (bool): keep only management staff.
        sort_by (str): 'staff_name', 'role' or 'seniority'.
    """
    records = [dict(r) for r in _roster().values()]

    if not include_inactive:
        records = [r for r in records if r['is_active']]
    if roles:
        wanted = {canonical_role(r) for r in roles}
        records = [r for r in records if canonical_role(r['role']) in wanted]
    if management_only:
        records = [r for r in records if r['is_management']]

    if sort_by == 'seniority':
        # Unranked staff sort last rather than first.
        records.sort(key=lambda r: (r['seniority'] is None, r['seniority'] or 0,
                                    r['staff_name'].lower()))
    elif sort_by == 'role':
        records.sort(key=lambda r: (r['role'], r['staff_name'].lower()))
    else:
        records.sort(key=lambda r: r['staff_name'].lower())

    return records


def get_staff_names(include_inactive=False, roles=None, clinical_only=False):
    """
    Sorted list of staff names.

    Args:
        clinical_only (bool): only NURSE/MEDIC staff (those who hold a track).
    """
    if clinical_only:
        roles = CLINICAL_ROLES
    return [r['staff_name'] for r in get_all_staff(include_inactive=include_inactive,
                                                   roles=roles)]


def staff_exists(staff_name, include_inactive=True):
    """True if the name is on the roster."""
    record = _lookup(staff_name)
    if record is None:
        return False
    return bool(record['is_active']) or include_inactive


def get_role(staff_name, default=''):
    """Base role (NURSE/MEDIC/COMMS/CCEMT/ATP/AMT)."""
    record = _lookup(staff_name)
    return record['role'] if record else default


def get_clinical_role(staff_name, default=''):
    """nurse / medic / dual — the value Preferences v6's ROLE column held."""
    record = _lookup(staff_name)
    return record['clinical_role'] if record else default


def get_effective_role(staff_name, default='nurse'):
    """Staffing bucket: nurse or medic (dual counts as nurse)."""
    record = _lookup(staff_name)
    return record['effective_role'] if record else default


def is_management(staff_name, default=False):
    """True if the staff member is management (roster MGMT column)."""
    record = _lookup(staff_name)
    return record['is_management'] if record else default


def is_dual(staff_name, default=False):
    """True if the staff member is a dual provider (roster DUAL column)."""
    record = _lookup(staff_name)
    return record['is_dual'] if record else default


def is_educator_at(staff_name, default=False):
    """
    True if the staff member may sign up to teach (roster 'Educator AT' column).

    Note the default: callers that used to read the spreadsheet defaulted to *allowing*
    educator signup when the column or the staff row was missing. Pass default=True to
    keep that behavior for an unknown name.
    """
    record = _lookup(staff_name)
    return record['is_educator_at'] if record else default


def get_no_matrix(staff_name, default=False):
    """True if the staff member is flagged No Matrix (Preferences v6)."""
    record = _lookup(staff_name)
    return record['no_matrix'] if record else default


def get_seniority(staff_name, default=None):
    """Seniority rank (1 = most senior), or default when unranked/unknown."""
    record = _lookup(staff_name)
    if not record or record['seniority'] is None:
        return default
    return record['seniority']


def get_shifts_per_pay_period(staff_name, default=None):
    """
    Required shifts per 14-day pay period, or default when not on file.

    None/not-on-file is meaningful: it marks management and other non-bidding staff, and
    is what the bid roster uses to skip them.
    """
    record = _lookup(staff_name)
    if not record or record['shifts_per_pay_period'] is None:
        return default
    return record['shifts_per_pay_period']


def get_night_minimum(staff_name, default=None):
    """Minimum night shifts per cycle, or default when not on file."""
    record = _lookup(staff_name)
    if not record or record['night_minimum'] is None:
        return default
    return record['night_minimum']


def get_weekend_minimum(staff_name, default=None):
    """Minimum weekend shifts per cycle, or default when not on file."""
    record = _lookup(staff_name)
    if not record or record['weekend_minimum'] is None:
        return default
    return record['weekend_minimum']


def get_weekend_group(staff_name, default=None):
    """Weekend group (A-E), or default when not assigned."""
    record = _lookup(staff_name)
    if not record or not record['weekend_group']:
        return default
    return record['weekend_group']


def get_email(staff_name, default=None):
    """Email address, or default when not on file."""
    record = _lookup(staff_name)
    if not record or not record['email']:
        return default
    return record['email']


def _live_track_cycles():
    """
    The track cycles whose tracks are actually being looked at right now: the active
    one, plus whichever has bidding or the needs-swap window open.

    All three matter, and they are routinely different cycles — FY26 can still be the
    active operational cycle while FY27 is the one being bid and swapped. Scoping to
    the active cycle alone would mean a relaxation granted on the cycle being swapped
    never applied to the tracks it was granted for.
    """
    from .db_utils import (get_active_track_config, get_bidding_track_config,
                           get_needs_swap_track_config)

    names = []
    for getter in (get_active_track_config, get_bidding_track_config,
                   get_needs_swap_track_config):
        config = getter()
        name = (config or {}).get('track_name')
        if name and name not in names:
            names.append(name)
    return names


def active_cycle_minimum_overrides():
    """
    {staff_name: {'night_minimum': int|None, 'weekend_minimum': int|None}} across the
    live track cycles — night/weekend minimums an admin relaxed by approving a Needs
    Swap offer that moved someone off a night or a weekend to cover a shortfall.

    Applied wherever this module hands out requirements, so a track approved under a
    relaxed minimum reads as valid everywhere in the app — the Admin Track Editor, the
    PDF and email summaries included — rather than only in the Needs Swap views that
    granted it. The relaxation lives on the cycle, not the staff record, so it lapses
    once that cycle stops being live and the original figure applies again.

    Where two live cycles both relax the same person, the lower figure wins: a track
    that satisfies the stricter cycle satisfies the looser one anyway, and refusing the
    relaxation is what puts a deliberately approved track back into a failing state.

    Returns {} when nothing is relaxed, or when the track tables aren't reachable.
    """
    try:
        from .db_utils import get_requirement_overrides

        merged = {}
        for track_name in _live_track_cycles():
            for name, entry in get_requirement_overrides(track_name).items():
                current = merged.setdefault(name, {'night_minimum': None, 'weekend_minimum': None})
                for field in ('night_minimum', 'weekend_minimum'):
                    value = entry.get(field)
                    if value is not None and (current[field] is None or value < current[field]):
                        current[field] = value
        return merged
    except Exception as e:
        print(f"Error loading minimum overrides: {e}")
        return {}


def _with_override(record, overrides, field):
    """A staff record's minimum, or the active cycle's relaxed figure when there is one."""
    relaxed = overrides.get(record['staff_name'], {}).get(field)
    return record[field] if relaxed is None else relaxed


def get_requirements_map(include_inactive=False):
    """
    {staff_name: {shifts_per_pay_period, night_minimum, weekend_minimum, weekend_group,
    email}} — the mapping the bidding code builds its roster and notifications from.

    Night and weekend minimums carry the active cycle's relaxations, if any (see
    active_cycle_minimum_overrides).
    """
    overrides = active_cycle_minimum_overrides()
    return {
        record['staff_name']: {
            'shifts_per_pay_period': record['shifts_per_pay_period'],
            'night_minimum': _with_override(record, overrides, 'night_minimum'),
            'weekend_minimum': _with_override(record, overrides, 'weekend_minimum'),
            'weekend_group': record['weekend_group'],
            'email': record['email'],
        }
        for record in get_all_staff(include_inactive=include_inactive)
    }


def get_role_mapping(include_inactive=False, clinical_only=False):
    """{staff_name: clinical_role} — the nurse/medic/dual mapping the track code uses."""
    return {r['staff_name']: r['clinical_role']
            for r in get_all_staff(include_inactive=include_inactive,
                                   roles=CLINICAL_ROLES if clinical_only else None)}


def get_base_role_mapping(include_inactive=False):
    """{staff_name: base role} — NURSE/MEDIC/COMMS/CCEMT/ATP/AMT, as the roster spells it."""
    return {r['staff_name']: r['role']
            for r in get_all_staff(include_inactive=include_inactive)}


def get_seniority_mapping(include_inactive=False):
    """{staff_name: seniority} for staff who have a rank."""
    return {r['staff_name']: r['seniority']
            for r in get_all_staff(include_inactive=include_inactive)
            if r['seniority'] is not None}


def get_no_matrix_mapping(include_inactive=False):
    """{staff_name: bool} for the No Matrix flag."""
    return {r['staff_name']: r['no_matrix']
            for r in get_all_staff(include_inactive=include_inactive)}


def get_management_names(include_inactive=False):
    """Names of management staff."""
    return [r['staff_name'] for r in get_all_staff(include_inactive=include_inactive,
                                                   management_only=True)]


def get_educator_names(include_inactive=False):
    """Names of staff authorized to sign up as educators."""
    return [r['staff_name'] for r in get_all_staff(include_inactive=include_inactive)
            if r['is_educator_at']]


def get_roster_issues(include_inactive=False):
    """
    Roster rows that need an admin's attention.

    Returns:
        dict: with keys 'unassigned_role' (imported without a role),
        'missing_seniority' (clinical staff with no rank, which leaves them out of bid
        ordering) and 'duplicate_seniority' ({rank: [names]}).
    """
    records = get_all_staff(include_inactive=include_inactive)

    by_rank = {}
    for record in records:
        if record['seniority'] is not None:
            by_rank.setdefault(record['seniority'], []).append(record['staff_name'])

    def bids_on_tracks(record):
        # Staff with shift requirements on file are the ones who bid; management and
        # other non-bidding staff have none.
        return (canonical_role(record['role']) in CLINICAL_ROLES
                and record['shifts_per_pay_period'] is not None)

    return {
        'unassigned_role': [r['staff_name'] for r in records
                            if canonical_role(r['role']) == UNASSIGNED_ROLE],
        'missing_seniority': [r['staff_name'] for r in records
                              if canonical_role(r['role']) in CLINICAL_ROLES
                              and r['seniority'] is None],
        'duplicate_seniority': {rank: names for rank, names in sorted(by_rank.items())
                                if len(names) > 1},
        # A blank shifts-per-pay-period is how management is marked as non-bidding, so
        # only non-management clinical staff missing it are a problem — they would drop
        # out of the bid roster without anyone noticing.
        'missing_requirements': [r['staff_name'] for r in records
                                 if canonical_role(r['role']) in CLINICAL_ROLES
                                 and not r['is_management']
                                 and r['shifts_per_pay_period'] is None],
        # Bid progression emails the next staff member in rank when a bid is submitted,
        # which silently can't happen without an address on file.
        'missing_email': [r['staff_name'] for r in records
                          if bids_on_tracks(r) and not r['email']],
    }


def get_staff_dataframe(include_inactive=True):
    """The roster as a DataFrame, for admin tables and exports."""
    records = get_all_staff(include_inactive=include_inactive)
    columns = ['staff_name', 'role', 'clinical_role', 'is_management', 'is_dual',
               'is_educator_at', 'no_matrix', 'seniority', 'shifts_per_pay_period',
               'night_minimum', 'weekend_minimum', 'weekend_group', 'email',
               'is_active', 'notes', 'created_date', 'modified_date']
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(records)[columns]


# ──────────────────────────────────────────────
# Requirements compatibility
# ──────────────────────────────────────────────

# Column order of Requirements.xlsx. Several validators read this frame positionally
# (row.iloc[4] for the weekend group, len(columns) >= 5 checks), so the order matters as
# much as the names.
REQUIREMENTS_COLUMNS = ['STAFF NAME', 'SHIFTS PER PAY PERIOD', 'NIGHT MINIMUM',
                        'WEEKEND MINIMUM', 'WEEKEND GROUP', 'EMAIL']


def build_requirements_df(include_inactive=False, clinical_only=True):
    """
    Build the DataFrame the track code used to get from Requirements.xlsx, from the
    staff table instead: same columns, same order, same blank-means-non-bidding
    semantics. Night and weekend minimums carry the active cycle's relaxations, if
    any (see active_cycle_minimum_overrides).

    Args:
        include_inactive (bool): include staff marked inactive on the roster.
        clinical_only (bool): only NURSE/MEDIC staff, matching what the spreadsheet
            held. Turn off to get the whole roster.

    Returns:
        DataFrame: columns per REQUIREMENTS_COLUMNS. Empty (but correctly shaped) when
        the roster has not been imported yet.
    """
    records = get_all_staff(include_inactive=include_inactive,
                            roles=CLINICAL_ROLES if clinical_only else None,
                            sort_by='seniority')
    if not records:
        return pd.DataFrame(columns=REQUIREMENTS_COLUMNS)

    overrides = active_cycle_minimum_overrides()
    rows = [{
        'STAFF NAME': record['staff_name'],
        'SHIFTS PER PAY PERIOD': record['shifts_per_pay_period'],
        'NIGHT MINIMUM': _with_override(record, overrides, 'night_minimum'),
        'WEEKEND MINIMUM': _with_override(record, overrides, 'weekend_minimum'),
        'WEEKEND GROUP': record['weekend_group'],
        'EMAIL': record['email'],
    } for record in records]

    return pd.DataFrame(rows, columns=REQUIREMENTS_COLUMNS)


# ──────────────────────────────────────────────
# Preferences v6 compatibility
# ──────────────────────────────────────────────

# Column order of Preferences v6.xlsx, reproduced so build_preferences_df() is a
# drop-in replacement for pd.read_excel() on that file.
_PREF_SHIFT_COLUMNS = ['D7B', 'GR', 'D11B', 'FW', 'D9L', 'LG', 'D7P', 'PG', 'D11M',
                       'MG', 'N7B', 'NG', 'N9L', 'N7P', 'NP']
PREFERENCES_COLUMNS = (['STAFF NAME', 'ROLE', 'No Matrix', 'Seniority',
                        'Reduced Rest OK'] + _PREF_SHIFT_COLUMNS + ['N to D Flex'])


def _shift_preference_rows(conn):
    """{staff_name: {shift_name: score}} from the user_preferences table."""
    result = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences'")
        if not cursor.fetchone():
            return result
        cursor.execute("""
            SELECT staff_name, shift_name, preference_score
            FROM user_preferences WHERE is_active = 1
        """)
        for staff_name, shift_name, score in cursor.fetchall():
            result.setdefault(clean_name(staff_name), {})[str(shift_name).strip()] = score
    except Exception as e:
        print(f"Error reading shift preferences: {e}")
    return result


def _boolean_preference_rows(conn):
    """{staff_name: {preference_name: value}} from the user_boolean_preferences table."""
    result = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_boolean_preferences'")
        if not cursor.fetchone():
            return result
        cursor.execute("""
            SELECT staff_name, preference_name, preference_value
            FROM user_boolean_preferences WHERE is_active = 1
        """)
        for staff_name, pref_name, value in cursor.fetchall():
            result.setdefault(clean_name(staff_name), {})[str(pref_name).strip()] = value
    except Exception as e:
        print(f"Error reading boolean preferences: {e}")
    return result


def build_preferences_df(include_inactive=False, clinical_only=True):
    """
    Build the DataFrame the track code used to get from Preferences v6.xlsx, from the
    database instead: one row per staff member, with the same column names and order.

    ROLE/No Matrix/Seniority come from the staff table. Reduced Rest OK, N to D Flex
    and the per-base shift scores come from the preference tables staff maintain in the
    app (user_preferences / user_boolean_preferences), defaulting to 0 / "No" where a
    staff member has never saved preferences — the same values the editor would show.

    Args:
        include_inactive (bool): include staff marked inactive on the roster.
        clinical_only (bool): only NURSE/MEDIC staff, matching what the spreadsheet
            held. Turn off to get the whole roster.

    Returns:
        DataFrame: columns per PREFERENCES_COLUMNS. Empty (but correctly shaped) when
        the roster has not been imported yet.
    """
    records = get_all_staff(include_inactive=include_inactive,
                            roles=CLINICAL_ROLES if clinical_only else None,
                            sort_by='seniority')
    if not records:
        return pd.DataFrame(columns=PREFERENCES_COLUMNS)

    conn = _get_conn()
    shift_prefs = _shift_preference_rows(conn)
    bool_prefs = _boolean_preference_rows(conn)

    rows = []
    for record in records:
        name = record['staff_name']
        staff_shift_prefs = shift_prefs.get(name, {})
        staff_bool_prefs = bool_prefs.get(name, {})

        reduced_rest = staff_bool_prefs.get('Reduced Rest OK', 0)
        try:
            reduced_rest = int(reduced_rest)
        except (TypeError, ValueError):
            reduced_rest = 1 if to_flag(reduced_rest) else 0

        n_to_d_flex = staff_bool_prefs.get('N to D Flex', 'No')
        if n_to_d_flex is None:
            n_to_d_flex = 'No'

        row = {
            'STAFF NAME': name,
            'ROLE': record['clinical_role'],
            'No Matrix': 1 if record['no_matrix'] else 0,
            'Seniority': record['seniority'],
            'Reduced Rest OK': reduced_rest,
            'N to D Flex': str(n_to_d_flex),
        }
        for shift in _PREF_SHIFT_COLUMNS:
            value = staff_shift_prefs.get(shift, 0)
            try:
                row[shift] = int(value)
            except (TypeError, ValueError):
                row[shift] = 0
        rows.append(row)

    return pd.DataFrame(rows, columns=PREFERENCES_COLUMNS)


# ──────────────────────────────────────────────
# Mutations
# ──────────────────────────────────────────────

_EDITABLE_FIELDS = ['role', 'is_management', 'is_dual', 'is_educator_at', 'no_matrix',
                    'seniority', 'shifts_per_pay_period', 'night_minimum',
                    'weekend_minimum', 'weekend_group', 'email', 'is_active', 'notes']

# Fields where NULL is a meaningful value, so an update passing None clears them.
_NULLABLE_INT_FIELDS = ['shifts_per_pay_period', 'night_minimum', 'weekend_minimum']

_BOOLEAN_FIELDS = ['is_management', 'is_dual', 'is_educator_at', 'no_matrix', 'is_active']


def _log_audit(cursor, staff_name, action, changes=None, changed_by=None):
    cursor.execute('''
        INSERT INTO staff_audit_log (staff_name, action, changes, changed_by, changed_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (staff_name, action, json.dumps(changes) if changes else None,
          changed_by or 'admin', _now()))


def validate_staff_fields(staff_name, role, seniority=None, exclude_name=None,
                          shifts_per_pay_period=None, night_minimum=None,
                          weekend_minimum=None, weekend_group=None, email=None):
    """
    Check a proposed roster row.

    Args:
        exclude_name (str, optional): the staff member being edited, so their own row
            doesn't count as a conflict.

    Returns:
        list: human-readable problems; empty when the row is valid.
    """
    errors = []
    name = clean_name(staff_name)
    if not name:
        errors.append("Staff name is required.")
    elif len(name) > 100:
        errors.append("Staff name is too long (max 100 characters).")

    canonical = canonical_role(role)
    if not canonical:
        errors.append("Role is required.")
    elif canonical not in STAFF_ROLES + [UNASSIGNED_ROLE]:
        errors.append(f"Unknown role '{role}'. Expected one of: {', '.join(STAFF_ROLES)}.")

    exclude = clean_name(exclude_name).lower() if exclude_name else None

    if name:
        existing = _lookup(name)
        if existing and existing['staff_name'].lower() != exclude:
            errors.append(f"'{existing['staff_name']}' is already on the roster.")

    rank = to_seniority(seniority)
    if rank is not None:
        if rank < 1:
            errors.append("Seniority must be 1 or greater (1 = most senior).")
        else:
            for record in _roster().values():
                if record['seniority'] == rank and record['staff_name'].lower() != exclude:
                    errors.append(
                        f"Seniority {rank} is already assigned to {record['staff_name']}. "
                        "Seniority ranks must be unique."
                    )
                    break

    for label, value, ceiling in (
        ('Shifts per pay period', shifts_per_pay_period, 14),
        ('Night minimum', night_minimum, PATTERN_DAY_COUNT),
        ('Weekend minimum', weekend_minimum, PATTERN_DAY_COUNT),
    ):
        number = to_optional_int(value)
        if number is None:
            continue
        if number < 0:
            errors.append(f"{label} cannot be negative.")
        elif number > ceiling:
            errors.append(f"{label} cannot exceed {ceiling}.")

    if weekend_group not in (None, ''):
        group = str(weekend_group).strip().upper()
        if group not in WEEKEND_GROUPS:
            errors.append(f"Weekend group must be one of {', '.join(WEEKEND_GROUPS)}, "
                          "or left blank.")

    if email not in (None, ''):
        address = str(email).strip()
        if '@' not in address or address.startswith('@') or address.endswith('@') \
                or ' ' in address:
            errors.append(f"'{address}' does not look like an email address.")

    return errors


def add_staff(staff_name, role, is_management=False, is_dual=False, is_educator_at=False,
              no_matrix=False, seniority=None, shifts_per_pay_period=None,
              night_minimum=None, weekend_minimum=None, weekend_group=None, email=None,
              is_active=True, notes=None, changed_by=None, validate=True):
    """
    Add a staff member to the roster.

    Returns:
        tuple: (success, message)
    """
    initialize_staff_tables()
    name = clean_name(staff_name)

    if validate:
        errors = validate_staff_fields(
            name, role, seniority,
            shifts_per_pay_period=shifts_per_pay_period,
            night_minimum=night_minimum,
            weekend_minimum=weekend_minimum,
            weekend_group=weekend_group,
            email=email,
        )
        if errors:
            return False, " ".join(errors)

    canonical = canonical_role(role)
    if not canonical:
        return False, "Role is required."

    # Preferences v6 spelled a dual provider's role as "dual"; accept that on input
    # and split it into NURSE + the dual flag.
    if str(role).strip().lower() == 'dual':
        is_dual = True

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        now = _now()
        cursor.execute('''
            INSERT INTO staff (staff_name, role, is_management, is_dual, is_educator_at,
                               no_matrix, seniority, shifts_per_pay_period,
                               night_minimum, weekend_minimum, weekend_group, email,
                               is_active, notes, created_date, modified_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, canonical, to_flag(is_management), to_flag(is_dual),
              to_flag(is_educator_at), to_flag(no_matrix), to_seniority(seniority),
              to_optional_int(shifts_per_pay_period), to_optional_int(night_minimum),
              to_optional_int(weekend_minimum), to_weekend_group(weekend_group),
              to_email(email), to_flag(is_active), notes, now, now))
        _log_audit(cursor, name, 'added', {
            'role': canonical,
            'is_management': bool(to_flag(is_management)),
            'is_dual': bool(to_flag(is_dual)),
            'is_educator_at': bool(to_flag(is_educator_at)),
            'no_matrix': bool(to_flag(no_matrix)),
            'seniority': to_seniority(seniority),
            'shifts_per_pay_period': to_optional_int(shifts_per_pay_period),
            'night_minimum': to_optional_int(night_minimum),
            'weekend_minimum': to_optional_int(weekend_minimum),
            'weekend_group': to_weekend_group(weekend_group),
            'email': to_email(email),
            'is_active': bool(is_active),
        }, changed_by)
        conn.commit()
        invalidate_cache()
        return True, f"Added {name} to the staff roster."
    except sqlite3.IntegrityError:
        return False, f"'{name}' is already on the roster."
    except Exception as e:
        return False, f"Error adding {name}: {e}"


def update_staff(staff_name, changed_by=None, validate=True, **fields):
    """
    Update attributes of an existing staff member. Only the fields passed are changed.

    Accepted fields: role, is_management, is_dual, is_educator_at, no_matrix, seniority,
    shifts_per_pay_period, night_minimum, weekend_minimum, weekend_group, email,
    is_active, notes. Use rename_staff() to change the name.

    Passing None for seniority, a requirements number, the weekend group or the email
    clears that field — blank is a meaningful value for all of them.

    Returns:
        tuple: (success, message)
    """
    record = _lookup(staff_name)
    if not record:
        return False, f"'{clean_name(staff_name)}' is not on the staff roster."

    unknown = [key for key in fields if key not in _EDITABLE_FIELDS]
    if unknown:
        return False, f"Cannot update unknown field(s): {', '.join(unknown)}."

    updates = {}
    for key, value in fields.items():
        if key == 'role':
            canonical = canonical_role(value)
            if not canonical:
                return False, "Role is required."
            if str(value).strip().lower() == 'dual':
                updates['is_dual'] = 1
            updates['role'] = canonical
        elif key == 'seniority':
            updates['seniority'] = to_seniority(value)
        elif key in _NULLABLE_INT_FIELDS:
            # A value that doesn't parse would coerce to None and silently clear the
            # field, so a typo is reported instead of quietly wiping a requirement.
            number = to_optional_int(value)
            if number is None and str(value if value is not None else '').strip():
                return False, f"'{value}' is not a whole number ({key.replace('_', ' ')})."
            updates[key] = number
        elif key == 'weekend_group':
            group = to_weekend_group(value)
            if group is None and str(value if value is not None else '').strip():
                return False, (f"Weekend group must be one of "
                               f"{', '.join(WEEKEND_GROUPS)}, or left blank.")
            updates['weekend_group'] = group
        elif key == 'email':
            updates['email'] = to_email(value)
        elif key == 'notes':
            updates['notes'] = value if value in (None, '') else str(value).strip()
        else:
            updates[key] = to_flag(value)

    if validate:
        errors = validate_staff_fields(
            record['staff_name'],
            updates.get('role', record['role']),
            updates.get('seniority', record['seniority']),
            exclude_name=record['staff_name'],
            shifts_per_pay_period=updates.get('shifts_per_pay_period',
                                              record['shifts_per_pay_period']),
            night_minimum=updates.get('night_minimum', record['night_minimum']),
            weekend_minimum=updates.get('weekend_minimum', record['weekend_minimum']),
            weekend_group=updates.get('weekend_group', record['weekend_group']),
            email=updates.get('email', record['email']),
        )
        if errors:
            return False, " ".join(errors)

    # Only record fields that actually change.
    before = {}
    after = {}
    for key, value in updates.items():
        current = record.get(key)
        if isinstance(current, bool):
            current = int(current)
        if current != value:
            before[key] = record.get(key)
            after[key] = bool(value) if key in _BOOLEAN_FIELDS else value
    if not after:
        return True, f"No changes for {record['staff_name']}."

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        assignments = ', '.join(f"{key} = ?" for key in updates)
        params = list(updates.values()) + [_now(), record['id']]
        cursor.execute(f"UPDATE staff SET {assignments}, modified_date = ? WHERE id = ?",
                       params)
        _log_audit(cursor, record['staff_name'], 'updated',
                   {'before': before, 'after': after}, changed_by)
        conn.commit()
        invalidate_cache()
        changed = ', '.join(sorted(after))
        return True, f"Updated {record['staff_name']} ({changed})."
    except Exception as e:
        return False, f"Error updating {record['staff_name']}: {e}"


def set_staff_active(staff_name, is_active, changed_by=None):
    """
    Mark a staff member active or inactive.

    Inactive staff keep their history (tracks, enrollments, bids) but drop out of every
    staff picker and roster the app builds — this is the normal way to handle someone
    leaving, rather than deleting them.

    Returns:
        tuple: (success, message)
    """
    record = _lookup(staff_name)
    if not record:
        return False, f"'{clean_name(staff_name)}' is not on the staff roster."

    target = 1 if to_flag(is_active) else 0
    if int(record['is_active']) == target:
        state = 'active' if target else 'inactive'
        return True, f"{record['staff_name']} is already {state}."

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE staff SET is_active = ?, modified_date = ? WHERE id = ?",
                       (target, _now(), record['id']))
        _log_audit(cursor, record['staff_name'],
                   'activated' if target else 'deactivated',
                   {'is_active': bool(target)}, changed_by)
        conn.commit()
        invalidate_cache()
        state = 'active' if target else 'inactive'
        return True, f"{record['staff_name']} is now {state}."
    except Exception as e:
        return False, f"Error changing active status for {record['staff_name']}: {e}"


def _staff_reference_columns():
    """
    [(table, column)] for every staff-name column in the database, excluding this
    module's own tables. Discovered from the live schema so new tables are covered
    without editing this module.
    """
    references = []
    try:
        cursor = _get_conn().cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            if table in _OWN_TABLES or table.startswith('sqlite_'):
                continue
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            for column in columns:
                if column in STAFF_NAME_COLUMNS:
                    references.append((table, column))
    except Exception as e:
        print(f"Error inspecting staff name references: {e}")
    return references


def count_staff_references(staff_name):
    """
    How many rows elsewhere in the database refer to this staff name.

    Returns:
        dict: {"table.column": row count} for non-zero counts only.
    """
    name = clean_name(staff_name)
    counts = {}
    if not name:
        return counts
    try:
        cursor = _get_conn().cursor()
        for table, column in _staff_reference_columns():
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = ? COLLATE NOCASE",
                (name,))
            count = cursor.fetchone()[0]
            if count:
                counts[f"{table}.{column}"] = count
    except Exception as e:
        print(f"Error counting references for {name}: {e}")
    return counts


def rename_staff(old_name, new_name, changed_by=None, propagate=True):
    """
    Rename a staff member — e.g. someone marries and changes their surname.

    Staff names are the join key across tracks, bids, preferences, summer leave,
    training enrollments and educator signups, so the rename rewrites every staff-name
    reference in the database in the same transaction as the roster row. What it
    touched is recorded in staff_name_history.

    Args:
        propagate (bool): when False, only the roster row is renamed. History stays
            under the old name — use this only when the other rows are intentionally
            being left alone.

    Returns:
        tuple: (success, message, rows_updated) — rows_updated maps "table.column" to
        the number of rows rewritten.
    """
    record = _lookup(old_name)
    if not record:
        return False, f"'{clean_name(old_name)}' is not on the staff roster.", {}

    new = clean_name(new_name)
    if not new:
        return False, "New name is required.", {}
    if new == record['staff_name']:
        return False, "The new name is the same as the current name.", {}

    conflict = _lookup(new)
    if conflict and conflict['id'] != record['id']:
        return False, f"'{conflict['staff_name']}' is already on the roster.", {}

    old = record['staff_name']
    rows_updated = {}

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        now = _now()

        cursor.execute("UPDATE staff SET staff_name = ?, modified_date = ? WHERE id = ?",
                       (new, now, record['id']))

        if propagate:
            for table, column in _staff_reference_columns():
                cursor.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} = ? COLLATE NOCASE",
                    (new, old))
                if cursor.rowcount:
                    rows_updated[f"{table}.{column}"] = cursor.rowcount

        cursor.execute('''
            INSERT INTO staff_name_history (staff_id, old_name, new_name, rows_updated,
                                            changed_by, changed_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (record['id'], old, new, json.dumps(rows_updated), changed_by or 'admin', now))
        _log_audit(cursor, new, 'renamed',
                   {'old_name': old, 'new_name': new, 'rows_updated': rows_updated,
                    'propagated': bool(propagate)}, changed_by)

        conn.commit()
        invalidate_cache()

        total = sum(rows_updated.values())
        if propagate:
            message = (f"Renamed {old} to {new} and updated {total} related "
                       f"row(s) across {len(rows_updated)} table(s).")
        else:
            message = f"Renamed {old} to {new} (related records left under the old name)."
        return True, message, rows_updated

    except Exception as e:
        try:
            _get_conn().rollback()
        except Exception:
            pass
        return False, f"Error renaming {old}: {e}", {}


def delete_staff(staff_name, changed_by=None, force=False):
    """
    Remove a staff member from the roster.

    Refuses when other tables still reference the name, since deleting would orphan
    tracks, bids or enrollments — deactivate instead, or pass force=True to delete the
    roster row anyway and leave those rows in place.

    Returns:
        tuple: (success, message)
    """
    record = _lookup(staff_name)
    if not record:
        return False, f"'{clean_name(staff_name)}' is not on the staff roster."

    name = record['staff_name']
    references = count_staff_references(name)
    if references and not force:
        detail = ', '.join(f"{key}: {count}" for key, count in sorted(references.items()))
        return False, (
            f"{name} still has records in the database ({detail}). "
            "Mark them inactive instead, or confirm a forced delete to remove the "
            "roster entry and leave those records in place."
        )

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM staff WHERE id = ?", (record['id'],))
        _log_audit(cursor, name, 'deleted',
                   {'record': {k: record[k] for k in _EDITABLE_FIELDS},
                    'forced': bool(force), 'orphaned_rows': references}, changed_by)
        conn.commit()
        invalidate_cache()
        if references:
            return True, (f"Deleted {name} from the roster. "
                          f"{sum(references.values())} related record(s) were left in place.")
        return True, f"Deleted {name} from the roster."
    except Exception as e:
        return False, f"Error deleting {name}: {e}"


# ──────────────────────────────────────────────
# Audit history
# ──────────────────────────────────────────────

def get_audit_log(limit=100, staff_name=None):
    """
    Recent roster changes, newest first.

    Returns:
        list: dicts with staff_name, action, changes (parsed), changed_by, changed_date.
    """
    if not staff_table_exists():
        return []
    try:
        cursor = _get_conn().cursor()
        if staff_name:
            cursor.execute('''
                SELECT staff_name, action, changes, changed_by, changed_date
                FROM staff_audit_log WHERE staff_name = ? COLLATE NOCASE
                ORDER BY id DESC LIMIT ?
            ''', (clean_name(staff_name), limit))
        else:
            cursor.execute('''
                SELECT staff_name, action, changes, changed_by, changed_date
                FROM staff_audit_log ORDER BY id DESC LIMIT ?
            ''', (limit,))
        entries = []
        for row in cursor.fetchall():
            try:
                changes = json.loads(row[2]) if row[2] else None
            except (TypeError, ValueError):
                changes = row[2]
            entries.append({
                'staff_name': row[0],
                'action': row[1],
                'changes': changes,
                'changed_by': row[3],
                'changed_date': row[4],
            })
        return entries
    except Exception as e:
        print(f"Error reading staff audit log: {e}")
        return []


def get_name_history(limit=100):
    """
    Past name changes, newest first.

    Returns:
        list: dicts with old_name, new_name, rows_updated (parsed), changed_by,
        changed_date.
    """
    if not staff_table_exists():
        return []
    try:
        cursor = _get_conn().cursor()
        cursor.execute('''
            SELECT old_name, new_name, rows_updated, changed_by, changed_date
            FROM staff_name_history ORDER BY id DESC LIMIT ?
        ''', (limit,))
        entries = []
        for row in cursor.fetchall():
            try:
                rows_updated = json.loads(row[2]) if row[2] else {}
            except (TypeError, ValueError):
                rows_updated = {}
            entries.append({
                'old_name': row[0],
                'new_name': row[1],
                'rows_updated': rows_updated,
                'changed_by': row[3],
                'changed_date': row[4],
            })
        return entries
    except Exception as e:
        print(f"Error reading staff name history: {e}")
        return []
