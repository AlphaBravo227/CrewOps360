# ui_components.py
"""
UI components for the Streamlit application
"""

import streamlit as st
import pandas as pd

def display_roster_results(staff_info, actual_shifts, the_list, role_col, staff_col, no_matrix_col):
    """
    Display roster results in an expandable section
    
    Args:
        staff_info (DataFrame): DataFrame containing staff information
        actual_shifts (int): Number of shifts that will be staffed
        the_list (DataFrame): DataFrame of staff ordered by seniority
        role_col (str): Column name for staff roles
        staff_col (str): Column name for staff names
        no_matrix_col (str): Column name for no matrix status
    """
    with st.expander("Roster Results", expanded=True):
        # Display counts
        total_staff = len(staff_info)
        nurse_count = len(staff_info[staff_info[role_col] == "nurse"])
        medic_count = len(staff_info[staff_info[role_col] == "medic"])
        dual_count = len(staff_info[staff_info[role_col] == "dual"])
        no_matrix_count = len(staff_info[staff_info[no_matrix_col] == 1])
        
        # Create metrics with improved visualization
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric("Total Staff", total_staff)
        col1.metric("No Matrix Staff", no_matrix_count)
        
        col2.metric("Nurses", nurse_count)
        col2.metric("Medics", medic_count)
        
        col3.metric("Dual Providers", dual_count)
        col3.metric("Role Delta", abs(nurse_count - medic_count))
        
        col4.metric("ZENITH (Max Shifts)", total_staff // 2)
        col4.metric("ACTUAL Shifts", actual_shifts)
        
        # Display THE LIST
        st.subheader("The LIST (Staff Ordered by Seniority)")
        st.dataframe(the_list, use_container_width=True)
        
        # Add staff distribution chart
        st.subheader("Staff Role Distribution")
        role_counts = {
            "Nurses": nurse_count,
            "Medics": medic_count,
            "Dual": dual_count
        }
        
        role_df = pd.DataFrame(list(role_counts.items()), columns=['Role', 'Count'])
        st.bar_chart(role_df.set_index('Role'))
