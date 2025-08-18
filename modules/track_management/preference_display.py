# modules/track_management/preference_display.py
"""
Module for displaying staff preferences
"""

import streamlit as st
import pandas as pd
# Fix #3: Correct relative imports from parent directory
from ..shift_definitions import day_shifts, night_shifts
from ..db_utils import get_db_connection

def color_pref(val):
    """
    Create a color gradient for preference values
    
    Args:
        val: Preference value (1-10)
        
    Returns:
        str: CSS style string for background color
    """
    # Create a color scale from white to green
    if pd.isna(val):
        return ''
    
    # Scale from 1-10
    intensity = int((val / 10) * 255)
    r = 255 - intensity
    g = 255
    b = 255 - intensity
    
    return f'background-color: rgb({r}, {g}, {b})'

def get_staff_preferences_for_display(staff_name, staff_info):
    """
    Get preferences for display - checks database first, then falls back to file data
    
    Args:
        staff_name (str): Name of the staff member
        staff_info (Series): Staff information row from Excel file
        
    Returns:
        tuple: (preferences_dict, boolean_preferences_dict, source)
    """
    try:
        # Check database first
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get shift preferences from database
        cursor.execute("""
            SELECT shift_name, preference_score, shift_type
            FROM user_preferences 
            WHERE staff_name = ? AND is_active = 1
        """, (staff_name,))
        
        db_shift_prefs = cursor.fetchall()
        
        # Get boolean preferences from database
        cursor.execute("""
            SELECT preference_name, preference_value
            FROM user_boolean_preferences 
            WHERE staff_name = ? AND is_active = 1
        """, (staff_name,))
        
        db_boolean_prefs = cursor.fetchall()
        
        if db_shift_prefs or db_boolean_prefs:
            # Build preferences from database
            shift_preferences = {}
            boolean_preferences = {}
            
            # Add shift preferences
            for shift_name, preference_score, shift_type in db_shift_prefs:
                shift_preferences[shift_name] = preference_score
            
            # Add boolean preferences
            for pref_name, pref_value in db_boolean_prefs:
                if pref_name == 'N to D Flex':
                    # Handle string values for N to D Flex
                    boolean_preferences[pref_name] = str(pref_value)
                else:
                    # Handle boolean values
                    boolean_preferences[pref_name] = bool(int(pref_value)) if str(pref_value).isdigit() else bool(pref_value)
            
            return shift_preferences, boolean_preferences, 'database'
        else:
            # Fall back to file preferences
            shift_prefs = {}
            boolean_prefs = {}
            
            # Extract shift preferences from file
            for shift in staff_info.index:
                if shift in day_shifts or shift in night_shifts:
                    if not pd.isna(staff_info[shift]):
                        shift_prefs[shift] = staff_info[shift]
            
            # Extract boolean preferences from file
            # Find the reduced rest column
            reduced_rest_column = next((col for col in staff_info.index if 'rest' in col.lower()), None)
            if reduced_rest_column and not pd.isna(staff_info[reduced_rest_column]):
                boolean_prefs['Reduced Rest OK'] = bool(staff_info[reduced_rest_column])
            
            # Find the N to D Flex column
            n_to_d_flex_column = next((col for col in staff_info.index if 'n to d flex' in col.lower()), None)
            if n_to_d_flex_column and not pd.isna(staff_info[n_to_d_flex_column]):
                n_to_d_flex_value = staff_info[n_to_d_flex_column]
                # Convert to standard format
                if str(n_to_d_flex_value).lower() in ['yes', 'y', '1', 'true']:
                    boolean_prefs['N to D Flex'] = "Yes"
                elif str(n_to_d_flex_value).lower() in ['no', 'n', '0', 'false']:
                    boolean_prefs['N to D Flex'] = "No"
                elif str(n_to_d_flex_value).lower() in ['maybe', 'm', 'possibly']:
                    boolean_prefs['N to D Flex'] = "Maybe"
                else:
                    boolean_prefs['N to D Flex'] = str(n_to_d_flex_value)
            
            return shift_prefs, boolean_prefs, 'file'
        
    except Exception as e:
        print(f"Error getting preferences for display: {str(e)}")
        # Fall back to file preferences
        shift_prefs = {}
        boolean_prefs = {}
        
        # Extract shift preferences from file
        for shift in staff_info.index:
            if shift in day_shifts or shift in night_shifts:
                if not pd.isna(staff_info[shift]):
                    shift_prefs[shift] = staff_info[shift]
        
        return shift_prefs, boolean_prefs, 'file'

def display_preferences(selected_staff, staff_info, preferences_df):
    """
    Display the current preferences for the selected staff member
    
    Args:
        selected_staff (str): Name of the selected staff member
        staff_info (Series): Staff information row
        preferences_df (DataFrame): DataFrame containing staff preferences
    """
    # Get the current preferences (database first, then file)
    shift_preferences, boolean_preferences, source = get_staff_preferences_for_display(selected_staff, staff_info)
    
    # Display title with source indicator
    if source == 'database':
        st.subheader(f"Current Preferences for {selected_staff} ✏️")
        st.info("🎯 **Custom Preferences Active** - These are your updated preferences from the database.")
    else:
        st.subheader(f"Original FY25 Preferences for {selected_staff}")
        st.info("📁 **File Preferences** - These are the original preferences from the uploaded file.")
    
    # Display staff attributes using the appropriate source
    attribute_cols = st.columns(4)
    
    with attribute_cols[0]:
        # Find the role column 
        role_column = next((col for col in staff_info.index if col.lower() == 'role'), None)
        if role_column:
            st.info(f"**Role:** {staff_info[role_column]}")
        else:
            st.info("**Role:** Not available")
        
    with attribute_cols[1]:
        # Find the no matrix column
        no_matrix_column = next((col for col in staff_info.index if 'matrix' in col.lower()), None)
        if no_matrix_column:
            no_matrix = "Yes" if staff_info[no_matrix_column] == 1 else "No"
            st.info(f"**No Matrix:** {no_matrix}")
        else:
            st.info("**No Matrix:** Not available")
        
    with attribute_cols[2]:
        # Display Reduced Rest OK from appropriate source
        if 'Reduced Rest OK' in boolean_preferences:
            reduced_rest_display = "Yes" if boolean_preferences['Reduced Rest OK'] else "No"
            source_indicator = "🎯" if source == 'database' else "📁"
            st.info(f"**Reduced Rest OK:** {reduced_rest_display} {source_indicator}")
        else:
            # Fall back to file data
            reduced_rest_column = next((col for col in staff_info.index if 'rest' in col.lower()), None)
            if reduced_rest_column:
                reduced_rest = "Yes" if staff_info[reduced_rest_column] == 1 else "No"
                st.info(f"**Reduced Rest OK:** {reduced_rest} 📁")
            else:
                st.info("**Reduced Rest OK:** Not available")
    
    with attribute_cols[3]:
        # Display N to D Flex from appropriate source
        if 'N to D Flex' in boolean_preferences:
            n_to_d_flex_display = boolean_preferences['N to D Flex']
            source_indicator = "🎯" if source == 'database' else "📁"
            st.info(f"**N to D Flex:** {n_to_d_flex_display} {source_indicator}")
        else:
            # Fall back to file data
            n_to_d_flex_column = next((col for col in staff_info.index if 'n to d flex' in col.lower()), None)
            if n_to_d_flex_column:
                n_to_d_flex_value = staff_info[n_to_d_flex_column]
                # Handle different possible values and convert to display format
                if pd.isna(n_to_d_flex_value) or n_to_d_flex_value == '' or n_to_d_flex_value is None:
                    n_to_d_flex_display = "Not set"
                elif str(n_to_d_flex_value).lower() in ['yes', 'y', '1', 'true']:
                    n_to_d_flex_display = "Yes"
                elif str(n_to_d_flex_value).lower() in ['no', 'n', '0', 'false']:
                    n_to_d_flex_display = "No"
                elif str(n_to_d_flex_value).lower() in ['maybe', 'm', 'possibly']:
                    n_to_d_flex_display = "Maybe"
                else:
                    n_to_d_flex_display = str(n_to_d_flex_value)
                st.info(f"**N to D Flex:** {n_to_d_flex_display} 📁")
            else:
                st.info("**N to D Flex:** Not available")
    
    # Separate day and night preferences
    day_preferences = {k: v for k, v in shift_preferences.items() if k in day_shifts}
    night_preferences = {k: v for k, v in shift_preferences.items() if k in night_shifts}
    
    # Create tables for day and night preferences
    if day_preferences:
        st.subheader("Day Shift Preferences")
        day_pref_df = pd.DataFrame(list(day_preferences.items()), columns=['Shift', 'Preference'])
        day_pref_df = day_pref_df.sort_values('Preference', ascending=False)
        
        st.dataframe(
            day_pref_df.style.map(color_pref, subset=['Preference']),
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("No day shift preferences found.")
    
    if night_preferences:
        st.subheader("Night Shift Preferences")
        night_pref_df = pd.DataFrame(list(night_preferences.items()), columns=['Shift', 'Preference'])
        night_pref_df = night_pref_df.sort_values('Preference', ascending=False)
        
        st.dataframe(
            night_pref_df.style.map(color_pref, subset=['Preference']),
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("No night shift preferences found.")
    
    # Add link to preference update form
    st.markdown("### Update Your Preferences")
    if source == 'database':
        st.markdown("""
        You have custom preferences active! To make further updates, go to the "Edit Preferences" tab.
                    
        **Note**: Any changes will be reflected immediately and used in the hypothetical staffing rebid process.
        """)
    else:
        st.markdown("""
        To update your preferences, go to the next tab "Edit Preferences," make edits, and save.
                    
        **Note**: Updated preferences will be reflected immediately and used in the hypothetical staffing rebid process.
        """)
