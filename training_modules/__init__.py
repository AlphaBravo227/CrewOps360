# training_modules/__init__.py
# Training modules for CrewOps360 integration with admin functions

from .unified_database import UnifiedDatabase
from .excel_handler import ExcelHandler
from .enrollment_manager import EnrollmentManager
from .ui_components import UIComponents
from .track_manager import TrainingTrackManager
from .admin_access import AdminAccess
from .admin_excel_functions import ExcelAdminFunctions, enhance_admin_reports
from .config import NON_CLASS_COLUMNS, DEFAULT_CLASS_DETAILS

__all__ = [
    'UnifiedDatabase', 
    'ExcelHandler', 
    'EnrollmentManager', 
    'UIComponents', 
    'TrainingTrackManager',
    'AdminAccess',
    'ExcelAdminFunctions',
    'enhance_admin_reports',
    'NON_CLASS_COLUMNS', 
    'DEFAULT_CLASS_DETAILS'
]