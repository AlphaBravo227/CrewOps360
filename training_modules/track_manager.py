# training_modules/track_manager.py - Updated to include CCEMT schedule integration from Excel

from datetime import datetime, timedelta
import sqlite3
import json

class TrainingTrackManager:
    """Enhanced Track Manager that includes CCEMT schedule integration from Excel"""
    
    def __init__(self, tracks_db_path=None):
        self.tracks_db_path = tracks_db_path
        self.tracks_cache = {}
        self.ccemt_schedule_cache = {}
        self.tracks_excel_handler = None  # For loading CCEMT schedules from Tracks.xlsx
        self.enrollment_excel_handler = None  # For getting staff roles from enrollment sheet
        
        # Pattern configuration for regular tracks
        self.pattern_start = datetime(2025, 9, 14)  # Sun A 1 - pattern start date
        self.pattern_length = 42  # 6 weeks = 42 days
        
        # CCEMT schedule start date (same as pattern start)
        self.ccemt_start_date = datetime(2025, 9, 14)  # First Sunday in CCEMT schedule
        
        # Shift descriptions for display
        self.shift_descriptions = {
            'D': 'Day Shift',
            'N': 'Night Shift',
            'AT': 'AT Shift',
            'LT': 'Day Shift (LT)'
        }
        
        # Load tracks if database exists
        if self.tracks_db_path:
            self.reload_tracks()

    def get_pattern_day_name(self, date):
        """
        Get the pattern day name (e.g., "Sun A 1") for a given date.
        
        Args:
            date: datetime object or string date
            
        Returns:
            str: Pattern day name
        """
        if isinstance(date, str):
            try:
                date = datetime.strptime(date, '%m/%d/%Y')
            except:
                return ""
        
        # Calculate days since pattern start
        days_since_start = (date - self.pattern_start).days
        
        # Get position in current pattern cycle
        pattern_day_index = days_since_start % self.pattern_length
        
        # Calculate week and day
        week_index = pattern_day_index // 7
        day_index = pattern_day_index % 7
        
        # Define components
        days_of_week = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        week_letters = ["A", "A", "B", "B", "C", "C"]
        week_numbers = [1, 2, 3, 4, 5, 6]
        
        if week_index < 6:
            day_name = days_of_week[day_index]
            week_letter = week_letters[week_index]
            week_number = week_numbers[week_index]
            return f"{day_name} {week_letter} {week_number}"
        
        return f"Day {pattern_day_index + 1}"
    
    def set_excel_handler(self, tracks_excel_handler, enrollment_excel_handler=None):
        """
        Set the Excel handlers for CCEMT schedule access and role lookups.
        
        Args:
            tracks_excel_handler: ExcelHandler for Tracks.xlsx (contains CCEMT tab)
            enrollment_excel_handler: Optional ExcelHandler for enrollment data (contains staff roles)
                                     If not provided, will use tracks_excel_handler for both
        """
        self.tracks_excel_handler = tracks_excel_handler
        self.enrollment_excel_handler = enrollment_excel_handler or tracks_excel_handler
        self.load_ccemt_schedules()
    
    def load_ccemt_schedules(self):
        """
        Load CCEMT schedules from the CCEMT tab in the Tracks.xlsx file.
        
        The schedule repeats every 4 weeks (28 days), so we load the pattern
        and cycle through it for any future date.
        
        Format:
        - Row 1: Headers (column A is blank, columns B-AC are day names: Sun, Mon, Tue, etc.)
        - Column A (starting row 2): Staff names
        - Columns B-AC (28 columns = 4 weeks): Shift codes (REPEATING PATTERN)
        - Starting date: 9/14/2025 (first Sunday)
        """
        if not self.tracks_excel_handler or not self.tracks_excel_handler.workbook:
            return
        
        try:
            # Access the CCEMT worksheet
            if 'CCEMT' not in self.tracks_excel_handler.workbook.sheetnames:
                print("CCEMT tab not found in Tracks workbook")
                return
            
            ccemt_sheet = self.tracks_excel_handler.workbook['CCEMT']
            
            # Build pattern mapping for 28 days (4 weeks) - columns B through AC
            # This pattern repeats indefinitely
            pattern_shifts = {}  # day_index (0-27) -> column_index
            
            for day_index in range(28):  # 0-27 for 28 days
                col_idx = day_index + 2  # Column B=2, C=3, ... AC=29
                pattern_shifts[day_index] = col_idx
            
            # Read staff schedules (starting from row 2)
            for row in ccemt_sheet.iter_rows(min_row=2):
                staff_name = row[0].value  # Column A
                
                if not staff_name:
                    continue
                
                staff_name = str(staff_name).strip()
                if not staff_name:
                    continue
                
                # Initialize schedule pattern for this staff member
                # Store as day_index (0-27) -> shift code
                self.ccemt_schedule_cache[staff_name] = {}
                
                # Read the 28-day pattern
                for day_index, col_idx in pattern_shifts.items():
                    # Get the cell value (col_idx is 1-based, but row[x] is 0-based)
                    cell_value = row[col_idx - 1].value
                    
                    if cell_value:
                        schedule_str = str(cell_value).strip().upper()
                        
                        # Classify shifts: anything starting with 'N' is night shift, 
                        # everything else is day shift
                        if schedule_str.startswith('N'):
                            # Night shift (NG, NW, etc.)
                            self.ccemt_schedule_cache[staff_name][day_index] = 'N'
                        else:
                            # Day shift (GR, GW, or any other code)
                            self.ccemt_schedule_cache[staff_name][day_index] = 'D'
            
            print(f"Loaded CCEMT schedules for {len(self.ccemt_schedule_cache)} staff members (4-week repeating pattern)")
            
        except Exception as e:
            print(f"Error loading CCEMT schedules: {e}")
            import traceback
            traceback.print_exc()
    
    def reload_tracks(self):
        """Reload track data from database"""
        if not self.tracks_db_path:
            return
        
        try:
            conn = sqlite3.connect(self.tracks_db_path)
            cursor = conn.cursor()
            
            # Get active tracks
            cursor.execute("""
                SELECT staff_name, track_data 
                FROM tracks 
                WHERE is_active = 1
            """)
            
            results = cursor.fetchall()
            self.tracks_cache = {}
            
            for staff_name, track_data_json in results:
                if track_data_json:
                    try:
                        track_data = json.loads(track_data_json)
                        self.tracks_cache[staff_name] = track_data
                    except json.JSONDecodeError:
                        continue
            
            conn.close()
            print(f"Loaded {len(self.tracks_cache)} tracks from database")
            
        except Exception as e:
            print(f"Error loading tracks: {e}")
    
    def get_staff_role(self, staff_name):
        """
        Get the role of a staff member from the enrollment Excel handler.
        Looks at column B (Role) in the Class_Enrollment sheet.
        
        If enrollment handler isn't available, falls back to checking CCEMT cache.
        """
        # First, check if we have enrollment Excel handler
        if self.enrollment_excel_handler:
            try:
                # Access the enrollment sheet to get role information
                enrollment_sheet = self.enrollment_excel_handler.enrollment_sheet
                
                if enrollment_sheet:
                    # Find staff member's row and get their role
                    for row in enrollment_sheet.iter_rows(min_row=2):
                        if row[0].value and str(row[0].value).strip() == staff_name:
                            # Role is in column B (index 1)
                            role_cell = row[1].value if len(row) > 1 else None
                            return str(role_cell).strip() if role_cell else None
                
            except Exception as e:
                print(f"Error getting staff role for {staff_name} from enrollment sheet: {e}")
        
        # Fallback: if staff is in CCEMT cache, assume they're CCEMT
        if staff_name in self.ccemt_schedule_cache:
            return 'CCEMT'
        
        return None
    
    def has_track_data(self, staff_name):
        """Check if staff member has track data (regular track OR CCEMT schedule)"""
        # Check regular track data first
        if staff_name in self.tracks_cache:
            return True
        
        # Check if staff member is CCEMT with schedule data
        staff_role = self.get_staff_role(staff_name)
        if staff_role == 'CCEMT' and staff_name in self.ccemt_schedule_cache:
            return True
        
        return False
    
    def get_staff_shift(self, staff_name, date):
        """
        Get the shift assignment for a staff member on a specific date.
        Handles both regular track staff and CCEMT staff.
        
        For CCEMT staff, uses a repeating 4-week (28-day) pattern.
        
        Args:
            staff_name: Name of the staff member
            date: Date to check (datetime or string)
            
        Returns:
            str: Shift code (D, N, AT, or empty string)
        """
        # Convert date to datetime object if needed
        if isinstance(date, str):
            try:
                date_obj = datetime.strptime(date, '%m/%d/%Y')
            except ValueError:
                return ""
        else:
            date_obj = date
        
        # Check if this is a CCEMT staff member
        staff_role = self.get_staff_role(staff_name)
        
        if staff_role == 'CCEMT':
            # Use CCEMT schedule data with repeating pattern
            if staff_name in self.ccemt_schedule_cache:
                # Calculate which day in the 28-day cycle this date falls on
                days_since_start = (date_obj - self.ccemt_start_date).days
                day_in_cycle = days_since_start % 28  # 0-27
                
                # Look up the shift for this day in the cycle
                return self.ccemt_schedule_cache[staff_name].get(day_in_cycle, "")
            else:
                return ""  # No CCEMT schedule data available
        
        # Fall back to existing logic for regular track staff
        if staff_name not in self.tracks_cache:
            return ""  # No track data available
        
        # Use pattern day logic for regular tracks
        pattern_day = self.get_pattern_day_name(date_obj)
        if not pattern_day:
            return ""
        
        track_data = self.tracks_cache.get(staff_name, {})
        return track_data.get(pattern_day, "")    
    
    def check_class_conflict(self, staff_name, class_date, is_two_day=False, can_work_n_prior=False):
        """
        Check if a staff member has a conflict with a class date.
        Works for both regular track staff and CCEMT staff.
        
        Args:
            staff_name: Name of the staff member
            class_date: Date of the class (string in MM/DD/YYYY format)
            is_two_day: Whether this is a two-day class
            can_work_n_prior: Whether night shift prior to class is allowed
            
        Returns:
            tuple: (has_conflict: bool, conflict_details: str)
        """
        try:
            # Parse the class date
            try:
                date_obj = datetime.strptime(class_date, '%m/%d/%Y')
            except ValueError:
                return False, "Invalid date format"
            
            # For two-day classes, check both days
            dates_to_check = [date_obj]
            if is_two_day:
                day2 = date_obj + timedelta(days=1)
                dates_to_check.append(day2)
            
            conflicts = []
            
            for check_date in dates_to_check:
                check_date_str = check_date.strftime('%m/%d/%Y')
                
                # Get shift for this date
                shift = self.get_staff_shift(staff_name, check_date)
                
                if shift:
                    # Any shift on the class day is a conflict
                    day_label = "Day 1" if check_date == date_obj else "Day 2"
                    shift_desc = self.shift_descriptions.get(shift, shift)
                    conflicts.append(f"{day_label} ({check_date_str}): {shift_desc}")
                
                # Check night shift the night before (if applicable)
                if not can_work_n_prior:
                    prior_date = check_date - timedelta(days=1)
                    prior_shift = self.get_staff_shift(staff_name, prior_date)
                    
                    if prior_shift == 'N':
                        day_label = "Day 1" if check_date == date_obj else "Day 2"
                        prior_date_str = prior_date.strftime('%m/%d/%Y')
                        conflicts.append(f"{day_label} ({check_date_str}): Night shift prior on {prior_date_str}")
            
            if conflicts:
                conflict_message = "; ".join(conflicts)
                return True, conflict_message
            
            return False, ""
            
        except Exception as e:
            print(f"Error checking conflicts for {staff_name} on {class_date}: {e}")
            return False, f"Error checking conflicts: {str(e)}"
    
    def get_date_conflicts_for_staff(self, staff_name, dates):
        """
        Check conflicts for multiple dates at once.
        
        Args:
            staff_name: Name of the staff member
            dates: List of dates to check
            
        Returns:
            dict: Dictionary mapping date -> conflict info
        """
        conflicts_dict = {}
        
        for date in dates:
            has_conflict, conflict_info = self.check_class_conflict(
                staff_name, 
                date, 
                is_two_day=False,  # Check each date individually
                can_work_n_prior=False
            )
            
            conflicts_dict[date] = {
                'has_conflict': has_conflict,
                'details': conflict_info
            }
        
        return conflicts_dict
    
    def get_conflict_summary(self, conflicts_dict):
        """
        Generate a summary of conflicts from a conflicts dictionary.
        
        Args:
            conflicts_dict: Dictionary of date conflicts
            
        Returns:
            str: Summary text
        """
        if not conflicts_dict:
            return "No schedule data available"
        
        # Handle case where conflicts_dict is not in expected format
        if not isinstance(conflicts_dict, dict):
            return "No schedule data available"
        
        # Check if the conflicts_dict has the expected structure
        if not conflicts_dict or all(not isinstance(v, dict) for v in conflicts_dict.values()):
            return "No schedule data available"
        
        total_dates = len(conflicts_dict)
        
        # Safely count conflicts by checking if 'has_conflict' key exists
        conflict_count = 0
        for conflict_info in conflicts_dict.values():
            if isinstance(conflict_info, dict) and conflict_info.get('has_conflict', False):
                conflict_count += 1
        
        if conflict_count == 0:
            return f"✅ All {total_dates} dates available"
        elif conflict_count == total_dates:
            return f"⚠️ Conflicts on all {total_dates} dates"
        else:
            return f"⚠️ {conflict_count} of {total_dates} dates have conflicts"
    
    def get_all_staff_with_tracks(self):
        """Get list of all staff with track data (regular tracks OR CCEMT schedules)"""
        all_staff = set()
        
        # Add staff with regular tracks
        all_staff.update(self.tracks_cache.keys())
        
        # Add CCEMT staff with schedules
        all_staff.update(self.ccemt_schedule_cache.keys())
        
        return list(all_staff)


# Integration helper function for existing codebase
def integrate_ccemt_schedules(track_manager, tracks_excel_handler, enrollment_excel_handler=None):
    """
    Helper function to integrate CCEMT schedules into an existing track manager.
    This should be called after both components are initialized.
    
    Args:
        track_manager: TrainingTrackManager instance
        tracks_excel_handler: ExcelHandler instance with the Tracks.xlsx file loaded (contains CCEMT tab)
        enrollment_excel_handler: Optional ExcelHandler instance with enrollment data (contains staff roles)
    """
    track_manager.set_excel_handler(tracks_excel_handler, enrollment_excel_handler)


# Usage example for app.py integration:
"""
# In app.py, after initializing both components:

if 'training_track_manager' not in st.session_state:
    st.session_state.training_track_manager = TrainingTrackManager('data/medflight_tracks.db')

# Excel handler for class enrollment (MASTER Education Classes Roster.xlsx)
if 'training_excel_handler' not in st.session_state:
    st.session_state.training_excel_handler = ExcelHandler('training/upload/MASTER Education Classes Roster.xlsx')

# Separate Excel handler for CCEMT tracks (Tracks.xlsx)
if 'tracks_excel_handler' not in st.session_state:
    st.session_state.tracks_excel_handler = ExcelHandler('upload_files/Tracks.xlsx')

# Integrate CCEMT schedules - pass BOTH handlers
st.session_state.training_track_manager.set_excel_handler(
    tracks_excel_handler=st.session_state.tracks_excel_handler,      # For CCEMT schedules
    enrollment_excel_handler=st.session_state.training_excel_handler  # For staff roles
)
"""
