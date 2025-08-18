# modules/enhanced_validation_display.py
"""
Enhanced validation display module for track management
Provides comprehensive visualization of all validation rules including weekend groups
"""

import streamlit as st
import pandas as pd
from .enhanced_track_validator import validate_track_comprehensive, format_validation_summary, get_validation_recommendations

def display_comprehensive_validation(track_data, days, shifts_per_pay_period, night_minimum, weekend_minimum=0, preassignments=None, weekend_group=None, requirements_df=None, staff_name=None):
    """
    Display comprehensive validation dashboard including weekend groups
    
    Args:
        track_data (dict): Track data to validate
        days (list): Ordered list of days
        shifts_per_pay_period (int): Required shifts per pay period
        night_minimum (int): Minimum night shifts
        weekend_minimum (int): Minimum weekend shifts
        preassignments (dict, optional): Preassignment data
        weekend_group (str, optional): Weekend group assignment (A, B, C, D, E)
        requirements_df (DataFrame, optional): Requirements DataFrame for weekend group lookup
        staff_name (str, optional): Staff name for weekend group lookup
        
    Returns:
        bool: True if track is valid, False otherwise
    """
    # Run comprehensive validation
    validation_result = validate_track_comprehensive(
        track_data, shifts_per_pay_period, night_minimum, 
        weekend_minimum, preassignments, days, weekend_group, requirements_df, staff_name
    )
    
    # Get formatted summary
    summary = format_validation_summary(validation_result)
    
    # Display overall status
    st.markdown("### 📊 Track Validation Dashboard")
    
    from modules.track_source_consistency import display_for_validation
    display_for_validation()
    
    if validation_result['overall_valid']:
        st.success("✅ **Track passes all validation requirements!**")
    else:
        st.error(f"❌ **Track has {summary['total_issues']} validation issues that must be fixed**")
    
    # Display quick stats
    col1, col2, col3 = st.columns(3)
    
    with col1:
        passed_count = sum(1 for cat in summary['categories'].values() if cat['status'])
        total_count = len(summary['categories'])
        st.metric("Requirements Passed", f"{passed_count}/{total_count}")
    
    with col2:
        st.metric("Total Issues", summary['total_issues'])
    
    with col3:
        status_emoji = "✅" if validation_result['overall_valid'] else "❌"
        st.metric("Overall Status", f"{status_emoji}")
    
    # Display detailed validation results
    st.markdown("### 📋 Detailed Validation Results")
    
    # Create tabs for different validation categories - UPDATED to include Weekend Groups
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Pay Period", "Night Minimum", "Weekend Minimum", 
        "Weekly Limits", "Rest Requirements", "Consecutive Shifts", "Weekend Groups"
    ])
    
    with tab1:
        display_pay_period_validation(validation_result['shifts_per_pay_period'])
    
    with tab2:
        display_night_minimum_validation(validation_result['night_minimum'])
    
    with tab3:
        display_weekend_minimum_validation(validation_result['weekend_minimum'])
    
    with tab4:
        display_weekly_limits_validation(validation_result['shifts_per_week'])
    
    with tab5:
        display_rest_requirements_validation(validation_result['rest_requirements'])
    
    with tab6:
        display_consecutive_shifts_validation(validation_result['consecutive_shifts'])
    
    with tab7:  # NEW: Weekend Groups tab
        display_weekend_group_validation(validation_result['weekend_group_assignment'])
    
    # Display recommendations if there are issues
    if not validation_result['overall_valid']:
        st.markdown("### 💡 Recommendations")
        recommendations = get_validation_recommendations(validation_result)
        
        for i, rec in enumerate(recommendations, 1):
            st.markdown(f"{i}. {rec}")
    
    return validation_result['overall_valid']

def display_weekend_group_validation(result):
    """Display weekend group validation details - NEW FUNCTION"""
    st.markdown("#### Weekend Group Assignment")
    
    if not result.get('weekend_group'):
        st.info("No weekend group assignment found for this staff member.")
        return
    
    weekend_group = result['weekend_group']
    
    if result['status']:
        st.success(f"✅ {result['details']}")
    else:
        st.error(f"❌ {result['details']}")
        
        if result['issues']:
            st.markdown("**Issues found:**")
            for issue in result['issues']:
                st.markdown(f"• {issue}")
    
    # Display weekend group information
    st.info(f"**Weekend Group:** {weekend_group}")
    
    # Show period validation details if available
    if 'periods_validated' in result and result['periods_validated']:
        st.markdown("**Period Details:**")
        
        periods_df_data = []
        for period_data in result['periods_validated']:
            status_icon = "✅" if period_data['valid'] else "❌"
            periods_df_data.append({
                "Period": f"Period {period_data['period']}",
                "Shifts Worked": period_data['shifts_worked'],
                "Shifts Required": period_data['shifts_required'],
                "Status": f"{status_icon}",
                "Details": ", ".join(period_data.get('details', []))
            })
        
        periods_df = pd.DataFrame(periods_df_data)
        st.dataframe(periods_df, use_container_width=True)
    
    # Show weekend days that are part of this group
    if 'weekend_days' in result and result['weekend_days']:
        st.markdown("**Weekend Days for Your Group:**")
        weekend_days_text = ", ".join(result['weekend_days'])
        st.markdown(f"🟡 {weekend_days_text}")
        st.info("These days will be highlighted in yellow in the track modification interface.")
    
    # Display weekend group rules
    st.info("""
    **Weekend Group Rules:**
    - Groups A & B: Work every other weekend (3 periods each)
    - Groups C, D & E: Work every third weekend (2 periods each)
    - Each period requires a minimum of 2 weekend shifts
    - Weekend shifts include: Friday nights, Saturday shifts, Sunday shifts
    """)

def display_pay_period_validation(result):
    """Display pay period validation details"""
    st.markdown("#### Shifts per Pay Period (Exact Match Required)")
    
    if result['status']:
        st.success(f"✅ {result['details']}")
    else:
        st.error(f"❌ {result['details']}")
        
        if result['issues']:
            st.markdown("**Issues found:**")
            for issue in result['issues']:
                st.markdown(f"• {issue}")
    
    st.info("**Rule:** Each 14-day pay period must have exactly the number of shifts specified in your requirements.")

def display_night_minimum_validation(result):
    """Display night minimum validation details"""
    st.markdown("#### Night Shift Minimum")
    
    if result['status']:
        st.success(f"✅ {result['details']}")
    else:
        st.error(f"❌ {result['details']}")
        
        if result['issues']:
            st.markdown("**Issues found:**")
            for issue in result['issues']:
                st.markdown(f"• {issue}")
    
    st.info("**Rule:** You must work at least the minimum number of night shifts specified in your requirements.")

def display_weekend_minimum_validation(result):
    """Display weekend minimum validation details"""
    st.markdown("#### Weekend Shift Minimum")
    
    if result['status']:
        st.success(f"✅ {result['details']}")
    else:
        st.error(f"❌ {result['details']}")
        
        if result['issues']:
            st.markdown("**Issues found:**")
            for issue in result['issues']:
                st.markdown(f"• {issue}")
    
    # Show weekend shifts found if available
    if 'weekend_shifts_found' in result:
        with st.expander("Weekend Shifts Found"):
            for shift in result['weekend_shifts_found']:
                st.markdown(f"• {shift}")
    
    st.info("**Rule:** Weekend shifts include Friday night shifts, and any Saturday or Sunday shifts (day, night, or AT).")

def display_weekly_limits_validation(result):
    """Display weekly limits validation details"""
    st.markdown("#### Weekly Shift Limits")
    
    if result['status']:
        st.success(f"✅ {result['details']}")
    else:
        st.error(f"❌ {result['details']}")
        
        if 'violations' in result:
            st.markdown("**Violations found:**")
            for violation in result['violations']:
                st.markdown(f"**Week {violation['week']}: {violation['count']} shifts**")
                with st.expander(f"Details for Week {violation['week']}"):
                    for shift in violation['shifts']:
                        st.markdown(f"• {shift}")
    
    st.info("**Rule:** No week can have 4 or more shifts. Maximum is 3 shifts per week.")

def display_rest_requirements_validation(result):
    """Display rest requirements validation details"""
    st.markdown("#### Rest Requirements")
    
    if result['status']:
        st.success(f"✅ {result['details']}")
    else:
        st.error(f"❌ {result['details']}")
        
        if 'violations' in result:
            st.markdown("**Violations found:**")
            
            for violation in result['violations']:
                if violation['type'] == 'AT_after_night':
                    st.markdown(f"• **AT Preassignment Issue:** {violation['description']}")
                elif violation['type'] == 'insufficient_rest_after_night':
                    st.markdown(f"• **Insufficient Rest:** {violation['description']}")
    
    st.info("""
    **Rules:**
    - AT preassignments cannot have a night shift on the preceding day
    - After a night shift, you must have 2 full unscheduled days before your next day shift
    """)

def display_consecutive_shifts_validation(result):
    """Display consecutive shifts validation details"""
    st.markdown("#### Consecutive Shifts Limits")
    
    if result['status']:
        st.success(f"✅ {result['details']}")
    else:
        st.error(f"❌ {result['details']}")
        
        if 'violations' in result:
            st.markdown("**Violations found:**")
            
            for violation in result['violations']:
                st.markdown(f"• **{violation['description']}**")
                
                with st.expander(f"Sequence Details ({violation['start_day']} to {violation['end_day']})"):
                    for day, shift in violation['shifts']:
                        shift_display = shift if shift != "AT" else "AT (Preassignment)"
                        st.markdown(f"• {day}: {shift_display}")
    
    st.info("""
    **Rule:** Maximum consecutive shifts allowed:
    - 4 shifts in a row if all are day shifts
    - 5 shifts in a row if the sequence includes at least one night shift
    """)

def display_validation_progress_bar(validation_result):
    """Display a progress bar showing validation completion"""
    categories = ['shifts_per_pay_period', 'night_minimum', 'weekend_minimum', 
                  'shifts_per_week', 'rest_requirements', 'consecutive_shifts', 'weekend_group_assignment']
    
    passed_count = sum(1 for cat in categories if validation_result.get(cat, {}).get('status', False))
    total_count = len(categories)
    
    progress = passed_count / total_count
    
    st.progress(progress)
    st.markdown(f"**Validation Progress:** {passed_count}/{total_count} requirements passed")

def display_validation_checklist(validation_result):
    """Display a checklist-style validation summary"""
    st.markdown("### ✅ Validation Checklist")
    
    checks = [
        ("Shifts per Pay Period", validation_result.get('shifts_per_pay_period', {}).get('status', False)),
        ("Night Minimum", validation_result.get('night_minimum', {}).get('status', False)),
        ("Weekend Minimum", validation_result.get('weekend_minimum', {}).get('status', False)),
        ("Weekly Limits", validation_result.get('shifts_per_week', {}).get('status', False)),
        ("Rest Requirements", validation_result.get('rest_requirements', {}).get('status', False)),
        ("Consecutive Shifts", validation_result.get('consecutive_shifts', {}).get('status', False)),
        ("Weekend Groups", validation_result.get('weekend_group_assignment', {}).get('status', False))
    ]
    
    for check_name, passed in checks:
        icon = "✅" if passed else "❌"
        color = "green" if passed else "red"
        st.markdown(f"{icon} <span style='color: {color}'>{check_name}</span>", unsafe_allow_html=True)

def create_validation_summary_card(validation_result):
    """Create a summary card for validation results"""
    is_valid = validation_result.get('overall_valid', False)
    
    if is_valid:
        card_color = "#d4edda"
        border_color = "#c3e6cb"
        icon = "✅"
        title = "Track Valid"
        message = "Your track meets all requirements and is ready for submission."
    else:
        card_color = "#f8d7da"
        border_color = "#f5c6cb"
        icon = "❌"
        title = "Issues Found"
        
        # Count issues
        total_issues = sum(len(result.get('issues', [])) for key, result in validation_result.items() 
                          if key != 'overall_valid' and isinstance(result, dict))
        message = f"Your track has {total_issues} issues that must be resolved before submission."
    
    st.markdown(f"""
    <div style="
        background-color: {card_color};
        border: 1px solid {border_color};
        border-radius: 5px;
        padding: 15px;
        margin: 10px 0;
    ">
        <h4 style="margin: 0 0 10px 0;">{icon} {title}</h4>
        <p style="margin: 0;">{message}</p>
    </div>
    """, unsafe_allow_html=True)

def get_weekend_group_highlighting_info(weekend_group, days):
    """
    Get information about which days should be highlighted for weekend group requirements
    
    Args:
        weekend_group (str): Weekend group (A, B, C, D, E)
        days (list): List of schedule days
        
    Returns:
        dict: Information about weekend highlighting
    """
    if not weekend_group:
        return {'highlight_days': [], 'weekend_group': None}
    
    try:
        # Use inline function to avoid import issues
        highlight_days = get_weekend_days_for_highlighting_inline(weekend_group, days)
        
        return {
            'highlight_days': highlight_days,
            'weekend_group': weekend_group,
            'highlight_color': '#fff3cd',  # Light yellow
            'highlight_info': f"Weekend Group {weekend_group} required days"
        }
    except Exception as e:
        return {'highlight_days': [], 'weekend_group': weekend_group, 'error': str(e)}

def get_weekend_days_for_highlighting_inline(weekend_group, days):
    """
    Get weekend days that should be highlighted for a specific weekend group
    """
    if not weekend_group:
        return []
    
    # Weekend group definitions
    WEEKEND_GROUPS = {
        'A': {
            'periods': [
                ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
                ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 2
                ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 3
            ]
        },
        'B': {
            'periods': [
                ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
                ['Fri B 3', 'Sat B 3', 'Sun B 4'],  # Period 2
                ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 3
            ]
        },
        'C': {
            'periods': [
                ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
                ['Fri B 3', 'Sat B 3', 'Sun B 4']   # Period 2
            ]
        },
        'D': {
            'periods': [
                ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
                ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 2
            ]
        },
        'E': {
            'periods': [
                ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 1
                ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 2
            ]
        }
    }
    
    if weekend_group not in WEEKEND_GROUPS:
        return []
    
    # Get all weekend days for the group
    all_weekend_days = []
    for period in WEEKEND_GROUPS[weekend_group]['periods']:
        all_weekend_days.extend(period)
    
    # Map to actual schedule days
    highlight_days = []
    for weekend_day in all_weekend_days:
        schedule_day = map_weekend_day_to_schedule_day_inline(weekend_day, days)
        if schedule_day:
            highlight_days.append(schedule_day)
    
    return highlight_days

def map_weekend_day_to_schedule_day_inline(weekend_day, days):
    """
    Map a weekend group day (e.g., 'Fri A 1') to actual schedule day
    """
    # Parse the weekend day format
    parts = weekend_day.split()
    if len(parts) != 3:
        return None
    
    day_name, block, week = parts
    
    # Find matching day in schedule
    for schedule_day in days:
        schedule_parts = schedule_day.split()
        if len(schedule_parts) >= 1:
            schedule_day_name = schedule_parts[0]
            
            # Check if day names match (Fri, Sat, Sun)
            if schedule_day_name == day_name:
                # Check if it contains the block and week
                if block in schedule_day and week in schedule_day:
                    return schedule_day
    
    return None