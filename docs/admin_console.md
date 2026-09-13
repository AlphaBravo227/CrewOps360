# The Admin Console

Every administrative area of CrewOps360 sits behind one sign-in, on one page.

## What it replaced

Administration used to be scattered across the modules, with two credentials:

| Where | Credential | Session |
| --- | --- | --- |
| Clinical Track Hub sidebar | admin password | never expired |
| Track Bidding sidebar | admin password | never expired |
| Staff Database / Track Data pages | admin password | never expired |
| Summer Leave sidebar | the same password, compared against its own hardcoded copy | never expired |
| Training & Events sidebar | a separate 4-digit PIN | 30 minutes |

So an administrator signed in twice to do one job, and finding a tool meant knowing
which module's sidebar it was hiding in. There is now a single admin session
(`modules/security.py`), a single door (`modules/admin_console.py`), and no PIN.

## Signing in

The password is looked up in this order, first hit wins:

1. `st.secrets["admin"]["password"]`
2. the top-level `admin_password` secret
3. the `CREWOPS_ADMIN_PASSWORD` environment variable
4. the built-in default, for local development only

Set a real one on deployment. In `.streamlit/secrets.toml`:

```toml
[admin]
password = "…"
```

The session lasts 60 minutes and every admin page extends it on render, so the
timeout only bites on a console left open and walked away from. It ends on
**Sign out**, on logging out of CrewOps360 (one sign-out, not two), or on expiry —
and ending it drops the per-module admin views with it, so nobody comes back to a
stale admin screen.

## Getting there

- **Landing page** — the *Admin Console* button under the module cards.
- **Any module's sidebar** — the same door, with session status and sign-out when
  you are signed in.

## The sections

| Section | What it holds |
| --- | --- |
| 👥 Staff Database | The roster and staff attributes: roles, management, dual, educator, no matrix, seniority, groupings, managers, Excel import. |
| 📌 Track Data | Preassignments and CCEMT schedules, per cycle. |
| 🗳️ Track Bidding | Track configs, bid access, add/remove selections, bid analysis and roster, base analysis, staffing rebalance, needs-swap requests. |
| 📚 Training & Events | Enrollment reports, staff and class management, educator coverage, class building, training years, exports, statistics, database maintenance, track manager. |
| ☀️ Summer Leave | Week allocations, staff selections, and the LT schedule report. |
| ✅ Track Approvals | Modifications to the active track waiting on an approve or reject. |
| 📤 Exports & Reports | Staff preferences, fiscal-year tracks, filtered active tracks, and database extracts. |
| 🗂️ System & Backups | Roster and track health, active track and capacity, staff/track mismatches, integrity check, backups, restore, email configuration. |

Most sections render inside the console. **Training & Events** and **Summer Leave**
have full-page dashboards of their own and are opened rather than re-implemented;
both carry an *Admin Console* button back.

## What was removed on the way

The Clinical Track Hub sidebar carried a wall of admin controls. The working ones
moved into the console. These did not, because they were not working:

- **Role Delta Filter** — three widgets that wrote to local variables nothing read.
  Their only consumers were in the track-management editor, which is not wired into
  the app.
- **Enhanced Validation Rules** — a static block of markdown with no controls. The
  rules it described are still enforced in `modules/enhanced_track_validator.py`.
- **Email Configuration** — described a Gmail SMTP setup the app stopped using when
  it moved to Resend. The console reads the live configuration off the notifier
  instead. Its *Test email* button also treated a `(success, message)` tuple as a
  boolean, so a failed send reported success; it reports the real result now.
- **The restore backup picker** — a column of single-option radio buttons, none of
  which could be deselected, so it always reported a selection. It is a dropdown.
- **`add_track_display_with_export_to_admin`** — a whole admin panel in
  `modules/track_display.py` that nothing had called in a long time. The workbook it
  built is worth having, so it is the *Filtered Tracks* tab under Exports & Reports
  now; the dead wrapper is gone.

## For developers

`modules/security.py` is the only place that decides whether someone is an admin:

```python
from modules.security import admin_is_authenticated, require_admin

# a check
if admin_is_authenticated():
    ...

# a gate that renders its own sign-in form
if not require_admin("my_page_login"):
    return
```

Do not add another password field. Those two functions and `authenticate_admin()`
(which the gate calls for you) are the whole of the admin surface —
`check_admin_access()`, the old per-page helper, is gone.
`training_admin_is_authenticated()` remains in
`training_modules/admin_access.py` as a name the training app reads; it now just
delegates to `admin_is_authenticated()`.

To add a section, append to `ADMIN_SECTIONS` in `modules/admin_console.py` and give
it a branch in `_render_section`. A section renders body-only — the console supplies
the navigation, the title and the gate.
