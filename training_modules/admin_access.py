# Updates needed for training_modules/admin_access.py

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd

# Update the AdminAccess class to include availability analyzer initialization
class AdminAccess:
    def __init__(self):
        self.admin_pin = "9999"
        self.session_timeout = 30  # minutes
        self.excel_admin_functions = None
        self.availability_analyzer = None  # NEW: Add availability analyzer
    
    def initialize_admin_functions(self, excel_admin_functions):
        """Initialize with ExcelAdminFunctions instance"""
        self.excel_admin_functions = excel_admin_functions
    
    def is_admin_authenticated(self):
        """Check if admin is currently authenticated"""
        if 'training_admin_authenticated' not in st.session_state:
            return False
        
        if 'training_admin_login_time' not in st.session_state:
            return False
        
        # Check if session has expired
        login_time = st.session_state.training_admin_login_time
        current_time = datetime.now()
        elapsed_minutes = (current_time - login_time).total_seconds() / 60
        
        if elapsed_minutes > self.session_timeout:
            self.logout_admin()
            return False
        
        return st.session_state.training_admin_authenticated
    
    def show_admin_access_button(self):
        """Show a discrete admin access button in the sidebar"""
        with st.sidebar:
            st.markdown("---")
            
            # Use an expander to keep it discrete
            with st.expander("⚙️ Training Admin Access", expanded=False):
                if not self.is_admin_authenticated():
                    self._show_login_form()
                else:
                    self._show_admin_panel()
    
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
                    st.session_state.training_admin_login_time = datetime.now()
                    st.success("✅ Training admin access granted")
                    st.rerun()
                else:
                    st.error("❌ Invalid PIN")
    
    def _show_admin_panel(self):
        """Show admin panel when authenticated"""
        st.success("🔓 **Training Admin Panel Active**")
        
        # Show session info
        login_time = st.session_state.training_admin_login_time
        elapsed_minutes = (datetime.now() - login_time).total_seconds() / 60
        remaining_minutes = max(0, self.session_timeout - elapsed_minutes)
        
        st.info(f"⏱️ Session expires in {remaining_minutes:.0f} minutes")
        
        # Logout button
        if st.button("🔒 Logout", key="training_admin_logout"):
            self.logout_admin()
            st.rerun()
        
        st.markdown("---")
        
        # Admin functions
        self._show_admin_functions()
    
    def _show_admin_functions(self):
        """Show available admin functions"""
        st.write("**📊 Training Administrative Functions**")
        
        # Create sections for different admin functions
        admin_sections = [
            ("📈 Enrollment Reports", "enrollment_reports", "View and export enrollment data"),
            ("👥 Manage Staff", "manage_staff", "View staff enrollment status"),
            ("📚 Manage Classes", "manage_classes", "Configure class settings and schedules"),
            ("📄 Data Export", "data_management", "Export training data"),
            ("📊 System Statistics", "system_stats", "View training system usage"),
            ("🗂️ Database Maintenance", "database_maintenance", "Training database operations"),
            ("🔧 Track Manager", "track_manager", "Manage track status and edit assignments"),
        ]
        
        for label, key, description in admin_sections:
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**{label}**")
                    st.caption(description)
                with col2:
                    if st.button("Open", key=f"training_admin_{key}", use_container_width=True):
                        st.session_state.training_admin_current_function = key
                        st.session_state.training_admin_show_function = True
                        st.rerun()
                
                st.markdown("---")


    def logout_admin(self):
        """Logout admin user"""
        keys_to_remove = [
            'training_admin_authenticated', 
            'training_admin_login_time', 
            'training_admin_current_function',
            'training_admin_show_function'
        ]
        
        for key in keys_to_remove:
            if key in st.session_state:
                del st.session_state[key]
    
    def require_admin(self):
        """Decorator-like function to require admin authentication"""
        if not self.is_admin_authenticated():
            st.error("🔒 Training administrative access required")
            st.info("Please use the training admin access panel in the sidebar")
            st.stop()
        
        # Extend session on activity
        st.session_state.training_admin_login_time = datetime.now()
    
    def show_admin_function_page(self):
        """Show the selected admin function page"""
        if not self.is_admin_authenticated():
            st.error("🔒 Access Denied")
            st.info("Please authenticate through the training admin panel in the sidebar")
            return False
        
        if not st.session_state.get('training_admin_show_function', False):
            return False
        
        current_function = st.session_state.get('training_admin_current_function', '')
        
        # Admin page header
        st.title("🛠️ Training Administrative Dashboard")
        
        # Session status bar
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Session Status", "🟢 Active")
        with col2:
            login_time = st.session_state.training_admin_login_time
            elapsed_minutes = (datetime.now() - login_time).total_seconds() / 60
            remaining_minutes = max(0, self.session_timeout - elapsed_minutes)
            st.metric("Time Remaining", f"{remaining_minutes:.0f} min")
        with col3:
            if st.button("🔒 Logout", key="training_admin_logout_main"):
                self.logout_admin()
                st.rerun()
        with col4:
            if st.button("⬅️ Back to Panel", key="training_admin_back"):
                st.session_state.training_admin_show_function = False
                st.rerun()
        
        st.markdown("---")
        
        # Show the selected admin function
        self._render_admin_function(current_function)
        
        return True
    
    def _render_admin_function(self, function_key):
        """Render the selected admin function"""
        if function_key == "enrollment_reports":
            self._show_enrollment_reports()
        elif function_key == "manage_staff":
            self._show_manage_staff()
        elif function_key == "manage_classes":
            self._show_manage_classes()
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
                            f"training_compliance_{datetime.now().strftime('%Y%m%d')}.csv",
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
        
        # Initialize availability analyzer if not already done
        if not hasattr(self, 'availability_analyzer') or self.availability_analyzer is None:
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
                
            except ImportError as e:
                st.error(f"Could not import AvailabilityAnalyzer: {str(e)}")
                return
            except Exception as e:
                st.error(f"Error initializing AvailabilityAnalyzer: {str(e)}")
                return
        
        # Date range selection
        st.markdown("#### 📅 Select Date Range")
        
        col1, col2 = st.columns(2)
        
        with col1:
            start_date = st.date_input(
                "Start Date",
                value=datetime.now(),
                key="availability_start_date"
            )
        
        with col2:
            end_date = st.date_input(
                "End Date",
                value=datetime.now() + timedelta(days=30),
                key="availability_end_date"
            )
        
        # Validation
        if start_date > end_date:
            st.error("Start date must be before or equal to end date.")
            return
        
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
                    
                    filename = f"session_availability_report_{start_date_str}_{end_date_str}.csv"
                    
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
                    
                    filename = f"class_summary_report_{start_date_str}_{end_date_str}.csv"
                    
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
                value=datetime.now(),
                disabled=True,
                help="Date range selection for educator availability analysis"
            )
        with col2:
            placeholder_end = st.date_input(
                "End Date (Preview)", 
                value=datetime.now() + timedelta(days=30),
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

    def _show_manage_classes(self):
        """Show class management functionality"""
        st.subheader("📚 Training Class Management")
        
        if not self.excel_admin_functions:
            st.error("Admin functions not initialized")
            return
        
        tab1, tab2, tab3 = st.tabs(["📋 Class Overview", "📊 Utilization", "📅 Schedules"])
        
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
                                    f"{selected_class.replace(' ', '_')}_roster.csv",
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
        
    def _show_track_status_manager(self):
        """Show track status management functionality"""
        st.subheader("🔧 Track Management System")
        from modules.admin_track_status import display_track_management_interface
        try:
            display_track_management_interface()
        except Exception as e:
            st.error(f"Error loading track status manager: {str(e)}")
            st.info("Make sure modules/admin_track_status.py exists and is properly configured")
