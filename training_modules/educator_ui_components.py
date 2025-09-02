# training_modules/educator_ui_components.py
"""
Enhanced UI Components specifically for educator signup functionality
Now shows the names of staff members who have signed up when multiple educators are needed
"""
import streamlit as st
from datetime import datetime

class EducatorUIComponents:
    
    @staticmethod
    def display_educator_opportunities(educator_manager, staff_name):
        """Display available educator opportunities for a staff member"""
        result = educator_manager.get_educator_opportunities_with_status(staff_name)
        
        # Handle both old and new return formats
        if isinstance(result, dict):
            # New format with filtering
            opportunities = result['opportunities']
            excluded_classes = result['excluded_classes']
        else:
            # Old format - just opportunities list, no filtering
            opportunities = result
            excluded_classes = []
        
        # Display excluded classes message if any
        if excluded_classes:
            st.info(
                f"**Classes excluded from educator signup:** You are assigned as a student to: "
                f"{', '.join(excluded_classes)}"
            )
            st.markdown("---")
        
        if not opportunities:
            st.info("No educator opportunities available at this time.")
            return
        
        st.write(f"**📚 Available Educator Opportunities**")
        st.caption("Sign up to be part of the education staff for classes")
        
        for opportunity in opportunities:
            class_name = opportunity['class_name']
            instructor_count = opportunity['instructor_count']
            
            # Create expander for each class
            with st.expander(f"**{class_name}** (Need {instructor_count} educator{'s' if instructor_count != 1 else ''} per date)"):
                
                # Show class details
                class_details = opportunity['class_details']
                EducatorUIComponents._display_class_info_for_educators(class_details)
                
                st.markdown("---")
                st.write("**📅 Available Dates:**")
                
                for date_info in opportunity['date_status']:
                    date = date_info['date']
                    current_signups = date_info['current_signups']
                    max_signups = date_info['max_signups']
                    is_signed_up = date_info['is_signed_up']
                    is_full = date_info['is_full']
                    conflict_info = date_info['conflict_info']
                    
                    # Get the list of educators who have signed up for this date
                    educator_roster = educator_manager.get_class_educator_roster(class_name, date)
                    signed_up_educators = [e['staff_name'] for e in educator_roster if e['status'] == 'active']
                    
                    # Create columns for date display
                    col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                    
                    with col1:
                        st.write(f"**📅 {date}**")
                        
                        # Show conflict info if available
                        if conflict_info:
                            if conflict_info.startswith('ℹ️'):
                                st.info(conflict_info)
                            else:
                                st.warning(f"⚠️ {conflict_info}")
                    
                    with col2:
                        # Show signup status
                        signup_status = f"Signed up: {current_signups}/{max_signups}"
                        if is_full:
                            st.error(f"🔴 {signup_status} (Full)")
                        elif current_signups >= max_signups * 0.8:
                            st.warning(f"🟡 {signup_status}")
                        else:
                            st.success(f"🟢 {signup_status}")
                        
                        # Show the names of educators who have signed up (if multiple educators needed)
                        if max_signups > 1 and signed_up_educators:
                            st.write("**👨‍🏫 Signed up:**")
                            for educator_name in signed_up_educators:
                                if educator_name == staff_name:
                                    st.write(f"• **{educator_name}** (You)")
                                else:
                                    st.write(f"• {educator_name}")
                        elif max_signups > 1 and not signed_up_educators:
                            st.write("**👨‍🏫 Signed up:** *None yet*")
                    
                    with col3:
                        if is_signed_up:
                            st.success("✅ Signed Up")
                        elif is_full:
                            st.error("Full")
                        else:
                            st.write("Available")
                    
                    with col4:
                        button_key = f"educator_{class_name}_{date}_{staff_name}".replace(" ", "_").replace("/", "_")
                        
                        if is_signed_up:
                            # Show cancel button
                            if st.button("Cancel", key=f"cancel_{button_key}"):
                                existing_signup = educator_manager.db.check_existing_educator_signup(
                                    staff_name, class_name, date
                                )
                                if existing_signup and educator_manager.cancel_educator_signup(existing_signup['id']):
                                    st.success("Educator signup cancelled!")
                                    st.rerun()
                                else:
                                    st.error("Error cancelling signup")
                        
                        elif not is_full:
                            # Show signup button with conflict handling
                            if conflict_info and not conflict_info.startswith('ℹ️'):
                                # Real conflict - show override option
                                EducatorUIComponents._handle_educator_signup_with_conflict(
                                    educator_manager, staff_name, class_name, date, 
                                    conflict_info, button_key
                                )
                            else:
                                # No conflict or AT info only - normal signup
                                if st.button("Sign Up", key=f"signup_{button_key}"):
                                    print(f"DEBUG: Educator signup button clicked for {staff_name} -> {class_name} on {date}")
                                    
                                    with st.spinner("Processing educator signup..."):
                                        try:
                                            success, message = educator_manager.signup_as_educator(
                                                staff_name, class_name, date
                                            )
                                            print(f"DEBUG: Educator signup result: success={success}, message={message}")
                                            
                                            if success:
                                                # Store success in session state
                                                st.session_state['educator_signup_success'] = True
                                                st.session_state['educator_signup_message'] = "Successfully signed up as educator!"
                                                st.rerun()
                                            else:
                                                st.error(f"Signup failed: {message}")
                                        except Exception as e:
                                            st.error(f"Error during signup: {str(e)}")
                                            print(f"DEBUG: Exception during educator signup: {e}")
                                            import traceback
                                            traceback.print_exc()


                        else:
                            st.write("Full")
                    
                    st.markdown("---")
    
    @staticmethod
    def _display_class_info_for_educators(class_details):
        """Display class information relevant for educators"""
        if not class_details:
            st.error("No class details available")
            return
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**📚 Class:** {class_details.get('class_name', 'Unknown')}")
            st.write(f"**👥 Max Students:** {class_details.get('students_per_class', '21')}")
            instructor_count = class_details.get('instructors_per_day', 0)
            st.write(f"**👨‍🏫 Educators Needed:** {instructor_count}")
        
        with col2:
            if class_details.get('is_two_day_class', 'No').lower() == 'yes':
                st.write("• **Two-day class format**")
                st.info("⚠️ 2-Day Class: Each day requires separate educator signup. You can sign up for one or both days.")
            if class_details.get('is_staff_meeting', False):
                st.write("• **Staff Meeting**")
        
        # Display class times
        st.write("**🕐 Class Times:**")
        times = EducatorUIComponents._get_class_times(class_details)
        for time_slot in times:
            st.write(f"• {time_slot}")
    
    @staticmethod
    def _get_class_times(class_details):
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
        
        return times if times else ["Time not specified"]
    
    @staticmethod
    def _handle_educator_signup_with_conflict(educator_manager, staff_name, class_name, 
                                        class_date, conflict_info, button_key):
        """Handle educator signup with conflict override"""
        
        # Show conflict warning and override option
        col_warn, col_override = st.columns([3, 2])
        
        with col_warn:
            st.warning(f"⚠️ {conflict_info}")
        
        with col_override:
            if st.button("Override", key=f"override_{button_key}"):
                st.session_state[f"show_educator_override_{button_key}"] = True
        
        # Show override dialog if triggered
        if st.session_state.get(f"show_educator_override_{button_key}", False):
            with st.container():
                st.error("**⚠️ Schedule Conflict Override - Educator Signup**")
                st.write(f"**Conflict:** {conflict_info}")
                st.write("By proceeding, you acknowledge that:")
                st.write("• You are responsible for arranging coverage for your regular duties")
                st.write("• You should coordinate with your supervisor about this educator assignment")
                
                acknowledge = st.checkbox(
                    "I acknowledge and will arrange appropriate coverage",
                    key=f"ack_educator_{button_key}"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Confirm Signup", key=f"confirm_educator_{button_key}", 
                            disabled=not acknowledge):
                        with st.spinner("Processing educator signup..."):
                            success, message = educator_manager.signup_as_educator(
                                staff_name, class_name, class_date, override_conflict=True
                            )
                        
                        if success:
                            # Clean up session state
                            if f"show_educator_override_{button_key}" in st.session_state:
                                del st.session_state[f"show_educator_override_{button_key}"]
                            # Store success in session state
                            st.session_state['educator_signup_success'] = True
                            st.session_state['educator_signup_message'] = "Successfully signed up as educator with conflict override!"
                            st.rerun()
                        else:
                            st.error(f"Signup failed: {message}")
                
                with col2:
                    if st.button("Cancel", key=f"cancel_educator_override_{button_key}"):
                        if f"show_educator_override_{button_key}" in st.session_state:
                            del st.session_state[f"show_educator_override_{button_key}"]
                        st.rerun()
    
    @staticmethod
    def display_staff_educator_enrollments(educator_manager, staff_name):
        """Display staff member's educator signups with enhanced colleague info"""
        signups = educator_manager.get_staff_educator_signups(staff_name)
        
        if not signups:
            st.info("You are not currently signed up as an educator for any classes.")
            return
        
        st.write(f"**👨‍🏫 Your Educator Signups ({len(signups)}):**")
        
        for signup in signups:
            with st.container():
                col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
                
                with col1:
                    class_name = signup['class_name']
                    st.write(f"**📚 {class_name}**")
                    
                    # Add conflict indicator
                    if signup.get('conflict_override'):
                        st.write("⚠️ **Conflict Override**")
                
                with col2:
                    st.write(f"**📅 Date:** {signup['class_date']}")
                    if signup.get('signup_date_display'):
                        st.write(f"**Signed up:** {signup['signup_date_display']}")
                
                with col3:
                    # Show conflict details if override
                    if signup.get('conflict_override') and signup.get('conflict_details'):
                        st.warning(f"**Conflict:** {signup['conflict_details']}")
                    
                    # Show other educators for this date - ENHANCED
                    other_educators = educator_manager.get_class_educator_roster(
                        class_name, signup['class_date']
                    )
                    other_names = [e['staff_name'] for e in other_educators 
                                 if e['staff_name'] != staff_name and e['status'] == 'active']
                    
                    # Get class details to show how many educators are needed
                    class_details = educator_manager.excel.get_class_details(class_name)
                    instructors_needed = class_details.get('instructors_per_day', 0) if class_details else 0
                    total_signups = len(other_educators)
                    
                    if instructors_needed > 1:
                        st.write(f"**Educators ({total_signups}/{instructors_needed}):**")
                        if other_names:
                            for name in other_names:
                                st.write(f"• {name}")
                            st.write(f"• **{staff_name}** (You)")
                        else:
                            st.write(f"• **{staff_name}** (You)")
                            if total_signups < instructors_needed:
                                still_needed = instructors_needed - total_signups
                                st.write(f"*Still need {still_needed} more educator{'s' if still_needed != 1 else ''}*")
                    else:
                        if other_names:
                            st.write("**Other educators:**")
                            for name in other_names:
                                st.write(f"• {name}")
                        else:
                            st.write("*Only educator signed up*")
                
                with col4:
                    if st.button("Cancel", key=f"cancel_educator_{signup['id']}"):
                        if educator_manager.cancel_educator_signup(signup['id']):
                            st.success("Educator signup cancelled!")
                            st.rerun()
                        else:
                            st.error("Error cancelling signup")
                
                st.markdown("---")
    
    @staticmethod
    def display_educator_metrics(educator_manager, staff_name):
        """Display educator signup metrics"""
        signups = educator_manager.get_staff_educator_signups(staff_name)
        opportunities = educator_manager.get_educator_opportunities()
        
        # Count total opportunities
        total_opportunities = sum(len(opp['available_dates']) for opp in opportunities)
        
        # Count conflicts
        conflict_count = sum(1 for signup in signups if signup.get('conflict_override'))
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Educator Signups", len(signups))
        
        with col2:
            st.metric("Total Opportunities", total_opportunities)
        
        with col3:
            if conflict_count > 0:
                st.metric("Conflict Overrides", conflict_count, delta=f"⚠️")
            else:
                st.metric("Conflict Overrides", conflict_count)
    
    @staticmethod
    def display_class_educator_summary(educator_manager, class_name):
        """Display educator summary for a specific class with enhanced name display"""
        class_details = educator_manager.excel.get_class_details(class_name)
        instructor_requirement = class_details.get('instructors_per_day', 0)
        
        if instructor_requirement <= 0:
            st.info("This class does not require educators.")
            return
        
        educator_summary = educator_manager.get_class_educator_summary(class_name)
        
        st.write(f"**👨‍🏫 Educator Requirements: {instructor_requirement} per date**")
        
        if not educator_summary:
            st.warning("No educator signups found for this class.")
            return
        
        # Display educator signups by date
        for date, summary in educator_summary.items():
            st.write(f"**📅 {date}:**")
            
            total_signed_up = summary.get('total', 0)
            conflicts = summary.get('conflicts', 0)
            staff_names = summary.get('staff_names', [])
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if total_signed_up >= instructor_requirement:
                    st.success(f"✅ Educators: {total_signed_up}/{instructor_requirement}")
                elif total_signed_up >= instructor_requirement * 0.5:
                    st.warning(f"🟡 Educators: {total_signed_up}/{instructor_requirement}")
                else:
                    st.error(f"🔴 Educators: {total_signed_up}/{instructor_requirement}")
                
                # Show needed count
                needed = max(0, instructor_requirement - total_signed_up)
                if needed > 0:
                    st.write(f"**Need {needed} more educator{'s' if needed != 1 else ''}**")
                else:
                    st.success("**Fully staffed!**")
            
            with col2:
                # Show conflicts if any
                if conflicts > 0:
                    st.warning(f"⚠️ {conflicts} conflict override{'s' if conflicts != 1 else ''}")
                else:
                    st.success("✅ No conflicts")
            
            with col3:
                # Show educator names - ENHANCED with better formatting
                if staff_names:
                    st.write("**👨‍🏫 Signed up:**")
                    for i, name in enumerate(staff_names, 1):
                        st.write(f"{i}. {name}")
                else:
                    st.write("*No educators signed up*")
            
            st.markdown("---")

    @staticmethod
    def display_educator_status():
        """Display educator signup success/error messages from session state"""
        if st.session_state.get('educator_signup_success', False):
            st.success(st.session_state.get('educator_signup_message', 'Educator signup successful!'))
            # Clear the success flag after displaying
            del st.session_state['educator_signup_success']
            if 'educator_signup_message' in st.session_state:
                del st.session_state['educator_signup_message']
