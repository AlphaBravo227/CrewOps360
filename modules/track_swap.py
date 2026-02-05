# modules/track_swap.py
"""
Track Swap submission module for Clinical Track Hub
Integrates with existing email notification system
FIXED: Proper success notifications that persist across page rerun
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import time
import pytz

_eastern_tz = pytz.timezone('America/New_York')
from .email_notifications import email_notifier
from .db_utils import save_track_swap_to_db

def display_track_swap_section():
    """
    Display the Track Swap submission section in the main landing area
    Styled consistently with Track Management section
    """
    st.markdown("### Submit a Track Swap")
    
    # Get staff names from master_df if available
    if st.session_state.get('master_df') is not None:
        staff_names = st.session_state.master_df.index.tolist()
        
        # Swap submission button
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Submit Track Swap Request", use_container_width=True, type="primary"):
            st.session_state.show_swap_form = True
            st.rerun()
    else:
        st.warning("Staff data not available for track swaps")

def display_swap_success_page():
    """
    Display the success page after swap submission
    This function handles the success notifications properly
    """
    success_data = st.session_state.get('swap_submission_success')
    
    if success_data:
        # Main success message with prominent styling
        st.success("🎉 **Track Swap Request Submitted Successfully!**")
        
        # Request details
        st.info(f"📋 **Request ID: #{success_data['swap_id']}** - Your swap request has been logged in the system")
        
        # Email confirmation
        st.info("📧 Email notifications have been sent to the administration team and your email address.")
        
        # Clear instruction to return to Hub
        st.markdown("---")
        st.markdown("### ✨ What's Next?")
        st.markdown("Your track swap request has been submitted for approval. You can now return to the main Hub.")
        
        # Return to Hub button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🏠 Return to Hub", use_container_width=True, type="primary"):
                # Clear the success state and timer
                if 'swap_submission_success' in st.session_state:
                    del st.session_state['swap_submission_success']
                if 'success_start_time' in st.session_state:
                    del st.session_state['success_start_time']
                st.rerun()
        
        # Auto-redirect with countdown timer
        if 'success_start_time' not in st.session_state:
            st.session_state['success_start_time'] = time.time()
        
        elapsed = time.time() - st.session_state['success_start_time']
        auto_redirect_delay = 15  # 15 seconds before auto-redirect
        
        if elapsed > auto_redirect_delay:
            st.markdown("*Automatically redirecting to main page...*")
            # Clear success state
            if 'swap_submission_success' in st.session_state:
                del st.session_state['swap_submission_success']
            if 'success_start_time' in st.session_state:
                del st.session_state['success_start_time']
            st.rerun()
        else:
            remaining = int(auto_redirect_delay - elapsed)
            st.markdown(f"*Automatically redirecting to main page in {remaining} seconds...*")
            # Use st.empty() and sleep for smoother countdown
            time.sleep(1)
            st.rerun()
        
        return True  # Indicates success page is being shown
    
    return False  # No success page to show

def display_track_swap_form():
    """
    Display the track swap submission form
    FIXED: Proper handling of success notifications
    """
    # DON'T check for success page here - that's handled in handle_track_swap_navigation()
    
    st.markdown("## Track Swap Request Form")
    st.markdown("---")
    
    # Get staff names for dropdowns
    if st.session_state.get('master_df') is not None:
        staff_names = [""] + st.session_state.master_df.index.tolist()
    else:
        st.error("Staff data not available")
        return
    
    # Form container
    with st.form("track_swap_form"):
        st.markdown("### Requester Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            requester_last_name = st.selectbox(
                "Your Name *",
                staff_names,
                help="Select from dropdown"
            )
            
        with col2:
            requester_email = st.text_input(
                "Your Email Address *", 
                placeholder="ex.ab227@bostonmedflight.com",
                help="Email address where confirmation will be sent"
            )
        
        st.markdown("### Swap Details")
        
        col3, col4 = st.columns(2)
        
        with col3:
            other_member_last_name = st.selectbox(
                "Other Member *",
                staff_names,
                help="Select from dropdown"
            )
        
        swap_details = st.text_area(
            "Swap Details *",
            placeholder="Please describe the swap request in detail:\n\n- Which specific shifts/days you want to swap",
            height=150,
            help="Provide as much detail as possible about the requested swap"
        )
                
        # Form submission
        col7, col8, col9 = st.columns([1, 2, 1])
        
        with col7:
            if st.form_submit_button("Cancel", use_container_width=True):
                st.session_state.show_swap_form = False
                st.rerun()
        
        with col8:
            submit_swap = st.form_submit_button("Submit Swap Request For Approval", use_container_width=True, type="primary")
        
        # Form validation and submission
        if submit_swap:
            # Validate required fields
            errors = []
            
            if not requester_last_name.strip():
                errors.append("Your last name is required")
            
            if not requester_email.strip():
                errors.append("Your email address is required")
            elif "@" not in requester_email:
                errors.append("Please enter a valid email address")
            
            if not other_member_last_name.strip():
                errors.append("Other member's last name is required")
            
            if not swap_details.strip():
                errors.append("Swap details are required")
            
            # Show errors if any
            if errors:
                st.error("Please correct the following errors:")
                for error in errors:
                    st.write(f"• {error}")
            else:
                # Process the swap request
                success, message, swap_id = submit_track_swap_request(
                    requester_last_name=requester_last_name,
                    requester_email=requester_email,
                    other_member_last_name=other_member_last_name,
                    swap_details=swap_details
                )
                
                if success:
                    # Store success state in session to persist across rerun
                    st.session_state['swap_submission_success'] = {
                        'swap_id': swap_id,
                        'message': message,
                        'timestamp': datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S"),
                        'requester': requester_last_name,
                        'other_member': other_member_last_name
                    }
                    
                    # Hide the form
                    st.session_state.show_swap_form = False
                    
                    # Show balloons effect for successful submission
                    st.balloons()
                    
                    # Rerun to show success page
                    st.rerun()
                    
                else:
                    st.error(f"❌ {message}")

def submit_track_swap_request(requester_last_name, requester_email, other_member_last_name, 
                             swap_details):
    """
    Submit the track swap request with database logging and email notifications
    
    Args:
        requester_last_name (str): Last name of the person requesting the swap
        requester_email (str): Email of the requester
        other_member_last_name (str): Last name of the other person involved
        swap_details (str): Details of the swap request
        
    Returns:
        tuple: (success, message, swap_id)
    """
    try:
        # Save to database first
        db_success, db_message, swap_id = save_track_swap_to_db(
            requester_last_name, 
            requester_email, 
            other_member_last_name, 
            swap_details
        )
        
        if not db_success:
            return (False, f"Database error: {db_message}", None)
        
        # Create swap request data for email
        swap_data = {
            'requester_last_name': requester_last_name,
            'requester_email': requester_email,
            'other_member_last_name': other_member_last_name,
            'swap_details': swap_details,
            'submission_timestamp': datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S"),
            'swap_id': swap_id
        }
        
        # Send email notification using existing email system
        email_success = send_track_swap_notification(swap_data)
        
        if email_success:
            return (True, f"Track swap request submitted successfully (ID: {swap_id})", swap_id)
        else:
            return (True, f"Track swap saved to database (ID: {swap_id}), but email notification failed", swap_id)
        
    except Exception as e:
        st.error(f"Error submitting swap request: {str(e)}")
        return (False, f"Error submitting swap request: {str(e)}", None)

def send_track_swap_notification(swap_data):
    """
    Send email notification for track swap request using existing email system
    
    Args:
        swap_data (dict): Swap request data including swap_id
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not email_notifier.configured:
        st.warning("Email notifications not configured - swap saved to database only")
        return False
    
    try:
        # Create email subject and body
        subject = f"Boston MedFlight - Track Swap Request #{swap_data['swap_id']}: {swap_data['requester_last_name']} ↔ {swap_data['other_member_last_name']}"
        
        body = f"""
Boston MedFlight Track Swap Request

SWAP REQUEST ID: #{swap_data['swap_id']}

REQUESTER INFORMATION:
- Name: {swap_data['requester_last_name']}
- Email: {swap_data['requester_email']}

SWAP DETAILS:
- Other Member: {swap_data['other_member_last_name']}
- Submission Time: {swap_data['submission_timestamp']}

SWAP REQUEST DETAILS:
{swap_data['swap_details']}

---
Please review this swap request and take appropriate action.
Swap requests are now logged in the database for tracking and audit purposes.

This notification was automatically generated by the Boston MedFlight Track Generator system.
        """
        
        # Get recipients (same as track submission notifications)
        recipients = []
        
        # Add admin email if configured
        if email_notifier.admin_email:
            recipients.append(email_notifier.admin_email)
        
        # Add notification recipients if configured
        if email_notifier.notification_recipients:
            for email in email_notifier.notification_recipients:
                if email not in recipients:
                    recipients.append(email)
        
        # Also send confirmation to the requester
        if swap_data['requester_email'] not in recipients:
            recipients.append(swap_data['requester_email'])
        
        if not recipients:
            st.error("No email recipients configured")
            return False
        
        # Send the email
        success = email_notifier.send_email(recipients, subject, body)
        
        return success
        
    except Exception as e:
        st.error(f"Error sending swap notification: {str(e)}")
        return False

def handle_track_swap_navigation():
    """
    Handle navigation for track swap functionality
    Call this in main app.py to manage swap form display
    FIXED: Now handles both form display AND success page display
    """
    # Check if we should show the success page first
    if st.session_state.get('swap_submission_success'):
        display_swap_success_page()
        return True  # Indicates success page is being shown
    
    # Check if we should show the swap form
    if st.session_state.get('show_swap_form', False):
        display_track_swap_form()
        return True  # Indicates form is being shown
    
    return False  # Normal operation