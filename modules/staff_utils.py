# staff_utils.py
"""
Utility functions for staff-specific rules and conflicts
"""

def is_special_conflict(staff1, staff2):
    """
    Check for special conflicts in staffing
    
    Args:
        staff1 (str): Name of first staff member
        staff2 (str): Name of second staff member
        
    Returns:
        bool: True if there's a special conflict, False otherwise
    """
    # Phillips K. and Phillips R. can't work together
    if staff1 in ["Phillips K.", "Phillips R."] and staff2 in ["Phillips K.", "Phillips R."]:
        return True
    # Boomhower and King can't work together
    if staff1 in ["Boomhower", "King"] and staff2 in ["Boomhower", "King"]:
        return True
    return False
