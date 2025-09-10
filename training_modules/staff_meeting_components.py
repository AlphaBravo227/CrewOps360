# training_modules/staff_meeting_components.py - Staff Meeting Progress & Dialog Components
import streamlit as st

class StaffMeetingComponents:
    
    @staticmethod
    def display_staff_meeting_progress(enrollment_manager, staff_name, excel_handler):
        """Display comprehensive Staff Meeting progress for a staff member"""
        
        # Check if staff has any SM classes assigned
        assigned_classes = excel_handler.get_assigned_classes(staff_name)
        has_staff_meetings = any(excel_handler.is_staff_meeting(cls) for cls in assigned_classes)
        
        if not has_staff_meetings:
            return  # Don't show if no SM classes assigned
        
        # Get progress data
        progress = enrollment_manager.get_staff_meeting_progress(staff_name)
        
        # Create progress display
        st.markdown("### 📋 Staff Meeting Progress")
        
        # Main metrics row
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_color = "normal" if not progress['total_complete'] else "inverse"
            st.metric(
                "Total Sessions", 
                f"{progress['total_enrolled']}/{progress['total_required']}",
                delta=f"-{progress['total_remaining']} remaining" if progress['total_remaining'] > 0 else "Complete!",
                delta_color=total_color
            )
        
        with col2:
            live_color = "normal" if not progress['live_complete'] else "inverse"
            st.metric(
                "LIVE Sessions", 
                f"{progress['live_enrolled']}/{progress['live_required']}",
                delta=f"-{progress['live_remaining']} remaining" if progress['live_remaining'] > 0 else "Complete!",
                delta_color=live_color
            )
        
        with col3:
            st.metric(
                "Virtual Sessions", 
                progress['virtual_enrolled'],
                delta="No limit" if progress['virtual_enrolled'] > 0 else None
            )
        
        with col4:
            if progress['all_requirements_met']:
                st.success("🎉 All Requirements Met!")
            elif progress['total_complete']:
                st.warning(f"⚠️ Need {progress['live_remaining']} more LIVE")
            elif progress['live_complete']:
                st.warning(f"⚠️ Need {progress['total_remaining']} more sessions")
            else:
                st.error(f"⚠️ Need {progress['total_remaining']} total, {progress['live_remaining']} LIVE")
        
        # Progress bar
        total_progress = min(100, (progress['total_enrolled'] / progress['total_required']) * 100)
        live_progress = min(100, (progress['live_enrolled'] / progress['live_required']) * 100)
        
        st.markdown("**Overall Progress:**")
        progress_col1, progress_col2 = st.columns(2)
        
        with progress_col1:
            st.markdown(f"**Total Sessions:** {total_progress:.0f}%")
            st.progress(total_progress / 100)
        
        with progress_col2:
            st.markdown(f"**LIVE Requirement:** {live_progress:.0f}%")
            st.progress(live_progress / 100)
        
        # Show enrolled sessions summary
        if progress['total_enrolled'] > 0:
            sm_enrollments = enrollment_manager.get_staff_meeting_enrollments(staff_name)
            
            with st.expander(f"📅 View All {progress['total_enrolled']} Enrolled Sessions"):
                for enrollment in sm_enrollments:
                    meeting_icon = "🔴" if enrollment.get('meeting_type') == 'LIVE' else "💻"
                    class_name = enrollment['class_name']
                    class_date = enrollment['class_date']
                    meeting_type = enrollment.get('meeting_type', 'Virtual')
                    
                    st.write(f"{meeting_icon} **{class_name}** - {class_date} ({meeting_type})")
        
        st.markdown("---")


class EnrollmentDialogComponents:
    
    @staticmethod
    def show_duplicate_enrollment_dialog(button_key, existing_enrollments, enrollment_manager, 
                                        staff_name, class_name, date, role, meeting_type, 
                                        session_time, override_conflict=False):
        """Show dialog for handling duplicate enrollment - UPDATED for two-day classes"""
        
        duplicate_dialog_key = f"duplicate_dialog_{button_key}"
        duplicate_data_key = f"duplicate_data_{button_key}"
        
        # Import the helper functions
        from .ui_components import UIComponents
        is_two_day = UIComponents._is_two_day_class(enrollment_manager, class_name)
        
        with st.container():
            warning_text = "**⚠️ Already Enrolled in This Two-Day Class**" if is_two_day else "**⚠️ Already Enrolled in This Class**"
            st.warning(warning_text)
            
            display_text = "You are already enrolled in the following session(s) for this class:"
            if is_two_day:
                display_text = "You are already enrolled in this two-day class for the following session(s):"
            
            st.write(display_text)
            
            for enrollment in existing_enrollments:
                details = enrollment_manager.get_enrollment_details_for_display(enrollment)
                st.info(f"• {details}")
            
            st.write("**Would you like to:**")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("Keep Current Enrollment", key=f"keep_{button_key}"):
                    keep_text = "No changes made. Your current enrollment remains active."
                    if is_two_day:
                        keep_text = "No changes made. Your current two-day enrollment remains active."
                    st.info(keep_text)
                    # Clean up session state
                    if duplicate_dialog_key in st.session_state:
                        del st.session_state[duplicate_dialog_key]
                    if duplicate_data_key in st.session_state:
                        del st.session_state[duplicate_data_key]
                    return False
            
            with col2:
                replace_text = "Replace with New Session" if not is_two_day else "Replace with New Two-Day Session"
                if st.button(replace_text, key=f"replace_{button_key}"):
                    # Handle replacement logic immediately
                    if len(existing_enrollments) == 1:
                        existing_id = existing_enrollments[0]['id']
                        
                        try:
                            success, message = enrollment_manager.enroll_staff_with_replacement(
                                staff_name, class_name, date, role, meeting_type, 
                                session_time, override_conflict, existing_id
                            )
                            
                            if success:
                                success_text = f"Successfully switched sessions: {message}"
                                if is_two_day:
                                    success_text = f"Successfully switched to new two-day session: {message}"
                                st.success(success_text)
                                # Clean up session state
                                if duplicate_dialog_key in st.session_state:
                                    del st.session_state[duplicate_dialog_key]
                                if duplicate_data_key in st.session_state:
                                    del st.session_state[duplicate_data_key]
                                # Brief pause then refresh
                                import time
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.error(f"Failed to switch sessions: {message}")
                        
                        except Exception as e:
                            st.error(f"Error during replacement: {str(e)}")
                    
                    else:
                        # Multiple enrollments - show selection UI
                        selection_text = "Choose which enrollment to replace:"
                        if is_two_day:
                            selection_text = "Choose which two-day enrollment to replace:"
                        st.write(selection_text)
                        
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
                                        # Brief pause then refresh
                                        import time
                                        time.sleep(1.5)
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


# Legacy compatibility functions
class UIComponentsCompat:
    """Compatibility layer for existing imports"""
    
    @staticmethod
    def display_enrollment_status():
        """Legacy method - no longer needed since we show success messages inline"""
        pass