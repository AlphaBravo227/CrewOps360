# training_modules/educator_admin_ui.py
"""
Educator Coverage - the education manager's workspace.

Everything about educators used to be spread across three screens: coverage numbers
were a tab inside Enrollment Reports, assigning an educator to a date meant going to
Manage Classes and scrolling past every student roster, and deciding *who is even
allowed* to teach meant leaving the training dashboard for the staff database. This
module is the one place all of it lives, so the education manager can read a gap and
close it without navigating away from the page that showed it.

The tabs are ordered the way the work runs: see the coverage, find the gaps, fill
them, then maintain the pool of people available to fill them.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

_eastern_tz = pytz.timezone('America/New_York')


def show_educator_coverage(admin):
    """Render the Educator Coverage section of the training admin dashboard.

    Args:
        admin: the AdminAccess instance, for its training-year context, its
            excel_admin_functions and the roster-row widgets it already owns.
    """
    st.subheader("👨‍🏫 Educator Coverage")

    excel_admin = getattr(admin, 'excel_admin_functions', None)
    if not excel_admin:
        st.error("Admin functions not initialized")
        return

    educator = getattr(excel_admin, 'educator', None)
    year = admin.current_training_year()

    if year:
        st.caption(
            f"Coverage, assignments and gaps for **{year}**. The authorised educator "
            f"roster on the *Educator Roster* tab is not year-scoped - it is the "
            f"standing staff roster and applies to every training year."
        )

    if not educator:
        st.warning(
            "Educator functionality is not available for this training year. "
            "Coverage and assignment need the educator manager, which is built "
            "from the year's roster workbook."
        )
        _educator_roster_tab(admin)
        return

    (tab_coverage, tab_gaps, tab_assign, tab_required,
     tab_roster, tab_people, tab_available) = st.tabs([
        "📊 Coverage",
        "🚨 Gaps",
        "✏️ Assign Educators",
        "🎚️ Educators Required",
        "👤 Educator Roster",
        "👥 Participation",
        "🗓️ Available to Teach",
    ])

    with tab_coverage:
        _coverage_tab(admin, excel_admin, year)
    with tab_gaps:
        _gaps_tab(admin, excel_admin, year)
    with tab_assign:
        _assign_tab(admin, excel_admin, educator, year)
    with tab_required:
        _requirements_tab(admin, excel_admin, educator, year)
    with tab_roster:
        _educator_roster_tab(admin)
    with tab_people:
        _participation_tab(admin, excel_admin, educator, year)
    with tab_available:
        _available_to_teach_tab(admin, excel_admin)


# ============================================================================
# COVERAGE
# ============================================================================

def _coverage_tab(admin, excel_admin, year):
    """Coverage rate per class/date - moved here from Enrollment Reports."""
    st.write("### 📊 Educator Coverage Analysis")
    st.caption("How well each class date is covered against the educators it requires.")

    from .admin_excel_functions import date_column_config, sortable_dates, year_filename_prefix

    try:
        coverage_df = excel_admin.get_educator_coverage_report()
    except Exception as e:
        st.error(f"Error generating the coverage report: {e}")
        return

    if coverage_df.empty:
        st.info("No educator data available - no classes require educators.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        fully_covered = len(coverage_df[coverage_df['Status'] == '✅ Fully Covered'])
        st.metric("Fully Covered", fully_covered)
    with col2:
        st.metric("Total Positions Needed", int(coverage_df['Still Needed'].sum()))
    with col3:
        critical_classes = len(coverage_df[coverage_df['Status'] == '❌ No Coverage'])
        st.metric("Classes w/o Educators", critical_classes)
    with col4:
        try:
            avg_coverage = coverage_df['Coverage Rate'].str.rstrip('%').astype(float).mean()
            st.metric("Avg Coverage", f"{avg_coverage:.1f}%")
        except (AttributeError, ValueError):
            st.metric("Avg Coverage", "n/a")

    # Reading the whole year at once is what the coverage table is for, but during a
    # busy month the only rows that matter are the ones that are not yet covered.
    status_options = ["All"] + sorted(coverage_df['Status'].dropna().unique().tolist())
    chosen_status = st.selectbox("Filter by coverage status:", status_options,
                                 key="educator_coverage_status_filter")
    display_df = (coverage_df if chosen_status == "All"
                  else coverage_df[coverage_df['Status'] == chosen_status])

    st.write("#### Coverage by Class / Date")
    if display_df.empty:
        st.info("No class dates with that status.")
    else:
        st.dataframe(
            sortable_dates(display_df, ['Date']),
            use_container_width=True,
            column_config=date_column_config(['Date']),
        )
        st.caption(f"{len(display_df)} of {len(coverage_df)} class dates shown.")

    st.download_button(
        "📥 Download coverage report (CSV)",
        coverage_df.to_csv(index=False),
        f"{year_filename_prefix(year)}educator_coverage_"
        f"{datetime.now(_eastern_tz).strftime('%Y%m%d')}.csv",
        "text/csv",
        key="educator_coverage_download",
    )


# ============================================================================
# GAPS
# ============================================================================

def _gaps_tab(admin, excel_admin, year):
    """The class dates still short of educators, worst first."""
    st.write("### 🚨 Classes Still Needing Educators")
    st.caption("Every class date that has fewer educators signed up than it requires.")

    from .admin_excel_functions import date_column_config, sortable_dates, year_filename_prefix

    try:
        needs_df = excel_admin.get_classes_needing_educators_report()
    except Exception as e:
        st.error(f"Error generating the gap report: {e}")
        return

    if needs_df.empty:
        st.success("✅ All educator positions are filled.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Class dates short", len(needs_df))
    with col2:
        st.metric("Positions to fill", int(needs_df['Still Needed'].sum()))
    with col3:
        # An uncovered date is only urgent while there is still time to staff it;
        # the report's own urgency column already encodes that.
        if 'Urgency' in needs_df.columns:
            urgent = needs_df['Urgency'].astype(str).str.contains('🔴|High|Urgent',
                                                                  case=False, na=False).sum()
            st.metric("Urgent", int(urgent))
        else:
            st.metric("Classes affected", needs_df['Class Name'].nunique())

    st.dataframe(
        sortable_dates(needs_df, ['Date']),
        use_container_width=True,
        column_config=date_column_config(['Date']),
    )

    st.info("Fill any of these on the **✏️ Assign Educators** tab without leaving this page.")

    st.download_button(
        "📥 Download gap report (CSV)",
        needs_df.to_csv(index=False),
        f"{year_filename_prefix(year)}educator_needs_"
        f"{datetime.now(_eastern_tz).strftime('%Y%m%d')}.csv",
        "text/csv",
        key="educator_needs_download",
    )


# ============================================================================
# ASSIGN
# ============================================================================

def _assign_tab(admin, excel_admin, educator, year):
    """Add and remove educators for a class date, without the student rosters.

    Manage Classes can already do this, but only underneath every student on the
    session. This view shows classes that require educators and nothing else.
    """
    st.write("### ✏️ Assign Educators")
    st.caption("Add or remove educators for any class date that requires instruction.")

    # A read-only or draft year refuses every write at the database, which an admin
    # only found out after filling in the form and submitting it. Say it up front.
    unified_db = st.session_state.get('unified_db')
    if unified_db and year and not unified_db.is_training_year_writable(year):
        row = admin._training_year_row(year) or {}
        st.warning(
            f"⚠️ **{year} is {row.get('status') or 'not open'}.** Assignments below are "
            f"read-only: adding and removing will be refused. Set the year to Open in "
            f"Training Admin → Training Years to edit it."
        )

    if not st.session_state.get('training_educator_manager'):
        st.error("The educator manager is not loaded in this session.")
        return

    try:
        opportunities = educator.get_educator_opportunities()
    except Exception as e:
        st.error(f"Could not read the classes requiring educators: {e}")
        return

    if not opportunities:
        st.info("No classes in this training year require educators.")
        return

    by_class = {opportunity['class_name']: opportunity for opportunity in opportunities}

    col_class, col_filter = st.columns([3, 2])
    with col_class:
        selected_class = st.selectbox(
            "Class:", [""] + sorted(by_class.keys()),
            key="educator_assign_class",
        )
    with col_filter:
        only_gaps = st.checkbox(
            "Only dates still needing educators", value=True,
            key="educator_assign_only_gaps",
            help="Uncheck to see every date for this class, including fully covered ones.",
        )

    if not selected_class:
        st.info("Pick a class to see its dates and educator assignments.")
        return

    opportunity = by_class[selected_class]
    required = opportunity['instructor_count']
    st.markdown(
        f"**{selected_class}** — requires **{required}** educator"
        f"{'s' if required != 1 else ''} per day"
        + (" · two-day class, educators sign up per day" if opportunity['is_two_day'] else "")
    )
    st.markdown("---")

    educator_manager = st.session_state.training_educator_manager
    shown = 0

    for class_date in opportunity['available_dates']:
        signups = educator_manager.db.get_educator_signups_for_class(
            selected_class, class_date, training_year=educator_manager.training_year
        )
        active = [s for s in signups if s.get('status', 'active') == 'active']
        still_needed = max(required - len(active), 0)

        if only_gaps and still_needed == 0:
            continue
        shown += 1

        marker = "✅" if still_needed == 0 else ("⚠️" if active else "❌")
        label = (f"{marker} {class_date} — {len(active)}/{required} educator"
                 f"{'s' if required != 1 else ''}")

        with st.expander(label, expanded=(shown == 1 and still_needed > 0)):
            if active:
                for signup in active:
                    admin._display_educator_row_with_remove(signup)
            else:
                st.info("No educators signed up for this date.")

            st.markdown("---")
            st.markdown("**➕ Add an educator**")
            _add_educator_form(admin, selected_class, class_date,
                               already_signed_up={s['staff_name'] for s in active})

    if shown == 0:
        st.success("✅ Every date for this class is fully covered.")


def _add_educator_form(admin, class_name, class_date, already_signed_up=frozenset()):
    """Sign one educator up for exactly the date this expander is showing.

    Deliberately not Manage Classes' add-educator form: that one re-derives Day 1 and
    Day 2 from whatever date it is handed and asks which to book, which is right when
    the caller only knows a session's anchor date. Here the loop has already expanded
    a two-day class into one expander per day, so the day is not in question - and
    re-deriving it from a Day 2 expander would book Day 2 *plus the day after it*.
    """
    educator_manager = st.session_state.training_educator_manager

    # The authorised pool first, because that is who is meant to be teaching. Anyone
    # else needs the deliberate act of switching the list over.
    try:
        from modules import staff_database as staffdb
        authorised = sorted(staffdb.get_educator_names())
    except Exception:
        authorised = []

    all_staff = sorted(admin.excel_admin_functions.excel.get_staff_list() or [])
    if not all_staff and not authorised:
        st.warning("No staff found to assign.")
        return

    form_key = f"assign_educator_{class_name}_{class_date}".replace(" ", "_").replace("/", "_")

    show_all = st.checkbox(
        "Show all staff, not just authorised educators",
        value=not authorised,
        key=f"{form_key}_show_all",
        help="Staff without the Educator AT flag can still be assigned here, but "
             "authorising them on the Educator Roster tab keeps the roster honest.",
    )

    if show_all:
        pool = all_staff or authorised
    else:
        # Only authorised staff who are actually on this training year's roster. The
        # two lists come from different places - the staff database and the year's
        # workbook - and their spellings can differ in case, so match on that basis.
        workbook_names = {name.strip().lower() for name in all_staff}
        pool = [name for name in authorised
                if not workbook_names or name.strip().lower() in workbook_names]

    candidates = [name for name in pool if name not in already_signed_up]

    if not candidates:
        st.info("Everyone in this pool is already signed up for this date."
                if pool else "No authorised educators available - tick the box above "
                             "to pick from the whole roster.")
        return

    with st.form(key=form_key):
        selected_staff = st.selectbox("Educator", [""] + candidates,
                                      key=f"{form_key}_staff")
        submitted = st.form_submit_button(f"➕ Add to {class_date}")

    if submitted:
        if not selected_staff:
            st.error("Pick a staff member first.")
            return

        result = educator_manager.signup_as_educator(
            staff_name=selected_staff,
            class_name=class_name,
            class_date=class_date,
            override_conflict=True,   # an admin assigning cover overrides both
            override_capacity=True,
        )

        if isinstance(result, tuple):
            success, message = result
            if success:
                st.success(f"Added {selected_staff} as educator for {class_date}.")
                st.rerun()
            else:
                st.error(f"Could not add {selected_staff}: {message}")
        else:
            st.error("Unexpected response from the educator system.")


# ============================================================================
# EDUCATORS REQUIRED
# ============================================================================

def _requirements_tab(admin, excel_admin, educator, year):
    """How many educators each class needs per day, editable here.

    The number lives on the class, next to seat counts and time slots, and Build
    Classes is still where a class is created with it. But it is the education
    manager reading the coverage tab who discovers a class was built needing two
    educators when it really needs three, and sending them into the full class editor
    to change one number means walking past every date, location and assignment on
    the way. This edits that one column and nothing else.
    """
    st.write("### 🎚️ Educators Required per Class")
    st.caption(
        "How many educators each class needs on each of its dates. This is what puts "
        "a class on the educator signup list at all - zero means it takes no "
        "educators. Everything on the Coverage and Gaps tabs is measured against it."
    )

    from . import class_catalog as catalog

    handler = st.session_state.get('training_excel_handler')
    if handler is None or not hasattr(handler, 'db_path'):
        st.error(
            "The class catalog is not loaded in this session, so requirements cannot "
            "be edited here. Use Training Admin → Build Classes instead."
        )
        return

    catalog_year = getattr(handler, 'training_year', None) or year
    if not catalog_year:
        st.error("No training year is selected, so there are no classes to configure.")
        return

    try:
        all_classes = excel_admin.excel.get_all_classes()
    except Exception as e:
        st.error(f"Could not list this year's classes: {e}")
        return

    if not all_classes:
        st.info(f"{catalog_year} has no classes yet. Build them under "
                f"Training Admin → Build Classes.")
        return

    rows = _requirement_rows(excel_admin, educator, all_classes)
    if not rows:
        st.info("No class details could be read for this year.")
        return

    show_all = st.checkbox(
        "Show classes that take no educators", value=False,
        key="educator_requirements_show_all",
        help="Classes set to zero are off the educator signup list entirely. Show "
             "them to put a class onto it.",
    )
    visible = rows if show_all else [r for r in rows if r['Required'] > 0]

    if not visible:
        st.info("No class in this year requires educators yet. Tick the box above to "
                "give one a requirement.")
        return

    table = pd.DataFrame([{
        'Class': r['Class'],
        'Required': r['Required'],
        'Dates': r['Dates'],
        'Most signed up on a date': r['Peak'],
        'Positions per year': r['Required'] * r['Dates'],
    } for r in visible])

    edited = st.data_editor(
        table,
        use_container_width=True,
        hide_index=True,
        key="educator_requirements_editor",
        disabled=['Class', 'Dates', 'Most signed up on a date', 'Positions per year'],
        column_config={
            'Required': st.column_config.NumberColumn(
                "Required per day", min_value=0, max_value=20, step=1,
                help="Educators needed on each date of this class. Zero takes it off "
                     "the educator signup list.",
            ),
            'Most signed up on a date': st.column_config.NumberColumn(
                help="The busiest date's current signups. Setting the requirement "
                     "below this leaves that date over-staffed - nobody is removed.",
            ),
            'Positions per year': st.column_config.NumberColumn(
                help="Requirement × dates: how many educator slots this class asks "
                     "for across the whole year.",
            ),
        },
    )

    original = {r['Class']: r['Required'] for r in visible}
    peaks = {r['Class']: r['Peak'] for r in visible}
    changes = {}
    for class_name, required in zip(edited['Class'], edited['Required']):
        try:
            new_value = int(required)
        except (TypeError, ValueError):
            continue
        if new_value != original.get(class_name):
            changes[class_name] = new_value

    if changes:
        _preview_requirement_changes(changes, original, peaks)

    if st.button("💾 Save requirements", type="primary", disabled=not changes,
                 use_container_width=False, key="educator_requirements_save"):
        _save_requirements(catalog, catalog_year, handler, changes)


def _requirement_rows(excel_admin, educator, all_classes):
    """Current requirement, date count and busiest date's signups, per class."""
    try:
        opportunities = {o['class_name']: o for o in educator.get_educator_opportunities()}
    except Exception:
        opportunities = {}

    rows = []
    for class_name in all_classes:
        try:
            class_details = excel_admin.excel.get_class_details(class_name)
        except Exception:
            class_details = None
        if not class_details:
            continue

        try:
            required = int(float(class_details.get('instructors_per_day') or 0))
        except (TypeError, ValueError):
            required = 0

        # Two-day classes are counted the way educators actually sign up for them -
        # per day - so "positions per year" matches what the coverage table shows.
        opportunity = opportunities.get(class_name)
        if opportunity:
            dates = opportunity['available_dates']
        else:
            try:
                dates = excel_admin.excel.get_class_dates(class_name) or []
            except Exception:
                dates = []

        rows.append({
            'Class': class_name,
            'Required': required,
            'Dates': len(dates),
            'Peak': _peak_signups(educator, class_name, dates),
        })

    rows.sort(key=lambda r: (-r['Required'], r['Class'].lower()))
    return rows


def _peak_signups(educator, class_name, dates):
    """The most educators signed up on any one date of this class."""
    peak = 0
    for class_date in dates:
        try:
            count = educator.db.get_educator_signup_count(
                class_name, class_date, training_year=educator.training_year)
        except Exception:
            continue
        peak = max(peak, count or 0)
    return peak


def _preview_requirement_changes(changes, original, peaks):
    """Say what saving would do, including the two ways it can strand signups."""
    lines = []
    stranding = []
    removing = []

    for class_name, new_value in sorted(changes.items()):
        was = original.get(class_name, 0)
        lines.append(f"**{class_name}**: {was} → {new_value} per day")
        if new_value == 0 and peaks.get(class_name, 0) > 0:
            removing.append(class_name)
        elif new_value < peaks.get(class_name, 0):
            stranding.append(f"{class_name} (a date has {peaks[class_name]})")

    st.info("Pending changes:\n\n" + "\n\n".join(f"- {line}" for line in lines))

    if removing:
        st.warning(
            "⚠️ Setting the requirement to zero takes these classes off the educator "
            "signup list, but does **not** cancel the signups already on them: "
            + ", ".join(removing) + ". Cancel those on the ✏️ Assign Educators tab "
            "first if they should not stand."
        )
    if stranding:
        st.warning(
            "⚠️ These end up below what is already signed up on their busiest date, "
            "so that date reads as over-staffed until someone is removed: "
            + ", ".join(stranding) + "."
        )


def _save_requirements(catalog, catalog_year, handler, changes):
    """Write the changed requirements, then drop the catalog's cached details."""
    saved, failures = 0, []

    for class_name, new_value in changes.items():
        try:
            catalog.set_instructors_per_day(catalog_year, class_name, new_value,
                                            db_path=handler.db_path)
            saved += 1
        except Exception as e:
            failures.append(f"{class_name}: {e}")

    # The catalog caches a class's details for the render it read them in, and every
    # coverage number on this page is computed from that copy. Without this the tab
    # would go on reporting the requirement the class used to have.
    if saved and hasattr(handler, 'invalidate'):
        handler.invalidate()

    if failures:
        st.error("Some requirements were not saved:\n\n"
                 + "\n\n".join(f"- {failure}" for failure in failures))
    if saved and not failures:
        st.success(f"Updated {saved} class{'es' if saved != 1 else ''}.")
        st.rerun()
    elif saved:
        st.info(f"{saved} of {len(changes)} saved.")


# ============================================================================
# EDUCATOR ROSTER
# ============================================================================

def _educator_roster_tab(admin):
    """Who is authorised to teach - the 'Educator AT' flag, editable here.

    This lives in the staff database, one admin area away from the training
    dashboard. Editing it here means the education manager who just found a gap can
    authorise someone to fill it without losing the page they were on.
    """
    st.write("### 👤 Authorised Educator Roster")
    st.caption(
        "Staff marked **Educator AT** may sign up to teach. This is the standing "
        "staff roster, shared by every training year - a change here applies "
        "everywhere, including the Staff Database admin page."
    )

    try:
        from modules import staff_database as staffdb
    except ImportError as e:
        st.error(f"Could not load the staff database module: {e}")
        return

    if not staffdb.staff_table_exists() or staffdb.staff_count() == 0:
        st.warning(
            "The staff roster has not been imported yet. Import it under "
            "**Staff Database → Import** before authorising educators here."
        )
        return

    _flag_unauthorized_signups(staffdb)

    col_search, col_show, col_inactive = st.columns([2, 2, 1])
    with col_search:
        search = st.text_input("Search by name", key="educator_roster_search",
                               placeholder="Start typing a name…")
    with col_show:
        view = st.radio(
            "Show", ["Authorised educators", "Whole roster"],
            key="educator_roster_view", horizontal=True,
            help="Switch to the whole roster to authorise someone new.",
        )
    with col_inactive:
        include_inactive = st.checkbox("Include inactive", value=False,
                                       key="educator_roster_inactive")

    records = staffdb.get_all_staff(include_inactive=include_inactive)
    if view == "Authorised educators":
        records = [r for r in records if r['is_educator_at']]
    if search:
        needle = search.strip().lower()
        records = [r for r in records if needle in r['staff_name'].lower()]

    authorised_total = len([r for r in staffdb.get_all_staff(include_inactive=include_inactive)
                            if r['is_educator_at']])
    st.metric("Authorised educators", authorised_total)

    if not records:
        st.info("No staff match these filters.")
        return

    table = pd.DataFrame([{
        'Educator AT': bool(r['is_educator_at']),
        'Staff Name': r['staff_name'],
        'Role': r['role'],
        'MGMT': bool(r['is_management']),
        'Active': bool(r['is_active']),
    } for r in records])

    # Edited in place rather than one form per person: authorising a handful of staff
    # after reading a gap report is one action, not six round trips.
    edited = st.data_editor(
        table,
        use_container_width=True,
        hide_index=True,
        key="educator_roster_editor",
        disabled=['Staff Name', 'Role', 'MGMT', 'Active'],
        column_config={
            'Educator AT': st.column_config.CheckboxColumn(
                "Educator AT",
                help="Tick to let this staff member sign up to teach.",
            ),
        },
    )

    original = dict(zip(table['Staff Name'], table['Educator AT']))
    changes = {
        name: bool(flag)
        for name, flag in zip(edited['Staff Name'], edited['Educator AT'])
        if bool(flag) != bool(original.get(name))
    }

    if changes:
        added = sorted(name for name, flag in changes.items() if flag)
        removed = sorted(name for name, flag in changes.items() if not flag)
        summary = []
        if added:
            summary.append(f"authorise {len(added)} ({', '.join(added)})")
        if removed:
            summary.append(f"remove authorisation from {len(removed)} ({', '.join(removed)})")
        st.info("Pending: " + "; ".join(summary))

    save_col, note_col = st.columns([1, 3])
    with save_col:
        save = st.button("💾 Save changes", type="primary", disabled=not changes,
                         use_container_width=True, key="educator_roster_save")
    with note_col:
        if removed_with_signups := _authorised_removals_with_signups(changes):
            st.warning(
                "Removing authorisation does not cancel existing signups. Still signed "
                "up to teach: " + ", ".join(sorted(removed_with_signups)) + "."
            )

    if save:
        failures = []
        for name, flag in changes.items():
            ok, message = staffdb.update_staff(name, changed_by='training_admin',
                                               is_educator_at=flag)
            if not ok:
                failures.append(f"{name}: {message}")
        if failures:
            st.error("Some changes were not saved:\n\n" + "\n\n".join(failures))
        else:
            st.success(f"Saved {len(changes)} roster change"
                       f"{'s' if len(changes) != 1 else ''}.")
            st.rerun()


def _flag_unauthorized_signups(staffdb):
    """Educators with active signups who are not marked Educator AT.

    A staff member can be un-authorised after signing up, or be signed up by an admin
    override. Either way the roster and the schedule disagree, and the education
    manager is the one who has to decide which is right.
    """
    educator_manager = st.session_state.get('training_educator_manager')
    unified_db = st.session_state.get('unified_db')
    if not educator_manager or not unified_db:
        return

    try:
        _, signups = unified_db.get_year_export_rows(educator_manager.training_year)
    except Exception:
        return

    authorised = {name.strip().lower() for name in staffdb.get_educator_names(include_inactive=True)}
    unauthorised = sorted({
        signup['staff_name'] for signup in signups
        if signup.get('staff_name')
        and signup['staff_name'].strip().lower() not in authorised
    })

    if unauthorised:
        st.warning(
            f"⚠️ {len(unauthorised)} staff have active educator signups but are not "
            f"marked Educator AT: {', '.join(unauthorised)}. Authorise them below, or "
            f"remove the signup on the **✏️ Assign Educators** tab."
        )


def _authorised_removals_with_signups(changes):
    """Names losing authorisation who still hold active educator signups."""
    losing = {name for name, flag in changes.items() if not flag}
    if not losing:
        return set()

    educator_manager = st.session_state.get('training_educator_manager')
    unified_db = st.session_state.get('unified_db')
    if not educator_manager or not unified_db:
        return set()

    try:
        _, signups = unified_db.get_year_export_rows(educator_manager.training_year)
    except Exception:
        return set()

    signed_up = {signup['staff_name'] for signup in signups if signup.get('staff_name')}
    return losing & signed_up


# ============================================================================
# PARTICIPATION
# ============================================================================

def _participation_tab(admin, excel_admin, educator, year):
    """Who is teaching, how much, and who is not teaching at all."""
    st.write("### 👥 Individual Educator Participation")
    st.caption("Teaching load per educator across the training year.")

    from .admin_excel_functions import year_filename_prefix

    try:
        participation_df = excel_admin.get_educator_participation_report()
    except Exception as e:
        st.error(f"Error generating the participation report: {e}")
        return

    if participation_df.empty:
        st.info("No educator signups found for this training year.")
        return

    # The column holding the signup count varies with how the report was built, so
    # find it rather than assuming a name - an unbalanced load is the whole point of
    # this table and a KeyError here would hide it.
    count_column = next(
        (col for col in participation_df.columns
         if 'signup' in col.lower() or 'classes' in col.lower() or 'total' in col.lower()),
        None,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Educators listed", len(participation_df))
    if count_column:
        counts = pd.to_numeric(participation_df[count_column], errors='coerce').fillna(0)
        with col2:
            st.metric("Total signups", int(counts.sum()))
        with col3:
            teaching = int((counts > 0).sum())
            st.metric("Actively teaching", teaching)

        if st.checkbox("Hide educators with no signups", value=False,
                       key="educator_participation_hide_zero"):
            participation_df = participation_df[counts > 0]

    st.dataframe(participation_df, use_container_width=True)

    st.download_button(
        "📥 Download participation report (CSV)",
        participation_df.to_csv(index=False),
        f"{year_filename_prefix(year)}educator_participation_"
        f"{datetime.now(_eastern_tz).strftime('%Y%m%d')}.csv",
        "text/csv",
        key="educator_participation_download",
    )


# ============================================================================
# AVAILABLE TO TEACH (placeholder - the logic lands here)
# ============================================================================

def _available_to_teach_tab(admin, excel_admin):
    """Which authorised educators are free to teach a given class date.

    Not implemented yet - the availability rules are still being decided. This tab is
    where they land, and it sits next to the coverage and gap views the answer feeds,
    so filling a gap and finding someone to fill it with are the same screen.
    """
    st.write("### 🗓️ Available Educators for Teaching")
    st.caption("Which authorised educators are free to teach the dates that need cover.")

    st.info("🚧 **Coming soon** — the availability logic for this tab is still being defined.")

    st.markdown("""
    **What this tab will answer:**

    - Which staff marked **Educator AT** are free on each date that still needs cover
    - Who is already committed that day, as a student or as an educator elsewhere
    - How the teaching load is spread across the authorised pool
    - Which gaps have no eligible educator at all, so they need a different fix
    """)

    st.markdown("---")
    st.markdown("#### 📚 Classes requiring educators")
    st.caption("The set of classes the availability engine will run against.")

    try:
        all_classes = excel_admin.excel.get_all_classes()
        educator_classes = []

        for class_name in all_classes:
            class_details = excel_admin.excel.get_class_details(class_name)
            if not class_details:
                continue

            instructor_count = class_details.get('instructors_per_day', 0)
            try:
                instructor_count = int(float(instructor_count)) if instructor_count else 0
            except (ValueError, TypeError):
                instructor_count = 0

            if instructor_count > 0:
                educator_classes.append({
                    'Class Name': class_name,
                    'Educators Needed': instructor_count,
                    'Two-day': 'Yes' if str(class_details.get('is_two_day_class', 'No')).lower() == 'yes' else 'No',
                    'Class Type': 'Staff Meeting' if 'SM' in class_name.upper() else 'Training',
                })

        if educator_classes:
            st.dataframe(pd.DataFrame(educator_classes), use_container_width=True,
                         hide_index=True)
            st.caption(f"{len(educator_classes)} classes require educators.")
        else:
            st.info("No classes in this training year are configured to require educators.")

    except Exception as e:
        st.error(f"Error loading educator class information: {e}")
