# modules/sample_data.py
"""
Module for loading sample data for development and testing
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

_eastern_tz = pytz.timezone('America/New_York')

def load_sample_data():
    """
    Load sample data for development and testing
    
    Returns:
        tuple: (preferences_df, current_tracks_df, requirements_df)
    """
    # Create sample preferences data
    preferences_data = {
        'Staff Name': ['Smith, John', 'Johnson, Emily', 'Williams, David', 'Brown, Sarah', 'Jones, Michael', 
                      'Garcia, Maria', 'Miller, Robert', 'Davis, Lisa', 'Rodriguez, James', 'Martinez, Jennifer'],
        'Role': ['nurse', 'medic', 'dual', 'nurse', 'medic', 'nurse', 'medic', 'dual', 'nurse', 'medic'],
        'No Matrix': [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        'Reduced Rest OK': [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        'Seniority': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    }
    
    # Add shift preferences (1-10 scale)
    for shift in ['D7B', 'D7P', 'D9L', 'D11M', 'D11B', 'FW', 'MG', 'GR', 'LG', 'PG',
                 'N7B', 'N7P', 'N9L', 'NG', 'NP']:
        # Generate random preferences (1-10)
        preferences_data[shift] = np.random.randint(1, 11, size=len(preferences_data['Staff Name']))
    
    # Create sample current tracks data
    # First, generate the column names (6 weeks of days)
    start_date = datetime.now(_eastern_tz) - timedelta(days=datetime.now(_eastern_tz).weekday())  # Start from the most recent Monday
    days = []
    
    for i in range(42):  # 6 weeks = 42 days
        day = start_date + timedelta(days=i)
        day_str = day.strftime('%a %m/%d')  # e.g., "Mon 01/01"
        days.append(day_str)
    
    # Create the dataframe
    current_tracks_data = {'Staff Name': preferences_data['Staff Name']}
    
    # Generate random shift assignments
    for day in days:
        # For each staff member, randomly assign D, N, or nothing
        shift_assignments = []
        
        for i in range(len(preferences_data['Staff Name'])):
            # Ensure approximately 50% of days have shifts, evenly split between D and N
            rand_val = np.random.rand()
            if rand_val < 0.25:
                shift_assignments.append('D')
            elif rand_val < 0.5:
                shift_assignments.append('N')
            else:
                shift_assignments.append('')
        
        current_tracks_data[day] = shift_assignments
    
    # Create the requirements data
    requirements_data = {
        'STAFF NAME': preferences_data['Staff Name'],
        'SHIFTS PER WEEK': [5] * len(preferences_data['Staff Name']),
        'NIGHT MINIMUM': [2] * len(preferences_data['Staff Name'])
    }
    
    # Create DataFrames
    preferences_df = pd.DataFrame(preferences_data)
    current_tracks_df = pd.DataFrame(current_tracks_data)
    requirements_df = pd.DataFrame(requirements_data)
    
    return preferences_df, current_tracks_df, requirements_df