# training_modules/availability_analyzer.py
"""
Availability Analyzer for Training Events - COMPLETE FIXED VERSION
Analyzes staff availability for class enrollment within date ranges without conflicts
Updated to handle role-based availability constraints and multiple sessions per day
INCLUDES ALL MISSING METHODS
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
                print("DEBUG: No eligible classes found in date range")
                return {}
            
            print(f"DEBUG: Found {len(eligible_classes)} eligible classes")
            
            # Get staff roles from Excel enrollment data
            staff_roles = self._get_excel_enrollment_roles()
            
            availability_report = {}
            
            for class_name, class_dates in eligible_classes.items():
                print(f"DEBUG: Processing class {class_name} with dates {class_dates}")
                availability_report[class_name] = {}
                
                # Get staff assigned to this class
                assigned_staff = self._get_assigned_staff(class_name) if include_assigned_only else self.excel.get_staff_list()
                
                if not assigned_staff:
                    print(f"DEBUG: No assigned staff found for {class_name}")
                    continue
                
                print(f"DEBUG: Found {len(assigned_staff)} assigned staff for {class_name}")
                
                # Get class details to understand session structure
                class_details = self.excel.get_class_details(class_name)
                if not class_details:
                    print(f"DEBUG: No class details found for {class_name}")
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

        # Get current enrollment count and capacity first
        current_enrolled = self._get_session_enrollment_count(class_name, date_str, session_option)
        max_students = session_option.get('max_students', 21)
        slots_remaining = max_students - current_enrolled
        
        # Early return if session is full
        if slots_remaining <= 0:
            return {
                'session_info': session_option,
                'available_staff': [],
                'staff_details': [],
                'total_available': 0,
                'class_capacity': max_students,
                'currently_enrolled': current_enrolled,
                'slots_remaining': 0
            }
        
        # Check if this is a 2-day class
        class_details = self.excel.get_class_details(class_name)
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes' if class_details else False
        
        # Analyze all assigned staff
        available_staff = []
        staff_details = []
        
        for staff_name in assigned_staff:
            # Skip if already enrolled (unless we want to include them)
            if not include_already_enrolled:
                if self._is_enrolled_in_class_anywhere(staff_name, class_name):
                    continue
            
            # Check role requirement if session has one
            role_requirement = session_option.get('role_requirement')
            if role_requirement:
                staff_role = staff_roles.get(staff_name, 'General')
                if role_requirement == 'Nurse' and staff_role not in ['NURSE', 'RN', 'Nurse']:
                    continue
                if role_requirement == 'Medic' and staff_role not in ['MEDIC', 'Medic']:
                    continue
            
            # Check weekly enrollment limit
            weekly_limit_ok, weekly_limit_reason = self._check_weekly_enrollment_limit_for_availability(staff_name, date_str)
            if not weekly_limit_ok:
                # Add to staff details with weekly limit warning (shown in admin view)
                staff_details.append({
                    'name': staff_name,
                    'role': staff_roles.get(staff_name, 'General'),
                    'warnings': [weekly_limit_reason],
                    'notes': [],
                    'has_conflict': True,
                    'conflict_details': weekly_limit_reason,
                    'can_override': False
                })
                continue
            
            # Enhanced conflict checking for 2-day classes
            has_conflict = False
            conflict_details = ""
            
            if is_two_day:
                # For 2-day classes, check BOTH days for conflicts
                both_days = self._get_two_day_dates(date_str)
                day_conflicts = []
                
                for i, day in enumerate(both_days):
                    has_day_conflict, day_conflict_details = self.enrollment.check_enrollment_conflict(
                        staff_name, class_name, day
                    )
                    
                    if has_day_conflict:
                        day_label = f"Day {i+1} ({day})"
                        day_conflicts.append(f"{day_label}: {day_conflict_details}")
                
                if day_conflicts:
                    has_conflict = True
                    conflict_details = "; ".join(day_conflicts)
            else:
                # Single-day classes
                has_conflict, conflict_details = self.enrollment.check_enrollment_conflict(
                    staff_name, class_name, date_str
                )
            
            # Add ALL staff to available list (including those with conflicts)
            available_staff.append(staff_name)
            
            # Create staff detail entry for ADMIN VIEW display
            staff_detail = {
                'name': staff_name,
                'role': staff_roles.get(staff_name, 'General'),
                'warnings': [],
                'notes': [],
                'has_conflict': has_conflict,
                'conflict_details': conflict_details if has_conflict else "No conflicts",
                'can_override': True
            }
            
            # SINGLE PLACE for conflict display - only add warning here
            if has_conflict:
                if is_two_day:
                    staff_detail['warnings'].append("Schedule conflicts on 2-day class")
                else:
                    staff_detail['warnings'].append("Schedule conflict")
            
            staff_details.append(staff_detail)
        
        return {
            'session_info': session_option,
            'available_staff': available_staff,
            'staff_details': staff_details,
            'total_available': len([s for s in staff_details if not s['has_conflict']]),
            'total_with_conflicts': len([s for s in staff_details if s['has_conflict']]),
            'class_capacity': max_students,
            'currently_enrolled': current_enrolled,
            'slots_remaining': slots_remaining
        }

    def _get_two_day_dates(self, base_date):
        """
        Get both days for a two-day class
        
        Args:
            base_date (str): Base date in MM/DD/YYYY format
            
        Returns:
            list: List of both dates [day1, day2]
        """
        try:
            from datetime import datetime, timedelta
            date_obj = datetime.strptime(base_date, '%m/%d/%Y')
            day_1 = date_obj.strftime('%m/%d/%Y')
            day_2 = (date_obj + timedelta(days=1)).strftime('%m/%d/%Y')
            return [day_1, day_2]
        except ValueError:
            return [base_date]
    
    def _check_weekly_enrollment_limit_for_availability(self, staff_name, class_date):
        """
        Check weekly enrollment limit for non-MGMT medics (1 class per week)
        Returns (can_enroll, error_message)
        """
        # Only apply to non-MGMT medics
        if not self._is_non_mgmt_medic(staff_name):
            return True, None
        
        try:
            # Parse the target date
            target_date = datetime.strptime(class_date, '%m/%d/%Y')
            
            # Calculate week boundaries (Sunday to Saturday)
            days_since_sunday = (target_date.weekday() + 1) % 7
            week_start = target_date - timedelta(days=days_since_sunday)
            week_end = week_start + timedelta(days=6)
            
            # Get all enrollments for this staff member
            enrollments = self.enrollment.get_staff_enrollments(staff_name)
            
            # Check for existing enrollments in the same week
            for enrollment in enrollments:
                try:
                    enrollment_date = datetime.strptime(enrollment['class_date'], '%m/%d/%Y')
                    
                    # If enrollment is in the same week
                    if week_start <= enrollment_date <= week_end:
                        # Found existing enrollment in this week
                        existing_class = enrollment['class_name']
                        error_message = f"Already enrolled in {existing_class} this week (1 class per week limit)"
                        return False, error_message
                        
                except ValueError:
                    continue  # Skip if date parsing fails
            
            # No existing enrollments found in this week
            return True, None
            
        except Exception as e:
            print(f"Error checking weekly limit for {staff_name}: {e}")
            return True, None  # Allow enrollment if error occurs

    def _is_non_mgmt_medic(self, staff_name):
        """
        Check if staff member is a non-MGMT medic
        Returns True if Role=MEDIC and MGMT checkbox is unchecked
        """
        try:
            if not self.excel.enrollment_sheet:
                return False
            
            # Find the staff member's row
            staff_row = None
            for row_idx, row in enumerate(self.excel.enrollment_sheet.iter_rows(min_row=2, max_col=1), start=2):
                if row[0].value and str(row[0].value).strip() == staff_name:
                    staff_row = row_idx
                    break
            
            if not staff_row:
                return False
            
            # Find Role and MGMT columns
            role_col = None
            mgmt_col = None
            
            for col_idx, col in enumerate(self.excel.enrollment_sheet.iter_cols(min_row=1, max_row=1), start=1):
                header_value = str(col[0].value).strip() if col[0].value else ""
                if header_value == "Role":
                    role_col = col_idx
                elif header_value == "MGMT":
                    mgmt_col = col_idx
            
            if not role_col or not mgmt_col:
                return False
            
            # Get role and MGMT values
            role_cell = self.excel.enrollment_sheet.cell(row=staff_row, column=role_col)
            mgmt_cell = self.excel.enrollment_sheet.cell(row=staff_row, column=mgmt_col)
            
            role_value = str(role_cell.value).strip().upper() if role_cell.value else ""
            mgmt_value = mgmt_cell.value
            
            # Check if Role is MEDIC and MGMT is not checked
            is_medic = role_value == "MEDIC"
            is_mgmt = self.excel._parse_checkbox_value(mgmt_value) if hasattr(self.excel, '_parse_checkbox_value') else bool(mgmt_value)
            
            return is_medic and not is_mgmt
            
        except Exception as e:
            print(f"Error checking non-MGMT medic status for {staff_name}: {e}")
            return False

    def _is_enrolled_in_class_on_date(self, staff_name, class_name, date_str):
        """Check if staff member is enrolled in ANY session of this class on the given date"""
        enrollments = self.enrollment.get_staff_enrollments(staff_name)
        
        for enrollment in enrollments:
            if (enrollment['class_name'] == class_name and 
                enrollment['class_date'] == date_str):
                return True
        
        return False

    def _is_enrolled_in_class_anywhere(self, staff_name, class_name):
        """Check if staff member is enrolled in this class on ANY date"""
        enrolled_classes = self.enrollment.get_enrolled_classes(staff_name)
        return class_name in enrolled_classes

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
        """Get staff roles from Excel enrollment data - FIXED VERSION"""
        staff_roles = {}
        
        try:
            if not self.excel.enrollment_sheet:
                print("No enrollment sheet available")
                return staff_roles
            
            # Find the Role column
            role_col = None
            for col_idx, col in enumerate(self.excel.enrollment_sheet.iter_cols(min_row=1, max_row=1), start=1):
                header_value = str(col[0].value).strip() if col[0].value else ""
                if header_value == "Role":
                    role_col = col_idx
                    break
            
            if not role_col:
                print("Role column not found")
                return staff_roles
            
            # Read staff names and roles
            for row in self.excel.enrollment_sheet.iter_rows(min_row=2):
                staff_name_cell = row[0].value
                role_cell = row[role_col - 1].value if len(row) >= role_col else None
                
                if staff_name_cell:
                    staff_name = str(staff_name_cell).strip()
                    role = str(role_cell).strip() if role_cell else 'General'
                    staff_roles[staff_name] = role
            
            print(f"DEBUG: Loaded roles for {len(staff_roles)} staff members")
            return staff_roles
            
        except Exception as e:
            print(f"Error getting staff roles: {e}")
            import traceback
            traceback.print_exc()
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
        if role in ['NURSE']:
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