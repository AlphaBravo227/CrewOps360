# modules/admin_track_status.py
"""
Admin function for managing track active/inactive status
Allows administrators to activate or deactivate tracks and view status history
"""

import streamlit as st
import sqlite3
from datetime import datetime
from modules.db_utils import get_db_connection

def log_status_change(track_id, staff_name, old_status, new_status, admin_user):
    """
    Log a status change to track_history table
    
    Args:
        track_id: ID of the track being modified
        staff_name: Name of staff member
        old_status: Previous is_active value (0 or 1)
        new_status: New is_active value (0 or 1)
        admin_user: Username of admin making the change
    
    Returns:
        tuple: (success, message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current track data
        cursor.execute("SELECT track_data FROM tracks WHERE id = ?", (track_id,))
        result = cursor.fetchone()
        
        if not result:
            return (False, "Track not found")
        
        track_data = result[0]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Determine status text
        status_text = "activated" if new_status == 1 else "deactivated"
        
        # Insert into track_history
        cursor.execute("""
            INSERT INTO track_history 
            (track_id, staff_name, track_data, submission_date, status, notes) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            track_id,
            staff_name,
            track_data,
            timestamp,
            status_text,
            f"Status changed by {admin_user} from {old_status} to {new_status}"
        ))
        
        conn.commit()
        return (True, f"Status change logged successfully")
        
    except Exception as e:
        return (False, f"Error logging status change: {str(e)}")

def change_track_status(track_id, staff_name, new_status, admin_user):
    """
    Change the is_active status of a track
    
    Args:
        track_id: ID of the track to modify
        staff_name: Name of staff member
        new_status: New is_active value (0 or 1)
        admin_user: Username of admin making the change
    
    Returns:
        tuple: (success, message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current status
        cursor.execute("SELECT is_active FROM tracks WHERE id = ?", (track_id,))
        result = cursor.fetchone()
        
        if not result:
            return (False, "Track not found")
        
        old_status = result[0]
        
        # Check if status is already the target value
        if old_status == new_status:
            status_text = "active" if new_status == 1 else "inactive"
            return (False, f"Track is already {status_text}")
        
        # Update the status
        cursor.execute("""
            UPDATE tracks 
            SET is_active = ? 
            WHERE id = ?
        """, (new_status, track_id))
        
        conn.commit()
        
        # Log the change
        log_success, log_msg = log_status_change(track_id, staff_name, old_status, new_status, admin_user)
        
        if not log_success:
            st.warning(f"Status changed but logging failed: {log_msg}")
        
        status_text = "activated" if new_status == 1 else "deactivated"
        return (True, f"Track {status_text} successfully")
        
    except Exception as e:
        return (False, f"Error changing track status: {str(e)}")

def get_all_tracks_with_status():
    """
    Get all tracks with their current status and relevant information
    
    Returns:
        list: List of tuples containing track information
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                t.id,
                t.staff_name,
                t.is_active,
                t.submission_date,
                t.version,
                t.effective_role,
                (SELECT submission_date 
                 FROM track_history 
                 WHERE track_id = t.id 
                 AND status IN ('activated', 'deactivated')
                 ORDER BY submission_date DESC 
                 LIMIT 1) as last_status_change
            FROM tracks t
            ORDER BY t.staff_name, t.submission_date DESC
        """)
        
        return cursor.fetchall()
        
    except Exception as e:
        st.error(f"Error retrieving tracks: {str(e)}")
        return []

def get_status_change_history(track_id):
    """
    Get the history of status changes for a specific track
    
    Args:
        track_id: ID of the track
    
    Returns:
        list: List of status change records
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT submission_date, status, notes
            FROM track_history
            WHERE track_id = ? 
            AND status IN ('activated', 'deactivated')
            ORDER BY submission_date DESC
        """, (track_id,))
        
        return cursor.fetchall()
        
    except Exception as e:
        st.error(f"Error retrieving status history: {str(e)}")
        return []

def display_track_status_manager():
    """
    Main display function for the track status management admin interface
    """
    st.header("🔄 Track Status Manager")
    st.markdown("Manage active/inactive status of staff tracks")
    
    # Get admin username for logging
    admin_user = st.session_state.get('username', 'admin')
    
    # Search filter
    st.subheader("🔍 Search and Filter")
    search_term = st.text_input("Search by staff name:", placeholder="Enter staff name...")
    
    # Get all tracks
    all_tracks = get_all_tracks_with_status()
    
    if not all_tracks:
        st.warning("No tracks found in database")
        return
    
    # Filter by search term
    if search_term:
        filtered_tracks = [
            track for track in all_tracks 
            if search_term.lower() in track[1].lower()
        ]
    else:
        filtered_tracks = all_tracks
    
    # Display summary statistics
    col1, col2, col3 = st.columns(3)
    with col1:
        total_tracks = len(filtered_tracks)
        st.metric("Total Tracks", total_tracks)
    with col2:
        active_tracks = len([t for t in filtered_tracks if t[2] == 1])
        st.metric("Active Tracks", active_tracks)
    with col3:
        inactive_tracks = len([t for t in filtered_tracks if t[2] == 0])
        st.metric("Inactive Tracks", inactive_tracks)
    
    st.markdown("---")
    
    # Display tracks
    if not filtered_tracks:
        st.info("No tracks match your search criteria")
        return
    
    st.subheader("📋 Track List")
    
    # Create a table-like display
    for track in filtered_tracks:
        track_id, staff_name, is_active, submission_date, version, role, last_status_change = track
        
        # Create container for each track
        with st.container():
            col1, col2, col3, col4, col5, col6 = st.columns([2, 1, 2, 2, 1, 1])
            
            with col1:
                st.write(f"**{staff_name}**")
                if role:
                    st.caption(f"Role: {role}")
            
            with col2:
                if is_active == 1:
                    st.success("✅ Active")
                else:
                    st.error("❌ Inactive")
            
            with col3:
                st.write(f"Submitted: {submission_date}")
                st.caption(f"Version: {version}")
            
            with col4:
                if last_status_change:
                    st.write(f"Last Change:")
                    st.caption(f"{last_status_change}")
                else:
                    st.write("No status changes")
            
            with col5:
                # Deactivate button (only show if currently active)
                if is_active == 1:
                    if st.button("🔴 Deactivate", key=f"deactivate_{track_id}"):
                        success, message = change_track_status(track_id, staff_name, 0, admin_user)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
            
            with col6:
                # Activate button (only show if currently inactive)
                if is_active == 0:
                    if st.button("🟢 Activate", key=f"activate_{track_id}"):
                        success, message = change_track_status(track_id, staff_name, 1, admin_user)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
            
            # Add expander for status history
            with st.expander(f"📜 View Status History for {staff_name}"):
                history = get_status_change_history(track_id)
                if history:
                    for date, status, notes in history:
                        st.write(f"**{date}** - {status.upper()}")
                        if notes:
                            st.caption(notes)
                else:
                    st.info("No status change history available")
            
            st.markdown("---")

# Function to integrate into admin dashboard
def add_track_status_manager_to_admin():
    """
    Function to be called from the admin dashboard to add this functionality
    """
    display_track_status_manager()


# Integration instructions for training_modules/admin_access.py:
"""
To integrate this into your admin dashboard, add the following changes:

1. In the _show_admin_functions method, add this to the admin_sections list:
   ("🔄 Track Status Manager", "track_status_manager", "Activate/deactivate staff tracks"),

2. In the _render_admin_function method, add this condition:
   elif function_key == "track_status_manager":
       self._show_track_status_manager()

3. Add this new method to the AdminAccess class:
   def _show_track_status_manager(self):
       '''Show track status management functionality'''
       st.subheader("🔄 Track Status Manager")
       from modules.admin_track_status import display_track_status_manager
       display_track_status_manager()
"""
