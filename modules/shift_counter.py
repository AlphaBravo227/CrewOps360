# Updated shift_counter.py with pay period (14-day block) support and AT handling
"""
Utility functions for consistent shift counting across the application
"""

import pandas as pd

def normalize_shift_value(value):
    """
    Normalize shift values for consistent handling
    
    Args:
        value: Shift value from track data
        
    Returns:
        str: Normalized value ('D', 'N', or '')
    """
    if value in ['D', 'N']:
        return value
    return ''

def count_shifts(track_data, days=None, preassignments=None):
    """
    Count total shifts, day shifts, and night shifts consistently
    Updated to handle AT preassignments as day shifts
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        days (list, optional): Specific days to count. If None, count all days in track_data.
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        tuple: (total_shifts, day_shifts, night_shifts)
    """
    if days is None:
        # Use all days in track_data
        values = [normalize_shift_value(val) for val in track_data.values()]
        
        # Add preassignments if provided - treat AT as day shifts
        if preassignments:
            for day, value in preassignments.items():
                if day not in track_data:
                    # Treat all preassignments (including AT) as day shifts (D)
                    values.append("D")
    else:
        # Convert days to list if it's a pandas Index
        if isinstance(days, pd.Index):
            days = days.tolist()
            
        # Use only the specified days
        values = []
        for day in days:
            if day in track_data:
                values.append(normalize_shift_value(track_data.get(day, '')))
            elif preassignments and day in preassignments:
                # Treat all preassignments (including AT) as day shifts (D)
                values.append("D")
            else:
                values.append("")
    
    # Explicitly compare to 'D' and 'N' for counting
    total_shifts = sum(1 for val in values if val in ['D', 'N'])
    day_shifts = sum(1 for val in values if val == 'D')
    night_shifts = sum(1 for val in values if val == 'N')
    
    return total_shifts, day_shifts, night_shifts

def count_shifts_by_week(track_data, days, preassignments=None):
    """
    Count shifts by week using consistent ordering of days
    Updated to handle AT preassignments
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        days (list): Ordered list of days in the schedule
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        list: Number of shifts in each week
    """
    # Make sure days is a list, not a pandas Index
    if isinstance(days, pd.Index):
        days = days.tolist()
        
    shifts_by_week = []
    
    # Ensure days are in correct order
    for i in range(0, len(days), 7):
        # Check if we have enough days left for this week
        if i + 7 <= len(days):
            week_days = days[i:i+7]
            # Use the count_shifts function for consistent counting
            week_total, _, _ = count_shifts(track_data, week_days, preassignments)
            shifts_by_week.append(week_total)
        elif i < len(days):
            # Handle partial weeks at the end (if any)
            week_days = days[i:]
            week_total, _, _ = count_shifts(track_data, week_days, preassignments)
            shifts_by_week.append(week_total)
    
    return shifts_by_week

def count_shifts_by_pay_period(track_data, days, preassignments=None):
    """
    Count shifts by pay period (14-day blocks) using consistent ordering of days
    Updated to handle AT preassignments
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        days (list): Ordered list of days in the schedule
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        list: Number of shifts in each pay period (14-day block)
    """
    # Make sure days is a list, not a pandas Index
    if isinstance(days, pd.Index):
        days = days.tolist()
        
    shifts_by_pay_period = []
    
    # Process in 14-day blocks (pay periods)
    for i in range(0, len(days), 14):
        # Check if we have enough days left for this pay period
        if i + 14 <= len(days):
            pay_period_days = days[i:i+14]
            # Use the count_shifts function for consistent counting
            pay_period_total, _, _ = count_shifts(track_data, pay_period_days, preassignments)
            shifts_by_pay_period.append(pay_period_total)
        elif i < len(days):
            # Handle partial pay periods at the end (if any)
            pay_period_days = days[i:]
            pay_period_total, _, _ = count_shifts(track_data, pay_period_days, preassignments)
            shifts_by_pay_period.append(pay_period_total)
    
    return shifts_by_pay_period

def validate_requirements(track_data, days, shifts_per_pay_period, night_minimum, preassignments=None):
    """
    Validate track against requirements using consistent counting methods
    Updated to use pay periods instead of weekly validation and handle AT preassignments
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        days (list): Ordered list of days in the schedule
        shifts_per_pay_period (int): Required shifts per pay period (14-day block)
        night_minimum (int): Minimum night shifts required
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        dict: Dictionary with validation results
    """
    from .track_validator import check_rest_requirements_updated, count_weekend_shifts_updated
    
    # Make sure days is a list, not a pandas Index
    if isinstance(days, pd.Index):
        days_list = days.tolist()
    else:
        days_list = list(days)
    
    weekend_minimum = 5  # Default minimum weekend shifts
    
    results = {
        'shifts_per_pay_period': {'status': True, 'details': ''},
        'night_minimum': {'status': True, 'details': ''},
        'rest_requirements': {'status': True, 'issues': []},
        'weekend_minimum': {'status': True, 'details': ''}
    }
    
    # Check shifts per pay period
    shifts_by_pay_period = count_shifts_by_pay_period(track_data, days_list, preassignments)
    
    # Check if all pay periods have the correct number of shifts
    if shifts_per_pay_period:
        all_pay_periods_valid = all(shifts == shifts_per_pay_period for shifts in shifts_by_pay_period)
        results['shifts_per_pay_period']['status'] = all_pay_periods_valid
        
        if not all_pay_periods_valid:
            invalid_pay_periods = [f"Pay Period {i+1}: {shifts}" for i, shifts in enumerate(shifts_by_pay_period) if shifts != shifts_per_pay_period]
            results['shifts_per_pay_period']['details'] = f"Invalid pay periods: {', '.join(invalid_pay_periods)}"
    
    # Check night minimum
    _, _, night_shifts = count_shifts(track_data, days_list, preassignments)
    results['night_minimum']['status'] = night_shifts >= night_minimum if night_minimum else True
    results['night_minimum']['details'] = f"Found {night_shifts} night shifts, minimum required: {night_minimum}"
    
    # Check weekend minimum with AT handling
    weekend_shifts = count_weekend_shifts_updated(track_data, preassignments)
    results['weekend_minimum']['status'] = weekend_shifts >= weekend_minimum if weekend_minimum else True
    results['weekend_minimum']['details'] = f"Found {weekend_shifts} weekend shifts, minimum required: {weekend_minimum}"
    
    # Check rest requirements with AT handling
    rest_issues = check_rest_requirements_updated(track_data, preassignments)
    
    if rest_issues:
        results['rest_requirements']['status'] = False
        results['rest_requirements']['issues'] = rest_issues
    
    return results

def count_weekend_shifts_updated(track_data, preassignments=None):
    """
    Count weekend shifts in a track, including preassignments (including AT)
    Updated to properly handle AT preassignments
    
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

def check_rest_requirements_updated(track_data, preassignments=None):
    """
    Check for rest requirement violations in a track, including preassignments with AT handling
    Updated to handle AT preassignments with different rest requirements
    
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