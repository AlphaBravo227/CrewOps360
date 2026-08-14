# ui_components.py
"""
UI components for the Streamlit application
"""

import streamlit as st
import pandas as pd
import html


def render_section_banner(title, subtitle=None, eyebrow=None, accent="#3498db", background="#eef5fc"):
    """
    Render a colored, left-bordered section header.

    Used where one page carries two different things a staff member can do (e.g.
    the Track Bidding page, which hosts both the bid itself and the Track Needs
    swap offers) so it's obvious at a glance where one section ends and the next
    begins. Give each section its own accent color.

    Args:
        title (str): Section heading text (emoji fine).
        subtitle (str): Optional one-line description under the title.
        eyebrow (str): Optional small uppercase label above the title.
        accent (str): Border/eyebrow color.
        background (str): Banner fill color.

    All text is escaped — pass plain strings, not HTML.
    """
    # Built as a single line with no blank lines: CommonMark ends an HTML block at
    # the first blank line, which would dump the rest out as literal escaped text.
    parts = []
    if eyebrow:
        parts.append(
            f'<div style="font-size:0.72rem; font-weight:700; letter-spacing:0.09em; '
            f'text-transform:uppercase; color:{accent};">{html.escape(str(eyebrow))}</div>'
        )
    parts.append(
        f'<div style="font-size:1.45rem; font-weight:700; color:#2c3e50; line-height:1.3; '
        f'margin-top:2px;">{html.escape(str(title))}</div>'
    )
    if subtitle:
        parts.append(
            f'<div style="font-size:0.95rem; color:#4b5563; margin-top:6px; line-height:1.4;">'
            f'{html.escape(str(subtitle))}</div>'
        )
    st.markdown(
        f'<div style="border-left:6px solid {accent}; background:{background}; '
        f'border-radius:8px; padding:14px 18px; margin:6px 0 18px 0;">' + "".join(parts) + '</div>',
        unsafe_allow_html=True
    )


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
