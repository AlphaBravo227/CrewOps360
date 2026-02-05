import os
import shutil
import tempfile
import sqlite3
from datetime import datetime
import pytz

_eastern_tz = pytz.timezone('America/New_York')

def validate_uploaded_database(uploaded_file):
    """
    Validate an uploaded database file
    
    Args:
        uploaded_file: Streamlit uploaded file object
        
    Returns:
        dict: Validation result with 'valid', 'tables', and 'error' keys
    """
    try:
        import sqlite3
        import tempfile
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_path = temp_file.name
        
        try:
            # Try to connect and read tables
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()
            
            # Get table information
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            table_info = {}
            for table in tables:
                table_name = table[0]
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    table_info[table_name] = count
                except:
                    table_info[table_name] = "Error reading"
            
            conn.close()
            
            # Check for expected tables
            expected_tables = ['tracks', 'track_history']
            has_expected = any(table in table_info for table in expected_tables)
            
            if not has_expected:
                return {
                    'valid': False,
                    'tables': table_info,
                    'error': f"Database does not contain expected tables: {expected_tables}"
                }
            
            return {
                'valid': True,
                'tables': table_info,
                'error': None
            }
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        return {
            'valid': False,
            'tables': {},
            'error': str(e)
        }
    
def restore_database_from_backup(backup_path):
    """
    Restore the database from a backup file
    
    Args:
        backup_path (str): Path to the backup database file
        
    Returns:
        tuple: (success, message)
    """
    try:
        import shutil
        
        # Paths
        current_db_path = 'data/medflight_tracks.db'
        
        # Create a backup of the current database before replacing
        if os.path.exists(current_db_path):
            timestamp = datetime.now(_eastern_tz).strftime("%Y%m%d_%H%M%S")
            pre_restore_backup = f'backups/pre_restore_backup_{timestamp}.db'
            
            # Ensure backups directory exists
            os.makedirs('backups', exist_ok=True)
            
            shutil.copy2(current_db_path, pre_restore_backup)
        
        # Copy the backup to replace the current database
        shutil.copy2(backup_path, current_db_path)
        
        # Verify the restored database
        import sqlite3
        conn = sqlite3.connect(current_db_path)
        cursor = conn.cursor()
        
        # Test basic connectivity
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        conn.close()
        
        backup_filename = os.path.basename(backup_path)
        return (True, f"Database successfully restored from {backup_filename}. Found {len(tables)} tables.")
        
    except Exception as e:
        return (False, f"Error restoring database: {str(e)}")

def restore_database_from_upload(uploaded_file):
    """
    Restore the database from an uploaded file
    
    Args:
        uploaded_file: Streamlit uploaded file object
        
    Returns:
        tuple: (success, message)
    """
    try:
        import shutil
        import tempfile
        
        # Paths
        current_db_path = 'data/medflight_tracks.db'
        
        # Create a backup of the current database before replacing
        if os.path.exists(current_db_path):
            timestamp = datetime.now(_eastern_tz).strftime("%Y%m%d_%H%M%S")
            pre_restore_backup = f'backups/pre_restore_backup_{timestamp}.db'
            
            # Ensure backups directory exists
            os.makedirs('backups', exist_ok=True)
            
            shutil.copy2(current_db_path, pre_restore_backup)
        
        # Write uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_path = temp_file.name
        
        try:
            # Copy temp file to database location
            shutil.copy2(temp_path, current_db_path)
            
            # Verify the restored database
            import sqlite3
            conn = sqlite3.connect(current_db_path)
            cursor = conn.cursor()
            
            # Test basic connectivity
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            conn.close()
            
            return (True, f"Database successfully restored from {uploaded_file.name}. Found {len(tables)} tables.")
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    except Exception as e:
        return {
            'valid': False,
            'tables': {},
            'error': str(e)
        }

def cleanup_old_backups(old_backup_list):
    """
    Clean up old backup files
    
    Args:
        old_backup_list (list): List of old backup file dictionaries
        
    Returns:
        dict: Cleanup result with 'deleted' count
    """
    deleted_count = 0
    
    try:
        for backup in old_backup_list:
            file_path = backup['Full Path']
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {file_path}: {str(e)}")
                    continue
        
        return {'deleted': deleted_count}
        
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
        return {'deleted': deleted_count}
