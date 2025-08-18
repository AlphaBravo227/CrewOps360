# modules/track_management/display.py
"""
Module for displaying track data with pay period support and individualized weekend minimum
FIXED: Proper AT counting in validation
"""

import streamlit as st
import pandas as pd
# Correct relative imports from parent directory
from ..shift_counter import count_shifts, count_shifts_by_pay_period
from ..track_validator import check_rest_requirements, count_weekend_shifts
from .utils import highlight_cells, create_block_day_headers, display_validation_metrics

def display_track(selected_staff, staff_track, days, shifts_per_pay_period, night_minimum, preassignments=None, track_source="Excel File", weekend_minimum=0):
    """
    Display the current track for the selected staff member
    FIXED: Proper AT counting in all validation functions
    """
    st.subheader(f"Current Track for {selected_staff}")
    
    # Check if using Annual Rebid mode
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
      
    from ..track_source_consistency import display_for_current_track_tab
    display_for_current_track_tab(selected_staff)
    
    # Extract track data
    track_data = {day: staff_track.iloc[0][day] for day in days}
    
    # In Annual Rebid mode, only show Schedule Details
    if use_database_logic:
        # Show the schedule in 2-week blocks (A, B, C) only
        display_schedule_by_blocks(track_data, days, preassignments)
        return
    
    # For Current Track Changes mode, show all the metrics and validation
    # FIXED: Create combined track data with preassignments for metrics calculation - proper AT handling
    combined_track = track_data.copy()
    if preassignments:
        for day, activity in preassignments.items():
            if day not in combined_track or not combined_track[day]:
                # FIXED: Add preassignment as "D" (day shift) for counting purposes - including AT
                combined_track[day] = "D"
    
    # Create summary metrics using consistent counting methods
    total_shifts, day_shifts, night_shifts = count_shifts(combined_track)
    
    # Count weekend shifts with updated function that handles AT
    weekend_shifts = count_weekend_shifts_updated(combined_track, preassignments)
    
    # Pay period breakdown using consistent counting methods
    shifts_by_pay_period = count_shifts_by_pay_period(combined_track, days)
    
    # Display metrics
    metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
    
    with metrics_col1:
        st.metric("Total Shifts", total_shifts)
        
    with metrics_col2:
        st.metric("Day Shifts", day_shifts)
        st.metric("Day %", f"{(day_shifts / total_shifts * 100) if total_shifts else 0:.1f}%")
        
    with metrics_col3:
        st.metric("Night Shifts", night_shifts)
        st.metric("Night %", f"{(night_shifts / total_shifts * 100) if total_shifts else 0:.1f}%")
        
    with metrics_col4:
        st.metric("Weekend Shifts", weekend_shifts)
        st.metric("Weekend %", f"{(weekend_shifts / total_shifts * 100) if total_shifts else 0:.1f}%")
    
    # Display requirements status with individualized weekend minimum
    display_requirements_status(
        shifts_by_pay_period, shifts_per_pay_period,
        night_shifts, night_minimum,
        weekend_shifts, weekend_minimum  # Use the individualized weekend minimum
    )
    
    # Add rest requirement check that includes preassignments
    display_rest_status(track_data, preassignments)
    
    # Show pay period shifts breakdown
    display_pay_period_breakdown(shifts_by_pay_period, shifts_per_pay_period)
    
    # Show the schedule in 2-week blocks (A, B, C)
    display_schedule_by_blocks(track_data, days, preassignments)

def count_weekend_shifts_updated(track_data, preassignments=None):
    """
    Count weekend shifts in a track, including preassignments (including AT)
    FIXED: Properly handle AT preassignments for weekend counting
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
                # FIXED: Treat all preassignments (including AT) as day shifts for weekend counting
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

def display_requirements_status(shifts_by_pay_period, shifts_per_pay_period, night_shifts, night_minimum, weekend_shifts, weekend_minimum):
    """
    Display status of requirements with individualized weekend minimum
    Updated to use pay periods instead of weekly validation
    """
    req_col1, req_col2, req_col3 = st.columns(3)
    
    with req_col1:
        pay_period_status = all(period == shifts_per_pay_period for period in shifts_by_pay_period) if shifts_per_pay_period else True
        
        st.markdown(f"""
        <div style="padding: 10px; border-radius: 5px; background-color: {'#d4edda' if pay_period_status else '#f8d7da'}">
            <span style="font-weight: bold;">Shifts Per Pay Period Requirement:</span> 
            {shifts_per_pay_period} shifts required | 
            <span style="color: {'green' if pay_period_status else 'red'};">
                {pay_period_status and '✅ Met' or '❌ Not Met'}
            </span>
        </div>
        """, unsafe_allow_html=True)
        
    with req_col2:
        night_status = night_shifts >= night_minimum if night_minimum else True
        
        st.markdown(f"""
        <div style="padding: 10px; border-radius: 5px; background-color: {'#d4edda' if night_status else '#f8d7da'}">
            <span style="font-weight: bold;">Night Shift Requirement:</span> 
            {night_minimum} shifts minimum | 
            <span style="color: {'green' if night_status else 'red'};">
                {night_status and '✅ Met' or '❌ Not Met'}
            </span>
        </div>
        """, unsafe_allow_html=True)
        
    with req_col3:
        weekend_status = weekend_shifts >= weekend_minimum
        
        st.markdown(f"""
        <div style="padding: 10px; border-radius: 5px; background-color: {'#d4edda' if weekend_status else '#f8d7da'}">
            <span style="font-weight: bold;">Weekend Shift Requirement:</span> 
            {weekend_minimum} shifts minimum | 
            <span style="color: {'green' if weekend_status else 'red'};">
                {weekend_status and '✅ Met' or '❌ Not Met'}
            </span>
        </div>
        """, unsafe_allow_html=True)

def display_rest_status(track_data, preassignments=None):
    """
    Display status of rest requirements with updated AT handling
    """
    rest_issues = check_rest_requirements_updated(track_data, preassignments)
    if rest_issues:
        st.markdown(f"""
        <div style="padding: 10px; border-radius: 5px; background-color: #f8d7da">
            <span style="font-weight: bold; color: red;">❌ Rest Requirement Issues:</span>
            <ul>{''.join([f'<li>{issue}</li>' for issue in rest_issues])}</ul>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="padding: 10px; border-radius: 5px; background-color: #d4edda">
            <span style="font-weight: bold; color: green;">✅ Rest Requirements Met</span>
        </div>
        """, unsafe_allow_html=True)

def check_rest_requirements_updated(track_data, preassignments=None):
    """
    Check for rest requirement violations in a track, including preassignments with AT handling
    FIXED: Proper AT rest requirement handling
    """
    from ..shift_utils import get_shift_end_time, calculate_rest_conflict
    
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
            # FIXED: Handle AT preassignments specially
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
            # FIXED: Handle AT preassignments specially
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
        
        # FIXED: Special case: Night shift followed by AT (only needs 1 day rest)
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

def display_pay_period_breakdown(shifts_by_pay_period, shifts_per_pay_period):
    """
    Display breakdown of shifts by pay period (14-day blocks)
    """
    st.subheader("Pay Period Shift Breakdown")
    
    pay_periods = ["Pay Period 1 (Block A)", "Pay Period 2 (Block B)", "Pay Period 3 (Block C)"]
    pay_period_data = []
    
    for i, (pay_period_name, shift_count) in enumerate(zip(pay_periods, shifts_by_pay_period)):
        status = "✅" if shifts_per_pay_period == 0 or shift_count == shifts_per_pay_period else "❌"
        pay_period_data.append({
            "Pay Period": pay_period_name,
            "Shifts": shift_count,
            "Status": status
        })
    
    pay_period_df = pd.DataFrame(pay_period_data)
    st.dataframe(pay_period_df, use_container_width=True)

def display_schedule_by_blocks(track_data, days, preassignments=None):
    """
    Display the schedule broken down by blocks
    """
    st.subheader("Schedule Details")
    
    # Define the blocks
    blocks = ["A", "B", "C"]
    
    # Create a block for each 2-week period
    for block_idx, block in enumerate(blocks):
        st.markdown(f"#### Block {block} (Pay Period {block_idx + 1})")
        
        # Calculate the days for this block (2 weeks = 14 days)
        start_idx = block_idx * 14
        end_idx = start_idx + 14
        block_days = days[start_idx:end_idx]
        
        # Create column headers (days)
        day_headers = []
        for i in range(14):
            day_num = i % 7
            week_num = (block_idx * 2) + (i // 7) + 1  # Adjust week number based on block
            day_name = ""
            if day_num == 0:
                day_name = "Sun"
            elif day_num == 1:
                day_name = "Mon"
            elif day_num == 2:
                day_name = "Tue"
            elif day_num == 3:
                day_name = "Wed"
            elif day_num == 4:
                day_name = "Thu"
            elif day_num == 5:
                day_name = "Fri"
            elif day_num == 6:
                day_name = "Sat"
            day_headers.append(f"{day_name} {block} {week_num}")
        
        # Create a dictionary for the dataframe
        data = {
            "Assignment": []
        }
        
        # Fill in assignments from track data and preassignments
        for day in block_days:
            if day in track_data and track_data[day]:
                # Use track data if available
                data["Assignment"].append(track_data[day])
            elif preassignments and day in preassignments:
                # Use preassignment if available and no track data
                data["Assignment"].append(f"Pre: {preassignments[day]}")
            else:
                # Otherwise empty
                data["Assignment"].append("")
        
        # Create dataframe with days as columns
        df = pd.DataFrame(data, index=day_headers)
        
        # Custom styling function - handles AT preassignments
        def custom_highlight_cells(val):
            """
            Apply highlighting to cells based on cell value
            
            Args:
                val: Cell value (could be string, float, or other type)
                
            Returns:
                str: CSS style string
            """
            # Convert val to string to handle all types safely
            val_str = str(val) if val is not None else ""
            
            if val_str == "D":
                return 'background-color: #d4edda'  # Green for day shifts
            elif val_str == "N":
                return 'background-color: #cce5ff'  # Blue for night shifts
            elif isinstance(val, str) and val.startswith("Pre:"):
                return 'background-color: #e2e3e5; font-weight: bold'  # Gray for preassignments
            else:
                return ''  # No background for off days
        
        # Display the dataframe with styles - transpose to show days as columns
        st.dataframe(
            df.T.style.map(custom_highlight_cells),
            use_container_width=True
        )
        
        # Add some spacing between blocks
        st.write("")

def display_track_summary(track_data, days, shifts_per_pay_period, night_minimum, weekend_minimum=5, preassignments=None):
    """
    Display a summary of track data for validation
    FIXED: Proper AT counting in validation summary
    """
    from ..track_validator import validate_track
    
    # FIXED: Create combined track data with preassignments for metrics calculation - proper AT handling
    combined_track = track_data.copy()
    if preassignments:
        for day, activity in preassignments.items():
            if day not in combined_track or not combined_track[day]:
                # FIXED: Add preassignment as "D" (day shift) for counting purposes - including AT
                combined_track[day] = "D"
    
    # Create summary metrics using consistent counting methods
    total_shifts, day_shifts, night_shifts = count_shifts(combined_track)
    
    # Count weekend shifts with AT handling
    weekend_shifts = count_weekend_shifts_updated(combined_track, preassignments)
    
    # Pay period breakdown using consistent counting methods
    shifts_by_pay_period = count_shifts_by_pay_period(combined_track, days)
    
    # Validate the track with updated function using individualized weekend minimum
    validation_result = validate_track_updated(
        track_data,
        shifts_per_pay_period,
        night_minimum,
        weekend_minimum,  # Use the individualized weekend minimum
        preassignments
    )
    
    # Store validity in session state
    valid = all(result['status'] for result in validation_result.values())
    if 'modified_track' in st.session_state:
        st.session_state.modified_track['valid'] = valid
    st.session_state.track_valid = valid
    
    # Display metrics
    display_validation_metrics(
        total_shifts, day_shifts, night_shifts, 
        weekend_shifts, shifts_by_pay_period, shifts_per_pay_period
    )
    
    # Display validation status
    display_validation_status(validation_result)
    
    return valid

def display_validation_status(validation_result):
    """
    Display validation status for a track
    Updated to use pay periods instead of weekly validation
    """
    valid = all(result['status'] for result in validation_result.values())
    
    if valid:
        st.success("✅ Track meets all requirements!")
    else:
        st.warning("⚠️ Current track does not meet all requirements. Please make adjustments before submitting.")
        
        # Show the validation issues with consistent formatting
        if not validation_result['shifts_per_pay_period']['status']:
            st.error(f"Shifts per Pay Period: {validation_result['shifts_per_pay_period']['details']}")
        
        if not validation_result['night_minimum']['status']:
            st.error(f"Night Minimum: {validation_result['night_minimum']['details']}")
            
        if not validation_result['weekend_minimum']['status']:
            st.error(f"Weekend Minimum: {validation_result['weekend_minimum']['details']}")
        
        if not validation_result['rest_requirements']['status']:
            st.error("Rest Requirements:")
            for issue in validation_result['rest_requirements']['issues']:
                st.error(f"- {issue}")

def validate_track_updated(track_data, shifts_per_pay_period=0, night_minimum=0, weekend_minimum=5, preassignments=None):
    """
    Validate a track against requirements, including preassignments with AT handling and individualized weekend minimum
    FIXED: Proper AT counting in all validation calculations
    """
    from ..shift_counter import count_shifts, count_shifts_by_pay_period
    
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
    
    # FIXED: Create a combined track data dictionary for validation - proper AT handling
    combined_track = track_data.copy()
    if preassignments:
        for day, value in preassignments.items():
            if day not in combined_track or not combined_track[day]:
                # FIXED: Treat all preassignments (including AT) as day shifts for shift counting
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
    
    # Check weekend minimum with AT handling - use individualized weekend minimum
    weekend_shifts = count_weekend_shifts_updated(track_data, preassignments)
    results['weekend_minimum']['status'] = weekend_shifts >= weekend_minimum if weekend_minimum else True
    results['weekend_minimum']['details'] = f"Found {weekend_shifts} weekend shifts, minimum required: {weekend_minimum}"
    
    # Check rest requirements with AT handling
    rest_issues = check_rest_requirements_updated(track_data, preassignments)
    
    if rest_issues:
        results['rest_requirements']['status'] = False
        results['rest_requirements']['issues'] = rest_issues
    
    return results