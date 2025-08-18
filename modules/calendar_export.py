"""
Module for generating Google Calendar and iCal files from staffing schedules.
Handles 6-week repeating schedule patterns with fiscal year calendar generation.
Reads from the medflight_tracks.db database in the data folder.
"""
import csv
import io
from datetime import datetime, timedelta
import uuid
import sqlite3
import json
import pandas as pd
from icalendar import Calendar, Event
import pytz


def get_database_path():
    """
    Get the path to the SQLite database in the data folder.
    
    Returns:
        str: Path to the database file
    """
    return 'data/medflight_tracks.db'


def extract_staff_names_from_db():
    """
    Extract staff names from the tracks table.
    
    Returns:
        list: List of staff names sorted alphabetically
    """
    conn = sqlite3.connect(get_database_path())
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT staff_name FROM tracks WHERE is_active = 1 ORDER BY staff_name")
        staff_names = [row[0] for row in cursor.fetchall()]
        return staff_names
        
    except Exception as e:
        print(f"Error extracting staff names: {e}")
        return []
    finally:
        conn.close()


def extract_dates_from_db():
    """
    Generate dates for the fiscal year schedule.
    Pattern mapping: Sept 28, 2025 = Sun B 3 (day 15 of 42-day pattern)
    Full 6-week pattern: A1-A2-B3-B4-C5-C6, then repeats
    Fiscal year runs: Sept 28, 2025 to Sept 26, 2026
    
    Returns:
        tuple: (pattern_start_date, list of dates for 6-week pattern)
    """
    # Sept 28, 2025 corresponds to Sun B 3, which is day 15 of the 42-day pattern
    # (A1=days 1-7, A2=days 8-14, B3=days 15-21, B4=days 22-28, C5=days 29-35, C6=days 36-42)
    
    # To create the full pattern starting from Sun A 1, we need to calculate backwards
    fiscal_start = datetime(2025, 9, 28)  # This is Sun B 3 (pattern day 15)
    
    # Sun B 3 is the 15th day of the pattern (index 14, since we start counting from 0)
    # So Sun A 1 (pattern day 1) would be 14 days before Sept 28
    pattern_start = fiscal_start - timedelta(days=14)  # This gives us Sun A 1
    
    # Generate 42 days (6 weeks) for the complete pattern starting from Sun A 1
    dates = []
    for i in range(42):
        dates.append(pattern_start + timedelta(days=i))
    
    return pattern_start, dates


def extract_schedule_from_db(staff_names, dates):
    """
    Extract the schedule data for each staff member from the tracks table.
    The database contains schedule data as JSON where keys are pattern day names
    (like "Sun A 1", "Mon A 1", etc.) and values are shifts (D, N, etc.).
    
    Args:
        staff_names: List of staff names
        dates: List of 42 dates for the 6-week pattern (starting from Sun A 1)
    
    Returns:
        dict: Dictionary mapping staff names to their schedules
    """
    conn = sqlite3.connect(get_database_path())
    
    try:
        # Create pattern day names based on your 6-week structure
        # 6 weeks: A1, A2, B3, B4, C5, C6 (2 weeks each letter)
        pattern_day_names = []
        
        days_of_week = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        week_letters = ["A", "A", "B", "B", "C", "C"]  # 2 weeks each of A, B, C
        week_numbers = [1, 2, 3, 4, 5, 6]
        
        for week_idx in range(6):
            letter = week_letters[week_idx]
            number = week_numbers[week_idx]
            for day in days_of_week:
                pattern_day_names.append(f"{day} {letter} {number}")
        
        schedule_data = {}
        
        for staff in staff_names:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT track_data FROM tracks 
                WHERE staff_name = ? AND is_active = 1 
                ORDER BY submission_date DESC 
                LIMIT 1
            """, (staff,))
            
            result = cursor.fetchone()
            
            if result is None:
                # If staff not found, create empty schedule
                schedule = [""] * 42
            else:
                track_data_str = result[0]
                schedule = []
                
                try:
                    # Parse the track_data JSON
                    track_data = json.loads(track_data_str)
                    
                    # Extract shifts for each pattern day in the correct order
                    for pattern_day in pattern_day_names:
                        shift = track_data.get(pattern_day, "")
                        schedule.append(shift if shift else "")
                        
                except Exception as e:
                    print(f"Error parsing track_data for {staff}: {e}")
                    # Create empty schedule if parsing fails
                    schedule = [""] * 42
            
            # Ensure we have exactly 42 days
            while len(schedule) < 42:
                schedule.append("")
            schedule = schedule[:42]  # Trim if too long
            
            # Pair each date with its corresponding shift
            schedule_data[staff] = list(zip(dates, schedule))
        
        return schedule_data
        
    except Exception as e:
        print(f"Error extracting schedule data: {e}")
        return {}
    finally:
        conn.close()


def generate_google_calendar(staff_name, schedule, start_date, end_date):
    """
    Generate a Google Calendar CSV file for a staff member.
    
    Args:
        staff_name: Name of the staff member
        schedule: List of (date, shift) tuples for the staff member (6-week pattern starting Sun A 1)
        start_date: Start date of the 6-week pattern (calculated Sun A 1)
        end_date: End date for the repeated schedule (Sept 26, 2026)
    
    Returns:
        tuple: (CSV file as string, filename)
    """
    # Create a CSV file in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header row for Google Calendar import
    writer.writerow([
        "Subject", "Start Date", "Start Time", "End Date", "End Time", 
        "All Day Event", "Description", "Location", "Private"
    ])
    
    # Fiscal year starts Sept 28, 2025 (Sun B 3, which is day 15 of the pattern)
    fiscal_year_start = datetime(2025, 9, 28)
    
    # Calculate offset: Sept 28 is Sun B 3 = day 15 (index 14) of the 42-day pattern
    fiscal_offset = 14  # Sun B 3 is the 15th day (index 14) of the pattern
    
    # 6-week pattern length
    schedule_length = len(schedule)  # Should be 42 days
    
    current_date = fiscal_year_start
    
    while current_date <= end_date:
        # Calculate which day in the 6-week pattern we're on
        days_from_fiscal_start = (current_date - fiscal_year_start).days
        pattern_day = (fiscal_offset + days_from_fiscal_start) % schedule_length
        
        # Get the shift for this pattern day
        if pattern_day < len(schedule):
            pattern_date, shift = schedule[pattern_day]
            
            if shift and shift.strip():  # Skip empty shifts
                # Format the date for Google Calendar
                date_str = current_date.strftime("%m/%d/%Y")
                
                # Write the event to CSV as an all-day event
                writer.writerow([
                    shift,                     # Subject (shift code, e.g., "D" or "N")
                    date_str,                  # Start Date
                    "",                        # Start Time (empty for all-day events)
                    date_str,                  # End Date
                    "",                        # End Time (empty for all-day events)
                    "True",                    # All Day Event
                    f"{staff_name} Shift",     # Description
                    "",                        # Location (empty as per request)
                    "True"                     # Private
                ])
        
        # Move to next day
        current_date += timedelta(days=1)
    
    # Get the CSV content and create filename
    csv_content = output.getvalue()
    filename = f"{staff_name}_schedule_{fiscal_year_start.strftime('%Y%m%d')}.csv"
    
    return csv_content, filename


def generate_ical_calendar(staff_name, schedule, start_date, end_date):
    """
    Generate an iCal (.ics) file for a staff member.
    
    Args:
        staff_name: Name of the staff member
        schedule: List of (date, shift) tuples for the staff member (6-week pattern starting Sun A 1)
        start_date: Start date of the 6-week pattern (calculated Sun A 1)
        end_date: End date for the repeated schedule (Sept 26, 2026)
    
    Returns:
        tuple: (iCal file as string, filename)
    """
    # Create a calendar
    cal = Calendar()
    cal.add('prodid', '-//Clinical Track Hub Calendar Converter//EN')
    cal.add('version', '2.0')
    
    # Fiscal year starts Sept 28, 2025 (Sun B 3, which is day 15 of the pattern)
    fiscal_year_start = datetime(2025, 9, 28)
    
    # Calculate offset: Sept 28 is Sun B 3 = day 15 (index 14) of the 42-day pattern
    fiscal_offset = 14  # Sun B 3 is the 15th day (index 14) of the pattern
    
    # 6-week pattern length
    schedule_length = len(schedule)  # Should be 42 days
    
    current_date = fiscal_year_start
    
    while current_date <= end_date:
        # Calculate which day in the 6-week pattern we're on
        days_from_fiscal_start = (current_date - fiscal_year_start).days
        pattern_day = (fiscal_offset + days_from_fiscal_start) % schedule_length
        
        # Get the shift for this pattern day
        if pattern_day < len(schedule):
            pattern_date, shift = schedule[pattern_day]
            
            if shift and shift.strip():  # Skip empty shifts
                # Create an event
                event = Event()
                event.add('summary', shift)  # Just the shift code (e.g., "D" or "N")
                
                # Set as an all-day event
                from datetime import date as date_type
                event_date = date_type(current_date.year, current_date.month, current_date.day)
                event.add('dtstart', event_date)
                event.add('dtend', event_date + timedelta(days=1))  # End date is exclusive in iCal
                
                # Set as an all-day event
                event.add('X-MICROSOFT-CDO-ALLDAYEVENT', 'TRUE')
                event.add('X-APPLE-TRAVEL-ADVISORY-BEHAVIOR', 'AUTOMATIC')
                
                # Add description
                event.add('description', f"{staff_name} Shift")
                
                # Add a unique ID
                event.add('uid', str(uuid.uuid4()))
                
                # Add the event to the calendar
                cal.add_component(event)
        
        # Move to next day
        current_date += timedelta(days=1)
    
    # Get the iCal content and create filename
    ical_content = cal.to_ical().decode('utf-8')
    filename = f"{staff_name}_schedule_{fiscal_year_start.strftime('%Y%m%d')}.ics"
    
    return ical_content, filename


def validate_schedule_pattern(schedule):
    """
    Validate that the schedule pattern is exactly 6 weeks (42 days).
    
    Args:
        schedule: List of (date, shift) tuples
    
    Returns:
        bool: True if valid 6-week pattern, False otherwise
    """
    if len(schedule) != 42:
        return False
    
    # Check that dates are consecutive
    for i in range(1, len(schedule)):
        prev_date = schedule[i-1][0]
        curr_date = schedule[i][0]
        if (curr_date - prev_date).days != 1:
            return False
    
    return True


def get_pattern_day_name(day_index):
    """
    Convert a day index (0-41) to the pattern day name (e.g., "Sun A 1", "Wed B 3").
    
    Args:
        day_index: Day index in the 6-week pattern (0-41)
    
    Returns:
        str: Pattern day name
    """
    days_of_week = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    week_letters = ["A", "A", "B", "B", "C", "C"]  # 2 weeks each of A, B, C
    week_numbers = [1, 2, 3, 4, 5, 6]
    
    week_index = day_index // 7  # Which week (0-5)
    day_of_week_index = day_index % 7  # Which day of the week (0-6)
    
    if week_index < len(week_letters):
        letter = week_letters[week_index]
        number = week_numbers[week_index]
        return f"{days_of_week[day_of_week_index]} {letter} {number}"
    else:
        return f"Day {day_index + 1}"


def get_fiscal_year_info():
    """
    Get information about the fiscal year and pattern mapping.
    Sept 28, 2025 = Sun B 3 (day 15 of pattern)
    Oct 26, 2025 = Sun A 1 (restart of pattern) 
    
    Returns:
        dict: Information about the fiscal year and pattern
    """
    # Calculate the true pattern start (Sun A 1)
    fiscal_start = datetime(2025, 9, 28)  # Sun B 3
    pattern_start = fiscal_start - timedelta(days=14)  # Sun A 1 (14 days earlier)
    fiscal_year_end = datetime(2026, 9, 26)
    
    return {
        "pattern_start": pattern_start,
        "pattern_start_name": "Sun A 1",
        "fiscal_year_start": fiscal_start,
        "fiscal_year_start_name": "Sun B 3",
        "fiscal_year_end": fiscal_year_end,
        "fiscal_offset": 14,  # Sept 28 is day 15 (index 14) of the pattern
        "pattern_length": 42
    }


def preview_schedule(staff_name, schedule, num_days=14):
    """
    Generate a preview of the schedule for debugging purposes.
    Shows the schedule starting from Sept 28, 2025 (Sun B 3).
    
    Args:
        staff_name: Name of the staff member
        schedule: List of (date, shift) tuples for the staff member
        num_days: Number of days to preview (default: 14)
    
    Returns:
        list: List of preview entries with date, pattern day, and shift
    """
    fiscal_info = get_fiscal_year_info()
    fiscal_year_start = fiscal_info["fiscal_year_start"]  # Sept 28, 2025
    fiscal_offset = fiscal_info["fiscal_offset"]  # 14 (for Sun B 3)
    schedule_length = len(schedule)
    
    preview = []
    current_date = fiscal_year_start
    
    for i in range(num_days):
        # Calculate which day in the 6-week pattern we're on
        pattern_day = (fiscal_offset + i) % schedule_length
        
        # Get the shift for this pattern day
        if pattern_day < len(schedule):
            pattern_date, shift = schedule[pattern_day]
            pattern_day_name = get_pattern_day_name(pattern_day)
            
            preview.append({
                "date": current_date + timedelta(days=i),
                "pattern_day": pattern_day_name,
                "shift": shift if shift and shift.strip() else "Off"
            })
    
    return preview


def check_database_exists():
    """
    Check if the SQLite database exists in the data folder.
    
    Returns:
        bool: True if database exists, False otherwise
    """
    import os
    return os.path.exists(get_database_path())


def get_all_staff_schedules():
    """
    Get schedules for all staff members in the database.
    
    Returns:
        dict: Dictionary mapping staff names to their schedules
    """
    try:
        staff_names = extract_staff_names_from_db()
        if not staff_names:
            return {}
        
        pattern_start, dates = extract_dates_from_db()
        schedule_data = extract_schedule_from_db(staff_names, dates)
        
        return schedule_data
    except Exception as e:
        print(f"Error getting all staff schedules: {e}")
        return {}


def generate_calendar_for_staff(staff_name, calendar_format="google"):
    """
    Generate a calendar file for a specific staff member.
    
    Args:
        staff_name: Name of the staff member
        calendar_format: Either "google" for CSV or "ical" for ICS
    
    Returns:
        tuple: (file_content, filename) or (None, None) if error
    """
    try:
        # Get schedule data
        schedule_data = get_all_staff_schedules()
        if staff_name not in schedule_data:
            return None, None
        
        schedule = schedule_data[staff_name]
        
        # Set date range
        start_date = datetime(2025, 9, 28)
        end_date = datetime(2026, 9, 26)
        
        if calendar_format.lower() == "google":
            return generate_google_calendar(staff_name, schedule, start_date, end_date)
        elif calendar_format.lower() == "ical":
            return generate_ical_calendar(staff_name, schedule, start_date, end_date)
        else:
            return None, None
            
    except Exception as e:
        print(f"Error generating calendar for {staff_name}: {e}")
        return None, None
