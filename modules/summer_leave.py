# modules/summer_leave.py - Summer Leave Time Selection Module

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import sqlite3
import os
from openpyxl import load_workbook
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
from training_modules.training_email_notifications import send_summer_leave_notification

# Constants
SUMMER_START_DATE = datetime(2026, 5, 31)  # May 31, 2026 (Sunday) - Default for Nurse/Medic
CCEMT_START_DATE = datetime(2026, 6, 7)    # June 7, 2026 (Sunday) - CCEMT specific
SUMMER_END_DATE = datetime(2026, 9, 12)    # September 12, 2026 (Saturday)

# Weekly shift caps by role (maximum shifts per week)
ROLE_CAPS = {
    'NURSE': 11,
    'MEDIC': 11,
    'AMT': 2,
    'CCEMT': 2,
    'COMMS': 2,
    'ATP': 2
}

# Roles that use shift-based caps (others use person-based caps)
SHIFT_BASED_ROLES = {'NURSE', 'MEDIC'}

# Cache for staff shifts and roles
_staff_shifts_cache = None
_staff_roles_cache = None

def load_staff_shifts_from_excel():
    """
    Load staff shifts per pay period from Requirements.xlsx

    Returns:
        dict: Dictionary mapping staff_name to shifts_per_pay_period
    """
    global _staff_shifts_cache

    if _staff_shifts_cache is not None:
        return _staff_shifts_cache

    try:
        # Use glob pattern like the rest of the app to find Requirements file
        import glob
        upload_dir = "upload files"

        # Find Requirements file
        requirements_files = glob.glob(os.path.join(upload_dir, "*equirement*.xlsx"))
        if not requirements_files:
            print("No Requirements file found in upload files directory")
            return {}

        requirements_path = requirements_files[0]

        # Use pandas with openpyxl engine in read-only mode to avoid file locks
        df = pd.read_excel(requirements_path, engine='openpyxl')

        staff_shifts = {}
        # Iterate through rows (skip header)
        for idx in range(len(df)):
            row = df.iloc[idx]
            if pd.notna(row.iloc[0]):  # Staff name exists
                staff_name = str(row.iloc[0]).strip()
                shifts_per_pay_period = row.iloc[1] if len(row) > 1 and pd.notna(row.iloc[1]) else None
                staff_shifts[staff_name] = shifts_per_pay_period

        _staff_shifts_cache = staff_shifts
        return staff_shifts

    except Exception as e:
        print(f"Error loading staff shifts from Requirements.xlsx: {e}")
        import traceback
        traceback.print_exc()
        return {}

def load_staff_roles_from_excel():
    """
    Load staff roles from Preferences v6.xlsx

    Returns:
        dict: Dictionary mapping staff_name to role (nurse, medic, dual)
    """
    global _staff_roles_cache

    if _staff_roles_cache is not None:
        return _staff_roles_cache

    try:
        # Use glob pattern like the rest of the app
        import glob
        upload_dir = "upload files"

        preferences_files = glob.glob(os.path.join(upload_dir, "Preferences*.xlsx"))
        if not preferences_files:
            print("No Preferences file found in upload files directory")
            return {}

        preferences_path = preferences_files[0]

        # Use pandas with openpyxl engine to avoid file locks
        df = pd.read_excel(preferences_path, engine='openpyxl')

        staff_roles = {}
        # Iterate through rows (skip header)
        for idx in range(len(df)):
            row = df.iloc[idx]
            if pd.notna(row.iloc[0]):  # Staff name exists
                staff_name = str(row.iloc[0]).strip()
                role = str(row.iloc[1]).strip().lower() if len(row) > 1 and pd.notna(row.iloc[1]) else None

                # Convert 'dual' to 'nurse' as specified
                if role == 'dual':
                    role = 'nurse'

                staff_roles[staff_name] = role

        _staff_roles_cache = staff_roles
        return staff_roles

    except Exception as e:
        print(f"Error loading staff roles from Preferences file: {e}")
        import traceback
        traceback.print_exc()
        return {}

def get_shifts_per_week(staff_name):
    """
    Get shifts per week for a staff member

    Args:
        staff_name (str): Name of staff member

    Returns:
        int or None: Shifts per week (shifts_per_pay_period / 2, rounded down), or None if not found
    """
    staff_shifts = load_staff_shifts_from_excel()
    shifts_per_pay_period = staff_shifts.get(staff_name)

    if shifts_per_pay_period is None:
        return None

    # Convert to int (pandas returns numpy.float64) and round down using integer division
    return int(shifts_per_pay_period) // 2

def get_staff_role_from_preferences(staff_name):
    """
    Get role for a staff member from Preferences.xlsx

    Args:
        staff_name (str): Name of staff member

    Returns:
        str: Role (nurse, medic, etc.) or None if not found
    """
    staff_roles = load_staff_roles_from_excel()
    return staff_roles.get(staff_name)

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
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            # Create summer_leave_requests table with shifts_used column
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS summer_leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_name TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                week_start_date TEXT NOT NULL,
                week_end_date TEXT NOT NULL,
                selection_date TEXT NOT NULL,
                modified_date TEXT,
                status TEXT DEFAULT 'active',
                shifts_used INTEGER
            )
            ''')
            print("Created summer_leave_requests table")
        else:
            # Check if shifts_used column exists
            cursor.execute("PRAGMA table_info(summer_leave_requests)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'shifts_used' not in columns:
                # Add shifts_used column
                cursor.execute("ALTER TABLE summer_leave_requests ADD COLUMN shifts_used INTEGER")
                print("Added shifts_used column to summer_leave_requests table")

                # Migrate existing data - populate shifts_used with staff's shifts per week
                cursor.execute("SELECT staff_name, role FROM summer_leave_requests WHERE status = 'active'")
                existing_selections = cursor.fetchall()

                for staff_name, role in existing_selections:
                    shifts_per_week = get_shifts_per_week(staff_name)
                    if shifts_per_week is not None:
                        cursor.execute(
                            "UPDATE summer_leave_requests SET shifts_used = ? WHERE staff_name = ?",
                            (shifts_per_week, staff_name)
                        )
                        print(f"Migrated {staff_name}: {shifts_per_week} shifts/week")

                conn.commit()
                print("Migration complete: populated shifts_used for existing selections")

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

def display_track_schedule(schedule_by_week, selected_week_display=None, week_availability=None, week_shift_info=None):
    """
    Display track schedule in a compact format

    Args:
        schedule_by_week (dict): Schedule data by week
        selected_week_display (str): Highlight this week if provided
        week_availability (dict): Dictionary mapping week display strings to availability status
        week_shift_info (dict): Dictionary mapping week display strings to shift usage info (shifts_used, shifts_remaining, cap)
    """
    if not schedule_by_week:
        st.info("No track data available for your role")
        return

    st.markdown("### Your Schedule for Summer Leave Period")

    for week_display, daily_schedule in schedule_by_week.items():
        # Check if this week is available
        is_available = week_availability.get(week_display, True) if week_availability else True

        # Get shift info for this week
        shift_info = week_shift_info.get(week_display) if week_shift_info else None

        # Build the header with availability indicator and shift info
        if week_display == selected_week_display:
            header = f"**📅 {week_display}** ⭐ **(Selected)**"
        elif not is_available:
            header = f"**📅 {week_display}** 🔴 **FULL - Not Available**"
        else:
            header = f"**📅 {week_display}**"

        # Add shift usage info if available
        if shift_info:
            shifts_used = shift_info['shifts_used']
            cap = shift_info['cap']
            shifts_remaining = shift_info['shifts_remaining']
            header += f" - {shifts_remaining} spot(s) remaining ({shifts_used}/{cap} spot(s) used)"

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

    # Check if this role uses shift-based caps
    is_shift_based = role in SHIFT_BASED_ROLES

    # Get staff's shifts per week (only required for NURSE/MEDIC)
    shifts_per_week = None
    if is_shift_based:
        shifts_per_week = get_shifts_per_week(staff_name)

        if shifts_per_week is None:
            st.error("❌ Unable to determine your shifts per week.")
            st.info("Please contact your administrator to update your shift information in the Requirements file.")
            return

        # Display staff's shifts per week
        st.info(f"📊 **Your Shifts Per Week:** {shifts_per_week}")

    # Get current selection
    current_selection = get_summer_leave_selection(staff_name)

    # Display current selection
    if current_selection:
        shifts_used = current_selection.get('shifts_used', shifts_per_week)
        st.success(f"✅ You have selected: **{current_selection['week_start_date']} to {current_selection['week_end_date']}**")
        st.info(f"**Shifts Used:** {shifts_used}")

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
    week_shift_info = {}  # Track shift usage info for each week

    for week_start_str, week_end_str, display_str in weeks:
        # Check availability for this week (shifts for NURSE/MEDIC, people for others)
        count_used = get_week_selections_by_role(week_start_str, role)
        cap = ROLE_CAPS.get(role, 2)

        count_remaining = cap - count_used
        is_available = count_remaining > 0

        # Store availability and shift info for display
        week_availability[display_str] = is_available
        week_shift_info[display_str] = {
            'shifts_used': count_used,
            'cap': cap,
            'shifts_remaining': count_remaining
        }

        if is_available:
            if is_shift_based:
                status = f"{count_remaining} shifts remaining"
                option_label = f"{display_str} - {status} ({count_used}/{cap} shifts used)"
            else:
                status = f"{count_remaining} spots remaining"
                option_label = f"{display_str} - {status} ({count_used}/{cap} people)"
        else:
            status = "FULL - Not Available"
            if is_shift_based:
                option_label = f"{display_str} - {status} ({count_used}/{cap} shifts used)"
            else:
                option_label = f"{display_str} - {status} ({count_used}/{cap} people)"

        # Include all weeks (available and full) in the mapping and dropdown
        week_mapping[option_label] = (week_start_str, week_end_str, display_str, count_remaining, is_available)
        week_options.append(option_label)

    if not week_options:
        st.warning("No weeks are currently available for your role.")
        # Still show schedule even if no weeks available, so user can see their shifts
        if schedule_by_week:
            st.markdown("---")
            display_track_schedule(schedule_by_week, None, week_availability, week_shift_info)
        return

    # Week selection dropdown with placeholder
    placeholder = "-- Select a week --"
    dropdown_options = [placeholder] + week_options

    selected_option = st.selectbox(
        "Choose a week:",
        options=dropdown_options,
        index=0
    )

    # Show shift selection and submit button if a valid week is selected
    if selected_option and selected_option != placeholder:
        week_start_str, week_end_str, display_str, count_remaining, is_available = week_mapping[selected_option]

        # Check if week is full
        if not is_available:
            st.error("❌ **This week is full and cannot be selected.**")
            st.info("Please choose a different week with available capacity.")
        else:
            selected_shifts = None

            # For NURSE/MEDIC: Show shift selection dropdown
            if is_shift_based:
                # Determine shift options for dropdown
                max_shifts_available = min(shifts_per_week, count_remaining)

                # Check if this is a partial week (user can't use all their shifts)
                is_partial = max_shifts_available < shifts_per_week

                if is_partial:
                    st.warning(f"⚠️ **Partial Week Notice:** This week only has {count_remaining} shift(s) remaining. You can only use {max_shifts_available} shift(s) for this week.")

                # Create shift selection dropdown
                shift_options = list(range(max_shifts_available, 0, -1))  # From max down to 1

                st.markdown("### How many shifts would you like to use?")
                selected_shifts = st.selectbox(
                    "Number of shifts:",
                    options=shift_options,
                    index=0,  # Default to maximum available
                    key="shift_count_select"
                )

                st.info(f"You are requesting **{selected_shifts}** shift(s) for the week of **{display_str}**")
            else:
                # For CCEMT and other roles: Simple confirmation
                st.info(f"You are requesting the week of **{display_str}**")

            # Submit button
            if st.button("✅ Submit My Selection", type="primary"):
                success, message = save_summer_leave_selection(staff_name, role, week_start_str, week_end_str, selected_shifts)
                if success:
                    st.success(f"✅ {message}")

                    # Send email notification to same group as training events
                    try:
                        # Get updated shift count for this week/role
                        total_shifts_used = get_week_selections_by_role(week_start_str, role)
                        role_cap = ROLE_CAPS.get(role, 2)

                        # Send notification
                        email_success, email_message = send_summer_leave_notification(
                            staff_name, role, week_start_str, week_end_str,
                            total_shifts_used, role_cap
                        )

                        # Don't fail the whole operation if email fails
                        if not email_success:
                            print(f"Email notification failed: {email_message}")
                    except Exception as e:
                        print(f"Error sending summer leave notification: {str(e)}")

                    st.balloons()
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

    # Always show track schedule so user can see when they're working
    if schedule_by_week:
        st.markdown("---")
        # If a valid week is selected, highlight it in the schedule
        if selected_option and selected_option != placeholder:
            week_start_str, week_end_str, display_str, shifts_remaining, is_available = week_mapping[selected_option]
            display_track_schedule(schedule_by_week, display_str, week_availability, week_shift_info)
        else:
            # Show schedule without any week highlighted
            display_track_schedule(schedule_by_week, None, week_availability, week_shift_info)

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
                'staff_with_selections': len(role_selections)
            }

        # Display as table
        stats_data = []
        for role, cap in ROLE_CAPS.items():
            stats = role_stats.get(role, {'staff_with_selections': 0})
            # Use different label for shift-based vs person-based roles
            cap_label = f"{cap} shifts" if role in SHIFT_BASED_ROLES else f"{cap} people"
            stats_data.append({
                'Role': role,
                'Weekly Cap': cap_label,
                'Staff with Selections': stats['staff_with_selections']
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

                            # Show shifts for NURSE/MEDIC, people count for others
                            if role in SHIFT_BASED_ROLES:
                                # Calculate total shifts used for this role/week
                                total_shifts = sum(sel.get('shifts_used', 0) or 0 for sel in role_week_selections)
                                st.markdown(f"**{role}:** {total_shifts}/{cap} shifts used")
                                for sel in role_week_selections:
                                    shifts = sel.get('shifts_used', '?')
                                    st.markdown(f"  - {sel['staff_name']} ({shifts} shifts)")
                            else:
                                # Show person count for CCEMT and others
                                person_count = len(role_week_selections)
                                st.markdown(f"**{role}:** {person_count}/{cap} people")
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
                'Week Selected': f"{selection['week_start_date']} to {selection['week_end_date']}" if selection else '',
                'Shifts Used': selection.get('shifts_used', 0) if selection else 0
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

            # Check if this role uses shift-based caps
            is_admin_shift_based = staff_role in SHIFT_BASED_ROLES

            # Get staff's shifts per week (only for NURSE/MEDIC)
            staff_shifts_per_week = None
            if is_admin_shift_based:
                staff_shifts_per_week = get_shifts_per_week(admin_selected_staff)

            if current_selection:
                if is_admin_shift_based:
                    shifts_used = current_selection.get('shifts_used', '?')
                    st.success(f"Current selection: {current_selection['week_start_date']} to {current_selection['week_end_date']} ({shifts_used} shifts)")
                else:
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

            # Check for shift data only for NURSE/MEDIC
            if is_admin_shift_based and staff_shifts_per_week is None:
                st.warning(f"⚠️ {admin_selected_staff} does not have shift information in Requirements.xlsx")
                st.info("Please update the Requirements file before adding a selection.")
            else:
                if is_admin_shift_based:
                    st.info(f"**{admin_selected_staff}'s Shifts Per Week:** {staff_shifts_per_week}")

                # Week selector (use staff's role to get appropriate weeks)
                weeks = get_summer_weeks(staff_role)
                week_options = [display_str for _, _, display_str in weeks]
                week_mapping = {display_str: (start, end) for start, end, display_str in weeks}

                selected_week = st.selectbox("Select Week:", options=week_options, key="admin_week_select")

                # Shift count selector (only for NURSE/MEDIC)
                selected_shifts = None
                if is_admin_shift_based:
                    shift_options = list(range(staff_shifts_per_week, 0, -1))  # From max down to 1
                    selected_shifts = st.selectbox(
                        "Number of Shifts:",
                        options=shift_options,
                        index=0,
                        key="admin_shift_count_select"
                    )

                if selected_week and st.button("✅ Save Selection"):
                    week_start_str, week_end_str = week_mapping[selected_week]
                    success, message = save_summer_leave_selection(admin_selected_staff, staff_role, week_start_str, week_end_str, selected_shifts)
                    if success:
                        st.success(message)

                        # Send email notification to same group as training events
                        try:
                            # Get updated shift count for this week/role
                            total_shifts_used = get_week_selections_by_role(week_start_str, staff_role)
                            role_cap = ROLE_CAPS.get(staff_role, 2)

                            # Send notification
                            email_success, email_message = send_summer_leave_notification(
                                admin_selected_staff, staff_role, week_start_str, week_end_str,
                                total_shifts_used, role_cap
                            )

                            # Don't fail the whole operation if email fails
                            if not email_success:
                                print(f"Email notification failed: {email_message}")
                        except Exception as e:
                            print(f"Error sending summer leave notification: {str(e)}")

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
