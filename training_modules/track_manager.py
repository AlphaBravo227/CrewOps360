# training_modules/track_manager.py - Updated to include CCEMT schedule integration from Excel

from datetime import datetime, timedelta
import sqlite3
import json

class TrainingTrackManager:
    """Enhanced Track Manager that includes CCEMT schedule integration from Excel"""
    
    def __init__(self, tracks_db_path=None, track_cohort=None, pattern_start=None):
        """
        Args:
            tracks_db_path: Path to the tracks database.
            track_cohort: track_configs.track_name whose tracks to load. None loads
                whichever cohort is active, which is only correct when the training
                year and the active track cohort are the same one.
            pattern_start: Date the 42-day pattern's "Sun A 1" falls on for this
                cohort. None keeps the FY26 anchor.
        """
        self.tracks_db_path = tracks_db_path
        self.track_cohort = track_cohort
        self.tracks_cache = {}
        # What reload_tracks() actually loaded. A named cohort with no tracks in it
        # falls back to the active cohort, which silently checks classes against the
        # wrong year's schedules; these let the caller say so instead of only
        # printing it to a console nobody is watching.
        self.tracks_source = None       # 'cohort' or 'active'
        self.tracks_source_label = None  # human-readable, e.g. "cohort 'FY27'"
        self.tracks_fell_back = False    # a cohort was asked for and wasn't there
        self.ccemt_schedule_cache = {}
        self.ccemt_raw_cache = {}  # Raw CCEMT shift codes (e.g., 'PG', 'NP') for display purposes
        self.tracks_excel_handler = None  # Fallback CCEMT source when the database has none
        self.enrollment_excel_handler = None  # For getting staff roles from enrollment sheet
        
        # Pattern configuration for regular tracks. The anchor is the date that counts
        # as "Sun A 1"; it is per-cohort, because a 364-day fiscal year is not a whole
        # number of 42-day cycles and each year's grid is laid out from its own start.
        # A wrong anchor shifts every conflict check by a few days without erroring,
        # so it is configurable rather than assumed.
        self.pattern_start = pattern_start or datetime(2025, 9, 14)  # Sun A 1
        self.pattern_length = 42  # 6 weeks = 42 days
        
        # CCEMT schedule start date — the date the 28-day pattern's first column falls
        # on. Configurable in the Track Data admin; defaults to the same Sunday the
        # 42-day track pattern starts on.
        self.ccemt_start_date = datetime(2025, 9, 14)  # First Sunday in CCEMT schedule
        try:
            from modules.ccemt_schedule import get_pattern_start_date
            self.ccemt_start_date = get_pattern_start_date()
        except Exception as e:
            print(f"Using the default CCEMT pattern start date: {e}")
        
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
    
    def set_excel_handler(self, tracks_excel_handler=None, enrollment_excel_handler=None):
        """
        Set the Excel handlers still used for lookups.

        Args:
            tracks_excel_handler: Optional ExcelHandler for a Tracks workbook. CCEMT
                schedules come from the database now, so this is only a fallback for a
                database that has none yet.
            enrollment_excel_handler: Optional ExcelHandler for enrollment data. Staff
                roles come from the staff database; this is its fallback.
        """
        self.tracks_excel_handler = tracks_excel_handler
        self.enrollment_excel_handler = enrollment_excel_handler or tracks_excel_handler
        self.load_ccemt_schedules()

    def load_ccemt_schedules(self):
        """
        Load CCEMT schedules — the 28-day (4-week) repeating pattern each CCEMT staff
        member works — from the database, and cycle through it for any date.

        The pattern used to live on the CCEMT tab of Tracks.xlsx; it is now editable in
        the Track Data admin. A Tracks workbook is only read if the database has no
        schedules at all, so an install that hasn't imported yet still works.
        """
        try:
            from modules.ccemt_schedule import classify_shift_code, get_schedules

            schedules = get_schedules()
            if schedules:
                self.ccemt_schedule_cache = {}
                self.ccemt_raw_cache = {}
                for staff_name, pattern in schedules.items():
                    self.ccemt_raw_cache[staff_name] = dict(pattern)
                    self.ccemt_schedule_cache[staff_name] = {
                        day_index: classify_shift_code(code)
                        for day_index, code in pattern.items()
                        if classify_shift_code(code)
                    }
                print(f"Loaded CCEMT schedules for {len(self.ccemt_schedule_cache)} "
                      "staff members from the database (4-week repeating pattern)")
                return
        except Exception as e:
            print(f"Could not read CCEMT schedules from the database: {e}")

        self._load_ccemt_schedules_from_excel()

    def _load_ccemt_schedules_from_excel(self):
        """
        Fallback: read the 28-day CCEMT pattern from the CCEMT tab of a Tracks workbook.

        Format:
        - Row 1: Headers (column A is blank, columns B-AC are day names: Sun, Mon, Tue, etc.)
        - Column A (starting row 2): Staff names
        - Columns B-AC (28 columns = 4 weeks): Shift codes (REPEATING PATTERN)
        - Starting date: 9/14/2025 (first Sunday)
        """
        # A Tracks workbook opened with openpyxl, which nothing currently supplies -
        # CCEMT schedules come from the database. getattr rather than an attribute:
        # the enrollment handler is a class catalog now and holds no workbook, so
        # reaching for one directly would raise rather than skip.
        workbook = getattr(self.tracks_excel_handler, 'workbook', None)
        if workbook is None:
            return

        try:
            # Access the CCEMT worksheet
            if 'CCEMT' not in workbook.sheetnames:
                print("CCEMT tab not found in Tracks workbook")
                return

            ccemt_sheet = workbook['CCEMT']
            
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
                self.ccemt_raw_cache[staff_name] = {}

                # Read the 28-day pattern
                for day_index, col_idx in pattern_shifts.items():
                    # Get the cell value (col_idx is 1-based, but row[x] is 0-based)
                    cell_value = row[col_idx - 1].value

                    if cell_value:
                        schedule_str = str(cell_value).strip().upper()

                        # Store the raw code for display purposes (e.g., 'PG', 'NP')
                        self.ccemt_raw_cache[staff_name][day_index] = schedule_str

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
        """Reload track data from database.

        Loads the cohort named by track_cohort when one is set, rather than
        whichever cohort happens to be active. During a fiscal-year cutover those
        differ: FY27's tracks are promoted to active months before FY26's last
        classes are taught, and checking a September FY26 class against an FY27
        track produces conflicts that aren't real.
        """
        if not self.tracks_db_path:
            return
        
        try:
            conn = sqlite3.connect(self.tracks_db_path)
            cursor = conn.cursor()
            
            self.tracks_fell_back = False

            if self.track_cohort:
                # Ordered oldest version first so a staff member who has more than one
                # row in the cohort (a resubmission left behind by the older save path)
                # ends up cached at their newest one rather than at whichever row the
                # database happened to return last.
                cursor.execute("""
                    SELECT staff_name, track_data
                    FROM tracks
                    WHERE track_name = ?
                    ORDER BY version ASC, id ASC
                """, (self.track_cohort,))
                results = cursor.fetchall()
                source = f"cohort '{self.track_cohort}'"
                self.tracks_source = 'cohort'
                if not results:
                    # A cohort that was named but never populated would silently
                    # disable conflict checking; fall back to the active tracks.
                    print(f"No tracks found for {source}; falling back to the active cohort")
                    cursor.execute("""
                        SELECT staff_name, track_data
                        FROM tracks
                        WHERE is_active = 1
                        ORDER BY version ASC, id ASC
                    """)
                    results = cursor.fetchall()
                    source = "the active cohort"
                    self.tracks_source = 'active'
                    self.tracks_fell_back = True
            else:
                # Get active tracks
                cursor.execute("""
                    SELECT staff_name, track_data
                    FROM tracks
                    WHERE is_active = 1
                    ORDER BY version ASC, id ASC
                """)
                results = cursor.fetchall()
                source = "the active cohort"
                self.tracks_source = 'active'
            
            self.tracks_cache = {}
            
            for staff_name, track_data_json in results:
                if track_data_json:
                    try:
                        track_data = json.loads(track_data_json)
                        self.tracks_cache[staff_name] = track_data
                    except json.JSONDecodeError:
                        continue
            
            conn.close()
            self.tracks_source_label = source
            print(f"Loaded {len(self.tracks_cache)} tracks from {source}")
            
        except Exception as e:
            print(f"Error loading tracks: {e}")
    
    def get_staff_role(self, staff_name):
        """
        Get the role of a staff member from the staff database.

        Falls back to the CCEMT cache when the staff database has no roster yet.
        """
        try:
            from modules.staff_database import get_role, staff_count
            if staff_count(include_inactive=False) > 0:
                role = get_role(staff_name)
                if role:
                    return role
        except Exception as e:
            print(f"Staff database unavailable for {staff_name}'s role: {e}")

        # Ask the class catalog, which reads the same staff database. Worth a second
        # attempt only because the call above is skipped entirely when the roster is
        # empty, and the catalog answers for a name the count did not see.
        if self.enrollment_excel_handler:
            try:
                role = self.enrollment_excel_handler.get_staff_role(staff_name)
                if role:
                    return role
            except Exception as e:
                print(f"Error getting staff role for {staff_name}: {e}")
        
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
    
    def get_staff_raw_shift(self, staff_name, date):
        """
        Get the raw shift code for a staff member on a date, for display purposes.

        For CCEMT staff, returns the original shift code from the Excel (e.g., 'PG', 'NP').
        For regular track staff, returns the full shift code (e.g., 'D7B', 'N7P').

        Args:
            staff_name: Name of the staff member
            date: Date to check (datetime or string in MM/DD/YYYY format)

        Returns:
            str: Raw shift code, or empty string if no shift / not found
        """
        if isinstance(date, str):
            try:
                date_obj = datetime.strptime(date, '%m/%d/%Y')
            except ValueError:
                return ""
        else:
            date_obj = date

        staff_role = self.get_staff_role(staff_name)

        if staff_role == 'CCEMT':
            raw_cache = getattr(self, 'ccemt_raw_cache', {})
            if staff_name in raw_cache:
                days_since_start = (date_obj - self.ccemt_start_date).days
                day_in_cycle = days_since_start % 28
                return raw_cache[staff_name].get(day_in_cycle, "")
            return ""

        if staff_name not in self.tracks_cache:
            return ""

        pattern_day = self.get_pattern_day_name(date_obj)
        if not pattern_day:
            return ""

        return self.tracks_cache.get(staff_name, {}).get(pattern_day, "")

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
def integrate_ccemt_schedules(track_manager, tracks_excel_handler=None,
                              enrollment_excel_handler=None):
    """
    Helper to wire the fallback Excel handlers into an existing track manager.

    CCEMT schedules and staff roles both come from the database now; the handlers are
    only consulted when the database has nothing yet.

    Args:
        track_manager: TrainingTrackManager instance
        tracks_excel_handler: Optional ExcelHandler for a Tracks workbook (CCEMT tab)
        enrollment_excel_handler: Optional ExcelHandler for enrollment data (staff roles)
    """
    track_manager.set_excel_handler(tracks_excel_handler, enrollment_excel_handler)
