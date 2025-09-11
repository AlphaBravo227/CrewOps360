# training_modules/availability_analyzer.py
"""
Availability Analyzer for Training Events
Analyzes staff availability for class enrollment within date ranges without conflicts
Updated to handle role-based availability constraints and multiple sessions per day
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
        Updated to handle multiple sessions per day as separate entries and role filtering
        
        Args:
            start_date (str): Start date in 'YYYY-MM-DD' format
            end_date (str): End date in 'YYYY-MM-DD' format
            include_assigned_only (bool): Only check staff assigned to each class
            include_already_enrolled (bool): Include staff already enrolled
            
        Returns:
            dict: Organized by class_name -> date_session -> availability data
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
                assigned_staff = self._get_assigned_staff(class_name) if include_assigned_only else self.excel.get_staff_list()
                
                if not assigned_staff:
                    continue
                
                # Get class details to understand session structure
                class_details = self.excel.get_class_details(class_name)
                if not class_details:
                    continue
                
                for date_str in class_dates:
                    date_obj = datetime.strptime(date_str, '%m/%d/%Y')
                    
                    # Get session options for this class/date combination
                    session_options = self._get_class_session_options(class_name, date_str, class_details)
                    
                    for session_option in session_options:
                        # Create unique key for each session
                        session_key = self._create_session_key(date_str, session_option)
                        
                        # Analyze availability for this specific session
                        session_availability = self._analyze_session_availability(
                            class_name, date_str, session_option, assigned_staff, 
                            staff_roles, date_obj, include_already_enrolled
                        )
                        
                        availability_report[class_name][session_key] = session_availability
            
            return availability_report
            
        except Exception as e:
            print(f"Error in get_no_conflict_enrollment_availability: {str(e)}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _get_class_session_options(self, class_name, class_date, class_details):
        """
        Get all session options for a class on a specific date
        Handles multiple sessions per day, nurse/medic separation, and staff meetings
        """
        session_options = []
        
        classes_per_day = int(class_details.get('classes_per_day', 1))
        max_students = int(class_details.get('students_per_class', 21))
        nurses_medic_separate = class_details.get('nurses_medic_separate', 'No').lower() == 'yes'
        is_staff_meeting = self.excel.is_staff_meeting(class_name)
        is_two_day = self._is_two_day_class(class_name)
        
        # Handle multiple sessions per day
        if classes_per_day > 1:
            for i in range(1, classes_per_day + 1):
                start_key = f'time_{i}_start'
                end_key = f'time_{i}_end'
                
                if start_key in class_details and end_key in class_details:
                    start_time = class_details[start_key]
                    end_time = class_details[end_key]
                    
                    if start_time and end_time:
                        session_time = f"{start_time}-{end_time}"
                        display_time = f"Session {i} ({start_time}-{end_time})"
                        
                        if nurses_medic_separate:
                            # Create separate options for nurses and medics
                            session_options.append({
                                'session_time': session_time,
                                'display_time': display_time,
                                'role_requirement': 'Nurse',
                                'max_students': max_students // 2,
                                'type': 'nurse_medic_separate',
                                'is_two_day': is_two_day
                            })
                            session_options.append({
                                'session_time': session_time,
                                'display_time': display_time,
                                'role_requirement': 'Medic',
                                'max_students': max_students // 2,
                                'type': 'nurse_medic_separate',
                                'is_two_day': is_two_day
                            })
                        else:
                            # Regular session
                            session_options.append({
                                'session_time': session_time,
                                'display_time': display_time,
                                'role_requirement': None,
                                'max_students': max_students,
                                'type': 'regular',
                                'is_two_day': is_two_day
                            })
        
        elif is_staff_meeting:
            # Staff meeting with Virtual/LIVE options
            has_live_option = self._check_live_option_for_date(class_name, class_date, class_details)
            
            meeting_types = ['Virtual']
            if has_live_option:
                meeting_types.append('LIVE')
            
            for meeting_type in meeting_types:
                session_options.append({
                    'meeting_type': meeting_type,
                    'display_time': f"{meeting_type} Staff Meeting",
                    'role_requirement': None,
                    'max_students': max_students,
                    'type': 'staff_meeting',
                    'is_two_day': is_two_day
                })
        
        else:
            # Single session class
            if nurses_medic_separate:
                # Create separate options for nurses and medics
                session_options.append({
                    'display_time': 'Nurse Slots',
                    'role_requirement': 'Nurse',
                    'max_students': max_students // 2,
                    'type': 'nurse_medic_separate_single',
                    'is_two_day': is_two_day
                })
                session_options.append({
                    'display_time': 'Medic Slots',
                    'role_requirement': 'Medic',
                    'max_students': max_students // 2,
                    'type': 'nurse_medic_separate_single',
                    'is_two_day': is_two_day
                })
            else:
                # Regular single session
                session_options.append({
                    'display_time': 'Regular Class',
                    'role_requirement': None,
                    'max_students': max_students,
                    'type': 'regular_single',
                    'is_two_day': is_two_day
                })
        
        return session_options
    
    def _create_session_key(self, date_str, session_option):
        """Create a unique key for each session option"""
        base_key = date_str
        
        if 'session_time' in session_option:
            base_key += f"_{session_option['session_time']}"
        
        if 'meeting_type' in session_option:
            base_key += f"_{session_option['meeting_type']}"
        
        if session_option.get('role_requirement'):
            base_key += f"_{session_option['role_requirement']}"
        
        return base_key
    
    def _analyze_session_availability(self, class_name, date_str, session_option, 
                                    assigned_staff, staff_roles, date_obj, include_already_enrolled):
        """
        Analyze staff availability for a specific session
        Filters staff by role eligibility
        """
        available_staff = []
        staff_details = []
        
        # Get role requirement for this session
        role_requirement = session_option.get('role_requirement')
        
        for staff_name in assigned_staff:
            # Get staff role
            staff_role = staff_roles.get(staff_name, 'General')
            
            # Role filtering: skip if staff role doesn't match session requirement
            if role_requirement and staff_role != role_requirement:
                continue
            
            # Check if already enrolled (unless we want to include them)
            if not include_already_enrolled:
                session_time = session_option.get('session_time')
                meeting_type = session_option.get('meeting_type')
                
                if self._is_enrolled_in_session(staff_name, class_name, date_str, session_time, meeting_type):
                    continue
            
            # Check role-based weekly enrollment limits
            week_start = self._get_week_start(date_obj)
            if not self._check_role_weekly_limits(staff_role, staff_name, week_start, date_str):
                continue
            
            # Check for schedule conflicts
            class_details = self.excel.get_class_details(class_name)
            conflict_info = self._check_staff_conflicts(staff_name, class_name, date_str, class_details)
            
            # Staff is available if no blocking conflicts
            if not conflict_info['blocking']:
                available_staff.append(staff_name)
                
                staff_info = {
                    'name': staff_name,
                    'role': staff_role,
                    'warnings': conflict_info['warnings'],
                    'notes': conflict_info['notes']
                }
                staff_details.append(staff_info)
        
        # Get current enrollment count for this session
        current_enrolled = self._get_session_enrollment_count(class_name, date_str, session_option)
        max_students = session_option.get('max_students', 21)
        
        return {
            'session_info': session_option,
            'available_staff': available_staff,
            'staff_details': staff_details,
            'total_available': len(available_staff),
            'class_capacity': max_students,
            'currently_enrolled': current_enrolled,
            'slots_remaining': max_students - current_enrolled
        }
    
    def _get_session_enrollment_count(self, class_name, date_str, session_option):
        """Get current enrollment count for a specific session"""
        session_time = session_option.get('session_time')
        meeting_type = session_option.get('meeting_type')
        role_requirement = session_option.get('role_requirement')
        
        if session_option['type'] == 'staff_meeting':
            return self.enrollment.get_date_enrollment_count(
                class_name, date_str, None, meeting_type, session_time
            )
        elif role_requirement:
            # For nurse/medic separated classes, count only the specific role
            return self.enrollment.get_date_enrollment_count(
                class_name, date_str, role_requirement, meeting_type, session_time
            )
        else:
            # Regular class
            return self.enrollment.get_date_enrollment_count(
                class_name, date_str, None, meeting_type, session_time
            )
    
    def _is_enrolled_in_session(self, staff_name, class_name, date_str, session_time=None, meeting_type=None):
        """Check if staff member is enrolled in a specific session"""
        enrollments = self.enrollment.get_staff_enrollments(staff_name)
        
        for enrollment in enrollments:
            if (enrollment['class_name'] == class_name and 
                enrollment['class_date'] == date_str and
                enrollment.get('session_time') == session_time and
                enrollment.get('meeting_type') == meeting_type):
                return True
        
        return False
    
    def _check_live_option_for_date(self, class_name, class_date, class_details):
        """Check if a specific date has LIVE option for staff meetings"""
        for i in range(1, 15):
            date_key = f'date_{i}'
            live_key = f'date_{i}_has_live'
            
            if date_key in class_details and class_details[date_key] == class_date:
                return class_details.get(live_key, False)
        
        return False
    
    def _is_two_day_class(self, class_name):
        """Check if this is a two-day class"""
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return False
        return class_details.get('is_two_day_class', 'No').lower() == 'yes'
    
    # Keep all existing methods unchanged
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
        """Placeholder data for educator availability preview"""
        return {
            "note": "This would contain educator availability data when fully implemented",
            "date_range": f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}"
        }
    
    def _get_classes_in_date_range(self, start_dt, end_dt):
        """Get all classes that have dates within the specified range"""
        all_classes = self.excel.get_all_classes()
        eligible_classes = {}
        
        print(f"DEBUG: Found {len(all_classes)} total classes")
        print(f"DEBUG: Date range: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
        
        for class_name in all_classes:
            class_details = self.excel.get_class_details(class_name)
            if not class_details:
                print(f"DEBUG: No class details for {class_name}")
                continue
            
            class_dates = []
            found_dates = []
            
            for i in range(1, 15):  # Check up to 14 date slots
                date_key = f'date_{i}'
                if date_key in class_details and class_details[date_key]:
                    found_dates.append(class_details[date_key])
                    try:
                        date_obj = datetime.strptime(class_details[date_key], '%m/%d/%Y')
                        if start_dt <= date_obj <= end_dt:
                            class_dates.append(class_details[date_key])
                            print(f"DEBUG: {class_name} - Found date {class_details[date_key]} in range")
                    except ValueError:
                        print(f"DEBUG: {class_name} - Could not parse date {class_details[date_key]}")
                        continue
            
            print(f"DEBUG: {class_name} - Found dates: {found_dates}, In range: {class_dates}")
            
            if class_dates:
                eligible_classes[class_name] = class_dates
        
        print(f"DEBUG: Eligible classes: {list(eligible_classes.keys())}")
        return eligible_classes
    
    def _get_excel_enrollment_roles(self):
        """Get staff roles from Excel enrollment data"""
        staff_roles = {}
        
        try:
            # Get enrollment data from Excel
            enrollment_data = self.excel.get_enrollment_data()
            if enrollment_data is not None and not enrollment_data.empty:
                for _, row in enrollment_data.iterrows():
                    staff_name = row.get('Staff Name')
                    role = row.get('Role', 'General')
                    if staff_name and pd.notna(staff_name):
                        staff_roles[staff_name] = role
        except Exception as e:
            print(f"Error getting staff roles: {e}")
        
        return staff_roles
    
    def _get_assigned_staff(self, class_name):
        """Get list of staff assigned to a specific class"""
        all_staff = self.excel.get_staff_list()
        assigned_staff = []
        
        print(f"DEBUG: Checking assignments for {class_name}")
        print(f"DEBUG: Total staff in system: {len(all_staff)}")
        
        for staff_name in all_staff:
            assigned_classes = self.excel.get_assigned_classes(staff_name)
            if class_name in assigned_classes:
                assigned_staff.append(staff_name)
                print(f"DEBUG: {staff_name} is assigned to {class_name}")
        
        print(f"DEBUG: {len(assigned_staff)} staff assigned to {class_name}")
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
    
    def _check_role_weekly_limits(self, role, staff_name, week_start, exclude_date):
        """
        Check if staff member can enroll based on role-specific weekly limits
        MEDIC: 1 class per week, RN & MGMT: unlimited
        
        Args:
            role (str): Staff role (MEDIC, RN, MGMT)
            staff_name (str): Name of staff member
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
            
            return weekly_count < 1
        
        # Default: allow enrollment for unknown roles
        return True
    
    def _check_staff_conflicts(self, staff_name, class_name, date_str, class_details):
        """
        Check for scheduling conflicts for a staff member
        
        Returns:
            dict: Contains 'blocking', 'warnings', and 'notes' keys
        """
        conflicts = {
            'blocking': False,
            'warnings': [],
            'notes': []
        }
        
        try:
            # Parse the date
            date_obj = datetime.strptime(date_str, '%m/%d/%Y')
            
            # Check for existing enrollments on the same date
            enrollments = self.enrollment.get_staff_enrollments(staff_name)
            same_date_enrollments = [
                e for e in enrollments 
                if e['class_date'] == date_str and e['class_name'] != class_name
            ]
            
            if same_date_enrollments:
                conflicts['warnings'].append(f"Has {len(same_date_enrollments)} other class(es) on this date")
            
            # Add other conflict checking logic as needed
            # This is a placeholder for additional conflict detection
            
        except ValueError:
            conflicts['warnings'].append("Could not parse date for conflict checking")
        except Exception as e:
            conflicts['warnings'].append(f"Error checking conflicts: {str(e)}")
        
        return conflicts