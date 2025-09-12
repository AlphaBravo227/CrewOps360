# Configuration settings for the Education Class Enrollment System

# Columns in the Class_Enrollment sheet that are NOT classes
# These columns will be excluded from class assignments
NON_CLASS_COLUMNS = [
    'STAFF NAME',
    'Role',
    'MGMT',
    'DUAL',
    'Educator AT',  # This is a designation, not a class
    # All other columns (CRM, STABLE, Wed SM Q1, etc.) are classes
]

# Default values for class details
DEFAULT_CLASS_DETAILS = {
    'students_per_class': 21,
    'nurses_medic_separate': 'No',
    'classes_per_day': 1,
    'is_two_day_class': 'No',
    'time_1_start': '08:00',
    'time_1_end': '16:00'
}

# Date format for display
DATE_FORMAT = '%m/%d/%Y'

# Time format for display
TIME_FORMAT = '%H:%M'