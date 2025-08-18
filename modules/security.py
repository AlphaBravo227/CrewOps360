# modules/security.py
"""
Security module for user authentication and access control
Handles both user PIN authentication and admin password verification
"""

import streamlit as st
import hashlib
import time
from datetime import datetime, timedelta

class SecurityManager:
    """Manage user authentication and security"""
    
    def __init__(self):
        # Security configuration
        self.USER_PIN = "2711"  # Four-digit PIN for users
        self.ADMIN_PASSWORD = "PW"  # Admin password remains the same
        
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
        Authenticate admin with password
        
        Args:
            entered_password (str): Password entered by admin
            
        Returns:
            bool: True if authentication successful
        """
        if entered_password == self.ADMIN_PASSWORD:
            st.session_state.admin_authenticated = True
            return True
        return False
    
    def check_user_access(self):
        """
        Check if user has valid access to the application
        
        Returns:
            bool: True if user can access the application
        """
        # Check if session expired
        if self.is_session_expired():
            st.session_state.user_authenticated = False
            st.session_state.auth_timestamp = None
            return False
        
        return st.session_state.user_authenticated
    
    def logout_user(self):
        """Logout user and clear authentication"""
        st.session_state.user_authenticated = False
        st.session_state.auth_timestamp = None
    
    def logout_admin(self):
        """Logout admin"""
        st.session_state.admin_authenticated = False
    
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
        <h1>🚁 Clinical Track Hub 🚁</h1>
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
            
            # PIN input field
            entered_pin = st.text_input(
                "Access Code",
                type="password",
                max_chars=4,
                placeholder="Enter 4-digit code (same as duty phone unlock)",
                help="Contact your supervisor if you need the access code",
                key="user_pin_input"
            )
            
            # Login button
            login_clicked = st.button("Access System", use_container_width=True, type="primary")
            
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

def check_admin_access(password):
    """
    Check admin access with password
    
    Args:
        password (str): Entered admin password
        
    Returns:
        bool: True if admin authenticated
    """
    security_manager = SecurityManager()
    return security_manager.authenticate_admin(password)

# Create global security manager instance
security_manager = SecurityManager()
