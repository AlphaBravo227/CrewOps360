# modules/staff_import.py
"""
One-time (and repeatable) import of the staff roster into the staff database.

The baseline list of names is the Education Classes Roster's Class_Enrollment sheet —
the only roster that covers everyone, clinical and non-clinical. Attributes are taken
from the two spreadsheets that used to be read on every page load:

    FY26 Education Classes Roster.xlsx / Class_Enrollment
        STAFF NAME    -> staff.staff_name
        Role          -> staff.role            (NURSE/MEDIC/COMMS/CCEMT/ATP/AMT)
        MGMT          -> staff.is_management
        DUAL          -> staff.is_dual
        Educator AT   -> staff.is_educator_at

    Preferences v6.xlsx
        No Matrix     -> staff.no_matrix
        Seniority     -> staff.seniority
        ROLE          -> confirms is_dual (Preferences spelled dual as a role)
        Reduced Rest OK / N to D Flex / per-base shift scores
                      -> seeded into the preference tables staff edit in the app, so
                         nothing is lost when the spreadsheet stops being read

    Requirements.xlsx
        SHIFTS PER PAY PERIOD -> staff.shifts_per_pay_period
        NIGHT MINIMUM         -> staff.night_minimum
        WEEKEND MINIMUM       -> staff.weekend_minimum
        WEEKEND GROUP         -> staff.weekend_group
        EMAIL                 -> staff.email

Import is idempotent: staff already on the roster are left alone unless
update_existing is set, so an admin's later edits are never silently overwritten by a
re-import.
"""

import os
from datetime import datetime

import pandas as pd
import pytz

from . import staff_database as staffdb
from .staff_database import (
    canonical_role,
    clean_name,
    to_email,
    to_flag,
    to_optional_int,
    to_seniority,
    to_weekend_group,
)

_eastern_tz = pytz.timezone('America/New_York')

DEFAULT_ROSTER_PATH = 'training/upload/FY26 Education Classes Roster.xlsx'
DEFAULT_PREFERENCES_PATH = 'upload files/Preferences v6.xlsx'
DEFAULT_REQUIREMENTS_PATH = 'upload files/Requirements.xlsx'
ENROLLMENT_SHEET = 'Class_Enrollment'

# Files consulted only to catch names the roster is missing (staff who hold a track or
# have requirements on file but were never added to the education roster).
SECONDARY_NAME_SOURCES = [
    ('Tracks', 'upload files/Tracks.xlsx'),
    ('Requirements', 'upload files/Requirements.xlsx'),
    ('Preassignments', 'upload files/Preassignments.xlsx'),
]

# Requirements fields, in the order the spreadsheet holds them.
REQUIREMENTS_FIELDS = ['shifts_per_pay_period', 'night_minimum', 'weekend_minimum',
                       'weekend_group', 'email']

# Preferences v6 shift-score columns, split by shift type for the preference tables.
_DAY_SHIFT_COLUMNS = ['D7B', 'D7P', 'D9L', 'D11M', 'D11B', 'FW', 'MG', 'GR', 'LG', 'PG']
_NIGHT_SHIFT_COLUMNS = ['N7B', 'N7P', 'N9L', 'NG', 'NP']


def _find_column(df, *candidates):
    """First column in df whose name case-insensitively matches one of candidates."""
    lookup = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        match = lookup.get(candidate.strip().lower())
        if match is not None:
            return match
    return None


def read_roster_attributes(roster_path=DEFAULT_ROSTER_PATH):
    """
    Read staff names and attributes from the Education Classes Roster.

    Returns:
        tuple: (records, error) where records is a list of dicts keyed staff_name,
        role, is_management, is_dual, is_educator_at, and error is None on success.
    """
    if not os.path.exists(roster_path):
        return [], f"Education Classes Roster not found: {roster_path}"

    try:
        df = pd.read_excel(roster_path, sheet_name=ENROLLMENT_SHEET)
    except Exception as e:
        return [], f"Could not read '{ENROLLMENT_SHEET}' from {roster_path}: {e}"

    name_col = _find_column(df, 'STAFF NAME', 'Staff Name', 'Name')
    role_col = _find_column(df, 'Role', 'ROLE')
    mgmt_col = _find_column(df, 'MGMT', 'Management')
    dual_col = _find_column(df, 'DUAL')
    educator_col = _find_column(df, 'Educator AT', 'Educator')

    if name_col is None:
        return [], f"No staff name column found in {ENROLLMENT_SHEET}."
    if role_col is None:
        return [], f"No Role column found in {ENROLLMENT_SHEET}."

    records = []
    for _, row in df.iterrows():
        name = clean_name(row[name_col])
        if not name or name.upper() == 'STAFF NAME':
            continue
        records.append({
            'staff_name': name,
            'role': canonical_role(row[role_col]),
            'raw_role': clean_name(row[role_col]),
            'is_management': to_flag(row[mgmt_col]) if mgmt_col else 0,
            'is_dual': to_flag(row[dual_col]) if dual_col else 0,
            'is_educator_at': to_flag(row[educator_col]) if educator_col else 0,
        })
    return records, None


def read_preferences_attributes(preferences_path=DEFAULT_PREFERENCES_PATH):
    """
    Read No Matrix, Seniority, the clinical role and the saved shift preferences from
    Preferences v6.

    Returns:
        tuple: (records_by_name, error) where each record holds no_matrix, seniority,
        clinical_role, reduced_rest_ok, n_to_d_flex and shift_scores.
    """
    if not os.path.exists(preferences_path):
        return {}, f"Preferences file not found: {preferences_path}"

    try:
        df = pd.read_excel(preferences_path)
    except Exception as e:
        return {}, f"Could not read {preferences_path}: {e}"

    name_col = _find_column(df, 'STAFF NAME', 'Staff Name', 'Name')
    role_col = _find_column(df, 'ROLE', 'Role')
    no_matrix_col = _find_column(df, 'No Matrix', 'No_Matrix')
    seniority_col = _find_column(df, 'Seniority', 'Rank')
    reduced_rest_col = _find_column(df, 'Reduced Rest OK', 'Reduced Rest')
    n_to_d_col = _find_column(df, 'N to D Flex')

    if name_col is None:
        return {}, f"No staff name column found in {preferences_path}."

    records = {}
    for _, row in df.iterrows():
        name = clean_name(row[name_col])
        if not name or name.upper() == 'STAFF NAME':
            continue

        shift_scores = {}
        for shift in _DAY_SHIFT_COLUMNS + _NIGHT_SHIFT_COLUMNS:
            col = _find_column(df, shift)
            if col is None:
                continue
            value = row[col]
            if pd.isna(value):
                continue
            try:
                shift_scores[shift] = int(float(value))
            except (TypeError, ValueError):
                continue

        n_to_d_flex = None
        if n_to_d_col is not None and pd.notna(row[n_to_d_col]):
            raw = row[n_to_d_col]
            if isinstance(raw, str):
                n_to_d_flex = raw.strip() or None
            else:
                # The file stores this as 1/0; the app stores Yes/No/Maybe.
                n_to_d_flex = 'Yes' if to_flag(raw) else 'No'

        records[name] = {
            'staff_name': name,
            'clinical_role': (clean_name(row[role_col]).lower() if role_col else ''),
            'no_matrix': to_flag(row[no_matrix_col]) if no_matrix_col else 0,
            'seniority': to_seniority(row[seniority_col]) if seniority_col else None,
            'reduced_rest_ok': (to_flag(row[reduced_rest_col])
                                if reduced_rest_col is not None else None),
            'n_to_d_flex': n_to_d_flex,
            'shift_scores': shift_scores,
        }
    return records, None


def read_requirements_attributes(requirements_path=DEFAULT_REQUIREMENTS_PATH):
    """
    Read shifts per pay period, night/weekend minimums, weekend group and email from
    Requirements.xlsx.

    Blank numeric cells are kept as None rather than 0 — a blank SHIFTS PER PAY PERIOD is
    how management and other non-bidding staff are marked, and is not the same as the 0
    carried by probationary staff.

    Returns:
        tuple: (records_by_name, error)
    """
    if not os.path.exists(requirements_path):
        return {}, f"Requirements file not found: {requirements_path}"

    try:
        df = pd.read_excel(requirements_path)
    except Exception as e:
        return {}, f"Could not read {requirements_path}: {e}"

    name_col = _find_column(df, 'STAFF NAME', 'Staff Name', 'Name')
    if name_col is None:
        return {}, f"No staff name column found in {requirements_path}."

    shifts_col = _find_column(df, 'SHIFTS PER PAY PERIOD', 'Shifts Per Pay Period')
    night_col = _find_column(df, 'NIGHT MINIMUM', 'Night Minimum')
    weekend_col = _find_column(df, 'WEEKEND MINIMUM', 'Weekend Minimum')
    group_col = _find_column(df, 'WEEKEND GROUP', 'Weekend Group')
    email_col = _find_column(df, 'EMAIL', 'Email', 'Email Address')

    records = {}
    for _, row in df.iterrows():
        name = clean_name(row[name_col])
        if not name or name.upper() == 'STAFF NAME':
            continue
        records[name] = {
            'staff_name': name,
            'shifts_per_pay_period': to_optional_int(row[shifts_col]) if shifts_col else None,
            'night_minimum': to_optional_int(row[night_col]) if night_col else None,
            'weekend_minimum': to_optional_int(row[weekend_col]) if weekend_col else None,
            'weekend_group': to_weekend_group(row[group_col]) if group_col else None,
            'email': to_email(row[email_col]) if email_col else None,
        }
    return records, None


def read_secondary_names(sources=None):
    """
    Staff names that appear in the other Excel uploads.

    Returns:
        dict: {staff_name: [source labels]}
    """
    names = {}
    for label, path in (sources or SECONDARY_NAME_SOURCES):
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_excel(path)
        except Exception as e:
            print(f"Could not read {path}: {e}")
            continue
        name_col = _find_column(df, 'STAFF NAME', 'Staff Name', 'Name') or df.columns[0]
        for value in df[name_col]:
            name = clean_name(value)
            if name and name.upper() != 'STAFF NAME':
                names.setdefault(name, []).append(label)
    return names


def _merge_attributes(roster_record, preferences_record, requirements_record=None):
    """
    Combine a roster row with its Preferences v6 and Requirements rows into one staff
    record.

    Preferences v6 spelled a dual provider's role as ROLE='dual' while the roster
    carries a separate DUAL checkbox. The two disagree for at least one staff member,
    so is_dual is the union of both — dropping the flag would change how that person is
    counted for staffing.
    """
    record = {
        'staff_name': roster_record['staff_name'],
        'role': roster_record['role'],
        'is_management': roster_record['is_management'],
        'is_dual': roster_record['is_dual'],
        'is_educator_at': roster_record['is_educator_at'],
        'no_matrix': 0,
        'seniority': None,
        'shifts_per_pay_period': None,
        'night_minimum': None,
        'weekend_minimum': None,
        'weekend_group': None,
        'email': None,
    }
    conflicts = []

    if requirements_record:
        for field in REQUIREMENTS_FIELDS:
            record[field] = requirements_record[field]

    if preferences_record:
        record['no_matrix'] = preferences_record['no_matrix']
        record['seniority'] = preferences_record['seniority']

        pref_role = preferences_record['clinical_role']
        if pref_role == 'dual' and not record['is_dual']:
            record['is_dual'] = 1
            conflicts.append(
                f"{record['staff_name']}: Preferences v6 lists them as dual but the "
                "roster's DUAL box is unchecked — imported as dual."
            )
        elif pref_role in ('nurse', 'medic') and record['role'] and \
                pref_role != record['role'].lower() and not record['is_dual']:
            conflicts.append(
                f"{record['staff_name']}: role is {record['role']} in the roster but "
                f"{pref_role} in Preferences v6 — kept the roster's {record['role']}."
            )

    return record, conflicts


def _seed_shift_preferences(preferences_record, overwrite=False):
    """
    Copy a staff member's Preferences v6 shift scores and boolean answers into the
    tables the in-app preference editor reads, so the spreadsheet can stop being the
    fallback source. Existing saved preferences are left alone unless overwrite is set.

    Returns:
        int: number of preference rows written.
    """
    name = preferences_record['staff_name']
    conn = staffdb._get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences'")
    if not cursor.fetchone():
        return 0

    written = 0
    timestamp = datetime.now(_eastern_tz).isoformat()

    if not overwrite:
        cursor.execute("SELECT COUNT(*) FROM user_preferences WHERE staff_name = ? AND is_active = 1",
                       (name,))
        if cursor.fetchone()[0]:
            return 0

    for shift, score in preferences_record['shift_scores'].items():
        shift_type = 'day' if shift in _DAY_SHIFT_COLUMNS else 'night'
        cursor.execute("""
            INSERT OR REPLACE INTO user_preferences
            (staff_name, shift_name, preference_score, shift_type, created_date,
             modified_date, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (name, shift, score, shift_type, timestamp, timestamp))
        written += 1

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_boolean_preferences'")
    if cursor.fetchone():
        boolean_values = {}
        if preferences_record['reduced_rest_ok'] is not None:
            boolean_values['Reduced Rest OK'] = int(preferences_record['reduced_rest_ok'])
        if preferences_record['n_to_d_flex'] is not None:
            boolean_values['N to D Flex'] = str(preferences_record['n_to_d_flex'])

        for pref_name, value in boolean_values.items():
            if not overwrite:
                cursor.execute("""
                    SELECT COUNT(*) FROM user_boolean_preferences
                    WHERE staff_name = ? AND preference_name = ? AND is_active = 1
                """, (name, pref_name))
                if cursor.fetchone()[0]:
                    continue
            cursor.execute("""
                INSERT OR REPLACE INTO user_boolean_preferences
                (staff_name, preference_name, preference_value, created_date,
                 modified_date, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (name, pref_name, value, timestamp, timestamp))
            written += 1

    return written


def _ensure_preference_tables(report):
    """
    Make sure the in-app preference tables exist before seeding into them.

    modules.preference_editor owns that schema, so it creates them — but it always
    writes to the app's database, so it is only called when this import is targeting
    that same database. With a --db override (tests, a copy of the database) seeding is
    skipped rather than written to the wrong file.
    """
    conn = staffdb._get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences'")
    if cursor.fetchone():
        return True

    if staffdb.get_db_path() != staffdb.DEFAULT_DB_PATH:
        report['warnings'].append(
            "Shift-preference tables do not exist in this database and were not "
            "created (the import is not targeting the app database) — Preferences v6 "
            "shift scores were not seeded.")
        return False

    try:
        from .preference_editor import initialize_preference_tables
        initialize_preference_tables()
        return True
    except Exception as e:
        report['warnings'].append(
            f"Could not create the shift-preference tables ({e}) — Preferences v6 "
            "shift scores were not seeded.")
        return False


def import_staff_roster(roster_path=DEFAULT_ROSTER_PATH,
                        preferences_path=DEFAULT_PREFERENCES_PATH,
                        requirements_path=DEFAULT_REQUIREMENTS_PATH,
                        include_secondary_names=True,
                        update_existing=False,
                        seed_shift_preferences=True,
                        overwrite_shift_preferences=False,
                        dry_run=False,
                        changed_by='staff import'):
    """
    Import (or refresh) the staff roster from the Excel sources.

    Args:
        include_secondary_names (bool): also add staff found only in Tracks /
            Requirements / Preassignments, so nobody the app already references is
            missing from the roster. They are added with their role inferred from
            Preferences v6 when possible, and flagged in the report.
        update_existing (bool): update attributes of staff already on the roster.
            Off by default so a re-import never overwrites admin edits.
        seed_shift_preferences (bool): copy Preferences v6 shift scores and boolean
            answers into the in-app preference tables.
        overwrite_shift_preferences (bool): replace preferences a staff member has
            already saved in the app. Off by default.
        dry_run (bool): report what would change without writing anything.

    Returns:
        dict: report with keys added, updated, unchanged, skipped, errors, conflicts,
        warnings, preferences_seeded, secondary_only, missing_from_preferences,
        roster_count, dry_run.
    """
    report = {
        'added': [],
        'updated': [],
        'unchanged': [],
        'skipped': [],
        'errors': [],
        'conflicts': [],
        'warnings': [],
        'preferences_seeded': 0,
        'secondary_only': {},
        'missing_from_preferences': [],
        'missing_email': [],
        'roster_count': 0,
        'dry_run': bool(dry_run),
    }

    staffdb.initialize_staff_tables()

    roster_records, roster_error = read_roster_attributes(roster_path)
    if roster_error:
        report['errors'].append(roster_error)
        return report

    preferences_records, preferences_error = read_preferences_attributes(preferences_path)
    if preferences_error:
        # Not fatal: names and roster attributes still import, only seniority and
        # No Matrix are missing, and the admin can fill those in.
        report['warnings'].append(preferences_error)

    requirements_records, requirements_error = read_requirements_attributes(requirements_path)
    if requirements_error:
        report['warnings'].append(requirements_error)

    report['roster_count'] = len(roster_records)

    seen = set()
    merged = []
    for roster_record in roster_records:
        name = roster_record['staff_name']
        key = name.lower()
        if key in seen:
            report['warnings'].append(f"{name} appears more than once in the roster — "
                                      "used the first row.")
            continue
        seen.add(key)

        if not roster_record['role']:
            report['warnings'].append(
                f"{name} has no Role in the roster — imported without a role, set one "
                "in Staff Database admin.")

        record, conflicts = _merge_attributes(roster_record,
                                              preferences_records.get(name),
                                              requirements_records.get(name))
        report['conflicts'].extend(conflicts)
        merged.append(record)

    # Names the app references that the education roster doesn't list.
    if include_secondary_names:
        secondary = read_secondary_names()
        for name, sources in sorted(secondary.items()):
            if name.lower() in seen:
                continue
            preferences_record = preferences_records.get(name)
            requirements_record = requirements_records.get(name)
            inferred_role = ''
            if preferences_record:
                inferred_role = canonical_role(preferences_record['clinical_role'])
            report['secondary_only'][name] = sorted(set(sources))
            secondary_record = {
                'staff_name': name,
                'role': inferred_role,
                'is_management': 0,
                'is_dual': 1 if (preferences_record and
                                 preferences_record['clinical_role'] == 'dual') else 0,
                'is_educator_at': 0,
                'no_matrix': preferences_record['no_matrix'] if preferences_record else 0,
                'seniority': preferences_record['seniority'] if preferences_record else None,
            }
            for field in REQUIREMENTS_FIELDS:
                secondary_record[field] = (requirements_record[field]
                                           if requirements_record else None)
            merged.append(secondary_record)
            seen.add(name.lower())
            if not inferred_role:
                report['warnings'].append(
                    f"{name} was found in {', '.join(sorted(set(sources)))} but not in "
                    "the Education Classes Roster and has no role on file — imported "
                    "with no role, set one in Staff Database admin.")

    # Clinical staff with no Preferences v6 row have no seniority, which excludes them
    # from bid ordering — worth surfacing rather than discovering during a bid cycle.
    for record in merged:
        if record['role'] in ('NURSE', 'MEDIC') and record['seniority'] is None:
            report['missing_from_preferences'].append(record['staff_name'])
        if record['role'] in ('NURSE', 'MEDIC') and \
                record['shifts_per_pay_period'] is not None and not record['email']:
            report['missing_email'].append(record['staff_name'])

    for record in merged:
        name = record['staff_name']
        existing = staffdb.get_staff(name)

        if existing is None:
            if dry_run:
                report['added'].append(name)
                continue
            success, message = staffdb.add_staff(
                staff_name=name,
                # Never guess a role: an unknown one is imported as UNASSIGNED and
                # listed on the admin page for someone to set.
                role=record['role'] or staffdb.UNASSIGNED_ROLE,
                is_management=record['is_management'],
                is_dual=record['is_dual'],
                is_educator_at=record['is_educator_at'],
                no_matrix=record['no_matrix'],
                seniority=record['seniority'],
                shifts_per_pay_period=record['shifts_per_pay_period'],
                night_minimum=record['night_minimum'],
                weekend_minimum=record['weekend_minimum'],
                weekend_group=record['weekend_group'],
                email=record['email'],
                is_active=True,
                changed_by=changed_by,
                # Seniority uniqueness is enforced for hand edits; on import the
                # spreadsheet is the authority, and a duplicate there should be
                # reported rather than block the whole import.
                validate=False,
            )
            if success:
                report['added'].append(name)
            else:
                report['errors'].append(message)
            continue

        # Already on the roster. Two kinds of difference get handled differently:
        # a *fill* is a field the roster has nothing for yet (adding the requirements
        # columns to an existing database leaves them all empty), which is applied
        # regardless — filling a blank overwrites nothing. A *conflict* is a field where
        # the spreadsheet and the database both have a value and they disagree; that only
        # gets applied when the caller asked for it, so an admin's edit stands.
        fills = {}
        conflicts = {}
        for field in (['role', 'is_management', 'is_dual', 'is_educator_at', 'no_matrix',
                       'seniority'] + REQUIREMENTS_FIELDS):
            new_value = record[field]
            current = existing[field]
            if field in ['seniority'] + REQUIREMENTS_FIELDS:
                # Never clear a value by importing a blank over it.
                if new_value is None:
                    continue
                if current is None:
                    fills[field] = new_value
                elif current != new_value:
                    conflicts[field] = new_value
            elif field == 'role':
                if not new_value or canonical_role(current) == new_value:
                    continue
                if canonical_role(current) == staffdb.UNASSIGNED_ROLE:
                    fills[field] = new_value
                else:
                    conflicts[field] = new_value
            else:
                if bool(current) != bool(new_value):
                    conflicts[field] = bool(new_value)

        differences = dict(fills)
        if update_existing:
            differences.update(conflicts)

        if not differences and not conflicts:
            report['unchanged'].append(name)
            continue

        if not differences:
            report['skipped'].append({'staff_name': name, 'differences': conflicts})
            continue

        if not update_existing and conflicts:
            report['skipped'].append({'staff_name': name, 'differences': conflicts})

        if dry_run:
            report['updated'].append({'staff_name': name, 'differences': differences})
        else:
            success, message = staffdb.update_staff(name, changed_by=changed_by,
                                                    validate=False, **differences)
            if success:
                report['updated'].append({'staff_name': name, 'differences': differences})
            else:
                report['errors'].append(message)

    if seed_shift_preferences and not dry_run and preferences_records:
        _ensure_preference_tables(report)
        for name, preferences_record in preferences_records.items():
            if not preferences_record['shift_scores'] and \
                    preferences_record['reduced_rest_ok'] is None and \
                    preferences_record['n_to_d_flex'] is None:
                continue
            try:
                report['preferences_seeded'] += _seed_shift_preferences(
                    preferences_record, overwrite=overwrite_shift_preferences)
            except Exception as e:
                report['errors'].append(f"Error seeding preferences for {name}: {e}")
        try:
            staffdb._get_conn().commit()
        except Exception as e:
            report['errors'].append(f"Error saving seeded preferences: {e}")

    return report


def format_import_report(report):
    """Render an import report as plain text lines, for CLI output and admin display."""
    lines = []
    if report['dry_run']:
        lines.append("DRY RUN — nothing was written.")
    lines.append(f"Roster rows read: {report['roster_count']}")
    lines.append(f"Added: {len(report['added'])}")
    lines.append(f"Updated: {len(report['updated'])}")
    lines.append(f"Unchanged: {len(report['unchanged'])}")
    lines.append(f"Skipped (differ, update not requested): {len(report['skipped'])}")
    lines.append(f"Preference rows seeded: {report['preferences_seeded']}")

    if report['secondary_only']:
        lines.append("")
        lines.append("Added from other uploads (not in the Education Classes Roster):")
        for name, sources in report['secondary_only'].items():
            lines.append(f"  - {name} (found in {', '.join(sources)})")

    if report['missing_from_preferences']:
        lines.append("")
        lines.append("Clinical staff with no seniority on file "
                     "(excluded from bid ordering until set):")
        for name in report['missing_from_preferences']:
            lines.append(f"  - {name}")

    if report['missing_email']:
        lines.append("")
        lines.append("Bidding staff with no email on file "
                     "(cannot be auto-notified when their bid opens):")
        for name in report['missing_email']:
            lines.append(f"  - {name}")

    if report['conflicts']:
        lines.append("")
        lines.append("Conflicts between the two spreadsheets:")
        for conflict in report['conflicts']:
            lines.append(f"  - {conflict}")

    if report['skipped']:
        lines.append("")
        lines.append("Existing roster entries that differ from the spreadsheets:")
        for entry in report['skipped']:
            differences = ', '.join(f"{k} -> {v}" for k, v in entry['differences'].items())
            lines.append(f"  - {entry['staff_name']}: {differences}")

    if report['warnings']:
        lines.append("")
        lines.append("Warnings:")
        for warning in report['warnings']:
            lines.append(f"  - {warning}")

    if report['errors']:
        lines.append("")
        lines.append("Errors:")
        for error in report['errors']:
            lines.append(f"  - {error}")

    return lines
