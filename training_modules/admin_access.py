# Updates needed for training_modules/admin_access.py

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import pytz
import os
import re
from . import class_catalog as catalog

_eastern_tz = pytz.timezone('America/New_York')

# Update the AdminAccess class to include availability analyzer initialization
def _year_last_class_date(year_label):
    """Latest class date in a training year, or None.

    A year whose end date falls before this still has classes to teach, and
    auto-close would freeze it with staff mid-way through them.
    """
    from datetime import datetime
    from . import class_catalog as catalog

    if not year_label:
        return None
    try:
        latest = None
        for class_name in catalog.get_class_names(year_label):
            record = catalog.get_class_row(year_label, class_name)
            if not record:
                continue
            for entry in catalog.get_dates_with_options(record['id']):
                try:
                    parsed = datetime.strptime(entry['class_date'], '%m/%d/%Y').date()
                except (ValueError, TypeError):
                    continue
                if latest is None or parsed > latest:
                    latest = parsed
        return latest
    except Exception:
        return None


# How long a training admin session stays authenticated. Module-level so the
# training app can ask whether an admin is signed in before the AdminAccess
# instance has been built - the year picker has to be widened for admins several
# steps earlier than that.
ADMIN_SESSION_TIMEOUT_MINUTES = 30


def clear_admin_session():
    """Drop every key that makes up an authenticated training admin session."""
    for key in ('training_admin_authenticated', 'training_admin_login_time',
                'training_admin_current_function', 'training_admin_show_function'):
        st.session_state.pop(key, None)


def training_admin_is_authenticated():
    """Whether a training admin is signed in and their session hasn't expired.

    Expiry logs the session out here rather than only reporting it, so an expired
    admin stops seeing draft years on the very render that notices.
    """
    if not st.session_state.get('training_admin_authenticated'):
        return False
    login_time = st.session_state.get('training_admin_login_time')
    if not login_time:
        return False
    elapsed_minutes = (datetime.now(_eastern_tz) - login_time).total_seconds() / 60
    if elapsed_minutes > ADMIN_SESSION_TIMEOUT_MINUTES:
        clear_admin_session()
        return False
    return True


class AdminAccess:
    def __init__(self):
        self.admin_pin = "9999"
        self.session_timeout = ADMIN_SESSION_TIMEOUT_MINUTES  # minutes
        self.excel_admin_functions = None
        self.availability_analyzer = None  # NEW: Add availability analyzer
        # The training year the cached analyzer was built for, so switching years
        # rebuilds it rather than reusing the previous year's roster and tracks.
        self.availability_analyzer_year = None
    
    def initialize_admin_functions(self, excel_admin_functions):
        """Initialize with ExcelAdminFunctions instance"""
        self.excel_admin_functions = excel_admin_functions
    
    def is_admin_authenticated(self):
        """Check if admin is currently authenticated"""
        return training_admin_is_authenticated()
    
    def show_admin_access_button(self):
        """Show the sidebar way in to the training admin.

        The dashboard itself is a full-width page of its own - the same shape as
        the Staff Database and Track Data admins in Track Bidding - so the sidebar
        carries only the door: a PIN form when nobody is signed in, and a button
        back into the dashboard for an admin who has stepped out of it.
        """
        with st.sidebar:
            st.markdown("---")
            
            # Use an expander to keep it discrete
            with st.expander("⚙️ Training Admin Access", expanded=False):
                if not self.is_admin_authenticated():
                    self._show_login_form()
                else:
                    self._show_admin_entry()
    
    def _show_login_form(self):
        """Show the PIN entry form"""
        st.write("**Training Administration**")
        
        # Use a form to handle the PIN entry
        with st.form("training_admin_login_form"):
            pin_input = st.text_input(
                "Enter Admin PIN:",
                type="password",
                placeholder="Enter 4-digit PIN",
                max_chars=4,
                help="Contact training administrator for access"
            )
            
            submitted = st.form_submit_button("Access Training Admin")
            
            if submitted:
                if pin_input == self.admin_pin:
                    st.session_state.training_admin_authenticated = True
                    st.session_state.training_admin_login_time = datetime.now(_eastern_tz)
                    # Signing in lands straight on the full-screen dashboard rather
                    # than leaving the admin to find a second control in the sidebar.
                    st.session_state.training_admin_current_function = None
                    st.session_state.training_admin_show_function = True
                    st.success("✅ Training admin access granted")
                    st.rerun()
                else:
                    st.error("❌ Invalid PIN")
    
    def _show_admin_entry(self):
        """Sidebar controls for an admin who is signed in but out on a staff page."""
        st.success("🔓 **Training Admin signed in**")
        st.info(f"⏱️ Session expires in {self.session_minutes_remaining():.0f} minutes")
        
        if st.button("🛠️ Open Training Admin", key="training_admin_open_dashboard",
                     use_container_width=True, type="primary"):
            st.session_state.training_admin_current_function = None
            st.session_state.training_admin_show_function = True
            st.rerun()
        
        if st.button("🔒 Logout", key="training_admin_logout", use_container_width=True):
            self.logout_admin()
            st.rerun()
    
    def session_minutes_remaining(self):
        """Minutes left on the current admin session (0 once it has expired)."""
        login_time = st.session_state.get('training_admin_login_time')
        if not login_time:
            return 0
        elapsed_minutes = (datetime.now(_eastern_tz) - login_time).total_seconds() / 60
        return max(0, self.session_timeout - elapsed_minutes)

    def logout_admin(self):
        """Logout admin user"""
        clear_admin_session()
    
    def require_admin(self):
        """Decorator-like function to require admin authentication"""
        if not self.is_admin_authenticated():
            st.error("🔒 Training administrative access required")
            st.info("Please use the training admin access panel in the sidebar")
            st.stop()
        
        # Extend session on activity
        st.session_state.training_admin_login_time = datetime.now(_eastern_tz)
    
    # The functions the dashboard offers, in the order they appear on its home
    # page. Shared by the home grid and the header of each function page, so a
    # function's title and description are written once.
    ADMIN_SECTIONS = [
        ("📈 Enrollment Reports", "enrollment_reports", "View and export enrollment data"),
        ("👥 Manage Staff", "manage_staff", "View staff enrollment status"),
        ("📚 Manage Classes", "manage_classes", "Configure class settings and schedules"),
        ("➕ Build Classes", "build_classes", "Create and reconfigure classes and their dates"),
        ("🗓️ Training Years", "training_years", "Manage fiscal-year rosters and cutover"),
        ("📄 Data Export", "data_management", "Export training data"),
        ("📊 System Statistics", "system_stats", "View training system usage"),
        ("🗂️ Database Maintenance", "database_maintenance", "Training database operations"),
        ("🔧 Track Manager", "track_manager", "Manage track status and edit assignments"),
    ]

    def show_admin_function_page(self):
        """Render the training admin as a full-width page of its own.

        With no function chosen it shows the dashboard home - the function menu,
        which used to live in the sidebar. Choosing one replaces the menu with that
        function, still full width, with a way back to the menu in the header.
        """
        if not self.is_admin_authenticated():
            st.error("🔒 Access Denied")
            st.info("Please authenticate through the training admin panel in the sidebar")
            return False
        
        if not st.session_state.get('training_admin_show_function', False):
            return False
        
        current_function = st.session_state.get('training_admin_current_function') or ''
        section = next((s for s in self.ADMIN_SECTIONS if s[1] == current_function), None)
        
        self._show_admin_page_header(section)

        # Which fiscal year everything below covers. During a cutover two years are
        # live at once and the numbers differ completely between them, so this is
        # not decoration - a compliance report is meaningless without it.
        self._show_training_year_context()

        st.markdown("---")
        
        if section:
            self._render_admin_function(current_function)
        elif current_function:
            st.error("Unknown admin function")
        else:
            self._show_admin_home()
        
        return True

    def _show_admin_page_header(self, section=None):
        """Navigation, title block and session status for the full-screen dashboard."""
        # Leaving the dashboard, and - once inside a function - stepping back to the
        # function menu. Both live here rather than in the sidebar, which is where
        # every other full-screen admin page in CrewOps360 keeps them.
        nav_cols = st.columns([2, 2, 6])
        with nav_cols[0]:
            if st.button("← Back to Training & Events", key="training_admin_exit",
                         use_container_width=True):
                st.session_state.training_admin_show_function = False
                st.session_state.training_admin_current_function = None
                st.rerun()
        if section:
            with nav_cols[1]:
                if st.button("⬅️ Admin Menu", key="training_admin_back",
                             use_container_width=True):
                    st.session_state.training_admin_current_function = None
                    st.rerun()

        title = section[0] if section else "🛠️ Training Administration"
        subtitle = (section[2] if section
                    else "Enrollment, classes, training years and reporting")
        st.markdown(f"""
        <div style="text-align: center; padding: 1rem;">
            <h1 style="color: #9C27B0;">{title}</h1>
            <p style="color: #666; font-size: 1.1rem;">{subtitle}</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")

        status_cols = st.columns(4)
        with status_cols[0]:
            st.metric("Session Status", "🟢 Active")
        with status_cols[1]:
            st.metric("Time Remaining", f"{self.session_minutes_remaining():.0f} min")
        with status_cols[2]:
            if st.button("🔒 Logout", key="training_admin_logout_main",
                         use_container_width=True):
                self.logout_admin()
                st.rerun()
        st.markdown("---")

    def _show_admin_home(self):
        """The function menu, as a full-width grid of cards."""
        st.markdown("### 📊 Training Administrative Functions")
        st.caption("Everything below reports on the training year named above.")

        columns = st.columns(2)
        for index, (label, key, description) in enumerate(self.ADMIN_SECTIONS):
            with columns[index % 2]:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.caption(description)
                    if st.button("Open", key=f"training_admin_{key}",
                                 use_container_width=True):
                        st.session_state.training_admin_current_function = key
                        st.session_state.training_admin_show_function = True
                        st.rerun()

    # ========================================================================
    # TRAINING YEAR CONTEXT
    # ========================================================================

    def current_training_year(self):
        """The training year every admin function on screen is reporting on.

        Read off the enrollment manager rather than the database's active year:
        during a cutover the two differ, and what an admin needs to know is which
        year the numbers in front of them came from, not which one is current.
        """
        enrollment_manager = st.session_state.get('training_enrollment_manager')
        year = getattr(enrollment_manager, 'training_year', None)
        if year:
            return year
        return st.session_state.get('training_loaded_year')

    def year_filename_prefix(self):
        """`FY27_` for the front of an export filename, or '' if no year is set.

        Two years are open at once during a cutover; a download named only for the
        day it was taken gives no way to tell them apart afterwards.
        """
        from .admin_excel_functions import year_filename_prefix
        return year_filename_prefix(self.current_training_year())

    def _training_year_row(self, year_label=None):
        """The training_years row for the year on screen, or None."""
        unified_db = st.session_state.get('unified_db')
        if not unified_db:
            return None
        label = year_label or self.current_training_year()
        if not label:
            return None
        try:
            return unified_db.get_training_year(label)
        except Exception:
            return None

    def training_year_span(self, year_label=None):
        """(start, end) of the year on screen as dates, or (None, None).

        Admin date pickers default to this. Defaulting to today instead is why a
        report on a closed year came back empty and a report on next year's draft
        looked like nobody had signed up.
        """
        row = self._training_year_row(year_label) or {}
        span = []
        for key in ('start_date', 'end_date'):
            raw = (row.get(key) or '').strip()
            try:
                span.append(datetime.strptime(raw, '%Y-%m-%d').date())
            except (ValueError, AttributeError):
                span.append(None)
        return span[0], span[1]

    def default_report_range(self, default_days=30, year_label=None):
        """A date range to open a report on: today if the year is running, its own
        span otherwise.

        A closed year and a draft year both sit entirely in the past or entirely in
        the future, so 'today plus thirty days' finds nothing in either.
        """
        today = datetime.now(_eastern_tz).date()
        start, end = self.training_year_span(year_label)
        if start and end and start <= today <= end:
            return today, min(today + timedelta(days=default_days), end)
        if start and end:
            return start, min(start + timedelta(days=default_days), end)
        return today, today + timedelta(days=default_days)

    def _show_training_year_context(self):
        """Name the year the dashboard is reporting on, and let an admin change it.

        The admin dashboard returns before the staff year selector is ever drawn, so
        without this an admin has no way to tell whether a compliance report covers
        the year that just closed or the one that just opened - and no way to switch
        without leaving the dashboard entirely.
        """
        from .unified_database import (
            YEAR_STATUS_DRAFT, YEAR_STATUS_OPEN, YEAR_STATUS_READONLY,
            YEAR_STATUS_ARCHIVED,
        )

        unified_db = st.session_state.get('unified_db')
        current = self.current_training_year()
        if not unified_db or not current:
            return

        try:
            years = unified_db.get_admin_visible_training_years()
        except Exception as e:
            st.caption(f"📅 Reporting on **{current}** (year list unavailable: {e})")
            return

        labels = [y['year_label'] for y in years]
        row = next((y for y in years if y['year_label'] == current), None)
        status = (row or {}).get('status')
        badge = {
            YEAR_STATUS_DRAFT: "📝 draft — staff can't see it",
            YEAR_STATUS_OPEN: "🟢 open for signups",
            YEAR_STATUS_READONLY: "🔒 read-only — no enrolling or cancelling",
            YEAR_STATUS_ARCHIVED: "📦 archived — hidden from staff",
        }.get(status, status or 'unconfigured')
        if (row or {}).get('is_active'):
            badge = f"active, {badge}"

        col_year, col_state = st.columns([2, 3])
        with col_year:
            if len(labels) > 1:
                choice = st.selectbox(
                    "Reporting on training year",
                    options=labels,
                    index=labels.index(current) if current in labels else 0,
                    format_func=lambda label: next(
                        (y['label'] for y in years if y['year_label'] == label), label),
                    key="admin_training_year_selector",
                    help="Every report, roster and export on this dashboard covers "
                         "the year selected here. Admins see draft and archived "
                         "years too, which staff never do.",
                )
                if choice != current:
                    # The same session key the staff screen reads, so the choice
                    # holds when the admin leaves the dashboard; app.py rebuilds
                    # the roster and managers for the new year on the next run.
                    st.session_state.training_selected_year = choice
                    # The staff screen's own selector keeps its last value in
                    # widget state. Left alone, it reverts this choice the moment
                    # the admin steps back out of the dashboard.
                    st.session_state.pop('training_year_selector', None)
                    st.rerun()
            else:
                st.markdown(f"**Training year:** {current}")
        with col_state:
            st.markdown(f"**Status:** {badge}")
            start, end = self.training_year_span(current)
            if start and end:
                st.caption(f"Runs {start} to {end} · roster "
                           f"`{(row or {}).get('roster_filename') or 'not set'}`")

        if (row or {}).get('enrollment_count') == 0:
            st.info(
                f"{current} has no enrollments yet. Reports on this dashboard will "
                f"come back empty - that's the year, not a fault."
            )

    def _render_admin_function(self, function_key):
        """Render the selected admin function"""
        if function_key == "enrollment_reports":
            self._show_enrollment_reports()
        elif function_key == "manage_staff":
            self._show_manage_staff()
        elif function_key == "manage_classes":
            self._show_manage_classes()
        elif function_key == "build_classes":
            self._show_build_classes()
        elif function_key == "training_years":
            self._show_training_years()
        elif function_key == "data_management":
            self._show_data_management()
        elif function_key == "system_stats":
            self._show_system_stats()
        elif function_key == "database_maintenance":
            self._show_database_maintenance()
        elif function_key == "track_manager":  # Updated to match menu item
            self._show_track_status_manager()
        else:
            st.error("Unknown admin function")


    def _show_enrollment_reports(self):
        """Show enrollment reports functionality"""
        if self.excel_admin_functions:
            # Use enhanced reporting from ExcelAdminFunctions
            from .admin_excel_functions import enhance_admin_reports
            enhance_admin_reports(self, self.excel_admin_functions)
            # The enhanced function will replace this method
            self._show_enhanced_enrollment_reports()
        else:
            st.error("Admin functions not initialized properly")
    
    # REPLACE the existing _show_manage_staff method with this updated version:
    def _show_manage_staff(self):
        """Show staff management functionality - UPDATED with Tab 4"""
        st.subheader("👥 Training Staff Management")
        year = self.current_training_year()
        if year:
            st.caption(f"Compliance and availability are measured against **{year}** "
                       f"only. A staff member complete in one year is not complete "
                       f"in the other.")
        
        if not self.excel_admin_functions:
            st.error("Admin functions not initialized")
            return
        
        # Updated to include Tab 4 and Tab 5
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["👤 Staff Overview", "📊 Compliance Status", "📝 Assignments", "📅 Available Staff for Events", "👨‍🏫 Available Educators for Teaching"])        

        with tab1:
            # FIXED Tab 1 content (Staff Overview)
            st.write("### Staff Training Overview")
            
            try:
                compliance_df = self.excel_admin_functions.get_enrollment_compliance_report()
                
                if not compliance_df.empty:
                    # Summary metrics
                    total_staff = len(compliance_df)
                    complete_staff = len(compliance_df[compliance_df['Status'] == 'âœ… Complete'])
                    behind_staff = len(compliance_df[compliance_df['Status'] == 'ðŸ"´ Behind Schedule'])
                    
                    # FIX: Check if Completion Rate is already numeric or needs conversion
                    if compliance_df['Completion Rate'].dtype == 'object':
                        # It's a string with '%' - strip and convert
                        avg_completion = compliance_df['Completion Rate'].str.rstrip('%').astype(float).mean()
                    else:
                        # It's already numeric (0.0 to 1.0) - convert to percentage
                        avg_completion = compliance_df['Completion Rate'].mean() * 100
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Staff", total_staff)
                    with col2:
                        st.metric("Fully Complete", complete_staff)
                    with col3:
                        st.metric("Behind Schedule", behind_staff)
                    with col4:
                        st.metric("Avg Completion", f"{avg_completion:.1f}%")
                    
                    # Staff search and filter
                    st.write("### Staff Search")
                    search_term = st.text_input("Search staff by name:", "")
                    
                    filtered_df = compliance_df
                    if search_term:
                        filtered_df = compliance_df[
                            compliance_df['Staff Name'].str.contains(search_term, case=False, na=False)
                        ]
                    
                    # Format the Completion Rate column as percentage for display
                    display_df = filtered_df.copy()
                    display_df['Completion Rate'] = display_df['Completion Rate'].apply(lambda x: f"{x*100:.1f}%")
                    
                    st.dataframe(display_df, use_container_width=True)
                else:
                    st.info("No staff enrollment data available")
                    
            except Exception as e:
                st.error(f"Error loading staff data: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
        
        with tab2:
            # Existing Tab 2 content (Compliance Status)
            st.write("### Training Compliance Status")
            
            try:
                compliance_df = self.excel_admin_functions.get_enrollment_compliance_report()
                
                if not compliance_df.empty:
                    # Filter by compliance status
                    status_filter = st.selectbox(
                        "Filter by status:",
                        ["All", "✅ Complete", "🟡 Nearly Complete", "🟠 In Progress", "🔴 Behind Schedule"]
                    )
                    
                    if status_filter != "All":
                        filtered_df = compliance_df[compliance_df['Status'] == status_filter]
                    else:
                        filtered_df = compliance_df
                    
                    st.dataframe(filtered_df, use_container_width=True)
                    
                    # Export filtered results
                    if st.button("📥 Export Compliance Report"):
                        csv = filtered_df.to_csv(index=False)
                        st.download_button(
                            "Download CSV",
                            csv,
                            f"{self.year_filename_prefix()}training_compliance_{datetime.now(_eastern_tz).strftime('%Y%m%d')}.csv",
                            "text/csv"
                        )
                else:
                    st.info("No compliance data available")
                    
            except Exception as e:
                st.error(f"Error loading compliance data: {str(e)}")
        
        with tab3:
            # Existing Tab 3 content (Assignments)
            st.write("### Staff Class Assignments")
            st.info("🚧 **Coming Soon**: Bulk assignment management")
        
        with tab4:
            # NEW Tab 4 - Available Staff for Events
            self._show_available_staff_for_events()
        
        with tab5:
            # NEW Tab 5 - Available Educators for Teaching (Future Implementation)
            self._show_available_educators_for_teaching()

    def _show_available_staff_for_events(self):
        """Show available staff for events within date range - NEW TAB 4"""
        st.write("### 📅 Available Staff for Events")
        st.caption("Analyze staff availability for class enrollment within a date range")
        
        # Initialize the availability analyzer, or rebuild it when the year changed.
        # This object holds the roster, enrollment manager and track manager for one
        # training year. AdminAccess itself survives a year switch - app.py clears the
        # managers but not the admin instance - so a cached analyzer went on answering
        # for the year the admin had just switched away from.
        current_year = self.current_training_year()
        if (not getattr(self, 'availability_analyzer', None)
                or getattr(self, 'availability_analyzer_year', None) != current_year):
            try:
                from training_modules.availability_analyzer import AvailabilityAnalyzer
                
                # Get required components from session state
                unified_db = st.session_state.get('unified_db')
                excel_handler = st.session_state.get('training_excel_handler')
                enrollment_manager = st.session_state.get('training_enrollment_manager')
                track_manager = st.session_state.get('training_track_manager')
                
                if not all([unified_db, excel_handler, enrollment_manager]):
                    st.error("Required components not initialized. Please ensure training system is properly loaded.")
                    return
                
                self.availability_analyzer = AvailabilityAnalyzer(
                    unified_db, excel_handler, enrollment_manager, track_manager
                )
                self.availability_analyzer_year = current_year
                
            except ImportError as e:
                st.error(f"Could not import AvailabilityAnalyzer: {str(e)}")
                return
            except Exception as e:
                st.error(f"Error initializing AvailabilityAnalyzer: {str(e)}")
                return
        
        # Date range selection. Open on the year being viewed, not on today: a
        # closed year's classes are all in the past and a draft year's are all in
        # the future, so "today plus thirty days" reported nothing for either and
        # looked like an empty roster rather than an out-of-range window.
        st.markdown("#### 📅 Select Date Range")

        default_start, default_end = self.default_report_range()
        year_start, year_end = self.training_year_span()

        col1, col2 = st.columns(2)
        
        with col1:
            start_date = st.date_input(
                "Start Date",
                value=default_start,
                key="availability_start_date"
            )
        
        with col2:
            end_date = st.date_input(
                "End Date",
                value=default_end,
                key="availability_end_date"
            )
        
        # Validation
        if start_date > end_date:
            st.error("Start date must be before or equal to end date.")
            return

        # The roster loaded is the selected year's, so a range outside that year
        # finds nothing. Say which year the window is being measured against.
        current_year = self.current_training_year()
        if year_start and year_end and (start_date > year_end or end_date < year_start):
            st.warning(
                f"⚠️ This range falls outside **{current_year}** "
                f"({year_start} to {year_end}), so no classes will be found. "
                f"Change the range, or switch year at the top of the dashboard."
            )
        elif current_year:
            st.caption(f"Analyzing **{current_year}** enrollments and tracks.")
        
        # Options
        st.markdown("#### ⚙️ Analysis Options")
        
        col1, col2 = st.columns(2)
        
        with col1:
            include_assigned_only = st.checkbox(
                "Only analyze staff assigned to each class",
                value=True,
                help="If checked, only staff assigned to a class will be analyzed for availability"
            )
        
        with col2:
            include_already_enrolled = st.checkbox(
                "Include staff already enrolled",
                value=False,
                help="If checked, staff already enrolled will be shown in results"
            )
        
        # Generate report button
        if st.button("📊 Analyze Staff Availability", type="primary", use_container_width=True):
            
            # Convert dates to string format
            start_date_str = start_date.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')
            
            with st.spinner(f"Analyzing staff availability from {start_date_str} to {end_date_str}..."):
                try:
                    # Get availability report
                    availability_report = self.availability_analyzer.get_no_conflict_enrollment_availability(
                        start_date_str,
                        end_date_str,
                        include_assigned_only,
                        include_already_enrolled
                    )
                    
                    if not availability_report:
                        st.warning("No classes found in the selected date range or no staff assignments found.")
                        return
                    
                    # Display results
                    self._display_availability_results(availability_report, start_date_str, end_date_str)
                    
                except Exception as e:
                    st.error(f"Error generating availability report: {str(e)}")
                    import traceback
                    traceback.print_exc()

    def _display_availability_results(self, availability_report, start_date_str, end_date_str):
        """Display the availability analysis results with session-based structure"""
        
        st.markdown("---")
        st.markdown(f"### 📊 Availability Report: {start_date_str} to {end_date_str}")
        
        # Calculate summary metrics for session-based structure
        total_classes = len(availability_report)
        total_sessions = sum(len(sessions) for sessions in availability_report.values())
        total_available_staff = sum(
            sum(session_data['total_available'] for session_data in class_data.values())
            for class_data in availability_report.values()
        )
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Classes in Range", total_classes)
        with col2:
            st.metric("Total Sessions", total_sessions)
        with col3:
            st.metric("Total Available Assignments", total_available_staff)
        
        st.markdown("---")
        
        # Display results by class and session
        for class_name, class_sessions in availability_report.items():
            
            with st.expander(f"📚 **{class_name}** ({len(class_sessions)} sessions)", expanded=True):
                
                # Group sessions by date for better organization
                sessions_by_date = {}
                for session_key, session_data in class_sessions.items():
                    # Extract date from session key (format: "MM/DD/YYYY_...")
                    date_part = session_key.split('_')[0]
                    if date_part not in sessions_by_date:
                        sessions_by_date[date_part] = []
                    sessions_by_date[date_part].append((session_key, session_data))
                
                for date_str, date_sessions in sessions_by_date.items():
                    st.markdown(f"#### 📅 {date_str}")
                    
                    for session_key, session_data in date_sessions:
                        session_info = session_data['session_info']
                        available_staff = session_data['available_staff']
                        staff_details = session_data['staff_details']
                        
                        # Create session header with role indication
                        session_header = session_info['display_time']
                        if session_info.get('role_requirement'):
                            session_header += f" - {session_info['role_requirement']} Only"
                        
                        # Color coding based on availability
                        slots_remaining = session_data['slots_remaining']
                        if slots_remaining <= 0:
                            status_color = "🔴"
                            status_text = "FULL"
                        elif slots_remaining <= 2:
                            status_color = "🟡"
                            status_text = f"{slots_remaining} slots left"
                        else:
                            status_color = "🟢"
                            status_text = f"{slots_remaining} slots available"
                        
                        st.markdown(f"**{session_header}** {status_color} {status_text}")
                        
                        # Show session metrics in columns
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.write(f"**Capacity:** {session_data['class_capacity']}")
                        with col2:
                            st.write(f"**Enrolled:** {session_data['currently_enrolled']}")
                        with col3:
                            st.write(f"**Available Staff:** {session_data['total_available']}")
                        with col4:
                            if session_info.get('is_two_day'):
                                st.write("📄 **2-Day Class**")
                        
                        # Display available staff for this session
                        if staff_details:
                            st.markdown("**Available Staff for this Session:**")
                            
                            # Create a more compact display
                            staff_by_role = {}
                            for staff in staff_details:
                                role = staff['role']
                                if role not in staff_by_role:
                                    staff_by_role[role] = []
                                staff_by_role[role].append(staff)
                            
                            # Display staff grouped by role
                            for role, staff_list in staff_by_role.items():
                                if len(staff_by_role) > 1:  # Only show role if there are multiple roles
                                    st.write(f"*{role}:*")
                                
                                # Show staff names with warnings/notes - FIXED VERSION
                                for staff in staff_list:
                                    role_text = f" ({staff['role']})" if staff.get('role') and staff['role'] != 'General' else ""
                                    staff_display = f"• {staff['name']}{role_text}"
                                    
                                    # SINGLE SOURCE: Only show warnings from the warnings list
                                    # Remove the duplicate has_conflict check
                                    if staff.get('warnings'):
                                        staff_display += f" ⚠️ ({', '.join(staff['warnings'])})"
                                    
                                    # Keep notes if any
                                    if staff.get('notes'):
                                        staff_display += f" 📝 ({', '.join(staff['notes'])})"
                                    
                                    st.write(staff_display)

                        else:
                            if session_info.get('role_requirement'):
                                st.warning(f"No available {session_info['role_requirement']} staff for this session")
                            else:
                                st.warning("No available staff for this session")
                        
                        st.markdown("---")
        
        # Enhanced export section (rest of the method remains the same)
        st.markdown("### 📥 Export Options")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📊 Export Session Details", use_container_width=True):
                # Create detailed CSV with session breakdown
                session_data = []
                
                for class_name, class_sessions in availability_report.items():
                    for session_key, session_data_item in class_sessions.items():
                        session_info = session_data_item['session_info']
                        
                        # Extract date from session key
                        date_part = session_key.split('_')[0]
                        
                        for staff_info in session_data_item['staff_details']:
                            session_data.append({
                                'Class Name': class_name,
                                'Date': date_part,
                                'Session': session_info['display_time'],
                                'Role Requirement': session_info.get('role_requirement', 'Any'),
                                'Session Type': session_info['type'],
                                'Staff Name': staff_info['name'],
                                'Staff Role': staff_info['role'],
                                'Warnings': "; ".join(staff_info['warnings']) if staff_info['warnings'] else "None",
                                'Notes': "; ".join(staff_info['notes']) if staff_info['notes'] else "None",
                                'Session Capacity': session_data_item['class_capacity'],
                                'Currently Enrolled': session_data_item['currently_enrolled'],
                                'Slots Remaining': session_data_item['slots_remaining'],
                                'Is Two Day': session_info.get('is_two_day', False)
                            })
                
                if session_data:
                    session_df = pd.DataFrame(session_data)
                    csv_data = session_df.to_csv(index=False)
                    
                    filename = (f"{self.year_filename_prefix()}session_availability_report_"
                                f"{start_date_str}_{end_date_str}.csv")
                    
                    st.download_button(
                        "📥 Download Session Report",
                        csv_data,
                        filename,
                        "text/csv",
                        use_container_width=True
                    )
                    st.success(f"✅ Session report ready: {len(session_data)} staff-session records")
                else:
                    st.warning("No session data available for export.")
        
        with col2:
            if st.button("📋 Export Summary by Class", use_container_width=True):
                # Create summary CSV by class
                summary_data = []
                
                for class_name, class_sessions in availability_report.items():
                    # Group by date
                    dates_summary = {}
                    for session_key, session_data in class_sessions.items():
                        # Extract date from session key
                        date_part = session_key.split('_')[0]
                        if date_part not in dates_summary:
                            dates_summary[date_part] = {
                                'total_sessions': 0,
                                'total_capacity': 0,
                                'total_enrolled': 0,
                                'total_available_staff': 0,
                                'sessions_detail': []
                            }
                        
                        dates_summary[date_part]['total_sessions'] += 1
                        dates_summary[date_part]['total_capacity'] += session_data['class_capacity']
                        dates_summary[date_part]['total_enrolled'] += session_data['currently_enrolled']
                        dates_summary[date_part]['total_available_staff'] += session_data['total_available']
                        dates_summary[date_part]['sessions_detail'].append(session_data['session_info']['display_time'])
                    
                    for date_str, date_summary in dates_summary.items():
                        summary_data.append({
                            'Class Name': class_name,
                            'Date': date_str,
                            'Total Sessions': date_summary['total_sessions'],
                            'Sessions Detail': "; ".join(date_summary['sessions_detail']),
                            'Total Capacity': date_summary['total_capacity'],
                            'Total Enrolled': date_summary['total_enrolled'],
                            'Total Available Staff': date_summary['total_available_staff'],
                            'Total Slots Remaining': date_summary['total_capacity'] - date_summary['total_enrolled']
                        })
                
                if summary_data:
                    summary_df = pd.DataFrame(summary_data)
                    csv_data = summary_df.to_csv(index=False)
                    
                    filename = (f"{self.year_filename_prefix()}class_summary_report_"
                                f"{start_date_str}_{end_date_str}.csv")
                    
                    st.download_button(
                        "📥 Download Summary Report",
                        csv_data,
                        filename,
                        "text/csv",
                        use_container_width=True
                    )
                    st.success(f"✅ Summary report ready: {len(summary_data)} class-date records")
                else:
                    st.warning("No summary data available for export.")

        # Optional: Add filtering controls for large reports
        if total_sessions > 10:
            st.markdown("### 🔍 Filter Options")
            
            # Get all unique classes for filtering
            all_classes = list(availability_report.keys())
            selected_classes = st.multiselect(
                "Filter by Classes (leave empty to show all):",
                options=all_classes,
                default=[]
            )
            
            # Get all unique roles for filtering
            all_roles = set()
            for class_sessions in availability_report.values():
                for session_data in class_sessions.values():
                    for staff in session_data['staff_details']:
                        all_roles.add(staff['role'])
            
            selected_roles = st.multiselect(
                "Filter by Staff Roles (leave empty to show all):",
                options=sorted(list(all_roles)),
                default=[]
            )
            
            if selected_classes or selected_roles:
                st.info(f"Filters applied - showing filtered results above")
                # Note: In a full implementation, you'd re-run the display logic with filters
                # For now, this is just UI framework

    def _show_available_educators_for_teaching(self):
        """Show available educators for teaching within date range - NEW TAB 5 (Future Implementation)"""
        st.write("### 👨‍🏫 Available Educators for Teaching")
        st.caption("Analyze educator availability for classes requiring instruction within a date range")
        
        # Future implementation placeholder with UI framework
        st.info("🚧 **Coming Soon**: Educator availability analysis")
        
        st.markdown("""
        **Planned Features:**
        
        📋 **Educator Eligibility Analysis**
        - Staff authorized for educator roles (based on 'Educator AT' column)
        - Classes requiring educators (instructor count > 0)
        - Existing educator signups vs requirements
        
        📅 **Schedule Conflict Checking**
        - AT shifts allowed for educators (non-blocking)
        - Track conflicts with educator-specific rules
        - Overlap detection with student enrollments
        
        📊 **Availability Reporting**
        - Classes needing educator coverage
        - Available authorized staff by date
        - Educator workload distribution
        - Coverage gap identification
        
        📥 **Export Capabilities**
        - Available educator lists by class/date
        - Coverage gap reports
        - Educator assignment recommendations
        """)
        
        # Placeholder UI elements for future development
        st.markdown("---")
        st.markdown("#### 🎯 Preview Interface (Non-Functional)")
        
        # Mock date range selector
        col1, col2 = st.columns(2)
        with col1:
            placeholder_start = st.date_input(
                "Start Date (Preview)",
                value=datetime.now(_eastern_tz),
                disabled=True,
                help="Date range selection for educator availability analysis"
            )
        with col2:
            placeholder_end = st.date_input(
                "End Date (Preview)", 
                value=datetime.now(_eastern_tz) + timedelta(days=30),
                disabled=True,
                help="Date range selection for educator availability analysis"
            )
        
        # Mock options
        st.markdown("#### ⚙️ Analysis Options (Preview)")
        col1, col2 = st.columns(2)
        
        with col1:
            st.checkbox(
                "Only authorized educators",
                value=True,
                disabled=True,
                help="Filter to staff marked as 'Educator AT' in the roster"
            )
        
        with col2:
            st.checkbox(
                "Show educator workload balance",
                value=False,
                disabled=True,
                help="Include analysis of educator assignment distribution"
            )
        
        # Mock analysis button
        if st.button("📊 Analyze Educator Availability (Coming Soon)", disabled=True, use_container_width=True):
            st.info("This feature will be implemented in a future update.")
        
        # Show current educator-enabled classes for context
        st.markdown("---")
        st.markdown("#### 📚 Current Classes Requiring Educators")
        
        # Get actual classes that need educators
        try:
            if hasattr(self, 'excel_admin_functions') and self.excel_admin_functions:
                all_classes = self.excel_admin_functions.excel.get_all_classes()
                educator_classes = []
                
                for class_name in all_classes:
                    class_details = self.excel_admin_functions.excel.get_class_details(class_name)
                    if class_details:
                        instructor_count = class_details.get('instructors_per_day', 0)
                        try:
                            instructor_count = int(float(instructor_count)) if instructor_count else 0
                        except (ValueError, TypeError):
                            instructor_count = 0
                        
                        if instructor_count > 0:
                            educator_classes.append({
                                'Class Name': class_name,
                                'Educators Needed': instructor_count,
                                'Class Type': 'Staff Meeting' if 'SM' in class_name.upper() else 'Training'
                            })
                
                if educator_classes:
                    educator_df = pd.DataFrame(educator_classes)
                    st.dataframe(educator_df, use_container_width=True, hide_index=True)
                    st.info(f"Found {len(educator_classes)} classes that require educators")
                else:
                    st.info("No classes currently configured to require educators")
                    
        except Exception as e:
            st.error(f"Error loading educator class information: {str(e)}")
        
        # Implementation roadmap
        st.markdown("---")
        st.markdown("#### 🗺️ Implementation Roadmap")
        
        roadmap_items = [
            "✅ Tab 5 structure created",
            "🔄 Enhance `get_no_conflict_educator_availability()` function", 
            "🔄 Integrate educator authorization checking",
            "🔄 Add educator-specific conflict rules (AT allowed)",
            "🔄 Build educator workload analysis",
            "🔄 Create educator coverage gap reporting",
            "🔄 Add export functionality for educator reports"
        ]
        
        for item in roadmap_items:
            st.write(f"• {item}")

    # ========================================================================
    # BUILD CLASSES
    # ========================================================================

    def _show_build_classes(self):
        """Create a class, reconfigure one, or import a year's classes from a workbook.

        Classes used to be built in the roster workbook and read back on every render.
        They are held in the database now, so this is where a class comes from - and
        why a class can have any number of dates, and a date more than one location,
        neither of which the spreadsheet layout could express.
        """
        from training_modules import class_catalog as catalog
        from training_modules import class_editor_ui

        st.subheader("➕ Build Classes")

        year = self.current_training_year()
        if not year:
            st.error("No training year is selected, so there is nothing to add a "
                     "class to. Pick one at the top of the dashboard.")
            return

        unified_db = st.session_state.get('unified_db')
        writable = True
        if unified_db:
            try:
                writable = unified_db.is_training_year_writable(year)
            except Exception:
                writable = True

        st.caption(f"Classes belong to a training year. Everything below is **{year}** "
                   f"— switch year at the top of the dashboard to build another one's.")

        # A read-only or archived year refuses enrollment writes, and building classes
        # in one is almost always the wrong year selected rather than the intent.
        if not writable:
            row = self._training_year_row(year) or {}
            st.warning(
                f"⚠️ **{year} is {row.get('status') or 'not open'}.** Classes can "
                f"still be built here, but staff cannot enroll in them until the year "
                f"is set to Open in Training Admin > Training Years.")

        editing = st.session_state.get('training_class_editing')
        creating = st.session_state.get('training_class_creating', False)

        if creating or editing:
            self._show_class_editor(year, editing, class_editor_ui)
            return

        tab_list, tab_import = st.tabs(["📋 Classes", "📥 Import from a workbook"])

        with tab_list:
            self._show_class_list(year, catalog)

        with tab_import:
            self._show_class_import(year, catalog)

    def _show_class_editor(self, year, editing, class_editor_ui):
        """The create/edit form, with a way back to the class list."""
        if st.button("⬅️ Back to classes", key="class_form_back"):
            class_editor_ui.clear_draft()
            st.session_state.pop('training_class_editing', None)
            st.session_state.training_class_creating = False
            st.rerun()

        st.markdown(f"### {'Edit ' + editing if editing else 'New class'}")

        def leave_editor():
            st.session_state.pop('training_class_editing', None)
            st.session_state.training_class_creating = False
            # The catalog caches a class's details for the render it was read in;
            # after an edit that copy describes the class as it used to be.
            handler = st.session_state.get('training_excel_handler')
            if handler is not None and hasattr(handler, 'invalidate'):
                handler.invalidate()

        class_editor_ui.render_class_form(year, editing, on_saved=leave_editor)

    def _show_class_list(self, year, catalog):
        """Every class in the year, with what it holds and a way into the editor."""
        if st.button("➕ Create a new class", type="primary",
                     key="class_list_create"):
            st.session_state.training_class_creating = True
            st.session_state.pop('training_class_editing', None)
            st.rerun()

        class_names = catalog.get_class_names(year)
        if not class_names:
            st.info(
                f"{year} has no classes yet. Create one above, or import them from "
                f"that year's roster workbook on the Import tab.")
            return

        st.write(f"**{len(class_names)} class(es) in {year}**")

        for position, class_name in enumerate(class_names):
            record = catalog.load_class_for_editing(year, class_name)
            if not record:
                continue

            dates = record['dates']
            locations = sorted({option['location']
                                for entry in dates for option in entry['options']
                                if option['location']})
            multi_site = [entry['class_date'] for entry in dates
                          if len(entry['options']) > 1]

            with st.container(border=True):
                heading = st.columns([5, 1, 1])
                with heading[0]:
                    origin = ("imported from the workbook"
                              if record['source'] == 'import' else "built here")
                    st.markdown(f"**{class_name}**")
                    st.caption(
                        f"{len(dates)} date(s) · {len(record['assigned_staff'])} "
                        f"staff assigned · {origin}")
                with heading[1]:
                    if st.button("Edit", key=f"class_edit_{position}",
                                 use_container_width=True):
                        st.session_state.training_class_editing = class_name
                        st.session_state.training_class_creating = False
                        st.rerun()
                with heading[2]:
                    if st.button("Delete", key=f"class_del_{position}",
                                 use_container_width=True):
                        st.session_state['training_class_deleting'] = class_name
                        st.rerun()

                if dates:
                    first, last = dates[0]['class_date'], dates[-1]['class_date']
                    span = first if first == last else f"{first} – {last}"
                    st.caption(f"📅 {span}")
                if locations:
                    st.caption(f"📍 {', '.join(locations)}")
                if multi_site:
                    st.caption(f"🔀 {len(multi_site)} date(s) run at more than one "
                               f"location: {', '.join(multi_site)}")

                if st.session_state.get('training_class_deleting') == class_name:
                    self._confirm_class_delete(year, class_name, catalog)

    def _confirm_class_delete(self, year, class_name, catalog):
        """Ask before deleting, and say what the deletion leaves behind."""
        unified_db = st.session_state.get('unified_db')
        enrolled = 0
        if unified_db:
            try:
                enrolled = len(unified_db.get_class_enrollments(
                    class_name, training_year=year))
            except Exception:
                enrolled = 0

        if enrolled:
            st.error(
                f"**{class_name} has {enrolled} active enrollment(s) in {year}.** "
                f"Deleting the class does not cancel them — they stay on record, but "
                f"with no schedule behind them, so the staff who booked will see the "
                f"class as unconfigured. Cancel the enrollments first if that isn't "
                f"what you want.")
        else:
            st.warning(f"Delete **{class_name}** from {year}? This cannot be undone.")

        confirm_columns = st.columns([2, 2, 6])
        with confirm_columns[0]:
            if st.button("Yes, delete it", key="class_del_confirm",
                         use_container_width=True):
                try:
                    catalog.delete_class(year, class_name)
                    st.session_state.pop('training_class_deleting', None)
                    handler = st.session_state.get('training_excel_handler')
                    if handler is not None and hasattr(handler, 'invalidate'):
                        handler.invalidate()
                    st.success(f"Deleted {class_name}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not delete the class: {e}")
        with confirm_columns[1]:
            if st.button("Keep it", key="class_del_cancel",
                         use_container_width=True):
                st.session_state.pop('training_class_deleting', None)
                st.rerun()

    def _show_class_import(self, year, catalog):
        """Bring a fiscal year's classes in from its roster workbook, once."""
        st.write("### Import from a roster workbook")
        st.caption(
            "The app does not read the workbook to run — classes live in the "
            "database. This brings a spreadsheet's classes, dates and assignments "
            "in, which is how a year built outside the app gets started.")

        row = self._training_year_row(year) or {}
        default_name = row.get('roster_filename') or ''
        upload_folder = os.path.join('training', 'upload')

        available = []
        try:
            available = sorted(name for name in os.listdir(upload_folder)
                               if name.lower().endswith(('.xlsx', '.xlsm')))
        except OSError as e:
            st.error(f"Could not read {upload_folder}: {e}")
            return

        if not available:
            st.info(f"No workbooks in {upload_folder}.")
            return

        default_index = (available.index(default_name)
                         if default_name in available else 0)
        chosen = st.selectbox("Workbook", options=available, index=default_index,
                              key="class_import_file",
                              help=f"{year}'s registered roster is "
                                   f"'{default_name or 'not set'}'.")

        existing = catalog.get_class_names(year)
        overwrite = st.checkbox(
            f"Replace classes already in {year}", value=False,
            key="class_import_overwrite",
            help="Off, a class already in the catalog is left exactly as it is, so a "
                 "re-import adds what the workbook has gained without undoing edits "
                 "made here. On, the workbook wins — dates, settings and assignments "
                 "are all replaced.")

        if existing and overwrite:
            st.warning(
                f"⚠️ This will overwrite all {len(existing)} class(es) already in "
                f"{year}, including any dates or locations added in the app that the "
                f"workbook does not have.")

        if st.button("📥 Import", type="primary", key="class_import_run"):
            path = os.path.join(upload_folder, chosen)
            with st.spinner(f"Reading {chosen}…"):
                try:
                    report = catalog.import_workbook(path, year, overwrite=overwrite)
                except Exception as e:
                    st.error(f"Import failed: {e}")
                    return

            handler = st.session_state.get('training_excel_handler')
            if handler is not None and hasattr(handler, 'invalidate'):
                handler.invalidate()

            if report['imported']:
                st.success(f"Imported {len(report['imported'])} class(es) into {year}: "
                           f"{', '.join(report['imported'])}")
            if report['skipped']:
                st.info(f"Left {len(report['skipped'])} class(es) alone because they "
                        f"are already in {year}: {', '.join(report['skipped'])}. "
                        f"Tick the box above to replace them.")
            for warning in report['warnings']:
                st.warning(warning)
            if not report['imported'] and not report['skipped']:
                st.warning("Nothing was imported — no class columns were found on the "
                           "workbook's Class_Enrollment sheet.")

    def _show_manage_classes(self):
        """Show class management functionality"""
        st.subheader("📚 Training Class Management")
        year = self.current_training_year()
        if year:
            st.caption(f"Classes and rosters for **{year}**, from that year's roster "
                       f"workbook. Switch year at the top of the dashboard.")
        
        if not self.excel_admin_functions:
            st.error("Admin functions not initialized")
            return
        
        tab1, tab2, tab3, tab4 = st.tabs(["📋 Class Overview", "📊 Utilization", "📅 Schedules", "✏️ Edit Class Rosters"])
        
        with tab1:
            st.write("### Class Overview")
            
            try:
                # Get all classes and basic info
                all_classes = self.excel_admin_functions.excel.get_all_classes()
                
                if all_classes:
                    st.write(f"**Total Classes:** {len(all_classes)}")
                    
                    # Class selection for detailed view
                    selected_class = st.selectbox("Select class for details:", [""] + all_classes)
                    
                    if selected_class:
                        class_report = self.excel_admin_functions.get_individual_class_report(selected_class)
                        
                        if class_report:
                            # Class metrics
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Class Type", class_report['class_type'])
                            with col2:
                                st.metric("Total Capacity", class_report['overall_stats']['total_capacity'])
                            with col3:
                                st.metric("Total Enrolled", class_report['overall_stats']['total_enrolled'])
                            with col4:
                                utilization = class_report['overall_stats']['overall_utilization']
                                st.metric("Utilization", f"{utilization:.1f}%")
                            
                            # Export class roster
                            if st.button("📥 Export Class Roster"):
                                roster_df, title = self.excel_admin_functions.export_class_roster(selected_class)
                                csv = roster_df.to_csv(index=False)
                                st.download_button(
                                    "Download Roster",
                                    csv,
                                    f"{self.year_filename_prefix()}{selected_class.replace(' ', '_')}_roster.csv",
                                    "text/csv"
                                )
                else:
                    st.info("No classes found")
                    
            except Exception as e:
                st.error(f"Error loading class data: {str(e)}")
        
        with tab2:
            st.write("### Class Utilization Analysis")
            
            try:
                utilization_df = self.excel_admin_functions.get_class_utilization_report()
                
                if not utilization_df.empty:
                    # Summary metrics
                    avg_utilization = utilization_df['Utilization Rate'].str.rstrip('%').astype(float).mean()
                    nearly_full = len(utilization_df[utilization_df['Status'] == '🔴 Nearly Full'])
                    low_util = len(utilization_df[utilization_df['Status'] == '🟢 Low Utilization'])
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Avg Utilization", f"{avg_utilization:.1f}%")
                    with col2:
                        st.metric("Nearly Full", nearly_full)
                    with col3:
                        st.metric("Low Utilization", low_util)
                    
                    st.dataframe(utilization_df, use_container_width=True)
                else:
                    st.info("No utilization data available")
                    
            except Exception as e:
                st.error(f"Error loading utilization data: {str(e)}")

        with tab4:
            st.write("### Edit Class Rosters")
            st.info("Manage student enrollments and educator assignments for each class session")

            # A read-only or draft year refuses every write at the database, which
            # an admin only found out after filling in a form and submitting it.
            # Say it once, up front, where the roster is.
            unified_db = st.session_state.get('unified_db')
            year = self.current_training_year()
            if unified_db and year and not unified_db.is_training_year_writable(year):
                row = self._training_year_row(year) or {}
                st.warning(
                    f"⚠️ **{year} is {row.get('status') or 'not open'}.** Rosters below "
                    f"are read-only: adding and removing will be refused. Set the year "
                    f"to Open in Training Admin > Training Years to edit it, or switch "
                    f"year at the top of the dashboard."
                )

            try:
                # Get all classes
                all_classes = self.excel_admin_functions.excel.get_all_classes()

                if all_classes:
                    # Class selection dropdown
                    selected_class = st.selectbox(
                        "Select a class to edit:",
                        options=[""] + all_classes,
                        key="edit_roster_class_selector"
                    )

                    if selected_class:
                        # Get class dates/sessions
                        class_dates = self.excel_admin_functions.excel.get_class_dates(selected_class)
                        class_details = self.excel_admin_functions.excel.get_class_details(selected_class)

                        if class_dates and class_details:
                            st.markdown(f"**Class:** {selected_class}")
                            st.markdown(f"**Type:** {class_details.get('class_type', 'N/A')}")
                            st.markdown("---")

                            # Expand two-day classes to show both days
                            is_two_day = st.session_state.training_enrollment_manager._is_two_day_class(selected_class)
                            dates_to_display = []

                            for date in class_dates:
                                if is_two_day:
                                    # Get both days for two-day classes
                                    both_days = st.session_state.training_enrollment_manager._get_two_day_dates(date)
                                    dates_to_display.extend(both_days)
                                else:
                                    dates_to_display.append(date)

                            # Remove duplicates while preserving order
                            seen = set()
                            unique_dates = []
                            for date in dates_to_display:
                                if date not in seen:
                                    seen.add(date)
                                    unique_dates.append(date)

                            # Display each session/date
                            for date in unique_dates:
                                self._display_session_roster_editor(selected_class, date, class_details)
                        else:
                            st.warning("No sessions found for this class")
                else:
                    st.info("No classes found")

            except Exception as e:
                st.error(f"Error loading class roster editor: {str(e)}")
                import traceback
                st.code(traceback.format_exc())

    def _display_session_roster_editor(self, class_name, class_date, class_details):
        """Display roster editor for a single class session with add/remove capabilities"""

        # Create an expander for each session
        with st.expander(f"📅 {class_date}", expanded=False):
            # Get enrollments and educator signups for this session
            enrollment_manager = st.session_state.training_enrollment_manager
            educator_manager = st.session_state.training_educator_manager
            enrollments = enrollment_manager.db.get_class_enrollments(
                class_name, class_date, training_year=enrollment_manager.training_year
            )
            educator_signups = educator_manager.db.get_educator_signups_for_class(
                class_name, class_date, training_year=educator_manager.training_year
            )

            # Get class capacity
            capacity = class_details.get('capacity', 'N/A')

            # Filter to only count active records
            active_enrollments = [e for e in enrollments if e.get('status', 'active') == 'active']
            active_educator_signups = [s for s in educator_signups if s.get('status', 'active') == 'active']

            # Display capacity and enrollment count
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Capacity", capacity)
            with col2:
                st.metric("Students Enrolled", len(active_enrollments))
            with col3:
                st.metric("Educators Signed Up", len(active_educator_signups))

            st.markdown("---")

            # Create two columns for Students and Educators
            col_students, col_educators = st.columns(2)

            with col_students:
                st.markdown("### 👥 Enrolled Students")

                if active_enrollments:
                    # Group by role if needed
                    roles_present = set(e.get('role', 'General') for e in active_enrollments)

                    if len(roles_present) > 1 and 'General' not in roles_present:
                        # Display by role groups (Nurse, Medic, CCEMT)
                        for role in sorted(roles_present):
                            role_enrollments = [e for e in active_enrollments if e.get('role') == role]
                            if role_enrollments:
                                st.markdown(f"**{role}:**")
                                for enrollment in role_enrollments:
                                    self._display_enrollment_row_with_remove(enrollment)
                    else:
                        # Display all enrollments
                        for enrollment in active_enrollments:
                            self._display_enrollment_row_with_remove(enrollment)
                else:
                    st.info("No students enrolled")

                # Add new student form
                st.markdown("---")
                st.markdown("**➕ Add New Student**")
                self._display_add_student_form(class_name, class_date, class_details)

            with col_educators:
                st.markdown("### 👨‍🏫 Educator Signups")

                if active_educator_signups:
                    for signup in active_educator_signups:
                        self._display_educator_row_with_remove(signup)
                else:
                    st.info("No educators signed up")

                # Add new educator form
                st.markdown("---")
                st.markdown("**➕ Add New Educator**")
                self._display_add_educator_form(class_name, class_date)

    def _display_enrollment_row_with_remove(self, enrollment):
        """Display a single enrollment with remove button"""
        col1, col2 = st.columns([4, 1])

        with col1:
            # Display staff name and details
            display_text = enrollment['staff_name']

            # Add role if not General
            if enrollment.get('role') and enrollment['role'] != 'General':
                display_text += f" ({enrollment['role']})"

            # Add session time if applicable
            if enrollment.get('session_time'):
                display_text += f" - {enrollment['session_time']}"

            # Add meeting type for Staff Meetings
            if enrollment.get('meeting_type'):
                display_text += f" - {enrollment['meeting_type']}"

            st.write(display_text)

        with col2:
            # Remove button
            if st.button("🗑️", key=f"remove_enrollment_{enrollment['id']}", help="Remove enrollment"):
                if st.session_state.training_enrollment_manager.cancel_enrollment(enrollment['id']):
                    st.success(f"Removed {enrollment['staff_name']}")
                    st.rerun()
                else:
                    st.error("Failed to remove enrollment")

    def _display_educator_row_with_remove(self, signup):
        """Display a single educator signup with remove button"""
        col1, col2 = st.columns([4, 1])

        with col1:
            st.write(signup['staff_name'])

        with col2:
            # Remove button
            if st.button("🗑️", key=f"remove_educator_{signup['id']}", help="Remove educator"):
                if st.session_state.training_educator_manager.cancel_educator_signup(signup['id']):
                    st.success(f"Removed {signup['staff_name']}")
                    st.rerun()
                else:
                    st.error("Failed to remove educator")

    def _display_add_student_form(self, class_name, class_date, class_details):
        """Display form to add a new student enrollment with session availability info"""
        # Get all staff
        staff_list = self.excel_admin_functions.excel.get_staff_list()

        if not staff_list:
            st.warning("No staff found")
            return

        # Get available session options to show capacity
        session_options = st.session_state.training_enrollment_manager.get_available_session_options(
            class_name, class_date
        )

        # Create unique key for this form
        form_key = f"add_student_{class_name}_{class_date}".replace(" ", "_").replace("/", "_")

        with st.form(key=form_key):
            # Staff selection
            selected_staff = st.selectbox(
                "Select Staff Member",
                options=[""] + sorted(staff_list),
                key=f"{form_key}_staff"
            )

            # Initialize variables
            role = 'General'
            session_time = None
            meeting_type = None

            # Check for multi-session classes
            if session_options and len(session_options) > 0:
                # Check if this is truly a multi-session class or just has display info
                first_option_type = session_options[0].get('type', '')
                is_multi_session = first_option_type in ['nurse_medic_separate', 'regular']

                if is_multi_session:
                    # Multi-session class - show session options with capacity
                    st.markdown("**Available Sessions:**")

                    session_choices = []
                    for opt in session_options:
                        if opt.get('type') == 'nurse_medic_separate':
                            # Show separate options for nurse and medic
                            display_time = opt.get('display_time', opt.get('session_time'))
                            nurse_count = len(opt.get('nurses', []))
                            medic_count = len(opt.get('medics', []))
                            ccemt_count = len(opt.get('ccemts', []))

                            if opt.get('has_ccemt'):
                                session_choices.append(f"{display_time} - Nurse ({nurse_count}/1)")
                                session_choices.append(f"{display_time} - Medic ({medic_count}/1)")
                                session_choices.append(f"{display_time} - CCEMT ({ccemt_count}/1)")
                            else:
                                max_per_role = int(class_details.get('students_per_class', 21)) // 2
                                session_choices.append(f"{display_time} - Nurse ({nurse_count}/{max_per_role})")
                                session_choices.append(f"{display_time} - Medic ({medic_count}/{max_per_role})")
                        else:
                            # Regular session - show total enrollment
                            display_time = opt.get('display_time', opt.get('session_time'))
                            enrolled_count = len(opt.get('enrolled', []))
                            max_students = int(class_details.get('students_per_class', 21))
                            session_choices.append(f"{display_time} ({enrolled_count}/{max_students})")

                    if session_choices:
                        selected_option = st.selectbox(
                            "Select Session",
                            options=[""] + session_choices,
                            key=f"{form_key}_session_option"
                        )

                        # Parse the selected option to extract session_time and role
                        if selected_option:
                            # Extract session time from the display string
                            for opt in session_options:
                                display_time = opt.get('display_time', opt.get('session_time'))
                                if display_time in selected_option:
                                    session_time = opt.get('session_time')

                                    # Check if role is specified in selection
                                    if ' - Nurse' in selected_option:
                                        role = 'Nurse'
                                    elif ' - Medic' in selected_option:
                                        role = 'Medic'
                                    elif ' - CCEMT' in selected_option:
                                        role = 'CCEMT'
                                    break
                else:
                    # Single-session class with role separation - fall through to else block below
                    pass

            # For single-session classes (including two-day) and Staff Meetings
            if not session_options or len(session_options) == 0 or (session_options and session_options[0].get('type') not in ['nurse_medic_separate', 'regular']):
                class_type = class_details.get('class_type', '')

                # Check if this class has role-based enrollment
                if 'Nurse' in class_type or 'Medic' in class_type or 'CCEMT' in class_type:
                    # Show current enrollment by role
                    enrollment_manager = st.session_state.training_enrollment_manager
                    enrollments = enrollment_manager.db.get_class_enrollments(
                        class_name, class_date,
                        training_year=enrollment_manager.training_year
                    )
                    nurse_count = len([e for e in enrollments if e.get('role') == 'Nurse'])
                    medic_count = len([e for e in enrollments if e.get('role') == 'Medic'])
                    ccemt_count = len([e for e in enrollments if e.get('role') == 'CCEMT'])

                    has_ccemt = class_details.get('has_ccemt', 'No').lower() == 'yes'
                    if has_ccemt:
                        role_options = [
                            f"Nurse ({nurse_count}/1)",
                            f"Medic ({medic_count}/1)",
                            f"CCEMT ({ccemt_count}/1)"
                        ]
                    else:
                        max_per_role = int(class_details.get('students_per_class', 21)) // 2
                        role_options = [
                            f"Nurse ({nurse_count}/{max_per_role})",
                            f"Medic ({medic_count}/{max_per_role})"
                        ]

                    selected_role_option = st.selectbox(
                        "Select Role",
                        options=[""] + role_options,
                        key=f"{form_key}_role"
                    )

                    if selected_role_option:
                        if 'Nurse' in selected_role_option:
                            role = 'Nurse'
                        elif 'Medic' in selected_role_option:
                            role = 'Medic'
                        elif 'CCEMT' in selected_role_option:
                            role = 'CCEMT'

                # Meeting type (for Staff Meetings)
                if 'Staff Meeting' in class_name:
                    meeting_type = st.selectbox(
                        "Meeting Type",
                        options=["", "LIVE", "Virtual"],
                        key=f"{form_key}_meeting"
                    )

            # Submit button
            submitted = st.form_submit_button("➕ Add Student")

            if submitted:
                if not selected_staff:
                    st.error("Please select a staff member")
                elif 'Staff Meeting' in class_name and not meeting_type:
                    st.error("Please select meeting type")
                elif session_options and len(session_options) > 0 and session_options[0].get('type') in ['nurse_medic_separate', 'regular'] and not session_time:
                    st.error("Please select a session")
                else:
                    # Add the enrollment
                    result = st.session_state.training_enrollment_manager.enroll_staff(
                        staff_name=selected_staff,
                        class_name=class_name,
                        class_date=class_date,
                        role=role,
                        meeting_type=meeting_type,
                        session_time=session_time,
                        override_conflict=True,  # Admin can override conflicts
                        override_capacity=True   # Admin can override capacity limits
                    )

                    # Handle tuple return (success, message) or special case ("duplicate_found", enrollments)
                    if isinstance(result, tuple):
                        success, message = result
                        if success is True:
                            st.success(f"Added {selected_staff} to {class_name}")
                            st.rerun()
                        elif success == "duplicate_found":
                            st.warning(f"{selected_staff} is already enrolled in this class")
                        else:
                            st.error(f"Failed to add enrollment: {message}")
                    else:
                        st.error("Unexpected response from enrollment system")

    def _display_add_educator_form(self, class_name, class_date):
        """Display form to add a new educator signup with two-day class support"""
        # Get all staff
        staff_list = self.excel_admin_functions.excel.get_staff_list()

        if not staff_list:
            st.warning("No staff found")
            return

        # Check if this is a two-day class
        is_two_day = st.session_state.training_enrollment_manager._is_two_day_class(class_name)

        # Create unique key for this form
        form_key = f"add_educator_{class_name}_{class_date}".replace(" ", "_").replace("/", "_")

        with st.form(key=form_key):
            # Staff selection
            selected_staff = st.selectbox(
                "Select Educator",
                options=[""] + sorted(staff_list),
                key=f"{form_key}_staff"
            )

            # For two-day classes, allow selecting which day
            selected_date = class_date
            if is_two_day:
                both_days = st.session_state.training_enrollment_manager._get_two_day_dates(class_date)
                if len(both_days) == 2:
                    st.info("Note: For 2-day classes, educators can sign up for individual days")
                    day_options = [
                        f"Day 1 ({both_days[0]})",
                        f"Day 2 ({both_days[1]})"
                    ]
                    selected_day_option = st.selectbox(
                        "Select Day",
                        options=day_options,
                        key=f"{form_key}_day"
                    )

                    # Extract the date from the selection
                    if "Day 1" in selected_day_option:
                        selected_date = both_days[0]
                    else:
                        selected_date = both_days[1]

            # Submit button
            submitted = st.form_submit_button("➕ Add Educator")

            if submitted:
                if not selected_staff:
                    st.error("Please select a staff member")
                else:
                    # Add the educator signup
                    result = st.session_state.training_educator_manager.signup_as_educator(
                        staff_name=selected_staff,
                        class_name=class_name,
                        class_date=selected_date,  # Use selected_date (which may be day 1 or day 2)
                        override_conflict=True,  # Admin can override conflicts
                        override_capacity=True   # Admin can override capacity limits
                    )

                    # Handle tuple return (success, message)
                    if isinstance(result, tuple):
                        success, message = result
                        if success:
                            day_label = f" for {selected_date}" if is_two_day else ""
                            st.success(f"Added {selected_staff} as educator{day_label}")
                            st.rerun()
                        else:
                            st.error(f"Failed to add educator: {message}")
                    else:
                        st.error("Unexpected response from educator system")

    # ========================================================================
    # DATA EXPORT / STATISTICS / MAINTENANCE
    #
    # These three were on the admin menu but had no implementation behind them,
    # so opening any of them raised AttributeError. They are written year-scoped
    # from the start: an export that doesn't name its year and a statistic that
    # silently spans two of them are both worse than useless during a cutover.
    # ========================================================================

    def _show_data_management(self):
        """Export one training year's enrollment and educator data."""
        st.subheader("📄 Data Export")

        unified_db = st.session_state.get('unified_db')
        if not unified_db:
            st.error("Training database not initialized")
            return

        year = self.current_training_year()
        if not year:
            st.error("No training year selected.")
            return

        start, end = self.training_year_span(year)
        st.caption(
            f"Exports **{year}**"
            + (f", which runs {start} to {end}. " if start and end else ". ")
            + "Switch year at the top of the dashboard to export another."
        )

        try:
            enrollments, signups = unified_db.get_year_export_rows(year)
        except Exception as e:
            st.error(f"Could not read {year}'s data: {e}")
            return

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Active enrollments", len(enrollments))
        with col2:
            st.metric("Active educator signups", len(signups))

        if not enrollments and not signups:
            st.info(f"{year} has no active enrollments or educator signups to export.")
            return

        enrollments_df = pd.DataFrame(enrollments)
        signups_df = pd.DataFrame(signups)

        from .admin_excel_functions import date_column_config, sortable_dates
        class_date_cols = ['class_date']

        tab_enrol, tab_edu = st.tabs(["👥 Enrollments", "👨‍🏫 Educator Signups"])
        with tab_enrol:
            if enrollments_df.empty:
                st.info(f"No active enrollments in {year}.")
            else:
                st.dataframe(
                    sortable_dates(enrollments_df, class_date_cols),
                    use_container_width=True,
                    column_config=date_column_config(class_date_cols),
                )
        with tab_edu:
            if signups_df.empty:
                st.info(f"No active educator signups in {year}.")
            else:
                st.dataframe(
                    sortable_dates(signups_df, class_date_cols),
                    use_container_width=True,
                    column_config=date_column_config(class_date_cols),
                )

        st.markdown("---")
        stamp = datetime.now(_eastern_tz).strftime('%Y%m%d_%H%M')
        prefix = self.year_filename_prefix()

        col_csv, col_xlsx = st.columns(2)
        with col_csv:
            if not enrollments_df.empty:
                st.download_button(
                    "📥 Enrollments (CSV)",
                    enrollments_df.to_csv(index=False),
                    f"{prefix}enrollments_{stamp}.csv",
                    "text/csv",
                    use_container_width=True,
                )
            if not signups_df.empty:
                st.download_button(
                    "📥 Educator signups (CSV)",
                    signups_df.to_csv(index=False),
                    f"{prefix}educator_signups_{stamp}.csv",
                    "text/csv",
                    use_container_width=True,
                )
        with col_xlsx:
            try:
                from io import BytesIO
                from .admin_excel_functions import _write_report_year_sheet

                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    # Both sheets are always written, empty or not, so the workbook
                    # has the same shape whichever year it covers.
                    (enrollments_df if not enrollments_df.empty
                     else pd.DataFrame(columns=['staff_name', 'class_name', 'class_date'])
                     ).to_excel(writer, sheet_name='Enrollments', index=False)
                    (signups_df if not signups_df.empty
                     else pd.DataFrame(columns=['staff_name', 'class_name', 'class_date'])
                     ).to_excel(writer, sheet_name='Educator Signups', index=False)
                    _write_report_year_sheet(writer, year, 'Training data export')
                st.download_button(
                    "📊 Both sheets (Excel)",
                    output.getvalue(),
                    f"{prefix}training_data_{stamp}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Could not build the workbook: {e}")

        st.markdown("---")
        self._show_roster_export()

    def _show_roster_export(self):
        """A whole fiscal year's training rosters as one Excel workbook.

        Separate from the raw data export above, and with its own year picker: this is
        the one people print and mail around, and wanting last year's copy is not a
        reason to move the whole dashboard onto last year.
        """
        from . import roster_export

        st.subheader("📚 Training rosters (Excel)")
        st.caption(
            "One workbook per fiscal year: a summary of every class, the rosters of "
            "who enrolled and where, educator signups, the full schedule, and the "
            "staff-by-class assignment grid.")

        unified_db = st.session_state.get('unified_db')
        if not unified_db:
            st.error("Training database not initialized")
            return

        try:
            years = [row['year_label']
                     for row in unified_db.get_admin_visible_training_years()]
        except Exception as e:
            st.error(f"Could not list the training years: {e}")
            return

        current = self.current_training_year()
        if current and current not in years:
            years.insert(0, current)
        if not years:
            st.info("No training years are configured yet.")
            return

        controls = st.columns([2, 3, 2])
        with controls[0]:
            chosen = st.selectbox(
                "Fiscal year", options=years,
                index=years.index(current) if current in years else 0,
                key="roster_export_year")
        with controls[1]:
            per_class = st.checkbox(
                "Add a printable sheet per class", value=False,
                key="roster_export_per_class",
                help="A tab for each class with its schedule and its roster. Handy "
                     "for printing; a year with twenty classes gains twenty tabs.")
        with controls[2]:
            st.write("")
            build = st.button("📊 Build workbook", type="primary",
                              use_container_width=True, key="roster_export_build")

        class_count = len(catalog.get_class_names(chosen))
        if not class_count:
            st.warning(
                f"{chosen} has no classes, so its workbook would be empty. Build them "
                f"in Training Admin > Build Classes, or import that year's roster "
                f"workbook there.")

        # Built on demand rather than on every render: a year with twenty classes is a
        # few hundred queries, and a download button needs its bytes up front.
        if build:
            with st.spinner(f"Building {chosen}'s rosters…"):
                try:
                    st.session_state['roster_export_file'] = {
                        'year': chosen,
                        'per_class': per_class,
                        'bytes': roster_export.build_roster_workbook(
                            chosen, unified_db=unified_db,
                            per_class_sheets=per_class),
                        'built': datetime.now(_eastern_tz).strftime('%I:%M %p'),
                    }
                except Exception as e:
                    st.session_state.pop('roster_export_file', None)
                    st.error(f"Could not build the workbook: {e}")

        ready = st.session_state.get('roster_export_file')
        if ready:
            stale = (ready['year'] != chosen or ready['per_class'] != per_class)
            if stale:
                st.info(
                    f"The workbook below is **{ready['year']}**"
                    + (" with per-class sheets" if ready['per_class'] else "")
                    + ", built at {}. Press Build workbook again for the current "
                      "selection.".format(ready['built']))
            stamp = datetime.now(_eastern_tz).strftime('%Y%m%d_%H%M')
            prefix = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(ready['year']).strip())
            st.download_button(
                f"📥 Download {ready['year']} training rosters",
                ready['bytes'],
                f"{prefix}_training_rosters_{stamp}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="roster_export_download")

    def _show_system_stats(self):
        """Usage statistics for the selected year, and across every year."""
        st.subheader("📊 System Statistics")

        unified_db = st.session_state.get('unified_db')
        if not unified_db:
            st.error("Training database not initialized")
            return

        year = self.current_training_year()

        try:
            stats = unified_db.get_enrollment_stats(year)
        except Exception as e:
            st.error(f"Could not read statistics: {e}")
            return

        st.markdown(f"#### {stats['training_year']}")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Enrollments", stats['total_enrollments'])
        with col2:
            st.metric("Educator signups", stats['total_educator_signups'])
        with col3:
            st.metric("Conflict overrides", stats['total_conflicts'])
        with col4:
            st.metric("Added today", stats['recent_enrollments']
                      + stats['recent_educator_signups'])
        st.caption(f"As of {stats['current_time_eastern']}")

        st.markdown("---")
        st.markdown("#### Every training year")
        st.caption(
            "A single year's totals can't tell you whether the outgoing year's tail "
            "or the incoming year's opening moved. This is the same data split by "
            "year, including any year with rows but no config row of its own."
        )

        try:
            per_year = unified_db.get_enrollment_stats_by_year()
        except Exception as e:
            st.error(f"Could not read the per-year breakdown: {e}")
            return

        if not per_year:
            st.info("No enrollments recorded in any year yet.")
            return

        breakdown = pd.DataFrame([{
            'Training Year': row['training_year'],
            'Status': ('active, ' if row['is_active'] else '') + row['status'],
            'Staff': row['staff'],
            'Enrollments': row['enrollments'],
            'Educator Signups': row['educator_signups'],
            'Conflict Overrides': row['conflict_overrides'],
        } for row in per_year])
        st.dataframe(breakdown, use_container_width=True, hide_index=True)

        unconfigured = [r['training_year'] for r in per_year if not r['configured']]
        if unconfigured:
            st.warning(
                "⚠️ These years have enrollments but no row in Training Years, so "
                "nobody can see or manage them: **" + "**, **".join(unconfigured)
                + "**. Create the year in Training Admin > Training Years, or "
                "correct the stamps with `scripts/repair_training_year_stamps.py`."
            )

    def _show_database_maintenance(self):
        """Integrity checks and the audit trail for the selected training year."""
        st.subheader("🗂️ Database Maintenance")

        unified_db = st.session_state.get('unified_db')
        if not unified_db:
            st.error("Training database not initialized")
            return

        year = self.current_training_year()
        if not year:
            st.error("No training year selected.")
            return

        tab_health, tab_audit = st.tabs(["🩺 Data Health", "📜 Audit Trail"])

        with tab_health:
            st.caption(
                f"Checks that only matter once more than one year exists. Each one "
                f"was harmless with a single year and becomes a wrong number with two."
            )
            try:
                report = unified_db.get_training_year_data_health(year)
            except Exception as e:
                st.error(f"Could not run the checks: {e}")
                return

            clean = True

            unstamped = (report['unstamped_enrollments']
                         + report['unstamped_educator_signups'])
            if unstamped:
                from .unified_database import LEGACY_TRAINING_YEAR
                clean = False
                st.error(
                    f"❌ {report['unstamped_enrollments']} enrollment(s) and "
                    f"{report['unstamped_educator_signups']} educator signup(s) carry "
                    f"no training year. Every query reads them as "
                    f"{LEGACY_TRAINING_YEAR}, so they show up in that year whatever "
                    f"year they really belong to. Run "
                    f"`python scripts/repair_training_year_stamps.py` to stamp them."
                )
            else:
                st.success("✅ Every enrollment and educator signup carries a training year.")

            if report['orphaned_years']:
                clean = False
                detail = ", ".join(f"{label} ({n} row{'' if n == 1 else 's'})"
                                   for label, n in report['orphaned_years'].items())
                st.error(
                    f"❌ Enrollments are stamped with years that have no Training "
                    f"Years row: {detail}. Nobody can see or manage them until the "
                    f"year is created."
                )
            else:
                st.success("✅ Every enrollment's training year is a configured year.")

            out_of_span = report['out_of_span']
            if out_of_span:
                clean = False
                st.warning(
                    f"⚠️ {len(out_of_span)} active enrollment(s) in **{year}** fall "
                    f"outside its span ({report['start_date']} to {report['end_date']}). "
                    f"Either the year's dates are wrong, or these belong to the "
                    f"neighbouring year — during a cutover it is easy to enrol "
                    f"someone into the year that happened to be selected."
                )
                from .admin_excel_functions import date_column_config, sortable_dates
                st.dataframe(
                    sortable_dates(pd.DataFrame(out_of_span), ['class_date']),
                    use_container_width=True, hide_index=True,
                    column_config=date_column_config(['class_date']),
                )
            elif report.get('span_readable'):
                st.success(
                    f"✅ Every {year} enrollment falls inside {report['start_date']} "
                    f"to {report['end_date']}."
                )
            else:
                clean = False
                st.warning(
                    f"⚠️ {year} has no readable start and end date "
                    f"({report['start_date'] or 'not set'} to "
                    f"{report['end_date'] or 'not set'}), so its enrollments can't "
                    f"be checked against its own span — and it will never "
                    f"auto-close. Set them as YYYY-MM-DD in Training Admin > "
                    f"Training Years."
                )

            if clean:
                st.info(f"{year} is clean: nothing to correct.")

        with tab_audit:
            st.caption(
                f"Enrollment and educator activity recorded against **{year}**. "
                f"Audit rows written before years were tracked are read as FY26."
            )
            try:
                entries = unified_db.get_year_audit_trail(year, limit=200)
            except Exception as e:
                st.error(f"Could not read the audit trail: {e}")
                return

            if not entries:
                st.info(f"No recorded activity for {year} yet.")
                return

            audit_df = pd.DataFrame([{
                'When': e.get('action_date') or '',
                'Action': e.get('action'),
                'Staff': e.get('staff_name'),
                'Class': e.get('class_name'),
                'Class Date': e.get('class_date'),
                'Role': e.get('role') or '',
            } for e in entries])
            from .admin_excel_functions import date_column_config, sortable_dates
            st.dataframe(
                sortable_dates(audit_df, ['Class Date']),
                use_container_width=True, hide_index=True,
                column_config=date_column_config(['Class Date']),
            )
            st.download_button(
                "📥 Download audit trail (CSV)",
                audit_df.to_csv(index=False),
                f"{self.year_filename_prefix()}audit_trail_"
                f"{datetime.now(_eastern_tz).strftime('%Y%m%d_%H%M')}.csv",
                "text/csv",
            )

    def _show_training_years(self):
        """Manage fiscal-year training cohorts: which Excel roster is active, which
        Track Bidding cohort it corresponds to, and promoting the next year live."""
        st.subheader("🗓️ Training Years")
        st.caption(
            "Each training year points at its own roster file in training/upload/ and can be "
            "linked to a Track Bidding cohort. Promoting a year to active switches which roster "
            "the registration screen opens on; the outgoing year stays open until you close it "
            "or its end date passes."
        )
        with st.expander("What the statuses mean", expanded=False):
            st.markdown(
                "- **Draft** - you're still building it. Admin-only; staff never see it.\n"
                "- **Open** - accepting signups. More than one year can be open at once, "
                "which is what lets the outgoing year finish while the new one starts.\n"
                "- **Read-only** - staff can see their enrollments but can't add or cancel. "
                "A year that isn't active moves here on its own once its end date passes.\n"
                "- **Archived** - hidden from staff entirely. Admin reporting only."
            )

        from .unified_database import (
            YEAR_STATUS_DRAFT, YEAR_STATUS_OPEN, YEAR_STATUS_READONLY,
            YEAR_STATUS_ARCHIVED, YEAR_STATUSES,
        )

        unified_db = st.session_state.get('unified_db')
        if not unified_db:
            st.error("Training database not initialized")
            return

        # Track cohorts are a soft reference only (no enforced FK) - just for the dropdown
        try:
            from modules.db_utils import get_all_track_configs
            track_options = [""] + [c['track_name'] for c in get_all_track_configs()]
        except Exception:
            track_options = [""]

        all_years = unified_db.get_all_training_years()

        st.markdown("### Existing Training Years")
        if not all_years:
            st.info("No training years configured yet.")

        status_labels = {
            YEAR_STATUS_DRAFT: ("📝", "Draft"),
            YEAR_STATUS_OPEN: ("🟢", "Open for signups"),
            YEAR_STATUS_READONLY: ("🔒", "Read-only"),
            YEAR_STATUS_ARCHIVED: ("📦", "Archived"),
        }

        for ty in all_years:
            label = ty['year_label']
            is_active = bool(ty['is_active'])
            status = ty.get('status') or YEAR_STATUS_DRAFT
            icon, status_text = status_labels.get(status, ("⚪", status))
            header = f"{icon} {label} - {status_text}"
            if is_active:
                header += " (Active)"
            with st.expander(header, expanded=False):
                if is_active:
                    st.info(
                        "This is the active year - the one the registration screen opens on. "
                        "Promote another year before closing it."
                    )
                # Classes come from the catalog, not this file. The filename is kept
                # because it names the workbook the year's classes were imported from
                # and the one Build Classes offers first, so a missing file is worth
                # noting and no longer worth an error.
                class_count = len(catalog.get_class_names(label))
                if class_count:
                    st.success(f"{class_count} class(es) configured for {label}")
                else:
                    st.warning(
                        f"{label} has no classes yet. Build them in Training Admin > "
                        f"Build Classes, or import a roster workbook there.")

                roster_filename = ty.get('roster_filename') or ""
                if roster_filename:
                    roster_path = os.path.join('training', 'upload', roster_filename)
                    if not os.path.exists(roster_path):
                        st.caption(f"Import source `{roster_path}` is not on disk. "
                                   f"That only matters if you want to import from it.")

                u_roster = st.text_input(
                    "Roster filename (in training/upload/)", value=roster_filename,
                    key=f"ty_roster_{label}",
                    help="The workbook this year's classes are imported from. The app "
                         "does not read it to run - classes are held in the database."
                )
                current_track = ty.get('linked_track_name') or ""
                track_index = track_options.index(current_track) if current_track in track_options else 0
                u_track = st.selectbox(
                    "Linked track cohort", options=track_options, index=track_index,
                    key=f"ty_track_{label}",
                    help="Which Track Bidding cohort this year's classes are checked "
                         "against for schedule conflicts. Set this: without it, conflict "
                         "checking uses whichever cohort is active today, which is the "
                         "wrong one for a year that has closed."
                )
                # Linking a cohort only changes conflict checking if that cohort has
                # tracks in it. A bid still in progress mostly lives in bid_drafts,
                # which conflict checking can't see, so say what the link will
                # actually find rather than letting it look connected and do nothing.
                if u_track:
                    try:
                        from modules.db_utils import get_cohort_track_coverage
                        coverage = get_cohort_track_coverage(u_track)
                    except Exception as cov_err:
                        coverage = None
                        st.caption(f"Could not read {u_track}'s track counts: {cov_err}")
                    if coverage is not None:
                        if coverage['submitted'] == 0:
                            st.warning(
                                f"⚠️ No tracks are stored under **{u_track}** yet"
                                + (f" ({coverage['drafts']} staff have an unsubmitted "
                                   f"draft bid)" if coverage['drafts'] else "")
                                + f". Conflict checking for {label} will fall back to "
                                  f"the currently active cohort until bids are "
                                  f"submitted."
                            )
                        else:
                            note = (f"**{u_track}** holds tracks for "
                                    f"{coverage['submitted']} staff")
                            if coverage['active']:
                                note += f" (active cohort: {coverage['active']})"
                            if coverage['drafts']:
                                note += (f"; {coverage['drafts']} more have an "
                                         f"unsubmitted draft bid")
                            note += (". Staff with no track in this cohort get no "
                                     "conflict checking in this year.")
                            st.caption(note)
                u_pattern = st.text_input(
                    "Track pattern start — 'Sun A 1' (YYYY-MM-DD)",
                    value=ty.get('pattern_start_date') or "",
                    key=f"ty_pattern_{label}",
                    help="The date the linked track cohort's 42-day pattern counts as "
                         "'Sun A 1' (FY26: 2025-09-14, FY27: 2026-09-27). This is the "
                         "track grid, not the training year — verify it against the bid "
                         "grid, because a wrong anchor shifts every conflict check by "
                         "days without reporting anything."
                )
                st.markdown("**Training year span** (10/1 – 9/30)")
                col1, col2 = st.columns(2)
                with col1:
                    u_start = st.text_input(
                        "Start date (YYYY-MM-DD)", value=ty.get('start_date') or "",
                        key=f"ty_start_{label}",
                        help="When this training year opens. Calendar-based (10/1), "
                             "which is a few days off the track cohort's start."
                    )
                with col2:
                    u_end = st.text_input(
                        "End date (YYYY-MM-DD)", value=ty.get('end_date') or "",
                        key=f"ty_end_{label}",
                        help="When this training year ends (9/30). The year flips to "
                             "read-only on its own the day after this date, so an "
                             "incorrect value freezes it early or leaves it open."
                    )

                # An end date before the year's last class means auto-close would
                # freeze the year while classes are still being taught.
                last_class = _year_last_class_date(label)
                if last_class:
                    st.caption(f"Last class in this year: **{last_class}**")
                    end_raw = (u_end or "").strip()
                    if end_raw:
                        try:
                            end_parsed = datetime.strptime(end_raw, '%Y-%m-%d').date()
                        except ValueError:
                            st.warning(
                                f"End date '{end_raw}' isn't a valid YYYY-MM-DD "
                                f"date, so this year will never auto-close."
                            )
                        else:
                            if end_parsed < last_class:
                                st.warning(
                                    f"⚠️ This year ends **{end_parsed}** but has "
                                    f"classes through **{last_class}**. "
                                    f"It will go read-only while "
                                    f"{(last_class - end_parsed).days} more day(s) "
                                    f"of classes are still scheduled — staff won't "
                                    f"be able to enroll in or cancel them. Either "
                                    f"extend the end date past the last class, or "
                                    f"move those dates into the next year."
                                )

                if st.button("Save", key=f"ty_save_{label}"):
                    ok, msg = unified_db.update_training_year(
                        label, roster_filename=u_roster.strip(),
                        linked_track_name=u_track, start_date=u_start.strip(),
                        end_date=u_end.strip(), pattern_start_date=u_pattern.strip()
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

                if not is_active:
                    st.markdown("---")
                    st.markdown("**Status**")
                    status_options = [s for s in YEAR_STATUSES]
                    new_status = st.selectbox(
                        "Lifecycle status",
                        options=status_options,
                        index=status_options.index(status) if status in status_options else 0,
                        format_func=lambda s: status_labels.get(s, ("", s))[1],
                        key=f"ty_status_{label}",
                        label_visibility="collapsed",
                    )
                    if new_status != status:
                        if st.button(f"Set {label} to {status_labels.get(new_status, ('', new_status))[1]}",
                                     key=f"ty_status_set_{label}"):
                            ok, msg = unified_db.set_training_year_status(label, new_status)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

                if not is_active:
                    st.markdown("---")
                    promote_col, delete_col = st.columns(2)

                    with promote_col:
                        if st.button(f"Promote {label} to Active", key=f"ty_promote_{label}", type="primary"):
                            st.session_state[f'confirm_ty_promote_{label}'] = True

                        if st.session_state.get(f'confirm_ty_promote_{label}', False):
                            st.warning(
                                f"This switches the registration screen to {label}'s roster "
                                f"for all staff. Are you sure?"
                            )
                            close_previous = st.checkbox(
                                "Also make the outgoing year read-only right away",
                                value=False, key=f"ty_close_prev_{label}",
                                help="Leave this unchecked during a normal cutover: the "
                                     "outgoing fiscal year still has months of classes left, "
                                     "and staff need to cancel and re-book in it. It closes "
                                     "on its own once its end date passes."
                            )
                            yc, nc = st.columns(2)
                            with yc:
                                if st.button("Yes, Promote", key=f"ty_promote_yes_{label}"):
                                    ok, msg = unified_db.promote_training_year_to_active(
                                        label, close_previous=close_previous)
                                    st.session_state[f'confirm_ty_promote_{label}'] = False
                                    if ok:
                                        # Force the training subsystem to reload against the
                                        # newly active roster instead of serving stale cached
                                        # Excel/enrollment objects for the rest of the session.
                                        for key in ('training_excel_handler', 'training_track_manager',
                                                    'training_enrollment_manager', 'training_educator_manager',
                                                    'training_excel_admin_functions'):
                                            st.session_state.pop(key, None)
                                        st.success(msg)
                                    else:
                                        st.error(msg)
                                    st.rerun()
                            with nc:
                                if st.button("Cancel", key=f"ty_promote_no_{label}"):
                                    st.session_state[f'confirm_ty_promote_{label}'] = False
                                    st.rerun()

                    with delete_col:
                        if st.button(f"Delete {label}", key=f"ty_delete_{label}"):
                            st.session_state[f'confirm_ty_delete_{label}'] = True

                        if st.session_state.get(f'confirm_ty_delete_{label}', False):
                            st.error(f"Delete training year {label}? This cannot be undone.")
                            yc, nc = st.columns(2)
                            with yc:
                                if st.button("Yes, Delete", key=f"ty_delete_yes_{label}"):
                                    ok, msg = unified_db.delete_training_year(label)
                                    st.session_state[f'confirm_ty_delete_{label}'] = False
                                    if ok:
                                        st.success(msg)
                                    else:
                                        st.error(msg)
                                    st.rerun()
                            with nc:
                                if st.button("Cancel", key=f"ty_delete_no_{label}"):
                                    st.session_state[f'confirm_ty_delete_{label}'] = False
                                    st.rerun()

        st.markdown("---")
        st.markdown("### Create New Training Year")
        with st.form("create_training_year_form"):
            new_label = st.text_input("Year label (e.g. FY27)")
            new_roster = st.text_input(
                "Roster filename (in training/upload/)",
                placeholder="FY27 Education Classes Roster.xlsx"
            )
            new_track = st.selectbox("Linked track cohort", options=track_options, key="new_ty_track")
            new_pattern = st.text_input(
                "Track pattern start — 'Sun A 1' (YYYY-MM-DD)", key="new_ty_pattern",
                placeholder="2026-09-27",
                help="The date the linked track cohort's 42-day pattern counts as "
                     "'Sun A 1'. Verify it against the bid grid before staff enroll."
            )
            st.markdown("**Training year span** (10/1 – 9/30)")
            c1, c2 = st.columns(2)
            with c1:
                new_start = st.text_input("Start date (YYYY-MM-DD)", key="new_ty_start",
                                          placeholder="2026-10-01")
            with c2:
                new_end = st.text_input("End date (YYYY-MM-DD)", key="new_ty_end",
                                        placeholder="2027-09-30")
            st.caption(
                "New years are created as a **draft** - staff won't see them until you "
                "set the status to Open or promote the year to active."
            )

            submitted = st.form_submit_button("Create Training Year")
            if submitted:
                if not new_label.strip():
                    st.error("Please enter a year label")
                else:
                    ok, msg = unified_db.create_training_year(
                        new_label.strip(), roster_filename=new_roster.strip() or None,
                        linked_track_name=new_track or None,
                        start_date=new_start.strip() or None, end_date=new_end.strip() or None,
                        pattern_start_date=new_pattern.strip() or None
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    def _show_track_status_manager(self):
        """Show track status management functionality"""
        st.subheader("🔧 Track Management System")
        from modules.admin_track_status import display_track_management_interface
        try:
            display_track_management_interface()
        except Exception as e:
            st.error(f"Error loading track status manager: {str(e)}")
            st.info("Make sure modules/admin_track_status.py exists and is properly configured")
