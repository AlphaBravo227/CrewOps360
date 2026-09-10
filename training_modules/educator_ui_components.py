# training_modules/educator_ui_components.py
"""
UI components for educator signup.

The opportunity list is laid out like the staff enrollment screen: one collapsed
panel per class, a summary grid of every date inside it, and the signup itself for
one date at a time. Before that, every date drew its own row of status columns,
rosters and buttons, so a class with a dozen dates ran to several screens and the
only way to find out what the fourth date offered was to scroll past three others.
"""
import streamlit as st
from datetime import datetime, timedelta

from .class_catalog import date_indices

class EducatorUIComponents:
    
    @staticmethod
    def display_educator_opportunities(educator_manager, staff_name):
        """The classes needing educators, one collapsed panel each."""
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
            class_details = opportunity['class_details'] or {}
            is_two_day = opportunity.get('is_two_day', False)
            date_status = opportunity.get('date_status') or []

            signed_up_dates = [entry['date'] for entry in date_status
                               if entry['is_signed_up']]

            # What the panel says while closed, so a class needing nothing from you
            # doesn't have to be opened to find that out.
            title = (f"**{class_name}** (Need {instructor_count} "
                     f"educator{'s' if instructor_count != 1 else ''} per date)")
            if len(signed_up_dates) == 1:
                title += " ✅ Signed up"
            elif signed_up_dates:
                title += f" ✅ Signed up ({len(signed_up_dates)} dates)"
            elif date_status and all(entry['is_full'] for entry in date_status):
                title += " 🔴 Fully staffed"

            with st.expander(title, expanded=False):
                st.caption(" • ".join(EducatorUIComponents._class_facts(
                    class_details, instructor_count, is_two_day)))

                if is_two_day:
                    st.info("📅 **Two-day class:** each day takes its own educator "
                            "signup. You can sign up for one day or both.")

                locations = EducatorUIComponents._date_attribute_map(
                    class_details, 'location', is_two_day)

                if not date_status:
                    st.warning("No dates configured for this class.")
                    continue

                EducatorUIComponents._display_educator_date_summary(
                    class_details, date_status, is_two_day, locations)

                # Only one date's signup is drawn at a time. Which date is a choice
                # the summary above has already given the user enough to make.
                chosen_date = date_status[0]['date']
                if len(date_status) > 1:
                    st.markdown("---")
                    dates = [entry['date'] for entry in date_status]
                    default_index = next(
                        (i for i, date in enumerate(dates) if date in signed_up_dates), 0)
                    labels = {entry['date']: EducatorUIComponents._radio_label(entry)
                              for entry in date_status}
                    chosen_date = st.radio(
                        "**Sign up for:**",
                        options=dates,
                        index=default_index,
                        format_func=lambda date: labels[date],
                        horizontal=True,
                        key=f"educator_date_choice_{class_name}"
                    )

                # Defaulted rather than indexed: the picker's stored choice can
                # outlive the dates it was made from, and a class dropping off the
                # list must not take the whole tab down with it.
                chosen = next((entry for entry in date_status
                               if entry['date'] == chosen_date), date_status[0])
                EducatorUIComponents._display_date_signup(
                    educator_manager, staff_name, class_name, chosen, is_two_day,
                    locations.get(chosen_date))

    @staticmethod
    def _class_facts(class_details, instructor_count, is_two_day):
        """The one-line read of what the class is, above its dates."""
        facts = [f"👨‍🏫 {instructor_count} educator"
                 f"{'s' if instructor_count != 1 else ''} needed per date"]

        times = EducatorUIComponents._get_class_times(class_details)
        if len(times) <= 2:
            facts.append(f"🕐 {' / '.join(times)}")
        else:
            first = times[0].split('-')[0].strip()
            last = times[-1].split('-')[-1].strip()
            facts.append(f"🕐 {len(times)} sessions ({first} - {last})")

        # A class our own staff don't attend has no student capacity worth printing -
        # the seat count on it is a leftover, not a fact about the class.
        if class_details.get('is_educator_only'):
            facts.append("🎓 External class - staff don't attend")
        else:
            facts.append(f"👥 Max {class_details.get('students_per_class', 21)} students")

        if class_details.get('is_staff_meeting', False):
            facts.append("📣 Staff meeting")
        if is_two_day:
            facts.append("📅 Two-day class")
        return facts

    @staticmethod
    def _date_attribute_map(class_details, attribute, is_two_day):
        """One of a date's attributes, keyed by every date it covers.

        A two-day class is offered to educators as two separate days, but its
        locations and night-prior flags are stored against the first of them - so
        day two is keyed to the same values rather than reading as a date with
        nothing known about it.
        """
        values = {}
        for index in date_indices(class_details):
            date = class_details.get(f'date_{index}')
            if not date:
                continue
            value = class_details.get(f'date_{index}_{attribute}')
            values[date] = value
            if is_two_day:
                try:
                    day_2 = (datetime.strptime(date, '%m/%d/%Y')
                             + timedelta(days=1)).strftime('%m/%d/%Y')
                except ValueError:
                    continue
                values.setdefault(day_2, value)
        return values

    @staticmethod
    def _staffing_text(entry):
        """How close one date is to being staffed."""
        current, needed = entry['current_signups'], entry['max_signups']
        if entry['is_full']:
            return f"🔴 Full ({current}/{needed})"
        if needed and current >= needed * 0.8:
            return f"🟡 {current} of {needed} signed up"
        return f"🟢 {current} of {needed} signed up"

    @staticmethod
    def _radio_label(entry):
        """A date on the picker, marked with what you'd find if you opened it."""
        label = entry['date']
        if entry['is_signed_up']:
            label += " ✅"
        elif entry['is_full']:
            label += " 🔴"
        return label

    @staticmethod
    def _display_educator_date_summary(class_details, date_status, is_two_day,
                                       locations):
        """Every date of one class, and what each still needs, as one grid.

        The same unit an educator signs up for gets one row, so the dates, their
        locations and their remaining spots can be compared without opening any.
        """
        night_prior = EducatorUIComponents._date_attribute_map(
            class_details, 'can_work_n_prior', is_two_day)

        rows = []
        shows_night_prior = False
        flag_reasons = set()
        for entry in date_status:
            date = entry['date']

            date_label = date
            if night_prior.get(date):
                date_label += " 🌙"
                shows_night_prior = True

            # The mark only says something is in the way. What it is stays with the
            # signup below, next to the override or the explanation for it.
            conflict_cell = ""
            conflict_info = entry.get('conflict_info') or ""
            if conflict_info.startswith('ℹ️'):
                conflict_cell = "ℹ️"
                flag_reasons.add('info')
            elif conflict_info:
                conflict_cell = "🟡"
                flag_reasons.add('track')

            rows.append({
                "Date": date_label,
                "Location": locations.get(date) or "",
                "Educators": EducatorUIComponents._staffing_text(entry),
                "Conflict": conflict_cell,
                "You": "✅ Signed up" if entry['is_signed_up'] else "",
            })

        # A column with nothing to say in any row is dropped rather than filled with
        # placeholders down its length: most classes run at one place, and a track
        # conflict column means nothing to someone without a track. Every dropped
        # column is width the remaining ones get back.
        columns = ["Date", "Location", "Educators", "Conflict", "You"]
        if not flag_reasons:
            columns.remove("Conflict")
        if not any(row["Location"] for row in rows):
            columns.remove("Location")
        else:
            for row in rows:
                row["Location"] = row["Location"] or "Not specified"

        header = ("| " + " | ".join(columns) + " |\n"
                  + "|" + "---|" * len(columns) + "\n")
        body = "\n".join(
            "| " + " | ".join(str(row[column]).replace("|", "\\|") for column in columns) + " |"
            for row in rows
        )
        st.markdown(header + body)

        legend = []
        if shows_night_prior:
            legend.append("🌙 = night shift prior OK")
        if 'track' in flag_reasons:
            legend.append("🟡 = conflicts with your track - see the date below for details")
        if 'info' in flag_reasons:
            legend.append("ℹ️ = AT shift only, which is no conflict for educators")
        if legend:
            st.caption(" • ".join(legend))

    @staticmethod
    def _display_date_signup(educator_manager, staff_name, class_name, entry,
                             is_two_day, location):
        """One date's roster and the button that puts you on it."""
        date = entry['date']
        conflict_info = entry.get('conflict_info') or ""

        if is_two_day:
            st.subheader(f"📅 {date} (one day of a two-day class)")
        else:
            st.subheader(f"📅 {date}")
        if location:
            st.write(f"**📍 Location:** {location}")

        # Said once, here, rather than beside every control that depends on it.
        if conflict_info.startswith('ℹ️'):
            st.info(conflict_info)
        elif conflict_info:
            st.warning(f"⚠️ {conflict_info}")

        roster = educator_manager.get_class_educator_roster(class_name, date)
        signed_up = [e['staff_name'] for e in roster if e['status'] == 'active']

        st.write(f"**👨‍🏫 Educators ({entry['current_signups']}/"
                 f"{entry['max_signups']}):**")
        if signed_up:
            for educator_name in signed_up:
                if educator_name == staff_name:
                    st.write(f"• **{educator_name}** (You)")
                else:
                    st.write(f"• {educator_name}")
        else:
            st.write("*Nobody signed up yet*")

        still_needed = max(0, entry['max_signups'] - entry['current_signups'])
        if still_needed:
            st.caption(f"Still need {still_needed} more "
                       f"educator{'s' if still_needed != 1 else ''}")
        else:
            st.caption("Fully staffed")

        button_key = (f"educator_{class_name}_{date}_{staff_name}"
                      .replace(" ", "_").replace("/", "_"))

        if entry['is_signed_up']:
            if st.button("Cancel signup", key=f"cancel_{button_key}"):
                existing_signup = educator_manager.db.check_existing_educator_signup(
                    staff_name, class_name, date,
                    training_year=educator_manager.training_year
                )
                if existing_signup and educator_manager.cancel_educator_signup(
                        existing_signup['id']):
                    st.success("Educator signup cancelled!")
                    st.rerun()
                else:
                    st.error("Error cancelling signup")

        elif entry['is_full']:
            st.error("🔴 Every educator spot on this date is taken.")

        elif conflict_info and not conflict_info.startswith('ℹ️'):
            # Real conflict - show override option
            EducatorUIComponents._handle_educator_signup_with_conflict(
                educator_manager, staff_name, class_name, date,
                conflict_info, button_key
            )

        else:
            # No conflict, or AT info only - normal signup
            if st.button("Sign Up", type="primary", key=f"signup_{button_key}"):
                with st.spinner("Processing educator signup..."):
                    try:
                        success, message = educator_manager.signup_as_educator(
                            staff_name, class_name, date
                        )

                        if success:
                            # Store success in session state
                            st.session_state['educator_signup_success'] = True
                            st.session_state['educator_signup_message'] = \
                                "Successfully signed up as educator!"
                            st.rerun()
                        else:
                            st.error(f"Signup failed: {message}")
                    except Exception as e:
                        st.error(f"Error during signup: {str(e)}")
                        import traceback
                        traceback.print_exc()

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
        """Handle educator signup with conflict override.

        The conflict itself has already been stated above the roster, so this only
        offers the way through it.
        """
        if st.button("Override conflict and sign up", key=f"override_{button_key}"):
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
    def display_staff_educator_enrollments(educator_manager, staff_name, read_only=False):
        """Display staff member's educator signups with enhanced colleague info.

        read_only drops the cancel buttons, for a training year that has closed.
        """
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
                    if read_only:
                        st.caption("🔒 Closed")
                    elif st.button("Cancel", key=f"cancel_educator_{signup['id']}"):
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
