# training_modules/unified_database.py
"""
Complete unified database module that consolidates both training enrollment data
and track data into a single medflight_tracks.db database.
"""
import sqlite3
from datetime import datetime
import os
import pytz

class UnifiedDatabase:
    def __init__(self, db_path):
        """
        Initialize the unified database.
        
        Args:
            db_path: Path to the unified database (data/medflight_tracks.db)
        """
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.conn = None
        self.cursor = None
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
        """Establish database connection"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        
    def disconnect(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            
    def initialize_training_tables(self):
        """Create training-related tables in the unified database"""
        self.connect()
        
        # Create training enrollments table with conflict override fields
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
        
        # Check if conflict fields exist in existing table (for migration)
        self.cursor.execute("PRAGMA table_info(training_enrollments)")
        columns = [column[1] for column in self.cursor.fetchall()]
        
        # Add new columns if they don't exist
        if 'session_time' not in columns:
            self.cursor.execute('ALTER TABLE training_enrollments ADD COLUMN session_time TEXT DEFAULT NULL')
            
        if 'conflict_override' not in columns:
            self.cursor.execute('ALTER TABLE training_enrollments ADD COLUMN conflict_override BOOLEAN DEFAULT 0')
            
        if 'conflict_details' not in columns:
            self.cursor.execute('ALTER TABLE training_enrollments ADD COLUMN conflict_details TEXT DEFAULT NULL')
            
        if 'override_acknowledged' not in columns:
            self.cursor.execute('ALTER TABLE training_enrollments ADD COLUMN override_acknowledged TEXT DEFAULT NULL')
        
        # Create training audit log table with conflict tracking
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
        
        # Check if conflict fields exist in audit table
        self.cursor.execute("PRAGMA table_info(training_enrollment_audit)")
        audit_columns = [column[1] for column in self.cursor.fetchall()]
        
        if 'session_time' not in audit_columns:
            self.cursor.execute('ALTER TABLE training_enrollment_audit ADD COLUMN session_time TEXT DEFAULT NULL')
            
        if 'conflict_override' not in audit_columns:
            self.cursor.execute('ALTER TABLE training_enrollment_audit ADD COLUMN conflict_override BOOLEAN DEFAULT 0')
            
        if 'conflict_details' not in audit_columns:
            self.cursor.execute('ALTER TABLE training_enrollment_audit ADD COLUMN conflict_details TEXT DEFAULT NULL')
        
        self.conn.commit()
        self.disconnect()
        
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
            
    def add_enrollment(self, staff_name, class_name, class_date, role='General', 
                      meeting_type=None, session_time=None, conflict_override=False, 
                      conflict_details=None):
        """Add a new training enrollment with optional conflict override"""
        self.connect()
        try:
            current_time = self._get_eastern_time()
            enrollment_timestamp = self._format_eastern_timestamp(current_time)
            override_timestamp = self._format_eastern_timestamp(current_time) if conflict_override else None
            
            self.cursor.execute('''
                INSERT INTO training_enrollments (staff_name, class_name, class_date, role, 
                                               meeting_type, session_time, conflict_override, 
                                               conflict_details, override_acknowledged, enrollment_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (staff_name, class_name, class_date, role, meeting_type, session_time,
                 conflict_override, conflict_details, override_timestamp, enrollment_timestamp))
            
            # Add audit entry
            audit_timestamp = self._format_eastern_timestamp(current_time)
            self.cursor.execute('''
                INSERT INTO training_enrollment_audit (action, staff_name, class_name, class_date, 
                                                    role, meeting_type, session_time, 
                                                    conflict_override, conflict_details, action_date)
                VALUES ('enrolled', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (staff_name, class_name, class_date, role, meeting_type, session_time,
                 conflict_override, conflict_details, audit_timestamp))
            
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
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
                    INSERT INTO training_enrollment_audit (action, staff_name, class_name, class_date, 
                                                        role, meeting_type, session_time, 
                                                        conflict_override, conflict_details, action_date)
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
            
    def get_staff_enrollments(self, staff_name):
        """Get all training enrollments for a staff member"""
        self.connect()
        self.cursor.execute('''
            SELECT * FROM training_enrollments
            WHERE staff_name = ? AND status = 'active'
            ORDER BY class_date
        ''', (staff_name,))
        enrollments = [dict(row) for row in self.cursor.fetchall()]
        self.disconnect()
        
        # Convert timestamps to Eastern time for display
        for enrollment in enrollments:
            if enrollment.get('enrollment_date'):
                enrollment['enrollment_date_display'] = self._parse_and_format_timestamp(
                    enrollment['enrollment_date']
                )
            if enrollment.get('override_acknowledged'):
                enrollment['override_acknowledged_display'] = self._parse_and_format_timestamp(
                    enrollment['override_acknowledged']
                )
        
        return enrollments
        
    def get_class_enrollments(self, class_name, class_date=None):
        """Get all training enrollments for a class"""
        self.connect()
        if class_date:
            self.cursor.execute('''
                SELECT * FROM training_enrollments
                WHERE class_name = ? AND class_date = ? AND status = 'active'
            ''', (class_name, class_date))
        else:
            self.cursor.execute('''
                SELECT * FROM training_enrollments
                WHERE class_name = ? AND status = 'active'
            ''', (class_name,))
        enrollments = [dict(row) for row in self.cursor.fetchall()]
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
            SELECT * FROM training_enrollments
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
        enrollments = [dict(row) for row in self.cursor.fetchall()]
        self.disconnect()
        return enrollments
        
    def get_live_staff_meeting_count(self, staff_name):
        """Get count of LIVE staff meetings for a staff member"""
        self.connect()
        self.cursor.execute('''
            SELECT COUNT(*) as count FROM training_enrollments
            WHERE staff_name = ? AND meeting_type = 'LIVE' AND status = 'active'
        ''', (staff_name,))
        count = self.cursor.fetchone()['count']
        self.disconnect()
        return count
        
    def get_conflict_override_enrollments(self, staff_name=None):
        """Get all training enrollments with conflict overrides"""
        self.connect()
        
        if staff_name:
            self.cursor.execute('''
                SELECT * FROM training_enrollments
                WHERE staff_name = ? AND conflict_override = 1 AND status = 'active'
                ORDER BY class_date
            ''', (staff_name,))
        else:
            self.cursor.execute('''
                SELECT * FROM training_enrollments
                WHERE conflict_override = 1 AND status = 'active'
                ORDER BY staff_name, class_date
            ''')
            
        enrollments = [dict(row) for row in self.cursor.fetchall()]
        self.disconnect()
        
        # Add display timestamps
        for enrollment in enrollments:
            if enrollment.get('override_acknowledged'):
                enrollment['override_acknowledged_display'] = self._parse_and_format_timestamp(
                    enrollment['override_acknowledged']
                )
        
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
        
        # Get conflicts count
        self.cursor.execute("SELECT COUNT(*) as conflicts FROM training_enrollments WHERE conflict_override = 1 AND status = 'active'")
        conflict_count = self.cursor.fetchone()['conflicts']
        
        # Get recent enrollments (last 24 hours Eastern time)
        current_time = self._get_eastern_time()
        yesterday = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_str = self._format_eastern_timestamp(yesterday)
        
        self.cursor.execute('''
            SELECT COUNT(*) as recent FROM training_enrollments 
            WHERE status = 'active' AND enrollment_date >= ?
        ''', (yesterday_str,))
        recent_enrollments = self.cursor.fetchone()['recent']
        
        self.disconnect()
        
        return {
            'total_enrollments': total_enrollments,
            'conflict_overrides': conflict_count,
            'recent_enrollments': recent_enrollments,
            'current_time_eastern': current_time.strftime('%m/%d/%Y %I:%M %p %Z')
        }