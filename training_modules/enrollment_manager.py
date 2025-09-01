# training_modules/enrollment_manager.py
"""
Updated Enrollment Manager for the training module that uses the unified database.
Includes duplicate enrollment prevention logic.
"""
from datetime import datetime

class EnrollmentManager:
    def __init__(self, unified_database, excel_handler, track_manager=None):
        """
        Initialize with unified database instead of separate training database.
        
        Args:
            unified_database: UnifiedDatabase instance
            excel_handler: ExcelHandler instance
            track_manager: TrainingTrackManager instance (optional)
        """
        self.db = unified_database
        self.excel = excel_handler
        self.track_manager = track_manager
        
    def check_existing_enrollment(self, staff_name, class_name):
        """Check if staff member is already enrolled in any session of this class"""
        enrollments = self.get_staff_enrollments(staff_name)
        existing_enrollments = [e for e in enrollments if e['class_name'] == class_name]
        return existing_enrollments

    def enroll_staff(self, staff_name, class_name, class_date, role='General', 
                    meeting_type=None, session_time=None, override_conflict=False,
                    replace_existing=False, existing_enrollment_id=None):
        """Enroll a staff member in a class with conflict and duplicate checking"""
        
        # Check for existing enrollments in this class (unless we're doing a replacement)
        if not replace_existing:
            existing_enrollments = self.check_existing_enrollment(staff_name, class_name)
            if existing_enrollments:
                # Return special status indicating duplicate enrollment found
                return "duplicate_found", existing_enrollments
        
        # If replacing existing enrollment, cancel it first
        if replace_existing and existing_enrollment_id:
            cancel_success = self.cancel_enrollment(existing_enrollment_id)
            if not cancel_success:
                return False, "Failed to cancel existing enrollment"
        
        # Check for conflicts if track manager is available
        conflict_details = None
        if self.track_manager and not override_conflict:
            has_conflict, conflict_info = self.check_enrollment_conflict(
                staff_name, class_name, class_date
            )
            
            if has_conflict:
                # Don't allow enrollment without override
                return False, conflict_info
        elif self.track_manager and override_conflict:
            # Get conflict details for recording
            has_conflict, conflict_details = self.check_enrollment_conflict(
                staff_name, class_name, class_date
            )
        
        # Check if enrollment is allowed (slots available, etc.)
        if self.can_enroll(staff_name, class_name, class_date, role, meeting_type, session_time):
            success = self.db.add_enrollment(
                staff_name, class_name, class_date, role, 
                meeting_type, session_time, override_conflict, conflict_details
            )
            if success:
                message = "Enrollment successful"
                if replace_existing:
                    message += " (existing enrollment replaced)"
                return success, message
            else:
                return False, "Enrollment failed"
        
        return False, "No available slots"

    def enroll_staff_with_replacement(self, staff_name, class_name, class_date, role='General',
                                    meeting_type=None, session_time=None, override_conflict=False,
                                    existing_enrollment_id=None):
        """Convenience method for enrolling with replacement of existing enrollment"""
        return self.enroll_staff(
            staff_name, class_name, class_date, role, meeting_type, 
            session_time, override_conflict, replace_existing=True, 
            existing_enrollment_id=existing_enrollment_id
        )

    def get_enrollment_details_for_display(self, enrollment):
        """Format enrollment details for user-friendly display"""
        details = []
        
        # Add date
        details.append(f"Date: {enrollment['class_date']}")
        
        # Add session time if available
        if enrollment.get('session_time'):
            details.append(f"Session: {enrollment['session_time']}")
        
        # Add meeting type if available  
        if enrollment.get('meeting_type'):
            details.append(f"Type: {enrollment['meeting_type']}")
            
        # Add role if not General
        if enrollment.get('role') and enrollment['role'] != 'General':
            details.append(f"Role: {enrollment['role']}")
        
        # Add conflict indicator if applicable
        if enrollment.get('conflict_override'):
            details.append("⚠️ Conflict Override")
            
        return " | ".join(details)

    def get_class_track_conflicts(self, class_name):
        """Get track conflicts summary for all dates of a class - wrapper for UI compatibility"""
        if not self.track_manager:
            return None
        
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return None
        
        # Get all available dates for this class
        dates = []
        can_work_n_prior_list = []
        
        for i in range(1, 9):
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                dates.append(class_details[date_key])
                can_work_n_prior_list.append(class_details.get(f'date_{i}_can_work_n_prior', False))
        
        if not dates:
            return None
        
        # Get all staff assigned to this class
        all_staff = self.excel.get_staff_list()
        assigned_staff = []
        
        for staff_name in all_staff:
            assigned_classes = self.excel.get_assigned_classes(staff_name)
            if class_name in assigned_classes:
                assigned_staff.append(staff_name)
        
        # Collect conflicts for all assigned staff
        class_conflicts = {}
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
        
        for staff_name in assigned_staff:
            if self.track_manager.has_track_data(staff_name):
                staff_conflicts = self.track_manager.get_class_date_conflicts(
                    staff_name, dates, is_two_day, can_work_n_prior_list
                )
                
                if staff_conflicts:
                    class_conflicts[staff_name] = staff_conflicts
        
        return class_conflicts

    def check_enrollment_conflict(self, staff_name, class_name, class_date):
        """Check if there's a schedule conflict for enrollment"""
        if not self.track_manager:
            return False, "No track data available"
        
        # Get class details to check if it's a two-day class and N prior settings
        class_details = self.excel.get_class_details(class_name)
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
        
        # Find which date index this is to get the can_work_n_prior setting
        can_work_n_prior = False
        for i in range(1, 9):
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key] == class_date:
                can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                break
        
        # Check for conflicts
        return self.track_manager.check_class_conflict(
            staff_name, class_date, is_two_day, can_work_n_prior
        )
        
    def can_enroll(self, staff_name, class_name, class_date, role, meeting_type=None, session_time=None):
        """Check if enrollment is allowed based on slots and assignment"""
        # Get class details
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return False
            
        # Check if staff is assigned to this class
        assigned_classes = self.excel.get_assigned_classes(staff_name)
        if class_name not in assigned_classes:
            return False
            
        # Check available slots
        max_students = int(class_details.get('students_per_class', 21))
        
        # For staff meetings, we need to check meeting type specific slots
        if self.excel.is_staff_meeting(class_name) and meeting_type:
            current_enrollment = self.db.get_enrollment_count(class_name, class_date, None, meeting_type, session_time)
        elif class_details.get('nurses_medic_separate', 'No').lower() == 'yes' and role != 'General':
            # If nurses and medics are separate, check role-specific slots
            max_students = max_students // 2
            current_enrollment = self.db.get_enrollment_count(class_name, class_date, role, meeting_type, session_time)
        else:
            current_enrollment = self.db.get_enrollment_count(class_name, class_date, None, meeting_type, session_time)
            
        return current_enrollment < max_students
        
    def cancel_enrollment(self, enrollment_id):
        """Cancel an enrollment"""
        return self.db.cancel_enrollment(enrollment_id)
        
    def get_enrolled_classes(self, staff_name):
        """Get list of class names the staff is enrolled in"""
        enrollments = self.db.get_staff_enrollments(staff_name)
        return list(set([e['class_name'] for e in enrollments]))
        
    def get_staff_enrollments(self, staff_name):
        """Get detailed enrollment information for a staff member"""
        return self.db.get_staff_enrollments(staff_name)
        
    def get_date_enrollment_count(self, class_name, class_date, role=None, meeting_type=None, session_time=None):
        """Get enrollment count for a specific date and role/meeting type/session"""
        return self.db.get_enrollment_count(class_name, class_date, role, meeting_type, session_time)
        
    def get_live_staff_meeting_count(self, staff_name):
        """Get count of LIVE staff meetings for a staff member"""
        return self.db.get_live_staff_meeting_count(staff_name)
        
    def get_session_enrollments(self, class_name, class_date, session_time=None, meeting_type=None):
        """Get list of staff enrolled in a specific session"""
        return self.db.get_session_enrollments(class_name, class_date, session_time, meeting_type)
        
    def get_class_conflicts_summary(self, staff_name, class_name):
        """Get a summary of conflicts for all dates of a class"""
        if not self.track_manager:
            return None
        
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return None
        
        # Collect all dates and their N prior settings - now dynamically checks rows 1-14
        dates = []
        can_work_n_prior_list = []
        locations = []
        
        for i in range(1, 15):  # Check rows 1-14 for dates (only process the ones that exist)
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                dates.append(class_details[date_key])
                can_work_n_prior_list.append(class_details.get(f'date_{i}_can_work_n_prior', False))
                locations.append(class_details.get(f'date_{i}_location', ''))
        
        if not dates:
            return None
        
        # Get conflicts for all dates
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
        conflicts = self.track_manager.get_class_date_conflicts(
            staff_name, dates, is_two_day, can_work_n_prior_list
        )
        
        # Add location info to conflicts
        for i, date in enumerate(dates):
            if date in conflicts and i < len(locations):
                conflicts[date]['location'] = locations[i]
        
        return conflicts        
    def get_available_session_options(self, class_name, class_date):
        """Get available session options with current enrollment info and conflict status"""
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return []
            
        classes_per_day = int(class_details.get('classes_per_day', 1))
        max_students = int(class_details.get('students_per_class', 21))
        nurses_medic_separate = class_details.get('nurses_medic_separate', 'No').lower() == 'yes'
        is_staff_meeting = self.excel.is_staff_meeting(class_name)
        
        session_options = []
        
        if classes_per_day > 1:
            # Multiple sessions per day
            for i in range(1, classes_per_day + 1):
                start_key = f'time_{i}_start'
                end_key = f'time_{i}_end'
                
                if start_key in class_details and end_key in class_details:
                    start_time = class_details[start_key]
                    end_time = class_details[end_key]
                    
                    if start_time and end_time:
                        session_time = f"{start_time}-{end_time}"
                        
                        if nurses_medic_separate:
                            # Get current enrollments for this session
                            nurse_enrollments = self.get_session_enrollments(class_name, class_date, session_time)
                            medic_enrollments = self.get_session_enrollments(class_name, class_date, session_time)
                            
                            # Filter by role
                            nurses = [e for e in nurse_enrollments if e.get('role') == 'Nurse']
                            medics = [e for e in medic_enrollments if e.get('role') == 'Medic']
                            
                            # Create options for both roles
                            nurse_available = len(nurses) < (max_students // 2)
                            medic_available = len(medics) < (max_students // 2)
                            
                            if nurse_available or medic_available:
                                session_options.append({
                                    'session_time': session_time,
                                    'display_time': f"Session {i} ({start_time}-{end_time})",
                                    'nurses': [e['staff_name'] for e in nurses],
                                    'medics': [e['staff_name'] for e in medics],
                                    'nurse_available': nurse_available,
                                    'medic_available': medic_available,
                                    'type': 'nurse_medic_separate'
                                })
                        else:
                            # Regular multiple sessions
                            enrollments = self.get_session_enrollments(class_name, class_date, session_time)
                            available_slots = max_students - len(enrollments)
                            
                            if available_slots > 0:
                                session_options.append({
                                    'session_time': session_time,
                                    'display_time': f"Session {i} ({start_time}-{end_time})",
                                    'enrolled': [e['staff_name'] for e in enrollments],
                                    'available_slots': available_slots,
                                    'type': 'regular'
                                })
        
        elif is_staff_meeting:
            # Staff meeting with LIVE/Virtual options
            for meeting_type in ['LIVE', 'Virtual']:
                enrollments = self.get_session_enrollments(class_name, class_date, None, meeting_type)
                available_slots = max_students - len(enrollments)
                
                if available_slots > 0:
                    session_options.append({
                        'meeting_type': meeting_type,
                        'enrolled': [e['staff_name'] for e in enrollments],
                        'available_slots': available_slots,
                        'type': 'staff_meeting'
                    })
        
        else:
            # Single session
            if nurses_medic_separate:
                # Single session with nurse/medic separation
                nurse_enrollments = self.get_session_enrollments(class_name, class_date)
                medic_enrollments = self.get_session_enrollments(class_name, class_date)
                
                nurses = [e for e in nurse_enrollments if e.get('role') == 'Nurse']
                medics = [e for e in medic_enrollments if e.get('role') == 'Medic']
                
                nurse_available = len(nurses) < (max_students // 2)
                medic_available = len(medics) < (max_students // 2)
                
                if nurse_available or medic_available:
                    session_options.append({
                        'nurses': [e['staff_name'] for e in nurses],
                        'medics': [e['staff_name'] for e in medics],
                        'nurse_available': nurse_available,
                        'medic_available': medic_available,
                        'type': 'nurse_medic_separate_single'
                    })
            else:
                # Single regular session
                enrollments = self.get_session_enrollments(class_name, class_date)
                available_slots = max_students - len(enrollments)
                
                if available_slots > 0:
                    session_options.append({
                        'enrolled': [e['staff_name'] for e in enrollments],
                        'available_slots': available_slots,
                        'type': 'regular_single'
                    })
        
        return session_options
        
    def get_enrollment_summary(self, class_name):
        """Get enrollment summary for all dates of a class"""
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return {}
        
        summary = {}
        
        for i in range(1, 9):
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                date = class_details[date_key]
                enrollments = self.get_session_enrollments(class_name, date)
                summary[date] = len(enrollments)
        
        # Also include staff names for detailed view
        detailed_summary = {}
        for date, count in summary.items():
            enrollments = self.get_session_enrollments(class_name, date)
            detailed_summary[date] = {
                'count': count,
                'enrolled_staff': [e['staff_name'] for e in enrollments]
            }
        
        # Add total unique staff across all dates
        all_enrollments = []
        for date in summary.keys():
            enrollments = self.get_session_enrollments(class_name, date)
            all_enrollments.extend(enrollments)
        
        unique_staff = set()
        for enrollment in all_enrollments:
            unique_staff.add(enrollment['staff_name'])
            
        return summary
    
    def get_class_enrollment_summary(self, class_name):
        """Get enrollment summary for a class with detailed breakdown"""
        enrollments = self.get_staff_enrollments_for_class(class_name)
        
        # Group by date
        summary = {}
        for enrollment in enrollments:
            date = enrollment['class_date']
            if date not in summary:
                summary[date] = {
                    'total': 0,
                    'roles': {},
                    'meeting_types': {},
                    'sessions': {},
                    'conflicts': 0,
                    'staff_names': []
                }
            summary[date]['total'] += 1
            summary[date]['staff_names'].append(enrollment['staff_name'])
            
            # Track conflicts
            if enrollment.get('conflict_override'):
                summary[date]['conflicts'] += 1
            
            # Track roles for nurse/medic separate classes
            role = enrollment.get('role', 'General')
            if role not in summary[date]['roles']:
                summary[date]['roles'][role] = 0
            summary[date]['roles'][role] += 1
            
            # Track meeting types for staff meetings
            meeting_type = enrollment.get('meeting_type')
            if meeting_type:
                if meeting_type not in summary[date]['meeting_types']:
                    summary[date]['meeting_types'][meeting_type] = 0
                summary[date]['meeting_types'][meeting_type] += 1
                
            # Track sessions for multi-session classes
            session_time = enrollment.get('session_time')
            if session_time:
                if session_time not in summary[date]['sessions']:
                    summary[date]['sessions'][session_time] = []
                summary[date]['sessions'][session_time].append(enrollment['staff_name'])
        
        return summary
    
    def get_staff_enrollments_for_class(self, class_name):
        """Get all enrollments for a specific class"""
        # This is a helper method to get all enrollments for a class
        # We'll use the database method if available, otherwise iterate through staff
        try:
            # Try to use a direct database method if it exists
            return self.db.get_class_enrollments(class_name)
        except AttributeError:
            # Fallback: get all staff and filter their enrollments
            all_staff = self.excel.get_staff_list()
            all_enrollments = []
            
            for staff_name in all_staff:
                staff_enrollments = self.get_staff_enrollments(staff_name)
                class_enrollments = [e for e in staff_enrollments if e['class_name'] == class_name]
                all_enrollments.extend(class_enrollments)
            
            return all_enrollments
        
    def get_available_slots(self, class_name, class_date, role='General', meeting_type=None, session_time=None):
        """Get number of available slots for a class date"""
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return 0
            
        max_students = int(class_details.get('students_per_class', 21))
        
        # For staff meetings, check by meeting type
        if self.excel.is_staff_meeting(class_name) and meeting_type:
            current_enrollment = self.db.get_enrollment_count(class_name, class_date, None, meeting_type, session_time)
        elif class_details.get('nurses_medic_separate', 'No').lower() == 'yes' and role != 'General':
            max_students = max_students // 2
            current_enrollment = self.db.get_enrollment_count(class_name, class_date, role, meeting_type, session_time)
        else:
            current_enrollment = self.db.get_enrollment_count(class_name, class_date, None, meeting_type, session_time)
            
        return max(0, max_students - current_enrollment)
        
    def is_enrolled_in_date_and_type(self, staff_name, class_name, class_date, meeting_type=None, session_time=None):
        """Check if staff is already enrolled in a specific date and meeting type/session"""
        enrollments = self.get_staff_enrollments(staff_name)
        
        for enrollment in enrollments:
            if (enrollment['class_name'] == class_name and 
                enrollment['class_date'] == class_date and
                enrollment.get('meeting_type') == meeting_type and
                enrollment.get('session_time') == session_time):
                return True
        return False
        
    def get_session_colleagues(self, staff_name, class_name, class_date, session_time=None, meeting_type=None):
        """Get list of other staff enrolled in the same session"""
        enrollments = self.get_session_enrollments(class_name, class_date, session_time, meeting_type)
        colleagues = []
        
        for enrollment in enrollments:
            if enrollment['staff_name'] != staff_name:
                colleague_info = {
                    'name': enrollment['staff_name'],
                    'role': enrollment.get('role', 'General'),
                    'has_conflict': enrollment.get('conflict_override', False)
                }
                colleagues.append(colleague_info)
                
        return colleagues