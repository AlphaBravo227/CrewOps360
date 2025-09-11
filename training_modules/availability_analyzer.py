# training_modules/availability_analyzer.py
"""
Availability Analyzer for Training Events
Analyzes staff availability for class enrollment within date ranges without conflicts
Updated to handle role-based availability constraints from Excel enrollments
"""
from datetime import datetime, timedelta
import sqlite3
import pandas as pd

class AvailabilityAnalyzer:
    def __init__(self, unified_database, excel_handler, enrollment_manager, track_manager=None):
        """
        Initialize the Availability Analyzer
        
        Args:
            unified_database: UnifiedDatabase instance
            excel_handler: ExcelHandler instance
            enrollment_manager: EnrollmentManager instance
            track_manager: TrainingTrackManager instance (optional)
        """
        self.db = unified_database
        self.excel = excel_handler
        self.enrollment = enrollment_manager
        self.track_manager = track_manager
    
    def get_no_conflict_enrollment_availability(self, start_date, end_date, 
                                              include_assigned_only=True,
                                              include_already_enrolled=False):
        """
        Get staff availability for class enrollment within date range without conflicts
        
        Args:
            start_date (str): Start date in 'YYYY-MM-DD' format
            end_date (str): End date in 'YYYY-MM-DD' format
            include_assigned_only (bool): Only check staff assigned to each class
            include_already_enrolled (bool): Include staff already enrolled
            
        Returns:
            dict: Organized by class_name -> date -> availability data
        """
        try:
            # Convert string dates to datetime objects
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Get all classes and filter by date range
            eligible_classes = self._get_classes_in_date_range(start_dt, end_dt)
            
            if not eligible_classes:
                return {}
            
            # Get staff roles from Excel enrollment data
            staff_roles = self._get_excel_enrollment_roles()
            
            availability_report = {}
            
            for class_name, class_dates in eligible_classes.items():
                availability_report[class_name] = {}
                
                # Get staff assigned to this class
                assigned_staff = self._get_assigned_staff(class_name)
                
                if not assigned_staff:
                    continue
                
                for date_str in class_dates:
                    date_obj = datetime.strptime(date_str, '%m/%d/%Y')
                    
                    # Get class details for conflict checking
                    class_details = self.excel.get_class_details(class_name)
                    
                    available_staff = []
                    staff_details = []
                    
                    for staff_name in assigned_staff:
                        # Check if already enrolled (unless we want to include them)
                        if not include_already_enrolled and self._is_already_enrolled(staff_name, class_name, date_str):
                            continue
                        
                        # Get staff role
                        role = staff_roles.get(staff_name, 'Unknown')
                        
                        # Check role-based weekly enrollment limits
                        week_start = self._get_week_start(date_obj)
                        if not self._check_role_weekly_limits(staff_name, role, week_start, date_str):
                            continue
                        
                        # Check for schedule conflicts
                        conflict_info = self._check_staff_conflicts(staff_name, class_name, date_str, class_details)
                        
                        # Staff is available if no blocking conflicts
                        if not conflict_info['blocking']:
                            available_staff.append(staff_name)
                            
                            staff_info = {
                                'name': staff_name,
                                'role': role,
                                'warnings': conflict_info['warnings'],
                                'notes': conflict_info['notes']
                            }
                            staff_details.append(staff_info)
                    
                    # Get class capacity info
                    max_students = int(class_details.get('students_per_class', 21)) if class_details else 21
                    current_enrolled = self.enrollment.get_date_enrollment_count(class_name, date_str)
                    
                    availability_report[class_name][date_str] = {
                        'available_staff': available_staff,
                        'staff_details': staff_details,
                        'total_available': len(available_staff),
                        'class_capacity': max_students,
                        'currently_enrolled': current_enrolled,
                        'slots_remaining': max_students - current_enrolled
                    }
            
            return availability_report
            
        except Exception as e:
            print(f"Error in get_no_conflict_enrollment_availability: {str(e)}")
            import traceback
            traceback.print_exc()
            return {}
    
    def get_no_conflict_educator_availability(self, start_date, end_date):
        """
        Analyze educator availability for classes requiring instruction within date range
        
        Args:
            start_date (str): Start date in 'YYYY-MM-DD' format
            end_date (str): End date in 'YYYY-MM-DD' format
            
        Returns:
            dict: Organized by class_name -> date -> educator availability data
        """
        # TODO: Full implementation
        # This is a framework for future development
        
        try:
            # Convert string dates to datetime objects
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Framework for future implementation
            educator_report = {
                "implementation_status": "Framework prepared - not yet implemented",
                "date_range": f"{start_date} to {end_date}",
                "planned_features": {
                    "educator_eligible_classes": "Classes with instructor_count > 0",
                    "authorized_educators": "Staff with 'Educator AT' = True", 
                    "conflict_checking": "AT shifts allowed for educators",
                    "workload_analysis": "Distribution of educator assignments",
                    "coverage_gaps": "Classes needing more educator signups"
                },
                "placeholder_data": self._get_educator_availability_preview(start_dt, end_dt)
            }
            
            return educator_report
            
        except Exception as e:
            print(f"Error in get_no_conflict_educator_availability: {str(e)}")
            return {
                "error": str(e),
                "implementation_status": "Framework only - full implementation pending"
            }
    
    def _get_educator_availability_preview(self, start_dt, end_dt):
        """
        Generate preview data for educator availability (placeholder implementation)
        This shows the structure that will be used for the full implementation
        """
        try:
            # Get classes that need educators in the date range
            educator_classes = {}
            all_classes = self.excel.get_all_classes()
            
            for class_name in all_classes:
                class_details = self.excel.get_class_details(class_name)
                
                if not class_details:
                    continue
                
                # Check if class needs educators
                instructor_count = class_details.get('instructors_per_day', 0)
                try:
                    instructor_count = int(float(instructor_count)) if instructor_count else 0
                except (ValueError, TypeError):
                    instructor_count = 0
                
                if instructor_count <= 0:
                    continue  # Skip classes that don't need educators
                
                # Get class dates in range
                class_dates = []
                for i in range(1, 15):
                    date_key = f'date_{i}'
                    if date_key in class_details and class_details[date_key]:
                        base_date_str = class_details[date_key]
                        
                        try:
                            base_date = datetime.strptime(base_date_str, '%m/%d/%Y')
                            
                            # Check if this is a two-day class
                            is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
                            
                            if is_two_day:
                                day_2 = base_date + timedelta(days=1)
                                if start_dt <= base_date <= end_dt and start_dt <= day_2 <= end_dt:
                                    class_dates.append(base_date_str)
                                    class_dates.append(day_2.strftime('%m/%d/%Y'))
                            else:
                                if start_dt <= base_date <= end_dt:
                                    class_dates.append(base_date_str)
                                    
                        except ValueError:
                            continue
                
                if class_dates:
                    # Remove duplicates and sort
                    class_dates = sorted(list(set(class_dates)))
                    
                    educator_classes[class_name] = {
                        "instructors_needed": instructor_count,
                        "dates": class_dates,
                        "preview_note": "Full implementation will show available authorized educators"
                    }
            
            return {
                "classes_needing_educators": educator_classes,
                "total_classes": len(educator_classes),
                "total_dates": sum(len(data["dates"]) for data in educator_classes.values()),
                "next_steps": [
                    "Implement educator authorization checking",
                    "Add educator-specific conflict rules", 
                    "Create educator workload balancing",
                    "Build coverage gap analysis"
                ]
            }
            
        except Exception as e:
            return {
                "error": f"Error in preview generation: {str(e)}",
                "fallback_message": "Educator availability framework is prepared for implementation"
            }
    
    def _get_classes_in_date_range(self, start_dt, end_dt):
        """Get all classes that have dates within the specified range"""
        eligible_classes = {}
        
        all_classes = self.excel.get_all_classes()
        
        for class_name in all_classes:
            class_details = self.excel.get_class_details(class_name)
            
            if not class_details:
                continue
            
            class_dates = []
            
            # Check all possible date rows (1-14)
            for i in range(1, 15):
                date_key = f'date_{i}'
                if date_key in class_details and class_details[date_key]:
                    base_date_str = class_details[date_key]
                    
                    try:
                        base_date = datetime.strptime(base_date_str, '%m/%d/%Y')
                        
                        # Check if this is a two-day class
                        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
                        
                        if is_two_day:
                            day_2 = base_date + timedelta(days=1)
                            if start_dt <= base_date <= end_dt and start_dt <= day_2 <= end_dt:
                                class_dates.append(base_date_str)
                                class_dates.append(day_2.strftime('%m/%d/%Y'))
                            else:
                                if start_dt <= base_date <= end_dt:
                                    class_dates.append(base_date_str)
                                    
                        else:
                            if start_dt <= base_date <= end_dt:
                                class_dates.append(base_date_str)
                                
                    except ValueError:
                        continue
            
            if class_dates:
                # Remove duplicates and sort
                class_dates = sorted(list(set(class_dates)))
                eligible_classes[class_name] = class_dates
        
        return eligible_classes
    
    def _get_excel_enrollment_roles(self):
        """
        Extract staff roles from Excel enrollment data
        Looks for roles in column B (Role) of enrollment records
        This is the authoritative source for training registration roles
        """
        staff_roles = {}
        
        try:
            # Get all enrollment records from the database (imported from Excel)
            self.db.connect()
            
            query = """
            SELECT DISTINCT staff_name, role
            FROM enrollment
            WHERE role IS NOT NULL AND role != ''
            """
            
            cursor = self.db.connection.cursor()
            cursor.execute(query)
            
            for staff_name, role in cursor.fetchall():
                if role and role.strip():
                    # Standardize role names from Excel
                    role_upper = role.strip().upper()
                    if role_upper in ['RN', 'NURSE']:
                        staff_roles[staff_name] = 'RN'
                    elif role_upper in ['MEDIC', 'PARAMEDIC']:
                        staff_roles[staff_name] = 'MEDIC'
                    elif role_upper in ['MGMT', 'MANAGEMENT', 'MANAGER']:
                        staff_roles[staff_name] = 'MGMT'
                    else:
                        staff_roles[staff_name] = role_upper
            
            self.db.disconnect()
            
        except Exception as e:
            print(f"Error extracting roles from enrollment records: {str(e)}")
            if hasattr(self.db, 'disconnect'):
                self.db.disconnect()
        
        return staff_roles
    
    def _get_assigned_staff(self, class_name):
        """Get list of staff assigned to a specific class"""
        all_staff = self.excel.get_staff_list()
        assigned_staff = []
        
        for staff_name in all_staff:
            assigned_classes = self.excel.get_assigned_classes(staff_name)
            if class_name in assigned_classes:
                assigned_staff.append(staff_name)
        
        return assigned_staff
    
    def _is_already_enrolled(self, staff_name, class_name, date_str):
        """Check if staff member is already enrolled in this class/date"""
        enrollments = self.enrollment.get_staff_enrollments(staff_name)
        
        for enrollment in enrollments:
            if (enrollment['class_name'] == class_name and 
                enrollment['class_date'] == date_str):
                return True
        
        return False
    
    def _get_week_start(self, date_obj):
        """Get the Sunday start of the week for a given date"""
        days_since_sunday = date_obj.weekday() + 1  # Monday = 0, so Sunday = 6
        if days_since_sunday == 7:  # Sunday
            days_since_sunday = 0
        
        week_start = date_obj - timedelta(days=days_since_sunday)
        return week_start
    
    def _check_role_weekly_limits(self, staff_name, role, week_start, exclude_date):
        """
        Check if staff member can enroll based on role-specific weekly limits
        MEDIC: 1 class per week, RN & MGMT: unlimited
        
        Args:
            staff_name (str): Name of staff member
            role (str): Staff role (MEDIC, RN, MGMT)
            week_start (datetime): Start of week (Sunday)
            exclude_date (str): Date being checked for enrollment (MM/DD/YYYY format)
        
        Returns:
            bool: True if role constraints allow enrollment, False otherwise
        """
        # RN and MGMT have no weekly enrollment constraints
        if role in ['RN', 'MGMT']:
            return True
        
        # MEDIC staff can only enroll in 1 class per week
        if role == 'MEDIC':
            week_end = week_start + timedelta(days=6)
            
            enrollments = self.enrollment.get_staff_enrollments(staff_name)
            weekly_count = 0
            
            for enrollment in enrollments:
                try:
                    enroll_date = datetime.strptime(enrollment['class_date'], '%m/%d/%Y')
                    
                    # Count enrollments in this week (excluding the date we're checking)
                    if (week_start <= enroll_date <= week_end and 
                        enrollment['class_date'] != exclude_date):
                        weekly_count += 1
                        
                except ValueError:
                    continue
            
            return weekly_count < 1  # MEDIC can only have 1 class per week
        
        # Unknown roles default to no constraints (same as RN/MGMT)
        return True
    
    def _check_staff_conflicts(self, staff_name, class_name, date_str, class_details):
        """
        Check for schedule conflicts for a staff member
        Returns dict with blocking conflicts, warnings, and notes
        """
        conflict_info = {
            'blocking': False,
            'warnings': [],
            'notes': []
        }
        
        if not self.track_manager or not self.track_manager.has_track_data(staff_name):
            conflict_info['notes'].append("No track data - conflict checking disabled")
            return conflict_info
        
        try:
            # Get can_work_n_prior setting for this class/date
            can_work_n_prior = False
            if class_details:
                for i in range(1, 15):
                    date_key = f'date_{i}'
                    if date_key in class_details and class_details[date_key] == date_str:
                        can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                        break
            
            # Check for schedule conflicts
            has_conflict, conflict_details = self.track_manager.check_class_conflict(
                staff_name, date_str, False, can_work_n_prior
            )
            
            if has_conflict:
                # Parse conflict details to separate blocking vs warning conflicts
                if 'AT' in conflict_details:
                    # AT shifts are warnings, not blocking
                    conflict_info['warnings'].append(f"AT shift scheduled: {conflict_details}")
                else:
                    # Other conflicts are blocking
                    conflict_info['blocking'] = True
                    conflict_info['warnings'].append(f"Schedule conflict: {conflict_details}")
            
            # Add note about N prior setting
            if can_work_n_prior:
                conflict_info['notes'].append("Night shift prior to class is allowed")
            
        except Exception as e:
            conflict_info['notes'].append(f"Error checking conflicts: {str(e)}")
        
        return conflict_info