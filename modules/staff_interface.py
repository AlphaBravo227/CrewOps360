# modules/staff_interface.py - Updated

"""
Module for staff interface components and functionality
"""

import streamlit as st
import pandas as pd

# Import the modularized components
from .track_display import display_current_track
from .preference_display import display_preferences
from .track_editor import modify_track_improved
from .track_submission import submit_track
from .preassignments_loader import get_staff_preassignments
from .db_utils import get_track_from_db

def staff_interface(
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
    preassignment_df=None,  # Add preassignment_df parameter
    selected_staff=None     # Add parameter with default None
):
    """
    Display the staff interface for track management
    
    Args:
        preferences_df (DataFrame): Staff preferences data
        current_tracks_df (DataFrame): Current track assignments
        requirements_df (DataFrame): Staff requirements data
        days (list): List of days in the schedule
        staff_col_prefs (str): Column name for staff in preferences
        staff_col_tracks (str): Column name for staff in tracks
        role_col (str): Column name for role
        no_matrix_col (str): Column name for no matrix status
        reduced_rest_col (str): Column name for reduced rest status
        seniority_col (str): Column name for seniority
        preassignment_df (DataFrame, optional): DataFrame containing staff preassignments
        selected_staff (str, optional): Pre-selected staff member. Defaults to None.
    """
    st.header("Staff Track Management")
    
    # Check if the user is creating a new track
    create_new = st.session_state.get('create_new_track', False)
    
    # Clear the flag after it's been used
    if create_new:
        st.session_state['create_new_track'] = False
        st.session_state['is_new_track'] = True
    
    # Get staff names from preferences file
    staff_names = preferences_df[staff_col_prefs].tolist()
    
    # If no staff is pre-selected, show the selection interface
    if selected_staff is None:
        # Add search box for staff - with unique key
        search_term = st.text_input("Search for staff member:", key="staff_mgmt_search")
        if search_term:
            filtered_staff = [s for s in staff_names if search_term.lower() in s.lower()]
            selected_staff = st.selectbox("Select Staff Member", filtered_staff, key="staff_mgmt_filtered") if filtered_staff else None
            if not filtered_staff:
                st.warning(f"No staff members found matching '{search_term}'")
        else:
            selected_staff = st.selectbox("Select Staff Member", staff_names, key="staff_mgmt_all")
    else:
        # Display which staff member is selected
        st.success(f"Working with staff member: {selected_staff}")
    
    if not selected_staff:
        st.info("Please select a staff member to continue.")
        return
    
    # Extract requirements for this staff member
    if requirements_df is not None:
        staff_req = requirements_df[requirements_df[staff_col_prefs] == selected_staff]
        
        if not staff_req.empty:
            shifts_per_week = staff_req.iloc[0].get('SHIFTS PER WEEK', 0)
            night_minimum = staff_req.iloc[0].get('NIGHT MINIMUM', 0)
        else:
            shifts_per_week = 0
            night_minimum = 0
            st.warning(f"No requirements found for {selected_staff}. Using defaults.")
    else:
        shifts_per_week = 0
        night_minimum = 0
        st.warning("Requirements file not loaded. Using defaults.")
    
    # Get staff information
    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
    staff_role = staff_info[role_col]
    st.session_state['staff_role'] = staff_role  # Ensure correct role is always in session state
    is_no_matrix = staff_info[no_matrix_col] == 1
    reduced_rest_ok = staff_info[reduced_rest_col] == 1
    
    # Get current track from database first, then fallback to Excel
    db_result = get_track_from_db(selected_staff)
    has_db_track = db_result[0]
    
    # Get current track from Excel file
    excel_track = current_tracks_df[current_tracks_df[staff_col_tracks] == selected_staff]
    has_excel_track = not excel_track.empty
    
    # Add track source indicator
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if has_db_track:
            track_data = db_result[1]['track_data']
            submission_date = db_result[1]['submission_date']
            is_approved = db_result[1]['is_approved']
            version = db_result[1]['version']
            
            st.info(f"📊 Track in database: version {version}, submitted on {submission_date}, status: {'Approved' if is_approved else 'Pending'}")
        elif has_excel_track:
            st.info("📊 Using reference track from Excel file (no database track found)")
        else:
            st.warning("⚠️ No track found for this staff member")
    
    with col2:
        # Add button to create new track
        if st.button("Create New Track", use_container_width=True):
            st.session_state['create_new_track'] = True
            st.session_state['is_new_track'] = True
            # Initialize an empty track
            st.session_state['track_changes'] = {
                selected_staff: {day: "" for day in days}
            }
            st.experimental_rerun()
    
    # Check if we have a valid track - either from database or Excel
    if not has_db_track and not has_excel_track:
        st.error(f"No current track found for {selected_staff}")
        return
    
    # Extract track data based on source
    if has_db_track:
        # Use track from database
        current_track_data = db_result[1]['track_data']
    else:
        # Extract from Excel file
        current_track_data = {day: excel_track.iloc[0][day] for day in days}
    
    # Get preassignments for this staff member if available
    staff_preassignments = {}
    if preassignment_df is not None:
        staff_preassignments = get_staff_preassignments(selected_staff, preassignment_df, days)
        
        # Display preassignment information if any are present
        if staff_preassignments:
            preassign_count = len(staff_preassignments)
            st.info(f"📌 {selected_staff} has {preassign_count} preassignments. These will be counted as shifts and cannot be modified.")
    
    # Initialize or reset session state variables to avoid conflicts
    # This button allows explicit reset of the track data
    reset_col, clear_col = st.columns(2)
    
    with reset_col:
        if st.button("Reset to Current Track", key=f"reset_{selected_staff}", use_container_width=True):
            reset_track_session_state(selected_staff, current_track_data, staff_preassignments, preferences_df, staff_col_prefs, role_col)
            st.session_state['is_new_track'] = False  # Make sure we're not in new track mode
            st.success("Track reset to current assignments")
            st.experimental_rerun()
    
    with clear_col:
        if st.button("Clear All Shifts", key=f"clear_{selected_staff}", use_container_width=True):
            # Create a blank track with just preassignments
            blank_track = {day: "" for day in days}
            if staff_preassignments:
                for day, preassignment in staff_preassignments.items():
                    blank_track[day] = preassignment
            
            # Update track_changes
            if 'track_changes' not in st.session_state:
                st.session_state.track_changes = {}
            st.session_state.track_changes[selected_staff] = blank_track
            
            # Update modified_track
            st.session_state.modified_track = {
                'staff': selected_staff,
                'track': blank_track.copy(),
                'valid': False,
                'is_new': True  # Treat as new track when clearing all
            }
            st.session_state['is_new_track'] = True
            
            st.success("All shifts cleared")
            st.experimental_rerun()
    
    # Initialize session state if needed
    if ('modified_track' not in st.session_state or 
        st.session_state.modified_track.get('staff') != selected_staff or
        'track_changes' not in st.session_state or
        selected_staff not in st.session_state.track_changes):
        reset_track_session_state(selected_staff, current_track_data, staff_preassignments, preferences_df, staff_col_prefs, role_col)
    
    # Store requirements in session state for use in track editor
    st.session_state.shifts_per_week = shifts_per_week
    st.session_state.night_minimum = night_minimum
    
    # Check if we should show the submission tab directly
    active_tab = "Current Track"
    if 'show_submission_tab' in st.session_state and st.session_state.show_submission_tab:
        active_tab = "Submission"
        # Reset the flag
        st.session_state.show_submission_tab = False
    elif 'active_tab' in st.session_state:
        active_tab = st.session_state.active_tab
        # Reset the flag
        st.session_state.pop('active_tab', None)
    
    # Create tabs for different views
    tab_options = ["Current Track", "Preferences", "Track Modification", "Submission"]
    tab_index = tab_options.index(active_tab) if active_tab in tab_options else 0
    
    tabs = st.tabs(tab_options)
    
    with tabs[0]:  # Current Track
        # Use the current track based on source priority: Database > Excel
        if has_db_track:
            # Convert database track to a dataframe format for display
            db_track_df = pd.DataFrame([{day: db_result[1]['track_data'].get(day, "") for day in days}])
            db_track_df[staff_col_tracks] = selected_staff
            display_current_track(selected_staff, db_track_df, days, shifts_per_week, night_minimum, preassignments=staff_preassignments, track_source="Database")
        else:
            # Use Excel track as fallback
            display_current_track(selected_staff, excel_track, days, shifts_per_week, night_minimum, preassignments=staff_preassignments, track_source="Excel File")
    
    with tabs[1]:  # Preferences
        display_preferences(selected_staff, staff_info, preferences_df)
    
    with tabs[2]:  # Track Modification
        modify_track_improved(
            selected_staff,
            excel_track,  # Always use Excel track as reference
            preferences_df,
            current_tracks_df,
            days,
            staff_col_prefs,
            staff_col_tracks,
            role_col,
            no_matrix_col,
            reduced_rest_col,
            seniority_col,
            shifts_per_week,
            night_minimum,
            preassignments=staff_preassignments,
            is_new_track=st.session_state.get('is_new_track', False)
        )
    
    with tabs[3]:  # Submission
        submit_track(
            selected_staff,
            excel_track,  # Always use Excel track as reference
            days,
            shifts_per_week,
            night_minimum,
            weekend_minimum=5,
            preassignments=staff_preassignments,
            is_new_track=st.session_state.get('is_new_track', False),
            has_db_track=has_db_track
        )

def reset_track_session_state(selected_staff, current_track_data, preassignments=None, preferences_df=None, staff_col_prefs=None, role_col=None):
    """
    Reset the track session state for a given staff member to avoid conflicts
    
    Args:
        selected_staff (str): Name of the selected staff member
        current_track_data (dict): Current track data
        preassignments (dict, optional): Dictionary of day -> preassignment value
        preferences_df (DataFrame, optional): Preferences DataFrame to get role
        staff_col_prefs (str, optional): Column name for staff in preferences
        role_col (str, optional): Column name for role
    """
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
        
    # Always update staff_role in session state if possible
    if preferences_df is not None and staff_col_prefs is not None and role_col is not None:
        staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
        st.session_state['staff_role'] = staff_info[role_col]
    
    # Reset the modified track to current track
    st.session_state.modified_track = {
        'staff': selected_staff,
        'track': track_copy,
        'valid': False,  # Start with invalid and require validation
        'is_new': st.session_state.get('is_new_track', False)  # Preserve new track status
    }
    
    # Reset track changes if they exist
    if 'track_changes' in st.session_state:
        st.session_state.track_changes[selected_staff] = track_copy.copy()
    else:
        st.session_state.track_changes = {selected_staff: track_copy.copy()}
    
    # Clear any potential validation flags
    if 'validation_button' in st.session_state:
        st.session_state.validation_button = False
