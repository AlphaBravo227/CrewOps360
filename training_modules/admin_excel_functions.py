# training_modules/admin_excel_functions.py
import pandas as pd
import openpyxl
from datetime import datetime
import streamlit as st
from .config import NON_CLASS_COLUMNS, DEFAULT_CLASS_DETAILS

class ExcelAdminFunctions:
    def __init__(self, excel_handler, enrollment_manager, database):
        self.excel = excel_handler
        self.enrollment = enrollment_manager
        self.db = database
        
    def get_enrollment_compliance_report(self):
        """Generate compliance report showing enrollment status vs assignments"""
        staff_list = self.excel.get_staff_list()
        report_data = []
        
        for staff_name in staff_list:
            # Get assigned classes
            assigned_classes = self.excel.get_assigned_classes(staff_name)
            enrolled_classes = self.enrollment.get_enrolled_classes(staff_name)
            live_meeting_count = self.enrollment.get_live_staff_meeting_count(staff_name)
            
            # Calculate completion metrics
            total_assigned = len(assigned_classes)
            total_enrolled = len(enrolled_classes)
            completion_rate = (total_enrolled / total_assigned * 100) if total_assigned > 0 else 0
            
            # Check staff meeting requirement
            staff_meetings_assigned = [cls for cls in assigned_classes 
                                    if self.excel.is_staff_meeting(cls)]
            staff_meeting_compliance = live_meeting_count >= 2 if staff_meetings_assigned else True
            
            # Get conflict overrides
            conflict_enrollments = self.db.get_conflict_override_enrollments(staff_name)
            
            report_data.append({
                'Staff Name': staff_name,
                'Total Assigned': total_assigned,
                'Total Enrolled': total_enrolled,
                'Completion Rate': f"{completion_rate:.1f}%",
                'Classes Remaining': total_assigned - total_enrolled,
                'LIVE Meetings': f"{live_meeting_count}/2" if staff_meetings_assigned else "N/A",
                'Meeting Compliance': "✅" if staff_meeting_compliance else "❌",
                'Conflict Overrides': len(conflict_enrollments),
                'Status': self._get_compliance_status(completion_rate, staff_meeting_compliance)
            })
            
        return pd.DataFrame(report_data)
    
    def _get_compliance_status(self, completion_rate, meeting_compliance):
        """Determine overall compliance status"""
        if completion_rate == 100 and meeting_compliance:
            return "✅ Complete"
        elif completion_rate >= 80 and meeting_compliance:
            return "🟡 Nearly Complete"
        elif completion_rate >= 50:
            return "🟠 In Progress"
        else:
            return "🔴 Behind Schedule"
    
    def get_class_utilization_report(self):
        """Generate report showing class capacity utilization"""
        all_classes = self.excel.get_all_classes()
        utilization_data = []
        
        for class_name in all_classes:
            class_details = self.excel.get_class_details(class_name)
            enrollment_summary = self.enrollment.get_class_enrollment_summary(class_name)
            
            max_students = int(class_details.get('students_per_class', 21))
            total_capacity = 0
            total_enrolled = 0
            total_dates = 0
            
            # Calculate across all dates
            for i in range(1, 9):
                date_key = f'date_{i}'
                if date_key in class_details and class_details[date_key]:
                    total_dates += 1
                    total_capacity += max_students
                    
                    date_str = class_details[date_key]
                    if date_str in enrollment_summary:
                        total_enrolled += enrollment_summary[date_str]['total']
            
            utilization_rate = (total_enrolled / total_capacity * 100) if total_capacity > 0 else 0
            
            utilization_data.append({
                'Class Name': class_name,
                'Total Dates': total_dates,
                'Total Capacity': total_capacity,
                'Current Enrolled': total_enrolled,
                'Utilization Rate': f"{utilization_rate:.1f}%",
                'Available Slots': total_capacity - total_enrolled,
                'Class Type': "Staff Meeting" if self.excel.is_staff_meeting(class_name) else "Training",
                'Status': self._get_utilization_status(utilization_rate)
            })
            
        return pd.DataFrame(utilization_data)
    
    def _get_utilization_status(self, utilization_rate):
        """Determine utilization status"""
        if utilization_rate >= 90:
            return "🔴 Nearly Full"
        elif utilization_rate >= 70:
            return "🟡 Good Utilization"
        elif utilization_rate >= 40:
            return "🟠 Moderate"
        else:
            return "🟢 Low Utilization"
    
    def get_conflict_analysis_report(self):
        """Analyze schedule conflicts and overrides"""
        all_staff = self.excel.get_staff_list()
        conflict_data = []
        
        for staff_name in all_staff:
            conflict_enrollments = self.db.get_conflict_override_enrollments(staff_name)
            
            for enrollment in conflict_enrollments:
                conflict_data.append({
                    'Staff Name': staff_name,
                    'Class Name': enrollment['class_name'],
                    'Class Date': enrollment['class_date'],
                    'Conflict Details': enrollment['conflict_details'],
                    'Override Date': enrollment.get('override_acknowledged_display', 'N/A'),
                    'Meeting Type': enrollment.get('meeting_type', 'N/A'),
                    'Session Time': enrollment.get('session_time', 'N/A')
                })
        
        return pd.DataFrame(conflict_data)
    
    def get_staff_without_assignments(self):
        """Find staff members with no class assignments"""
        all_staff = self.excel.get_staff_list()
        unassigned_staff = []
        
        for staff_name in all_staff:
            assigned_classes = self.excel.get_assigned_classes(staff_name)
            if not assigned_classes:
                unassigned_staff.append(staff_name)
        
        return unassigned_staff
    
    def get_classes_without_enrollments(self):
        """Find classes with no current enrollments"""
        all_classes = self.excel.get_all_classes()
        unused_classes = []
        
        for class_name in all_classes:
            enrollments = self.db.get_class_enrollments(class_name)
            if not enrollments:
                unused_classes.append(class_name)
        
        return unused_classes
    
    def validate_excel_structure(self):
        """Validate Excel file structure and identify issues"""
        issues = []
        
        # Check if workbook loaded successfully
        if self.excel.load_error:
            issues.append(f"Excel Loading Error: {self.excel.load_error}")
            return issues
        
        # Check staff list
        staff_list = self.excel.get_staff_list()
        if not staff_list:
            issues.append("No staff members found in the roster")
        
        # Check for duplicate staff names
        duplicates = set([x for x in staff_list if staff_list.count(x) > 1])
        if duplicates:
            issues.append(f"Duplicate staff names found: {', '.join(duplicates)}")
        
        # Check class sheets
        all_classes = self.excel.get_all_classes()
        for class_name in all_classes:
            class_details = self.excel.get_class_details(class_name)
            
            # Check if class sheet exists and has valid data
            if not class_details or class_details == DEFAULT_CLASS_DETAILS:
                issues.append(f"Class '{class_name}' has no detailed configuration sheet")
                continue
            
            # Check for dates
            has_dates = any(class_details.get(f'date_{i}') for i in range(1, 9))
            if not has_dates:
                issues.append(f"Class '{class_name}' has no scheduled dates")
        
        return issues if issues else ["✅ Excel structure validation passed"]
    
    def get_individual_class_report(self, class_name):
        """Generate comprehensive report for a specific class"""
        class_details = self.excel.get_class_details(class_name)
        enrollment_summary = self.enrollment.get_class_enrollment_summary(class_name)
        
        if not class_details:
            return None
            
        # Basic class info
        report = {
            'class_name': class_name,
            'class_type': 'Staff Meeting' if self.excel.is_staff_meeting(class_name) else 'Training Class',
            'max_students_per_session': int(class_details.get('students_per_class', 21)),
            'classes_per_day': int(class_details.get('classes_per_day', 1)),
            'is_two_day_class': class_details.get('is_two_day_class', 'No'),
            'nurses_medic_separate': class_details.get('nurses_medic_separate', 'No'),
            'dates': [],
            'overall_stats': {},
            'staff_analysis': {}
        }
        
        # Get all scheduled dates and their details
        total_capacity = 0
        total_enrolled = 0
        total_conflicts = 0
        
        for i in range(1, 9):
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                date_str = class_details[date_key]
                location = class_details.get(f'date_{i}_location', '')
                has_live = class_details.get(f'date_{i}_has_live', False)
                can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                
                # Get enrollments for this date
                date_enrollments = self.db.get_class_enrollments(class_name, date_str)
                enrolled_count = len(date_enrollments)
                conflict_count = sum(1 for e in date_enrollments if e.get('conflict_override', False))
                
                max_students = int(class_details.get('students_per_class', 21))
                capacity = max_students
                
                date_info = {
                    'date': date_str,
                    'location': location,
                    'has_live_option': has_live,
                    'night_shift_ok': can_work_n_prior,
                    'total_enrolled': enrolled_count,
                    'total_capacity': capacity,
                    'utilization_rate': (enrolled_count / capacity * 100) if capacity > 0 else 0,
                    'conflicts': conflict_count,
                    'available_slots': capacity - enrolled_count,
                    'enrollments': date_enrollments
                }
                
                report['dates'].append(date_info)
                total_capacity += capacity
                total_enrolled += enrolled_count
                total_conflicts += conflict_count
        
        # Overall statistics
        report['overall_stats'] = {
            'total_dates': len(report['dates']),
            'total_capacity': total_capacity,
            'total_enrolled': total_enrolled,
            'overall_utilization': (total_enrolled / total_capacity * 100) if total_capacity > 0 else 0,
            'total_conflicts': total_conflicts,
            'total_available_slots': total_capacity - total_enrolled
        }
        
        # Get assigned vs enrolled staff
        assigned_staff = self._get_staff_assigned_to_class(class_name)
        all_enrollments = self.db.get_class_enrollments(class_name)
        enrolled_staff_names = list(set([e['staff_name'] for e in all_enrollments]))
        
        report['staff_analysis'] = {
            'total_assigned': len(assigned_staff),
            'total_enrolled': len(enrolled_staff_names),
            'enrollment_rate': (len(enrolled_staff_names) / len(assigned_staff) * 100) if assigned_staff else 0,
            'assigned_but_not_enrolled': [s for s in assigned_staff if s not in enrolled_staff_names],
            'enrolled_staff': enrolled_staff_names
        }
        
        return report
    
    def _get_staff_assigned_to_class(self, class_name):
        """Get list of staff assigned to a specific class"""
        all_staff = self.excel.get_staff_list()
        assigned_staff = []
        
        for staff_name in all_staff:
            assigned_classes = self.excel.get_assigned_classes(staff_name)
            if class_name in assigned_classes:
                assigned_staff.append(staff_name)
        
        return assigned_staff
    
    def export_class_roster(self, class_name, date_str=None):
        """Export roster for a specific class/date in printable format"""
        if date_str:
            # Single date roster
            enrollments = self.db.get_class_enrollments(class_name, date_str)
            title = f"{class_name} - {date_str}"
        else:
            # All dates roster
            enrollments = self.db.get_class_enrollments(class_name)
            title = f"{class_name} - All Dates"
        
        roster_data = []
        for enrollment in enrollments:
            roster_data.append({
                'Staff Name': enrollment['staff_name'],
                'Date': enrollment['class_date'],
                'Role': enrollment.get('role', 'General'),
                'Meeting Type': enrollment.get('meeting_type', ''),
                'Session Time': enrollment.get('session_time', ''),
                'Has Conflict': '⚠️' if enrollment.get('conflict_override') else '',
                'Enrollment Date': enrollment.get('enrollment_date', ''),
                'Status': enrollment.get('status', 'active')
            })
        
        df = pd.DataFrame(roster_data)
        df = df.sort_values(['Date', 'Staff Name'])
        
        return df, title
    
    def get_class_completion_tracking(self, class_name):
        """Track completion status for all assigned staff"""
        assigned_staff = self._get_staff_assigned_to_class(class_name)
        class_details = self.excel.get_class_details(class_name)
        
        completion_data = []
        
        for staff_name in assigned_staff:
            staff_enrollments = [e for e in self.db.get_class_enrollments(class_name) 
                               if e['staff_name'] == staff_name]
            
            # Get all available dates for this class
            available_dates = []
            for i in range(1, 9):
                date_key = f'date_{i}'
                if date_key in class_details and class_details[date_key]:
                    available_dates.append(class_details[date_key])
            
            enrolled_dates = [e['class_date'] for e in staff_enrollments]
            
            # For staff meetings, check LIVE requirement
            live_count = sum(1 for e in staff_enrollments 
                           if e.get('meeting_type') == 'LIVE')
            
            is_staff_meeting = self.excel.is_staff_meeting(class_name)
            meeting_compliance = live_count >= 2 if is_staff_meeting else True
            
            completion_data.append({
                'Staff Name': staff_name,
                'Enrolled Dates': len(enrolled_dates),
                'Available Dates': len(available_dates),
                'Completion Status': 'Complete' if enrolled_dates else 'Not Started',
                'LIVE Meetings': f"{live_count}/2" if is_staff_meeting else 'N/A',
                'Meeting Compliance': '✅' if meeting_compliance else '❌',
                'Conflicts': sum(1 for e in staff_enrollments if e.get('conflict_override')),
                'Enrolled Dates List': ', '.join(enrolled_dates) if enrolled_dates else 'None'
            })
        
        return pd.DataFrame(completion_data)


# Integration function for enhanced admin reports
def enhance_admin_reports(admin_access_instance, excel_admin_functions):
    """Add enhanced reporting to admin access"""
    
    def _show_enhanced_enrollment_reports():
        st.subheader("📈 Enhanced Enrollment Reports")
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Compliance", "🎯 Utilization", "⚠️ Conflicts", "📋 Individual Classes", "🔍 Validation"])
        
        with tab1:
            st.write("### Staff Enrollment Compliance")
            try:
                compliance_df = excel_admin_functions.get_enrollment_compliance_report()
                
                if not compliance_df.empty:
                    # Summary metrics
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        complete_count = len(compliance_df[compliance_df['Status'] == '✅ Complete'])
                        st.metric("Fully Compliant", f"{complete_count}/{len(compliance_df)}")
                    with col2:
                        avg_completion = compliance_df['Completion Rate'].str.rstrip('%').astype(float).mean()
                        st.metric("Avg Completion", f"{avg_completion:.1f}%")
                    with col3:
                        total_conflicts = compliance_df['Conflict Overrides'].sum()
                        st.metric("Total Conflicts", total_conflicts)
                    with col4:
                        behind_schedule = len(compliance_df[compliance_df['Status'] == '🔴 Behind Schedule'])
                        st.metric("Behind Schedule", behind_schedule)
                    
                    # Detailed table
                    st.dataframe(compliance_df, use_container_width=True)
                    
                    # Export functionality
                    if st.button("📥 Export Compliance Report"):
                        csv = compliance_df.to_csv(index=False)
                        st.download_button(
                            "Download CSV",
                            csv,
                            f"compliance_report_{datetime.now().strftime('%Y%m%d')}.csv",
                            "text/csv"
                        )
                else:
                    st.info("No compliance data available")
            except Exception as e:
                st.error(f"Error generating compliance report: {str(e)}")
        
        with tab2:
            st.write("### Class Utilization Analysis")
            try:
                utilization_df = excel_admin_functions.get_class_utilization_report()
                
                if not utilization_df.empty:
                    # Utilization metrics
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        avg_utilization = utilization_df['Utilization Rate'].str.rstrip('%').astype(float).mean()
                        st.metric("Avg Utilization", f"{avg_utilization:.1f}%")
                    with col2:
                        total_capacity = utilization_df['Total Capacity'].sum()
                        total_enrolled = utilization_df['Current Enrolled'].sum()
                        st.metric("Overall Utilization", f"{total_enrolled}/{total_capacity}")
                    with col3:
                        nearly_full = len(utilization_df[utilization_df['Status'] == '🔴 Nearly Full'])
                        st.metric("Nearly Full Classes", nearly_full)
                    
                    st.dataframe(utilization_df, use_container_width=True)
                else:
                    st.info("No utilization data available")
            except Exception as e:
                st.error(f"Error generating utilization report: {str(e)}")
        
        with tab3:
            st.write("### Schedule Conflict Analysis")
            try:
                conflict_df = excel_admin_functions.get_conflict_analysis_report()
                
                if not conflict_df.empty:
                    st.warning(f"Found {len(conflict_df)} schedule conflicts requiring manual resolution")
                    st.dataframe(conflict_df, use_container_width=True)
                else:
                    st.success("No schedule conflicts found!")
            except Exception as e:
                st.error(f"Error generating conflict report: {str(e)}")
        
        with tab4:
            st.write("### Individual Class Reports")
            
            try:
                # Class selection
                all_classes = excel_admin_functions.excel.get_all_classes()
                selected_class = st.selectbox("Select Class for Detailed Report:", [""] + all_classes)
                
                if selected_class:
                    class_report = excel_admin_functions.get_individual_class_report(selected_class)
                    
                    if class_report:
                        # Class overview
                        st.write(f"## 📚 {class_report['class_name']}")
                        
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
                        
                        # Staff assignment analysis
                        st.write("### 👥 Staff Assignment Analysis")
                        staff_stats = class_report['staff_analysis']
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Staff Assigned", staff_stats['total_assigned'])
                        with col2:
                            st.metric("Staff Enrolled", staff_stats['total_enrolled'])
                        with col3:
                            enrollment_rate = staff_stats['enrollment_rate']
                            st.metric("Enrollment Rate", f"{enrollment_rate:.1f}%")
                        
                        # Show staff not yet enrolled
                        if staff_stats['assigned_but_not_enrolled']:
                            st.warning("Staff assigned but not enrolled:")
                            for staff in staff_stats['assigned_but_not_enrolled']:
                                st.write(f"• {staff}")
                        
                        # Export options
                        st.write("### 📥 Export Options")
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            if st.button("Export Class Roster"):
                                roster_df, title = excel_admin_functions.export_class_roster(selected_class)
                                csv = roster_df.to_csv(index=False)
                                st.download_button(
                                    "Download Roster CSV",
                                    csv,
                                    f"{selected_class.replace(' ', '_')}_roster_{datetime.now().strftime('%Y%m%d')}.csv",
                                    "text/csv"
                                )
                        
                        with col2:
                            if st.button("Export Completion Tracking"):
                                completion_df = excel_admin_functions.get_class_completion_tracking(selected_class)
                                csv = completion_df.to_csv(index=False)
                                st.download_button(
                                    "Download Completion CSV",
                                    csv,
                                    f"{selected_class.replace(' ', '_')}_completion_{datetime.now().strftime('%Y%m%d')}.csv",
                                    "text/csv"
                                )
                    else:
                        st.error(f"Could not generate report for {selected_class}")
            except Exception as e:
                st.error(f"Error with individual class reports: {str(e)}")
        
        with tab5:
            st.write("### Excel Structure Validation")
            try:
                validation_issues = excel_admin_functions.validate_excel_structure()
                
                if "✅ Excel structure validation passed" in validation_issues:
                    st.success("Excel file structure is valid!")
                else:
                    st.error("Validation issues found:")
                    for issue in validation_issues:
                        st.write(f"• {issue}")
                
                # Additional checks
                unassigned_staff = excel_admin_functions.get_staff_without_assignments()
                if unassigned_staff:
                    st.warning(f"Staff without class assignments: {', '.join(unassigned_staff)}")
                
                unused_classes = excel_admin_functions.get_classes_without_enrollments()
                if unused_classes:
                    st.info(f"Classes with no enrollments: {', '.join(unused_classes)}")
            except Exception as e:
                st.error(f"Error with validation: {str(e)}")
    
    # Replace the existing method
    admin_access_instance._show_enhanced_enrollment_reports = _show_enhanced_enrollment_reports