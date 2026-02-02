# modules/admin_export.py
"""
Admin export functionality for preferences management
Integrates with Streamlit admin sidebar
"""

import streamlit as st
import pandas as pd
import sqlite3
import io
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import json
from .db_utils import get_all_location_preferences

class AdminExportManager:
    """Manages admin export functionality for preferences"""

    # Mapping from bases to shifts (D11B is now D11H)
    BASE_TO_SHIFTS = {
        "DAY_KMHT": ["D11H", "D11B"],  # D11B is the old name for D11H
        "DAY_KLWM": ["D9L", "LG"],
        "DAY_KBED": ["D7B", "GR"],
        "DAY_1B9": ["D11M", "MG"],
        "DAY_KPYM": ["D7P", "PG"],
        "NIGHT_KLWM": ["N9L"],
        "NIGHT_KBED": ["N7B", "NG"],
        "NIGHT_KPYM": ["N7P", "NP"]
    }

    def __init__(self, db_path: str = "data/medflight_tracks.db"):
        self.db_path = db_path

        # Ensure data directory exists
        if not os.path.exists("data"):
            os.makedirs("data", exist_ok=True)

    def convert_legacy_shift_prefs_to_location_prefs(self, shift_prefs: Dict[str, int]) -> Dict[str, int]:
        """
        Convert legacy shift-based preferences (9-0 scale) to location-based preferences (1-5 for days, 1-3 for nights)

        Algorithm:
        1. For each base, find all shifts that map to it and take the maximum (best) score
        2. Rank bases by their scores from highest to lowest
        3. Assign ranks: highest score → 1 (most preferred), next → 2, etc.

        Args:
            shift_prefs: Dict of shift names to preference scores (e.g., {"D7P": 9, "D7B": 8, ...})

        Returns:
            Dict with location preference rankings (e.g., {"DAY_KPYM": 1, "DAY_KBED": 2, ...})
        """
        # Convert shift names to uppercase for consistent matching
        shift_prefs_upper = {k.upper(): v for k, v in shift_prefs.items()}

        # Map bases to their maximum scores from legacy shift preferences
        base_scores = {}
        for base, shifts in self.BASE_TO_SHIFTS.items():
            max_score = None
            for shift in shifts:
                shift_upper = shift.upper()
                if shift_upper in shift_prefs_upper:
                    score = shift_prefs_upper[shift_upper]
                    if max_score is None or score > max_score:
                        max_score = score

            if max_score is not None:
                base_scores[base] = max_score

        # Separate day and night bases
        day_bases = {k: v for k, v in base_scores.items() if k.startswith("DAY_")}
        night_bases = {k: v for k, v in base_scores.items() if k.startswith("NIGHT_")}

        # Sort by score (highest first) and assign ranks
        location_prefs = {}

        # Day bases: rank 1-5 (1 = most preferred)
        sorted_day_bases = sorted(day_bases.items(), key=lambda x: x[1], reverse=True)
        for rank, (base, score) in enumerate(sorted_day_bases, start=1):
            location_prefs[base] = rank

        # Fill in any missing day bases with default values (if not all 5 day bases were ranked)
        for base in ["DAY_KMHT", "DAY_KLWM", "DAY_KBED", "DAY_1B9", "DAY_KPYM"]:
            if base not in location_prefs:
                location_prefs[base] = 3  # Default middle value

        # Night bases: rank 1-3 (1 = most preferred)
        sorted_night_bases = sorted(night_bases.items(), key=lambda x: x[1], reverse=True)
        for rank, (base, score) in enumerate(sorted_night_bases, start=1):
            location_prefs[base] = rank

        # Fill in any missing night bases with default values
        for base in ["NIGHT_KLWM", "NIGHT_KBED", "NIGHT_KPYM"]:
            if base not in location_prefs:
                location_prefs[base] = 2  # Default middle value

        return location_prefs

    def get_legacy_shift_preferences(self, staff_name: str) -> Optional[Dict[str, int]]:
        """
        Get legacy shift preferences for a staff member from user_preferences table

        Args:
            staff_name: Name of staff member

        Returns:
            Dict of shift names to preference scores, or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences'")
            if not cursor.fetchone():
                conn.close()
                return None

            # Get active preferences for this staff member
            cursor.execute("""
                SELECT shift_name, preference_score
                FROM user_preferences
                WHERE staff_name = ? AND is_active = 1
            """, (staff_name,))

            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return None

            # Convert to dict
            return {shift_name: score for shift_name, score in rows}

        except Exception as e:
            print(f"Error getting legacy preferences for {staff_name}: {str(e)}")
            return None

    def check_database_status(self) -> str:
        """Check if database exists and what tables it contains"""
        try:
            if not os.path.exists(self.db_path):
                return "Database file not found"
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check for preference tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('user_preferences', 'preference_history')")
            pref_tables = cursor.fetchall()
            
            # Get counts if tables exist
            status_parts = []
            if any(table[0] == 'user_preferences' for table in pref_tables):
                cursor.execute("SELECT COUNT(*) FROM user_preferences WHERE is_active = 1")
                active_prefs = cursor.fetchone()[0]
                status_parts.append(f"{active_prefs} active preferences")
            
            if any(table[0] == 'preference_history' for table in pref_tables):
                cursor.execute("SELECT COUNT(DISTINCT staff_name) FROM preference_history")
                unique_staff = cursor.fetchone()[0]
                status_parts.append(f"{unique_staff} staff with history")
            
            conn.close()
            
            if status_parts:
                return f"Connected - {', '.join(status_parts)}"
            else:
                return "Connected - No preference data found"
                
        except Exception as e:
            return f"Error: {str(e)}"
        
    def get_location_preferences(self) -> pd.DataFrame:
        """Load location-based preferences from database"""
        try:
            success, location_prefs_list = get_all_location_preferences()

            if not success or not location_prefs_list:
                return pd.DataFrame()

            # Transform to DataFrame format
            location_prefs_data = []
            for pref in location_prefs_list:
                location_prefs_data.append({
                    'staff_name': pref['staff_name'],
                    'DAY_KMHT': pref['day_locations']['KMHT'],
                    'DAY_KLWM': pref['day_locations']['KLWM'],
                    'DAY_KBED': pref['day_locations']['KBED'],
                    'DAY_1B9': pref['day_locations']['1B9'],
                    'DAY_KPYM': pref['day_locations']['KPYM'],
                    'NIGHT_KLWM': pref['night_locations']['KLWM'],
                    'NIGHT_KBED': pref['night_locations']['KBED'],
                    'NIGHT_KPYM': pref['night_locations']['KPYM'],
                    'ZIP_CODE': pref['zip_code'],
                    'REDUCED_REST_OK': 1 if pref['reduced_rest_ok'] else 0,
                    'N_TO_D_FLEX': pref['n_to_d_flex'],
                    'last_updated': pref['modified_date']
                })

            return pd.DataFrame(location_prefs_data)

        except Exception as e:
            st.error(f"Error loading location preferences: {str(e)}")
            return pd.DataFrame()

    def get_app_preferences(self) -> pd.DataFrame:
        """Load app preferences from database (LEGACY - for old shift-based system)"""
        try:
            conn = sqlite3.connect(self.db_path)

            # Check if user_preferences table exists
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences'")
            table_exists = cursor.fetchone()

            if not table_exists:
                st.info("No user preference updates found in database yet.")
                conn.close()
                return pd.DataFrame()

            # Get all current active preferences from database
            query = """
            SELECT
                staff_name,
                shift_name,
                preference_score,
                shift_type,
                modified_date as last_updated
            FROM user_preferences
            WHERE is_active = 1
            ORDER BY staff_name, shift_name
            """

            raw_prefs_df = pd.read_sql_query(query, conn)
            conn.close()

            if raw_prefs_df.empty:
                st.info("No active user preferences found in database.")
                return pd.DataFrame()

            # Transform the data to match the original Excel format
            app_prefs_list = []

            # Group by staff name
            for staff_name, group in raw_prefs_df.groupby('staff_name'):
                staff_prefs = {
                    'staff_name': staff_name,
                    'last_updated': group['last_updated'].max()  # Most recent update
                }

                # Add preference scores for each shift
                for _, row in group.iterrows():
                    shift_name = row['shift_name'].lower()
                    staff_prefs[shift_name] = row['preference_score']

                app_prefs_list.append(staff_prefs)

            app_prefs_df = pd.DataFrame(app_prefs_list)
            return app_prefs_df

        except Exception as e:
            st.error(f"Error loading app preferences: {str(e)}")
            return pd.DataFrame()
    
    def combine_preferences(self, original_prefs_df: pd.DataFrame, app_prefs_df: pd.DataFrame) -> pd.DataFrame:
        """
        Combine original and app preferences with source tracking
        Boolean preferences (Reduced Rest OK, N to D Flex) follow priority:
        1. user_boolean_preferences table (user edits)
        2. uploaded preferences file (backup)
        3. default values (0 for Reduced Rest, "No" for N to D Flex)
        
        Args:
            original_prefs_df: Original Excel preferences
            app_prefs_df: Updated app preferences
            
        Returns:
            Combined DataFrame with SOURCE column
        """
        if original_prefs_df.empty:
            st.error("Original preferences DataFrame is empty")
            return pd.DataFrame()
        
        # Get boolean preferences from database for all staff
        boolean_prefs_dict = self._get_all_boolean_preferences()
        
        # Create combined preferences list
        combined_prefs = []
        
        # Create lookup for app preferences (shift preferences only)
        app_prefs_dict = {}
        if not app_prefs_df.empty:
            for _, row in app_prefs_df.iterrows():
                app_prefs_dict[row['staff_name'].lower()] = row.to_dict()
        
        # Process original preferences
        for _, original_row in original_prefs_df.iterrows():
            staff_name = original_row['STAFF NAME']
            staff_name_lower = staff_name.lower()
            
            # Check if this staff has app-updated shift preferences
            if staff_name_lower in app_prefs_dict:
                app_pref = app_prefs_dict[staff_name_lower]
                
                # Get boolean preferences with priority logic
                reduced_rest, n_to_d_flex = self._get_boolean_preferences_with_priority(
                    staff_name, boolean_prefs_dict, original_row
                )
                
                # Use app preferences with boolean preferences from priority logic
                combined_row = {
                    'STAFF NAME': staff_name,
                    'ROLE': original_row.get('ROLE', ''),
                    'SOURCE': 'App Updated',
                    'LAST UPDATED': app_pref.get('last_updated', ''),
                    'No Matrix': original_row.get('No Matrix', 0),
                    'Seniority': original_row.get('Seniority', 0),
                    'Reduced Rest OK': reduced_rest,  # Priority logic applied
                    'N to D Flex': n_to_d_flex,     # Priority logic applied
                    'D7B': app_pref.get('d7b', 0),
                    'GR': app_pref.get('gr', 0),
                    'D11B': app_pref.get('d11b', 0),
                    'FW': app_pref.get('fw', 0),
                    'D9L': app_pref.get('d9l', 0),
                    'LG': app_pref.get('lg', 0),
                    'D7P': app_pref.get('d7p', 0),
                    'PG': app_pref.get('pg', 0),
                    'D11M': app_pref.get('d11m', 0),
                    'MG': app_pref.get('mg', 0),
                    'N7B': app_pref.get('n7b', 0),
                    'NG': app_pref.get('ng', 0),
                    'N9L': app_pref.get('n9l', 0),
                    'N7P': app_pref.get('n7p', 0),
                    'NP': app_pref.get('np', 0)
                }
                
                # Remove from app dict to track processed entries
                del app_prefs_dict[staff_name_lower]
                
            else:
                # Use original preferences but still apply boolean preference priority logic
                reduced_rest, n_to_d_flex = self._get_boolean_preferences_with_priority(
                    staff_name, boolean_prefs_dict, original_row
                )
                
                combined_row = {
                    'STAFF NAME': staff_name,
                    'ROLE': original_row.get('ROLE', ''),
                    'SOURCE': 'Original Excel',
                    'LAST UPDATED': 'N/A',
                    'No Matrix': original_row.get('No Matrix', 0),
                    'Seniority': original_row.get('Seniority', 0),
                    'Reduced Rest OK': reduced_rest,  # Priority logic applied
                    'N to D Flex': n_to_d_flex,     # Priority logic applied
                    'D7B': original_row.get('D7B', 0),
                    'GR': original_row.get('GR', 0),
                    'D11B': original_row.get('D11B', 0),
                    'FW': original_row.get('FW', 0),
                    'D9L': original_row.get('D9L', 0),
                    'LG': original_row.get('LG', 0),
                    'D7P': original_row.get('D7P', 0),
                    'PG': original_row.get('PG', 0),
                    'D11M': original_row.get('D11M', 0),
                    'MG': original_row.get('MG', 0),
                    'N7B': original_row.get('N7B', 0),
                    'NG': original_row.get('NG', 0),
                    'N9L': original_row.get('N9L', 0),
                    'N7P': original_row.get('N7P', 0),
                    'NP': original_row.get('NP', 0)
                }
            
            combined_prefs.append(combined_row)
        
        # Add any remaining app-only preferences (staff who only exist in app)
        for staff_name_lower, app_pref in app_prefs_dict.items():
            staff_name = app_pref['staff_name']
            
            # For app-only staff, get boolean preferences from database (or defaults)
            reduced_rest, n_to_d_flex = self._get_boolean_preferences_with_priority(
                staff_name, boolean_prefs_dict, None  # No original row
            )
            
            combined_row = {
                'STAFF NAME': staff_name,
                'ROLE': 'Unknown',  # No role info in app preferences
                'SOURCE': 'App Only',
                'LAST UPDATED': app_pref.get('last_updated', ''),
                'No Matrix': 0,
                'Seniority': 0,
                'Reduced Rest OK': reduced_rest,  # From database or default
                'N to D Flex': n_to_d_flex,     # From database or default
                'D7B': app_pref.get('d7b', 0),
                'GR': app_pref.get('gr', 0),
                'D11B': app_pref.get('d11b', 0),
                'FW': app_pref.get('fw', 0),
                'D9L': app_pref.get('d9l', 0),
                'LG': app_pref.get('lg', 0),
                'D7P': app_pref.get('d7p', 0),
                'PG': app_pref.get('pg', 0),
                'D11M': app_pref.get('d11m', 0),
                'MG': app_pref.get('mg', 0),
                'N7B': app_pref.get('n7b', 0),
                'NG': app_pref.get('ng', 0),
                'N9L': app_pref.get('n9l', 0),
                'N7P': app_pref.get('n7p', 0),
                'NP': app_pref.get('np', 0)
            }
            combined_prefs.append(combined_row)
        
        return pd.DataFrame(combined_prefs)

    def _get_all_boolean_preferences(self) -> dict:
        """
        Get all boolean preferences from the database
        
        Returns:
            dict: {staff_name_lower: {pref_name: pref_value}}
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if boolean preferences table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_boolean_preferences'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
                conn.close()
                return {}
            
            # Get all active boolean preferences
            cursor.execute("""
                SELECT staff_name, preference_name, preference_value
                FROM user_boolean_preferences 
                WHERE is_active = 1
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            # Organize by staff name
            boolean_prefs = {}
            for staff_name, pref_name, pref_value in rows:
                staff_key = staff_name.lower()
                if staff_key not in boolean_prefs:
                    boolean_prefs[staff_key] = {}
                boolean_prefs[staff_key][pref_name] = pref_value
            
            return boolean_prefs
            
        except Exception as e:
            print(f"Error getting boolean preferences: {str(e)}")
            return {}

    def _get_boolean_preferences_with_priority(self, staff_name: str, boolean_prefs_dict: dict, original_row) -> tuple:
        """
        Get boolean preferences with priority logic:
        1. user_boolean_preferences table
        2. uploaded preferences file
        3. defaults
        
        Args:
            staff_name: Staff member name
            boolean_prefs_dict: Dictionary of all database boolean preferences
            original_row: Original Excel row (can be None for app-only staff)
            
        Returns:
            tuple: (reduced_rest_value, n_to_d_flex_value)
        """
        staff_key = staff_name.lower()
        
        # Default values
        reduced_rest = 0  # Default to "No"
        n_to_d_flex = "No"  # Default to "No"
        
        # Check database first (highest priority)
        if staff_key in boolean_prefs_dict:
            db_prefs = boolean_prefs_dict[staff_key]
            
            if 'Reduced Rest OK' in db_prefs:
                # Convert database value to 0/1
                db_value = db_prefs['Reduced Rest OK']
                if isinstance(db_value, str) and db_value.isdigit():
                    reduced_rest = int(db_value)
                elif isinstance(db_value, bool):
                    reduced_rest = 1 if db_value else 0
                elif isinstance(db_value, (int, float)):
                    reduced_rest = 1 if db_value else 0
            
            if 'N to D Flex' in db_prefs:
                # N to D Flex is stored as string in database
                n_to_d_flex = str(db_prefs['N to D Flex'])
        
        # If not found in database, check original file (backup)
        else:
            if original_row is not None:
                # Get from original Excel file
                file_reduced_rest = original_row.get('Reduced Rest OK', 0)
                file_n_to_d_flex = original_row.get('N to D Flex', 0)
                
                # Convert file values to proper format
                if isinstance(file_reduced_rest, (int, float)):
                    reduced_rest = 1 if file_reduced_rest else 0
                elif isinstance(file_reduced_rest, str):
                    reduced_rest = 1 if file_reduced_rest.lower() in ['1', 'yes', 'true'] else 0
                
                # Convert N to D Flex from file format
                if isinstance(file_n_to_d_flex, str):
                    n_to_d_flex = file_n_to_d_flex
                elif file_n_to_d_flex == 1:
                    n_to_d_flex = "Yes"
                elif file_n_to_d_flex == 0:
                    n_to_d_flex = "No"
                else:
                    n_to_d_flex = "Maybe"
            # If no original_row (app-only staff), defaults are already set above
        
        return reduced_rest, n_to_d_flex

    def export_location_preferences(self, original_prefs_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        Export location-based preferences with role information from original file.
        Includes all staff from original file, converting legacy shift preferences for those
        who haven't filled out new location preferences.

        Args:
            original_prefs_df: Original preferences DataFrame (for role info and staff list)

        Returns:
            DataFrame with location preferences ready for export
        """
        if original_prefs_df is None or original_prefs_df.empty:
            st.warning("No original preferences file provided - cannot export.")
            return pd.DataFrame()

        # Get location preferences from new system
        location_prefs_df = self.get_location_preferences()

        # Create a dict of staff who have new location preferences
        location_prefs_dict = {}
        if not location_prefs_df.empty:
            for _, row in location_prefs_df.iterrows():
                location_prefs_dict[row['staff_name'].lower()] = row.to_dict()

        # Create export data for all staff
        export_data = []

        for _, orig_row in original_prefs_df.iterrows():
            staff_name = orig_row['STAFF NAME']
            staff_name_lower = staff_name.lower()

            # Get common attributes from original file
            role = orig_row.get('ROLE', 'Unknown')
            no_matrix = orig_row.get('No Matrix', 0)
            seniority = orig_row.get('Seniority', 0)

            # Check if staff has new location preferences
            if staff_name_lower in location_prefs_dict:
                # Use new system preferences
                loc_prefs = location_prefs_dict[staff_name_lower]

                export_row = {
                    'STAFF NAME': staff_name,
                    'ROLE': role,
                    'No Matrix': no_matrix,
                    'Seniority': seniority,
                    'DAY_KMHT': loc_prefs['DAY_KMHT'],
                    'DAY_KLWM': loc_prefs['DAY_KLWM'],
                    'DAY_KBED': loc_prefs['DAY_KBED'],
                    'DAY_1B9': loc_prefs['DAY_1B9'],
                    'DAY_KPYM': loc_prefs['DAY_KPYM'],
                    'NIGHT_KLWM': loc_prefs['NIGHT_KLWM'],
                    'NIGHT_KBED': loc_prefs['NIGHT_KBED'],
                    'NIGHT_KPYM': loc_prefs['NIGHT_KPYM'],
                    'ZIP_CODE': loc_prefs['ZIP_CODE'],
                    'REDUCED_REST_OK': loc_prefs['REDUCED_REST_OK'],
                    'N_TO_D_FLEX': loc_prefs['N_TO_D_FLEX'],
                    'LAST_UPDATED': loc_prefs['last_updated'],
                    'PREFERENCE_SOURCE': 'New System'
                }
            else:
                # Try to get legacy shift preferences and convert them
                legacy_prefs = self.get_legacy_shift_preferences(staff_name)

                if legacy_prefs:
                    # Convert legacy preferences to location preferences
                    converted_prefs = self.convert_legacy_shift_prefs_to_location_prefs(legacy_prefs)

                    # Get boolean preferences with priority logic
                    boolean_prefs_dict = self._get_all_boolean_preferences()
                    reduced_rest, n_to_d_flex = self._get_boolean_preferences_with_priority(
                        staff_name, boolean_prefs_dict, orig_row
                    )

                    export_row = {
                        'STAFF NAME': staff_name,
                        'ROLE': role,
                        'No Matrix': no_matrix,
                        'Seniority': seniority,
                        'DAY_KMHT': converted_prefs.get('DAY_KMHT', 3),
                        'DAY_KLWM': converted_prefs.get('DAY_KLWM', 3),
                        'DAY_KBED': converted_prefs.get('DAY_KBED', 3),
                        'DAY_1B9': converted_prefs.get('DAY_1B9', 3),
                        'DAY_KPYM': converted_prefs.get('DAY_KPYM', 3),
                        'NIGHT_KLWM': converted_prefs.get('NIGHT_KLWM', 2),
                        'NIGHT_KBED': converted_prefs.get('NIGHT_KBED', 2),
                        'NIGHT_KPYM': converted_prefs.get('NIGHT_KPYM', 2),
                        'ZIP_CODE': orig_row.get('ZIP CODE', ''),
                        'REDUCED_REST_OK': reduced_rest,
                        'N_TO_D_FLEX': n_to_d_flex,
                        'LAST_UPDATED': 'Legacy Converted',
                        'PREFERENCE_SOURCE': 'Legacy Converted'
                    }
                else:
                    # No preferences in either system - use defaults
                    # Get boolean preferences with priority logic
                    boolean_prefs_dict = self._get_all_boolean_preferences()
                    reduced_rest, n_to_d_flex = self._get_boolean_preferences_with_priority(
                        staff_name, boolean_prefs_dict, orig_row
                    )

                    export_row = {
                        'STAFF NAME': staff_name,
                        'ROLE': role,
                        'No Matrix': no_matrix,
                        'Seniority': seniority,
                        'DAY_KMHT': 3,
                        'DAY_KLWM': 3,
                        'DAY_KBED': 3,
                        'DAY_1B9': 3,
                        'DAY_KPYM': 3,
                        'NIGHT_KLWM': 2,
                        'NIGHT_KBED': 2,
                        'NIGHT_KPYM': 2,
                        'ZIP_CODE': orig_row.get('ZIP CODE', ''),
                        'REDUCED_REST_OK': reduced_rest,
                        'N_TO_D_FLEX': n_to_d_flex,
                        'LAST_UPDATED': 'No Preferences',
                        'PREFERENCE_SOURCE': 'Default Values'
                    }

            export_data.append(export_row)

        return pd.DataFrame(export_data)

    def generate_summary_stats(self, combined_df: pd.DataFrame) -> Dict:
        """Generate summary statistics for the combined preferences"""
        if combined_df.empty:
            return {}
        
        summary = {
            'total_staff': len(combined_df),
            'original_excel_count': len(combined_df[combined_df['SOURCE'] == 'Original Excel']),
            'app_updated_count': len(combined_df[combined_df['SOURCE'] == 'App Updated']),
            'app_only_count': len(combined_df[combined_df['SOURCE'] == 'App Only']),
            'role_breakdown': combined_df['ROLE'].value_counts().to_dict()
        }
        
        return summary
    
    def export_raw_preferences_data(self) -> bytes:
        """Export raw preferences data as downloadable content"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('user_preferences', 'preference_history')")
            tables = cursor.fetchall()
            
            if not tables:
                st.warning("No preference tables found in database.")
                return b"No preference data available in database."
            
            # Get all preference data including history
            query_parts = []
            
            # Add current preferences if table exists
            if any(table[0] == 'user_preferences' for table in tables):
                query_parts.append("""
                SELECT 
                    staff_name,
                    shift_name,
                    preference_score,
                    shift_type,
                    created_date,
                    modified_date,
                    CASE WHEN is_active = 1 THEN 'active' ELSE 'inactive' END as status,
                    'current' as source
                FROM user_preferences
                """)
            
            # Add historical preferences if table exists
            if any(table[0] == 'preference_history' for table in tables):
                query_parts.append("""
                SELECT 
                    staff_name,
                    'multiple' as shift_name,
                    preference_data as preference_score,
                    action as shift_type,
                    timestamp as created_date,
                    timestamp as modified_date,
                    'history' as status,
                    source
                FROM preference_history
                """)
            
            if query_parts:
                query = " UNION ALL ".join(query_parts) + " ORDER BY staff_name, modified_date DESC"
                df = pd.read_sql_query(query, conn)
            else:
                df = pd.DataFrame()
            
            conn.close()
            
            if df.empty:
                return b"No preference data found in database."
            
            # Convert to CSV for .dl format (delimiter format)
            output = io.StringIO()
            df.to_csv(output, index=False, sep='|')  # Using pipe delimiter for .dl format
            
            return output.getvalue().encode('utf-8')
            
        except Exception as e:
            st.error(f"Error exporting raw preferences: {str(e)}")
            return b"Error occurred while exporting preferences data."


def display_admin_export_section(preferences_df: pd.DataFrame):
    """
    Display admin export functionality in sidebar
    
    Args:
        preferences_df: Original preferences DataFrame from Excel
    """
    if not st.session_state.get('admin_authenticated', False):
        return
    
    st.markdown("---")
    st.header("📤 Preferences Export Center")
    
    # Use the correct database path in the data folder
    export_manager = AdminExportManager("data/medflight_tracks.db")
    
    # Check database status
    db_status = export_manager.check_database_status()
    if db_status:
        st.info(f"📊 Database: {db_status}")
    
    # Initialize session state for export data
    if 'export_combined_prefs' not in st.session_state:
        st.session_state.export_combined_prefs = None
    if 'export_summary' not in st.session_state:
        st.session_state.export_summary = None
    if 'export_location_prefs' not in st.session_state:
        st.session_state.export_location_prefs = None
    
    # Refresh data button
    if st.button("🔄 Refresh Export Data", use_container_width=True):
        with st.spinner("Loading preference data..."):
            # Load location preferences (NEW SYSTEM)
            location_prefs_df = export_manager.export_location_preferences(preferences_df)
            st.session_state.export_location_prefs = location_prefs_df

            # Load app preferences from database (LEGACY SYSTEM)
            app_prefs_df = export_manager.get_app_preferences()

            # Combine with original preferences (LEGACY SYSTEM)
            if not preferences_df.empty:
                combined_df = export_manager.combine_preferences(preferences_df, app_prefs_df)
                summary = export_manager.generate_summary_stats(combined_df)

                # Store in session state
                st.session_state.export_combined_prefs = combined_df
                st.session_state.export_summary = summary

                st.success("✅ Export data refreshed successfully!")
            else:
                st.error("❌ No original preferences data available")
    
    # Display summary if available
    if st.session_state.export_summary:
        summary = st.session_state.export_summary
        
        st.subheader("📊 Data Summary")
        
        # Create metrics columns
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Total Staff", summary['total_staff'])
            st.metric("App Updated", summary['app_updated_count'])
        
        with col2:
            st.metric("Original Excel", summary['original_excel_count'])
            st.metric("App Only", summary['app_only_count'])
        
        # Role breakdown
        st.markdown("**Role Breakdown:**")
        for role, count in summary['role_breakdown'].items():
            st.text(f"• {role}: {count}")
    
    # Export buttons
    st.subheader("📁 Export Options")

    # NEW: Location Preferences Export
    st.markdown("#### 📍 Location-Based Preferences (NEW SYSTEM)")
    if st.button("📊 Export Location Preferences Excel", use_container_width=True):
        if st.session_state.export_location_prefs is not None and not st.session_state.export_location_prefs.empty:
            location_df = st.session_state.export_location_prefs

            # Create Excel file in memory
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Main location preferences sheet
                location_df.to_excel(writer, sheet_name='Location Preferences', index=False)

                # Summary sheet
                summary_data = [
                    ['Total Staff with Preferences', len(location_df)],
                    ['', ''],
                    ['Column Descriptions', ''],
                    ['No Matrix', 'Staff member excluded from matrix scheduling (1=Yes, 0=No)'],
                    ['Seniority', 'Staff member seniority ranking'],
                    ['DAY_KMHT', 'Day shift preference for KMHT (1-5, 1=most preferred)'],
                    ['DAY_KLWM', 'Day shift preference for KLWM (1-5, 1=most preferred)'],
                    ['DAY_KBED', 'Day shift preference for KBED (1-5, 1=most preferred)'],
                    ['DAY_1B9', 'Day shift preference for 1B9 (1-5, 1=most preferred)'],
                    ['DAY_KPYM', 'Day shift preference for KPYM (1-5, 1=most preferred)'],
                    ['NIGHT_KLWM', 'Night shift preference for KLWM (1-3, 1=most preferred)'],
                    ['NIGHT_KBED', 'Night shift preference for KBED (1-3, 1=most preferred)'],
                    ['NIGHT_KPYM', 'Night shift preference for KPYM (1-3, 1=most preferred)'],
                    ['ZIP_CODE', 'Staff member zip code'],
                    ['REDUCED_REST_OK', '1=Yes, 0=No'],
                    ['N_TO_D_FLEX', 'Yes/No/Maybe'],
                    ['PREFERENCE_SOURCE', 'New System: filled out location prefs | Legacy Converted: converted from old shift system | Default Values: no preferences found']
                ]

                summary_df = pd.DataFrame(summary_data, columns=['Field', 'Description'])
                summary_df.to_excel(writer, sheet_name='Field Descriptions', index=False)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"location_preferences_{timestamp}.xlsx"

            st.download_button(
                label="⬇️ Download Location Preferences",
                data=output.getvalue(),
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            st.success("✅ Location preferences export ready for download!")
        else:
            st.warning("⚠️ Please refresh export data first")

    st.markdown("---")
    st.markdown("#### 📋 Legacy Shift-Based Preferences (OLD SYSTEM)")

    # Raw .dl file export
    if st.button("📄 Export Raw .dl File", use_container_width=True):
        with st.spinner("Generating raw export..."):
            raw_data = export_manager.export_raw_preferences_data()
            
            if raw_data:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"preferences_raw_{timestamp}.dl"
                
                st.download_button(
                    label="⬇️ Download Raw .dl File",
                    data=raw_data,
                    file_name=filename,
                    mime="text/plain",
                    use_container_width=True
                )
                st.success("✅ Raw export ready for download!")
    
    # Comprehensive Excel export
    if st.button("📊 Export Comprehensive Excel", use_container_width=True):
        if st.session_state.export_combined_prefs is not None:
            combined_df = st.session_state.export_combined_prefs
            
            # Create Excel file in memory
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Main preferences sheet
                combined_df.to_excel(writer, sheet_name='Combined Preferences', index=False)
                
                # Summary sheet
                summary_data = []
                if st.session_state.export_summary:
                    summary = st.session_state.export_summary
                    summary_data = [
                        ['Total Staff', summary['total_staff']],
                        ['Original Excel', summary['original_excel_count']],
                        ['App Updated', summary['app_updated_count']],
                        ['App Only', summary['app_only_count']],
                        ['', ''],
                        ['Role Breakdown', ''],
                    ]
                    
                    for role, count in summary['role_breakdown'].items():
                        summary_data.append([role, count])
                
                summary_df = pd.DataFrame(summary_data, columns=['Metric', 'Count'])
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"comprehensive_preferences_{timestamp}.xlsx"
            
            st.download_button(
                label="⬇️ Download Comprehensive Excel",
                data=output.getvalue(),
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            st.success("✅ Comprehensive export ready for download!")
        else:
            st.warning("⚠️ Please refresh export data first")
    
    # Export explanation
    with st.expander("ℹ️ Export Information"):
        st.markdown("""
        **Export Options Explained:**
        
        **Raw .dl File:**
        - Contains all preference data from the database
        - Includes both current and historical records
        - Pipe-delimited format for technical use
        
        **Comprehensive Excel:**
        - Combines original Excel preferences with app updates
        - **SOURCE column indicates data origin:**
          - `Original Excel`: No app updates (uses original data)
          - `App Updated`: Staff updated via app (uses latest data)
          - `App Only`: Staff exists only in app database
        - Includes summary statistics sheet
        - Easy to read and analyze format
        
        **Data Priority:**
        App preferences always take priority over original Excel data when both exist.
        """)


# Integration function for main app.py
def integrate_admin_export_in_sidebar(preferences_df: pd.DataFrame):
    """
    Function to be called in main app.py sidebar
    
    Args:
        preferences_df: The original preferences DataFrame loaded from Excel
    """
    display_admin_export_section(preferences_df)