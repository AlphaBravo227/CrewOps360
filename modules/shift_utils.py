# shift_utils.py
"""
Utility functions for working with shifts
"""

from datetime import datetime, timedelta
from .shift_definitions import day_shifts, night_shifts

def get_shift_end_time(shift_name, shift_type):
    """
    Calculate the end time of a shift based on 12-hour duration
    
    Args:
        shift_name (str): The name of the shift
        shift_type (str): The type of shift ('D' for day, 'N' for night)
        
    Returns:
        str: End time in 'HHMM' format or None if shift not found
    """
    shifts = day_shifts if shift_type == "D" else night_shifts
    if shift_name in shifts:
        start_time = shifts[shift_name]["start_time"]
        start_hour = int(start_time[:2])
        start_minute = int(start_time[2:])
        
        # Create a datetime object with the start time
        start_dt = datetime.now().replace(hour=start_hour, minute=start_minute)
        # Add 12 hours for shift duration
        end_dt = start_dt + timedelta(hours=12)
        
        # Format as HHMM
        return f"{end_dt.hour:02d}{end_dt.minute:02d}"
    return None

def calculate_rest_conflict(prev_shift_end, next_shift_start, reduced_rest_ok):
    """
    Check if there's a rest conflict between shifts
    
    Args:
        prev_shift_end (str): End time of previous shift in 'HHMM' format
        next_shift_start (str): Start time of next shift in 'HHMM' format
        reduced_rest_ok (bool): Whether reduced rest (10h instead of 12h) is acceptable
        
    Returns:
        bool: True if there's a rest conflict, False otherwise
    """
    if not prev_shift_end or not next_shift_start:
        return False
    
    prev_hour = int(prev_shift_end[:2])
    prev_min = int(prev_shift_end[2:])
    next_hour = int(next_shift_start[:2])
    next_min = int(next_shift_start[2:])
    
    # Convert to minutes for easier calculation
    prev_total_mins = prev_hour * 60 + prev_min
    next_total_mins = next_hour * 60 + next_min
    
    # If next day, add 24 hours worth of minutes
    if next_total_mins < prev_total_mins:
        next_total_mins += 24 * 60
    
    rest_mins = next_total_mins - prev_total_mins
    required_rest = 10 * 60 if reduced_rest_ok else 12 * 60
    
    return rest_mins < required_rest
