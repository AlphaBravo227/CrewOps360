# modules/email_notifications.py
"""
Module for sending email notifications when tracks are submitted
Secure Gmail integration with OAuth2 and App Password support
"""

import smtplib
import ssl
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from datetime import datetime
import streamlit as st
import os
import json
import base64
import pytz

_eastern_tz = pytz.timezone('America/New_York')
from email import encoders

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

class EmailNotifier:
    """Handle email notifications for track submissions"""
    
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.sender_email = "aaron.e.bell@gmail.com"
        self.display_email = "notifications@crewops360.com"   # Domain address shown to recipients

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
        timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        
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
            # Display domain address — recipients see "CrewOps360 Notifications <notifications@crewops360.com>"
            message["From"] = f"CrewOps360 Notifications <{self.display_email}>"
            message["Reply-To"] = self.display_email
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

    def send_email_with_attachment(self, recipients, subject, body, attachment_bytes, attachment_filename):
        """
        Send email using Gmail SMTP with a single binary attachment (e.g. a PDF)

        Args:
            recipients (list): List of recipient email addresses
            subject (str): Email subject
            body (str): Email body
            attachment_bytes (bytes): Raw attachment content
            attachment_filename (str): Filename to present the attachment as

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            message = MIMEMultipart()
            message["From"] = f"CrewOps360 Notifications <{self.display_email}>"
            message["Reply-To"] = self.display_email
            message["To"] = ", ".join(recipients)
            message["Subject"] = subject

            message.attach(MIMEText(body, "plain"))

            attachment = MIMEBase("application", "octet-stream")
            attachment.set_payload(attachment_bytes)
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition", f'attachment; filename="{attachment_filename}"'
            )
            message.attach(attachment)

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

    def send_location_preference_notification(self, staff_name, day_locations, night_locations, zip_code, reduced_rest_ok, n_to_d_flex):
        """
        Send email notification when a staff member changes their shift location preferences

        Args:
            staff_name (str): Name of staff member who updated preferences
            day_locations (dict): Day location preferences {location: rank}
            night_locations (dict): Night location preferences {location: rank}
            zip_code (str): Staff member's zip code
            reduced_rest_ok (bool): Reduced rest preference
            n_to_d_flex (str): N to D flex preference (Yes/No/Maybe)

        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email notifications not configured")

        try:
            timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")

            subject = f"Boston MedFlight - Location Preferences Updated: {staff_name}"

            # Build day location summary sorted by rank
            day_summary_lines = []
            for location, rank in sorted(day_locations.items(), key=lambda x: x[1] if x[1] else 999):
                if rank:
                    day_summary_lines.append(f"    Choice {rank}: {location}")

            # Build night location summary sorted by rank
            night_summary_lines = []
            for location, rank in sorted(night_locations.items(), key=lambda x: x[1] if x[1] else 999):
                if rank:
                    night_summary_lines.append(f"    Choice {rank}: {location}")

            reduced_rest_str = "Yes" if reduced_rest_ok else "No"

            body = f"""
Boston MedFlight - Shift Location Preference Update

Staff Member: {staff_name}
Timestamp: {timestamp}

Day Shift Location Preferences:
{chr(10).join(day_summary_lines)}

Night Shift Location Preferences:
{chr(10).join(night_summary_lines)}

Additional Information:
    Zip Code: {zip_code}
    Reduced Rest OK: {reduced_rest_str}
    N to D Flex: {n_to_d_flex}

This notification was automatically generated by the Boston MedFlight CrewOps360 system.
            """

            # Send to all notification recipients
            recipients = []
            if self.admin_email:
                recipients.append(self.admin_email)
            if self.notification_recipients:
                for email in self.notification_recipients:
                    if email not in recipients:
                        recipients.append(email)

            if not recipients:
                return (False, "No email recipients configured")

            success = self.send_email(recipients, subject, body)

            if success:
                return (True, "Location preference notification sent successfully.")
            else:
                return (False, "Failed to send location preference notification")

        except Exception as e:
            return (False, f"Error sending location preference notification: {str(e)}")

    def create_bid_notification_content(self, staff_name, track_name, track_data, version, submission_date, validation_result=None):
        """
        Create email subject/body for the admin track-bid submission notification

        Args:
            staff_name (str): Name of staff member who submitted the bid
            track_name (str): Bid track/cycle name (e.g. "FY27")
            track_data (dict): Bid track data that was submitted
            version (int): Bid version number
            submission_date (str): Timestamp string as stored in the database
            validation_result (dict, optional): Result of validate_track_comprehensive()

        Returns:
            tuple: (subject, body)
        """
        subject = f"Boston MedFlight - New Track Bid Submitted: {staff_name} ({track_name})"

        total_shifts = sum(1 for assignment in track_data.values() if assignment in ["D", "N", "AT"])
        day_shifts = sum(1 for assignment in track_data.values() if assignment == "D")
        night_shifts = sum(1 for assignment in track_data.values() if assignment == "N")
        at_shifts = sum(1 for assignment in track_data.values() if assignment == "AT")

        weekend_shifts = 0
        for day, assignment in track_data.items():
            if not assignment or assignment not in ["D", "N", "AT"]:
                continue
            day_parts = day.split()
            if len(day_parts) > 0:
                day_name = day_parts[0]
                if day_name == "Fri" and assignment == "N":
                    weekend_shifts += 1
                elif day_name in ["Sat", "Sun"] and assignment in ["D", "N", "AT"]:
                    weekend_shifts += 1

        if validation_result is not None:
            n_issues = sum(1 for v in validation_result.values() if isinstance(v, dict) and not v.get('status', True))
            status_line = "All requirements met" if validation_result.get('overall_valid', True) else f"{n_issues} requirement(s) NOT met"
        else:
            status_line = "Not evaluated"

        body = f"""
Boston MedFlight Track Bid Submission Notification

Staff Member: {staff_name}
Bid Track: {track_name}
Bid Version: {version}
Submitted: {submission_date}
Requirements Status: {status_line}

Bid Summary:
- Total Shifts: {total_shifts}
- Day Shifts: {day_shifts}
- Night Shifts: {night_shifts}
- AT/Preassignments: {at_shifts}
- Weekend Shifts: {weekend_shifts} (includes Friday nights, Saturdays, and Sundays)

This notification was automatically generated by the Boston MedFlight CrewOps360 system.

To review bids, please access the Track Bidding admin interface.
        """

        return subject, body

    def send_bid_submission_notification(self, staff_name, track_name, track_data, version, submission_date, validation_result=None):
        """
        Send an admin notification email with summary statistics when a track bid is submitted

        Args:
            staff_name (str): Name of staff member who submitted the bid
            track_name (str): Bid track/cycle name
            track_data (dict): Bid track data that was submitted
            version (int): Bid version number
            submission_date (str): Timestamp string as stored in the database
            validation_result (dict, optional): Result of validate_track_comprehensive()

        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email notifications not configured")

        try:
            subject, body = self.create_bid_notification_content(
                staff_name, track_name, track_data, version, submission_date, validation_result
            )

            recipients = []
            if self.admin_email:
                recipients.append(self.admin_email)
            if self.notification_recipients:
                for email in self.notification_recipients:
                    if email not in recipients:
                        recipients.append(email)

            if not recipients:
                return (False, "No email recipients configured")

            success = self.send_email(recipients, subject, body)

            if success:
                return (True, "Bid submission notification sent successfully.")
            else:
                return (False, "Failed to send bid submission notification")

        except Exception as e:
            return (False, f"Error sending bid submission notification: {str(e)}")

    def send_bid_summary_email(self, recipient_email, staff_name, track_name, pdf_bytes, filename):
        """
        Email a staff member their own bid summary PDF, sent from the admin account

        Args:
            recipient_email (str): Address the staff member entered to receive the PDF
            staff_name (str): Name of the staff member
            track_name (str): Bid track/cycle name
            pdf_bytes (bytes): The generated bid summary PDF
            filename (str): Filename to attach the PDF as

        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email notifications not configured")

        recipient_email = (recipient_email or "").strip()
        if not recipient_email or not _EMAIL_RE.match(recipient_email):
            return (False, "Please enter a valid email address")

        try:
            timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
            subject = f"Boston MedFlight - Your Track Bid Summary: {track_name}"
            body = f"""
Boston MedFlight Track Bid Summary

Attached is a summary of the track bid submitted for {staff_name} in {track_name}.

Sent: {timestamp}

This email was sent at your request from the Boston MedFlight CrewOps360 system.
            """

            success = self.send_email_with_attachment([recipient_email], subject, body, pdf_bytes, filename)

            if success:
                return (True, f"Bid summary emailed to {recipient_email}")
            else:
                return (False, "Failed to send bid summary email")

        except Exception as e:
            return (False, f"Error sending bid summary email: {str(e)}")

    def create_bid_access_opened_content(self, staff_name, track_name, requirements=None):
        """
        Create email subject/body telling a staff member their bid access just opened
        because the next-more-senior staff member in their role submitted a bid.

        Args:
            staff_name (str): Name of the staff member whose access just opened
            track_name (str): Bid track/cycle name
            requirements (dict, optional): shifts_per_pay_period/night_minimum/weekend_minimum

        Returns:
            tuple: (subject, body)
        """
        timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        subject = f"Boston MedFlight - Your Track Bid is Now Open: {track_name}"

        requirements = requirements or {}
        shifts = requirements.get('shifts_per_pay_period')
        night_min = requirements.get('night_minimum')
        weekend_min = requirements.get('weekend_minimum')

        body = f"""
Boston MedFlight Track Bidding - Your Bid Access is Now Open

Staff Member: {staff_name}
Bid Track: {track_name}
Opened: {timestamp}

You're next in seniority rank order - the staff member ahead of you has submitted
their bid, and your bid access for {track_name} has now been enabled.

Your Requirements:
- Shifts per Pay Period: {shifts if shifts is not None else 'N/A'}
- Night Minimum: {night_min if night_min is not None else 'N/A'}
- Weekend Minimum: {weekend_min if weekend_min is not None else 'N/A'}

Please log in to https://dashboard.crewops360.com/ and navigate to Track Bidding to submit your selections.  Detailed instructions are found linked at the top in the Track Bidding module. 

This notification was automatically generated by the Boston MedFlight CrewOps360 system.
        """

        return subject, body

    def send_bid_access_opened_notification(self, staff_name, staff_email, track_name, requirements=None):
        """
        Email a staff member (plus the admin recipients) that their bid access just
        opened, sent from the same admin account as other bid notifications.

        Args:
            staff_name (str): Name of the staff member whose access just opened
            staff_email (str): Staff member's email address, from Requirements.xlsx
            track_name (str): Bid track/cycle name
            requirements (dict, optional): shifts_per_pay_period/night_minimum/weekend_minimum

        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email notifications not configured")

        staff_email = (staff_email or "").strip()
        if not staff_email or not _EMAIL_RE.match(staff_email):
            return (False, "Invalid or missing staff email address")

        try:
            subject, body = self.create_bid_access_opened_content(staff_name, track_name, requirements)

            recipients = [staff_email]
            if self.admin_email and self.admin_email not in recipients:
                recipients.append(self.admin_email)
            if self.notification_recipients:
                for email in self.notification_recipients:
                    if email not in recipients:
                        recipients.append(email)

            success = self.send_email(recipients, subject, body)

            if success:
                return (True, f"Bid-open notification sent to {staff_name} ({staff_email}) and admins.")
            else:
                return (False, "Failed to send bid-open notification")

        except Exception as e:
            return (False, f"Error sending bid-open notification: {str(e)}")

    def send_missing_bidder_email_alert(self, staff_name, track_name):
        """
        Alert the admin recipients that a staff member is next in rank for bid access
        but has no email on file, so they could not be auto-notified and must be
        enabled and notified manually.

        Args:
            staff_name (str): Name of the staff member who is next in rank
            track_name (str): Bid track/cycle name

        Returns:
            tuple: (success, message)
        """
        if not self.configured:
            return (False, "Email notifications not configured")

        try:
            timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
            subject = f"Boston MedFlight - Action Needed: Enable & Notify {staff_name} Manually ({track_name})"
            body = f"""
Boston MedFlight Track Bidding - Manual Action Needed

Staff Member: {staff_name}
Bid Track: {track_name}
Timestamp: {timestamp}

{staff_name} is next in seniority rank order for bid access, but no email address is
on file for them in Requirements.xlsx, so they could not be automatically notified.

Bid access was NOT automatically enabled. Please enable bid access for {staff_name}
and notify them manually, and consider adding their email address to
Requirements.xlsx for future cycles.

This notification was automatically generated by the Boston MedFlight CrewOps360 system.
            """

            recipients = []
            if self.admin_email:
                recipients.append(self.admin_email)
            if self.notification_recipients:
                for email in self.notification_recipients:
                    if email not in recipients:
                        recipients.append(email)

            if not recipients:
                return (False, "No email recipients configured")

            success = self.send_email(recipients, subject, body)

            if success:
                return (True, "Admins alerted to enable/notify manually.")
            else:
                return (False, "Failed to send admin alert email")

        except Exception as e:
            return (False, f"Error sending admin alert email: {str(e)}")

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

Timestamp: {datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")}
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

def send_location_preference_notification(staff_name, day_locations, night_locations, zip_code, reduced_rest_ok, n_to_d_flex):
    """
    Convenient function to send location preference update notification

    Args:
        staff_name (str): Name of staff member who updated preferences
        day_locations (dict): Day location preferences {location: rank}
        night_locations (dict): Night location preferences {location: rank}
        zip_code (str): Staff member's zip code
        reduced_rest_ok (bool): Reduced rest preference
        n_to_d_flex (str): N to D flex preference (Yes/No/Maybe)

    Returns:
        tuple: (success, message)
    """
    return email_notifier.send_location_preference_notification(
        staff_name, day_locations, night_locations, zip_code, reduced_rest_ok, n_to_d_flex
    )

def send_bid_submission_notification(staff_name, track_name, track_data, version, submission_date, validation_result=None):
    """
    Convenient function to send the admin track-bid submission notification

    Args:
        staff_name (str): Name of staff member who submitted the bid
        track_name (str): Bid track/cycle name
        track_data (dict): Bid track data that was submitted
        version (int): Bid version number
        submission_date (str): Timestamp string as stored in the database
        validation_result (dict, optional): Result of validate_track_comprehensive()

    Returns:
        tuple: (success, message)
    """
    return email_notifier.send_bid_submission_notification(
        staff_name, track_name, track_data, version, submission_date, validation_result
    )

def send_bid_summary_email(recipient_email, staff_name, track_name, pdf_bytes, filename):
    """
    Convenient function to email a staff member their own bid summary PDF

    Args:
        recipient_email (str): Address the staff member entered to receive the PDF
        staff_name (str): Name of the staff member
        track_name (str): Bid track/cycle name
        pdf_bytes (bytes): The generated bid summary PDF
        filename (str): Filename to attach the PDF as

    Returns:
        tuple: (success, message)
    """
    return email_notifier.send_bid_summary_email(recipient_email, staff_name, track_name, pdf_bytes, filename)

def send_bid_access_opened_notification(staff_name, staff_email, track_name, requirements=None):
    """
    Convenient function to notify a staff member (plus admins) that their bid access
    just opened because the next-more-senior staff member in their role submitted a bid.

    Args:
        staff_name (str): Name of the staff member whose access just opened
        staff_email (str): Staff member's email address, from Requirements.xlsx
        track_name (str): Bid track/cycle name
        requirements (dict, optional): shifts_per_pay_period/night_minimum/weekend_minimum

    Returns:
        tuple: (success, message)
    """
    return email_notifier.send_bid_access_opened_notification(staff_name, staff_email, track_name, requirements)

def send_missing_bidder_email_alert(staff_name, track_name):
    """
    Convenient function to alert admins that a staff member next in bid rank order has
    no email on file and must be enabled/notified manually.

    Args:
        staff_name (str): Name of the staff member who is next in rank
        track_name (str): Bid track/cycle name

    Returns:
        tuple: (success, message)
    """
    return email_notifier.send_missing_bidder_email_alert(staff_name, track_name)
