# Track Source Display Consistency Fix
# This module ensures that all 📊 icons display consistent track source information

import streamlit as st

def get_track_source_display_info():
    """
    Centralized function to get consistent track source display information
    
    Returns:
        dict: Contains mode, display_text, and styling information
    """
    # Get the current mode from session state
    track_source = st.session_state.get('track_source', "Annual Rebid")
    use_database_logic = track_source == "Annual Rebid"
    
    # FIXED: Check for Current Track Changes mode correctly
    if track_source == "Current Track Changes":
        return {
            'mode': 'In-Year Modifications',
            'display_text': '📊 Using Current Track Changes Mode: Shift availability depends on current staffing levels.',
            'style': 'info',
            'icon': '📊',
            'short_text': 'Current Track Changes Mode',
            'description': 'Shift availability depends on current staffing levels.'
        }
    else:  # Annual Rebid mode
        return {
            'mode': 'Annual Rebid',
            'display_text': '📊 Annual Rebid Mode: Previous tracks cleared, new tracks selected by seniority.',
            'style': 'info',
            'icon': '📊',
            'short_text': 'Annual Rebid Mode',
            'description': 'Previous tracks cleared, new tracks selected by seniority.'
        }

def get_track_data_source_info(selected_staff, has_db_track=None):
    """
    Get information about the specific data source for a staff member's track
    
    Args:
        selected_staff (str): Name of the selected staff member
        has_db_track (bool, optional): Whether staff has database track
        
    Returns:
        dict: Contains source information for display
    """
    if has_db_track is None:
        has_db_track = st.session_state.get('has_db_track', False)
    
    track_source = st.session_state.get('track_source', "Annual Rebid")
    
    # Check if we have a database track
    if has_db_track:
        if track_source == "Annual Rebid":
            return {
                'source': 'Database',
                'display_text': '📊 This track is from the Annual Rebid database.',
                'style': 'info',
                'icon': '📊'
            }
        else:  # Current Track Changes mode with database track
            return {
                'source': 'Imported Track',
                'display_text': '📊 This track is from the Imported Tracks.',
                'style': 'info',
                'icon': '📊'
            }
    else:
        # No database track
        if track_source == "Annual Rebid":
            return {
                'source': 'New Track',
                'display_text': '📊 Creating new track for Annual Rebid.',
                'style': 'info',
                'icon': '📊'
            }
        else:  # Current Track Changes mode without database track
            return {
                'source': 'Excel Reference',
                'display_text': '📊 This track is from the Current Track Changes reference file.',
                'style': 'info',
                'icon': '📊'
            }

def display_track_source_info(location="general"):
    """
    Display consistent track source information wherever the 📊 icon appears
    
    Args:
        location (str): Location context for customized messaging
    """
    source_info = get_track_source_display_info()
    
    if location == "current_track_tab":
        st.info(source_info['display_text'])
    elif location == "track_modification":
        st.info(source_info['display_text'])
    elif location == "validation":
        st.info(source_info['display_text'])
    elif location == "submission":
        st.info(source_info['display_text'])
    else:
        st.info(source_info['display_text'])

def display_track_data_source_info(selected_staff, location="general"):
    """
    Display information about the specific data source for a staff member's track
    
    Args:
        selected_staff (str): Name of the selected staff member
        location (str): Location context for customized messaging
    """
    # Get database track status
    from modules.db_utils import get_track_from_db
    db_result = get_track_from_db(selected_staff)
    has_db_track = db_result[0]
    
    source_info = get_track_data_source_info(selected_staff, has_db_track)
    
    if location == "current_track_tab":
        st.info(source_info['display_text'])
    elif location == "track_modification":
        st.info(source_info['display_text'])
    else:
        st.info(source_info['display_text'])

def update_track_source_displays():
    """
    MISSING FUNCTION - NOW ADDED
    Update all track source displays to ensure consistency
    This should be called whenever the mode changes
    """
    # Force refresh of session state values
    if 'track_source_display_info' in st.session_state:
        del st.session_state['track_source_display_info']
    
    # Get fresh display info
    st.session_state['track_source_display_info'] = get_track_source_display_info()

# Validation function to check consistency
def validate_track_source_consistency():
    """
    Validate that all track source displays are consistent
    
    Returns:
        dict: Validation results
    """
    issues = []
    
    # Check if track_source is set
    if 'track_source' not in st.session_state:
        issues.append("track_source not set in session state")
    
    # Check if mode matches expected values
    track_source = st.session_state.get('track_source', "")
    if track_source not in ["Annual Rebid", "Current Track Changes"]:
        issues.append(f"Invalid track_source value: {track_source}")
    
    # Check for conflicting settings
    if 'TRACK_SOURCE_MODE' in st.session_state:
        hardcoded_mode = st.session_state.get('TRACK_SOURCE_MODE')
        if hardcoded_mode == "Annual Rebid" and track_source != "Annual Rebid":
            issues.append("Hardcoded mode doesn't match session state")
        elif hardcoded_mode == "In Year Modifications" and track_source != "Current Track Changes":
            issues.append("Hardcoded mode doesn't match session state")
    
    return {
        'valid': len(issues) == 0,
        'issues': issues
    }

# Helper functions for specific components
def get_current_track_tab_display():
    """Get display text for Current Track tab"""
    source_info = get_track_source_display_info()
    return source_info['display_text']

def get_track_modification_display():
    """Get display text for Track Modification tab"""
    source_info = get_track_source_display_info()
    return source_info['display_text']

def get_validation_display():
    """Get display text for Validation tab"""
    source_info = get_track_source_display_info()
    return source_info['display_text']

def get_submission_display():
    """Get display text for Submission tab"""
    source_info = get_track_source_display_info()
    return source_info['display_text']

# Configuration check function
def check_mode_configuration():
    """
    Check if the application mode is properly configured
    
    Returns:
        dict: Configuration status
    """
    # Check hardcoded mode in app.py
    hardcoded_mode = None
    try:
        # This would need to be imported from app.py or passed as parameter
        # For now, we'll check session state
        if 'TRACK_SOURCE_MODE' in st.session_state:
            hardcoded_mode = st.session_state['TRACK_SOURCE_MODE']
    except:
        pass
    
    session_mode = st.session_state.get('track_source', "Annual Rebid")
    
    return {
        'hardcoded_mode': hardcoded_mode,
        'session_mode': session_mode,
        'consistent': hardcoded_mode is None or (
            (hardcoded_mode == "Annual Rebid" and session_mode == "Annual Rebid") or
            (hardcoded_mode == "In Year Modifications" and session_mode == "Current Track Changes")
        )
    }

# Main update function to call from app.py
def ensure_track_source_consistency():
    """
    Ensure all track source displays are consistent with the current mode
    Call this function at the beginning of app.py or whenever mode changes
    """
    # Update display info
    update_track_source_displays()
    
    # Validate consistency
    validation = validate_track_source_consistency()
    
    if not validation['valid']:
        st.error(f"Track source consistency issues: {', '.join(validation['issues'])}")
        return False
    
    return True

# Example usage functions for each location where 📊 appears
def display_for_current_track_tab(selected_staff):
    """Display track source info in Current Track tab"""
    display_track_source_info("current_track_tab")
    display_track_data_source_info(selected_staff, "current_track_tab")

def display_for_track_modification(selected_staff):
    """Display track source info in Track Modification tab"""
    display_track_source_info("track_modification")
    display_track_data_source_info(selected_staff, "track_modification")

def display_for_validation():
    """Display track source info in Validation tab"""
    display_track_source_info("validation")

def display_for_submission():
    """Display track source info in Submission tab"""
    display_track_source_info("submission")

# DEBUGGING FUNCTIONS - Add these for troubleshooting
def debug_session_state():
    """Debug function to show current session state values"""
    st.write("DEBUG: Current session state values:")
    st.write(f"- track_source: {st.session_state.get('track_source', 'NOT SET')}")
    st.write(f"- TRACK_SOURCE_MODE: {st.session_state.get('TRACK_SOURCE_MODE', 'NOT SET')}")
    
    # Check hardcode in app.py - this would need to be passed as parameter
    validation = check_mode_configuration()
    st.write(f"- Configuration status: {validation}")

def force_mode_reset():
    """Force reset the mode to match hardcoded setting"""
    hardcoded_mode = st.session_state.get('TRACK_SOURCE_MODE', 'In Year Modifications')
    
    if hardcoded_mode == "In Year Modifications":
        st.session_state.track_source = "Current Track Changes"
        st.success("✅ Forced mode reset to In-Year Modifications")
    else:
        st.session_state.track_source = "Annual Rebid"
        st.success("✅ Forced mode reset to Annual Rebid")
    
    # Clear cached info
    if 'track_source_display_info' in st.session_state:
        del st.session_state['track_source_display_info']