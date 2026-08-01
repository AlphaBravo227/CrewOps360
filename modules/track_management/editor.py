# modules/track_management/editor.py
"""
UPDATED: Track editor with enhanced hypothetical scheduler display and fixed weekend group highlighting
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from modules.enhanced_track_validator import validate_track_comprehensive
from modules.enhanced_validation_display import display_comprehensive_validation, create_validation_summary_card, get_weekend_group_highlighting_info
from modules.track_modification_core import calculate_all_modification_options
from modules.db_utils import get_track_from_db
from modules.track_management.utils import reset_track_session_state
from modules.track_management.preassignment import display_preassignments

def modify_track_enhanced(
    selected_staff,
    staff_track,
    preferences_df,
    current_tracks_df,
    days,
    staff_col_prefs,
    staff_col_tracks,
    role_col,
    no_matrix_col,
    reduced_rest_col,
    seniority_col,
    shifts_per_pay_period,
    night_minimum,
    preassignments=None,
    is_new_track=False,
    weekend_minimum=0,
    requirements_df=None
):
    """
    Streamlined track modification with continuous validation and enhanced hypothetical scheduler display
    """
    st.subheader(f"Track Modification for {selected_staff}")
    
    # Get weekend group for this staff member
    weekend_group = None
    if requirements_df is not None:
        from modules.weekend_group_validator import get_staff_weekend_group
        weekend_group = get_staff_weekend_group(selected_staff, requirements_df)
    
    # Display requirements prominently
    st.markdown("### 📋 Requirements for Track Modification")
    req_cols = st.columns(4)
    with req_cols[0]:
        st.metric("Shifts per Pay Period", shifts_per_pay_period, help="Exact match required")
    with req_cols[1]:
        st.metric("Night Minimum", night_minimum, help="Minimum required (>=)")
    with req_cols[2]:
        st.metric("Weekend Minimum", weekend_minimum, help="Minimum required (>=)")
    with req_cols[3]:
        if weekend_group:
            st.metric("Weekend Group", weekend_group, help="Your assigned weekend group")
        else:
            st.metric("Weekend Group", "None", help="No weekend group assigned")
    
    # Check track source setting
    use_database_logic = st.session_state.get('track_source', "Annual Rebid") == "Annual Rebid"
    has_db_track = st.session_state.get('has_db_track', False)

    # Display track source info
    from ..track_source_consistency import display_for_track_modification
    display_for_track_modification(selected_staff)

    
    # Get track source information
    db_result = get_track_from_db(selected_staff)
    has_db_track = db_result[0]
    
    # Add banner for track status
    if is_new_track:
        st.info("🆕 Creating a new track. Start by selecting the days you want to work.")
    elif has_db_track:
        track_data = db_result[1]['track_data']
        submission_date = db_result[1]['submission_date']
        is_approved = db_result[1]['is_approved']
        version = db_result[1]['version']
        st.info(f"✏️ Modifying database track (version {version}, submitted on {submission_date}).")
    else:
        st.info("✏️ Modifying reference track from Excel file.")
    
    # Extract staff information
    staff_info = preferences_df[preferences_df[staff_col_prefs] == selected_staff].iloc[0]
    staff_role = staff_info[role_col]
    
    # Show role delta filter status if enabled
    if st.session_state.get('enable_role_delta_filter', False):
        effective_role = "nurse" if staff_role == "dual" else staff_role
        st.info(f"""
        🔍 **Role Delta Filter Enabled**
        - Day Shift Threshold: {st.session_state.get('day_delta_threshold', 3)}
        - Night Shift Threshold: {st.session_state.get('night_delta_threshold', 2)}
        - Staff Role: {staff_role} (treated as {effective_role} for needs calculation)
        """)
    
    # Pull shift capacity from database
    from ..db_utils import get_active_track_config, get_track_capacity
    _active_cfg = get_active_track_config()
    _active_tn = _active_cfg['track_name'] if _active_cfg else 'FY26'
    _cap = get_track_capacity(_active_tn)
    max_day_nurses = _cap['max_day_nurses']
    max_day_medics = _cap['max_day_medics']
    max_night_nurses = _cap['max_night_nurses']
    max_night_medics = _cap['max_night_medics']
    
    # Generate track modification options
    with st.spinner("Analyzing schedule needs and preferences..."):
        modification_results = calculate_all_modification_options(
            selected_staff, preferences_df, current_tracks_df, days,
            staff_col_prefs, staff_col_tracks, role_col, no_matrix_col,
            reduced_rest_col, seniority_col, max_day_nurses=max_day_nurses,
            max_day_medics=max_day_medics, max_night_nurses=max_night_nurses,
            max_night_medics=max_night_medics
        )
        
        options_by_day = modification_results["options_by_day"]
        day_assignments = modification_results["day_assignments"]
        night_assignments = modification_results["night_assignments"]
        assignment_details = modification_results["assignment_details"]
    
    # Set up reference track
    if use_database_logic:
        if has_db_track:
            reference_track = db_result[1]['track_data'].copy()
        else:
            reference_track = {day: staff_track.iloc[0][day] for day in days}
    else:
        reference_track = {day: staff_track.iloc[0][day] for day in days}
    
    # Initialize track changes
    if 'track_changes' not in st.session_state:
        st.session_state.track_changes = {}
        
    if selected_staff not in st.session_state.track_changes:
        if is_new_track or (use_database_logic and not has_db_track):
            track_data = {day: "" for day in days}
        else:
            track_data = reference_track.copy()
        
        # Add preassignments
        if preassignments:
            for day, preassignment in preassignments.items():
                if preassignment == "AT":
                    track_data[day] = "AT"
                else:
                    track_data[day] = "D"
        
        st.session_state.track_changes[selected_staff] = track_data
    
    # Initialize modified_track
    if 'modified_track' not in st.session_state:
        st.session_state.modified_track = {
            'staff': selected_staff,
            'track': st.session_state.track_changes[selected_staff].copy(),
            'valid': False,
            'is_new': is_new_track
        }
    elif st.session_state.modified_track.get('staff') != selected_staff:
        st.session_state.modified_track = {
            'staff': selected_staff,
            'track': st.session_state.track_changes[selected_staff].copy(),
            'valid': False,
            'is_new': is_new_track
        }
    
    # User guidance
    st.markdown("""
    ### How to Modify Your Track
    
    1. Select days/nights where you want to work by selecting D, N, or Off to remove the selection
    2. Use **"Validate Block"** buttons to save individual 2-week blocks
    3. Pre-assignments (AT, if any) are shown as selected and locked
    4. Days where your role is needed are highlighted in green — darker green means it's the highest ranked hypothetical shift based on your preferences
    5. **Weekend group days are highlighted in yellow** (if assigned to a weekend group)
    6. Go to the Submission tab when you're satisfied with your track
    7. **Note:** Hypothetical shifts are not guaranteed base assignments — your submitted track only designates a "D" or "N" for each day.
    """)
    
    # Show preassignments if any
    if preassignments:
        display_preassignments(selected_staff, preassignments)

    # CONTINUOUS VALIDATION - This runs automatically when track changes
    st.markdown("### 🎯 Validation Dashboard")
    
    from modules.track_source_consistency import display_for_validation
    display_for_validation()
    
    # Get current track for validation
    current_track = build_validation_track(selected_staff, days, preassignments)
    
    # Display comprehensive validation WITH weekend group information
    # This automatically updates whenever the user makes changes due to Streamlit's reactive nature
    is_valid = display_comprehensive_validation(
        current_track, days, shifts_per_pay_period, night_minimum, 
        weekend_minimum, preassignments, weekend_group, requirements_df, selected_staff
    )
    
    # Store validity in session state (this updates automatically)
    st.session_state.modified_track['valid'] = is_valid
    st.session_state.track_valid = is_valid
    
    # Display track modification interface WITH enhanced hypothetical scheduler display
    display_track_modification_interface_enhanced(
        selected_staff, options_by_day, reference_track, days, 
        preassignments, use_database_logic, has_db_track, staff_role, weekend_group,
        day_assignments, night_assignments, assignment_details
    )
    
    # Final validation with proper navigation and clear description
    st.markdown("### 📊 Final Track Validation")
    st.info("**Purpose:** This performs a comprehensive validation of your entire 6-week track against all requirements including pay periods, weekend groups, consecutive shifts, and rest requirements. Use this before going to the Submission tab.")
    
    if st.button("Validate Complete Track", key="final_validation", use_container_width=True, type="primary"):
        complete_track = build_validation_track(selected_staff, days, preassignments)
        final_valid = display_comprehensive_validation(
            complete_track, days, shifts_per_pay_period, night_minimum, 
            weekend_minimum, preassignments, weekend_group, requirements_df, selected_staff
        )
        
        st.session_state.modified_track['valid'] = final_valid
        st.session_state.track_valid = final_valid
        
        if final_valid:
            st.success("✅ Your track is valid! Go to the Submission tab to submit your changes.")
        else:
            st.error("Your track does not meet all requirements. Please review the issues above and make adjustments.")

def _need_indicator_style(rank, is_week_best=False):
    """
    Green background for a Day/Night Need indicator card, shaded in two tiers:
    - is_week_best marks the best rank actually available that week for that
      shift type (Day or Night), whatever it happens to be — a true rank 1 if
      one's available, otherwise whatever rank IS the best on offer (e.g. a
      3rd choice some week with no better option). That gets the top shade.
    - Everything else (a worse rank than the week's best, or no preference
      data at all) gets the lighter tint.
    """
    color = "#9de2ba" if is_week_best else "#d1fae5"
    return f"background-color: {color}; color: #000000; padding: 5px; border-radius: 3px; text-align: center;"


def _render_six_week_overview(selected_staff, days, reference_track, preassignments):
    """
    Compact 42-day overview spanning all three blocks in one table, shown below the
    Validate button on every block tab so the full track stays visible no matter
    which block is currently being edited, and updates live as selections change.
    A plain HTML table (not st.dataframe) so the column order is fixed and can't be
    dragged around; every day column is pinned to the same width. A thick divider
    marks the block boundaries without splitting the table into separate pieces.
    """
    col_w = 17
    label_w = 44

    def cell_value(day, is_reference):
        if is_reference:
            v = reference_track.get(day, "")
        else:
            is_preassigned = preassignments and day in preassignments
            if is_preassigned:
                return str(preassignments[day])
            v = st.session_state.track_changes[selected_staff].get(day, "")
        if pd.isna(v):
            v = ""
        return str(v)

    def cell_style(value, extra=""):
        base = (
            f"box-sizing: border-box; width: {col_w}px; min-width: {col_w}px; "
            f"max-width: {col_w}px; overflow: hidden; border: 1px solid #ddd; "
            "text-align: center; vertical-align: middle; font-size: 9px; "
            "padding: 3px 0; white-space: nowrap;"
        )
        if value == "D":
            base += " background-color: #d4edda;"
        elif value == "N":
            base += " background-color: #cce5ff;"
        elif value:
            base += " background-color: #e2e3e5; font-weight: bold;"
        return base + extra

    header_cell_base = (
        f"box-sizing: border-box; width: {col_w}px; min-width: {col_w}px; "
        f"max-width: {col_w}px; overflow: hidden; border: 1px solid #ddd; "
        "background-color: #f0f2f6; font-size: 7px; font-weight: 400; color: #666; "
        "text-align: center; vertical-align: middle;"
    )
    thick = " border-right: 2px solid #444;"

    weekday_header = ""
    tag_header = ""
    current_cells = ""
    proposed_cells = ""
    for i, day in enumerate(days):
        parts = day.split()
        weekday = parts[0] if parts else day
        tag = f"{parts[1]}{parts[2]}" if len(parts) == 3 else ""
        extra = thick if i in (13, 27) else ""

        weekday_header += f'<th style="{header_cell_base} padding: 3px 0;{extra}">{weekday}</th>'
        tag_header += f'<th style="{header_cell_base} padding: 2px 0;{extra}">{tag}</th>'

        ref_val = cell_value(day, True)
        prop_val = cell_value(day, False)
        current_cells += f'<td style="{cell_style(ref_val, extra)}">{ref_val}</td>'
        proposed_cells += f'<td style="{cell_style(prop_val, extra)}">{prop_val}</td>'

    label_style = (
        f"box-sizing: border-box; width: {label_w}px; border: 1px solid #ddd; "
        "background-color: #f0f2f6; font-weight: 500; font-size: 10px; "
        "text-align: center; vertical-align: middle; padding: 3px 2px; white-space: nowrap;"
    )
    label_header_style = label_style + " font-size: 7px; font-weight: 400;"
    table_width = label_w + col_w * len(days)

    st.markdown(f"""
    <div style="overflow-x: auto;">
    <table style="border-collapse: collapse; table-layout: fixed; width: {table_width}px;">
        <colgroup>
            <col style="width: {label_w}px;">
            {''.join(f'<col style="width: {col_w}px;">' for _ in days)}
        </colgroup>
        <thead>
            <tr><th style="{label_style}"></th>{weekday_header}</tr>
            <tr><th style="{label_header_style}"></th>{tag_header}</tr>
        </thead>
        <tbody>
            <tr><td style="{label_style}">Current</td>{current_cells}</tr>
            <tr><td style="{label_style}">Proposed</td>{proposed_cells}</tr>
        </tbody>
    </table>
    </div>
    """, unsafe_allow_html=True)


def display_track_modification_interface_enhanced(selected_staff, options_by_day, reference_track, days, preassignments, use_database_logic, has_db_track, staff_role, weekend_group=None, day_assignments=None, night_assignments=None, assignment_details=None):
    """
    UPDATED: Display the track modification interface with enhanced hypothetical scheduler display and fixed weekend group highlighting
    """
    
    # Get weekend group highlighting information with FIXED mapping
    weekend_highlight_info = get_weekend_group_highlighting_info_fixed(weekend_group, days)
    weekend_highlight_days = weekend_highlight_info.get('highlight_days', [])
    
    # Color legend - UPDATED to include weekend group highlighting  
    legend_items = [
        ('<span class="legend-box" style="background-color: #d4edda;"></span>', 'Day Shift'),
        ('<span class="legend-box" style="background-color: #cce5ff;"></span>', 'Night Shift'),
        ('<span class="legend-box" style="background-color: #e2e3e5;"></span>', 'Preassignment (Locked)'),
        ('<span class="legend-box" style="background-color: #9de2ba;"></span>', 'Best rank available this week'),
        ('<span class="legend-box" style="background-color: #d1fae5;"></span>', 'Lower rank / no preference data'),
        ('<span style="font-weight: bold">*</span>', 'No Preference Data')
    ]
    
    if not use_database_logic:
        legend_items.insert(-1, ('<span class="legend-box" style="background-color: #fff3cd;"></span>', 'Changed Assignment'))
    
    # NEW: Add weekend group highlighting to legend
    if weekend_group and weekend_highlight_days:
        legend_items.insert(-1, ('<span class="legend-box" style="background-color: #fff3cd; border: 2px solid #f0ad4e;"></span>', f'Weekend Group {weekend_group} Days'))
    
    legend_html = f"""
    <style>
    .legend-box {{
        display: inline-block;
        width: 20px;
        height: 20px;
        margin-right: 5px;
        border-radius: 3px;
    }}
    .legend-container {{
        display: flex;
        justify-content: center;
        margin-bottom: 20px;
        flex-wrap: wrap;
    }}
    .legend-item {{
        display: flex;
        align-items: center;
        margin-right: 20px;
        margin-bottom: 10px;
    }}
    </style>
    
    <div class="legend-container">
        {''.join([f'<div class="legend-item">{box}<span>{text}</span></div>' for box, text in legend_items])}
    </div>
    """
    
    st.markdown(legend_html, unsafe_allow_html=True)
    
    # Show weekend group information if available - FIXED formatting
    if weekend_group:
        st.info(f"🟡 **Weekend Group {weekend_group}:** Days highlighted in yellow are part of your weekend group requirements.")
    
    # Create tabs for blocks. Styled via a small injected script rather than CSS
    # scoped to st.container(key=...)'s generated class name — that class name's
    # exact format isn't guaranteed stable across Streamlit versions, and this app
    # only pins a wide range (see requirements.txt), so a selector tied to it can
    # silently stop matching on whatever version is actually deployed. Finding the
    # tabs by their own visible text and the standard role="tab" attribute instead
    # only depends on Streamlit continuing to render tabs accessibly, which is far
    # more stable than any particular version's internal class naming.
    blocks = ["A", "B", "C"]  # Use simple letters
    block_tabs = st.tabs([f"Block {block}" for block in blocks])
    components.html("""
    <script>
    (function() {
        var labels = ["Block A", "Block B", "Block C"];
        function styleBlockTabs() {
            try {
                var doc = window.parent.document;
                var tabs = doc.querySelectorAll('[role="tab"]');
                for (var i = 0; i < tabs.length; i++) {
                    var tab = tabs[i];
                    var text = (tab.textContent || "").trim();
                    if (labels.indexOf(text) === -1) continue;
                    tab.style.fontSize = "1.05rem";
                    tab.style.fontWeight = "700";
                    tab.style.padding = "10px 22px";
                    tab.style.height = "auto";
                    tab.style.borderRadius = "0.5rem";
                    tab.style.margin = "0 6px 6px 0";
                    if (tab.getAttribute("aria-selected") === "true") {
                        tab.style.border = "1px solid #ff4b4b";
                        tab.style.backgroundColor = "rgba(255, 75, 75, 0.06)";
                    } else {
                        tab.style.border = "1px solid rgba(49, 51, 63, 0.2)";
                        tab.style.backgroundColor = "";
                    }
                }
            } catch (e) {}
        }
        styleBlockTabs();
        var target = window.parent.document.body;
        if (target) {
            new MutationObserver(styleBlockTabs).observe(target, {childList: true, subtree: true});
        }
    })();
    </script>
    """, height=0)
    
    # Process each block
    days_per_block = 14
    for block_idx, block_tab in enumerate(block_tabs):
        with block_tab:
            start_idx = block_idx * days_per_block
            end_idx = min(start_idx + days_per_block, len(days))
            block_days = days[start_idx:end_idx]

            # Validate Block button, above Week 1 for this block
            validate_col1, validate_col2, validate_col3 = st.columns([1, 2, 1])
            with validate_col2:
                if st.button(f"🔍 Validate and Save Block {blocks[block_idx]}",
                           key=f"validate_block_{blocks[block_idx]}_{selected_staff}",
                           use_container_width=True):
                    # Validate just this block's portion of the track
                    block_track = build_validation_track(selected_staff, block_days, preassignments)
                    st.success(f"Block {blocks[block_idx]} validation complete! Check the dashboard above for results.")
                    if st.session_state.get('track_valid', False):
                        st.balloons()
            st.markdown("---")

            st.markdown("#### 6-Week Overview")
            # Reserve the spot here (right after the button) but fill it in after this
            # block's own week loop below has run — same reason as the per-week table's
            # placeholder: rendering before this block's radios are processed would read
            # session_state before their on-change updates were applied this run.
            overview_placeholder = st.empty()
            st.markdown("---")

            # Split into weeks
            for week_idx in range(2):
                week_start = week_idx * 7
                week_end = min(week_start + 7, len(block_days))
                
                if week_start >= len(block_days):
                    continue
                
                week_days = block_days[week_start:week_end]
                week_num = block_idx * 2 + week_idx + 1
                
                st.markdown(f"#### Week {week_num}")

                # Reserve the table's position here, above the radios, but don't render its
                # content until after the radio row below has run. Streamlit reruns the whole
                # script on every widget interaction; if the table read session_state before
                # the radios' on-change updates were applied (later in this same script run),
                # it would always show last run's values — a one-click-behind lag where the
                # Proposed Track row only catches up once you interact with something else.
                table_placeholder = st.empty()

                # Render the radios, Day Shifts boxes, and Night Shifts boxes as three
                # SEPARATE st.columns() rows rather than stacking all of it inside one
                # column per day. Each new st.columns() call starts a fresh row whose
                # columns all begin at the same Y position — so a day with 4 radio options
                # (e.g. an AT preassignment) or a wrapped label can never push that day's
                # boxes out of line with its neighbors, regardless of content height above.
                day_states = {}

                # --- Row 1: radio selectors ---
                radio_cols = st.columns([1.3] + [1] * len(week_days))
                with radio_cols[0]:
                    st.markdown("&nbsp;")

                for idx, day in enumerate(week_days):
                    with radio_cols[idx + 1]:
                        is_preassigned = preassignments and day in preassignments
                        is_weekend_group_day = day in weekend_highlight_days

                        # Compact label for the radio widget only (e.g. "Sun A1" instead of
                        # "Sun A 1") so it never wraps to a second line.
                        day_name_parts = day.split()
                        if len(day_name_parts) == 3:
                            compact_day_label = f"{day_name_parts[0]} {day_name_parts[1]}{day_name_parts[2]}"
                        else:
                            compact_day_label = day

                        if is_preassigned:
                            # Handle preassignments (existing logic)
                            preassign_value = preassignments[day]

                            radio_options = ["Off", "D", "N"]
                            if preassign_value == "AT":
                                radio_options = ["Off", "D", "N", "AT"]
                                selected_option = "AT"
                            elif preassign_value == "D":
                                selected_option = "D"
                            elif preassign_value == "N":
                                selected_option = "N"
                            else:
                                selected_option = "D"

                            try:
                                preselected_index = radio_options.index(selected_option)
                            except ValueError:
                                preselected_index = 0

                            # Disabled radio for preassignments
                            st.radio(
                                f"Select for {compact_day_label}",
                                options=radio_options,
                                index=preselected_index,
                                horizontal=False,
                                disabled=True,
                                key=f"select_preassign_{selected_staff}_{day}".replace(" ", "_").replace("/", "_")
                            )

                            # Force preassigned value
                            st.session_state.track_changes[selected_staff][day] = selected_option
                            st.session_state.modified_track['track'][day] = selected_option

                            day_states[day] = {
                                'has_options': True,
                                'is_preassigned': True,
                                'preassign_value': preassign_value,
                                'is_weekend_group_day': is_weekend_group_day,
                            }

                        else:
                            # Regular day selection with ENHANCED hypothetical scheduler display
                            reference_value = reference_track.get(day, "")
                            current_value = st.session_state.track_changes[selected_staff].get(day, "")

                            # Get availability info
                            day_info = options_by_day[day]
                            day_available = day_info["day_shift"]["is_needed"]
                            night_available = day_info["night_shift"]["is_needed"]

                            # Build options list using enhanced logic
                            available_options = build_available_options(
                                day_info, reference_value, current_value, use_database_logic
                            )

                            if not available_options:
                                st.markdown('''
                                <div style="background-color: #f8f9fa; padding: 10px; border-radius: 5px; text-align: center;">
                                    <strong>No shifts available</strong>
                                </div>
                                ''', unsafe_allow_html=True)
                                day_states[day] = {'has_options': False}
                                continue

                            # Default selection using enhanced logic
                            default_idx = get_default_selection_index(available_options, current_value)

                            # Create radio selector with unique key that causes automatic rerun when changed
                            selection = st.radio(
                                f"Select for {compact_day_label}",
                                options=available_options,
                                index=default_idx,
                                horizontal=False,
                                key=f"select_{selected_staff}_{day}".replace(" ", "_").replace("/", "_")
                            )

                            # Update track changes using enhanced logic
                            update_track_selection(selected_staff, day, selection, current_value)

                            day_states[day] = {
                                'has_options': True,
                                'is_preassigned': False,
                                'is_weekend_group_day': is_weekend_group_day,
                                'day_available': day_available,
                                'night_available': night_available,
                                'day_info': day_info,
                                'proposed_value': selection,
                            }

                # Build the Current/Proposed Track comparison as a plain HTML table rather
                # than st.dataframe: st.dataframe's grid lets a user drag-reorder columns
                # and auto-sizes them per column's content, so the day order and widths
                # could drift from one render to the next. A static table has neither
                # problem — column order is fixed in the markup and widths are fixed by
                # CSS (table-layout: fixed), the same on every tab, with long labels
                # ellipsized rather than pushing a column wider. Rendered now (after the
                # radios above have already updated session_state this run) into the
                # placeholder reserved earlier, so it reflects the latest selection
                # immediately instead of lagging a run behind.
                label_ratio = 1.3
                day_ratio = 1.0
                total_ratio = label_ratio + day_ratio * len(week_days)
                label_width_pct = 100 * label_ratio / total_ratio
                day_width_pct = 100 * day_ratio / total_ratio

                cell_base = (
                    "border: 1px solid #ddd; padding: 4px 2px; text-align: center; "
                    "white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
                )
                header_style = cell_base + " background-color: #f0f2f6; font-weight: bold; font-size: 0.8em;"
                label_cell_style = cell_base + " background-color: #f0f2f6; font-weight: bold; text-align: left; font-size: 0.85em;"

                def _row_value(day, is_reference):
                    if is_reference:
                        v = reference_track.get(day, "")
                        if pd.isna(v):
                            v = ""
                        return str(v) if v else "Off"
                    is_preassigned = preassignments and day in preassignments
                    if is_preassigned:
                        return f"Pre: {preassignments[day]}"
                    v = st.session_state.track_changes[selected_staff].get(day, "")
                    if pd.isna(v):
                        v = ""
                    return str(v) if v else "Off"

                def _cell_style(value):
                    if value == "D":
                        return "background-color: #d4edda;"
                    if value == "N":
                        return "background-color: #cce5ff;"
                    if "Pre:" in value:
                        return "background-color: #e2e3e5; font-weight: bold;"
                    return ""

                header_cells = "".join(
                    f'<th style="{header_style} width: {day_width_pct}%;">{day}</th>'
                    for day in week_days
                )

                reference_values = {day: _row_value(day, True) for day in week_days}
                proposed_values = {day: _row_value(day, False) for day in week_days}

                reference_cells = "".join(
                    f'<td style="{cell_base} width: {day_width_pct}%; {_cell_style(reference_values[day])}">{reference_values[day]}</td>'
                    for day in week_days
                )

                proposed_cells = ""
                for day in week_days:
                    ref_val = reference_values[day].replace("Off", "")
                    mod_val = proposed_values[day].replace("Off", "")
                    change_border = ""
                    if (not use_database_logic
                            and "Pre:" not in ref_val and "Pre:" not in mod_val
                            and ref_val != mod_val):
                        change_border = " border: 2px solid #ffc107;"
                    proposed_cells += (
                        f'<td style="{cell_base} width: {day_width_pct}%; '
                        f'{_cell_style(proposed_values[day])}{change_border}">{proposed_values[day]}</td>'
                    )

                table_placeholder.markdown(f"""
                <table style="width: 100%; table-layout: fixed; border-collapse: collapse;">
                    <colgroup>
                        <col style="width: {label_width_pct}%;">
                        {''.join(f'<col style="width: {day_width_pct}%;">' for _ in week_days)}
                    </colgroup>
                    <thead>
                        <tr><th style="{header_style} width: {label_width_pct}%;"></th>{header_cells}</tr>
                    </thead>
                    <tbody>
                        <tr><td style="{label_cell_style}">Current Track</td>{reference_cells}</tr>
                        <tr><td style="{label_cell_style}">Proposed Track</td>{proposed_cells}</tr>
                    </tbody>
                </table>
                """, unsafe_allow_html=True)

                # Best (lowest-numbered) preference rank actually available this week, for
                # Day and Night separately — so if no rank-1 shift is available at all, the
                # best rank that IS available (e.g. rank 3) still gets called out as the
                # standout option instead of every box looking equally unremarkable.
                best_day_rank = None
                best_night_rank = None
                for state in day_states.values():
                    if not state.get('has_options') or state.get('is_preassigned'):
                        continue
                    day_info = state['day_info']
                    if state['day_available']:
                        r = day_info["day_shift"].get("preference_score")
                        if r is not None and (best_day_rank is None or r < best_day_rank):
                            best_day_rank = r
                    if state['night_available']:
                        r = day_info["night_shift"].get("preference_score")
                        if r is not None and (best_night_rank is None or r < best_night_rank):
                            best_night_rank = r

                # --- Row 2: Day Shifts boxes (or the preassignment lock box) ---
                day_cols = st.columns([1.3] + [1] * len(week_days))
                with day_cols[0]:
                    st.markdown("""
                    <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 5px; border-radius: 3px; text-align: center;">
                        <strong>Day Shifts</strong>
                    </div>
                    """, unsafe_allow_html=True)

                for idx, day in enumerate(week_days):
                    with day_cols[idx + 1]:
                        state = day_states.get(day, {})
                        if not state.get('has_options'):
                            continue

                        is_weekend_group_day = state['is_weekend_group_day']

                        if state['is_preassigned']:
                            preassign_value = state['preassign_value']

                            preassign_style = "background-color: #e2e3e5; padding: 5px; border-radius: 3px; text-align: center;"
                            if is_weekend_group_day:
                                preassign_style = "background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center;"

                            weekend_display = f'🟡 Weekend Group {weekend_group}' if is_weekend_group_day else ""

                            st.markdown(f"""
                            <div style="{preassign_style}">
                                <strong>🔒 Preassigned: {preassign_value}</strong>
                                {weekend_display}
                            </div>
                            """, unsafe_allow_html=True)
                            continue

                        if not state['day_available']:
                            continue

                        day_info = state['day_info']

                        # Get enhanced information from hypothetical scheduler
                        day_needs_count = day_info["day_shift"].get("needs_count", 0)
                        day_pref = day_info["day_shift"].get("preference_score", None)
                        day_shift_name = ""

                        # Get hypothetical shift assignment if available
                        if day_assignments and day in day_assignments:
                            day_shift_name = day_assignments[day]

                        # Check if this is a Friday (day shifts on Friday don't count as weekend)
                        day_parts = day.split()
                        is_friday = len(day_parts) > 0 and day_parts[0] == "Fri"

                        # Don't highlight Friday day shifts yellow (only Friday nights count as weekend)
                        if is_weekend_group_day and not is_friday:
                            indicator_style = "background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center;"
                            weekend_indicator = f'Weekend Group {weekend_group}'
                        else:
                            is_week_best_day = day_pref is not None and day_pref == best_day_rank
                            indicator_style = _need_indicator_style(day_pref, is_week_best_day)
                            weekend_indicator = ''

                        # Black outline when this is what they've actually picked for
                        # their proposed track — a clear "this is your selection" marker
                        # independent of the rank shading.
                        if state.get('proposed_value') == 'D':
                            indicator_style += ' outline: 3px solid #000000; outline-offset: -1px;'

                        # If there is a need but no assignment, show asterisk and description
                        if day_needs_count > 0 and not day_shift_name:
                            day_shift_name = "* <span style='font-size:smaller;'>(Need exists but all named shifts are filled)</span>"

                        # UPDATED: Enhanced display with remaining needs and hypothetical scheduler results
                        day_star = ' ⭐' if day_pref == 1 else ''
                        pref_display = f'<br>Rank: {day_pref}{day_star}' if day_pref else ''
                        shift_display = f'<br>Hypothetical: {day_shift_name}' if day_shift_name else ''
                        weekend_display = f'🟡 {weekend_indicator}' if weekend_indicator else ''

                        st.markdown(f"""
                        <div style="{indicator_style}">
                            <strong>Day Need ({day_needs_count})</strong>
                            {shift_display}
                            {pref_display}
                            {weekend_display}
                        </div>
                        """, unsafe_allow_html=True)

                # Blank spacer row so the Day Shifts and Night Shifts boxes don't read as
                # one solid green block.
                st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

                # --- Row 3: Night Shifts boxes ---
                night_cols = st.columns([1.3] + [1] * len(week_days))
                with night_cols[0]:
                    st.markdown("""
                    <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 5px; border-radius: 3px; text-align: center;">
                        <strong>Night Shifts</strong>
                    </div>
                    """, unsafe_allow_html=True)

                for idx, day in enumerate(week_days):
                    with night_cols[idx + 1]:
                        state = day_states.get(day, {})
                        if not state.get('has_options') or state.get('is_preassigned'):
                            continue

                        is_weekend_group_day = state['is_weekend_group_day']
                        day_available = state['day_available']
                        night_available = state['night_available']

                        if night_available:
                            day_info = state['day_info']

                            # Get enhanced information from hypothetical scheduler
                            night_needs_count = day_info["night_shift"].get("needs_count", 0)
                            night_pref = day_info["night_shift"].get("preference_score", None)
                            night_shift_name = ""

                            # Get hypothetical shift assignment if available
                            if night_assignments and day in night_assignments:
                                night_shift_name = night_assignments[day]

                            # If there is a need but no assignment, show asterisk and description
                            if night_needs_count > 0 and not night_shift_name:
                                night_shift_name = "* <span style='font-size:smaller;'>(Need exists but all named shifts are filled)</span>"

                            # Night shifts always count as weekend (including Friday nights)
                            if is_weekend_group_day:
                                indicator_style = "background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center;"
                                weekend_indicator = f'Weekend Group {weekend_group}'
                            else:
                                is_week_best_night = night_pref is not None and night_pref == best_night_rank
                                indicator_style = _need_indicator_style(night_pref, is_week_best_night)
                                weekend_indicator = ''

                            # Black outline when this is what they've actually picked for
                            # their proposed track.
                            if state.get('proposed_value') == 'N':
                                indicator_style += ' outline: 3px solid #000000; outline-offset: -1px;'

                            # UPDATED: Enhanced display with remaining needs and hypothetical scheduler results
                            night_star = ' ⭐' if night_pref == 1 else ''
                            pref_display = f'<br>Rank: {night_pref}{night_star}' if night_pref else ''
                            shift_display = f'<br>Hypothetical: {night_shift_name}' if night_shift_name else ''
                            weekend_display = f'🟡 {weekend_indicator}' if weekend_indicator else ''

                            st.markdown(f"""
                            <div style="{indicator_style}">
                                <strong>Night Need ({night_needs_count})</strong>
                                {shift_display}
                                {pref_display}
                                {weekend_display}
                            </div>
                            """, unsafe_allow_html=True)

                        elif is_weekend_group_day and not day_available and not night_available:
                            # Show weekend group indicator even if no shifts are needed
                            day_parts = day.split()
                            is_friday = len(day_parts) > 0 and day_parts[0] == "Fri"

                            # Only show weekend group indicator for non-Friday days, or Friday with note about night shifts
                            if not is_friday:
                                st.markdown(f"""
                                <div style="background-color: #fff3cd; border: 2px solid #f0ad4e; padding: 5px; border-radius: 3px; text-align: center;">
                                    <strong>🟡 Weekend Group {weekend_group}</strong>
                                    <br>This day is part of your weekend requirements
                                </div>
                                """, unsafe_allow_html=True)
                            else:
                                st.markdown(f"""
                                <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 5px; border-radius: 3px; text-align: center;">
                                    <strong>Weekend Group {weekend_group}</strong>
                                    <br><small>Only Friday <em>night</em> shifts count as weekend</small>
                                </div>
                                """, unsafe_allow_html=True)

                st.markdown("---")  # Separator between weeks

            # Now that this block's own radios above have updated session_state this
            # run, fill in the overview placeholder reserved earlier with fresh data.
            with overview_placeholder.container():
                _render_six_week_overview(selected_staff, days, reference_track, preassignments)

def get_weekend_group_highlighting_info_fixed(weekend_group, days):
    """
    FIXED: Get information about which days should be highlighted for weekend group requirements
    This version properly handles Block A highlighting
    """
    if not weekend_group:
        return {'highlight_days': [], 'weekend_group': None}
    
    try:
        # Use fixed function to avoid import issues
        highlight_days = get_weekend_days_for_highlighting_fixed(weekend_group, days)
        
        return {
            'highlight_days': highlight_days,
            'weekend_group': weekend_group,
            'highlight_color': '#fff3cd',  # Light yellow
            'highlight_info': f"Weekend Group {weekend_group} required days"
        }
    except Exception as e:
        return {'highlight_days': [], 'weekend_group': weekend_group, 'error': str(e)}

def get_weekend_days_for_highlighting_fixed(weekend_group, days):
    """
    FIXED: Get weekend days that should be highlighted for a specific weekend group
    This version properly handles all blocks including Block A
    """
    if not weekend_group:
        return []
    
    # Weekend group definitions
    WEEKEND_GROUPS = {
        'A': {
            'periods': [
                ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
                ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 2
                ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 3
            ]
        },
        'B': {
            'periods': [
                ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
                ['Fri B 3', 'Sat B 3', 'Sun B 4'],  # Period 2
                ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 3
            ]
        },
        'C': {
            'periods': [
                ['Fri C 6', 'Sat C 6', 'Sun A 1'],  # Period 1
                ['Fri B 3', 'Sat B 3', 'Sun B 4']   # Period 2
            ]
        },
        'D': {
            'periods': [
                ['Fri A 1', 'Sat A 1', 'Sun A 2'],  # Period 1
                ['Fri B 4', 'Sat B 4', 'Sun C 5']   # Period 2
            ]
        },
        'E': {
            'periods': [
                ['Fri A 2', 'Sat A 2', 'Sun B 3'],  # Period 1
                ['Fri C 5', 'Sat C 5', 'Sun C 6']   # Period 2
            ]
        }
    }
    
    if weekend_group not in WEEKEND_GROUPS:
        return []
    
    # Get all weekend days for the group
    all_weekend_days = []
    for period in WEEKEND_GROUPS[weekend_group]['periods']:
        all_weekend_days.extend(period)
    
    # Map to actual schedule days with FIXED mapping logic
    highlight_days = []
    for weekend_day in all_weekend_days:
        schedule_day = map_weekend_day_to_schedule_day_fixed(weekend_day, days)
        if schedule_day:
            highlight_days.append(schedule_day)
    
    return highlight_days

def map_weekend_day_to_schedule_day_fixed(weekend_day, days):
    """
    FIXED: Map a weekend group day (e.g., 'Fri A 1') to actual schedule day
    This version properly handles Block A and all other blocks consistently
    """
    # Parse the weekend day format
    parts = weekend_day.split()
    if len(parts) != 3:
        return None
    
    day_name, block, week = parts
    
    # Find matching day in schedule with improved logic
    for schedule_day in days:
        schedule_parts = schedule_day.split()
        if len(schedule_parts) >= 3:  # Ensure we have day, block, and week
            schedule_day_name = schedule_parts[0]
            schedule_block = schedule_parts[1]
            schedule_week = schedule_parts[2]
            
            # Check if day names match (Fri, Sat, Sun)
            if schedule_day_name == day_name:
                # Check exact match first
                if schedule_block == block and schedule_week == week:
                    return schedule_day
        
        # Fallback: check if the schedule day contains both block and week
        # This handles different formatting conventions
        if day_name in schedule_day and block in schedule_day and week in schedule_day:
            # Make sure it's the right day of week
            if schedule_day.startswith(day_name):
                return schedule_day
    
    return None

def build_validation_track(selected_staff, days, preassignments=None):
    """Build complete track for validation"""
    # Initialize validation_track with empty values for all days
    validation_track = {day: "" for day in days}
    
    # Update with track changes if they exist
    if 'track_changes' in st.session_state and selected_staff in st.session_state.track_changes:
        validation_track.update(st.session_state.track_changes[selected_staff])
    
    # Ensure preassignments are included
    if preassignments:
        for day, preassign_value in preassignments.items():
            if preassign_value == "AT":
                validation_track[day] = "AT"
            elif preassign_value in ["D", "N"]:
                validation_track[day] = preassign_value
            else:
                validation_track[day] = "D"
    
    return validation_track

st.markdown("---")  # Add a separator at the end of the function

def build_available_options(day_info, reference_value, current_value, use_database_logic):
    """
    Build available options based on the enhanced logic for Off selection
    """
    available_options = []
    
    day_available = day_info["day_shift"]["is_needed"]
    night_available = day_info["night_shift"]["is_needed"]
    
    # ALWAYS include "Off" option - users should always be able to unselect their shift
    available_options.append("Off")
    
    # Add day shift if:
    # 1. Day shift is needed (has capacity) OR
    # 2. User currently has day shift assigned (can keep it)
    if day_available or current_value == "D":
        available_options.append("D")
    
    # Add night shift if:
    # 1. Night shift is needed (has capacity) OR  
    # 2. User currently has night shift assigned (can keep it)
    if night_available or current_value == "N":
        available_options.append("N")
    
    return available_options


def get_default_selection_index(available_options, current_value):
    """
    Get the default selection index for the radio buttons
    """
    if current_value in available_options:
        return available_options.index(current_value)
    else:
        # If current value not available, default to "Off" if available, otherwise first option
        if "Off" in available_options:
            return available_options.index("Off")
        else:
            return 0


def update_track_selection(selected_staff, day, selection, current_value):
    """
    Update track changes based on selection
    """
    if selection == "Off":
        # User selected Off - clear their assignment
        st.session_state.track_changes[selected_staff][day] = ""
        st.session_state.modified_track['track'][day] = ""
        st.session_state.modified_track['valid'] = False
        
    elif selection != current_value:
        # User selected a different shift
        st.session_state.track_changes[selected_staff][day] = selection
        st.session_state.modified_track['track'][day] = selection
        st.session_state.modified_track['valid'] = False


