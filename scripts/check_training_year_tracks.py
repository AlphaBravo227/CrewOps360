#!/usr/bin/env python3
"""
Self-check for the link between a training year and a track cohort.

A training year names the track cohort its classes are checked against for schedule
conflicts. This verifies that naming a cohort actually loads that cohort's tracks,
that the fallback to the active cohort reports itself instead of happening silently,
and that the coverage numbers the admin screen shows match what conflict checking can
really see.

Usage:
    python scripts/check_training_year_tracks.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training_modules.track_manager import TrainingTrackManager  # noqa: E402

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


def seed(db_path):
    """Build the mid-cutover shape: FY26 active, FY27 mid-bid.

    Submitted bids land in `tracks` with is_active = 0 until the cohort is promoted;
    bids still being built sit in bid_drafts, where conflict checking can't see them.
    """
    from modules import db_utils
    db_utils.initialize_database()
    conn = db_utils.get_db_connection()
    cursor = conn.cursor()

    for staff, day_code in (('Active Annie', 'D'), ('Active Andy', 'N')):
        cursor.execute(
            """INSERT INTO tracks (staff_name, track_data, submission_date, version,
                                   is_active, track_name)
               VALUES (?, ?, '', 1, 1, 'FY26')""",
            (staff, json.dumps({'Sun A 1': day_code})))
    # A submitted FY27 bid: same staff member, a different shift than their FY26 track,
    # so a check against the wrong cohort is visible rather than coincidental.
    cursor.execute(
        """INSERT INTO tracks (staff_name, track_data, submission_date, version,
                               is_active, track_name)
           VALUES ('Active Annie', ?, '', 1, 0, 'FY27')""",
        (json.dumps({'Sun A 1': 'N'}),))
    # A superseded row left behind by the older save path, lower version.
    cursor.execute(
        """INSERT INTO tracks (staff_name, track_data, submission_date, version,
                               is_active, track_name)
           VALUES ('Active Andy', ?, '', 1, 0, 'FY27')""",
        (json.dumps({'Sun A 1': 'D'}),))
    cursor.execute(
        """INSERT INTO tracks (staff_name, track_data, submission_date, version,
                               is_active, track_name)
           VALUES ('Active Andy', ?, '', 2, 0, 'FY27')""",
        (json.dumps({'Sun A 1': ''}),))
    # A draft bid, never submitted.
    cursor.execute(
        """INSERT INTO bid_drafts (staff_name, track_name, track_data, saved_date)
           VALUES ('Drafting Dana', 'FY27', ?, '')""",
        (json.dumps({'Sun A 1': 'D'}),))
    # A draft left behind by someone who has since submitted: already counted as
    # submitted, so it must not also count as still outstanding.
    cursor.execute(
        """INSERT INTO bid_drafts (staff_name, track_name, track_data, saved_date)
           VALUES ('Active Annie', 'FY27', ?, '')""",
        (json.dumps({'Sun A 1': 'D'}),))
    conn.commit()


def check_cohort_loading(db_path):
    print("\nCohort loading")
    linked = TrainingTrackManager(db_path, track_cohort='FY27')
    check("a linked cohort loads that cohort's tracks, not the active ones",
          linked.tracks_cache.get('Active Annie') == {'Sun A 1': 'N'},
          str(linked.tracks_cache))
    check("the loaded source is reported as the cohort",
          linked.tracks_source == 'cohort' and not linked.tracks_fell_back,
          f"{linked.tracks_source} / fell_back={linked.tracks_fell_back}")
    check("a staff member with two rows in the cohort caches at the newest version",
          linked.tracks_cache.get('Active Andy') == {'Sun A 1': ''},
          str(linked.tracks_cache.get('Active Andy')))

    unlinked = TrainingTrackManager(db_path)
    check("no cohort named still loads the active cohort",
          unlinked.tracks_cache.get('Active Annie') == {'Sun A 1': 'D'}
          and unlinked.tracks_source == 'active',
          str(unlinked.tracks_cache))
    check("the active load is not flagged as a fallback",
          not unlinked.tracks_fell_back)

    empty = TrainingTrackManager(db_path, track_cohort='FY28')
    check("an empty cohort falls back to the active cohort",
          empty.tracks_cache.get('Active Annie') == {'Sun A 1': 'D'},
          str(empty.tracks_cache))
    check("the fallback reports itself so the app can warn about it",
          empty.tracks_fell_back and empty.tracks_source == 'active',
          f"{empty.tracks_source} / fell_back={empty.tracks_fell_back}")


def check_coverage():
    print("\nCohort coverage reported to the admin screen")
    from modules.db_utils import get_cohort_track_coverage
    fy27 = get_cohort_track_coverage('FY27')
    check("submitted bids are counted once per staff member",
          fy27['submitted'] == 2, str(fy27))
    check("unsubmitted drafts are counted separately",
          fy27['drafts'] == 1, str(fy27))
    check("a draft left behind by someone who has submitted isn't counted twice",
          fy27['submitted'] + fy27['drafts'] == 3, str(fy27))
    check("the active cohort's size is reported for comparison",
          fy27['active'] == 2, str(fy27))
    empty = get_cohort_track_coverage('FY28')
    check("a cohort with nothing in it reports zero submitted",
          empty['submitted'] == 0 and empty['drafts'] == 0, str(empty))
    check("no cohort named reports zeros rather than failing",
          get_cohort_track_coverage(None)['submitted'] == 0)


def check_pattern_anchor():
    print("\nPattern anchor")
    from datetime import datetime
    default = TrainingTrackManager()
    check("the default anchor is FY26's 'Sun A 1'",
          default.get_pattern_day_name(datetime(2025, 9, 14)) == 'Sun A 1')
    fy27 = TrainingTrackManager(pattern_start=datetime(2026, 9, 27))
    check("a per-year anchor moves the whole grid with it",
          fy27.get_pattern_day_name(datetime(2026, 9, 27)) == 'Sun A 1'
          and fy27.get_pattern_day_name(datetime(2026, 10, 5)) == 'Mon A 2',
          fy27.get_pattern_day_name(datetime(2026, 10, 5)))


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, 'training_year_tracks_check.db')

        # db_utils reaches the database by a fixed path, so point it at the throwaway
        # file for the duration of the check.
        from modules import db_utils
        db_utils.close_all_connections()
        original_connect = db_utils.sqlite3.connect
        db_utils.sqlite3.connect = lambda *args, **kwargs: original_connect(
            db_path, *args[1:], **kwargs)
        print(f"Temporary database: {db_path}")

        try:
            seed(db_path)
            check_cohort_loading(db_path)
            check_coverage()
            check_pattern_anchor()
        finally:
            db_utils.close_all_connections()
            db_utils.sqlite3.connect = original_connect

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed.")
    if _failures:
        print("Failed: " + ", ".join(_failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
