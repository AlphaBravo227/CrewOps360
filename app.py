# app.py - CrewOps360 Main Application - Complete Integrated System
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import glob
import sqlite3
import json
import hashlib
from io import BytesIO
import base64

# Calendar export functionality
try:
    from modules.calendar_export import (
        check_database_exists,
        extract_staff_names_from_db,
        get_all_staff_schedules,
        generate_calendar_for_staff,
        preview_schedule,
        get_fiscal_year_info
    )
    CALENDAR_EXPORT_AVAILABLE = True
except ImportError as e:
    CALENDAR_EXPORT_AVAILABLE = False
    print(f"Calendar export functionality not available: {e}")

# Import modules with correct paths based on original working app
try:
    from modules.fiscal_year import add_fiscal_year_display_to_app, add_fiscal_year_export_to_admin
except ImportError:
    # Create stub functions if fiscal year module doesn't exist
    def add_fiscal_year_display_to_app():
        pass
    def add_fiscal_year_export_to_admin():
        pass

from modules.db_utils import initialize_database
# Import existing modules that actually work
from modules.security import display_user_login, display_session_info, check_admin_access
from modules.shift_definitions import day_shifts, night_shifts
from modules.shift_utils import get_shift_end_time, calculate_rest_conflict
from modules.staff_utils import is_special_conflict
from modules.ui_components import display_roster_results
from modules.column_mapper import auto_detect_columns
from modules.track_management import display_staff_track_interface
from modules.pdf_generator import generate_schedule_pdf
from modules.export_utils import export_tracks_to_excel, export_track_history_to_excel
from modules.enhanced_track_validator import validate_track_comprehensive
from modules.enhanced_validation_display import display_comprehensive_validation
from modules.preference_editor import initialize_preference_tables
from modules.admin_export import integrate_admin_export_in_sidebar
from modules.track_source_consistency import ensure_track_source_consistency
from modules.app_helper import validate_uploaded_database, restore_database_from_backup, restore_database_from_upload, cleanup_old_backups
from modules.track_display import display_track_viewer
from modules.enhanced_landing import inject_custom_css
from modules.track_swap import display_track_swap_section, handle_track_swap_navigation

# Import training modules with new unified database approach
try:
    from training_modules.unified_database import UnifiedDatabase
    from training_modules.excel_handler import ExcelHandler
    from training_modules.enrollment_manager import EnrollmentManager
    from training_modules.ui_components import UIComponents as TrainingUIComponents
    from training_modules.track_manager import TrainingTrackManager
    from training_modules.admin_access import AdminAccess
    from training_modules.admin_excel_functions import ExcelAdminFunctions, enhance_admin_reports
    TRAINING_MODULES_AVAILABLE = True
except ImportError as e:
    TRAINING_MODULES_AVAILABLE = False
    print(f"Training modules not available: {e}")

# Set page config - MUST BE FIRST STREAMLIT COMMAND
st.set_page_config(
    page_title="CrewOps360", 
    page_icon="🚁",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Inject custom CSS for enhanced styling
inject_custom_css()

# Additional CSS for CrewOps360 branding
st.markdown("""
<style>
.crewops-header {
    text-align: center;
    padding: 2rem 0;
    background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
    border-radius: 15px;
    margin-bottom: 2rem;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.module-card {
    border: 2px solid #1E88E5;
    border-radius: 15px;
    padding: 2rem;
    margin-bottom: 2rem;
    background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
    cursor: pointer;
}

.module-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 8px 25px rgba(30, 136, 229, 0.3);
}

.module-card-secondary {
    background: linear-gradient(135deg, #F3E5F5 0%, #E1BEE7 100%);
    border-color: #9C27B0;
}

.back-button {
    position: fixed;
    top: 20px;
    left: 20px;
    z-index: 1000;
    background: #1E88E5;
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 25px;
    font-weight: bold;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
    cursor: pointer;
    transition: all 0.3s ease;
}

.back-button:hover {
    background: #1565C0;
    transform: translateY(-2px);
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.3);
}

.training-header {
    text-align: center;
    padding: 2rem 0;
    background: linear-gradient(135deg, #F3E5F5 0%, #E1BEE7 100%);
    border-radius: 15px;
    margin-bottom: 2rem;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}
</style>
""", unsafe_allow_html=True)

# Initialize session state for navigation
if 'selected_module' not in st.session_state:
    st.session_state.selected_module = None

if 'show_main_landing' not in st.session_state:
    st.session_state.show_main_landing = False

def display_crewops360_header():
    st.markdown("")
    st.markdown("")
    st.markdown("""
    <div class="crewops-header">
        <h1 style="color: #1E88E5; font-size: 3.5rem; font-weight: 700; margin-bottom: 0.5rem;">
            🚁 CrewOps360 🚑
        </h1>
        <p style="color: #666; font-size: 1.3rem; margin-bottom: 0;">
            Comprehensive Crew Operations Management Platform
        </p>
    </div>
    """, unsafe_allow_html=True)

def display_training_header():
    """Display the Training & Events header"""
    st.markdown("""
    <div class="training-header">
        <h1 style="color: #9C27B0; font-size: 3.5rem; font-weight: 700; margin-bottom: 0.5rem;">
            📚 Training & Events
        </h1>
        <p style="color: #666; font-size: 1.3rem; margin-bottom: 0;">
            Education Class Enrollment System
        </p>
    </div>
    """, unsafe_allow_html=True)

def display_module_selection():
    """Display the main module selection page"""
    display_crewops360_header()
    
    # Create centered layout
    col1, col2, col3 = st.columns([1, 3, 1])
    
    with col2:
        st.markdown("### 🎯 Select Module")
        st.markdown("---")
        
        # Clinical Track Hub Module
        st.markdown("""
        <div class="module-card">
            <div style="text-align: center;">
                <h2 style="color: #1E88E5; margin-bottom: 1rem;">🚁 Clinical Track Hub</h2>
                <p style="color: #333; font-size: 1.1rem; margin-bottom: 1.5rem; line-height: 1.6;">
                    Manage clinical staff schedules, track preferences, validate shift assignments, 
                    and generate calendar exports for flight operations.
                </p>
                <ul style="text-align: left; color: #555; margin-bottom: 2rem;">
                    <li>📋 Staff track management and validation</li>
                    <li>📅 Calendar export functionality</li>
                    <li>🔄 Track swapping and modifications</li>
                    <li>📊 Comprehensive reporting and analytics</li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🚁 Enter Clinical Track Hub", use_container_width=True, key="clinical_hub_btn"):
            st.session_state.selected_module = "clinical_track_hub"
            st.rerun()
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Training & Events Registration Module
        training_status = "Available" if TRAINING_MODULES_AVAILABLE else "Setup Required"
        st.markdown(f"""
        <div class="module-card module-card-secondary">
            <div style="text-align: center;">
                <h2 style="color: #9C27B0; margin-bottom: 1rem;">📚 Training & Events Registration</h2>
                <p style="color: #333; font-size: 1.1rem; margin-bottom: 1.5rem; line-height: 1.6;">
                    Register for training programs, continuing education, and company events. 
                    Track certifications and compliance requirements.
                </p>
                <ul style="text-align: left; color: #555; margin-bottom: 2rem;">
                    <li>🎓 Training course registration</li>
                    <li>🎉 Company event sign-ups</li>
                    <li>📈 Progress monitoring</li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        training_button_disabled = not TRAINING_MODULES_AVAILABLE
        if st.button("📚 Enter Training & Events", use_container_width=True, 
                    key="training_btn", disabled=training_button_disabled):
            if TRAINING_MODULES_AVAILABLE:
                st.session_state.selected_module = "training_events"
                st.rerun()
            else:
                st.error("Training modules are not properly configured. Please check the training folder setup.")

# Enhanced Training Events App Section with Educator Signup
# This replaces the display_training_events_app() function in app.py

def display_training_events_app():
    st.markdown("")
    st.markdown("")
    
    # Back button
    if st.button("← Back to CrewOps360", key="back_from_training"):
        st.session_state.selected_module = None
        st.rerun()
    
    display_training_header()
    
    if not TRAINING_MODULES_AVAILABLE:
        st.error("Training modules are not available. Please ensure all training files are properly configured.")
        return
    
    # Initialize unified database and training components
    try:
        # Initialize unified database (uses main medflight_tracks.db)
        if 'unified_db' not in st.session_state:
            st.session_state.unified_db = UnifiedDatabase('data/medflight_tracks.db')
            st.session_state.unified_db.initialize_training_tables()

        # Initialize Excel handler
        if 'training_excel_handler' not in st.session_state:
            excel_path = 'training/upload/MASTER Education Classes Roster.xlsx'
            
            if not os.path.exists(excel_path):
                st.error(f"Excel file not found: {excel_path}")
                st.info("Please ensure the 'MASTER Education Classes Roster.xlsx' file is in the training/upload folder")
                return
            
            st.session_state.training_excel_handler = ExcelHandler(excel_path)
            
            if st.session_state.training_excel_handler.load_error:
                st.error(f"Error loading Excel file: {st.session_state.training_excel_handler.load_error}")
                return

        # Initialize training track manager (uses main database now)
        if 'training_track_manager' not in st.session_state:
            st.session_state.training_track_manager = TrainingTrackManager('data/medflight_tracks.db')

        # Initialize enrollment manager
        if 'training_enrollment_manager' not in st.session_state:
            st.session_state.training_enrollment_manager = EnrollmentManager(
                st.session_state.unified_db,
                st.session_state.training_excel_handler,
                st.session_state.training_track_manager
            )

        # Initialize educator manager - NEW
        if 'training_educator_manager' not in st.session_state:
            from training_modules.educator_manager import EducatorManager
            st.session_state.training_educator_manager = EducatorManager(
                st.session_state.unified_db,
                st.session_state.training_excel_handler,
                st.session_state.training_track_manager
            )

        # Integrate CCEMT schedules after both components are initialized
        if hasattr(st.session_state.training_track_manager, 'set_excel_handler'):
            st.session_state.training_track_manager.set_excel_handler(
                st.session_state.training_excel_handler
            )
            print("CCEMT schedule integration completed")

        # Initialize admin access
        if 'training_admin_access' not in st.session_state:
            st.session_state.training_admin_access = AdminAccess()

        # Initialize enhanced admin functions with educator manager
        if 'training_excel_admin_functions' not in st.session_state:
            st.session_state.training_excel_admin_functions = ExcelAdminFunctions(
                st.session_state.training_excel_handler,
                st.session_state.training_enrollment_manager,
                st.session_state.unified_db,
                st.session_state.training_educator_manager  # Pass educator manager
            )
            
            # Connect admin functions to admin access
            st.session_state.training_admin_access.initialize_admin_functions(
                st.session_state.training_excel_admin_functions
            )

    except Exception as e:
        st.error(f"Error initializing training components: {str(e)}")
        return

    # Show admin access in sidebar (for administrators only)
    st.session_state.training_admin_access.show_admin_access_button()
    
    # Check if admin function page should be displayed - ONLY block if admin is authenticated AND viewing admin page
    if (st.session_state.training_admin_access.is_admin_authenticated() and 
        st.session_state.get('training_admin_show_function', False)):
        # Admin dashboard is being displayed, don't show regular content
        st.session_state.training_admin_access.show_admin_function_page()
        return

    # Add track database status to sidebar
    with st.sidebar:
        st.subheader("📊 Track Database Status")
        if st.session_state.training_track_manager.tracks_db_path:
            st.success(f"✅ Track database loaded")
            st.info(f"Found {len(st.session_state.training_track_manager.tracks_cache)} staff tracks")
            
            if st.button("🔄 Reload Tracks"):
                st.session_state.training_track_manager.reload_tracks()
                st.rerun()
        else:
            st.warning("⚠️ No track database found")

    # USER INTERFACE - This should be accessible to all authenticated users
    # Staff selection
    staff_list = st.session_state.training_excel_handler.get_staff_list()
    selected_staff = st.selectbox(
        "Select Your Name:",
        options=[""] + staff_list,
        key="training_staff_selector"
    )

    if selected_staff:
        # Check if track data is available for this staff member
        if (st.session_state.training_track_manager and 
            not st.session_state.training_track_manager.has_track_data(selected_staff)):
            st.warning("⚠️ No track schedule found for your profile. Schedule conflict checking is disabled.")
        
        # Get assigned classes and enrollment status
        assigned_classes = st.session_state.training_excel_handler.get_assigned_classes(selected_staff)
        enrolled_classes = st.session_state.training_enrollment_manager.get_enrolled_classes(selected_staff)
        live_meeting_count = st.session_state.training_enrollment_manager.get_live_staff_meeting_count(selected_staff)
        
        # Get educator signup metrics - NEW
        educator_signups = st.session_state.training_educator_manager.get_staff_educator_signups(selected_staff)
        
        # Display enrollment summary with LIVE meeting metric and educator metrics
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("Total Assigned Classes", len(assigned_classes))
        with col2:
            st.metric("Classes Enrolled", len(enrolled_classes))
        with col3:
            st.metric("Classes Remaining", len(assigned_classes) - len(enrolled_classes))
        with col4:
            # Check if user has any staff meetings assigned
            has_staff_meetings = any(st.session_state.training_excel_handler.is_staff_meeting(cls) for cls in assigned_classes)
            if has_staff_meetings:
                st.metric("FY26 LIVE Staff Meetings", f"{live_meeting_count}/2")
                if live_meeting_count >= 2:
                    st.success("✅ LIVE meeting requirement met!")
                else:
                    st.info(f"📝 Need {2 - live_meeting_count} more LIVE meeting(s)")
            else:
                st.metric("LIVE Meetings", "N/A")
        with col5:
            st.metric("Educator Signups", len(educator_signups))
        
        st.markdown("---")
        
        # Tabs for different views - ENHANCED WITH EDUCATOR TAB
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📝 Enroll in Classes", "📋 My Enrollments", "📊 Class Details", "📚 Educator Signup", "📅 Track Schedule"])
        
        with tab1:
            # Enroll in Classes Tab (existing functionality)
            st.header("📝 Enroll in Classes")
            
            if not assigned_classes:
                st.info("You have no classes assigned at this time.")
            else:
                # Display ALL assigned classes with enrollment status
                for class_name in assigned_classes:
                    # Get enrollment status for this class
                    from training_modules.ui_components import UIComponents as TrainingUIComponents
                    enrollment_status = TrainingUIComponents.get_class_enrollment_status(
                        st.session_state.training_enrollment_manager, 
                        selected_staff, 
                        class_name, 
                        st.session_state.training_excel_handler
                    )
                    
                    # Determine if class is enrolled and create appropriate display
                    is_enrolled = class_name in enrolled_classes
                    
                    # Create the display text with enrollment status
                    if is_enrolled:
                        if enrollment_status:
                            display_text = f"**{class_name}** {enrollment_status}"
                        else:
                            display_text = f"**{class_name}** ✅ Enrolled"
                        expanded_default = False  # Collapsed for enrolled classes
                    else:
                        display_text = f"**{class_name}**"
                        expanded_default = False  # Keep collapsed by default
                    
                    # Show class in expander
                    with st.expander(display_text, expanded=expanded_default):
                        
                        # SHOW ENROLLMENT STATUS FIRST - PRIORITY INFORMATION
                        if is_enrolled:
                            # Show current enrollment details at the top
                            st.markdown("### 📋 Your Current Enrollment")
                            enrollments = st.session_state.training_enrollment_manager.get_staff_enrollments(selected_staff)
                            class_enrollments = [e for e in enrollments if e['class_name'] == class_name]
                            
                            if class_enrollments:
                                for enrollment in class_enrollments:
                                    col1, col2, col3 = st.columns([2, 2, 1])
                                    
                                    with col1:
                                        st.write(f"**Date:** {enrollment['class_date']}")
                                        if enrollment.get('session_time'):
                                            st.write(f"**Session:** {enrollment['session_time']}")
                                    
                                    with col2:
                                        if enrollment['role'] != 'General':
                                            st.write(f"**Role:** {enrollment['role']}")
                                        
                                        # Show meeting type for staff meetings
                                        if st.session_state.training_excel_handler.is_staff_meeting(class_name):
                                            meeting_type = enrollment.get('meeting_type', 'Virtual')
                                            if meeting_type == 'LIVE':
                                                st.write("**Type:** 🔴 LIVE")
                                            else:
                                                st.write("**Type:** 💻 Virtual")
                                        
                                        # Show conflict indicator
                                        if enrollment.get('conflict_override'):
                                            st.warning("⚠️ Schedule conflict - swap required")
                                    
                                    with col3:
                                        if st.button("Cancel", key=f"cancel_enroll_{enrollment['id']}"):
                                            if st.session_state.training_enrollment_manager.cancel_enrollment(enrollment['id']):
                                                st.success("Enrollment cancelled!")
                                                st.rerun()
                                            else:
                                                st.error("Error cancelling enrollment")
                                    
                                    st.markdown("---")
                            else:
                                st.error("Error: Enrollment status inconsistent")
                        
                        # CLASS DETAILS SECTION - SECONDARY INFORMATION
                        class_details = st.session_state.training_excel_handler.get_class_details(class_name)
                        
                        if class_details:
                            # Show class details in a collapsible section to reduce visual clutter
                            with st.expander("📚 Class Details & Information", expanded=False):
                                TrainingUIComponents.display_class_info(class_details)
                            
                            # Get available dates for this class
                            available_dates = st.session_state.training_excel_handler.get_class_dates(class_name)
                            
                            if available_dates:
                                if is_enrolled:
                                    # Show additional enrollment options for enrolled users
                                    st.markdown("### Sessions Available")
                                    TrainingUIComponents.display_session_enrollment_options_with_tracks(
                                        st.session_state.training_enrollment_manager,
                                        class_name,
                                        available_dates,
                                        selected_staff,
                                        st.session_state.training_track_manager
                                    )
                                else:
                                    # Show enrollment options for unenrolled classes
                                    st.markdown("### 📅 Available Sessions")
                                    st.info("Select a session to enroll in this class.")
                                    TrainingUIComponents.display_session_enrollment_options_with_tracks(
                                        st.session_state.training_enrollment_manager,
                                        class_name,
                                        available_dates,
                                        selected_staff,
                                        st.session_state.training_track_manager
                                    )
                            else:
                                st.warning("No available dates found for this class.")
                        else:
                            st.error("Class details not found.")

        with tab2:
            # My Enrollments Tab (existing functionality)
            st.header("📋 My Enrollments")
            
            enrollments = st.session_state.training_enrollment_manager.get_staff_enrollments(selected_staff)
            
            if not enrollments:
                st.info("You are not currently enrolled in any classes.")
            else:
                st.write(f"**You are enrolled in {len(enrollments)} class session(s):**")
                
                for enrollment in enrollments:
                    with st.container():
                        # Display enrollment with cancel option
                        if TrainingUIComponents.display_enrollment_row(
                            enrollment, 
                            st.session_state.training_excel_handler, 
                            st.session_state.training_enrollment_manager
                        ):
                            # Handle cancellation
                            if st.session_state.training_enrollment_manager.cancel_enrollment(enrollment['id']):
                                st.success("Enrollment cancelled successfully!")
                                st.rerun()
                            else:
                                st.error("Error cancelling enrollment.")
            
            # NEW: Add educator enrollments section
            st.markdown("---")
            st.markdown("### 👨‍🏫 Your Educator Signups")
            
            from training_modules.educator_ui_components import EducatorUIComponents
            EducatorUIComponents.display_staff_educator_enrollments(
                st.session_state.training_educator_manager,
                selected_staff
            )
        
        with tab3:
            # Class Details Tab (existing functionality enhanced)
            st.header("📊 Class Details")
            
            if assigned_classes:
                # Class selector
                selected_class = st.selectbox(
                    "Select a class to view details:",
                    options=assigned_classes,
                    key="class_details_selector"
                )
                
                if selected_class:
                    class_details = st.session_state.training_excel_handler.get_class_details(selected_class)
                    
                    if class_details:
                        # Display detailed class information
                        TrainingUIComponents.display_class_info(class_details)
                        
                        # Show enrollment summary
                        enrollment_summary = st.session_state.training_enrollment_manager.get_class_enrollment_summary(selected_class)
                        TrainingUIComponents.display_enrollment_summary(enrollment_summary, class_details)
                        
                        # NEW: Show educator summary if class needs educators
                        if st.session_state.training_excel_handler.needs_educators(selected_class):
                            st.markdown("---")
                            st.write("### 👨‍🏫 Educator Coverage")
                            EducatorUIComponents.display_class_educator_summary(
                                st.session_state.training_educator_manager,
                                selected_class
                            )
                        
                        # Show track conflicts if available
                        if st.session_state.training_track_manager.tracks_db_path:
                            try:
                                # For now, just show that track conflict checking is available
                                st.write("**Track Schedule Integration:**")
                                st.info("✅ Track database connected - schedule conflicts will be checked during enrollment")
                                
                                # Optional: Show number of staff with track data
                                all_staff_with_tracks = st.session_state.training_track_manager.get_all_staff_with_tracks()
                                if all_staff_with_tracks:
                                    st.write(f"📊 Track data available for {len(all_staff_with_tracks)} staff members")
                                else:
                                    st.warning("⚠️ No track data found in database")
                                    
                            except Exception as e:
                                st.error(f"Error accessing track data: {str(e)}")
                        else:
                            st.warning("⚠️ Track database not available - schedule conflicts cannot be checked")
            else:
                st.info("You have no classes assigned at this time.")
        
        with tab4:
            # NEW: Educator Signup Tab
            st.header("📚 Educator Signup")
            st.caption("Sign up to be part of the education staff for classes")
            
            # Display educator metrics
            EducatorUIComponents.display_educator_metrics(
                st.session_state.training_educator_manager,
                selected_staff
            )
            
            st.markdown("---")
            
            # Display available educator opportunities
            EducatorUIComponents.display_educator_opportunities(
                st.session_state.training_educator_manager,
                selected_staff
            )
        
        with tab5:
            # Track Schedule Tab (existing functionality)
            st.header("📅 Track Schedule")
            
            if st.session_state.training_track_manager.tracks_db_path:
                if st.session_state.training_track_manager.has_track_data(selected_staff):
                    st.info("Track schedule integration coming soon - will show your work schedule alongside training commitments.")
                else:
                    st.warning("No track schedule found for your profile.")
            else:
                st.warning("Track database not available.")
        
    else:
        st.info("Please select your name from the dropdown above to get started.")

# Additional helper function for admin integration
def initialize_training_admin_components():
    """Initialize all training admin components if not already done"""
    if not TRAINING_MODULES_AVAILABLE:
        return False
    
    try:
        # Check if all components are initialized
        required_components = [
            'unified_db',
            'training_excel_handler', 
            'training_track_manager',
            'training_enrollment_manager',
            'training_admin_access',
            'training_excel_admin_functions'
        ]
        
        for component in required_components:
            if component not in st.session_state:
                return False
        
        return True
        
    except Exception as e:
        st.error(f"Error checking training components: {str(e)}")
        return False

def display_clinical_track_hub():
    """Display the Clinical Track Hub with back navigation - FIXED spacing and button issues"""
    
    # Add minimal top margin to prevent button cutoff
    st.markdown("")
    st.markdown("")
    
    # Simple back button that works properly
    if st.button("← Back to CrewOps360", key="back_from_clinical"):
        st.session_state.selected_module = None
        st.rerun()
    
    # Original Clinical Track Hub content with proper spacing
    st.markdown("""
    # <span style='color:#1E88E5'>Clinical Track Hub</span>
    """, unsafe_allow_html=True)
    
    # All the existing Clinical Track Hub functionality goes here
    run_clinical_track_hub()

def run_clinical_track_hub():
    """Run the original Clinical Track Hub functionality"""
    # Create wrapper classes for compatibility with new app structure
    class TrainingTrackManager:
        """Track manager wrapper using existing functionality"""
        
        def __init__(self):
            self.tracks = {}
            self.preferences = {}
            self.requirements = {}
            
        def load_preferences(self, preferences_df):
            """Load staff preferences"""
            self.preferences = preferences_df
            return True
            
        def load_tracks(self, tracks_df):
            """Load current tracks"""
            self.tracks = tracks_df
            return True
            
        def load_requirements(self, requirements_df):
            """Load requirements"""
            self.requirements = requirements_df
            return True
            
        def get_track_statistics(self):
            """Get basic track statistics"""
            return {
                "total_tracks": len(self.tracks) if hasattr(self.tracks, '__len__') else 0,
                "valid_tracks": 0,
                "pending_tracks": 0
            }

    class ScheduleOptimizer:
        """Schedule optimizer wrapper using existing functionality"""
        
        def __init__(self):
            self.preferences = None
            self.constraints = {}
            
        def set_preferences(self, preferences_df):
            """Set staff preferences"""
            self.preferences = preferences_df
            
        def set_constraints(self, constraints):
            """Set scheduling constraints"""
            self.constraints = constraints
            
        def optimize_schedule(self):
            """Use existing hypothetical scheduler"""
            try:
                from modules.hypothetical_scheduler_new import generate_hypothetical_schedule_new
                return {"status": "success", "message": "Use existing hypothetical scheduler"}
            except ImportError:
                return {"status": "error", "message": "Hypothetical scheduler not available"}
            
        def get_schedule_recommendations(self, staff_name):
            """Get recommendations using existing functionality"""
            return {"recommendations": [], "message": "Use existing recommendation system"}

    class PatternValidator:
        """Pattern validator wrapper using existing functionality"""
        
        def validate_pattern(self, track_data):
            """Validate shift pattern using existing validation"""
            if not track_data:
                return False, ["No track data provided"]
            
            try:
                validation_result = validate_track_comprehensive(track_data)
                is_valid = validation_result.get('overall_valid', False)
                
                warnings = []
                if not is_valid:
                    for key, result in validation_result.items():
                        if key != 'overall_valid' and isinstance(result, dict) and not result.get('status', True):
                            warnings.extend(result.get('issues', []))
                
                return is_valid, warnings
                
            except Exception as e:
                return False, [f"Validation error: {str(e)}"]
        
        def validate_rest_requirements(self, track_data):
            """Validate rest requirements using existing functionality"""
            try:
                from modules.track_validator import check_rest_requirements
                violations = check_rest_requirements(track_data)
                return violations
            except ImportError:
                return []
        
        def get_pattern_recommendations(self, track_data):
            """Get pattern recommendations"""
            recommendations = []
            
            if not track_data:
                return recommendations
            
            day_shifts = sum(1 for shift in track_data.values() if shift == 'D')
            night_shifts = sum(1 for shift in track_data.values() if shift == 'N')
            
            if day_shifts > night_shifts * 2:
                recommendations.append("Consider balancing day and night shifts more evenly")
            
            if night_shifts > day_shifts * 2:
                recommendations.append("Consider adding more day shifts for better balance")
            
            return recommendations

    def validate_and_show_warnings(track_data, requirements=None):
        """Validation wrapper using existing comprehensive validation"""
        if not track_data:
            st.warning("No track data provided")
            return False
        
        try:
            validation_result = validate_track_comprehensive(
                track_data,
                shifts_per_pay_period=requirements.get('shifts_per_pay_period', 14) if requirements else 14,
                night_minimum=requirements.get('night_minimum', 5) if requirements else 5,
                weekend_minimum=requirements.get('weekend_minimum', 5) if requirements else 5
            )
            
            is_valid = validation_result.get('overall_valid', False)
            
            if not is_valid:
                for key, result in validation_result.items():
                    if key != 'overall_valid' and isinstance(result, dict) and not result.get('status', True):
                        for issue in result.get('issues', []):
                            st.warning(issue)
            
            return is_valid
        except Exception as e:
            st.error(f"Validation error: {str(e)}")
            return False

    def manually_convert_tracks_excel_to_db(tracks_file_path):
        """
        Manually convert Tracks.xlsx to medflight_tracks.db
        Clears existing tracks and replaces with Excel data
        """
        try:
            import json
            from datetime import datetime
            
            tracks_df = pd.read_excel(tracks_file_path)
            
            if tracks_df.empty:
                return False, "Excel file is empty or could not be read"
            
            columns = tracks_df.columns.tolist()
            staff_col = columns[0]
            day_columns = columns[1:]
            
            if len(day_columns) < 42:
                return False, f"Expected at least 42 day columns, found {len(day_columns)}"
            
            initialize_database()
            
            db_path = 'data/medflight_tracks.db'
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM tracks")
            cursor.execute("DELETE FROM track_history")
            
            submission_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            conversion_count = 0
            error_count = 0
            
            for index, row in tracks_df.iterrows():
                try:
                    staff_name = str(row[staff_col]).strip()
                    
                    if not staff_name or staff_name.lower() in ['nan', 'none', '']:
                        continue
                    
                    track_data = {}
                    
                    for day_col in day_columns:
                        day_value = row[day_col]
                        
                        if pd.isna(day_value):
                            track_data[day_col] = ""
                        else:
                            track_data[day_col] = str(day_value).strip()
                    
                    track_json = json.dumps(track_data)
                    
                    cursor.execute('''
                        INSERT INTO tracks (
                            staff_name, track_data, submission_date, is_approved, 
                            version, is_active, track_source, has_preassignments, 
                            preassignment_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        staff_name,
                        track_json,
                        submission_date,
                        1,
                        1,
                        1,
                        "Preferred Track",
                        0,
                        0
                    ))
                    
                    track_id = cursor.lastrowid
                    cursor.execute('''
                        INSERT INTO track_history (
                            track_id, staff_name, track_data, submission_date, status
                        ) VALUES (?, ?, ?, ?, ?)
                    ''', (
                        track_id,
                        staff_name,
                        track_json,
                        submission_date,
                        "Manual Import from Excel"
                    ))
                    
                    conversion_count += 1
                    
                except Exception as row_error:
                    error_count += 1
                    print(f"Error processing row {index} for staff '{staff_name}': {str(row_error)}")
                    continue
            
            conn.commit()
            conn.close()
            
            if conversion_count > 0:
                success_message = f"Successfully converted {conversion_count} staff tracks to database"
                if error_count > 0:
                    success_message += f" ({error_count} rows had errors and were skipped)"
                return True, success_message
            else:
                return False, f"No tracks were converted. {error_count} rows had errors."
                
        except Exception as e:
            return False, f"Error during manual conversion: {str(e)}"

    # Add verify_database_integrity function if it doesn't exist
    try:
        from modules.db_utils import verify_database_integrity
    except ImportError:
        def verify_database_integrity():
            """
            Verify the integrity of the database structure and data
            """
            try:
                conn = sqlite3.connect('data/medflight_tracks.db')
                cursor = conn.cursor()
                
                # Test basic connectivity
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result[0] != 1:
                    return False
                
                # Check if required tables exist
                required_tables = ['tracks', 'track_history']
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing_tables = [table[0] for table in cursor.fetchall()]
                
                missing_tables = [table for table in required_tables if table not in existing_tables]
                if missing_tables:
                    return False
                
                # Check tracks table structure
                cursor.execute("PRAGMA table_info(tracks)")
                tracks_columns = [column[1] for column in cursor.fetchall()]
                required_columns = ['id', 'staff_name', 'track_data', 'submission_date']
                missing_columns = [col for col in required_columns if col not in tracks_columns]
                if missing_columns:
                    return False
                
                # Test data integrity - check for corrupted JSON
                cursor.execute("SELECT id, staff_name, track_data FROM tracks WHERE is_active = 1")
                tracks = cursor.fetchall()
                
                for track_id, staff_name, track_data in tracks:
                    try:
                        json.loads(track_data)
                    except json.JSONDecodeError:
                        return False
                
                conn.close()
                return True
                
            except Exception as e:
                print(f"Database integrity check failed: {str(e)}")
                return False

    def display_calendar_export_section():
        """
        Display the calendar export functionality in the main app.
        """
        if not CALENDAR_EXPORT_AVAILABLE:
            st.error("📅 Calendar export functionality is not available. Please install required dependencies.")
            return
        
        if not check_database_exists():
            st.warning("📅 No database found. Calendar export requires submitted tracks in the database.")
            return
        
        st.markdown("### 📅 Calendar Export")
        st.caption("Generate complete fiscal year Google Calendar or iCal files from submitted tracks")
        
        # Get available staff
        try:
            staff_names = extract_staff_names_from_db()
            
            if not staff_names:
                st.info("No staff tracks found in database. Submit some tracks first.")
                return
            
            col1, col2 = st.columns(2)
            
            with col1:
                selected_staff = st.selectbox(
                    "Select Staff Member",
                    options=staff_names,
                    key="calendar_export_staff_select"
                )
            
            with col2:
                calendar_format = st.selectbox(
                    "Calendar Format",
                    options=["Google Calendar (CSV)", "iCal (ICS)"],
                    key="calendar_format_select"
                )
            
            # Show fiscal year info
            fiscal_info = get_fiscal_year_info()
            st.info(f"📊 **Export Period:** 28 Sept 2025 through 26 Sept 2026")
            
            # Preview section
            if selected_staff:
                with st.expander("📋 Preview Schedule (First 14 Days)", expanded=False):
                    try:
                        schedule_data = get_all_staff_schedules()
                        if selected_staff in schedule_data:
                            preview = preview_schedule(selected_staff, schedule_data[selected_staff], num_days=14)
                            
                            preview_df = pd.DataFrame(preview)
                            preview_df['date'] = preview_df['date'].dt.strftime('%m/%d/%Y (%A)')
                            preview_df.columns = ['Date', 'Pattern Day', 'Shift']
                            
                            st.dataframe(preview_df, use_container_width=True, hide_index=True)
                        else:
                            st.warning("No schedule data found for this staff member.")
                    except Exception as e:
                        st.error(f"Error generating preview: {str(e)}")
                
                # Generate calendar file
                if st.button("📥 Generate Calendar", type="primary", use_container_width=True):
                    try:
                        format_type = "google" if "Google" in calendar_format else "ical"
                        
                        with st.spinner(f"Generating {calendar_format} file..."):
                            file_content, filename = generate_calendar_for_staff(selected_staff, format_type)
                        
                        if file_content and filename:
                            # Determine MIME type
                            mime_type = "text/csv" if format_type == "google" else "text/calendar"
                            
                            st.download_button(
                                label=f"📥 Download {filename}",
                                data=file_content,
                                file_name=filename,
                                mime=mime_type,
                                use_container_width=True
                            )
                            
                            st.success(f"✅ {calendar_format} file generated successfully!")
                            
                            # Show file info
                            st.info(f"📄 **File:** {filename}")
                            st.info(f"📊 **Size:** {len(file_content)} characters")
                            st.info(f"🗓️ **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                            
                        else:
                            st.error("❌ Failed to generate calendar file. Please check if the staff member has a valid track.")
                            
                    except Exception as e:
                        st.error(f"❌ Error generating calendar: {str(e)}")
            
            # Instructions
            with st.expander("📖 Import Instructions", expanded=False):
                if "Google" in calendar_format:
                    st.markdown("""
                    ### Google Calendar Import Instructions:
                    
                    1. **Download** the CSV file using the button above
                    2. **Open** Google Calendar in your web browser
                    3. **Click** the gear icon (⚙️) in the top right corner
                    4. **Select** "Settings" from the dropdown menu
                    5. **Click** "Import & export" in the left sidebar
                    6. **Click** "Select file from your computer"
                    7. **Choose** the downloaded CSV file
                    8. **Select** which calendar to add events to
                    9. **Click** "Import"
                    
                    **Note:** Events will appear as all-day events with just the shift code (D, N, etc.)
                    """)
                else:
                    st.markdown("""
                    ### iCal Import Instructions:
                    
                    **For Google Calendar:**
                    1. Download the ICS file
                    2. Open Google Calendar
                    3. Click the "+" next to "Other calendars"
                    4. Select "Import"
                    5. Choose the ICS file and import
                    
                    **For Apple Calendar:**
                    1. Download the ICS file
                    2. Double-click the file or drag it to Calendar app
                    3. Choose which calendar to import to
                    
                    **For Outlook:**
                    1. Download the ICS file
                    2. Open Outlook
                    3. Go to File > Open & Export > Import/Export
                    4. Choose "Import an iCalendar (.ics) or vCalendar file"
                    5. Select the downloaded file
                    
                    **Note:** Events will appear as all-day events with shift codes.
                    """)
        
        except Exception as e:
            st.error(f"Error loading calendar export: {str(e)}")

    # Function to detect data source format
    def detect_data_source_format(df):
        """Detect whether the DataFrame follows Database or Excel File format."""
        result = {
            "is_database_format": False,
            "staff_name_col": None,
            "first_day_col": None,
            "day_indices": []
        }
        
        if df is None or df.empty:
            return result
        
        cols = df.columns.tolist()
        
        if len(cols) > 1 and "STAFF NAME" in cols[0].upper():
            result["is_database_format"] = False
            result["staff_name_col"] = cols[0]
            result["first_day_col"] = 1
            result["day_indices"] = list(range(1, min(43, len(cols))))
            return result
        
        result["is_database_format"] = True
        result["staff_name_col"] = cols[0]
        result["first_day_col"] = 5
        result["day_indices"] = list(range(5, min(47, len(cols))))
        return result

    # Function to load Excel files
    def load_excel_files_from_directory():
        upload_dir = "upload files"
        files_found = {
            "preferences": None, 
            "current_tracks": None, 
            "requirements": None,
            "preassignments": None
        }
        
        if not os.path.exists(upload_dir):
            st.warning(f"Directory '{upload_dir}' not found. Creating directory...")
            os.makedirs(upload_dir)
            return files_found
        
        excel_files = glob.glob(os.path.join(upload_dir, "*.xlsx")) + glob.glob(os.path.join(upload_dir, "*.xls"))
        
        if not excel_files:
            st.warning(f"No Excel files found in '{upload_dir}' directory.")
            return files_found
        
        for file_path in excel_files:
            file_name = os.path.basename(file_path).lower()
            
            if "preference" in file_name and "preassign" not in file_name:
                files_found["preferences"] = file_path
            elif "track" in file_name and "preassign" not in file_name:
                files_found["current_tracks"] = file_path
            elif ("requirement" in file_name or "staff req" in file_name) and "preassign" not in file_name:
                files_found["requirements"] = file_path
            elif "preassign" in file_name:
                files_found["preassignments"] = file_path
        
        # Assign unidentified files to missing slots
        unassigned_files = [f for f in excel_files if f not in files_found.values()]
        
        if not files_found["preferences"] and unassigned_files:
            files_found["preferences"] = unassigned_files.pop(0)
        
        if not files_found["current_tracks"] and unassigned_files:
            files_found["current_tracks"] = unassigned_files.pop(0)
        
        if not files_found["requirements"] and unassigned_files:
            files_found["requirements"] = unassigned_files.pop(0)
        
        return files_found

    # Initialize database
    initialize_database()

    # Initialize preference editor tables
    try:
        initialize_preference_tables()
    except Exception as e:
        pass

    # Initialize session state for the Clinical Track Hub
    if 'track_manager' not in st.session_state:
        st.session_state.track_manager = TrainingTrackManager()

    if 'master_df' not in st.session_state:
        st.session_state.master_df = None
        st.session_state.days = None
        st.session_state.current_tracks_df = None
        st.session_state.staff_col_tracks = None
        st.session_state.assignment_reasons = None
        st.session_state.preferences_df = None
        st.session_state.staff_col_prefs = None
        st.session_state.role_col = None
        st.session_state.no_matrix_col = None
        st.session_state.reduced_rest_col = None
        st.session_state.seniority_col = None
        st.session_state.requirements_df = None
        st.session_state.max_day_nurses = 12
        st.session_state.max_day_medics = 12
        st.session_state.max_night_nurses = 5
        st.session_state.max_night_medics = 5
        st.session_state.enable_role_delta_filter = False
        st.session_state.day_delta_threshold = 3
        st.session_state.night_delta_threshold = 2
        st.session_state.preassignment_df = None

    if 'selected_staff' not in st.session_state:
        st.session_state.selected_staff = None

    if 'staff_track_active' not in st.session_state:
        st.session_state.staff_track_active = False

    # Load Excel files
    excel_files = load_excel_files_from_directory()

    # Load preassignments
    if excel_files["preassignments"]:
        try:
            preassignment_df = pd.read_excel(excel_files["preassignments"])
            
            staff_col = None
            for col in preassignment_df.columns:
                if isinstance(col, str) and "name" in col.lower() and "staff" in col.lower():
                    staff_col = col
                    break
                    
            if staff_col is None:
                staff_col = preassignment_df.columns[0]
            
            if preassignment_df.duplicated(staff_col).any():
                st.warning(f"Duplicate staff entries found in preassignments file. Using the first entry for each staff member.")
                
                preassignment_dict = {}
                for staff_name, group in preassignment_df.groupby(staff_col):
                    staff_dict = {}
                    first_row = group.iloc[0]
                    for col in group.columns:
                        if col != staff_col and pd.notna(first_row[col]) and str(first_row[col]).strip():
                            staff_dict[col] = str(first_row[col]).strip()
                    preassignment_dict[staff_name] = staff_dict
                
                preassignment_df = preassignment_dict
            else:
                preassignment_df = preassignment_df.set_index(staff_col)
                
            st.session_state.preassignment_df = preassignment_df
        except Exception as e:
            st.error(f"Error loading preassignments file: {str(e)}")
            preassignment_df = None
            st.session_state.preassignment_df = None
    else:
        preassignment_df = None
        st.session_state.preassignment_df = None

    # Sidebar with enhanced validation info and admin authentication
    with st.sidebar:
        st.markdown("## Admin Area")
        
        # Use the security module for admin authentication
        password = st.text_input("Enter admin password:", type="password")
        
        admin_authenticated = check_admin_access(password)
        
        if admin_authenticated:
            st.success("Admin access granted!")
            
            st.header("Data Files")
            
            # Display file loading status
            if excel_files["preferences"]:
                st.success(f"✅ Preferences file loaded: {os.path.basename(excel_files['preferences'])}")
            else:
                st.error("❌ Preferences file not found")

            if excel_files["current_tracks"]:
                st.success(f"✅ Current tracks file loaded: {os.path.basename(excel_files['current_tracks'])}")
            else:
                st.error("❌ Current tracks file not found")

            if excel_files["requirements"]:
                st.success(f"✅ Requirements file loaded: {os.path.basename(excel_files['requirements'])}")
            else:
                st.warning("⚠️ Requirements file not found (optional)")

            if excel_files["preassignments"]:
                st.success(f"✅ Preassignments file loaded: {os.path.basename(excel_files['preassignments'])}")
            else:
                st.warning("⚠️ Preassignments file not found (optional)")

            # Add export functionality
            if st.session_state.get('preferences_df') is not None:
                integrate_admin_export_in_sidebar(st.session_state.preferences_df)
            else:
                st.markdown("---")
                st.header("📤 Staff Preferences Export Center")
                st.info("📊 Export functionality will appear here once preferences file is processed.")
            
            # ADD THIS NEW SECTION HERE:
            st.markdown("---")
            add_fiscal_year_export_to_admin(admin_authenticated)

            st.header("Enhanced Validation Rules")
            st.markdown("""
            ### New Validation Features:
            - **Exact Pay Period Matching**: Each 14-day period must have exactly the required shifts
            - **Weekly Limits**: No week can have 4+ shifts (max 3 per week)
            - **Enhanced Rest Rules**:
              - AT preassignments cannot follow night shifts
              - 2 unscheduled days required between night and day shifts
            - **Consecutive Shift Limits**: Max 4 in a row (5 if nights included)
            - **Weekend Requirements**: Friday nights + Saturday/Sunday shifts
            """)
            
            # Display staff name mismatches if both files loaded
            if excel_files["preferences"] and excel_files["current_tracks"]:
                try:
                    preferences_df = pd.read_excel(excel_files["preferences"])
                    current_tracks_df = pd.read_excel(excel_files["current_tracks"])
                    
                    column_detection_result = auto_detect_columns(preferences_df, current_tracks_df)
                    column_mappings = column_detection_result["column_mappings"]
                    
                    staff_col_prefs = column_mappings["staff_col_prefs"]
                    staff_col_tracks = column_mappings["staff_col_tracks"]
                    
                    if staff_col_prefs and staff_col_tracks:
                        pref_staff = set(preferences_df[staff_col_prefs])
                        track_staff = set(current_tracks_df[staff_col_tracks])
                        
                        only_in_pref = pref_staff - track_staff
                        only_in_track = track_staff - pref_staff
                        
                        if only_in_pref or only_in_track:
                            st.warning("⚠️ Staff name mismatches detected between files")
                            
                            if only_in_pref:
                                with st.expander("Staff in Preferences but not in Tracks:"):
                                    st.write(", ".join(sorted(only_in_pref)))
                            
                            if only_in_track:
                                with st.expander("Staff in Tracks but not in Preferences:"):
                                    st.write(", ".join(sorted(only_in_track)))
                except Exception as e:
                    st.error(f"Error checking staff mismatches: {str(e)}")

            st.header("Track Source Configuration")
            TRACK_SOURCE_MODE = "Annual Rebid"
            
            if TRACK_SOURCE_MODE == "Annual Rebid":
                st.session_state.track_source = "Annual Rebid"
                st.success("🔥 **Current Mode: Annual Rebid**")
                st.info("""
                **Annual Rebid Mode Active:**
                - Uses enhanced validation rules for all submissions
                - Considers all possible shifts regardless of Excel file availability
                - Applies strict pay period and rest requirements
                - Saves submitted tracks to the database for future reference
                """)
                
                if 'current_tracks_df' in st.session_state and st.session_state.current_tracks_df is not None:
                    source_format = detect_data_source_format(st.session_state.current_tracks_df)
                    st.session_state.data_source_format = source_format
            
            elif TRACK_SOURCE_MODE == "In Year Modifications":
                st.session_state.track_source = "Current Track Changes"
                st.warning("⚙️ **Current Mode: In Year Modifications**")
                st.info("""
                **In Year Modifications Mode Active:**
                - Uses current track changes logic
                - Shift availability depends on current staffing levels
                - Allows manual loading of tracks from Excel files
                """)
                
                st.markdown("---")
                st.subheader("🔥 Manual Track Import")
                
                tracks_file_path = os.path.join("upload files", "Tracks.xlsx")
                tracks_file_exists = os.path.exists(tracks_file_path)
                
                if tracks_file_exists:
                    st.success(f"✅ Found: {tracks_file_path}")
                    
                    try:
                        file_size = os.path.getsize(tracks_file_path)
                        file_size_kb = file_size / 1024
                        mod_time = os.path.getmtime(tracks_file_path)
                        mod_datetime = datetime.fromtimestamp(mod_time)
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("File Size", f"{file_size_kb:.1f} KB")
                        with col2:
                            st.metric("Last Modified", mod_datetime.strftime("%Y-%m-%d %H:%M"))
                    except:
                        pass
                    
                    if st.button("🔥 Manually Convert Tracks.xlsx to Database", 
                               key="manual_convert_tracks",
                               use_container_width=True,
                               type="primary"):
                        
                        success, message = manually_convert_tracks_excel_to_db(tracks_file_path)
                        
                        if success:
                            st.success(f"✅ {message}")
                            st.rerun()
                        else:
                            st.error(f"❌ {message}")                        
                else:
                    st.error(f"❌ Tracks.xlsx not found in 'upload files' folder")

            st.session_state['TRACK_SOURCE_MODE'] = TRACK_SOURCE_MODE
            #ensure_track_source_consistency()
            
            st.header("Configuration")
            
            with st.expander("Shift Capacity Configuration", expanded=True):
                st.markdown("#### Shift Capacity Settings (Hardcoded)")
                st.markdown("- Max Day Shift Nurses: **10**")
                st.markdown("- Max Day Shift Medics: **10**")
                st.markdown("- Max Night Shift Nurses: **6**")
                st.markdown("- Max Night Shift Medics: **5**")
            
            with st.expander("Role Delta Filter", expanded=False):
                st.markdown("#### Role Balance Filter")
                
                enable_role_delta_filter = st.checkbox("Enable Role Delta Filter", value=False,
                                          help="Filter out needs when the difference between roles exceeds the threshold")
                
                day_delta_threshold = st.number_input("Day Shift Delta Threshold", min_value=1, max_value=10, value=2,
                                      help="Filter out role needs when absolute difference exceeds this threshold (days)")
                
                night_delta_threshold = st.number_input("Night Shift Delta Threshold", min_value=1, max_value=10, value=2,
                                        help="Filter out role needs when absolute difference exceeds this threshold (nights)")

            # Database Management Section
            st.header("🔧 Database Management")
            
            db_cols = st.columns(3)
            
            with db_cols[0]:
                if st.button("🔄 Verify Database Integrity"):
                    try:
                        result = verify_database_integrity()
                        if result:
                            st.success("✅ Database integrity verified")
                        else:
                            st.error("❌ Database integrity check failed")
                    except Exception as e:
                        st.error(f"❌ Error during integrity check: {str(e)}")
            
            with db_cols[1]:
                if st.button("📥 Backup Database"):
                    try:
                        backup_dir = "backups"
                        os.makedirs(backup_dir, exist_ok=True)
                        
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        backup_file = f"{backup_dir}/medflight_tracks_backup_{timestamp}.db"
                        
                        import shutil
                        if os.path.exists('data/medflight_tracks.db'):
                            shutil.copy2('data/medflight_tracks.db', backup_file)
                            st.success(f"✅ Database backed up to {backup_file}")
                        else:
                            st.error("❌ Database file not found")
                    except Exception as e:
                        st.error(f"❌ Backup failed: {str(e)}")
            
            with db_cols[2]:
                if st.button("🧹 Cleanup Old Backups"):
                    try:
                        backup_dir = "backups"
                        if os.path.exists(backup_dir):
                            backup_files = glob.glob(os.path.join(backup_dir, "*.db"))
                            old_files = [f for f in backup_files if os.path.getctime(f) < (datetime.now() - timedelta(days=30)).timestamp()]
                            
                            deleted_count = 0
                            for old_file in old_files:
                                try:
                                    os.remove(old_file)
                                    deleted_count += 1
                                except:
                                    continue
                            
                            st.success(f"✅ Cleaned up {deleted_count} old backup files")
                        else:
                            st.info("No backup directory found")
                    except Exception as e:
                        st.error(f"❌ Cleanup failed: {str(e)}")
                            
            # Export Database Contents Section
            st.header("📊 Database Export")
            
            with st.expander("Export Database Contents", expanded=False):
                st.markdown("""
                ### Export Options
                
                Choose what data you want to export from the database:
                - **Current Tracks**: All active tracks in the database (Excel format)
                - **Track History**: Complete history of all track changes (Excel format)
                - **Raw Database**: Download the complete SQLite database file (.db)
                - **Both Excel Files**: Export both current tracks and history as Excel files
                """)
                
                export_option = st.radio(
                    "Select Export Type",
                    options=["Current Tracks", "Track History", "Raw Database", "Both Excel Files"],
                    index=0,
                    help="Choose what data to export"
                )
                
                if st.button("Generate Export", use_container_width=True):
                    try:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        
                        if export_option == "Raw Database":
                            with st.spinner("Preparing database download..."):
                                db_path = 'data/medflight_tracks.db'
                                
                                if os.path.exists(db_path):
                                    try:
                                        with open(db_path, 'rb') as db_file:
                                            db_data = db_file.read()
                                        
                                        filename = f"medflight_tracks_backup_{timestamp}.db"
                                        
                                        st.download_button(
                                            label="📥 Download Database File",
                                            data=db_data,
                                            file_name=filename,
                                            mime="application/octet-stream",
                                            use_container_width=True,
                                            help="Download the complete SQLite database file"
                                        )
                                        
                                        file_size_mb = len(db_data) / (1024 * 1024)
                                        st.success(f"✅ Database ready for download ({file_size_mb:.2f} MB)")
                                        st.info(f"📄 **File:** {filename}")
                                        st.info(f"💾 **Size:** {file_size_mb:.2f} MB")
                                        st.info(f"🗓️ **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                                        
                                    except Exception as e:
                                        st.error(f"❌ Error reading database file: {str(e)}")
                                else:
                                    st.error("❌ Database file not found. Please ensure tracks have been submitted.")
                        
                        elif export_option in ["Current Tracks", "Both Excel Files"]:
                            with st.spinner("Generating current tracks export..."):
                                excel_data = export_tracks_to_excel()
                                if excel_data:
                                    filename = f"current_tracks_export_{timestamp}.xlsx"
                                    st.download_button(
                                        label="📥 Download Current Tracks",
                                        data=excel_data,
                                        file_name=filename,
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        use_container_width=True
                                    )
                                else:
                                    st.error("❌ Error generating current tracks export")
                        
                        if export_option in ["Track History", "Both Excel Files"]:
                            with st.spinner("Generating track history export..."):
                                excel_data = export_track_history_to_excel()
                                if excel_data:
                                    filename = f"track_history_export_{timestamp}.xlsx"
                                    st.download_button(
                                        label="📥 Download Track History",
                                        data=excel_data,
                                        file_name=filename,
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        use_container_width=True
                                    )
                                else:
                                    st.error("❌ Error generating track history export")
                                    
                    except Exception as e:
                        st.error(f"Error during export: {str(e)}")

            # Database Restore Section
            st.header("🔄 Database Restore")

            with st.expander("Restore Database from Backup", expanded=False):
                st.markdown("""
                ### Database Restore Options
                
                **⚠️ WARNING: This will replace your current active database!**
                
                You can restore the database from:
                - **Recent Backups**: Automatic backups created during submissions
                - **Manual Backups**: Database files you've previously downloaded
                - **Upload Backup**: Upload a backup file from your computer
                """)
                
                restore_tab1, restore_tab2, restore_tab3 = st.tabs(["Recent Backups", "Manual Upload", "Backup History"])
                
                with restore_tab1:
                    st.markdown("#### 🔍 Select from Recent Backups")
                    
                    backup_directories = ['backups', 'data']
                    backup_files = []
                    
                    for backup_dir in backup_directories:
                        if os.path.exists(backup_dir):
                            for file in os.listdir(backup_dir):
                                if file.endswith('.db') and ('backup' in file.lower() or 'medflight' in file.lower()):
                                    file_path = os.path.join(backup_dir, file)
                                    file_stat = os.stat(file_path)
                                    backup_files.append({
                                        'name': file,
                                        'path': file_path,
                                        'size': file_stat.st_size,
                                        'modified': datetime.fromtimestamp(file_stat.st_mtime),
                                        'directory': backup_dir
                                    })
                    
                    backup_files.sort(key=lambda x: x['modified'], reverse=True)
                    
                    if backup_files:
                        st.markdown(f"Found {len(backup_files)} backup files:")
                        
                        selected_backup = None
                        
                        for i, backup in enumerate(backup_files[:10]):
                            file_size_mb = backup['size'] / (1024 * 1024)
                            modified_str = backup['modified'].strftime("%Y-%m-%d %H:%M:%S")
                            
                            with st.container():
                                backup_col1, backup_col2, backup_col3, backup_col4 = st.columns([3, 2, 2, 1])
                                
                                with backup_col1:
                                    if st.radio(
                                        "Select backup:",
                                        options=[backup['name']],
                                        key=f"backup_radio_{i}",
                                        label_visibility="collapsed"
                                    ):
                                        selected_backup = backup
                                
                                with backup_col2:
                                    st.write(f"📅 {modified_str}")
                                
                                with backup_col3:
                                    st.write(f"💾 {file_size_mb:.2f} MB")
                                
                                with backup_col4:
                                    st.write(f"📁 {backup['directory']}")
                            
                            if i < min(len(backup_files), 10) - 1:
                                st.divider()
                        
                        if len(backup_files) > 10:
                            st.info(f"Showing 10 most recent backups. Total available: {len(backup_files)}")
                        
                        if selected_backup:
                            st.markdown("---")
                            st.markdown(f"**Selected backup:** {selected_backup['name']}")
                            st.markdown(f"**Modified:** {selected_backup['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
                            st.markdown(f"**Size:** {selected_backup['size'] / (1024 * 1024):.2f} MB")
                            
                            st.error("⚠️ **DANGER ZONE**: This will replace your current database!")
                            
                            confirm_restore = st.checkbox(
                                f"I understand this will replace the current database with {selected_backup['name']}",
                                key="confirm_restore_backup"
                            )
                            
                            if confirm_restore:
                                if st.button("🔄 Restore Database", type="primary", use_container_width=True):
                                    restore_success, restore_message = restore_database_from_backup(selected_backup['path'])
                                    
                                    if restore_success:
                                        st.success(f"✅ {restore_message}")
                                        st.balloons()
                                        st.info("🔄 Please refresh the page to see the restored data.")
                                    else:
                                        st.error(f"❌ {restore_message}")
                            else:
                                st.info("Check the confirmation box above to enable the restore button.")
                    else:
                        st.info("No backup files found in the backup directories.")
                
                with restore_tab2:
                    st.markdown("#### 📤 Upload Backup File")
                    
                    uploaded_backup = st.file_uploader(
                        "Choose backup database file",
                        type=['db'],
                        help="Select a .db file to restore",
                        key="upload_backup_file"
                    )
                    
                    if uploaded_backup is not None:
                        file_size_mb = len(uploaded_backup.getvalue()) / (1024 * 1024)
                        st.success(f"✅ Uploaded: {uploaded_backup.name} ({file_size_mb:.2f} MB)")
                        
                        st.markdown("---")
                        st.error("⚠️ **DANGER ZONE**: This will replace your current database!")
                        st.warning("⚠️ **No validation performed**: Make sure this is a valid database file!")
                        
                        confirm_upload_restore = st.checkbox(
                            f"I understand this will replace the current database with {uploaded_backup.name}",
                            key="confirm_restore_upload"
                        )
                        
                        if confirm_upload_restore:
                            if st.button("🔄 Restore from Upload", type="primary", use_container_width=True):
                                restore_success, restore_message = restore_database_from_upload(uploaded_backup)
                                
                                if restore_success:
                                    st.success(f"✅ {restore_message}")
                                    st.balloons()
                                    st.info("🔄 Please refresh the page to see the restored data.")
                                else:
                                    st.error(f"❌ {restore_message}")
                        else:
                            st.info("Check the confirmation box above to enable the restore button.")
                
                with restore_tab3:
                    st.markdown("#### 📊 Backup History & Management")
                    
                    if st.button("Show All Backups", use_container_width=True):
                        all_backups = []
                        
                        for backup_dir in backup_directories:
                            if os.path.exists(backup_dir):
                                for file in os.listdir(backup_dir):
                                    if file.endswith('.db'):
                                        file_path = os.path.join(backup_dir, file)
                                        file_stat = os.stat(file_path)
                                        all_backups.append({
                                            'File Name': file,
                                            'Directory': backup_dir,
                                            'Size (MB)': f"{file_stat.st_size / (1024 * 1024):.2f}",
                                            'Modified': datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                                            'Full Path': file_path
                                        })
                        
                        if all_backups:
                            all_backups.sort(key=lambda x: x['Modified'], reverse=True)
                            
                            backup_df = pd.DataFrame(all_backups)
                            st.dataframe(backup_df[['File Name', 'Directory', 'Size (MB)', 'Modified']], use_container_width=True)
                            
                            st.markdown("---")
                            st.markdown("#### 🧹 Backup Cleanup")
                            
                            old_backups = [b for b in all_backups 
                                         if datetime.strptime(b['Modified'], "%Y-%m-%d %H:%M:%S") < datetime.now() - timedelta(days=30)]
                            
                            if old_backups:
                                st.info(f"Found {len(old_backups)} backups older than 30 days.")
                                
                                if st.button("🗑️ Clean Old Backups (30+ days)", use_container_width=True):
                                    cleanup_result = cleanup_old_backups(old_backups)
                                    st.success(f"✅ Cleaned up {cleanup_result['deleted']} old backup files.")
                            else:
                                st.info("No old backups found (30+ days).")
                        else:
                            st.info("No backup files found.")

            # Email Configuration Section
            st.header("📧 Email Configuration")
            with st.expander("Email Settings", expanded=False):
                st.markdown("""
                ### Current Email Configuration
                
                The system is configured to send notifications to:
                - Admin: aaron.e.bell@gmail.com
                - Notification recipients: Configured in secrets
                
                SMTP Settings:
                - Server: smtp.gmail.com
                - Port: 587
                - Sender: aaron.e.bell@gmail.com
                """)
                if st.button("Test Email Configuration", use_container_width=True):
                    try:
                        from modules.email_notifications import EmailNotifier
                        notifier = EmailNotifier()
                        with st.spinner("Sending test email..."):
                            success = notifier.test_email_configuration()
                            if success:
                                st.success("✅ Test email sent successfully!")
                            else:
                                st.error("❌ Failed to send test email")
                    except Exception as e:
                        st.error(f"Error testing email configuration: {str(e)}")

    # MAIN PROCESSING
    if excel_files["preferences"] and excel_files["current_tracks"]:
        try:
            # Load the data from files
            preferences_df = pd.read_excel(excel_files["preferences"])
            current_tracks_df = pd.read_excel(excel_files["current_tracks"])
            
            # Load requirements file
            if excel_files["requirements"]:
                requirements_df = pd.read_excel(excel_files["requirements"])
                
                if len(requirements_df.columns) >= 5:
                    st.session_state.requirements_df = requirements_df
                else:
                    st.session_state.requirements_df = None
            else:
                requirements_df = None
                st.session_state.requirements_df = None
            
            # Save dataframes to session state
            st.session_state.current_tracks_df = current_tracks_df
            st.session_state.preferences_df = preferences_df
            
            # Initialize track manager
            if st.session_state.track_manager:
                st.session_state.track_manager.load_preferences(preferences_df)
                st.session_state.track_manager.load_tracks(current_tracks_df)
                if requirements_df is not None:
                    st.session_state.track_manager.load_requirements(requirements_df)
            
            # Run automated column detection
            column_detection_result = auto_detect_columns(preferences_df, current_tracks_df)
            column_mappings = column_detection_result["column_mappings"]
            all_columns_found = column_detection_result["all_found"]
            
            # Store detected mappings in session state
            for key, value in column_mappings.items():
                if value is not None:
                    st.session_state[key] = value
            
            # Use detected column mappings
            staff_col_prefs = column_mappings["staff_col_prefs"]
            staff_col_tracks = column_mappings["staff_col_tracks"]
            role_col = column_mappings["role_col"]
            no_matrix_col = column_mappings["no_matrix_col"]
            reduced_rest_col = column_mappings["reduced_rest_col"]
            seniority_col = column_mappings["seniority_col"]
            
            # Save staff column names to session state
            st.session_state.staff_col_prefs = staff_col_prefs
            st.session_state.staff_col_tracks = staff_col_tracks
            st.session_state.role_col = role_col
            st.session_state.no_matrix_col = no_matrix_col
            st.session_state.reduced_rest_col = reduced_rest_col
            st.session_state.seniority_col = seniority_col
            
            # Create the master grid
            staff_names = current_tracks_df[staff_col_tracks].tolist()
            days = current_tracks_df.columns[1:43]  # 6 weeks = 42 days
            
            # Save days to session state
            st.session_state.days = days
            
            # Initialize master dataframe
            master_df = pd.DataFrame(index=staff_names, columns=days)
            assignment_reasons = {}

            # Store initialization info in session state
            st.session_state.master_df = master_df
            st.session_state.assignment_reasons = assignment_reasons

            # Detect and store data source format
            source_format = detect_data_source_format(current_tracks_df)
            st.session_state.data_source_format = source_format

        except Exception as e:
            st.error("An error occurred while loading the data. Please contact an administrator.")
    else:
        st.info("Waiting for data to load. If no data appears, please contact an administrator.")

    # ENHANCED STAFF SELECTION SECTION - Split Screen Layout with Fullscreen Option
    if st.session_state.master_df is not None:
        
        # Check if we're in fullscreen track viewer mode
        if st.session_state.get('track_viewer_fullscreen', False):
            display_track_viewer()

        # Check if we're in fullscreen fiscal year mode
        if st.session_state.get('fy_show_fullscreen', False):
            add_fiscal_year_display_to_app()
            st.stop()  # Prevent other content from rendering
            
        # Skip staff selection if already in track management
        elif st.session_state.get('staff_track_active', False) and st.session_state.selected_staff:
            selected_staff = st.session_state.selected_staff
            
            st.success(f"Staff member {selected_staff} selected. View and modify their track below.")
                    
            # Display Staff Track Management with enhanced validation
            if (st.session_state.preferences_df is not None and 
                st.session_state.current_tracks_df is not None and 
                st.session_state.days is not None):
                
                try:
                    display_staff_track_interface(
                        selected_staff,
                        st.session_state.preferences_df,
                        st.session_state.current_tracks_df,
                        st.session_state.requirements_df,
                        st.session_state.days,
                        st.session_state.staff_col_prefs,
                        st.session_state.staff_col_tracks,
                        st.session_state.role_col,
                        st.session_state.no_matrix_col,
                        st.session_state.reduced_rest_col,
                        st.session_state.seniority_col,
                        preassignment_df=st.session_state.preassignment_df
                    )
                except Exception as e:
                    st.error(f"Error displaying staff interface: {str(e)}")
                    
                    if st.button("Reset and return to staff selection"):
                        st.session_state.staff_track_active = False
                        st.session_state.selected_staff = None
                        st.rerun()
            else:
                st.warning("Missing data. Please ensure all files are loaded.")
        else:        
            # Split layout: Left = Staff Management, Right = Calendar Export + Track Display
            left_col, right_col = st.columns(2, gap="large")
            
            # LEFT SIDE section
            with left_col:
                # Check if we should show the swap form (takes priority)
                if handle_track_swap_navigation():
                    # Track swap form is being displayed, don't show other sections
                    pass
                else:
                    # Normal landing page layout
                    st.markdown("### Preferred Track Display")
                    st.caption("View active tracks by role - informational purposes only")
                
                    # Enhanced Track viewer component with fullscreen option
                    display_track_viewer()
                    
                    # Track Swap Section
                    display_track_swap_section()
                    
                    #Track Management Section
                    st.markdown("### Track Management")
                                    
                    staff_names = st.session_state.master_df.index.tolist()
                    selected_staff = st.selectbox("Select Staff Member", staff_names, key="main_staff_select")
                    
                    # Store selected staff and proceed to Track Management
                    if selected_staff:
                        if st.button("🔧 Manage Staff Track with Validation", use_container_width=True, type="primary"):
                            st.session_state.selected_staff = selected_staff
                            st.session_state.staff_track_active = True
                            st.rerun()

            
            # RIGHT SIDE: Calendar Export + Fiscal Year Track Display
            with right_col:
                # Calendar Export Section (TOP)
                display_calendar_export_section()
                
                st.markdown("---")  # Separator
                
                # Fiscal Year Display Section (BOTTOM)
                add_fiscal_year_display_to_app()
    else:
        st.info("Waiting for data to load. If no data appears, please contact an administrator.")
# SECURITY CHECK - This is the first thing that runs
if not display_user_login():
    st.stop()

# If we get here, user is authenticated - show session info
display_session_info()

# Main Navigation Logic
if st.session_state.selected_module is None:
    # Show main CrewOps360 landing page
    display_module_selection()
elif st.session_state.selected_module == "clinical_track_hub":
    # Show Clinical Track Hub
    display_clinical_track_hub()
elif st.session_state.selected_module == "training_events":
    # Show Training & Events application (FULL VERSION)
    display_training_events_app()

