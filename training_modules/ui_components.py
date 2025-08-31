# training_modules/ui_components.py - Updated sections for duplicate enrollment handling

import streamlit as st
from datetime import datetime

class UIComponents:
    
    @staticmethod
    def display_enrollment_metrics(assigned_classes, enrolled_classes, live_meeting_count, excel_handler):
        """Display enrollment metrics including LIVE staff meeting count"""
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Assigned Classes", len(assigned_classes))
        with col2:
            st.metric("Classes Enrolled", len(enrolled_classes))
        with col3:
            st.metric("Classes Remaining", len(assigned_classes) - len(enrolled_classes))
        with col4:
            # Check if user has any staff meetings assigned
            has_staff_meetings = any(excel_handler.is_staff_meeting(cls) for cls in assigned_classes)
            if has_staff_meetings:
                st.metric("FY26 LIVE Staff Meetings", f"{live_meeting_count}/2")
                if live_meeting_count >= 2:
                    st.success("✅ LIVE meeting requirement met!")
                else:
                    st.info(f"📝 Need {2 - live_meeting_count} more LIVE meeting(s)")

    @staticmethod
    def get_class_enrollment_status(enrollment_manager, staff_name, class_name, excel_handler):
        """Get enrollment status for display in collapsed expander"""
        enrollments = enrollment_manager.get_staff_enrollments(staff_name)
        class_enrollments = [e for e in enrollments if e['class_name'] == class_name]
        
        if not class_enrollments:
            return ""  # Not enrolled, show nothing
        
        # Check if any enrollments have conflicts
        has_conflict_override = any(e.get('conflict_override', False) for e in class_enrollments)
        
        # Check if it's a staff meeting to show LIVE/Virtual
        is_staff_meeting = excel_handler.is_staff_meeting(class_name)
        
        if is_staff_meeting:
            # For staff meetings, show if LIVE or Virtual
            meeting_types = set([e.get('meeting_type', 'Virtual') for e in class_enrollments])
            if 'LIVE' in meeting_types:
                status = "✅ Enrolled (LIVE)"
            else:
                status = "✅ Enrolled (Virtual)"
        else:
            # For all other classes, just show enrolled
            status = "✅ Enrolled"
        
        # Add conflict indicator if applicable
        if has_conflict_override:
            status += " ⚠️"
        
        return status

    @staticmethod
    def display_enrollment_row(enrollment, excel_handler, enrollment_manager):
        """Display a single enrollment row with conflict indicator"""
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 1])
        
        with col1:
            class_name = enrollment['class_name']
            display_name = f"**{class_name}**"
            
            # Add meeting type indicator for staff meetings
            if excel_handler.is_staff_meeting(class_name):
                meeting_type = enrollment.get('meeting_type', 'Virtual')
                if meeting_type == 'LIVE':
                    display_name += " 🔴 LIVE"
                else:
                    display_name += " 💻 Virtual"
            
            # Add conflict indicator
            if enrollment.get('conflict_override'):
                display_name += " ⚠️"
            
            st.write(display_name)
        
        with col2:
            st.write(f"**Date:** {enrollment['class_date']}")
            
            # Show session time if applicable
            if enrollment.get('session_time'):
                st.write(f"**Session:** {enrollment['session_time']}")
        
        with col3:
            if enrollment['role'] != 'General':
                st.write(f"**Role:** {enrollment['role']}")
            else:
                # Show class times
                class_details = excel_handler.get_class_details(enrollment['class_name'])
                if class_details:
                    times = UIComponents.get_class_times(class_details)
                    if times and times != "Time not specified":
                        st.write(f"**Time:** {times}")
            
            # Show conflict details if override
            if enrollment.get('conflict_override'):
                st.write("**⚠️ Swap Required**")
        
        with col4:
            # Show colleagues in the same session
            colleagues = enrollment_manager.get_session_colleagues(
                enrollment['staff_name'],
                enrollment['class_name'],
                enrollment['class_date'],
                enrollment.get('session_time'),
                enrollment.get('meeting_type')
            )
            
            if colleagues:
                st.write("**Also enrolled:**")
                for colleague in colleagues:
                    name_display = colleague['name']
                    if colleague['role'] != 'General':
                        name_display += f" ({colleague['role']})"
                    st.write(f"• {name_display}")
            else:
                st.write("*No one else enrolled*")
        
        with col5:
            return st.button("Cancel", key=f"cancel_{enrollment['id']}")

    @staticmethod
    def display_class_info(class_details):
        """Display class information in a formatted way"""
        if not class_details:
            st.error("No class details available")
            return
        
        # Check if this is missing class data - now checks rows 1-14 dynamically
        is_missing_data = (not class_details or 
                        not any(class_details.get(f'date_{i}') for i in range(1, 15)))
        
        if is_missing_data:
            st.error("📅 **Class data not configured**")
            st.info("This class appears in the assignment roster but does not have a corresponding configuration sheet with dates and details. Please contact the training administrator to set up the class schedule.")
            return
        
        # Display basic class information
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**📚 Class:** {class_details.get('class_name', 'Unknown')}")
            st.write(f"**👥 Max Students:** {class_details.get('students_per_class', '21')}")
            st.write(f"**📅 Sessions per Day:** {class_details.get('classes_per_day', '1')}")
        
        with col2:
            if class_details.get('nurses_medic_separate', 'No').lower() == 'yes':
                st.write("• **Separate slots for Nurses and Medics**")
            if class_details.get('is_two_day_class', 'No').lower() == 'yes':
                st.write("• **Two-day class format**")
            if class_details.get('is_staff_meeting', False):
                st.write("• **Staff Meeting (LIVE/Virtual options)**")
        
        # Display available dates - now dynamically checks all possible date rows
        st.write("**📅 Available Dates:**")
        dates = []
        for i in range(1, 15):  # Check rows 1-14 for dates
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                date = class_details[date_key]
                location = class_details.get(f'date_{i}_location', '')
                can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                
                date_info = f"• {date}"
                if location:
                    date_info += f" - Location: {location}"
                if can_work_n_prior:
                    date_info += " 🌙"
                    
                dates.append(date_info)
        
        if dates:
            for date_info in dates:
                st.write(date_info)
        else:
            st.warning("No dates configured for this class")
        
        # Display class times
        st.write("**🕐 Class Times:**")
        times = UIComponents.get_detailed_times(class_details)
        for time_slot in times:
            st.write(f"• {time_slot}")
        
        # Legend
        st.write("")
        st.write("**Legend:** 🌙 = Night shift prior OK")

    @staticmethod
    def get_detailed_times(class_details):
        """Get detailed time information"""
        times = []
        classes_per_day = int(class_details.get('classes_per_day', 1))
        
        for i in range(1, min(classes_per_day + 1, 5)):  # Max 4 time slots
            start_key = f'time_{i}_start'
            end_key = f'time_{i}_end'
            
            if start_key in class_details and end_key in class_details:
                start_time = class_details[start_key]
                end_time = class_details[end_key]
                
                if start_time and end_time:
                    if classes_per_day > 1:
                        times.append(f"Session {i}: {start_time} - {end_time}")
                    else:
                        times.append(f"{start_time} - {end_time}")
        
        return times if times else ["Time not specified"]

    @staticmethod
    def get_class_times(class_details):
        """Format class times for display (simple format)"""
        times = []
        classes_per_day = int(class_details.get('classes_per_day', 1))
        
        for i in range(1, classes_per_day + 1):
            start_key = f'time_{i}_start'
            end_key = f'time_{i}_end'
            
            if start_key in class_details and end_key in class_details:
                start_time = class_details[start_key]
                end_time = class_details[end_key]
                
                if start_time and end_time:
                    times.append(f"{start_time} - {end_time}")
        
        return ", ".join(times) if times else "Time not specified"

    @staticmethod
    def display_session_enrollment_options_with_tracks(enrollment_manager, class_name, available_dates, 
                                                       selected_staff, track_manager):
        """Display session enrollment options with track conflict information"""
        
        # Check if class has no available dates
        if not available_dates:
            # Check if the class exists but has no data configured
            class_details = enrollment_manager.excel.get_class_details(class_name)
            
            # Check if this returns default values (indicating missing sheet/data)
            is_missing_data = (not class_details or 
                             class_details.get('class_name') == class_name and 
                             not any(class_details.get(f'date_{i}') for i in range(1, 9)))
            
            if is_missing_data:
                st.error("📅 **Class data not configured**")
                st.info("This class appears in your assignment list but does not have a corresponding configuration sheet with scheduled dates. Please contact the training administrator to have dates added for this class.")
            else:
                st.warning("No available dates found for this class.")
            return []
        
        enrolled_sessions = []
        
        # Iterate through available dates and show enrollment options
        for date in available_dates:
            st.subheader(f"📅 {date}")
            
            # Check for track conflicts if available
            conflict_info = None
            if track_manager and track_manager.has_track_data(selected_staff):
                has_conflict, conflict_details = enrollment_manager.check_enrollment_conflict(
                    selected_staff, class_name, date
                )
                conflict_info = (has_conflict, conflict_details)
            
            # Get session options for this date
            session_options = enrollment_manager.get_available_session_options(class_name, date)
            
            if not session_options:
                st.warning(f"No available slots for {date}")
                continue
            
            # Display session options with conflict handling
            for idx, option in enumerate(session_options):
                option_key = f"{class_name}_{date}_{idx}"
                
                UIComponents._display_session_option_with_conflict(
                    option, option_key, enrollment_manager, selected_staff, 
                    class_name, date, conflict_info
                )
            
            st.markdown("---")
        
        return enrolled_sessions

    @staticmethod
    def display_enrollment_summary(enrollment_summary, class_details):
        """Display enrollment summary for a class with conflict indicators"""
        st.write("")
        st.write("**📊 Current Enrollment Status:**")
        
        max_students = int(class_details.get('students_per_class', 21))
        is_staff_meeting = class_details.get('is_staff_meeting', False)
        nurses_medic_separate = class_details.get('nurses_medic_separate', 'No').lower() == 'yes'
        
        if not enrollment_summary:
            st.info("No enrollments found for this class.")
            return
        
        # Display enrollment by date
        for date, summary in enrollment_summary.items():
            st.write(f"**📅 {date}:**")
            
            total_enrolled = summary.get('total', 0)
            conflicts = summary.get('conflicts', 0)
            
            # Basic enrollment info
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if is_staff_meeting:
                    # For staff meetings, show LIVE/Virtual breakdown
                    meeting_types = summary.get('meeting_types', {})
                    live_count = meeting_types.get('LIVE', 0)
                    virtual_count = meeting_types.get('Virtual', 0)
                    
                    st.write(f"🔴 LIVE: {live_count}")
                    st.write(f"💻 Virtual: {virtual_count}")
                    st.write(f"**Total: {total_enrolled}/{max_students}**")
                
                elif nurses_medic_separate:
                    # For nurse/medic separate classes
                    roles = summary.get('roles', {})
                    nurses = roles.get('Nurse', 0)
                    medics = roles.get('Medic', 0)
                    general = roles.get('General', 0)
                    
                    st.write(f"👩‍⚕️ Nurses: {nurses}")
                    st.write(f"🚑 Medics: {medics}")
                    if general > 0:
                        st.write(f"👤 General: {general}")
                    st.write(f"**Total: {total_enrolled}/{max_students}**")
                
                else:
                    # Regular classes
                    st.write(f"👤 Enrolled: {total_enrolled}/{max_students}")
                    
                    # Show sessions if multiple per day
                    sessions = summary.get('sessions', {})
                    if sessions:
                        st.write("**Sessions:**")
                        for session_time, staff_list in sessions.items():
                            st.write(f"  • {session_time}: {len(staff_list)}")
            
            with col2:
                # Show utilization
                utilization = (total_enrolled / max_students * 100) if max_students > 0 else 0
                if utilization >= 90:
                    st.error(f"🔴 {utilization:.0f}% Full")
                elif utilization >= 70:
                    st.warning(f"🟡 {utilization:.0f}% Full")
                elif utilization >= 40:
                    st.info(f"🟠 {utilization:.0f}% Full")
                else:
                    st.success(f"🟢 {utilization:.0f}% Full")
                
                # Available slots
                available = max_students - total_enrolled
                st.write(f"Available: {available}")
            
            with col3:
                # Show conflicts if any
                if conflicts > 0:
                    st.warning(f"⚠️ {conflicts} conflict(s)")
                else:
                    st.success("✅ No conflicts")
                
                # Show staff names if not too many
                staff_names = summary.get('staff_names', [])
                if len(staff_names) <= 5:
                    st.write("**Enrolled:**")
                    for name in staff_names:
                        st.write(f"• {name}")
                elif len(staff_names) > 5:
                    st.write(f"**{len(staff_names)} staff enrolled**")
            
            st.markdown("---")

    @staticmethod
    def display_track_conflict_summary(conflicts_summary, track_manager):
        """Display a summary of track conflicts for a class"""
        if not conflicts_summary:
            if not track_manager or not track_manager.tracks_db_path:
                st.info("📊 Track data not available - unable to check for schedule conflicts")
            return
        
        # Get summary text
        summary = track_manager.get_conflict_summary(conflicts_summary)
        
        # Display with appropriate styling
        if "All" in summary and "available" in summary:
            st.success(summary)
        elif "all" in summary and "Conflicts" in summary:
            st.error(summary)
        else:
            st.warning(summary)

    @staticmethod
    def display_class_details_full(class_details):
        """Display full class details with location information"""
        
        # Check if this is missing class data - now checks rows 1-14 dynamically
        is_missing_data = (not class_details or 
                        not any(class_details.get(f'date_{i}') for i in range(1, 15)))
        
        if is_missing_data:
            st.error("📅 **Class data not configured**")
            st.info("This class appears in the assignment roster but does not have a corresponding configuration sheet with dates and details. Please contact the training administrator to set up the class schedule.")
            return
        
        # Display comprehensive class details
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**📚 Class:** {class_details.get('class_name', 'Unknown')}")
            st.write(f"**👥 Max Students:** {class_details.get('students_per_class', '21')}")
            st.write(f"**📅 Sessions per Day:** {class_details.get('classes_per_day', '1')}")
        
        with col2:
            if class_details.get('nurses_medic_separate', 'No').lower() == 'yes':
                st.write("• **Separate slots for Nurses and Medics**")
            if class_details.get('is_two_day_class', 'No').lower() == 'yes':
                st.write("• **Two-day class format**")
            if class_details.get('is_staff_meeting', False):
                st.write("• **Staff Meeting (LIVE/Virtual options)**")
        
        st.write("")
        st.write("**🕐 Class Times:**")
        times = UIComponents.get_detailed_times(class_details)
        for time_slot in times:
            st.write(f"• {time_slot}")
        
        # Display available dates with full details - now dynamically checks all possible date rows
        st.write("")
        st.write("**📅 Available Dates:**")
        dates = []
        for i in range(1, 15):  # Check rows 1-14 for dates
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                date = class_details[date_key]
                location = class_details.get(f'date_{i}_location', '')
                can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                
                date_info = f"• {date}"
                if location:
                    date_info += f" - Location: {location}"
                if can_work_n_prior:
                    date_info += " 🌙"
                    
                dates.append(date_info)
        
        if dates:
            dates_str = "\n".join(dates)
            st.write(dates_str)
        else:
            st.warning("No dates configured for this class")
        
        # Additional class information
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
        if is_two_day:
            st.write("• This is a two-day class")
        
        st.write("")
        st.write("**Legend:**")
        st.write("🔴 = LIVE option available | 💻 = Virtual only | 🌙 = Night shift prior OK")

    @staticmethod
    def _display_session_option_with_conflict(option, option_key, enrollment_manager, 
                                             selected_staff, class_name, date, conflict_info):
        """Display a single session option with conflict handling"""
        has_conflict = conflict_info[0] if conflict_info else False
        conflict_details = conflict_info[1] if conflict_info else ""
        
        if option['type'] == 'nurse_medic_separate':
            # Multiple sessions with nurse/medic separation
            with st.container():
                st.write(f"**{option['display_time']}**")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**👩‍⚕️ Nurse:**")
                    if option['nurses']:
                        for nurse in option['nurses']:
                            st.write(f"  • {nurse}")
                    else:
                        st.write("  • *Available*")
                    
                    if option['nurse_available']:
                        if UIComponents._handle_enrollment_button(
                            "Enroll as Nurse", f"nurse_{option_key}", 
                            has_conflict, conflict_details,
                            enrollment_manager, selected_staff, class_name, 
                            date, "Nurse", option.get('session_time')
                        ):
                            st.rerun()
                    else:
                        st.write("*Nurse slot filled*")
                
                with col2:
                    st.write("**🚑 Medic:**")
                    if option['medics']:
                        for medic in option['medics']:
                            st.write(f"  • {medic}")
                    else:
                        st.write("  • *Available*")
                    
                    if option['medic_available']:
                        if UIComponents._handle_enrollment_button(
                            "Enroll as Medic", f"medic_{option_key}",
                            has_conflict, conflict_details,
                            enrollment_manager, selected_staff, class_name,
                            date, "Medic", option.get('session_time')
                        ):
                            st.rerun()
                    else:
                        st.write("*Medic slot filled*")
                
                st.markdown("---")
        
        elif option['type'] == 'regular':
            # Multiple regular sessions
            with st.container():
                st.write(f"**{option['display_time']}**")
                st.write(f"**Currently enrolled ({len(option['enrolled'])}):**")
                
                if option['enrolled']:
                    for person in option['enrolled']:
                        st.write(f"  • {person}")
                else:
                    st.write("  • *No one enrolled yet*")
                
                st.write(f"**Available slots:** {option['available_slots']}")
                
                if UIComponents._handle_enrollment_button(
                    f"Enroll in {option['display_time']}", f"enroll_{option_key}",
                    has_conflict, conflict_details,
                    enrollment_manager, selected_staff, class_name,
                    date, "General", option.get('session_time')
                ):
                    st.rerun()
                
                st.markdown("---")
        
        elif option['type'] == 'staff_meeting':
            # Staff meeting with LIVE/Virtual options
            with st.container():
                meeting_icon = "🔴" if option['meeting_type'] == 'LIVE' else "💻"
                st.write(f"**{meeting_icon} {option['meeting_type']} Option**")
                st.write(f"**Currently enrolled ({len(option['enrolled'])}):**")
                
                if option['enrolled']:
                    for person in option['enrolled']:
                        st.write(f"  • {person}")
                else:
                    st.write("  • *No one enrolled yet*")
                
                st.write(f"**Available slots:** {option['available_slots']}")
                
                if option['meeting_type'] == 'LIVE':
                    st.info("🔴 **LIVE Option** - This will count toward your LIVE meeting requirement")
                
                if UIComponents._handle_enrollment_button(
                    f"Enroll in {option['meeting_type']} Option", f"enroll_{option_key}",
                    has_conflict, conflict_details,
                    enrollment_manager, selected_staff, class_name,
                    date, "General", None, option['meeting_type']
                ):
                    st.rerun()
                
                st.markdown("---")
        
        elif option['type'] in ['nurse_medic_separate_single', 'regular_single']:
            # Handle single session types similarly
            UIComponents._display_single_session_option(
                option, option_key, enrollment_manager, selected_staff,
                class_name, date, has_conflict, conflict_details
            )

    @staticmethod
    def _display_single_session_option(option, option_key, enrollment_manager, selected_staff,
                                      class_name, date, has_conflict, conflict_details):
        """Display single session enrollment options"""
        if option['type'] == 'nurse_medic_separate_single':
            with st.container():
                st.write("**Current Enrollments:**")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**👩‍⚕️ Nurses:**")
                    if option['nurses']:
                        for nurse in option['nurses']:
                            st.write(f"  • {nurse}")
                    else:
                        st.write("  • *Available*")
                    
                    if option['nurse_available']:
                        if UIComponents._handle_enrollment_button(
                            "Enroll as Nurse", f"nurse_{option_key}",
                            has_conflict, conflict_details,
                            enrollment_manager, selected_staff, class_name,
                            date, "Nurse"
                        ):
                            st.rerun()
                    else:
                        st.write("*Nurse slot filled*")
                
                with col2:
                    st.write("**🚑 Medics:**")
                    if option['medics']:
                        for medic in option['medics']:
                            st.write(f"  • {medic}")
                    else:
                        st.write("  • *Available*")
                    
                    if option['medic_available']:
                        if UIComponents._handle_enrollment_button(
                            "Enroll as Medic", f"medic_{option_key}",
                            has_conflict, conflict_details,
                            enrollment_manager, selected_staff, class_name,
                            date, "Medic"
                        ):
                            st.rerun()
                    else:
                        st.write("*Medic slot filled*")
                
                st.markdown("---")
        
        elif option['type'] == 'regular_single':
            with st.container():
                st.write("**Currently enrolled:**")
                
                if option['enrolled']:
                    for person in option['enrolled']:
                        st.write(f"  • {person}")
                else:
                    st.write("  • *No one enrolled yet*")
                
                st.write(f"**Available slots:** {option['available_slots']}")
                
                if UIComponents._handle_enrollment_button(
                    f"Enroll in {class_name}", f"enroll_{option_key}",
                    has_conflict, conflict_details,
                    enrollment_manager, selected_staff, class_name,
                    date, "General"
                ):
                    st.rerun()

    @staticmethod
    def display_session_enrollment_options(enrollment_manager, class_name, available_dates, selected_staff):
        """Wrapper for backward compatibility - redirects to track-aware version"""
        # Check if track manager is available
        track_manager = enrollment_manager.track_manager if hasattr(enrollment_manager, 'track_manager') else None
        
        if track_manager:
            return UIComponents.display_session_enrollment_options_with_tracks(
                enrollment_manager, class_name, available_dates, selected_staff, track_manager
            )
        else:
            # Fall back to original implementation
            return UIComponents._display_session_enrollment_options_original(
                enrollment_manager, class_name, available_dates, selected_staff
            )

    @staticmethod
    def _display_session_enrollment_options_original(enrollment_manager, class_name, available_dates, selected_staff):
        """Original implementation without track conflict checking"""
        # Simple fallback implementation
        enrolled_sessions = []
        
        for date in available_dates:
            st.subheader(f"📅 {date}")
            
            session_options = enrollment_manager.get_available_session_options(class_name, date)
            
            if not session_options:
                st.warning(f"No available slots for {date}")
                continue
            
            for idx, option in enumerate(session_options):
                option_key = f"{class_name}_{date}_{idx}"
                
                # Display without conflict checking
                UIComponents._display_session_option_with_conflict(
                    option, option_key, enrollment_manager, selected_staff, 
                    class_name, date, None  # No conflict info
                )
            
            st.markdown("---")
        
        return enrolled_sessions
    
    # ... existing methods stay the same ...
    
    @staticmethod
    def _handle_enrollment_button(button_label, button_key, has_conflict, conflict_details,
                            enrollment_manager, staff_name, class_name, date,
                            role="General", session_time=None, meeting_type=None):
        """Handle enrollment button with conflict override dialog and duplicate checking"""
        
        # Check if we're in the middle of handling a duplicate for this button
        duplicate_dialog_key = f"duplicate_dialog_{button_key}"
        duplicate_data_key = f"duplicate_data_{button_key}"
        
        # If we have stored duplicate data, show the dialog
        if duplicate_dialog_key in st.session_state and st.session_state[duplicate_dialog_key]:
            existing_enrollments = st.session_state.get(duplicate_data_key, [])
            
            result = UIComponents._show_duplicate_enrollment_dialog(
                button_key, existing_enrollments, enrollment_manager, staff_name,
                class_name, date, role, meeting_type, session_time
            )
            
            # If dialog completed successfully, clean up and return
            if result:
                if duplicate_dialog_key in st.session_state:
                    del st.session_state[duplicate_dialog_key]
                if duplicate_data_key in st.session_state:
                    del st.session_state[duplicate_data_key]
                return True
            
            # Dialog is still active, don't process normal button
            return False
        
        if has_conflict:
            # Show button with warning color
            col1, col2 = st.columns([3, 2])
            with col1:
                st.warning(f"⚠️ Enrollment blocked: {conflict_details}")
            with col2:
                if st.button("Override", key=f"override_{button_key}"):
                    st.session_state[f"show_override_{button_key}"] = True
            
            # Show override dialog if triggered
            if st.session_state.get(f"show_override_{button_key}", False):
                with st.container():
                    st.error("**⚠️ Schedule Conflict Override**")
                    st.write(f"**Conflict:** {conflict_details}")
                    st.write("By proceeding, you acknowledge that:")
                    st.write("• You are responsible for arranging a shift swap to attend this class")
                    st.write("• You should discuss any extenuating circumstances with your manager")
                    
                    acknowledge = st.checkbox(
                        "I acknowledge and will arrange for a schedule swap",
                        key=f"ack_{button_key}"
                    )
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Confirm Override", key=f"confirm_{button_key}", disabled=not acknowledge):
                            result, data = enrollment_manager.enroll_staff(
                                staff_name, class_name, date, role,
                                meeting_type, session_time, override_conflict=True
                            )
                            
                            if result == "duplicate_found":
                                # Store duplicate data in session state
                                st.session_state[duplicate_dialog_key] = True
                                st.session_state[duplicate_data_key] = data
                                st.rerun()
                            elif result:
                                st.success("Enrolled with conflict override!")
                                del st.session_state[f"show_override_{button_key}"]
                                return True
                            else:
                                st.error(f"Enrollment failed: {data}")
                    
                    with col2:
                        if st.button("Cancel", key=f"cancel_{button_key}"):
                            del st.session_state[f"show_override_{button_key}"]
            
            return False
        else:
            # Normal enrollment without conflict
            if st.button(button_label, key=button_key):
                result, data = enrollment_manager.enroll_staff(
                    staff_name, class_name, date, role,
                    meeting_type, session_time, override_conflict=False
                )
                
                if result == "duplicate_found":
                    # Store duplicate data in session state and trigger dialog
                    st.session_state[duplicate_dialog_key] = True
                    st.session_state[duplicate_data_key] = data
                    st.rerun()  # Refresh to show dialog
                elif result:
                    st.success("Successfully enrolled!")
                    return True
                else:
                    st.error(f"Enrollment failed: {data}")
            return False
        
    @staticmethod
    def _show_duplicate_enrollment_dialog(button_key, existing_enrollments, enrollment_manager, 
                                        staff_name, class_name, date, role, meeting_type, 
                                        session_time, override_conflict=False):
        """Show dialog for handling duplicate enrollment"""
        
        duplicate_dialog_key = f"duplicate_dialog_{button_key}"
        duplicate_data_key = f"duplicate_data_{button_key}"
        
        with st.container():
            st.warning("**⚠️ Already Enrolled in This Class**")
            st.write("You are already enrolled in the following session(s) for this class:")
            
            for enrollment in existing_enrollments:
                details = enrollment_manager.get_enrollment_details_for_display(enrollment)
                st.info(f"• {details}")
            
            st.write("**Would you like to:**")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("Keep Current Enrollment", key=f"keep_{button_key}"):
                    st.info("No changes made. Your current enrollment remains active.")
                    # Clean up session state
                    if duplicate_dialog_key in st.session_state:
                        del st.session_state[duplicate_dialog_key]
                    if duplicate_data_key in st.session_state:
                        del st.session_state[duplicate_data_key]
                    return False
            
            with col2:
                if st.button("Replace with New Session", key=f"replace_{button_key}"):
                    # Handle replacement logic immediately
                    if len(existing_enrollments) == 1:
                        existing_id = existing_enrollments[0]['id']
                        
                        try:
                            success, message = enrollment_manager.enroll_staff_with_replacement(
                                staff_name, class_name, date, role, meeting_type, 
                                session_time, override_conflict, existing_id
                            )
                            
                            if success:
                                st.success(f"Successfully switched sessions: {message}")
                                # Clean up session state
                                if duplicate_dialog_key in st.session_state:
                                    del st.session_state[duplicate_dialog_key]
                                if duplicate_data_key in st.session_state:
                                    del st.session_state[duplicate_data_key]
                                # Force page refresh to update UI
                                import time
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(f"Failed to switch sessions: {message}")
                        
                        except Exception as e:
                            st.error(f"Error during replacement: {str(e)}")
                    
                    else:
                        # Multiple enrollments - show selection UI
                        st.write("Choose which enrollment to replace:")
                        for i, enrollment in enumerate(existing_enrollments):
                            details = enrollment_manager.get_enrollment_details_for_display(enrollment)
                            if st.button(f"Replace: {details}", key=f"replace_specific_{button_key}_{i}"):
                                try:
                                    success, message = enrollment_manager.enroll_staff_with_replacement(
                                        staff_name, class_name, date, role, meeting_type,
                                        session_time, override_conflict, enrollment['id']
                                    )
                                    
                                    if success:
                                        st.success(message)
                                        # Clean up session state
                                        if duplicate_dialog_key in st.session_state:
                                            del st.session_state[duplicate_dialog_key]
                                        if duplicate_data_key in st.session_state:
                                            del st.session_state[duplicate_data_key]
                                        st.rerun()
                                    else:
                                        st.error(f"Failed to switch sessions: {message}")
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
            
            with col3:
                if st.button("Cancel", key=f"cancel_duplicate_{button_key}"):
                    # Clean up session state
                    if duplicate_dialog_key in st.session_state:
                        del st.session_state[duplicate_dialog_key]
                    if duplicate_data_key in st.session_state:
                        del st.session_state[duplicate_data_key]
                    return False
        
        return False