import pandas as pd
import openpyxl
from datetime import datetime, time
import os
from training_modules.config import NON_CLASS_COLUMNS, DEFAULT_CLASS_DETAILS

class ExcelHandler:
    def __init__(self, excel_path):
        self.excel_path = excel_path
        self.workbook = None
        self.enrollment_sheet = None
        self.load_error = None
        self._load_workbook()
        
    def _load_workbook(self):
        """Load the Excel workbook"""
        try:
            # Check if file exists
            if not os.path.exists(self.excel_path):
                self.load_error = f"Excel file not found: {self.excel_path}"
                print(self.load_error)
                return
                
            # Try to load with pandas first to check structure
            try:
                # Read the first sheet to verify it exists
                df_test = pd.read_excel(self.excel_path, sheet_name=None)
                sheet_names = list(df_test.keys())
                print(f"Sheets found via pandas: {sheet_names}")
            except Exception as e:
                print(f"Warning: Could not read with pandas: {e}")
                
            # Load workbook with openpyxl
            self.workbook = openpyxl.load_workbook(self.excel_path, data_only=True)
            print(f"Available sheets: {self.workbook.sheetnames}")
            
            # Look for Class_Enrollment sheet (case-insensitive)
            enrollment_sheet_name = None
            for sheet_name in self.workbook.sheetnames:
                if 'class_enrollment' in sheet_name.lower().replace(' ', '_'):
                    enrollment_sheet_name = sheet_name
                    break
                    
            if not enrollment_sheet_name:
                # If not found, use the first sheet
                enrollment_sheet_name = self.workbook.sheetnames[0]
                print(f"Warning: Class_Enrollment sheet not found, using first sheet: {enrollment_sheet_name}")
                
            self.enrollment_sheet = self.workbook[enrollment_sheet_name]
            print(f"Successfully loaded enrollment sheet: {enrollment_sheet_name}")
            
        except Exception as e:
            self.load_error = f"Error loading workbook: {str(e)}"
            print(self.load_error)
            import traceback
            traceback.print_exc()
            
    def get_staff_list(self):
        """Get list of all staff names"""
        if self.enrollment_sheet is None:
            print(f"Excel loading error: {self.load_error}")
            return []
            
        staff_list = []
        try:
            # Start from row 2 (assuming row 1 is header)
            for row in self.enrollment_sheet.iter_rows(min_row=2, max_col=1):
                if row[0].value:
                    # Clean up the staff name
                    staff_name = str(row[0].value).strip()
                    if staff_name and staff_name.upper() != 'STAFF NAME':
                        staff_list.append(staff_name)
                        
            print(f"Found {len(staff_list)} staff members")
        except Exception as e:
            print(f"Error reading staff list: {e}")
            import traceback
            traceback.print_exc()
            
        return staff_list
        
    def get_assigned_classes(self, staff_name):
        """Get list of classes assigned to a staff member"""
        if self.enrollment_sheet is None:
            return []
            
        assigned_classes = []
        
        try:
            # Find the staff member's row
            staff_row = None
            for row_idx, row in enumerate(self.enrollment_sheet.iter_rows(min_row=2, max_col=1), start=2):
                if row[0].value and str(row[0].value).strip() == staff_name:
                    staff_row = row_idx
                    break
                    
            if staff_row:
                # Get headers (class names) from row 1
                headers = []
                for col_idx, col in enumerate(self.enrollment_sheet.iter_cols(min_col=2, max_row=1), start=2):
                    if col[0].value:
                        header_value = str(col[0].value).strip()
                        # Only include columns that are NOT in the non-class list
                        if header_value not in NON_CLASS_COLUMNS:
                            headers.append((col_idx, header_value))
                
                print(f"Found class columns: {[h[1] for h in headers]}")
                
                # Check which classes are assigned (checkbox is True)
                for col_idx, class_name in headers:
                    cell = self.enrollment_sheet.cell(row=staff_row, column=col_idx)
                    cell_value = cell.value
                    
                    # Handle different representations of True
                    if (cell_value is True or 
                        (isinstance(cell_value, str) and cell_value.lower() in ['true', 'yes', '1', 'x', '✓']) or
                        (isinstance(cell_value, int) and cell_value == 1)):
                        assigned_classes.append(class_name)
                        
            print(f"Staff {staff_name} assigned to: {assigned_classes}")
                        
        except Exception as e:
            print(f"Error getting assigned classes: {e}")
            import traceback
            traceback.print_exc()
            
        return assigned_classes
        
    def is_staff_meeting(self, class_name):
        """Check if a class is a staff meeting (contains 'SM')"""
        return 'SM' in class_name.upper()
        
    def _parse_time_value(self, time_value):
        """Parse various time formats from Excel"""
        if time_value is None:
            return None
            
        # If it's already a string in HH:MM format
        if isinstance(time_value, str):
            # Remove any whitespace
            time_value = time_value.strip()
            # Handle common time formats
            if ':' in time_value:
                return time_value
            # Handle time without colon (e.g., "800" -> "8:00")
            elif time_value.isdigit():
                if len(time_value) == 3:
                    return f"{time_value[0]}:{time_value[1:3]}"
                elif len(time_value) == 4:
                    return f"{time_value[0:2]}:{time_value[2:4]}"
                else:
                    return time_value
                    
        # If it's a datetime object
        elif isinstance(time_value, datetime):
            return time_value.strftime('%H:%M')
            
        # If it's a time object
        elif isinstance(time_value, time):
            return time_value.strftime('%H:%M')
            
        # If it's a float (Excel time as decimal fraction of day)
        elif isinstance(time_value, (int, float)):
            # Excel stores time as fraction of day
            hours = int(time_value * 24)
            minutes = int((time_value * 24 - hours) * 60)
            return f"{hours:02d}:{minutes:02d}"
            
        # Try to convert to string and parse
        else:
            try:
                time_str = str(time_value)
                if ':' in time_str:
                    return time_str
            except:
                pass
                
        return None
        
    def get_class_details(self, class_name):
        """Get details for a specific class from its sheet"""
        try:
            # Try exact match first
            sheet = None
            if class_name in self.workbook.sheetnames:
                sheet = self.workbook[class_name]
            else:
                # Try case-insensitive match
                for sheet_name in self.workbook.sheetnames:
                    if sheet_name.lower() == class_name.lower():
                        sheet = self.workbook[sheet_name]
                        break
                        
            if sheet is None:
                print(f"Warning: Sheet '{class_name}' not found in workbook")
                # Return default values with the class name
                default_details = DEFAULT_CLASS_DETAILS.copy()
                default_details['class_name'] = class_name
                return default_details
                
            details = {}
            
            # Extract dates (rows 1-8, column B), LIVE options (column C), 
            # Can work N prior (column D), and Location (column E)
            for i in range(1, 9):
                date_value = sheet.cell(row=i, column=2).value
                live_option = sheet.cell(row=i, column=3).value
                can_work_n_prior = sheet.cell(row=i, column=4).value
                location = sheet.cell(row=i, column=5).value
                
                if date_value:
                    # Handle different date formats
                    if isinstance(date_value, datetime):
                        details[f'date_{i}'] = date_value.strftime('%m/%d/%Y')
                    elif isinstance(date_value, str) and date_value.strip():
                        details[f'date_{i}'] = date_value
                    else:
                        details[f'date_{i}'] = None
                        
                    # Check if LIVE option is available for this date
                    # Handle different representations of True for checkboxes
                    has_live = (live_option is True or 
                               (isinstance(live_option, str) and live_option.lower() in ['true', 'yes', '1', 'x', '✓']) or
                               (isinstance(live_option, int) and live_option == 1))
                    
                    details[f'date_{i}_has_live'] = has_live
                    
                    # Check if night workers can attend
                    can_n_prior = (can_work_n_prior is True or
                                  (isinstance(can_work_n_prior, str) and can_work_n_prior.lower() in ['true', 'yes', '1', 'x', '✓']) or
                                  (isinstance(can_work_n_prior, int) and can_work_n_prior == 1))
                    
                    details[f'date_{i}_can_work_n_prior'] = can_n_prior
                    
                    # Store location
                    details[f'date_{i}_location'] = location if location else ""
                    
                    print(f"DEBUG: Date {i} - {details[f'date_{i}']} - LIVE: {has_live} - N prior OK: {can_n_prior} - Location: {location}")
                else:
                    details[f'date_{i}'] = None
                    details[f'date_{i}_has_live'] = False
                    details[f'date_{i}_can_work_n_prior'] = False
                    details[f'date_{i}_location'] = ""
            
            # Extract other details with defaults
            details['students_per_class'] = sheet.cell(row=9, column=2).value or 21
            details['nurses_medic_separate'] = sheet.cell(row=10, column=2).value or 'No'
            details['classes_per_day'] = sheet.cell(row=11, column=2).value or 1
            details['is_two_day_class'] = sheet.cell(row=12, column=2).value or 'No'
            
            # Extract times (rows 13-20, column B) with improved parsing
            time_labels = ['time_1_start', 'time_1_end', 'time_2_start', 'time_2_end',
                         'time_3_start', 'time_3_end', 'time_4_start', 'time_4_end']
            
            # Debug: Let's see what we're getting from the cells
            print(f"\nDEBUG: Reading times for class '{class_name}':")
            
            for idx, label in enumerate(time_labels):
                row_num = 13 + idx
                time_value = sheet.cell(row=row_num, column=2).value
                print(f"  Row {row_num}, {label}: raw value = {repr(time_value)}, type = {type(time_value)}")
                
                parsed_time = self._parse_time_value(time_value)
                details[label] = parsed_time
                
                if parsed_time:
                    print(f"    -> Parsed as: {parsed_time}")
                else:
                    # Use default times if parsing fails
                    if label == 'time_1_start' and not parsed_time:
                        details[label] = '08:00'
                        print(f"    -> Using default: 08:00")
                    elif label == 'time_1_end' and not parsed_time:
                        details[label] = '16:00'
                        print(f"    -> Using default: 16:00")
            
            # Add class name to details
            details['class_name'] = class_name
            
            print(f"\nDEBUG: Final time values for {class_name}:")
            print(f"  time_1_start: {details.get('time_1_start')}")
            print(f"  time_1_end: {details.get('time_1_end')}")
            
            return details
            
        except Exception as e:
            print(f"Error getting class details for {class_name}: {e}")
            import traceback
            traceback.print_exc()
            # Return default values with the class name
            default_details = DEFAULT_CLASS_DETAILS.copy()
            default_details['class_name'] = class_name
            return default_details
    
    def get_available_dates_with_options(self, class_name):
        """Get available dates with LIVE/Virtual options for staff meetings"""
        class_details = self.get_class_details(class_name)
        if not class_details:
            return []
            
        date_options = []
        
        for i in range(1, 9):
            date_key = f'date_{i}'
            live_key = f'date_{i}_has_live'
            
            if date_key in class_details and class_details[date_key]:
                date_str = class_details[date_key]
                has_live = class_details.get(live_key, False)
                
                if self.is_staff_meeting(class_name):
                    # For staff meetings, provide separate options
                    if has_live:
                        date_options.append((date_str, 'LIVE', f"{date_str} (LIVE Option)"))
                        date_options.append((date_str, 'Virtual', f"{date_str} (Virtual Option)"))
                    else:
                        date_options.append((date_str, 'Virtual', f"{date_str} (Virtual Only)"))
                else:
                    # For regular classes, just return the date
                    date_options.append((date_str, None, date_str))
                    
        return date_options
            
    def get_all_classes(self):
        """Get list of all available classes"""
        if self.enrollment_sheet is None:
            return []
            
        classes = []
        try:
            # Get headers from Class_Enrollment sheet
            for col in self.enrollment_sheet.iter_cols(min_col=2, max_row=1):
                if col[0].value:
                    header_value = str(col[0].value).strip()
                    # Only include columns that are NOT in the non-class list
                    if header_value not in NON_CLASS_COLUMNS:
                        classes.append(header_value)
                        
            print(f"All available classes: {classes}")
        except Exception as e:
            print(f"Error getting all classes: {e}")
            
        return classes