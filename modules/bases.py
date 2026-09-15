# modules/bases.py
"""
Bases as rows.

A base used to be a column. `user_location_preferences` carried `day_kbed`,
`day_klwm`, `day_kmht`, `day_1b9`, `day_kpym`, `night_klwm`, `night_kbed`,
`night_kpym`; `track_configs` carried the same eight. Adding a sixth base meant a
schema migration, an edit to every function that unpacked those columns in order,
and a new pair of number inputs in the bidding admin — and the fact that Manchester
and Mansfield have no night presence was written into `get_base_shift_counts()` as
a literal `'night': 0` rather than being a fact about the fleet.

Two tables replace that:

| Was | Now |
| --- | --- |
| Eight `day_*` / `night_*` columns on `user_location_preferences` | `staff_base_preferences` — a row per staff member, base and shift kind |
| The base list, hardcoded in five modules | `duty_bases` |
| `'night': 0` for KMHT and 1B9 | Derived: a base has a night presence when a night vehicle sits there |

The interface callers already had was base-keyed dicts — `{'KBED': 1, 'KLWM': 3}` —
so the shape they see is unchanged. Only the storage moved.

The legacy columns are still written for the five original bases, so anything not yet
reading through here keeps working. They are not read, and a sixth base will not
appear in them.
"""

from datetime import datetime

import pytz

_eastern_tz = pytz.timezone('America/New_York')

DAY = 'day'
NIGHT = 'night'

# The bases this service flies, seeded once and then owned by an admin. The order is
# the one the preference editor lists them in.
DEFAULT_BASES = [
    ('KBED', 'Bedford', 1),
    ('KMHT', 'Manchester', 2),
    ('KLWM', 'Lawrence', 3),
    ('KPYM', 'Plymouth', 4),
    ('1B9', 'Mansfield', 5),
]

# The five the retired columns could hold. Used only to keep those columns written
# while something might still read them; a sixth base simply will not appear there.
LEGACY_DAY_COLUMNS = {'KMHT': 'day_kmht', 'KLWM': 'day_klwm', 'KBED': 'day_kbed',
                      '1B9': 'day_1b9', 'KPYM': 'day_kpym'}
LEGACY_NIGHT_COLUMNS = {'KLWM': 'night_klwm', 'KBED': 'night_kbed',
                        'KPYM': 'night_kpym'}


def _get_conn():
    from .db_utils import get_db_connection
    return get_db_connection()


def _now():
    return datetime.now(_eastern_tz).isoformat()


def initialize_base_tables(seed=True, migrate=True):
    """
    Create the base registry and per-base preference tables. Safe to call repeatedly.

    Seeds the base list on first run, and lifts whatever the eight legacy columns
    held into rows so nobody has to re-enter their preferences.
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS duty_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE COLLATE NOCASE,
            label TEXT,
            sort_order INTEGER NOT NULL DEFAULT 99,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff_base_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            base_code TEXT NOT NULL,
            shift_kind TEXT NOT NULL,
            rank INTEGER,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            UNIQUE(staff_name, base_code, shift_kind)
        )
        ''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_staff_base_prefs_staff
                          ON staff_base_preferences(staff_name)''')
        conn.commit()

        if seed:
            cursor.execute("SELECT COUNT(*) FROM duty_bases")
            if cursor.fetchone()[0] == 0:
                stamp = _now()
                cursor.executemany('''
                    INSERT OR IGNORE INTO duty_bases
                        (code, label, sort_order, is_active, created_date, modified_date)
                    VALUES (?, ?, ?, 1, ?, ?)
                ''', [(code, label, order, stamp, stamp)
                      for code, label, order in DEFAULT_BASES])
                conn.commit()

        if migrate:
            migrate_legacy_columns()

        return True
    except Exception as e:
        print(f"Error initializing base tables: {e}")
        return False


def migrate_legacy_columns():
    """
    Lift the eight `day_*` / `night_*` columns into rows, once.

    Skipped when rows already exist — this is a one-way move, and re-running it over
    edited preferences would put the old values back.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM staff_base_preferences")
    if cursor.fetchone()[0]:
        return 0

    cursor.execute("""SELECT name FROM sqlite_master
                      WHERE type='table' AND name='user_location_preferences'""")
    if not cursor.fetchone():
        return 0

    columns = ', '.join(list(LEGACY_DAY_COLUMNS.values())
                        + list(LEGACY_NIGHT_COLUMNS.values()))
    cursor.execute(f"""SELECT staff_name, {columns}
                       FROM user_location_preferences WHERE is_active = 1""")

    stamp = _now()
    rows = []
    for record in cursor.fetchall():
        name = record[0]
        values = record[1:]
        codes = list(LEGACY_DAY_COLUMNS) + list(LEGACY_NIGHT_COLUMNS)
        kinds = [DAY] * len(LEGACY_DAY_COLUMNS) + [NIGHT] * len(LEGACY_NIGHT_COLUMNS)
        for code, kind, rank in zip(codes, kinds, values):
            if rank is not None:
                rows.append((name, code, kind, rank, stamp, stamp))

    if rows:
        cursor.executemany('''
            INSERT OR IGNORE INTO staff_base_preferences
                (staff_name, base_code, shift_kind, rank, created_date, modified_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', rows)
        conn.commit()
    return len(rows)


# ──────────────────────────────────────────────
# The base registry
# ──────────────────────────────────────────────

def get_bases(include_inactive=False):
    """Every base, in the order the editors list them."""
    initialize_base_tables()
    conn = _get_conn()
    cursor = conn.cursor()
    where = '' if include_inactive else 'WHERE is_active = 1'
    cursor.execute(f'''SELECT code, label, sort_order, is_active
                       FROM duty_bases {where} ORDER BY sort_order, code''')
    return [{'code': r[0], 'label': r[1] or r[0], 'sort_order': r[2],
             'is_active': bool(r[3])} for r in cursor.fetchall()]


def base_labels():
    """{code: label}."""
    return {base['code']: base['label'] for base in get_bases(include_inactive=True)}


def set_base(code, label=None, sort_order=99, is_active=True):
    """Add a base or update one in place."""
    code = str(code).strip()
    if not code:
        return False
    initialize_base_tables()
    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    cursor.execute('''
        INSERT INTO duty_bases (code, label, sort_order, is_active,
                                created_date, modified_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            label = excluded.label,
            sort_order = excluded.sort_order,
            is_active = excluded.is_active,
            modified_date = excluded.modified_date
    ''', (code, label, int(sort_order), 1 if is_active else 0, stamp, stamp))
    conn.commit()
    return True


def base_codes(shift_kind=None):
    """
    The base codes, optionally only those with a presence on this shift kind.

    Derived from the vehicle inventory rather than declared: a base has a night
    presence when a night vehicle sits there. That is what the old
    `get_base_shift_counts` wrote as a literal `'night': 0` for Manchester and
    Mansfield — a fact about the fleet, stated as a fact about the code.
    """
    codes = [base['code'] for base in get_bases()]
    if shift_kind is None:
        return codes
    counts = base_shift_counts()
    return [code for code in codes if counts.get(code, {}).get(shift_kind, 0) > 0]


def base_shift_counts():
    """
    {base: {'day': N, 'night': N}} — how many vehicles sit at each base.

    This is the shape `db_utils.get_base_shift_counts` returns, computed from
    `duty_vehicles` instead of from eight columns on a track config.
    """
    from .duty_schedule_db import get_vehicles

    counts = {base['code']: {DAY: 0, NIGHT: 0} for base in get_bases()}
    for vehicle in get_vehicles():
        code = (vehicle.get('base') or '').strip()
        if not code:
            continue        # a float belongs to no base
        counts.setdefault(code, {DAY: 0, NIGHT: 0})
        counts[code][vehicle['shift_kind']] = counts[code].get(vehicle['shift_kind'], 0) + 1
    return counts


# ──────────────────────────────────────────────
# Per-staff preferences
# ──────────────────────────────────────────────

def get_preferences(staff_name):
    """
    One staff member's base preferences.

    Returns:
        dict: {'day': {base: rank}, 'night': {base: rank}} — bases they have not
        ranked are simply absent.
    """
    initialize_base_tables()
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute('''SELECT base_code, shift_kind, rank
                      FROM staff_base_preferences WHERE staff_name = ?''',
                   (staff_name,))
    prefs = {DAY: {}, NIGHT: {}}
    for code, kind, rank in cursor.fetchall():
        if kind in prefs and rank is not None:
            prefs[kind][code] = rank
    return prefs


def get_all_preferences():
    """{staff_name: {'day': {base: rank}, 'night': {...}}} for everybody."""
    initialize_base_tables()
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute('''SELECT staff_name, base_code, shift_kind, rank
                      FROM staff_base_preferences ORDER BY staff_name''')
    everyone = {}
    for name, code, kind, rank in cursor.fetchall():
        if rank is None:
            continue
        prefs = everyone.setdefault(name, {DAY: {}, NIGHT: {}})
        if kind in prefs:
            prefs[kind][code] = rank
    return everyone


def set_preferences(staff_name, day_locations=None, night_locations=None):
    """
    Replace one staff member's base preferences.

    Args:
        day_locations (dict): {base: rank}. None leaves the day preferences alone;
            an empty dict clears them.
        night_locations (dict): the same, for nights.
    """
    initialize_base_tables()
    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()

    for kind, ranks in ((DAY, day_locations), (NIGHT, night_locations)):
        if ranks is None:
            continue
        cursor.execute('''DELETE FROM staff_base_preferences
                          WHERE staff_name = ? AND shift_kind = ?''',
                       (staff_name, kind))
        cursor.executemany('''
            INSERT INTO staff_base_preferences
                (staff_name, base_code, shift_kind, rank, created_date, modified_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', [(staff_name, code, kind, rank, stamp, stamp)
              for code, rank in (ranks or {}).items() if rank is not None])
    conn.commit()
    return True


def delete_preferences(staff_name):
    """Drop somebody's base preferences entirely."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM staff_base_preferences WHERE staff_name = ?",
                   (staff_name,))
    conn.commit()
    return cursor.rowcount
