# training_modules/educator_ui_components.py - FIXED for 2-day class display
"""
UI Components specifically for educator signup functionality with proper 2-day class support
"""
import streamlit as st
from datetime import datetime

class EducatorUIComponents:
    
    @staticmethod
    def display_educator_opportunities(educator_manager, staff_name):
        """Display available educator opportunities for a staff member with proper 2-day handling"""
        opportunities = educator_manager.get_educator_opportunities_with_status(staff_name)
        
        if not opportunities:
            st.info("No educator opportunities available at this time.")
            return
        
        st.write(f"**📚 Available Educator Opportunities**")
        st.caption("Sign up to be part of the education staff for classes")
        
        for opportunity in opportunities:
            class_name = opportunity['class_name']
            instructor_count = opportunity['instructor_count']
            is_two_day = opportunity.get('is_two_day', False)
            
            # Enhanced expander title for 2-day classes
            if is_two_day:
                expander_title = f"**{class_name}** (Need {instructor_count} educator{'s' if instructor_count != 1 else ''} per day) - 🔴 **2-DAY CLASS**"
            else:
                expander_title = f"**{class_name}** (Need {instructor_count} educator{'s' if instructor_count != 1 else ''} per date)"
            
            # Create expander for each class
            with st.expander(expander_title):
                
                # Show class details
                class_details = opportunity['class_details']
                EducatorUIComponents._display_class_info_for_educators(class_details)
                
                # Add special note for 2-day classes
                if is_two_day:
                    st.warning("⚠️ **2-Day Class**: Each day requires separate educator signup. You can sign up for one or both days.")
                
                st.markdown("---")
                st.write("**📅 Available Dates:**")
                
                # Group dates for 2-day classes for better display
                if is_two_day:
                    EducatorUIComponents._display_two_day_opportunities(
                        opportunity, educator_manager, staff_name
                    )
                else:
                    EducatorUIComponents._display_regular_opportunities(
                        opportunity, educator_manager, staff_name
                    )
    
    @staticmethod
    def _display_two_day_opportunities(opportunity, educator_manager, staff_name):
        """Display opportunities for 2-day classes with grouped date pairs"""
        class_name = opportunity['class_name']
        date_status_list = opportunity['date_status']
        
        # Group dates into pairs (day 1, day 2)
        date_pairs = []
        for i in range(0, len(date_status_list), 2):
            if i + 1 < len(date_status_list):
                date_pairs.append((date_status_list[i], date_status_list[i + 1]))
            else:
                # Odd number of dates, add single date
                date_pairs.append((date_status_list[i], None))
        
        for pair_idx, date_pair in enumerate(date_pairs):
            day_1, day_2 = date_pair
            
            st.write(f"**Session {pair_idx + 1}:**")
            
            # Create columns for each day
            if day_2:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**Day 1: {day_1['date']}**")
                    EducatorUIComponents._display_single_date_opportunity(
                        day_1, educator_manager, staff_name, class_name, f"day1_{pair_idx}"
                    )
                
                with col2:
                    st.write(f"**Day 2: {day_2['date']}**")
                    EducatorUIComponents._display_single_date_opportunity(
                        day_2, educator_manager, staff_name, class_name, f"day2_{pair_idx}"
                    )
            else:
                # Single date
                st.write(f"**{day_1['date']}**")
                EducatorUIComponents._display_single_date_opportunity(
                    day_1, educator_manager, staff_name, class_name, f"single_{pair_idx}"
                )
            
            st.markdown("---")
    
    @staticmethod
    def _display_regular_opportunities(opportunity, educator_manager, staff_name):
        """Display opportunities for regular (single-day) classes"""
        class_name = opportunity['class_name']
        
        for date_idx, date_info in enumerate(opportunity['date_status']):
            EducatorUIComponents._display_single_date_opportunity(
                date_info, educator_manager, staff_name, class_name, f"reg_{date_idx}"
            )
            st.markdown("---")
    
    @staticmethod
    def _display_single_date_opportunity(date_info, educator_manager, staff_name, class_name, unique_key):
        """Display a single date opportunity with all controls"""
        date = date_info['date']
        current_signups = date_info['current_signups']
        max_signups = date_info['max_signups']
        is_signed_up = date_info['is_signed_up']
        is_full = date_info['is_full']
        conflict_info = date_info['conflict_info']
        
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
        
        with col3:
            if is_signed_up:
                st.success("✅ Signed Up")
            elif is_full:
                st.error("Full")
            else:
                st.write("Available")
        
        with col4:
            button_key = f"educator_{class_name}_{date}_{staff_name}_{unique_key}".replace(" ", "_").replace("/", "_")
            
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
            
            elif is_full:
                st.write("*No slots*")
            
            else:
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
                        try:
                            success, message = educator_manager.signup_as_educator(
                                staff_name, class_name, date
                            )
                            if success:
                                st.success("Successfully signed up as educator!")
                                st.rerun()
                            else:
                                st.error(f"Signup failed: {message}")
                        except Exception as e:
                            st.error(f"Error during signup: {str(e)}")
                            st.write(f"Debug info: class_name={class_name}, date={date}, staff_name={staff_name}")
    
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
            is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
            if is_two_day:
                st.write("• **Two-day class format** 🔴")
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
                        success, message = educator_manager.signup_as_educator(
                            staff_name, class_name, class_date, override_conflict=True
                        )
                        
                        if success:
                            st.success("Successfully signed up as educator with conflict override!")
                            del st.session_state[f"show_educator_override_{button_key}"]
                            st.rerun()
                        else:
                            st.error(f"Signup failed: {message}")
                
                with col2:
                    if st.button("Cancel", key=f"cancel_educator_override_{button_key}"):
                        del st.session_state[f"show_educator_override_{button_key}"]
    
    @staticmethod
    def display_staff_educator_enrollments(educator_manager, staff_name):
        """Display staff member's educator signups with enhanced 2-day class info"""
        signups = educator_manager.get_staff_educator_signups(staff_name)
        
        if not signups:
            st.info("You are not currently signed up as an educator for any classes.")
            return
        
        st.write(f"**👨‍🏫 Your Educator Signups ({len(signups)}):**")
        
        # Group signups by class for better organization
        signups_by_class = {}
        for signup in signups:
            class_name = signup['class_name']
            if class_name not in signups_by_class:
                signups_by_class[class_name] = []
            signups_by_class[class_name].append(signup)
        
        for class_name, class_signups in signups_by_class.items():
            with st.expander(f"**📚 {class_name}** ({len(class_signups)} signup{'s' if len(class_signups) != 1 else ''})", expanded=True):
                
                # Check if this might be a 2-day class by looking at consecutive dates
                dates = [signup['class_date'] for signup in class_signups]
                dates.sort()
                
                # Display each signup
                for signup in sorted(class_signups, key=lambda x: x['class_date']):
                    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
                    
                    with col1:
                        st.write(f"**📅 Date:** {signup['class_date']}")
                        
                        # Add conflict indicator
                        if signup.get('conflict_override'):
                            st.write("⚠️ **Conflict Override**")
                    
                    with col2:
                        if signup.get('signup_date_display'):
                            st.write(f"**Signed up:** {signup['signup_date_display']}")
                        
                        # Show conflict details if override
                        if signup.get('conflict_override') and signup.get('conflict_details'):
                            st.warning(f"**Conflict:** {signup['conflict_details']}")
                    
                    with col3:
                        # Show other educators for this date
                        other_educators = educator_manager.get_class_educator_roster(
                            class_name, signup['class_date']
                        )
                        other_names = [e['staff_name'] for e in other_educators 
                                     if e['staff_name'] != staff_name and e['status'] == 'active']
                        
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
        """Display educator signup metrics with 2-day class considerations"""
        signups = educator_manager.get_staff_educator_signups(staff_name)
        opportunities = educator_manager.get_educator_opportunities()
        
        # Count total opportunities (including expanded 2-day dates)
        total_opportunities = sum(len(opp['available_dates']) for opp in opportunities)
        
        # Count conflicts
        conflict_count = sum(1 for signup in signups if signup.get('conflict_override'))
        
        # Count unique classes (for 2-day classes, this shows unique class participation)
        unique_classes = len(set(signup['class_name'] for signup in signups))
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Educator Signups", len(signups))
        
        with col2:
            st.metric("Unique Classes", unique_classes)
        
        with col3:
            st.metric("Total Opportunities", total_opportunities)
        
        with col4:
            if conflict_count > 0:
                st.metric("Conflict Overrides", conflict_count, delta=f"⚠️")
            else:
                st.metric("Conflict Overrides", conflict_count)
    
    @staticmethod
    def display_class_educator_summary(educator_manager, class_name):
        """Display educator summary for a specific class with 2-day class support"""
        class_details = educator_manager.excel.get_class_details(class_name)
        instructor_requirement = class_details.get('instructors_per_day', 0)
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
        
        if instructor_requirement <= 0:
            st.info("This class does not require educators.")
            return
        
        educator_summary = educator_manager.get_class_educator_summary(class_name)
        
        # Enhanced header for 2-day classes
        if is_two_day:
            st.write(f"**👨‍🏫 Educator Requirements: {instructor_requirement} per day (2-Day Class - Each day requires separate signups)**")
        else:
            st.write(f"**👨‍🏫 Educator Requirements: {instructor_requirement} per date**")
        
        if not educator_summary:
            st.warning("No educator signups found for this class.")
            return
        
        # Sort dates for better display
        sorted_dates = sorted(educator_summary.keys())
        
        # For 2-day classes, group dates in pairs for better visualization
        if is_two_day and len(sorted_dates) > 1:
            st.write("**📅 Educator Coverage by Session:**")
            
            # Group dates into pairs
            date_pairs = []
            for i in range(0, len(sorted_dates), 2):
                if i + 1 < len(sorted_dates):
                    date_pairs.append((sorted_dates[i], sorted_dates[i + 1]))
                else:
                    date_pairs.append((sorted_dates[i], None))
            
            for pair_idx, (date_1, date_2) in enumerate(date_pairs):
                st.write(f"**Session {pair_idx + 1}:**")
                
                if date_2:
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Day 1: {date_1}**")
                        EducatorUIComponents._display_date_educator_summary(
                            educator_summary[date_1], instructor_requirement
                        )
                    
                    with col2:
                        st.write(f"**Day 2: {date_2}**")
                        EducatorUIComponents._display_date_educator_summary(
                            educator_summary[date_2], instructor_requirement
                        )
                else:
                    st.write(f"**{date_1}:**")
                    EducatorUIComponents._display_date_educator_summary(
                        educator_summary[date_1], instructor_requirement
                    )
                
                st.markdown("---")
        else:
            # Regular display for single-day classes or classes with single dates
            st.write("**📅 Educator Coverage by Date:**")
            
            for date in sorted_dates:
                st.write(f"**{date}:**")
                EducatorUIComponents._display_date_educator_summary(
                    educator_summary[date], instructor_requirement
                )
                st.markdown("---")
    
    @staticmethod
    def _display_date_educator_summary(date_summary, instructor_requirement):
        """Display educator summary for a single date"""
        total_signed_up = date_summary.get('total', 0)
        conflicts = date_summary.get('conflicts', 0)
        staff_names = date_summary.get('staff_names', [])
        
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
        
        with col2:
            # Show conflicts if any
            if conflicts > 0:
                st.warning(f"⚠️ {conflicts} conflict override{'s' if conflicts != 1 else ''}")
            else:
                st.success("✅ No conflicts")
        
        with col3:
            # Show educator names
            if staff_names:
                st.write("**Signed up:**")
                for name in staff_names:
                    st.write(f"• {name}")
            else:
                st.write("*No educators signed up*")