# modules/db_utils.py - UPDATED WITH EFFECTIVE ROLE SUPPORT + verify_database_integrity
"""
Enhanced database utilities with effective role tracking
UPDATED to include staff role metadata in track submissions + missing verify_database_integrity function
"""

import sqlite3
import os
import pandas as pd
import json
from datetime import datetime
import streamlit as st
import threading
import pytz

# Eastern timezone for user-facing timestamps
_eastern_tz = pytz.timezone('America/New_York')

# Dictionary to store thread-local connections
thread_local_connections = {}

def get_db_connection():
    """
    Get a SQLite database connection for the current thread
    
    Returns:
        connection: SQLite connection object
    """
    # Get current thread ID
    thread_id = threading.get_ident()
    
    # Check if we already have a connection for this thread
    if thread_id in thread_local_connections:
        return thread_local_connections[thread_id]
        
    # Create database directory if it doesn't exist
    os.makedirs('data', exist_ok=True)
    
    # Create a new connection for this thread
    conn = sqlite3.connect('data/medflight_tracks.db')
    
    # Store it in our thread-local dictionary
    thread_local_connections[thread_id] = conn
    
    return conn

def close_all_connections():
    """Close all database connections"""
    global thread_local_connections
    
    for thread_id, conn in thread_local_connections.items():
        try:
            conn.close()
        except Exception:
            pass
    
    # Clear the dictionary
    thread_local_connections = {}

def verify_database_integrity():
    """
    Verify the integrity of the database structure and data
    NEW FUNCTION: Added to resolve the ImportError in app.py
    
    Returns:
        bool: True if database integrity is verified, False otherwise
    """
    try:
        # Check if database file exists
        db_path = 'data/medflight_tracks.db'
        if not os.path.exists(db_path):
            print("Database file does not exist")
            return False
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Test basic connectivity
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        if result[0] != 1:
            return False
        
        # Check if required tables exist
        required_tables = ['tracks', 'track_history', 'preassignments', 'track_swaps']
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [table[0] for table in cursor.fetchall()]
        
        missing_tables = [table for table in required_tables if table not in existing_tables]
        if missing_tables:
            print(f"Missing tables: {missing_tables}")
            return False
        
        # Check table structures - verify key columns exist
        cursor.execute("PRAGMA table_info(tracks)")
        tracks_columns = [column[1] for column in cursor.fetchall()]
        required_tracks_columns = ['id', 'staff_name', 'track_data', 'submission_date']
        missing_columns = [col for col in required_tracks_columns if col not in tracks_columns]
        if missing_columns:
            print(f"Missing columns in tracks table: {missing_columns}")
            return False
        
        # Test data integrity - check for corrupted JSON in track_data
        cursor.execute("SELECT id, staff_name, track_data FROM tracks WHERE is_active = 1")
        tracks = cursor.fetchall()
        
        for track_id, staff_name, track_data in tracks:
            try:
                json.loads(track_data)
            except json.JSONDecodeError:
                print(f"Corrupted JSON data found for track ID {track_id} (staff: {staff_name})")
                return False
        
        # Test write capability
        test_timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO track_history (track_id, staff_name, track_data, submission_date, status) VALUES (?, ?, ?, ?, ?)",
                      (0, "INTEGRITY_TEST", "{}", test_timestamp, "integrity_check"))
        
        # Remove the test record
        cursor.execute("DELETE FROM track_history WHERE staff_name = 'INTEGRITY_TEST' AND status = 'integrity_check'")
        
        conn.commit()
        
        return True
        
    except Exception as e:
        print(f"Database integrity check failed: {str(e)}")
        return False

def initialize_database():
    """
    Create SQLite database with all necessary tables
    UPDATED: Enhanced tracks table with role metadata columns + TRACK SWAP TABLE
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create database directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create enhanced tracks table with role tracking
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            track_data TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            is_approved INTEGER DEFAULT 0,
            approved_by TEXT,
            approval_date TEXT,
            version INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            original_role TEXT,
            effective_role TEXT,
            track_source TEXT,
            has_preassignments INTEGER DEFAULT 0,
            preassignment_count INTEGER DEFAULT 0
        )
        ''')
        
        # Create track_history table for audit trail
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS track_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            staff_name TEXT NOT NULL,
            track_data TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (track_id) REFERENCES tracks(id)
        )
        ''')

        # Create bid_drafts table for in-progress (not yet submitted) bid selections.
        # Kept separate from `tracks` so saving progress never creates a row that the
        # submission lock (a row existing in `tracks`) would mistake for a real submission.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bid_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            track_name TEXT NOT NULL,
            track_data TEXT NOT NULL,
            saved_date TEXT NOT NULL,
            UNIQUE(staff_name, track_name)
        )
        ''')

        # Create preassignments table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS preassignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            day TEXT NOT NULL,
            activity TEXT NOT NULL,
            created_date TEXT NOT NULL
        )
        ''')
        
        # NEW: Create track_swaps table for logging swap submissions
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS track_swaps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_name TEXT NOT NULL,
            requester_email TEXT NOT NULL,
            other_member_name TEXT NOT NULL,
            swap_details TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewed_by TEXT,
            review_date TEXT,
            review_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # NEW: Create user_location_preferences table for location-based shift preferences
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_location_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL UNIQUE,
            day_kmht INTEGER,
            day_klwm INTEGER,
            day_kbed INTEGER,
            day_1b9 INTEGER,
            day_kpym INTEGER,
            night_klwm INTEGER,
            night_kbed INTEGER,
            night_kpym INTEGER,
            zip_code TEXT NOT NULL,
            reduced_rest_ok INTEGER NOT NULL,
            n_to_d_flex TEXT NOT NULL,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
        ''')
        
        # Create track_configs table for track naming and bidding system
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS track_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL UNIQUE,
            is_active INTEGER DEFAULT 0,
            is_bidding_open INTEGER DEFAULT 0,
            max_day_nurses INTEGER DEFAULT 11,
            max_day_medics INTEGER DEFAULT 11,
            max_night_nurses INTEGER DEFAULT 5,
            max_night_medics INTEGER DEFAULT 5,
            day_vehicles INTEGER DEFAULT 9,
            night_vehicles INTEGER DEFAULT 4,
            day_leave_slots INTEGER DEFAULT 2,
            night_leave_slots INTEGER DEFAULT 1,
            min_day_staff INTEGER DEFAULT 7,
            min_night_staff INTEGER DEFAULT 4,
            day_kmht INTEGER DEFAULT 1,
            day_klwm INTEGER DEFAULT 2,
            day_kbed INTEGER DEFAULT 2,
            day_1b9 INTEGER DEFAULT 2,
            day_kpym INTEGER DEFAULT 2,
            night_klwm INTEGER DEFAULT 1,
            night_kbed INTEGER DEFAULT 2,
            night_kpym INTEGER DEFAULT 2,
            use_weekday_capacity INTEGER DEFAULT 0,
            auto_bid_progression INTEGER DEFAULT 0,
            needs_swap_open INTEGER DEFAULT 0,
            needs_swap_surplus_buffer INTEGER DEFAULT 0,
            needs_swap_min_day INTEGER DEFAULT 7,
            needs_swap_min_night INTEGER DEFAULT 5,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL
        )
        ''')

        # Per-cycle relaxations of a staff member's night/weekend minimum, written when
        # an admin approves a Needs Swap offer that drops them below one. Scoped to a
        # track cycle so a reduction granted for one cycle's shortfall doesn't silently
        # carry into the next; original_* keeps what the staff record said before the
        # first relaxation, so it is always clear what was given up and can be restored.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS needs_swap_requirement_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            night_minimum INTEGER,
            weekend_minimum INTEGER,
            original_night_minimum INTEGER,
            original_weekend_minimum INTEGER,
            offer_id INTEGER,
            created_by TEXT,
            created_date TEXT NOT NULL,
            modified_date TEXT NOT NULL,
            UNIQUE(track_name, staff_name)
        )
        ''')

        # NEW: Per-weekday capacity overrides, layered on top of a track's flat
        # max_day/night nurse/medic caps. NULL fields inherit the flat cap for
        # that track; only consulted when track_configs.use_weekday_capacity = 1.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS track_weekday_capacity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL,
            weekday TEXT NOT NULL,
            max_day_nurses INTEGER,
            max_day_medics INTEGER,
            max_night_nurses INTEGER,
            max_night_medics INTEGER,
            modified_date TEXT NOT NULL,
            UNIQUE(track_name, weekday)
        )
        ''')

        # Add reference columns to track_configs if they don't exist (migration)
        cursor.execute("PRAGMA table_info(track_configs)")
        tc_columns = [column[1] for column in cursor.fetchall()]
        if 'day_vehicles' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN day_vehicles INTEGER DEFAULT 9')
        if 'night_vehicles' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN night_vehicles INTEGER DEFAULT 4')
        if 'day_leave_slots' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN day_leave_slots INTEGER DEFAULT 2')
        if 'night_leave_slots' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN night_leave_slots INTEGER DEFAULT 1')
        if 'min_day_staff' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN min_day_staff INTEGER DEFAULT 7')
        if 'min_night_staff' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN min_night_staff INTEGER DEFAULT 4')
        if 'day_kmht' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN day_kmht INTEGER DEFAULT 1')
        if 'day_klwm' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN day_klwm INTEGER DEFAULT 2')
        if 'day_kbed' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN day_kbed INTEGER DEFAULT 2')
        if 'day_1b9' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN day_1b9 INTEGER DEFAULT 2')
        if 'day_kpym' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN day_kpym INTEGER DEFAULT 2')
        if 'night_klwm' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN night_klwm INTEGER DEFAULT 1')
        if 'night_kbed' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN night_kbed INTEGER DEFAULT 2')
        if 'night_kpym' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN night_kpym INTEGER DEFAULT 2')
        if 'use_weekday_capacity' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN use_weekday_capacity INTEGER DEFAULT 0')
        if 'auto_bid_progression' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN auto_bid_progression INTEGER DEFAULT 0')
        if 'needs_swap_open' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN needs_swap_open INTEGER DEFAULT 0')
        if 'needs_swap_surplus_buffer' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN needs_swap_surplus_buffer INTEGER DEFAULT 0')
        # Superseded needs_swap_surplus_buffer (a relative cushion on top of the
        # cycle's own minimum) with the absolute crew floors a shift must keep to be
        # given up, set per period. The old column is left in place but unused.
        if 'needs_swap_min_day' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN needs_swap_min_day INTEGER DEFAULT 7')
        if 'needs_swap_min_night' not in tc_columns:
            cursor.execute('ALTER TABLE track_configs ADD COLUMN needs_swap_min_night INTEGER DEFAULT 5')

        # Check if we need to add the new columns to existing tracks table
        cursor.execute("PRAGMA table_info(tracks)")
        columns = [column[1] for column in cursor.fetchall()]

        # Add new columns if they don't exist
        if 'original_role' not in columns:
            cursor.execute('ALTER TABLE tracks ADD COLUMN original_role TEXT')
        if 'effective_role' not in columns:
            cursor.execute('ALTER TABLE tracks ADD COLUMN effective_role TEXT')
        if 'track_source' not in columns:
            cursor.execute('ALTER TABLE tracks ADD COLUMN track_source TEXT')
        if 'has_preassignments' not in columns:
            cursor.execute('ALTER TABLE tracks ADD COLUMN has_preassignments INTEGER DEFAULT 0')
        if 'preassignment_count' not in columns:
            cursor.execute('ALTER TABLE tracks ADD COLUMN preassignment_count INTEGER DEFAULT 0')
        if 'track_name' not in columns:
            cursor.execute("ALTER TABLE tracks ADD COLUMN track_name TEXT DEFAULT 'FY26'")

        # Seed the default FY26 track config if it doesn't exist
        cursor.execute("SELECT id FROM track_configs WHERE track_name = 'FY26'")
        if not cursor.fetchone():
            now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('''
                INSERT INTO track_configs (track_name, is_active, is_bidding_open,
                    max_day_nurses, max_day_medics, max_night_nurses, max_night_medics,
                    day_vehicles, night_vehicles, day_leave_slots, night_leave_slots,
                    min_day_staff, min_night_staff,
                    day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
                    night_klwm, night_kbed, night_kpym,
                    created_date, modified_date)
                VALUES ('FY26', 1, 0, 11, 11, 5, 5, 9, 4, 2, 1, 7, 4, 1, 2, 2, 2, 2, 1, 2, 2, ?, ?)
            ''', (now, now))
        else:
            # Fill in any NULL columns on existing FY26 without overwriting user edits
            cursor.execute('''
                UPDATE track_configs SET
                    max_day_nurses = COALESCE(max_day_nurses, 11),
                    max_day_medics = COALESCE(max_day_medics, 11),
                    max_night_nurses = COALESCE(max_night_nurses, 5),
                    max_night_medics = COALESCE(max_night_medics, 5),
                    day_vehicles = COALESCE(day_vehicles, 9),
                    night_vehicles = COALESCE(night_vehicles, 4),
                    day_leave_slots = COALESCE(day_leave_slots, 2),
                    night_leave_slots = COALESCE(night_leave_slots, 1),
                    min_day_staff = COALESCE(min_day_staff, 7),
                    min_night_staff = COALESCE(min_night_staff, 4),
                    day_kmht = COALESCE(day_kmht, 1),
                    day_klwm = COALESCE(day_klwm, 2),
                    day_kbed = COALESCE(day_kbed, 2),
                    day_1b9 = COALESCE(day_1b9, 2),
                    day_kpym = COALESCE(day_kpym, 2),
                    night_klwm = COALESCE(night_klwm, 1),
                    night_kbed = COALESCE(night_kbed, 2),
                    night_kpym = COALESCE(night_kpym, 2)
                WHERE track_name = 'FY26'
            ''')

        # Backfill track_name on any existing rows that are still NULL
        cursor.execute("UPDATE tracks SET track_name = 'FY26' WHERE track_name IS NULL")

        # NEW: Create summer_leave_requests table for vacation time selections
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS summer_leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            week_start_date TEXT NOT NULL,
            week_end_date TEXT NOT NULL,
            selection_date TEXT NOT NULL,
            modified_date TEXT,
            status TEXT DEFAULT 'active'
        )
        ''')

        # NEW: Create summer_leave_config table for LT_OPEN status per user
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS summer_leave_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL UNIQUE,
            lt_open INTEGER DEFAULT 0,
            modified_date TEXT NOT NULL
        )
        ''')

        # NEW: Create track_bid_access table for per-staff bidding access, scoped
        # per track_name (bidding cycle) so access doesn't carry over between cycles.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS track_bid_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            track_name TEXT NOT NULL,
            bid_access INTEGER DEFAULT 0,
            modified_date TEXT NOT NULL,
            access_opened_date TEXT,
            UNIQUE(staff_name, track_name)
        )
        ''')

        # Add access_opened_date to track_bid_access if it doesn't exist (migration)
        cursor.execute("PRAGMA table_info(track_bid_access)")
        tba_columns = [column[1] for column in cursor.fetchall()]
        if 'access_opened_date' not in tba_columns:
            cursor.execute('ALTER TABLE track_bid_access ADD COLUMN access_opened_date TEXT')

        # NEW: Audit log of automatic bid-progression attempts (one row per bid
        # submission while the feature is on) plus manual bid-notification sends,
        # so admins can see what was — or wasn't — sent, and when.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bid_progression_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL,
            submitted_by TEXT NOT NULL,
            next_staff TEXT,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            notified_email TEXT,
            event_date TEXT NOT NULL,
            trigger_type TEXT DEFAULT 'auto'
        )
        ''')

        # Add trigger_type to bid_progression_log if it doesn't exist (migration)
        cursor.execute("PRAGMA table_info(bid_progression_log)")
        bpl_columns = [column[1] for column in cursor.fetchall()]
        if 'trigger_type' not in bpl_columns:
            cursor.execute("ALTER TABLE bid_progression_log ADD COLUMN trigger_type TEXT DEFAULT 'auto'")

        # NEW: Staff-submitted offers to move onto an identified staffing need.
        # One row per (staff, need, shift they'd give up) — a staff member may offer
        # several give-up options for the same need, ranked, and an admin approves the
        # single pairing they want to apply as a track change.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS track_need_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            need_day TEXT NOT NULL,
            need_period TEXT NOT NULL,
            give_up_day TEXT NOT NULL,
            give_up_period TEXT NOT NULL,
            preference_rank INTEGER NOT NULL DEFAULT 1,
            staff_notes TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            submission_date TEXT NOT NULL,
            reviewed_by TEXT,
            review_date TEXT,
            review_notes TEXT,
            UNIQUE(track_name, staff_name, need_day, need_period, give_up_day, give_up_period)
        )
        ''')

        # Commit changes
        conn.commit()
        
        return True
    
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        return False

# NEW FUNCTION: Add track swap database operations
def save_track_swap_to_db(requester_name, requester_email, other_member_name, swap_details):
    """
    Save track swap request to database
    
    Args:
        requester_name (str): Name of the person requesting the swap
        requester_email (str): Email of the requester
        other_member_name (str): Name of the other person involved
        swap_details (str): Details of the swap request
        
    Returns:
        tuple: (success, message, swap_id)
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current date and time
        submission_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # Insert track swap request
        cursor.execute("""
            INSERT INTO track_swaps 
            (requester_name, requester_email, other_member_name, swap_details, submission_date, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (requester_name, requester_email, other_member_name, swap_details, submission_date))
        
        # Get the new swap ID
        swap_id = cursor.lastrowid
        
        # Commit changes
        conn.commit()
        
        return (True, f"Track swap request saved for {requester_name} ↔ {other_member_name}", swap_id)
    
    except Exception as e:
        error_message = f"Error saving track swap: {str(e)}"
        print(error_message)
        return (False, error_message, None)

def get_track_swaps_from_db(limit=50):
    """
    Retrieve track swap requests from database
    
    Args:
        limit (int): Maximum number of records to return
        
    Returns:
        tuple: (success, swap_data or error_message)
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query database for track swaps
        cursor.execute("""
            SELECT id, requester_name, requester_email, other_member_name, 
                   swap_details, submission_date, status, reviewed_by, 
                   review_date, review_notes
            FROM track_swaps 
            ORDER BY submission_date DESC 
            LIMIT ?
        """, (limit,))
        
        swaps = cursor.fetchall()
        
        if not swaps:
            return (True, [])
        
        # Convert to list of dictionaries
        swap_list = []
        for swap in swaps:
            swap_dict = {
                'id': swap[0],
                'requester_name': swap[1],
                'requester_email': swap[2],
                'other_member_name': swap[3],
                'swap_details': swap[4],
                'submission_date': swap[5],
                'status': swap[6],
                'reviewed_by': swap[7],
                'review_date': swap[8],
                'review_notes': swap[9]
            }
            swap_list.append(swap_dict)
        
        return (True, swap_list)
    
    except Exception as e:
        error_message = f"Error retrieving track swaps: {str(e)}"
        print(error_message)
        return (False, error_message)

def save_track_to_db(staff_name, track_data, is_new=False, track_name=None):
    """
    Save track data to SQLite database

    Args:
        staff_name (str): Name of the staff member
        track_data (dict or enhanced_dict): Dictionary of day -> assignment or enhanced structure
        is_new (bool): Whether this is a new track or an update
        track_name (str, optional): Track name to save under (defaults to active track)

    Returns:
        tuple: (success, message, track_id)
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get fresh database connection for this thread
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Handle both legacy and enhanced track data formats
        if isinstance(track_data, dict) and 'track_data' in track_data and 'staff_metadata' in track_data:
            # Enhanced format with metadata
            actual_track_data = track_data['track_data']
            metadata = track_data['staff_metadata']
            track_json = json.dumps(actual_track_data)
        else:
            # Legacy format - just track data
            actual_track_data = track_data
            metadata = {}
            track_json = json.dumps(actual_track_data)
        
        # Resolve track_name: default to the active track config
        if not track_name:
            active_cfg = get_active_track_config()
            track_name = active_cfg['track_name'] if active_cfg else 'FY26'

        # Get current date and time
        submission_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        # Check if staff member already has a track for this track_name
        cursor.execute(
            "SELECT id, version FROM tracks WHERE staff_name = ? AND track_name = ? AND is_active = 1",
            (staff_name, track_name)
        )
        existing_track = cursor.fetchone()
        
        if existing_track and not is_new:
            # Update existing track
            track_id = existing_track[0]
            current_version = existing_track[1]
            new_version = current_version + 1
            
            # First, add entry to track_history
            cursor.execute(
                "INSERT INTO track_history (track_id, staff_name, track_data, submission_date, status) VALUES (?, ?, ?, ?, ?)",
                (track_id, staff_name, track_json, submission_date, "updated")
            )
            
            # Then update the main tracks table with new version number and metadata
            if metadata:
                cursor.execute("""
                    UPDATE tracks SET 
                        track_data = ?, 
                        submission_date = ?, 
                        is_approved = 0, 
                        approved_by = NULL, 
                        approval_date = NULL, 
                        version = ?,
                        original_role = ?,
                        effective_role = ?,
                        track_source = ?,
                        has_preassignments = ?,
                        preassignment_count = ?
                    WHERE id = ?
                """, (
                    track_json, 
                    submission_date, 
                    new_version,
                    metadata.get('original_role'),
                    metadata.get('effective_role'),
                    metadata.get('track_source'),
                    1 if metadata.get('has_preassignments') else 0,
                    metadata.get('preassignment_count', 0),
                    track_id
                ))
            else:
                # Legacy update without metadata
                cursor.execute(
                    "UPDATE tracks SET track_data = ?, submission_date = ?, is_approved = 0, approved_by = NULL, approval_date = NULL, version = ? WHERE id = ?",
                    (track_json, submission_date, new_version, track_id)
                )
            
            message = f"Track updated for {staff_name} (version {new_version})"
            if metadata.get('effective_role'):
                message += f" (role: {metadata.get('effective_role')})"
        else:
            # Deactivate existing tracks if creating a new one
            if is_new and existing_track:
                # Mark existing track as inactive
                track_id = existing_track[0]
                cursor.execute(
                    "UPDATE tracks SET is_active = 0 WHERE id = ?",
                    (track_id,)
                )
                
                # Add entry to track_history for deactivation
                cursor.execute(
                    "INSERT INTO track_history (track_id, staff_name, track_data, submission_date, status) VALUES (?, ?, ?, ?, ?)",
                    (track_id, staff_name, "{}", submission_date, "deactivated")
                )
            
            # Insert new track with metadata if available
            if metadata:
                cursor.execute("""
                    INSERT INTO tracks (
                        staff_name, track_data, submission_date, version, is_active,
                        original_role, effective_role, track_source, has_preassignments, preassignment_count, track_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    staff_name,
                    track_json,
                    submission_date,
                    1,
                    1,
                    metadata.get('original_role'),
                    metadata.get('effective_role'),
                    metadata.get('track_source'),
                    1 if metadata.get('has_preassignments') else 0,
                    metadata.get('preassignment_count', 0),
                    track_name
                ))
            else:
                # Legacy insert without metadata
                cursor.execute(
                    "INSERT INTO tracks (staff_name, track_data, submission_date, version, is_active, track_name) VALUES (?, ?, ?, ?, ?, ?)",
                    (staff_name, track_json, submission_date, 1, 1, track_name)
                )
            
            # Get the new track ID
            track_id = cursor.lastrowid
            
            # Add entry to track_history
            cursor.execute(
                "INSERT INTO track_history (track_id, staff_name, track_data, submission_date, status) VALUES (?, ?, ?, ?, ?)",
                (track_id, staff_name, track_json, submission_date, "created")
            )
            
            message = f"New track saved for {staff_name}"
            if metadata.get('effective_role'):
                message += f" (role: {metadata.get('effective_role')})"
        
        # Commit changes
        conn.commit()
        
        return (True, message, track_id)
    
    except Exception as e:
        error_message = f"Error saving track: {str(e)}"
        print(error_message)
        return (False, error_message, None)

def get_track_from_db(staff_name, track_name=None):
    """
    Retrieve track data from SQLite database.
    If track_name is None, returns the active track (is_active=1).
    If track_name is provided, returns the track for that track_name.

    Args:
        staff_name (str): Name of the staff member
        track_name (str, optional): Specific track_name to look up

    Returns:
        tuple: (success, track_data_with_metadata or error_message)
    """
    try:
        if not staff_name:
            return (False, "Invalid staff name provided")

        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()

        if track_name:
            cursor.execute("""
                SELECT id, track_data, submission_date, is_approved, version,
                       original_role, effective_role, track_source, has_preassignments, preassignment_count
                FROM tracks
                WHERE staff_name = ? AND track_name = ?
                ORDER BY version DESC LIMIT 1
            """, (staff_name, track_name))
        else:
            cursor.execute("""
                SELECT id, track_data, submission_date, is_approved, version,
                       original_role, effective_role, track_source, has_preassignments, preassignment_count
                FROM tracks
                WHERE staff_name = ? AND is_active = 1
            """, (staff_name,))
        result = cursor.fetchone()
        
        if result:
            track_id, track_json, submission_date, is_approved, version, original_role, effective_role, track_source, has_preassignments, preassignment_count = result
            
            # Convert JSON string back to dictionary
            try:
                track_data = json.loads(track_json)
                
                # Return enhanced track data with metadata
                return (True, {
                    'track_id': track_id,
                    'track_data': track_data,
                    'submission_date': submission_date,
                    'is_approved': is_approved == 1,
                    'version': version,
                    'metadata': {
                        'original_role': original_role,
                        'effective_role': effective_role,
                        'track_source': track_source,
                        'has_preassignments': has_preassignments == 1,
                        'preassignment_count': preassignment_count
                    }
                })
            except json.JSONDecodeError as e:
                print(f"JSON decode error for {staff_name}: {str(e)}")
                return (False, f"Error decoding track data for {staff_name}")
        else:
            print(f"No active track found for {staff_name}")
            return (False, f"No active track found for {staff_name}")
    
    except Exception as e:
        error_message = f"Error retrieving track: {str(e)}"
        print(error_message)
        return (False, error_message)

def _roles_from_staff_database(staff_name):
    """
    (original_role, effective_role) for a staff member, from the staff roster.

    Used to fill in track rows that carry no role metadata of their own.

    Returns:
        tuple: (clinical role, staffing bucket), defaulting to ('nurse', 'nurse').
    """
    try:
        from .staff_database import get_clinical_role, get_effective_role
        return (get_clinical_role(staff_name, 'nurse'),
                get_effective_role(staff_name, 'nurse'))
    except Exception as e:
        print(f"Could not resolve roles for {staff_name} from the staff database: {e}")
        return ('nurse', 'nurse')


def get_all_active_tracks():
    """
    Get all active tracks from the database for staffing analysis
    UPDATED: Enhanced to include role metadata for better analytics

    Returns:
        tuple: (success, tracks_data_with_metadata or error_message)
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get database connection for this thread
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query for all active tracks with metadata
        cursor.execute("""
            SELECT staff_name, track_data, submission_date, version,
                   original_role, effective_role, track_source, has_preassignments, preassignment_count
            FROM tracks 
            WHERE is_active = 1 
            ORDER BY staff_name
        """)
        results = cursor.fetchall()
        
        if results:
            # Format results with enhanced metadata
            tracks = []
            for row in results:
                staff_name, track_json, submission_date, version, original_role, effective_role, track_source, has_preassignments, preassignment_count = row

                # Tracks submitted before role metadata was recorded (and any imported
                # from a spreadsheet) have no role stored. Resolve it from the staff
                # roster rather than handing callers a None they have to guard against.
                if not original_role or not effective_role:
                    roster_original, roster_effective = _roles_from_staff_database(staff_name)
                    original_role = original_role or roster_original
                    effective_role = effective_role or roster_effective

                # Convert JSON string back to dictionary
                try:
                    track_data = json.loads(track_json)
                    tracks.append({
                        'staff_name': staff_name,
                        'track_data': track_data,
                        'submission_date': submission_date,
                        'version': version,
                        'metadata': {
                            'original_role': original_role,
                            'effective_role': effective_role,
                            'track_source': track_source,
                            'has_preassignments': has_preassignments == 1,
                            'preassignment_count': preassignment_count
                        }
                    })
                except json.JSONDecodeError:
                    # Skip corrupted track data
                    print(f"Warning: Corrupted track data for {staff_name}")
                    continue
            
            return (True, tracks)
        else:
            return (False, "No active tracks found")
    
    except Exception as e:
        error_message = f"Error retrieving active tracks: {str(e)}"
        print(error_message)
        return (False, error_message)

def get_database_staff_count_by_role(day, shift_type, preferences_df, staff_col_prefs, role_col):
    """
    Get count of staff assigned to a specific day and shift type from the database
    UPDATED: Enhanced to use effective role metadata when available
    
    Args:
        day (str): The day to check
        shift_type (str): "D" for day or "N" for night
        preferences_df (DataFrame): Staff preferences data for role lookup
        staff_col_prefs (str): Column name for staff in preferences
        role_col (str): Column name for role in preferences
        
    Returns:
        dict: Dictionary with nurse_count and medic_count
    """
    try:
        # Get all active tracks
        success, tracks_data = get_all_active_tracks()
        if not success:
            return {"nurse_count": 0, "medic_count": 0}
        
        nurse_count = 0
        medic_count = 0
        
        for track in tracks_data:
            staff_name = track['staff_name']
            track_data = track['track_data']
            metadata = track.get('metadata', {})
            
            # Check if this staff has the specified shift type on this day
            if day in track_data and track_data[day] == shift_type:
                # Try to use effective role from metadata first
                effective_role = metadata.get('effective_role')
                
                if effective_role:
                    # Use the stored effective role
                    if effective_role == "nurse":
                        nurse_count += 1
                    elif effective_role == "medic":
                        medic_count += 1
                else:
                    # Fallback to preferences lookup
                    staff_info = preferences_df[preferences_df[staff_col_prefs] == staff_name]
                    if not staff_info.empty:
                        staff_role = staff_info.iloc[0][role_col]
                        
                        # Count based on role (treat dual as nurse)
                        if staff_role in ["nurse", "dual"]:
                            nurse_count += 1
                        elif staff_role == "medic":
                            medic_count += 1
        
        return {"nurse_count": nurse_count, "medic_count": medic_count}
        
    except Exception as e:
        print(f"Error getting database staff count: {str(e)}")
        return {"nurse_count": 0, "medic_count": 0}

def get_role_distribution_stats():
    """
    Get statistics about role distribution in submitted tracks
    NEW: Analytics function to show role breakdown
    
    Returns:
        dict: Role distribution statistics
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query for role distribution
        cursor.execute("""
            SELECT 
                original_role,
                effective_role,
                COUNT(*) as count,
                track_source
            FROM tracks 
            WHERE is_active = 1 
            GROUP BY original_role, effective_role, track_source
            ORDER BY count DESC
        """)
        results = cursor.fetchall()
        
        stats = {
            'total_tracks': 0,
            'by_original_role': {},
            'by_effective_role': {},
            'by_track_source': {},
            'role_conversions': []
        }
        
        for original_role, effective_role, count, track_source in results:
            stats['total_tracks'] += count
            
            # Count by original role
            if original_role:
                if original_role not in stats['by_original_role']:
                    stats['by_original_role'][original_role] = 0
                stats['by_original_role'][original_role] += count
            
            # Count by effective role
            if effective_role:
                if effective_role not in stats['by_effective_role']:
                    stats['by_effective_role'][effective_role] = 0
                stats['by_effective_role'][effective_role] += count
            
            # Count by track source
            if track_source:
                if track_source not in stats['by_track_source']:
                    stats['by_track_source'][track_source] = 0
                stats['by_track_source'][track_source] += count
            
            # Track role conversions (dual -> nurse)
            if original_role and effective_role and original_role != effective_role:
                stats['role_conversions'].append({
                    'from': original_role,
                    'to': effective_role,
                    'count': count
                })
        
        return stats
        
    except Exception as e:
        print(f"Error getting role distribution stats: {str(e)}")
        return {'total_tracks': 0, 'by_original_role': {}, 'by_effective_role': {}, 'by_track_source': {}, 'role_conversions': []}

# Legacy compatibility functions
def save_preassignment(staff_name, day, activity):
    """Save a preassignment to the database (unchanged)"""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        created_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "SELECT id FROM preassignments WHERE staff_name = ? AND day = ?",
            (staff_name, day)
        )
        existing = cursor.fetchone()
        
        if existing:
            preassignment_id = existing[0]
            cursor.execute(
                "UPDATE preassignments SET activity = ?, created_date = ? WHERE id = ?",
                (activity, created_date, preassignment_id)
            )
            message = f"Updated preassignment for {staff_name} on {day}"
        else:
            cursor.execute(
                "INSERT INTO preassignments (staff_name, day, activity, created_date) VALUES (?, ?, ?, ?)",
                (staff_name, day, activity, created_date)
            )
            preassignment_id = cursor.lastrowid
            message = f"Added new preassignment for {staff_name} on {day}"
        
        conn.commit()
        return (True, message, preassignment_id)
    
    except Exception as e:
        error_message = f"Error saving preassignment: {str(e)}"
        print(error_message)
        return (False, error_message, None)

def get_staff_preassignments(staff_name):
    """Get all preassignments for a staff member (unchanged)"""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id, day, activity, created_date FROM preassignments WHERE staff_name = ? ORDER BY day",
            (staff_name,)
        )
        results = cursor.fetchall()
        
        if results:
            preassignments = {}
            for row in results:
                preassignment_id, day, activity, created_date = row
                preassignments[day] = activity
            
            return (True, preassignments)
        else:
            return (False, f"No preassignments found for {staff_name}")
    
    except Exception as e:
        error_message = f"Error retrieving preassignments: {str(e)}"
        print(error_message)
        return (False, error_message)

def get_track_history_from_db(staff_name, limit=10):
    """
    Retrieve track history for a staff member
    UPDATED: Enhanced to include role metadata in history
    
    Args:
        staff_name (str): Name of the staff member
        limit (int): Maximum number of history records to retrieve
        
    Returns:
        tuple: (success, history_data or error_message)
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get database connection for this thread
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query database for staff member's track history with role info
        cursor.execute(
            """
            SELECT h.id, t.id, h.track_data, h.submission_date, h.status, t.version, t.is_active,
                   t.original_role, t.effective_role, t.track_source, t.has_preassignments, t.preassignment_count
            FROM track_history h
            JOIN tracks t ON h.track_id = t.id
            WHERE h.staff_name = ?
            ORDER BY h.submission_date DESC
            LIMIT ?
            """, 
            (staff_name, limit)
        )
        results = cursor.fetchall()
        
        if results:
            # Format results with metadata
            history = []
            for row in results:
                history_id, track_id, track_json, submission_date, status, version, is_active, original_role, effective_role, track_source, has_preassignments, preassignment_count = row
                
                # Convert JSON string back to dictionary
                try:
                    track_data = json.loads(track_json)
                except:
                    track_data = {}
                
                history.append({
                    'history_id': history_id,
                    'track_id': track_id,
                    'track_data': track_data,
                    'submission_date': submission_date,
                    'status': status,
                    'version': version,
                    'is_active': is_active == 1,
                    'metadata': {
                        'original_role': original_role,
                        'effective_role': effective_role,
                        'track_source': track_source,
                        'has_preassignments': has_preassignments == 1,
                        'preassignment_count': preassignment_count
                    }
                })
            
            return (True, history)
        else:
            return (False, f"No track history found for {staff_name}")
    
    except Exception as e:
        error_message = f"Error retrieving track history: {str(e)}"
        print(error_message)
        return (False, error_message)

def check_database_connection():
    """
    Check database connection and existence
    UPDATED: Enhanced to verify new role metadata columns
    
    Returns:
        tuple: (success, message)
    """
    try:
        # Check if database directory exists
        db_dir = 'data'
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            return (False, f"Created database directory '{db_dir}'")
        
        # Check if database file exists
        db_path = 'data/medflight_tracks.db'
        if not os.path.exists(db_path):
            # Try to initialize the database
            if initialize_database():
                return (True, "Database initialized successfully with role tracking")
            else:
                return (False, "Failed to initialize database")
        
        # Try to connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if tracks table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks'")
        if not cursor.fetchone():
            conn.close()
            return (False, "'tracks' table does not exist in the database")
        
        # Check if role metadata columns exist
        cursor.execute("PRAGMA table_info(tracks)")
        columns = [column[1] for column in cursor.fetchall()]
        
        missing_columns = []
        expected_columns = ['original_role', 'effective_role', 'track_source', 'has_preassignments', 'preassignment_count']
        for col in expected_columns:
            if col not in columns:
                missing_columns.append(col)
        
        if missing_columns:
            conn.close()
            return (False, f"Missing role metadata columns: {', '.join(missing_columns)}")
        
        # Check if preassignments table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='preassignments'")
        if not cursor.fetchone():
            conn.close()
            return (False, "'preassignments' table does not exist in the database")
        
        # Close connection
        conn.close()
        
        return (True, "Database connection successful with role tracking enabled")
    
    except Exception as e:
        return (False, f"Database error: {str(e)}")

def cleanup_inactive_tracks():
    """
    Clean up old inactive tracks to maintain database performance
    UPDATED: Enhanced to preserve role metadata in cleanup logs
    
    Returns:
        tuple: (success, message)
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Count inactive tracks older than 30 days with role info
        cursor.execute(
            """
            SELECT COUNT(*), 
                   COUNT(CASE WHEN effective_role = 'nurse' THEN 1 END) as nurse_tracks,
                   COUNT(CASE WHEN effective_role = 'medic' THEN 1 END) as medic_tracks
            FROM tracks 
            WHERE is_active = 0 
            AND datetime(submission_date) < datetime('now', '-30 days')
            """
        )
        result = cursor.fetchone()
        count_to_delete, nurse_tracks, medic_tracks = result if result else (0, 0, 0)
        
        if count_to_delete == 0:
            return (True, "No inactive tracks to clean up")
        
        # Delete old inactive tracks
        cursor.execute(
            """
            DELETE FROM tracks 
            WHERE is_active = 0 
            AND datetime(submission_date) < datetime('now', '-30 days')
            """
        )
        
        # Commit changes
        conn.commit()
        
        role_info = f" (nurses: {nurse_tracks}, medics: {medic_tracks})" if nurse_tracks or medic_tracks else ""
        return (True, f"Cleaned up {count_to_delete} old inactive tracks{role_info}")
    
    except Exception as e:
        error_message = f"Error cleaning up inactive tracks: {str(e)}"
        print(error_message)
        return (False, error_message)
    
def get_excel_to_db_column_mapping():
    """
    Get the mapping between Excel columns and database format
    This helps maintain consistency between Excel imports and database storage
    
    Returns:
        dict: Mapping information for Excel to database conversion
    """
    # The Excel file structure from your Tracks.xlsx:
    # Column 0: "STAFF NAME"
    # Columns 1-42: Day columns like "Sun A 1", "Mon A 1", etc.
    
    # Database structure:
    # - staff_name: Maps to "STAFF NAME" column
    # - track_data: JSON object with day columns as keys
    # - track_source: Set to "Preferred Track" for manual imports
    
    mapping_info = {
        "excel_staff_column": 0,  # First column contains staff names
        "excel_day_columns_start": 1,  # Day columns start from index 1
        "excel_day_columns_count": 42,  # 6 weeks × 7 days = 42 days
        "database_track_source": "Preferred Track",  # As requested
        "day_column_names": [
            "Sun A 1", "Mon A 1", "Tue A 1", "Wed A 1", "Thu A 1", "Fri A 1", "Sat A 1",
            "Sun A 2", "Mon A 2", "Tue A 2", "Wed A 2", "Thu A 2", "Fri A 2", "Sat A 2",
            "Sun B 3", "Mon B 3", "Tue B 3", "Wed B 3", "Thu B 3", "Fri B 3", "Sat B 3",
            "Sun B 4", "Mon B 4", "Tue B 4", "Wed B 4", "Thu B 4", "Fri B 4", "Sat B 4",
            "Sun C 5", "Mon C 5", "Tue C 5", "Wed C 5", "Thu C 5", "Fri C 5", "Sat C 5",
            "Sun C 6", "Mon C 6", "Tue C 6", "Wed C 6", "Thu C 6", "Fri C 6", "Sat C 6"
        ]
    }
    
    return mapping_info

def get_database_stats():
    """
    Get database statistics for admin dashboard
    NEW: Enhanced stats function for admin tools
    
    Returns:
        dict: Database statistics including role information
    """
    try:
        # Initialize database if needed
        initialize_database()
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Count active tracks
        cursor.execute("SELECT COUNT(*) FROM tracks WHERE is_active = 1")
        stats['active_tracks'] = cursor.fetchone()[0]
        
        # Count total submissions
        cursor.execute("SELECT COUNT(*) FROM track_history")
        stats['total_submissions'] = cursor.fetchone()[0]
        
        # Count approved tracks
        cursor.execute("SELECT COUNT(*) FROM tracks WHERE is_active = 1 AND is_approved = 1")
        stats['approved_tracks'] = cursor.fetchone()[0]
        
        # Get latest submission date
        cursor.execute("SELECT MAX(submission_date) FROM tracks WHERE is_active = 1")
        stats['latest_submission'] = cursor.fetchone()[0]
        
        # Count tracks by role
        cursor.execute("""
            SELECT effective_role, COUNT(*) 
            FROM tracks 
            WHERE is_active = 1 AND effective_role IS NOT NULL
            GROUP BY effective_role
        """)
        role_counts = cursor.fetchall()
        stats['tracks_by_role'] = {role: count for role, count in role_counts}
        
        # Count tracks by source
        cursor.execute("""
            SELECT track_source, COUNT(*) 
            FROM tracks 
            WHERE is_active = 1 AND track_source IS NOT NULL
            GROUP BY track_source
        """)
        source_counts = cursor.fetchall()
        stats['tracks_by_source'] = {source: count for source, count in source_counts}
        
        # Count track swaps
        cursor.execute("SELECT COUNT(*) FROM track_swaps")
        stats['track_swaps'] = cursor.fetchone()[0]
        
        # Count pending track swaps
        cursor.execute("SELECT COUNT(*) FROM track_swaps WHERE status = 'pending'")
        stats['pending_swaps'] = cursor.fetchone()[0]
        
        return stats
        
    except Exception as e:
        print(f"Error getting database stats: {str(e)}")
        return {}

def save_location_preferences_to_db(staff_name, day_locations, night_locations, zip_code, reduced_rest_ok, n_to_d_flex):
    """
    Save location-based preferences to database

    Args:
        staff_name (str): Name of the staff member
        day_locations (dict): Day location preferences {location: rank 1-5}
        night_locations (dict): Night location preferences {location: rank 1-3}
        zip_code (str): Staff member's zip code
        reduced_rest_ok (bool): Reduced rest preference
        n_to_d_flex (str): N to D flex preference (Yes/No/Maybe)

    Returns:
        tuple: (success, message)
    """
    try:
        # Initialize database if needed
        initialize_database()

        conn = get_db_connection()
        cursor = conn.cursor()

        current_timestamp = datetime.now(_eastern_tz).isoformat()

        # Convert boolean to integer for storage
        reduced_rest_value = 1 if reduced_rest_ok else 0

        # Insert or replace the location preferences
        cursor.execute("""
            INSERT OR REPLACE INTO user_location_preferences
            (staff_name, day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
             night_klwm, night_kbed, night_kpym, zip_code,
             reduced_rest_ok, n_to_d_flex, created_date, modified_date, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            staff_name,
            day_locations.get('KMHT'),
            day_locations.get('KLWM'),
            day_locations.get('KBED'),
            day_locations.get('1B9'),
            day_locations.get('KPYM'),
            night_locations.get('KLWM'),
            night_locations.get('KBED'),
            night_locations.get('KPYM'),
            zip_code,
            reduced_rest_value,
            n_to_d_flex,
            current_timestamp,
            current_timestamp
        ))

        conn.commit()
        return (True, "Location preferences saved successfully")

    except Exception as e:
        error_message = f"Error saving location preferences: {str(e)}"
        print(error_message)
        return (False, error_message)

def get_location_preferences_from_db(staff_name):
    """
    Retrieve location-based preferences from database

    Args:
        staff_name (str): Name of the staff member

    Returns:
        tuple: (success, preferences_dict or None)
    """
    try:
        # Initialize database if needed
        initialize_database()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
                   night_klwm, night_kbed, night_kpym, zip_code,
                   reduced_rest_ok, n_to_d_flex, modified_date
            FROM user_location_preferences
            WHERE staff_name = ? AND is_active = 1
        """, (staff_name,))

        result = cursor.fetchone()

        if result:
            (day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
             night_klwm, night_kbed, night_kpym, zip_code,
             reduced_rest_ok, n_to_d_flex, modified_date) = result

            preferences = {
                'day_locations': {
                    'KMHT': day_kmht,
                    'KLWM': day_klwm,
                    'KBED': day_kbed,
                    '1B9': day_1b9,
                    'KPYM': day_kpym
                },
                'night_locations': {
                    'KLWM': night_klwm,
                    'KBED': night_kbed,
                    'KPYM': night_kpym
                },
                'zip_code': zip_code,
                'reduced_rest_ok': bool(reduced_rest_ok),
                'n_to_d_flex': n_to_d_flex,
                'modified_date': modified_date
            }

            return (True, preferences)
        else:
            return (False, None)

    except Exception as e:
        error_message = f"Error retrieving location preferences: {str(e)}"
        print(error_message)
        return (False, None)

def get_all_location_preferences():
    """
    Get all active location preferences from the database

    Returns:
        tuple: (success, list of preferences or error_message)
    """
    try:
        # Initialize database if needed
        initialize_database()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT staff_name, day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
                   night_klwm, night_kbed, night_kpym, zip_code,
                   reduced_rest_ok, n_to_d_flex, modified_date
            FROM user_location_preferences
            WHERE is_active = 1
            ORDER BY staff_name
        """)

        results = cursor.fetchall()

        if results:
            preferences_list = []
            for row in results:
                (staff_name, day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
                 night_klwm, night_kbed, night_kpym, zip_code,
                 reduced_rest_ok, n_to_d_flex, modified_date) = row

                preferences_list.append({
                    'staff_name': staff_name,
                    'day_locations': {
                        'KMHT': day_kmht,
                        'KLWM': day_klwm,
                        'KBED': day_kbed,
                        '1B9': day_1b9,
                        'KPYM': day_kpym
                    },
                    'night_locations': {
                        'KLWM': night_klwm,
                        'KBED': night_kbed,
                        'KPYM': night_kpym
                    },
                    'zip_code': zip_code,
                    'reduced_rest_ok': bool(reduced_rest_ok),
                    'n_to_d_flex': n_to_d_flex,
                    'modified_date': modified_date
                })

            return (True, preferences_list)
        else:
            return (False, "No location preferences found")

    except Exception as e:
        error_message = f"Error retrieving all location preferences: {str(e)}"
        print(error_message)
        return (False, error_message)

# ============================================================================
# SUMMER LEAVE REQUESTS DATABASE FUNCTIONS
# ============================================================================

def get_summer_leave_config(staff_name):
    """
    Get LT_OPEN status for a staff member

    Args:
        staff_name (str): Name of staff member

    Returns:
        bool: True if LT is open for this staff member, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT lt_open FROM summer_leave_config
            WHERE staff_name = ?
        """, (staff_name,))

        result = cursor.fetchone()

        if result:
            return bool(result[0])
        else:
            # Default to False if no config exists
            return False

    except Exception as e:
        print(f"Error getting summer leave config for {staff_name}: {str(e)}")
        return False

def set_summer_leave_config(staff_name, lt_open):
    """
    Set LT_OPEN status for a staff member

    Args:
        staff_name (str): Name of staff member
        lt_open (bool): Whether LT is open for this staff member

    Returns:
        tuple: (success, message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        modified_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        lt_open_int = 1 if lt_open else 0

        # Check if config exists
        cursor.execute("SELECT id FROM summer_leave_config WHERE staff_name = ?", (staff_name,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE summer_leave_config
                SET lt_open = ?, modified_date = ?
                WHERE staff_name = ?
            """, (lt_open_int, modified_date, staff_name))
        else:
            cursor.execute("""
                INSERT INTO summer_leave_config (staff_name, lt_open, modified_date)
                VALUES (?, ?, ?)
            """, (staff_name, lt_open_int, modified_date))

        conn.commit()
        status = "enabled" if lt_open else "disabled"
        return (True, f"LT selection {status} for {staff_name}")

    except Exception as e:
        error_msg = f"Error setting summer leave config: {str(e)}"
        print(error_msg)
        return (False, error_msg)

def get_summer_leave_selection(staff_name):
    """
    Get summer leave selection for a staff member

    Args:
        staff_name (str): Name of staff member

    Returns:
        dict or None: Selection details if exists, None otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, role, week_start_date, week_end_date, selection_date, modified_date, shifts_used
            FROM summer_leave_requests
            WHERE staff_name = ? AND status = 'active'
        """, (staff_name,))

        result = cursor.fetchone()

        if result:
            return {
                'id': result[0],
                'staff_name': staff_name,
                'role': result[1],
                'week_start_date': result[2],
                'week_end_date': result[3],
                'selection_date': result[4],
                'modified_date': result[5],
                'shifts_used': result[6]
            }
        else:
            return None

    except Exception as e:
        print(f"Error getting summer leave selection for {staff_name}: {str(e)}")
        return None

def save_summer_leave_selection(staff_name, role, week_start_date, week_end_date, shifts_used=None):
    """
    Save or update summer leave selection for a staff member

    Args:
        staff_name (str): Name of staff member
        role (str): Staff member's role
        week_start_date (str): Start date of week (YYYY-MM-DD)
        week_end_date (str): End date of week (YYYY-MM-DD)
        shifts_used (int): Number of shifts being used (optional, defaults to staff's shifts per week)

    Returns:
        tuple: (success, message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        current_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        # Check if selection already exists
        cursor.execute("SELECT id FROM summer_leave_requests WHERE staff_name = ?", (staff_name,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE summer_leave_requests
                SET role = ?, week_start_date = ?, week_end_date = ?, modified_date = ?, status = 'active', shifts_used = ?
                WHERE staff_name = ?
            """, (role, week_start_date, week_end_date, current_date, shifts_used, staff_name))
            message = f"Updated leave selection for {staff_name}"
        else:
            cursor.execute("""
                INSERT INTO summer_leave_requests
                (staff_name, role, week_start_date, week_end_date, selection_date, status, shifts_used)
                VALUES (?, ?, ?, ?, ?, 'active', ?)
            """, (staff_name, role, week_start_date, week_end_date, current_date, shifts_used))
            message = f"Saved leave selection for {staff_name}"

        conn.commit()
        return (True, message)

    except Exception as e:
        error_msg = f"Error saving summer leave selection: {str(e)}"
        print(error_msg)
        return (False, error_msg)

def cancel_summer_leave_selection(staff_name):
    """
    Cancel summer leave selection for a staff member

    Args:
        staff_name (str): Name of staff member

    Returns:
        tuple: (success, message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        current_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            UPDATE summer_leave_requests
            SET status = 'cancelled', modified_date = ?
            WHERE staff_name = ? AND status = 'active'
        """, (current_date, staff_name))

        if cursor.rowcount > 0:
            conn.commit()
            return (True, f"Cancelled leave selection for {staff_name}")
        else:
            return (False, "No active selection found to cancel")

    except Exception as e:
        error_msg = f"Error cancelling summer leave selection: {str(e)}"
        print(error_msg)
        return (False, error_msg)

def get_week_selections_by_role(week_start_date, role):
    """
    Get total shifts used or person count for a specific week and role

    For NURSE/MEDIC: Returns sum of shifts_used (shift-based caps)
    For other roles: Returns count of people (person-based caps)

    Args:
        week_start_date (str): Start date of week (YYYY-MM-DD)
        role (str): Role to filter by

    Returns:
        int: Total shifts used (NURSE/MEDIC) or person count (others) for this week and role
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Shift-based counting for NURSE/MEDIC
        if role in ['NURSE', 'MEDIC']:
            cursor.execute("""
                SELECT SUM(shifts_used) FROM summer_leave_requests
                WHERE week_start_date = ? AND role = ? AND status = 'active'
            """, (week_start_date, role))

            result = cursor.fetchone()
            return result[0] if result and result[0] is not None else 0
        else:
            # Person-based counting for CCEMT, AMT, etc.
            cursor.execute("""
                SELECT COUNT(*) FROM summer_leave_requests
                WHERE week_start_date = ? AND role = ? AND status = 'active'
            """, (week_start_date, role))

            result = cursor.fetchone()
            return result[0] if result else 0

    except Exception as e:
        print(f"Error getting week selections: {str(e)}")
        return 0

def get_all_summer_leave_selections():
    """
    Get all active summer leave selections for admin view

    Returns:
        list: List of all active selections
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT staff_name, role, week_start_date, week_end_date, selection_date, modified_date, shifts_used
            FROM summer_leave_requests
            WHERE status = 'active'
            ORDER BY role, staff_name
        """)

        results = cursor.fetchall()

        selections = []
        for row in results:
            selections.append({
                'staff_name': row[0],
                'role': row[1],
                'week_start_date': row[2],
                'week_end_date': row[3],
                'selection_date': row[4],
                'modified_date': row[5],
                'shifts_used': row[6]
            })

        return selections

    except Exception as e:
        print(f"Error getting all summer leave selections: {str(e)}")
        return []

def get_all_summer_leave_configs():
    """
    Get all LT_OPEN configurations for admin view

    Returns:
        dict: Dictionary mapping staff_name to lt_open status
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT staff_name, lt_open
            FROM summer_leave_config
        """)

        results = cursor.fetchall()

        configs = {}
        for row in results:
            configs[row[0]] = bool(row[1])

        return configs

    except Exception as e:
        print(f"Error getting all summer leave configs: {str(e)}")
        return {}

# ============================================================================
# TRACK CONFIG / BIDDING DATABASE FUNCTIONS
# ============================================================================

def get_active_track_config():
    """Return the track_config row where is_active = 1, or None."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM track_configs WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        if row:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))
        return None
    except Exception as e:
        print(f"Error getting active track config: {e}")
        return None


def get_bidding_track_config():
    """Return the track_config row that is currently open for bidding, or None."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM track_configs WHERE is_bidding_open = 1 AND is_active = 0 LIMIT 1")
        row = cursor.fetchone()
        if row:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))
        return None
    except Exception as e:
        print(f"Error getting bidding track config: {e}")
        return None


def get_track_config_by_name(track_name):
    """Return track_config for a given track_name, or None."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM track_configs WHERE track_name = ?", (track_name,))
        row = cursor.fetchone()
        if row:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))
        return None
    except Exception as e:
        print(f"Error getting track config by name: {e}")
        return None


def get_all_track_configs():
    """Return all track_config rows."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM track_configs ORDER BY created_date DESC")
        rows = cursor.fetchall()
        if rows:
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, r)) for r in rows]
        return []
    except Exception as e:
        print(f"Error getting all track configs: {e}")
        return []


def create_track_config(track_name, max_day_nurses=11, max_day_medics=11,
                        max_night_nurses=5, max_night_medics=5,
                        day_vehicles=9, night_vehicles=4,
                        day_leave_slots=2, night_leave_slots=1,
                        min_day_staff=7, min_night_staff=4,
                        day_kmht=1, day_klwm=2, day_kbed=2, day_1b9=2, day_kpym=2,
                        night_klwm=1, night_kbed=2, night_kpym=2):
    """Create a new track config (not active, bidding closed by default)."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO track_configs
            (track_name, is_active, is_bidding_open,
             max_day_nurses, max_day_medics, max_night_nurses, max_night_medics,
             day_vehicles, night_vehicles, day_leave_slots, night_leave_slots,
             min_day_staff, min_night_staff,
             day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
             night_klwm, night_kbed, night_kpym,
             created_date, modified_date)
            VALUES (?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (track_name, max_day_nurses, max_day_medics,
              max_night_nurses, max_night_medics,
              day_vehicles, night_vehicles, day_leave_slots, night_leave_slots,
              min_day_staff, min_night_staff,
              day_kmht, day_klwm, day_kbed, day_1b9, day_kpym,
              night_klwm, night_kbed, night_kpym,
              now, now))
        conn.commit()
        return True, f"Track config '{track_name}' created successfully"
    except sqlite3.IntegrityError:
        return False, f"Track config '{track_name}' already exists"
    except Exception as e:
        return False, f"Error creating track config: {e}"


def update_track_config(track_name, **kwargs):
    """Update fields on a track config. Pass keyword args for columns to update."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        allowed = {'is_active', 'is_bidding_open', 'max_day_nurses', 'max_day_medics',
                    'max_night_nurses', 'max_night_medics',
                    'day_vehicles', 'night_vehicles', 'day_leave_slots', 'night_leave_slots',
                    'min_day_staff', 'min_night_staff',
                    'day_kmht', 'day_klwm', 'day_kbed', 'day_1b9', 'day_kpym',
                    'night_klwm', 'night_kbed', 'night_kpym', 'use_weekday_capacity',
                    'auto_bid_progression', 'needs_swap_open',
                    'needs_swap_min_day', 'needs_swap_min_night'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False, "No valid fields to update"
        updates['modified_date'] = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [track_name]
        cursor.execute(f"UPDATE track_configs SET {set_clause} WHERE track_name = ?", values)
        conn.commit()
        return True, f"Track config '{track_name}' updated"
    except Exception as e:
        return False, f"Error updating track config: {e}"


def toggle_bidding(track_name, open_bidding):
    """Open or close bidding for a track_name."""
    return update_track_config(track_name, is_bidding_open=1 if open_bidding else 0)


def get_track_capacity(track_name):
    """Return capacity dict for a track_name, or defaults."""
    config = get_track_config_by_name(track_name)
    if config:
        return {
            'max_day_nurses': config['max_day_nurses'],
            'max_day_medics': config['max_day_medics'],
            'max_night_nurses': config['max_night_nurses'],
            'max_night_medics': config['max_night_medics'],
            'day_vehicles': config.get('day_vehicles', 9),
            'night_vehicles': config.get('night_vehicles', 4),
            'day_leave_slots': config.get('day_leave_slots', 2),
            'night_leave_slots': config.get('night_leave_slots', 1),
            'min_day_staff': config.get('min_day_staff', 7),
            'min_night_staff': config.get('min_night_staff', 4),
            'use_weekday_capacity': bool(config.get('use_weekday_capacity', 0)),
        }
    return {'max_day_nurses': 11, 'max_day_medics': 11,
            'max_night_nurses': 5, 'max_night_medics': 5,
            'day_vehicles': 9, 'night_vehicles': 4,
            'day_leave_slots': 2, 'night_leave_slots': 1,
            'min_day_staff': 7, 'min_night_staff': 4,
            'use_weekday_capacity': False}


# Weekday order matches the first token of the "days" column labels generated by
# modules.track_management.utils.format_day_name (e.g. "Sun A 1" -> "Sun").
_WEEKDAY_ORDER = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def get_weekday_capacity_overrides(track_name):
    """
    Return {weekday: {'max_day_nurses': int|None, 'max_day_medics': int|None,
    'max_night_nurses': int|None, 'max_night_medics': int|None}} for all 7 weekdays
    of a track. A None field means "inherit the track's flat cap for that field".
    """
    result = {wd: {'max_day_nurses': None, 'max_day_medics': None,
                   'max_night_nurses': None, 'max_night_medics': None}
              for wd in _WEEKDAY_ORDER}
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT weekday, max_day_nurses, max_day_medics, max_night_nurses, max_night_medics
            FROM track_weekday_capacity WHERE track_name = ?
        """, (track_name,))
        for weekday, dn, dm, nn, nm in cursor.fetchall():
            if weekday in result:
                result[weekday] = {'max_day_nurses': dn, 'max_day_medics': dm,
                                    'max_night_nurses': nn, 'max_night_medics': nm}
        return result
    except Exception as e:
        print(f"Error getting weekday capacity overrides: {e}")
        return result


def set_weekday_capacity_override(track_name, weekday, max_day_nurses, max_day_medics,
                                   max_night_nurses, max_night_medics):
    """Upsert the day-of-week capacity override for one weekday of a track."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO track_weekday_capacity
                (track_name, weekday, max_day_nurses, max_day_medics,
                 max_night_nurses, max_night_medics, modified_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_name, weekday) DO UPDATE SET
                max_day_nurses = excluded.max_day_nurses,
                max_day_medics = excluded.max_day_medics,
                max_night_nurses = excluded.max_night_nurses,
                max_night_medics = excluded.max_night_medics,
                modified_date = excluded.modified_date
        ''', (track_name, weekday, max_day_nurses, max_day_medics,
              max_night_nurses, max_night_medics, now))
        conn.commit()
        return True, f"Saved {weekday} capacity for '{track_name}'"
    except Exception as e:
        return False, f"Error saving weekday capacity override: {e}"


def get_track_capacity_by_weekday(track_name):
    """
    Return {weekday: {max_day_nurses, max_day_medics, max_night_nurses, max_night_medics}}
    for all 7 weekdays. If the track doesn't have day-of-week limits enabled (or has
    no override for a given field), that weekday/field falls back to the track's flat
    caps — existing uniform-cap behavior is preserved unless an admin opts in.
    """
    base = get_track_capacity(track_name)
    flat = {k: base[k] for k in
            ('max_day_nurses', 'max_day_medics', 'max_night_nurses', 'max_night_medics')}
    result = {wd: dict(flat) for wd in _WEEKDAY_ORDER}

    if not base.get('use_weekday_capacity'):
        return result

    overrides = get_weekday_capacity_overrides(track_name)
    for wd, fields in overrides.items():
        for key, value in fields.items():
            if value is not None:
                result[wd][key] = value
    return result


# Default per-base shift-slot counts, matching the historical fixed shift-to-base
# mapping. KMHT and 1B9 have no night presence.
_DEFAULT_BASE_SHIFT_COUNTS = {
    'KMHT': {'day': 1, 'night': 0},
    'KLWM': {'day': 2, 'night': 1},
    'KBED': {'day': 2, 'night': 2},
    '1B9':  {'day': 2, 'night': 0},
    'KPYM': {'day': 2, 'night': 2},
}


def get_base_shift_counts(track_name):
    """
    Return {base_name: {'day': N, 'night': N}} shift-slot counts for a track config,
    used by the hypothetical scheduler to size competition for each base. Falls back
    to the historical fixed defaults for any track config not found or not yet
    carrying these columns.
    """
    config = get_track_config_by_name(track_name)
    if not config:
        return _DEFAULT_BASE_SHIFT_COUNTS
    return {
        'KMHT': {'day': config.get('day_kmht', _DEFAULT_BASE_SHIFT_COUNTS['KMHT']['day']), 'night': 0},
        'KLWM': {'day': config.get('day_klwm', _DEFAULT_BASE_SHIFT_COUNTS['KLWM']['day']),
                 'night': config.get('night_klwm', _DEFAULT_BASE_SHIFT_COUNTS['KLWM']['night'])},
        'KBED': {'day': config.get('day_kbed', _DEFAULT_BASE_SHIFT_COUNTS['KBED']['day']),
                 'night': config.get('night_kbed', _DEFAULT_BASE_SHIFT_COUNTS['KBED']['night'])},
        '1B9':  {'day': config.get('day_1b9', _DEFAULT_BASE_SHIFT_COUNTS['1B9']['day']), 'night': 0},
        'KPYM': {'day': config.get('day_kpym', _DEFAULT_BASE_SHIFT_COUNTS['KPYM']['day']),
                 'night': config.get('night_kpym', _DEFAULT_BASE_SHIFT_COUNTS['KPYM']['night'])},
    }


def promote_bid_to_active(bid_track_name):
    """
    Promote a bidding track to active:
    1. Set is_active=0 on the currently active track config
    2. Set is_active=0 on all tracks belonging to the old active track_name
    3. Set is_active=1, is_bidding_open=0 on the bid track config
    4. Set is_active=1 on all tracks belonging to the bid track_name
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        # Find current active track config
        cursor.execute("SELECT track_name FROM track_configs WHERE is_active = 1")
        active_row = cursor.fetchone()
        if active_row:
            old_active = active_row[0]
            # Deactivate old active config
            cursor.execute("UPDATE track_configs SET is_active = 0, modified_date = ? WHERE track_name = ?",
                           (now, old_active))
            # Deactivate all tracks in the old active group
            cursor.execute("UPDATE tracks SET is_active = 0 WHERE track_name = ?", (old_active,))

        # Activate the bid track config
        cursor.execute("""UPDATE track_configs SET is_active = 1, is_bidding_open = 0, modified_date = ?
                          WHERE track_name = ?""", (now, bid_track_name))
        # Activate all tracks in the bid group
        cursor.execute("UPDATE tracks SET is_active = 1 WHERE track_name = ?", (bid_track_name,))

        conn.commit()
        return True, f"'{bid_track_name}' is now the active track"
    except Exception as e:
        return False, f"Error promoting bid track: {e}"


def save_bid_track_to_db(staff_name, track_data, track_name, metadata=None):
    """Save a bid track for a staff member under a specific track_name."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()

        if isinstance(track_data, dict) and 'track_data' in track_data and 'staff_metadata' in track_data:
            actual_track_data = track_data['track_data']
            meta = track_data['staff_metadata']
        else:
            actual_track_data = track_data
            meta = metadata or {}

        track_json = json.dumps(actual_track_data)
        submission_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        # Check for existing bid by this staff for this track_name
        cursor.execute("""SELECT id, version FROM tracks
                          WHERE staff_name = ? AND track_name = ? AND is_active = 0""",
                       (staff_name, track_name))
        existing = cursor.fetchone()

        if existing:
            track_id = existing[0]
            new_version = existing[1] + 1
            cursor.execute("""INSERT INTO track_history
                (track_id, staff_name, track_data, submission_date, status)
                VALUES (?, ?, ?, ?, ?)""",
                (track_id, staff_name, track_json, submission_date, "bid_updated"))
            cursor.execute("""UPDATE tracks SET
                track_data = ?, submission_date = ?, version = ?,
                original_role = ?, effective_role = ?, track_source = ?,
                has_preassignments = ?, preassignment_count = ?
                WHERE id = ?""", (
                track_json, submission_date, new_version,
                meta.get('original_role'), meta.get('effective_role'),
                meta.get('track_source', 'Bid'),
                1 if meta.get('has_preassignments') else 0,
                meta.get('preassignment_count', 0),
                track_id))
            message = f"Bid updated for {staff_name} (version {new_version})"
        else:
            cursor.execute("""INSERT INTO tracks
                (staff_name, track_data, submission_date, version, is_active, track_name,
                 original_role, effective_role, track_source, has_preassignments, preassignment_count)
                VALUES (?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?)""", (
                staff_name, track_json, submission_date, track_name,
                meta.get('original_role'), meta.get('effective_role'),
                meta.get('track_source', 'Bid'),
                1 if meta.get('has_preassignments') else 0,
                meta.get('preassignment_count', 0)))
            track_id = cursor.lastrowid
            cursor.execute("""INSERT INTO track_history
                (track_id, staff_name, track_data, submission_date, status)
                VALUES (?, ?, ?, ?, ?)""",
                (track_id, staff_name, track_json, submission_date, "bid_created"))
            message = f"Bid saved for {staff_name}"

        conn.commit()
        return True, message, track_id
    except Exception as e:
        return False, f"Error saving bid: {e}", None


def get_bid_track_from_db(staff_name, track_name):
    """Get a staff member's bid track for a given track_name."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT id, track_data, submission_date, is_approved, version,
                          original_role, effective_role, track_source,
                          has_preassignments, preassignment_count
                          FROM tracks WHERE staff_name = ? AND track_name = ?
                          ORDER BY version DESC LIMIT 1""",
                       (staff_name, track_name))
        result = cursor.fetchone()
        if result:
            track_data = json.loads(result[1])
            return True, {
                'track_id': result[0],
                'track_data': track_data,
                'submission_date': result[2],
                'is_approved': result[3] == 1,
                'version': result[4],
                'metadata': {
                    'original_role': result[5],
                    'effective_role': result[6],
                    'track_source': result[7],
                    'has_preassignments': result[8] == 1,
                    'preassignment_count': result[9],
                }
            }
        return False, f"No bid found for {staff_name} in {track_name}"
    except Exception as e:
        return False, f"Error getting bid track: {e}"


def save_bid_draft(staff_name, track_name, track_data):
    """Save (upsert) a staff member's in-progress, not-yet-submitted bid selections."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        track_json = json.dumps(track_data)
        saved_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("SELECT id FROM bid_drafts WHERE staff_name = ? AND track_name = ?",
                       (staff_name, track_name))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("UPDATE bid_drafts SET track_data = ?, saved_date = ? WHERE id = ?",
                           (track_json, saved_date, existing[0]))
        else:
            cursor.execute("""INSERT INTO bid_drafts (staff_name, track_name, track_data, saved_date)
                              VALUES (?, ?, ?, ?)""",
                           (staff_name, track_name, track_json, saved_date))
        conn.commit()
        return True, saved_date
    except Exception as e:
        return False, f"Error saving progress: {e}"


def get_bid_draft(staff_name, track_name):
    """Get a staff member's saved in-progress bid draft, if any."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT track_data, saved_date FROM bid_drafts
                          WHERE staff_name = ? AND track_name = ?""",
                       (staff_name, track_name))
        result = cursor.fetchone()
        if result:
            return True, {'track_data': json.loads(result[0]), 'saved_date': result[1]}
        return False, f"No saved progress for {staff_name} in {track_name}"
    except Exception as e:
        return False, f"Error getting saved progress: {e}"


def delete_bid_draft(staff_name, track_name):
    """Delete a staff member's saved in-progress bid draft (e.g. once they submit for real)."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bid_drafts WHERE staff_name = ? AND track_name = ?",
                       (staff_name, track_name))
        conn.commit()
        return True, "Deleted"
    except Exception as e:
        return False, f"Error deleting saved progress: {e}"


def get_bid_summaries(track_name):
    """
    One row per submitted bid — staff name, version, submission date and effective
    role — without the 42-day track_data blob or the JSON parse that goes with it.

    For anywhere that lists or counts bids rather than reading them: get_all_bid_tracks()
    decodes every track for every bid, which is wasted work when all you want is who
    submitted and when.
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT staff_name, version, submission_date, effective_role
                          FROM tracks WHERE track_name = ? ORDER BY staff_name""",
                       (track_name,))
        return [{'staff_name': r[0], 'version': r[1], 'submission_date': r[2],
                 'effective_role': r[3]} for r in cursor.fetchall()]
    except Exception as e:
        print(f"Error getting bid summaries: {e}")
        return []


def count_bids_by_track():
    """{track_name: submitted bid count} for every cycle, in one query."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT track_name, COUNT(*) FROM tracks GROUP BY track_name")
        return dict(cursor.fetchall())
    except Exception as e:
        print(f"Error counting bids by track: {e}")
        return {}


def count_bid_access_by_track():
    """{track_name: number of staff with bid access enabled} for every cycle, in one query."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT track_name, COUNT(*) FROM track_bid_access
                          WHERE bid_access = 1 GROUP BY track_name""")
        return dict(cursor.fetchall())
    except Exception as e:
        print(f"Error counting bid access by track: {e}")
        return {}


def get_all_bid_tracks(track_name):
    """Get all submitted bids for a given track_name."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT staff_name, track_data, submission_date, version,
                          original_role, effective_role, track_source,
                          has_preassignments, preassignment_count
                          FROM tracks WHERE track_name = ?
                          ORDER BY staff_name""", (track_name,))
        results = cursor.fetchall()
        if results:
            tracks = []
            for row in results:
                try:
                    td = json.loads(row[1])
                    tracks.append({
                        'staff_name': row[0],
                        'track_data': td,
                        'submission_date': row[2],
                        'version': row[3],
                        'metadata': {
                            'original_role': row[4],
                            'effective_role': row[5],
                            'track_source': row[6],
                            'has_preassignments': row[7] == 1,
                            'preassignment_count': row[8],
                        }
                    })
                except json.JSONDecodeError:
                    continue
            return True, tracks
        return False, "No bids found"
    except Exception as e:
        return False, f"Error getting bid tracks: {e}"


def get_tracks_by_track_name(track_name):
    """Get all tracks for a given track_name (active or bid)."""
    return get_all_bid_tracks(track_name)


def delete_track_config(track_name):
    """Delete a track config and all associated bids/tracks."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM track_configs WHERE track_name = ?", (track_name,))
        row = cursor.fetchone()
        if not row:
            return False, f"Track config '{track_name}' not found"
        if row[0] == 1:
            return False, f"Cannot delete the active track config '{track_name}'"
        cursor.execute("SELECT id FROM tracks WHERE track_name = ?", (track_name,))
        track_ids = [r[0] for r in cursor.fetchall()]
        if track_ids:
            placeholders = ",".join("?" * len(track_ids))
            cursor.execute(f"DELETE FROM track_history WHERE track_id IN ({placeholders})", track_ids)
            cursor.execute("DELETE FROM tracks WHERE track_name = ?", (track_name,))
        cursor.execute("DELETE FROM track_weekday_capacity WHERE track_name = ?", (track_name,))
        cursor.execute("DELETE FROM track_configs WHERE track_name = ?", (track_name,))
        conn.commit()
        deleted_bids = len(track_ids)
        return True, f"Deleted track config '{track_name}' and {deleted_bids} associated bid(s)"
    except Exception as e:
        return False, f"Error deleting track config: {e}"


def delete_bid(staff_name, track_name):
    """Delete a single staff member's bid for a track."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tracks WHERE staff_name = ? AND track_name = ? AND is_active = 0",
                       (staff_name, track_name))
        row = cursor.fetchone()
        if not row:
            return False, f"No bid found for {staff_name} in {track_name}"
        track_id = row[0]
        cursor.execute("DELETE FROM track_history WHERE track_id = ?", (track_id,))
        cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        conn.commit()
        return True, f"Deleted bid for {staff_name} in {track_name}"
    except Exception as e:
        return False, f"Error deleting bid: {e}"


def wipe_all_bids(track_name):
    """Delete ALL bids for a track config (reset bidding)."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tracks WHERE track_name = ? AND is_active = 0", (track_name,))
        track_ids = [r[0] for r in cursor.fetchall()]
        if not track_ids:
            return True, f"No bids to delete for {track_name}"
        placeholders = ",".join("?" * len(track_ids))
        cursor.execute(f"DELETE FROM track_history WHERE track_id IN ({placeholders})", track_ids)
        cursor.execute("DELETE FROM tracks WHERE track_name = ? AND is_active = 0", (track_name,))
        conn.commit()
        return True, f"Wiped {len(track_ids)} bid(s) for {track_name}"
    except Exception as e:
        return False, f"Error wiping bids: {e}"


# ============================================================================
# TRACK BID ACCESS DATABASE FUNCTIONS (per-staff bidding access, per cycle)
# ============================================================================

def get_bid_access(staff_name, track_name):
    """
    Get bidding access status for a staff member for a specific bid track.

    Args:
        staff_name (str): Name of staff member
        track_name (str): Name of the bid track (cycle)

    Returns:
        bool: True if bidding access is open for this staff member, False otherwise
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT bid_access FROM track_bid_access
            WHERE staff_name = ? AND track_name = ?
        """, (staff_name, track_name))

        result = cursor.fetchone()

        if result:
            return bool(result[0])
        else:
            # Default to False if no config exists
            return False

    except Exception as e:
        print(f"Error getting bid access for {staff_name}: {str(e)}")
        return False

def set_bid_access(staff_name, track_name, access_open):
    """
    Set bidding access status for a staff member for a specific bid track.

    Args:
        staff_name (str): Name of staff member
        track_name (str): Name of the bid track (cycle)
        access_open (bool): Whether bidding access is open for this staff member

    Returns:
        tuple: (success, message)
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()

        modified_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        access_int = 1 if access_open else 0

        cursor.execute("SELECT id FROM track_bid_access WHERE staff_name = ? AND track_name = ?",
                       (staff_name, track_name))
        existing = cursor.fetchone()

        if existing:
            if access_open:
                # Record when access was opened - this is the "bid open notification sent"
                # moment, whether triggered by the auto-progression email or an admin
                # manually toggling access. Left untouched when access is later disabled,
                # so the most recent notification time stays visible either way.
                cursor.execute("""
                    UPDATE track_bid_access
                    SET bid_access = ?, modified_date = ?, access_opened_date = ?
                    WHERE staff_name = ? AND track_name = ?
                """, (access_int, modified_date, modified_date, staff_name, track_name))
            else:
                cursor.execute("""
                    UPDATE track_bid_access
                    SET bid_access = ?, modified_date = ?
                    WHERE staff_name = ? AND track_name = ?
                """, (access_int, modified_date, staff_name, track_name))
        else:
            cursor.execute("""
                INSERT INTO track_bid_access (staff_name, track_name, bid_access, modified_date, access_opened_date)
                VALUES (?, ?, ?, ?, ?)
            """, (staff_name, track_name, access_int, modified_date, modified_date if access_open else None))

        conn.commit()
        status = "enabled" if access_open else "disabled"
        return (True, f"Bid access {status} for {staff_name}")

    except Exception as e:
        error_msg = f"Error setting bid access: {str(e)}"
        print(error_msg)
        return (False, error_msg)

def get_all_bid_access_configs(track_name):
    """
    Get all bidding access configurations for a given bid track, for admin view.

    Args:
        track_name (str): Name of the bid track (cycle)

    Returns:
        dict: Dictionary mapping staff_name to bid_access status
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT staff_name, bid_access
            FROM track_bid_access
            WHERE track_name = ?
        """, (track_name,))

        results = cursor.fetchall()

        configs = {}
        for row in results:
            configs[row[0]] = bool(row[1])

        return configs

    except Exception as e:
        print(f"Error getting all bid access configs: {str(e)}")
        return {}


def get_all_bid_access_details(track_name):
    """
    Get all bidding access configs for a track, including when access was opened
    (the "bid open notification sent" timestamp - set whether access was opened by
    the auto-progression email or an admin manually toggling it on).

    Args:
        track_name (str): Name of the bid track (cycle)

    Returns:
        dict: staff_name -> {'access': bool, 'access_opened_date': str or None}
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT staff_name, bid_access, access_opened_date
            FROM track_bid_access
            WHERE track_name = ?
        """, (track_name,))

        return {
            row[0]: {'access': bool(row[1]), 'access_opened_date': row[2]}
            for row in cursor.fetchall()
        }

    except Exception as e:
        print(f"Error getting bid access details: {str(e)}")
        return {}


def log_bid_progression_event(track_name, submitted_by, next_staff, level, message,
                               notified_email=None, trigger_type='auto'):
    """
    Record one bid-progression attempt (sent or not sent) for the audit log shown in
    the Manage Bid Access tab — either the automatic cascade or a manual send.

    Args:
        track_name (str): Bid track/cycle name
        submitted_by (str): Staff member whose bid submission triggered this attempt,
            or a fixed label (e.g. "Manual Send") when trigger_type is 'manual'
        next_staff (str or None): Staff member notified/advanced (None if there was none)
        level (str): 'success', 'warning', or 'info'
        message (str): Human-readable description of what happened
        notified_email (str, optional): Email address actually notified, if any
        trigger_type (str): 'auto' (the automatic cascade) or 'manual' (admin-triggered)

    Returns:
        bool: True if the event was recorded, False otherwise
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        event_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO bid_progression_log
            (track_name, submitted_by, next_staff, level, message, notified_email, event_date, trigger_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (track_name, submitted_by, next_staff, level, message, notified_email, event_date, trigger_type))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error logging bid progression event: {str(e)}")
        return False


def get_bid_progression_log(track_name, limit=100):
    """
    Get recent bid-progression log entries (automatic and manual) for a track,
    newest first.

    Args:
        track_name (str): Bid track/cycle name
        limit (int): Maximum number of entries to return

    Returns:
        list: List of dicts with event_date, submitted_by, next_staff, level,
        message, notified_email, trigger_type
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT event_date, submitted_by, next_staff, level, message, notified_email, trigger_type
            FROM bid_progression_log
            WHERE track_name = ?
            ORDER BY id DESC
            LIMIT ?
        """, (track_name, limit))
        rows = cursor.fetchall()
        cols = ['event_date', 'submitted_by', 'next_staff', 'level', 'message', 'notified_email', 'trigger_type']
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        print(f"Error getting bid progression log: {str(e)}")
        return []


# ──────────────────────────────────────────────
# Track Needs Swap — staff offers to move onto an identified staffing need
# ──────────────────────────────────────────────

_NEED_OFFER_COLUMNS = [
    'id', 'track_name', 'staff_name', 'need_day', 'need_period',
    'give_up_day', 'give_up_period', 'preference_rank', 'staff_notes',
    'status', 'submission_date', 'reviewed_by', 'review_date', 'review_notes',
]


def get_requirement_overrides(track_name):
    """
    Per-cycle night/weekend minimum relaxations for one track cycle, as
    {staff_name: {night_minimum, weekend_minimum, original_night_minimum,
    original_weekend_minimum, offer_id, created_by, modified_date}}.

    A None minimum means that field is not relaxed for that person. Written by
    approving a Needs Swap offer — see track_needs_swap.apply_offer().
    """
    result = {}
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT staff_name, night_minimum, weekend_minimum, original_night_minimum,
                   original_weekend_minimum, offer_id, created_by, modified_date
            FROM needs_swap_requirement_overrides WHERE track_name = ?
        """, (track_name,))
        for row in cursor.fetchall():
            result[row[0]] = {
                'night_minimum': row[1], 'weekend_minimum': row[2],
                'original_night_minimum': row[3], 'original_weekend_minimum': row[4],
                'offer_id': row[5], 'created_by': row[6], 'modified_date': row[7],
            }
        return result
    except Exception as e:
        print(f"Error getting requirement overrides: {e}")
        return result


def set_requirement_override(track_name, staff_name, night_minimum=None, weekend_minimum=None,
                              original_night_minimum=None, original_weekend_minimum=None,
                              offer_id=None, created_by=None):
    """
    Record (or tighten) a per-cycle minimum relaxation for one staff member.

    The original_* values are written only the first time a person is relaxed on this
    cycle — a second approval must not overwrite the true starting figure with the
    already-reduced one. A minimum passed as None leaves that field as it stands.

    Returns (success, message).
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            SELECT night_minimum, weekend_minimum, original_night_minimum, original_weekend_minimum
            FROM needs_swap_requirement_overrides WHERE track_name = ? AND staff_name = ?
        """, (track_name, staff_name))
        existing = cursor.fetchone()

        if existing:
            night = night_minimum if night_minimum is not None else existing[0]
            weekend = weekend_minimum if weekend_minimum is not None else existing[1]
            orig_night = existing[2] if existing[2] is not None else original_night_minimum
            orig_weekend = existing[3] if existing[3] is not None else original_weekend_minimum
            cursor.execute("""
                UPDATE needs_swap_requirement_overrides
                SET night_minimum = ?, weekend_minimum = ?, original_night_minimum = ?,
                    original_weekend_minimum = ?, offer_id = ?, created_by = ?, modified_date = ?
                WHERE track_name = ? AND staff_name = ?
            """, (night, weekend, orig_night, orig_weekend, offer_id, created_by, now,
                  track_name, staff_name))
        else:
            cursor.execute("""
                INSERT INTO needs_swap_requirement_overrides
                    (track_name, staff_name, night_minimum, weekend_minimum,
                     original_night_minimum, original_weekend_minimum, offer_id,
                     created_by, created_date, modified_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (track_name, staff_name, night_minimum, weekend_minimum,
                  original_night_minimum, original_weekend_minimum, offer_id, created_by,
                  now, now))

        conn.commit()
        return True, f"Recorded minimum relaxation for {staff_name} on {track_name}."
    except Exception as e:
        print(f"Error setting requirement override: {e}")
        return False, str(e)


def clear_requirement_override(track_name, staff_name):
    """Drop a per-cycle minimum relaxation, restoring the staff record's own figures."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM needs_swap_requirement_overrides
            WHERE track_name = ? AND staff_name = ?
        """, (track_name, staff_name))
        removed = cursor.rowcount
        conn.commit()
        return True, (f"Restored {staff_name}'s own minimums." if removed
                      else f"No relaxation on file for {staff_name}.")
    except Exception as e:
        print(f"Error clearing requirement override: {e}")
        return False, str(e)


def get_needs_swap_track_config():
    """Return the track_config row with the needs-swap window open, or None."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM track_configs WHERE needs_swap_open = 1 LIMIT 1")
        row = cursor.fetchone()
        if row:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))
        return None
    except Exception as e:
        print(f"Error getting needs swap track config: {e}")
        return None


def save_need_swap_offers(track_name, staff_name, offers, staff_notes=None):
    """
    Replace a staff member's still-pending offers for a track cycle with `offers`.

    Offers already acted on by an admin (approved/declined/superseded) are left
    untouched — a staff member can revise what they're still waiting on, but can't
    rewrite history.

    Args:
        track_name (str): Bid track/cycle name
        staff_name (str): Staff member submitting
        offers (list): Dicts with need_day, need_period, give_up_day, give_up_period,
            preference_rank
        staff_notes (str, optional): Free-text note stored on every row of this submission

    Returns:
        tuple: (success, message)
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""DELETE FROM track_need_offers
                          WHERE track_name = ? AND staff_name = ? AND status = 'pending'""",
                       (track_name, staff_name))

        saved = 0
        for offer in offers:
            # An offer the admin already decided on stays as-is rather than being
            # re-opened as pending by a later submission.
            cursor.execute("""SELECT status FROM track_need_offers
                              WHERE track_name = ? AND staff_name = ? AND need_day = ?
                                AND need_period = ? AND give_up_day = ? AND give_up_period = ?""",
                           (track_name, staff_name, offer['need_day'], offer['need_period'],
                            offer['give_up_day'], offer['give_up_period']))
            if cursor.fetchone():
                continue
            cursor.execute("""INSERT INTO track_need_offers
                (track_name, staff_name, need_day, need_period, give_up_day, give_up_period,
                 preference_rank, staff_notes, status, submission_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                           (track_name, staff_name, offer['need_day'], offer['need_period'],
                            offer['give_up_day'], offer['give_up_period'],
                            int(offer.get('preference_rank', 1)), staff_notes, now))
            saved += 1

        conn.commit()
        if not offers:
            return True, "Your previous offers were withdrawn — nothing is pending for you now."
        return True, f"Submitted {saved} swap option{'s' if saved != 1 else ''}."
    except Exception as e:
        return False, f"Error saving swap offers: {e}"


def get_need_swap_offers(track_name, staff_name=None, statuses=None):
    """
    Offers for a track cycle, newest submission first.

    Args:
        track_name (str): Bid track/cycle name
        staff_name (str, optional): Limit to one staff member
        statuses (list, optional): Limit to these status values

    Returns:
        list: List of dicts keyed by _NEED_OFFER_COLUMNS
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        query = f"SELECT {', '.join(_NEED_OFFER_COLUMNS)} FROM track_need_offers WHERE track_name = ?"
        params = [track_name]
        if staff_name:
            query += " AND staff_name = ?"
            params.append(staff_name)
        if statuses:
            query += f" AND status IN ({', '.join('?' * len(statuses))})"
            params.extend(statuses)
        query += " ORDER BY need_day, staff_name, preference_rank"
        cursor.execute(query, params)
        return [dict(zip(_NEED_OFFER_COLUMNS, row)) for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error getting need swap offers: {e}")
        return []


def update_need_swap_offer_status(offer_id, status, reviewed_by=None, review_notes=None):
    """Set one offer's status (pending/approved/declined/superseded) and stamp the review."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""UPDATE track_need_offers
                          SET status = ?, reviewed_by = ?, review_date = ?, review_notes = ?
                          WHERE id = ?""",
                       (status, reviewed_by, now, review_notes, offer_id))
        conn.commit()
        return True, f"Offer marked {status}."
    except Exception as e:
        return False, f"Error updating offer: {e}"


def supersede_sibling_need_offers(offer_id):
    """
    Mark the approved offer's siblings — the same staff member's other pending
    give-up options for that same need — as superseded, since the need is now
    covered by them and only one of the options can be applied.

    Returns:
        int: Number of rows superseded
    """
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT track_name, staff_name, need_day, need_period
                          FROM track_need_offers WHERE id = ?""", (offer_id,))
        row = cursor.fetchone()
        if not row:
            return 0
        now = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""UPDATE track_need_offers
                          SET status = 'superseded', review_date = ?,
                              review_notes = 'Another option for this need was approved'
                          WHERE track_name = ? AND staff_name = ? AND need_day = ?
                            AND need_period = ? AND status = 'pending' AND id != ?""",
                       (now, row[0], row[1], row[2], row[3], offer_id))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"Error superseding sibling offers: {e}")
        return 0


def delete_need_swap_offers(track_name, staff_name=None):
    """Delete offers for a track cycle (all of them, or just one staff member's)."""
    try:
        initialize_database()
        conn = get_db_connection()
        cursor = conn.cursor()
        if staff_name:
            cursor.execute("DELETE FROM track_need_offers WHERE track_name = ? AND staff_name = ?",
                           (track_name, staff_name))
        else:
            cursor.execute("DELETE FROM track_need_offers WHERE track_name = ?", (track_name,))
        deleted = cursor.rowcount
        conn.commit()
        return True, f"Deleted {deleted} offer{'s' if deleted != 1 else ''}."
    except Exception as e:
        return False, f"Error deleting offers: {e}"


# Clean up connections when the module is unloaded
import atexit
atexit.register(close_all_connections)