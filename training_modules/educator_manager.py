# training_modules/educator_manager.py - FIXED for 2-day class support
"""
Educator Signup Manager for the training module that handles educator signups
with track conflict checking and proper 2-day class support.
"""
from datetime import datetime, timedelta

class EducatorManager:
    def __init__(self, unified_database, excel_handler, track_manager=None):
        """
        Initialize with unified database and other components.
        
        Args:
            unified_database: UnifiedDatabase instance
            excel_handler: ExcelHandler instance
            track_manager: TrainingTrackManager instance (optional)
        """
        self.db = unified_database
        self.excel = excel_handler
        self.track_manager = track_manager
        
    def get_educator_opportunities(self):
        """Get all classes that need educators (non-zero instructor count) with expanded 2-day support"""
        all_classes = self.excel.get_all_classes()
        opportunities = []
        
        for class_name in all_classes:
            class_details = self.excel.get_class_details(class_name)
            
            if not class_details:
                print(f"Warning: No class details found for {class_name}")
                continue
            
            # Check if class has instructor requirements (row 21, column B)
            instructor_count = class_details.get('instructors_per_day', 0)
            
            # Convert to int if it's a string or float
            try:
                instructor_count = int(float(instructor_count)) if instructor_count else 0
            except (ValueError, TypeError):
                instructor_count = 0
                print(f"Warning: Could not parse instructor count for {class_name}: {class_details.get('instructors_per_day')}")
            
            # Only include classes that need instructors
            if instructor_count > 0:
                # Check if this is a two-day class
                is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
                
                # Get all available dates for this class
                base_dates = []
                for i in range(1, 9):
                    date_key = f'date_{i}'
                    if date_key in class_details and class_details[date_key]:
                        base_dates.append(class_details[date_key])
                
                # Expand dates for 2-day classes
                expanded_dates = []
                if is_two_day:
                    for base_date in base_dates:
                        try:
                            # Parse the date and add both days
                            date_obj = datetime.strptime(base_date, '%m/%d/%Y')
                            day_1 = date_obj.strftime('%m/%d/%Y')
                            day_2 = (date_obj + timedelta(days=1)).strftime('%m/%d/%Y')
                            
                            expanded_dates.extend([day_1, day_2])
                            print(f"DEBUG: Expanded 2-day class {class_name} date {base_date} to [{day_1}, {day_2}]")
                        except ValueError as e:
                            print(f"Warning: Could not parse date {base_date} for class {class_name}: {e}")
                            expanded_dates.append(base_date)  # Add original if parsing fails
                else:
                    expanded_dates = base_dates
                
                if expanded_dates:  # Only include if there are actual dates
                    opportunities.append({
                        'class_name': class_name,
                        'instructor_count': instructor_count,
                        'available_dates': expanded_dates,
                        'class_details': class_details,
                        'is_two_day': is_two_day
                    })
                    print(f"DEBUG: Added opportunity for {class_name} with {len(expanded_dates)} dates (2-day: {is_two_day})")
                else:
                    print(f"Warning: Class {class_name} needs {instructor_count} instructors but has no available dates")
        
        return opportunities
    
    def can_signup_as_educator(self, staff_name, class_name, class_date):
        """Check if staff can sign up as educator for this class/date"""
        
        try:
            print(f"DEBUG: Checking signup eligibility for {staff_name} in {class_name} on {class_date}")
            
            # Check if already signed up for this specific class/date
            existing_signup = self.db.check_existing_educator_signup(staff_name, class_name, class_date)
            if existing_signup:
                print(f"DEBUG: Already signed up")
                return False, "Already signed up as educator for this date"
            
            # Check capacity
            class_details = self.excel.get_class_details(class_name)
            if not class_details:
                print(f"DEBUG: No class details found for {class_name}")
                return False, "Class details not found"
            
            instructor_count = class_details.get('instructors_per_day', 0)
            print(f"DEBUG: Raw instructor count for {class_name}: {repr(instructor_count)}")
            
            try:
                max_instructors = int(float(instructor_count)) if instructor_count else 0
            except (ValueError, TypeError) as e:
                print(f"DEBUG: Error parsing instructor count: {e}")
                max_instructors = 0
            
            print(f"DEBUG: Parsed max instructors: {max_instructors}")
            
            if max_instructors <= 0:
                print(f"DEBUG: No educator positions available")
                return False, "No educator positions available for this class"
            
            # Check current signups vs capacity
            current_signups = self.db.get_educator_signup_count(class_name, class_date)
            print(f"DEBUG: Current signups: {current_signups}, Max: {max_instructors}")
            
            if current_signups >= max_instructors:
                return False, f"Educator positions full ({current_signups}/{max_instructors})"
            
            print(f"DEBUG: Signup allowed")
            return True, "Available"
            
        except Exception as e:
            print(f"Error in can_signup_as_educator: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Error checking eligibility: {str(e)}"
    
    def get_class_educator_roster(self, class_name, class_date=None):
        """Get educator roster for a specific class/date"""
        signups = self.db.get_educator_signups_for_class(class_name, class_date)
        
        roster_data = []
        for signup in signups:
            roster_data.append({
                'staff_name': signup['staff_name'],
                'class_date': signup['class_date'],
                'signup_date': signup.get('signup_date_display', ''),
                'has_conflict': signup.get('conflict_override', False),
                'conflict_details': signup.get('conflict_details', ''),
                'status': signup.get('status', 'active')
            })
        
        return roster_data
    
    def get_classes_needing_educators(self):
        """Get classes that still need educator signups with proper 2-day support"""
        opportunities = self.get_educator_opportunities()
        needs_educators = []
        
        for opportunity in opportunities:
            class_name = opportunity['class_name']
            instructor_count = opportunity['instructor_count']
            
            for date in opportunity['available_dates']:
                current_signups = self.db.get_educator_signup_count(class_name, date)
                
                if current_signups < instructor_count:
                    needs_educators.append({
                        'class_name': class_name,
                        'class_date': date,
                        'needed': instructor_count - current_signups,
                        'current': current_signups,
                        'required': instructor_count,
                        'is_two_day': opportunity['is_two_day']
                    })
        
        return needs_educators
    
    def check_educator_conflict(self, staff_name, class_name, class_date):
        """
        Check if there's a schedule conflict for educator signup.
        AT shifts are ignored for educators as they are placeholders.
        For 2-day classes, we check conflicts for the specific date only.
        """
        if not self.track_manager:
            return False, "No track data available"
        
        # Get class details to check if it's a two-day class and N prior settings
        class_details = self.excel.get_class_details(class_name)
        is_two_day = class_details.get('is_two_day_class', 'No').lower() == 'yes'
        
        # Find which date index this is to get the can_work_n_prior setting
        # For 2-day classes, we need to map the specific date back to the base date
        can_work_n_prior = False
        
        if is_two_day:
            # For 2-day classes, find the base date that this specific date belongs to
            try:
                current_date_obj = datetime.strptime(class_date, '%m/%d/%Y')
                
                for i in range(1, 9):
                    date_key = f'date_{i}'
                    if date_key in class_details and class_details[date_key]:
                        base_date_obj = datetime.strptime(class_details[date_key], '%m/%d/%Y')
                        day_2_obj = base_date_obj + timedelta(days=1)
                        
                        # Check if current_date matches either day 1 or day 2 of this base date
                        if (current_date_obj == base_date_obj or current_date_obj == day_2_obj):
                            can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                            print(f"DEBUG: Found matching base date {class_details[date_key]} for {class_date}, can_work_n_prior: {can_work_n_prior}")
                            break
            except ValueError as e:
                print(f"Warning: Could not parse date {class_date}: {e}")
        else:
            # For single-day classes, find the matching date directly
            for i in range(1, 9):
                date_key = f'date_{i}'
                if date_key in class_details and class_details[date_key] == class_date:
                    can_work_n_prior = class_details.get(f'date_{i}_can_work_n_prior', False)
                    break
        
        # Check for conflicts using modified logic for educators
        # For 2-day classes, we only check the specific date, not both days
        has_conflict, conflict_details = self.track_manager.check_class_conflict(
            staff_name, class_date, False, can_work_n_prior  # Set is_two_day to False for individual date checking
        )
        
        # For educators, filter out AT conflicts but keep them for information
        if has_conflict and 'AT' in conflict_details:
            # Check if the conflict is ONLY AT shifts
            at_only_conflict = self._is_at_only_conflict_for_date(staff_name, class_date)
            
            if at_only_conflict:
                # AT only - no real conflict for educators, but show as info
                return False, f"ℹ️ AT shift on schedule - No conflict for educators ({conflict_details})"
            else:
                # Mixed conflicts - AT plus other shifts
                filtered_details = self._filter_at_from_conflicts(conflict_details)
                if filtered_details:
                    return True, filtered_details
                else:
                    # Only AT conflicts after filtering
                    return False, f"ℹ️ Only AT shifts - No conflict for educators"
        
        return has_conflict, conflict_details
    
    def _is_at_only_conflict_for_date(self, staff_name, class_date):
        """Check if conflicts are only due to AT shifts for a specific date"""
        if not self.track_manager:
            return False
        
        from datetime import datetime, timedelta
        
        if isinstance(class_date, str):
            try:
                class_date_obj = datetime.strptime(class_date, '%m/%d/%Y')
            except:
                return False
        else:
            class_date_obj = class_date
        
        # Check shifts around the class date
        day_before = class_date_obj - timedelta(days=1)
        
        non_at_conflicts = False
        
        # Check day before
        shift_before = self.track_manager.get_staff_shift(staff_name, day_before)
        if shift_before and shift_before in ['D', 'N']:  # Exclude AT
            non_at_conflicts = True
        
        # Check class day only
        shift = self.track_manager.get_staff_shift(staff_name, class_date_obj)
        if shift and shift in ['D', 'N']:  # Exclude AT
            non_at_conflicts = True
        
        return not non_at_conflicts
    
    def _filter_at_from_conflicts(self, conflict_details):
        """Remove AT shift references from conflict details"""
        if not conflict_details:
            return conflict_details
        
        # Split conflicts and filter out AT references
        conflicts = conflict_details.split(';')
        filtered_conflicts = []
        
        for conflict in conflicts:
            conflict = conflict.strip()
            if 'AT' not in conflict and conflict:
                filtered_conflicts.append(conflict)
        
        return '; '.join(filtered_conflicts)
    
    def signup_as_educator(self, staff_name, class_name, class_date, override_conflict=False):
        """Sign up staff member as educator with conflict checking"""
        
        try:
            # Check if signup is allowed
            can_signup_result = self.can_signup_as_educator(staff_name, class_name, class_date)
            
            # Handle the case where can_signup_as_educator might return None
            if can_signup_result is None:
                return False, "Error checking signup eligibility"
            
            can_signup, message = can_signup_result
            if not can_signup:
                return False, message
            
            # Check for conflicts if track manager is available
            conflict_details = None
            if self.track_manager and not override_conflict:
                has_conflict, conflict_info = self.check_educator_conflict(
                    staff_name, class_name, class_date
                )
                
                if has_conflict and not conflict_info.startswith('ℹ️'):
                    # Real conflict that blocks signup
                    return False, conflict_info
                elif conflict_info.startswith('ℹ️'):
                    # Informational only (AT shifts) - allow signup but record info
                    conflict_details = conflict_info
                    
            elif self.track_manager and override_conflict:
                # Get conflict details for recording
                has_conflict, conflict_details = self.check_educator_conflict(
                    staff_name, class_name, class_date
                )
            
            # Perform the signup
            success = self.db.add_educator_signup(
                staff_name, class_name, class_date, override_conflict, conflict_details
            )
            
            if success:
                return True, "Successfully signed up as educator"
            else:
                return False, "Signup failed - you may already be signed up for this date"
                
        except Exception as e:
            print(f"Error in signup_as_educator: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Signup error: {str(e)}"
    
    def cancel_educator_signup(self, signup_id):
        """Cancel an educator signup"""
        return self.db.cancel_educator_signup(signup_id)
    
    def get_staff_educator_signups(self, staff_name):
        """Get all educator signups for a staff member"""
        return self.db.get_staff_educator_signups(staff_name)
    
    def get_class_educator_summary(self, class_name):
        """Get educator signup summary for a class with detailed breakdown"""
        signups = self.db.get_educator_signups_for_class(class_name)
        
        # Group by date
        summary = {}
        for signup in signups:
            date = signup['class_date']
            if date not in summary:
                summary[date] = {
                    'total': 0,
                    'conflicts': 0,
                    'staff_names': []
                }
            summary[date]['total'] += 1
            summary[date]['staff_names'].append(signup['staff_name'])
            
            # Track conflicts
            if signup.get('conflict_override'):
                summary[date]['conflicts'] += 1
        
        return summary
    
    def get_educator_opportunities_with_status(self, staff_name):
        """Get educator opportunities with signup status for a specific staff member"""
        opportunities = self.get_educator_opportunities()
        
        for opportunity in opportunities:
            class_name = opportunity['class_name']
            instructor_count = opportunity['instructor_count']
            
            # Add status for each date
            date_status = []
            for date in opportunity['available_dates']:
                current_signups = self.db.get_educator_signup_count(class_name, date)
                is_signed_up = self.db.check_existing_educator_signup(staff_name, class_name, date) is not None
                
                # Check for conflicts (for display purposes)
                conflict_info = ""
                if self.track_manager and self.track_manager.has_track_data(staff_name):
                    has_conflict, conflict_details = self.check_educator_conflict(
                        staff_name, class_name, date
                    )
                    if has_conflict or conflict_details.startswith('ℹ️'):
                        conflict_info = conflict_details
                
                date_status.append({
                    'date': date,
                    'current_signups': current_signups,
                    'max_signups': instructor_count,
                    'is_signed_up': is_signed_up,
                    'is_full': current_signups >= instructor_count,
                    'conflict_info': conflict_info
                })
            
            opportunity['date_status'] = date_status
        
        return opportunities