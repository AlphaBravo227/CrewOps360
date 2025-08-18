import streamlit as st
from datetime import datetime

class UIComponents:
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
                st.metric("LIVE Staff Meetings", f"{live_meeting_count}/2")
                if live_meeting_count >= 2:
                    st.success("✅ LIVE meeting requirement met!")
                elif live_meeting_count == 1:
                    st.warning("⚠️ Need 1 more LIVE meeting")
                else:
                    st.error("❗ Need 2 LIVE meetings")
    
    @staticmethod
    def display_class_info(class_details):
        """Display basic class information with location"""
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Class Information:**")
            st.write(f"• Students per class: {class_details.get('students_per_class', 21)}")
            st.write(f"• Classes per day: {class_details.get('classes_per_day', 1)}")
            
            if class_details.get('nurses_medic_separate', 'No').lower() == 'yes':
                st.write("• **Nurses and Medics have separate slots**")
                
        with col2:
            st.write("**Schedule:**")
            is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
            if is_two_day:
                st.write("• This is a two-day class")
            
            # Display class times
            times = UIComponents.get_class_times(class_details)
            if times:
                st.write(f"• Time: {times}")
    
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
    def display_session_enrollment_options_with_tracks(enrollment_manager, class_name, available_dates, 
                                                       selected_staff, track_manager):
        """Display session enrollment options with track conflict information"""
        enrolled_sessions = []
        
        for date in available_dates:
            st.write(f"### 📅 {date}")
            
            # Check for conflicts with this date
            conflict_info = None
            if track_manager and track_manager.has_track_data(selected_staff):
                has_conflict, conflict_details = enrollment_manager.check_enrollment_conflict(
                    selected_staff, class_name, date
                )
                
                # Get shift info for display
                shift = track_manager.get_staff_shift(selected_staff, date)
                shift_desc = track_manager.shift_descriptions.get(shift, 'Off' if shift == '' else shift)
                
                # Display shift and conflict info
                if shift:
                    shift_display = f"**Your shift:** {shift} ({shift_desc})"
                    if has_conflict:
                        st.error(f"{shift_display} - ⚠️ CONFLICT: {conflict_details}")
                    else:
                        st.info(shift_display)
                else:
                    st.success("**Your shift:** Off - Available for training")
                
                conflict_info = (has_conflict, conflict_details)
            
            # Get location for this date
            class_details = enrollment_manager.excel.get_class_details(class_name)
            location = ""
            for i in range(1, 9):
                if class_details.get(f'date_{i}') == date:
                    location = class_details.get(f'date_{i}_location', '')
                    break
            
            if location:
                st.write(f"**Location:** {location}")
            
            # Get available session options for this date
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
                st.write(f"**Currently enrolled ({len(option['enrolled'])}/{21 - option['available_slots']}):**")
                
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
                    st.info("🔴 **LIVE Option Selected** - This will count toward your LIVE meeting requirement")
                
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
    def _handle_enrollment_button(button_label, button_key, has_conflict, conflict_details,
                                 enrollment_manager, staff_name, class_name, date,
                                 role="General", session_time=None, meeting_type=None):
        """Handle enrollment button with conflict override dialog"""
        
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
                    st.write("• You are responsible for arranging a shift swap to attend this class. Alternate coverage will not be solicited or guaranteed")
                    st.write("• You should discuss any extenuating circumstances with your manager to help resolve the conflict")
                    
                    acknowledge = st.checkbox(
                        "I acknowledge and will arrange for a schedule swap",
                        key=f"ack_{button_key}"
                    )
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Confirm Override", key=f"confirm_{button_key}", disabled=not acknowledge):
                            success, message = enrollment_manager.enroll_staff(
                                staff_name, class_name, date, role,
                                meeting_type, session_time, override_conflict=True
                            )
                            if success:
                                st.success("Enrolled with conflict override!")
                                del st.session_state[f"show_override_{button_key}"]
                                return True
                            else:
                                st.error(f"Enrollment failed: {message}")
                    
                    with col2:
                        if st.button("Cancel", key=f"cancel_{button_key}"):
                            del st.session_state[f"show_override_{button_key}"]
            
            return False
        else:
            # Normal enrollment without conflict
            if st.button(button_label, key=button_key):
                success, message = enrollment_manager.enroll_staff(
                    staff_name, class_name, date, role,
                    meeting_type, session_time, override_conflict=False
                )
                if success:
                    st.success("Successfully enrolled!")
                    return True
                else:
                    st.error(f"Enrollment failed: {message}")
            return False
    
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
        # [Original implementation code here - omitted for brevity]
        # This would contain the original display_session_enrollment_options code
        pass
    
    @staticmethod
    def get_class_times(class_details):
        """Format class times for display"""
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
    def display_class_details_full(class_details):
        """Display full class details with location information"""
        st.write("**📅 Available Dates:**")
        dates_found = False
        date_cols = st.columns(4)
        
        for i in range(1, 9):
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                col_idx = (i - 1) % 4
                with date_cols[col_idx]:
                    date_str = class_details[date_key]
                    location = class_details.get(f'date_{i}_location', '')
                    can_work_n = class_details.get(f'date_{i}_can_work_n_prior', False)
                    
                    # Build display string
                    display_str = f"• {date_str}"
                    
                    # Add location if available
                    if location:
                        display_str += f" ({location})"
                    
                    # Add indicators for special conditions
                    if class_details.get('class_name') and 'SM' in class_details['class_name'].upper():
                        has_live_key = f'date_{i}_has_live'
                        if class_details.get(has_live_key, False):
                            display_str += " 🔴"
                        else:
                            display_str += " 💻"
                    
                    if can_work_n:
                        display_str += " 🌙"  # Moon icon for night shift OK
                    
                    st.write(display_str)
                dates_found = True
        
        if not dates_found:
            st.write("No dates scheduled")
        
        st.write("")
        st.write("**⚙️ Class Configuration:**")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"• Max students: {class_details.get('students_per_class', 21)}")
            st.write(f"• Classes per day: {class_details.get('classes_per_day', 1)}")
        
        with col2:
            if class_details.get('nurses_medic_separate', 'No').lower() == 'yes':
                st.write("• **Separate slots for Nurses and Medics**")
            if class_details.get('is_two_day_class', 'No').lower() == 'yes':
                st.write("• **Two-day class format**")
        
        st.write("")
        st.write("**🕐 Class Times:**")
        times = UIComponents.get_detailed_times(class_details)
        for time_slot in times:
            st.write(f"• {time_slot}")
        
        st.write("")
        st.write("**Legend:**")
        st.write("🔴 = LIVE option available | 💻 = Virtual only | 🌙 = Night shift prior OK")
    
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
    def display_enrollment_summary(enrollment_summary, class_details):
        """Display enrollment summary for a class with conflict indicators"""
        st.write("")
        st.write("**📊 Current Enrollment Status:**")
        
        max_students = int(class_details.get('students_per_class', 21))
        nurses_medic_separate = class_details.get('nurses_medic_separate', 'No').lower() == 'yes'
        is_staff_meeting = class_details.get('class_name') and 'SM' in class_details['class_name'].upper()
        classes_per_day = int(class_details.get('classes_per_day', 1))
        
        if enrollment_summary:
            for date, data in enrollment_summary.items():
                with st.container():
                    st.write(f"**📅 {date}**")
                    
                    # Get location for this date
                    location = ""
                    for i in range(1, 9):
                        if class_details.get(f'date_{i}') == date:
                            location = class_details.get(f'date_{i}_location', '')
                            break
                    
                    if location:
                        st.write(f"**Location:** {location}")
                    
                    if classes_per_day > 1 and data.get('sessions'):
                        # Show session-based enrollment
                        for session_time, enrolled_names in data['sessions'].items():
                            st.write(f"  **{session_time}:**")
                            for name in enrolled_names:
                                st.write(f"    • {name}")
                            st.write(f"    Enrolled: {len(enrolled_names)}/{max_students}")
                    
                    elif is_staff_meeting:
                        # Show LIVE vs Virtual breakdown for staff meetings
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.write(f"Total: {data['total']}/{max_students}")
                        with col2:
                            live_count = data['meeting_types'].get('LIVE', 0)
                            st.write(f"🔴 LIVE: {live_count}")
                        with col3:
                            virtual_count = data['meeting_types'].get('Virtual', 0)
                            st.write(f"💻 Virtual: {virtual_count}")
                        with col4:
                            if data.get('conflicts', 0) > 0:
                                st.write(f"⚠️ Conflicts: {data['conflicts']}")
                    
                    elif nurses_medic_separate:
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.write(f"Total: {data['total']}/{max_students}")
                        with col2:
                            nurse_count = data['roles'].get('Nurse', 0)
                            st.write(f"👩‍⚕️ Nurses: {nurse_count}/{max_students//2}")
                        with col3:
                            medic_count = data['roles'].get('Medic', 0)
                            st.write(f"🚑 Medics: {medic_count}/{max_students//2}")
                        with col4:
                            if data.get('conflicts', 0) > 0:
                                st.write(f"⚠️ Conflicts: {data['conflicts']}")
                    else:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"Enrolled: {data['total']}/{max_students}")
                        with col2:
                            if data.get('conflicts', 0) > 0:
                                st.write(f"⚠️ Conflicts: {data['conflicts']}")
                    
                    # Progress bar
                    progress = data['total'] / max_students
                    st.progress(progress)
                    st.markdown("---")
        else:
            st.info("No enrollments yet for this class.")
    
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
                        