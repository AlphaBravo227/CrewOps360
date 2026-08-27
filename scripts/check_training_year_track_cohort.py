#!/usr/bin/env python3
"""
Self-check for the link between a training year and its track cohort.

A training year is linked to a Track Bidding cohort so that class conflicts are checked
against the tracks that year's staff actually bid, on that cohort's 42-day grid. Every
way this goes wrong is silent - the enrollment screen reports availability against the
wrong tracks rather than raising anything - so the pieces are verified here:

  * a linked cohort's tracks are loaded even though the cohort is not the active one
  * the newest version of a staff member's track in that cohort wins
  * an empty cohort falls back to the active one, and says so
  * a wrong pattern anchor is caught before it shifts conflict checks

Usage:
    python scripts/check_training_year_track_cohort.py
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training_modules.track_manager import (  # noqa: E402
    TrainingTrackManager,
    resolve_track_context,
)

_failures = []
_checks = 0


def check(label, condition, detail=''):
    global _checks
    _checks += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
        _failures.append(label)


def build_tracks_db(path):
    """A tracks database holding an active FY26 cohort and a bid-only FY27 cohort."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            track_data TEXT NOT NULL,
            submission_date TEXT,
            version INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            track_name TEXT
        )
    """)

    def add(staff, track, name, active, version):
        conn.execute(
            "INSERT INTO tracks (staff_name, track_data, submission_date, version,"
            " is_active, track_name) VALUES (?, ?, ?, ?, ?, ?)",
            (staff, json.dumps(track), '2026-07-20 17:28:57', version, active, name))

    # FY26 is the active cohort: Bell is off on Wed A 2.
    add('Bell', {'Wed A 2': '', 'Thu A 2': 'N'}, 'FY26', 1, 1)
    # FY27 is bid but not promoted: Bell works a day shift on Wed A 2. Two rows, as
    # happens when a promoted track is re-bid - the later version is the real one.
    add('Bell', {'Wed A 2': 'N'}, 'FY27', 0, 1)
    add('Bell', {'Wed A 2': 'D'}, 'FY27', 0, 2)
    conn.commit()
    conn.close()


def check_cohort_loading(db_path):
    print("\nCohort loading")

    active = TrainingTrackManager(db_path)
    check("an unlinked year loads the active cohort",
          active.tracks_cache.get('Bell') == {'Wed A 2': '', 'Thu A 2': 'N'},
          str(active.tracks_cache))
    check("an unlinked year reports no cohort of its own", active.loaded_cohort is None)

    linked = TrainingTrackManager(db_path, track_cohort='FY27')
    check("a linked cohort loads even though it is not active",
          'Bell' in linked.tracks_cache, str(linked.tracks_cache))
    check("the newest version of a track in the cohort wins",
          linked.tracks_cache.get('Bell') == {'Wed A 2': 'D'},
          str(linked.tracks_cache.get('Bell')))
    check("the cohort actually loaded is reported", linked.loaded_cohort == 'FY27')

    empty = TrainingTrackManager(db_path, track_cohort='FY28')
    check("a cohort with no tracks falls back to the active one",
          empty.tracks_cache.get('Bell') == {'Wed A 2': '', 'Thu A 2': 'N'})
    check("the fallback is visible rather than silent", empty.loaded_cohort is None)


def check_conflicts(db_path):
    print("\nConflict checking")

    # FY27's pattern starts Sun 09/27/2026, so Wed A 2 falls on 10/07/2026.
    fy27 = TrainingTrackManager(db_path, track_cohort='FY27',
                                pattern_start=datetime(2026, 9, 27))
    check("the class date maps to the expected pattern day",
          fy27.get_pattern_day_name(datetime(2026, 10, 7)) == 'Wed A 2',
          fy27.get_pattern_day_name(datetime(2026, 10, 7)))

    has_conflict, details = fy27.check_class_conflict('Bell', '10/07/2026')
    check("a day shift on the bid track conflicts with that day's class",
          has_conflict and 'Day Shift' in details, details)

    # The same class read against the active cohort - what happens when the link is
    # ignored - shows Bell as free, which is the bug this guards against.
    fy26 = TrainingTrackManager(db_path, pattern_start=datetime(2026, 9, 27))
    has_conflict, _ = fy26.check_class_conflict('Bell', '10/07/2026')
    check("the active cohort would have shown that class as available",
          not has_conflict)

    # A pattern anchor a year out shifts the lookup onto a different pattern day.
    shifted = TrainingTrackManager(db_path, track_cohort='FY27',
                                   pattern_start=datetime(2027, 9, 27))
    check("a wrong anchor moves the class onto a different pattern day",
          shifted.get_pattern_day_name(datetime(2026, 10, 7)) != 'Wed A 2',
          shifted.get_pattern_day_name(datetime(2026, 10, 7)))


def check_context_resolution():
    print("\nTraining year settings")

    cohort, start, warnings = resolve_track_context({
        'year_label': 'FY27', 'linked_track_name': 'FY27',
        'pattern_start_date': '2026-09-27'})
    check("a correctly configured year resolves cleanly",
          cohort == 'FY27' and start == datetime(2026, 9, 27) and not warnings,
          str(warnings))

    _, _, warnings = resolve_track_context({
        'year_label': 'FY27', 'linked_track_name': 'FY27',
        'pattern_start_date': '2027-09-27'})
    check("an anchor that isn't a Sunday is flagged",
          any('Sunday' in w for w in warnings), str(warnings))

    _, start, warnings = resolve_track_context({
        'year_label': 'FY27', 'linked_track_name': 'FY27',
        'pattern_start_date': 'Sept 27'})
    check("an unparseable anchor is flagged and falls back to the default",
          start is None and any('valid YYYY-MM-DD' in w for w in warnings), str(warnings))

    cohort, _, warnings = resolve_track_context({'year_label': 'FY27'})
    check("a year with no linked cohort is flagged",
          cohort is None and any('linked to a track cohort' in w for w in warnings),
          str(warnings))

    cohort, _, _ = resolve_track_context({'year_label': 'FY27', 'linked_track_name': '  '})
    check("a blank cohort counts as unlinked", cohort is None)


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, 'tracks_check.db')
        build_tracks_db(db_path)
        print(f"Temporary database: {db_path}")

        check_cohort_loading(db_path)
        check_conflicts(db_path)
        check_context_resolution()

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("Failed: " + ", ".join(_failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
