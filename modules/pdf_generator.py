# modules/pdf_generator.py
"""
FIXED: PDF generator with proper Unicode character handling
Updated to handle checkmarks and other Unicode characters properly
"""

import os
from fpdf import FPDF  # fpdf2 package uses 'fpdf' as the module name
import pandas as pd
from datetime import datetime
import pytz

_eastern_tz = pytz.timezone('America/New_York')

class SchedulePDF(FPDF):
    """Custom PDF class for schedule generation"""
    
    def header(self):
        """Create header for all pages"""
        # Logo (if available)
        if os.path.exists('assets/logo.png'):
            self.image('assets/logo.png', 10, 8, 30)
        
        # Set font for header
        self.set_font('Arial', 'B', 15)
        
        # Add title
        self.cell(0, 10, 'Boston MedFlight Schedule', 0, 1, 'C')
        
        # Add date
        self.set_font('Arial', '', 10)
        current_date = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S")
        self.cell(0, 10, f'Generated: {current_date}', 0, 1, 'R')
        
        # Add line
        self.line(10, 30, 200, 30)
        self.ln(5)
    
    def footer(self):
        """Create footer for all pages"""
        # Set position at 1.5 cm from bottom
        self.set_y(-15)
        
        # Set font
        self.set_font('Arial', 'I', 8)
        
        # Add page number
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')

def sanitize_text_for_pdf(text):
    """
    FIXED: Sanitize text to remove Unicode characters that can't be encoded in latin-1
    Replace problematic characters with safe alternatives
    """
    if not isinstance(text, str):
        text = str(text)
    
    # Dictionary of Unicode characters to replace
    unicode_replacements = {
        '\u2705': '[OK]',     # ✅ -> [OK]
        '\u274c': '[X]',      # ❌ -> [X]
        '\u2713': '[v]',      # ✓ -> [v]
        '\u2717': '[x]',      # ✗ -> [x]
        '\u2714': '[V]',      # ✔ -> [V]
        '\u2716': '[X]',      # ✖ -> [X]
        '\u2611': '[+]',      # ☑ -> [+]
        '\u2610': '[ ]',      # ☐ -> [ ]
        '\u2612': '[x]',      # ☒ -> [x]
        '\u2019': "'",        # ' -> '
        '\u2018': "'",        # ' -> '
        '\u201c': '"',        # " -> "
        '\u201d': '"',        # " -> "
        '\u2013': '-',        # – -> -
        '\u2014': '--',       # — -> --
        '\u2026': '...',      # … -> ...
        '\u00a0': ' ',        # Non-breaking space -> regular space
    }
    
    # Replace Unicode characters
    for unicode_char, replacement in unicode_replacements.items():
        text = text.replace(unicode_char, replacement)
    
    # Encode to latin-1 with error handling
    try:
        # Test if the text can be encoded to latin-1
        text.encode('latin-1')
        return text
    except UnicodeEncodeError:
        # If it still can't be encoded, replace problematic characters with '?'
        return text.encode('latin-1', 'replace').decode('latin-1')

def count_shifts_comprehensive(track_data, preassignments=None):
    """
    FIXED: Comprehensive shift counting including all AT assignments
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        tuple: (total_shifts, day_shifts, night_shifts, at_shifts)
    """
    total_shifts = 0
    day_shifts = 0
    night_shifts = 0
    at_shifts = 0
    
    # Get all possible days from both sources
    all_days = set()
    if track_data:
        all_days.update(track_data.keys())
    if preassignments:
        all_days.update(preassignments.keys())
    
    # Count shifts for each day, prioritizing track_data over preassignments
    for day in all_days:
        assignment = None
        
        # Check track_data first
        if day in track_data and track_data[day]:
            assignment = track_data[day]
        elif preassignments and day in preassignments and preassignments[day]:
            assignment = preassignments[day]
        
        # Count based on assignment
        if assignment == "D":
            day_shifts += 1
            total_shifts += 1
        elif assignment == "N":
            night_shifts += 1
            total_shifts += 1
        elif assignment == "AT":
            at_shifts += 1
            total_shifts += 1
    
    return total_shifts, day_shifts, night_shifts, at_shifts

def count_weekend_shifts_comprehensive(track_data, preassignments=None):
    """
    FIXED: Count weekend shifts including all AT assignments
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        int: Number of weekend shifts
    """
    weekend_count = 0
    
    # Get all possible days from both sources
    all_days = set()
    if track_data:
        all_days.update(track_data.keys())
    if preassignments:
        all_days.update(preassignments.keys())
    
    # Count weekend shifts for each day
    for day in all_days:
        assignment = None
        
        # Check track_data first, then preassignments
        if day in track_data and track_data[day]:
            assignment = track_data[day]
        elif preassignments and day in preassignments and preassignments[day]:
            assignment = preassignments[day]
        
        if not assignment:
            continue
            
        # Extract day name from the date string (e.g., "Fri 05/24")
        day_parts = day.split()
        if len(day_parts) > 0:
            day_name = day_parts[0]
            
            # Count Friday night shifts
            if day_name == "Fri" and assignment == "N":
                weekend_count += 1
            
            # Count all Saturday and Sunday shifts (D, N, or AT)
            elif day_name in ["Sat", "Sun"] and assignment in ["D", "N", "AT"]:
                weekend_count += 1
    
    return weekend_count

def count_shifts_by_pay_period_comprehensive(track_data, days_list, preassignments=None):
    """
    FIXED: Count shifts by pay period including AT assignments
    
    Args:
        track_data (dict): Dictionary of day -> assignment
        days_list (list): Ordered list of days
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        list: Number of shifts in each pay period (14-day blocks)
    """
    shifts_by_pay_period = []
    
    # Process in 14-day blocks (pay periods)
    for i in range(0, len(days_list), 14):
        pay_period_days = days_list[i:i+14] if i+14 <= len(days_list) else days_list[i:]
        
        pay_period_count = 0
        for day in pay_period_days:
            assignment = None
            
            # Check track_data first, then preassignments
            if day in track_data and track_data[day]:
                assignment = track_data[day]
            elif preassignments and day in preassignments and preassignments[day]:
                assignment = preassignments[day]
            
            # Count all shift types (D, N, AT)
            if assignment in ["D", "N", "AT"]:
                pay_period_count += 1
        
        shifts_by_pay_period.append(pay_period_count)
    
    return shifts_by_pay_period

def generate_schedule_pdf(staff_name, track_data, days, shifts_per_pay_period=0, night_minimum=0, weekend_minimum=0, preassignments=None):
    """
    Generate a PDF with the staff schedule
    FIXED: Proper AT handling and Unicode character support
    
    Args:
        staff_name (str): Name of the staff member
        track_data (dict): Dictionary of day -> assignment
        days (list): List of days in the schedule
        shifts_per_pay_period (int): Required shifts per pay period (14-day block)
        night_minimum (int): Minimum night shifts required
        weekend_minimum (int): Minimum weekend shifts required
        preassignments (dict, optional): Dictionary of day -> preassignment value
        
    Returns:
        tuple: (pdf_bytes, filename)
    """
    # Create PDF instance
    pdf = SchedulePDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # Set font
    pdf.set_font('Arial', 'B', 12)
    
    # Staff name - FIXED: Sanitize for PDF
    pdf.cell(0, 10, sanitize_text_for_pdf(f'Schedule for: {staff_name}'), 0, 1)
    pdf.ln(5)
    
    # Add summary statistics
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 10, 'Schedule Summary', 0, 1)
    
    # FIXED: Calculate statistics with comprehensive AT support
    total_shifts, day_shifts, night_shifts, at_shifts = count_shifts_comprehensive(track_data, preassignments)
    weekend_shifts = count_weekend_shifts_comprehensive(track_data, preassignments)
    
    # Fix: Make sure days is a list, not a pandas Index
    if isinstance(days, pd.Index):
        days_list = days.tolist()
    else:
        days_list = list(days)
    
    # FIXED: Calculate expected total shifts (pay period requirement x 3 pay periods)
    expected_total_shifts = shifts_per_pay_period * 3 if shifts_per_pay_period > 0 else 0
    
    # Create summary table
    pdf.set_font('Arial', '', 10)
    
    # Table header
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(40, 7, 'Metric', 1, 0, 'L', 1)
    pdf.cell(40, 7, 'Value', 1, 0, 'C', 1)
    pdf.cell(40, 7, 'Requirement', 1, 0, 'C', 1)
    pdf.cell(40, 7, 'Status', 1, 1, 'C', 1)
    
    # FIXED: Total shifts with proper validation and sanitized status text
    total_status = "Met" if expected_total_shifts == 0 or total_shifts == expected_total_shifts else "Not Met"
    pdf.cell(40, 7, 'Total Shifts', 1, 0, 'L')
    pdf.cell(40, 7, f'{total_shifts}', 1, 0, 'C')
    pdf.cell(40, 7, f'{expected_total_shifts}' if expected_total_shifts > 0 else 'N/A', 1, 0, 'C')
    pdf.cell(40, 7, sanitize_text_for_pdf(total_status), 1, 1, 'C')
    
    # Day shifts
    pdf.cell(40, 7, 'Day Shifts', 1, 0, 'L')
    pdf.cell(40, 7, f'{day_shifts}', 1, 0, 'C')
    pdf.cell(40, 7, 'N/A', 1, 0, 'C')
    pdf.cell(40, 7, 'N/A', 1, 1, 'C')
    
    # Night shifts
    night_status = "Met" if night_shifts >= night_minimum else "Not Met"
    pdf.cell(40, 7, 'Night Shifts', 1, 0, 'L')
    pdf.cell(40, 7, f'{night_shifts}', 1, 0, 'C')
    pdf.cell(40, 7, f'{night_minimum} minimum', 1, 0, 'C')
    pdf.cell(40, 7, sanitize_text_for_pdf(night_status), 1, 1, 'C')
    
    # Weekend shifts
    weekend_status = "Met" if weekend_shifts >= weekend_minimum else "Not Met"
    pdf.cell(40, 7, 'Weekend Shifts', 1, 0, 'L')
    pdf.cell(40, 7, f'{weekend_shifts}', 1, 0, 'C')
    pdf.cell(40, 7, f'{weekend_minimum} minimum', 1, 0, 'C')
    pdf.cell(40, 7, sanitize_text_for_pdf(weekend_status), 1, 1, 'C')
    
    # AT Preassignments (only show if there are any)
    if at_shifts > 0:
        pdf.cell(40, 7, 'AT Preassignments', 1, 0, 'L')
        pdf.cell(40, 7, f'{at_shifts}', 1, 0, 'C')
        pdf.cell(40, 7, 'N/A', 1, 0, 'C')
        pdf.cell(40, 7, 'N/A', 1, 1, 'C')
    
    pdf.ln(5)
    
    # FIXED: Pay Period Breakdown (including AT shifts)
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 10, 'Pay Period Breakdown', 0, 1)
    
    shifts_by_pay_period = count_shifts_by_pay_period_comprehensive(track_data, days_list, preassignments)
    
    # Pay period table header
    pdf.set_font('Arial', '', 10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(60, 7, 'Pay Period', 1, 0, 'L', 1)
    pdf.cell(30, 7, 'Shifts', 1, 0, 'C', 1)
    pdf.cell(30, 7, 'Required', 1, 0, 'C', 1)
    pdf.cell(30, 7, 'Status', 1, 1, 'C', 1)
    
    pay_periods = ["Pay Period 1 (Block A)", "Pay Period 2 (Block B)", "Pay Period 3 (Block C)"]
    
    for i, (pay_period_name, shift_count) in enumerate(zip(pay_periods, shifts_by_pay_period)):
        # FIXED: Sanitize status symbols for PDF
        status_text = "Met" if shifts_per_pay_period == 0 or shift_count == shifts_per_pay_period else "Not Met"
        
        pdf.cell(60, 7, pay_period_name, 1, 0, 'L')
        pdf.cell(30, 7, f'{shift_count}', 1, 0, 'C')
        pdf.cell(30, 7, f'{shifts_per_pay_period}' if shifts_per_pay_period > 0 else 'N/A', 1, 0, 'C')
        pdf.cell(30, 7, sanitize_text_for_pdf(status_text), 1, 1, 'C')
    
    pdf.ln(5)
    
    # Schedule by block
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 10, 'Schedule by Block - Starting Sun 9/14/25', 0, 1)
    
    # Define blocks
    blocks = ["A", "B", "C"]
    
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
            week_num = (block_idx * 2) + (i // 7) + 1  # Adjust week number based on block
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
            # Safety check to prevent index errors
            if week_idx * 7 >= len(day_headers):
                continue
                
            week_start = week_idx * 7
            week_end = min(week_start + 7, len(day_headers))
            
            # Get headers and days for this week
            week_headers = day_headers[week_start:week_end]
            week_days = block_days[week_start:week_end]
            
            # Make sure we have days for this week
            if not week_days:
                continue
                
            # Calculate the absolute week number (1-6)
            absolute_week = (block_idx * 2) + week_idx + 1
            
            # Add week header
            pdf.set_font('Arial', 'I', 9)
            pdf.cell(0, 7, f'Week {absolute_week}', 0, 1)
            
            # Table header with day headers
            pdf.set_font('Arial', '', 9)
            pdf.set_fill_color(220, 220, 220)
            
            # First row - day names
            cell_width = 170 / len(week_headers)
            pdf.cell(20, 7, 'Date', 1, 0, 'C', 1)
            for header in week_headers:
                pdf.cell(cell_width, 7, header.split()[0], 1, 0, 'C', 1)  # Just day name
            pdf.ln()
            
            # Second row - shifts
            pdf.cell(20, 7, 'Shift', 1, 0, 'C', 1)
            for day in week_days:
                # FIXED: Check track_data first, then preassignments
                shift = ""
                if day in track_data and track_data[day]:
                    shift = track_data[day]
                elif preassignments and day in preassignments and preassignments[day]:
                    shift = preassignments[day]
                
                # FIXED: Color cells based on shift type including AT
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
    
    # Generate PDF bytes with proper error handling
    try:
        # Get the PDF bytes
        pdf_bytes = pdf.output(dest='S')
        
        # Ensure we have bytes, not bytearray
        if isinstance(pdf_bytes, bytearray):
            pdf_bytes = bytes(pdf_bytes)
            
        # If we got a string, encode it
        if isinstance(pdf_bytes, str):
            pdf_bytes = pdf_bytes.encode('latin-1')
            
    except Exception as e:
        try:
            # Fallback for different fpdf2 versions
            pdf_output = pdf.output()
            if isinstance(pdf_output, str):
                pdf_bytes = pdf_output.encode('latin-1')
            elif isinstance(pdf_output, bytearray):
                pdf_bytes = bytes(pdf_output)
            else:
                pdf_bytes = pdf_output
        except Exception as e2:
            raise Exception(f"Error generating PDF: {e}, {e2}")
    
    # Create filename with sanitized staff name
    safe_name = ''.join(c if c.isalnum() else '_' for c in staff_name)
    filename = f"{safe_name}_schedule_{datetime.now(_eastern_tz).strftime('%Y%m%d%H%M%S')}.pdf"

    return pdf_bytes, filename


def fit_text_to_width(pdf, text, max_width):
    """
    Truncate text with an ellipsis so it fits max_width (mm) in the PDF's current font.
    Char-count budgets can't guarantee a fit since glyph widths vary (e.g. 'W' vs 'i').
    """
    text = sanitize_text_for_pdf(text)
    if pdf.get_string_width(text) <= max_width:
        return text
    while text and pdf.get_string_width(text + '...') > max_width:
        text = text[:-1]
    return (text + '...') if text else '...'


class BidSummaryPDF(FPDF):
    """Compact single-page PDF summarizing one submitted track bid."""

    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 8, 'Boston MedFlight - Track Bid Summary', 0, 1, 'C')
        self.set_font('Arial', '', 8)
        gen_ts = datetime.now(_eastern_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        self.cell(0, 5, sanitize_text_for_pdf(f'Generated: {gen_ts}'), 0, 1, 'C')
        self.line(10, 18, 200, 18)
        self.ln(3)

    def footer(self):
        self.set_y(-8)
        self.set_font('Arial', 'I', 6)
        self.cell(0, 5, 'Boston MedFlight - CrewOps360 (auto-generated)', 0, 0, 'C')

    def section_title(self, text):
        self.set_font('Arial', 'B', 11)
        self.set_fill_color(230, 230, 230)
        self.cell(0, 6.5, sanitize_text_for_pdf(text), 0, 1, 'L', 0)
        self.ln(0.5)


def _build_requirement_rows(shifts_by_pay_period, shifts_per_pay_period, night_count,
                             night_minimum, weekend_count, weekend_minimum,
                             validation_result, weekend_group):
    """
    Build (label, status, short_summary) rows for the Requirements Met table.
    Summaries are generated from counts/issue-lengths rather than the validator's
    verbose `details` strings so each row stays a predictable single line.
    """
    rows = []

    pp_status = validation_result.get('shifts_per_pay_period', {}).get('status', True) if validation_result else (
        shifts_per_pay_period <= 0 or all(c == shifts_per_pay_period for c in shifts_by_pay_period)
    )
    periods_str = '/'.join(str(c) for c in shifts_by_pay_period)
    pp_summary = f"Periods: {periods_str} (need {shifts_per_pay_period} each)" if shifts_per_pay_period > 0 \
        else f"Periods: {periods_str} (no requirement)"
    rows.append(("Pay Period Shifts", pp_status, pp_summary))

    night_status = validation_result.get('night_minimum', {}).get('status', True) if validation_result else (
        night_count >= night_minimum
    )
    rows.append(("Night Minimum", night_status, f"{night_count} nights (minimum {night_minimum})"))

    weekend_status = validation_result.get('weekend_minimum', {}).get('status', True) if validation_result else (
        weekend_count >= weekend_minimum
    )
    rows.append(("Weekend Minimum", weekend_status, f"{weekend_count} weekend shifts (minimum {weekend_minimum})"))

    if validation_result:
        week_res = validation_result.get('shifts_per_week')
        if week_res is not None:
            n = len(week_res.get('issues', []))
            summary = "All weeks under 4 shifts" if week_res.get('status', True) else f"{n} week(s) at/over 4-shift limit"
            rows.append(("Weekly Shift Limit", week_res.get('status', True), summary))

        rest_res = validation_result.get('rest_requirements')
        if rest_res is not None:
            n = len(rest_res.get('issues', []))
            summary = "All rest requirements met" if rest_res.get('status', True) else f"{n} rest requirement violation(s)"
            rows.append(("Rest Requirements", rest_res.get('status', True), summary))

        consec_res = validation_result.get('consecutive_shifts')
        if consec_res is not None:
            n = len(consec_res.get('issues', []))
            summary = "Consecutive-shift limit respected" if consec_res.get('status', True) else f"{n} sequence(s) too long"
            rows.append(("Consecutive Shift Limit", consec_res.get('status', True), summary))

        wg_res = validation_result.get('weekend_group_assignment')
        if wg_res is not None and weekend_group:
            periods = wg_res.get('periods_validated', [])
            met = sum(1 for p in periods if p.get('valid'))
            total = len(periods)
            summary = f"Group {weekend_group}: {met}/{total} periods met" if total else f"Group {weekend_group}"
            rows.append(("Weekend Group", wg_res.get('status', True), summary))

    return rows


def generate_bid_summary_pdf(staff_name, track_data, days, track_name, version, submission_date,
                              shifts_per_pay_period=0, night_minimum=0, weekend_minimum=0,
                              preassignments=None, validation_result=None, weekend_group=None):
    """
    Generate a one-page PDF summarizing a submitted track bid: who/what/when,
    which requirements were met, key metrics, and a compact 6-week grid.

    Args:
        staff_name (str): Name of the staff member
        track_data (dict): Dictionary of day -> assignment (preassignments already merged in)
        days (list): Ordered list of the 42 schedule days
        track_name (str): Bid track/cycle name (e.g. "FY27")
        version (int): Bid version number
        submission_date (str): Timestamp string as stored in the database
        shifts_per_pay_period (int): Required shifts per 14-day pay period (exact match)
        night_minimum (int): Minimum night shifts required
        weekend_minimum (int): Minimum weekend shifts required
        preassignments (dict, optional): Dictionary of day -> preassignment value
        validation_result (dict, optional): Result of validate_track_comprehensive(); if
            omitted, falls back to the three basic pay-period/night/weekend checks
        weekend_group (str, optional): Weekend group assignment (A-E)

    Returns:
        tuple: (pdf_bytes, filename)
    """
    pdf = BidSummaryPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(False)
    pdf.add_page()

    if isinstance(days, pd.Index):
        days_list = days.tolist()
    else:
        days_list = list(days)

    total_shifts, day_shifts, night_shifts, at_shifts = count_shifts_comprehensive(track_data, preassignments)
    weekend_shifts = count_weekend_shifts_comprehensive(track_data, preassignments)
    shifts_by_pay_period = count_shifts_by_pay_period_comprehensive(track_data, days_list, preassignments)
    expected_total = shifts_per_pay_period * 3 if shifts_per_pay_period > 0 else 0

    overall_valid = validation_result.get('overall_valid', True) if validation_result else True

    # Bid details block
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(45, 6.5, 'Staff Member:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(75, 6.5, fit_text_to_width(pdf, staff_name, 71), 0, 0)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(30, 6.5, 'Bid Version:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6.5, f'v{version}', 0, 1)

    pdf.set_font('Arial', 'B', 10)
    pdf.cell(45, 6.5, 'Bid Track:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(75, 6.5, fit_text_to_width(pdf, track_name, 71), 0, 0)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(30, 6.5, 'Submitted:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6.5, sanitize_text_for_pdf(submission_date), 0, 1)

    pdf.ln(1)
    if overall_valid:
        pdf.set_fill_color(212, 237, 218)
        status_text = 'ALL REQUIREMENTS MET'
    else:
        pdf.set_fill_color(248, 215, 218)
        n_issues = sum(1 for v in (validation_result or {}).values() if isinstance(v, dict) and not v.get('status', True))
        status_text = f'{n_issues} REQUIREMENT(S) NOT MET'
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 7, status_text, 1, 1, 'C', 1)
    pdf.ln(1.5)

    # Requirements Met table
    pdf.section_title('Requirements Met')
    rows = _build_requirement_rows(
        shifts_by_pay_period, shifts_per_pay_period, night_shifts, night_minimum,
        weekend_shifts, weekend_minimum, validation_result, weekend_group
    )
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(55, 6, 'Requirement', 1, 0, 'L', 1)
    pdf.cell(25, 6, 'Status', 1, 0, 'C', 1)
    pdf.cell(110, 6, 'Summary', 1, 1, 'L', 1)
    pdf.set_font('Arial', '', 9)
    for label, status, summary in rows:
        pdf.set_fill_color(212, 237, 218) if status else pdf.set_fill_color(248, 215, 218)
        pdf.cell(55, 6, fit_text_to_width(pdf, label, 51), 1, 0, 'L')
        pdf.cell(25, 6, 'Met' if status else 'Not Met', 1, 0, 'C', 1)
        pdf.cell(110, 6, fit_text_to_width(pdf, summary, 106), 1, 1, 'L')
    pdf.ln(2)

    # Metrics table
    pdf.section_title('Bid Metrics')
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(65, 6, 'Metric', 1, 0, 'L', 1)
    pdf.cell(35, 6, 'Value', 1, 0, 'C', 1)
    pdf.cell(45, 6, 'Requirement', 1, 0, 'C', 1)
    pdf.cell(45, 6, 'Status', 1, 1, 'C', 1)
    pdf.set_font('Arial', '', 9)

    def metric_row(label, value, requirement, status_text):
        pdf.cell(65, 6, label, 1, 0, 'L')
        pdf.cell(35, 6, str(value), 1, 0, 'C')
        pdf.cell(45, 6, requirement, 1, 0, 'C')
        pdf.cell(45, 6, sanitize_text_for_pdf(status_text), 1, 1, 'C')

    total_status = "Met" if expected_total == 0 or total_shifts == expected_total else "Not Met"
    metric_row('Total Shifts', total_shifts, f'{expected_total}' if expected_total else 'N/A', total_status)
    metric_row('Day Shifts', day_shifts, 'N/A', 'N/A')
    metric_row('Night Shifts', night_shifts, f'{night_minimum} minimum', "Met" if night_shifts >= night_minimum else "Not Met")
    metric_row('Weekend Shifts', weekend_shifts, f'{weekend_minimum} minimum', "Met" if weekend_shifts >= weekend_minimum else "Not Met")
    if at_shifts > 0:
        metric_row('AT Preassignments', at_shifts, 'N/A', 'N/A')
    pdf.ln(2)

    # Pay period breakdown mini-table
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(65, 6, 'Pay Period', 1, 0, 'L', 1)
    pdf.cell(35, 6, 'Shifts', 1, 0, 'C', 1)
    pdf.cell(45, 6, 'Required', 1, 0, 'C', 1)
    pdf.cell(45, 6, 'Status', 1, 1, 'C', 1)
    pdf.set_font('Arial', '', 9)
    pp_names = ["Pay Period 1 (Block A)", "Pay Period 2 (Block B)", "Pay Period 3 (Block C)"]
    for name, count in zip(pp_names, shifts_by_pay_period):
        status = "Met" if shifts_per_pay_period == 0 or count == shifts_per_pay_period else "Not Met"
        pdf.cell(65, 6, name, 1, 0, 'L')
        pdf.cell(35, 6, str(count), 1, 0, 'C')
        pdf.cell(45, 6, f'{shifts_per_pay_period}' if shifts_per_pay_period else 'N/A', 1, 0, 'C')
        pdf.cell(45, 6, status, 1, 1, 'C')
    pdf.ln(2)

    # Compact schedule grid
    pdf.section_title('Submitted Track')
    blocks = ["A", "B", "C"]
    for block_idx, block in enumerate(blocks):
        start_idx = block_idx * 14
        end_idx = start_idx + 14
        block_days = days_list[start_idx:end_idx]
        if not block_days:
            continue

        pdf.set_font('Arial', 'B', 8)
        pdf.cell(0, 5, f'Block {block}', 0, 1)

        for week_idx in range(2):
            week_start = week_idx * 7
            week_end = min(week_start + 7, len(block_days))
            week_days = block_days[week_start:week_end]
            if not week_days:
                continue

            cell_width = 172 / len(week_days)
            pdf.set_font('Arial', '', 7)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(18, 4.5, 'Date', 1, 0, 'C', 1)
            for wd in week_days:
                pdf.cell(cell_width, 4.5, wd.split()[0], 1, 0, 'C', 1)
            pdf.ln()

            pdf.cell(18, 4.5, 'Shift', 1, 0, 'C', 1)
            for day in week_days:
                shift = ""
                if day in track_data and track_data[day]:
                    shift = track_data[day]
                elif preassignments and day in preassignments and preassignments[day]:
                    shift = preassignments[day]

                if shift == "D":
                    pdf.set_fill_color(212, 237, 218)
                    pdf.cell(cell_width, 4.5, 'D', 1, 0, 'C', 1)
                elif shift == "N":
                    pdf.set_fill_color(204, 229, 255)
                    pdf.cell(cell_width, 4.5, 'N', 1, 0, 'C', 1)
                elif shift == "AT":
                    pdf.set_fill_color(255, 243, 205)
                    pdf.cell(cell_width, 4.5, 'AT', 1, 0, 'C', 1)
                else:
                    pdf.set_fill_color(255, 255, 255)
                    pdf.cell(cell_width, 4.5, '-', 1, 0, 'C', 1)
            pdf.ln(5)

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

    safe_name = ''.join(c if c.isalnum() else '_' for c in staff_name)
    filename = f"{safe_name}_bid_summary_v{version}_{datetime.now(_eastern_tz).strftime('%Y%m%d%H%M%S')}.pdf"

    return pdf_bytes, filename