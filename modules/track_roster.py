# modules/track_roster.py
"""
The active track roster, built from the database.

Tracks.xlsx's first sheet held one row per staff member and 42 day columns — the roster
of who works which day. Tracks are submitted, approved and stored in the `tracks` table,
so that sheet was a stale copy of what the database already knew.

build_current_tracks_df() produces the same shape from the database, so the code that
took `current_tracks_df` (the "reference track" a staff member's editor starts from, the
shift-occupancy counts, the fiscal-year exports) keeps working with no spreadsheet
involved.
"""

import json

import pandas as pd

from .day_pattern import PATTERN_DAYS

STAFF_NAME_COLUMN = 'STAFF NAME'

# Assignment codes a track day can hold.
DAY_SHIFT = 'D'
NIGHT_SHIFT = 'N'
PREASSIGNED = 'AT'


def _get_conn():
    from .db_utils import get_db_connection
    return get_db_connection()


def _tracks_table_exists(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks'")
    return cursor.fetchone() is not None


def get_active_track_rows(track_name=None, include_retired=False):
    """
    Active tracks as {staff_name: {day: assignment}}.

    Args:
        track_name (str, optional): restrict to one track cycle. Defaults to every
            active track regardless of cycle, which is what the app's "current tracks"
            view has always meant.
        include_retired (bool): with a track_name, read that cohort whether or not it
            is the live one. Promotion clears is_active on the outgoing cohort's rows,
            so a fiscal year still being worked after a cutover is only readable this
            way. Ignored without a track_name — "every cohort at once" would merge
            two fiscal years into one grid.

    Returns:
        dict: staff name -> day -> assignment code.
    """
    tracks = {}
    try:
        conn = _get_conn()
        if not _tracks_table_exists(conn):
            return tracks
        cursor = conn.cursor()
        if track_name and include_retired:
            cursor.execute("""
                SELECT staff_name, track_data FROM tracks
                WHERE track_name = ?
                ORDER BY staff_name
            """, (track_name,))
        elif track_name:
            cursor.execute("""
                SELECT staff_name, track_data FROM tracks
                WHERE is_active = 1 AND track_name = ?
                ORDER BY staff_name
            """, (track_name,))
        else:
            cursor.execute("""
                SELECT staff_name, track_data FROM tracks
                WHERE is_active = 1
                ORDER BY staff_name
            """)
        for staff_name, track_json in cursor.fetchall():
            name = str(staff_name).strip()
            if not name:
                continue
            try:
                track_data = json.loads(track_json) if track_json else {}
            except (TypeError, ValueError):
                print(f"Warning: corrupted track data for {name}")
                continue
            # A later version of the same staff member's track wins; the query is
            # ordered by name only, so keep merging rather than assuming one row each.
            tracks.setdefault(name, {}).update(
                {str(day): value for day, value in track_data.items()})
    except Exception as e:
        print(f"Error reading active tracks: {e}")
    return tracks


def get_bid_track_rows(track_name):
    """
    Submitted bids for a bidding cycle as {staff_name: {day: assignment}}.

    Bids live in the same table as active tracks but with is_active = 0 and the cycle's
    track_name, which is how the bidding views count occupancy for a cycle in progress.
    """
    tracks = {}
    if not track_name:
        return tracks
    try:
        conn = _get_conn()
        if not _tracks_table_exists(conn):
            return tracks
        cursor = conn.cursor()
        cursor.execute("""
            SELECT staff_name, track_data FROM tracks
            WHERE is_active = 0 AND track_name = ?
            ORDER BY staff_name
        """, (track_name,))
        for staff_name, track_json in cursor.fetchall():
            name = str(staff_name).strip()
            if not name:
                continue
            try:
                track_data = json.loads(track_json) if track_json else {}
            except (TypeError, ValueError):
                continue
            tracks.setdefault(name, {}).update(
                {str(day): value for day, value in track_data.items()})
    except Exception as e:
        print(f"Error reading bid tracks: {e}")
    return tracks


def build_tracks_df(tracks, staff_names=None, days=None):
    """
    Shape a {staff_name: {day: assignment}} mapping like the old Tracks.xlsx sheet:
    a STAFF NAME column followed by the 42 day columns.

    Args:
        tracks (dict): staff name -> day -> assignment.
        staff_names (list, optional): rows to include, in this order. Defaults to the
            staff present in `tracks`, sorted. Pass the roster to include staff who have
            no track yet — they get an all-blank row, which is what the editors expect
            when creating a track from scratch.
        days (list, optional): day columns. Defaults to the canonical 42.

    Returns:
        DataFrame: one row per staff member, blank string where there is no assignment.
    """
    day_columns = list(days) if days is not None else list(PATTERN_DAYS)

    if staff_names is None:
        names = sorted(tracks.keys())
    else:
        names = [str(name).strip() for name in staff_names if str(name).strip()]

    rows = []
    for name in names:
        track = tracks.get(name, {})
        row = {STAFF_NAME_COLUMN: name}
        for day in day_columns:
            value = track.get(day, '')
            row[day] = '' if value is None else str(value).strip()
        rows.append(row)

    columns = [STAFF_NAME_COLUMN] + day_columns
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def build_current_tracks_df(track_name=None, staff_names=None, days=None,
                            include_staff_without_tracks=True, include_retired=False):
    """
    The active track roster in Tracks.xlsx's shape, from the database.

    Args:
        track_name (str, optional): restrict to one track cycle.
        include_retired (bool): with a track_name, build the grid for that cohort even
            after it has stopped being the live one — see get_active_track_rows.
        staff_names (list, optional): rows to include, in order. Defaults to the active
            clinical staff on the roster when include_staff_without_tracks is set, so
            every nurse and medic appears whether or not they have submitted a track.
        days (list, optional): day columns; defaults to the canonical 42.
        include_staff_without_tracks (bool): when no staff_names are given, include
            roster staff who have no track yet (blank rows) instead of only those who do.

    Returns:
        DataFrame: STAFF NAME plus 42 day columns.
    """
    tracks = get_active_track_rows(track_name, include_retired=include_retired)

    if staff_names is None and include_staff_without_tracks:
        try:
            from .staff_database import get_staff_names
            roster = get_staff_names(clinical_only=True)
        except Exception as e:
            print(f"Could not read the staff roster for the track grid: {e}")
            roster = []
        # Anyone with a track but no longer on the active roster still belongs in the
        # grid — their track is live until someone retires it.
        extras = sorted(name for name in tracks if name not in set(roster))
        staff_names = roster + extras

    return build_tracks_df(tracks, staff_names=staff_names, days=days)


def get_staff_on_shift(day, shift_code, track_name=None, include_retired=False):
    """
    Names assigned to one day/shift across active tracks.

    Args:
        shift_code (str): 'D', 'N' or 'AT'.
    """
    wanted = str(shift_code).strip().upper()
    rows = get_active_track_rows(track_name, include_retired=include_retired)
    return sorted(name for name, track in rows.items()
                  if str(track.get(day, '')).strip().upper() == wanted)


def active_track_count(track_name=None, include_retired=False):
    """How many staff have an active track."""
    return len(get_active_track_rows(track_name, include_retired=include_retired))
