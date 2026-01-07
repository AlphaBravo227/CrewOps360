# modules/track_management/__init__.py - UPDATED WITH PREFERENCE EDITOR TAB
"""
Updated track management interface with enhanced validation, weekend groups, preference editor, and separate validation tab
"""

__version__ = "2.3.0"

import streamlit as st
import pandas as pd

# Import the enhanced validation modules
from ..enhanced_track_validator import validate_track_comprehensive
from ..enhanced_validation_display import display_comprehensive_validation
from ..track_source_consistency import display_for_validation
display_for_validation()

# Import other components
from .display import display_track
from .preference_display import display_preferences
from .editor import modify_track_enhanced  # Updated editor
from .submission import submit_track
from .preassignment import get_staff_preassignments
from .utils import reset_track_session_state
from ..db_utils import get_track_from_db
from ..hypothetical_scheduler_new import (
    generate_hypothetical_schedule_new as generate_hypothetical_schedule,
    display_hypothetical_results_new as display_hypothetical_results
)
# Import the new location-based preference editor (v2) and keep old for history
from ..preference_editor import display_location_preference_editor, display_preference_history

def display_staff_track_interface(
    selected_staff,
    preferences_df, 
    current_tracks_df, 
    requirements_df,
    days,
    staff_col_prefs,
    staff_col_tracks,
    role_col,
    no_matrix_col,
    reduced_rest_col,
    seniority_col,
    preassignment_df=None
):
    """
    Main interface function for staff track management with enhanced validation including weekend groups and preference editing
    """
    st.header("Staff Track Management")
    
    # Check if creating a new track
    create_new = st.session_state.get('create_new_track', False)
    if create_new:
        st.session_state['create_new_track'] = False
        st.session_state['is_new_track'] = True
    
    # Check track source setting
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
    st.session_state['using_database_logic'] = use_database_logic

    # Extract requirements for this staff member including weekend group
    shifts_per_pay_period = 0
    night_minimum = 0
    weekend_minimum = 0
    weekend_group = None
    
    if requirements_df is not None and not requirements_df.empty:
        try:
            # Find staff member
            staff_found = False
            staff_req = None
            
            possible_staff_cols = [
                requirements_df.columns[0],
                'STAFF NAME', 'Staff Name', 'staff name', 'Name', 'NAME'
            ]
            
            for col_name in possible_staff_cols:
                if col_name in requirements_df.columns:
                    staff_req = requirements_df[requirements_df[col_name] == selected_staff]
                    if not staff_req.empty:
                        staff_found = True
                        break
                    
                    staff_req = requirements_df[requirements_df[col_name].str.lower() == selected_staff.lower()]
                    if not staff_req.empty:
                        staff_found = True
                        break
            
            if staff_found and not staff_req.empty:
                staff_row = staff_req.iloc[0]
                
                try:
                    if len(requirements_df.columns) >= 4:
                        if pd.notna(staff_row.iloc[1]):
                            shifts_per_pay_period = int(float(staff_row.iloc[1]))
                        if pd.notna(staff_row.iloc[2]):
                            night_minimum = int(float(staff_row.iloc[2]))
                        if pd.notna(staff_row.iloc[3]):
                            weekend_minimum = int(float(staff_row.iloc[3]))
                    
                    # NEW: Get weekend group from column 4 (0-indexed)
                    if len(requirements_df.columns) >= 5:
                        if pd.notna(staff_row.iloc[4]):
                            weekend_group = str(staff_row.iloc[4]).strip().upper()
                            # Validate weekend group
                            if weekend_group not in ['A', 'B', 'C', 'D', 'E']:
                                weekend_group = None
                            
                except (ValueError, IndexError, TypeError) as e:
                    st.warning(f"Error loading requirements: {e}")
                    
        except Exception as e:
            st.error(f"Error processing requirements file: {str(e)}")
    
    # Display requirements including weekend group
    st.markdown("### 📋 Staff Requirements")
    req_cols = st.columns(4)
    with req_cols[0]:
        st.metric("Shifts per Pay Period", shifts_per_pay_period, help="Exact match required")
    with req_cols[1]:
        st.metric("Night Minimum", night_minimum, help="Minimum required (>=)")
    with req_cols[2]:
        st.metric("Weekend Minimum", weekend_minimum, help="Minimum required (>=)")
    with req_cols[3]:
        if weekend_group:
            st.metric("Weekend Group", weekend_group, help=f"Assigned to weekend group {weekend_group}")
        else:
            st.metric("Weekend Group", "None", help="No weekend group assigned")
    
    # Get staff information
    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
    
    # Check database track
    db_result = get_track_from_db(selected_staff)
    has_db_track = db_result[0]
    st.session_state['has_db_track'] = has_db_track
    
    # Get track data based on source
    if use_database_logic and has_db_track:
        db_track_data = db_result[1]['track_data']
        submission_date = db_result[1]['submission_date']
        is_approved = db_result[1]['is_approved']
        version = db_result[1]['version']
        
        staff_track_df = pd.DataFrame([{day: db_track_data.get(day, "") for day in days}])
        staff_track_df[staff_col_tracks] = selected_staff
        
        track_source = "Database"
        st.info(f"📊 Using Annual Rebid database track (version {version}, submitted on {submission_date}).")
    else:
        staff_track_df = current_tracks_df[current_tracks_df[staff_col_tracks] == selected_staff]
        
        if staff_track_df.empty:
            st.error(f"No current track found for {selected_staff} in Excel file.")
            return
        
        track_source = "Excel File"
        if use_database_logic and not has_db_track:
            st.info("📊 No Annual Rebid database track found. Creating new track from scratch.")
        else:
            st.info("📊 Using Current Track Changes reference file.")
    
    # Get preassignments
    staff_preassignments = {}
    if preassignment_df is not None:
        staff_preassignments = get_staff_preassignments(selected_staff, preassignment_df, days)
        
        if staff_preassignments:
            preassign_count = len(staff_preassignments)
            st.info(f"📌 {selected_staff} has {preassign_count} preassignments. These will be counted as shifts and cannot be modified.")
    
    # Initialize current track data
    if use_database_logic and has_db_track:
        current_track_data = db_result[1]['track_data']
    elif use_database_logic and not has_db_track:
        current_track_data = {day: "" for day in days}
    else:
        current_track_data = {day: staff_track_df.iloc[0][day] for day in days}
    
    # Add preassignments to current track data
    if staff_preassignments:
        for day, preassignment in staff_preassignments.items():
            if day not in current_track_data or not current_track_data[day]:
                current_track_data[day] = preassignment
    
    # Store requirements in session state including weekend group
    st.session_state.shifts_per_pay_period = shifts_per_pay_period
    st.session_state.night_minimum = night_minimum
    st.session_state.weekend_minimum = weekend_minimum
    st.session_state.weekend_group = weekend_group  # NEW: Store weekend group
    
    # Reset and clear buttons
    reset_col, clear_col = st.columns(2)
    
    with reset_col:
        if st.button("Reset to Current Track", key=f"reset_{selected_staff}", use_container_width=True):
            is_new = use_database_logic and not has_db_track
            reset_track_session_state(selected_staff, current_track_data, staff_preassignments)
            st.session_state['is_new_track'] = is_new
            st.success("Track reset to current assignments")
            st.rerun()
    
    with clear_col:
        if st.button("Clear All Shifts", key=f"clear_{selected_staff}", use_container_width=True):
            blank_track = {day: "" for day in days}
            if staff_preassignments:
                for day, preassignment in staff_preassignments.items():
                    blank_track[day] = preassignment
            
            if 'track_changes' not in st.session_state:
                st.session_state.track_changes = {}
            st.session_state.track_changes[selected_staff] = blank_track
            
            st.session_state.modified_track = {
                'staff': selected_staff,
                'track': blank_track.copy(),
                'valid': False,
                'is_new': True
            }
            st.session_state['is_new_track'] = True
            
            st.success("All shifts cleared")
            st.rerun()
    
    # Initialize session state if needed
    if ('modified_track' not in st.session_state or 
        st.session_state.modified_track.get('staff') != selected_staff or
        'track_changes' not in st.session_state or
        selected_staff not in st.session_state.track_changes):
        
        is_new_track = st.session_state.get('is_new_track', use_database_logic and not has_db_track)
        reset_track_session_state(selected_staff, current_track_data, staff_preassignments)
        st.session_state['is_new_track'] = is_new_track
    
    # Handle tab navigation - FIXED: Proper tab switching
    active_tab = "Current Track"

    # Check for navigation requests with proper cleanup
    if st.session_state.get('show_submission_tab', False):
        active_tab = "Submission"
        # Clear the navigation flag immediately
        del st.session_state['show_submission_tab']
    elif st.session_state.get('active_tab'):
        active_tab = st.session_state['active_tab']
        # Clear the navigation flag immediately
        del st.session_state['active_tab']

    # Create tabs - UPDATED: Added Preference Editor tab
    tab_options = ["📍 Current Track", "⚙️ Preferences", "🛠️ Edit Preferences", "🔄 Track Modification", "🔍 Validation", "📤 Submission", "🔮 Hypothetical Schedule"]

    # Force specific tab if requested
    selected_tab_index = 0
    try:
        selected_tab_index = tab_options.index(active_tab)
    except ValueError:
        selected_tab_index = 0

    # Create the tabs - FIXED: Don't try to pre-select, let Streamlit handle it naturally
    tabs = st.tabs(tab_options)

    # If we need to show submission tab, add a visual indicator
    if active_tab == "Submission":
        st.info("🎯 **Navigated to Submission Tab** - You can now submit your track changes.")
       
    with tabs[0]:  # Current Track
        display_track(selected_staff, staff_track_df, days, shifts_per_pay_period, night_minimum, 
                      preassignments=staff_preassignments, track_source=track_source, weekend_minimum=weekend_minimum)
    
    with tabs[1]:  # Preferences
        display_preferences(selected_staff, staff_info, preferences_df)
    
    with tabs[2]:  # NEW: Edit Preferences (Location-Based)
        display_location_preference_editor(selected_staff)

        # Also show preference history (old shift-based system kept for reference)
        st.markdown("---")
        st.markdown("### 📊 Legacy Shift Preference History")
        st.info("ℹ️ This section shows historical shift-type preferences (old system). The new system uses location-based preferences above.")
        display_preference_history(selected_staff)
    
    with tabs[3]:  # Track Modification - UPDATED: Removed validation dashboard from here
        is_new_track = st.session_state.get('is_new_track', use_database_logic and not has_db_track)
        
        # UPDATED: Pass weekend group and requirements_df to modification function, but without validation dashboard
        modify_track_enhanced_without_validation(
            selected_staff,
            staff_track_df,
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
            preassignments=staff_preassignments,
            is_new_track=is_new_track,
            weekend_minimum=weekend_minimum,
            requirements_df=requirements_df  # Pass requirements_df for weekend group lookup
        )
    
    with tabs[4]:  # NEW: Validation Tab
        display_validation_tab(
            selected_staff, days, shifts_per_pay_period, night_minimum, 
            weekend_minimum, staff_preassignments, weekend_group, requirements_df
        )
    
    with tabs[5]:  # Submission
        submit_track(
            selected_staff,
            staff_track_df,
            days,
            shifts_per_pay_period,
            night_minimum,
            weekend_minimum=weekend_minimum,
            preassignments=staff_preassignments,
            is_new_track=st.session_state.get('is_new_track', use_database_logic and not has_db_track),
            has_db_track=has_db_track
        )

    with tabs[6]:  # Hypothetical Schedule
        st.subheader(f"Hypothetical Schedule for {selected_staff}")
        
        with st.spinner("Generating hypothetical schedule using enhanced data with staffing analysis..."):
            # FIXED: Use the enhanced hypothetical scheduler with staffing analysis
            from ..track_modification_core import calculate_all_modification_options
            
            # Get the same comprehensive results used in Track Modification with staffing analysis
            hypothetical_results = calculate_all_modification_options(
                selected_staff, preferences_df, current_tracks_df, days,
                staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
                reduced_rest_col, seniority_col
            )
            
            # Extract the data components
            day_assignments = hypothetical_results['day_assignments']
            night_assignments = hypothetical_results['night_assignments']
            assignment_details = hypothetical_results['assignment_details']  # Now includes staffing_analysis
            preference_source = hypothetical_results.get('preference_source', 'file')
            
            # Get staff role for capacity checking
            staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
            staff_role = staff_info[role_col]
            effective_role = "nurse" if staff_role == "dual" else staff_role
            
            # Display preference source info
            from ..preference_editor import get_current_preferences
            enhanced_prefs, source = get_current_preferences(selected_staff)
            
            if source == 'database':
                st.success("🎯 **Using Your Custom Preferences** - Results based on preferences you edited in the system")
            else:
                st.info("📁 **Using File Preferences** - Results based on uploaded file preferences (you can edit them in the 'Edit Preferences' tab)")
            
            # Display the schedule with enhanced formatting including "*requires a swap, fully staffed"
            st.markdown("### 📅 Your Hypothetical Schedule")
            st.markdown("*These assignments match exactly what you see in the Track Modification tab*")
            
            # Create summary statistics
            total_day_shifts = sum(1 for assignment in day_assignments.values() if assignment)
            total_night_shifts = sum(1 for assignment in night_assignments.values() if assignment)
            total_shifts = total_day_shifts + total_night_shifts
            
            # Display summary
            with st.expander("Schedule Summary", expanded=True):
                cols = st.columns(3)
                cols[0].metric("Total Shifts", total_shifts)
                cols[1].metric("Day Shifts", total_day_shifts)
                cols[2].metric("Night Shifts", total_night_shifts)
            
            # Create schedule table by blocks with "*requires a swap, fully staffed" notation
            blocks = ["A", "B", "C"]
            block_tabs = st.tabs([f"Block {block}" for block in blocks])
            
            for block_idx, block_tab in enumerate(block_tabs):
                with block_tab:
                    start_idx = block_idx * 14
                    end_idx = start_idx + 14
                    block_days = days[start_idx:end_idx]
                    
                    # Create table data
                    table_data = []
                    
                    for day in block_days:
                        day_assignment = day_assignments.get(day)
                        night_assignment = night_assignments.get(day)
                        
                        day_details = assignment_details.get(day, {}).get('day', {})
                        night_details = assignment_details.get(day, {}).get('night', {})
                        
                        # Get staffing analysis for capacity checking
                        day_staffing = day_details.get('staffing_analysis', {})
                        night_staffing = night_details.get('staffing_analysis', {})
                        
                        # Check if shifts are at max capacity for the selected staff's role
                        day_at_max = False
                        night_at_max = False

                        if effective_role == "nurse":
                            day_at_max = day_staffing.get('nurse_needs', 1) <= 0
                            night_at_max = night_staffing.get('nurse_needs', 1) <= 0
                        else:  # medic
                            day_at_max = day_staffing.get('medic_needs', 1) <= 0
                            night_at_max = night_staffing.get('medic_needs', 1) <= 0

                        # MOVED UP: Get current assignment for comparison BEFORE formatting
                        if use_database_logic:
                            db_result = get_track_from_db(selected_staff)
                            if db_result[0]:
                                current_assignment = db_result[1]['track_data'].get(day, "")
                            else:
                                current_assignment = ""
                        else:
                            current_track = current_tracks_df[current_tracks_df[staff_col_tracks] == selected_staff]
                            if not current_track.empty:
                                current_assignment = current_track.iloc[0][day]
                            else:
                                current_assignment = ""

                        if pd.isna(current_assignment):
                            current_assignment = ""

                        # Format day shift info
                        day_info = "No assignment: all shifts filled by more senior staff"
                        if day_assignment:
                            pref = day_details.get('preference_score')
                            if pref:
                                day_info = f"{day_assignment} (pref {pref})"
                            else:
                                day_info = f"{day_assignment} (No pref)"
                            
                            # Add fully staffed notation if at max capacity
                            # BUT only if the staff member is NOT currently assigned to day shift
                            if day_at_max and current_assignment != "D":
                                day_info += " *requires a swap, fully staffed"

                        # Format night shift info
                        night_info = "No assignment: all shifts filled by more senior staff"
                        if night_assignment:
                            pref = night_details.get('preference_score')
                            if pref:
                                night_info = f"{night_assignment} (pref {pref})"
                            else:
                                night_info = f"{night_assignment} (No pref)"
                            
                            # Add fully staffed notation if at max capacity
                            # BUT only if the staff member is NOT currently assigned to night shift
                            if night_at_max and current_assignment != "N":
                                night_info += " *requires a swap, fully staffed"

                        # Build table data
                        table_data.append({
                            "Day": day,
                            "Day Shift": day_info,
                            "Night Shift": night_info,
                            "Current": current_assignment if current_assignment else ""
                        })                                            
                    # Display table
                    df = pd.DataFrame(table_data)
                    st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Display explanation including the new notation
            st.markdown("---")
            st.markdown(f"""
            ### 📋 How to Read This Schedule
            
            - **Day Shift Assignment**: Shows specific shift assignment (if any) and your preference score for that shift
            - **Night Shift Assignment**: Shows specific shift assignment (if any) and your preference score for that shift  
            - **Current**: Your current track assignment for comparison
            - **Preference Scores**: Higher numbers = higher preference (0-9 for Days, 0-4 for Nights)
            - **"*requires a swap, fully staffed"**: Shift at capacity for {effective_role}; a swap with another {effective_role} is needed for this shift
            - **"No assignment: all shifts filled by more senior staff"**: At capacity for your role; seniority too low to assign
            
            **Note**: This schedule represents what shifts you would hypothetically be assigned based on seniority and preferences. The "*requires a swap, fully staffed" notation indicates shifts where all positions for your role are filled.
            """)
            
            # Display additional details
            st.markdown("### 📊 Additional Details")
            
            summary_cols = st.columns(3)
            with summary_cols[0]:
                st.metric("Total Day Shifts", total_day_shifts)
            with summary_cols[1]:
                st.metric("Total Night Shifts", total_night_shifts)
            with summary_cols[2]:
                st.metric("Total Shifts", total_shifts)        
                
def display_validation_tab(selected_staff, days, shifts_per_pay_period, night_minimum, weekend_minimum, staff_preassignments, weekend_group, requirements_df):
    """
    NEW: Display the validation tab with comprehensive track validation
    """
    st.subheader(f"Track Validation for {selected_staff}")
    
    # Display requirements prominently
    st.markdown("### 📋 Validation Requirements")
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
    
    # Get current track for validation
    current_track = build_validation_track(selected_staff, days, staff_preassignments)
    
    # MOVED: Validation Dashboard from Track Modification tab
    st.markdown("### 🎯 Comprehensive Validation Dashboard")
    
    st.info("""
    **Purpose:** This dashboard validates your entire 6-week track against all Boston MedFlight requirements including:
    - Exact pay period shift matching (14-day blocks)
    - Night shift minimums  
    - Weekend shift minimums
    - Weekly shift limits (< 4 per week)
    - Rest requirements (2 days after nights, no nights before AT)
    - Consecutive shift limits (max 4 in a row, 5 if nights included)
    - Weekend group assignments (if applicable)
    """)
    
    # Display comprehensive validation WITH weekend group information
    # This automatically updates whenever the user makes changes due to Streamlit's reactive nature
    is_valid = display_comprehensive_validation(
        current_track, days, shifts_per_pay_period, night_minimum, 
        weekend_minimum, staff_preassignments, weekend_group, requirements_df, selected_staff
    )
    
    # Store validity in session state (this updates automatically)
    st.session_state.modified_track['valid'] = is_valid
    st.session_state.track_valid = is_valid
    
    # Validation action buttons
    st.markdown("### 🔧 Validation Actions")
    
    val_col1, val_col2 = st.columns(2)
    
    with val_col1:
        if st.button("🔄 Refresh Validation", key="refresh_validation", use_container_width=True):
            # Force a fresh validation
            current_track = build_validation_track(selected_staff, days, staff_preassignments)
            is_valid = display_comprehensive_validation(
                current_track, days, shifts_per_pay_period, night_minimum, 
                weekend_minimum, staff_preassignments, weekend_group, requirements_df, selected_staff
            )
            
            st.session_state.modified_track['valid'] = is_valid
            st.session_state.track_valid = is_valid
            
            if is_valid:
                st.success("✅ Validation refreshed - Track is valid!")
                st.balloons()
            else:
                st.warning("⚠️ Validation refreshed - Issues found above.")
    
    # Validation tips
    st.markdown("### 💡 Validation Tips")
    
    with st.expander("Understanding Validation Results", expanded=False):
        st.markdown("""
        **Pay Period Matching:** Each 14-day block must have exactly the required number of shifts
        
        **Night Minimums:** You must work at least the specified number of night shifts over the 6-week period
        
        **Weekend Minimums:** Weekend shifts include Friday night shifts and any Saturday/Sunday shifts
        
        **Weekly Limits:** No individual week can have 4 or more shifts (maximum 3 per week)
        
        **Rest Requirements:** 
        - After night shifts, you need 2 full unscheduled days before your next day shift
        - AT preassignments cannot be scheduled immediately after night shifts
        
        **Consecutive Limits:** You cannot work more than 4 shifts in a row (5 if the sequence includes night shifts)
        
        **Weekend Groups:** If assigned to a weekend group (A, B, C, D, E), you must work the required weekend periods
        """)
    
    # Show current validation status summary
    if is_valid:
        st.success("🎉 **Your track passes all validation requirements!** You can proceed to the Submission tab.")
    else:
        st.warning("⚠️ **Your track has validation issues.** Please review the results above and make changes in the Track Modification tab.")

def modify_track_enhanced_without_validation(
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
    UPDATED: Track modification without the validation dashboard (moved to separate tab)
    """
    from .editor import modify_track_enhanced
    
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
    from ..db_utils import get_track_from_db
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
        from ..track_modification_core import calculate_all_modification_options
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
    6. Go to the **Validation tab** to check your complete track, then proceed to Submission when ready
    """)
    
    # Show preassignments if any
    if preassignments:
        from .preassignment import display_preassignments
        display_preassignments(selected_staff, preassignments)

    # Display track modification interface WITH enhanced hypothetical scheduler display
    from .editor import display_track_modification_interface_enhanced
    display_track_modification_interface_enhanced(
        selected_staff, options_by_day, reference_track, days, 
        preassignments, use_database_logic, has_db_track, staff_role, weekend_group,
        day_assignments, night_assignments, assignment_details
    )
    
    # Quick validation status (simplified)
    st.markdown("### 📊 Quick Validation Status")
    st.info("**Note:** For comprehensive validation results, go to the **Validation tab**.")
    
    # Get current track for quick validation
    current_track = build_validation_track(selected_staff, days, preassignments)
    
    # Run basic validation
    from ..enhanced_track_validator import validate_track_comprehensive
    validation_result = validate_track_comprehensive(
        current_track, shifts_per_pay_period, night_minimum, 
        weekend_minimum, preassignments, days, weekend_group, requirements_df, selected_staff
    )
    
    # Store validity in session state
    is_valid = validation_result['overall_valid']
    st.session_state.modified_track['valid'] = is_valid
    st.session_state.track_valid = is_valid
    
    # Show quick status
    if is_valid:
        st.success("✅ Your track appears to meet all requirements! Go to the Validation tab for detailed results.")
    else:
        # Count issues
        total_issues = sum(len(result.get('issues', [])) for key, result in validation_result.items() 
                          if key != 'overall_valid' and isinstance(result, dict) and not result['status'])
        st.warning(f"⚠️ Your track has {total_issues} validation issues. Go to the Validation tab for details.")

def generate_hypothetical_schedule_enhanced(
    selected_staff, preferences_df, current_tracks_df, days,
    staff_col_prefs, staff_col_tracks, role_col, seniority_col
):
    """
    UPDATED: Generate hypothetical schedule using enhanced preferences from database or file
    """
    from ..preference_editor import get_preferences_for_hypothetical_scheduler
    from ..hypothetical_scheduler_new import generate_hypothetical_schedule_new
    
    # Get the most recent preferences (database or file)
    enhanced_preferences = get_preferences_for_hypothetical_scheduler(selected_staff)
    
    # Create a temporary preferences DataFrame with the enhanced preferences
    if enhanced_preferences:
        # Update the preferences_df with the enhanced preferences for this staff member
        temp_preferences_df = preferences_df.copy()
        staff_idx = temp_preferences_df[staff_col_prefs] == selected_staff
        
        for shift_name, preference_score in enhanced_preferences.items():
            if shift_name in temp_preferences_df.columns:
                temp_preferences_df.loc[staff_idx, shift_name] = preference_score
        
        # Use the updated preferences
        return generate_hypothetical_schedule_new(
            selected_staff, temp_preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, seniority_col
        )
    else:
        # Fall back to original preferences
        return generate_hypothetical_schedule_new(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, seniority_col
        )

def display_hypothetical_results_enhanced(results, selected_staff, days):
    """
    UPDATED: Display hypothetical results with preference source information
    """
    from ..hypothetical_scheduler_new import display_hypothetical_results_new
    from ..preference_editor import get_current_preferences
    
    # Check if using enhanced preferences
    enhanced_prefs, source = get_current_preferences(selected_staff)
    
    # Display preference source info
    if source == 'database':
        st.success("🎯 **Using Your Custom Preferences** - Results based on preferences you edited in the system")
    else:
        st.info("📁 **Using File Preferences** - Results based on uploaded file preferences (you can edit them in the 'Edit Preferences' tab)")
    
    # Display the regular results
    display_hypothetical_results_new(results, selected_staff, days)

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

# Navigation helper functions
def navigate_to_submission():
    """Helper function to navigate to submission tab"""
    st.session_state['show_submission_tab'] = True
    st.session_state['force_tab_index'] = 5  # Updated index for Submission tab
    st.rerun()

def navigate_to_modification():
    """Helper function to navigate to modification tab"""
    st.session_state['active_tab'] = "Track Modification"
    st.session_state['force_tab_index'] = 3  # Modification tab index
    st.rerun()

def navigate_to_validation():
    """Helper function to navigate to validation tab"""
    st.session_state['active_tab'] = "Validation"
    st.session_state['force_tab_index'] = 4  # Validation tab index
    st.rerun()
       