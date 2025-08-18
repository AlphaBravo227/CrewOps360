# modules/track_modification_core.py - FIXED TO USE HYPOTHETICAL SCHEDULER DATA
"""
Module for track modification staffing needs calculation core logic
FIXED: Now derives all staffing information from hypothetical scheduler instead of recalculating
"""
import pandas as pd
import streamlit as st
import sqlite3
import os
from typing import Dict, List, Tuple, Any
from modules.shift_definitions import day_shifts, night_shifts
from modules.shift_utils import get_shift_end_time, calculate_rest_conflict
from modules.staff_utils import is_special_conflict

# Import the hypothetical scheduler
from modules.hypothetical_scheduler_new import generate_hypothetical_schedule_new as generate_hypothetical_schedule

def get_all_staff_updated_preferences(preferences_df, staff_col_prefs):
    """
    Get updated preferences for ALL staff members from database where available
    This ensures the competition simulation uses everyone's most recent preferences
    
    Args:
        preferences_df (DataFrame): Original preferences DataFrame from file
        staff_col_prefs (str): Column name for staff in preferences
        
    Returns:
        DataFrame: Updated preferences DataFrame with database preferences where available
    """
    from modules.preference_editor import get_current_preferences
    
    # Create a copy of the preferences DataFrame
    updated_preferences_df = preferences_df.copy()
    
    # Update preferences for ALL staff members who have database entries
    for idx, row in preferences_df.iterrows():
        staff_name = row[staff_col_prefs]
        
        # Get current preferences for this staff member
        enhanced_preferences, preference_source = get_current_preferences(staff_name)
        
        if enhanced_preferences and preference_source == 'database':
            # Update this staff member's preferences
            for shift_name, preference_score in enhanced_preferences.items():
                if shift_name in updated_preferences_df.columns:
                    # Use at[] for single value assignment to ensure correct column
                    updated_preferences_df.at[idx, shift_name] = preference_score
    
    return updated_preferences_df

def enhance_hypothetical_scheduler_with_staffing_analysis(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, seniority_col
):
    """
    Enhanced hypothetical scheduler that includes comprehensive staffing analysis
    FIXED: Now ensures ALL staff members' most recent preferences are used
    
    Returns:
        dict: Enhanced results including staffing analysis for each day/shift
    """
    # FIXED: Get most recent preferences for ALL staff, not just selected staff
    updated_preferences_df = get_all_staff_updated_preferences(preferences_df, staff_col_prefs)
    
    # Check what preference source the selected staff is using
    from modules.preference_editor import get_current_preferences
    _, preference_source = get_current_preferences(selected_staff)
    
    # Generate schedule with updated preferences for ALL staff
    base_results = generate_hypothetical_schedule(
        selected_staff, updated_preferences_df, current_tracks_df, days,
        staff_col_prefs, staff_col_tracks, role_col, seniority_col
    )
    
    # Add preference source information to results
    base_results['preference_source'] = preference_source
    
    # Get max shifts from session state
    max_day_nurses = st.session_state.get('max_day_nurses', 10)
    max_day_medics = st.session_state.get('max_day_medics', 10)
    max_night_nurses = st.session_state.get('max_night_nurses', 6)
    max_night_medics = st.session_state.get('max_night_medics', 5)
    
    # Check track source setting
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
    
    # Enhance assignment_details with comprehensive staffing analysis
    enhanced_assignment_details = {}
    
    for day in days:
        day_data = base_results['assignment_details'].get(day, {})
        
        # Calculate staffing for day shift
        day_staffing = calculate_shift_staffing_analysis(
            day, "D", "day", updated_preferences_df, current_tracks_df, 
            staff_col_prefs, staff_col_tracks, role_col,
            max_day_nurses, max_day_medics, use_database_logic
        )
        
        # Calculate staffing for night shift  
        night_staffing = calculate_shift_staffing_analysis(
            day, "N", "night", updated_preferences_df, current_tracks_df,
            staff_col_prefs, staff_col_tracks, role_col,
            max_night_nurses, max_night_medics, use_database_logic
        )
        
        # Rest of the function remains the same...
        # Get preference scores from base results with enhanced preference information
        day_base = day_data.get('day', {})
        night_base = day_data.get('night', {})
        
        # Extract preferences from the most recent source
        day_preferences = day_base.get('preferences', {})
        night_preferences = night_base.get('preferences', {})
        
        # If using database preferences for selected staff, make sure we have the right preference scores
        if preference_source == 'database':
            # Get enhanced preferences and add them to the preferences dict
            staff_idx = updated_preferences_df[staff_col_prefs] == selected_staff
            if not updated_preferences_df[staff_idx].empty:
                staff_row = updated_preferences_df[staff_idx].iloc[0]
                
                # Update day preferences
                from modules.shift_definitions import day_shifts, night_shifts
                for shift_name in day_shifts.keys():
                    if shift_name in staff_row.index and pd.notna(staff_row[shift_name]):
                        day_preferences[shift_name] = staff_row[shift_name]
                
                # Update night preferences
                for shift_name in night_shifts.keys():
                    if shift_name in staff_row.index and pd.notna(staff_row[shift_name]):
                        night_preferences[shift_name] = staff_row[shift_name]
        
        enhanced_assignment_details[day] = {
            'day': {
                **day_base,  # Keep all original data
                'staffing_analysis': day_staffing,
                'preferences': day_preferences,  # Updated with most recent preferences
                'filtered_by_delta': day_base.get('filtered_by_delta', False),
                'no_preference_data': day_base.get('no_preference_data', False),
                'preference_source': preference_source
            },
            'night': {
                **night_base,  # Keep all original data
                'staffing_analysis': night_staffing,
                'preferences': night_preferences,  # Updated with most recent preferences
                'filtered_by_delta': night_base.get('filtered_by_delta', False),
                'no_preference_data': night_base.get('no_preference_data', False),
                'preference_source': preference_source
            }
        }
    
    # Return enhanced results
    return {
        **base_results,  # Keep all original data
        'assignment_details': enhanced_assignment_details
    }

def calculate_shift_staffing_analysis(
    day, shift_code, shift_type, preferences_df, current_tracks_df,
    staff_col_prefs, staff_col_tracks, role_col,
    max_nurses, max_medics, use_database_logic
):
    """
    Calculate comprehensive staffing analysis for a specific shift
    This replaces the duplicate logic in analyze_track_modification_needs
    
    Returns:
        dict: Complete staffing analysis including counts, needs, etc.
    """
    from modules.hypothetical_scheduler_new import get_staff_on_shift_from_database, get_staff_on_shift_from_excel, get_staff_role_for_counting
    
    # Get current staff on shift using the same logic as hypothetical scheduler
    if use_database_logic:
        staff_on_shift = get_staff_on_shift_from_database(day, shift_code, preferences_df, staff_col_prefs, role_col)
    else:
        staff_on_shift = get_staff_on_shift_from_excel(day, shift_code, current_tracks_df, staff_col_tracks)
    
    # Count staff by role using the same logic as hypothetical scheduler
    nurses = 0
    medics = 0
    
    for staff in staff_on_shift:
        if staff in preferences_df[staff_col_prefs].values:
            effective_role = get_staff_role_for_counting(staff, preferences_df, staff_col_prefs, role_col)
            if effective_role == "nurse":
                nurses += 1
            elif effective_role == "medic":
                medics += 1
    
    # Calculate needs
    nurse_needs = max_nurses - nurses
    medic_needs = max_medics - medics
    
    return {
        'current_nurses': nurses,
        'current_medics': medics,
        'max_nurses': max_nurses,
        'max_medics': max_medics,
        'nurse_needs': nurse_needs,
        'medic_needs': medic_needs,
        'nurses_needed': nurse_needs > 0,
        'medics_needed': medic_needs > 0,
        'staff_on_shift': staff_on_shift
    }

def analyze_track_modification_needs_from_scheduler(
    day, shift_type, assignment_details, staff_role
):
    """
    FIXED: Now derives all information from hypothetical scheduler data
    Uses the EXACT preference score calculated by the hypothetical scheduler
    
    Args:
        day (str): The day being analyzed
        shift_type (str): "day" or "night"
        assignment_details (dict): Enhanced assignment details from hypothetical scheduler
        staff_role (str): Role of the staff member
        
    Returns:
        tuple: (needs_count, is_needed, preference_score, filtered_by_delta)
    """
    # Get data from enhanced assignment details
    day_data = assignment_details.get(day, {})
    shift_data = day_data.get(shift_type.lower(), {})
    staffing_analysis = shift_data.get('staffing_analysis', {})
    
    # For dual providers, consistently show them as nurses for needs calculation
    effective_role = "nurse" if staff_role == "dual" else staff_role
    
    # Get needs based on role from staffing analysis
    if effective_role == "nurse":
        needs_count = staffing_analysis.get('nurse_needs', 0)
        is_needed = staffing_analysis.get('nurses_needed', False)
    else:  # medic
        needs_count = staffing_analysis.get('medic_needs', 0)
        is_needed = staffing_analysis.get('medics_needed', False)
    
    # FIXED: Get preference score directly from the hypothetical scheduler assignment
    # This is the exact preference score for the assigned shift from the scheduler
    preference_score = shift_data.get('preference_score', None)
    
    # Get filtered by delta from scheduler data
    filtered_by_delta = shift_data.get('filtered_by_delta', False)
    
    return needs_count, is_needed, preference_score, filtered_by_delta

def calculate_track_modification_options(
    selected_staff, day, preferences_df, current_tracks_df, 
    days, staff_col_prefs, staff_col_tracks, role_col, 
    no_matrix_col, reduced_rest_col, seniority_col,
    day_assignments, night_assignments, assignment_details
):
    """
    Calculate valid options for track modification for a specific day.
    FIXED: Now uses enhanced assignment_details with staffing analysis
    """
    # Get staff information
    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
    staff_role = staff_info[role_col]
    
    # FIXED: Use enhanced function that gets data from scheduler
    day_needs_count, day_is_needed, day_pref_score, day_filtered_by_delta = analyze_track_modification_needs_from_scheduler(
        day, "day", assignment_details, staff_role
    )
    
    night_needs_count, night_is_needed, night_pref_score, night_filtered_by_delta = analyze_track_modification_needs_from_scheduler(
        day, "night", assignment_details, staff_role
    )
    
    # Get current track assignment for this day
    current_track = current_tracks_df[current_tracks_df[staff_col_tracks] == selected_staff]
    current_assignment = ""
    if not current_track.empty and day in current_track.columns:
        current_assignment = current_track.iloc[0][day]
        # Handle other notations (only accept D or N)
        if current_assignment not in ["D", "N"]:
            current_assignment = ""
    
    # Get shift assignments from hypothetical scheduler
    day_shift = day_assignments.get(day, "")
    night_shift = night_assignments.get(day, "")
    
    # For dual providers, always treat as nurses in the track modification view
    effective_role = "nurse" if staff_role == "dual" else staff_role
    
    # Determine available options
    available_options = []
    
    # Always include "Off" option
    available_options.append("Off")
    
    # Add day shift if needed or if currently assigned
    if day_is_needed or current_assignment == "D":
        available_options.append("D")
    
    # Add night shift if needed or if currently assigned
    if night_is_needed or current_assignment == "N":
        available_options.append("N")
    
    # Add asterisk to preference scores if needed for display
    day_pref_display = day_pref_score
    night_pref_display = night_pref_score
    
    # Add asterisk for no preference data
    if assignment_details.get(day, {}).get("day", {}).get("no_preference_data", False):
        day_pref_display = f"{day_pref_score}*" if day_pref_score else "*"

    if assignment_details.get(day, {}).get("night", {}).get("no_preference_data", False):
        night_pref_display = f"{night_pref_score}*" if night_pref_score else "*"

    # Return comprehensive information about the day and options
    return {
        "day": day,
        "current_assignment": current_assignment,
        "day_shift": {
            "is_needed": day_is_needed,
            "needs_count": day_needs_count,
            "preference_score": day_pref_display,
            "shift_name": day_shift if day_shift else "",  # Do not strip 'p' suffix
            "filtered_by_delta": day_filtered_by_delta
        },
        "night_shift": {
            "is_needed": night_is_needed,
            "needs_count": night_needs_count, 
            "preference_score": night_pref_display,
            "shift_name": night_shift if night_shift else "",  # Do not strip 'p' suffix
            "filtered_by_delta": night_filtered_by_delta
        },
        "available_options": available_options,
        "effective_role": effective_role,
        "staff_role": staff_role
    }

def calculate_all_modification_options(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
    reduced_rest_col, seniority_col, max_day_nurses=None, max_day_medics=None,
    max_night_nurses=None, max_night_medics=None
):
    """
    FIXED: Calculate all track modification options using enhanced hypothetical scheduler
    Now uses single source of truth for all staffing calculations
    """
    # Update session state with passed values if provided
    if max_day_nurses is not None:
        st.session_state.max_day_nurses = max_day_nurses
    if max_day_medics is not None:
        st.session_state.max_day_medics = max_day_medics
    if max_night_nurses is not None:
        st.session_state.max_night_nurses = max_night_nurses
    if max_night_medics is not None:
        st.session_state.max_night_medics = max_night_medics
    
    # FIXED: Use enhanced hypothetical scheduler with staffing analysis
    results = enhance_hypothetical_scheduler_with_staffing_analysis(
        selected_staff,
        preferences_df,
        current_tracks_df,
        days,
        staff_col_prefs,
        staff_col_tracks,
        role_col,
        seniority_col
    )
    
    day_assignments = results['day_assignments']
    night_assignments = results['night_assignments']
    assignment_details = results['assignment_details']  # Now enhanced with staffing analysis
    preference_source = results.get('preference_source', 'file')  # Get preference source from results
    
    # Calculate options for each day using enhanced data
    options_by_day = {}
    
    for day in days:
        day_options = calculate_track_modification_options(
            selected_staff, day, preferences_df, current_tracks_df,
            days, staff_col_prefs, staff_col_tracks, role_col,
            no_matrix_col, reduced_rest_col, seniority_col,
            day_assignments, night_assignments, assignment_details
        )
        options_by_day[day] = day_options
    
    # Return comprehensive results with preference validation
    preference_validation = validate_preference_usage(selected_staff, preferences_df, staff_col_prefs)
    
    return {
        "options_by_day": options_by_day,
        "day_assignments": day_assignments,
        "night_assignments": night_assignments,
        "assignment_details": assignment_details,  # Enhanced with staffing analysis
        "selected_staff": selected_staff,
        "preference_source": preference_source,
        "preference_validation": preference_validation
    }

def validate_preference_usage(selected_staff, preferences_df, staff_col_prefs):
    """
    Validate that the most recent preferences are being used
    Returns information about preference source and completeness
    
    Args:
        selected_staff (str): Name of the selected staff member
        preferences_df (DataFrame): Original preferences DataFrame
        staff_col_prefs (str): Column name for staff in preferences
        
    Returns:
        dict: Information about preference usage
    """
    from modules.preference_editor import get_current_preferences
    
    # Get current preferences
    current_prefs, source = get_current_preferences(selected_staff)
    
    # Check if staff exists in original file
    staff_in_file = selected_staff in preferences_df[staff_col_prefs].values
    
    # Count complete preferences
    day_prefs_count = 0
    night_prefs_count = 0
    
    if current_prefs:
        from modules.shift_definitions import day_shifts, night_shifts
        day_prefs_count = sum(1 for shift in day_shifts.keys() if shift in current_prefs)
        night_prefs_count = sum(1 for shift in night_shifts.keys() if shift in current_prefs)
    
    return {
        'source': source,
        'has_preferences': bool(current_prefs),
        'staff_in_file': staff_in_file,
        'day_preferences_count': day_prefs_count,
        'night_preferences_count': night_prefs_count,
        'total_day_shifts': len(day_shifts),
        'total_night_shifts': len(night_shifts),
        'preferences_complete': (
            day_prefs_count == len(day_shifts) and 
            night_prefs_count == len(night_shifts)
        )
    }

# Legacy functions kept for compatibility but marked as deprecated
def get_database_track_counts(day, shift_type, role):
    """DEPRECATED: Use staffing_analysis from enhanced scheduler instead"""
    # Implementation kept for backward compatibility but should not be used
    pass

def get_excel_track_counts(day, shift_type, current_tracks_df, staff_col_tracks, 
                          preferences_df, staff_col_prefs, role_col):
    """DEPRECATED: Use staffing_analysis from enhanced scheduler instead"""
    # Implementation kept for backward compatibility but should not be used
    pass

def analyze_track_modification_needs(day, shift_type, assignment_details, staff_role, 
                                    preferences_df, current_tracks_df, staff_col_prefs, 
                                    staff_col_tracks, role_col):
    """DEPRECATED: Use analyze_track_modification_needs_from_scheduler instead"""
    # Redirect to new function for backward compatibility
    return analyze_track_modification_needs_from_scheduler(day, shift_type, assignment_details, staff_role)

# In the hypothetical scheduler display section, ensure you use the same data as the track modification section.
# Example (pseudo-code, adapt to your actual display function):
#
# hypothetical_results = calculate_all_modification_options(selected_staff, preferences_df, current_tracks_df, days, ...)
# day_assignments = hypothetical_results['day_assignments']
# assignment_details = hypothetical_results['assignment_details']
#
# for day in days:
#     assigned_shift = day_assignments.get(day, "")
#     assigned_pref = assignment_details.get(day, {}).get('day', {}).get('preference_score', "")
#     display_str = f"{assigned_shift} (pref {assigned_pref})" if assigned_shift else "No assignment"
#     st.write(f"{day}: {display_str}")
#
# This ensures the hypothetical scheduler display always matches the track modification section for the selected staff.