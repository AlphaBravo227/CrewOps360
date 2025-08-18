# Updated track_validator.py with pay period (14-day block) support and AT handling
"""
Module for validating tracks against requirements
Updated to properly handle AT preassignments
"""

import pandas as pd

def check_rest_requirements(track_data, preassignments=None):
    """
    Check for rest requirement violations in a track, including preassignments with AT handling
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        list: List of rest requirement issues
    """
    from .shift_utils import get_shift_end_time, calculate_rest_conflict
    
    issues = []
    days = list(track_data.keys())
    
    # Add preassignment days to the list if they are not already in track_data
    if preassignments:
        for day in preassignments:
            if day not in days:
                days.append(day)
    
    # Sort days to ensure chronological order
    days.sort()
    
    # Check consecutive days
    for i in range(len(days) - 1):
        current_day = days[i]
        next_day = days[i + 1]
        
        # Get current shift (from track_data or preassignments)
        current_shift = None
        if current_day in track_data and track_data.get(current_day):
            current_shift = track_data.get(current_day)
        elif preassignments and current_day in preassignments:
            # Handle AT preassignments specially
            preassign_value = preassignments[current_day]
            if preassign_value == "AT":
                current_shift = "AT"
            else:
                current_shift = "D"  # Treat other preassignments as day shifts
        
        # Get next shift (from track_data or preassignments)
        next_shift = None
        if next_day in track_data and track_data.get(next_day):
            next_shift = track_data.get(next_day)
        elif preassignments and next_day in preassignments:
            # Handle AT preassignments specially
            preassign_value = preassignments[next_day]
            if preassign_value == "AT":
                next_shift = "AT"
            else:
                next_shift = "D"  # Treat other preassignments as day shifts
        
        # Skip if either day doesn't have a shift
        if not current_shift or not next_shift:
            continue
        
        # Check for rest conflicts with special AT handling
        has_conflict = False
        
        # Special case: Night shift followed by AT (only needs 1 day rest)
        if current_shift == "N" and next_shift == "AT":
            # AT after night shift only needs 1 day rest (satisfied by consecutive days)
            has_conflict = False
        # Regular case: Night shift followed by day shift (needs standard rest)
        elif current_shift == "N" and next_shift in ["D", "N"]:
            current_end_time = get_shift_end_time("N", "N")
            next_start_time = "0700" if next_shift == "D" else "1900"
            has_conflict = calculate_rest_conflict(current_end_time, next_start_time, False)
        # AT followed by night shift
        elif current_shift == "AT" and next_shift == "N":
            # AT is treated as day shift for rest calculations
            current_end_time = get_shift_end_time("D", "D")
            next_start_time = "1900"
            has_conflict = calculate_rest_conflict(current_end_time, next_start_time, False)
        # Other combinations
        elif current_shift in ["D", "AT"] and next_shift == "N":
            current_end_time = get_shift_end_time("D", "D")
            next_start_time = "1900"
            has_conflict = calculate_rest_conflict(current_end_time, next_start_time, False)
        elif current_shift == "N" and next_shift == "D":
            current_end_time = get_shift_end_time("N", "N")
            next_start_time = "0700"
            has_conflict = calculate_rest_conflict(current_end_time, next_start_time, False)
        
        if has_conflict:
            # Format display names
            current_display = "AT (Preassignment)" if current_shift == "AT" else current_shift
            next_display = "AT (Preassignment)" if next_shift == "AT" else next_shift
            
            issues.append(f"Insufficient rest between {current_day} ({current_display}) and {next_day} ({next_display})")
    
    return issues

def count_weekend_shifts(track_data, preassignments=None):
    """
    Count weekend shifts in a track, including preassignments (including AT)
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        int: Number of weekend shifts
    """
    weekend_count = 0
    days = list(track_data.keys())
    
    # Add preassignment days to the count
    if preassignments:
        for day in preassignments:
            if day not in days:
                days.append(day)
    
    # Loop through days to identify weekends
    for day in days:
        # Extract day name from the date string (e.g., "Fri 05/24")
        day_parts = day.split()
        if len(day_parts) > 0:
            day_name = day_parts[0]
            
            # Check track_data first, then preassignments
            if day in track_data and track_data.get(day) in ["D", "N"]:
                assignment = track_data.get(day)
            elif preassignments and day in preassignments:
                # Treat all preassignments (including AT) as day shifts for weekend counting
                assignment = "D"
            else:
                assignment = ""
            
            # Count Friday night shifts
            if day_name == "Fri" and assignment == "N":
                weekend_count += 1
            
            # Count all Saturday and Sunday shifts (including AT preassignments)
            if day_name in ["Sat", "Sun"] and assignment in ["D", "N"]:
                weekend_count += 1
    
    return weekend_count

def validate_track(track_data, shifts_per_pay_period=0, night_minimum=0, weekend_minimum=5, preassignments=None):
    """
    Validate a track against requirements, including preassignments with AT handling
    Updated to use pay periods instead of weekly validation
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        shifts_per_pay_period (int): Required shifts per pay period (14-day block)
        night_minimum (int): Minimum night shifts required
        weekend_minimum (int): Minimum weekend shifts required
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        dict: Dictionary with validation results
    """
    from .shift_counter import count_shifts, count_shifts_by_pay_period
    
    results = {
        'shifts_per_pay_period': {'status': True, 'details': ''},
        'night_minimum': {'status': True, 'details': ''},
        'weekend_minimum': {'status': True, 'details': ''},
        'rest_requirements': {'status': True, 'issues': []}
    }
    
    # Extract days from track_data
    days = list(track_data.keys())
    
    # Add preassignment days to the list
    if preassignments:
        for day in preassignments:
            if day not in days:
                days.append(day)
    
    # Sort days
    days.sort()
    
    # Create a combined track data dictionary for validation
    combined_track = track_data.copy()
    if preassignments:
        for day, value in preassignments.items():
            if day not in combined_track or not combined_track[day]:
                # Treat all preassignments (including AT) as day shifts for shift counting
                combined_track[day] = "D"
    
    # Check shifts per pay period
    shifts_by_pay_period = count_shifts_by_pay_period(combined_track, days)
    
    # Check if all pay periods have the correct number of shifts
    if shifts_per_pay_period:
        # Handle case where shifts_by_pay_period could be empty
        if not shifts_by_pay_period:
            results['shifts_per_pay_period']['status'] = False
            results['shifts_per_pay_period']['details'] = "No shifts found in any pay period"
        else:
            all_pay_periods_valid = all(shifts == shifts_per_pay_period for shifts in shifts_by_pay_period)
            results['shifts_per_pay_period']['status'] = all_pay_periods_valid
            
            if not all_pay_periods_valid:
                invalid_pay_periods = [f"Pay Period {i+1}: {shifts}" for i, shifts in enumerate(shifts_by_pay_period) if shifts != shifts_per_pay_period]
                results['shifts_per_pay_period']['details'] = f"Invalid pay periods: {', '.join(invalid_pay_periods)}"
    
    # Check night minimum
    _, _, night_shifts = count_shifts(combined_track)
    results['night_minimum']['status'] = night_shifts >= night_minimum if night_minimum else True
    results['night_minimum']['details'] = f"Found {night_shifts} night shifts, minimum required: {night_minimum}"
    
    # Check weekend minimum
    weekend_shifts = count_weekend_shifts(track_data, preassignments)
    results['weekend_minimum']['status'] = weekend_shifts >= weekend_minimum if weekend_minimum else True
    results['weekend_minimum']['details'] = f"Found {weekend_shifts} weekend shifts, minimum required: {weekend_minimum}"
    
    # Check rest requirements
    rest_issues = check_rest_requirements(track_data, preassignments)
    
    if rest_issues:
        results['rest_requirements']['status'] = False
        results['rest_requirements']['issues'] = rest_issues
    
    return results