# modules/admin_pdf_generator.py
"""
Admin Edit PDF Generator
Generates PDFs for admin track edits with:
1. Changes summary page (narrative format)
2. Full schedule with the updated assignments
"""

import os
from fpdf import FPDF
from datetime import datetime
import pytz

_eastern_tz = pytz.timezone('America/New_York')
from modules.pdf_generator import (
    sanitize_text_for_pdf, 
    count_shifts_comprehensive,
    SchedulePDF
)

# Define the 42 day columns (6 weeks)
DAY_COLUMNS = [
    "Sun A 1", "Mon A 1", "Tue A 1", "Wed A 1", "Thu A 1", "Fri A 1", "Sat A 1",
    "Sun A 2", "Mon A 2", "Tue A 2", "Wed A 2", "Thu A 2", "Fri A 2", "Sat A 2",
    "Sun B 3", "Mon B 3", "Tue B 3", "Wed B 3", "Thu B 3", "Fri B 3", "Sat B 3",
    "Sun B 4", "Mon B 4", "Tue B 4", "Wed B 4", "Thu B 4", "Fri B 4", "Sat B 4",
    "Sun C 5", "Mon C 5", "Tue C 5", "Wed C 5", "Thu C 5", "Fri C 5", "Sat C 5",
    "Sun C 6", "Mon C 6", "Tue C 6", "Wed C 6", "Thu C 6", "Fri C 6", "Sat C 6"
]

class AdminEditPDF(SchedulePDF):
    """Custom PDF class for admin edit documentation"""
    
    def __init__(self):
        super().__init__()
        self.admin_edit_mode = True
    
    def header(self):
        """Create header for all pages"""
        # Logo (if available)
        if os.path.exists('assets/logo.png'):
            self.image('assets/logo.png', 10, 8, 30)
        
        # Set font for header
        self.set_font('Arial', 'B', 15)
        
        # Add title with ADMIN EDIT marker
        self.cell(0, 10, 'Boston MedFlight Schedule - ADMIN EDIT', 0, 1, 'C')
        
        # Add date
        self.set_font('Arial', '', 10)
        current_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        self.cell(0, 10, f'Generated: {current_date}', 0, 1, 'R')
        
        # Add line
        self.line(10, 30, 200, 30)
        self.ln(5)

def create_narrative_summary(changes):
    """
    Create a narrative summary of changes
    
    Args:
        changes (list): List of change dictionaries with 'day', 'original', 'new' keys
        
    Returns:
        str: Narrative summary of changes
    """
    if not changes:
        return "No changes were made to the schedule."
    
    # Group changes by type
    to_day = []
    to_night = []
    to_at = []
    to_off = []
    
    for change in changes:
        day = change['day']
        original = change['original']
        new_val = change['new']
        
        if new_val == 'D':
            to_day.append(f"{day} (was {original})")
        elif new_val == 'N':
            to_night.append(f"{day} (was {original})")
        elif new_val == 'AT':
            to_at.append(f"{day} (was {original})")
        else:  # Off
            to_off.append(f"{day} (was {original})")
    
    # Build narrative
    summary_parts = []
    
    if to_day:
        summary_parts.append(f"Changed to Day shifts: {', '.join(to_day)}")
    
    if to_night:
        summary_parts.append(f"Changed to Night shifts: {', '.join(to_night)}")
    
    if to_at:
        summary_parts.append(f"Changed to AT: {', '.join(to_at)}")
    
    if to_off:
        summary_parts.append(f"Changed to Off: {', '.join(to_off)}")
    
    return ". ".join(summary_parts) + "."

def add_changes_summary_page(pdf, staff_name, version, changes, admin_user, timestamp):
    """
    Add the changes summary page to the PDF
    
    Args:
        pdf: PDF object
        staff_name (str): Name of staff member
        version (int): Version number
        changes (list): List of changes
        admin_user (str): Admin who made the changes
        timestamp (str): Timestamp of the edit
    """
    pdf.add_page()
    
    # Title
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, 'ADMIN TRACK EDIT SUMMARY', 0, 1, 'C')
    pdf.ln(5)
    
    # Staff and Version Info
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, f'Staff Member: {sanitize_text_for_pdf(staff_name)}', 0, 1)
    pdf.cell(0, 8, f'New Version: {version}', 0, 1)
    pdf.cell(0, 8, f'Edit Date: {timestamp}', 0, 1)
    pdf.ln(5)
    
    # Number of changes
    pdf.set_font('Arial', '', 11)
    pdf.set_fill_color(255, 243, 205)  # Light yellow background
    pdf.cell(0, 10, f'Total Changes Made: {len(changes)} days modified', 1, 1, 'L', 1)
    pdf.ln(5)
    
    # Narrative Summary Section
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, 'Changes Summary:', 0, 1)
    
    pdf.set_font('Arial', '', 10)
    narrative = create_narrative_summary(changes)
    
    # Use multi_cell for word wrapping
    pdf.multi_cell(0, 6, sanitize_text_for_pdf(narrative))
    pdf.ln(5)
    
    # Detailed Changes Table
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, 'Detailed Changes:', 0, 1)
    pdf.ln(2)
    
    # Table header
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(10, 7, '#', 1, 0, 'C', 1)
    pdf.cell(70, 7, 'Day', 1, 0, 'L', 1)
    pdf.cell(50, 7, 'Original', 1, 0, 'C', 1)
    pdf.cell(50, 7, 'Changed To', 1, 1, 'C', 1)
    
    # Table rows
    pdf.set_font('Arial', '', 9)
    for idx, change in enumerate(changes, 1):
        # Alternate row colors
        if idx % 2 == 0:
            pdf.set_fill_color(245, 245, 245)
        else:
            pdf.set_fill_color(255, 255, 255)
        
        pdf.cell(10, 6, str(idx), 1, 0, 'C', 1)
        pdf.cell(70, 6, sanitize_text_for_pdf(change['day']), 1, 0, 'L', 1)
        pdf.cell(50, 6, sanitize_text_for_pdf(change['original']), 1, 0, 'C', 1)
        
        # Color code the new value
        new_val = change['new']
        if new_val == 'D':
            pdf.set_fill_color(212, 237, 218)  # Light green
        elif new_val == 'N':
            pdf.set_fill_color(204, 229, 255)  # Light blue
        elif new_val == 'AT':
            pdf.set_fill_color(255, 243, 205)  # Light yellow
        else:  # Off
            pdf.set_fill_color(255, 255, 255)  # White
        
        pdf.cell(50, 6, sanitize_text_for_pdf(new_val), 1, 1, 'C', 1)
    
    pdf.ln(10)
    
    # Admin Attribution
    pdf.set_font('Arial', 'I', 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.multi_cell(0, 6, f'This track was edited by an administrator. Original track requirements '
                   f'and validations may not apply to admin-edited schedules.', 0, 'L', 1)

def add_full_schedule_pages(pdf, staff_name, track_data, preassignments=None):
    """
    Add the full schedule pages to the PDF
    
    Args:
        pdf: PDF object
        staff_name (str): Name of staff member
        track_data (dict): Dictionary of day -> assignment
        preassignments (dict, optional): Dictionary of day -> preassignment value
    """
    pdf.add_page()
    
    # Page title
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'UPDATED SCHEDULE', 0, 1, 'C')
    pdf.ln(5)
    
    # Staff info
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, f'Staff Member: {sanitize_text_for_pdf(staff_name)}', 0, 1)
    pdf.ln(2)
    
    # Calculate shift counts
    total_shifts, day_shifts, night_shifts, at_shifts = count_shifts_comprehensive(track_data, preassignments)
    
    # Shift summary
    pdf.set_font('Arial', '', 10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(40, 7, 'Shift Type', 1, 0, 'L', 1)
    pdf.cell(40, 7, 'Count', 1, 1, 'C', 1)
    
    pdf.cell(40, 7, 'Total Shifts', 1, 0, 'L')
    pdf.cell(40, 7, f'{total_shifts}', 1, 1, 'C')
    
    pdf.cell(40, 7, 'Day Shifts', 1, 0, 'L')
    pdf.cell(40, 7, f'{day_shifts}', 1, 1, 'C')
    
    pdf.cell(40, 7, 'Night Shifts', 1, 0, 'L')
    pdf.cell(40, 7, f'{night_shifts}', 1, 1, 'C')
    
    if at_shifts > 0:
        pdf.cell(40, 7, 'AT Preassignments', 1, 0, 'L')
        pdf.cell(40, 7, f'{at_shifts}', 1, 1, 'C')
    
    pdf.ln(5)
    
    # Schedule by block
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 10, 'Schedule by Block - Starting Sun 9/14/25', 0, 1)
    
    # Define blocks
    blocks = ["A", "B", "C"]
    days_list = DAY_COLUMNS
    
    # Process each block
    for block_idx, block in enumerate(blocks):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 7, f'Block {block}', 0, 1)
        
        # Calculate days for this block (2 weeks = 14 days)
        start_idx = block_idx * 14
        end_idx = start_idx + 14
        block_days = days_list[start_idx:end_idx] if start_idx < len(days_list) else []
        
        if not block_days:
            continue
        
        # Create day headers
        day_headers = []
        for i in range(14):
            day_num = i % 7
            week_num = (block_idx * 2) + (i // 7) + 1
            day_name = ""
            if day_num == 0:
                day_name = "Sun"
            elif day_num == 1:
                day_name = "Mon"
            elif day_num == 2:
                day_name = "Tue"
            elif day_num == 3:
                day_name = "Wed"
            elif day_num == 4:
                day_name = "Thu"
            elif day_num == 5:
                day_name = "Fri"
            elif day_num == 6:
                day_name = "Sat"
            day_headers.append(f"{day_name} {block} {week_num}")
        
        # Split into two weeks for better fit on page
        for week_idx in range(2):
            if week_idx * 7 >= len(day_headers):
                continue
                
            week_start = week_idx * 7
            week_end = min(week_start + 7, len(day_headers))
            
            week_headers = day_headers[week_start:week_end]
            week_days = block_days[week_start:week_end]
            
            if not week_days:
                continue
                
            absolute_week = (block_idx * 2) + week_idx + 1
            
            # Add week header
            pdf.set_font('Arial', 'I', 9)
            pdf.cell(0, 7, f'Week {absolute_week}', 0, 1)
            
            # Table header with day headers
            pdf.set_font('Arial', '', 9)
            pdf.set_fill_color(220, 220, 220)
            
            cell_width = 170 / len(week_headers)
            pdf.cell(20, 7, 'Date', 1, 0, 'C', 1)
            for header in week_headers:
                pdf.cell(cell_width, 7, header.split()[0], 1, 0, 'C', 1)
            pdf.ln()
            
            # Shift row
            pdf.cell(20, 7, 'Shift', 1, 0, 'C', 1)
            for day in week_days:
                shift = ""
                if day in track_data and track_data[day]:
                    shift = track_data[day]
                elif preassignments and day in preassignments and preassignments[day]:
                    shift = preassignments[day]
                
                if shift == "D":
                    pdf.set_fill_color(212, 237, 218)  # Light green
                    pdf.cell(cell_width, 7, 'D', 1, 0, 'C', 1)
                elif shift == "N":
                    pdf.set_fill_color(204, 229, 255)  # Light blue
                    pdf.cell(cell_width, 7, 'N', 1, 0, 'C', 1)
                elif shift == "AT":
                    pdf.set_fill_color(255, 243, 205)  # Light yellow
                    pdf.cell(cell_width, 7, 'AT', 1, 0, 'C', 1)
                else:
                    pdf.cell(cell_width, 7, 'Off', 1, 0, 'C')
            
            pdf.ln(10)

def generate_admin_edit_pdf(staff_name, track_data, changes, version, admin_user, preassignments=None):
    """
    Generate a PDF for an admin edit with changes summary and full schedule
    
    Args:
        staff_name (str): Name of staff member
        track_data (dict): Dictionary of day -> assignment (the UPDATED track data)
        changes (list): List of change dictionaries with 'day', 'original', 'new' keys
        version (int): New version number
        admin_user (str): Username of admin who made the edit
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        tuple: (pdf_bytes, filename)
    """
    # Create PDF
    pdf = AdminEditPDF()
    pdf.alias_nb_pages()
    
    # Get timestamp
    timestamp = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
    
    # Add changes summary page
    add_changes_summary_page(pdf, staff_name, version, changes, admin_user, timestamp)
    
    # Add full schedule pages
    add_full_schedule_pages(pdf, staff_name, track_data, preassignments)
    
    # Generate PDF bytes
    try:
        pdf_bytes = pdf.output(dest='S')
        
        if isinstance(pdf_bytes, bytearray):
            pdf_bytes = bytes(pdf_bytes)
            
        if isinstance(pdf_bytes, str):
            pdf_bytes = pdf_bytes.encode('latin-1')
            
    except Exception as e:
        try:
            pdf_output = pdf.output()
            if isinstance(pdf_output, str):
                pdf_bytes = pdf_output.encode('latin-1')
            elif isinstance(pdf_output, bytearray):
                pdf_bytes = bytes(pdf_output)
            else:
                pdf_bytes = pdf_output
        except Exception as e2:
            raise Exception(f"Error generating PDF: {e}, {e2}")
    
    # Create filename - lastname_version_admin_edit_timestamp.pdf
    # Extract last name (assumes "FirstName LastName" format)
    name_parts = staff_name.split()
    if len(name_parts) > 1:
        last_name = name_parts[-1]
    else:
        last_name = staff_name
    
    safe_lastname = ''.join(c if c.isalnum() else '_' for c in last_name)
    timestamp_short = datetime.now(_eastern_tz).strftime('%Y%m%d%H%M%S')
    filename = f"{safe_lastname}_v{version}_admin_edit_{timestamp_short}.pdf"
    
    return pdf_bytes, filename
