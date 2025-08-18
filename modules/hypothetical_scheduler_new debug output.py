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
        
        # Get all staff with the same effective role
        same_role_staff = []
        for _, row in preferences_df.iterrows():
            row_role = row[role_col]
            row_effective_role = "nurse" if row_role == "dual" else row_role
            
            if row_effective_role == effective_role:
                same_role_staff.append({
                    'name': row[staff_col_prefs],
                    'seniority': int(row[seniority_col]),
                    'role': row_role
                })
        
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

# Debug enhancement for calculate_hypothetical_assignment function
# Add this debugging code to track shift assignments

def calculate_hypothetical_assignment(
    selected_staff, day, shift_type, preferences_df, current_tracks_df,
    staff_col_prefs, staff_col_tracks, role_col, seniority_col, use_database_logic
):
    """
    Enhanced version with debugging to track shift assignments
    """
    # Import the shift definitions
    from .shift_definitions import day_shifts, night_shifts
    
    # Step 1: Get staff currently assigned to this SPECIFIC shift type
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
    
    # Add selected staff to the list if not already there
    if selected_staff not in staff_on_shift:
        staff_on_shift.append(selected_staff)
    
    # Step 2: Filter by role if needed (nurses vs medics)
    selected_staff_role = get_staff_role_for_counting(selected_staff, preferences_df, staff_col_prefs, role_col)
    
    # Only include staff of the same effective role for competition
    staff_same_role = []
    for staff in staff_on_shift:
        staff_role = get_staff_role_for_counting(staff, preferences_df, staff_col_prefs, role_col)
        if staff_role == selected_staff_role:
            staff_same_role.append(staff)
    
    # Step 3: Rank staff by seniority (1 = most senior)
    staff_with_seniority = []
    for staff in staff_same_role:
        seniority = get_staff_seniority_rank(staff, preferences_df, staff_col_prefs, seniority_col)
        staff_with_seniority.append((staff, seniority))
    
    # Sort by seniority (ascending - 1 is most senior)
    staff_with_seniority.sort(key=lambda x: x[1])
    
    # DEBUG: Print competition details
    if selected_staff in ["Kilduff", "Young"]:
        print(f"\n=== DEBUG: {day} {shift_type} shift competition ===")
        print(f"Selected staff: {selected_staff}")
        print(f"Staff competing: {[s[0] for s in staff_with_seniority]}")
        print(f"Seniority order: {staff_with_seniority}")
    
    # Step 4: Calculate role-based ranking for selected staff
    role_ranking_info = get_staff_role_based_ranking(
        selected_staff, preferences_df, staff_col_prefs, role_col, seniority_col
    )
    
    # Find position of selected staff in this specific competition
    selected_position = None
    for i, (staff, _) in enumerate(staff_with_seniority):
        if staff == selected_staff:
            selected_position = i
            break
    
    # Step 5: Determine max shifts available for this role
    if shift_type == "day":
        if selected_staff_role == "nurse":
            max_shifts = 10  # Max day shift nurses
        else:  # medic
            max_shifts = 10  # Max day shift medics
        available_shifts = list(day_shifts.keys())
    else:  # night
        if selected_staff_role == "nurse":
            max_shifts = 6   # Max night shift nurses  
        else:  # medic
            max_shifts = 5   # Max night shift medics
        available_shifts = list(night_shifts.keys())
    
    # Check if we exceed max shifts for this role
    if len(staff_with_seniority) > max_shifts:
        if selected_position is not None and selected_position >= max_shifts:
            return {
                'assignment': None,
                'reason': f"No shift available - {len(staff_with_seniority)} {selected_staff_role}s compete for {max_shifts} {shift_type} shifts, you rank #{selected_position + 1} in this competition",
                'preference_score': None,
                'role_ranking_info': role_ranking_info,
                'competition_rank': selected_position + 1,
                'total_competitors': len(staff_with_seniority)
            }
    
    # Step 6: Complete full simulation - assign shifts to ALL staff based on seniority
    assigned_shifts = {}
    selected_staff_result = None
    
    # DEBUG: Track assignments
    assignment_log = []
    
    for staff, seniority in staff_with_seniority:
        if not available_shifts:  # No more shifts available
            # If this is our selected staff and no shifts remain
            if staff == selected_staff:
                selected_staff_result = {
                    'assignment': None,
                    'reason': f"No shifts remaining - all {max_shifts} {shift_type} shifts assigned to more senior {selected_staff_role}s",
                    'preference_score': None,
                    'role_ranking_info': role_ranking_info,
                    'competition_rank': selected_position + 1 if selected_position is not None else 999,
                    'total_competitors': len(staff_with_seniority)
                }
            continue
        
        # Get staff preferences for this shift type
        staff_preferences = get_staff_shift_preferences(
            staff, preferences_df, staff_col_prefs, shift_type
        )
        
        # DEBUG: Show preferences for key staff
        if staff in ["Kilduff", "Young"]:
            print(f"\n{staff}'s preferences: {staff_preferences}")
            print(f"Available shifts before assignment: {available_shifts}")
        
        if staff_preferences:
            # Find highest preference shift that's still available
            available_prefs = {shift: pref for shift, pref in staff_preferences.items() 
                             if shift in available_shifts}
            
            if available_prefs:
                # Assign to highest preference available shift
                best_shift = max(available_prefs.items(), key=lambda x: x[1])
                shift_name = best_shift[0]
                preference_score = best_shift[1]
                
                assigned_shifts[staff] = {
                    'shift': shift_name,
                    'preference': preference_score
                }
                available_shifts.remove(shift_name)
                
                # DEBUG: Log assignment
                assignment_log.append(f"{staff} assigned to {shift_name} (pref: {preference_score})")
                if staff in ["Kilduff", "Young"]:
                    print(f"ASSIGNED: {staff} -> {shift_name} (preference: {preference_score})")
                    print(f"Remaining shifts: {available_shifts}")
                
                # Store result for selected staff (DON'T return yet - continue simulation)
                if staff == selected_staff:
                    selected_staff_result = {
                        'assignment': shift_name,
                        'reason': f"Assigned to {shift_name} (preference: {preference_score}, role rank: {role_ranking_info['role_rank']}/{role_ranking_info['total_in_role']})",
                        'preference_score': preference_score,
                        'role_ranking_info': role_ranking_info,
                        'competition_rank': selected_position + 1 if selected_position is not None else 999,
                        'total_competitors': len(staff_with_seniority),
                        'debug_assignments': assignment_log  # Add debug info
                    }
            else:
                # No preferences for available shifts, assign first available
                shift_name = available_shifts[0]
                assigned_shifts[staff] = {
                    'shift': shift_name,
                    'preference': None
                }
                available_shifts.remove(shift_name)
                
                # Store result for selected staff (DON'T return yet - continue simulation)
                if staff == selected_staff:
                    selected_staff_result = {
                        'assignment': shift_name,
                        'reason': f"Assigned to {shift_name} (no preference for available shifts, role rank: {role_ranking_info['role_rank']}/{role_ranking_info['total_in_role']})",
                        'preference_score': None,
                        'role_ranking_info': role_ranking_info,
                        'competition_rank': selected_position + 1 if selected_position is not None else 999,
                        'total_competitors': len(staff_with_seniority),
                        'debug_assignments': assignment_log  # Add debug info
                    }
        else:
            # No preferences at all, assign first available
            shift_name = available_shifts[0]
            assigned_shifts[staff] = {
                'shift': shift_name,
                'preference': None
            }
            available_shifts.remove(shift_name)
            
            # Store result for selected staff (DON'T return yet - continue simulation)
            if staff == selected_staff:
                selected_staff_result = {
                    'assignment': shift_name,
                    'reason': f"Assigned to {shift_name} (no preferences data, role rank: {role_ranking_info['role_rank']}/{role_ranking_info['total_in_role']})",
                    'preference_score': None,
                    'role_ranking_info': role_ranking_info,
                    'competition_rank': selected_position + 1 if selected_position is not None else 999,
                    'total_competitors': len(staff_with_seniority),
                    'debug_assignments': assignment_log  # Add debug info
                }
    
    # DEBUG: Print final assignments
    if selected_staff in ["Kilduff", "Young"]:
        print(f"\n=== FINAL ASSIGNMENTS for {day} {shift_type} ===")
        for s, details in assigned_shifts.items():
            print(f"{s}: {details['shift']} (pref: {details['preference']})")
        print("=" * 50)
    
    # Step 7: Return result AFTER completing full simulation
    if selected_staff_result:
        return selected_staff_result
    
    # If we get here, something went wrong
    return {
        'assignment': None,
        'reason': "Assignment calculation error",
        'preference_score': None,
        'role_ranking_info': role_ranking_info,
        'competition_rank': selected_position + 1 if selected_position is not None else 999,
        'total_competitors': len(staff_with_seniority)
    }

def generate_hypothetical_schedule_new(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, seniority_col
):
    """
    Generate a hypothetical schedule for a staff member using the new simplified logic
    UPDATED: Now includes role-based ranking information
    """
    # Check track source
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
    
    # Initialize results
    day_assignments = {}
    night_assignments = {}
    assignment_details = {}
    
    # Get role-based ranking information for the staff member
    role_ranking_info = get_staff_role_based_ranking(
        selected_staff, preferences_df, staff_col_prefs, role_col, seniority_col
    )
    
    # Process each day
    for day in days:
        # Calculate day shift assignment
        day_result = calculate_hypothetical_assignment(
            selected_staff, day, "day", preferences_df, current_tracks_df,
            staff_col_prefs, staff_col_tracks, role_col, seniority_col, use_database_logic
        )
        
        # Calculate night shift assignment
        night_result = calculate_hypothetical_assignment(
            selected_staff, day, "night", preferences_df, current_tracks_df,
            staff_col_prefs, staff_col_tracks, role_col, seniority_col, use_database_logic
        )
        
        # Store results
        day_assignments[day] = day_result['assignment']
        night_assignments[day] = night_result['assignment']
        
        assignment_details[day] = {
            'day': {
                'assignment': day_result['assignment'],
                'reason': day_result['reason'],
                'preference_score': day_result['preference_score'],
                'role_ranking_info': day_result['role_ranking_info'],
                'competition_rank': day_result.get('competition_rank'),
                'total_competitors': day_result.get('total_competitors')
            },
            'night': {
                'assignment': night_result['assignment'],
                'reason': night_result['reason'],
                'preference_score': night_result['preference_score'],
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
    Display the hypothetical schedule results
    UPDATED: Now shows role-based ranking instead of overall ranking
    """
    st.header(f"Hypothetical Schedule for {selected_staff}")
    
    # Display role-based ranking information
    role_ranking_info = results['role_ranking_info']
    use_database_logic = results['use_database_logic']
    
    # Create enhanced ranking display
    ranking_cols = st.columns(4)
    
    with ranking_cols[0]:
        st.metric(
            f"Rank Among {role_ranking_info['effective_role'].title()}s", 
            f"{role_ranking_info['role_rank']} of {role_ranking_info['total_in_role']}",
            help=f"Your ranking among all {role_ranking_info['effective_role']}s by seniority"
        )
    
    with ranking_cols[1]:
        st.metric(
            "Your Role", 
            role_ranking_info['role'].title(),
            help="Your assigned role (dual staff compete as nurses)"
        )
    
    with ranking_cols[2]:
        st.metric(
            "Overall Seniority Rank", 
            role_ranking_info['overall_rank'],
            help="Your rank among all staff by hire date"
        )
    
    with ranking_cols[3]:
        st.metric(
            "Mode", 
            'Annual Rebid' if use_database_logic else 'Current Track Changes',
            help="Assignment calculation mode being used"
        )
    
    # Add explanation of role-based ranking
    if role_ranking_info['role'] == 'dual':
        st.info(f"💡 **Role Competition**: As a dual-trained provider, you compete with nurses for nursing positions. Your rank among the {role_ranking_info['total_in_role']} nurses/dual staff is **#{role_ranking_info['role_rank']}**.")
    else:
        st.info(f"💡 **Role Competition**: You compete with other {role_ranking_info['effective_role']}s for {role_ranking_info['effective_role']} positions. Your rank among the {role_ranking_info['total_in_role']} {role_ranking_info['effective_role']}s is **#{role_ranking_info['role_rank']}**.")
    
    # Get assignments and details
    day_assignments = results['day_assignments']
    night_assignments = results['night_assignments']
    assignment_details = results['assignment_details']
    
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
                
                # Format day shift info
                day_info = "None"
                if day_assignment:
                    pref = day_details.get('preference_score')
                    if pref:
                        day_info = f"{day_assignment} (Pref: {pref})"
                    else:
                        day_info = f"{day_assignment} (No pref)"
                
                # Format night shift info
                night_info = "None"
                if night_assignment:
                    pref = night_details.get('preference_score')
                    if pref:
                        night_info = f"{night_assignment} (Pref: {pref})"
                    else:
                        night_info = f"{night_assignment} (No pref)"
                
                table_data.append({
                    "Day": day,
                    "Day Shift": day_info,
                    "Day Reason": day_details.get('reason', ''),
                    "Night Shift": night_info,
                    "Night Reason": night_details.get('reason', '')
                })
            
            # Display table
            df = pd.DataFrame(table_data)
            st.dataframe(df, use_container_width=True)
    
    # Display updated explanation
    st.markdown(f"""
    ### How Hypothetical Assignments Work
    
    1. **Role-Based Competition**: {role_ranking_info['effective_role'].title()}s compete separately for their positions
       - Day shifts: 10 positions each for nurses and medics
       - Night shifts: 6 positions for nurses, 5 for medics
    
    2. **Your Role Ranking**: Among {role_ranking_info['total_in_role']} {role_ranking_info['effective_role']}s, you rank **#{role_ranking_info['role_rank']}** by seniority
    
    3. **Assignment Process**: Starting with the most senior {role_ranking_info['effective_role']}, each person gets their highest preference shift from those remaining
    
    4. **Preference Scores**: Higher numbers = higher preference (1-10 scale, where 10 is highest)
    
    5. **Your Turn**: When it's your turn (position #{role_ranking_info['role_rank']}), you get your highest preference from the remaining shifts
    
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