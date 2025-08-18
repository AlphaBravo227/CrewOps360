# training_modules/track_manager.py
"""
Updated Track Manager for the training module that uses the main medflight_tracks.db
instead of looking for a separate tracks database in the upload folder.
"""
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import json
import ast
import os


class TrackManager:
    def __init__(self, tracks_db_path=None):
        """
        Initialize the TrackManager with unified database.
        
        Args:
            tracks_db_path: Path to the main tracks database (data/medflight_tracks.db)
        """
        self.tracks_db_path = tracks_db_path or 'data/medflight_tracks.db'
        self.pattern_start = datetime(2025, 9, 14)  # Sun A 1
        self.pattern_length = 42  # 6 weeks
        self.tracks_cache = {}  # Cache for staff tracks
        self.load_error = None
        
        # Define shift conflict rules
        self.shift_descriptions = {
            'D': 'Day Shift',
            'N': 'Night Shift', 
            'AT': 'Admin Time',
            '': 'Off'
        }
        
        # Try to load tracks on initialization
        if self.tracks_db_path and os.path.exists(self.tracks_db_path):
            self._load_all_tracks()
        else:
            self.load_error = f"Main tracks database not found at {self.tracks_db_path}"
    
    def _load_all_tracks(self):
        """
        Load all staff tracks from the main database into cache.
        """
        try:
            conn = sqlite3.connect(self.tracks_db_path)
            
            # The main database uses the 'tracks' table
            # Get active tracks only
            df = pd.read_sql_query("""
                SELECT staff_name, track_data 
                FROM tracks 
                WHERE is_active = 1
            """, conn)
            
            if len(df) == 0:
                self.load_error = "No active tracks found in main database"
                conn.close()
                return
            
            # Parse and cache each staff member's track
            for _, row in df.iterrows():
                staff_name = str(row['staff_name']).strip()
                track_data_str = str(row['track_data'])
                
                try:
                    # Parse track data (it's stored as JSON in the main database)
                    track_data = self._parse_track_data(track_data_str)
                    self.tracks_cache[staff_name] = track_data
                except Exception as e:
                    print(f"Error parsing track for {staff_name}: {e}")
                    self.tracks_cache[staff_name] = {}
            
            conn.close()
            print(f"Loaded tracks for {len(self.tracks_cache)} staff members from main database")
            
        except Exception as e:
            self.load_error = f"Error loading tracks from main database: {str(e)}"
            print(self.load_error)
    
    def _parse_track_data(self, track_data_str):
        """
        Parse track data from JSON string.
        
        Args:
            track_data_str: String containing track data (JSON format)
            
        Returns:
            dict: Parsed track data
        """
        try:
            # Try JSON first (the main database stores as JSON)
            return json.loads(track_data_str)
        except json.JSONDecodeError:
            try:
                # Fallback to Python literal eval for backwards compatibility
                return ast.literal_eval(track_data_str)
            except (ValueError, SyntaxError):
                return {}
    
    def get_pattern_day_name(self, date):
        """
        Get the pattern day name (e.g., "Sun A 1") for a given date.
        
        Args:
            date: datetime object or string date
            
        Returns:
            str: Pattern day name
        """
        if isinstance(date, str):
            date = datetime.strptime(date, '%m/%d/%Y')
        
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
    
    def get_staff_shift(self, staff_name, date):
        """
        Get the shift assignment for a staff member on a specific date.
        
        Args:
            staff_name: Name of the staff member
            date: Date to check (datetime or string)
            
        Returns:
            str: Shift code (D, N, AT, or empty string)
        """
        if staff_name not in self.tracks_cache:
            return None  # No track data available
        
        pattern_day = self.get_pattern_day_name(date)
        track_data = self.tracks_cache.get(staff_name, {})
        
        return track_data.get(pattern_day, "")
    
    def check_class_conflict(self, staff_name, class_date, is_two_day=False, can_work_n_prior=False):
        """
        Check if a staff member has a conflict with a class date.
        
        Args:
            staff_name: Name of the staff member
            class_date: Date of the class (datetime or string)
            is_two_day: Whether this is a two-day class
            can_work_n_prior: Whether night shift prior is allowed for this class
            
        Returns:
            tuple: (has_conflict, conflict_details)
        """
        if isinstance(class_date, str):
            class_date = datetime.strptime(class_date, '%m/%d/%Y')
        
        if staff_name not in self.tracks_cache:
            return (False, "No track data available")
        
        conflicts = []
        
        # Check day before
        day_before = class_date - timedelta(days=1)
        shift_before = self.get_staff_shift(staff_name, day_before)
        
        if shift_before == 'N' and not can_work_n_prior:
            conflicts.append(f"Night shift on {day_before.strftime('%m/%d/%Y')}")
        
        # Check class day
        shift_class_day = self.get_staff_shift(staff_name, class_date)
        if shift_class_day in ['D', 'AT', 'N']:
            conflicts.append(f"{self.shift_descriptions.get(shift_class_day, shift_class_day)} on {class_date.strftime('%m/%d/%Y')}")
        
        # Check second day if two-day class
        if is_two_day:
            day_two = class_date + timedelta(days=1)
            shift_day_two = self.get_staff_shift(staff_name, day_two)
            
            if shift_day_two in ['D', 'AT', 'N']:
                conflicts.append(f"{self.shift_descriptions.get(shift_day_two, shift_day_two)} on {day_two.strftime('%m/%d/%Y')}")
        
        has_conflict = len(conflicts) > 0
        conflict_details = "; ".join(conflicts) if conflicts else "No conflicts"
        
        return (has_conflict, conflict_details)
    
    def get_class_date_conflicts(self, staff_name, class_dates, is_two_day=False, can_work_n_prior_list=None):
        """
        Check conflicts for multiple class dates.
        
        Args:
            staff_name: Name of the staff member
            class_dates: List of class dates
            is_two_day: Whether this is a two-day class
            can_work_n_prior_list: List of booleans for each date indicating if N prior is allowed
            
        Returns:
            dict: Dictionary mapping dates to conflict information
        """
        if can_work_n_prior_list is None:
            can_work_n_prior_list = [False] * len(class_dates)
        
        conflicts = {}
        
        for i, date in enumerate(class_dates):
            if date:  # Skip None/empty dates
                can_work_n = can_work_n_prior_list[i] if i < len(can_work_n_prior_list) else False
                has_conflict, details = self.check_class_conflict(
                    staff_name, date, is_two_day, can_work_n
                )
                
                # Get the shift for display
                shift = self.get_staff_shift(staff_name, date)
                
                conflicts[date] = {
                    'has_conflict': has_conflict,
                    'details': details,
                    'shift': shift,
                    'shift_desc': self.shift_descriptions.get(shift, 'Off')
                }
        
        return conflicts

    def get_conflict_summary(self, conflicts_dict):
        """
        Generate a summary of conflicts for a class.
        
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

    def format_shift_display(self, date, shift_info):
        """
        Format shift information for display.
        
        Args:
            date: Date string
            shift_info: Dictionary with shift information
            
        Returns:
            str: Formatted display string
        """
        shift = shift_info.get('shift', '')
        has_conflict = shift_info.get('has_conflict', False)
        
        if shift:
            display = f"{date} - {shift} ({shift_info.get('shift_desc', '')})"
            if has_conflict:
                display += " ⚠️ CONFLICT"
        else:
            display = f"{date} - Off"
        
        return display
    
    def has_track_data(self, staff_name):
        """
        Check if track data exists for a staff member.
        
        Args:
            staff_name: Name of the staff member
            
        Returns:
            bool: True if track data exists
        """
        return staff_name in self.tracks_cache
    
    def reload_tracks(self):
        """
        Reload all tracks from the main database.
        """
        self.tracks_cache.clear()
        self.load_error = None
        self._load_all_tracks()
    
    def get_all_staff_with_tracks(self):
        """
        Get list of all staff members with track data.
        
        Returns:
            list: Staff names with track data
        """
        return list(self.tracks_cache.keys())