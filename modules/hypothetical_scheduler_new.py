# modules/hypothetical_scheduler_new.py - UPDATED WITH ROLE-BASED RANKINGS
"""
UPDATED: New Hypothetical Scheduler Module with Role-Based Seniority Rankings
Now displays the ranking within the specific role group (nurses vs medics) rather than overall ranking
"""

import streamlit as st
import pandas as pd
import json
import sqlite3
import os
from .shift_definitions import day_shifts, night_shifts
from .db_utils import get_db_connection

# Maps each individual shift to its base short name (matches user_location_preferences keys)
_SHIFT_TO_BASE = {
    "D11H": "KMHT", "D11B": "KMHT",
    "D9L":  "KLWM", "LG":   "KLWM",
    "D7B":  "KBED", "GR":   "KBED",
    "D11M": "1B9",  "MG":   "1B9",
    "D7P":  "KPYM", "PG":   "KPYM",
    "N9L":  "KLWM",
    "N7B":  "KBED", "NG":   "KBED",
    "N7P":  "KPYM", "NP":   "KPYM",
}


def _load_all_base_preferences():
    """Return {staff_name: row_dict} for every staff member with base preferences."""
    from .db_utils import get_all_location_preferences
    success, results = get_all_location_preferences()
    if not success or not isinstance(results, list):
        return {}
    return {row['staff_name']: row for row in results}

def get_staff_seniority_rank(staff_name, preferences_df, staff_col_prefs, seniority_col):
    """
    Get the seniority rank for a staff member
    
    Args:
        staff_name (str): Name of the staff member
        preferences_df (DataFrame): Preferences DataFrame
        staff_col_prefs (str): Column name for staff
        seniority_col (str): Column name for seniority
        
    Returns:
        int: Seniority rank (1 = most senior)
    """
    try:
        staff_info = preferences_df[preferences_df[staff_col_prefs] == staff_name]
        if not staff_info.empty:
            return int(staff_info.iloc[0][seniority_col])
        return 999  # Default to low seniority if not found
    except:
        return 999

def get_staff_role_based_ranking(staff_name, preferences_df, staff_col_prefs, role_col, seniority_col):
    """
    NEW: Calculate role-based seniority ranking for a staff member
    
    Args:
        staff_name (str): Name of the staff member
        preferences_df (DataFrame): Preferences DataFrame
        staff_col_prefs (str): Column name for staff
        role_col (str): Column name for role
        seniority_col (str): Column name for seniority
        
    Returns:
        dict: Contains overall_rank, role_rank, role, total_in_role
    """
    try:
        # Get the staff member's role and overall seniority
        staff_info = preferences_df[preferences_df[staff_col_prefs] == staff_name]
        if staff_info.empty:
            return {
                'overall_rank': 999,
                'role_rank': 999,
                'role': 'unknown',
                'total_in_role': 0,
                'effective_role': 'nurse'
            }
        
        staff_role = staff_info.iloc[0][role_col]
        staff_seniority = int(staff_info.iloc[0][seniority_col])
        effective_role = "nurse" if staff_role == "dual" else staff_role
        
        # Fully vectorized: compute effective roles for all staff at once, then filter
        _eff_roles = preferences_df[role_col].apply(lambda r: "nurse" if r == "dual" else r)
        _filtered = preferences_df[_eff_roles == effective_role]
        same_role_staff = (
            _filtered[[staff_col_prefs, seniority_col, role_col]]
            .rename(columns={staff_col_prefs: 'name', seniority_col: 'seniority', role_col: 'role'})
            .assign(seniority=lambda df: df['seniority'].astype(int))
            .to_dict('records')
        )
        
        # Sort by seniority (1 = most senior)
        same_role_staff.sort(key=lambda x: x['seniority'])
        
        # Find the rank within this role group
        role_rank = None
        for i, staff in enumerate(same_role_staff):
            if staff['name'] == staff_name:
                role_rank = i + 1  # 1-based ranking
                break
        
        return {
            'overall_rank': staff_seniority,
            'role_rank': role_rank if role_rank else 999,
            'role': staff_role,
            'effective_role': effective_role,
            'total_in_role': len(same_role_staff)
        }
    
    except Exception as e:
        print(f"Error calculating role-based ranking: {e}")
        return {
            'overall_rank': 999,
            'role_rank': 999,
            'role': 'unknown',
            'total_in_role': 0,
            'effective_role': 'nurse'
        }

def get_staff_shift_preferences(staff_name, preferences_df, staff_col_prefs, shift_type):
    """
    Get shift preferences for a staff member
    
    Args:
        staff_name (str): Name of the staff member
        preferences_df (DataFrame): Preferences DataFrame
        staff_col_prefs (str): Column name for staff
        shift_type (str): "day" or "night"
        
    Returns:
        dict: Dictionary of shift -> preference score
    """
    try:
        staff_info = preferences_df[preferences_df[staff_col_prefs] == staff_name]
        if staff_info.empty:
            return {}
        
        staff_row = staff_info.iloc[0]
        shift_dict = day_shifts if shift_type == "day" else night_shifts
        
        preferences = {}
        for shift_name in shift_dict.keys():
            if shift_name in staff_row.index and pd.notna(staff_row[shift_name]):
                preferences[shift_name] = staff_row[shift_name]
        
        return preferences
    except:
        return {}

def get_staff_on_shift_from_database(day, shift_type, preferences_df, staff_col_prefs, role_col):
    """
    FIXED: Get staff assigned to a specific day and shift type from database
    Properly handles day name format variations
    
    Args:
        day (str): The day to check  
        shift_type (str): "D" for day or "N" for night
        preferences_df (DataFrame): Preferences DataFrame
        staff_col_prefs (str): Column name for staff
        role_col (str): Column name for role
        
    Returns:
        list: List of staff names assigned to this SPECIFIC shift type
    """
    try:
        db_path = 'data/medflight_tracks.db'
        if not os.path.exists(db_path):
            return []
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT staff_name, track_data 
            FROM tracks 
            WHERE is_active = 1
        """)
        
        results = cursor.fetchall()
        conn.close()
        
        staff_on_shift = []
        for staff_name, track_json in results:
            try:
                track_data = json.loads(track_json)
                
                # FIXED: Generate proper day name variations
                day_variants = generate_day_name_variants(day)
                
                # Check each variant
                for day_variant in day_variants:
                    if day_variant in track_data and track_data[day_variant] == shift_type:
                        staff_on_shift.append(staff_name)
                        break  # Found a match, no need to check other variants
                        
            except:
                continue
        
        return staff_on_shift
    except:
        return []

def generate_day_name_variants(day):
    """
    Generate all possible day name format variations
    
    Args:
        day (str): Input day name (e.g., "Mon A 1", "Mon A1", "MonA1")
        
    Returns:
        list: All possible variants of the day name
    """
    import re
    
    # Start with the original day name
    variants = [day]
    
    # Pattern to match day names: (Day) (Block)(Number) or (Day) (Block) (Number)
    # Examples: "Mon A1", "Mon A 1", "MonA1", "MonA 1"
    
    # Extract components using regex
    pattern = r'^(\w{3})\s*([ABC])\s*(\d+)$'
    match = re.match(pattern, day)
    
    if match:
        day_name, block_letter, number = match.groups()
        
        # Generate all possible combinations:
        possible_formats = [
            f"{day_name}{block_letter}{number}",           # "MonA1"
            f"{day_name} {block_letter}{number}",          # "Mon A1"  
            f"{day_name}{block_letter} {number}",          # "MonA 1"
            f"{day_name} {block_letter} {number}",         # "Mon A 1"
        ]
        
        # Add all unique formats
        for variant in possible_formats:
            if variant not in variants:
                variants.append(variant)
    
    # Remove duplicates while preserving order
    return list(dict.fromkeys(variants))

# Test the function
def test_day_variants():
    """Test the day variant generation"""
    test_cases = [
        "Mon A 1",
        "Mon A1", 
        "MonA1",
        "MonA 1",
        "Tue B 3",
        "Wed C 5"
    ]
    
    for test_day in test_cases:
        variants = generate_day_name_variants(test_day)
        print(f"Input: '{test_day}' -> Variants: {variants}")

# Example output:
# Input: 'Mon A 1' -> Variants: ['Mon A 1', 'MonA1', 'Mon A1', 'MonA 1']
# Input: 'Mon A1' -> Variants: ['Mon A1', 'MonA1', 'MonA 1', 'Mon A 1']

def get_staff_on_shift_from_excel(day, shift_type, current_tracks_df, staff_col_tracks):
    """
    Get staff assigned to a specific day and shift type from Excel file
    
    Args:
        day (str): The day to check
        shift_type (str): "D" for day or "N" for night
        current_tracks_df (DataFrame): Current tracks DataFrame
        staff_col_tracks (str): Column name for staff
        
    Returns:
        list: List of staff names assigned to this SPECIFIC shift type
    """
    try:
        staff_on_shift = current_tracks_df[current_tracks_df[day] == shift_type][staff_col_tracks].tolist()
        return staff_on_shift
    except:
        return []

def get_staff_role_for_counting(staff_name, preferences_df, staff_col_prefs, role_col):
    """
    Get the effective role for a staff member for counting purposes
    
    Args:
        staff_name (str): Name of the staff member
        preferences_df (DataFrame): Preferences DataFrame
        staff_col_prefs (str): Column name for staff
        role_col (str): Column name for role
        
    Returns:
        str: "nurse" or "medic" (dual becomes nurse)
    """
    try:
        staff_info = preferences_df[preferences_df[staff_col_prefs] == staff_name]
        if not staff_info.empty:
            role = staff_info.iloc[0][role_col]
            return "nurse" if role == "dual" else role
        return "nurse"  # Default
    except:
        return "nurse"

def calculate_hypothetical_assignment(
    selected_staff, day, shift_type, preferences_df, current_tracks_df,
    staff_col_prefs, staff_col_tracks, role_col, seniority_col, use_database_logic,
    all_base_prefs=None
):
    """
    Simulate seniority-based shift assignment using base preferences.
    all_base_prefs: {staff_name: row_dict} pre-loaded from user_location_preferences.
    Returns assignment as base short name (e.g. "KBED"), preference_score as rank int.
    """
    from .shift_definitions import day_shifts, night_shifts

    # Step 1: Get staff currently assigned to this shift type
    if use_database_logic:
        staff_on_shift = get_staff_on_shift_from_database(
            day, "D" if shift_type == "day" else "N",
            preferences_df, staff_col_prefs, role_col
        )
    else:
        staff_on_shift = get_staff_on_shift_from_excel(
            day, "D" if shift_type == "day" else "N",
            current_tracks_df, staff_col_tracks
        )

    if selected_staff not in staff_on_shift:
        staff_on_shift.append(selected_staff)

    # Step 2: Filter to same effective role
    selected_staff_role = get_staff_role_for_counting(selected_staff, preferences_df, staff_col_prefs, role_col)
    staff_same_role = [
        s for s in staff_on_shift
        if get_staff_role_for_counting(s, preferences_df, staff_col_prefs, role_col) == selected_staff_role
    ]

    # Step 3: Sort by seniority
    staff_with_seniority = sorted(
        [(s, get_staff_seniority_rank(s, preferences_df, staff_col_prefs, seniority_col)) for s in staff_same_role],
        key=lambda x: x[1]
    )

    # Step 4: Role-based ranking for display
    role_ranking_info = get_staff_role_based_ranking(
        selected_staff, preferences_df, staff_col_prefs, role_col, seniority_col
    )

    selected_position = next(
        (i for i, (s, _) in enumerate(staff_with_seniority) if s == selected_staff), None
    )

    # Step 5: Max slots and available shifts
    if shift_type == "day":
        max_shifts = 10
        available_shifts = list(day_shifts.keys())
        location_key = 'day_locations'
        max_rank = 5
    else:
        max_shifts = 6 if selected_staff_role == "nurse" else 5
        available_shifts = list(night_shifts.keys())
        location_key = 'night_locations'
        max_rank = 3

    if len(staff_with_seniority) > max_shifts:
        if selected_position is not None and selected_position >= max_shifts:
            staff_base_data = (all_base_prefs or {}).get(selected_staff)
            return {
                'assignment': None,
                'reason': (
                    f"No shift available — {len(staff_with_seniority)} {selected_staff_role}s "
                    f"compete for {max_shifts} {shift_type} shifts, you rank #{selected_position + 1}"
                ),
                'preference_score': None,
                'no_preference_data': staff_base_data is None,
                'role_ranking_info': role_ranking_info,
                'competition_rank': selected_position + 1,
                'total_competitors': len(staff_with_seniority)
            }

    # Step 6: Simulate full competition using base preferences
    assigned_shifts = {}
    selected_staff_result = None
    assignment_log = []

    for staff, seniority in staff_with_seniority:
        if not available_shifts:
            if staff == selected_staff:
                selected_staff_result = {
                    'assignment': None,
                    'reason': (
                        f"No shifts remaining — all {max_shifts} {shift_type} shifts "
                        f"assigned to more senior {selected_staff_role}s"
                    ),
                    'preference_score': None,
                    'no_preference_data': False,
                    'role_ranking_info': role_ranking_info,
                    'competition_rank': selected_position + 1 if selected_position is not None else 999,
                    'total_competitors': len(staff_with_seniority)
                }
            continue

        # Look up base preferences for this staff member
        staff_base_data = (all_base_prefs or {}).get(staff)
        has_base_prefs = staff_base_data is not None

        if has_base_prefs:
            locations = staff_base_data.get(location_key, {})
            # Score = max_rank + 1 - rank  (rank 1 → highest score, competing for most-preferred base first)
            shift_scores = {
                shift: (max_rank + 1 - locations[_SHIFT_TO_BASE[shift]])
                for shift in available_shifts
                if _SHIFT_TO_BASE.get(shift) in locations and locations.get(_SHIFT_TO_BASE.get(shift)) is not None
            }

            if shift_scores:
                best_shift = max(shift_scores.items(), key=lambda x: x[1])
                shift_name = best_shift[0]
                base_short = _SHIFT_TO_BASE.get(shift_name, shift_name)
                preference_rank = locations.get(base_short)

                assigned_shifts[staff] = {'shift': shift_name, 'preference': preference_rank}
                available_shifts.remove(shift_name)
                assignment_log.append(f"{staff} → {base_short} ({shift_name}, Rank {preference_rank})")

                if staff == selected_staff:
                    selected_staff_result = {
                        'assignment': base_short,
                        'reason': (
                            f"Assigned to {base_short} ({shift_name}, Rank {preference_rank}, "
                            f"role rank: {role_ranking_info['role_rank']}/{role_ranking_info['total_in_role']})"
                        ),
                        'preference_score': preference_rank,
                        'no_preference_data': False,
                        'role_ranking_info': role_ranking_info,
                        'competition_rank': selected_position + 1 if selected_position is not None else 999,
                        'total_competitors': len(staff_with_seniority),
                        'debug_assignments': assignment_log
                    }
            else:
                # Base prefs exist but none match remaining shifts — take first available
                shift_name = available_shifts[0]
                base_short = _SHIFT_TO_BASE.get(shift_name, shift_name)
                assigned_shifts[staff] = {'shift': shift_name, 'preference': None}
                available_shifts.remove(shift_name)
                assignment_log.append(f"{staff} → {base_short} ({shift_name}, no preferred base available)")

                if staff == selected_staff:
                    selected_staff_result = {
                        'assignment': base_short,
                        'reason': (
                            f"Assigned to {base_short} ({shift_name}, preferred bases unavailable, "
                            f"role rank: {role_ranking_info['role_rank']}/{role_ranking_info['total_in_role']})"
                        ),
                        'preference_score': None,
                        'no_preference_data': False,
                        'role_ranking_info': role_ranking_info,
                        'competition_rank': selected_position + 1 if selected_position is not None else 999,
                        'total_competitors': len(staff_with_seniority),
                        'debug_assignments': assignment_log
                    }
        else:
            # No base preferences — take first available shift
            shift_name = available_shifts[0]
            base_short = _SHIFT_TO_BASE.get(shift_name, shift_name)
            assigned_shifts[staff] = {'shift': shift_name, 'preference': None}
            available_shifts.remove(shift_name)
            assignment_log.append(f"{staff} → {base_short} ({shift_name}, no base prefs)")

            if staff == selected_staff:
                selected_staff_result = {
                    'assignment': base_short,
                    'reason': (
                        f"Assigned to {base_short} ({shift_name}, no base preferences set, "
                        f"role rank: {role_ranking_info['role_rank']}/{role_ranking_info['total_in_role']})"
                    ),
                    'preference_score': None,
                    'no_preference_data': True,
                    'role_ranking_info': role_ranking_info,
                    'competition_rank': selected_position + 1 if selected_position is not None else 999,
                    'total_competitors': len(staff_with_seniority),
                    'debug_assignments': assignment_log
                }

    # Step 7: Return result after full simulation
    if selected_staff_result:
        return selected_staff_result

    return {
        'assignment': None,
        'reason': "Assignment calculation error",
        'preference_score': None,
        'no_preference_data': False,
        'role_ranking_info': role_ranking_info,
        'competition_rank': selected_position + 1 if selected_position is not None else 999,
        'total_competitors': len(staff_with_seniority)
    }

def generate_hypothetical_schedule_new(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, seniority_col
):
    """
    Generate a hypothetical schedule using base preferences (user_location_preferences).
    Base prefs are loaded once and passed into each per-day competition.
    """
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"

    # Load all staff base preferences once to avoid per-staff DB queries in the loop
    all_base_prefs = _load_all_base_preferences()

    day_assignments = {}
    night_assignments = {}
    assignment_details = {}

    role_ranking_info = get_staff_role_based_ranking(
        selected_staff, preferences_df, staff_col_prefs, role_col, seniority_col
    )

    for day in days:
        day_result = calculate_hypothetical_assignment(
            selected_staff, day, "day", preferences_df, current_tracks_df,
            staff_col_prefs, staff_col_tracks, role_col, seniority_col,
            use_database_logic, all_base_prefs
        )

        night_result = calculate_hypothetical_assignment(
            selected_staff, day, "night", preferences_df, current_tracks_df,
            staff_col_prefs, staff_col_tracks, role_col, seniority_col,
            use_database_logic, all_base_prefs
        )

        day_assignments[day] = day_result['assignment']
        night_assignments[day] = night_result['assignment']

        assignment_details[day] = {
            'day': {
                'assignment': day_result['assignment'],
                'reason': day_result['reason'],
                'preference_score': day_result['preference_score'],
                'no_preference_data': day_result.get('no_preference_data', False),
                'role_ranking_info': day_result['role_ranking_info'],
                'competition_rank': day_result.get('competition_rank'),
                'total_competitors': day_result.get('total_competitors')
            },
            'night': {
                'assignment': night_result['assignment'],
                'reason': night_result['reason'],
                'preference_score': night_result['preference_score'],
                'no_preference_data': night_result.get('no_preference_data', False),
                'role_ranking_info': night_result['role_ranking_info'],
                'competition_rank': night_result.get('competition_rank'),
                'total_competitors': night_result.get('total_competitors')
            }
        }

    return {
        'day_assignments': day_assignments,
        'night_assignments': night_assignments,
        'assignment_details': assignment_details,
        'role_ranking_info': role_ranking_info,
        'use_database_logic': use_database_logic
    }

def display_hypothetical_results_new(results, selected_staff, days):
    """
    Display hypothetical scheduler results with enhanced formatting
    UPDATED: Now includes "*requires a swap, fully staffed" notation for shifts at max capacity
    """
    # Get role information for the selected staff
    role_ranking_info = results.get('role_ranking_info', {})
    
    # Display role competition info
    if role_ranking_info.get('role') == 'dual':
        st.info(f"💡 **Role Competition**: As a dual-trained provider, you compete with nurses for nursing positions. Your rank among the {role_ranking_info['total_in_role']} nurses/dual staff is **#{role_ranking_info['role_rank']}**.")
    else:
        st.info(f"💡 **Role Competition**: You compete with other {role_ranking_info['effective_role']}s for {role_ranking_info['effective_role']} positions. Your rank among the {role_ranking_info['total_in_role']} {role_ranking_info['effective_role']}s is **#{role_ranking_info['role_rank']}**.")
    
    # Get assignments and details
    day_assignments = results['day_assignments']
    night_assignments = results['night_assignments']
    assignment_details = results['assignment_details']
    
    # Get the selected staff's effective role for capacity checking
    selected_staff_role = role_ranking_info.get('role', 'nurse')
    effective_role = role_ranking_info.get('effective_role', 'nurse')
    
    # Create summary statistics
    total_day_shifts = sum(1 for assignment in day_assignments.values() if assignment)
    total_night_shifts = sum(1 for assignment in night_assignments.values() if assignment)
    total_shifts = total_day_shifts + total_night_shifts
    
    # Display summary
    with st.expander("Schedule Summary", expanded=True):
        cols = st.columns(4)
        cols[0].metric("Total Shifts", total_shifts)
        cols[1].metric("Day Shifts", total_day_shifts)
        cols[2].metric("Night Shifts", total_night_shifts)
        cols[3].metric(f"Role Rank", f"{role_ranking_info['role_rank']}/{role_ranking_info['total_in_role']}")
    
    # Create schedule table by blocks
    blocks = ["A", "B", "C"]
    block_tabs = st.tabs([f"Block {block}" for block in blocks])
    
    for block_idx, block_tab in enumerate(block_tabs):
        with block_tab:
            start_idx = block_idx * 14
            end_idx = start_idx + 14
            block_days = days[start_idx:end_idx]
            
            # Create table data
            table_data = []
            
            for day in block_days:
                day_assignment = day_assignments.get(day)
                night_assignment = night_assignments.get(day)
                
                day_details = assignment_details.get(day, {}).get('day', {})
                night_details = assignment_details.get(day, {}).get('night', {})
                
                # Get staffing analysis for capacity checking (may not exist in basic hypothetical scheduler)
                day_staffing = day_details.get('staffing_analysis', {})
                night_staffing = night_details.get('staffing_analysis', {})
                
                # Check if shifts are at max capacity for the selected staff's role
                day_at_max = False
                night_at_max = False
                
                # Only check if staffing analysis exists (enhanced version)
                if day_staffing:
                    if effective_role == "nurse":
                        day_at_max = day_staffing.get('nurse_needs', 1) <= 0
                    else:  # medic
                        day_at_max = day_staffing.get('medic_needs', 1) <= 0
                
                if night_staffing:
                    if effective_role == "nurse":
                        night_at_max = night_staffing.get('nurse_needs', 1) <= 0
                    else:  # medic
                        night_at_max = night_staffing.get('medic_needs', 1) <= 0
                
                # Format day shift info
                day_info = "None"
                if day_assignment:
                    pref = day_details.get('preference_score')
                    no_pref = day_details.get('no_preference_data', False)
                    if pref:
                        day_info = f"{day_assignment} (Rank {pref})"
                    elif no_pref:
                        day_info = f"{day_assignment} (Rank *)"
                    else:
                        day_info = f"{day_assignment} (unranked)"
                    
                    # Add fully staffed notation if at max capacity
                    if day_at_max:
                        day_info += " *requires a swap, fully staffed"
                
                # Format night shift info
                night_info = "None"
                if night_assignment:
                    pref = night_details.get('preference_score')
                    no_pref = night_details.get('no_preference_data', False)
                    if pref:
                        night_info = f"{night_assignment} (Rank {pref})"
                    elif no_pref:
                        night_info = f"{night_assignment} (Rank *)"
                    else:
                        night_info = f"{night_assignment} (unranked)"
                    
                    # Add fully staffed notation if at max capacity
                    if night_at_max:
                        night_info += " *requires a swap, fully staffed"
                
                table_data.append({
                    "Day": day,
                    "Day Shift": day_info,
                    "Day Reason": day_details.get('reason', ''),
                    "Night Shift": night_info,
                    "Night Reason": night_details.get('reason', '')
                })
            
            # Display table
            df = pd.DataFrame(table_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Display updated explanation
    st.markdown(f"""
    ### How Hypothetical Assignments Work
    
    1. **Role-Based Competition**: {role_ranking_info['effective_role'].title()}s compete separately for their positions
       - Day shifts: 10 positions each for nurses and medics
       - Night shifts: 6 positions for nurses, 5 for medics
    
    2. **Your Role Ranking**: Among {role_ranking_info['total_in_role']} {role_ranking_info['effective_role']}s, you rank **#{role_ranking_info['role_rank']}** by seniority
    
    3. **Assignment Process**: Starting with the most senior {role_ranking_info['effective_role']}, each person picks their highest-ranked available base

    4. **Base Rank**: Rank 1 = most preferred base, higher numbers = less preferred. "*" means no base preferences are on file.

    5. **Your Turn**: When it's your turn (position #{role_ranking_info['role_rank']}), you get your highest-ranked base still available
    
    6. **Fully Staffed Notation**: "*requires a swap, fully staffed" indicates that the shift is at maximum capacity for your role ({effective_role}s) and would require a swap with another {effective_role} to obtain
    
    **Note**: This simulation shows assignments based purely on seniority and preference within your role group. It doesn't consider rest requirements, leave time, or other scheduling constraints.
    
    **Role Details**: {'Dual-trained staff compete as nurses for nursing positions.' if role_ranking_info['role'] == 'dual' else f"You compete with other {role_ranking_info['effective_role']}s for {role_ranking_info['effective_role']} positions."}
    """)

def display_hypothetical_scheduler_interface_new(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, seniority_col
):
    """
    Display the new hypothetical scheduler interface
    UPDATED: Now includes role-based ranking information
    """
    st.subheader(f"Hypothetical Schedule for {selected_staff}")
    
    # Generate the hypothetical schedule
    with st.spinner("Calculating hypothetical assignments based on role-specific seniority rankings..."):
        results = generate_hypothetical_schedule_new(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, seniority_col
        )
        
        # Display the results
        display_hypothetical_results_new(results, selected_staff, days)