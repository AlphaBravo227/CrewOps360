# training_modules/unified_database.py
"""
Enhanced unified database module that includes educator signup functionality
along with existing training enrollment data and track data.
COMPLETELY FIXED VERSION - No more None IDs
"""
import sqlite3
from datetime import datetime
import os
import pytz
from .training_email_notifications import send_training_event_notification

class UnifiedDatabase:
    def __init__(self, db_path, excel_handler=None):
        '''
        Initialize the unified database.
        
        Args:
            db_path: Path to the unified database (data/medflight_tracks.db)
            excel_handler: ExcelHandler instance for accessing class details (optional)
        '''
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.excel_handler = excel_handler  # NEW: Store excel_handler reference
        # Set up Eastern timezone (handles EST/EDT automatically)
        self.eastern_tz = pytz.timezone('America/New_York')
        
    def _get_eastern_time(self):
        """Get current time in Eastern timezone"""
        return datetime.now(self.eastern_tz)
        
    def _format_eastern_timestamp(self, dt):
        """Format datetime for database storage with timezone info"""
        if dt.tzinfo is None:
            # Assume it's Eastern time if no timezone
            dt = self.eastern_tz.localize(dt)
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z')
    def connect(self):
        """Establish database connection with proper row factory and thread safety - FIXED"""
        # Close any existing connection first to ensure clean state
        if self.conn:
            try:
                self.conn.close()
            except:
                pass
        
        # Create new connection with check_same_thread=False for Streamlit compatibility
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # CRITICAL: Always ensure row factory is set for dictionary access
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()        

        
    def disconnect(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            
    def initialize_training_tables(self):
        """Create training-related tables with proper schema - COMPLETELY FIXED"""
        self.connect()
        
        # Create training enrollments table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_enrollments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_name TEXT NOT NULL,
                class_name TEXT NOT NULL,
                class_date TEXT NOT NULL,
                role TEXT DEFAULT 'General',
                meeting_type TEXT DEFAULT NULL,
                session_time TEXT DEFAULT NULL,
                conflict_override BOOLEAN DEFAULT 0,
                conflict_details TEXT DEFAULT NULL,
                override_acknowledged TEXT DEFAULT NULL,
                enrollment_date TEXT DEFAULT NULL,
                status TEXT DEFAULT 'active',
                UNIQUE(staff_name, class_name, class_date, meeting_type, session_time)
            )
        ''')
        
        # Create educator signups table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_educator_signups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_name TEXT NOT NULL,
                class_name TEXT NOT NULL,
                class_date TEXT NOT NULL,
                conflict_override BOOLEAN DEFAULT 0,
                conflict_details TEXT DEFAULT NULL,
                override_acknowledged TEXT DEFAULT NULL,
                signup_date TEXT DEFAULT NULL,
                status TEXT DEFAULT 'active',
                UNIQUE(staff_name, class_name, class_date)
            )
        ''')
        
        # Create training enrollment audit log table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_enrollment_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                staff_name TEXT NOT NULL,
                class_name TEXT NOT NULL,
                class_date TEXT NOT NULL,
                role TEXT,
                meeting_type TEXT,
                session_time TEXT,
                conflict_override BOOLEAN DEFAULT 0,
                conflict_details TEXT,
                action_date TEXT DEFAULT NULL,
                details TEXT
            )
        ''')
        
        # Create educator signup audit log table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_educator_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                staff_name TEXT NOT NULL,
                class_name TEXT NOT NULL,
                class_date TEXT NOT NULL,
                conflict_override BOOLEAN DEFAULT 0,
                conflict_details TEXT,
                action_date TEXT DEFAULT NULL,
                details TEXT
            )
        ''')
        
        self.conn.commit()
        self.disconnect()
        print("Training tables created successfully with proper AUTO INCREMENT")
        
    def migrate_from_separate_database(self, old_db_path):
        """
        Migrate data from the old separate training database to the unified database.
        
        Args:
            old_db_path: Path to the old training/data/enrollment.db
        """
        if not os.path.exists(old_db_path):
            print(f"Old database not found at {old_db_path}, skipping migration")
            return
        
        # Connect to old database
        old_conn = sqlite3.connect(old_db_path)
        old_conn.row_factory = sqlite3.Row
        old_cursor = old_conn.cursor()
        
        # Connect to new unified database
        self.connect()
        
        try:
            # Migrate enrollments
            old_cursor.execute("SELECT * FROM enrollments")
            enrollments = old_cursor.fetchall()
            
            for enrollment in enrollments:
                # Insert into new training_enrollments table
                self.cursor.execute('''
                    INSERT OR IGNORE INTO training_enrollments 
                    (staff_name, class_name, class_date, role, meeting_type, session_time,
                     conflict_override, conflict_details, override_acknowledged, 
                     enrollment_date, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    enrollment['staff_name'],
                    enrollment['class_name'],
                    enrollment['class_date'],
                    enrollment.get('role', 'General'),
                    enrollment.get('meeting_type'),
                    enrollment.get('session_time'),
                    enrollment.get('conflict_override', 0),
                    enrollment.get('conflict_details'),
                    enrollment.get('override_acknowledged'),
                    enrollment.get('enrollment_date'),
                    enrollment.get('status', 'active')
                ))
            
            # Migrate audit log if it exists
            try:
                old_cursor.execute("SELECT * FROM enrollment_audit")
                audit_records = old_cursor.fetchall()
                
                for record in audit_records:
                    self.cursor.execute('''
                        INSERT OR IGNORE INTO training_enrollment_audit 
                        (action, staff_name, class_name, class_date, role, meeting_type, 
                         session_time, conflict_override, conflict_details, action_date, details)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        record['action'],
                        record['staff_name'],
                        record['class_name'],
                        record['class_date'],
                        record.get('role'),
                        record.get('meeting_type'),
                        record.get('session_time'),
                        record.get('conflict_override', 0),
                        record.get('conflict_details'),
                        record.get('action_date'),
                        record.get('details')
                    ))
            except sqlite3.OperationalError:
                print("No audit table found in old database, skipping audit migration")
            
            self.conn.commit()
            print(f"Successfully migrated {len(enrollments)} enrollments from old database")
            
        except Exception as e:
            print(f"Error during migration: {e}")
            self.conn.rollback()
        finally:
            old_conn.close()
            self.disconnect()
    
    # STUDENT ENROLLMENT METHODS - COMPLETELY FIXED
    def add_enrollment(self, staff_name, class_name, class_date, role='General', 
                    meeting_type=None, session_time=None, conflict_override=False, 
                    conflict_details=None):
        """Add a new training enrollment - COMPLETELY FIXED"""
        print(f"DEBUG: add_enrollment called for {staff_name}, {class_name}, {class_date}")
        
        self.connect()
        try:
            # First, check if this exact enrollment already exists
            self.cursor.execute('''
                SELECT id, status FROM training_enrollments 
                WHERE staff_name = ? AND class_name = ? AND class_date = ? 
                AND (meeting_type = ? OR (meeting_type IS NULL AND ? IS NULL))
                AND (session_time = ? OR (session_time IS NULL AND ? IS NULL))
            ''', (staff_name, class_name, class_date, meeting_type, meeting_type, 
                session_time, session_time))
            
            existing = self.cursor.fetchone()
            
            if existing:
                # If it exists but is cancelled, reactivate it
                if existing['status'] == 'cancelled':
                    print(f"DEBUG: Reactivating cancelled enrollment ID {existing['id']}")
                    
                    current_time = self._get_eastern_time()
                    enrollment_timestamp = self._format_eastern_timestamp(current_time)
                    override_timestamp = self._format_eastern_timestamp(current_time) if conflict_override else None
                    
                    self.cursor.execute('''
                        UPDATE training_enrollments 
                        SET status = 'active', role = ?, conflict_override = ?,
                            conflict_details = ?, override_acknowledged = ?, enrollment_date = ?
                        WHERE id = ?
                    ''', (role, conflict_override, conflict_details, 
                        override_timestamp, enrollment_timestamp, existing['id']))
                    
                    self.conn.commit()
                    print(f"DEBUG: Enrollment reactivated successfully")
                    return True
                else:
                    print(f"DEBUG: Enrollment already exists and is active")
                    return False  # Already exists and is active
            
            # No existing enrollment, create new one
            current_time = self._get_eastern_time()
            enrollment_timestamp = self._format_eastern_timestamp(current_time)
            override_timestamp = self._format_eastern_timestamp(current_time) if conflict_override else None
            
            print(f"DEBUG: Inserting new enrollment with timestamp {enrollment_timestamp}")
            
            # Insert with explicit column list (excludes id to allow auto-increment)
            self.cursor.execute('''
                INSERT INTO training_enrollments 
                (staff_name, class_name, class_date, role, meeting_type, session_time,
                 conflict_override, conflict_details, override_acknowledged, enrollment_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            ''', (staff_name, class_name, class_date, role, meeting_type, session_time,
                conflict_override, conflict_details, override_timestamp, enrollment_timestamp))
            
            # Get the auto-generated ID
            inserted_id = self.cursor.lastrowid
            print(f"SUCCESS: Enrollment created with ID: {inserted_id}")
            
            # Add audit entry
            audit_timestamp = self._format_eastern_timestamp(current_time)
            self.cursor.execute('''
                INSERT INTO training_enrollment_audit 
                (action, staff_name, class_name, class_date, role, meeting_type, 
                 session_time, conflict_override, conflict_details, action_date)
                VALUES ('enrolled', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (staff_name, class_name, class_date, role, meeting_type, session_time,
                conflict_override, conflict_details, audit_timestamp))
            
            self.conn.commit()
            print(f"DEBUG: Enrollment inserted and committed successfully")
            
            # Verify the enrollment was added
            self.cursor.execute('''
                SELECT id FROM training_enrollments 
                WHERE staff_name = ? AND class_name = ? AND class_date = ? 
                AND status = 'active'
                ORDER BY id DESC LIMIT 1
            ''', (staff_name, class_name, class_date))
            
            verification = self.cursor.fetchone()
            if verification:
                print(f"DEBUG: Verified enrollment created with ID {verification['id']}")
            else:
                print(f"DEBUG: WARNING - Could not verify enrollment was created")
            
            return True
            
        except sqlite3.IntegrityError as e:
            print(f"DEBUG: IntegrityError - {e}")
            self.conn.rollback()
            return False
        except Exception as e:
            print(f"DEBUG: Unexpected error in add_enrollment - {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
            return False
        finally:
            self.disconnect()
    
    def cancel_enrollment(self, enrollment_id):
        """Cancel a training enrollment"""
        self.connect()
        try:
            # Get enrollment details for audit
            self.cursor.execute('''
                SELECT staff_name, class_name, class_date, role, meeting_type, 
                       session_time, conflict_override, conflict_details
                FROM training_enrollments
                WHERE id = ?
            ''', (enrollment_id,))
            enrollment = self.cursor.fetchone()
            
            if enrollment:
                # Update status
                self.cursor.execute('''
                    UPDATE training_enrollments
                    SET status = 'cancelled'
                    WHERE id = ?
                ''', (enrollment_id,))
                
                # Add audit entry with Eastern timestamp
                current_time = self._get_eastern_time()
                audit_timestamp = self._format_eastern_timestamp(current_time)
                self.cursor.execute('''
                    INSERT INTO training_enrollment_audit 
                    (action, staff_name, class_name, class_date, role, meeting_type, 
                     session_time, conflict_override, conflict_details, action_date)
                    VALUES ('cancelled', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (enrollment['staff_name'], enrollment['class_name'], 
                     enrollment['class_date'], enrollment['role'], 
                     enrollment['meeting_type'], enrollment['session_time'],
                     enrollment['conflict_override'], enrollment['conflict_details'],
                     audit_timestamp))
                
                self.conn.commit()
                return True
            return False
        finally:
            self.disconnect()
    
    # EDUCATOR SIGNUP METHODS - COMPLETELY FIXED
    def add_educator_signup(self, staff_name, class_name, class_date, 
                           conflict_override=False, conflict_details=None):
        """Add a new educator signup - COMPLETELY FIXED"""
        self.connect()
        try:
            current_time = self._get_eastern_time()
            signup_timestamp = self._format_eastern_timestamp(current_time)
            override_timestamp = self._format_eastern_timestamp(current_time) if conflict_override else None
            
            # Insert with explicit column list (excludes id to allow auto-increment)
            self.cursor.execute('''
                INSERT INTO training_educator_signups 
                (staff_name, class_name, class_date, conflict_override, conflict_details, 
                 override_acknowledged, signup_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            ''', (staff_name, class_name, class_date, conflict_override, conflict_details, 
                 override_timestamp, signup_timestamp))
            
            # Get the auto-generated ID
            inserted_id = self.cursor.lastrowid
            print(f"SUCCESS: Educator signup created with ID: {inserted_id}")
            
            # Add audit entry
            audit_timestamp = self._format_eastern_timestamp(current_time)
            self.cursor.execute('''
                INSERT INTO training_educator_audit 
                (action, staff_name, class_name, class_date, conflict_override, 
                 conflict_details, action_date)
                VALUES ('educator_signup', ?, ?, ?, ?, ?, ?)
            ''', (staff_name, class_name, class_date, conflict_override, 
                 conflict_details, audit_timestamp))
            
            self.conn.commit()
            # ===== ADD THIS SECTION: Send email notification =====
            try:
                # Get educator count for this class/date
                if self.excel_handler:
                    class_details = self.excel_handler.get_class_details(class_name)
                    
                    # Get class time
                    start_time = class_details.get('time_1_start')
                    end_time = class_details.get('time_1_end')
                    if start_time and end_time:
                        class_time = f"{start_time} - {end_time}"
                    elif start_time:
                        class_time = f"Starts: {start_time}"
                    else:
                        class_time = "Time not specified"
                    
                    # Get class location for the specific date
                    class_location = "Location not specified"
                    for i in range(1, 15):  # Check rows 1-14 for dates
                        date_key = f'date_{i}'
                        location_key = f'date_{i}_location'
                        
                        if date_key in class_details and class_details[date_key] == class_date:
                            location = class_details.get(location_key, '')
                            class_location = location.strip() if location else "Location not specified"
                            break
                else:
                    class_time = "Time not specified"
                    class_location = "Location not specified"
                
                # Get educator count for this class/date
                educator_signups = self.get_educator_signups_for_class(class_name, class_date)
                total_educators = len(educator_signups) if educator_signups else 0
                
                email_success, email_msg = send_training_event_notification(
                    staff_name=staff_name,
                    class_name=class_name,
                    class_date=class_date,
                    role='Educator',
                    action_type='enrollment',
                    conflict_override=conflict_override,
                    conflict_details=conflict_details,
                    total_enrolled=total_educators,
                    class_time=class_time,
                    class_location=class_location
                )
                
                # Log email result but don't fail signup if email fails
                if not email_success:
                    print(f"Educator signup email notification failed: {email_msg}")
            except Exception as e:
                print(f"Error sending educator signup notification email: {str(e)}")
            # ===== END EMAIL NOTIFICATION =====
            
            return True
            
        except sqlite3.IntegrityError as e:
            print(f"IntegrityError in add_educator_signup: {e}")
            return False
        finally:
            self.disconnect()
    
    def cancel_educator_signup(self, signup_id):
        """Cancel an educator signup"""
        self.connect()
        try:
            # Get signup details for audit
            self.cursor.execute('''
                SELECT staff_name, class_name, class_date, conflict_override, conflict_details
                FROM training_educator_signups
                WHERE id = ?
            ''', (signup_id,))
            signup = self.cursor.fetchone()
            
            if signup:
                # Store details before cancellation
                staff_name = signup['staff_name']
                class_name = signup['class_name']
                class_date = signup['class_date']
                
                # Update status
                self.cursor.execute('''
                    UPDATE training_educator_signups
                    SET status = 'cancelled'
                    WHERE id = ?
                ''', (signup_id,))
                
                # Add audit entry
                current_time = self._get_eastern_time()
                audit_timestamp = self._format_eastern_timestamp(current_time)
                self.cursor.execute('''
                    INSERT INTO training_educator_audit 
                    (action, staff_name, class_name, class_date, conflict_override, 
                    conflict_details, action_date)
                    VALUES ('educator_cancelled', ?, ?, ?, ?, ?, ?)
                ''', (staff_name, class_name, class_date,
                    signup['conflict_override'], signup['conflict_details'], audit_timestamp))
                
                self.conn.commit()
                
                # ===== ADD THIS SECTION: Send email notification =====
                try:
                    # Get remaining educator count for this class/date
                    educator_signups = self.get_educator_signups_for_class(class_name, class_date)
                    total_educators = len(educator_signups) if educator_signups else 0
                    
                    email_success, email_msg = send_training_event_notification(
                        staff_name=staff_name,
                        class_name=class_name,
                        class_date=class_date,
                        role='Educator',
                        action_type='cancellation',
                        conflict_override=False,
                        conflict_details=None,
                        total_enrolled=total_educators
                    )
                    
                    # Log email result but don't fail cancellation if email fails
                    if not email_success:
                        print(f"Educator cancellation email notification failed: {email_msg}")
                except Exception as e:
                    print(f"Error sending educator cancellation notification email: {str(e)}")
                # ===== END OF NEW SECTION =====
                
                return True
            return False
        finally:
            self.disconnect()

    def get_educator_signups_for_class(self, class_name, class_date=None):
        """Get all educator signups for a class - FIXED"""
        self.connect()
        if class_date:
            self.cursor.execute('''
                SELECT id, staff_name, class_name, class_date, conflict_override,
                       conflict_details, signup_date, status
                FROM training_educator_signups
                WHERE class_name = ? AND class_date = ? AND status = 'active'
                ORDER BY signup_date
            ''', (class_name, class_date))
        else:
            self.cursor.execute('''
                SELECT id, staff_name, class_name, class_date, conflict_override,
                       conflict_details, signup_date, status
                FROM training_educator_signups
                WHERE class_name = ? AND status = 'active'
                ORDER BY class_date, signup_date
            ''', (class_name,))
        
        rows = self.cursor.fetchall()
        signups = []
        for row in rows:
            signups.append({
                'id': row['id'],
                'staff_name': row['staff_name'],
                'class_name': row['class_name'],
                'class_date': row['class_date'],
                'conflict_override': row['conflict_override'],
                'conflict_details': row['conflict_details'],
                'signup_date': row['signup_date'],
                'status': row['status']
            })
        
        self.disconnect()
        return signups
    
    def get_educator_signup_count(self, class_name, class_date):
        """Get count of educator signups for a specific class and date"""
        self.connect()
        self.cursor.execute('''
            SELECT COUNT(*) as count FROM training_educator_signups
            WHERE class_name = ? AND class_date = ? AND status = 'active'
        ''', (class_name, class_date))
        count = self.cursor.fetchone()['count']
        self.disconnect()
        return count
    
    def check_existing_educator_signup(self, staff_name, class_name, class_date):
        """Check if staff member already signed up as educator - COMPLETELY FIXED"""
        self.connect()
        self.cursor.execute('''
            SELECT id, staff_name, class_name, class_date, status
            FROM training_educator_signups
            WHERE staff_name = ? AND class_name = ? AND class_date = ? AND status = 'active'
        ''', (staff_name, class_name, class_date))
        
        signup = self.cursor.fetchone()
        if signup:
            result = {
                'id': signup['id'],
                'staff_name': signup['staff_name'],
                'class_name': signup['class_name'],
                'class_date': signup['class_date'],
                'status': signup['status']
            }
            self.disconnect()
            return result
        
        self.disconnect()
        return None
    
    # EXISTING ENROLLMENT METHODS - FIXED

    def get_staff_enrollments(self, staff_name):
        """Get all training enrollments for a staff member - FIXED connection management"""
        self.connect()
        
        try:
            # Explicit column selection
            self.cursor.execute('''
                SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                    session_time, conflict_override, conflict_details, 
                    override_acknowledged, enrollment_date, status
                FROM training_enrollments
                WHERE staff_name = ? AND status = 'active'
                ORDER BY class_date
            ''', (staff_name,))
            
            rows = self.cursor.fetchall()
            enrollments = []
            
            for row in rows:
                # Explicit dictionary creation
                enrollment_dict = {
                    'id': row['id'],
                    'staff_name': row['staff_name'],
                    'class_name': row['class_name'],
                    'class_date': row['class_date'],
                    'role': row['role'],
                    'meeting_type': row['meeting_type'],
                    'session_time': row['session_time'],
                    'conflict_override': row['conflict_override'],
                    'conflict_details': row['conflict_details'],
                    'override_acknowledged': row['override_acknowledged'],
                    'enrollment_date': row['enrollment_date'],
                    'status': row['status']
                }
                
                # Convert timestamps for display
                if enrollment_dict.get('enrollment_date'):
                    enrollment_dict['enrollment_date_display'] = self._parse_and_format_timestamp(
                        enrollment_dict['enrollment_date']
                    )
                if enrollment_dict.get('override_acknowledged'):
                    enrollment_dict['override_acknowledged_display'] = self._parse_and_format_timestamp(
                        enrollment_dict['override_acknowledged']
                    )
                
                enrollments.append(enrollment_dict)
            
            return enrollments
            
        finally:
            self.disconnect()

    def get_class_enrollments(self, class_name, class_date=None):
        """Get all training enrollments for a class"""
        self.connect()
        if class_date:
            self.cursor.execute('''
                SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                       session_time, conflict_override, conflict_details, status
                FROM training_enrollments
                WHERE class_name = ? AND class_date = ? AND status = 'active'
            ''', (class_name, class_date))
        else:
            self.cursor.execute('''
                SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                       session_time, conflict_override, conflict_details, status
                FROM training_enrollments
                WHERE class_name = ? AND status = 'active'
            ''', (class_name,))
            
        rows = self.cursor.fetchall()
        enrollments = []
        for row in rows:
            enrollments.append({
                'id': row['id'],
                'staff_name': row['staff_name'],
                'class_name': row['class_name'],
                'class_date': row['class_date'],
                'role': row['role'],
                'meeting_type': row['meeting_type'],
                'session_time': row['session_time'],
                'conflict_override': row['conflict_override'],
                'conflict_details': row['conflict_details'],
                'status': row['status']
            })
        
        self.disconnect()
        return enrollments
        
    def get_enrollment_count(self, class_name, class_date, role=None, meeting_type=None, session_time=None):
        """Get enrollment count for a specific class, date, and optional filters"""
        self.connect()
        
        query = '''
            SELECT COUNT(*) as count FROM training_enrollments
            WHERE class_name = ? AND class_date = ? AND status = 'active'
        '''
        params = [class_name, class_date]
        
        if role and role != 'General':
            query += ' AND role = ?'
            params.append(role)
            
        if meeting_type:
            query += ' AND meeting_type = ?'
            params.append(meeting_type)
            
        if session_time:
            query += ' AND session_time = ?'
            params.append(session_time)
            
        self.cursor.execute(query, params)
        count = self.cursor.fetchone()['count']
        self.disconnect()
        return count
        
    def get_session_enrollments(self, class_name, class_date, session_time=None, meeting_type=None):
        """Get all enrollments for a specific training session"""
        self.connect()
        
        query = '''
            SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                   session_time, conflict_override
            FROM training_enrollments
            WHERE class_name = ? AND class_date = ? AND status = 'active'
        '''
        params = [class_name, class_date]
        
        if session_time:
            query += ' AND session_time = ?'
            params.append(session_time)
        else:
            query += ' AND (session_time IS NULL OR session_time = "")'
            
        if meeting_type:
            query += ' AND meeting_type = ?'
            params.append(meeting_type)
        elif meeting_type is None:
            query += ' AND (meeting_type IS NULL OR meeting_type = "")'
            
        self.cursor.execute(query, params)
        rows = self.cursor.fetchall()
        enrollments = []
        for row in rows:
            enrollments.append({
                'id': row['id'],
                'staff_name': row['staff_name'],
                'class_name': row['class_name'],
                'class_date': row['class_date'],
                'role': row['role'],
                'meeting_type': row['meeting_type'],
                'session_time': row['session_time'],
                'conflict_override': row['conflict_override']
            })
        
        self.disconnect()
        return enrollments
        
    def _parse_and_format_timestamp(self, timestamp_str):
        """Parse stored timestamp and format for display"""
        if not timestamp_str:
            return None
            
        try:
            # If it already has timezone info, parse it
            if 'EST' in timestamp_str or 'EDT' in timestamp_str:
                # Remove timezone abbreviation and parse
                clean_timestamp = timestamp_str.replace(' EST', '').replace(' EDT', '')
                dt = datetime.strptime(clean_timestamp, '%Y-%m-%d %H:%M:%S')
                # Localize to Eastern time
                eastern_dt = self.eastern_tz.localize(dt)
            else:
                # Old format without timezone, assume Eastern
                dt = datetime.fromisoformat(timestamp_str.replace(' ', 'T'))
                eastern_dt = self.eastern_tz.localize(dt)
            
            # Format for display
            return eastern_dt.strftime('%m/%d/%Y %I:%M %p %Z')
            
        except Exception as e:
            print(f"Warning: Could not parse timestamp {timestamp_str}: {e}")
            return timestamp_str  # Return original if parsing fails
            
    def get_enrollment_stats(self):
        """Get training enrollment statistics with Eastern time info"""
        self.connect()
        
        # Get total enrollments
        self.cursor.execute("SELECT COUNT(*) as total FROM training_enrollments WHERE status = 'active'")
        total_enrollments = self.cursor.fetchone()['total']
        
        # Get total educator signups
        self.cursor.execute("SELECT COUNT(*) as total FROM training_educator_signups WHERE status = 'active'")
        total_educator_signups = self.cursor.fetchone()['total']
        
        # Get conflicts count
        self.cursor.execute("SELECT COUNT(*) as conflicts FROM training_enrollments WHERE conflict_override = 1 AND status = 'active'")
        enrollment_conflicts = self.cursor.fetchone()['conflicts']
        
        # Get educator conflicts count
        self.cursor.execute("SELECT COUNT(*) as conflicts FROM training_educator_signups WHERE conflict_override = 1 AND status = 'active'")
        educator_conflicts = self.cursor.fetchone()['conflicts']
        
        # Get recent enrollments (last 24 hours Eastern time)
        current_time = self._get_eastern_time()
        yesterday = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_str = self._format_eastern_timestamp(yesterday)
        
        self.cursor.execute('''
            SELECT COUNT(*) as recent FROM training_enrollments 
            WHERE status = 'active' AND enrollment_date >= ?
        ''', (yesterday_str,))
        recent_enrollments = self.cursor.fetchone()['recent']
        
        # Get recent educator signups
        self.cursor.execute('''
            SELECT COUNT(*) as recent FROM training_educator_signups 
            WHERE status = 'active' AND signup_date >= ?
        ''', (yesterday_str,))
        recent_educator_signups = self.cursor.fetchone()['recent']
        
        self.disconnect()
        
        return {
            'total_enrollments': total_enrollments,
            'total_educator_signups': total_educator_signups,
            'enrollment_conflicts': enrollment_conflicts,
            'educator_conflicts': educator_conflicts,
            'total_conflicts': enrollment_conflicts + educator_conflicts,
            'recent_enrollments': recent_enrollments,
            'recent_educator_signups': recent_educator_signups,
            'current_time_eastern': current_time.strftime('%m/%d/%Y %I:%M %p %Z')
        }

    def get_live_staff_meeting_count(self, staff_name):
        """Get count of LIVE staff meetings for a staff member - FIXED"""
        self.connect()
        try:
            self.cursor.execute('''
                SELECT COUNT(*) as count FROM training_enrollments
                WHERE staff_name = ? AND meeting_type = 'LIVE' AND status = 'active'
            ''', (staff_name,))
            count = self.cursor.fetchone()['count']
            return count
        finally:
            self.disconnect()

    def get_conflict_override_enrollments(self, staff_name=None):
        """Get all training enrollments with conflict overrides - FIXED"""
        self.connect()
        
        try:
            if staff_name:
                self.cursor.execute('''
                    SELECT id, staff_name, class_name, class_date, role, meeting_type,
                        conflict_override, conflict_details, override_acknowledged
                    FROM training_enrollments
                    WHERE staff_name = ? AND conflict_override = 1 AND status = 'active'
                    ORDER BY class_date
                ''', (staff_name,))
            else:
                self.cursor.execute('''
                    SELECT id, staff_name, class_name, class_date, role, meeting_type,
                        conflict_override, conflict_details, override_acknowledged
                    FROM training_enrollments
                    WHERE conflict_override = 1 AND status = 'active'
                    ORDER BY staff_name, class_date
                ''')
                
            rows = self.cursor.fetchall()
            enrollments = []
            for row in rows:
                enrollment_dict = {
                    'id': row['id'],
                    'staff_name': row['staff_name'],
                    'class_name': row['class_name'],
                    'class_date': row['class_date'],
                    'role': row['role'],
                    'meeting_type': row['meeting_type'],
                    'conflict_override': row['conflict_override'],
                    'conflict_details': row['conflict_details'],
                    'override_acknowledged': row['override_acknowledged']
                }
                
                if enrollment_dict.get('override_acknowledged'):
                    enrollment_dict['override_acknowledged_display'] = self._parse_and_format_timestamp(
                        enrollment_dict['override_acknowledged']
                    )
                
                enrollments.append(enrollment_dict)
            
            return enrollments
        finally:
            self.disconnect()

    def get_conflict_override_educator_signups(self, staff_name=None):
        """Get all educator signups with conflict overrides - FIXED"""
        self.connect()
        
        try:
            if staff_name:
                self.cursor.execute('''
                    SELECT id, staff_name, class_name, class_date, conflict_override,
                        conflict_details, override_acknowledged
                    FROM training_educator_signups
                    WHERE staff_name = ? AND conflict_override = 1 AND status = 'active'
                    ORDER BY class_date
                ''', (staff_name,))
            else:
                self.cursor.execute('''
                    SELECT id, staff_name, class_name, class_date, conflict_override,
                        conflict_details, override_acknowledged
                    FROM training_educator_signups
                    WHERE conflict_override = 1 AND status = 'active'
                    ORDER BY staff_name, class_date
                ''')
                
            rows = self.cursor.fetchall()
            signups = []
            for row in rows:
                signup_dict = {
                    'id': row['id'],
                    'staff_name': row['staff_name'],
                    'class_name': row['class_name'],
                    'class_date': row['class_date'],
                    'conflict_override': row['conflict_override'],
                    'conflict_details': row['conflict_details'],
                    'override_acknowledged': row['override_acknowledged']
                }
                
                if signup_dict.get('override_acknowledged'):
                    signup_dict['override_acknowledged_display'] = self._parse_and_format_timestamp(
                        signup_dict['override_acknowledged']
                    )
                
                signups.append(signup_dict)
            
            return signups
        finally:
            self.disconnect()

    def get_staff_educator_signups(self, staff_name):
        """Get all educator signups for a staff member - FIXED"""
        self.connect()
        
        try:
            # Explicit column selection ensures proper ordering
            self.cursor.execute('''
                SELECT id, staff_name, class_name, class_date, conflict_override, 
                    conflict_details, override_acknowledged, signup_date, status
                FROM training_educator_signups
                WHERE staff_name = ? AND status = 'active'
                ORDER BY class_date
            ''', (staff_name,))
            
            rows = self.cursor.fetchall()
            signups = []
            
            for row in rows:
                # Explicit dictionary creation to ensure all fields are captured
                signup_dict = {
                    'id': row['id'],
                    'staff_name': row['staff_name'],
                    'class_name': row['class_name'],
                    'class_date': row['class_date'],
                    'conflict_override': row['conflict_override'],
                    'conflict_details': row['conflict_details'],
                    'override_acknowledged': row['override_acknowledged'],
                    'signup_date': row['signup_date'],
                    'status': row['status']
                }
                
                # Convert timestamps for display
                if signup_dict.get('signup_date'):
                    signup_dict['signup_date_display'] = self._parse_and_format_timestamp(
                        signup_dict['signup_date']
                    )
                if signup_dict.get('override_acknowledged'):
                    signup_dict['override_acknowledged_display'] = self._parse_and_format_timestamp(
                        signup_dict['override_acknowledged']
                    )
                
                signups.append(signup_dict)
            
            return signups
        finally:
            self.disconnect()