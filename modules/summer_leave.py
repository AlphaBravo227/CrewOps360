# modules/summer_leave.py - Summer Leave Time Selection Module

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import sqlite3
import os
from modules.db_utils import (
    get_summer_leave_config,
    set_summer_leave_config,
    get_summer_leave_selection,
    save_summer_leave_selection,
    cancel_summer_leave_selection,
    get_week_selections_by_role,
    get_all_summer_leave_selections,
    get_all_summer_leave_configs,
    get_db_connection
)

# Constants
SUMMER_START_DATE = datetime(2026, 5, 31)  # May 31, 2026 (Sunday) - Default for Nurse/Medic
CCEMT_START_DATE = datetime(2026, 6, 7)    # June 7, 2026 (Sunday) - CCEMT specific
SUMMER_END_DATE = datetime(2026, 9, 12)    # September 12, 2026 (Saturday)

# Weekly caps by role
ROLE_CAPS = {
    'NURSE': 3,
    'MEDIC': 3,
    'AMT': 2,
    'CCEMT': 2,
    'COMMS': 2,
    'ATP': 2
}

def ensure_summer_leave_tables():
    """
    Ensure summer leave tables exist in the database.
    This is a migration function that runs when the module is first accessed.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summer_leave_requests'")
        if not cursor.fetchone():
            # Create summer_leave_requests table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS summer_leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_name TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                week_start_date TEXT NOT NULL,
                week_end_date TEXT NOT NULL,
                selection_date TEXT NOT NULL,
                modified_date TEXT,
                status TEXT DEFAULT 'active'
            )
            ''')
            print("Created summer_leave_requests table")

        # Check if config table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summer_leave_config'")
        if not cursor.fetchone():
            # Create summer_leave_config table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS summer_leave_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_name TEXT NOT NULL UNIQUE,
                lt_open INTEGER DEFAULT 0,
                modified_date TEXT NOT NULL
            )
            ''')
            print("Created summer_leave_config table")

        conn.commit()
        return True

    except Exception as e:
        print(f"Error ensuring summer leave tables: {e}")
        return False

def get_summer_weeks(role=None):
    """
    Generate list of all weeks in the summer leave period (Sunday-Saturday)

    Args:
        role (str): Role of the staff member (optional). If 'CCEMT', uses CCEMT start date.

    Returns:
        list: List of tuples (week_start_date, week_end_date, display_string)
    """
    weeks = []

    # Use role-specific start date
    if role == 'CCEMT':
        current_date = CCEMT_START_DATE
    else:
        current_date = SUMMER_START_DATE

    while current_date <= SUMMER_END_DATE:
        # Calculate week end (Saturday)
        week_end = current_date + timedelta(days=6)

        # Don't go past the summer end date
        if week_end > SUMMER_END_DATE:
            week_end = SUMMER_END_DATE

        # Format display string
        display_str = f"{current_date.strftime('%B %d')}-{week_end.strftime('%d, %Y')}"

        weeks.append((
            current_date.strftime('%Y-%m-%d'),
            week_end.strftime('%Y-%m-%d'),
            display_str
        ))

        # Move to next Sunday
        current_date += timedelta(days=7)

    return weeks

def get_staff_track_schedule(staff_name, role, track_manager):
    """
    Get track schedule for a staff member during summer period

    Args:
        staff_name (str): Name of staff member
        role (str): Staff member's role
        track_manager: TrainingTrackManager instance

    Returns:
        dict: Dictionary mapping week to daily schedule
    """
    if not track_manager or role not in ['NURSE', 'MEDIC', 'CCEMT']:
        return None

    weeks = get_summer_weeks(role)
    schedule_by_week = {}

    for week_start_str, week_end_str, display_str in weeks:
        week_start = datetime.strptime(week_start_str, '%Y-%m-%d')
        week_end = datetime.strptime(week_end_str, '%Y-%m-%d')

        # Get daily schedule for this week
        daily_schedule = []
        current_day = week_start

        while current_day <= week_end:
            # Format date as MM/DD/YYYY for track_manager
            shift = track_manager.get_staff_shift(staff_name, current_day.strftime('%m/%d/%Y'))
            daily_schedule.append({
                'date': current_day.strftime('%a %m/%d'),
                'shift': shift if shift else 'Off'
            })
            current_day += timedelta(days=1)

        schedule_by_week[display_str] = daily_schedule

    return schedule_by_week

def display_track_schedule(schedule_by_week, selected_week_display=None, week_availability=None):
    """
    Display track schedule in a compact format

    Args:
        schedule_by_week (dict): Schedule data by week
        selected_week_display (str): Highlight this week if provided
        week_availability (dict): Dictionary mapping week display strings to availability status
    """
    if not schedule_by_week:
        st.info("No track data available for your role")
        return

    st.markdown("### Your Schedule for Summer Leave Period")

    for week_display, daily_schedule in schedule_by_week.items():
        # Check if this week is available
        is_available = week_availability.get(week_display, True) if week_availability else True

        # Build the header with availability indicator
        if week_display == selected_week_display:
            header = f"**📅 {week_display}** ⭐ **(Selected)**"
        elif not is_available:
            header = f"**📅 {week_display}** 🔴 **FULL - Not Available**"
        else:
            header = f"**📅 {week_display}**"

        st.markdown(header)

        # Create a compact display of the week
        cols = st.columns(len(daily_schedule))
        for idx, day_info in enumerate(daily_schedule):
            with cols[idx]:
                st.markdown(f"**{day_info['date']}**")
                st.markdown(f"{day_info['shift']}")

        st.markdown("---")

def display_user_interface(staff_name, role, excel_handler, track_manager):
    """
    Display the user interface for summer leave selection

    Args:
        staff_name (str): Name of staff member
        role (str): Staff member's role
        excel_handler: ExcelHandler instance
        track_manager: TrainingTrackManager instance
    """
    st.header("☀️ Summer Leave Time Selection")
    st.markdown(f"**Staff:** {staff_name} | **Role:** {role}")

    # Display role-specific date range
    if role == 'CCEMT':
        start_date_display = CCEMT_START_DATE.strftime('%B %d, %Y')
    else:
        start_date_display = SUMMER_START_DATE.strftime('%B %d, %Y')

    st.markdown(f"**Period:** {start_date_display} - {SUMMER_END_DATE.strftime('%B %d, %Y')}")
    st.markdown("---")

    # Check if LT is open for this user
    lt_open = get_summer_leave_config(staff_name)

    if not lt_open:
        st.warning("⚠️ Selection is not available at this time.")
        st.info("Please contact your supervisor if you believe this is an error.")
        return

    # Get current selection
    current_selection = get_summer_leave_selection(staff_name)

    # Display current selection
    if current_selection:
        st.success(f"✅ You have selected: **{current_selection['week_start_date']} to {current_selection['week_end_date']}**")

        week_start = datetime.strptime(current_selection['week_start_date'], '%Y-%m-%d')
        week_end = datetime.strptime(current_selection['week_end_date'], '%Y-%m-%d')
        display_str = f"{week_start.strftime('%B %d')}-{week_end.strftime('%d, %Y')}"

        st.info(f"Selected on: {current_selection['selection_date']}")
        st.info("Please contact your supervisor if you would like to make changes.")

        # Show only the selected week's schedule
        schedule_by_week = get_staff_track_schedule(staff_name, role, track_manager)
        if schedule_by_week and display_str in schedule_by_week:
            st.markdown("---")
            st.markdown("### Your Schedule for Summer Leave Period")

            # Display only the selected week
            daily_schedule = schedule_by_week[display_str]
            st.markdown(f"**📅 {display_str}** ⭐ **(Selected)**")

            cols = st.columns(len(daily_schedule))
            for idx, day_info in enumerate(daily_schedule):
                with cols[idx]:
                    st.markdown(f"**{day_info['date']}**")
                    st.markdown(f"{day_info['shift']}")

        return  # Don't show selection UI if already selected

    # Get all available weeks
    weeks = get_summer_weeks(role)

    # Get track schedule if applicable
    schedule_by_week = get_staff_track_schedule(staff_name, role, track_manager)

    # Display week selection
    st.markdown("### Select Your Week")

    week_options = []
    week_mapping = {}
    week_availability = {}  # Track availability for each week

    for week_start_str, week_end_str, display_str in weeks:
        # Check availability for this week
        selections_count = get_week_selections_by_role(week_start_str, role)
        cap = ROLE_CAPS.get(role, 2)

        is_available = selections_count < cap
        status = "Available" if is_available else "Full"

        # Store availability for display in schedule
        week_availability[display_str] = is_available

        option_label = f"{display_str} - {status} ({selections_count}/{cap})"

        if is_available:
            week_options.append(option_label)
            week_mapping[option_label] = (week_start_str, week_end_str, display_str)

    if not week_options:
        st.warning("No weeks are currently available for your role.")
        # Still show schedule even if no weeks available, so user can see their shifts
        if schedule_by_week:
            st.markdown("---")
            display_track_schedule(schedule_by_week, None, week_availability)
        return

    # Week selection dropdown with placeholder
    placeholder = "-- Select a week --"
    dropdown_options = [placeholder] + week_options

    selected_option = st.selectbox(
        "Choose a week:",
        options=dropdown_options,
        index=0
    )

    # Show submit button right after week selection if a valid week is selected
    if selected_option and selected_option != placeholder:
        week_start_str, week_end_str, display_str = week_mapping[selected_option]

        # Submit button
        if st.button("✅ Submit My Selection", type="primary"):
            success, message = save_summer_leave_selection(staff_name, role, week_start_str, week_end_str)
            if success:
                st.success(f"✅ {message}")
                st.balloons()
                st.rerun()
            else:
                st.error(f"❌ {message}")

    # Always show track schedule so user can see when they're working
    if schedule_by_week:
        st.markdown("---")
        # If a valid week is selected, highlight it in the schedule
        if selected_option and selected_option != placeholder:
            week_start_str, week_end_str, display_str = week_mapping[selected_option]
            display_track_schedule(schedule_by_week, display_str, week_availability)
        else:
            # Show schedule without any week highlighted
            display_track_schedule(schedule_by_week, None, week_availability)

def display_admin_interface(staff_list, role_mapping):
    """
    Display admin interface for managing summer leave

    Args:
        staff_list (list): List of all staff names
        role_mapping (dict): Dictionary mapping staff names to roles
    """
    st.header("🔧 Summer Leave Administration")
    st.markdown("---")

    # Get all configs and selections
    all_configs = get_all_summer_leave_configs()
    all_selections = get_all_summer_leave_selections()

    # Create selections lookup
    selections_lookup = {sel['staff_name']: sel for sel in all_selections}

    # Tabs for different admin functions
    tab1, tab2, tab3 = st.tabs(["📊 Overview", "👥 Manage Staff", "➕ Add/Remove Selection"])

    with tab1:
        st.markdown("### Summary by Role")

        # Calculate statistics by role
        role_stats = {}
        for role in ROLE_CAPS.keys():
            role_selections = [sel for sel in all_selections if sel['role'] == role]
            role_stats[role] = {
                'total_selections': len(role_selections),
                'staff_with_selections': len(role_selections)
            }

        # Display as table
        stats_data = []
        for role, cap in ROLE_CAPS.items():
            stats = role_stats.get(role, {'total_selections': 0, 'staff_with_selections': 0})
            stats_data.append({
                'Role': role,
                'Cap per Week': cap,
                'Staff with Selections': stats['staff_with_selections'],
                'Total Selections': stats['total_selections']
            })

        st.dataframe(pd.DataFrame(stats_data), use_container_width=True)

        st.markdown("---")
        st.markdown("### All Selections by Week")

        # Group selections by week
        weeks = get_summer_weeks()
        for week_start_str, week_end_str, display_str in weeks:
            week_selections = [sel for sel in all_selections if sel['week_start_date'] == week_start_str]

            if week_selections:
                with st.expander(f"📅 {display_str} ({len(week_selections)} selections)"):
                    # Group by role
                    for role in ROLE_CAPS.keys():
                        role_week_selections = [sel for sel in week_selections if sel['role'] == role]
                        if role_week_selections:
                            cap = ROLE_CAPS[role]
                            st.markdown(f"**{role}:** {len(role_week_selections)}/{cap}")
                            for sel in role_week_selections:
                                st.markdown(f"  - {sel['staff_name']}")

    with tab2:
        st.markdown("### Manage Staff LT Access")

        # Create dataframe for all staff
        staff_data = []
        for staff_name in sorted(staff_list):
            role = role_mapping.get(staff_name, 'Unknown')
            lt_open = all_configs.get(staff_name, False)
            selection = selections_lookup.get(staff_name)

            staff_data.append({
                'Staff Name': staff_name,
                'Role': role,
                'LT Open': lt_open,
                'Has Selection': '✅' if selection else '❌',
                'Week Selected': f"{selection['week_start_date']} to {selection['week_end_date']}" if selection else ''
            })

        df = pd.DataFrame(staff_data)

        # Display dataframe
        st.dataframe(df, use_container_width=True)

        st.markdown("---")
        st.markdown("### Toggle LT Access")

        # Staff selector
        selected_staff = st.selectbox("Select Staff Member:", options=sorted(staff_list))

        if selected_staff:
            current_status = all_configs.get(selected_staff, False)
            staff_role = role_mapping.get(selected_staff, 'Unknown')

            st.info(f"**{selected_staff}** ({staff_role}) - LT Open: **{'Yes' if current_status else 'No'}**")

            col1, col2 = st.columns(2)

            with col1:
                if st.button("✅ Enable LT Selection"):
                    success, message = set_summer_leave_config(selected_staff, True)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

            with col2:
                if st.button("❌ Disable LT Selection"):
                    success, message = set_summer_leave_config(selected_staff, False)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

            # Bulk enable/disable
            st.markdown("---")
            st.markdown("### Bulk Operations")

            col3, col4 = st.columns(2)

            with col3:
                if st.button("✅ Enable All Staff"):
                    count = 0
                    for staff in staff_list:
                        success, _ = set_summer_leave_config(staff, True)
                        if success:
                            count += 1
                    st.success(f"Enabled LT selection for {count} staff members")
                    st.rerun()

            with col4:
                if st.button("❌ Disable All Staff"):
                    count = 0
                    for staff in staff_list:
                        success, _ = set_summer_leave_config(staff, False)
                        if success:
                            count += 1
                    st.success(f"Disabled LT selection for {count} staff members")
                    st.rerun()

    with tab3:
        st.markdown("### Add or Remove Selection")

        # Staff selector
        admin_selected_staff = st.selectbox("Select Staff Member:", options=sorted(staff_list), key="admin_staff_select")

        if admin_selected_staff:
            staff_role = role_mapping.get(admin_selected_staff, 'Unknown')
            current_selection = selections_lookup.get(admin_selected_staff)

            st.info(f"**{admin_selected_staff}** ({staff_role})")

            if current_selection:
                st.success(f"Current selection: {current_selection['week_start_date']} to {current_selection['week_end_date']}")

                if st.button("❌ Remove This Selection"):
                    success, message = cancel_summer_leave_selection(admin_selected_staff)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

            st.markdown("---")
            st.markdown("### Add/Update Selection")

            # Week selector (use staff's role to get appropriate weeks)
            weeks = get_summer_weeks(staff_role)
            week_options = [display_str for _, _, display_str in weeks]
            week_mapping = {display_str: (start, end) for start, end, display_str in weeks}

            selected_week = st.selectbox("Select Week:", options=week_options, key="admin_week_select")

            if selected_week and st.button("✅ Save Selection"):
                week_start_str, week_end_str = week_mapping[selected_week]
                success, message = save_summer_leave_selection(admin_selected_staff, staff_role, week_start_str, week_end_str)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

def display_summer_leave_app(excel_handler, track_manager):
    """
    Main entry point for Summer Leave module

    Args:
        excel_handler: ExcelHandler instance for reading staff data
        track_manager: TrainingTrackManager instance for track schedules
    """
    # Ensure database tables exist (migration)
    if not ensure_summer_leave_tables():
        st.error("Failed to initialize summer leave database tables. Please contact support.")
        return

    # Back button
    if st.button("← Back to Main Menu"):
        st.session_state.selected_module = None
        st.rerun()

    st.title("☀️ Summer Leave Time Selection")
    st.markdown("**Summer 2026 Leave Period**")
    st.markdown("---")

    # Get staff list from Excel
    staff_list = excel_handler.get_staff_list() if excel_handler else []

    if not staff_list:
        st.error("Could not load staff list from Excel file.")
        return

    # Create role mapping
    role_mapping = {}
    for staff_name in staff_list:
        # Get role from Excel (Column B)
        try:
            enrollment_sheet = excel_handler.enrollment_sheet
            for row in enrollment_sheet.iter_rows(min_row=2):
                if row[0].value and str(row[0].value).strip() == staff_name:
                    role_cell = row[1].value if len(row) > 1 else None
                    role_mapping[staff_name] = str(role_cell).strip() if role_cell else 'Unknown'
                    break
        except Exception as e:
            print(f"Error getting role for {staff_name}: {e}")
            role_mapping[staff_name] = 'Unknown'

    # Check for admin mode
    if 'summer_leave_admin_mode' not in st.session_state:
        st.session_state.summer_leave_admin_mode = False

    # Admin toggle
    with st.sidebar:
        st.markdown("### Administration")
        admin_password = st.text_input("Admin Password:", type="password", key="summer_admin_pw")

        if admin_password == "PW":
            if st.button("🔧 Enter Admin Mode"):
                st.session_state.summer_leave_admin_mode = True
                st.rerun()

        if st.session_state.summer_leave_admin_mode:
            st.success("✅ Admin Mode Active")
            if st.button("👤 Switch to User Mode"):
                st.session_state.summer_leave_admin_mode = False
                st.rerun()

    # Display appropriate interface
    if st.session_state.summer_leave_admin_mode:
        display_admin_interface(staff_list, role_mapping)
    else:
        # User selects their name
        st.markdown("### Select Your Name")
        selected_staff = st.selectbox("Staff Name:", options=[''] + sorted(staff_list))

        if selected_staff:
            staff_role = role_mapping.get(selected_staff, 'Unknown')

            if staff_role == 'Unknown':
                st.error("Could not determine your role. Please contact your supervisor.")
                return

            st.markdown("---")
            display_user_interface(selected_staff, staff_role, excel_handler, track_manager)
