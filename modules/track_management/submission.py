# modules/track_management/submission.py - UPDATED WITH ENHANCED BUTTON LOGIC AND EMAIL NOTIFICATIONS
"""
Module for handling track submission and PDF generation
UPDATED: Now includes effective role in track submission data, email notifications, and improved button logic
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

_eastern_tz = pytz.timezone('America/New_York')
from ..track_validator import validate_track
from ..shift_counter import count_shifts, count_shifts_by_pay_period, count_weekend_shifts_updated
from ..db_utils import save_track_to_db, get_track_from_db
from ..pdf_generator import generate_schedule_pdf
from ..backup_utils import handle_track_submission
from ..email_notifications import send_track_submission_notification
# Remove problematic imports - implement functions directly in this file
def get_effective_role(staff_role):
    """
    Get the effective role for staffing purposes
    
    Args:
        staff_role (str): Original staff role (nurse, medic, dual)
        
    Returns:
        str: Effective role (nurse or medic)
    """
    # Handle None or empty values
    if not staff_role:
        print(f"Warning: Empty or None role encountered, defaulting to 'nurse'")
        return "nurse"
    
    # Normalize the role to lowercase for comparison and remove whitespace
    normalized_role = str(staff_role).lower().strip()
    
    # Debug logging
    print(f"Debug: Processing role '{staff_role}' -> normalized to '{normalized_role}'")
    
    # Check for medic FIRST (more specific check)
    if 'medic' in normalized_role:
        print(f"Debug: Role '{staff_role}' identified as medic -> effective role: medic")
        return "medic"
    elif normalized_role == "dual" or 'dual' in normalized_role:
        print(f"Debug: Role '{staff_role}' identified as dual -> effective role: nurse")
        return "nurse"  # Dual providers are treated as nurses
    elif 'nurse' in normalized_role:
        print(f"Debug: Role '{staff_role}' identified as nurse -> effective role: nurse")
        return "nurse"
    else:
        # Log unexpected role for debugging
        print(f"ERROR: Unexpected role '{staff_role}' (normalized: '{normalized_role}'), defaulting to 'nurse'")
        # For safety, check one more time if it contains medic
        if 'medic' in staff_role.lower():
            print(f"Debug: Found 'medic' in unexpected role, returning medic")
            return "medic"
        return "nurse"


def validate_track_with_at(track_data, shifts_per_pay_period, night_minimum, weekend_minimum, preassignments=None):
    """
    FIXED: Validate track with proper AT handling and debugging output
    """
    results = {
        'pay_period_shifts': {'status': False, 'details': ''},
        'night_minimum': {'status': False, 'details': ''},
        'weekend_minimum': {'status': False, 'details': ''}
    }
    
    # Get all possible days from track_data keys (this should be the complete list of days)
    all_days = list(track_data.keys()) if isinstance(track_data, dict) else []
    
    # Make sure we have days to process
    if not all_days:
        results['pay_period_shifts']['details'] = "No days found in track data"
        return results
    
    # Check pay period requirements (14-day blocks)
    shifts_by_pay_period = []
    
    # Process each 14-day pay period
    for i in range(0, len(all_days), 14):
        period_days = all_days[i:i+14]
        period_shifts = 0
        
        for day in period_days:
            assignment = None
            
            # First check track_data
            if day in track_data and track_data[day] and str(track_data[day]).strip():
                assignment = str(track_data[day]).strip()
            # Then check preassignments if no assignment in track_data
            elif preassignments and day in preassignments and str(preassignments[day]).strip():
                assignment = str(preassignments[day]).strip()
            
            # Count D, N, and AT as shifts (normalize values to handle any case issues)
            if assignment and assignment.upper() in ["D", "N", "AT"]:
                period_shifts += 1
        
        shifts_by_pay_period.append(period_shifts)
    
    # Check if all pay periods meet requirement
    pay_period_status = all(period == shifts_per_pay_period for period in shifts_by_pay_period) if shifts_per_pay_period else True
    results['pay_period_shifts']['status'] = pay_period_status
    results['pay_period_shifts']['details'] = f"Pay period shifts: {shifts_by_pay_period}, required: {shifts_per_pay_period} each"
    
    # DEBUG: Add some debugging information
    if not pay_period_status:
        st.warning(f"🔍 **Debug Info**: Total days processed: {len(all_days)}")
        for i, period_count in enumerate(shifts_by_pay_period):
            period_start = i * 14
            period_end = min((i + 1) * 14, len(all_days))
            period_days = all_days[period_start:period_end]
            st.warning(f"Pay Period {i+1}: {period_count} shifts from {len(period_days)} days")
            
            # Show which days have assignments in this period
            period_assignments = []
            for day in period_days:
                assignment = None
                if day in track_data and track_data[day] and str(track_data[day]).strip():
                    assignment = str(track_data[day]).strip()
                elif preassignments and day in preassignments and str(preassignments[day]).strip():
                    assignment = str(preassignments[day]).strip()
                
                if assignment and assignment.upper() in ["D", "N", "AT"]:
                    period_assignments.append(f"{day}: {assignment}")
            
            if period_assignments:
                st.info(f"Period {i+1} assignments: {', '.join(period_assignments)}")
            else:
                st.info(f"Period {i+1}: No shifts found")
    
    # Count night shifts
    night_shifts = 0
    for day in all_days:
        assignment = None
        if day in track_data and track_data[day] and str(track_data[day]).strip():
            assignment = str(track_data[day]).strip()
        elif preassignments and day in preassignments and str(preassignments[day]).strip():
            assignment = str(preassignments[day]).strip()
        
        if assignment and assignment.upper() == "N":
            night_shifts += 1
    
    results['night_minimum']['status'] = night_shifts >= night_minimum if night_minimum else True
    results['night_minimum']['details'] = f"Found {night_shifts} night shifts, minimum required: {night_minimum}"
    
    # Count weekend shifts (including AT)
    weekend_shifts = 0
    for day in all_days:
        assignment = None
        if day in track_data and track_data[day] and str(track_data[day]).strip():
            assignment = str(track_data[day]).strip()
        elif preassignments and day in preassignments and str(preassignments[day]).strip():
            assignment = str(preassignments[day]).strip()
        
        if not assignment:
            continue
            
        day_parts = day.split()
        if len(day_parts) > 0:
            day_name = day_parts[0]
            
            # Count Friday night shifts
            if day_name == "Fri" and assignment.upper() == "N":
                weekend_shifts += 1
            # Count all Saturday and Sunday shifts (including AT)
            elif day_name in ["Sat", "Sun"] and assignment.upper() in ["D", "N", "AT"]:
                weekend_shifts += 1
    
    results['weekend_minimum']['status'] = weekend_shifts >= weekend_minimum if weekend_minimum else True
    results['weekend_minimum']['details'] = f"Found {weekend_shifts} weekend shifts, minimum required: {weekend_minimum}"
    
    return results

def display_preassignments(selected_staff, preassignments):
    """
    Display preassignments for the selected staff member
    """
    if not preassignments:
        return
        
    st.subheader("📅 Your Preassignments")
    st.info("The following days have been pre-assigned and cannot be changed:")
    
    # Create preassignment data for display
    preassign_data = []
    for day, preassign_value in preassignments.items():
        if preassign_value == "AT":
            description = "Administrative Time (AT)"
            counts_as = "Day Shift"
        elif preassign_value == "D":
            description = "Day Shift (Preassigned)"
            counts_as = "Day Shift"
        elif preassign_value == "N":
            description = "Night Shift (Preassigned)"
            counts_as = "Night Shift"
        else:
            description = f"Preassignment: {preassign_value}"
            counts_as = "Shift"
            
        preassign_data.append({
            "Day": day,
            "Assignment": description,
            "Counts As": counts_as
        })
    
    preassign_df = pd.DataFrame(preassign_data)
    st.dataframe(preassign_df, use_container_width=True)

def display_track_schedule(track_data, days, preassignments=None):
    """
    Display a schedule in a readable format with AT handling
    """
    # Define the blocks
    blocks = ["A", "B", "C"]
    
    # Create a block for each 2-week period
    for block_idx, block in enumerate(blocks):
        st.markdown(f"#### Block {block}")
        
        # Calculate the days for this block (2 weeks = 14 days)
        start_idx = block_idx * 14
        end_idx = start_idx + 14
        block_days = days[start_idx:end_idx]
        
        # Create column headers (days)
        day_headers = []
        for i in range(14):
            if i < len(block_days):
                day_headers.append(block_days[i])
        
        # Create a dictionary for the dataframe
        data = {
            "Assignment": []
        }
        
        # Fill in assignments from track data and preassignments
        for day in day_headers:
            if day in track_data and track_data[day]:
                # Use track data if available
                data["Assignment"].append(track_data[day])
            elif preassignments and day in preassignments:
                # Use preassignment if available and no track data
                preassign_value = preassignments[day]
                if preassign_value == "AT":
                    data["Assignment"].append("Pre: AT")
                else:
                    data["Assignment"].append(f"Pre: {preassign_value}")
            else:
                # Otherwise empty
                data["Assignment"].append("")
        
        # Create dataframe with days as columns
        df = pd.DataFrame(data, index=day_headers)
        
        # Custom styling function - handles AT preassignments
        def custom_highlight_cells(val):
            """Apply highlighting to cells based on cell value"""
            val_str = str(val) if val is not None else ""
            
            if val_str == "D":
                return 'background-color: #d4edda'  # Green for day shifts
            elif val_str == "N":
                return 'background-color: #cce5ff'  # Blue for night shifts
            elif val_str == "AT":
                return 'background-color: #fff3cd; font-weight: bold'  # Yellow for AT
            elif isinstance(val, str) and val.startswith("Pre:"):
                return 'background-color: #e2e3e5; font-weight: bold'  # Gray for preassignments
            else:
                return ''  # No background for off days
        
        # Display the dataframe with styles - transpose to show days as columns
        st.dataframe(
            df.T.style.map(custom_highlight_cells),
            use_container_width=True
        )
        
        # Add some spacing between blocks
        st.write("")
def display_track_comparison(original_track, modified_track, days):
    """
    Display a comparison between original and modified tracks
    """
    def normalize_value(value):
        """Normalize track values for consistent comparison"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()
    
    # Count changes with proper normalization
    changes = []
    for day in days:
        # Normalize both values for comparison
        orig_value = normalize_value(original_track.get(day))
        mod_value = normalize_value(modified_track.get(day))
        
        if orig_value != mod_value:
            # Display meaningful values (empty string shows as "Off")
            orig_display = orig_value if orig_value else "Off"
            mod_display = mod_value if mod_value else "Off"
            
            changes.append({
                "Day": day,
                "Original": orig_display,
                "Modified": mod_display
            })
    
def save_track_to_db_enhanced(staff_name, enhanced_track_data, is_new=False):
    """
    UPDATED: Enhanced save function that includes staff role metadata with debugging
    and fixes for medic role processing
    """
    try:
        from ..db_utils import initialize_database
        import sqlite3
        import json
        import os
        from datetime import datetime
        
        # Initialize database if needed
        initialize_database()
        
        # Create database directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Get database connection
        conn = sqlite3.connect('data/medflight_tracks.db')
        cursor = conn.cursor()
        
        # Check if tracks table needs new columns for metadata
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
        
        # Extract data from enhanced structure
        track_data = enhanced_track_data['track_data']
        metadata = enhanced_track_data['staff_metadata']
        
        # Debug logging
        print(f"\n=== Saving track for {staff_name} ===")
        print(f"Original role: {metadata.get('original_role')}")
        print(f"Effective role: {metadata.get('effective_role')}")
        print(f"Track source: {metadata.get('track_source')}")
        
        # Validate role data
        original_role = metadata.get('original_role', '')
        effective_role = metadata.get('effective_role', '')
        
        if not original_role:
            print(f"WARNING: No original role for {staff_name}")
        if not effective_role:
            print(f"WARNING: No effective role for {staff_name}")
        
        # Extra validation - ensure medics are saved correctly
        if original_role and original_role.lower().strip() == 'medic':
            if effective_role != 'medic':
                print(f"ERROR: Medic {staff_name} has incorrect effective role: {effective_role}")
                # Force correction
                effective_role = 'medic'
                metadata['effective_role'] = 'medic'
                print(f"CORRECTED: Set effective role to 'medic' for {staff_name}")
        
        # Also check if the word 'medic' appears anywhere in the original role
        elif original_role and 'medic' in original_role.lower():
            if effective_role != 'medic':
                print(f"ERROR: Staff with 'medic' in role ({original_role}) has incorrect effective role: {effective_role}")
                # Force correction
                effective_role = 'medic'
                metadata['effective_role'] = 'medic'
                print(f"CORRECTED: Set effective role to 'medic' for {staff_name}")
        
        # Update the metadata with corrected values
        metadata['original_role'] = original_role
        metadata['effective_role'] = effective_role
        
        # Convert track data to JSON string
        track_json = json.dumps(track_data)
        
        # Get current date and time
        submission_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if staff member already has a track
        cursor.execute(
            "SELECT id, version FROM tracks WHERE staff_name = ? AND is_active = 1", 
            (staff_name,)
        )
        existing_track = cursor.fetchone()
        
        if existing_track and not is_new:
            # Update existing track with enhanced metadata
            track_id = existing_track[0]
            current_version = existing_track[1]
            new_version = current_version + 1
            
            # First, add entry to track_history
            cursor.execute(
                "INSERT INTO track_history (track_id, staff_name, track_data, submission_date, status) VALUES (?, ?, ?, ?, ?)",
                (track_id, staff_name, track_json, submission_date, "updated")
            )
            
            # Then update the main tracks table with new version number and metadata
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
                original_role,
                effective_role,
                metadata.get('track_source', ''),
                1 if metadata.get('has_preassignments', False) else 0,
                metadata.get('preassignment_count', 0),
                track_id
            ))
            
            conn.commit()
            print(f"SUCCESS: Track updated for {staff_name} (version {new_version}, role: {effective_role})")
            return True, f"Track successfully updated for {staff_name} (version {new_version})", track_id
            
        else:
            # Insert new track with enhanced metadata
            cursor.execute("""
                INSERT INTO tracks (
                    staff_name, track_data, submission_date, is_approved, 
                    approved_by, approval_date, is_active, version,
                    original_role, effective_role, track_source,
                    has_preassignments, preassignment_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                staff_name, 
                track_json, 
                submission_date, 
                0,  # is_approved
                None,  # approved_by 
                None,  # approval_date
                1,  # is_active
                1,  # version
                original_role,
                effective_role,
                metadata.get('track_source', ''),
                1 if metadata.get('has_preassignments', False) else 0,
                metadata.get('preassignment_count', 0)
            ))
            
            track_id = cursor.lastrowid
            
            # Add initial entry to track_history
            cursor.execute(
                "INSERT INTO track_history (track_id, staff_name, track_data, submission_date, status) VALUES (?, ?, ?, ?, ?)",
                (track_id, staff_name, track_json, submission_date, "created")
            )
            
            conn.commit()
            print(f"SUCCESS: New track created for {staff_name} (role: {effective_role})")
            return True, f"New track successfully saved for {staff_name}", track_id
            
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            error_msg = f"A track already exists for {staff_name}. Please update the existing track instead."
        else:
            error_msg = f"Database integrity error: {str(e)}"
        print(f"ERROR: {error_msg}")
        return False, error_msg, None
        
    except Exception as e:
        error_msg = f"An error occurred while saving the track: {str(e)}"
        print(f"ERROR: {error_msg}")
        import traceback
        traceback.print_exc()
        return False, error_msg, None
        
    finally:
        if 'conn' in locals():
            conn.close()

def count_shifts_with_at_fixed(track_data, days, staff_preassignments):
    """
    FIXED: Count shifts with proper AT handling for track summary
    """
    total_shifts = 0
    day_shifts = 0
    night_shifts = 0
    
    # Get all possible days
    all_days = set()
    if isinstance(days, (list, tuple)):
        all_days.update(days)
    else:
        all_days.update(days.tolist() if hasattr(days, 'tolist') else list(days))
    
    # Count shifts for each day
    for day in all_days:
        assignment = None
        
        # Check track_data first
        if day in track_data and track_data[day]:
            assignment = track_data[day]
        # Then check preassignments
        elif staff_preassignments and day in staff_preassignments:
            assignment = staff_preassignments[day]
        
        # Count based on assignment (treat AT as day shift for counting)
        if assignment == "D" or assignment == "AT":
            day_shifts += 1
            total_shifts += 1
        elif assignment == "N":
            night_shifts += 1
            total_shifts += 1
    
    return total_shifts, day_shifts, night_shifts

def count_shifts_by_pay_period_with_at_fixed(track_data, days, staff_preassignments):
    """
    FIXED: Count shifts by pay period with proper AT handling
    """
    # Make sure days is a list
    if hasattr(days, 'tolist'):
        days_list = days.tolist()
    elif not isinstance(days, list):
        days_list = list(days)
    else:
        days_list = days
    
    shifts_by_pay_period = []
    
    # Process each 14-day pay period
    for i in range(0, len(days_list), 14):
        period_days = days_list[i:i+14]
        period_shifts = 0
        
        for day in period_days:
            assignment = None
            
            # Check track_data first
            if day in track_data and track_data[day]:
                assignment = track_data[day]
            # Then check preassignments
            elif staff_preassignments and day in staff_preassignments:
                assignment = staff_preassignments[day]
            
            # Count D, N, and AT as shifts
            if assignment in ["D", "N", "AT"]:
                period_shifts += 1
        
        shifts_by_pay_period.append(period_shifts)
    
    return shifts_by_pay_period
def submit_track(selected_staff, staff_track, days, shifts_per_pay_period, night_minimum, weekend_minimum=0, preassignments=None, is_new_track=False, has_db_track=False):
    """
    Handle track submission with enhanced button logic, email notifications and PDF generation
    FIXED: Now properly retrieves staff role from preferences DataFrame
    """
    st.subheader(f"Submit Track for {selected_staff}")
    
    # Check track source with consistent terminology
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
    
    # Get staff preassignments from session state
    staff_preassignments = st.session_state.get('staff_preassignments', {})
    
    # FIXED: Get staff role directly from preferences DataFrame instead of relying on session state
    preferences_df = st.session_state.get('preferences_df')
    staff_col_prefs = st.session_state.get('staff_col_prefs')
    role_col = st.session_state.get('role_col')
    
    # Default to nurse if we can't find the role
    staff_role = 'nurse'
    
    if preferences_df is not None and staff_col_prefs and role_col:
        try:
            # Look up the staff member in preferences
            staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff]
            if not staff_info.empty:
                staff_role = staff_info.iloc[0][role_col]
                print(f"DEBUG: Retrieved staff role '{staff_role}' for {selected_staff} from preferences")
            else:
                print(f"WARNING: Could not find {selected_staff} in preferences DataFrame")
        except Exception as e:
            print(f"ERROR: Failed to retrieve staff role: {str(e)}")
    else:
        print("WARNING: Missing preferences data for role lookup")
    
    # Get effective role and weekend group
    effective_role = get_effective_role(staff_role)
    weekend_group = st.session_state.get('weekend_group', None)
    
    print(f"DEBUG: Final role assignment for {selected_staff}: original='{staff_role}', effective='{effective_role}'")
    
    # Display track source information
    from modules.track_source_consistency import display_for_submission, get_track_data_source_info

    # Display mode information
    display_for_submission()

    # Display specific track status
    data_source_info = get_track_data_source_info(selected_staff, has_db_track)
    if data_source_info['source'] == 'Database':
        st.info(f"📊 You are updating your existing {data_source_info['source']} track.")
    elif data_source_info['source'] == 'New Track':
        st.info("ℹ️ You are creating your first track in the system.")
    else:
        st.info(f"📄 You are updating from {data_source_info['source']}.")
    
    # Check if there's a modified track in session state
    if 'modified_track' not in st.session_state or st.session_state.modified_track.get('staff') != selected_staff:
        # Create one if it doesn't exist
        if 'track_changes' not in st.session_state or selected_staff not in st.session_state.track_changes:
            # Extract track data based on Annual Rebid or Current Track Changes source
            if use_database_logic and has_db_track:
                # Get database track
                db_result = get_track_from_db(selected_staff)
                if db_result[0]:  # Success
                    track_data = db_result[1]['track_data']
                else:
                    # Fallback to Excel if database access fails
                    track_data = {day: staff_track.iloc[0][day] for day in days}
            elif use_database_logic and not has_db_track:
                # Create empty track if using Annual Rebid logic without existing track
                track_data = {day: "" for day in days}
            else:
                # Extract from Excel file for Current Track Changes mode
                track_data = {day: staff_track.iloc[0][day] for day in days}
            
            # Initialize track changes
            if 'track_changes' not in st.session_state:
                st.session_state.track_changes = {}
            
            # Add preassignments to the track - FIXED: Keep AT as AT, don't convert to D
            track_with_preassignments = track_data.copy()
            if staff_preassignments:
                for day, preassignment in staff_preassignments.items():
                    if day not in track_with_preassignments or not track_with_preassignments[day]:
                        # FIXED: Keep AT as AT for proper validation
                        track_with_preassignments[day] = preassignment
                
            st.session_state.track_changes[selected_staff] = track_with_preassignments
            
            # Initialize modified track
            st.session_state.modified_track = {
                'staff': selected_staff,
                'track': track_with_preassignments.copy(),
                'valid': False,
                'is_new': is_new_track
            }
    
    # Get the modified track
    modified_track = st.session_state.track_changes[selected_staff]

    # Use validation from modification tab if available
    valid = None
    if 'modified_track' in st.session_state and st.session_state.modified_track.get('staff') == selected_staff:
        valid = st.session_state.modified_track.get('valid', None)

    # If not validated yet, or track has changed, re-validate
    if valid is None:
        validation_result = validate_track_with_at(
            modified_track,
            shifts_per_pay_period,
            night_minimum,
            weekend_minimum,
            staff_preassignments
        )
        valid = all(result['status'] for result in validation_result.values())
        st.session_state.modified_track['valid'] = valid
        st.session_state.track_valid = valid
    else:
        # If already validated, create a dummy validation_result for display
        validation_result = {'status': valid}

    # Display validation status
    if valid:
        st.success("✅ Your modified track meets all requirements and is ready to submit.")
    else:
        st.error("❌ Your track has validation issues:")
        # Only show details if we have a real validation_result
        if isinstance(validation_result, dict) and 'pay_period_shifts' in validation_result:
            for check, result in validation_result.items():
                if isinstance(result, dict) and not result.get('status', True):
                    st.write(f"• {result.get('details', '')}")
    
    # Show preassignments if any
    if staff_preassignments:
        display_preassignments(selected_staff, staff_preassignments)

    # Display the track details
    st.subheader("Schedule Details")
    display_track_schedule(modified_track, days, staff_preassignments)
    
    # Show comparison with original track if not a new track
    if not is_new_track and has_db_track:
        # Get database track for comparison
        db_result = get_track_from_db(selected_staff)
        if db_result[0]:  # Success
            original_track = db_result[1]['track_data']
            
            st.subheader("Track Changes")
            display_track_comparison(original_track, modified_track, days)
    elif not is_new_track and not use_database_logic:
        # Compare with Excel track when in Current Track Changes mode and not new
        original_track = {day: staff_track.iloc[0][day] for day in days}
        
        st.subheader("Track Changes")
        display_track_comparison(original_track, modified_track, days)
    
    # NEW ENHANCED BUTTON LOGIC: Show submit button, then show notifications and PDF button
    if valid:
        # Check if track has been submitted (stored in session state)
        track_submitted = st.session_state.get('track_submitted', False)
        
        if not track_submitted:
            # Only show submit button if not yet submitted
            submit_col, spacer_col = st.columns([1, 1])
            
            with submit_col:
                # Submit button text changes based on new vs existing track
                submit_button_text = "Submit New Track" if is_new_track else "Update Track"
                
                if st.button(submit_button_text, use_container_width=True, type="primary", key="submit_track_btn"):
                    with st.spinner("Saving track..."):
                        try:
                            # Prepare track data for saving
                            track_to_save = {}
                            for k, v in modified_track.items():
                                track_to_save[k] = v
                            
                            # FIXED: Keep preassignments as their original values (including AT)
                            for day, preassignment in staff_preassignments.items():
                                if day not in track_to_save or not track_to_save[day]:
                                    track_to_save[day] = preassignment  # Keep AT as AT
                            
                            # UPDATED: Create enhanced track submission data with effective role
                            enhanced_track_data = {
                                'track_data': track_to_save,
                                'staff_metadata': {
                                    'staff_name': selected_staff,
                                    'original_role': staff_role,  # This will now be correct
                                    'effective_role': effective_role,  # This will now be correct
                                    'submission_timestamp': datetime.now(_eastern_tz).isoformat(),
                                    'track_source': 'Annual Rebid' if use_database_logic else 'Current Track Changes',
                                    'is_new_track': is_new_track,
                                    'has_preassignments': bool(staff_preassignments),
                                    'preassignment_count': len(staff_preassignments) if staff_preassignments else 0
                                }
                            }
                            
                            # Save to database with enhanced data
                            success, message, track_id = save_track_to_db_enhanced(
                                selected_staff, 
                                enhanced_track_data, 
                                is_new=is_new_track
                            )
                            
                            if success:
                                # Handle backup
                                backup_result = handle_track_submission(selected_staff, track_to_save)
                                
                                # Show backup status - STORE IN SESSION STATE TO PERSIST
                                if backup_result['backup']['success']:
                                    st.session_state['backup_message'] = ("success", "✅ " + backup_result['backup']['message'])
                                else:
                                    st.session_state['backup_message'] = ("warning", "⚠️ " + backup_result['backup']['message'])
                                
                                # UPDATED: Send email notification
                                try:
                                    # Determine submission type
                                    submission_type = "new" if is_new_track else "update"
                                    
                                    # Send email notification
                                    email_success, email_message = send_track_submission_notification(
                                        selected_staff, 
                                        track_to_save, 
                                        submission_type, 
                                        track_id
                                    )
                                    
                                    if email_success:
                                        st.session_state['email_message'] = ("success", f"📧 Email notification sent successfully to admin")
                                    else:
                                        st.session_state['email_message'] = ("warning", f"📧 Email notification issue: {email_message}")
                                        
                                except ImportError as e:
                                    st.session_state['email_message'] = ("warning", f"📧 Email module not available: {str(e)}")
                                except Exception as e:
                                    st.session_state['email_message'] = ("warning", f"📧 Email notification failed: {str(e)}")
                                    # Don't show full traceback to users, but log it
                                    import traceback
                                    print(f"Email notification error: {traceback.format_exc()}")
                                
                                # Set up PDF data
                                st.session_state['pdf_ready'] = True
                                st.session_state['pdf_data'] = {
                                    'selected_staff': selected_staff,
                                    'modified_track': track_to_save,
                                    'days': days,
                                    'shifts_per_pay_period': shifts_per_pay_period,
                                    'night_minimum': night_minimum,
                                    'weekend_minimum': weekend_minimum,
                                    'preassignments': staff_preassignments
                                }
                                
                                # Mark track as submitted
                                st.session_state['track_submitted'] = True
                                
                                # Store main success message
                                st.session_state['submission_success'] = f"✅ Track submitted successfully for {selected_staff}"
                                
                                # Reset new track flag after submission
                                st.session_state['is_new_track'] = False
                                
                                # Update has_db_track flag
                                st.session_state['has_db_track'] = True
                                
                                # Show balloons effect
                                st.balloons()
                                
                                # Force a rerun to show the results
                                st.rerun()
                                
                            else:
                                st.error(f"❌ Error saving track: {message}")
                        except Exception as e:
                            st.error(f"❌ Error processing submission: {str(e)}")
                            import traceback
                            print(f"Submission error: {traceback.format_exc()}")
            
            with spacer_col:
                # Empty column to maintain layout
                st.empty()
        
        else:
            # Track has been submitted - show persistent notifications and PDF download button
            
            # Display persistent success messages
            if 'submission_success' in st.session_state:
                st.success(st.session_state['submission_success'])
            
            if 'backup_message' in st.session_state:
                msg_type, msg_text = st.session_state['backup_message']
                if msg_type == "success":
                    st.success(msg_text)
                else:
                    st.warning(msg_text)
            
            if 'email_message' in st.session_state:
                msg_type, msg_text = st.session_state['email_message']
                if msg_type == "success":
                    st.success(msg_text)
                else:
                    st.warning(msg_text)
            
            # Show only PDF download button (removed resubmit functionality)
            download_col, spacer_col = st.columns([1, 1])
            
            with download_col:
                # PDF download button
                if st.button("Download Schedule PDF", use_container_width=True, key="download_pdf_btn"):
                    with st.spinner("Generating PDF..."):
                        try:
                            # Use stored data if available, otherwise use current data
                            if 'pdf_data' in st.session_state:
                                pdf_data = st.session_state['pdf_data']
                                pdf_bytes, filename = generate_schedule_pdf(
                                    pdf_data['selected_staff'],
                                    pdf_data['modified_track'],
                                    pdf_data['days'],
                                    pdf_data['shifts_per_pay_period'],
                                    pdf_data['night_minimum'],
                                    pdf_data['weekend_minimum'],
                                    pdf_data.get('preassignments')
                                )
                            else:
                                # Generate PDF with current data
                                track_to_save = {}
                                for k, v in modified_track.items():
                                    track_to_save[k] = v
                                
                                pdf_bytes, filename = generate_schedule_pdf(
                                    selected_staff,
                                    track_to_save,
                                    days,
                                    shifts_per_pay_period,
                                    night_minimum,
                                    weekend_minimum,
                                    staff_preassignments
                                )
                            
                            # Offer PDF download
                            st.download_button(
                                label="Download PDF",
                                data=pdf_bytes,
                                file_name=filename,
                                mime="application/pdf",
                                use_container_width=True,
                                key="download_pdf_btn_actual"
                            )
                        except Exception as e:
                            st.error(f"❌ Error generating PDF: {str(e)}")
            
            with spacer_col:
                # Empty column to maintain layout
                st.empty()

    else:
        st.error("❌ Your track cannot be submitted until all requirements are met.")