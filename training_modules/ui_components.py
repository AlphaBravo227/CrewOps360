# training_modules/ui_components.py - Core UI Components
import streamlit as st
from datetime import datetime, timedelta

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
        
        # Check if it's a two-day class
        is_two_day = UIComponents._is_two_day_class(enrollment_manager, class_name)
        
        if is_staff_meeting:
            # For staff meetings, show if LIVE or Virtual
            meeting_types = set([e.get('meeting_type', 'Virtual') for e in class_enrollments])
            if 'LIVE' in meeting_types:
                status = "✅ Enrolled (LIVE)"
            else:
                status = "✅ Enrolled (Virtual)"
        elif is_two_day:
            # For two-day classes, show how many days enrolled
            unique_dates = set([e['class_date'] for e in class_enrollments])
            if len(unique_dates) >= 2:
                status = "✅ Enrolled (2-Day Class)"
            else:
                status = "⚠️ Partially Enrolled (2-Day Class)"
        else:
            # For all other classes, just show enrolled
            status = "✅ Enrolled"
        
        # Add conflict indicator if applicable
        if has_conflict_override:
            status += " ⚠️"
        
        return status

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
    def display_enrollment_row(enrollment, excel_handler, enrollment_manager):
        """Display a single enrollment row with conflict indicator"""
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 1])
        
        with col1:
            class_name = enrollment['class_name']
            display_name = f"**{class_name}**"
            
            # Check if this is part of a two-day class
            is_two_day = UIComponents._is_two_day_class(enrollment_manager, class_name)
            if is_two_day:
                # Check if user has both days enrolled
                staff_name = enrollment['staff_name']
                all_enrollments = enrollment_manager.get_staff_enrollments(staff_name)
                class_enrollments = [e for e in all_enrollments if e['class_name'] == class_name]
                enrolled_dates = set([e['class_date'] for e in class_enrollments])
                
                if len(enrolled_dates) >= 2:
                    display_name += " 📅 (2-Day Complete)"
                else:
                    display_name += " ⚠️ (2-Day Partial)"
            
            # Add meeting type indicator for staff meetings
            elif excel_handler.is_staff_meeting(class_name):
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
            # Create unique button key using multiple identifiers
            staff_name = enrollment.get('staff_name', 'unknown')
            class_name = enrollment.get('class_name', 'unknown')
            class_date = enrollment.get('class_date', 'unknown')
            meeting_type = enrollment.get('meeting_type', '')
            session_time = enrollment.get('session_time', '')
            enrollment_id = enrollment.get('id', 'no_id')
            
            # Create a comprehensive unique key
            unique_key = f"cancel_{staff_name}_{class_name}_{class_date}_{meeting_type}_{session_time}_{enrollment_id}"
            # Clean the key to remove spaces and special characters that might cause issues
            unique_key = unique_key.replace(' ', '_').replace('/', '_').replace(':', '_').replace('-', '_').replace(',', '_')
            
            # For two-day classes, show special cancel text
            is_two_day = UIComponents._is_two_day_class(enrollment_manager, class_name)
            cancel_text = "Cancel Both Days" if is_two_day else "Cancel"
            
            return st.button(cancel_text, key=unique_key)

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
    def display_enrollment_metrics_with_sm(assigned_classes, enrolled_classes, enrollment_manager, staff_name, excel_handler):
        """Display enrollment metrics including enhanced Staff Meeting tracking"""
        
        # Standard metrics
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Assigned Classes", len(assigned_classes))
        with col2:
            st.metric("Classes Enrolled", len(enrolled_classes))
        with col3:
            st.metric("Classes Remaining", len(assigned_classes) - len(enrolled_classes))
        
        # Import and use Staff Meeting Progress component
        from .staff_meeting_components import StaffMeetingComponents
        StaffMeetingComponents.display_staff_meeting_progress(enrollment_manager, staff_name, excel_handler)