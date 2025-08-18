# modules/track_management/utils.py
"""
Common utilities for track management
"""

import streamlit as st
import pandas as pd

def reset_track_session_state(selected_staff, current_track_data, preassignments=None):
    """
    Reset the track session state for a given staff member to avoid conflicts
    
    Args:
        selected_staff (str): Name of the selected staff member
        current_track_data (dict): Current track data
        preassignments (dict, optional): Dictionary of day -> preassignment value
    """
    # FIXED: Check if using Annual Rebid logic with consistent terminology
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
    
    # For Annual Rebid logic without existing track, set empty track
    if use_database_logic and not st.session_state.get('has_db_track', False):
        # Create an empty track (all days set to "")
        track_copy = {k: "" for k in current_track_data.keys()}
    else:
        # Create a deep copy of the current track
        track_copy = {}
        for k, v in current_track_data.items():
            track_copy[k] = v
    
    # Add preassignments to the track data
    if preassignments:
        for day, preassignment in preassignments.items():
            # Only add preassignments if the day doesn't already have a value
            if day not in track_copy or not track_copy[day]:
                track_copy[day] = preassignment
        
    # Reset the modified track to current track
    st.session_state.modified_track = {
        'staff': selected_staff,
        'track': track_copy,
        'valid': False,  # Start with invalid and require validation
        'is_new': st.session_state.get('is_new_track', use_database_logic and not st.session_state.get('has_db_track', False))
    }
    
    # Reset track changes if they exist
    if 'track_changes' in st.session_state:
        st.session_state.track_changes[selected_staff] = track_copy.copy()
    else:
        st.session_state.track_changes = {selected_staff: track_copy.copy()}
    
    # Clear any potential validation flags
    if 'validation_button' in st.session_state:
        st.session_state.validation_button = False

def create_block_day_headers(block_idx, days_per_block):
    """
    Create day headers for a block
    
    Args:
        block_idx (int): Block index (0-based)
        days_per_block (int): Number of days per block
        
    Returns:
        list: Day headers for the block
    """
    day_headers = []
    for i in range(days_per_block):
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
        
        block_letter = ["A", "B", "C"][block_idx]  # Extract just the letter
        day_headers.append(f"{day_name} {block_letter} {week_num}")
        
    return day_headers

def format_day_name(i, block_idx):
    """
    Format day name based on index and block
    
    Args:
        i (int): Day index within block
        block_idx (int): Block index
        
    Returns:
        str: Formatted day name (e.g. "Sun A 1")
    """
    day_num = i % 7
    week_num = (block_idx * 2) + (i // 7) + 1
    
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    day_name = day_names[day_num]
    
    block_letter = ["A", "B", "C"][block_idx]
    
    return f"{day_name} {block_letter} {week_num}"

def highlight_cells(val):
    """
    Apply highlighting to track cells based on assignment type
    
    Args:
        val: Cell value (could be string, float, or other type)
        
    Returns:
        str: CSS style string
    """
    # Convert val to string to handle all types safely
    val_str = str(val) if val is not None else ""
    
    if val_str == 'D':
        return 'background-color: #d4edda'  # Green for day shifts
    elif val_str == 'N':
        return 'background-color: #cce5ff'  # Blue for night shifts
    elif val and isinstance(val, str) and val not in ['D', 'N', 'Off']:  
        return 'background-color: #e2e3e5'  # Gray for preassignments
    # No longer applying red background to Off days
    return ''

def highlight_combined(df):
    """
    Apply highlighting to a combined dataframe with track and needs info
    
    Args:
        df (DataFrame): DataFrame to style
        
    Returns:
        DataFrame: Styled dataframe
    """
    styles = pd.DataFrame('', index=df.index, columns=df.columns)
    
    # Style the "Current Track" row
    if "Current Track" in df.index:
        for col in df.columns:
            cell_value = df.loc["Current Track", col]
            # Convert to string for safe comparison
            cell_str = str(cell_value) if cell_value is not None else ""
            
            if cell_str == "D":
                styles.loc["Current Track", col] = 'background-color: #d4edda'
            elif cell_str == "N":
                styles.loc["Current Track", col] = 'background-color: #cce5ff'
            # No red background for Off days
            elif cell_value is not None and isinstance(cell_value, str) and cell_str not in ["D", "N", "Off"]:
                # This is a preassignment
                styles.loc["Current Track", col] = 'background-color: #e2e3e5'
    
    # Style the needs rows
    if "Day Shift Needs" in df.index:
        for col in df.columns:
            cell_value = df.loc["Day Shift Needs", col]
            cell_str = str(cell_value) if cell_value is not None else ""
            
            # Day Shift Needs
            if cell_value is not None and isinstance(cell_value, str) and "Need" in cell_str and "No" not in cell_str:
                styles.loc["Day Shift Needs", col] = 'background-color: rgba(40, 167, 69, 0.3)'
            # Specially color rows with "Delta Exceeded" text
            elif cell_value is not None and isinstance(cell_value, str) and "Delta Exceeded" in cell_str:
                styles.loc["Day Shift Needs", col] = 'background-color: rgba(255, 193, 7, 0.2)'
    
    # Style night shift needs
    if "Night Shift Needs" in df.index:
        for col in df.columns:
            cell_value = df.loc["Night Shift Needs", col]
            cell_str = str(cell_value) if cell_value is not None else ""
            
            if cell_value is not None and isinstance(cell_value, str) and "Need" in cell_str and "No" not in cell_str:
                styles.loc["Night Shift Needs", col] = 'background-color: rgba(40, 167, 69, 0.3)'
            # Specially color rows with "Delta Exceeded" text
            elif cell_value is not None and isinstance(cell_value, str) and "Delta Exceeded" in cell_str:
                styles.loc["Night Shift Needs", col] = 'background-color: rgba(255, 193, 7, 0.2)'
    
    return styles

def generate_color_legend():
    """
    Generate HTML for color legend in track displays
    
    Returns:
        str: HTML string for color legend
    """
    return """
    <style>
    .legend-box {
        display: inline-block;
        width: 20px;
        height: 20px;
        margin-right: 5px;
        border-radius: 3px;
    }
    .legend-container {
        display: flex;
        justify-content: center;
        margin-bottom: 20px;
        flex-wrap: wrap;
    }
    .legend-item {
        display: flex;
        align-items: center;
        margin-right: 20px;
        margin-bottom: 10px;
    }
    </style>
    
    <div class="legend-container">
        <div class="legend-item">
            <span class="legend-box" style="background-color: #d4edda;"></span>
            <span>Day Shift</span>
        </div>
        <div class="legend-item">
            <span class="legend-box" style="background-color: #cce5ff;"></span>
            <span>Night Shift</span>
        </div>
        <div class="legend-item">
            <span class="legend-box" style="background-color: #fff3cd;"></span>
            <span>Changed Assignment</span>
        </div>
        <div class="legend-item">
            <span class="legend-box" style="background-color: #e2e3e5;"></span>
            <span>Preassignment</span>
        </div>
        <div class="legend-item">
            <span class="legend-box" style="background-color: #28a745; opacity: 0.3;"></span>
            <span>Role Needed</span>
        </div>
    </div>
    """

def generate_track_grid_css():
    """
    Generate CSS for track grid displays
    
    Returns:
        str: CSS string for track grids
    """
    return """
    <style>
    /* Styling for the grid container */
    .integrated-grid {
        border: 1px solid #ddd;
        border-radius: 5px;
        margin-bottom: 20px;
        overflow: hidden;
    }
    
    /* Styling for the grid headers */
    .grid-header {
        background-color: #f8f9fa;
        padding: 10px;
        font-weight: bold;
        text-align: center;
        border-bottom: 1px solid #ddd;
    }
    
    /* Styling for the grid cells */
    .grid-cell {
        padding: 10px;
        border-bottom: 1px solid #ddd;
        border-right: 1px solid #ddd;
        text-align: center;
    }
    
    /* Styling for selection row */
    .selection-row {
        background-color: #f1f8ff;
        border-top: 2px solid #0366d6;
    }
    
    /* Custom styling for radio buttons to make them fit the grid better */
    div.row-widget.stRadio > div {
        flex-direction: row;
        align-items: center;
        justify-content: center;
    }
    
    div.row-widget.stRadio > div[role="radiogroup"] > label {
        padding: 5px !important;
        min-width: 40px;
        margin: 0 3px !important;
        text-align: center;
    }
    
    /* Styling for preassignment cells */
    .preassignment-cell {
        background-color: #e2e3e5;
        padding: 8px;
        border-radius: 3px;
        text-align: center;
        font-weight: bold;
    }
    </style>
    """

def get_default_session_values():
    """
    Get default values for session state variables
    
    Returns:
        dict: Dictionary of default values
    """
    return {
        'max_day_nurses': 12,
        'max_day_medics': 12,
        'max_night_nurses': 5,
        'max_night_medics': 5,
        'enable_role_delta_filter': False,
        'day_delta_threshold': 3,
        'night_delta_threshold': 2,
        'shifts_per_week': 0,
        'night_minimum': 0,
        'weekend_minimum': 5
    }

def display_validation_metrics(total_shifts, day_shifts, night_shifts, weekend_shifts, shifts_by_week, shifts_per_week):
    """
    Display validation metrics for a track
    
    Args:
        total_shifts (int): Total number of shifts
        day_shifts (int): Number of day shifts
        night_shifts (int): Number of night shifts
        weekend_shifts (int): Number of weekend shifts
        shifts_by_week (list): List of shift counts by week
        shifts_per_week (int): Required shifts per week
    """
    import streamlit as st
    
    # Create a metric display
    metric_cols = st.columns(5)
    metric_cols[0].metric("Total Shifts", total_shifts)
    metric_cols[1].metric("Day Shifts", day_shifts)
    metric_cols[2].metric("Night Shifts", night_shifts)
    metric_cols[3].metric("Weekend Shifts", weekend_shifts)
    
    # Show weekly breakdown
    weekly_shifts = []
    for i, count in enumerate(shifts_by_week):
        week_num = i + 1
        status = "✅" if shifts_per_week == 0 or count == shifts_per_week else "❌"
        weekly_shifts.append(f"Week {week_num}: {count} {status}")
    
    metric_cols[4].markdown("\n".join(weekly_shifts))

def display_validation_status(validation_result):
    """
    Display validation status for a track
    
    Args:
        validation_result (dict): Validation result dictionary
    """
    import streamlit as st
    
    valid = all(result['status'] for result in validation_result.values())
    
    if valid:
        st.success("✅ Track meets all requirements!")
    else:
        st.warning("⚠️ Current track does not meet all requirements. Please make adjustments before submitting.")
        
        # Show the validation issues with consistent formatting
        if not validation_result['shifts_per_week']['status']:
            st.error(f"Shifts per Week: {validation_result['shifts_per_week']['details']}")
        
        if not validation_result['night_minimum']['status']:
            st.error(f"Night Minimum: {validation_result['night_minimum']['details']}")
            
        if not validation_result['weekend_minimum']['status']:
            st.error(f"Weekend Minimum: {validation_result['weekend_minimum']['details']}")
        
        if not validation_result['rest_requirements']['status']:
            st.error("Rest Requirements:")
            for issue in validation_result['rest_requirements']['issues']:
                st.error(f"- {issue}")
# 2. Additional utility function to handle block navigation
def handle_block_navigation(selected_staff, target_block):
    """
    Handle navigation to a specific block while maintaining state
    """
    block_key = f"active_block_{selected_staff}"
    st.session_state[block_key] = target_block
    
    # Clear any validation retention flags
    stay_on_block_key = f"stay_on_block_{selected_staff}"
    if stay_on_block_key in st.session_state:
        del st.session_state[stay_on_block_key]


# 3. Enhanced validation function that maintains block position
def validate_block_with_retention(selected_staff, block, block_days, preassignments):
    """
    Validate a specific block and retain the user's position on that block
    """
    from .utils import build_validation_track
    
    # Validate just this block's portion of the track
    block_track = build_validation_track(selected_staff, block_days, preassignments)
    
    # Store the current block to stay on after validation
    stay_on_block_key = f"stay_on_block_{selected_staff}"
    st.session_state[stay_on_block_key] = block
    
    # Update the active block tracker
    block_key = f"active_block_{selected_staff}"
    st.session_state[block_key] = block
    
    return block_track