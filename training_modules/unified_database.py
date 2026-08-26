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

# The roster workbook FY26 uses. Before FY27 got its own file there was only one
# roster, named "MASTER", so a database written back then still points at that name.
FY26_ROSTER_FILENAME = 'FY26 Education Classes Roster.xlsx'
LEGACY_ROSTER_FILENAME = 'MASTER Education Classes Roster.xlsx'

# A training year runs on the calendar - 10/1 through 9/30 - which is NOT the span of
# the track cohort it is checked against. Track cohorts start on whichever Sunday
# begins their 42-day pattern (FY26: 2025-09-28, FY27: 2026-09-27), so the two differ
# by a few days at each end. These are the training-year dates; the track cohort's
# grid is anchored separately by pattern_start_date.
FY26_TRAINING_YEAR_START = '2025-10-01'
FY26_TRAINING_YEAR_END = '2026-09-30'

# What the FY26 row was seeded with before the two spans were told apart: the track
# cohort's dates. Used to spot an untouched row that still needs correcting.
_LEGACY_FY26_START = '2025-09-28'
_LEGACY_FY26_END = '2026-09-26'

# FY26 was the only cohort that existed before enrollments carried a training_year,
# so every row written back then belongs to it.
LEGACY_TRAINING_YEAR = 'FY26'

# Rows written before the training_year column existed were backfilled with the
# column default, but COALESCE keeps the filter correct even if a NULL slips through.
_YEAR_MATCH = "COALESCE(training_year, '%s') = ?" % LEGACY_TRAINING_YEAR

# Training year lifecycle. A single is_active flag can't express the overlap a
# fiscal-year cutover needs - the outgoing year has to stay editable for its last
# few months while the incoming year takes signups - so status carries that and
# is_active only marks which year the registration screen opens on.
YEAR_STATUS_DRAFT = 'draft'        # being built; admin-only, invisible to staff
YEAR_STATUS_OPEN = 'open'          # accepting signups; more than one year may be open
YEAR_STATUS_READONLY = 'readonly'  # visible to staff, no enrolling or cancelling
YEAR_STATUS_ARCHIVED = 'archived'  # hidden from staff; admin and reporting only

YEAR_STATUSES = (YEAR_STATUS_DRAFT, YEAR_STATUS_OPEN,
                 YEAR_STATUS_READONLY, YEAR_STATUS_ARCHIVED)

# Statuses a staff member can see at all, and the one status that accepts writes.
STAFF_VISIBLE_STATUSES = (YEAR_STATUS_OPEN, YEAR_STATUS_READONLY)


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

        # Create training_years table: one row per fiscal-year training cohort,
        # pointing at its Excel roster file and (optionally) a matching
        # modules.db_utils track_configs cohort. Mirrors the track_configs
        # active/promote pattern used by Track Bidding.
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_years (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year_label TEXT NOT NULL UNIQUE,
                is_active INTEGER DEFAULT 0,
                status TEXT DEFAULT 'draft',
                roster_filename TEXT,
                linked_track_name TEXT,
                pattern_start_date TEXT,
                start_date TEXT,
                end_date TEXT,
                created_date TEXT NOT NULL,
                modified_date TEXT NOT NULL
            )
        ''')

        # Add the status column if missing (migration). Existing rows take their
        # status from is_active: the active year was open, every other year was a
        # past cohort nobody should still be writing to.
        self.cursor.execute("PRAGMA table_info(training_years)")
        year_columns = [col[1] for col in self.cursor.fetchall()]
        if 'status' not in year_columns:
            self.cursor.execute(
                f"ALTER TABLE training_years ADD COLUMN status TEXT DEFAULT '{YEAR_STATUS_OPEN}'"
            )
            self.cursor.execute(
                "UPDATE training_years SET status = CASE WHEN is_active = 1 THEN ? ELSE ? END",
                (YEAR_STATUS_OPEN, YEAR_STATUS_READONLY)
            )

        if 'pattern_start_date' not in year_columns:
            self.cursor.execute(
                "ALTER TABLE training_years ADD COLUMN pattern_start_date TEXT"
            )
            # FY26's anchor is the one the code carried hardcoded; record it so the
            # value is visible and editable rather than implied.
            self.cursor.execute(
                "UPDATE training_years SET pattern_start_date = '2025-09-14' "
                "WHERE year_label = 'FY26' AND pattern_start_date IS NULL"
            )

        # Add training_year column to enrollment/signup tables if missing (migration).
        # Existing rows backfill to 'FY26' since that's the only cohort that existed
        # before this column was introduced.
        for table_name in ('training_enrollments', 'training_educator_signups'):
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = [col[1] for col in self.cursor.fetchall()]
            if 'training_year' not in existing_columns:
                self.cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN training_year TEXT "
                    f"DEFAULT '{LEGACY_TRAINING_YEAR}'"
                )

        # Seed the default FY26 training year if it doesn't exist yet
        self.cursor.execute("SELECT id FROM training_years WHERE year_label = 'FY26'")
        if not self.cursor.fetchone():
            now = self._format_eastern_timestamp(self._get_eastern_time())
            self.cursor.execute('''
                INSERT INTO training_years
                    (year_label, is_active, status, roster_filename, linked_track_name,
                     pattern_start_date, start_date, end_date, created_date, modified_date)
                VALUES ('FY26', 1, ?, ?, 'FY26', '2025-09-14', ?, ?, ?, ?)
            ''', (YEAR_STATUS_OPEN, FY26_ROSTER_FILENAME,
                  FY26_TRAINING_YEAR_START, FY26_TRAINING_YEAR_END, now, now))

        # Correct an FY26 row still carrying the track cohort's dates rather than the
        # training year's. The two were conflated when there was only one year and
        # nothing depended on the difference; end_date now drives auto-close, and
        # closing on 9/26 would freeze the year while classes still ran to 9/30.
        # Only an untouched row is corrected - an admin's own dates are left alone.
        self.cursor.execute(
            "UPDATE training_years SET start_date = ?, end_date = ?, modified_date = ? "
            "WHERE year_label = 'FY26' AND start_date = ? AND end_date = ?",
            (FY26_TRAINING_YEAR_START, FY26_TRAINING_YEAR_END,
             self._format_eastern_timestamp(self._get_eastern_time()),
             _LEGACY_FY26_START, _LEGACY_FY26_END)
        )

        # Point any year still naming the pre-FY27 "MASTER" roster at its renamed file.
        # The workbook became FY26-specific when FY27 got its own; a database written
        # before that rename still holds the old name, which no longer exists on disk.
        self.cursor.execute(
            "UPDATE training_years SET roster_filename = ?, modified_date = ? "
            "WHERE roster_filename = ?",
            (FY26_ROSTER_FILENAME,
             self._format_eastern_timestamp(self._get_eastern_time()),
             LEGACY_ROSTER_FILENAME)
        )

        self.conn.commit()
        self.disconnect()
        print("Training tables created successfully with proper AUTO INCREMENT")

    # ========================================================================
    # TRAINING YEAR METHODS (fiscal-year roster/cohort management)
    # ========================================================================

    def _training_year_row_to_dict(self, row):
        return {
            'id': row['id'],
            'year_label': row['year_label'],
            'is_active': row['is_active'],
            'status': row['status'] or YEAR_STATUS_DRAFT,
            'roster_filename': row['roster_filename'],
            'linked_track_name': row['linked_track_name'],
            'pattern_start_date': row['pattern_start_date'],
            'start_date': row['start_date'],
            'end_date': row['end_date'],
            'created_date': row['created_date'],
            'modified_date': row['modified_date'],
        }

    def _fetch_active_training_year_row(self):
        """Query training_years for the active row using the currently-open cursor.
        Callers must already hold a connection (via self.connect()); this does not
        manage connect/disconnect itself so it's safe to call mid-transaction."""
        self.cursor.execute("SELECT * FROM training_years WHERE is_active = 1 LIMIT 1")
        return self.cursor.fetchone()

    def _resolve_training_year(self, training_year=None):
        """Return the training year a query should be scoped to.

        An explicit label wins; otherwise the active year is used, so callers that
        don't care about history read the year staff are currently registering for.
        Requires an open connection - callers already hold one via self.connect().
        """
        if training_year:
            return training_year
        row = self._fetch_active_training_year_row()
        return row['year_label'] if row else LEGACY_TRAINING_YEAR

    def get_active_training_year(self):
        """Return the training_years row where is_active = 1, or None."""
        self.connect()
        try:
            row = self._fetch_active_training_year_row()
            return self._training_year_row_to_dict(row) if row else None
        finally:
            self.disconnect()

    def get_training_year(self, year_label):
        """Return the training_years row for a given year_label, or None."""
        self.connect()
        try:
            self.cursor.execute("SELECT * FROM training_years WHERE year_label = ?", (year_label,))
            row = self.cursor.fetchone()
            return self._training_year_row_to_dict(row) if row else None
        finally:
            self.disconnect()

    def get_all_training_years(self):
        """Return all training_years rows, most recently created first."""
        self.connect()
        try:
            self.cursor.execute("SELECT * FROM training_years ORDER BY created_date DESC")
            rows = self.cursor.fetchall()
            return [self._training_year_row_to_dict(row) for row in rows]
        finally:
            self.disconnect()

    def _auto_close_expired_years(self):
        """Move any non-active year past its end date to read-only.

        Freezing the outgoing year is the kind of thing that gets forgotten in the
        weeks after a cutover, so it happens on its own once the year is over.
        Only years that are currently open move: draft years aren't published yet
        and archived years are already past read-only. The active year is left
        alone - if its end date has passed and nothing has been promoted, staff
        still need somewhere to register.
        Requires an open connection.
        """
        today = self._get_eastern_time().strftime('%Y-%m-%d')
        self.cursor.execute("""
            UPDATE training_years
            SET status = ?, modified_date = ?
            WHERE status = ? AND is_active = 0
                  AND end_date IS NOT NULL AND end_date != '' AND end_date < ?
        """, (YEAR_STATUS_READONLY,
              self._format_eastern_timestamp(self._get_eastern_time()),
              YEAR_STATUS_OPEN, today))
        return self.cursor.rowcount

    def set_training_year_status(self, year_label, status):
        """Set a training year's lifecycle status."""
        if status not in YEAR_STATUSES:
            return False, f"Unknown status '{status}'"
        self.connect()
        try:
            self.cursor.execute("SELECT is_active FROM training_years WHERE year_label = ?",
                                (year_label,))
            row = self.cursor.fetchone()
            if not row:
                return False, f"Training year '{year_label}' not found"
            if row['is_active'] and status != YEAR_STATUS_OPEN:
                return False, (f"'{year_label}' is the active year - promote another year "
                               f"first, then set this one to {status}")

            self.cursor.execute(
                "UPDATE training_years SET status = ?, modified_date = ? WHERE year_label = ?",
                (status, self._format_eastern_timestamp(self._get_eastern_time()), year_label)
            )
            self.conn.commit()
            return True, f"'{year_label}' is now {status}"
        except Exception as e:
            return False, f"Error updating status: {e}"
        finally:
            self.disconnect()

    def get_staff_visible_training_years(self):
        """Return the years staff may see, active year first, then newest.

        Expired years are closed off first so the list reflects today, not
        whenever an admin last touched the screen.
        """
        self.connect()
        try:
            self._auto_close_expired_years()
            self.conn.commit()
            placeholders = ','.join('?' for _ in STAFF_VISIBLE_STATUSES)
            self.cursor.execute(
                f"SELECT * FROM training_years WHERE status IN ({placeholders}) "
                f"ORDER BY is_active DESC, created_date DESC",
                STAFF_VISIBLE_STATUSES
            )
            return [self._training_year_row_to_dict(r) for r in self.cursor.fetchall()]
        finally:
            self.disconnect()

    def _year_accepts_writes(self, year_label):
        """Whether year_label is open for enrolling/cancelling. Requires an open
        connection, so write paths can check without a second connect()."""
        self.cursor.execute("SELECT status FROM training_years WHERE year_label = ?", (year_label,))
        row = self.cursor.fetchone()
        if not row:
            return True  # no config row: the pre-training_years state, always writable
        return (row['status'] or YEAR_STATUS_DRAFT) == YEAR_STATUS_OPEN

    def is_training_year_writable(self, year_label=None):
        """Whether enrolling and cancelling are allowed in this year.

        Only an open year accepts writes; a read-only, archived or draft year does
        not. Callers pass the year a staff member is looking at, which is not
        necessarily the active one.
        """
        self.connect()
        try:
            self._auto_close_expired_years()
            self.conn.commit()
            return self._year_accepts_writes(self._resolve_training_year(year_label))
        finally:
            self.disconnect()

    def create_training_year(self, year_label, roster_filename=None, linked_track_name=None,
                              start_date=None, end_date=None, status=YEAR_STATUS_DRAFT,
                              pattern_start_date=None):
        """Create a new training year. Starts as a draft: admin-visible only, so a
        half-built roster is never exposed to staff before it's ready."""
        if status not in YEAR_STATUSES:
            return False, f"Unknown status '{status}'"
        self.connect()
        try:
            now = self._format_eastern_timestamp(self._get_eastern_time())
            self.cursor.execute('''
                INSERT INTO training_years
                    (year_label, is_active, status, roster_filename, linked_track_name,
                     pattern_start_date, start_date, end_date, created_date, modified_date)
                VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (year_label, status, roster_filename, linked_track_name,
                  pattern_start_date, start_date, end_date, now, now))
            self.conn.commit()
            return True, f"Training year '{year_label}' created successfully"
        except sqlite3.IntegrityError:
            return False, f"Training year '{year_label}' already exists"
        except Exception as e:
            return False, f"Error creating training year: {e}"
        finally:
            self.disconnect()

    def update_training_year(self, year_label, **kwargs):
        """Update roster_filename/linked_track_name/start_date/end_date on a training year."""
        allowed = {'roster_filename', 'linked_track_name', 'start_date', 'end_date',
                   'pattern_start_date'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False, "No valid fields to update"
        self.connect()
        try:
            updates['modified_date'] = self._format_eastern_timestamp(self._get_eastern_time())
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [year_label]
            self.cursor.execute(f"UPDATE training_years SET {set_clause} WHERE year_label = ?", values)
            self.conn.commit()
            return True, f"Training year '{year_label}' updated"
        except Exception as e:
            return False, f"Error updating training year: {e}"
        finally:
            self.disconnect()

    def promote_training_year_to_active(self, year_label, close_previous=False):
        """Make year_label the year the registration screen opens on.

        The outgoing year stays open by default. A fiscal year ends months after
        the next one starts taking signups, and staff still need to cancel and
        re-book their remaining classes in it; it goes read-only on its end date,
        or immediately if close_previous is set.
        """
        self.connect()
        try:
            now = self._format_eastern_timestamp(self._get_eastern_time())
            active_row = self._fetch_active_training_year_row()
            previous_label = active_row['year_label'] if active_row else None
            if previous_label:
                self.cursor.execute(
                    "UPDATE training_years SET is_active = 0, status = ?, modified_date = ? "
                    "WHERE year_label = ?",
                    (YEAR_STATUS_READONLY if close_previous else YEAR_STATUS_OPEN,
                     now, previous_label)
                )
            self.cursor.execute(
                "UPDATE training_years SET is_active = 1, status = ?, modified_date = ? "
                "WHERE year_label = ?",
                (YEAR_STATUS_OPEN, now, year_label)
            )
            self._auto_close_expired_years()
            self.conn.commit()

            message = f"'{year_label}' is now the active training year"
            if previous_label and close_previous:
                message += f"; '{previous_label}' is now read-only"
            elif previous_label:
                message += f"; '{previous_label}' stays open for signups"
            return True, message
        except Exception as e:
            return False, f"Error promoting training year: {e}"
        finally:
            self.disconnect()

    def delete_training_year(self, year_label):
        """Delete a training year config. Blocked if it is currently active."""
        self.connect()
        try:
            self.cursor.execute("SELECT is_active FROM training_years WHERE year_label = ?", (year_label,))
            row = self.cursor.fetchone()
            if not row:
                return False, f"Training year '{year_label}' not found"
            if row['is_active']:
                return False, f"Cannot delete the active training year '{year_label}'"
            self.cursor.execute("DELETE FROM training_years WHERE year_label = ?", (year_label,))
            self.conn.commit()
            return True, f"Deleted training year '{year_label}'"
        except Exception as e:
            return False, f"Error deleting training year: {e}"
        finally:
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
    
    # STUDENT ENROLLMENT METHODS - COMPLETELY FIXED
    def add_enrollment(self, staff_name, class_name, class_date, role='General', 
                    meeting_type=None, session_time=None, conflict_override=False, 
                    conflict_details=None):
        """Add a new training enrollment - COMPLETELY FIXED"""
        print(f"DEBUG: add_enrollment called for {staff_name}, {class_name}, {class_date}")
        
        self.connect()
        try:
            self._auto_close_expired_years()
            active_row = self._fetch_active_training_year_row()
            active_label = active_row['year_label'] if active_row else LEGACY_TRAINING_YEAR
            if not self._year_accepts_writes(active_label):
                print(f"DEBUG: {active_label} is not open for signups; enrollment refused")
                return False

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
                    
                    # Re-stamp the training year: reactivating a cancelled row during a
                    # later year makes it an enrollment in that year, not the old one.
                    active_year_row = self._fetch_active_training_year_row()
                    training_year = (active_year_row['year_label'] if active_year_row
                                     else LEGACY_TRAINING_YEAR)

                    self.cursor.execute('''
                        UPDATE training_enrollments 
                        SET status = 'active', role = ?, conflict_override = ?,
                            conflict_details = ?, override_acknowledged = ?, enrollment_date = ?,
                            training_year = ?
                        WHERE id = ?
                    ''', (role, conflict_override, conflict_details, 
                        override_timestamp, enrollment_timestamp, training_year, existing['id']))
                    
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

            active_year_row = self._fetch_active_training_year_row()
            training_year = (active_year_row['year_label'] if active_year_row
                             else LEGACY_TRAINING_YEAR)

            # Insert with explicit column list (excludes id to allow auto-increment)
            self.cursor.execute('''
                INSERT INTO training_enrollments
                (staff_name, class_name, class_date, role, meeting_type, session_time,
                 conflict_override, conflict_details, override_acknowledged, enrollment_date, status,
                 training_year)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ''', (staff_name, class_name, class_date, role, meeting_type, session_time,
                conflict_override, conflict_details, override_timestamp, enrollment_timestamp,
                training_year))
            
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
        """Cancel a training enrollment. Refused once its year is read-only."""
        self.connect()
        try:
            self._auto_close_expired_years()
            # Check against the row's own year, not the active one - a closed year's
            # enrollments stay frozen even while a newer year is open.
            self.cursor.execute(
                "SELECT COALESCE(training_year, ?) AS year FROM training_enrollments WHERE id = ?",
                (LEGACY_TRAINING_YEAR, enrollment_id))
            year_row = self.cursor.fetchone()
            if year_row and not self._year_accepts_writes(year_row['year']):
                print(f"DEBUG: {year_row['year']} is read-only; cancellation refused")
                return False

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
            self._auto_close_expired_years()
            active_row = self._fetch_active_training_year_row()
            active_label = active_row['year_label'] if active_row else LEGACY_TRAINING_YEAR
            if not self._year_accepts_writes(active_label):
                print(f"DEBUG: {active_label} is not open for signups; educator signup refused")
                return False

            current_time = self._get_eastern_time()
            signup_timestamp = self._format_eastern_timestamp(current_time)
            override_timestamp = self._format_eastern_timestamp(current_time) if conflict_override else None
            
            # Check if a cancelled record already exists (UNIQUE constraint blocks re-insert)
            self.cursor.execute('''
                SELECT id FROM training_educator_signups
                WHERE staff_name = ? AND class_name = ? AND class_date = ?
            ''', (staff_name, class_name, class_date))
            existing = self.cursor.fetchone()

            if existing:
                # Reactivate the cancelled signup instead of inserting a duplicate,
                # re-stamping the year so it belongs to the year it was revived in.
                active_year_row = self._fetch_active_training_year_row()
                training_year = (active_year_row['year_label'] if active_year_row
                                 else LEGACY_TRAINING_YEAR)

                self.cursor.execute('''
                    UPDATE training_educator_signups
                    SET status = 'active', conflict_override = ?, conflict_details = ?,
                        override_acknowledged = ?, signup_date = ?, training_year = ?
                    WHERE id = ?
                ''', (conflict_override, conflict_details, override_timestamp,
                      signup_timestamp, training_year, existing['id']))
                inserted_id = existing['id']
                print(f"SUCCESS: Educator signup reactivated with ID: {inserted_id}")
            else:
                active_year_row = self._fetch_active_training_year_row()
                training_year = (active_year_row['year_label'] if active_year_row
                                 else LEGACY_TRAINING_YEAR)

                # Insert with explicit column list (excludes id to allow auto-increment)
                self.cursor.execute('''
                    INSERT INTO training_educator_signups
                    (staff_name, class_name, class_date, conflict_override, conflict_details,
                     override_acknowledged, signup_date, status, training_year)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                ''', (staff_name, class_name, class_date, conflict_override, conflict_details,
                     override_timestamp, signup_timestamp, training_year))

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
        """Cancel an educator signup. Refused once its year is read-only."""
        self.connect()
        try:
            self._auto_close_expired_years()
            self.cursor.execute(
                "SELECT COALESCE(training_year, ?) AS year FROM training_educator_signups WHERE id = ?",
                (LEGACY_TRAINING_YEAR, signup_id))
            year_row = self.cursor.fetchone()
            if year_row and not self._year_accepts_writes(year_row['year']):
                print(f"DEBUG: {year_row['year']} is read-only; cancellation refused")
                return False

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

    def get_educator_signups_for_class(self, class_name, class_date=None, training_year=None):
        """Get all educator signups for a class within one training year"""
        self.connect()
        year = self._resolve_training_year(training_year)
        if class_date:
            self.cursor.execute(f'''
                SELECT id, staff_name, class_name, class_date, conflict_override,
                       conflict_details, signup_date, status
                FROM training_educator_signups
                WHERE class_name = ? AND class_date = ? AND status = 'active'
                      AND {_YEAR_MATCH}
                ORDER BY signup_date
            ''', (class_name, class_date, year))
        else:
            self.cursor.execute(f'''
                SELECT id, staff_name, class_name, class_date, conflict_override,
                       conflict_details, signup_date, status
                FROM training_educator_signups
                WHERE class_name = ? AND status = 'active' AND {_YEAR_MATCH}
                ORDER BY class_date, signup_date
            ''', (class_name, year))
        
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
    
    def get_educator_signup_count(self, class_name, class_date, training_year=None):
        """Count educator signups for a class and date within one training year"""
        self.connect()
        year = self._resolve_training_year(training_year)
        self.cursor.execute(f'''
            SELECT COUNT(*) as count FROM training_educator_signups
            WHERE class_name = ? AND class_date = ? AND status = 'active'
                  AND {_YEAR_MATCH}
        ''', (class_name, class_date, year))
        count = self.cursor.fetchone()['count']
        self.disconnect()
        return count
    
    def check_existing_educator_signup(self, staff_name, class_name, class_date,
                                       training_year=None):
        """Check if staff member already signed up as educator in one training year"""
        self.connect()
        year = self._resolve_training_year(training_year)
        self.cursor.execute(f'''
            SELECT id, staff_name, class_name, class_date, status
            FROM training_educator_signups
            WHERE staff_name = ? AND class_name = ? AND class_date = ? AND status = 'active'
                  AND {_YEAR_MATCH}
        ''', (staff_name, class_name, class_date, year))
        
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

    def get_staff_enrollments(self, staff_name, training_year=None):
        """Get a staff member's training enrollments for one training year.

        Defaults to the active year so a prior year's enrollments never count
        toward the current one.
        """
        self.connect()
        
        try:
            year = self._resolve_training_year(training_year)
            # Explicit column selection
            self.cursor.execute(f'''
                SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                    session_time, conflict_override, conflict_details, 
                    override_acknowledged, enrollment_date, status, training_year
                FROM training_enrollments
                WHERE staff_name = ? AND status = 'active' AND {_YEAR_MATCH}
                ORDER BY class_date
            ''', (staff_name, year))
            
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
                    'status': row['status'],
                    'training_year': row['training_year']
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

    def get_class_enrollments(self, class_name, class_date=None, training_year=None):
        """Get all training enrollments for a class within one training year"""
        self.connect()
        year = self._resolve_training_year(training_year)
        if class_date:
            self.cursor.execute(f'''
                SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                       session_time, conflict_override, conflict_details, status
                FROM training_enrollments
                WHERE class_name = ? AND class_date = ? AND status = 'active'
                      AND {_YEAR_MATCH}
            ''', (class_name, class_date, year))
        else:
            self.cursor.execute(f'''
                SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                       session_time, conflict_override, conflict_details, status
                FROM training_enrollments
                WHERE class_name = ? AND status = 'active' AND {_YEAR_MATCH}
            ''', (class_name, year))
            
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
        
    def get_enrollment_count(self, class_name, class_date, role=None, meeting_type=None,
                             session_time=None, training_year=None):
        """Get enrollment count for a specific class, date, and optional filters.

        Scoped to one training year so a prior year's enrollments never consume
        this year's seats.
        """
        self.connect()
        
        year = self._resolve_training_year(training_year)
        query = f'''
            SELECT COUNT(*) as count FROM training_enrollments
            WHERE class_name = ? AND class_date = ? AND status = 'active'
                  AND {_YEAR_MATCH}
        '''
        params = [class_name, class_date, year]
        
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
        
    def get_session_enrollments(self, class_name, class_date, session_time=None,
                                meeting_type=None, training_year=None):
        """Get all enrollments for a specific training session in one training year"""
        self.connect()
        
        year = self._resolve_training_year(training_year)
        query = f'''
            SELECT id, staff_name, class_name, class_date, role, meeting_type, 
                   session_time, conflict_override
            FROM training_enrollments
            WHERE class_name = ? AND class_date = ? AND status = 'active'
                  AND {_YEAR_MATCH}
        '''
        params = [class_name, class_date, year]
        
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
            
    def get_enrollment_stats(self, training_year=None):
        """Get training enrollment statistics for one training year.

        Pass training_year='' to count every year at once; the default reports the
        active year so the admin dashboard isn't inflated by closed years.
        """
        self.connect()
        
        all_years = training_year == ''
        year = None if all_years else self._resolve_training_year(training_year)
        year_clause = '' if all_years else f' AND {_YEAR_MATCH}'
        year_params = () if all_years else (year,)
        
        # Get total enrollments
        self.cursor.execute(
            f"SELECT COUNT(*) as total FROM training_enrollments WHERE status = 'active'{year_clause}",
            year_params)
        total_enrollments = self.cursor.fetchone()['total']
        
        # Get total educator signups
        self.cursor.execute(
            f"SELECT COUNT(*) as total FROM training_educator_signups WHERE status = 'active'{year_clause}",
            year_params)
        total_educator_signups = self.cursor.fetchone()['total']
        
        # Get conflicts count
        self.cursor.execute(
            "SELECT COUNT(*) as conflicts FROM training_enrollments "
            f"WHERE conflict_override = 1 AND status = 'active'{year_clause}", year_params)
        enrollment_conflicts = self.cursor.fetchone()['conflicts']
        
        # Get educator conflicts count
        self.cursor.execute(
            "SELECT COUNT(*) as conflicts FROM training_educator_signups "
            f"WHERE conflict_override = 1 AND status = 'active'{year_clause}", year_params)
        educator_conflicts = self.cursor.fetchone()['conflicts']
        
        # Get recent enrollments (last 24 hours Eastern time)
        current_time = self._get_eastern_time()
        yesterday = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_str = self._format_eastern_timestamp(yesterday)
        
        self.cursor.execute(f'''
            SELECT COUNT(*) as recent FROM training_enrollments 
            WHERE status = 'active' AND enrollment_date >= ?{year_clause}
        ''', (yesterday_str,) + year_params)
        recent_enrollments = self.cursor.fetchone()['recent']
        
        # Get recent educator signups
        self.cursor.execute(f'''
            SELECT COUNT(*) as recent FROM training_educator_signups 
            WHERE status = 'active' AND signup_date >= ?{year_clause}
        ''', (yesterday_str,) + year_params)
        recent_educator_signups = self.cursor.fetchone()['recent']
        
        self.disconnect()
        
        return {
            'training_year': 'All years' if all_years else year,
            'total_enrollments': total_enrollments,
            'total_educator_signups': total_educator_signups,
            'enrollment_conflicts': enrollment_conflicts,
            'educator_conflicts': educator_conflicts,
            'total_conflicts': enrollment_conflicts + educator_conflicts,
            'recent_enrollments': recent_enrollments,
            'recent_educator_signups': recent_educator_signups,
            'current_time_eastern': current_time.strftime('%m/%d/%Y %I:%M %p %Z')
        }

    def get_live_staff_meeting_count(self, staff_name, training_year=None):
        """Count a staff member's LIVE staff meetings within one training year.

        The LIVE requirement resets each year, so this must not see prior years.
        """
        self.connect()
        try:
            year = self._resolve_training_year(training_year)
            self.cursor.execute(f'''
                SELECT COUNT(*) as count FROM training_enrollments
                WHERE staff_name = ? AND meeting_type = 'LIVE' AND status = 'active'
                      AND {_YEAR_MATCH}
            ''', (staff_name, year))
            count = self.cursor.fetchone()['count']
            return count
        finally:
            self.disconnect()

    def get_conflict_override_enrollments(self, staff_name=None, training_year=None):
        """Get training enrollments with conflict overrides for one training year"""
        self.connect()
        
        try:
            year = self._resolve_training_year(training_year)
            if staff_name:
                self.cursor.execute(f'''
                    SELECT id, staff_name, class_name, class_date, role, meeting_type,
                        conflict_override, conflict_details, override_acknowledged
                    FROM training_enrollments
                    WHERE staff_name = ? AND conflict_override = 1 AND status = 'active'
                          AND {_YEAR_MATCH}
                    ORDER BY class_date
                ''', (staff_name, year))
            else:
                self.cursor.execute(f'''
                    SELECT id, staff_name, class_name, class_date, role, meeting_type,
                        conflict_override, conflict_details, override_acknowledged
                    FROM training_enrollments
                    WHERE conflict_override = 1 AND status = 'active' AND {_YEAR_MATCH}
                    ORDER BY staff_name, class_date
                ''', (year,))
                
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

    def get_conflict_override_educator_signups(self, staff_name=None, training_year=None):
        """Get educator signups with conflict overrides for one training year"""
        self.connect()
        
        try:
            year = self._resolve_training_year(training_year)
            if staff_name:
                self.cursor.execute(f'''
                    SELECT id, staff_name, class_name, class_date, conflict_override,
                        conflict_details, override_acknowledged
                    FROM training_educator_signups
                    WHERE staff_name = ? AND conflict_override = 1 AND status = 'active'
                          AND {_YEAR_MATCH}
                    ORDER BY class_date
                ''', (staff_name, year))
            else:
                self.cursor.execute(f'''
                    SELECT id, staff_name, class_name, class_date, conflict_override,
                        conflict_details, override_acknowledged
                    FROM training_educator_signups
                    WHERE conflict_override = 1 AND status = 'active' AND {_YEAR_MATCH}
                    ORDER BY staff_name, class_date
                ''', (year,))
                
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

    def get_staff_educator_signups(self, staff_name, training_year=None):
        """Get a staff member's educator signups for one training year"""
        self.connect()
        
        try:
            year = self._resolve_training_year(training_year)
            # Explicit column selection ensures proper ordering
            self.cursor.execute(f'''
                SELECT id, staff_name, class_name, class_date, conflict_override, 
                    conflict_details, override_acknowledged, signup_date, status
                FROM training_educator_signups
                WHERE staff_name = ? AND status = 'active' AND {_YEAR_MATCH}
                ORDER BY class_date
            ''', (staff_name, year))
            
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


def get_active_roster_path(db_path='data/medflight_tracks.db', upload_folder='training/upload',
                            default_filename=FY26_ROSTER_FILENAME):
    """
    Resolve the Excel roster path for the currently active training year.
    Falls back to the historical default path if no training year is configured yet
    (e.g. the training_years table hasn't been created by initialize_training_tables() yet).
    """
    filename = default_filename
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT roster_filename FROM training_years WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row and row['roster_filename']:
            filename = row['roster_filename']
    except sqlite3.OperationalError:
        pass

    # A database that predates the FY26 rename still names the "MASTER" workbook, and
    # initialize_training_tables() may not have run yet to correct it. Resolve to the
    # renamed file when the old name is gone so the roster still loads.
    path = os.path.join(upload_folder, filename)
    if filename == LEGACY_ROSTER_FILENAME and not os.path.exists(path):
        renamed = os.path.join(upload_folder, FY26_ROSTER_FILENAME)
        if os.path.exists(renamed):
            return renamed
    return path