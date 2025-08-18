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
        test_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        submission_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
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

def save_track_to_db(staff_name, track_data, is_new=False):
    """
    Save track data to SQLite database
    UPDATED: Enhanced to handle role metadata when available
    
    Args:
        staff_name (str): Name of the staff member
        track_data (dict or enhanced_dict): Dictionary of day -> assignment or enhanced structure
        is_new (bool): Whether this is a new track or an update
        
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
        
        # Get current date and time
        submission_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if staff member already has a track
        cursor.execute(
            "SELECT id, version FROM tracks WHERE staff_name = ? AND is_active = 1", 
            (staff_name,)
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
                        original_role, effective_role, track_source, has_preassignments, preassignment_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    metadata.get('preassignment_count', 0)
                ))
            else:
                # Legacy insert without metadata
                cursor.execute(
                    "INSERT INTO tracks (staff_name, track_data, submission_date, version, is_active) VALUES (?, ?, ?, ?, ?)",
                    (staff_name, track_json, submission_date, 1, 1)
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

def get_track_from_db(staff_name):
    """
    Retrieve track data from SQLite database
    UPDATED: Enhanced to return role metadata when available
    
    Args:
        staff_name (str): Name of the staff member
        
    Returns:
        tuple: (success, track_data_with_metadata or error_message)
    """
    try:
        # Validate input
        if not staff_name:
            return (False, "Invalid staff name provided")
        
        # Initialize database if needed
        initialize_database()
        
        # Get database connection for this thread
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query database for staff member's active track with metadata
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
        
        created_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
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

# Clean up connections when the module is unloaded
import atexit
atexit.register(close_all_connections)