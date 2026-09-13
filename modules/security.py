# modules/security.py
"""
Security module for user authentication and access control.

Two credentials, and only two: the four-digit access code every user needs to
open the app at all, and a single administrator password.

That admin password is the whole of administrative access. Every admin area —
the Clinical Track Hub tools, Track Bidding, the Staff Database, Track Data,
Training & Events and Summer Leave — reads the one session this module keeps, so
an administrator signs in once and stays signed in across all of them. Training
used to carry a second PIN of its own; it does not any more.
"""

import os
import streamlit as st
import hashlib
import time
from datetime import datetime, timedelta

# ──────────────────────────────────────────────
# Admin session (shared by every admin area in the app)
# ──────────────────────────────────────────────

# How long an admin session lasts without activity. Every admin page extends it
# on render, so this only bites on a console left open and walked away from.
ADMIN_SESSION_TIMEOUT_MINUTES = 60

# The credential to fall back on when nothing is configured. Deployments set a
# real one in secrets or the environment; see get_admin_password().
_DEFAULT_ADMIN_PASSWORD = "PW"

# Everything that makes up an authenticated admin session, cleared together.
_ADMIN_SESSION_KEYS = (
    'admin_authenticated',
    'admin_login_time',
    'admin_console_section',
    # Per-module admin view state. Left behind, these put a logged-out user back
    # into an admin screen the moment they open the module again.
    'track_bidding_admin_mode',
    'summer_leave_admin_mode',
    'training_admin_current_function',
    'training_admin_show_function',
)


def get_admin_password():
    """The configured admin password.

    Looked up in order: `st.secrets["admin"]["password"]`, a top-level
    `admin_password` secret, the `CREWOPS_ADMIN_PASSWORD` environment variable,
    then the built-in default. Reading secrets raises when no secrets file
    exists at all, which is the normal case running locally, so the whole lookup
    is guarded.
    """
    try:
        secrets = st.secrets
        admin_section = secrets.get('admin') if hasattr(secrets, 'get') else None
        if admin_section:
            configured = admin_section.get('password')
            if configured:
                return str(configured)
        configured = secrets.get('admin_password') if hasattr(secrets, 'get') else None
        if configured:
            return str(configured)
    except Exception:
        pass

    return os.getenv('CREWOPS_ADMIN_PASSWORD') or _DEFAULT_ADMIN_PASSWORD


def admin_is_authenticated():
    """Whether an admin is signed in and their session has not expired.

    Expiry logs the session out here rather than only reporting it, so an admin
    whose session ran out stops seeing admin screens on the render that notices.
    """
    if not st.session_state.get('admin_authenticated'):
        return False

    login_time = st.session_state.get('admin_login_time')
    if not login_time:
        return False

    elapsed_minutes = (datetime.now() - login_time).total_seconds() / 60
    if elapsed_minutes > ADMIN_SESSION_TIMEOUT_MINUTES:
        logout_admin()
        return False

    return True


def admin_session_minutes_remaining():
    """Minutes left on the current admin session (0 once it has expired)."""
    login_time = st.session_state.get('admin_login_time')
    if not login_time:
        return 0
    elapsed_minutes = (datetime.now() - login_time).total_seconds() / 60
    return max(0, ADMIN_SESSION_TIMEOUT_MINUTES - elapsed_minutes)


def touch_admin_session():
    """Push the expiry out. Called by admin pages so activity keeps a session alive."""
    if st.session_state.get('admin_authenticated'):
        st.session_state.admin_login_time = datetime.now()


def authenticate_admin(password):
    """Sign an admin in if the password matches. Returns True on success."""
    if password and password == get_admin_password():
        st.session_state.admin_authenticated = True
        st.session_state.admin_login_time = datetime.now()
        return True
    return False


def logout_admin():
    """End the admin session and drop every admin view it left behind."""
    for key in _ADMIN_SESSION_KEYS:
        st.session_state.pop(key, None)
    st.session_state.admin_authenticated = False


def require_admin(form_key="admin_login", message="🔒 Admin access required."):
    """Gate a page behind the one admin password. Returns True when signed in.

    Renders the sign-in form itself when nobody is, so a caller only has to
    return early on False.
    """
    if admin_is_authenticated():
        touch_admin_session()
        return True

    st.warning(message)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form(form_key):
            password = st.text_input("Admin password", type="password",
                                     key=f"{form_key}_password")
            submitted = st.form_submit_button("Unlock", use_container_width=True,
                                              type="primary")
        if submitted:
            if authenticate_admin(password):
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


class SecurityManager:
    """Manage user authentication and security"""
    
    def __init__(self):
        # Security configuration
        self.USER_PIN = "2711"  # Four-digit PIN for users
        
        # Session timeout (in minutes)
        self.SESSION_TIMEOUT = 180  # 3 hours
        
        # Failed attempt tracking
        self.MAX_FAILED_ATTEMPTS = 5
        self.LOCKOUT_DURATION = 30  # minutes
        
        # Initialize session state
        self.init_session_state()
    
    def init_session_state(self):
        """Initialize security-related session state variables"""
        if 'user_authenticated' not in st.session_state:
            st.session_state.user_authenticated = False
        
        if 'admin_authenticated' not in st.session_state:
            st.session_state.admin_authenticated = False
        
        if 'auth_timestamp' not in st.session_state:
            st.session_state.auth_timestamp = None
        
        if 'failed_attempts' not in st.session_state:
            st.session_state.failed_attempts = 0
        
        if 'lockout_until' not in st.session_state:
            st.session_state.lockout_until = None
    
    def hash_pin(self, pin):
        """Hash PIN for secure comparison"""
        return hashlib.sha256(pin.encode()).hexdigest()
    
    def is_locked_out(self):
        """Check if user is currently locked out due to failed attempts"""
        if st.session_state.lockout_until is None:
            return False
        
        current_time = datetime.now()
        if current_time < st.session_state.lockout_until:
            return True
        else:
            # Lockout period has expired, reset
            st.session_state.lockout_until = None
            st.session_state.failed_attempts = 0
            return False
    
    def apply_lockout(self):
        """Apply lockout after too many failed attempts"""
        st.session_state.lockout_until = datetime.now() + timedelta(minutes=self.LOCKOUT_DURATION)
        st.session_state.failed_attempts = 0
    
    def is_session_expired(self):
        """Check if the current session has expired"""
        if st.session_state.auth_timestamp is None:
            return True
        
        current_time = datetime.now()
        session_age = current_time - st.session_state.auth_timestamp
        
        return session_age > timedelta(minutes=self.SESSION_TIMEOUT)
    
    def authenticate_user(self, entered_pin):
        """
        Authenticate user with PIN
        
        Args:
            entered_pin (str): PIN entered by user
            
        Returns:
            bool: True if authentication successful
        """
        # Check if locked out
        if self.is_locked_out():
            return False
        
        # Check PIN
        if entered_pin == self.USER_PIN:
            # Successful authentication
            st.session_state.user_authenticated = True
            st.session_state.auth_timestamp = datetime.now()
            st.session_state.failed_attempts = 0
            st.session_state.lockout_until = None
            return True
        else:
            # Failed authentication
            st.session_state.failed_attempts += 1
            
            # Apply lockout if too many failed attempts
            if st.session_state.failed_attempts >= self.MAX_FAILED_ATTEMPTS:
                self.apply_lockout()
            
            return False
    
    def authenticate_admin(self, entered_password):
        """
        Authenticate admin with the single shared admin password
        
        Args:
            entered_password (str): Password entered by admin
            
        Returns:
            bool: True if authentication successful
        """
        return authenticate_admin(entered_password)
    
    def check_user_access(self):
        """
        Check if user has valid access to the application
        
        Returns:
            bool: True if user can access the application
        """
        # Check if session expired. The admin session goes with it: an admin
        # session outliving the login that carried it is a way back into admin
        # screens for whoever enters the access code next on that browser.
        if self.is_session_expired():
            st.session_state.user_authenticated = False
            st.session_state.auth_timestamp = None
            logout_admin()
            return False
        
        return st.session_state.user_authenticated
    
    def logout_user(self):
        """Logout user, and with them any admin session they were holding.

        Leaving the admin session standing meant the next person to enter the
        access code on the same browser arrived already signed in as an admin.
        """
        st.session_state.user_authenticated = False
        st.session_state.auth_timestamp = None
        logout_admin()
    
    def logout_admin(self):
        """Logout admin"""
        logout_admin()
    
    def get_remaining_lockout_time(self):
        """Get remaining lockout time in minutes"""
        if st.session_state.lockout_until is None:
            return 0
        
        current_time = datetime.now()
        if current_time >= st.session_state.lockout_until:
            return 0
        
        time_diff = st.session_state.lockout_until - current_time
        return int(time_diff.total_seconds() / 60) + 1
    
    def get_session_remaining_time(self):
        """Get remaining session time in minutes"""
        if st.session_state.auth_timestamp is None:
            return 0
        
        current_time = datetime.now()
        session_age = current_time - st.session_state.auth_timestamp
        remaining = timedelta(minutes=self.SESSION_TIMEOUT) - session_age
        
        if remaining.total_seconds() <= 0:
            return 0
        
        return int(remaining.total_seconds() / 60)

def display_user_login():
    """
    Display user PIN login interface
    
    Returns:
        bool: True if user is authenticated
    """
    security_manager = SecurityManager()
    
    # Check if user is already authenticated and session is valid
    if security_manager.check_user_access():
        return True
    
    # Display login interface
    st.markdown("""
    <div style="text-align: center; padding: 2rem;">
        <h1>🚁 CrewOps 360 🚑</h1>
        <p>Enter the 4-digit access code to continue (same as duty phone unlock)</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Check if locked out
    if security_manager.is_locked_out():
        remaining_time = security_manager.get_remaining_lockout_time()
        st.error(f"🔒 **Access Temporarily Blocked**")
        st.warning(f"Too many failed attempts. Please wait {remaining_time} minutes before trying again.")
        
        # Add a refresh button
        if st.button("Check Access Status", use_container_width=True):
            st.rerun()
        
        return False
    
    # Create centered login form
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        with st.container():
            # PIN input with custom styling
            st.markdown("""
            <style>
            .pin-input {
                text-align: center;
                font-size: 2rem;
                letter-spacing: 1rem;
            }
            </style>
            """, unsafe_allow_html=True)
            
            # PIN input + submit in a form, so pressing Enter in the field submits
            # too instead of requiring a separate click on "Access System".
            with st.form("login_form"):
                entered_pin = st.text_input(
                    "Access Code",
                    type="password",
                    max_chars=4,
                    placeholder="Enter 4-digit code (same as duty phone unlock)",
                    help="Contact your supervisor if you need the access code",
                    key="user_pin_input"
                )
                login_clicked = st.form_submit_button("Access System", use_container_width=True, type="primary")

            # Process login attempt
            if login_clicked:
                if len(entered_pin) == 4 and entered_pin.isdigit():
                    success = security_manager.authenticate_user(entered_pin)
                    
                    if success:
                        st.success("✅ Access granted! Loading application...")
                        time.sleep(1)  # Brief pause for user feedback
                        st.rerun()
                    else:
                        failed_attempts = st.session_state.failed_attempts
                        remaining_attempts = security_manager.MAX_FAILED_ATTEMPTS - failed_attempts
                        
                        if remaining_attempts > 0:
                            st.error(f"❌ Invalid access code. {remaining_attempts} attempts remaining.")
                        else:
                            st.error("🔒 Access blocked due to too many failed attempts.")
                        
                        # Clear the input
                        time.sleep(2)
                        st.rerun()
                else:
                    st.error("Please enter a 4-digit numerical code.")
            
            # Display failed attempts warning
            if st.session_state.failed_attempts > 0 and not security_manager.is_locked_out():
                failed_attempts = st.session_state.failed_attempts
                remaining_attempts = security_manager.MAX_FAILED_ATTEMPTS - failed_attempts
                
                if remaining_attempts <= 2:
                    st.warning(f"⚠️ Warning: {remaining_attempts} attempts remaining before lockout.")
    
    # Footer information
    st.markdown("""
    <div style="text-align: center; margin-top: 3rem; color: #666;">
        <p><small>Authorized personnel only. All access is logged.</small></p>
    </div>
    """, unsafe_allow_html=True)
    
    return False

def display_session_info():
    """Display session information for authenticated users"""
    security_manager = SecurityManager()
    
    if st.session_state.user_authenticated:
        remaining_time = security_manager.get_session_remaining_time()
        
        if remaining_time <= 15:  # Warning when less than 15 minutes remain
            st.warning(f"⏰ Session expires in {remaining_time} minutes")
        
        # Add logout button in sidebar
        with st.sidebar:
            st.markdown("---")
            st.markdown("### Session")
            st.info(f"⏱️ Session: {remaining_time} min remaining")
            
            if st.button("🚪 Logout", use_container_width=True):
                security_manager.logout_user()
                st.success("Logged out successfully")
                time.sleep(1)
                st.rerun()

def require_user_authentication(func):
    """
    Decorator to require user authentication for functions
    
    Args:
        func: Function to protect
        
    Returns:
        Wrapped function that checks authentication
    """
    def wrapper(*args, **kwargs):
        if display_user_login():
            return func(*args, **kwargs)
        else:
            return None
    
    return wrapper

# Create global security manager instance
security_manager = SecurityManager()
