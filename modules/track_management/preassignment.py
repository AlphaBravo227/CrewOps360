# modules/track_management/preassignment.py
"""
Module for handling preassignments within the track management system
"""

import streamlit as st
import pandas as pd

from ..day_pattern import pattern_day_sort_key as _pattern_day_sort_key


def load_preassignments(track_name=None):
    """
    Load a track cycle's preassignments from the database.

    Preassignments used to be authored in Preassignments.xlsx and dropped in the upload
    folder; they are now stored per bid cycle in the database and configured in the
    Track Bidding admin. The return shape is unchanged — a DataFrame indexed by staff
    name with one column per day — so get_staff_preassignments() and has_preassignment()
    below work exactly as before.

    Args:
        track_name (str, optional): the cycle to load. Defaults to the cycle bidding is
            open on, then the active cycle.

    Returns:
        DataFrame or None: None when the cycle has no preassignments.
    """
    try:
        from ..preassignment_db import build_preassignment_df
        return build_preassignment_df(track_name)
    except Exception as e:
        st.error(f"Error loading preassignments: {str(e)}")
        return None

def get_staff_preassignments(staff_name, preassignment_df, days):
    """
    Get preassignments for a specific staff member
    
    Args:
        staff_name (str): Name of the staff member
        preassignment_df (DataFrame or dict): DataFrame or dict containing preassignments
        days (list): List of days in the schedule
        
    Returns:
        dict: Dictionary of day -> preassignment value or empty dict if not preassigned
    """
    # Handle the case when preassignment_df is None
    if preassignment_df is None:
        return {}
    
    # Handle different types of preassignment_df
    if isinstance(preassignment_df, dict):
        # If it's already a dictionary, use it directly
        if staff_name in preassignment_df:
            return preassignment_df[staff_name]
        return {}
    else:
        # Assume it's a DataFrame
        # Check if staff_name exists in the DataFrame index
        if staff_name not in preassignment_df.index:
            return {}
        
        # Get the staff member's row
        staff_row = preassignment_df.loc[staff_name]
        
        # Create a dictionary of preassignments
        preassignments = {}
        
        # For each day, check if there's a preassignment
        for day in days:
            if day in staff_row.index:
                # Get the preassignment value
                value = staff_row[day]
                
                # Check if it's not empty or NaN
                if pd.notna(value) and str(value).strip():
                    preassignments[day] = str(value).strip()
        
        return preassignments

def has_preassignment(staff_name, day, preassignment_df):
    """
    Check if a staff member has a preassignment for a specific day
    
    Args:
        staff_name (str): Name of the staff member
        day (str): The day to check
        preassignment_df (DataFrame or dict): DataFrame or dict containing preassignments
        
    Returns:
        bool: True if preassigned, False otherwise
    """
    # Handle the case when preassignment_df is None
    if preassignment_df is None:
        return False
    
    # Handle different types of preassignment_df
    if isinstance(preassignment_df, dict):
        # If it's already a dictionary, use it directly
        if staff_name in preassignment_df:
            staff_preassignments = preassignment_df[staff_name]
            return day in staff_preassignments and staff_preassignments[day]
        return False
    else:
        # Assume it's a DataFrame
        # Check if staff_name exists in the DataFrame index
        if staff_name not in preassignment_df.index:
            return False
        
        # Get the staff member's row
        staff_row = preassignment_df.loc[staff_name]
        
        # Check if the day is in the row and has a non-empty value
        if day in staff_row.index and pd.notna(staff_row[day]) and str(staff_row[day]).strip():
            return True
        
        return False

def display_preassignments(staff_name, preassignments):
    """
    Display preassignments for a staff member
    
    Args:
        staff_name (str): Name of the staff member
        preassignments (dict): Dictionary of day -> preassignment value
    """
    import streamlit as st
    import pandas as pd
    
    if not preassignments:
        return
    
    st.subheader("Preassignments")
    
    # Create dataframe for display
    data = []
    for day, activity in sorted(preassignments.items(), key=lambda item: _pattern_day_sort_key(item[0])):
        data.append({
            "Day": day,
            "Activity": activity,
            "Counts As": "Day Shift"  # All preassignments count as day shifts
        })
    
    # Display dataframe
    if data:
        df = pd.DataFrame(data)
        
        # Apply styling
        def highlight_preassignments(val):
            return 'background-color: #e2e3e5'  # Gray background
        
        st.dataframe(
            df.style.map(highlight_preassignments, subset=['Activity'])
        )
        
        # Add explanation
        st.info("📌 Preassignments are locked and count as day shifts for scheduling purposes. They cannot be modified.")
    else:
        st.info("No preassignments found for this staff member.")

def count_preassignment_shifts(preassignments, days=None):
    """
    Count shifts from preassignments
    
    Args:
        preassignments (dict): Dictionary of day -> preassignment value
        days (list, optional): Specific days to count. If None, count all days.
        
    Returns:
        int: Number of preassigned shifts
    """
    if not preassignments:
        return 0
    
    if days is None:
        # Count all preassignments
        return len(preassignments)
    else:
        # Count only preassignments on specified days
        return sum(1 for day in days if day in preassignments)

def preassignments_by_week(preassignments, days):
    """
    Count preassignments by week
    
    Args:
        preassignments (dict): Dictionary of day -> preassignment value
        days (list): Ordered list of days in the schedule
        
    Returns:
        list: Number of preassignments in each week
    """
    if not preassignments or not days:
        return []
    
    # Make sure days is a list, not a pandas Index
    if isinstance(days, pd.Index):
        days = days.tolist()
        
    preassignments_by_week = []
    
    # Ensure days are in correct order
    for i in range(0, len(days), 7):
        # Check if we have enough days left for this week
        if i + 7 <= len(days):
            week_days = days[i:i+7]
            # Count preassignments in this week
            week_count = sum(1 for day in week_days if day in preassignments)
            preassignments_by_week.append(week_count)
        elif i < len(days):
            # Handle partial weeks at the end (if any)
            week_days = days[i:]
            week_count = sum(1 for day in week_days if day in preassignments)
            preassignments_by_week.append(week_count)
    
    return preassignments_by_week

def merge_preassignments_with_track(track_data, preassignments):
    """
    Merge preassignments into track data
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        preassignments (dict): Dictionary of day -> preassignment value
        
    Returns:
        dict: Combined dictionary with preassignments added as day shifts
    """
    if not preassignments:
        return track_data.copy()
    
    # Create a copy of track data
    combined = track_data.copy()
    
    # Add preassignments
    for day, activity in preassignments.items():
        if day not in combined or not combined[day]:
            # Add preassignment as a day shift
            combined[day] = "D"
    
    return combined

def validate_track_with_preassignments(track_data, preassignments, shifts_per_week, night_minimum, weekend_minimum=5):
    """
    Validate track with preassignments against requirements
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        preassignments (dict): Dictionary of day -> preassignment value
        shifts_per_week (int): Required shifts per week
        night_minimum (int): Minimum night shifts required
        weekend_minimum (int): Minimum weekend shifts required
        
    Returns:
        dict: Dictionary with validation results
    """
    from ..track_validator import validate_track
    
    # Use the existing validate_track function with preassignments
    return validate_track(track_data, shifts_per_week, night_minimum, weekend_minimum, preassignments)
