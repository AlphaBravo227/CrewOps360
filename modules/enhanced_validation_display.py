# modules/enhanced_validation_display.py
"""
Enhanced validation display module for track management
Provides comprehensive visualization of every track validation rule
"""

import streamlit as st
import pandas as pd
from .enhanced_track_validator import validate_track_comprehensive, format_validation_summary, get_validation_recommendations

def display_comprehensive_validation(track_data, days, shifts_per_pay_period, night_minimum, weekend_minimum=0, preassignments=None):
    """
    Display comprehensive validation dashboard
    
    Args:
        track_data (dict): Track data to validate
        days (list): Ordered list of days
        shifts_per_pay_period (int): Required shifts per pay period
        night_minimum (int): Minimum night shifts
        weekend_minimum (int): Minimum weekend shifts
        preassignments (dict, optional): Preassignment data
        
    Returns:
        bool: True if track is valid, False otherwise
    """
    # Run comprehensive validation
    validation_result = validate_track_comprehensive(
        track_data, shifts_per_pay_period, night_minimum, 
        weekend_minimum, preassignments, days
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
    
    # Create tabs for different validation categories
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Pay Period", "Night Minimum", "Weekend Minimum", 
        "Weekly Limits", "Rest Requirements", "Consecutive Shifts"
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
    
    # Display recommendations if there are issues
    if not validation_result['overall_valid']:
        st.markdown("### 💡 Recommendations")
        recommendations = get_validation_recommendations(validation_result)
        
        for i, rec in enumerate(recommendations, 1):
            st.markdown(f"{i}. {rec}")
    
    return validation_result['overall_valid']

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
                  'shifts_per_week', 'rest_requirements', 'consecutive_shifts']
    
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
        ("Consecutive Shifts", validation_result.get('consecutive_shifts', {}).get('status', False))
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
