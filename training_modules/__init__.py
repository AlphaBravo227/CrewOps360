# training_modules/__init__.py - Updated to include AvailabilityAnalyzer
# Training modules for CrewOps360 integration with admin functions

from .unified_database import UnifiedDatabase
from .excel_handler import ExcelHandler
from .enrollment_manager import EnrollmentManager
from .ui_components import UIComponents
from .class_display_components import ClassDisplayComponents
from .enrollment_session_components import EnrollmentSessionComponents
from .staff_meeting_components import StaffMeetingComponents, EnrollmentDialogComponents
from .track_manager import TrainingTrackManager
from .admin_access import AdminAccess
from .admin_excel_functions import ExcelAdminFunctions, enhance_admin_reports
from .availability_analyzer import AvailabilityAnalyzer  # NEW
from .config import NON_CLASS_COLUMNS, DEFAULT_CLASS_DETAILS

__all__ = [
    'UIComponents',
    'ClassDisplayComponents', 
    'EnrollmentSessionComponents',
    'StaffMeetingComponents',
    'EnrollmentDialogComponents',
    'UnifiedDatabase', 
    'ExcelHandler', 
    'EnrollmentManager', 
    'TrainingTrackManager',
    'AdminAccess',
    'ExcelAdminFunctions',
    'enhance_admin_reports',
    'AvailabilityAnalyzer',  # NEW
    'NON_CLASS_COLUMNS', 
    'DEFAULT_CLASS_DETAILS'
]