# modules/preference_editor.py - ENHANCED VERSION
"""
Enhanced Preference Management System
Allows users to edit their shift preferences AND boolean preferences within the application
"""

import streamlit as st
import pandas as pd
import sqlite3
import os
import json
from datetime import datetime
from .shift_definitions import day_shifts, night_shifts
from .db_utils import get_db_connection, initialize_database

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
