# modules/track_management/editor.py
"""
UPDATED: Track editor with enhanced hypothetical scheduler display and fixed weekend group highlighting
"""

import streamlit as st
import pandas as pd
from modules.enhanced_track_validator import validate_track_comprehensive
from modules.enhanced_validation_display import display_comprehensive_validation, create_validation_summary_card, get_weekend_group_highlighting_info
from modules.track_modification_core import calculate_all_modification_options
from modules.db_utils import get_track_from_db
from modules.track_management.utils import reset_track_session_state
from modules.track_management.preassignment import display_preassignments

def modify_track_enhanced(
    selected_staff,
    staff_track,
    preferences_df,
    current_tracks_df,
    days,
    staff_col_prefs,
    staff_col_tracks,
    role_col,
    no_matrix_col,
    reduced_rest_col,
    seniority_col,
    shifts_per_pay_period,
    night_minimum,
    preassignments=None,
    is_new_track=False,
    weekend_minimum=0,
    requirements_df=None
):
    """
    Streamlined track modification with continuous validation and enhanced hypothetical scheduler display
    """
    st.subheader(f"Track Modification for {selected_staff}")
    
    # Get weekend group for this staff member
    weekend_group = None
    if requirements_df is not None:
        from modules.weekend_group_validator import get_staff_weekend_group
        weekend_group = get_staff_weekend_group(selected_staff, requirements_df)
    
    # Display requirements prominently
    st.markdown("### 📋 Requirements for Track Modification")
    req_cols = st.columns(4)
    with req_cols[0]:
        st.metric("Shifts per Pay Period", shifts_per_pay_period, help="Exact match required")
    with req_cols[1]:
        st.metric("Night Minimum", night_minimum, help="Minimum required (>=)")
    with req_cols[2]:
        st.metric("Weekend Minimum", weekend_minimum, help="Minimum required (>=)")
    with req_cols[3]:
        if weekend_group:
            st.metric("Weekend Group", weekend_group, help="Your assigned weekend group")
        else:
            st.metric("Weekend Group", "None", help="No weekend group assigned")
    
    # Check track source setting
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
    has_db_track = st.session_state.get('has_db_track', False)

    # Display track source info
    from ..track_source_consistency import display_for_track_modification
    display_for_track_modification(selected_staff)

    
    # Get track source information
    db_result = get_track_from_db(selected_staff)
    has_db_track = db_result[0]
    
    # Add banner for track status
    if is_new_track:
        st.info("🆕 Creating a new track. Start by selecting the days you want to work.")
    elif has_db_track:
        track_data = db_result[1]['track_data']
        submission_date = db_result[1]['submission_date']
        is_approved = db_result[1]['is_approved']
        version = db_result[1]['version']
        st.info(f"✏️ Modifying database track (version {version}, submitted on {submission_date}).")
    else:
        st.info("✏️ Modifying reference track from Excel file.")
    
    # Extract staff information
    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
    staff_role = staff_info[role_col]
    
    # Show role delta filter status if enabled
    if st.session_state.get('enable_role_delta_filter', False):
        effective_role = "nurse" if staff_role == "dual" else staff_role
        st.info(f"""
        🔍 **Role Delta Filter Enabled**
        - Day Shift Threshold: {st.session_state.get('day_delta_threshold', 3)}
        - Night Shift Threshold: {st.session_state.get('night_delta_threshold', 2)}
        - Staff Role: {staff_role} (treated as {effective_role} for needs calculation)
        """)
    
    # Hardcoded shift capacity settings
    max_day_nurses = 10
    max_day_medics = 10
    max_night_nurses = 6
    max_night_medics = 5
    
    # Generate track modification options
    with st.spinner("Analyzing schedule needs and preferences..."):
        modification_results = calculate_all_modification_options(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
            reduced_rest_col, seniority_col, max_day_nurses=max_day_nurses,
            max_day_medics=max_day_medics, max_night_nurses=max_night_nurses,
            max_night_medics=max_night_medics
        )
        
        options_by_day = modification_results["options_by_day"]
        day_assignments = modification_results["day_assignments"]
        night_assignments = modification_results["night_assignments"]
        assignment_details = modification_results["assignment_details"]
    
    # Set up reference track
    if use_database_logic:
        if has_db_track:
            reference_track = db_result[1]['track_data'].copy()
        else:
            reference_track = {day: staff_track.iloc[0][day] for day in days}
    else:
        reference_track = {day: staff_track.iloc[0][day] for day in days}
    
    # Initialize track changes
    if 'track_changes' not in st.session_state:
        st.session_state.track_changes = {}
        
    if selected_staff not in st.session_state.track_changes:
        if is_new_track or (use_database_logic and not has_db_track):
            track_data = {day: "" for day in days}
        else:
            track_data = reference_track.copy()
        
        # Add preassignments
        if preassignments:
            for day, preassignment in preassignments.items():
                if preassignment == "AT":
                    track_data[day] = "AT"
                else:
                    track_data[day] = "D"
        
        st.session_state.track_changes[selected_staff] = track_data
    
    # Initialize modified_track
    if 'modified_track' not in st.session_state:
        st.session_state.modified_track = {
            'staff': selected_staff,
            'track': st.session_state.track_changes[selected_staff].copy(),
            'valid': False,
            'is_new': is_new_track
        }
    elif st.session_state.modified_track.get('staff') != selected_staff:
        st.session_state.modified_track = {
            'staff': selected_staff,
            'track': st.session_state.track_changes[selected_staff].copy(),
            'valid': False,
            'is_new': is_new_track
        }
    
    # User guidance
    st.markdown("""
    ### How to Modify Your Track
    
    1. Select days where you want to work by clicking on the radio buttons
    2. Use **"Validate Block"** buttons to check and lock in individual 2-week blocks before proceeding to next block
    3. Preassignments (if any) are shown as selected and locked radio buttons
    4. Days where your role is needed are highlighted in green
    5. **Weekend group days are highlighted in yellow** (if assigned to a weekend group)
    6. Go to the Submission tab when you're satisfied with your track
    """)
    
    # Show preassignments if any
    if preassignments:
        display_preassignments(selected_staff, preassignments)

    # CONTINUOUS VALIDATION - This runs automatically when track changes
    st.markdown("### 🎯 Validation Dashboard")
    
    from modules.track_source_consistency import display_for_validation
    display_for_validation()
    
    # Get current track for validation
    current_track = build_validation_track(selected_staff, days, preassignments)
    
    # Display comprehensive validation WITH weekend group information
    # This automatically updates whenever the user makes changes due to Streamlit's reactive nature
    is_valid = display_comprehensive_validation(
        current_track, days, shifts_per_pay_period, night_minimum, 
        weekend_minimum, preassignments, weekend_group, requirements_df, selected_staff
    )
    
    # Store validity in session state (this updates automatically)
    st.session_state.modified_track['valid'] = is_valid
    st.session_state.track_valid = is_valid
    
    # Display track modification interface WITH enhanced hypothetical scheduler display
    display_track_modification_interface_enhanced(
        selected_staff, options_by_day, reference_track, days, 
        preassignments, use_database_logic, has_db_track, staff_role, weekend_group,
        day_assignments, night_assignments, assignment_details
    )
    
    # Final validation with proper navigation and clear description
    st.markdown("### 📊 Final Track Validation")
    st.info("**Purpose:** This performs a comprehensive validation of your entire 6-week track against all requirements including pay periods, weekend groups, consecutive shifts, and rest requirements. Use this before going to the Submission tab.")
    
    if st.button("Validate Complete Track", key="final_validation", use_container_width=True, type="primary"):
        complete_track = build_validation_track(selected_staff, days, preassignments)
        final_valid = display_comprehensive_validation(
            complete_track, days, shifts_per_pay_period, night_minimum, 
            weekend_minimum, preassignments, weekend_group, requirements_df, selected_staff
        )
        
        st.session_state.modified_track['valid'] = final_valid
        st.session_state.track_valid = final_valid
        
        if final_valid:
            st.success("✅ Your track is valid! Go to the Submission tab to submit your changes.")
        else:
            st.error("Your track does not meet all requirements. Please review the issues above and make adjustments.")

def display_track_modification_interface_enhanced(selected_staff, options_by_day, reference_track, days, preassignments, use_database_logic, has_db_track, staff_role, weekend_group=None, day_assignments=None, night_assignments=None, assignment_details=None):
    """
    UPDATED: Display the track modification interface with enhanced hypothetical scheduler display and fixed weekend group highlighting
    """
    
    # Get weekend group highlighting information with FIXED mapping
    weekend_highlight_info = get_weekend_group_highlighting_info_fixed(weekend_group, days)
    weekend_highlight_days = weekend_highlight_info.get('highlight_days', [])
    
    # Color legend - UPDATED to include weekend group highlighting  
    legend_items = [
        ('<span class="legend-box" style="background-color: #d4edda;"></span>', 'Day Shift'),
        ('<span class="legend-box" style="background-color: #cce5ff;"></span>', 'Night Shift'),
        ('<span class="legend-box" style="background-color: #e2e3e5;"></span>', 'Preassignment (Locked)'),
        ('<span class="legend-box" style="background-color: #28a745; opacity: 0.3;"></span>', 'Role Needed'),
        ('<span style="font-weight: bold">*</span>', 'No Preference Data')
    ]
    
    if not use_database_logic:
        legend_items.insert(-1, ('<span class="legend-box" style="background-color: #fff3cd;"></span>', 'Changed Assignment'))
    
    # NEW: Add weekend group highlighting to legend
    if weekend_group and weekend_highlight_days:
        legend_items.insert(-1, ('<span class="legend-box" style="background-color: #fff3cd; border: 2px solid #f0ad4e;"></span>', f'Weekend Group {weekend_group} Days'))
    
    legend_html = f"""
    <style>
    .legend-box {{
        display: inline-block;
        width: 20px;
        height: 20px;
        margin-right: 5px;
        border-radius: 3px;
    }}
    .legend-container {{
        display: flex;
        justify-content: center;
        margin-bottom: 20px;
        flex-wrap: wrap;
    }}
    .legend-item {{
        display: flex;
        align-items: center;
        margin-right: 20px;
        margin-bottom: 10px;
    }}
    </style>
    
    <div class="legend-container">
        {''.join([f'<div class="legend-item">{box}<span>{text}</span></div>' for box, text in legend_items])}
    </div>
    """
    
    st.markdown(legend_html, unsafe_allow_html=True)
    
    # Show weekend group information if available - FIXED formatting
    if weekend_group:
        st.info(f"🟡 **Weekend Group {weekend_group}:** Days highlighted in yellow are part of your weekend group requirements.")
    
    # Create tabs for blocks
    blocks = ["A", "B", "C"]  # Use simple letters
    block_tabs = st.tabs([f"Block {block}" for block in blocks])
    
    # Process each block
    days_per_block = 14
    for block_idx, block_tab in enumerate(block_tabs):
        with block_tab:
            start_idx = block_idx * days_per_block
            end_idx = min(start_idx + days_per_block, len(days))
            block_days = days[start_idx:end_idx]
            
            # Split into weeks with validation buttons between
            for week_idx in range(2):
                week_start = week_idx * 7
                week_end = min(week_start + 7, len(block_days))
                
                if week_start >= len(block_days):
                    continue
                
                week_days = block_days[week_start:week_end]
                week_num = block_idx * 2 + week_idx + 1
                
                st.markdown(f"#### Week {week_num}")
                
                # Create table data
                week_data = []
                day_headers = []
                
                for day_idx, day in enumerate(week_days):
                    day_parts = day.split()
                    day_name = day_parts[0] if day_parts else "Unknown"
                    day_headers.append(day_name)
                
                # Reference track row
                reference_row = {"Row Type": "Reference Track"}
                for idx, day in enumerate(week_days):
                    reference_assignment = reference_track.get(day, "")
                    reference_row[day_headers[idx]] = reference_assignment if reference_assignment else "Off"
                
                week_data.append(reference_row)
                
                # Modified track row
                editable_row = {"Row Type": "Proposed Track"}
                for idx, day in enumerate(week_days):
                    is_preassigned = preassignments and day in preassignments
                    
                    if is_preassigned:
                        preassign_value = preassignments[day]
                        editable_row[day_headers[idx]] = f"Pre: {preassign_value}"
                    else:
                        current_value = st.session_state.track_changes[selected_staff].get(day, "")
                        editable_row[day_headers[idx]] = current_value if current_value else "Off"
                
                week_data.append(editable_row)
                
                # Create and display dataframe
                df = pd.DataFrame(week_data)
                df = df.set_index("Row Type")
                
                # Custom styling with weekend group highlighting
                def highlight_cells(df):
                    styles = pd.DataFrame('', index=df.index, columns=df.columns)
                    for idx, row in df.iterrows():
                        for col_idx, col in enumerate(df.columns):
                            val = row[col]
                            # day = week_days[col_idx] if col_idx < len(week_days) else None
                            # Apply regular shift highlighting
                            if val == "D":
                                styles.loc[idx, col] = 'background-color: #d4edda'
                            elif val == "N":
                                styles.loc[idx, col] = 'background-color: #cce5ff'
                            elif "Pre:" in str(val):
                                styles.loc[idx, col] = 'background-color: #e2e3e5; font-weight: bold'
                    # Highlight changes in Current Track Changes mode
                    if not use_database_logic and "Reference Track" in df.index and "Proposed Track" in df.index:
                        for col in df.columns:
                            ref_val = str(df.loc["Reference Track", col]).replace("Off", "")
                            mod_val = str(df.loc["Proposed Track", col]).replace("Off", "")
                            if "Pre:" in ref_val or "Pre:" in mod_val:
                                continue
                            if ref_val != mod_val:
                                styles.loc["Proposed Track", col] += '; border: 2px solid #ffc107'
                    return styles
                
                st.dataframe(df.style.apply(highlight_cells, axis=None), use_container_width=True)
                
                # Create radio button selectors with ENHANCED hypothetical scheduler display
                cols = st.columns(len(week_days))
                
                for idx, day in enumerate(week_days):
                    with cols[idx]:
                        is_preassigned = preassignments and day in preassignments
                        is_weekend_group_day = day in weekend_highlight_days
                        
                        if is_preassigned:
                            # Handle preassignments (existing logic)
                            preassign_value = preassignments[day]
                            
                            radio_options = ["Off", "D", "N"]
                            if preassign_value == "AT":
                                radio_options = ["Off", "D", "N", "AT"]
                                selected_option = "AT"
                            elif preassign_value == "D":
                                selected_option = "D"
                            elif preassign_value == "N":
                                selected_option = "N"
                            else:
                                selected_option = "D"
                            
                            try:
                                preselected_index = radio_options.index(selected_option)
                            except ValueError:
                                preselected_index = 0
                            
                            # Disabled radio for preassignments
                            st.radio(
                                f"Select for {day}",
                                options=radio_options,
                                index=preselected_index,
                                horizontal=True,
                                disabled=True,
                                key=f"select_preassign_{selected_staff}_{day}".replace(" ", "_").replace("/", "_")
                            )
                            
                            # Force preassigned value
                            st.session_state.track_changes[selected_staff][day] = selected_option
                            st.session_state.modified_track['track'][day] = selected_option
                            
                            # Show preassignment indicator with FIXED weekend group info
                            preassign_style = "background-color: #e2e3e5; padding: 5px; border-radius: 3px; text-align: center; margin-top: 5px;"
                            if is_weekend_group_day:
                                preassign_style = "background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center; margin-top: 5px;"
                            
                            weekend_display = ""
                            if is_weekend_group_day:
                                weekend_display = f'🟡 Weekend Group {weekend_group}'
                            
                            st.markdown(f"""
                            <div style="{preassign_style}">
                                <strong>🔒 Preassigned: {preassign_value}</strong>
                                {weekend_display}
                            </div>
                            """, unsafe_allow_html=True)
                            
                        else:
                            # Regular day selection with ENHANCED hypothetical scheduler display
                            reference_value = reference_track.get(day, "")
                            current_value = st.session_state.track_changes[selected_staff].get(day, "")
                            
                            # Get availability info
                            day_info = options_by_day[day]
                            day_available = day_info["day_shift"]["is_needed"]
                            night_available = day_info["night_shift"]["is_needed"]
                            
                            # Build options list
                            available_options = []
                            
                            if not use_database_logic or day_available or night_available:
                                available_options.append("Off")
                            
                            if day_available or current_value == "D":
                                available_options.append("D")
                            
                            if night_available or current_value == "N":
                                available_options.append("N")
                            
                            if not available_options:
                                st.markdown("""
                                <div style="background-color: #f8f9fa; padding: 10px; border-radius: 5px; text-align: center;">
                                    <strong>No shifts available</strong>
                                </div>
                                """, unsafe_allow_html=True)
                                continue
                            
                            # Default selection
                            if current_value in available_options:
                                default_idx = available_options.index(current_value)
                            else:
                                default_idx = 0
                            
                            # Create radio selector with unique key that causes automatic rerun when changed
                            selection = st.radio(
                                f"Select for {day}",
                                options=available_options,
                                index=default_idx,
                                horizontal=True,
                                key=f"select_{selected_staff}_{day}".replace(" ", "_").replace("/", "_")
                            )
                            
                            # Update track changes - this triggers automatic validation due to Streamlit's reactive nature
                            if selection == "Off" and current_value != "":
                                st.session_state.track_changes[selected_staff][day] = ""
                                st.session_state.modified_track['track'][day] = ""
                                st.session_state.modified_track['valid'] = False
                            elif selection != "Off" and selection != current_value:
                                st.session_state.track_changes[selected_staff][day] = selection
                                st.session_state.modified_track['track'][day] = selection
                                st.session_state.modified_track['valid'] = False
                            
                            # ENHANCED: Show availability indicators with hypothetical scheduler results
                            if day_available:
                                # Get enhanced information from hypothetical scheduler
                                day_needs_count = day_info["day_shift"].get("needs_count", 0)
                                day_pref = day_info["day_shift"].get("preference_score", None)
                                day_shift_name = ""
                                
                                # Get hypothetical shift assignment if available
                                if day_assignments and day in day_assignments:
                                    day_shift_name = day_assignments[day]
                                
                                # Check if this is a Friday (day shifts on Friday don't count as weekend)
                                day_parts = day.split()
                                is_friday = len(day_parts) > 0 and day_parts[0] == "Fri"
                                
                                # Don't highlight Friday day shifts yellow (only Friday nights count as weekend)
                                if is_weekend_group_day and not is_friday:
                                    indicator_style = "background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center; margin-bottom: 5px;"
                                    weekend_indicator = f'Weekend Group {weekend_group}'
                                else:
                                    indicator_style = "background-color: rgba(40, 167, 69, 0.3); padding: 5px; border-radius: 3px; text-align: center; margin-bottom: 5px;"
                                    weekend_indicator = ''
                                
                                # UPDATED: Enhanced display with remaining needs and hypothetical scheduler results
                                pref_display = f'<br>Preference: {day_pref}' if day_pref else ''
                                shift_display = f'<br>Hypothetical: {day_shift_name}' if day_shift_name else ''
                                weekend_display = f'🟡 {weekend_indicator}' if weekend_indicator else ''
                                
                                # If there is a need but no assignment, show asterisk and description
                                if day_needs_count > 0 and not day_shift_name:
                                    day_shift_name = "* <span style='font-size:smaller;'>(Need exists but all named shifts are filled)</span>"
                                
                                st.markdown(f"""
                                <div style="{indicator_style}">
                                    <strong>Day Need ({day_needs_count})</strong>
                                    {shift_display}
                                    {pref_display}
                                    {weekend_display}
                                </div>
                                """, unsafe_allow_html=True)
                            
                            if night_available:
                                # Get enhanced information from hypothetical scheduler
                                night_needs_count = day_info["night_shift"].get("needs_count", 0)
                                night_pref = day_info["night_shift"].get("preference_score", None)
                                night_shift_name = ""
                                
                                # Get hypothetical shift assignment if available
                                if night_assignments and day in night_assignments:
                                    night_shift_name = night_assignments[day]
                                
                                # If there is a need but no assignment, show asterisk and description
                                if night_needs_count > 0 and not night_shift_name:
                                    night_shift_name = "* <span style='font-size:smaller;'>(Need exists but all named shifts are filled)</span>"
                                
                                # Night shifts always count as weekend (including Friday nights)
                                if is_weekend_group_day:
                                    indicator_style = "background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center;"
                                    weekend_indicator = f'Weekend Group {weekend_group}'
                                else:
                                    indicator_style = "background-color: rgba(40, 167, 69, 0.3); padding: 5px; border-radius: 3px; text-align: center;"
                                    weekend_indicator = ''
                                
                                # UPDATED: Enhanced display with remaining needs and hypothetical scheduler results
                                pref_display = f'<br>Preference: {night_pref}' if night_pref else ''
                                shift_display = f'<br>Hypothetical: {night_shift_name}' if night_shift_name else ''
                                weekend_display = f'🟡 {weekend_indicator}' if weekend_indicator else ''
                                
                                st.markdown(f"""
                                <div style="{indicator_style}">
                                    <strong>Night Need ({night_needs_count})</strong>
                                    {shift_display}
                                    {pref_display}
                                    {weekend_display}
                                </div>
                                """, unsafe_allow_html=True)
                            
                            # Show weekend group indicator even if no shifts are needed
                            if is_weekend_group_day and not day_available and not night_available:
                                # Check if this is a Friday (day shifts on Friday don't count as weekend)
                                day_parts = day.split()
                                is_friday = len(day_parts) > 0 and day_parts[0] == "Fri"
                                
                                # Only show weekend group indicator for non-Friday days, or Friday with note about night shifts
                                if not is_friday:
                                    st.markdown(f"""
                                    <div style="background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center; margin-top: 5px;">
                                        <strong>🟡 Weekend Group {weekend_group}</strong>
                                        <br>This day is part of your weekend requirements
                                    </div>
                                    """, unsafe_allow_html=True)
                                else:
                                    st.markdown(f"""
                                    <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 5px; border-radius: 3px; text-align: center; margin-top: 5px;">
                                        <strong>Weekend Group {weekend_group}</strong>
                                        <br><small>Only Friday <em>night</em> shifts count as weekend</small>
                                    </div>
                                    """, unsafe_allow_html=True)
                
                # Add Validate Block button between Week 1 and Week 2 of each block
                if week_idx == 0:  # After displaying Week 1, before Week 2
                    st.markdown("---")
                    validate_col1, validate_col2, validate_col3 = st.columns([1, 2, 1])
                    with validate_col2:
                        if st.button(f"🔍 Validate and Save Block {blocks[block_idx]}", 
                                   key=f"validate_block_{blocks[block_idx]}_{selected_staff}", 
                                   use_container_width=True):
                            # Validate just this block's portion of the track
                            block_track = build_validation_track(selected_staff, block_days, preassignments)
                            st.success(f"Block {blocks[block_idx]} validation complete! Check the dashboard above for results.")
                            if st.session_state.get('track_valid', False):
                                st.balloons()
                    st.markdown("---")
                    
                st.markdown("---")  # Separator between weeks

def get_weekend_group_highlighting_info_fixed(weekend_group, days):
    """
    FIXED: Get information about which days should be highlighted for weekend group requirements
    This version properly handles Block A highlighting
    """
    if not weekend_group:
        return {'highlight_days': [], 'weekend_group': None}
    
    try:
        # Use fixed function to avoid import issues
        highlight_days = get_weekend_days_for_highlighting_fixed(weekend_group, days)
        
        return {
            'highlight_days': highlight_days,
            'weekend_group': weekend_group,
            'highlight_color': '#fff3cd',  # Light yellow
            'highlight_info': f"Weekend Group {weekend_group} required days"
        }
    except Exception as e:
        return {'highlight_days': [], 'weekend_group': weekend_group, 'error': str(e)}

def get_weekend_days_for_highlighting_fixed(weekend_group, days):
    """
    FIXED: Get weekend days that should be highlighted for a specific weekend group
    This version properly handles all blocks including Block A
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
    
    # Map to actual schedule days with FIXED mapping logic
    highlight_days = []
    for weekend_day in all_weekend_days:
        schedule_day = map_weekend_day_to_schedule_day_fixed(weekend_day, days)
        if schedule_day:
            highlight_days.append(schedule_day)
    
    return highlight_days

def map_weekend_day_to_schedule_day_fixed(weekend_day, days):
    """
    FIXED: Map a weekend group day (e.g., 'Fri A 1') to actual schedule day
    This version properly handles Block A and all other blocks consistently
    """
    # Parse the weekend day format
    parts = weekend_day.split()
    if len(parts) != 3:
        return None
    
    day_name, block, week = parts
    
    # Find matching day in schedule with improved logic
    for schedule_day in days:
        schedule_parts = schedule_day.split()
        if len(schedule_parts) >= 3:  # Ensure we have day, block, and week
            schedule_day_name = schedule_parts[0]
            schedule_block = schedule_parts[1]
            schedule_week = schedule_parts[2]
            
            # Check if day names match (Fri, Sat, Sun)
            if schedule_day_name == day_name:
                # Check exact match first
                if schedule_block == block and schedule_week == week:
                    return schedule_day
        
        # Fallback: check if the schedule day contains both block and week
        # This handles different formatting conventions
        if day_name in schedule_day and block in schedule_day and week in schedule_day:
            # Make sure it's the right day of week
            if schedule_day.startswith(day_name):
                return schedule_day
    
    return None

def build_validation_track(selected_staff, days, preassignments=None):
    """Build complete track for validation"""
    # Initialize validation_track with empty values for all days
    validation_track = {day: "" for day in days}
    
    # Update with track changes if they exist
    if 'track_changes' in st.session_state and selected_staff in st.session_state.track_changes:
        validation_track.update(st.session_state.track_changes[selected_staff])
    
    # Ensure preassignments are included
    if preassignments:
        for day, preassign_value in preassignments.items():
            if preassign_value == "AT":
                validation_track[day] = "AT"
            elif preassign_value in ["D", "N"]:
                validation_track[day] = preassign_value
            else:
                validation_track[day] = "D"
    
    return validation_track

st.markdown("---")  # Add a separator at the end of the function