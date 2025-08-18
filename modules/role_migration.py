# modules/role_migration.py
"""
Role Data Migration Script
Populates missing role metadata for existing tracks in the database
"""

import sqlite3
import pandas as pd
import json
import streamlit as st
import os
from datetime import datetime
from .db_utils import initialize_database, get_db_connection

def get_effective_role(staff_role):
    """
    Get the effective role for staffing purposes
    
    Args:
        staff_role (str): Original staff role (nurse, medic, dual)
        
    Returns:
        str: Effective role (nurse or medic)
    """
    if staff_role == "dual":
        return "nurse"  # Dual providers are treated as nurses
    elif staff_role == "medic":
        return "medic"
    else:  # "nurse" or any other role
        return "nurse"

def detect_track_source(track_data, submission_date):
    """
    Attempt to detect track source based on submission patterns
    
    Args:
        track_data (dict): Track data
        submission_date (str): Submission date
        
    Returns:
        str: Likely track source
    """
    # This is a best guess - you can adjust logic based on your patterns
    # For now, we'll default to "Current Track Changes" for existing data
    # since Annual Rebid mode is newer
    
    # Check if track has many empty days (might indicate Annual Rebid)
    if track_data:
        total_days = len(track_data)
        assigned_days = sum(1 for assignment in track_data.values() if assignment in ["D", "N", "AT"])
        
        # If very few assigned days, might be Annual Rebid
        if total_days > 0 and (assigned_days / total_days) < 0.3:
            return "Annual Rebid"
    
    # Default to Current Track Changes for existing data
    return "Current Track Changes"

def count_preassignments_in_track(track_data):
    """
    Count AT preassignments in track data
    
    Args:
        track_data (dict): Track data
        
    Returns:
        tuple: (has_preassignments_bool, preassignment_count)
    """
    if not track_data:
        return False, 0
    
    at_count = sum(1 for assignment in track_data.values() if assignment == "AT")
    return at_count > 0, at_count

def migrate_role_data(preferences_df, staff_col_prefs, role_col, dry_run=True):
    """
    Migrate role data for existing tracks
    
    Args:
        preferences_df (DataFrame): Staff preferences data
        staff_col_prefs (str): Column name for staff in preferences
        role_col (str): Column name for role in preferences
        dry_run (bool): If True, only show what would be updated without actually updating
        
    Returns:
        dict: Migration results
    """
    results = {
        'total_tracks': 0,
        'updated_tracks': 0,
        'staff_not_found': [],
        'updates': [],
        'errors': []
    }
    
    try:
        # Initialize database
        initialize_database()
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Find tracks that need role data migration
        cursor.execute("""
            SELECT id, staff_name, track_data, submission_date, original_role, effective_role, track_source
            FROM tracks 
            WHERE original_role IS NULL OR effective_role IS NULL OR track_source IS NULL
            ORDER BY staff_name, submission_date
        """)
        
        tracks_to_update = cursor.fetchall()
        results['total_tracks'] = len(tracks_to_update)
        
        if results['total_tracks'] == 0:
            results['message'] = "No tracks found that need role data migration."
            return results
        
        # Process each track
        for track_id, staff_name, track_json, submission_date, current_original_role, current_effective_role, current_track_source in tracks_to_update:
            try:
                # Parse track data for preassignment analysis
                try:
                    track_data = json.loads(track_json) if track_json else {}
                except json.JSONDecodeError:
                    track_data = {}
                
                # Look up staff in preferences
                staff_info = preferences_df[preferences_df[staff_col_prefs] == staff_name]
                
                if staff_info.empty:
                    results['staff_not_found'].append(staff_name)
                    continue
                
                # Get staff role
                staff_role = staff_info.iloc[0][role_col]
                effective_role = get_effective_role(staff_role)
                
                # Detect track source if missing
                if current_track_source is None:
                    track_source = detect_track_source(track_data, submission_date)
                else:
                    track_source = current_track_source
                
                # Count preassignments
                has_preassignments, preassignment_count = count_preassignments_in_track(track_data)
                
                # Prepare update data
                update_data = {
                    'track_id': track_id,
                    'staff_name': staff_name,
                    'original_role': current_original_role or staff_role,
                    'effective_role': current_effective_role or effective_role,
                    'track_source': track_source,
                    'has_preassignments': has_preassignments,
                    'preassignment_count': preassignment_count
                }
                
                results['updates'].append(update_data)
                
                # Perform update if not dry run
                if not dry_run:
                    cursor.execute("""
                        UPDATE tracks SET 
                            original_role = ?,
                            effective_role = ?,
                            track_source = ?,
                            has_preassignments = ?,
                            preassignment_count = ?
                        WHERE id = ?
                    """, (
                        update_data['original_role'],
                        update_data['effective_role'],
                        update_data['track_source'],
                        1 if update_data['has_preassignments'] else 0,
                        update_data['preassignment_count'],
                        track_id
                    ))
                
                results['updated_tracks'] += 1
                
            except Exception as e:
                results['errors'].append(f"Error processing track {track_id} for {staff_name}: {str(e)}")
                continue
        
        # Commit changes if not dry run
        if not dry_run:
            conn.commit()
            results['message'] = f"Successfully migrated role data for {results['updated_tracks']} tracks."
        else:
            results['message'] = f"Dry run complete. Would update {results['updated_tracks']} tracks."
        
        return results
        
    except Exception as e:
        results['errors'].append(f"Migration error: {str(e)}")
        results['message'] = "Migration failed due to errors."
        return results

def display_migration_interface():
    """
    Display the migration interface in Streamlit
    """
    st.header("🔄 Role Data Migration")
    
    st.markdown("""
    This tool will populate missing role metadata for existing tracks in your database.
    
    **What it does:**
    - Looks up staff roles from the current preferences file
    - Sets original_role from preferences (nurse, medic, dual)
    - Sets effective_role (dual → nurse conversion)
    - Estimates track_source based on submission patterns
    - Counts AT preassignments in existing tracks
    """)
    
    # Check if we have the required data
    if 'preferences_df' not in st.session_state or st.session_state.preferences_df is None:
        st.error("❌ Preferences file not loaded. Please load the preferences file first.")
        return
    
    if 'staff_col_prefs' not in st.session_state or 'role_col' not in st.session_state:
        st.error("❌ Column mappings not detected. Please ensure the preferences file is properly loaded.")
        return
    
    preferences_df = st.session_state.preferences_df
    staff_col_prefs = st.session_state.staff_col_prefs
    role_col = st.session_state.role_col
    
    st.success("✅ Prerequisites met. Ready to migrate role data.")
    
    # Migration options
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🔍 Step 1: Preview Migration")
        if st.button("Preview Migration (Dry Run)", use_container_width=True, type="secondary"):
            with st.spinner("Analyzing tracks that need migration..."):
                results = migrate_role_data(preferences_df, staff_col_prefs, role_col, dry_run=True)
                
                st.markdown("#### Migration Preview Results")
                
                # Display summary
                preview_cols = st.columns(3)
                preview_cols[0].metric("Tracks to Update", results['updated_tracks'])
                preview_cols[1].metric("Total Tracks Checked", results['total_tracks'])
                preview_cols[2].metric("Staff Not Found", len(results['staff_not_found']))
                
                # Show what would be updated
                if results['updates']:
                    st.markdown("#### Tracks That Would Be Updated:")
                    
                    update_data = []
                    for update in results['updates'][:10]:  # Show first 10
                        update_data.append({
                            "Staff Name": update['staff_name'],
                            "Original Role": update['original_role'],
                            "Effective Role": update['effective_role'],
                            "Track Source": update['track_source'],
                            "Has Preassignments": "Yes" if update['has_preassignments'] else "No",
                            "Preassignment Count": update['preassignment_count']
                        })
                    
                    update_df = pd.DataFrame(update_data)
                    st.dataframe(update_df, use_container_width=True)
                    
                    if len(results['updates']) > 10:
                        st.info(f"Showing first 10 of {len(results['updates'])} tracks to be updated.")
                
                # Show staff not found
                if results['staff_not_found']:
                    st.warning(f"⚠️ Staff not found in preferences file: {', '.join(set(results['staff_not_found']))}")
                
                # Show errors
                if results['errors']:
                    st.error("❌ Errors encountered:")
                    for error in results['errors']:
                        st.error(f"• {error}")
                
                st.info(results['message'])
    
    with col2:
        st.markdown("### ⚡ Step 2: Execute Migration")
        
        st.warning("""
        **⚠️ Important:**
        - This will modify your database
        - Consider backing up your database first
        - Review the preview results before proceeding
        """)
        
        if st.button("🚀 Execute Migration", use_container_width=True, type="primary"):
            # Double confirmation
            if st.checkbox("I understand this will modify the database"):
                with st.spinner("Migrating role data..."):
                    results = migrate_role_data(preferences_df, staff_col_prefs, role_col, dry_run=False)
                    
                    st.markdown("#### Migration Results")
                    
                    # Display summary
                    result_cols = st.columns(3)
                    result_cols[0].metric("Tracks Updated", results['updated_tracks'])
                    result_cols[1].metric("Total Tracks Checked", results['total_tracks'])
                    result_cols[2].metric("Staff Not Found", len(results['staff_not_found']))
                    
                    if results['updated_tracks'] > 0:
                        st.success(f"✅ {results['message']}")
                        
                        # Show role distribution after migration
                        try:
                            from .db_utils import get_role_distribution_stats
                            role_stats = get_role_distribution_stats()
                            
                            if role_stats['total_tracks'] > 0:
                                st.markdown("#### Updated Role Distribution:")
                                
                                dist_cols = st.columns(2)
                                
                                with dist_cols[0]:
                                    st.markdown("**Effective Roles:**")
                                    for role, count in role_stats['by_effective_role'].items():
                                        percentage = (count / role_stats['total_tracks'] * 100)
                                        st.metric(role.title(), f"{count} ({percentage:.1f}%)")
                                
                                with dist_cols[1]:
                                    st.markdown("**Track Sources:**")
                                    for source, count in role_stats['by_track_source'].items():
                                        percentage = (count / role_stats['total_tracks'] * 100)
                                        st.metric(source, f"{count} ({percentage:.1f}%)")
                                        
                        except Exception as e:
                            st.warning(f"Could not load updated statistics: {str(e)}")
                    
                    else:
                        st.info(results['message'])
                    
                    # Show staff not found
                    if results['staff_not_found']:
                        st.warning("⚠️ Staff members not found in preferences file:")
                        unique_not_found = list(set(results['staff_not_found']))
                        for staff in unique_not_found:
                            st.warning(f"• {staff}")
                        st.info("These tracks were skipped. You may need to update preferences file or manually set role data.")
                    
                    # Show errors
                    if results['errors']:
                        st.error("❌ Errors encountered during migration:")
                        for error in results['errors']:
                            st.error(f"• {error}")
            else:
                st.info("Please check the confirmation box to proceed with migration.")

def create_backup_before_migration():
    """
    Create a backup of the database before migration
    
    Returns:
        tuple: (success, backup_path_or_error_message)
    """
    try:
        import shutil
        
        db_path = 'data/medflight_tracks.db'
        if not os.path.exists(db_path):
            return False, "Database file not found"
        
        # Create backup with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f'data/medflight_tracks_backup_before_migration_{timestamp}.db'
        
        shutil.copy2(db_path, backup_path)
        return True, backup_path
        
    except Exception as e:
        return False, f"Error creating backup: {str(e)}"