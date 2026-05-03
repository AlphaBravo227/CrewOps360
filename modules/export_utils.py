# modules/export_utils.py - UPDATED WITH ROLE METADATA EXPORT
"""
Enhanced export utilities for database data including role metadata
UPDATED to include staff role information in exports
"""

import pandas as pd
import streamlit as st
import sqlite3
import json
import os
import io
from datetime import datetime

def export_tracks_to_excel():
    """
    Export all tracks from the database to an Excel file
    UPDATED: Enhanced to include role metadata in exports
    
    Returns:
        bytes: Excel file as bytes if successful, None otherwise
    """
    try:
        # Check if database file exists
        db_path = 'data/medflight_tracks.db'
        if not os.path.exists(db_path):
            st.warning("No database found. Please submit at least one track first.")
            return None
            
        # Connect to database
        conn = sqlite3.connect(db_path)
        
        # Enhanced query to include role metadata
        query = """
        SELECT t.id, t.staff_name, t.track_data, t.submission_date, t.is_approved, 
               t.approved_by, t.approval_date, t.version, t.original_role, t.effective_role,
               t.track_source, t.has_preassignments, t.preassignment_count
        FROM tracks t
        WHERE t.is_active = 1
        ORDER BY t.staff_name, t.submission_date DESC
        """
        
        # Load data into DataFrame
        tracks_df = pd.read_sql_query(query, conn)
        
        # Close connection
        conn.close()
        
        if tracks_df.empty:
            st.warning("No tracks found in database.")
            return None
            
        # Vectorize simple column transformations before the JSON-parsing loop
        tracks_df = tracks_df.assign(
            approved_str=tracks_df['is_approved'].map({1: 'Yes', 0: 'No'}).fillna('No'),
            approved_by=tracks_df['approved_by'].fillna('N/A'),
            approval_date=tracks_df['approval_date'].fillna('N/A'),
            original_role=tracks_df['original_role'].fillna('Unknown'),
            effective_role=tracks_df['effective_role'].fillna('Unknown'),
            track_source=tracks_df['track_source'].fillna('Unknown'),
            has_preassignments_str=tracks_df['has_preassignments'].map({1: 'Yes', 0: 'No'}).fillna('No'),
            preassignment_count=tracks_df['preassignment_count'].fillna(0),
        )

        # JSON parsing still requires per-row work; itertuples avoids Series copy overhead
        processed_rows = []
        for row in tracks_df.itertuples(index=False):
            try:
                track_data = json.loads(row.track_data)
                processed_rows.append({
                    'Staff Name': row.staff_name,
                    'Original Role': row.original_role,
                    'Effective Role': row.effective_role,
                    'Track Source': row.track_source,
                    'Submission Date': row.submission_date,
                    'Version': row.version,
                    'Approved': row.approved_str,
                    'Approved By': row.approved_by,
                    'Approval Date': row.approval_date,
                    'Has Preassignments': row.has_preassignments_str,
                    'Preassignment Count': row.preassignment_count,
                    **track_data
                })
            except json.JSONDecodeError:
                st.error(f"Error parsing track data for {row.staff_name}")
                continue
        
        if not processed_rows:
            st.warning("No valid track data found.")
            return None
            
        # Create DataFrame from processed rows
        export_df = pd.DataFrame(processed_rows)
        
        # Create Excel file in memory with multiple sheets
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Main tracks sheet
            export_df.to_excel(writer, sheet_name='Tracks', index=False)
            
            # Role distribution summary sheet
            role_summary = create_role_summary(export_df)
            role_summary.to_excel(writer, sheet_name='Role Summary', index=False)
            
            # Track source summary sheet
            source_summary = create_track_source_summary(export_df)
            source_summary.to_excel(writer, sheet_name='Track Source Summary', index=False)
            
        return output.getvalue()
        
    except Exception as e:
        st.error(f"Error exporting tracks: {str(e)}")
        return None

def create_role_summary(tracks_df):
    """
    Create a summary of role distribution
    
    Args:
        tracks_df (DataFrame): DataFrame containing track data
        
    Returns:
        DataFrame: Role summary data
    """
    try:
        # Count by original role
        original_role_counts = tracks_df['Original Role'].value_counts().reset_index()
        original_role_counts.columns = ['Original Role', 'Count']
        original_role_counts['Percentage'] = (original_role_counts['Count'] / len(tracks_df) * 100).round(1)
        
        # Count by effective role
        effective_role_counts = tracks_df['Effective Role'].value_counts().reset_index()
        effective_role_counts.columns = ['Effective Role', 'Count']
        effective_role_counts['Percentage'] = (effective_role_counts['Count'] / len(tracks_df) * 100).round(1)
        
        # Combine into summary
        summary_data = []
        
        # Add header
        summary_data.append({
            'Category': 'ORIGINAL ROLES',
            'Role': '',
            'Count': '',
            'Percentage': ''
        })
        
        # Add original role data
        summary_data.extend([
            {'Category': '', 'Role': role, 'Count': count, 'Percentage': f"{pct}%"}
            for role, count, pct in zip(
                original_role_counts['Original Role'],
                original_role_counts['Count'],
                original_role_counts['Percentage'],
            )
        ])
        
        # Add spacer
        summary_data.append({
            'Category': '',
            'Role': '',
            'Count': '',
            'Percentage': ''
        })
        
        # Add header
        summary_data.append({
            'Category': 'EFFECTIVE ROLES',
            'Role': '',
            'Count': '',
            'Percentage': ''
        })
        
        # Add effective role data
        summary_data.extend([
            {'Category': '', 'Role': role, 'Count': count, 'Percentage': f"{pct}%"}
            for role, count, pct in zip(
                effective_role_counts['Effective Role'],
                effective_role_counts['Count'],
                effective_role_counts['Percentage'],
            )
        ])
        
        # Count role conversions (dual -> nurse)
        conversions = tracks_df[tracks_df['Original Role'] != tracks_df['Effective Role']]
        if not conversions.empty:
            summary_data.append({
                'Category': '',
                'Role': '',
                'Count': '',
                'Percentage': ''
            })
            
            summary_data.append({
                'Category': 'ROLE CONVERSIONS',
                'Role': '',
                'Count': '',
                'Percentage': ''
            })
            
            summary_data.extend([
                {'Category': '', 'Role': f"{orig} → {eff}", 'Count': 1, 'Percentage': ''}
                for orig, eff in zip(conversions['Original Role'], conversions['Effective Role'])
            ])
        
        return pd.DataFrame(summary_data)
        
    except Exception as e:
        print(f"Error creating role summary: {str(e)}")
        return pd.DataFrame()

def create_track_source_summary(tracks_df):
    """
    Create a summary of track sources
    
    Args:
        tracks_df (DataFrame): DataFrame containing track data
        
    Returns:
        DataFrame: Track source summary data
    """
    try:
        # Count by track source
        source_counts = tracks_df['Track Source'].value_counts().reset_index()
        source_counts.columns = ['Track Source', 'Count']
        source_counts['Percentage'] = (source_counts['Count'] / len(tracks_df) * 100).round(1)
        
        # Count preassignments
        preassignment_counts = tracks_df['Has Preassignments'].value_counts().reset_index()
        preassignment_counts.columns = ['Has Preassignments', 'Count']
        preassignment_counts['Percentage'] = (preassignment_counts['Count'] / len(tracks_df) * 100).round(1)
        
        # Combine into summary
        summary_data = []
        
        # Add track source header
        summary_data.append({
            'Category': 'TRACK SOURCES',
            'Value': '',
            'Count': '',
            'Percentage': ''
        })
        
        # Add track source data
        summary_data.extend([
            {'Category': '', 'Value': src, 'Count': count, 'Percentage': f"{pct}%"}
            for src, count, pct in zip(
                source_counts['Track Source'],
                source_counts['Count'],
                source_counts['Percentage'],
            )
        ])
        
        # Add spacer
        summary_data.append({
            'Category': '',
            'Value': '',
            'Count': '',
            'Percentage': ''
        })
        
        # Add preassignments header
        summary_data.append({
            'Category': 'PREASSIGNMENTS',
            'Value': '',
            'Count': '',
            'Percentage': ''
        })
        
        # Add preassignment data
        summary_data.extend([
            {'Category': '', 'Value': has_pre, 'Count': count, 'Percentage': f"{pct}%"}
            for has_pre, count, pct in zip(
                preassignment_counts['Has Preassignments'],
                preassignment_counts['Count'],
                preassignment_counts['Percentage'],
            )
        ])
        
        # Add preassignment statistics
        if 'Preassignment Count' in tracks_df.columns:
            total_preassignments = tracks_df['Preassignment Count'].sum()
            avg_preassignments = tracks_df[tracks_df['Preassignment Count'] > 0]['Preassignment Count'].mean()
            
            summary_data.append({
                'Category': '',
                'Value': '',
                'Count': '',
                'Percentage': ''
            })
            
            summary_data.append({
                'Category': 'PREASSIGNMENT STATS',
                'Value': '',
                'Count': '',
                'Percentage': ''
            })
            
            summary_data.append({
                'Category': '',
                'Value': 'Total Preassignments',
                'Count': int(total_preassignments),
                'Percentage': ''
            })
            
            if not pd.isna(avg_preassignments):
                summary_data.append({
                    'Category': '',
                    'Value': 'Avg per Staff (with preassignments)',
                    'Count': f"{avg_preassignments:.1f}",
                    'Percentage': ''
                })
        
        return pd.DataFrame(summary_data)
        
    except Exception as e:
        print(f"Error creating track source summary: {str(e)}")
        return pd.DataFrame()

def export_track_history_to_excel():
    """
    Export track history from the database to an Excel file
    UPDATED: Enhanced to include role metadata in history export
    
    Returns:
        bytes: Excel file as bytes if successful, None otherwise
    """
    try:
        # Check if database file exists
        db_path = 'data/medflight_tracks.db'
        if not os.path.exists(db_path):
            st.warning("No database found. Please submit at least one track first.")
            return None
            
        # Connect to database
        conn = sqlite3.connect(db_path)
        
        # Enhanced query to include role metadata in history
        query = """
        SELECT h.id, h.track_id, h.staff_name, h.track_data, h.submission_date, h.status,
               t.original_role, t.effective_role, t.track_source, t.has_preassignments, t.preassignment_count
        FROM track_history h
        LEFT JOIN tracks t ON h.track_id = t.id
        ORDER BY h.staff_name, h.submission_date DESC
        """
        
        # Load data into DataFrame
        history_df = pd.read_sql_query(query, conn)
        
        # Close connection
        conn.close()
        
        if history_df.empty:
            st.warning("No track history found in database.")
            return None
            
        # Vectorize simple column transformations before the JSON-parsing loop
        history_df = history_df.assign(
            original_role=history_df['original_role'].fillna('Unknown'),
            effective_role=history_df['effective_role'].fillna('Unknown'),
            track_source=history_df['track_source'].fillna('Unknown'),
            has_preassignments_str=history_df['has_preassignments'].map({1: 'Yes', 0: 'No'}).fillna('No'),
            preassignment_count=history_df['preassignment_count'].fillna(0),
        )

        processed_rows = []
        for row in history_df.itertuples(index=False):
            try:
                track_data = json.loads(row.track_data)
                processed_rows.append({
                    'Staff Name': row.staff_name,
                    'Track ID': row.track_id,
                    'Submission Date': row.submission_date,
                    'Status': row.status,
                    'Original Role': row.original_role,
                    'Effective Role': row.effective_role,
                    'Track Source': row.track_source,
                    'Has Preassignments': row.has_preassignments_str,
                    'Preassignment Count': row.preassignment_count,
                    **track_data
                })
            except json.JSONDecodeError:
                st.error(f"Error parsing track history for {row.staff_name}")
                continue
        
        if not processed_rows:
            st.warning("No valid track history found.")
            return None
            
        # Create DataFrame from processed rows
        export_df = pd.DataFrame(processed_rows)
        
        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df.to_excel(writer, sheet_name='Track History', index=False)
            
        return output.getvalue()
        
    except Exception as e:
        st.error(f"Error exporting track history: {str(e)}")
        return None

def export_role_analytics_to_excel():
    """
    NEW: Export comprehensive role analytics to Excel
    
    Returns:
        bytes: Excel file as bytes if successful, None otherwise
    """
    try:
        # Check if database file exists
        db_path = 'data/medflight_tracks.db'
        if not os.path.exists(db_path):
            st.warning("No database found. Please submit at least one track first.")
            return None
            
        # Connect to database
        conn = sqlite3.connect(db_path)
        
        # Get role distribution by track source
        role_source_query = """
        SELECT 
            original_role,
            effective_role,
            track_source,
            COUNT(*) as count,
            AVG(preassignment_count) as avg_preassignments
        FROM tracks 
        WHERE is_active = 1 
        GROUP BY original_role, effective_role, track_source
        ORDER BY track_source, effective_role, count DESC
        """
        
        role_source_df = pd.read_sql_query(role_source_query, conn)
        
        # Get shifts by role (sample some days)
        shifts_by_role_query = """
        SELECT 
            staff_name,
            original_role,
            effective_role,
            track_data
        FROM tracks 
        WHERE is_active = 1
        """
        
        shifts_df = pd.read_sql_query(shifts_by_role_query, conn)
        
        # Close connection
        conn.close()
        
        # Process shifts data to count by role
        role_shift_summary = []
        
        for row in shifts_df.itertuples(index=False):
            try:
                track_data = json.loads(row.track_data)
                values = list(track_data.values())
                day_count = values.count('D')
                night_count = values.count('N')
                at_count = values.count('AT')
                total = day_count + night_count + at_count
                role_shift_summary.append({
                    'Staff Name': row.staff_name,
                    'Original Role': row.original_role,
                    'Effective Role': row.effective_role,
                    'Total Shifts': total,
                    'Day Shifts': day_count,
                    'Night Shifts': night_count,
                    'AT Shifts': at_count,
                    'Day Percentage': f"{(day_count / total * 100):.1f}%" if total > 0 else "0%",
                    'Night Percentage': f"{(night_count / total * 100):.1f}%" if total > 0 else "0%",
                })
            except json.JSONDecodeError:
                continue
        
        role_shifts_df = pd.DataFrame(role_shift_summary)
        
        # Create Excel file with multiple analytics sheets
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Role distribution by source
            role_source_df.to_excel(writer, sheet_name='Role by Track Source', index=False)
            
            # Shift patterns by role
            role_shifts_df.to_excel(writer, sheet_name='Shifts by Role', index=False)
            
            # Summary statistics
            if not role_shifts_df.empty:
                # Group by effective role for summary stats
                role_stats = role_shifts_df.groupby('Effective Role').agg({
                    'Total Shifts': ['mean', 'min', 'max', 'std'],
                    'Day Shifts': ['mean', 'min', 'max'],
                    'Night Shifts': ['mean', 'min', 'max'],
                    'AT Shifts': ['mean', 'min', 'max']
                }).round(2)
                
                # Flatten column names
                role_stats.columns = [f"{col[0]}_{col[1]}" for col in role_stats.columns]
                role_stats = role_stats.reset_index()
                
                role_stats.to_excel(writer, sheet_name='Role Statistics', index=False)
            
        return output.getvalue()
        
    except Exception as e:
        st.error(f"Error exporting role analytics: {str(e)}")
        return None