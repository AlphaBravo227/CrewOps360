# modules/duty_board_ui.py
"""
Duty Schedule admin — the screen that replaces `Active 2-Week Template`.

Four tabs, in the order a scheduler works:

- **Board** — the vehicle-by-date grid, coloured by whether each is crewed, over the
  counter block and a staff grid. This is the sheet's top display, with its reasoning
  visible instead of encoded in a digit sum.
- **Assign** — one date at a time: who is on a day shift, who is on a night, and what
  is still uncrewed. Filtering to the people actually available is the thing the
  spreadsheet could never do, and the reason this is worth having.
- **Vehicles** — the inventory and its priority order.
- **Pairs** — who may not crew together.

Nothing here chooses an assignment. A scheduler does, and later an algorithm will;
this screen's job is to make the consequences of each choice visible as it is made.
"""

import io
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from . import duty_board, duty_crew
from . import duty_schedule_db as ddb
from .security import require_admin

_STATE_START = 'duty_board_start'
_STATE_DATE = 'duty_board_focus_date'


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _fmt(iso, with_weekday=True):
    """
    'Sun 11 Oct' — the sheet's own column heading.

    Built from the parts rather than with strftime's %-d, which is not portable:
    this app runs on Windows, where that format raises.
    """
    day = datetime.strptime(iso, '%Y-%m-%d')
    stamp = f"{day.day} {day.strftime('%b')}"
    return f"{day.strftime('%a')} {stamp}" if with_weekday else stamp


def _default_start():
    """
    The Sunday on or before today.

    A block runs Sunday to Saturday twice over, so offering anything else as a start
    would put the pay period out of step from the first screen.
    """
    today = datetime.now()
    return (today - timedelta(days=(today.weekday() + 1) % 7)).strftime('%Y-%m-%d')


def _current_start():
    if _STATE_START not in st.session_state:
        st.session_state[_STATE_START] = _default_start()
    return st.session_state[_STATE_START]


def _chip(text, bg, fg, title=''):
    tooltip = f' title="{title}"' if title else ''
    return (f'<span{tooltip} style="background:{bg};color:{fg};padding:2px 7px;'
            f'border-radius:4px;font-size:12px;font-weight:600;'
            f'display:inline-block;white-space:nowrap;">{text}</span>')


def _status_chip(result):
    style = duty_crew.STATUS_STYLE[result['status']]
    label = result['status'].replace('_', ' ')
    return _chip(label, style['bg'], style['fg'], result.get('reason', ''))


# The sheet coloured the font by the role still wanted — blue for a nurse, red for a
# medic — and these are its own hues, darkened enough to stay readable on the amber
# fill they sit on.
NURSE_INK = '#0057A3'
MEDIC_INK = '#B3001B'


def _cell_mark(result):
    """
    What one vehicle-on-a-date cell shows.

    The fill says the status. The mark says the thing the spreadsheet put in the
    font, which is what a scheduler actually acts on: which role is still wanted,
    and whether they have to be senior.

    Returns:
        tuple: (text, colour, bold) — colour '' means inherit the status fill's ink.
    """
    status = result['status']

    if status == duty_crew.UNSTAFFED:
        return '—', '', False

    if status == duty_crew.INCOMPLETE:
        need = result.get('needs')
        if not need:
            return '·', '', False          # only orientees aboard
        # The seat names itself and picks its own ink, so a service whose seats are
        # two EMTs gets the same treatment without anything here knowing what an
        # EMT is.
        short = need.get('short') or need.get('label') or '?'
        ink = need.get('ink') or ''
        # The sheet said "and they have to be the senior one" with bold alone. Bold
        # carries it at 12px far less well than it did in Excel, so the weight is
        # backed by the word — nobody should have to consult a key to read a board
        # they are working from.
        if need['senior_required']:
            return f'Sr {short}', ink, True
        return short, ink, False

    if status == duty_crew.CREWED:
        # Bold on a crewed vehicle meant every provider aboard is senior.
        return '✓', '', result.get('both_senior', False)

    return '✕', '', False


# ──────────────────────────────────────────────
# Block picker
# ──────────────────────────────────────────────

def _block_picker():
    """Choose which two-week block to work on, and open it if it is new."""
    existing = ddb.get_blocks()
    labels = {b['start_date']: f"{_fmt(b['start_date'])} — {b['status']}"
              for b in existing}

    col_pick, col_new, col_status = st.columns([2, 2, 2])

    with col_pick:
        options = list(labels.keys())
        current = _current_start()
        if current not in options:
            options = [current] + options
            labels[current] = f"{_fmt(current)} — not opened yet"
        chosen = st.selectbox(
            "Two-week block", options,
            index=options.index(current),
            format_func=lambda iso: labels.get(iso, _fmt(iso)),
            key='duty_block_select')
        if chosen != current:
            st.session_state[_STATE_START] = chosen
            st.session_state.pop(_STATE_DATE, None)
            st.rerun()

    with col_new:
        picked = st.date_input(
            "Or start a new block on",
            value=datetime.strptime(_current_start(), '%Y-%m-%d'),
            key='duty_block_new_date')
        if picked.weekday() != 6:
            st.caption("⚠️ Blocks run Sunday to Saturday. Pick a Sunday.")
        elif st.button("Open this block", key='duty_block_open',
                       use_container_width=True):
            ddb.get_or_create_block(picked.strftime('%Y-%m-%d'))
            st.session_state[_STATE_START] = picked.strftime('%Y-%m-%d')
            st.rerun()

    with col_status:
        block = ddb.get_block(_current_start())
        if not block:
            st.info("Not opened yet — open it to start assigning.")
        elif block['status'] == ddb.BLOCK_PUBLISHED:
            st.success(f"Published {block['published_date'] or ''}"
                       f"{' by ' + block['published_by'] if block['published_by'] else ''}")
        else:
            st.warning("Draft — staff cannot see this yet.")

    return ddb.get_block(_current_start())


# ──────────────────────────────────────────────
# Board tab
# ──────────────────────────────────────────────

def need_display_html(board):
    """
    The sheet's top block as HTML: every vehicle against every date.

    Built as markup rather than a dataframe because the colour and weight *are* the
    information — and because each cell can then carry, as a tooltip, the reason it
    reads the way it does, which is the thing the spreadsheet could never say.
    """
    dates = board['schedule_dates']

    head = ''.join(f'<th style="padding:4px 6px;font-size:11px;font-weight:600;'
                   f'text-align:center;white-space:nowrap;">{_fmt(d)}</th>'
                   for d in dates)
    rows = []
    for kind in (ddb.DAY, ddb.NIGHT):
        rows.append(
            f'<tr><td colspan="{len(dates) + 2}" style="padding:8px 6px 3px;'
            f'font-size:11px;letter-spacing:.08em;text-transform:uppercase;'
            f'color:#666;font-weight:700;">{kind}</td></tr>')
        for vehicle in board['vehicles'][kind]:
            cells = []
            for iso in dates:
                result = board['grid'][iso][vehicle['code']]
                style = duty_crew.STATUS_STYLE[result['status']]
                people = result['providers']
                who = ', '.join(p['staff_name'] for p in people)
                text, ink, bold = _cell_mark(result)
                tip = ' — '.join(part for part in
                                 (who, result['reason']) if part) or 'unstaffed'
                cells.append(
                    f'<td title="{vehicle["code"]} {_fmt(iso)} — {tip}" '
                    f'style="background:{style["bg"]};'
                    f'color:{ink or style["fg"]};'
                    f'text-align:center;font-size:12px;'
                    f'font-weight:{"800" if bold else "500"};'
                    f'padding:5px 4px;border:1px solid #fff;">{text}</td>')
            rows.append(
                f'<tr><td style="padding:4px 8px;font-size:11px;color:#888;'
                f'text-align:right;">{vehicle["priority"]}</td>'
                f'<td style="padding:4px 8px;font-size:12px;font-weight:600;'
                f'white-space:nowrap;">{vehicle["code"]}</td>'
                + ''.join(cells) + '</tr>')

    return ('<div style="overflow-x:auto;">'
            '<table style="border-collapse:collapse;font-family:system-ui,sans-serif;">'
            f'<thead><tr><th></th><th></th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _need_display(board):
    """Draw the need display and the key that explains its marks."""
    st.markdown(need_display_html(board), unsafe_allow_html=True)

    incomplete = duty_crew.STATUS_STYLE[duty_crew.INCOMPLETE]
    crewed = duty_crew.STATUS_STYLE[duty_crew.CREWED]

    def _key(text, ink, bold, bg, note):
        mark = (f'<span style="background:{bg};color:{ink};padding:2px 7px;'
                f'border-radius:4px;font-size:12px;'
                f'font-weight:{"800" if bold else "500"};">{text}</span>')
        return f'{mark} <span style="font-size:12px;color:#555;">{note}</span>'

    legend = ' '.join(
        _chip(duty_crew.STATUS_STYLE[s]['label'],
              duty_crew.STATUS_STYLE[s]['bg'], duty_crew.STATUS_STYLE[s]['fg'])
        for s in (duty_crew.CREWED, duty_crew.INCOMPLETE,
                  duty_crew.NO_CREW, duty_crew.UNSTAFFED))
    marks = ' &nbsp; '.join([
        _key('RN', NURSE_INK, False, incomplete['bg'], 'wants a nurse'),
        _key('Sr RN', NURSE_INK, True, incomplete['bg'], 'wants a <b>senior</b> nurse'),
        _key('MED', MEDIC_INK, False, incomplete['bg'], 'wants a medic'),
        _key('Sr MED', MEDIC_INK, True, incomplete['bg'], 'wants a <b>senior</b> medic'),
        _key('✓', crewed['fg'], False, crewed['bg'], 'crewed'),
        _key('✓', crewed['fg'], True, crewed['bg'], 'crewed, <b>both senior</b>'),
    ])
    st.markdown(f'<div style="margin-top:8px;">{legend}</div>'
                f'<div style="margin-top:8px;line-height:2;">{marks}</div>',
                unsafe_allow_html=True)
    st.caption("A crew is one RN seat and one medic seat with at least one senior "
               "provider. Two nurses (unless one is a dual in the medic seat), two "
               "medics, or two juniors have the bodies but not a crew. "
               "An amber cell names the role still wanted, in bold when the provider "
               "already on board is junior — so the other has to be the senior of "
               "the pair. Hover any cell for who is on it and why.")


def _counter_block(board):
    """
    The sheet's rows 18–35: who is on, split by role, and how many crews they could
    make. `possible_crews` reproduces its Q20/Q29 pairing formula.
    """
    dates = board['schedule_dates']
    rows = {}
    for kind, label in ((ddb.DAY, 'Day'), (ddb.NIGHT, 'Night')):
        for field, name in (('seniors', 'Senior'), ('total', 'Total'),
                            ('possible_crews', 'Possible crews'),
                            ('nurses', 'Nurse'), ('medics', 'Medic'),
                            ('duals', 'Dual')):
            rows[f"{label} · {name}"] = [
                board['counters'][iso][kind][field] for iso in dates]

    frame = pd.DataFrame(rows, index=[_fmt(d) for d in dates]).T
    st.dataframe(frame, use_container_width=True)


def _staff_grid(board):
    """
    The assignment grid. Each cell shows the vehicle where one is assigned, otherwise
    what the track says, so an unresolved `D` reads as work still to do.

    The two lead-in columns are the preceding Friday and Saturday, carried exactly as
    the sheet carried them so a night before the block is visible when judging rest.
    """
    dates = board['dates']
    records = []
    for row in board['staff']:
        line = {
            'Staff': row['staff_name'],
            'Sr': row['seniority'],
            'Role': 'dual' if row['is_dual'] else (row['role'] or '').lower(),
            'S/J': 'Sr' if duty_crew.is_senior(row) else 'Jr',
        }
        for iso in dates:
            day = row['days'][iso]
            if day['assignment']:
                seat = day['assignment']['seat']
                mark = day['assignment']['vehicle_code']
                if seat == ddb.SEAT_THIRD:
                    mark += ' (3rd)'
                elif _dual_marker(row, seat, _vehicle_spec(board, mark)):
                    mark += 'p'     # reached that seat on a dual credential
            elif day['training']:
                mark = day['training'][0]
            else:
                mark = day['track']
            line[_fmt(iso)] = mark
        records.append(line)

    frame = pd.DataFrame(records)
    lead_in = [_fmt(d) for d in board['lead_in_dates']]
    st.dataframe(frame, use_container_width=True, hide_index=True,
                 column_config={col: st.column_config.TextColumn(col, width='small')
                                for col in lead_in})
    st.caption(f"{', '.join(lead_in)} are the preceding Friday and Saturday, carried "
               "for the rest and 10-hour-turn check. A `p` marks a dual provider "
               "working the medic seat.")


def _render_board_tab(board):
    summary = duty_board.block_summary(board)

    cols = st.columns(5)
    cols[0].metric("Crewed", summary[duty_crew.CREWED])
    cols[1].metric("No crew", summary[duty_crew.NO_CREW])
    cols[2].metric("Incomplete", summary[duty_crew.INCOMPLETE])
    cols[3].metric("Unstaffed", summary[duty_crew.UNSTAFFED])
    cols[4].metric("Dates below minimum", len(summary['short_dates']))

    if board.get('snapshot_missing'):
        st.warning("This block is published but has no frozen snapshot behind it, so "
                   "what it shows can still change if a track is edited. Re-publish "
                   "to freeze it.")

    st.markdown("#### What is crewed")
    _need_display(board)

    with st.expander("Counters — who is on, and how many crews they could make"):
        _counter_block(board)

    st.markdown("#### Staff grid")
    _staff_grid(board)


# ──────────────────────────────────────────────
# Assign tab
# ──────────────────────────────────────────────

def _render_assign_tab(board, block):
    """One date at a time: the uncrewed vehicles, and who is free to fill them."""
    if not block:
        st.info("Open this block first, on the Board tab.")
        return
    if board['published']:
        st.warning("This block is published. Un-publish it to make changes.")

    dates = board['schedule_dates']
    focus = st.session_state.get(_STATE_DATE) or dates[0]
    if focus not in dates:
        focus = dates[0]

    focus = st.radio("Date", dates, index=dates.index(focus), horizontal=True,
                     format_func=_fmt, key='duty_assign_date')
    st.session_state[_STATE_DATE] = focus

    kind = st.radio("Shift", [ddb.DAY, ddb.NIGHT], horizontal=True,
                    format_func=str.capitalize, key='duty_assign_kind')

    vehicles = board['vehicles'][kind]
    free = duty_board.available_staff(board, focus, kind)

    left, right = st.columns([3, 2])

    with left:
        st.markdown(f"**Vehicles — {_fmt(focus)}, {kind}**")
        for vehicle in vehicles:
            result = board['grid'][focus][vehicle['code']]
            people = result['providers'] + result['riders']
            with st.container(border=True):
                head, action = st.columns([3, 2])
                with head:
                    st.markdown(
                        f"**{vehicle['code']}** &nbsp; {_status_chip(result)}"
                        + (f"<br><span style='font-size:12px;color:#666;'>"
                           f"{result['reason']}</span>" if result['reason'] else ''),
                        unsafe_allow_html=True)
                    labels = _seat_labels(ddb.crew_spec_of(vehicle))
                    for person in people:
                        st.caption(f"{person['staff_name']} — "
                                   f"{labels.get(person['seat'], person['seat'])}")
                with action:
                    if people and not board['published']:
                        drop = st.selectbox(
                            "Remove", ['—'] + [p['staff_name'] for p in people],
                            key=f"drop_{vehicle['code']}_{focus}",
                            label_visibility='collapsed')
                        if drop != '—':
                            ddb.clear_assignment(block['id'], drop, focus)
                            st.rerun()

    with right:
        st.markdown(f"**Available — {len(free)} free**")
        if not free:
            st.caption("Nobody on this shift is still unassigned.")
        for person in free:
            with st.container(border=True):
                flags = []
                if person['is_dual']:
                    flags.append('dual')
                flags.append('Sr' if duty_crew.is_senior(person) else 'Jr')
                if duty_crew.on_orientation(person):
                    flags.append('orientation')
                st.markdown(
                    f"**{person['staff_name']}** "
                    f"<span style='font-size:12px;color:#666;'>"
                    f"#{person['seniority']} · {' · '.join(flags)}</span>",
                    unsafe_allow_html=True)
                if person['training']:
                    st.caption("⚠️ " + ', '.join(person['training']))

                if board['published']:
                    continue
                pick, seat_pick = st.columns([3, 2])
                with pick:
                    target = st.selectbox(
                        "Vehicle", ['—'] + [v['code'] for v in vehicles],
                        key=f"assign_{person['staff_name']}_{focus}",
                        label_visibility='collapsed')
                with seat_pick:
                    seats = _seat_options_across(person, vehicles)
                    seat_labels = _seat_labels_across(vehicles)
                    seat = st.selectbox(
                        "Seat", seats, key=f"seat_{person['staff_name']}_{focus}",
                        format_func=lambda key: seat_labels.get(key, key),
                        label_visibility='collapsed')
                if target != '—':
                    ddb.set_assignment(block['id'], person['staff_name'], focus,
                                       target, seat=seat,
                                       source=ddb.SOURCE_MANUAL)
                    st.rerun()


def _seat_options(record, spec=None):
    """
    Which seats this person may take on this vehicle, most likely first.

    Read off the crew spec rather than hardcoded: a seat lists the roles it accepts
    and `provider_roles` gives a dual provider both of theirs, so putting a dual
    nurse in the medic seat — the sheet's `p` — falls out rather than being a case.
    """
    spec = spec or ddb.DEFAULT_CREW_SPEC
    if duty_crew.on_orientation(record):
        return [ddb.SEAT_THIRD]
    base = duty_crew.base_role(record)
    qualified = [seat for seat in spec.get('seats') or []
                 if duty_crew.seat_accepts(seat, record)]
    # The seat they are hired for first, then any a dual credential opens up.
    qualified.sort(key=lambda seat: base not in (seat.get('roles') or []))
    return [seat['key'] for seat in qualified] + [ddb.SEAT_THIRD]


def _dual_marker(record, seat_key, spec=None):
    """
    Whether somebody is in a seat only a second credential opens for them — the
    spreadsheet's `p` suffix.

    Read off the spec rather than hardcoded as "a nurse in the medic seat": a seat
    the person's hired role is not listed for is one they reached through a dual
    credential, whatever the two roles happen to be.
    """
    spec = spec or ddb.DEFAULT_CREW_SPEC
    seat = duty_crew.seat_by_key(spec).get(seat_key)
    if not seat:
        return False
    return duty_crew.base_role(record) not in (seat.get('roles') or [])


def _vehicle_spec(board, code):
    """The crew spec for one vehicle code on this board."""
    for kind in (ddb.DAY, ddb.NIGHT):
        for vehicle in board['vehicles'][kind]:
            if vehicle['code'] == code:
                return ddb.crew_spec_of(vehicle)
    return ddb.DEFAULT_CREW_SPEC


def _seat_options_across(record, vehicles):
    """
    Seats this person could take on any of these vehicles, most likely first.

    The assign tab offers a seat before a vehicle is picked, so the list is the
    union across the shift's vehicles rather than one vehicle's. A seat that turns
    out not to exist on the vehicle chosen shows up immediately as a misseat.
    """
    seen, options = set(), []
    for vehicle in vehicles:
        for key in _seat_options(record, ddb.crew_spec_of(vehicle)):
            if key not in seen:
                seen.add(key)
                options.append(key)
    return options or [ddb.SEAT_THIRD]


def _seat_labels_across(vehicles):
    """{seat key: label} across these vehicles."""
    labels = {ddb.SEAT_THIRD: '3rd'}
    for vehicle in vehicles:
        labels.update(_seat_labels(ddb.crew_spec_of(vehicle)))
    return labels


def _seat_labels(spec=None):
    """{seat key: label} for this spec, including the rider seat."""
    spec = spec or ddb.DEFAULT_CREW_SPEC
    labels = {seat['key']: seat.get('label') or seat['key']
              for seat in spec.get('seats') or []}
    labels[ddb.SEAT_THIRD] = '3rd'
    return labels


# ──────────────────────────────────────────────
# Vehicles tab
# ──────────────────────────────────────────────

def _render_vehicles_tab():
    st.caption("The inventory the board draws, in priority order. Retiring a vehicle "
               "keeps it readable in past blocks rather than deleting it.")

    vehicles = ddb.get_vehicles(include_inactive=True)
    frame = pd.DataFrame(vehicles)[
        ['code', 'label', 'shift_kind', 'priority', 'base',
         'rw_weight', 'gr_weight', 'is_active']]
    st.dataframe(frame, use_container_width=True, hide_index=True)

    with st.expander("Add or edit a vehicle"):
        with st.form('duty_vehicle_form'):
            cols = st.columns(3)
            code = cols[0].text_input("Code", help="D7B, N9L, MG …")
            label = cols[1].text_input("Label")
            kind = cols[2].selectbox("Shift", [ddb.DAY, ddb.NIGHT],
                                     format_func=str.capitalize)
            cols = st.columns(4)
            priority = cols[0].number_input("Priority", 1, 99, 1)
            base_names = ddb.base_labels()
            base = cols[1].selectbox("Base", [''] + ddb.bases(),
                                     format_func=lambda b: base_names.get(b, '—'))
            rw = cols[2].number_input("Rotor-wing weight", 0.0, 1.0, 1.0, step=0.5)
            gr = cols[3].number_input("Ground weight", 0.0, 1.0, 0.0, step=0.5)
            active = st.checkbox("Active", value=True)
            if st.form_submit_button("Save vehicle"):
                if not code.strip():
                    st.error("A vehicle needs a code.")
                else:
                    ddb.set_vehicle(code, label=label, shift_kind=kind,
                                    priority=priority, base=base,
                                    rw_weight=rw, gr_weight=gr, is_active=active)
                    st.success(f"Saved {code.strip()}.")
                    st.rerun()

    st.caption(f"Minimum staffing: day {ddb.MIN_RW_DAY} rotor-wing and "
               f"{ddb.MIN_GR_DAY} ground, night {ddb.MIN_RW_NIGHT} and "
               f"{ddb.MIN_GR_NIGHT}. D7P, N7P and N9L each count as half of each, "
               "which is how the spreadsheet counted them.")


# ──────────────────────────────────────────────
# Pairs tab
# ──────────────────────────────────────────────

def _render_pairs_tab():
    st.caption("Two people who may not crew the same vehicle — the spreadsheet's "
               "COUPLES block and its can't-work-with matrix. A restricted pair is "
               "blocked outright: a vehicle carrying both never reads as crewed.")

    pairs = ddb.get_restricted_pairs(include_inactive=True)
    if pairs:
        st.dataframe(pd.DataFrame(pairs), use_container_width=True, hide_index=True)
    else:
        st.info("No restricted pairs recorded.")

    from .staff_database import get_staff_names
    names = get_staff_names(clinical_only=True)

    with st.form('duty_pair_form'):
        cols = st.columns(3)
        first = cols[0].selectbox("Staff member", names, key='pair_a')
        second = cols[1].selectbox("May not crew with", names, key='pair_b',
                                   index=min(1, len(names) - 1))
        reason = cols[2].text_input("Reason", placeholder="couple, family …")
        if st.form_submit_button("Add restriction"):
            if first == second:
                st.error("Pick two different people.")
            elif ddb.set_restricted_pair(first, second, reason=reason):
                st.success(f"{first} and {second} will not be crewed together.")
                st.rerun()

    if pairs:
        labels = {f"{p['staff_a']} / {p['staff_b']}": p for p in pairs}
        chosen = st.selectbox("Remove a restriction", ['—'] + list(labels))
        if chosen != '—' and st.button("Remove", key='duty_pair_remove'):
            pair = labels[chosen]
            ddb.delete_restricted_pair(pair['staff_a'], pair['staff_b'])
            st.rerun()


# ──────────────────────────────────────────────
# Export and publish
# ──────────────────────────────────────────────

def export_frame(board):
    """
    The board as one grid: a row per staff member, a column per date.

    The same shape the spreadsheet's rows 39–122 held, so it can be pasted into
    whatever still consumes that.
    """
    records = []
    for row in board['staff']:
        line = {'Staff': row['staff_name'], 'Sr': row['seniority'],
                'Role': 'dual' if row['is_dual'] else (row['role'] or '').lower()}
        for iso in board['dates']:
            day = row['days'][iso]
            if day['assignment']:
                mark = day['assignment']['vehicle_code']
                if _dual_marker(row, day['assignment']['seat'],
                                _vehicle_spec(board, mark)):
                    mark += 'p'
            else:
                mark = day['track']
            line[iso] = mark
        records.append(line)
    return pd.DataFrame(records)


def _render_publish(board, block):
    if not block:
        return
    st.markdown("#### Publish")
    left, right = st.columns(2)

    with left:
        if block['status'] == ddb.BLOCK_DRAFT:
            st.caption("Publishing freezes what the tracks and training calendar say "
                       "right now, so the posted schedule stops moving if somebody "
                       "swaps a track afterwards.")
            if st.button("Publish this block", type='primary',
                         key='duty_publish', use_container_width=True):
                rows = duty_board.snapshot_block(block['start_date'])
                ddb.publish_block(block['start_date'], published_by='admin')
                st.success(f"Published, with {rows} rows of context frozen.")
                st.rerun()
        else:
            if st.button("Un-publish (back to draft)", key='duty_unpublish',
                         use_container_width=True):
                ddb.unpublish_block(block['start_date'])
                ddb.clear_block_context(block['id'])
                st.rerun()

    with right:
        frame = export_frame(board)
        st.download_button(
            "Download the grid (CSV)",
            frame.to_csv(index=False).encode('utf-8'),
            file_name=f"duty-schedule-{block['start_date']}.csv",
            mime='text/csv', use_container_width=True)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            frame.to_excel(writer, index=False, sheet_name='Duty')
        st.download_button(
            "Download the grid (Excel)", buffer.getvalue(),
            file_name=f"duty-schedule-{block['start_date']}.xlsx",
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            use_container_width=True)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def display_duty_schedule_admin():
    """The Duty Schedule admin page."""
    if not require_admin('duty_schedule_admin'):
        return

    ddb.initialize_duty_tables()

    st.markdown("## 🚑 Duty Schedule")
    st.caption("Turn a two-week block of tracks into vehicle assignments. The track "
               "says who works a day or a night; this is where that becomes D7B.")

    block = _block_picker()
    st.divider()

    board = duty_board.build_board(_current_start())

    board_tab, assign_tab, vehicles_tab, pairs_tab = st.tabs(
        ["Board", "Assign", "Vehicles", "Pairs"])

    with board_tab:
        _render_board_tab(board)
        st.divider()
        _render_publish(board, block)
    with assign_tab:
        _render_assign_tab(board, block)
    with vehicles_tab:
        _render_vehicles_tab()
    with pairs_tab:
        _render_pairs_tab()
