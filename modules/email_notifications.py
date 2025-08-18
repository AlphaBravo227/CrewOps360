# modules/email_notifications.py
"""
Module for sending email notifications when tracks are submitted
Secure Gmail integration with OAuth2 and App Password support
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from datetime import datetime
import streamlit as st
import os
import json
import base64
from email import encoders

class EmailNotifier:
    """Handle email notifications for track submissions"""
    
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.sender_email = "aaron.e.bell@gmail.com"
        
        # Load email configuration from environment or secrets
        self.load_email_config()
    
    def load_email_config(self):
        """Load email configuration from Streamlit secrets or environment variables"""
        try:
            # Try Streamlit secrets first (recommended for deployment)
            if hasattr(st, 'secrets') and 'email' in st.secrets:
                self.app_password = st.secrets.email.app_password
                # Fix: Handle both string and list formats for notification_recipients
                recipients = st.secrets.email.get('notification_recipients', [])
                if isinstance(recipients, str):
                    # If it's a string, split by comma and strip whitespace
                    self.notification_recipients = [email.strip() for email in recipients.split(',') if email.strip()]
                else:
                    # If it's already a list, use it directly
                    self.notification_recipients = recipients
                self.admin_email = st.secrets.email.get('admin_email', 'aaron.e.bell@gmail.com')
            else:
                # Fallback to environment variables
                self.app_password = os.getenv('GMAIL_APP_PASSWORD')
                recipients_str = os.getenv('EMAIL_NOTIFICATION_RECIPIENTS', '')
                self.notification_recipients = [email.strip() for email in recipients_str.split(',') if email.strip()]
                self.admin_email = os.getenv('ADMIN_EMAIL', 'aaron.e.bell@gmail.com')
            
            # Validate configuration
            if not self.app_password:
                st.warning("⚠️ Email notifications not configured. Please set up Gmail App Password.")
                self.configured = False
            else:
                self.configured = True
                
        except Exception as e:
            st.error(f"Error loading email configuration: {str(e)}")
            self.configured = False
    
    def send_track_submission_notification(self, staff_name, track_data, submission_type="update", track_id=None):
        """
        Send email notification when a track is submitted
        
        Args:
            staff_name (str): Name of staff member who submitted track
            track_data (dict): Track data that was submitted
            submission_type (str): "new" or "update"
            track_id (int, optional): Database track ID
            
        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email notifications not configured")
        
        try:
            # Generate email content
            subject, body = self.create_notification_content(staff_name, track_data, submission_type, track_id)
            
            # Send to all notification recipients
            recipients = []
            
            # Add admin email if configured
            if self.admin_email:
                recipients.append(self.admin_email)
            
            # Add notification recipients if configured
            if self.notification_recipients:
                for email in self.notification_recipients:
                    if email not in recipients:  # Only add if not already in list
                        recipients.append(email)
            
            # If no recipients configured, return error
            if not recipients:
                return (False, "No email recipients configured")
            
            # Send the email
            success = self.send_email(recipients, subject, body)
            
            if success:
                return (True, "Notification sent successfully.")
            else:
                return (False, "Failed to send email notification")
                
        except Exception as e:
            return (False, f"Error sending notification: {str(e)}")
    
    def create_notification_content(self, staff_name, track_data, submission_type, track_id):
        """
        Create email subject and body content
        
        Args:
            staff_name (str): Name of staff member
            track_data (dict): Track data
            submission_type (str): "new" or "update"
            track_id (int, optional): Track ID
            
        Returns:
            tuple: (subject, body)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Create subject
        action = "New Track Submitted" if submission_type == "new" else "Track Updated"
        subject = f"Boston MedFlight - {action}: {staff_name}"
        
        # Count shifts for summary
        total_shifts = sum(1 for assignment in track_data.values() if assignment in ["D", "N", "AT"])
        day_shifts = sum(1 for assignment in track_data.values() if assignment == "D")
        night_shifts = sum(1 for assignment in track_data.values() if assignment == "N")
        at_shifts = sum(1 for assignment in track_data.values() if assignment == "AT")
        
        # Count weekend shifts (including Friday nights, Saturday and Sunday shifts)
        weekend_shifts = 0
        for day, assignment in track_data.items():
            if not assignment or assignment not in ["D", "N", "AT"]:
                continue
                
            # Extract day name from the date string (e.g., "Fri 05/24")
            day_parts = day.split()
            if len(day_parts) > 0:
                day_name = day_parts[0]
                
                # Count Friday night shifts
                if day_name == "Fri" and assignment == "N":
                    weekend_shifts += 1
                # Count all Saturday and Sunday shifts (including AT)
                elif day_name in ["Sat", "Sun"] and assignment in ["D", "N", "AT"]:
                    weekend_shifts += 1
        
        # Create body with weekend shifts included
        body = f"""
    Boston MedFlight Track Submission Notification

    Staff Member: {staff_name}
    Submission Type: {submission_type.title()}
    Timestamp: {timestamp}
    Track ID: {track_id if track_id else 'N/A'}

    Track Summary:
    - Total Shifts: {total_shifts}
    - Day Shifts: {day_shifts}
    - Night Shifts: {night_shifts}
    - AT/Preassignments: {at_shifts}
    - Weekend Shifts: {weekend_shifts} (includes Friday nights, Saturdays, and Sundays)

    Weekend Breakdown:
    - Friday Night Shifts: {sum(1 for day, assignment in track_data.items() if day.split()[0] == "Fri" and assignment == "N")}
    - Saturday Shifts: {sum(1 for day, assignment in track_data.items() if day.split()[0] == "Sat" and assignment in ["D", "N", "AT"])}
    - Sunday Shifts: {sum(1 for day, assignment in track_data.items() if day.split()[0] == "Sun" and assignment in ["D", "N", "AT"])}

    This notification was automatically generated by the Boston MedFlight Track Generator system.

    To review tracks, please access the admin interface.
        """
        
        return subject, body
    
    def send_email(self, recipients, subject, body):
        """
        Send email using Gmail SMTP
        
        Args:
            recipients (list): List of recipient email addresses
            subject (str): Email subject
            body (str): Email body
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create message
            message = MIMEMultipart()
            message["From"] = self.sender_email
            message["To"] = ", ".join(recipients)
            message["Subject"] = subject
            
            # Add body to email
            message.attach(MIMEText(body, "plain"))
            
            # Create secure connection and send email
            context = ssl.create_default_context()
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.sender_email, self.app_password)
                
                text = message.as_string()
                server.sendmail(self.sender_email, recipients, text)
            
            return True
            
        except smtplib.SMTPAuthenticationError:
            st.error("Email authentication failed. Please check Gmail App Password.")
            return False
        except smtplib.SMTPException as e:
            st.error(f"SMTP error occurred: {str(e)}")
            return False
        except Exception as e:
            st.error(f"Unexpected error sending email: {str(e)}")
            return False
    
    def test_email_configuration(self):
        """
        Test email configuration by sending a test email
        
        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email not configured")
        
        try:
            test_subject = "Boston MedFlight - Email Configuration Test"
            test_body = f"""
This is a test email to verify email notifications are working correctly.

Timestamp: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Sender: {self.sender_email}

If you receive this email, the notification system is working properly.
            """
            
            recipients = [self.admin_email]
            success = self.send_email(recipients, test_subject, test_body)
            
            if success:
                return (True, f"Test email sent successfully to {self.admin_email}")
            else:
                return (False, "Failed to send test email")
                
        except Exception as e:
            return (False, f"Error testing email: {str(e)}")

# Global instance
email_notifier = EmailNotifier()

def send_track_submission_notification(staff_name, track_data, submission_type="update", track_id=None):
    """
    Convenient function to send track submission notification
    
    Args:
        staff_name (str): Name of staff member who submitted track
        track_data (dict): Track data that was submitted
        submission_type (str): "new" or "update"
        track_id (int, optional): Database track ID
        
    Returns:
        tuple: (success, message)
    """
    return email_notifier.send_track_submission_notification(staff_name, track_data, submission_type, track_id)

def test_email_configuration():
    """
    Test email configuration
    
    Returns:
        tuple: (success, message)
    """
    return email_notifier.test_email_configuration()
