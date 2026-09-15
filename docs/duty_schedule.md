# Duty Schedule

A track says a staff member works a day or a night. It does not say which aircraft or
which ambulance. Turning `D` into `D7B` was done by hand on
`Active 2-Week Template v10.17.25.xlsx`, against a coloured display at the top of the
sheet that showed which vehicles had a legal crew — and against staff attributes pulled
over a SharePoint link from `Comprehensive Schedule Preferences v2.xlsx`.

This is that, in the app. See [track_data.md](track_data.md) for where the tracks come
from and [staff_database.md](staff_database.md) for the roster it reads.

**Where:** Admin Console → **Duty Schedule**.

| Was | Now |
| --- | --- |
| The 15 vehicle rows at the top of the sheet | `duty_vehicles` — code, priority, base, RW/ground weighting |
| One dated tab per cycle (`11 Oct 2026`) | `duty_blocks` — one row per two-week block, draft until published |
| The assignment grid, rows 39–122 | `duty_assignments` — one row per person per date |
| The COUPLES block and custom matrix, rows 248–264 | `duty_restricted_pairs` |
| `Updated Prefs` over the SharePoint link | `user_location_preferences`, already a column-for-column match |
| Senior/junior, column B | `staff.no_matrix`, already the rule in track bidding |
| Drive time, columns AW:BA | Not carried. `staff.zip_code` is stored if it is ever wanted |

## What the board does, and does not do

It does not decide who goes on what. A scheduler does, and later an algorithm will.
The board's job is to put everything needed to decide in one place, and to show the
consequence of each choice as it is made.

The one thing it does that the spreadsheet could not: **filter to the people actually
available**. The sheet could sort its 84 rows; it could not hide the sixty of them who
are off that day. Pick a date and a shift on the **Assign** tab and you get the people
whose track has them on, in seniority order, minus anyone already placed.

## The crew rule

On the spreadsheet this was arithmetic. Sixteen hidden six-row blocks counted who was
on each vehicle and folded them into one number — senior RN ×9, senior medic ×90,
junior RN ×900, junior medic ×9000 — and about fifty conditional-format rules
enumerated the sums that were legal: 99, 990, 9009, 189, 18009 and so on.

It worked, but it could only say *what colour*, never *why*. And the encoding had begun
to fray: every reachable total is a multiple of nine, so the rule written for 123 could
never fire, and the places collide once counts pass single digits — twelve senior RNs
and "one senior medic plus two senior RNs" are both 108.

Stated plainly, the rule those sums encode is:

> A crew is one RN seat and one medic seat, and at least one of the two is senior.

`modules/duty_crew.crew_status()` evaluates that directly, and returns a reason as well
as a status:

| Status | Means | What to do |
| --- | --- | --- |
| `crewed` | a legal crew | nothing |
| `incomplete` | somebody is on it, but not enough of them | add a person |
| `no_crew` | enough people, but they don't make a crew | swap somebody |
| `unstaffed` | nobody on it | fill it |

`no_crew` covers two nurses with neither in the medic seat, two medics, and a pairing
where both providers are junior. All three have the bodies and still cannot fly, which
is why they read differently from `incomplete` — one needs an extra person, the other
needs a different one.

### Who is wanted, not just that somebody is

The fill was only half of what the sheet said. Its **font** carried a second channel,
and it is the more useful one:

| Sheet | Meant |
| --- | --- |
| blue font | a **nurse** is still wanted |
| red font | a **medic** is still wanted |
| **bold** | the provider already aboard is junior, so the other has to be the senior |
| bold on a green cell | every provider aboard is senior |

Both survive as `needs` (`{'role', 'senior_required'}`) and `both_senior` on the
`crew_status()` result, so the reason reads "needs a senior medic" rather than "needs a
person". On the board a cell shows `RN`, `Sr RN`, `MED` or `Sr MED` in the sheet's own
blue and red. Bold alone carried this fine in Excel and carries it poorly at 12px in a
browser, so the weight is backed by the word — nobody should have to consult a key to
read a board they are working from.

A crewed cell shows `✓`, in bold when every provider aboard is senior. That is what
tells a scheduler which crews have a senior to spare for somewhere that is short one.

### Seats, and the `p` suffix

A crew is one RN seat and one medic seat. Who may sit where:

- a **medic** takes the medic seat
- a **nurse** takes the RN seat
- a **dual provider** takes either — and a dual nurse in the medic seat is what the
  spreadsheet wrote as `D7Bp`. That is why its helper counted a nurse on the p-variant
  toward the medic slot; the arithmetic was right.
- somebody **on orientation** rides as an uncounted third seat, whichever seat the row
  says

The board and the export both write the `p` back out, so `GRp` still means what it
always meant.

## Two-week blocks

A block runs Sunday to Saturday twice over, on the pay period. It carries the
**preceding Friday and Saturday** as well — sixteen columns, not fourteen — because a
night worked on the Saturday before decides whether the Sunday is a legal turn, and the
sheet kept those two columns for exactly that.

A block is a **draft** until somebody publishes it. Staff see published blocks only.

### Publishing freezes it

A draft reads the tracks and the training calendar live, so a swap made while the block
is being built shows up straight away. A published block must not do that — nobody wants
the posted schedule moving under them — so publishing writes a snapshot into
`duty_block_context` and the published board reads that instead.

Un-publishing clears the snapshot and the block goes back to reading live.

A block published before snapshots existed has no context behind it. The board says so
rather than passing it off as frozen; re-publishing fixes it.

## Vehicles

The inventory is seeded from the sheet and then owned by an admin — add, retire and
re-prioritize on the **Vehicles** tab rather than in code. Retiring keeps a vehicle
readable in past blocks instead of deleting it.

| Base | Airport | Day | Night |
| --- | --- | --- | --- |
| B | KBED Bedford | `D7B`, `GR` | `N7B`, `NG` |
| H | KMHT Manchester | `D11H` | — |
| L | KLWM Lawrence | `D9L`, `LG` | `N9L` |
| P | KPYM Plymouth | `D7P`, `PG` | `N7P`, `NP` |
| M | 1B9 Mansfield | `D11M`, `MG` | — |

`D7P`, `N7P` and `N9L` each count as half rotor-wing and half ground, which is how
`AP39`/`AQ39` counted them. Minimum staffing is day 5 rotor-wing and 2 ground, night 3
and 1 — held in `modules/duty_schedule_db.py` as policy rather than inventory.

One to check: **`NP`** is the only vehicle the spreadsheet never counted in either the
rotor-wing or the ground column. It is seeded as ground, to match `PG`.

## Restricted pairs

Two people who may not crew the same vehicle. A restricted pair is a **hard block**: a
vehicle carrying both never reads as crewed, whatever else is right about it. Pairs are
unordered, so it does not matter which way round one is entered.

## Reading it in code

```python
from modules import duty_board, duty_crew
from modules import duty_schedule_db as ddb

ddb.initialize_duty_tables()
block = ddb.get_or_create_block('2026-10-11')     # a Sunday

board = duty_board.build_board('2026-10-11')
duty_board.available_staff(board, '2026-10-11', ddb.DAY)   # who is free
board['grid']['2026-10-11']['D7B']                         # status and reason
duty_board.block_summary(board)                            # counts, and dates below minimum

ddb.set_assignment(block['id'], 'Bell', '2026-10-11', 'D7B', seat=ddb.SEAT_RN)
duty_board.snapshot_block('2026-10-11')
ddb.publish_block('2026-10-11', published_by='admin')
```

## Staff attributes this added

Two new columns on `staff`, both set in the Staff Database admin:

- **`date_of_hire`** — column I of the sheet, which the roster never held.
- **`on_orientation`** — somebody who rides as an uncounted third rather than filling a
  crew seat. Defaults to 0, so adding the column does not take the whole roster off the
  board.

Senior/junior needed nothing: it is `staff.no_matrix`, which
`track_bidding._bid_role_and_senior` already reads this way.

## Checking it

```bash
python scripts/check_duty_schedule.py
```

Runs against a throwaway database and verifies the crew rules against the spreadsheet
totals they replace — 99 and 990 and 9009 crew, 9900 and 909 and 9090 do not — along
with the vehicle inventory, availability filtering, restricted pairs, and that
publishing actually freezes a block against a track change.

## Not carried over

Deliberately out of scope for now:

- **The assignment algorithm.** A separate piece of work. When it arrives it writes
  `duty_assignments` rows with `source='algorithm'`, which the schema already allows.
- **Leave, military, jury duty and AOC.** These live in another system and will come in
  as a further calendar overlay, the way training already does.
- **Drive-time calculation.** `zip_code` is stored; the times were computed outside the
  workbook.
- **FYTD equity counters.** Derivable once blocks have been published for a while, and
  the natural input to the algorithm above.
- **Holiday staffing**, which was its own sheet.
