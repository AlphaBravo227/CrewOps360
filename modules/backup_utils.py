"""
Module for handling track submission backups
"""

import os
import shutil
from datetime import datetime

def create_backup(staff_name):
    """
    Create a backup of the SQLite database
    
    Args:
        staff_name (str): Name of the staff member who submitted the track
    """
    try:
        # Source database file
        db_source = 'data/medflight_tracks.db'
        
        # Check if database file exists
        if not os.path.exists(db_source):
            return False, "Database file not found. Please ensure the database is initialized."
        
        # Create backups directory if it doesn't exist
        os.makedirs('backups', exist_ok=True)
        
        # Create timestamp for backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create backup filename
        backup_filename = f"backups/medflight_tracks_{timestamp}.db"
        
        # Copy the database file
        shutil.copy2(db_source, backup_filename)
            
        return True, "Database backup created successfully"
    except Exception as e:
        return False, f"Error creating database backup: {str(e)}"

def handle_track_submission(staff_name, track_data):
    """
    Handle backup for a track submission
    
    Args:
        staff_name (str): Name of the staff member
        track_data (dict): The track data that was submitted
    """
    # Create backup
    backup_success, backup_message = create_backup(staff_name)
    
    return {
        'backup': {'success': backup_success, 'message': backup_message}
    } 