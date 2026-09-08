# vPromotions Help Center — Liners, PSAs, and Live Mentions
# =============================================
# Source: https://vcreativeinc.com/knowledge/vpromotions#liners-psas-and-live-mentions
# Extracted: 2026-07-27
# Product-scoped: only loaded for vpromotions runs.

## WORKFLOW: Navigate the Liners Tab Toolbar
KEYWORDS: liners tab, station selector, liner category, jump to date, liners list
JIRA:
---
WHAT: The Liners tab on the Home/Calendar page is where liners are viewed, edited, and created, showing the liner slot grid for the selected station.
WHO: Any user with Liners tab access; only Promotions Manager, Program Director, or General Manager abilities can create liners.
WHERE: Home/Calendar page > Liners tab.
HOW:
1. Use the Station Selector to confirm/switch the station; a station can be set as your default so it appears first when the Liners tab opens.
2. Use the Liner Category selector to choose which category's slot times display (Default if no custom categories exist); more than one category can be displayed on the grid at once, and a default category can be set.
3. Navigate dates with Today (returns to the current week), the Backward arrow and Forward arrow (one week at a time), and Jump to Date (a specific date).
4. Review the Liners List of currently scheduled liners: use Show entries (10–100) and Search to filter; columns are Start (first scheduled date), End (final scheduled date), Title, Total Qty (total scheduled runs), Remaining (occurrences not yet run), and Current Week (runs this week).
5. Click a Title (a blue link) to open the liner's list view showing when it was/will be scheduled plus read timestamps.
6. Use Avails: for a quick count of open liner slots in the displayed period, and Time Period to see the range currently on the grid.
CONSTRAINTS: Liner slots must be created before liners can be scheduled — slots are placeholders defining when liners may run. If no slot times appear after selecting the station, slots have not been created yet.
GOTCHAS: A "(PRG)" label at the end of a title indicates a Program Liner; a title without it was created inside a PRF.
TEST-DATA HINTS: Liner title "Monday Mayhem" with Remaining = 3 for one day's occurrences, 6 across two days.

## WORKFLOW: Work with Liners on the Liner Grid
KEYWORDS: liner grid, drag and drop, mark as read, past due, swap liners
JIRA:
---
WHAT: The liner grid displays available slots and scheduled liners, and supports direct manipulation of placement and status.
WHO: Users with liner management access.
WHERE: Home/Calendar page > Liners tab > the grid below the toolbar.
HOW:
1. Drag a scheduled liner to a different available slot to move it; drag one liner onto another scheduled liner to swap their positions.
2. Read the visual indicators: orange liners are PRF liners, yellow liners are Program Liners, a checkmark means the liner was marked as read, an exclamation mark means it is past due and not marked as read, and a slot labeled Available holds no scheduled liner.
3. Select a liner on the grid to open its popover, then use: the green checkmark to mark the liner as read; the pencil icon to edit the current occurrence, the selected occurrence and all future occurrences, or every occurrence; the copy icon to copy the liner (it appears in a floating area — hover for placement instructions, then select an available slot to paste it); and the list all icon to open the liner's list view.
4. In the list view, review read timestamps, use the trash can icon to delete an individual liner, check multiple scheduled liners and use Bulk Actions in the upper-right to delete several at once, and use Edit to apply a copy change to the current liner only, the selected liner and all future occurrences, or every occurrence.
CONSTRAINTS: Edits always prompt for scope (this occurrence / this and future / all occurrences) — choosing the wrong scope changes more or fewer airings than intended.
GOTCHAS: Past-due liners are flagged with red exclamation marks on the grid, making unmarked airings easy to spot at a glance.
TEST-DATA HINTS: n/a (grid interaction reference).

## WORKFLOW: Understand vPromotions Liner Types and Scheduling Methods
KEYWORDS: liner types, program liners, static liners, legacy scheduling, priority scheduling
JIRA:
---
WHAT: Reference for the three liner types and the two mutually exclusive scheduling methods available in vPromotions.
WHO: Anyone configuring or working with liners.
WHERE: Liner type selection happens on the Liners tab; the scheduling method is set per station in Settings > vPromo > Available Liner Slots.
HOW: Liner types are Promotion Liners (attached to promotions on the Home Calendar), Program Liners (scheduled directly, not tied to a promotion), and Static Liners/Billboards/PSAs (listed and tracked, but not scheduled). Scheduling methods are: "Schedule Liners Immediately On Save" (Legacy), which schedules each liner the moment it is saved, with later liners scheduling around earlier ones; and "Schedule Liners According to Priorities Daily," which holds liners in the Liner Queue with a priority of 1 (highest) to 4 (lowest) and schedules them in passes, similar to a music scheduler.
CONSTRAINTS: The three Static Liner methods are Static Liners, Billboards, and PSAs — all are listed rather than time-scheduled.
GOTCHAS: The Legacy method can fill the Liner Grid with lower-priority liners scheduled far into the future, leaving little room for high-priority liners that come in with short notice — the priority-based method exists to solve this.
TEST-DATA HINTS: n/a (conceptual reference).

## WORKFLOW: Create Program Liners
KEYWORDS: program liners, +program liners, non-prf liner, on air tab
JIRA:
---
WHAT: Program Liners are liners created and scheduled outside of any PRF, used for station programming content.
WHO: Promotions Manager, Program Director, or General Manager abilities.
WHERE: Home/Calendar page > Liners tab > +Program Liners button.
HOW: Click +Program Liners and create/schedule the liner the same way as a PRF liner. Once scheduled, Program Liners appear on the On Air tab and display in yellow on the liner grid with a "(PRG)" label after the title in the Liners List.
CONSTRAINTS: Requires Promotions Manager, Program Director, or General Manager ability; abilities are managed in the People Tab, which is available only to Firm Admins.
GOTCHAS: For liners related to an existing promotion, create them inside the PRF instead — PRF-created liners stay associated with the promotion, keeping all related elements visible together. Note that PRF liners do not appear on the On Air tab until the PRF is fully approved, whereas Program Liners appear as soon as they are scheduled.
TEST-DATA HINTS: Copy such as "Check out our Sunday morning countdown show" or "Download our app."

## WORKFLOW: Manage Static Liners, Billboards, and Station PSAs
KEYWORDS: static liners, billboards, station psas, artist mentions, holding tank
JIRA:
---
WHAT: Static Liners, Billboards, and PSAs are live-mention content that is listed and tracked rather than scheduled to a specific time.
WHO: Users with liner creation/management access (Promotions Manager, Program Director, General Manager abilities).
WHERE: Home/Calendar page > Liners tab > the Station PSAs button, the Static Liners/Billboards button, and the +Static Liners/Billboards button.
HOW:
1. Use Static Liners/Billboards to view, create, and manage static liners, billboards, and artist mentions — content that is not scheduled for a specific time and instead remains in a liner "holding tank" that on-air staff access as filler during their shows.
2. Use +Static Liners/Billboards when you only need to create a new one (this button is creation-only, unlike the manage view).
3. Use Station PSAs to view, create, and manage PSA liners — the same concept as Static Liners/Billboards but used specifically for PSAs.
CONSTRAINTS: These liner types are never placed into liner slots on the grid, so they don't consume scheduled inventory and won't show grid indicators like past-due exclamation marks.
GOTCHAS: Because they are filler content, they rely on on-air staff pulling from the holding tank — there is no scheduled time forcing them to air.
TEST-DATA HINTS: n/a (content-management reference).

## WORKFLOW: Check Liner Availability
KEYWORDS: liner availability, open slots, dayparts, avails, get
JIRA:
---
WHAT: Liner Availability reports how many open liner slots remain within selected date ranges or dayparts.
WHO: Any user with Liners tab access.
WHERE: Home/Calendar page > Liners tab > Liner Availability tool (the Avails: display gives a quick count for the current view).
HOW: Open Liner Availability, select the applicable date range and/or daypart options (for example, morning drive or afternoon drive), and click Get to see how many slots remain open.
CONSTRAINTS: Availability is reported for the currently selected station and category context.
GOTCHAS: The Avails: indicator in the toolbar is a quick glance at the displayed time period only — use the Liner Availability tool for daypart- or range-specific counts.
TEST-DATA HINTS: Daypart selections for morning drive and afternoon drive.

## WORKFLOW: Create Custom Liner Slot Categories
KEYWORDS: custom liner category, available liner slots, categories field, slots for
JIRA:
---
WHAT: Custom liner slot categories let a station group liner slot times separately from the built-in Default category.
WHO: Only Promotions Manager, Program Director, or General Manager abilities can create liners or custom liner categories (abilities are managed in the People Tab, available only to Firm Admins).
WHERE: Hover over your name in the upper-right corner, then Settings > vPromo > Available Liner Slots; work in the New Station Available Slots section on the right side of the page.
HOW:
1. Go to Settings > vPromo > Available Liner Slots and select the station.
2. In the New Station Available Slots section, enter the new category's name in the Categories field — it appears highlighted and underlined below the field; select the highlighted name to save the category.
3. Select the appropriate days and times for the custom category.
4. Click the blue Add button to save the liner category.
5. Click Yes, Continue on the warning that appears.
6. The category becomes available in the "Slots for:" dropdown above the grid — hover over Slots for to see the Default category plus all custom categories, and click one to display only that category's slot times on the grid.
7. On the main Liners tab, select the station and the categories you want displayed; when creating a liner, select the appropriate category.
CONSTRAINTS: The selected end hour represents the final full hour in the schedule — to schedule through the 6:00 p.m. hour and stop at 7:00 p.m., select 6:00 p.m. as the end hour. The warning shown when adding does not block you; it only confirms you intend to work with custom categories.
GOTCHAS: The system automatically selects the Default liner category when creating a liner, so the custom category must be chosen deliberately each time. Use the trash can icon to delete a custom category; slot times can also be moved manually on the liner grid. All scheduled liners appear on the On Air tab regardless of category, but PRF liners won't appear until the PRF is fully approved.
TEST-DATA HINTS: Category "Community Calendar Hit" on station USML-AM, weekdays at 22 minutes past each hour from 10:00 a.m. through 7:00 p.m.

## WORKFLOW: Switch a Station to Priority-Based Liner Scheduling
KEYWORDS: priority-based liner scheduling, available liner slots, liner queue, legacy liners
JIRA:
---
WHAT: Converts a station from Legacy (schedule-on-save) liner scheduling to priority-based scheduling, where liners queue up and are scheduled in priority passes.
WHO: Requires the setting to be enabled for the Firm by the vCreative Help Desk; then configured per station by a user with settings access.
WHERE: Settings > vPromo > Available Liner Slots, using the station selector at the top of the grid.
HOW:
1. Before switching, choose a date to start using Priority-Based Liner Scheduling and delete all liners scheduled from that date forward (use the List All icon on each liner in the grid to mass-delete scheduled liners).
2. Go to Settings > vPromo > Available Liner Slots and choose a Station from the selector at the top of the grid.
3. Select "Schedule liners according to Priorities daily" and Save — each station is set up individually.
4. Go to the Liners tab of each current promotion on the calendar to add liners to the Liner Queue.
5. Once all liners are in, go to the main Liners tab from the Home calendar and schedule liners.
CONSTRAINTS: Priority-Based Liners and Legacy Liners do not work together — existing liners scheduled on/after the cutover date must be deleted first. If the scheduling-method selector does not appear after choosing a station, contact the vCreative Help Desk to enable Priority-Based Liner Scheduling for the Firm.
GOTCHAS: Switching only affects the selected station; other stations remain on their existing method until individually converted.
TEST-DATA HINTS: n/a (migration/configuration workflow).

## WORKFLOW: Schedule Liners from the Liner Queue
KEYWORDS: schedule liners, liner queue, priority passes, reschedule, +schedule liners
JIRA:
---
WHAT: With Priority-Based Liner Scheduling, saved liners collect in the Liner Queue and are placed onto the grid in priority order when you run scheduling.
WHO: Users with liner scheduling access on a station configured for Priority/Frequency-Based Liner Scheduling.
WHERE: Home/Calendar page > Liners tab > the Liner Queue button and the +Schedule Liners button (both appear only for stations using priority-based scheduling).
HOW:
1. Create liners and Save — each is added to the Liner Queue rather than scheduled immediately, with a Priority of 1 (highest) through 4 (lowest).
2. Click Liner Queue from the Liner Grid to see which liners will schedule within the given dates, and edit any liner there to change copy, Priority, run dates, etc. before scheduling.
3. Once all liners for the period are entered, click +Schedule Liners (or the Schedule button), enter the date(s) you are scheduling, and review the list of liners that will be scheduled from the Liner Queue.
4. Confirm — the scheduler places Priority 1 liners first at their configured per-day or per-daypart quantities, then moves to Priority 2, then 3, then 4.
CONSTRAINTS: Scheduling should be done only after all liners for the time period are entered, since each pass fills slots in priority order.
GOTCHAS: If you schedule dates that were already scheduled, a warning appears; proceeding removes all liners for those days and reschedules them — no separate "unscheduling" step is needed, which is useful when new liners must be worked in.
TEST-DATA HINTS: Priority 1 liner scheduled ahead of Priority 4 liners for the same date range.

## WORKFLOW: Set Priority-Based Liner Frequencies and Rules
KEYWORDS: liner frequency, run of schedule, every hour, qty per day, liner rules
JIRA:
---
WHAT: Frequency controls how often a priority-based liner schedules; rules keep its placement varied from day to day.
WHO: Users creating or editing Priority-Based Liners or Program Liners.
WHERE: The liner form when adding to the Liner Queue, and editable afterward from the Liner Queue.
HOW:
1. Choose a Frequency: Run of Schedule (fills every open liner slot with all liners set to this frequency), Every Hour (once per hour), Every Other Hour (once every other hour), Qty Per Selected Daypart (requires Dayparts to be selected; schedules the chosen number of times per daypart), or Qty Per Day (chosen number of times per day).
2. Optionally apply rules: "No Scheduling the Same Liner at the Same Time Two Days in a Row" (looks back one day and blocks that exact time) and "No Scheduling the Same Liner at the Same Time It Ran 2 Days Ago" (looks back two days and blocks that exact time).
3. Adjust Frequency and rules later from the Liner Queue, then reschedule to apply the changes.
CONSTRAINTS: Qty Per Selected Daypart requires at least one entry in the Dayparts field. Dayparts and Days are not required — if left blank, the system assumes all dayparts and all days.
GOTCHAS: Run of Schedule should only be used for Priority 4 liners, and only when multiple Priority 4 liners share that frequency — applying it to a Priority 1 liner means no other liners will schedule at all. Every Hour works best on Priority 1 liners since they schedule in the first pass; pair it with rules when there is more than one available slot per hour so the liner lands at different times day to day.
TEST-DATA HINTS: Priority 4 liners set to Run of Schedule; a Priority 1 liner set to Every Hour with the two-day-in-a-row rule applied.

## WORKFLOW: Exclude a Liner Category from Scheduling
KEYWORDS: do not schedule categories, category exclusion, reschedule, manual category
JIRA:
---
WHAT: Prevents liners in specified categories from being disturbed when you run Schedule Liners under Priority-Based Liner Scheduling.
WHO: Users running liner scheduling on a priority-based station.
WHERE: The scheduling dialog opened from Schedule Liners — the "Do not schedule categories" field.
HOW: When scheduling liners, select the liner categories you want left out in the "Do not schedule categories" field. When you schedule, liners in those categories remain undisturbed.
CONSTRAINTS: Applies to Priority-Based Liner Scheduling only.
GOTCHAS: This is the way to protect a manually scheduled category from being wiped and rebuilt when you reschedule other categories over the same dates — without it, rescheduling a date range removes and re-places all liners for those days.
TEST-DATA HINTS: Exclude a manually managed custom category while rescheduling the Default category.

## WORKFLOW: Manually Schedule Liners into Slots
KEYWORDS: activate manual scheduling, insert, drag and drop, available slot
JIRA:
---
WHAT: Manual scheduling lets you place liners into specific available slots yourself instead of letting the system decide placement.
WHO: Users with liner management access; works the same under either scheduling method.
WHERE: Home/Calendar page > Liners tab > Activate Manual Scheduling button, and the liner grid itself.
HOW:
1. Choose the Station and Liner Category from the dropdown menus, and use the left/right arrows to move backward and forward in time.
2. Click Activate Manual Scheduling — the button turns blue to indicate manual scheduling is active.
3. Select an open slot to display a dropdown of available liners, choose the preferred liner, and click Insert to place it.
4. Click Deactivate Manual Scheduling to return to system scheduling.
5. Alternatively, drag and drop already-scheduled liners into any available Liner Slot to adjust the schedule directly on the grid.
CONSTRAINTS: Liners can only be inserted into slots that exist and are open — slot times must already be configured for the station and category.
GOTCHAS: The Liner Grid editing and manual scheduling behave identically under both Legacy and Priority-Based scheduling. Past-due liners are flagged with red exclamation marks (!), so scan for those when manually filling the grid.
TEST-DATA HINTS: n/a (grid interaction workflow).

## WORKFLOW: Mark a Liner as Read or Tracked with Manual Time Entry
KEYWORDS: mark as read, mark as tracked, clock icon, air talent, liner time
JIRA:
---
WHAT: Lets air talent record the actual or intended air time of a liner rather than defaulting to the click time or scheduled time.
WHO: Air Talent / on-air staff working the On Air tab.
WHERE: The Mark as Read and Mark as Tracked buttons, each with a small clock icon beside it.
HOW:
1. Click Mark as Read to mark the liner as having aired at the moment the button is clicked.
2. Click the Mark as Read clock icon to mark it as read at any time earlier than the current time — for example, if the liner was read five minutes ago, set the time to five minutes ago.
3. Click Mark as Tracked to mark the liner as having aired at the time it was scheduled to air.
4. Click the Mark as Tracked clock icon to set a future time within the day being viewed — for example, if a liner is scheduled for 8:05 AM but talent finds a better intro at 8:23 AM, enter 8:23 AM.
CONSTRAINTS: The Mark as Read clock only accepts times prior to the current time; the Mark as Tracked clock only accepts times within the day currently being viewed.
GOTCHAS: Only liners Marked as Read or Tracked count toward airing reports (for example, the Feature Sponsorship Report in kb-sponsorships.md), so untracked liners will be missing from client reporting.
TEST-DATA HINTS: Liner scheduled 8:05 AM Sunday, re-tracked to 8:23 AM.
