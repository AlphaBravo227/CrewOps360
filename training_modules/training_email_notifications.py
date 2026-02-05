# training_modules/training_email_notifications.py
"""
Module for sending email notifications when staff enroll or cancel training events
within 60 days of the current date
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import streamlit as st
import os
import pytz

_eastern_tz = pytz.timezone('America/New_York')

class TrainingEmailNotifier:
    """Handle email notifications for training event enrollments and cancellations"""
    
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
                # Handle both string and list formats for notification_recipients
                recipients = st.secrets.email.get('notification_recipients', [])
                if isinstance(recipients, str):
                    # If it's a string, split by comma and strip whitespace
                    self.notification_recipients = [email.strip() for email in recipients.split(',') if email.strip()]
            else:
                # Fallback to environment variables
                self.app_password = os.getenv('GMAIL_APP_PASSWORD')
                recipients_str = os.getenv('EMAIL_NOTIFICATION_RECIPIENTS', '')
                self.notification_recipients = [email.strip() for email in recipients_str.split(',') if email.strip()]
            
            # Validate configuration
            if not self.app_password:
                st.warning("âš ï¸ Email notifications not configured. Please set up Gmail App Password.")
                self.configured = False
            else:
                self.configured = True
                
        except Exception as e:
            st.error(f"Error loading email configuration: {str(e)}")
            self.configured = False
    
    def is_within_60_days(self, class_date_str):
        """
        Check if a class date is within 60 days from today
        
        Args:
            class_date_str (str): Date string in format 'MM/DD/YYYY' or 'YYYY-MM-DD'
            
        Returns:
            bool: True if within 60 days, False otherwise
        """
        try:
            # Try parsing different date formats
            try:
                class_date = datetime.strptime(class_date_str, '%m/%d/%Y')
                # Make timezone-aware to match today
                class_date = _eastern_tz.localize(class_date)
            except ValueError:
                try:
                    class_date = datetime.strptime(class_date_str, '%Y-%m-%d')
                    # Make timezone-aware to match today
                    class_date = _eastern_tz.localize(class_date)
                except ValueError:
                    # If we can't parse the date, assume it's not within 60 days
                    return False

            today = datetime.now(_eastern_tz)
            days_until_class = (class_date - today).days
            
            # Check if class is within 60 days (including past classes up to today)
            return -1 <= days_until_class <= 60
            
        except Exception as e:
            print(f"Error checking date range: {e}")
            return False
    
    def send_training_notification(self, staff_name, class_name, class_date, role, 
                                   action_type, conflict_override=False, conflict_details=None,
                                   total_enrolled=None, class_time=None, class_location=None,
                                   meeting_type=None):
        """
        Send email notification for training enrollment or cancellation
        Only sends if class is within 60 days
        
        Args:
            staff_name (str): Name of staff member
            class_name (str): Name of the class
            class_date (str): Date of the class
            role (str): Role (Nurse, Medic, Educator)
            action_type (str): 'enrollment' or 'cancellation'
            conflict_override (bool): Whether conflicts were overridden
            conflict_details (str): Details about conflicts if any
            total_enrolled (int): Total number enrolled in class (optional)
            class_time (str): Time of the class (optional)
            class_location (str): Location of the class (optional)
            meeting_type (str): Type of meeting for staff meetings (LIVE or Virtual) (optional)
            
        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email notifications not configured")
        
        # Check if class is within 60 days
        if not self.is_within_60_days(class_date):
            return (True, "Class is more than 60 days away - notification not sent")
        
        try:
            # Generate email content
            subject, body = self.create_notification_content(
                staff_name, class_name, class_date, role, action_type,
                conflict_override, conflict_details, total_enrolled,
                class_time, class_location, meeting_type
            )
            
            # Send to all notification recipients
            recipients = []
                        
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
                return (True, "Training notification sent successfully.")
            else:
                return (False, "Failed to send email notification")
                
        except Exception as e:
            return (False, f"Error sending notification: {str(e)}")
    
    def create_notification_content(self, staff_name, class_name, class_date, role, 
                                   action_type, conflict_override, conflict_details, total_enrolled,
                                   class_time=None, class_location=None, meeting_type=None):
        """
        Create email subject and body content
        
        Args:
            staff_name (str): Name of staff member
            class_name (str): Name of the class
            class_date (str): Date of the class
            role (str): Role (Nurse, Medic, Educator)
            action_type (str): 'enrollment' or 'cancellation'
            conflict_override (bool): Whether conflicts were overridden
            conflict_details (str): Details about conflicts if any
            total_enrolled (int): Total number enrolled in class
            class_time (str): Time of the class (optional)
            class_location (str): Location of the class (optional)
            meeting_type (str): Type of meeting for staff meetings (LIVE or Virtual) (optional)
            
        Returns:
            tuple: (subject, body)
        """
        timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # Create subject
        action = "Enrollment" if action_type == "enrollment" else "Cancellation"
        subject = f"Boston MedFlight Training {action}: {staff_name} - {class_name}"
        
        # Create body
        body = f"""
Boston MedFlight Training Event Notification

ACTION: {action.upper()}
Staff Member: {staff_name}
Class Name: {class_name}
Class Date: {class_date}
Class Time: {class_time}
Class Location: {class_location}
Meeting Type: {meeting_type}
Role: {role}
Timestamp: {timestamp}
"""        
        # Add conflict information if applicable
        if conflict_override and conflict_details:
            body += f"""
CONFLICT OVERRIDE: Yes
Conflict Details: {conflict_details}
"""
        
        # Add total enrollment count if provided
        if total_enrolled is not None:
            body += f"""
Total Currently Enrolled: {total_enrolled}
"""
        
        body += """
---
This notification was automatically generated by the Boston MedFlight Training & Events system.
Only events within 60 days trigger email notifications.

To review enrollments, please access the Training & Events admin interface.
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
            
            # Create secure connection with more lenient SSL settings
            context = ssl.create_default_context()
            # Allow legacy server connections
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.sender_email, self.app_password)
                
                text = message.as_string()
                server.sendmail(self.sender_email, recipients, text)
            
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            print(f"Email authentication failed: {str(e)}")
            # Don't show error to user in UI to avoid cluttering success messages
            return False
        except smtplib.SMTPException as e:
            print(f"SMTP error occurred: {str(e)}")
            return False
        except Exception as e:
            print(f"Unexpected error sending email: {str(e)}")
            return False

# Global instance
training_email_notifier = TrainingEmailNotifier()

def send_training_event_notification(staff_name, class_name, class_date, role, 
                                     action_type, conflict_override=False, 
                                     conflict_details=None, total_enrolled=None,
                                     class_time=None, class_location=None, meeting_type=None):
    """
    Convenient function to send training event notification
    Only sends if class is within 60 days of current date
    
    Args:
        staff_name (str): Name of staff member
        class_name (str): Name of the class
        class_date (str): Date of the class
        role (str): Role (Nurse, Medic, Educator)
        action_type (str): 'enrollment' or 'cancellation'
        conflict_override (bool): Whether conflicts were overridden
        conflict_details (str): Details about conflicts if any
        total_enrolled (int): Total number enrolled in class (optional)
        class_time (str): Time of the class (optional)
        class_location (str): Location of the class (optional)
        meeting_type (str): Type of meeting for staff meetings (LIVE or Virtual) (optional)
        
    Returns:
        tuple: (success, message)
    """
    return training_email_notifier.send_training_notification(
        staff_name, class_name, class_date, role, action_type,
        conflict_override, conflict_details, total_enrolled,
        class_time, class_location, meeting_type
    )
