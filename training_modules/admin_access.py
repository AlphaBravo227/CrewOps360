# training_modules/admin_access.py
import streamlit as st
from datetime import datetime

class AdminAccess:
    def __init__(self):
        self.admin_pin = "9999"
        self.session_timeout = 30  # minutes
        self.excel_admin_functions = None
    
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
            ("🗂️ Database Maintenance", "database_maintenance", "Training database operations")
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
    
    def _show_manage_staff(self):
        """Show staff management functionality"""
        st.subheader("👥 Training Staff Management")
        
        if not self.excel_admin_functions:
            st.error("Admin functions not initialized")
            return
        
        tab1, tab2, tab3 = st.tabs(["👤 Staff Overview", "📊 Compliance Status", "📝 Assignments"])
        
        with tab1:
            st.write("### Staff Training Overview")
            
            # Get staff list and basic stats
            try:
                compliance_df = self.excel_admin_functions.get_enrollment_compliance_report()
                
                if not compliance_df.empty:
                    # Summary metrics
                    total_staff = len(compliance_df)
                    complete_staff = len(compliance_df[compliance_df['Status'] == '✅ Complete'])
                    behind_staff = len(compliance_df[compliance_df['Status'] == '🔴 Behind Schedule'])
                    avg_completion = compliance_df['Completion Rate'].str.rstrip('%').astype(float).mean()
                    
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
                    
                    st.dataframe(filtered_df, use_container_width=True)
                else:
                    st.info("No staff enrollment data available")
                    
            except Exception as e:
                st.error(f"Error loading staff data: {str(e)}")
        
        with tab2:
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
            st.write("### Staff Class Assignments")
            st.info("🚧 **Coming Soon**: Bulk assignment management")
    
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
        
        with tab3:
            st.write("### Class Schedules")
            st.info("🚧 **Coming Soon**: Schedule management interface")
    
    def _show_data_management(self):
        """Show data management functionality"""
        st.subheader("📄 Training Data Export")
        
        if not self.excel_admin_functions:
            st.error("Admin functions not initialized")
            return
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("### Export Reports")
            
            if st.button("📊 Export Compliance Report", use_container_width=True):
                try:
                    compliance_df = self.excel_admin_functions.get_enrollment_compliance_report()
                    csv = compliance_df.to_csv(index=False)
                    st.download_button(
                        "Download Compliance Report",
                        csv,
                        f"training_compliance_{datetime.now().strftime('%Y%m%d')}.csv",
                        "text/csv"
                    )
                except Exception as e:
                    st.error(f"Error generating report: {str(e)}")
            
            if st.button("📈 Export Utilization Report", use_container_width=True):
                try:
                    utilization_df = self.excel_admin_functions.get_class_utilization_report()
                    csv = utilization_df.to_csv(index=False)
                    st.download_button(
                        "Download Utilization Report",
                        csv,
                        f"class_utilization_{datetime.now().strftime('%Y%m%d')}.csv",
                        "text/csv"
                    )
                except Exception as e:
                    st.error(f"Error generating report: {str(e)}")
        
        with col2:
            st.write("### Export Individual Classes")
            
            try:
                all_classes = self.excel_admin_functions.excel.get_all_classes()
                selected_export_class = st.selectbox("Select class to export:", [""] + all_classes)
                
                if selected_export_class:
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        if st.button("Export Roster"):
                            roster_df, title = self.excel_admin_functions.export_class_roster(selected_export_class)
                            csv = roster_df.to_csv(index=False)
                            st.download_button(
                                "Download Roster",
                                csv,
                                f"{selected_export_class.replace(' ', '_')}_roster.csv",
                                "text/csv"
                            )
                    
                    with col2:
                        if st.button("Export Completion Status"):
                            completion_df = self.excel_admin_functions.get_class_completion_tracking(selected_export_class)
                            csv = completion_df.to_csv(index=False)
                            st.download_button(
                                "Download Completion",
                                csv,
                                f"{selected_export_class.replace(' ', '_')}_completion.csv",
                                "text/csv"
                            )
                            
            except Exception as e:
                st.error(f"Error with class export: {str(e)}")
    
    def _show_system_stats(self):
        """Show system statistics with real data"""
        st.subheader("📊 Training System Statistics")
        
        if not self.excel_admin_functions:
            st.error("Admin functions not initialized")
            return
        
        try:
            # Get real statistics from the database
            stats = st.session_state.unified_db.get_enrollment_stats()
            all_classes = self.excel_admin_functions.excel.get_all_classes()
            all_staff = self.excel_admin_functions.excel.get_staff_list()
            
            # Real-time metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Staff", len(all_staff))
            with col2:
                st.metric("Active Classes", len(all_classes))
            with col3:
                st.metric("Total Enrollments", stats['total_enrollments'])
            with col4:
                st.metric("Conflict Overrides", stats['conflict_overrides'])
            
            st.markdown("---")
            
            # Additional insights
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("### 📈 Quick Insights")
                
                # Get classes without enrollments
                unused_classes = self.excel_admin_functions.get_classes_without_enrollments()
                if unused_classes:
                    st.warning(f"📚 {len(unused_classes)} classes have no enrollments")
                    with st.expander("View classes without enrollments"):
                        for cls in unused_classes:
                            st.write(f"• {cls}")
                else:
                    st.success("✅ All classes have enrollments")
                
                # Get unassigned staff
                unassigned_staff = self.excel_admin_functions.get_staff_without_assignments()
                if unassigned_staff:
                    st.info(f"👥 {len(unassigned_staff)} staff have no class assignments")
                    with st.expander("View unassigned staff"):
                        for staff in unassigned_staff:
                            st.write(f"• {staff}")
                else:
                    st.success("✅ All staff have class assignments")
            
            with col2:
                st.write("### ⏰ Recent Activity")
                st.info(f"System time: {stats['current_time_eastern']}")
                st.metric("Recent Enrollments (24h)", stats['recent_enrollments'])
                
                # Show recent conflicts if any
                recent_conflicts = st.session_state.unified_db.get_conflict_override_enrollments()
                if recent_conflicts:
                    st.warning(f"⚠️ {len(recent_conflicts)} active conflict overrides")
                    with st.expander("View conflict overrides"):
                        for conflict in recent_conflicts[:5]:  # Show first 5
                            st.write(f"• {conflict['staff_name']} - {conflict['class_name']}")
                else:
                    st.success("✅ No active conflict overrides")
                    
        except Exception as e:
            st.error(f"Error loading system statistics: {str(e)}")
    
    def _show_database_maintenance(self):
        """Show database maintenance functionality"""
        st.subheader("🗂️ Training Database Maintenance")
        
        st.warning("⚠️ **Caution**: Database maintenance operations should be performed carefully")
        
        tab1, tab2, tab3 = st.tabs(["📊 Database Info", "🧹 Cleanup", "💾 Backup"])
        
        with tab1:
            st.write("### Training Database Information")
            
            try:
                # Get database statistics
                stats = st.session_state.unified_db.get_enrollment_stats()
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Enrollments", stats['total_enrollments'])
                with col2:
                    st.metric("Conflict Overrides", stats['conflict_overrides'])
                with col3:
                    st.metric("Recent Activity", stats['recent_enrollments'])
                
                # Show database health
                st.write("### Database Health")
                st.success("✅ Training database is operational")
                st.info(f"Last updated: {stats['current_time_eastern']}")
                
            except Exception as e:
                st.error(f"Error checking database: {str(e)}")
        
        with tab2:
            st.write("### Database Cleanup")
            st.info("🚧 **Coming Soon**: Cleanup tools for training data")
            st.write("Features planned:")
            st.write("• Remove cancelled enrollments")
            st.write("• Archive old enrollment data")
            st.write("• Optimize database performance")
        
        with tab3:
            st.write("### Backup Operations")
            st.info("🚧 **Coming Soon**: Training-specific backup tools")
            st.write("Features planned:")
            st.write("• Export training data backup")
            st.write("• Restore training data")
            st.write("• Scheduled backups")