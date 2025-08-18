# modules/column_mapper.py
"""
Module for automated column name detection and mapping
"""

def auto_detect_columns(preferences_df, current_tracks_df):
    """
    Automatically detect and map column names based on standard naming conventions.
    
    Args:
        preferences_df (DataFrame): DataFrame containing staff preferences and attributes
        current_tracks_df (DataFrame): DataFrame containing current staff assignments
        
    Returns:
        dict: Dictionary with detected column mappings
    """
    column_mappings = {
        "staff_col_prefs": None,
        "staff_col_tracks": None,
        "role_col": None,
        "no_matrix_col": None,
        "reduced_rest_col": None,
        "seniority_col": None
    }
    
    # Define standard column names with potential variations
    staff_name_variations = ["STAFF NAME", "Staff Name", "staff name", "StaffName", "Staff_Name", "NAME", "Name", "name"]
    role_variations = ["ROLE", "Role", "role", "Position", "POSITION", "position", "Title", "TITLE", "title"]
    no_matrix_variations = ["No Matrix", "NO MATRIX", "no matrix", "NoMatrix", "No_Matrix", "Not Matrix", "Not_Matrix"]
    reduced_rest_variations = ["Reduced Rest OK", "REDUCED REST OK", "reduced rest ok", "ReducedRest", "Reduced_Rest"]
    seniority_variations = ["Seniority", "SENIORITY", "seniority", "Senority", "SENORITY", "Rank", "RANK", "rank"]
    
    # Get lowercase versions of column names for case-insensitive matching
    prefs_cols_lower = {col.lower(): col for col in preferences_df.columns}
    tracks_cols_lower = {col.lower(): col for col in current_tracks_df.columns}
    
    # Find staff name column in preferences file
    for variation in staff_name_variations:
        if variation.lower() in prefs_cols_lower:
            column_mappings["staff_col_prefs"] = prefs_cols_lower[variation.lower()]
            break
    
    # Find staff name column in current tracks file
    for variation in staff_name_variations:
        if variation.lower() in tracks_cols_lower:
            column_mappings["staff_col_tracks"] = tracks_cols_lower[variation.lower()]
            break
    
    # Find role column in preferences file
    for variation in role_variations:
        if variation.lower() in prefs_cols_lower:
            column_mappings["role_col"] = prefs_cols_lower[variation.lower()]
            break
    
    # Find no matrix column in preferences file
    for variation in no_matrix_variations:
        if variation.lower() in prefs_cols_lower:
            column_mappings["no_matrix_col"] = prefs_cols_lower[variation.lower()]
            break
    
    # Find reduced rest column in preferences file
    for variation in reduced_rest_variations:
        if variation.lower() in prefs_cols_lower:
            column_mappings["reduced_rest_col"] = prefs_cols_lower[variation.lower()]
            break
    
    # Find seniority column in preferences file
    for variation in seniority_variations:
        if variation.lower() in prefs_cols_lower:
            column_mappings["seniority_col"] = prefs_cols_lower[variation.lower()]
            break
    
    # Check if all required columns were found
    missing_columns = [key for key, value in column_mappings.items() if value is None]
    
    # Return what we found along with status
    return {
        "column_mappings": column_mappings,
        "all_found": len(missing_columns) == 0,
        "missing_columns": missing_columns
    }
