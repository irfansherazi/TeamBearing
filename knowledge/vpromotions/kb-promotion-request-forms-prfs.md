# vPromotions Help Center — Promotion Request Forms (PRFs)
# =============================================
# Source: https://vcreativeinc.com/knowledge/vpromotions#promotion-request-forms-prfs
# Extracted: 2026-07-27
# Product-scoped: only loaded for vpromotions runs.

## WORKFLOW: Complete the Assignments Step in the PRF Setup Wizard
KEYWORDS: assignments step, job task, wizard, assign task
JIRA:
---
WHAT: The Assignments step of the Contest/Event PRF Setup Wizard lets you assign jobs or tasks to team members as part of setting up a promotion.
WHO: Any user running the Wizard for a PRF they're authorized to configure.
WHERE: PRF Setup Wizard (click the wizard icon) → Assignments step.
HOW: 1. Use the Job/Task dropdown to select the job or task to assign. 2. Optionally mark it recurring if it must be completed more than once. 3. Use the Who dropdown to pick the responsible person — options are filtered to users with the matching ability (e.g., only Salesperson-ability users show for a Salesperson job). 4. Click the green plus sign to add another due date/time for the same job/task. 5. Click "Add Job/Task" to assign an additional job/task to the same person. 6. Use the trash-can icon to remove and redo an assignment entry. 7. Click the blue "Add" button to save the assignment.
CONSTRAINTS: Job/task options available in the Who dropdown are ability-specific.
GOTCHAS: Saving an assignment sends the assignee an in-account notification, plus an email if they have email notifications enabled; the wizard returns to the Assignments step afterward so you can add more.
TEST-DATA HINTS: none given.

## WORKFLOW: Configure Contest Plays in the Setup Wizard (Play Types & Fields)
KEYWORDS: create plays, play types, jackpot fields, grand prize, text to win, wizard
JIRA:
---
WHAT: The Create Plays step (Contest Wizard) / Add Contest step (Event Wizard) is where you choose a contest's play type and schedule its plays; field names here are the authoritative Wizard labels.
WHO: Users running the Setup Wizard.
WHERE: Contest PRF Setup Wizard → "Create Plays" step, or Event PRF Setup Wizard → "Add Contest" step.
HOW:
1. Grand Prize: use only when the PRF already has other plays/prizes/winners — schedule it as the last play. Check "Live Drawing" so On Air staff can trigger the draw via the ticket icon on the On Air tab; leave unchecked to restrict triggering to manager permissions via the ticket icon in PRF details.
2. Jackpot Prize: enter Minimum (starting jackpot), Maximum Value (total available), Jackpot Increment (added after each no-winner play), and Low Quantity Warning (remaining value that triggers a notification). On air, staff choose Assign Winner or "No Winner" (the latter auto-adds the increment to the next play).
3. Recurring: pick a date range, weekdays, and time(s); click "Add Time" for additional daily times (e.g., 7:00 a.m. and 3:00 p.m.).
4. Multiple: check "Multiple", enter the count in "Plays per Time", and pick the single date/time in the When field (e.g., 5 Plays per Time on Monday at 10:00 a.m.).
5. Text to Win: enter the contest keyword and shortcode.
6. Add Contest Solicit: check it, then set "Minutes Between Solicit and Winner"; the Copy field becomes "Solicit Copy" and Contest Notes becomes "Winner Copy".
7. Fill Copy (on-air script) and Contest Notes (background info for on-air staff) — both support formatting options.
8. Optionally check "Automatically Return Prizes/Packages to the Prize Closet After Contest" and/or "Off-Air Play(s)" (hides plays from On Air tab).
CONSTRAINTS: Grand Prize requires pre-existing plays/prizes/winners on the PRF. An Off-Air Play cannot be converted to on-air by editing — it must be deleted and recreated as on-air.
GOTCHAS: This Wizard-specific field set (Minimum / Maximum Value / Jackpot Increment / Low Quantity Warning; Plays per Time) should be used as the exact label reference for Wizard-driven tests — see the Contests and Giveaways category for the equivalent Prize-Closet-side workflows (Jackpot Contests, Jackpot Low Quantity Warning, Grand Prize Contest) which describe the same feature from the Prize Closet/PRF Details angle.
TEST-DATA HINTS: Example Recurring contest: weekdays 7:00 a.m., July 13–July 31. Example Multiple: 5 Plays per Time, Monday 10:00 a.m.

## WORKFLOW: Assign Prizes in the Setup Wizard
KEYWORDS: assign prizes, wizard, prize quantity, consolation prize, packages
JIRA:
---
WHAT: The Assign Prizes Wizard step attaches Prizes or Prize Packages (from the Prize Closet) to the plays just created.
WHO: Users running the Setup Wizard.
WHERE: Contest/Event PRF Setup Wizard → "Assign Prizes" step.
HOW: 1. Use the Prize field to select an existing Prize Closet prize, or type a new prize name to create it inline. 2. If assigning a Prize Package instead of an individual prize, select "Packages" rather than "Prizes". 3. Set Quantity to how many units each winner receives (e.g., 1 for a single gift card, 2 for a pair of tickets, 4 for a four-pack). 4. Optionally set a Consolation Prize (and its quantity) for non-winning participants.
CONSTRAINTS: There must be enough available prize quantity to cover all plays being assigned that prize — if the step hangs while loading, check available quantity first.
GOTCHAS: An "Add Qty" button may appear directly in the Prize field, letting you add quantity without leaving the Wizard.
TEST-DATA HINTS: Quantity examples: 1 = one gift card, 2 = a pair of tickets, 4 = a four-pack.

## WORKFLOW: Assign Rules in the Setup Wizard
KEYWORDS: assign rules, wizard, eligibility, new rule
JIRA:
---
WHAT: The Assign Rules (Contest Wizard) / Add Rules (Event Wizard) step attaches eligibility rules to the contest.
WHO: Users running the Setup Wizard.
WHERE: Contest/Event PRF Setup Wizard → "Assign Rules" / "Add Rules" step.
HOW: 1. Open the Rules dropdown, which lists rules available for the PRF's station. 2. Select all rules that apply. 3. Use "+ New Rule" to create a new rule directly from the Wizard instead of going back to Settings.
CONSTRAINTS: Only rules configured for that station appear in the dropdown.
GOTCHAS: Some rules may already be pre-selected if configured as default rules for the station/category.
TEST-DATA HINTS: none given.

## WORKFLOW: Add a Release Form in the Setup Wizard
KEYWORDS: add release, release form, wizard step, station release
JIRA:
---
WHAT: The Add Release Wizard step inserts and lets you customize the station's saved release form for this specific contest.
WHO: Users running the Setup Wizard.
WHERE: Contest/Event PRF Setup Wizard → "Add Release" step.
HOW: 1. The station's saved release form (originally entered in vPromotions Settings) auto-populates. 2. Edit it as needed to add contest-specific information, using the available formatting options. 3. Save/continue.
CONSTRAINTS: The base release form must already exist in Settings for it to auto-populate here.
GOTCHAS: none specified.
TEST-DATA HINTS: none given.

## WORKFLOW: Create Liners in the PRF Setup Wizard
KEYWORDS: create liners, priority, dayparts, frequency, liner merge fields, setup wizard
JIRA:
---
WHAT: Create Liners is the step in the Contest/Event PRF Setup Wizard used to build the on-air liners tied to a promotion.
WHO: Any user with wizard access to the PRF (Contest PRF: final step 6; Event PRF: step 5).
WHERE: Open the PRF, select the wizard icon, and choose Create Liners from the step list.
HOW:
1. Set Priority (e.g., Priority 1 for must-air client-paid liners, Priority 4 for general station-promotion liners) — higher-priority liners are scheduled first and can replace lower-priority ones.
2. Choose a Category — Default unless custom liner categories exist.
3. Optionally restrict scheduling with Day Parts (e.g., limit to the morning daypart) and Days/Rules (e.g., restrict to Wed–Sat, or apply a rule preventing same-time airing on consecutive days).
4. Set Frequency: Run of Schedule, Every Hour, Every Other Hour, Quantity per Selected Daypart (requires Day Parts selected), or Quantity per Day.
5. Set Start Time and End Time (date + hour/minute) to control the liner's active window.
6. Optionally select Create Multiple Versions to build Version A/Version B copy for different clients, and enter a Client name (defaults to the PRF's client if left blank).
7. Insert Liner Merge Fields (shown as text in double brackets) into the Copy field to auto-pull contest/PRF/winner data.
8. Enter the on-air Copy and any Notes for on-air staff; both fields support formatting and hyperlinks.
9. Select Save to advance, Skip to move on without changes, Back to return to the previous step, or Close to exit and finish later.
CONSTRAINTS: Day Parts and Days/Rules only restrict when a liner CAN run — they do not force a specific air time. Quantity per Selected Daypart requires at least one Day Part to be selected. Dayparts must already exist in vPromotions settings or none will appear as options.
GOTCHAS: Leaving Day Parts/Days blank does not mean "never scheduled" — it means "no restriction," so the liner can air any time/day in the date range. Client field left blank silently falls back to the PRF's client.
TEST-DATA HINTS: Priority 1, Category "Default", Frequency "Run of Schedule", Start Time/End Time spanning the promotion's on-air window.

## WORKFLOW: Add Special Instructions in the Event PRF Setup Wizard
KEYWORDS: special instructions, event wizard, setup location, arrival instructions
JIRA:
---
WHAT: Add Special Instructions is step 2 of the Event PRF Setup Wizard, used to record details the on-site team needs to know.
WHO: Any user completing the Event PRF Setup Wizard.
WHERE: Open the Event PRF, select the wizard icon, choose Add Special Instructions.
HOW: Enter free-text details such as the setup location, client contact information, arrival instructions, parking details, or other notes team members need before working the event, then Save to advance.
CONSTRAINTS: None beyond standard wizard navigation (Save/Skip/Back/Close).
GOTCHAS: This field is separate from Add Location — use it for logistics/context, not the physical address itself.
TEST-DATA HINTS: "Enter through the loading dock on 5th Ave; ask for the event manager on arrival; parking validated at the front desk."

## WORKFLOW: Add Location in the Event PRF Setup Wizard
KEYWORDS: add location, event wizard, mapping, where field, create link
JIRA:
---
WHAT: Add Location is step 3 of the Event PRF Setup Wizard; it auto-populates the event address and generates a map link for the on-site team.
WHO: Any user completing the Event PRF Setup Wizard.
WHERE: Open the Event PRF, select the wizard icon, choose Add Location.
HOW:
1. The Where field is pre-filled automatically from the PRF's Location field.
2. Select Create Link to search for the location using a mapping application on your device.
3. Select the generated link to confirm it points to the correct place.
4. If incorrect, delete the text in Where, enter a more precise address, and select Create Link again.
CONSTRAINTS: The Where field's accuracy depends on how Location was entered on the original PRF.
GOTCHAS: Always verify the created map link before relying on it for event-day navigation — imprecise addresses can generate an incorrect link.
TEST-DATA HINTS: "123 Main St, Springfield, IL 62701" as the Where value.

## WORKFLOW: Assign Equipment in the Event PRF Setup Wizard
KEYWORDS: assign equipment, equipment list, event wizard, equipment package
JIRA:
---
WHAT: Assign Equipment is step 4 of the Event PRF Setup Wizard, used to specify what gear the on-site team should bring.
WHO: Any user completing the Event PRF Setup Wizard; equipment lists are configured separately at the market level.
WHERE: Open the Event PRF, select the wizard icon, choose Assign Equipment.
HOW: Select the Equipment field and choose individual equipment items or pre-built equipment packages to attach to the event, then Save.
CONSTRAINTS: If no items appear in the Equipment field, an equipment list has not yet been created for the market — it must be set up before it can be assigned here.
GOTCHAS: An empty Equipment field is a setup problem, not a bug — check the market's equipment list configuration first.
TEST-DATA HINTS: Equipment item "Wireless PA System", equipment package "Remote Broadcast Kit".

## WORKFLOW: Generate and Send the Event PA Sheet
KEYWORDS: event pa sheet, actions menu, equipment checklist, send email
JIRA:
---
WHAT: The Event PA Sheet is a one-page document compiling the information entered through the Event PRF Setup Wizard for on-site team use.
WHO: Any user with access to the PRF details/Actions menu.
WHERE: Open the PRF details and select Event PA Sheet from the green Actions menu.
HOW:
1. Open the PRF and select Event PA Sheet from the Actions menu to view the compiled sheet (event title/client, start/end date-time, location, Default Event Notes, special instructions, assigned team members and mobile numbers, equipment checklist, on-site contests/prizes, PRF blog messages, and PRF details).
2. To update equipment status, use Equipment In/Out (located beneath Event PA Sheet in the Actions menu) to check items in/out and note damaged, missing, or problematic equipment — these selections automatically populate the Event PA Sheet's equipment section.
3. Select Send Email at the bottom of the sheet to email it to everyone assigned to the PRF.
CONSTRAINTS: Default Event Notes must be pre-configured under Settings > vPromo > Default Event Notes to appear automatically on the sheet.
GOTCHAS: Equipment check-in/out notes are entered in the separate Equipment In/Out tool, not directly on the PA Sheet itself.
TEST-DATA HINTS: n/a (compiled/read-only document sourced from other wizard steps).

## WORKFLOW: Submit a New PRF (Promotion Request Form)
KEYWORDS: new prf, submit prf, prf category, auto-fill, calendar
JIRA:
---
WHAT: Submitting a PRF is the only way to add a promotion to the vPromotions Calendar and begin its approval process.
WHO: Any user with PRF-submission access; available PRF Categories depend on the user's assigned abilities.
WHERE: Click the green + New PRF button in the upper left of the vPromotions Calendar.
HOW:
1. Click + New PRF.
2. Choose one or more Categories needed for the promotion (e.g., Remote, Contest, Web Content).
3. Fill out the form completely; fields shown depend on the Category/Categories selected.
4. Click Save.
Best practice for multi-category PRFs: choose the first category and fill it out completely first, then add additional categories and fill in only the remaining fields — this maximizes auto-fill accuracy.
CONSTRAINTS: When multiple categories are chosen, fields with identical names across categories auto-fill from the first category's entries. Run Dates never auto-fill (each category keeps its own). Stations only auto-fill from the first station entered into the first category's form.
GOTCHAS: Auto-filled fields can still be edited per-category if the content should differ (e.g., different liner copy for Remote vs. Web Content) — auto-fill is a convenience default, not a lock.
TEST-DATA HINTS: Categories "Remote" + "Web Content" sharing fields Title, Description, Liner Copy, Total Buy.

## WORKFLOW: Understand PRF Fields and Category-Based Field Display
KEYWORDS: prf fields, prf builder, custom fields, category fields
JIRA:
---
WHAT: PRF Fields are the form inputs that appear based on which Category (or Categories) are selected on a PRF.
WHO: Any user filling out a PRF (viewing behavior); Promotions Directors configure fields via PRF Builder.
WHERE: Fields appear dynamically below the Category selector on the PRF form, grouped under a heading for each chosen Category. Field configuration lives at Settings > Promo > PRF Builder.
HOW: As Categories are added to a PRF, fields specific to each Category appear under that Category's heading. A field shared by multiple selected Categories appears only once (under the first Category requiring it), but any value entered is copied into all Categories that need it.
CONSTRAINTS: Field customization (adding/removing/reordering fields per Category) requires Promotions Director access to the Custom PRF Builder.
GOTCHAS: A field appearing to "belong" to only one Category visually can still supply its value to other selected Categories behind the scenes — don't assume a blank-looking section means the data wasn't captured.
TEST-DATA HINTS: n/a (structural/UI-behavior reference).

## WORKFLOW: Set Up a Corporate PRF Category
KEYWORDS: corporate prf category, multi-market, standardize form, promotions director
JIRA:
---
WHAT: A Corporate PRF Category shares one standardized PRF Category and form across every market (firm) in a company, enabling multi-market submission.
WHO: Requires Promotions Director, Program Director, or General Manager ability, combined with "Large Multi-Market User" ability, and membership in the Corporate Firm.
WHERE: Settings > vPromo (or Promo) > PRF Categories, and Settings > vPromo > PRF Builder, within the corporate firm.
HOW:
1. Go to Settings > Promo > PRF Categories and create the PRF Category (skip if it already exists).
2. Go to Settings > Promo > PRF Builder and edit the form fields as needed.
3. Notify local markets of the upcoming change.
4. In the corporate firm, go to Settings > vPromo > PRF Categories, find the "Corporate PRF" column, and check the box for the category.
5. Confirm by clicking Make Corporate (or click Close to cancel) in the confirmation message.
CONSTRAINTS: If a local market already has a PRF Category with the exact same name, the corporate version replaces it locally; removing the corporate designation restores the original local category and form.
GOTCHAS: Each PRF Category has its market (firm) name appended, and only stations from that market can be selected under it — the Corporate PRF Category is what allows selecting stations across multiple markets in one submission.
TEST-DATA HINTS: Category name "Contest" being standardized and shared corporately.

## WORKFLOW: Configure a Quick Contest PRF for PDs/Promotions Directors
KEYWORDS: quick contest prf, prf category visibility, auto-start wizard, program director
JIRA:
---
WHAT: A short, minimal-field PRF Category that lets Program/Promotions Directors create a PRF container quickly and jump straight into the Setup Wizard.
WHO: Program Directors and Promotions Directors configuring the category; visibility can be restricted to specific abilities/roles.
WHERE: Settings > Promo > PRF Categories (create category + set Visibility); Settings > Promo > PRF Builder (trim fields); Settings > User > General Settings (auto-start wizard option).
HOW:
1. Go to Settings > Promo > PRF Categories and add a new PRF Category; in the Visibility field, select the role(s) allowed to use it.
2. Go to Settings > Promo > PRF Builder, select the new category, and delete unwanted fields (the first 5 fields are always required); add any additional fields needed.
3. Go to Settings > User > General Settings, check "As soon as I submit a PRF start the Wizard," and Save Changes.
CONSTRAINTS: The first 5 fields on any PRF Builder form cannot be removed. Only users with the Ability chosen in Visibility will see this Category when creating a New PRF.
GOTCHAS: Everyone can still see the resulting PRFs on the Calendar even though only authorized roles can create them using this shortened category.
TEST-DATA HINTS: n/a (settings-configuration workflow).

## WORKFLOW: Create and Manage a Campaign PRF
KEYWORDS: campaign, sub-prf, multi-station, move prf, campaign recap
JIRA:
---
WHAT: A Campaign groups multiple promotional PRFs (Sub-PRFs), potentially across multiple stations, together on the Calendar.
WHO: Requires access to the Campaign category in the PRF Category selector, granted by a Promotions Director; Promotions/Program Directors can request the Campaign category be added via Settings > vPromo > PRF Categories.
WHERE: Click the green + New PRF button and choose Campaign as the first Category; manage via the Calendar or the Campaigns tab at the top of the Calendar screen.
HOW:
1. Click + New PRF and select Campaign as the first selection — all categories added afterward are contained within the campaign.
2. Set the run dates to encompass the entire campaign and include all stations that are part of it, then Save.
3. Find the campaign on the Calendar (click the campaign item, then "Open Campaign" to see only items within it — click "Exit Campaign" in the blue banner to return) or via the Campaigns tab (click the "+" next to the campaign name to expand its promotions).
4. Add additional PRFs to the campaign from either screen.
5. To move an existing PRF into a campaign: click the PRF on the Calendar, click Move (below Make Recurring) on the popover, choose the campaign from the dropdown, and click Move & Save.
6. To move a PRF out: click it, click Move, choose "Move Out of Campaign" (or another campaign), and click Move & Save.
CONSTRAINTS: A Campaign itself has no approval process, but each Sub-PRF inside it is approved individually. A PRF can only be moved into a campaign if it falls within the campaign's run dates, is on a station included in the campaign, and has not yet started.
GOTCHAS: Sponsorships for multi-station opportunities are tracked from the Campaign's Details > Sponsorship tab, not from an individual Sub-PRF. A full campaign recap (covering all promotions inside it) is generated via the Campaign's Actions menu > Promotion Recap.
TEST-DATA HINTS: n/a (structural workflow).

## WORKFLOW: Submit a Production Order via Advanced vPPO Integration
KEYWORDS: vppo integration, production order, vppo tab, take me to it
JIRA:
---
WHAT: Advanced vPPO Integration lets a PRF submit complete production orders (audio, video, graphics, digital) directly to vPPO without leaving vPromotions.
WHO: Requires the vPPO tab to be visible on the PRF Details (enabled by a Firm Administrator) and the Can View/Can Create vPPO Production Orders ability.
WHERE: Open the PRF Details and select the vPPO tab.
HOW:
1. Open the PRF Details and click the vPPO tab (if missing, ask the Firm Administrator to activate vPPO Integration).
2. Click +Add New to add production items (spots) — all items added on one PRF share the same Production Order in vPPO.
3. Use the Take Me To It icon to jump directly to the spot in vPPO, the Upload Files To This Spot icon to attach a production file, or the Copy This Spot icon to duplicate a spot's info into a new spot on the same PRF.
CONSTRAINTS: Once a vPPO Production Order is submitted from vPromotions, all further changes to that order must be made in vPPO, not vPromotions.
GOTCHAS: The vPPO tab will not appear at all until a Firm Admin completes the separate vPromotions-vPPO Integration Set-Up.
TEST-DATA HINTS: n/a (integration workflow).

## WORKFLOW: Order Production via vPPO Packages on a PRF
KEYWORDS: vppo packages, ad type, audio production, digital production
JIRA:
---
WHAT: The vPPO Packages field on a PRF lets a submitter select pre-defined production packages (audio and/or digital) that are automatically sent to vPPO upon PRF approval.
WHO: Any user filling out a PRF Category on which vPPO is enabled by the Firm Admin.
WHERE: The "vPPO Packages" dropdown field on the PRF form (only present when vPPO is enabled for that Category).
HOW:
1. Select one or more packages from the vPPO Packages dropdown.
2. For Audio Production packages, fill in the Script and Production Notes fields that appear.
3. For Digital Production packages, fill in the Digital URL and Digital Notes fields that appear (packages with both ad types show all 4 fields).
4. Attach any files via the "+Click Here To Add File" field — these are sent to vPPO as Files on the resulting Quick Order; more files can be added directly in vPPO afterward.
5. After submission, users with Can View/Can Create vPPO Orders can track status from PRF Details > vPPO tab, and click "Take Me To It" to open the vPPO Quick Order directly.
CONSTRAINTS: The vPPO Packages field only appears on PRF Categories where vPPO has been enabled.
GOTCHAS: Files attached in vPPO itself (after PRF submission) sync back and remain visible/downloadable from the PRF's Files tab in vPromotions.
TEST-DATA HINTS: n/a (integration workflow).

## WORKFLOW: Review PRF Activity History
KEYWORDS: prf history, activity tracking, plays history, prize history
JIRA:
---
WHAT: vPromotions tracks a detailed, timestamped activity history of changes made to a PRF.
WHO: Any user with PRF Details access.
WHERE: PRF Details > History (lists newest activity first, with a scroll bar to review older entries and a "More" link for extra detail).
HOW: Open the PRF Details and view History to see tracked activity including Plays (added/edited), Liners (added/edited), Files (added), Sponsorships, Equipment, PRF Creation and Approval, and PRF Edits.
CONSTRAINTS: Not all activity lives in this single History log — some activity types are tracked in dedicated tabs instead.
GOTCHAS: Adding/removing prizes is tracked in Prize History (not PRF Details History); assigning/accepting/completing tasks is tracked under People; assigning winners, claiming, and forfeiting are tracked in the Details/Plays tab. Check the correct location if an expected entry isn't in the main History log.
TEST-DATA HINTS: n/a (reference/read-only feature).

## WORKFLOW: Track a PRF Through the Approval Process
KEYWORDS: prf approval, sales manager approve, denied, category-based approval
JIRA:
---
WHAT: Every submitted PRF moves through a sequential approval chain before the promotion goes live.
WHO: Typical chain is Sales Person (submits) > Sales Manager approves > Promotions Director approves > Program Director approves > Promotion is Live; exact roles/order vary per station and can use Category-Based Approval Process for per-category chains.
WHERE: Click the PRF's calendar item to open a popover showing where it currently sits in the approval process.
HOW: Submit the PRF; a faded/colorless calendar item indicates it has not yet been approved. Click the calendar item to see the current approval stage. Once fully approved, the item displays in full color on the Calendar.
CONSTRAINTS: If a PRF is denied, the denying approver must enter a reason; the PRF returns to the original submitter, who can cancel it or edit and resubmit for approval.
GOTCHAS: Each station's approval process can differ, so the same category may require different approvers depending on station. To set up or change an approval chain, contact vCreative's Help Desk (self-service configuration is not shown here).
TEST-DATA HINTS: n/a (process/status reference).

## WORKFLOW: Manage Files on a PRF
KEYWORDS: files tab, upload file, download multiple files, file size limit
JIRA:
---
WHAT: The Files tab in PRF Details centralizes every file attached to a promotion, regardless of where it was uploaded.
WHO: Any user with PRF Details access.
WHERE: PRF Details > Files tab.
HOW:
1. Open PRF Details > Files to see files attached on the original PRF, uploaded from the On Air tab, or uploaded directly to the Files tab.
2. Click the preview button to listen to or view a file before downloading.
3. Select multiple files and download them together, or download all files on the PRF at once (ensure your browser's pop-up blocker is disabled for vPromotions).
CONSTRAINTS: Maximum file size is 100MB. Executable file types (e.g., .exe) and other potentially harmful file types cannot be uploaded.
GOTCHAS: Multi-file download silently fails to open new tabs if a pop-up blocker is active — disable it first.
TEST-DATA HINTS: n/a (file-management workflow).

## WORKFLOW: Add a Sales Assignment Field to a PRF Category
KEYWORDS: sales assignment field, prf builder, allow multiple, dropdown field
JIRA:
---
WHAT: The Sales Assignment field lets whoever submits a PRF assign a salesperson directly on the form, instead of adding them after submission.
WHO: Requires Promotions Director, Program Director, or General Manager ability to configure; once configured, any submitter can use the field.
WHERE: Settings > vPromo > PRF Builder.
HOW:
1. Drag a new Dropdown field from "New Fields" to the left of the field list for the target Category.
2. Name the field exactly "Sales Assignment" (one space between the words).
3. Click outside the field to trigger the confirmation message.
4. Check "Allow Multiple" — required for the field to function correctly.
5. Drag the completed field to the Field Clipboard, then drag it from the Clipboard onto any other PRF Category forms where it's needed; reorder with up/down as desired.
CONSTRAINTS: The field name must be exactly "Sales Assignment"; "Allow Multiple" must be checked. The dropdown auto-populates with everyone holding "Sales Person" or "Sales Manager" ability for the stations selected on that PRF.
GOTCHAS: Place the Sales Assignment field below the Station selector on the form — if placed above, the field can clear itself when a station is chosen for which the previously selected salesperson has no access.
TEST-DATA HINTS: Field label "Sales Assignment", "Allow Multiple" checked.

## WORKFLOW: Use Special PRF Fields That Auto-Populate the Wizard
KEYWORDS: liner copy field, play copy field, prize information field, pa need field
JIRA:
---
WHAT: Certain exactly-named PRF Builder fields automatically feed their values into the Contest/Event Setup Wizard, avoiding duplicate data entry.
WHO: Promotions/Program Directors configuring PRF Builder forms.
WHERE: Settings > vPromo > PRF Builder — fields must be newly created (not renamed from existing fields) with the exact label shown.
HOW: Add a new field with one of these exact labels and type to auto-populate the corresponding Wizard location: "Liner Copy" [Long Text] to the Wizard's liner copy area; "Liner Notes" [Long Text] to each Liner's notes area; "Play Copy" [Long Text] to each Play's contest copy area; "Play Notes" [Long Text] to each Play's contest notes area; "Location" [Short Text] to the Event Wizard's Location field (also creates a Google Maps link); "Prize Information" [Long Text] to the Prize Description field in Prizes On The Fly; "Prize Value" [Number] to the Prize Value field in Prizes On The Fly; "PA Need" [Number] to create sign-up openings for Promotions Assistants on-site; "Sales Assignment" [Dropdown, Allow Multiple checked] to assign a salesperson from the PRF.
CONSTRAINTS: The field must be newly created with the exact label text shown — renaming an existing field will not trigger auto-population. Field data types must match (e.g., Long Text vs. Short Text vs. Number vs. Dropdown) as specified.
GOTCHAS: A mismatched field type (e.g., Short Text instead of Long Text) or a slightly different label will silently break the auto-populate link with no error shown.
TEST-DATA HINTS: Field label "Liner Copy" (Long Text), field label "PA Need" (Number) with value 3 for three PA sign-up slots.

## WORKFLOW: Run the Promotions-Initiated Proposal Workflow
KEYWORDS: idea proposal workflow, create proposal, release to sales, sold it, create prf
JIRA:
---
WHAT: Lets Promotions initiate a sponsorship/promotion proposal and hand it to a salesperson to sell, later converting it into a PRF once sold.
WHO: Firm Admins activate the feature; Promotions Directors create and release proposals; salespeople (Account Executives) receive, sell, and convert them.
WHERE: Settings > Firm > Firm Options (activation); Proposals tab on the Main/Home Calendar (usage).
HOW:
1. A Firm Admin checks "Enable Proposal Workflow" in Settings > Firm > Firm Options and clicks Save Changes — this adds the +Idea button and Proposals tab to the Home Calendar. An IRF approval process must then be created (include only approver roles, not the salesperson who requests).
2. From the Proposals tab, click Create Proposal to open the Proposal form; propose a New Promotion, an existing Sponsorship (from a PRF's Details > Sponsorships), or both, specifying what the station and client each provide and their values.
3. Click Save to store the Proposal for later editing.
4. Click the blue "Release to Sales" button (icon with salespeople) to send it to the assigned salesperson.
5. The salesperson clicks the green "Sold It!" button once the client confirms.
6. After the sale is confirmed, click Create PRF from the Proposals tab to convert any New Promotion elements into a standard PRF, which then follows the normal approval workflow.
CONSTRAINTS: The IRF approval process must be set up separately after activation, and should only include approver roles (not the requesting salesperson).
GOTCHAS: Only "New Promotion" proposal elements convert into a PRF via Create PRF — existing Sponsorship elements are tracked/sold through the sponsorship record itself.
TEST-DATA HINTS: n/a (multi-role workflow).

## WORKFLOW: Create a Recurring Promotion
KEYWORDS: make recurring, recurring promotion, date range, weekly remote
JIRA:
---
WHAT: Make Recurring duplicates an existing PRF's calendar item across a repeating day-of-week schedule within a date range, such as a weekly remote.
WHO: Any user with PRF edit access.
WHERE: Click the PRF's calendar item, then click "Make Recurring" in the upper right of the popover.
HOW:
1. Submit the original PRF first.
2. Click its calendar item, then click Make Recurring.
3. Choose the day(s) of the week the promotion should recur.
4. Enter the start of the recurrence date range — this must be a date AFTER the original calendar item's date.
5. Enter the end date for the recurrence.
6. Click Save; each occurrence is added to both the Calendar and the approval queue.
CONSTRAINTS: The recurrence start date must be later than the original PRF's date.
GOTCHAS: Each recurring occurrence enters the approval queue separately — recurring does not bypass approval for the additional dates.
TEST-DATA HINTS: Days "Monday, Wednesday, Friday", date range one month out from the original PRF date.

## WORKFLOW: Understand Real-Time PRF Updates and Concurrent Viewers
KEYWORDS: real time updates, concurrent editing, viewers count, prf conflict
JIRA:
---
WHAT: vPromotions pushes PRF additions and edits to all viewers immediately, without requiring a manual page refresh.
WHO: Any user viewing the Calendar or a PRF's Details.
WHERE: Calendar (new PRFs appear live) and PRF Details (edits from other users appear live); viewer/notification counts display just above the Actions button.
HOW: Add or edit a PRF as normal — other users viewing the same Calendar or PRF Details see the change appear automatically after it's saved, with no refresh needed. Check the indicator just above the Actions button to see how many Viewers are currently in that PRF, and a separate notification count for co-workers who have recently clicked into the details.
CONSTRAINTS: If two users edit the same PRF simultaneously, whichever user saves last overwrites the other's unsaved changes — the earlier save is discarded, not merged.
GOTCHAS: There is no conflict warning before this overwrite occurs — check the Viewers count to know if someone else is in the PRF before making edits.
TEST-DATA HINTS: n/a (real-time UI behavior reference).

## WORKFLOW: Track Assigned Tasks Across a Market
KEYWORDS: assigned tasks, my assigned tasks, tasks badge, task filters
JIRA:
---
WHAT: Lets Market Managers, Promotions Directors, and Program Directors view and manage tasks they've assigned, in addition to their own tasks.
WHO: Market Managers, Promotions Directors, Program Directors (with the ability to see assigned/all tasks).
WHERE: Tasks tab on the Home Calendar, or the Tasks Badge in the upper right of vPromotions.
HOW:
1. Open the Tasks tab or click the Tasks Badge.
2. Use the "Showing" field to switch between My Tasks, My Assigned Tasks, and All Assigned Tasks.
3. Use the two filter buttons to show/hide Completed Tasks and Pending Tasks.
4. Use the Actions available on a task: Blog (message the person assigned to the task), Edit (reassign the task or change its due date/time), or Delete (remove a task you assigned).
CONSTRAINTS: Incomplete tasks that were due more than 30 days ago no longer display in the task list.
GOTCHAS: A task that seems to have "disappeared" may simply be over 30 days past due and no longer shown — check completed records elsewhere if you need that history.
TEST-DATA HINTS: n/a (task-management reference).

## WORKFLOW: Copy Plays, Liners, and Sponsorships from a Copied PRF
KEYWORDS: copy prf, copy elements, copy plays, copy liners, copy sponsorships
JIRA:
---
WHAT: When copying a PRF, Plays, queued Liners, and Sponsorship opportunities can be copied along with it, with dates automatically adjusted to the new PRF's schedule.
WHO: Requires Promotions Director, Program Director, or General Manager ability.
WHERE: PRF Details > Actions > Copy PRF (initial copy); PRF Details > Actions > Copy Elements (to copy later or copy items added after the initial copy).
HOW:
1. From the original PRF's Details, click Actions > Copy PRF, adjust dates and other fields as needed, and click Save.
2. On the resulting screen, check the boxes for Plays, Queued Liners, and/or Sponsorships to copy (Play dates/times, Liner run dates, and Sponsorship dates are all adjusted based on the new PRF's dates).
3. Click Copy Elements to complete the copy.
4. To copy additional items later (including ones added to the original PRF after the initial copy), open the copied PRF (it displays a "copy" icon next to its title), click Actions > Copy Elements, and select what to copy.
CONSTRAINTS: Copying Queued Liners only works for stations using Priority-Based Liner Scheduling.
GOTCHAS: Copy Elements can also be used to pull Plays/Liners/Sponsorships into a PRF that Sales copied from another PRF, and doubles as a way to navigate back to the original source PRF.
TEST-DATA HINTS: n/a (copy workflow).

## WORKFLOW: Set PRF Calendar Visibility by Day/Date Range
KEYWORDS: calendar visibility, show on calendar, contest days, actions menu
JIRA:
---
WHAT: PRF Calendar Visibility controls which specific days/date ranges a Contest or Content-type promotion displays on the Home Calendar, without needing separate PRFs.
WHO: Any user with PRF Details/Actions access.
WHERE: Two entry points — PRF Details > Actions > Calendar Visibility, or the Contest Wizard's Plays tab.
HOW:
Option 1 (Actions menu): Open the promotion's Details tab, click Actions, choose "Calendar Visibility," then select the date ranges and days of the week the promotion should appear on the Home Calendar.
Option 2 (Contest Wizard): On the Plays tab of the Contest Wizard, just below the Days field, check "Only show the PRF on the calendar on these days" to limit calendar display to the days of the week chosen for scheduling Plays.
CONSTRAINTS: The Contest Wizard checkbox option only considers days of the week, not the specific dates on which Plays are scheduled.
GOTCHAS: A multi-week Monday–Friday contest can be managed as a single PRF (editing all Plays/Liners in one place) while still only displaying on the Calendar for the applicable days — no need to split it into separate PRFs per week.
TEST-DATA HINTS: Days of week "Monday–Friday" for a multi-week contest.
