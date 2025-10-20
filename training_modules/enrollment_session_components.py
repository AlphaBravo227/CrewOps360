# training_modules/enrollment_session_components.py - Enrollment Session Handling Components
import streamlit as st
from datetime import datetime, timedelta
from .staff_meeting_components import EnrollmentDialogComponents

class EnrollmentSessionComponents:
    
    @staticmethod
    def display_session_enrollment_options_with_tracks(enrollment_manager, class_name, available_dates, 
                                                       selected_staff, track_manager):
        """Display session enrollment options with track conflict information - UPDATED for two-day classes"""
        
        # Check if class has no available dates
        if not available_dates:
            # Check if the class exists but has no data configured
            class_details = enrollment_manager.excel.get_class_details(class_name)
            
            # Check if this returns default values (indicating missing sheet/data)
            is_missing_data = (not class_details or 
                             class_details.get('class_name') == class_name and 
                             not any(class_details.get(f'date_{i}') for i in range(1, 15)))
            
            if is_missing_data:
                st.error("📅 **Class data not configured**")
                st.info("This class appears in your assignment list but does not have a corresponding configuration sheet with scheduled dates. Please contact the training administrator to have dates added for this class.")
            else:
                st.warning("No available dates found for this class.")
            return []
        
        enrolled_sessions = []
        
        # Get class details to access location information and check if two-day
        class_details = enrollment_manager.excel.get_class_details(class_name)
        is_two_day = EnrollmentSessionComponents._is_two_day_class(enrollment_manager, class_name)
        
        # Get current user's enrollments for this class to show their status
        user_enrollments = enrollment_manager.get_staff_enrollments(selected_staff)
        user_class_enrollments = [e for e in user_enrollments if e['class_name'] == class_name]
        
        # For two-day classes, show combined conflict information
        if is_two_day:
            st.info("📅 **Two-Day Class**: Enrollment covers consecutive days. You only need to enroll once for both days.")
        
        # Iterate through available dates and show enrollment options
        for date in available_dates:
            # For two-day classes, show the expanded date range
            if is_two_day:
                both_days = EnrollmentSessionComponents._get_two_day_dates(date)
                if len(both_days) == 2:
                    st.subheader(f"📅 {both_days[0]} - {both_days[1]} (2-Day Class)")
                else:
                    st.subheader(f"📅 {date} (2-Day Class)")
            else:
                st.subheader(f"📅 {date}")
            
            # Show location information if available
            if class_details:
                location = None
                for i in range(1, 15):  # Check rows 1-14 for dates
                    date_key = f'date_{i}'
                    location_key = f'date_{i}_location'
                    
                    if date_key in class_details and class_details[date_key] == date:
                        location = class_details.get(location_key, '')
                        break
                
                if location and location.strip():
                    st.write(f"### 📍 Location: {location}")
                else:
                    st.write(f"### 📍 Location: Not specified")
            
            # Check for track conflicts - for two-day classes, check both days
            conflict_info = None
            if track_manager and track_manager.has_track_data(selected_staff):
                if is_two_day:
                    # Check conflicts for both days and combine them
                    both_days = EnrollmentSessionComponents._get_two_day_dates(date)
                    combined_conflicts = []
                    
                    for i, day in enumerate(both_days):
                        has_conflict, conflict_details = enrollment_manager.check_enrollment_conflict(
                            selected_staff, class_name, day
                        )
                        if has_conflict:
                            day_label = f"Day {i+1} ({day})"
                            combined_conflicts.append(f"{day_label}: {conflict_details}")
                    
                    if combined_conflicts:
                        combined_message = "; ".join(combined_conflicts)
                        conflict_info = (True, combined_message)
                    else:
                        conflict_info = (False, "No conflicts for either day")
                else:
                    # Single day conflict check
                    has_conflict, conflict_details = enrollment_manager.check_enrollment_conflict(
                        selected_staff, class_name, date
                    )
                    conflict_info = (has_conflict, conflict_details)
            
            # Get session options for this date
            session_options = enrollment_manager.get_available_session_options(class_name, date)
            
            if not session_options:
                st.warning(f"No available slots for {date}")
                continue
            
            # Add two-day indicator to options
            for option in session_options:
                option['is_two_day'] = is_two_day
            
            # Display session options with conflict handling
            for idx, option in enumerate(session_options):
                option_key = f"{class_name}_{date}_{idx}"
                
                EnrollmentSessionComponents._display_session_option_with_conflict(
                    option, option_key, enrollment_manager, selected_staff, 
                    class_name, date, conflict_info, user_class_enrollments
                )
            
            st.markdown("---")
        
        return enrolled_sessions

    @staticmethod
    def _display_session_option_with_conflict(option, option_key, enrollment_manager, 
                                            selected_staff, class_name, date, conflict_info, user_enrollments):
        """Display a single session option with conflict handling - UPDATED for weekly limits"""
        has_conflict = conflict_info[0] if conflict_info else False
        conflict_details = conflict_info[1] if conflict_info else ""
        
        # Check if user is enrolled in this specific session
        user_enrolled_in_session = EnrollmentSessionComponents._is_user_enrolled_in_session(
            user_enrollments, date, option
        )
        
        # NEW: Check weekly enrollment limit before displaying enrollment options
        weekly_limit_blocked = False
        weekly_limit_message = ""
        
        if not user_enrolled_in_session:
            # Only check weekly limits if they're not already enrolled in this session
            can_enroll, limit_error, existing_class = enrollment_manager._check_weekly_enrollment_limit(selected_staff, date)
            if not can_enroll:
                weekly_limit_blocked = True
                weekly_limit_message = limit_error
        
        # Check if this is a two-day class
        is_two_day = option.get('is_two_day', False)
        
        if option['type'] == 'nurse_medic_separate':
            # Multiple sessions with nurse/medic separation
            with st.container():
                if is_two_day:
                    st.write(f"**{option['display_time']} - Two-Day Class**")
                else:
                    st.write(f"**{option['display_time']}**")
                
                # Show weekly limit warning if applicable
                if weekly_limit_blocked:
                    st.warning(f"⚠️ {weekly_limit_message}")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**👩‍⚕️ Nurses:**")
                    EnrollmentSessionComponents._display_enrolled_participants(option['nurses'], selected_staff, "Nurse", user_enrolled_in_session)
                    
                    if option['nurse_available'] and not (user_enrolled_in_session and user_enrolled_in_session.get('role') == 'Nurse'):
                        if not weekly_limit_blocked:
                            button_text = "Enroll as Nurse (2-Day)" if is_two_day else "Enroll as Nurse"
                            if EnrollmentSessionComponents._handle_enrollment_button(
                                button_text, f"nurse_{option_key}",
                                has_conflict, conflict_details,
                                enrollment_manager, selected_staff, class_name,
                                date, "Nurse", option.get('session_time')
                            ):
                                return  # Will trigger rerun
                        # If weekly limit blocked, don't show button at all
                    elif user_enrolled_in_session and user_enrolled_in_session.get('role') == 'Nurse':
                        cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
                        if st.button(cancel_text, key=f"cancel_nurse_{option_key}"):
                            if enrollment_manager.cancel_enrollment(user_enrolled_in_session['id']):
                                st.success("Enrollment cancelled!")
                                st.rerun()
                    else:
                        st.write("*Nurse slot filled*")
                
                with col2:
                    st.write("**🚑 Medics:**")
                    EnrollmentSessionComponents._display_enrolled_participants(option['medics'], selected_staff, "Medic", user_enrolled_in_session)
                    
                    if option['medic_available'] and not (user_enrolled_in_session and user_enrolled_in_session.get('role') == 'Medic'):
                        if not weekly_limit_blocked:
                            button_text = "Enroll as Medic (2-Day)" if is_two_day else "Enroll as Medic"
                            if EnrollmentSessionComponents._handle_enrollment_button(
                                button_text, f"medic_{option_key}",
                                has_conflict, conflict_details,
                                enrollment_manager, selected_staff, class_name,
                                date, "Medic", option.get('session_time')
                            ):
                                return  # Will trigger rerun
                        # If weekly limit blocked, don't show button at all
                    elif user_enrolled_in_session and user_enrolled_in_session.get('role') == 'Medic':
                        cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
                        if st.button(cancel_text, key=f"cancel_medic_{option_key}"):
                            if enrollment_manager.cancel_enrollment(user_enrolled_in_session['id']):
                                st.success("Enrollment cancelled!")
                                st.rerun()
                    else:
                        st.write("*Medic slot filled*")
                
                st.markdown("---")        

        elif option['type'] == 'regular':
            # Multiple regular sessions
            with st.container():
                display_time = option['display_time']
                if is_two_day and "2-Day" not in display_time:
                    display_time += " - Two-Day Class"
                
                st.write(f"**{display_time}**")
                
                # Show weekly limit warning if applicable
                if weekly_limit_blocked:
                    st.warning(f"⚠️ {weekly_limit_message}")
                
                st.write(f"**Currently enrolled ({len(option['enrolled'])}):**")
                
                EnrollmentSessionComponents._display_enrolled_participants(option['enrolled'], selected_staff, None, user_enrolled_in_session)
                
                st.write(f"**Available slots:** {option['available_slots']}")
                
                if not user_enrolled_in_session:
                    if not weekly_limit_blocked:
                        button_text = f"Enroll in {option['display_time']}" + (" (2-Day)" if is_two_day else "")
                        if EnrollmentSessionComponents._handle_enrollment_button(
                            button_text, f"enroll_{option_key}",
                            has_conflict, conflict_details,
                            enrollment_manager, selected_staff, class_name,
                            date, "General", option.get('session_time')
                        ):
                            return  # Will trigger rerun
                    # If weekly limit blocked, don't show button at all
                else:
                    cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
                    if st.button(cancel_text, key=f"cancel_{option_key}"):
                        if enrollment_manager.cancel_enrollment(user_enrolled_in_session['id']):
                            st.success("Enrollment cancelled!")
                            st.rerun()
                
                st.markdown("---")
        
        elif option['type'] == 'staff_meeting':
            # Staff meeting with LIVE/Virtual options
            with st.container():
                meeting_icon = "🔴" if option['meeting_type'] == 'LIVE' else "💻"
                meeting_display = f"{meeting_icon} {option['meeting_type']} Option"
                if is_two_day:
                    meeting_display += " - Two-Day Class"
                
                st.write(f"**{meeting_display}**")
                
                # Show weekly limit warning if applicable
                if weekly_limit_blocked:
                    st.warning(f"⚠️ {weekly_limit_message}")
                
                # Highlight user's enrolled section if they're in this meeting type
                if user_enrolled_in_session:
                    st.markdown("""
                    <div style="background-color: rgba(0, 255, 0, 0.1); padding: 10px; border-radius: 5px; border-left: 4px solid #4CAF50;">
                        <strong>✅ You are enrolled in this option</strong>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.write(f"**Currently enrolled ({len(option['enrolled'])}):**")
                
                EnrollmentSessionComponents._display_enrolled_participants(option['enrolled'], selected_staff, None, user_enrolled_in_session)
                
                st.write(f"**Available slots:** {option['available_slots']}")
                
                if option['meeting_type'] == 'LIVE':
                    st.info("🔴 **LIVE Option** - This will count toward your LIVE meeting requirement")
                
                if not user_enrolled_in_session:
                    if not weekly_limit_blocked:
                        button_text = f"Enroll in {option['meeting_type']} Option" + (" (2-Day)" if is_two_day else "")
                        if EnrollmentSessionComponents._handle_enrollment_button(
                            button_text, f"enroll_{option_key}",
                            has_conflict, conflict_details,
                            enrollment_manager, selected_staff, class_name,
                            date, "General", None, option['meeting_type']
                        ):
                            return  # Will trigger rerun
                    # If weekly limit blocked, don't show button at all
                else:
                    cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
                    if st.button(cancel_text, key=f"cancel_{option_key}"):
                        if enrollment_manager.cancel_enrollment(user_enrolled_in_session['id']):
                            st.success("Enrollment cancelled!")
                            st.rerun()
                
                st.markdown("---")
        
        elif option['type'] in ['nurse_medic_separate_single', 'regular_single']:
            # Handle single session types with weekly limit support
            EnrollmentSessionComponents._display_single_session_option(
                option, option_key, enrollment_manager, selected_staff,
                class_name, date, has_conflict, conflict_details, user_enrolled_in_session,
                weekly_limit_blocked, weekly_limit_message
            )

    @staticmethod
    def _display_single_session_option(option, option_key, enrollment_manager, selected_staff,
                                     class_name, date, has_conflict, conflict_details, user_enrollment,
                                     weekly_limit_blocked, weekly_limit_message):
        """Display single session enrollment options - UPDATED with weekly limit support"""
        
        is_two_day = option.get('is_two_day', False)
        
        if option['type'] == 'nurse_medic_separate_single':
            with st.container():
                header_text = "**Current Enrollments:**"
                if is_two_day:
                    header_text = "**Current Enrollments (2-Day Class):**"
                
                st.write(header_text)
                
                # Show weekly limit warning if applicable
                if weekly_limit_blocked:
                    st.warning(f"⚠️ {weekly_limit_message}")
                
                # Highlight if user is enrolled
                if user_enrollment:
                    enrollment_text = "✅ You are enrolled in this class"
                    if is_two_day:
                        enrollment_text += " (both days)"
                    
                    st.markdown(f"""
                    <div style="background-color: rgba(0, 255, 0, 0.1); padding: 10px; border-radius: 5px; border-left: 4px solid #4CAF50;">
                        <strong>{enrollment_text}</strong>
                    </div>
                    """, unsafe_allow_html=True)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**👩‍⚕️ Nurses:**")
                    EnrollmentSessionComponents._display_enrolled_participants(option['nurses'], selected_staff, "Nurse", user_enrollment)
                    
                    if option['nurse_available'] and not (user_enrollment and user_enrollment.get('role') == 'Nurse'):
                        if not weekly_limit_blocked:
                            button_text = "Enroll as Nurse (2-Day)" if is_two_day else "Enroll as Nurse"
                            if EnrollmentSessionComponents._handle_enrollment_button(
                                button_text, f"nurse_{option_key}",
                                has_conflict, conflict_details,
                                enrollment_manager, selected_staff, class_name,
                                date, "Nurse"
                            ):
                                return True
                        # If weekly limit blocked, don't show button at all
                    elif user_enrollment and user_enrollment.get('role') == 'Nurse':
                        cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
                        if st.button(cancel_text, key=f"cancel_nurse_{option_key}"):
                            if enrollment_manager.cancel_enrollment(user_enrollment['id']):
                                st.success("Enrollment cancelled!")
                                st.rerun()
                    else:
                        st.write("*Nurse slot filled*")
                
                with col2:
                    st.write("**🚑 Medics:**")
                    EnrollmentSessionComponents._display_enrolled_participants(option['medics'], selected_staff, "Medic", user_enrollment)
                    
                    if option['medic_available'] and not (user_enrollment and user_enrollment.get('role') == 'Medic'):
                        if not weekly_limit_blocked:
                            button_text = "Enroll as Medic (2-Day)" if is_two_day else "Enroll as Medic"
                            if EnrollmentSessionComponents._handle_enrollment_button(
                                button_text, f"medic_{option_key}",
                                has_conflict, conflict_details,
                                enrollment_manager, selected_staff, class_name,
                                date, "Medic"
                            ):
                                return True
                        # If weekly limit blocked, don't show button at all
                    elif user_enrollment and user_enrollment.get('role') == 'Medic':
                        cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
                        if st.button(cancel_text, key=f"cancel_medic_{option_key}"):
                            if enrollment_manager.cancel_enrollment(user_enrollment['id']):
                                st.success("Enrollment cancelled!")
                                st.rerun()
                    else:
                        st.write("*Medic slot filled*")
                
                st.markdown("---")
        
        elif option['type'] == 'regular_single':
            # Handle regular single session classes
            with st.container():
                header_text = "**Current Enrollments:**"
                if is_two_day:
                    header_text = "**Current Enrollments (2-Day Class):**"
                
                st.write(header_text)
                
                # Show weekly limit warning if applicable
                if weekly_limit_blocked:
                    st.warning(f"⚠️ {weekly_limit_message}")
                
                # Highlight if user is enrolled
                if user_enrollment:
                    enrollment_text = "✅ You are enrolled in this class"
                    if is_two_day:
                        enrollment_text += " (both days)"
                    
                    st.markdown(f"""
                    <div style="background-color: rgba(0, 255, 0, 0.1); padding: 10px; border-radius: 5px; border-left: 4px solid #4CAF50;">
                        <strong>{enrollment_text}</strong>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.write(f"**Currently enrolled ({len(option['enrolled'])}):**")
                EnrollmentSessionComponents._display_enrolled_participants(option['enrolled'], selected_staff, None, user_enrollment)
                
                st.write(f"**Available slots:** {option['available_slots']}")
                
                if not user_enrollment:
                    if not weekly_limit_blocked:
                        button_text = "Enroll in Class"
                        if is_two_day:
                            button_text += " (2-Day)"
                        
                        if EnrollmentSessionComponents._handle_enrollment_button(
                            button_text, f"enroll_{option_key}",
                            has_conflict, conflict_details,
                            enrollment_manager, selected_staff, class_name,
                            date, "General"
                        ):
                            return True
                    # If weekly limit blocked, don't show button at all
                else:
                    cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
                    if st.button(cancel_text, key=f"cancel_{option_key}"):
                        if enrollment_manager.cancel_enrollment(user_enrollment['id']):
                            st.success("Enrollment cancelled!")
                            st.rerun()
                
                st.markdown("---")
        
        return False

    @staticmethod
    def _display_enrolled_participants(participants, selected_staff, role_filter, user_enrollment):
        """Display list of enrolled participants with user highlighted"""
        if not participants and not user_enrollment:
            st.write("  • *No one enrolled yet*")
            return
        
        # Create a set of all participants including the user if enrolled
        all_participants = set(participants)
        if user_enrollment:
            # Check if this matches the role filter (for nurse/medic separate)
            if role_filter is None or user_enrollment.get('role') == role_filter:
                all_participants.add(selected_staff)
        
        if all_participants:
            for participant in sorted(all_participants):
                if participant == selected_staff:
                    st.markdown("  • **You** ✅")
                else:
                    st.write(f"  • {participant}")
        else:
            st.write("  • *No one enrolled yet*")

    @staticmethod
    def _is_user_enrolled_in_session(user_enrollments, date, option):
        """Check if user is enrolled in this specific session and return enrollment details"""
        for enrollment in user_enrollments:
            if enrollment['class_date'] != date:
                continue
            
            # Check based on option type
            if option['type'] == 'staff_meeting':
                if enrollment.get('meeting_type') == option['meeting_type']:
                    return enrollment
            elif option['type'] in ['regular', 'nurse_medic_separate']:
                # For multi-session classes, match by session time
                enrollment_session = enrollment.get('session_time')
                option_session = option.get('session_time')
                if enrollment_session == option_session:
                    return enrollment
            elif option['type'] in ['regular_single', 'nurse_medic_separate_single']:
                # For single sessions, just matching the date is enough since there's only one session
                return enrollment
        
        return None

    @staticmethod
    def _is_two_day_class(enrollment_manager, class_name):
        """Check if a class is a two-day class"""
        class_details = enrollment_manager.excel.get_class_details(class_name)
        return class_details.get('is_two_day_class', 'No').lower() == 'yes'

    @staticmethod
    def _get_two_day_dates(base_date):
        """Get both days for a two-day class"""
        try:
            date_obj = datetime.strptime(base_date, '%m/%d/%Y')
            day_1 = date_obj.strftime('%m/%d/%Y')
            day_2 = (date_obj + timedelta(days=1)).strftime('%m/%d/%Y')
            return [day_1, day_2]
        except ValueError:
            return [base_date]

    @staticmethod
    def _handle_enrollment_button(button_label, button_key, has_conflict, conflict_details,
                            enrollment_manager, staff_name, class_name, date,
                            role="General", session_time=None, meeting_type=None):
        """Handle enrollment button with conflict override dialog - UPDATED for two-day classes"""
        
        # Check if this is a Staff Meeting class
        is_staff_meeting = enrollment_manager.excel.is_staff_meeting(class_name)
        is_two_day = EnrollmentSessionComponents._is_two_day_class(enrollment_manager, class_name)
        
        # Check if we're in the middle of handling a duplicate for this button
        duplicate_dialog_key = f"duplicate_dialog_{button_key}"
        duplicate_data_key = f"duplicate_data_{button_key}"
        
        # Only show duplicate dialog for non-SM classes
        if not is_staff_meeting and duplicate_dialog_key in st.session_state and st.session_state[duplicate_dialog_key]:
            existing_enrollments = st.session_state.get(duplicate_data_key, [])
            
            from .staff_meeting_components import EnrollmentDialogComponents
            result = EnrollmentDialogComponents.show_duplicate_enrollment_dialog(
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
                conflict_message = f"⚠️ Enrollment blocked: {conflict_details}"
                if is_two_day:
                    conflict_message = f"⚠️ Two-day enrollment blocked: {conflict_details}"
                st.warning(conflict_message)
            with col2:
                if st.button("Override", key=f"override_{button_key}"):
                    st.session_state[f"show_override_{button_key}"] = True
                    st.rerun()
            
            # Show override confirmation if triggered
            if st.session_state.get(f"show_override_{button_key}", False):
                override_title = "⚠️ **Conflict Override - Two-Day Class**" if is_two_day else "⚠️ **Conflict Override**"
                st.warning(override_title)
                st.write(f"**Conflict:** {conflict_details}")
                
                if is_two_day:
                    st.write("By proceeding with this two-day class enrollment, you acknowledge that:")
                else:
                    st.write("By proceeding, you acknowledge that:")
                
                st.write("• You are responsible for arranging coverage for your regular duties")
                st.write("• You should coordinate with your supervisor and/or peer schedulers regarding the conflict(s)")
                
                acknowledge = st.checkbox(
                    "I acknowledge and will coordinate coverage as needed",
                    key=f"ack_{button_key}"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    confirm_text = "Confirm Two-Day Enrollment" if is_two_day else "Confirm Enrollment"
                    if st.button(confirm_text, key=f"confirm_{button_key}", 
                            disabled=not acknowledge):
                        EnrollmentSessionComponents._process_enrollment(
                            enrollment_manager, staff_name, class_name, date, role,
                            meeting_type, session_time, True, is_staff_meeting, is_two_day,
                            button_key, duplicate_dialog_key, duplicate_data_key
                        )
                
                with col2:
                    if st.button("Cancel", key=f"cancel_{button_key}"):
                        if f"show_override_{button_key}" in st.session_state:
                            del st.session_state[f"show_override_{button_key}"]
                        st.rerun()
            
            return False
        else:
            # Normal enrollment without conflict
            if st.button(button_label, key=button_key):
                EnrollmentSessionComponents._process_enrollment(
                    enrollment_manager, staff_name, class_name, date, role,
                    meeting_type, session_time, False, is_staff_meeting, is_two_day,
                    button_key, duplicate_dialog_key, duplicate_data_key
                )
            return False

    @staticmethod
    def _process_enrollment(enrollment_manager, staff_name, class_name, date, role,
                          meeting_type, session_time, override_conflict, is_staff_meeting, 
                          is_two_day, button_key, duplicate_dialog_key, duplicate_data_key):
        """Process enrollment with proper error handling"""
        with st.spinner("Processing enrollment..."):
            try:
                result, data = enrollment_manager.enroll_staff(
                    staff_name, class_name, date, role,
                    meeting_type, session_time, override_conflict
                )
                
                if result == "duplicate_found" and not is_staff_meeting:
                    # Only show duplicate dialog for non-SM classes
                    st.session_state[duplicate_dialog_key] = True
                    st.session_state[duplicate_data_key] = data
                    st.rerun()
                elif result:
                    # Show success message
                    if is_staff_meeting and "multiple Staff Meeting" in data:
                        st.success("✅ Successfully enrolled in additional Staff Meeting session!")
                    elif is_two_day:
                        success_msg = "✅ Successfully enrolled in two-day class!"
                        if override_conflict:
                            success_msg += " (with conflict override)"
                        st.success(success_msg)
                    else:
                        success_msg = "✅ Successfully enrolled!"
                        if override_conflict:
                            success_msg = "✅ Successfully enrolled with conflict override!"
                        st.success(success_msg)
                    
                    # Clean up session state
                    if f"show_override_{button_key}" in st.session_state:
                        del st.session_state[f"show_override_{button_key}"]
                    
                    # Brief pause to show success message, then refresh
                    import time
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(f"Enrollment failed: {data}")
            except Exception as e:
                st.error(f"Error during enrollment: {str(e)}")

    # Backward compatibility methods
    @staticmethod
    def display_session_enrollment_options(enrollment_manager, class_name, available_dates, selected_staff):
        """Wrapper for backward compatibility - redirects to track-aware version"""
        # Check if track manager is available
        track_manager = enrollment_manager.track_manager if hasattr(enrollment_manager, 'track_manager') else None
        
        if track_manager:
            return EnrollmentSessionComponents.display_session_enrollment_options_with_tracks(
                enrollment_manager, class_name, available_dates, selected_staff, track_manager
            )
        else:
            # Fall back to original implementation
            return EnrollmentSessionComponents._display_session_enrollment_options_original(
                enrollment_manager, class_name, available_dates, selected_staff
            )

    @staticmethod
    def _display_session_enrollment_options_original(enrollment_manager, class_name, available_dates, selected_staff):
        """Original implementation without track conflict checking"""
        enrolled_sessions = []
        
        for date in available_dates:
            st.subheader(f"📅 {date}")
            
            session_options = enrollment_manager.get_available_session_options(class_name, date)
            
            if not session_options:
                st.warning(f"No available slots for {date}")
                continue
            
            # Get current user's enrollments for this class
            user_enrollments = enrollment_manager.get_staff_enrollments(selected_staff)
            user_class_enrollments = [e for e in user_enrollments if e['class_name'] == class_name]
            
            for idx, option in enumerate(session_options):
                option_key = f"{class_name}_{date}_{idx}"
                
                # Display without conflict checking
                EnrollmentSessionComponents._display_session_option_with_conflict(
                    option, option_key, enrollment_manager, selected_staff, 
                    class_name, date, None, user_class_enrollments  # No conflict info
                )
            
            st.markdown("---")
        
        return enrolled_sessions