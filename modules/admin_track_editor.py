# modules/admin_track_editor.py
"""
Admin Track Editor Module
Allows administrators to directly edit active track assignments
- Edit any of the 42 days with D, N, AT, or Off
- No validation constraints (admin override capability)
- Saves as new version with admin_edit identifier
- Shows confirmation dialog with change summary
- Generates PDF of changes after successful save
"""

import streamlit as st
import sqlite3
import json
from datetime import datetime
import pytz

_eastern_tz = pytz.timezone('America/New_York')
from modules.db_utils import get_db_connection
from modules.admin_pdf_generator import generate_admin_edit_pdf

# Define the 42 day columns (6 weeks)
DAY_COLUMNS = [
    "Sun A 1", "Mon A 1", "Tue A 1", "Wed A 1", "Thu A 1", "Fri A 1", "Sat A 1",
    "Sun A 2", "Mon A 2", "Tue A 2", "Wed A 2", "Thu A 2", "Fri A 2", "Sat A 2",
    "Sun B 3", "Mon B 3", "Tue B 3", "Wed B 3", "Thu B 3", "Fri B 3", "Sat B 3",
    "Sun B 4", "Mon B 4", "Tue B 4", "Wed B 4", "Thu B 4", "Fri B 4", "Sat B 4",
    "Sun C 5", "Mon C 5", "Tue C 5", "Wed C 5", "Thu C 5", "Fri C 5", "Sat C 5",
    "Sun C 6", "Mon C 6", "Tue C 6", "Wed C 6", "Thu C 6", "Fri C 6", "Sat C 6"
]

# Shift options for dropdown
SHIFT_OPTIONS = ["", "D", "N", "AT"]  # Empty string represents "Off"

def get_active_staff_list():
    """
    Get list of staff members with active tracks
    
    Returns:
        list: List of tuples (track_id, staff_name, submission_date, version)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, staff_name, submission_date, version, effective_role
            FROM tracks
            WHERE is_active = 1
            ORDER BY staff_name ASC
        """)
        
        return cursor.fetchall()
        
    except Exception as e:
        st.error(f"Error retrieving active staff: {str(e)}")
        return []

def get_track_data(track_id):
    """
    Get track data for a specific track ID
    
    Args:
        track_id: ID of the track
        
    Returns:
        dict: Track data including metadata
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                id, 
                staff_name, 
                track_data, 
                submission_date, 
                version,
                effective_role,
                has_preassignments,
                preassignment_count
            FROM tracks
            WHERE id = ?
        """, (track_id,))
        
        result = cursor.fetchone()
        
        if not result:
            return None
        
        # Parse the track data JSON
        track_json = json.loads(result[2])
        
        return {
            "track_id": result[0],
            "staff_name": result[1],
            "track_data": track_json,
            "submission_date": result[3],
            "version": result[4],
            "effective_role": result[5],
            "has_preassignments": result[6],
            "preassignment_count": result[7]
        }
        
    except Exception as e:
        st.error(f"Error retrieving track data: {str(e)}")
        return None

def get_preassignments_for_staff(staff_name):
    """
    Get preassignments for a specific staff member
    
    Args:
        staff_name: Name of the staff member
        
    Returns:
        list: List of tuples (day, activity)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT day, activity
            FROM preassignments
            WHERE staff_name = ?
            ORDER BY day
        """, (staff_name,))
        
        return cursor.fetchall()
        
    except Exception as e:
        st.error(f"Error retrieving preassignments: {str(e)}")
        return []

def calculate_changes(original_track, edited_track):
    """
    Calculate the differences between original and edited track
    
    Args:
        original_track: Original track data dictionary
        edited_track: Edited track data dictionary
        
    Returns:
        list: List of changes with day, original value, and new value
    """
    changes = []
    
    for day in DAY_COLUMNS:
        orig_val = original_track.get(day, "").strip()
        new_val = edited_track.get(day, "").strip()
        
        # Normalize empty values
        if not orig_val:
            orig_val = "Off"
        if not new_val:
            new_val = "Off"
            
        if orig_val != new_val:
            changes.append({
                "day": day,
                "original": orig_val,
                "new": new_val
            })
    
    return changes

def save_edited_track(track_id, staff_name, edited_track_data, admin_user, changes_summary):
    """
    Save the edited track to database as a new version with admin_edit status
    
    Args:
        track_id: ID of the track being edited
        staff_name: Name of staff member
        edited_track_data: Dictionary of edited track data
        admin_user: Username of admin making the edit
        changes_summary: Summary of changes made
        
    Returns:
        tuple: (success, message, new_version) - new_version is None if failed
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current version
        cursor.execute("SELECT version FROM tracks WHERE id = ?", (track_id,))
        result = cursor.fetchone()
        
        if not result:
            return (False, "Track not found", None)
        
        current_version = result[0]
        new_version = current_version + 1
        
        # Convert edited track data to JSON
        track_json = json.dumps(edited_track_data)
        timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to track_history with admin_edit status
        notes = f"Admin edit by {admin_user}. Changes: {len(changes_summary)} days modified"
        
        cursor.execute("""
            INSERT INTO track_history 
            (track_id, staff_name, track_data, submission_date, status, notes) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            track_id,
            staff_name,
            track_json,
            timestamp,
            "admin_edit",
            notes
        ))
        
        # Update the main tracks table
        cursor.execute("""
            UPDATE tracks 
            SET track_data = ?,
                submission_date = ?,
                version = ?,
                is_approved = 0,
                approved_by = NULL,
                approval_date = NULL
            WHERE id = ?
        """, (track_json, timestamp, new_version, track_id))
        
        conn.commit()
        
        return (True, f"Track updated successfully to version {new_version}", new_version)
        
    except Exception as e:
        return (False, f"Error saving edited track: {str(e)}", None)

def display_track_editor():
    """
    Main display function for the admin track editor interface
    """
    st.header("✏️ Admin Track Editor")
    st.markdown("Edit active track assignments with full override capability")
    
    # Get admin username
    admin_user = st.session_state.get('username', 'admin')
    
    # Initialize session state for editor
    if 'editor_selected_track_id' not in st.session_state:
        st.session_state.editor_selected_track_id = None
    if 'editor_track_data' not in st.session_state:
        st.session_state.editor_track_data = None
    if 'editor_edited_data' not in st.session_state:
        st.session_state.editor_edited_data = None
    if 'editor_show_confirmation' not in st.session_state:
        st.session_state.editor_show_confirmation = False
    
    # Staff Selection Section
    st.subheader("📋 Select Staff Member")
    
    active_staff = get_active_staff_list()
    
    if not active_staff:
        st.warning("No active tracks found in database")
        return
    
    # Create searchable dropdown with staff names
    staff_options = ["-- Select Staff Member --"] + [
        f"{staff[1]} (v{staff[3]}, {staff[4] if staff[4] else 'no role'})"
        for staff in active_staff
    ]
    
    selected_option = st.selectbox(
        "Search and select staff member:",
        options=staff_options,
        key="staff_selector"
    )
    
    # Parse selected staff
    if selected_option != "-- Select Staff Member --":
        # Extract staff name from the option
        staff_name = selected_option.split(" (v")[0]
        
        # Find the track ID for this staff member
        selected_track = next(
            (track for track in active_staff if track[1] == staff_name),
            None
        )
        
        if selected_track:
            track_id = selected_track[0]
            
            # Load button
            if st.button("📂 Load Track for Editing", type="primary"):
                track_data = get_track_data(track_id)
                if track_data:
                    st.session_state.editor_selected_track_id = track_id
                    st.session_state.editor_track_data = track_data
                    st.session_state.editor_edited_data = track_data['track_data'].copy()
                    st.session_state.editor_show_confirmation = False
                    st.session_state.editor_pdf_ready = False
                    st.session_state.editor_pdf_bytes = None
                    st.session_state.editor_pdf_filename = None
                    st.success(f"✅ Loaded track for {staff_name}")
                    st.rerun()
    
    # If track is loaded, show editor
    if st.session_state.editor_track_data:
        track_data = st.session_state.editor_track_data
        staff_name = track_data['staff_name']
        
        st.markdown("---")
        st.subheader(f"🔧 Editing Track for: {staff_name}")
        
        # Display track metadata
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Current Version", track_data['version'])
        with col2:
            st.metric("Role", track_data['effective_role'] or "N/A")
        with col3:
            st.metric("Last Modified", track_data['submission_date'][:10])
        with col4:
            preassign_count = track_data.get('preassignment_count', 0)
            st.metric("Preassignments", preassign_count)
        
        # Show preassignments if any
        if track_data.get('has_preassignments'):
            with st.expander("📌 View Preassignments", expanded=False):
                preassignments = get_preassignments_for_staff(staff_name)
                if preassignments:
                    for day, activity in preassignments:
                        st.info(f"**{day}**: {activity}")
                else:
                    st.caption("No preassignments found in database")
        
        st.markdown("---")
        
        # Track Editor Grid
        st.subheader("📅 Edit Track Assignments")
        st.caption("Select shift type for each day: D (Day), N (Night), AT (Administrative Time), or leave blank for Off")
        
        # Create the editing grid - 7 columns (one for each day of week)
        # 6 rows (one for each week)
        
        edited_data = st.session_state.editor_edited_data.copy()
        
        week_labels = ["Week A-1", "Week A-2", "Week B-3", "Week B-4", "Week C-5", "Week C-6"]
        
        for week_idx in range(6):
            st.markdown(f"**{week_labels[week_idx]}**")
            cols = st.columns(7)
            
            for day_idx in range(7):
                col_index = week_idx * 7 + day_idx
                day_name = DAY_COLUMNS[col_index]
                
                # Get current value
                current_value = edited_data.get(day_name, "").strip()
                if not current_value:
                    current_value = ""
                
                # Determine index for selectbox
                try:
                    current_index = SHIFT_OPTIONS.index(current_value)
                except ValueError:
                    current_index = 0  # Default to "Off"
                
                # Create selectbox in column
                with cols[day_idx]:
                    # Short day label
                    day_short = day_name.split()[0]  # "Sun", "Mon", etc.
                    
                    new_value = st.selectbox(
                        day_short,
                        options=SHIFT_OPTIONS,
                        index=current_index,
                        key=f"day_{col_index}",
                        label_visibility="visible"
                    )
                    
                    # Update edited data
                    edited_data[day_name] = new_value
            
            st.markdown("")  # Add spacing between weeks
        
        # Update session state
        st.session_state.editor_edited_data = edited_data
        
        st.markdown("---")
        
        # PDF Download Section (if PDF is ready)
        if st.session_state.get('editor_pdf_ready', False):
            st.subheader("📄 Download Admin Edit PDF")
            
            pdf_bytes = st.session_state.get('editor_pdf_bytes')
            pdf_filename = st.session_state.get('editor_pdf_filename')
            
            if pdf_bytes and pdf_filename:
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.success("✅ PDF is ready for download")
                    st.caption(f"Filename: {pdf_filename}")
                    st.caption("This PDF contains a summary of changes and the updated schedule.")
                
                with col2:
                    st.download_button(
                        label="📥 Download PDF",
                        data=pdf_bytes,
                        file_name=pdf_filename,
                        mime="application/pdf",
                        type="primary"
                    )
        
        st.markdown("---")
        
        # Action buttons
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            if st.button("💾 Save Changes", type="primary"):
                # Calculate changes
                changes = calculate_changes(
                    track_data['track_data'],
                    edited_data
                )
                
                if not changes:
                    st.warning("No changes detected")
                else:
                    # Show confirmation dialog
                    st.session_state.editor_show_confirmation = True
                    st.session_state.editor_changes = changes
                    st.rerun()
        
        with col2:
            if st.button("🔄 Reset to Original"):
                st.session_state.editor_edited_data = track_data['track_data'].copy()
                st.session_state.editor_show_confirmation = False
                st.success("Reset to original values")
                st.rerun()
        
        with col3:
            if st.button("❌ Cancel / Clear Editor"):
                st.session_state.editor_selected_track_id = None
                st.session_state.editor_track_data = None
                st.session_state.editor_edited_data = None
                st.session_state.editor_show_confirmation = False
                st.session_state.editor_pdf_ready = False
                st.session_state.editor_pdf_bytes = None
                st.session_state.editor_pdf_filename = None
                st.info("Editor cleared")
                st.rerun()
        
        # Confirmation Dialog
        if st.session_state.editor_show_confirmation:
            st.markdown("---")
            st.subheader("⚠️ Confirm Changes")
            
            changes = st.session_state.editor_changes
            
            st.warning(f"You are about to save **{len(changes)} changes** to {staff_name}'s track.")
            
            # Display changes in a table
            st.markdown("**Changes Summary:**")
            
            # Create a nice table display
            for idx, change in enumerate(changes, 1):
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.text(f"{idx}. {change['day']}")
                with col2:
                    st.text(f"{change['original']}")
                with col3:
                    st.text(f"→ {change['new']}")
            
            st.markdown("")
            
            # Confirmation buttons
            conf_col1, conf_col2 = st.columns(2)
            
            with conf_col1:
                if st.button("✅ Confirm and Save", type="primary", key="confirm_save"):
                    # Save the edited track
                    success, message, new_version = save_edited_track(
                        track_data['track_id'],
                        staff_name,
                        edited_data,
                        admin_user,
                        changes
                    )
                    
                    if success:
                        st.success(f"✅ {message}")
                        
                        # Generate PDF automatically
                        try:
                            # Get preassignments if any
                            preassignments_list = get_preassignments_for_staff(staff_name)
                            preassignments_dict = {day: activity for day, activity in preassignments_list} if preassignments_list else None
                            
                            # Generate the PDF
                            pdf_bytes, pdf_filename = generate_admin_edit_pdf(
                                staff_name=staff_name,
                                track_data=edited_data,
                                changes=changes,
                                version=new_version,
                                admin_user=admin_user,
                                preassignments=preassignments_dict
                            )
                            
                            # Store PDF in session state for download
                            st.session_state.editor_pdf_bytes = pdf_bytes
                            st.session_state.editor_pdf_filename = pdf_filename
                            st.session_state.editor_pdf_ready = True
                            
                            st.success("📄 PDF generated successfully!")
                            
                        except Exception as e:
                            st.warning(f"Track saved but PDF generation failed: {str(e)}")
                            st.session_state.editor_pdf_ready = False
                        
                        st.balloons()
                        
                        # Reload the track to show updated data
                        st.session_state.editor_track_data = get_track_data(track_data['track_id'])
                        st.session_state.editor_edited_data = st.session_state.editor_track_data['track_data'].copy()
                        st.session_state.editor_show_confirmation = False
                        
                        # Give user a moment to see the success message
                        import time
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
            
            with conf_col2:
                if st.button("🚫 Cancel", key="cancel_save"):
                    st.session_state.editor_show_confirmation = False
                    st.info("Changes cancelled")
                    st.rerun()

def add_track_editor_to_admin():
    """
    Function to be called from admin dashboard to add this functionality
    """
    display_track_editor()


# Integration instructions:
"""
To integrate this into your admin dashboard, add the following:

1. In admin_track_status.py or your admin interface, add a new tab/section:
   
   tab1, tab2 = st.tabs(["📄 Track Status", "✏️ Edit Tracks"])
   
   with tab1:
       display_track_status_manager()
   
   with tab2:
       from modules.admin_track_editor import display_track_editor
       display_track_editor()

2. Or add as a separate menu item in your admin functions list:
   ("✏️ Track Editor", "track_editor", "Edit active track assignments")

3. Then add the corresponding handler:
   elif function_key == "track_editor":
       from modules.admin_track_editor import display_track_editor
       display_track_editor()
"""
