# modules/enhanced_track_validator.py
"""
Enhanced track validator with specific Boston MedFlight rules
Updated to handle AT preassignments and enforce all validation rules including weekend groups
"""

import pandas as pd
from datetime import datetime, timedelta

def validate_track_comprehensive(track_data, shifts_per_pay_period=0, night_minimum=0, weekend_minimum=5, preassignments=None, days=None, weekend_group=None, requirements_df=None, staff_name=None):
    """
    Comprehensive track validation against all Boston MedFlight requirements
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        shifts_per_pay_period (int): Required shifts per pay period (exact match)
        night_minimum (int): Minimum night shifts required (>=)
        weekend_minimum (int): Minimum weekend shifts required (>=)
        preassignments (dict, optional): Dictionary of day -> preassignment value
        days (list, optional): Ordered list of days for sequence validation
        weekend_group (str, optional): Weekend group assignment (A, B, C, D, E)
        requirements_df (DataFrame, optional): Requirements DataFrame for weekend group lookup
        staff_name (str, optional): Staff name for weekend group lookup
        
    Returns:
        dict: Comprehensive validation results
    """
    results = {
        'shifts_per_pay_period': {'status': True, 'details': '', 'issues': []},
        'night_minimum': {'status': True, 'details': '', 'issues': []},
        'weekend_minimum': {'status': True, 'details': '', 'issues': []},
        'shifts_per_week': {'status': True, 'details': '', 'issues': []},
        'rest_requirements': {'status': True, 'details': '', 'issues': []},
        'consecutive_shifts': {'status': True, 'details': '', 'issues': []},
        'weekend_group_assignment': {'status': True, 'details': '', 'issues': []},
        'overall_valid': True
    }
    
    # Create combined track for counting (includes preassignments)
    combined_track = create_combined_track(track_data, preassignments)
    
    # Get ordered days list
    if days is None:
        days = sorted(list(combined_track.keys()))
    
    # 1. Validate shifts per pay period (exact match)
    shifts_per_pay_period_result = validate_shifts_per_pay_period(combined_track, days, shifts_per_pay_period)
    results['shifts_per_pay_period'] = shifts_per_pay_period_result
    
    # 2. Validate night minimum (>= requirement)
    night_minimum_result = validate_night_minimum(combined_track, night_minimum)
    results['night_minimum'] = night_minimum_result
    
    # 3. Validate weekend minimum (>= requirement)
    weekend_minimum_result = validate_weekend_minimum(combined_track, weekend_minimum)
    results['weekend_minimum'] = weekend_minimum_result
    
    # 4. Validate shifts per week (< 4 per week)
    shifts_per_week_result = validate_shifts_per_week_limit(combined_track, days)
    results['shifts_per_week'] = shifts_per_week_result
    
    # 5. Validate rest requirements (AT and N->D rules)
    rest_requirements_result = validate_rest_requirements_enhanced(combined_track, preassignments, days)
    results['rest_requirements'] = rest_requirements_result
    
    # 6. Validate consecutive shifts limit (max 4 in a row, 5 if N included)
    consecutive_shifts_result = validate_consecutive_shifts_limit(combined_track, days)
    results['consecutive_shifts'] = consecutive_shifts_result
    
    # 7. NEW: Validate weekend group assignment (A, B, C, D, E)
    weekend_group_result = validate_weekend_group_assignment(combined_track, weekend_group, days, requirements_df, staff_name)
    results['weekend_group_assignment'] = weekend_group_result
    
    # Determine overall validity
    results['overall_valid'] = all(result['status'] for result in results.values() if result != results['overall_valid'])
    
    return results

def validate_weekend_group_assignment(combined_track, weekend_group, days, requirements_df=None, staff_name=None):
    """
    Validate weekend group assignment for a staff member
    
    Args:
        combined_track (dict): Combined track data
        weekend_group (str): Weekend group assignment (A, B, C, D, E)
        days (list): List of schedule days
        requirements_df (DataFrame, optional): Requirements DataFrame for weekend group lookup
        staff_name (str, optional): Staff name for weekend group lookup
        
    Returns:
        dict: Validation result for weekend group assignment
    """
    result = {'status': True, 'details': '', 'issues': [], 'weekend_days': [], 'periods_validated': []}
    
    # Get weekend group from requirements if not provided
    if not weekend_group and requirements_df is not None and staff_name:
        weekend_group = get_staff_weekend_group_inline(staff_name, requirements_df)
    
    if not weekend_group:
        result['details'] = "No weekend group assignment found"
        return result
    
    # Use inline weekend group validation since import might not work
    wg_result = validate_weekend_group_assignment_inline(combined_track, weekend_group, days)
    
    # Copy results
    result['status'] = wg_result['status']
    result['details'] = wg_result['details']
    result['issues'] = wg_result.get('issues', [])
    result['weekend_group'] = weekend_group
    result['periods_validated'] = wg_result.get('periods_validated', [])
    
    # Get weekend days for highlighting
    weekend_days = get_weekend_days_for_group_inline(weekend_group)
    
    # Map to actual schedule days
    result['weekend_days'] = []
    for weekend_day in weekend_days:
        schedule_day = map_weekend_day_to_schedule_day_inline(weekend_day, days)
        if schedule_day:
            result['weekend_days'].append(schedule_day)
    
    return result

# Inline weekend group functions to avoid import issues
def get_staff_weekend_group_inline(staff_name, requirements_df):
    """
    Get the weekend group assignment for a staff member
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
                if weekend_group in ['A', 'B', 'C', 'D', 'E']:
                    return weekend_group
        
        return None
        
    except Exception as e:
        return None

def get_weekend_days_for_group_inline(weekend_group):
    """
    Get all weekend days for a specific group
    """
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
    
    if weekend_group not in WEEKEND_GROUPS:
        return []
    
    all_days = []
    for period in WEEKEND_GROUPS[weekend_group]['periods']:
        all_days.extend(period)
    
    return all_days

def map_weekend_day_to_schedule_day_inline(weekend_day, days):
    """
    Map a weekend group day (e.g., 'Fri A 1') to actual schedule day
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

def validate_weekend_group_assignment_inline(track_data, weekend_group, days):
    """
    Validate weekend group assignment for a staff member
    """
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
            schedule_day = map_weekend_day_to_schedule_day_inline(weekend_day, days)
            
            if schedule_day:
                assignment = track_data.get(schedule_day, "")
                
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

def create_combined_track(track_data, preassignments=None):
    """
    Create combined track data including preassignments
    
    Args:
        track_data (dict): Original track data
        preassignments (dict, optional): Preassignment data
        
    Returns:
        dict: Combined track data
    """
    combined = track_data.copy()
    
    if preassignments:
        for day, activity in preassignments.items():
            if day not in combined or not combined[day]:
                if activity == "AT":
                    combined[day] = "AT"
                elif activity in ["D", "N"]:
                    combined[day] = activity
                else:
                    # Other preassignments become day shifts
                    combined[day] = "D"
    
    return combined

def validate_shifts_per_pay_period(combined_track, days, shifts_per_pay_period):
    """
    Validate shifts per pay period (exact match required)
    
    Args:
        combined_track (dict): Combined track data
        days (list): Ordered list of days
        shifts_per_pay_period (int): Required shifts per pay period
        
    Returns:
        dict: Validation result for shifts per pay period
    """
    result = {'status': True, 'details': '', 'issues': []}
    
    if shifts_per_pay_period <= 0:
        result['details'] = "No pay period requirement specified"
        return result
    
    # Count shifts by pay period (14-day blocks)
    shifts_by_pay_period = []
    
    for i in range(0, len(days), 14):
        pay_period_days = days[i:i+14] if i+14 <= len(days) else days[i:]
        
        pay_period_count = 0
        for day in pay_period_days:
            assignment = combined_track.get(day, "")
            if assignment in ["D", "N", "AT"]:  # AT counts as shift
                pay_period_count += 1
        
        shifts_by_pay_period.append(pay_period_count)
    
    # Check each pay period for exact match
    invalid_pay_periods = []
    for i, count in enumerate(shifts_by_pay_period):
        if count != shifts_per_pay_period:
            pay_period_num = i + 1
            invalid_pay_periods.append(f"Pay Period {pay_period_num}: {count} shifts (required: {shifts_per_pay_period})")
            result['issues'].append(f"Pay Period {pay_period_num} has {count} shifts, exactly {shifts_per_pay_period} required")
    
    if invalid_pay_periods:
        result['status'] = False
        result['details'] = f"Pay periods with incorrect shift counts: {', '.join(invalid_pay_periods)}"
    else:
        result['details'] = f"All pay periods have exactly {shifts_per_pay_period} shifts as required"
    
    return result

def validate_night_minimum(combined_track, night_minimum):
    """
    Validate night shift minimum (>= requirement)
    
    Args:
        combined_track (dict): Combined track data
        night_minimum (int): Minimum night shifts required
        
    Returns:
        dict: Validation result for night minimum
    """
    result = {'status': True, 'details': '', 'issues': []}
    
    # Count night shifts
    night_count = sum(1 for assignment in combined_track.values() if assignment == "N")
    
    if night_minimum > 0:
        if night_count < night_minimum:
            result['status'] = False
            result['details'] = f"Insufficient night shifts: {night_count} found, {night_minimum} minimum required"
            result['issues'].append(f"Need {night_minimum - night_count} more night shifts")
        else:
            result['details'] = f"Night minimum met: {night_count} shifts (minimum: {night_minimum})"
    else:
        result['details'] = f"No night minimum specified. Found {night_count} night shifts"
    
    return result

def validate_weekend_minimum(combined_track, weekend_minimum):
    """
    Validate weekend shift minimum (Friday N, Saturday D/N, Sunday D/N)
    
    Args:
        combined_track (dict): Combined track data
        weekend_minimum (int): Minimum weekend shifts required
        
    Returns:
        dict: Validation result for weekend minimum
    """
    result = {'status': True, 'details': '', 'issues': []}
    
    weekend_count = 0
    weekend_details = []
    
    for day, assignment in combined_track.items():
        if not assignment or assignment == "":
            continue
            
        # Extract day name from date string (e.g., "Fri 05/24")
        day_parts = day.split()
        if len(day_parts) > 0:
            day_name = day_parts[0]
            
            # Friday night shifts count as weekend
            if day_name == "Fri" and assignment == "N":
                weekend_count += 1
                weekend_details.append(f"{day} (Friday Night)")
            
            # Saturday and Sunday shifts (D, N, or AT) count as weekend
            elif day_name in ["Sat", "Sun"] and assignment in ["D", "N", "AT"]:
                weekend_count += 1
                shift_type = "AT" if assignment == "AT" else ("Day" if assignment == "D" else "Night")
                weekend_details.append(f"{day} ({day_name} {shift_type})")
    
    if weekend_minimum > 0:
        if weekend_count < weekend_minimum:
            result['status'] = False
            result['details'] = f"Insufficient weekend shifts: {weekend_count} found, {weekend_minimum} minimum required"
            result['issues'].append(f"Need {weekend_minimum - weekend_count} more weekend shifts")
        else:
            result['details'] = f"Weekend minimum met: {weekend_count} shifts (minimum: {weekend_minimum})"
    else:
        result['details'] = f"No weekend minimum specified. Found {weekend_count} weekend shifts"
    
    # Add details of weekend shifts found
    if weekend_details:
        result['weekend_shifts_found'] = weekend_details
    
    return result

def validate_shifts_per_week_limit(combined_track, days):
    """
    Validate shifts per week limit (< 4 per week)
    
    Args:
        combined_track (dict): Combined track data
        days (list): Ordered list of days
        
    Returns:
        dict: Validation result for weekly shift limits
    """
    result = {'status': True, 'details': '', 'issues': []}
    
    # Count shifts by week (7-day periods)
    violations = []
    
    for i in range(0, len(days), 7):
        week_days = days[i:i+7] if i+7 <= len(days) else days[i:]
        week_num = (i // 7) + 1
        
        week_count = 0
        week_shifts = []
        
        for day in week_days:
            assignment = combined_track.get(day, "")
            if assignment in ["D", "N", "AT"]:
                week_count += 1
                shift_type = assignment if assignment != "AT" else "AT"
                week_shifts.append(f"{day} ({shift_type})")
        
        # Check if week exceeds limit (>= 4 is violation)
        if week_count >= 4:
            violations.append({
                'week': week_num,
                'count': week_count,
                'shifts': week_shifts
            })
            result['issues'].append(f"Week {week_num}: {week_count} shifts (limit: < 4)")
    
    if violations:
        result['status'] = False
        violation_details = []
        for v in violations:
            violation_details.append(f"Week {v['week']}: {v['count']} shifts")
        result['details'] = f"Weekly limit violations: {', '.join(violation_details)}"
        result['violations'] = violations
    else:
        result['details'] = "All weeks have fewer than 4 shifts as required"
    
    return result
def validate_rest_requirements_enhanced(combined_track, preassignments, days):
    """
    Validate enhanced rest requirements (AT and N->D rules)
    
    CORRECTED Rules:
    1. AT preassignment cannot have N shift on preceding day
    2. After a night shift, you need 2 full unscheduled days before a DAYSHIFT ("D")
    3. After a night shift, you need only 1 full unscheduled day before an AT shift
    4. NO restriction on consecutive nightshifts ("N" after "N" is allowed)
    
    Args:
        combined_track (dict): Combined track data
        preassignments (dict): Preassignment data
        days (list): Ordered list of days
        
    Returns:
        dict: Validation result for rest requirements
    """
    result = {'status': True, 'details': '', 'issues': []}
    
    violations = []
    
    # Process each day to check for violations
    for i in range(len(days)):
        current_day = days[i]
        current_shift = combined_track.get(current_day, "")
        
        # Skip if no shift on this day
        if not current_shift:
            continue
            
        # Rule 1: Check if this is an AT preassignment with N on preceding day
        if current_shift == "AT" and preassignments and current_day in preassignments:
            if i > 0:
                prev_day = days[i - 1]
                prev_shift = combined_track.get(prev_day, "")
                if prev_shift == "N":
                    violations.append({
                        'type': 'AT_after_night',
                        'description': f"AT preassignment on {current_day} cannot follow night shift on {prev_day}",
                        'current_day': prev_day,
                        'next_day': current_day,
                        'current_shift': prev_shift,
                        'next_shift': current_shift
                    })
        
        # Rules 2-4: If this is a night shift, check subsequent days for proper rest
        if current_shift == "N":
            # Look ahead to find the next non-night shift (D or AT only)
            for j in range(i + 1, len(days)):
                check_day = days[j]
                check_shift = combined_track.get(check_day, "")
                
                # CORRECTED: Only check rest requirements for D and AT shifts
                # Skip consecutive night shifts (N after N is allowed)
                if check_shift == "N":
                    continue  # Skip night shifts - no rest requirement
                
                # If we find a D or AT shift, check if rest requirement is met
                if check_shift in ["D", "AT"]:
                    days_between = j - i - 1  # Number of unscheduled days between
                    
                    # Different requirements for different shift types
                    if check_shift == "AT":
                        # AT only needs 1 full unscheduled day after night shift
                        required_days = 1
                        if days_between < required_days:
                            violations.append({
                                'type': 'insufficient_rest_after_night',
                                'description': f"AT shift on {check_day} too soon after night shift on {current_day} (need {required_days} unscheduled day between, found {days_between})",
                                'night_day': current_day,
                                'next_shift_day': check_day,
                                'days_between': days_between,
                                'required_days': required_days,
                                'shift_type': 'AT'
                            })
                    elif check_shift == "D":
                        # Day shifts need 2 full unscheduled days after night shift
                        required_days = 2
                        if days_between < required_days:
                            violations.append({
                                'type': 'insufficient_rest_after_night',
                                'description': f"Day shift on {check_day} too soon after night shift on {current_day} (need {required_days} unscheduled days between, found {days_between})",
                                'night_day': current_day,
                                'next_shift_day': check_day,
                                'days_between': days_between,
                                'required_days': required_days,
                                'shift_type': 'D'
                            })
                    
                    # Only check the first non-night shift we find after this night shift
                    break
    
    if violations:
        result['status'] = False
        result['details'] = f"Found {len(violations)} rest requirement violations"
        result['issues'] = [v['description'] for v in violations]
        result['violations'] = violations
    else:
        result['details'] = "All rest requirements met"
    
    return result

def validate_consecutive_shifts_limit(combined_track, days):
    """
    Validate consecutive shifts limit (max 4 in a row, 5 if N included)
    
    Args:
        combined_track (dict): Combined track data
        days (list): Ordered list of days
        
    Returns:
        dict: Validation result for consecutive shifts
    """
    result = {'status': True, 'details': '', 'issues': []}
    
    violations = []
    
    # Find consecutive shift sequences
    i = 0
    while i < len(days):
        current_shift = combined_track.get(days[i], "")
        
        if current_shift in ["D", "N", "AT"]:
            # Start of a consecutive sequence
            sequence_start = i
            sequence_shifts = [current_shift]
            sequence_days = [days[i]]
            
            # Continue while we have consecutive shifts
            j = i + 1
            while j < len(days):
                next_shift = combined_track.get(days[j], "")
                if next_shift in ["D", "N", "AT"]:
                    sequence_shifts.append(next_shift)
                    sequence_days.append(days[j])
                    j += 1
                else:
                    break
            
            # Check if sequence violates rules
            sequence_length = len(sequence_shifts)
            has_night = "N" in sequence_shifts
            
            # Rule: Max 4 in a row, 5 if night included
            max_allowed = 5 if has_night else 4
            
            if sequence_length > max_allowed:
                violations.append({
                    'start_day': sequence_days[0],
                    'end_day': sequence_days[-1],
                    'length': sequence_length,
                    'max_allowed': max_allowed,
                    'has_night': has_night,
                    'shifts': list(zip(sequence_days, sequence_shifts)),
                    'description': f"Consecutive shifts from {sequence_days[0]} to {sequence_days[-1]}: {sequence_length} shifts (max allowed: {max_allowed})"
                })
                result['issues'].append(f"Too many consecutive shifts: {sequence_length} from {sequence_days[0]} to {sequence_days[-1]} (max: {max_allowed})")
            
            # Move to end of this sequence
            i = j
        else:
            i += 1
    
    if violations:
        result['status'] = False
        result['details'] = f"Found {len(violations)} consecutive shift violations"
        result['violations'] = violations
    else:
        result['details'] = "All consecutive shift limits respected"
    
    return result

def format_validation_summary(validation_result):
    """
    Format validation results into a readable summary
    
    Args:
        validation_result (dict): Validation results
        
    Returns:
        dict: Formatted summary
    """
    summary = {
        'overall_valid': validation_result['overall_valid'],
        'total_issues': 0,
        'categories': {}
    }
    
    # Count total issues
    for category, result in validation_result.items():
        if category != 'overall_valid' and isinstance(result, dict):
            if 'issues' in result:
                issue_count = len(result['issues'])
                summary['total_issues'] += issue_count
                summary['categories'][category] = {
                    'status': result['status'],
                    'issue_count': issue_count,
                    'details': result['details']
                }
    
    return summary

def get_validation_recommendations(validation_result):
    """
    Get recommendations for fixing validation issues
    
    Args:
        validation_result (dict): Validation results
        
    Returns:
        list: List of recommendations
    """
    recommendations = []
    
    if not validation_result['shifts_per_pay_period']['status']:
        recommendations.append("Adjust shifts to meet exact pay period requirements")
    
    if not validation_result['night_minimum']['status']:
        recommendations.append("Add more night shifts to meet minimum requirement")
    
    if not validation_result['weekend_minimum']['status']:
        recommendations.append("Add more weekend shifts (Friday nights, Saturday/Sunday shifts)")
    
    if not validation_result['shifts_per_week']['status']:
        recommendations.append("Reduce weekly shifts to fewer than 4 per week")
    
    if not validation_result['rest_requirements']['status']:
        recommendations.append("Ensure proper rest between shifts (2 days after nights, no nights before AT)")
    
    if not validation_result['consecutive_shifts']['status']:
        recommendations.append("Break up consecutive shift sequences (max 4 in a row, 5 if nights included)")
    
    if not validation_result['weekend_group_assignment']['status']:
        recommendations.append("Work required weekend shifts according to your assigned weekend group")
    
    return recommendations

def get_weekend_days_for_highlighting(weekend_group, days):
    """
    Get weekend days that should be highlighted for a specific weekend group
    
    Args:
        weekend_group (str): Weekend group (A, B, C, D, E)
        days (list): List of schedule days
        
    Returns:
        list: List of days that should be highlighted as weekend requirements
    """
    if not weekend_group:
        return []
    
    # Use the inline function
    return get_weekend_days_for_highlighting_inline(weekend_group, days)

def get_weekend_days_for_highlighting_inline(weekend_group, days):
    """
    Get weekend days that should be highlighted for a specific weekend group
    """
    if not weekend_group:
        return []
    
    # Weekend group definitions
    WEEKEND_GROUPS = {
        'A': {
            'periods': [
                ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
                ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 2
                ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 3
            ]
        },
        'B': {
            'periods': [
                ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
                ['Fri B 3', 'Sat B 3', 'Sun B 4'],  # Period 2
                ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 3
            ]
        },
        'C': {
            'periods': [
                ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
                ['Fri B 3', 'Sat B 3', 'Sun B 4']   # Period 2
            ]
        },
        'D': {
            'periods': [
                ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
                ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 2
            ]
        },
        'E': {
            'periods': [
                ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 1
                ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 2
            ]
        }
    }
    
    if weekend_group not in WEEKEND_GROUPS:
        return []
    
    # Get all weekend days for the group
    all_weekend_days = []
    for period in WEEKEND_GROUPS[weekend_group]['periods']:
        all_weekend_days.extend(period)
    
    # Map to actual schedule days
    highlight_days = []
    for weekend_day in all_weekend_days:
        schedule_day = map_weekend_day_to_schedule_day_inline(weekend_day, days)
        if schedule_day:
            highlight_days.append(schedule_day)
    
    return highlight_days