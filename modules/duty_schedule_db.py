# modules/duty_schedule_db.py
"""
The duty schedule: vehicles, two-week blocks, and who flies what.

This is the database behind what used to be `Active 2-Week Template v10.17.25.xlsx`.
A track says a staff member works a day or a night; it does not say which aircraft or
ambulance. Turning `D` into `D7B` was done by hand on that spreadsheet, against a
top display that coloured every vehicle by whether the people assigned to it made a
legal crew, and against staff attributes pulled over a SharePoint link from
`Comprehensive Schedule Preferences v2.xlsx`.

Four tables replace it:

| Was | Now |
| --- | --- |
| The 15 vehicle rows at the top of the sheet | `duty_vehicles` — code, priority, base, RW/ground weighting |
| One dated tab per cycle (`11 Oct 2026`) | `duty_blocks` — one row per two-week block, draft until published |
| The assignment grid, rows 39–122 | `duty_assignments` — one row per person per date |
| The COUPLES block and custom matrix, rows 248–264 | `duty_restricted_pairs` |

and `duty_block_context` freezes what the tracks and the training calendar said at
the moment a block was published, so a posted schedule stops moving.

Everything else the sheet looked up over that external link is already here:
`user_location_preferences` is a column-for-column match for its `Updated Prefs`
sheet, and senior/junior is `staff.no_matrix`.

The crew rules that colour the board live in `modules/duty_crew.py`; assembling a
block from tracks and training lives in `modules/duty_board.py`.
"""

from datetime import datetime, timedelta

import pytz

_eastern_tz = pytz.timezone('America/New_York')

# Block geometry. Fourteen days of schedule, plus the preceding Friday and Saturday
# carried for context: a night worked on the Saturday before the block decides whether
# the Sunday is a legal turn, and the sheet kept those two columns for exactly that.
BLOCK_DAYS = 14
LEAD_IN_DAYS = 2

DAY = 'day'
NIGHT = 'night'

# Minimum staffing, from the note at AE12:AE16 of the sheet. Held here rather than in a
# table because they are policy rather than inventory — the vehicle list is editable,
# but how many of them have to be crewed is a standing rule.
MIN_RW_DAY = 5
MIN_GR_DAY = 2
MIN_RW_NIGHT = 3
MIN_GR_NIGHT = 1
NIGHT_SURGE_THRESHOLD = 8   # days crewed at or above this call for a fifth night
NIGHT_SURGE_TARGET = 5

# The bases, by their airport identifier. FLOAT belongs to no base.
BASES = ('KBED', 'KMHT', 'KLWM', 'KPYM', '1B9')
BASE_LABELS = {
    'KBED': 'Bedford',
    'KMHT': 'Manchester',
    'KLWM': 'Lawrence',
    'KPYM': 'Plymouth',
    '1B9': 'Mansfield',
}

# The starting inventory, read off the sheet's priority column and its RW/GR counting
# formulas at AP39/AQ39. D7P, N7P and N9L each count as half rotor-wing and half
# ground, which is why the weights are floats and not a single 'kind' column.
#
# Seeded once, then owned by the admin — add, retire and re-prioritize in the UI
# rather than here. NP is the one the spreadsheet never counted in either column;
# it is seeded as ground to match PG, and is worth an admin's eye.
DEFAULT_VEHICLES = [
    # (code, label,            kind,  priority, base,   rw,  gr)
    ('D7B',   'Day 0700 Bedford',     DAY,   1,  'KBED', 1.0, 0.0),
    ('D7P',   'Day 0700 Plymouth',    DAY,   2,  'KPYM', 0.5, 0.5),
    ('D9L',   'Day 0900 Lawrence',    DAY,   3,  'KLWM', 1.0, 0.0),
    ('D11M',  'Day 1100 Mansfield',   DAY,   4,  '1B9',  1.0, 0.0),
    ('D11H',  'Day 1100 Manchester',  DAY,   5,  'KMHT', 1.0, 0.0),
    ('MG',    'Mansfield Ground',     DAY,   6,  '1B9',  0.0, 1.0),
    ('GR',    'Bedford Ground',       DAY,   7,  'KBED', 0.0, 1.0),
    ('LG',    'Lawrence Ground',      DAY,   8,  'KLWM', 0.0, 1.0),
    ('PG',    'Plymouth Ground',      DAY,   9,  'KPYM', 0.0, 1.0),
    ('FLOAT', 'Float',                DAY,  10,  '',     0.0, 1.0),
    ('N7B',   'Night 1900 Bedford',   NIGHT, 1,  'KBED', 1.0, 0.0),
    ('N7P',   'Night 1900 Plymouth',  NIGHT, 2,  'KPYM', 0.5, 0.5),
    ('N9L',   'Night 2100 Lawrence',  NIGHT, 3,  'KLWM', 0.5, 0.5),
    ('NG',    'Bedford Ground Night', NIGHT, 4,  'KBED', 0.0, 1.0),
    ('NP',    'Plymouth Ground Night', NIGHT, 5, 'KPYM', 0.0, 1.0),
]

# A block is draft until a scheduler releases it. Staff see published blocks only.
BLOCK_DRAFT = 'draft'
BLOCK_PUBLISHED = 'published'
BLOCK_STATUSES = (BLOCK_DRAFT, BLOCK_PUBLISHED)

# Which seat a person occupies on a vehicle. A crew is one RN seat and one medic seat;
# a dual-provider nurse taking the medic seat is what the spreadsheet wrote as the `p`
# suffix (D7Bp). THIRD is an orientee riding along, who fills neither.
SEAT_RN = 'rn'
SEAT_MEDIC = 'medic'
SEAT_THIRD = 'third'
SEATS = (SEAT_RN, SEAT_MEDIC, SEAT_THIRD)

# Who decided an assignment. A row in duty_assignments is always a decision about a
# vehicle — what the track and the training calendar say is context, and lives in
# duty_block_context, because a person can be both "on a day shift" and "on D7B" for
# the same date, and one row per person per date cannot hold both.
SOURCE_MANUAL = 'manual'
SOURCE_ALGORITHM = 'algorithm'
SOURCES = (SOURCE_MANUAL, SOURCE_ALGORITHM)


def _get_conn():
    from .db_utils import get_db_connection
    return get_db_connection()


def _now():
    return datetime.now(_eastern_tz).strftime('%Y-%m-%d %H:%M:%S')


def _date_str(value):
    """Coerce a date, datetime or string to YYYY-MM-DD."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        return None
    return value.strftime('%Y-%m-%d')


def _pair_key(staff_a, staff_b):
    """
    Restricted pairs are unordered — (King, Boomhower) and (Boomhower, King) are one
    restriction. Storing them sorted is what lets UNIQUE enforce that.
    """
    first, second = sorted([str(staff_a).strip(), str(staff_b).strip()],
                           key=lambda s: s.lower())
    return first, second


# ──────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────

def initialize_duty_tables(seed_vehicles=True):
    """
    Create the duty schedule tables if they don't exist, and seed the vehicle
    inventory the first time. Safe to call repeatedly.
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS duty_vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE COLLATE NOCASE,
            label TEXT,
            shift_kind TEXT NOT NULL,
            priority INTEGER NOT NULL,
            base TEXT,
            rw_weight REAL NOT NULL DEFAULT 0,
            gr_weight REAL NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS duty_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'draft',
            published_by TEXT,
            published_date TEXT,
            notes TEXT,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL
        )
        ''')

        # One row per person per date. The UNIQUE is what stops a double-booking
        # becoming data: the sheet caught those after the fact by looking for a comma
        # in the cell (AF39), which only worked if somebody typed the comma.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS duty_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_id INTEGER NOT NULL,
            staff_name TEXT NOT NULL,
            duty_date TEXT NOT NULL,
            vehicle_code TEXT NOT NULL,
            seat TEXT NOT NULL DEFAULT 'rn',
            source TEXT NOT NULL DEFAULT 'manual',
            note TEXT,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            UNIQUE(block_id, staff_name, duty_date)
        )
        ''')

        # What the tracks and the training calendar said, frozen when a block is
        # published. A draft reads both live, so a track swap shows up straight away;
        # a published block must not move under people who have already read it.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS duty_block_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_id INTEGER NOT NULL,
            staff_name TEXT NOT NULL,
            duty_date TEXT NOT NULL,
            track_code TEXT,
            training TEXT,
            created_date TEXT NOT NULL,
            UNIQUE(block_id, staff_name, duty_date)
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS duty_restricted_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_a TEXT NOT NULL COLLATE NOCASE,
            staff_b TEXT NOT NULL COLLATE NOCASE,
            reason TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            UNIQUE(staff_a, staff_b)
        )
        ''')

        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_duty_assignments_block
                          ON duty_assignments(block_id)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_duty_assignments_date
                          ON duty_assignments(block_id, duty_date)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_duty_assignments_staff
                          ON duty_assignments(block_id, staff_name)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_duty_vehicles_active
                          ON duty_vehicles(is_active, shift_kind, priority)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_duty_context_block
                          ON duty_block_context(block_id)''')

        conn.commit()

        if seed_vehicles:
            cursor.execute("SELECT COUNT(*) FROM duty_vehicles")
            if cursor.fetchone()[0] == 0:
                seed_default_vehicles()

        return True
    except Exception as e:
        print(f"Error initializing duty schedule tables: {e}")
        return False


def seed_default_vehicles():
    """Write the starting vehicle inventory. Only used when the table is empty."""
    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    for code, label, kind, priority, base, rw, gr in DEFAULT_VEHICLES:
        cursor.execute('''
            INSERT OR IGNORE INTO duty_vehicles
                (code, label, shift_kind, priority, base, rw_weight, gr_weight,
                 is_active, created_date, modified_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ''', (code, label, kind, priority, base, rw, gr, stamp, stamp))
    conn.commit()
    return True


# ──────────────────────────────────────────────
# Vehicles
# ──────────────────────────────────────────────

def get_vehicles(shift_kind=None, include_inactive=False):
    """
    The vehicle inventory, in the order the board draws it: days then nights, each
    by priority.

    Args:
        shift_kind (str, optional): 'day' or 'night' to take one half.
        include_inactive (bool): include retired vehicles.

    Returns:
        list[dict]
    """
    conn = _get_conn()
    cursor = conn.cursor()
    clauses, params = [], []
    if shift_kind:
        clauses.append("shift_kind = ?")
        params.append(shift_kind)
    if not include_inactive:
        clauses.append("is_active = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor.execute(f'''
        SELECT code, label, shift_kind, priority, base, rw_weight, gr_weight, is_active
        FROM duty_vehicles {where}
        ORDER BY CASE shift_kind WHEN 'day' THEN 0 ELSE 1 END, priority, code
    ''', params)
    return [
        {'code': r[0], 'label': r[1], 'shift_kind': r[2], 'priority': r[3],
         'base': r[4] or '', 'rw_weight': r[5], 'gr_weight': r[6],
         'is_active': bool(r[7])}
        for r in cursor.fetchall()
    ]


def get_vehicle(code):
    """One vehicle by code, or None."""
    for vehicle in get_vehicles(include_inactive=True):
        if vehicle['code'].lower() == str(code).strip().lower():
            return vehicle
    return None


def set_vehicle(code, label=None, shift_kind=DAY, priority=99, base='',
                rw_weight=0.0, gr_weight=0.0, is_active=True):
    """Add a vehicle or update one in place, keyed on its code."""
    code = str(code).strip()
    if not code:
        return False
    if shift_kind not in (DAY, NIGHT):
        raise ValueError(f"shift_kind must be '{DAY}' or '{NIGHT}', got {shift_kind!r}")

    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    cursor.execute('''
        INSERT INTO duty_vehicles
            (code, label, shift_kind, priority, base, rw_weight, gr_weight,
             is_active, created_date, modified_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            label = excluded.label,
            shift_kind = excluded.shift_kind,
            priority = excluded.priority,
            base = excluded.base,
            rw_weight = excluded.rw_weight,
            gr_weight = excluded.gr_weight,
            is_active = excluded.is_active,
            modified_date = excluded.modified_date
    ''', (code, label, shift_kind, int(priority), base or '',
          float(rw_weight), float(gr_weight), 1 if is_active else 0, stamp, stamp))
    conn.commit()
    return True


def retire_vehicle(code):
    """
    Mark a vehicle inactive. Kept rather than deleted so past blocks that reference
    it still read back.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE duty_vehicles SET is_active = 0, modified_date = ? WHERE code = ?",
                   (_now(), str(code).strip()))
    conn.commit()
    return cursor.rowcount > 0


# ──────────────────────────────────────────────
# Blocks
# ──────────────────────────────────────────────

def block_dates(start_date, include_lead_in=False):
    """
    The dates a block covers, as YYYY-MM-DD strings.

    Args:
        start_date: the block's first day.
        include_lead_in (bool): prepend the preceding Friday and Saturday, which the
            board carries so the rest and 10-hour-turn checks can see them.
    """
    start = datetime.strptime(_date_str(start_date), '%Y-%m-%d')
    first = start - timedelta(days=LEAD_IN_DAYS) if include_lead_in else start
    span = BLOCK_DAYS + (LEAD_IN_DAYS if include_lead_in else 0)
    return [(first + timedelta(days=offset)).strftime('%Y-%m-%d') for offset in range(span)]


def get_or_create_block(start_date, notes=None):
    """
    The block starting on this date, creating it as a draft if it is new.

    Returns:
        dict: the block record.
    """
    start = _date_str(start_date)
    if not start:
        raise ValueError(f"Unrecognizable block start date: {start_date!r}")

    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    cursor.execute('''
        INSERT OR IGNORE INTO duty_blocks
            (start_date, status, notes, created_date, modified_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (start, BLOCK_DRAFT, notes, stamp, stamp))
    conn.commit()
    return get_block(start)


def get_block(start_date):
    """One block by its start date, or None."""
    start = _date_str(start_date)
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, start_date, status, published_by, published_date, notes,
               created_date, modified_date
        FROM duty_blocks WHERE start_date = ?
    ''', (start,))
    row = cursor.fetchone()
    if not row:
        return None
    return {'id': row[0], 'start_date': row[1], 'status': row[2],
            'published_by': row[3], 'published_date': row[4], 'notes': row[5],
            'created_date': row[6], 'modified_date': row[7]}


def get_blocks(status=None, limit=None):
    """Every block, newest first."""
    conn = _get_conn()
    cursor = conn.cursor()
    where = "WHERE status = ?" if status else ""
    params = [status] if status else []
    sql = f'''SELECT id, start_date, status, published_by, published_date, notes,
                     created_date, modified_date
              FROM duty_blocks {where} ORDER BY start_date DESC'''
    if limit:
        sql += f" LIMIT {int(limit)}"
    cursor.execute(sql, params)
    return [
        {'id': r[0], 'start_date': r[1], 'status': r[2], 'published_by': r[3],
         'published_date': r[4], 'notes': r[5], 'created_date': r[6],
         'modified_date': r[7]}
        for r in cursor.fetchall()
    ]


def publish_block(start_date, published_by=None):
    """Release a block to staff."""
    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    cursor.execute('''
        UPDATE duty_blocks SET status = ?, published_by = ?, published_date = ?,
               modified_date = ?
        WHERE start_date = ?
    ''', (BLOCK_PUBLISHED, published_by, stamp, stamp, _date_str(start_date)))
    conn.commit()
    return cursor.rowcount > 0


def unpublish_block(start_date):
    """Pull a block back to draft."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE duty_blocks SET status = ?, published_by = NULL, published_date = NULL,
               modified_date = ?
        WHERE start_date = ?
    ''', (BLOCK_DRAFT, _now(), _date_str(start_date)))
    conn.commit()
    return cursor.rowcount > 0


def delete_block(start_date):
    """Remove a block and everything assigned in it."""
    block = get_block(start_date)
    if not block:
        return False
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM duty_assignments WHERE block_id = ?", (block['id'],))
    cursor.execute("DELETE FROM duty_block_context WHERE block_id = ?", (block['id'],))
    cursor.execute("DELETE FROM duty_blocks WHERE id = ?", (block['id'],))
    conn.commit()
    return True


# ──────────────────────────────────────────────
# Assignments
# ──────────────────────────────────────────────

def get_assignments(block_id, duty_date=None, staff_name=None, vehicle_code=None):
    """
    Assignments in a block, optionally narrowed to one date, person or vehicle.

    Returns:
        list[dict]: staff_name, duty_date, vehicle_code, seat, source, note.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    clauses, params = ["block_id = ?"], [block_id]
    if duty_date:
        clauses.append("duty_date = ?")
        params.append(_date_str(duty_date))
    if staff_name:
        clauses.append("staff_name = ?")
        params.append(staff_name)
    if vehicle_code:
        clauses.append("vehicle_code = ?")
        params.append(vehicle_code)
    cursor.execute(f'''
        SELECT staff_name, duty_date, vehicle_code, seat, source, note
        FROM duty_assignments WHERE {' AND '.join(clauses)}
        ORDER BY duty_date, vehicle_code, staff_name
    ''', params)
    return [
        {'staff_name': r[0], 'duty_date': r[1], 'vehicle_code': r[2],
         'seat': r[3], 'source': r[4], 'note': r[5]}
        for r in cursor.fetchall()
    ]


def set_assignment(block_id, staff_name, duty_date, vehicle_code,
                   seat=SEAT_RN, source=SOURCE_MANUAL, note=None):
    """
    Put one person on one vehicle for one date. Replaces whatever they had that day.

    Clearing is `clear_assignment`, not writing an empty code — a blank vehicle is
    a person with nothing on, which is an absent row rather than an empty one.
    """
    if seat not in SEATS:
        raise ValueError(f"seat must be one of {SEATS}, got {seat!r}")
    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    cursor.execute('''
        INSERT INTO duty_assignments
            (block_id, staff_name, duty_date, vehicle_code, seat, source, note,
             created_date, modified_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(block_id, staff_name, duty_date) DO UPDATE SET
            vehicle_code = excluded.vehicle_code,
            seat = excluded.seat,
            source = excluded.source,
            note = excluded.note,
            modified_date = excluded.modified_date
    ''', (block_id, staff_name, _date_str(duty_date), str(vehicle_code).strip(),
          seat, source, note, stamp, stamp))
    conn.commit()
    return True


def clear_assignment(block_id, staff_name, duty_date):
    """Take a person off whatever they were on that date."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute('''DELETE FROM duty_assignments
                      WHERE block_id = ? AND staff_name = ? AND duty_date = ?''',
                   (block_id, staff_name, _date_str(duty_date)))
    conn.commit()
    return cursor.rowcount > 0


def get_block_context(block_id):
    """
    The frozen track and training context for a published block.

    Returns:
        dict: {(staff_name, duty_date): {'track_code': str, 'training': [str, ...]}},
        empty for a block that has never been published.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""SELECT staff_name, duty_date, track_code, training
                      FROM duty_block_context WHERE block_id = ?""", (block_id,))
    context = {}
    for name, date, code, training in cursor.fetchall():
        context[(name, date)] = {
            'track_code': code or '',
            'training': [part for part in (training or '').split('|') if part],
        }
    return context


def set_block_context(block_id, rows):
    """
    Write a block's frozen context, replacing whatever was there.

    Args:
        rows (iterable): (staff_name, duty_date, track_code, [training labels]).
    """
    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    cursor.execute("DELETE FROM duty_block_context WHERE block_id = ?", (block_id,))
    cursor.executemany("""
        INSERT INTO duty_block_context
            (block_id, staff_name, duty_date, track_code, training, created_date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [(block_id, name, _date_str(date), code or '',
           '|'.join(training or []), stamp)
          for name, date, code, training in rows])
    conn.commit()
    return cursor.rowcount


def clear_block_context(block_id):
    """Drop a block's frozen context, so it reads live again."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM duty_block_context WHERE block_id = ?", (block_id,))
    conn.commit()
    return cursor.rowcount


def count_assignments(block_id, sources=None):
    """How many rows a block holds, optionally by source."""
    conn = _get_conn()
    cursor = conn.cursor()
    if sources:
        placeholders = ','.join('?' for _ in sources)
        cursor.execute(f'''SELECT COUNT(*) FROM duty_assignments
                           WHERE block_id = ? AND source IN ({placeholders})''',
                       [block_id, *sources])
    else:
        cursor.execute("SELECT COUNT(*) FROM duty_assignments WHERE block_id = ?",
                       (block_id,))
    return cursor.fetchone()[0]


# ──────────────────────────────────────────────
# Restricted pairs
# ──────────────────────────────────────────────

def get_restricted_pairs(include_inactive=False):
    """
    Pairs who may not crew the same vehicle — the sheet's COUPLES block and its
    custom can't-work-with matrix.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    where = "" if include_inactive else "WHERE is_active = 1"
    cursor.execute(f'''SELECT staff_a, staff_b, reason, is_active
                       FROM duty_restricted_pairs {where}
                       ORDER BY staff_a, staff_b''')
    return [{'staff_a': r[0], 'staff_b': r[1], 'reason': r[2], 'is_active': bool(r[3])}
            for r in cursor.fetchall()]


def set_restricted_pair(staff_a, staff_b, reason=None, is_active=True):
    """Record that two people may not share a vehicle."""
    first, second = _pair_key(staff_a, staff_b)
    if not first or not second or first.lower() == second.lower():
        return False
    conn = _get_conn()
    cursor = conn.cursor()
    stamp = _now()
    cursor.execute('''
        INSERT INTO duty_restricted_pairs
            (staff_a, staff_b, reason, is_active, created_date, modified_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(staff_a, staff_b) DO UPDATE SET
            reason = excluded.reason,
            is_active = excluded.is_active,
            modified_date = excluded.modified_date
    ''', (first, second, reason, 1 if is_active else 0, stamp, stamp))
    conn.commit()
    return True


def delete_restricted_pair(staff_a, staff_b):
    """Drop a restriction."""
    first, second = _pair_key(staff_a, staff_b)
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM duty_restricted_pairs WHERE staff_a = ? AND staff_b = ?",
                   (first, second))
    conn.commit()
    return cursor.rowcount > 0


def restricted_partners(staff_name, pairs=None):
    """
    Everyone a staff member may not be crewed with.

    Args:
        pairs (list, optional): a pre-loaded `get_restricted_pairs()`, so a board
            checking every cell doesn't re-query per cell.

    Returns:
        set[str]: partner names, lowercased for comparison.
    """
    pairs = get_restricted_pairs() if pairs is None else pairs
    name = str(staff_name).strip().lower()
    partners = set()
    for pair in pairs:
        if pair['staff_a'].strip().lower() == name:
            partners.add(pair['staff_b'].strip().lower())
        elif pair['staff_b'].strip().lower() == name:
            partners.add(pair['staff_a'].strip().lower())
    return partners
