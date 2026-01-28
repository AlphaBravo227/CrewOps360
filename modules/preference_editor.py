# modules/preference_editor.py - ENHANCED VERSION WITH LOCATION-BASED PREFERENCES
"""
Enhanced Preference Management System
Allows users to edit their shift preferences AND boolean preferences within the application
NOW INCLUDES: Location-based preference system (v2)
"""

import streamlit as st
import pandas as pd
import sqlite3
import os
import json
from datetime import datetime
from .shift_definitions import day_shifts, night_shifts
from .db_utils import (
    get_db_connection,
    initialize_database,
    save_location_preferences_to_db,
    get_location_preferences_from_db
)

def initialize_preference_tables():
    """
    Initialize the database tables for storing user preferences including boolean preferences
    """
    try:
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create user_preferences table (existing shift preferences)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            shift_name TEXT NOT NULL,
            preference_score INTEGER NOT NULL,
            shift_type TEXT NOT NULL,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            UNIQUE(staff_name, shift_name)
        )
        ''')
        
        # Create user_boolean_preferences table (new for boolean preferences)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_boolean_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            preference_name TEXT NOT NULL,
            preference_value TEXT NOT NULL,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            UNIQUE(staff_name, preference_name)
        )
        ''')
        
        # Create preference_history table for audit trail
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS preference_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            preference_data TEXT NOT NULL,
            action TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            source TEXT NOT NULL
        )
        ''')
        
        # Commit changes
        conn.commit()
        
        return True
        
    except Exception as e:
        print(f"Error initializing preference tables: {str(e)}")
        return False

def get_current_preferences(staff_name):
    """
    Get the most recent preferences for a staff member (both shift and boolean preferences)
    First checks database, then falls back to uploaded file preferences
    
    Args:
        staff_name (str): Name of the staff member
        
    Returns:
        tuple: (preferences_dict, source) where source is 'database' or 'file'
    """
    try:
        # Initialize preference tables if needed
        initialize_preference_tables()
        
        # Check database first
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get shift preferences
        cursor.execute("""
            SELECT shift_name, preference_score, shift_type
            FROM user_preferences 
            WHERE staff_name = ? AND is_active = 1
        """, (staff_name,))
        
        db_shift_prefs = cursor.fetchall()
        
        # Get boolean preferences
        cursor.execute("""
            SELECT preference_name, preference_value
            FROM user_boolean_preferences 
            WHERE staff_name = ? AND is_active = 1
        """, (staff_name,))
        
        db_boolean_prefs = cursor.fetchall()
        
        if db_shift_prefs or db_boolean_prefs:
            # Build combined preferences dictionary
            preferences = {}
            
            # Add shift preferences
            for shift_name, preference_score, shift_type in db_shift_prefs:
                preferences[shift_name] = preference_score
            
            # Add boolean preferences
            for pref_name, pref_value in db_boolean_prefs:
                preferences[pref_name] = pref_value
                
            return preferences, 'database'
        else:
            # Fall back to file preferences
            file_prefs = get_file_preferences(staff_name)
            return file_prefs, 'file' if file_prefs else 'none'
        
    except Exception as e:
        print(f"Error getting current preferences: {str(e)}")
        # Fall back to file preferences
        file_prefs = get_file_preferences(staff_name)
        return file_prefs, 'file' if file_prefs else 'none'

def get_current_boolean_preferences(staff_name):
    """
    Get current boolean preferences for a staff member
    
    Args:
        staff_name (str): Name of the staff member
        
    Returns:
        dict: Dictionary of boolean preferences
    """
    try:
        # Initialize preference tables if needed
        initialize_preference_tables()
        
        # Check database first
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT preference_name, preference_value
            FROM user_boolean_preferences 
            WHERE staff_name = ? AND is_active = 1
        """, (staff_name,))
        
        db_prefs = cursor.fetchall()
        
        boolean_prefs = {}
        for pref_name, pref_value in db_prefs:
            if pref_name == 'N to D Flex':
                # Handle string values for N to D Flex
                boolean_prefs[pref_name] = str(pref_value)
            else:
                # Handle boolean values for Reduced Rest OK - fix the conversion!
                boolean_prefs[pref_name] = bool(int(pref_value)) if str(pref_value).isdigit() else bool(pref_value)
        
        # If no database preferences, get from file
        if not boolean_prefs:
            file_prefs = get_file_preferences(staff_name)
            if file_prefs:
                # Extract boolean preferences from file
                boolean_prefs['Reduced Rest OK'] = bool(file_prefs.get('Reduced Rest OK', 0))
                n_to_d_flex_value = file_prefs.get('N to D Flex', 0)
                # Convert N to D Flex from file format
                if isinstance(n_to_d_flex_value, str):
                    boolean_prefs['N to D Flex'] = n_to_d_flex_value
                elif n_to_d_flex_value == 1:
                    boolean_prefs['N to D Flex'] = "Yes"
                elif n_to_d_flex_value == 0:
                    boolean_prefs['N to D Flex'] = "No"
                else:
                    boolean_prefs['N to D Flex'] = "Maybe"
        
        return boolean_prefs
        
    except Exception as e:
        print(f"Error getting boolean preferences: {str(e)}")
        return {}

def get_file_preferences(staff_name):
    """
    Get preferences from the uploaded file for a specific staff member
    
    Args:
        staff_name (str): Name of the staff member
        
    Returns:
        dict: Dictionary of preferences from file or None if not found
    """
    try:
        # Get preferences from session state (uploaded file)
        if 'preferences_df' in st.session_state:
            preferences_df = st.session_state.preferences_df
            staff_col_prefs = st.session_state.get('staff_col_prefs', 'STAFF NAME')
            
            # Find the staff member's row
            staff_row = preferences_df[preferences_df[staff_col_prefs] == staff_name]
            
            if not staff_row.empty:
                # Convert to dictionary
                preferences = staff_row.iloc[0].to_dict()
                return preferences
        
        return None
        
    except Exception as e:
        print(f"Error getting file preferences: {str(e)}")
        return None

def save_preferences_to_database(staff_name, shift_preferences, boolean_preferences):
    """
    Save both shift and boolean preferences to the database
    
    Args:
        staff_name (str): Name of the staff member
        shift_preferences (dict): Dictionary of shift preferences
        boolean_preferences (dict): Dictionary of boolean preferences
        
    Returns:
        tuple: (success, message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        current_timestamp = datetime.now().isoformat()
        
        # Save shift preferences
        for shift_name, preference_score in shift_preferences.items():
            shift_type = 'day' if shift_name in day_shifts else 'night'
            
            cursor.execute("""
                INSERT OR REPLACE INTO user_preferences 
                (staff_name, shift_name, preference_score, shift_type, created_date, modified_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (staff_name, shift_name, preference_score, shift_type, current_timestamp, current_timestamp))
        
        # Save boolean preferences (handle different value types)
        for pref_name, pref_value in boolean_preferences.items():
            # Convert values to appropriate storage format
            if pref_name == 'N to D Flex':
                # Store string values for N to D Flex (Yes, No, Maybe)
                storage_value = str(pref_value) if pref_value is not None else "No"
            else:
                # Store boolean as integer for other preferences
                storage_value = int(pref_value) if pref_value is not None else 0
            
            cursor.execute("""
                INSERT OR REPLACE INTO user_boolean_preferences 
                (staff_name, preference_name, preference_value, created_date, modified_date, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (staff_name, pref_name, storage_value, current_timestamp, current_timestamp))
        
        # Log the action in history
        all_preferences = {**shift_preferences, **boolean_preferences}
        cursor.execute("""
            INSERT INTO preference_history 
            (staff_name, preference_data, action, timestamp, source)
            VALUES (?, ?, ?, ?, ?)
        """, (staff_name, json.dumps(all_preferences), 'updated', current_timestamp, 'user_edit'))
        
        # Commit changes
        conn.commit()
        
        return (True, "All preferences saved successfully")
        
    except Exception as e:
        return (False, f"Error saving preferences: {str(e)}")

def validate_preferences(day_preferences, night_preferences, boolean_preferences):
    """
    Validate preferences with flexible shift validation
    Additional preferences are ALWAYS required
    Shift preferences only validated if user has started editing them
    
    Args:
        day_preferences (dict): Day shift preferences
        night_preferences (dict): Night shift preferences  
        boolean_preferences (dict): Additional preferences (Reduced Rest OK, N to D Flex)
        
    Returns:
        tuple: (is_valid, error_messages)
    """
    errors = []
    
    # ALWAYS validate Additional Preferences Questions (required)
    reduced_rest_answered = boolean_preferences.get('reduced_rest_answered', False)
    n_to_d_flex_answered = boolean_preferences.get('n_to_d_flex_answered', False)
    
    if not reduced_rest_answered:
        errors.append("❗ Required: Please answer 'Reduced Rest OK' question (Yes or No)")
    
    if not n_to_d_flex_answered:
        errors.append("❗ Required: Please answer 'N to D Flex' question (Yes, No, or Maybe)")
    
    # Check if user has started editing shift preferences
    day_values = [v for v in day_preferences.values() if v is not None]
    night_values = [v for v in night_preferences.values() if v is not None]
    
    # Only validate shift preferences IF user has started editing them
    day_started_editing = len(day_values) > 0
    night_started_editing = len(night_values) > 0
    
    # Validate day shifts only if user started editing them
    if day_started_editing:
        if len(day_values) < len(day_shifts):
            errors.append("Since you started editing day shifts, please complete all day shift rankings")
        elif len(day_values) == len(day_shifts):
            # Validate day preferences (0-9, each used once, where 9=most preferred)
            expected_day_values = set(range(0, len(day_shifts)))  # 0 to 9 for 10 day shifts
            actual_day_values = set(day_values)
            
            if len(day_values) != len(set(day_values)):
                errors.append("Each day shift ranking can only be used once")
            
            if actual_day_values != expected_day_values:
                missing = expected_day_values - actual_day_values
                extra = actual_day_values - expected_day_values
                if missing:
                    errors.append(f"Missing day shift rankings: {sorted(missing)}")
                if extra:
                    errors.append(f"Invalid day shift rankings: {sorted(extra)}")
    
    # Validate night shifts only if user started editing them
    if night_started_editing:
        if len(night_values) < len(night_shifts):
            errors.append("Since you started editing night shifts, please complete all night shift rankings")
        elif len(night_values) == len(night_shifts):
            # Validate night preferences (0-4, each used once, where 4=most preferred)
            expected_night_values = set(range(0, len(night_shifts)))  # 0 to 4 for 5 night shifts
            actual_night_values = set(night_values)
            
            if len(night_values) != len(set(night_values)):
                errors.append("Each night shift ranking can only be used once")
            
            if actual_night_values != expected_night_values:
                missing = expected_night_values - actual_night_values
                extra = actual_night_values - expected_night_values
                if missing:
                    errors.append(f"Missing night shift rankings: {sorted(missing)}")
                if extra:
                    errors.append(f"Invalid night shift rankings: {sorted(extra)}")
    
    return len(errors) == 0, errors

def display_preference_editor(staff_name):
    """
    Display the enhanced preference editing interface with shift and boolean preferences
    
    Args:
        staff_name (str): Name of the staff member
    """
    st.subheader(f"Edit Preferences for {staff_name}")
    
    # Initialize preference tables
    initialize_preference_tables()
    
    # Get current preferences for display purposes
    current_prefs, source = get_current_preferences(staff_name)
    current_boolean_prefs = get_current_boolean_preferences(staff_name)
    
    # Display source information
    if source == 'database':
        st.info("📊 You have previously edited preferences. Current saved preferences are shown below for reference.")
        
        # Show current saved preferences in an expander
        with st.expander("View Your Current Saved Preferences", expanded=True):
            # Split into columns for better layout
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**Current Day Shift Rankings:**")
                day_prefs = {k: v for k, v in current_prefs.items() if k in day_shifts}
                if day_prefs:
                    day_sorted = sorted(day_prefs.items(), key=lambda x: x[1], reverse=True)
                    for shift, rank in day_sorted:
                        st.markdown(f"**{rank}.** {shift}")
                else:
                    st.markdown("_No day preferences saved_")
            
            with col2:
                st.markdown("**Current Night Shift Rankings:**")
                night_prefs = {k: v for k, v in current_prefs.items() if k in night_shifts}
                if night_prefs:
                    night_sorted = sorted(night_prefs.items(), key=lambda x: x[1], reverse=True)
                    for shift, rank in night_sorted:
                        st.markdown(f"**{rank}.** {shift}")
                else:
                    st.markdown("_No night preferences saved_")

            with col3:
                            st.markdown("**Current Additional Preferences:**")
                            if current_boolean_prefs:
                                for pref_name, pref_value in current_boolean_prefs.items():
                                    if pref_name == 'N to D Flex':
                                        # Handle string values for N to D Flex
                                        status = f"✅ {pref_value}" if pref_value else "❌ Not set"
                                    else:
                                        # Handle boolean values for Reduced Rest OK
                                        status = "✅ Yes" if pref_value else "❌ No"
                                    st.markdown(f"**{pref_name}:** {status}")
                            else:
                                st.markdown("_No boolean preferences saved_")
    else:
        st.info("📁 Original preferences from uploaded file are available. You haven't edited them yet.")
    
    st.markdown("---")
    st.markdown("### Set Your New Preferences")
    st.info("💡 **Instructions:** Select a ranking for each shift and set your additional preferences. Each shift number can only be used once within each category.")
    
    # Additional Preferences Section (below instructions as requested)
    st.markdown("---")
    st.markdown("### ⚙️ Additional Preferences")
    st.markdown("**🔴 Required: Please answer both questions below**")
    
    # Get current boolean preference values
    current_reduced_rest = current_boolean_prefs.get('Reduced Rest OK', None)
    current_n_to_d_flex = current_boolean_prefs.get('N to D Flex', None)
    
    # Create two columns for the boolean preferences
    bool_col1, bool_col2 = st.columns(2)
    
    with bool_col1:
        st.markdown("### 🛌 Reduced Rest OK")
        st.markdown("**Required:** Are you willing to work shifts with reduced rest time?")
        
        # Radio buttons for Yes/No with explicit tracking
        reduced_rest_options = ["Please select...", "Yes", "No"]
        if current_reduced_rest is not None:
            if current_reduced_rest:
                initial_reduced_index = 1  # Yes
            else:
                initial_reduced_index = 2  # No
        else:
            initial_reduced_index = 0  # Please select
            
        reduced_rest_selection = st.radio(
            "Reduced Rest OK",
            options=reduced_rest_options,
            index=initial_reduced_index,
            key=f"reduced_rest_{staff_name}",
            help="Accept shifts with 10 hours rest instead of 12 hours",
            label_visibility="collapsed"
        )
        
        # Track if answered
        reduced_rest_answered = reduced_rest_selection != "Please select..."
        reduced_rest_value = reduced_rest_selection == "Yes" if reduced_rest_answered else None
        
        st.caption("_Choose 'Yes' if you're willing to work shifts with reduced rest time (10 hours instead of 12)_")
    
    with bool_col2:
        st.markdown("### 🔄 N to D Flex")
        st.markdown("**Required:** Are you flexible with night-to-day shift transitions?")
        
        # Radio buttons for Yes/No/Maybe with explicit tracking
        n_to_d_flex_options = ["Please select...", "Yes", "No", "Maybe"]
        if current_n_to_d_flex is not None:
            # Convert stored value to display option
            if current_n_to_d_flex == 1 or (isinstance(current_n_to_d_flex, str) and current_n_to_d_flex.lower() == "yes"):
                initial_flex_index = 1  # Yes
            elif current_n_to_d_flex == 0 or (isinstance(current_n_to_d_flex, str) and current_n_to_d_flex.lower() == "no"):
                initial_flex_index = 2  # No
            elif isinstance(current_n_to_d_flex, str) and current_n_to_d_flex.lower() == "maybe":
                initial_flex_index = 3  # Maybe
            else:
                initial_flex_index = 0  # Please select
        else:
            initial_flex_index = 0  # Please select
            
        n_to_d_flex_selection = st.radio(
            "N to D Flex",
            options=n_to_d_flex_options,
            index=initial_flex_index,
            key=f"n_to_d_flex_{staff_name}",
            help="Flexibility with transitioning from night shifts to day shifts",
            label_visibility="collapsed"
        )
        
        # Track if answered
        n_to_d_flex_answered = n_to_d_flex_selection != "Please select..."
        n_to_d_flex_value = n_to_d_flex_selection if n_to_d_flex_answered else None
        
        st.caption("_Choose your level of flexibility with night-to-day shift transitions_")
    
    # Shift Preferences Section
    st.markdown("---")
    st.markdown("### 🔄 Shift Preferences")
    
    # Create two columns for day and night shifts
    shift_col1, shift_col2 = st.columns(2)
    
    with shift_col1:
        st.markdown("### 🌅 Day Shift Preferences")
        st.markdown(f"**Rank each shift from 0 (least preferred) to {len(day_shifts) - 1} (most preferred)**")
        st.markdown("Each number can only be used once! Higher numbers = more preferred")
        
        # Create selectboxes for day shifts
        day_preferences = {}
        all_day_ranks = list(range(0, len(day_shifts)))  # 0 to 9 for day shifts
        
        for shift_name, shift_description in day_shifts.items():
            # Get current value if exists
            current_value = current_prefs.get(shift_name) if source == 'database' else None
            initial_index = 0 if current_value is None else (all_day_ranks.index(current_value) + 1)
            
            day_preferences[shift_name] = st.selectbox(
                f"{shift_name} - {shift_description}",
                options=[None] + all_day_ranks,
                index=initial_index,
                key=f"day_{shift_name}_{staff_name}",
                help=f"Select ranking (9=most preferred, 0=least preferred)"
            )
    
    with shift_col2:
        st.markdown("### 🌙 Night Shift Preferences")
        st.markdown(f"**Rank each shift from 0 (least preferred) to {len(night_shifts) - 1} (most preferred)**")
        st.markdown("Each number can only be used once! Higher numbers = more preferred")
        
        # Create selectboxes for night shifts
        night_preferences = {}
        all_night_ranks = list(range(0, len(night_shifts)))  # 0 to 4 for night shifts
        
        for shift_name, shift_description in night_shifts.items():
            # Get current value if exists
            current_value = current_prefs.get(shift_name) if source == 'database' else None
            initial_index = 0 if current_value is None else (all_night_ranks.index(current_value) + 1)
            
            night_preferences[shift_name] = st.selectbox(
                f"{shift_name} - {shift_description}",
                options=[None] + all_night_ranks,
                index=initial_index,
                key=f"night_{shift_name}_{staff_name}",
                help=f"Select ranking (4=most preferred, 0=least preferred)"
            )
    
    # Validation and saving
    st.markdown("---")
    
    # Create boolean preferences dict for validation
    boolean_preferences_for_validation = {
        'reduced_rest_answered': reduced_rest_answered,
        'n_to_d_flex_answered': n_to_d_flex_answered,
        'Reduced Rest OK': reduced_rest_value,
        'N to D Flex': n_to_d_flex_value
    }
    
    # Validate shift and boolean preferences
    is_valid, errors = validate_preferences(day_preferences, night_preferences, boolean_preferences_for_validation)
    
    if not is_valid:
        st.error("❌ **Validation Errors:**")
        for error in errors:
            if "Required:" in error:
                st.error(f"🔴 {error}")  # Highlight required field errors
            else:
                st.error(f"• {error}")
    else:
        st.success("✅ **All preferences are valid!**")
    
    # Display current preferences summary (show if additional questions answered, regardless of shift completion)
    day_filled = all(v is not None for v in day_preferences.values())
    night_filled = all(v is not None for v in night_preferences.values())
    additional_filled = reduced_rest_answered and n_to_d_flex_answered
    
    # Check if user has started editing shifts
    day_started = any(v is not None for v in day_preferences.values())
    night_started = any(v is not None for v in night_preferences.values())
    
    if additional_filled:
        with st.expander("Preview Your Preferences", expanded=True):
            summary_col1, summary_col2, summary_col3 = st.columns(3)
            
            with summary_col1:
                st.markdown("**Day Shift Rankings:**")
                if day_filled:
                    day_sorted = sorted(day_preferences.items(), key=lambda x: x[1], reverse=True)
                    for shift, rank in day_sorted:
                        st.markdown(f"**{rank}.** {shift}")
                elif day_started:
                    st.markdown("_In progress..._")
                    for shift, rank in day_preferences.items():
                        if rank is not None:
                            st.markdown(f"**{rank}.** {shift}")
                else:
                    st.markdown("_Not edited (will use file preferences)_")
            
            with summary_col2:
                st.markdown("**Night Shift Rankings:**")
                if night_filled:
                    night_sorted = sorted(night_preferences.items(), key=lambda x: x[1], reverse=True)
                    for shift, rank in night_sorted:
                        st.markdown(f"**{rank}.** {shift}")
                elif night_started:
                    st.markdown("_In progress..._")
                    for shift, rank in night_preferences.items():
                        if rank is not None:
                            st.markdown(f"**{rank}.** {shift}")
                else:
                    st.markdown("_Not edited (will use file preferences)_")
            
            with summary_col3:
                st.markdown("**Additional Preferences:**")
                reduced_status = f"✅ {reduced_rest_selection}" if reduced_rest_answered else "❌ Not answered"
                flex_status = f"✅ {n_to_d_flex_selection}" if n_to_d_flex_answered else "❌ Not answered"
                st.markdown(f"**Reduced Rest OK:** {reduced_status}")
                st.markdown(f"**N to D Flex:** {flex_status}")
    
    # Save button logic: Always require additional questions, but flexible on shifts
    can_save = is_valid and additional_filled
    
    if can_save:
        save_col1, save_col2 = st.columns([1, 1])
        
        with save_col1:
            if st.button("💾 Save Preferences", use_container_width=True, type="primary"):
                # Only save shift preferences that have been edited
                shift_prefs = {}
                
                # Save day shifts only if user completed them
                if day_filled:
                    shift_prefs.update(day_preferences)
                
                # Save night shifts only if user completed them  
                if night_filled:
                    shift_prefs.update(night_preferences)
                
                # Always save boolean preferences (they're required)
                boolean_prefs = {
                    'Reduced Rest OK': reduced_rest_value,
                    'N to D Flex': n_to_d_flex_value  # This will be "Yes", "No", or "Maybe"
                }
                
                # Save to database
                success, message = save_preferences_to_database(staff_name, shift_prefs, boolean_prefs)
                
                if success:
                    saved_items = []
                    if day_filled:
                        saved_items.append("day shift rankings")
                    if night_filled:
                        saved_items.append("night shift rankings")
                    saved_items.append("additional preferences")
                    
                    st.success(f"✅ Successfully saved: {', '.join(saved_items)}")
                    st.balloons()
                    
                    # Update session state to reflect that user has custom preferences
                    if 'user_has_custom_preferences' not in st.session_state:
                        st.session_state.user_has_custom_preferences = {}
                    st.session_state.user_has_custom_preferences[staff_name] = True
                    
                    st.info("🔄 Your updated preferences will be used throughout the system!")
                else:
                    st.error(f"❌ {message}")
        
        with save_col2:
            if st.button("🔄 Reset to File Preferences", use_container_width=True):
                # Reset to original file preferences
                file_prefs = get_file_preferences(staff_name)
                if file_prefs:
                    # Get all shift preferences from file
                    file_shift_prefs = {k: v for k, v in file_prefs.items() if k in day_shifts or k in night_shifts}
                    
                    # Handle file boolean preferences (convert to proper format)
                    file_reduced_rest = file_prefs.get('Reduced Rest OK', 0)
                    file_n_to_d_flex = file_prefs.get('N to D Flex', 0)
                    
                    # Convert N to D Flex from file format
                    if isinstance(file_n_to_d_flex, str):
                        file_n_to_d_flex_value = file_n_to_d_flex
                    elif file_n_to_d_flex == 1:
                        file_n_to_d_flex_value = "Yes"
                    elif file_n_to_d_flex == 0:
                        file_n_to_d_flex_value = "No"
                    else:
                        file_n_to_d_flex_value = "Maybe"
                    
                    file_boolean_prefs = {
                        'Reduced Rest OK': bool(file_reduced_rest),
                        'N to D Flex': file_n_to_d_flex_value
                    }
                    
                    success, message = save_preferences_to_database(staff_name, file_shift_prefs, file_boolean_prefs)
                    if success:
                        st.success("✅ Reset to original file preferences")
                        st.rerun()
                    else:
                        st.error(f"❌ Error resetting: {message}")
                else:
                    st.warning("No file preferences found to reset to")
    
    elif not additional_filled:
        st.warning("🔴 **Required:** Please answer both Additional Preferences questions above before you can save.")
    else:
        # Show specific validation issues
        if errors:
            st.info("⏳ Please resolve the validation errors above to enable saving.")

def get_preferences_for_hypothetical_scheduler(staff_name):
    """
    Get preferences to use in the hypothetical scheduler
    Prioritizes database preferences over file preferences
    
    Args:
        staff_name (str): Name of the staff member
        
    Returns:
        dict: Dictionary of shift -> preference score
    """
    prefs, source = get_current_preferences(staff_name)
    return prefs

def display_preference_history(staff_name):
    """
    Display preference edit history for a staff member
    
    Args:
        staff_name (str): Name of the staff member
    """
    st.subheader("📈 Preference History")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT preference_data, action, timestamp, source
            FROM preference_history 
            WHERE staff_name = ?
            ORDER BY timestamp DESC
            LIMIT 10
        """, (staff_name,))
        
        history = cursor.fetchall()
        
        if history:
            history_data = []
            for pref_data, action, timestamp, source in history:
                try:
                    # Parse the timestamp
                    dt = datetime.fromisoformat(timestamp)
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    formatted_time = timestamp
                
                history_data.append({
                    "Action": action.title(),
                    "Source": source.replace('_', ' ').title(),
                    "Timestamp": formatted_time
                })
            
            df = pd.DataFrame(history_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No preference history found. Make some edits to see your history here!")
            
    except Exception as e:
        st.error(f"Error loading preference history: {str(e)}")

# ============================================================================
# NEW LOCATION-BASED PREFERENCE SYSTEM (V2)
# ============================================================================

# Location definitions
DAY_LOCATIONS = ['KMHT', 'KLWM', 'KBED', '1B9', 'KPYM']
NIGHT_LOCATIONS = ['KLWM', 'KBED', 'KPYM']

# Choice labels for the new UI (1 = First Choice = most desirable)
DAY_CHOICE_LABELS = ['First Choice', 'Second Choice', 'Third Choice', 'Fourth Choice', 'Fifth Choice']
NIGHT_CHOICE_LABELS = ['First Choice', 'Second Choice', 'Third Choice']

def validate_location_preferences(day_choice_selections, night_choice_selections, zip_code, reduced_rest_answered, n_to_d_flex_answered):
    """
    Validate location preferences

    Args:
        day_choice_selections (dict): Day choice selections {rank: location} - e.g., {1: 'KMHT', 2: 'KLWM', ...}
        night_choice_selections (dict): Night choice selections {rank: location}
        zip_code (str): Zip code
        reduced_rest_answered (bool): Whether reduced rest was answered
        n_to_d_flex_answered (bool): Whether N to D flex was answered

    Returns:
        tuple: (is_valid, error_messages)
    """
    errors = []

    # Validate zip code (required)
    if not zip_code or zip_code.strip() == '':
        errors.append("🔴 Required: Please enter your Zip Code")

    # Validate reduced rest (required)
    if not reduced_rest_answered:
        errors.append("🔴 Required: Please answer 'Reduced Rest OK' question (Yes or No)")

    # Validate N to D flex (required)
    if not n_to_d_flex_answered:
        errors.append("🔴 Required: Please answer 'N to D Flex' question (Yes, No, or Maybe)")

    # Validate day location preferences (all choices must have unique locations)
    day_locations_selected = [loc for loc in day_choice_selections.values() if loc is not None]
    if len(day_locations_selected) < len(DAY_LOCATIONS):
        errors.append("🔴 Required: Please select a location for all day shift choices")
    elif len(day_locations_selected) == len(DAY_LOCATIONS):
        # Check for duplicate locations
        if len(day_locations_selected) != len(set(day_locations_selected)):
            errors.append("❌ Each day shift location can only be selected once")
        # Check that all locations are valid
        invalid_locs = [loc for loc in day_locations_selected if loc not in DAY_LOCATIONS]
        if invalid_locs:
            errors.append(f"❌ Invalid day location(s): {invalid_locs}")

    # Validate night location preferences (all choices must have unique locations)
    night_locations_selected = [loc for loc in night_choice_selections.values() if loc is not None]
    if len(night_locations_selected) < len(NIGHT_LOCATIONS):
        errors.append("🔴 Required: Please select a location for all night shift choices")
    elif len(night_locations_selected) == len(NIGHT_LOCATIONS):
        # Check for duplicate locations
        if len(night_locations_selected) != len(set(night_locations_selected)):
            errors.append("❌ Each night shift location can only be selected once")
        # Check that all locations are valid
        invalid_locs = [loc for loc in night_locations_selected if loc not in NIGHT_LOCATIONS]
        if invalid_locs:
            errors.append(f"❌ Invalid night location(s): {invalid_locs}")

    return len(errors) == 0, errors

def display_location_preference_editor(staff_name):
    """
    Display the location-based preference editing interface (NEW VERSION)

    Args:
        staff_name (str): Name of the staff member
    """
    st.subheader(f"Shift Location Preferences for {staff_name}")

    # Initialize database
    initialize_database()

    # Check if user has existing preferences
    success, existing_prefs = get_location_preferences_from_db(staff_name)

    if success and existing_prefs:
        st.success("✅ You have completed your shift preference survey!")

        # Show current preferences in an expander
        with st.expander("📊 View Your Current Preferences", expanded=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**Day Shift Locations:**")
                st.caption("(1st Choice = most desirable)")
                # Sort by rank (ascending - rank 1 is best)
                day_sorted = sorted(existing_prefs['day_locations'].items(), key=lambda x: x[1] if x[1] else 999)
                for location, rank in day_sorted:
                    if rank:
                        choice_label = DAY_CHOICE_LABELS[rank - 1] if rank <= len(DAY_CHOICE_LABELS) else f"Choice {rank}"
                        st.markdown(f"**{choice_label}:** {location}")

            with col2:
                st.markdown("**Night Shift Locations:**")
                st.caption("(1st Choice = most desirable)")
                # Sort by rank (ascending - rank 1 is best)
                night_sorted = sorted(existing_prefs['night_locations'].items(), key=lambda x: x[1] if x[1] else 999)
                for location, rank in night_sorted:
                    if rank:
                        choice_label = NIGHT_CHOICE_LABELS[rank - 1] if rank <= len(NIGHT_CHOICE_LABELS) else f"Choice {rank}"
                        st.markdown(f"**{choice_label}:** {location}")

            with col3:
                st.markdown("**Additional Information:**")
                st.markdown(f"**Zip Code:** {existing_prefs['zip_code']}")
                reduced_status = "✅ Yes" if existing_prefs['reduced_rest_ok'] else "❌ No"
                st.markdown(f"**Reduced Rest OK:** {reduced_status}")
                st.markdown(f"**N to D Flex:** ✅ {existing_prefs['n_to_d_flex']}")
                st.caption(f"_Last updated: {existing_prefs['modified_date']}_")

        st.markdown("---")
        st.info("💡 You can update your preferences using the form below.")
    else:
        st.warning("⚠️ You have not completed your shift preference survey yet.")
        st.info("📝 Please complete all fields below to submit your preferences.")

    st.markdown("---")
    st.markdown("### 📍 Shift Location Preferences")
    st.info("💡 **Instructions:** Select your preferred location for each choice. First Choice = most desirable. Each location can only be selected once within each shift type.")

    # Create two columns for day and night locations
    loc_col1, loc_col2 = st.columns(2)

    with loc_col1:
        st.markdown("### ☀️ Day Shift Locations")
        st.markdown("**Select your preferred location for each choice**")
        st.caption("Locations: KMHT, KLWM, KBED, 1B9, KPYM")
        st.caption("⚠️ Each location can only be selected once")

        # Build existing choices from existing preferences (rank -> location)
        existing_day_choices = {}
        if success and existing_prefs:
            for loc, rank in existing_prefs['day_locations'].items():
                if rank:
                    existing_day_choices[rank] = loc

        day_choice_selections = {}  # {choice_rank: selected_location}

        for rank, choice_label in enumerate(DAY_CHOICE_LABELS, start=1):
            # Get current location for this choice rank
            current_location = existing_day_choices.get(rank)

            # Find index for selectbox
            if current_location and current_location in DAY_LOCATIONS:
                initial_index = DAY_LOCATIONS.index(current_location) + 1
            else:
                initial_index = 0

            day_choice_selections[rank] = st.selectbox(
                f"📍 {choice_label}",
                options=[None] + DAY_LOCATIONS,
                index=initial_index,
                key=f"day_choice_{rank}_{staff_name}",
                format_func=lambda x: "None" if x is None else x,
                help=f"Select location for {choice_label}"
            )

        # Convert choice selections to location preferences (location -> rank)
        day_preferences = {}
        for rank, location in day_choice_selections.items():
            if location:
                day_preferences[location] = rank

    with loc_col2:
        st.markdown("### 🌙 Night Shift Locations")
        st.markdown("**Select your preferred location for each choice**")
        st.caption("Locations: KLWM, KBED, KPYM")
        st.caption("⚠️ Each location can only be selected once")

        # Build existing choices from existing preferences (rank -> location)
        existing_night_choices = {}
        if success and existing_prefs:
            for loc, rank in existing_prefs['night_locations'].items():
                if rank:
                    existing_night_choices[rank] = loc

        night_choice_selections = {}  # {choice_rank: selected_location}

        for rank, choice_label in enumerate(NIGHT_CHOICE_LABELS, start=1):
            # Get current location for this choice rank
            current_location = existing_night_choices.get(rank)

            # Find index for selectbox
            if current_location and current_location in NIGHT_LOCATIONS:
                initial_index = NIGHT_LOCATIONS.index(current_location) + 1
            else:
                initial_index = 0

            night_choice_selections[rank] = st.selectbox(
                f"📍 {choice_label}",
                options=[None] + NIGHT_LOCATIONS,
                index=initial_index,
                key=f"night_choice_{rank}_{staff_name}",
                format_func=lambda x: "None" if x is None else x,
                help=f"Select location for {choice_label}"
            )

        # Convert choice selections to location preferences (location -> rank)
        night_preferences = {}
        for rank, location in night_choice_selections.items():
            if location:
                night_preferences[location] = rank

    # Additional preferences section
    st.markdown("---")
    st.markdown("### ⚙️ Additional Information")
    st.markdown("**🔴 All fields below are required**")

    # Three columns for additional info
    info_col1, info_col2, info_col3 = st.columns(3)

    with info_col1:
        st.markdown("#### 📮 Zip Code")
        current_zip = existing_prefs['zip_code'] if (success and existing_prefs) else ""
        zip_code = st.text_input(
            "Zip Code",
            value=current_zip,
            key=f"zip_code_{staff_name}",
            help="Enter your zip code (required)",
            placeholder="e.g., 02101",
            label_visibility="collapsed"
        )

    with info_col2:
        st.markdown("#### 🛌 Reduced Rest OK")
        st.caption("Accept 10 hours rest instead of 12 which could allow for more flexible scheduling and higher preference availability on subsequent shifts?")

        # Get current value
        current_reduced_rest = None
        if success and existing_prefs:
            current_reduced_rest = existing_prefs['reduced_rest_ok']

        reduced_rest_options = ["Please select...", "Yes", "No"]
        if current_reduced_rest is not None:
            initial_reduced_index = 1 if current_reduced_rest else 2
        else:
            initial_reduced_index = 0

        reduced_rest_selection = st.radio(
            "Reduced Rest OK",
            options=reduced_rest_options,
            index=initial_reduced_index,
            key=f"reduced_rest_{staff_name}",
            help="Accept shifts with 10 hours rest instead of 12 hours",
            label_visibility="collapsed"
        )

        reduced_rest_answered = reduced_rest_selection != "Please select..."
        reduced_rest_value = reduced_rest_selection == "Yes" if reduced_rest_answered else None

    with info_col3:
        st.markdown("#### 🔄 N to D Flex")
        st.caption("By seniority and schedule needs, I would like to opt-in to automatic Night-to-Day transitions?")

        # Get current value
        current_n_to_d_flex = None
        if success and existing_prefs:
            current_n_to_d_flex = existing_prefs['n_to_d_flex']

        n_to_d_flex_options = ["Please select...", "Yes", "No", "Maybe"]
        if current_n_to_d_flex and current_n_to_d_flex in ["Yes", "No", "Maybe"]:
            initial_flex_index = n_to_d_flex_options.index(current_n_to_d_flex)
        else:
            initial_flex_index = 0

        n_to_d_flex_selection = st.radio(
            "N to D Flex",
            options=n_to_d_flex_options,
            index=initial_flex_index,
            key=f"n_to_d_flex_{staff_name}",
            help="Flexibility with transitioning from night shifts to day shifts",
            label_visibility="collapsed"
        )

        n_to_d_flex_answered = n_to_d_flex_selection != "Please select..."
        n_to_d_flex_value = n_to_d_flex_selection if n_to_d_flex_answered else None

    # Validation and preview
    st.markdown("---")

    # Validate all preferences (pass choice_selections for duplicate checking)
    is_valid, errors = validate_location_preferences(
        day_choice_selections, night_choice_selections, zip_code,
        reduced_rest_answered, n_to_d_flex_answered
    )

    if not is_valid:
        st.error("❌ **Please complete all required fields:**")
        for error in errors:
            st.error(f"• {error}")
    else:
        st.success("✅ **All preferences are valid and ready to save!**")

        # Show preview
        with st.expander("📋 Preview Your Preferences", expanded=True):
            preview_col1, preview_col2, preview_col3 = st.columns(3)

            with preview_col1:
                st.markdown("**Day Shift Locations:**")
                st.caption("(1st Choice = most desirable)")
                # Sort by rank (ascending - rank 1 is best)
                for rank in sorted(day_choice_selections.keys()):
                    location = day_choice_selections[rank]
                    if location:
                        choice_label = DAY_CHOICE_LABELS[rank - 1] if rank <= len(DAY_CHOICE_LABELS) else f"Choice {rank}"
                        st.markdown(f"**{choice_label}:** {location}")

            with preview_col2:
                st.markdown("**Night Shift Locations:**")
                st.caption("(1st Choice = most desirable)")
                # Sort by rank (ascending - rank 1 is best)
                for rank in sorted(night_choice_selections.keys()):
                    location = night_choice_selections[rank]
                    if location:
                        choice_label = NIGHT_CHOICE_LABELS[rank - 1] if rank <= len(NIGHT_CHOICE_LABELS) else f"Choice {rank}"
                        st.markdown(f"**{choice_label}:** {location}")

            with preview_col3:
                st.markdown("**Additional Information:**")
                st.markdown(f"**Zip Code:** {zip_code}")
                reduced_status = "✅ Yes" if reduced_rest_value else "❌ No"
                st.markdown(f"**Reduced Rest OK:** {reduced_status}")
                st.markdown(f"**N to D Flex:** ✅ {n_to_d_flex_value}")

    # Save button
    st.markdown("---")
    if is_valid:
        save_col1, save_col2 = st.columns([2, 1])

        with save_col1:
            if st.button("💾 Save My Preferences", use_container_width=True, type="primary"):
                # Save to database
                success_save, message = save_location_preferences_to_db(
                    staff_name,
                    day_preferences,
                    night_preferences,
                    zip_code.strip(),
                    reduced_rest_value,
                    n_to_d_flex_value
                )

                if success_save:
                    st.success(f"✅ {message}")
                    st.balloons()
                    st.info("🔄 Your preferences have been saved and will be used for scheduling!")

                    # Rerun to show updated preferences
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

        with save_col2:
            st.caption("All fields are required before saving")
    else:
        st.warning("⚠️ Please complete all required fields above before saving.")
