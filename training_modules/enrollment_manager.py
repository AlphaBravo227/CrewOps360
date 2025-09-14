# training_modules/enrollment_manager.py - FIXED VERSION for Two-Day Classes
"""
Updated Enrollment Manager with proper two-day class support.
FIXED: Handles consecutive day enrollment, conflict checking, and cancellation.
"""
from datetime import datetime, timedelta

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
        
    def _get_two_day_dates(self, base_date_str):
        """Convert base date string to both days for two-day class"""
        try:
            base_date = datetime.strptime(base_date_str, '%m/%d/%Y')
            day_1 = base_date.strftime('%m/%d/%Y')
            day_2 = (base_date + timedelta(days=1)).strftime('%m/%d/%Y')
            return [day_1, day_2]
        except ValueError:
            return [base_date_str]  # Return original if parsing fails
    
    def _is_two_day_class(self, class_name):
        """Check if a class is configured as a two-day class"""
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return False
        return class_details.get('is_two_day_class', 'No').lower() == 'yes'
    
    def check_existing_enrollment(self, staff_name, class_name):
        """Check if staff member is already enrolled in any session of this class"""
        enrollments = self.get_staff_enrollments(staff_name)
        existing_enrollments = [e for e in enrollments if e['class_name'] == class_name]
        return existing_enrollments

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

    def _check_weekly_enrollment_limit(self, staff_name, class_date):
        """
        Check weekly enrollment limit for non-MGMT medics (1 class per week)
        Returns (can_enroll, error_message, existing_class)
        """
        # Only apply to non-MGMT medics
        if not self._is_non_mgmt_medic(staff_name):
            return True, None, None
        
        try:
            # Parse the target date
            target_date = datetime.strptime(class_date, '%m/%d/%Y')
            
            # Calculate week boundaries (Sunday to Saturday)
            days_since_sunday = (target_date.weekday() + 1) % 7
            week_start = target_date - timedelta(days=days_since_sunday)
            week_end = week_start + timedelta(days=6)
            
            # Get all enrollments for this staff member
            enrollments = self.get_staff_enrollments(staff_name)
            
            # Check for existing enrollments in the same week
            for enrollment in enrollments:
                try:
                    enrollment_date = datetime.strptime(enrollment['class_date'], '%m/%d/%Y')
                    
                    # If enrollment is in the same week
                    if week_start <= enrollment_date <= week_end:
                        # Found existing enrollment in this week
                        existing_class = enrollment['class_name']
                        error_message = f"Cannot enroll - you are already enrolled in {existing_class} this week and are limited to one class per week."
                        return False, error_message, existing_class
                        
                except ValueError:
                    continue  # Skip if date parsing fails
            
            # No existing enrollments found in this week
            return True, None, None
            
        except Exception as e:
            print(f"Error checking weekly limit for {staff_name}: {e}")
            return True, None, None  # Allow enrollment if error occurs

    def enroll_staff(self, staff_name, class_name, class_date, role='General', 
                    meeting_type=None, session_time=None, override_conflict=False,
                    replace_existing=False, existing_enrollment_id=None):
        """Enroll a staff member in a class with proper two-day class support"""
        
        # Check if this is a Staff Meeting class or two-day class
        is_staff_meeting = self.excel.is_staff_meeting(class_name)
        is_two_day = self._is_two_day_class(class_name)
        
        print(f"DEBUG: Enrolling {staff_name} in {class_name} - Two-day: {is_two_day}")
        
        # Get the actual dates to enroll (single date or two consecutive days)
        if is_two_day:
            enrollment_dates = self._get_two_day_dates(class_date)
            print(f"DEBUG: Two-day enrollment dates: {enrollment_dates}")
        else:
            enrollment_dates = [class_date]
        # NEW: Check weekly enrollment limit for non-MGMT medics
        # Check each enrollment date for weekly limits
        for date in enrollment_dates:
            can_enroll, limit_error, existing_class = self._check_weekly_enrollment_limit(staff_name, date)
            if not can_enroll:
                return False, limit_error
        
        # Skip duplicate check for Staff Meeting classes (they can enroll multiple times)
        if not replace_existing and not is_staff_meeting:
            existing_enrollments = self.check_existing_enrollment(staff_name, class_name)
            if existing_enrollments:
                return "duplicate_found", existing_enrollments
        
        # For Staff Meeting classes, check if they're already enrolled in this specific session
        if is_staff_meeting and not replace_existing:
            for date in enrollment_dates:
                is_already_enrolled = self.is_enrolled_in_date_and_type(
                    staff_name, class_name, date, meeting_type, session_time
                )
                if is_already_enrolled:
                    return False, "You are already enrolled in this specific Staff Meeting session"
        
        # If replacing existing enrollment, cancel it first
        if replace_existing and existing_enrollment_id:
            cancel_success = self.cancel_enrollment(existing_enrollment_id)
            if not cancel_success:
                return False, "Failed to cancel existing enrollment"
        
        # Check for conflicts on ALL dates if track manager is available
        combined_conflict_details = []
        if self.track_manager and not override_conflict:
            for i, date in enumerate(enrollment_dates):
                has_conflict, conflict_info = self.check_enrollment_conflict(
                    staff_name, class_name, date
                )
                
                if has_conflict:
                    day_label = f"Day {i+1}" if is_two_day else "Date"
                    combined_conflict_details.append(f"{day_label}: {conflict_info}")
            
            # If ANY day has conflicts, block enrollment
            if combined_conflict_details:
                combined_message = "; ".join(combined_conflict_details)
                print(f"DEBUG: Schedule conflicts found: {combined_message}")
                return False, combined_message
                
        elif self.track_manager and override_conflict:
            # Get conflict details for recording
            for i, date in enumerate(enrollment_dates):
                has_conflict, conflict_info = self.check_enrollment_conflict(
                    staff_name, class_name, date
                )
                if has_conflict:
                    day_label = f"Day {i+1}" if is_two_day else "Date"
                    combined_conflict_details.append(f"{day_label}: {conflict_info}")
        
        # Check if enrollment is allowed for ALL dates
        for date in enrollment_dates:
            can_enroll_result = self.can_enroll(staff_name, class_name, date, role, meeting_type, session_time)
            if not can_enroll_result:
                return False, f"No available slots for {date}"
        
        # Perform the enrollment for all dates
        combined_conflict_str = "; ".join(combined_conflict_details) if combined_conflict_details else None
        success_count = 0
        
        for date in enrollment_dates:
            print(f"DEBUG: Attempting to add enrollment for {date}")
            success = self.db.add_enrollment(
                staff_name, class_name, date, role, 
                meeting_type, session_time, override_conflict, combined_conflict_str
            )
            
            if success:
                success_count += 1
            else:
                print(f"DEBUG: Failed to add enrollment for {date}")
        
        if success_count == len(enrollment_dates):
            # All enrollments successful
            message = "Enrollment successful"
            if replace_existing:
                message += " (existing enrollment replaced)"
            elif is_two_day:
                message += f" for both days ({enrollment_dates[0]} and {enrollment_dates[1]})"
            elif is_staff_meeting:
                progress = self.get_staff_meeting_progress(staff_name)
                total_enrolled = progress['total_enrolled']
                live_enrolled = progress['live_enrolled']
                
                if total_enrolled > 1:
                    message += f" - You now have {total_enrolled}/8 Staff Meeting sessions"
                    if meeting_type == 'LIVE':
                        message += f" ({live_enrolled}/2 LIVE)"
                    else:
                        message += f" ({live_enrolled}/2 LIVE)"
            return True, message
        elif success_count > 0:
            # Partial success - this shouldn't happen but handle it
            return False, f"Partial enrollment failure ({success_count}/{len(enrollment_dates)} days enrolled)"
        else:
            # Complete failure
            if not is_staff_meeting:
                existing_enrollments = self.check_existing_enrollment(staff_name, class_name)
                if existing_enrollments:
                    return "duplicate_found", existing_enrollments
            return False, "Enrollment failed - unknown error"

    def cancel_enrollment(self, enrollment_id):
        """Cancel an enrollment - for two-day classes, cancel both days automatically"""
        # Get the enrollment details first
        enrollments = self.get_staff_enrollments_by_id(enrollment_id)
        if not enrollments:
            return False
        
        enrollment = enrollments[0]
        staff_name = enrollment['staff_name']
        class_name = enrollment['class_name']
        class_date = enrollment['class_date']
        
        # Check if this is a two-day class
        is_two_day = self._is_two_day_class(class_name)
        
        if is_two_day:
            print(f"DEBUG: Cancelling two-day class enrollment for {staff_name}")
            
            # Get both days for this enrollment
            enrollment_dates = self._get_two_day_dates(class_date)
            
            # Cancel all enrollments for this class on both days
            all_enrollments = self.get_staff_enrollments(staff_name)
            cancelled_count = 0
            
            for enroll in all_enrollments:
                if (enroll['class_name'] == class_name and 
                    enroll['class_date'] in enrollment_dates):
                    if self.db.cancel_enrollment(enroll['id']):
                        cancelled_count += 1
            
            print(f"DEBUG: Cancelled {cancelled_count} enrollments for two-day class")
            return cancelled_count > 0
        else:
            # Single day cancellation
            return self.db.cancel_enrollment(enrollment_id)
    
    def get_staff_enrollments_by_id(self, enrollment_id):
        """Helper method to get enrollment details by ID"""
        # This is a simplified implementation - you may need to adjust based on your database structure
        try:
            self.db.connect()
            self.db.cursor.execute('''
                SELECT * FROM training_enrollments WHERE id = ? AND status = 'active'
            ''', (enrollment_id,))
            result = self.db.cursor.fetchall()
            
            enrollments = []
            for row in result:
                enrollments.append({
                    'id': row['id'],
                    'staff_name': row['staff_name'],
                    'class_name': row['class_name'],
                    'class_date': row['class_date'],
                    'role': row['role'],
                    'meeting_type': row['meeting_type'],
                    'session_time': row['session_time'],
                    'conflict_override': row['conflict_override'],
                    'conflict_details': row['conflict_details'],
                    'status': row['status']
                })
            
            self.db.disconnect()
            return enrollments
        except Exception as e:
            print(f"Error getting enrollment by ID: {e}")
            if hasattr(self.db, 'disconnect'):
                self.db.disconnect()
            return []

    def check_enrollment_conflict(self, staff_name, class_name, class_date):
        """Check if there's a schedule conflict for enrollment - works with individual dates"""
        if not self.track_manager:
            return False, "No track data available"
        
        # Get class details to check N prior settings
        class_details = self.excel.get_class_details(class_name)
        
        # Find which date index this is to get the can_work_n_prior setting
        can_work_n_prior = False
        for i in range(1, 15):  # Check rows 1-14
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key] == class_date:
                can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                break
        
        # For two-day classes, we check each day individually but don't pass is_two_day=True
        # because we're checking a specific single date, not the full two-day sequence
        return self.track_manager.check_class_conflict(
            staff_name, class_date, False, can_work_n_prior  # Always False here since we check each day individually
        )

    # ... (rest of the methods remain the same as in the original file)
    
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
        
        for i in range(1, 15):  # Check rows 1-14
            date_key = f'date_{i}'
            if date_key in class_details and class_details[date_key]:
                base_date = class_details[date_key]
                
                # For two-day classes, expand to both days
                if self._is_two_day_class(class_name):
                    both_days = self._get_two_day_dates(base_date)
                    dates.extend(both_days)
                    can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                    can_work_n_prior_list.extend([can_work_n_prior, can_work_n_prior])
                else:
                    dates.append(base_date)
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
        
        for staff_name in assigned_staff:
            if self.track_manager.has_track_data(staff_name):
                staff_conflicts = {}
                
                # Check each date individually for two-day classes
                for i, date in enumerate(dates):
                    can_work_n = can_work_n_prior_list[i] if i < len(can_work_n_prior_list) else False
                    has_conflict, conflict_details = self.track_manager.check_class_conflict(
                        staff_name, date, False, can_work_n  # Check each day individually
                    )
                    
                    if has_conflict:
                        staff_conflicts[date] = {
                            'has_conflict': True,
                            'details': conflict_details,
                            'shift': self.track_manager.get_staff_shift(staff_name, date)
                        }
                
                if staff_conflicts:
                    class_conflicts[staff_name] = staff_conflicts
        
        return class_conflicts

    # Keep all other existing methods unchanged...
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
        
        available_slots = max_students - current_enrollment
        
        return available_slots > 0

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
    
    def get_staff_meeting_enrollments(self, staff_name, class_name=None):
        """Get all Staff Meeting enrollments for a staff member"""
        all_enrollments = self.get_staff_enrollments(staff_name)
        
        # Filter for Staff Meeting classes
        sm_enrollments = []
        for enrollment in all_enrollments:
            enrollment_class = enrollment['class_name']
            if self.excel.is_staff_meeting(enrollment_class):
                # If specific class requested, filter further
                if class_name is None or enrollment_class == class_name:
                    sm_enrollments.append(enrollment)
        
        return sm_enrollments

    def get_staff_meeting_progress(self, staff_name):
        """Get Staff Meeting progress including total and LIVE count requirements"""
        sm_enrollments = self.get_staff_meeting_enrollments(staff_name)
        
        total_sessions = len(sm_enrollments)
        live_sessions = 0
        virtual_sessions = 0
        
        # Count LIVE vs Virtual sessions
        for enrollment in sm_enrollments:
            meeting_type = enrollment.get('meeting_type', 'Virtual')
            if meeting_type == 'LIVE':
                live_sessions += 1
            else:
                virtual_sessions += 1
        
        # Calculate progress
        total_required = 8
        live_required = 2
        
        progress = {
            'total_enrolled': total_sessions,
            'total_required': total_required,
            'total_remaining': max(0, total_required - total_sessions),
            'live_enrolled': live_sessions,
            'live_required': live_required,
            'live_remaining': max(0, live_required - live_sessions),
            'virtual_enrolled': virtual_sessions,
            'total_complete': total_sessions >= total_required,
            'live_complete': live_sessions >= live_required,
            'all_requirements_met': total_sessions >= total_required and live_sessions >= live_required
        }
        
        return progress

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

    def get_available_session_options(self, class_name, class_date):
        """Get available session options - updated for two-day class display"""
        class_details = self.excel.get_class_details(class_name)
        if not class_details:
            return []
            
        classes_per_day = int(class_details.get('classes_per_day', 1))
        max_students = int(class_details.get('students_per_class', 21))
        nurses_medic_separate = class_details.get('nurses_medic_separate', 'No').lower() == 'yes'
        is_staff_meeting = self.excel.is_staff_meeting(class_name)
        is_two_day = self._is_two_day_class(class_name)
        
        session_options = []
        
        # Add two-day indicator to display if applicable
        date_display = class_date
        if is_two_day:
            both_days = self._get_two_day_dates(class_date)
            if len(both_days) == 2:
                date_display = f"{both_days[0]} - {both_days[1]} (2-Day Class)"
        
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
                        display_time = f"Session {i} ({start_time}-{end_time})"
                        
                        if is_two_day:
                            display_time += " - 2-Day Class"
                        
                        if nurses_medic_separate:
                            # Get enrollments for first day only (they enroll for both days together)
                            all_enrollments = self.get_session_enrollments(class_name, class_date, session_time)
                            
                            nurses = []
                            medics = []
                            
                            for enrollment in all_enrollments:
                                role = enrollment.get('role', 'General')
                                staff_name = enrollment['staff_name']
                                
                                if role == 'Nurse':
                                    nurses.append(staff_name)
                                elif role == 'Medic':
                                    medics.append(staff_name)
                            
                            max_per_role = max_students // 2
                            nurse_available = len(nurses) < max_per_role
                            medic_available = len(medics) < max_per_role
                            
                            session_options.append({
                                'session_time': session_time,
                                'display_time': display_time,
                                'nurses': nurses,
                                'medics': medics,
                                'nurse_available': nurse_available,
                                'medic_available': medic_available,
                                'type': 'nurse_medic_separate',
                                'is_two_day': is_two_day,
                                'date_display': date_display
                            })
                        else:
                            # Regular multiple sessions
                            all_enrollments = self.get_session_enrollments(class_name, class_date, session_time)
                            enrolled_names = [e['staff_name'] for e in all_enrollments]
                            available_slots = max_students - len(enrolled_names)
                            
                            session_options.append({
                                'session_time': session_time,
                                'display_time': display_time,
                                'enrolled': enrolled_names,
                                'available_slots': available_slots,
                                'type': 'regular',
                                'is_two_day': is_two_day,
                                'date_display': date_display
                            })
        
        elif is_staff_meeting:
            # Staff meeting logic (unchanged, but add two-day support if needed)
            has_live_option = False
            for i in range(1, 15):
                date_key = f'date_{i}'
                live_key = f'date_{i}_has_live'
                
                if date_key in class_details and class_details[date_key] == class_date:
                    has_live_option = class_details.get(live_key, False)
                    break
            
            meeting_types = ['Virtual']
            if has_live_option:
                meeting_types.append('LIVE')
            
            for meeting_type in meeting_types:
                all_enrollments = self.get_session_enrollments(class_name, class_date, None, meeting_type)
                enrolled_names = [e['staff_name'] for e in all_enrollments]
                available_slots = max_students - len(enrolled_names)
                
                session_options.append({
                    'meeting_type': meeting_type,
                    'enrolled': enrolled_names,
                    'available_slots': available_slots,
                    'type': 'staff_meeting',
                    'is_two_day': is_two_day,
                    'date_display': date_display
                })
        
        else:
            # Single session
            if nurses_medic_separate:
                # Single session with nurse/medic separation
                all_enrollments = self.get_session_enrollments(class_name, class_date)
                
                nurses = []
                medics = []
                
                for enrollment in all_enrollments:
                    role = enrollment.get('role', 'General')
                    staff_name = enrollment['staff_name']
                    
                    if role == 'Nurse':
                        nurses.append(staff_name)
                    elif role == 'Medic':
                        medics.append(staff_name)
                
                max_per_role = max_students // 2
                nurse_available = len(nurses) < max_per_role
                medic_available = len(medics) < max_per_role
                
                session_options.append({
                    'nurses': nurses,
                    'medics': medics,
                    'nurse_available': nurse_available,
                    'medic_available': medic_available,
                    'type': 'nurse_medic_separate_single',
                    'is_two_day': is_two_day,
                    'date_display': date_display
                })
            else:
                # Single regular session
                all_enrollments = self.get_session_enrollments(class_name, class_date)
                enrolled_names = [e['staff_name'] for e in all_enrollments]
                available_slots = max_students - len(enrolled_names)
                
                session_options.append({
                    'enrolled': enrolled_names,
                    'available_slots': available_slots,
                    'type': 'regular_single',
                    'is_two_day': is_two_day,
                    'date_display': date_display
                })
        
        return session_options

    def get_class_enrollment_summary(self, class_name):
        """Get enrollment summary for a class with detailed statistics"""
        enrollments = self.db.get_class_enrollments(class_name)
        
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