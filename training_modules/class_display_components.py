# training_modules/class_display_components.py - Class Information Display Components
import streamlit as st
from datetime import datetime, timedelta

class ClassDisplayComponents:
    
    @staticmethod
    def display_class_info(class_details):
        """Display class information in a formatted way - UPDATED to show two-day indicator"""
        if not class_details:
            st.error("No class details available")
            return
        
        # Check if this is missing class data
        is_missing_data = (not class_details or 
                        not any(class_details.get(f'date_{i}') for i in range(1, 15)))
        
        if is_missing_data:
            st.error("📅 **Class data not configured**")
            st.info("This class appears in the assignment roster but does not have a corresponding configuration sheet with dates and details. Please contact the training administrator to set up the class schedule.")
            return
        
        # Check if this is a two-day class
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
        
        # Display basic class information
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**📚 Class:** {class_details.get('class_name', 'Unknown')}")
            st.write(f"**👥 Max Students:** {class_details.get('students_per_class', '21')}")
            st.write(f"**📅 Sessions per Day:** {class_details.get('classes_per_day', '1')}")
        
        with col2:
            if class_details.get('nurses_medic_separate', 'No').lower() == 'yes':
                st.write("• **Separate slots for Nurses and Medics**")
            if is_two_day:
                st.write("• **🔴 Two-day class format**")
            if class_details.get('is_staff_meeting', False):
                st.write("• **Staff Meeting (LIVE/Virtual options)**")
        
        # Display available dates with two-day expansion
        st.write("**📅 Available Dates:**")
        dates = []
        for i in range(1, 15):  # Check rows 1-14 for dates
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                base_date = class_details[date_key]
                location = class_details.get(f'date_{i}_location', '')
                can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                
                if is_two_day:
                    # Show both days for two-day classes
                    try:
                        date_obj = datetime.strptime(base_date, '%m/%d/%Y')
                        day_1 = date_obj.strftime('%m/%d/%Y')
                        day_2 = (date_obj + timedelta(days=1)).strftime('%m/%d/%Y')
                        
                        date_info = f"• {day_1} - {day_2} (2-Day Class)"
                        if location:
                            date_info += f" - Location: {location}"
                        if can_work_n_prior:
                            date_info += " 🌙"
                    except ValueError:
                        # Fallback if date parsing fails
                        date_info = f"• {base_date} (2-Day Class)"
                        if location:
                            date_info += f" - Location: {location}"
                        if can_work_n_prior:
                            date_info += " 🌙"
                else:
                    # Single day display
                    date_info = f"• {base_date}"
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
        times = ClassDisplayComponents.get_detailed_times(class_details)
        for time_slot in times:
            st.write(f"• {time_slot}")
        
        # Legend
        st.write("")
        st.write("**Legend:** 🌙 = Night shift prior OK")
        if is_two_day:
            st.info("**📅 Two-Day Class:** Enrollment covers consecutive days. You only need to enroll once.")

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