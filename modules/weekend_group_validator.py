# modules/weekend_group_validator.py
"""
Module for validating weekend group assignments
"""

import streamlit as st
import pandas as pd

# Define weekend group assignments
WEEKEND_GROUPS = {
    'A': {
        'type': 'Every Other',
        'periods': [
            ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
            ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 2
            ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 3
        ]
    },
    'B': {
        'type': 'Every Other',
        'periods': [
            ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
            ['Fri B 3', 'Sat B 3', 'Sun B 4'],  # Period 2
            ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 3
        ]
    },
    'C': {
        'type': 'Every Third',
        'periods': [
            ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
            ['Fri B 3', 'Sat B 3', 'Sun B 4']   # Period 2
        ]
    },
    'D': {
        'type': 'Every Third',
        'periods': [
            ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
            ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 2
        ]
    },
    'E': {
        'type': 'Every Third',
        'periods': [
            ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 1
            ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 2
        ]
    }
}

def get_staff_weekend_group(staff_name, requirements_df):
    """
    Get the weekend group assignment for a staff member
    
    Args:
        staff_name (str): Name of the staff member
        requirements_df (DataFrame): Requirements DataFrame
        
    Returns:
        str or None: Weekend group (A, B, C, D, E) or None if not found
    """
    if requirements_df is None or requirements_df.empty:
        return None
    
    try:
        # Find staff member in requirements
        staff_found = False
        staff_req = None
        
        # Try different possible staff column names
        possible_staff_cols = [
            requirements_df.columns[0],
            'STAFF NAME', 'Staff Name', 'staff name', 'Name', 'NAME'
        ]
        
        for col_name in possible_staff_cols:
            if col_name in requirements_df.columns:
                staff_req = requirements_df[requirements_df[col_name] == staff_name]
                if not staff_req.empty:
                    staff_found = True
                    break
                    
                # Try case-insensitive match
                staff_req = requirements_df[requirements_df[col_name].str.lower() == staff_name.lower()]
                if not staff_req.empty:
                    staff_found = True
                    break
        
        if not staff_found or staff_req.empty:
            return None
        
        # Get weekend group from column 4 (0-indexed)
        if len(requirements_df.columns) >= 5:  # Column 4 exists
            weekend_group = staff_req.iloc[0].iloc[4]
            
            if pd.notna(weekend_group):
                weekend_group = str(weekend_group).strip().upper()
                if weekend_group in WEEKEND_GROUPS:
                    return weekend_group
        
        return None
        
    except Exception as e:
        print(f"Error getting weekend group for {staff_name}: {str(e)}")
        return None

def get_weekend_days_for_group(weekend_group):
    """
    Get all weekend days for a specific group
    
    Args:
        weekend_group (str): Weekend group (A, B, C, D, E)
        
    Returns:
        list: List of all weekend days for the group
    """
    if weekend_group not in WEEKEND_GROUPS:
        return []
    
    all_days = []
    for period in WEEKEND_GROUPS[weekend_group]['periods']:
        all_days.extend(period)
    
    return all_days

def map_weekend_day_to_schedule_day(weekend_day, days):
    """
    Map a weekend group day (e.g., 'Fri A 1') to actual schedule day
    
    Args:
        weekend_day (str): Weekend day in format 'Fri A 1'
        days (list): List of actual schedule days
        
    Returns:
        str or None: Matching schedule day or None if not found
    """
    # Parse the weekend day format
    parts = weekend_day.split()
    if len(parts) != 3:
        return None
    
    day_name, block, week = parts
    
    # Find matching day in schedule
    for schedule_day in days:
        schedule_parts = schedule_day.split()
        if len(schedule_parts) >= 1:
            schedule_day_name = schedule_parts[0]
            
            # Check if day names match (Fri, Sat, Sun)
            if schedule_day_name == day_name:
                # Check if it contains the block and week
                if block in schedule_day and week in schedule_day:
                    return schedule_day
    
    return None

def validate_weekend_group_assignment(track_data, weekend_group, days, preassignments=None):
    """
    Validate weekend group assignment for a staff member
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        weekend_group (str): Weekend group (A, B, C, D, E)
        days (list): List of schedule days
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        dict: Validation result with status and details
    """
    result = {
        'status': True,
        'details': '',
        'issues': [],
        'weekend_group': weekend_group,
        'periods_validated': []
    }
    
    if weekend_group not in WEEKEND_GROUPS:
        result['status'] = False
        result['details'] = f"Invalid weekend group: {weekend_group}"
        return result
    
    # Get weekend group configuration
    group_config = WEEKEND_GROUPS[weekend_group]
    periods = group_config['periods']
    
    # Create combined track data with preassignments
    combined_track = track_data.copy()
    if preassignments:
        for day, activity in preassignments.items():
            if day not in combined_track or not combined_track[day]:
                # Treat all preassignments (including AT) as day shifts
                combined_track[day] = "D"
    
    # Validate each period
    total_periods = len(periods)
    periods_with_minimum = 0
    
    for period_idx, period_days in enumerate(periods):
        period_num = period_idx + 1
        period_shifts = 0
        period_details = []
        
        # Check each day in the period
        for weekend_day in period_days:
            # Map to actual schedule day
            schedule_day = map_weekend_day_to_schedule_day(weekend_day, days)
            
            if schedule_day:
                assignment = combined_track.get(schedule_day, "")
                
                # Count weekend shifts (N on Friday, D or N on Saturday/Sunday)
                day_name = weekend_day.split()[0]
                
                if day_name == "Fri" and assignment == "N":
                    period_shifts += 1
                    period_details.append(f"{schedule_day}: Friday Night")
                elif day_name in ["Sat", "Sun"] and assignment in ["D", "N"]:
                    shift_type = "Day" if assignment == "D" else "Night"
                    period_shifts += 1
                    period_details.append(f"{schedule_day}: {day_name} {shift_type}")
        
        # Check if period meets minimum (2 shifts)
        period_valid = period_shifts >= 2
        if period_valid:
            periods_with_minimum += 1
        
        result['periods_validated'].append({
            'period': period_num,
            'days': period_days,
            'shifts_worked': period_shifts,
            'shifts_required': 2,
            'valid': period_valid,
            'details': period_details
        })
        
        if not period_valid:
            result['issues'].append(f"Period {period_num}: {period_shifts} shifts (minimum 2 required)")
    
    # Overall validation
    if periods_with_minimum == total_periods:
        result['status'] = True
        result['details'] = f"Weekend Group {weekend_group}: All {total_periods} periods meet minimum requirement"
    else:
        result['status'] = False
        result['details'] = f"Weekend Group {weekend_group}: {periods_with_minimum}/{total_periods} periods meet minimum requirement"
    
    return result

def get_weekend_group_info(weekend_group):
    """
    Get information about a weekend group
    
    Args:
        weekend_group (str): Weekend group (A, B, C, D, E)
        
    Returns:
        dict: Weekend group information
    """
    if weekend_group not in WEEKEND_GROUPS:
        return None
    
    config = WEEKEND_GROUPS[weekend_group]
    return {
        'group': weekend_group,
        'type': config['type'],
        'total_periods': len(config['periods']),
        'periods': config['periods'],
        'all_days': get_weekend_days_for_group(weekend_group)
    }

def is_weekend_group_day(day, weekend_group, days):
    """
    Check if a specific day is part of a weekend group assignment
    
    Args:
        day (str): Schedule day to check
        weekend_group (str): Weekend group (A, B, C, D, E)
        days (list): List of all schedule days
        
    Returns:
        bool: True if day is part of weekend group assignment
    """
    if weekend_group not in WEEKEND_GROUPS:
        return False
    
    # Get all weekend days for the group
    weekend_days = get_weekend_days_for_group(weekend_group)
    
    # Check if the day matches any weekend group day
    for weekend_day in weekend_days:
        if map_weekend_day_to_schedule_day(weekend_day, days) == day:
            return True
    
    return False

def format_weekend_group_display(weekend_group):
    """
    Format weekend group for display
    
    Args:
        weekend_group (str): Weekend group (A, B, C, D, E)
        
    Returns:
        str: Formatted display string
    """
    if weekend_group not in WEEKEND_GROUPS:
        return "Unknown"
    
    config = WEEKEND_GROUPS[weekend_group]
    return f"Group {weekend_group} ({config['type']}, {len(config['periods'])} periods)"