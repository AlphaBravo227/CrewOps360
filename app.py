# app.py - CrewOps360 Main Application - Complete Integrated System
import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

_eastern_tz = pytz.timezone('America/New_York')
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
    from modules.fiscal_year import add_fiscal_year_display_to_app
except ImportError:
    # Create a stub function if the fiscal year module doesn't exist
    def add_fiscal_year_display_to_app(track_name=None):
        pass

from modules.db_utils import initialize_database
# Import existing modules that actually work
from modules.security import display_user_login, display_session_info, admin_is_authenticated
from modules.admin_console import display_admin_console, render_admin_sidebar_entry
from modules.summer_leave import display_summer_leave_app
from modules.shift_definitions import day_shifts, night_shifts
from modules.shift_utils import get_shift_end_time, calculate_rest_conflict
from modules.staff_utils import is_special_conflict
from modules.ui_components import display_roster_results
from modules.column_mapper import auto_detect_columns
from modules.pdf_generator import generate_schedule_pdf
from modules.enhanced_track_validator import validate_track_comprehensive
from modules.enhanced_validation_display import display_comprehensive_validation
from modules.preference_editor import initialize_preference_tables
from modules.track_source_consistency import ensure_track_source_consistency
from modules.track_display import display_track_viewer
from modules.enhanced_landing import inject_custom_css
from modules.track_bidding import display_track_bidding
from modules.db_utils import get_active_track_config, get_track_capacity
from modules.track_year import (
    SELECTED_YEAR_KEY,
    get_hub_track_years,
    get_track_year_dates,
    resolve_selected_year,
)
from modules.staff_database import (
    build_preferences_df,
    build_requirements_df,
    get_staff_names,
    initialize_staff_tables,
    staff_count,
)
from modules.day_pattern import PATTERN_DAYS
from modules.track_roster import build_current_tracks_df
from modules.preassignment_db import initialize_preassignment_tables
from modules.ccemt_schedule import initialize_ccemt_tables
from modules.track_management.preassignment import load_preassignments

# Import training modules with new unified database approach
try:
    from training_modules.unified_database import (
        UnifiedDatabase, get_active_roster_path, YEAR_STATUS_OPEN, YEAR_STATUS_DRAFT)
    from training_modules.enrollment_manager import EnrollmentManager
    from training_modules.ui_components import UIComponents as TrainingUIComponents  # Renamed to avoid conflict
    from training_modules.class_display_components import ClassDisplayComponents
    from training_modules.enrollment_session_components import EnrollmentSessionComponents
    from training_modules.staff_meeting_components import StaffMeetingComponents
    from training_modules.track_manager import TrainingTrackManager
    from training_modules.class_catalog import ClassCatalog
    from training_modules.admin_access import AdminAccess, training_admin_is_authenticated
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
    padding: 0.75rem 0;
    background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
    border-radius: 15px;
    margin-bottom: 1rem;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.module-card {
    border: 2px solid #1E88E5;
    border-radius: 15px;
    padding: 1.1rem 2rem;
    margin-bottom: 0;
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

/* Click-anywhere module cards: the real navigation control is an st.button,
   stretched invisibly over the whole card via its st.container(key=...)
   wrapper, so clicking the card itself (not just a separate label below it)
   triggers it. Streamlit has no click-handler for plain markdown, so the
   button has to be the actual target underneath. */
div[class*="st-key-"][class*="_card"] {
    position: relative;
}
/* Streamlit wraps every element (including the button) in its own
   .element-container, which is itself position:relative with zero height —
   left alone, that becomes the button's containing block instead of the
   card, collapsing the overlay to nothing. Neutralize it so the button's
   position:absolute below resolves against the card wrapper instead. */
div[class*="st-key-"][class*="_card"] div.element-container {
    position: static !important;
}
div[class*="st-key-"][class*="_card"] div[data-testid="stButton"] {
    position: absolute;
    inset: 0;
    z-index: 2;
    margin: 0;
}
div[class*="st-key-"][class*="_card"] div[data-testid="stButton"] button {
    width: 100%;
    height: 100%;
    opacity: 0;
    cursor: pointer;
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

# Deep-link support: a link generated by the admin's outreach-email composer
# (Needs Swap Requests -> Draft an outreach email) can carry ?module=track_bidding
# so a staff member who clicks it lands straight on that module instead of the
# module-picker home page. Applied once per browser session — after that the
# user's own navigation (including "Back to CrewOps360", which resets
# selected_module to None) is left alone, so this never fights a later click.
#
# Checked against the exact set the Main Navigation Logic dispatcher below
# understands — that if/elif chain has no trailing else, so an unrecognized
# value (a stale link, a typo, a module renamed later) would otherwise leave
# the whole page blank with no way back instead of falling through to the
# module picker.
_DEEP_LINKABLE_MODULES = {
    'clinical_track_hub', 'track_bidding', 'staff_database', 'track_data',
    'training_events', 'shift_location_preferences', 'summer_leave',
}
if 'deep_link_module_applied' not in st.session_state:
    st.session_state.deep_link_module_applied = True
    from modules.ui_components import get_query_params
    _deep_link_module = get_query_params().get('module')
    if _deep_link_module in _DEEP_LINKABLE_MODULES:
        st.session_state.selected_module = _deep_link_module

def display_crewops360_header():
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

    render_admin_sidebar_entry("_landing")

    # Create centered layout
    col1, col2, col3 = st.columns([1, 3, 1])

    with col2:
        st.markdown("### 🎯 Select Module")
        st.markdown("---")

        # Track Bidding Module
        with st.container(key="track_bidding_card"):
            st.markdown("""
            <div class="module-card" style="background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%); border: 2px solid #FF9800;">
                <div style="text-align: center;">
                    <h2 style="color: #E65100; margin-bottom: 0.4rem;">🗳️ Track Bidding</h2>
                    <p style="color: #333; font-size: 1.1rem; margin-bottom: 0.6rem; line-height: 1.6;">
                        Bid on your preferred shifts for the upcoming track cycle.
                        Review availability, select your schedule, and submit your bid.
                    </p>
                    <ul style="text-align: left; color: #555; margin-bottom: 0.5rem;">
                        <li>🔄 Select shifts for the next bidding cycle</li>
                        <li>📊 View real-time staffing availability</li>
                        <li>🔍 Validate your bid against requirements</li>
                        <li>📤 Submit your bid</li>
                    </ul>
                </div>
            </div>
            """, unsafe_allow_html=True)
            clicked_track_bidding = st.button(
                "🗳️ Enter Track Bidding", use_container_width=True, key="track_bidding_btn")
        if clicked_track_bidding:
            st.session_state.selected_module = "track_bidding"
            st.rerun()

        # Clinical Track Hub Module
        _landing_active_cfg = get_active_track_config()
        _landing_active_label = _landing_active_cfg['track_name'] if _landing_active_cfg else "FY26"
        with st.container(key="clinical_hub_card"):
            st.markdown(f"""
            <div class="module-card">
                <div style="text-align: center;">
                    <h2 style="color: #1E88E5; margin-bottom: 0.4rem;">🚁 Clinical Track Hub</h2>
                    <p style="color: #4CAF50; font-weight: 600; margin-bottom: 0.4rem;">Active Track: {_landing_active_label}</p>
                    <p style="color: #333; font-size: 1.1rem; margin-bottom: 0.6rem; line-height: 1.6;">
                        Manage your active clinical staff schedule, track preferences, validate shift assignments,
                        and generate calendar exports for flight operations.
                    </p>
                    <ul style="text-align: left; color: #555; margin-bottom: 0.5rem;">
                        <li>📋 Staff track management and validation</li>
                        <li>📅 Calendar export functionality</li>
                        <li>🔄 Track swapping and modifications</li>
                        <li>📊 Comprehensive reporting and analytics</li>
                    </ul>
                </div>
            </div>
            """, unsafe_allow_html=True)
            clicked_clinical_hub = st.button(
                "🚁 Enter Clinical Track Hub", use_container_width=True, key="clinical_hub_btn")
        if clicked_clinical_hub:
            st.session_state.selected_module = "clinical_track_hub"
            st.rerun()

        # Training & Events Registration Module
        training_status = "Available" if TRAINING_MODULES_AVAILABLE else "Setup Required"
        with st.container(key="training_card"):
            st.markdown(f"""
            <div class="module-card module-card-secondary">
                <div style="text-align: center;">
                    <h2 style="color: #9C27B0; margin-bottom: 0.4rem;">📚 Training & Events Registration</h2>
                    <p style="color: #333; font-size: 1.1rem; margin-bottom: 0.6rem; line-height: 1.6;">
                        Register for training programs, continuing education, and company events.
                        Track certifications and compliance requirements.
                    </p>
                    <ul style="text-align: left; color: #555; margin-bottom: 0.5rem;">
                        <li>🎓 Training course registration</li>
                        <li>🎉 Company event sign-ups</li>
                        <li>📈 Progress monitoring</li>
                    </ul>
                </div>
            </div>
            """, unsafe_allow_html=True)
            training_button_disabled = not TRAINING_MODULES_AVAILABLE
            clicked_training = st.button(
                "📚 Enter Training & Events", use_container_width=True,
                key="training_btn", disabled=training_button_disabled)
        if clicked_training:
            if TRAINING_MODULES_AVAILABLE:
                st.session_state.selected_module = "training_events"
                st.rerun()
            else:
                st.error("Training modules are not properly configured. Please check the training folder setup.")

        # Shift Location Preferences Module
        with st.container(key="location_pref_card"):
            st.markdown("""
            <div class="module-card" style="background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%); border: 2px solid #4CAF50;">
                <div style="text-align: center;">
                    <h2 style="color: #2E7D32; margin-bottom: 0.4rem;">📍 Shift Location Preferences</h2>
                    <p style="color: #333; font-size: 1.1rem; margin-bottom: 0.6rem; line-height: 1.6;">
                        Set your preferred work locations for day and night shifts.
                        Rank locations by preference to help with scheduling.
                    </p>
                    <ul style="text-align: left; color: #555; margin-bottom: 0.5rem;">
                        <li>☀️ Day shift location preferences (5 locations)</li>
                        <li>🌙 Night shift location preferences (3 locations)</li>
                        <li>📊 First Choice = most desirable</li>
                    </ul>
                </div>
            </div>
            """, unsafe_allow_html=True)
            clicked_location_pref = st.button(
                "📍 Enter Shift Location Preferences", use_container_width=True, key="location_pref_btn")
        if clicked_location_pref:
            st.session_state.selected_module = "shift_location_preferences"
            st.rerun()

        # Summer Leave Requests Module
        with st.container(key="summer_leave_card"):
            st.markdown("""
            <div class="module-card">
                <div style="text-align: center;">
                    <h2 style="color: #FF9800; margin-bottom: 0.4rem;">☀️ Summer Leave Requests</h2>
                    <p style="color: #333; font-size: 1.1rem; margin-bottom: 0.6rem; line-height: 1.6;">
                        Select your week for summer vacation leave time.
                        View available weeks and manage your selection.
                    </p>
                    <ul style="text-align: left; color: #555; margin-bottom: 0.5rem;">
                        <li>📅 View available weeks (May 31 - Sep 12, 2026)</li>
                        <li>✅ Select your preferred week</li>
                        <li>📊 View your work schedule for each week</li>
                        <li>🔄 Change or cancel your selection</li>
                    </ul>
                </div>
            </div>
            """, unsafe_allow_html=True)
            clicked_summer_leave = st.button(
                "☀️ Enter Summer Leave Requests", use_container_width=True, key="summer_leave_btn")
        if clicked_summer_leave:
            st.session_state.selected_module = "summer_leave"
            st.rerun()

        # Administration. One card, one sign-in, everything behind it — rather
        # than a password box hidden in each module's sidebar.
        st.markdown("---")
        if admin_is_authenticated():
            st.success("🔓 You are signed in as an administrator.")
        if st.button("🛠️ Admin Console", use_container_width=True, key="admin_console_btn"):
            st.session_state.selected_module = "admin"
            st.rerun()
        st.caption("Staff Database · Track Data · Track Bidding · Training & Events · "
                   "Summer Leave · approvals, exports and system tools.")

# Shift Location Preferences Module
def display_shift_location_preferences_module():
    """Display the Shift Location Preferences module for staff to set their location preferences"""
    from modules.preference_editor import display_location_preference_editor
    from modules.db_utils import initialize_database

    render_admin_sidebar_entry("_location_prefs")

    st.markdown("")
    st.markdown("")

    # Back button
    if st.button("← Back to CrewOps360", key="back_from_location_prefs"):
        st.session_state.selected_module = None
        st.rerun()

    # Header
    st.markdown("""
    <div style="text-align: center; padding: 1rem;">
        <h1 style="color: #2E7D32;">📍 Shift Location Preferences</h1>
        <p style="color: #666; font-size: 1.1rem;">
            Set your preferred work locations for day and night shifts
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # Initialize database
    initialize_database()
    initialize_staff_tables()

    # Staff list comes from the staff database — active nurses and medics, the staff who
    # hold a clinical track and therefore have base location preferences.
    staff_names = get_staff_names(clinical_only=True)

    if not staff_names:
        st.error("No clinical staff found in the staff database. An administrator needs "
                 "to import or add the staff roster (Staff Database admin).")
        return

    # Staff selection
    st.markdown("### Select Staff Member")
    selected_staff = st.selectbox(
        "Choose a staff member to edit preferences:",
        options=[""] + staff_names,
        key="location_pref_staff_select",
        format_func=lambda x: "-- Select Staff Member --" if x == "" else x
    )

    if selected_staff:
        st.markdown("---")
        display_location_preference_editor(selected_staff)
    else:
        st.info("Please select a staff member above to view or edit their location preferences.")

# Enhanced Training Events App Section with Educator Signup
# This replaces the display_training_events_app() function in app.py

def _offer_training_year_escape(selected_year_label, fallback_label,
                                show_module_exit=False):
    """A way back when the selected year's roster can't be loaded.

    Everything below the roster load returns early on failure, the year selector
    included, so a year whose workbook is missing - a draft being built is the
    normal case - left the session pinned to it with no control on screen to pick
    another. Admins are the only ones who can reach such a year, and they were the
    ones with no way out of it.

    show_module_exit adds a way off the module entirely, for the admin dashboard:
    it draws its own navigation, and a roster failure returns before it is ever
    reached, so without this there is nothing on screen to leave with.
    """
    if not selected_year_label:
        if show_module_exit and st.button("← Back to CrewOps360",
                                          key="training_year_escape_module"):
            st.session_state.selected_module = None
            st.rerun()
        return
    target = fallback_label if fallback_label != selected_year_label else None
    label = (f"⬅️ Back to {target}" if target
             else "⬅️ Clear the selected training year")
    if st.button(label, key="training_year_escape"):
        st.session_state.pop('training_selected_year', None)
        st.session_state.pop('training_year_selector', None)
        # Force the handlers to be rebuilt for whatever year we land on.
        st.session_state.pop('training_loaded_year_signature', None)
        st.rerun()

    if show_module_exit and st.button("← Back to CrewOps360",
                                      key="training_year_escape_module"):
        st.session_state.selected_module = None
        st.rerun()


def display_training_events_app():
    # An authenticated admin on the training admin dashboard gets the whole page.
    # The header, the back button and the sidebar below belong to the staff-facing
    # enrollment screen; the dashboard replaces that screen outright rather than
    # sitting beside it, the same way the Staff Database and Track Data admins do
    # in Track Bidding.
    admin_dashboard = (training_admin_is_authenticated()
                       and st.session_state.get('training_admin_show_function', False))

    st.markdown("")
    st.markdown("")
    
    if not admin_dashboard:
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
        # Initialize unified database (uses main medflight_tracks.db). Normally
        # already built at startup; this covers a session that got here first.
        if 'unified_db' not in st.session_state:
            st.session_state.unified_db = UnifiedDatabase('data/medflight_tracks.db')
            st.session_state.unified_db.initialize_training_tables()

        # Update unified_db with excel_handler reference after it's initialized
        if 'training_excel_handler' in st.session_state and st.session_state.training_excel_handler:
            st.session_state.unified_db.excel_handler = st.session_state.training_excel_handler

        # Work out which training year this session is looking at before anything is
        # loaded: the roster, the enrollments and the conflict checks all have to come
        # from the same year, so the choice can't be made after the handlers are built.
        # An authenticated admin sees every year, staff only the ones they can act
        # in. Building next year's roster means reporting on a draft before anyone
        # else may see it, and answering a question about a finished year means
        # reading an archived one; restricting admins to the staff picker made both
        # impossible. The staff-facing screen below is unaffected - a year an admin
        # picks that staff can't see is simply not in the list once they log out.
        admin_view = training_admin_is_authenticated()
        if admin_view:
            visible_years = st.session_state.unified_db.get_admin_visible_training_years()
        else:
            visible_years = st.session_state.unified_db.get_staff_visible_training_years()
        active_year = st.session_state.unified_db.get_active_training_year()
        default_year_label = None
        if active_year:
            default_year_label = active_year['year_label']
        elif visible_years:
            default_year_label = visible_years[0]['year_label']

        visible_labels = [y['year_label'] for y in visible_years]
        # Only an explicit pick from the year selector is remembered. Defaulting used
        # to be remembered too, which pinned a session opened before a cutover to the
        # outgoing year: promoting FY27 left that browser still on FY26 with no sign
        # anything had changed.
        selected_year_label = st.session_state.get('training_selected_year')
        # Drop a pick that no longer applies - the year was archived, or it was the
        # only year when it was chosen and a promotion has since moved things on.
        if selected_year_label and visible_labels and selected_year_label not in visible_labels:
            selected_year_label = None
            st.session_state.pop('training_selected_year', None)
        if not selected_year_label:
            selected_year_label = default_year_label

        selected_year = next(
            (y for y in visible_years if y['year_label'] == selected_year_label), None)
        # Status is already on each row; derive writability from it rather than asking
        # the database once per option per render.
        writable_by_label = {
            y['year_label']: y['status'] == YEAR_STATUS_OPEN for y in visible_years
        }
        year_is_writable = writable_by_label.get(
            selected_year_label,
            st.session_state.unified_db.is_training_year_writable(selected_year_label))

        # Switching years means a different roster workbook, so the cached handlers
        # built against the old one have to go. Editing the year's own settings does
        # too: the linked cohort and the pattern start are read once, when the track
        # manager is built, so linking a cohort to the year an admin is already
        # looking at used to change nothing until the session was restarted.
        year_signature = (
            selected_year_label,
            (selected_year or {}).get('roster_filename'),
            (selected_year or {}).get('linked_track_name'),
            (selected_year or {}).get('pattern_start_date'),
        )
        if st.session_state.get('training_loaded_year_signature') != year_signature:
            for key in ('training_excel_handler', 'training_track_manager',
                        'training_enrollment_manager', 'training_educator_manager',
                        'training_excel_admin_functions'):
                st.session_state.pop(key, None)
            # Admin date pickers hold a range chosen against the previous year, and
            # a range from FY26 finds nothing in FY27. Dropping the widget state
            # lets them re-default to the year now being viewed.
            for key in ('schedule_report_start_date', 'schedule_report_end_date',
                        'schedule_report_prev_start_date',
                        'availability_start_date', 'availability_end_date'):
                st.session_state.pop(key, None)
            st.session_state.training_loaded_year_signature = year_signature
            st.session_state.training_loaded_year = selected_year_label

        # The class catalog for the year being viewed. Classes used to be read out of
        # that year's roster workbook here, on every render; they come from the
        # database now, and a workbook is only opened when an admin imports one.
        if 'training_excel_handler' not in st.session_state:
            st.session_state.training_excel_handler = ClassCatalog(selected_year_label)

            if st.session_state.training_excel_handler.load_error:
                st.error(f"Error opening the class catalog: "
                         f"{st.session_state.training_excel_handler.load_error}")
                # Nothing below renders without a catalog, including the year selector
                # that got us here, so leave a way off the page.
                st.session_state.pop('training_excel_handler', None)
                _offer_training_year_escape(selected_year_label, default_year_label,
                                            show_module_exit=admin_dashboard)
                return

            # A year with no classes is what an unimported year looks like. Say so
            # where it can be acted on rather than letting every staff member find an
            # empty registration screen.
            if not st.session_state.training_excel_handler.get_all_classes():
                st.warning(
                    f"⚠️ **{selected_year_label} has no classes yet.** Build them in "
                    f"Training Admin > Build Classes, or import that year's roster "
                    f"workbook there.")

        # Initialize Track Manager (existing code)
        if 'training_track_manager' not in st.session_state:
            # Conflict checking has to run against the track cohort that was in force
            # during the year being viewed, on that year's pattern grid - not against
            # whatever cohort is active today.
            cohort = (selected_year or {}).get('linked_track_name') or None
            pattern_start = None
            pattern_start_raw = (selected_year or {}).get('pattern_start_date')
            if pattern_start_raw:
                try:
                    pattern_start = datetime.strptime(pattern_start_raw.strip(), '%Y-%m-%d')
                except ValueError:
                    st.warning(
                        f"{selected_year_label}'s pattern start date "
                        f"'{pattern_start_raw}' isn't a valid YYYY-MM-DD date. "
                        f"Using the default; check Training Admin > Training Years."
                    )

            st.session_state.training_track_manager = TrainingTrackManager(
                'data/medflight_tracks.db',
                track_cohort=cohort,
                pattern_start=pattern_start,
            )
            print("✓ Track Manager initialized")

            # CCEMT schedules come from the database (Track Data admin); the enrollment
            # workbook is still connected as the fallback source of staff roles.
            st.session_state.training_track_manager.set_excel_handler(
                enrollment_excel_handler=st.session_state.training_excel_handler
            )
            print("✓ CCEMT schedules loaded")

        # A linked cohort with no tracks in it falls back to the active cohort, which
        # means conflict checking silently runs against another year's schedules. Say
        # so where an admin can act on it rather than only on the console.
        _tm = st.session_state.get('training_track_manager')
        if getattr(_tm, 'tracks_fell_back', False) and admin_is_authenticated():
            st.warning(
                f"⚠️ {selected_year_label} is linked to track cohort "
                f"**{_tm.track_cohort}**, but no tracks are stored under that cohort "
                f"yet, so conflict checking is falling back to the currently active "
                f"cohort. Bids that are still drafts aren't stored as tracks — they "
                f"only count once they're submitted. Check Training Admin > "
                f"Training Years."
            )

        # Initialize enrollment manager, pinned to the year being viewed so a closed
        # year reports its own enrollments rather than the active year's.
        if 'training_enrollment_manager' not in st.session_state:
            st.session_state.training_enrollment_manager = EnrollmentManager(
                st.session_state.unified_db,
                st.session_state.training_excel_handler,
                st.session_state.training_track_manager,
                training_year=selected_year_label
            )

        # Initialize educator manager - NEW
        if 'training_educator_manager' not in st.session_state:
            from training_modules.educator_manager import EducatorManager
            st.session_state.training_educator_manager = EducatorManager(
                st.session_state.unified_db,
                st.session_state.training_excel_handler,
                st.session_state.training_track_manager,
                training_year=selected_year_label
            )

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
        # The admin dashboard draws its own navigation and is never reached from
        # here, so leave a way off the module rather than a dead page.
        if admin_dashboard and st.button("← Back to CrewOps360",
                                         key="training_init_error_back"):
            st.session_state.selected_module = None
            st.rerun()
        return

    # The admin dashboard is a full-width page: nothing of the staff screen, the
    # sidebar included, is drawn behind it.
    if (st.session_state.training_admin_access.is_admin_authenticated() and
            st.session_state.get('training_admin_show_function', False)):
        st.session_state.training_admin_access.show_admin_function_page()
        return

    # Show the way in to the admin dashboard in the sidebar (for administrators only)
    st.session_state.training_admin_access.show_admin_access_button()

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
    # During a fiscal-year cutover two years are open at once: the outgoing year still
    # has classes to finish and the incoming year is taking signups. Offer the choice
    # only when there is one to make.
    if len(visible_years) > 1:
        # An admin's list carries drafts and archived years too, which "closed" does
        # not describe; get_admin_visible_training_years() already labels each one
        # with its own state and enrollment count, so use that when it's there.
        admin_labels = {y['year_label']: y['label']
                        for y in visible_years if y.get('label')}
        year_choice = st.selectbox(
            "Training year",
            options=visible_labels,
            index=visible_labels.index(selected_year_label) if selected_year_label in visible_labels else 0,
            format_func=lambda label: (
                admin_labels.get(label)
                or (f"{label} (current)" if active_year and label == active_year['year_label']
                    else f"{label} (closed)" if not writable_by_label.get(label, True)
                    else label)
            ),
            key="training_year_selector",
        )
        if year_choice != selected_year_label:
            st.session_state.training_selected_year = year_choice
            # The admin dashboard has a selector of its own writing the same key;
            # clearing its widget state stops it reverting this choice on the way
            # back in.
            st.session_state.pop('admin_training_year_selector', None)
            st.rerun()
    elif selected_year_label:
        st.caption(f"📅 Registering for: **{selected_year_label}**")

    if selected_year_label and not year_is_writable:
        end_date = (selected_year or {}).get('end_date')
        status = (selected_year or {}).get('status')
        switch_note = (f" Switch to {active_year['year_label']} above to register."
                       if active_year and active_year['year_label'] != selected_year_label
                       else "")
        # A draft year isn't closed - it hasn't opened. Only an admin can be looking
        # at one, and telling them it has ended sends them checking an end date that
        # was never the problem.
        if status == YEAR_STATUS_DRAFT:
            st.info(
                f"**{selected_year_label} is a draft.** Staff can't see it and nobody "
                f"can enrol in it yet. Set it to Open in Training Admin > Training "
                f"Years when its roster is ready." + switch_note
            )
        else:
            closed_note = f" It ended {end_date}." if end_date else ""
            st.warning(
                f"**{selected_year_label} is closed.**{closed_note} You can review what you "
                f"took, but enrolling and cancelling are no longer available for this year."
                + switch_note
            )

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
        
        # Display enrollment summary using enhanced Staff Meeting tracking
        TrainingUIComponents.display_enrollment_metrics_with_sm(
            assigned_classes, enrolled_classes, 
            st.session_state.training_enrollment_manager, 
            selected_staff, 
            st.session_state.training_excel_handler
        )


# Replace the tabs section in app.py display_training_events_app() function
# This goes where the tab creation and content currently exists

        st.markdown("---")
        
        # Check if user is authorized for educator signup
        is_educator_authorized = st.session_state.training_excel_handler.is_educator_authorized(selected_staff)
        
        # Create tabs conditionally based on educator authorization
        if is_educator_authorized:
            # Show all tabs including Educator Signup
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "📝 Enroll in Classes", 
                "📋 My Enrollments", 
                "📊 Class Details", 
                "📚 Educator Signup", 
                "📅 Track Schedule"
            ])
        else:
            # Hide Educator Signup tab for unauthorized users
            tab1, tab2, tab3, tab4 = st.tabs([
                "📝 Enroll in Classes", 
                "📋 My Enrollments", 
                "📊 Class Details", 
                "📅 Track Schedule"
            ])
            # Set tab4 to None for educator tab since it doesn't exist
            tab5 = None  # Track schedule tab
        
        with tab1:
                    # Enroll in Classes Tab - UPDATED to keep classes expanded after enrollment
                    st.header("📝 Enroll in Classes")
                    
                    if not year_is_writable:
                        st.info(
                            f"{selected_year_label} is closed - no new enrollments. "
                            f"Your record for the year is under **My Enrollments**."
                        )
                    elif not assigned_classes:
                        st.info("You have no classes assigned at this time.")
                    else:
                        # Display ALL assigned classes - always keep them expanded to show enrollment options
                        for class_name in assigned_classes:
                            # Get enrollment status for this class
                            enrollment_status = TrainingUIComponents.get_class_enrollment_status(
                                                    st.session_state.training_enrollment_manager, 
                                                    selected_staff, 
                                                    class_name, 
                                                    st.session_state.training_excel_handler
                                                )
                            # Determine if class is enrolled
                            is_enrolled = class_name in enrolled_classes
                            
                            # Create the display text with enrollment status
                            if is_enrolled:
                                if enrollment_status:
                                    display_text = f"**{class_name}** {enrollment_status}"
                                else:
                                    display_text = f"**{class_name}** ✅ Enrolled"
                                # UPDATED: Keep expanded even if enrolled so user can see their enrollment in context
                                expanded_default = False  # Changed from False to True
                            else:
                                display_text = f"**{class_name}**"
                                expanded_default = False  # Keep expanded to show enrollment options
                            
                            # Show class in expander - ALWAYS expanded now
                            with st.expander(display_text, expanded=expanded_default):
                                # UPDATED: Always show enrollment options regardless of enrollment status
                                available_dates = st.session_state.training_excel_handler.get_class_dates(class_name)
                                
                                if available_dates:
                                    # Use the updated enrollment display method that keeps options visible
                                    EnrollmentSessionComponents.display_session_enrollment_options_with_tracks(
                                        st.session_state.training_enrollment_manager,
                                        class_name,
                                        available_dates,
                                        selected_staff,
                                        st.session_state.training_track_manager
                                    )
                                else:
                                    st.warning("No available dates found for this class. Please contact the training administrator.")

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
                            st.session_state.training_enrollment_manager,
                            read_only=not year_is_writable
                        ):
                            # Handle cancellation
                            if st.session_state.training_enrollment_manager.cancel_enrollment(enrollment['id']):
                                st.success("Enrollment cancelled successfully!")
                                st.rerun()
                            else:
                                st.error("Error cancelling enrollment.")
            
            # Show educator enrollments only if user is authorized
            if is_educator_authorized:
                st.markdown("---")
                st.markdown("### 👨‍🏫 Your Educator Signups")
                
                from training_modules.educator_ui_components import EducatorUIComponents
                EducatorUIComponents.display_staff_educator_enrollments(
                    st.session_state.training_educator_manager,
                    selected_staff,
                    read_only=not year_is_writable
                )

        with tab3:
            # Class Details Tab (existing functionality)
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
                        # Display detailed class information using existing method
                        ClassDisplayComponents.display_class_info(class_details)
                    else:
                        st.error("Class details not found.")
            else:
                st.info("You have no classes assigned.")

        # Only show Educator Signup tab if user is authorized
        if is_educator_authorized and tab5 is not None:
            with tab4:  # This is the Educator Signup tab when authorized
                st.header("📚 Educator Signup")
                
                # Import the EducatorUIComponents class
                from training_modules.educator_ui_components import EducatorUIComponents
                
                # Display educator metrics
                EducatorUIComponents.display_educator_metrics(
                    st.session_state.training_educator_manager,
                    selected_staff
                )
                
                st.markdown("---")
                
                if not year_is_writable:
                    st.info(
                        f"{selected_year_label} is closed - no new educator signups. "
                        f"What you taught that year is listed under **My Enrollments**."
                    )
                else:
                    # Display available educator opportunities (THIS IS THE CORRECT METHOD)
                    EducatorUIComponents.display_educator_opportunities(
                        st.session_state.training_educator_manager,
                        selected_staff
                    )

        # Track Schedule tab (always the last tab) - keep original placeholder
        schedule_tab = tab5 if is_educator_authorized else tab4
        with schedule_tab:
            # Track Schedule Tab (existing functionality)
            st.header("📅 Track Schedule")
            
            if st.session_state.training_track_manager.tracks_db_path:
                if st.session_state.training_track_manager.has_track_data(selected_staff):
                    st.info("Track schedule integration coming soon - will show your work schedule alongside training commitments.")
                else:
                    st.warning("No track schedule found for your profile.")
            else:
                st.warning("Track database not available.")

def display_clinical_track_hub():
    """Display the Clinical Track Hub with back navigation - FIXED spacing and button issues"""
    
    # Add minimal top margin to prevent button cutoff
    st.markdown("")
    st.markdown("")
    
    # Simple back button that works properly
    if st.button("← Back to CrewOps360", key="back_from_clinical"):
        st.session_state.selected_module = None
        st.rerun()

    # Work out which fiscal year this session is looking at before anything is loaded:
    # the track grid, the viewer, the calendar export and the fiscal-year display all
    # have to come from the same year, so the choice can't be made after the data is.
    selected_year, year_is_writable = display_track_year_selector()

    # All the existing Clinical Track Hub functionality goes here
    run_clinical_track_hub(selected_year, year_is_writable)


def display_track_year_selector():
    """Header, and the fiscal-year picker when there is more than one year to pick.

    A cutover is an overlap, not a switch: FY27's tracks are promoted months before
    FY26's last shift is worked, and promotion clears is_active on FY26's rows. Without
    a picker the year people are still working simply vanishes from the hub the day the
    next one goes live.

    Returns:
        tuple: (selected track cohort name, whether it accepts track changes)
    """
    active_cfg = get_active_track_config()
    active_label = active_cfg['track_name'] if active_cfg else "FY26"

    visible_years = get_hub_track_years()
    labels = [y['track_name'] for y in visible_years]

    # Only an explicit pick is remembered. Remembering a default would pin a browser
    # opened before a cutover to the outgoing year with no sign anything had changed.
    remembered = st.session_state.get(SELECTED_YEAR_KEY)
    selected_year, dropped_stale = resolve_selected_year(
        visible_years, active_label, remembered)
    if dropped_stale:
        st.session_state.pop(SELECTED_YEAR_KEY, None)

    year = next((y for y in visible_years if y['track_name'] == selected_year), None)
    year_is_writable = bool(year['is_writable']) if year else selected_year == active_label
    is_live = selected_year == active_label

    heading_note = (f"Active Track: {selected_year}" if is_live
                    else f"Viewing: {selected_year} — Active Track: {active_label}")
    heading_colour = '#4CAF50' if is_live else '#F57C00'
    st.markdown(f"""
    # <span style='color:#1E88E5'>Clinical Track Hub</span> <span style='color:{heading_colour}; font-size:1.2rem;'>— {heading_note}</span>
    """, unsafe_allow_html=True)

    # Offer the choice only when there is one to make.
    if len(visible_years) > 1:
        label_by_name = {y['track_name']: y['label'] for y in visible_years}
        year_choice = st.selectbox(
            "Fiscal year",
            options=labels,
            index=labels.index(selected_year) if selected_year in labels else 0,
            format_func=lambda name: label_by_name.get(name, name),
            key="hub_track_year_selector",
            help="Two fiscal years overlap during a cutover — the year being worked "
                 "and the year that has just been promoted. Pick the one you want to "
                 "see.",
        )
        if year_choice != selected_year:
            st.session_state[SELECTED_YEAR_KEY] = year_choice
            st.rerun()

    if not year_is_writable:
        span = get_track_year_dates(selected_year)
        st.info(
            f"**Viewing {selected_year}**, which runs "
            f"{span['start'].strftime('%b %d, %Y')} – {span['end'].strftime('%b %d, %Y')} "
            f"and is not the active track. These tracks can be viewed and exported"
            + (f"; switch to **{active_label}** above for the active year."
               if active_label != selected_year else ".")
        )

    return selected_year, year_is_writable

def run_clinical_track_hub(selected_year=None, year_is_writable=True):
    """Run the original Clinical Track Hub functionality

    Args:
        selected_year (str, optional): the track cohort — fiscal year — being viewed.
            Everything the hub reads is scoped to it; None means the live cohort.
        year_is_writable (bool): whether track changes may be made against that year.
            Only the live cohort accepts them, so a closed year gets the read surfaces
            without the buttons the database would refuse anyway.
    """
    # Reads for the live year stay unscoped, exactly as they were: a track row still
    # carrying an older cycle's name is is_active and belongs in the live grid, and
    # scoping it away would quietly drop staff from the hub. Only a closed year has to
    # be fetched by name, because promotion is what cleared is_active on its rows.
    read_year = None if year_is_writable else selected_year
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
        st.caption(f"Generate complete {selected_year or 'fiscal year'} Google Calendar "
                   f"or iCal files from submitted tracks")
        
        # Get available staff
        try:
            staff_names = extract_staff_names_from_db(read_year)
            
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
            
            # Show fiscal year info for the year being exported, not a fixed FY26
            fiscal_info = get_fiscal_year_info(read_year)
            st.info(
                f"📊 **Export Period:** "
                f"{fiscal_info['fiscal_year_start'].strftime('%d %b %Y')} through "
                f"{fiscal_info['fiscal_year_end'].strftime('%d %b %Y')}"
                + (f" ({selected_year})" if selected_year else ""))
            
            # Preview section
            if selected_staff:
                with st.expander("📋 Preview Schedule (First 14 Days)", expanded=False):
                    try:
                        schedule_data = get_all_staff_schedules(read_year)
                        if selected_staff in schedule_data:
                            preview = preview_schedule(selected_staff,
                                                       schedule_data[selected_staff],
                                                       num_days=14,
                                                       track_name=read_year)
                            
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
                            file_content, filename = generate_calendar_for_staff(
                                selected_staff, format_type, track_name=read_year)
                        
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
                            st.info(f"🗓️ **Generated:** {datetime.now(_eastern_tz).strftime('%Y-%m-%d %H:%M:%S')}")
                            
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

    # Initialize database
    initialize_database()
    initialize_staff_tables()

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
        _init_cap = get_track_capacity((get_active_track_config() or {}).get('track_name', 'FY26'))
        st.session_state.max_day_nurses = _init_cap['max_day_nurses']
        st.session_state.max_day_medics = _init_cap['max_day_medics']
        st.session_state.max_night_nurses = _init_cap['max_night_nurses']
        st.session_state.max_night_medics = _init_cap['max_night_medics']
        st.session_state.enable_role_delta_filter = False
        st.session_state.day_delta_threshold = 3
        st.session_state.night_delta_threshold = 2
        st.session_state.preassignment_df = None

    if 'selected_staff' not in st.session_state:
        st.session_state.selected_staff = None

    # Preassignments for the cycle being viewed, from the database (authored per bid
    # cycle in the Track Bidding admin). They are per-cycle, so a fiscal year's grid has
    # to be drawn with its own. Naming it also settles what the default left ambiguous:
    # load_preassignments() falls back to the cycle bidding is open on, so while FY27
    # was out to bid the hub was locking FY26's grid against FY27's commitments.
    try:
        preassignment_df = load_preassignments(selected_year)
    except Exception as e:
        st.error(f"Error loading preassignments: {str(e)}")
        preassignment_df = None
    st.session_state.preassignment_df = preassignment_df

    # Administration used to be a wall of controls in this sidebar behind a
    # password box of its own: exports, database maintenance, restore, the
    # approvals queue, plus a dead Role Delta Filter whose widgets wrote to local
    # variables nothing read, a static list of validation rules, and an email
    # panel describing a Gmail setup the app stopped using. All of it now lives in
    # the Admin Console — one sign-in, one page — and the sidebar carries the door.
    render_admin_sidebar_entry("_hub")

    # MAIN PROCESSING
    #
    # Every frame here is built from the database, shaped exactly like the spreadsheets
    # they replace (Preferences v6, Requirements, Tracks) so the column detection and
    # every downstream consumer keep working unchanged.
    if staff_count(include_inactive=False):
        try:
            preferences_df = build_preferences_df()
            requirements_df = build_requirements_df()
            # Scoped to the fiscal year being viewed. A cohort that has stopped being
            # the live one still has months of shifts to work, so include_retired is
            # what keeps its grid readable after the next year is promoted.
            current_tracks_df = build_current_tracks_df(
                track_name=read_year, days=PATTERN_DAYS, include_retired=True)

            st.session_state.requirements_df = requirements_df

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
            
            # Create the master grid: every active clinical staff member against the
            # fixed 42-day pattern, whether or not they have a track yet.
            staff_names = current_tracks_df[staff_col_tracks].tolist()
            days = list(PATTERN_DAYS)

            # Save days to session state
            st.session_state.days = days

            # Initialize master dataframe
            master_df = pd.DataFrame(index=staff_names, columns=days)
            assignment_reasons = {}

            # Store initialization info in session state
            st.session_state.master_df = master_df
            st.session_state.assignment_reasons = assignment_reasons

        except Exception as e:
            st.error("An error occurred while loading the data. Please contact an administrator.")
    else:
        st.error("The staff database has no active staff yet. An administrator needs "
                 "to import the staff roster (Admin Console → Staff Database).")

    # ENHANCED STAFF SELECTION SECTION - Split Screen Layout with Fullscreen Option
    if st.session_state.master_df is not None:
        
        # Check if we're in fullscreen track viewer mode
        if st.session_state.get('track_viewer_fullscreen', False):
            display_track_viewer(read_year)
            st.stop()  # Prevent other content from rendering

        # Check if we're in fullscreen fiscal year mode
        if st.session_state.get('fy_show_fullscreen', False):
            add_fiscal_year_display_to_app(read_year)
            st.stop()  # Prevent other content from rendering
            
        # Track Swap and Track Management used to live here. Both are being rebuilt
        # with different functionality, so the hub is read-only for now: the track
        # viewer, the calendar export and the fiscal-year display.
        else:
            # Split layout: Left = Track Display, Right = Calendar Export + Fiscal Year
            left_col, right_col = st.columns(2, gap="large")
            
            # LEFT SIDE section
            with left_col:
                st.markdown("### Preferred Track Display")
                st.caption(f"View {selected_year or 'active'} tracks by role - "
                           f"informational purposes only")

                # Enhanced Track viewer component with fullscreen option
                display_track_viewer(read_year)

            # RIGHT SIDE: Calendar Export + Fiscal Year Track Display
            with right_col:
                # Calendar Export Section (TOP)
                display_calendar_export_section()
                
                st.markdown("---")  # Separator
                
                # Fiscal Year Display Section (BOTTOM)
                add_fiscal_year_display_to_app(read_year)
    else:
        st.info("Waiting for data to load. If no data appears, please contact an administrator.")
# SECURITY CHECK - This is the first thing that runs
if not display_user_login():
    st.stop()

# If we get here, user is authenticated - show session info
display_session_info()

# The roster, preassignment and CCEMT tables are read by every module, so make sure they
# exist regardless of which page the user lands on first.
initialize_staff_tables()
initialize_preassignment_tables()
initialize_ccemt_tables()

# The unified training database, for the same reason. It used to be built only on
# the way into Training & Events, so opening Summer Leave first — which asks it for
# the active training year — crashed the page outright.
if TRAINING_MODULES_AVAILABLE and 'unified_db' not in st.session_state:
    st.session_state.unified_db = UnifiedDatabase('data/medflight_tracks.db')
    st.session_state.unified_db.initialize_training_tables()

# Main Navigation Logic
if st.session_state.selected_module is None:
    # Show main CrewOps360 landing page
    display_module_selection()
elif st.session_state.selected_module == "clinical_track_hub":
    # Show Clinical Track Hub
    display_clinical_track_hub()
elif st.session_state.selected_module == "track_bidding":
    # Show Track Bidding
    display_track_bidding()
elif st.session_state.selected_module == "admin":
    # Show the Admin Console — the single entry point to every admin area
    display_admin_console()
elif st.session_state.selected_module == "training_events":
    # Show Training & Events application (FULL VERSION)
    display_training_events_app()
elif st.session_state.selected_module == "shift_location_preferences":
    # Show Shift Location Preferences module
    display_shift_location_preferences_module()
elif st.session_state.selected_module == "summer_leave":
    # Show Summer Leave Requests application
    # Initialize Excel handler and track manager if not already done
    # Kept under its own session keys rather than the training app's: those are scoped
    # to whichever training year is being viewed, and a year linked to a not-yet-active
    # track cohort would hand summer leave that cohort's tracks instead of the active
    # ones it needs.
    if 'summer_leave_excel_handler' not in st.session_state or st.session_state.summer_leave_excel_handler is None:
        # Summer leave only wants this for staff roles, which come from the staff
        # database. It used to insist the roster workbook was on disk to get them,
        # and stopped the page dead when it wasn't; the catalog needs no file.
        from training_modules.class_catalog import ClassCatalog
        unified_db = st.session_state.get('unified_db')
        active_year = unified_db.get_active_training_year() if unified_db else None
        st.session_state.summer_leave_excel_handler = ClassCatalog(
            (active_year or {}).get('year_label'))

    if 'summer_leave_track_manager' not in st.session_state or st.session_state.summer_leave_track_manager is None:
        from training_modules.track_manager import TrainingTrackManager
        st.session_state.summer_leave_track_manager = TrainingTrackManager('data/medflight_tracks.db')

        # Load tracks from database
        st.session_state.summer_leave_track_manager.reload_tracks()

        # CCEMT schedules come from the database; the enrollment workbook stays connected
        # as the fallback source of staff roles.
        st.session_state.summer_leave_track_manager.set_excel_handler(
            enrollment_excel_handler=st.session_state.summer_leave_excel_handler
        )

    display_summer_leave_app(
        st.session_state.summer_leave_excel_handler,
        st.session_state.summer_leave_track_manager
    )

