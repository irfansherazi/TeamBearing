# vPromotions Help Center — FAQ
# =============================================
# Source: https://vcreativeinc.com/knowledge/vpromotions#faq
# Extracted: 2026-07-27
# Product-scoped: only loaded for vpromotions runs.

## WORKFLOW: Adjust Calendar Filters When PRFs Are Missing from the Calendar
KEYWORDS: calendar filters, blank calendar, missing PRF, station filter, quick filter
JIRA:
---
WHAT: vPromotions calendars are per-user and filtered; a "blank calendar" or missing PRFs is almost always a filter setting, not a data problem.
WHO: Any vPromotions user; filters are personal to each account.
WHERE: Home Calendar page. Type filters (Events, Contests, Content) and view filters (Month, Week, 4 Week) sit directly on the calendar. More filters are under the Blue Funnel Filter Icon.
HOW:
1. On the Home Calendar, confirm the Events, Contests, and Content type filters are toggled on — a bright color means on/showing, a shaded color means off/hidden.
2. Pick a view: Month, Week, or 4 Week.
3. Click the Blue Funnel Filter Icon to reveal: a Search box (search by PRF title, client, or station), a Sub PRF's toggle (hides Campaign sub-PRFs), a Stations checklist, a Statuses checklist, and a Category checklist.
4. Verify every Station you need is checked — an unchecked station hides all its PRFs.
5. Verify Statuses and Categories you want to see are checked; best practice is to leave all Categories on.
6. To save a reusable combination, click the blue plus sign to create a Quick Filter.
CONSTRAINTS: A PRF is hidden if ANY of its Type, Station, Status, or Category filter is off.
GOTCHAS: On the calendar, a small orange "c" marks Contests, a small blue "e" marks Events, and a small green "c" marks Content type PRFs — use these to sanity-check what type a hidden PRF might be.
TEST-DATA HINTS: none given.

## WORKFLOW: Edit or Revise a PRF After Submission
KEYWORDS: edit PRF, revise PRF, PRF locked, revision process, PRF blog, actions menu
JIRA:
---
WHAT: What a Sales user can change on a PRF depends on its approval stage; fully-approved PRFs require a formal Revision instead of a direct edit.
WHO: Sales people have stage-limited edit rights; Promotions Directors and Program Directors can edit PRFs at any time.
WHERE: PRF Details page, Actions menu (Edit, Delete, Cancel, Revise); PRF Blog for messaging.
HOW:
1. Before the first approval: open the PRF Details, use the Actions menu, and choose Edit, Delete, or Cancel freely.
2. During the approval process (after first approval, before Live status): do not attempt inline edits — send a message via the PRF Blog asking the Promotions or Program Director to make the change.
3. On a fully approved/Live PRF: open the Actions menu and choose Revise. Make the desired changes on the revision copy.
4. Submit the revision; it routes through the same approval chain as the original PRF.
5. If approved, the Revision replaces the Original. If denied, the Original is unlocked and the Revision is discarded.
CONSTRAINTS: If a first approval occurs while a sales person is mid-edit, the edit closes without saving. The Original PRF is LOCKED (no adding People, Plays, Equipment, Liners) while its Revision is pending approval.
GOTCHAS: Promotions/Program Directors bypass all of this and can edit at any time. For small, quick changes, a PRF Blog message is often faster than starting the Revision process.
TEST-DATA HINTS: none given.

## WORKFLOW: Respect the 100 MB Per-File Upload Limit
KEYWORDS: file upload, max file size, attachment limit, upload error
JIRA:
---
WHAT: vPromotions accepts almost any file type for upload, but enforces a hard per-file size cap.
WHO: Any user uploading files/attachments in vPromotions.
WHERE: Any file upload control within vPromotions (PRF attachments, prize documents, etc.).
HOW: 1. Select the file to attach. 2. Confirm the file is under the size limit before uploading. 3. If the upload fails, check the file size first.
CONSTRAINTS: Maximum file size is 100 MB per file; larger files will not upload.
GOTCHAS: There is no bulk/aggregate limit mentioned — the cap is strictly per individual file.
TEST-DATA HINTS: Limit value: 100 MB.

## WORKFLOW: Write Winner Email Subject Lines That Avoid Spam Filters
KEYWORDS: spam filter, winner email, email deliverability, subject line, phishing
JIRA:
---
WHAT: Winner notification emails can land in spam due to sender domain trust and subject-line wording, not vPromotions malfunction.
WHO: Any user setting up or sending Winner Emails/templates.
WHERE: Winner Email templates (Prize or Prize Package email settings).
HOW: 1. Note that all winner emails send from "[YourStationName]@vprizecloset.com", matching the Station Name shown in Station Filters on the Home Calendar and in Settings/Firm/Stations. 2. When writing the subject line, avoid urgency language, exaggerated claims (e.g. "everybody wins"), all-caps text, and excessive exclamation marks. 3. Avoid trigger words like win, free, sale, offer, urgent, last chance, and claim your prize. 4. Limit the number of hyperlinks in the email body.
CONSTRAINTS: The "from" domain is fixed by the system (vprizecloset.com) and cannot be changed per user.
GOTCHAS: A properly matched sender domain is what prevents "phishing" flags — this is a system-level safeguard, not something to configure per email.
TEST-DATA HINTS: Example from-address pattern: "[YourStationName]@vprizecloset.com".

## WORKFLOW: Add a New Employee/User to vPromotions
KEYWORDS: new employee, add user, sign up, register, onboarding
JIRA:
---
WHAT: New team members self-register their own vPromotions/vPPO account rather than being created by an admin.
WHO: Any new employee needing access; no special permission required to self-register.
WHERE: Login page at vcreative.net, "sign up now" link.
HOW: 1. Direct the new employee to vcreative.net. 2. Click "sign up now". 3. For onboarding docs, use the direct registration link "https://vcreative.net/#/register".
CONSTRAINTS: None specified beyond self-service sign-up.
GOTCHAS: This preserves password privacy and lets each user choose their own username — admins should not create accounts on a user's behalf.
TEST-DATA HINTS: Registration URL: https://vcreative.net/#/register.

## WORKFLOW: Run a Year-End Prize Report for 1099 Reporting
KEYWORDS: year end report, 1099, tax id, prize report, dupe detector
JIRA:
---
WHAT: The Year End Prize Report compiles winners who crossed the $600 taxable threshold so their 1099-MISC forms can be printed.
WHO: Requires "Tax ID Access" ability to view winners' Social Security Numbers; typically Firm Admins/Promotions Directors.
WHERE: Main Menu (hover over your name, upper right) → Reports → Year End Prize Report.
HOW:
1. Before running, go to Settings / vPromo / Winners and run the Dupe Detector to merge duplicate winner records.
2. Hover your name (upper right) → Reports → Year End Prize Report.
3. Enter the report date range and exclude any Contests whose prize 1099s are issued by a third-party promotional partner.
4. Click the blue "Generate Report" button; an orange confirmation message appears while the report is generated and emailed.
5. From the emailed link, log in again (in the same browser you're already logged into vPromotions with) to view the report.
6. Click the blue "PRINT 1099's" button at the top center of the report page.
7. Leave "print guidelines" checked to print on special 1099 blanks using the "Copy" buttons per copy; uncheck it to print winner info only onto pre-printed 1099 MISC forms (Copy A, Copy B).
CONSTRAINTS: Only winners with a cumulative $600+ in Claimed prizes for the period appear. Unclaimed prizes must be marked Claimed first. Data not imported into vPromotions won't appear.
GOTCHAS: Viewing the report in a different browser than the one you're logged into vPromotions with will fail to decrypt SS# data (see related "Error in SS# Field" workflow).
TEST-DATA HINTS: Taxable threshold: $600.

## WORKFLOW: Activate Idea/Proposal Request Workflow
KEYWORDS: proposal workflow, idea request, firm options, IRF approval, enable feature
JIRA:
---
WHAT: Idea/Proposal Request (IRF) Workflow is an optional Firm-level feature that adds a sales-facing idea submission and approval process.
WHO: Only a Firm Admin can enable this (requires the Firm tab in Settings).
WHERE: Settings (hover your name, upper right) → Firm tab → Firm Options.
HOW:
1. Go to Settings from the Main Menu.
2. Click the Firm tab (if absent, you are not a Firm Admin).
3. Choose Firm Options.
4. Check the "Enable Proposal Workflow" checkbox.
5. Click Save Changes.
6. Set up the IRF Workflow Approval Process: enter your customized approval sequence and add the roles that will approve proposals (do not include the sales role, since they are the requester).
7. Click Save Process.
CONSTRAINTS: Only Firm Admins can access Firm Options/enable this feature.
GOTCHAS: Enabling this adds the "+Idea" button for Sales and a Proposals Tab for relevant roles — expect UI changes firm-wide once saved.
TEST-DATA HINTS: none given.

## WORKFLOW: Reduce Blog and Approval Notifications for Manager Roles
KEYWORDS: blog notifications, approval notifications, notification settings, manager role, general settings
JIRA:
---
WHAT: Manager-level roles (Sales Mgr, Promo Dir, PD, GM) can receive blog/approval notifications for every station by default and may want to narrow that scope.
WHO: Any manager role account; Firm Administrators can also change this on behalf of a user.
WHERE: User settings → General Settings, with four controls: "Receive Approval Task Notifications for" (stations), "Receive Approval Task Notifications for these categories" (Events, Contests, Content), "Receive Blog Notifications for" (stations), "Receive Blog Notifications for these categories" (Events, Contests, Content).
HOW (self-service): 1. Open your User Settings. 2. Go to General Settings. 3. Uncheck stations/categories you don't need notifications for. 4. Save.
HOW (admin, for another user): 1. Go to Settings / Firm / People. 2. Click the Edit icon in the Action column next to the user's name. 3. Choose the General Setting tab. 4. Adjust the four notification controls. 5. Save.
CONSTRAINTS: Removing a station from Blog Notifications only stops broad blog notifications for that station — the user still receives blog notifications for any PRF where they're explicitly assigned in the People tab.
GOTCHAS: Category and Station notification controls are separate for Approval Tasks vs. Blog Notifications — all four must be checked to fully suppress a given source.
TEST-DATA HINTS: Category options are Events, Contests, Content.

## WORKFLOW: Create a Variable Cash Prize for Contests with Different Payout Amounts
KEYWORDS: variable cash prize, cash contest, prize type, variable amount
JIRA:
---
WHAT: To give away cash prizes where winners can receive different dollar amounts within the same contest, use the "Variable Cash Prize" prize type.
WHO: Users who create Prizes/Prize Closet entries (typically Promotions Director role).
WHERE: Prize entry screen — Prize Type field.
HOW: 1. When creating the Prize, set the Prize Type to Variable Cash Prize instead of a standard fixed Cash prize. 2. Configure the variable amount range/options as prompted by that prize type.
CONSTRAINTS: none specified beyond selecting the correct Prize Type.
GOTCHAS: Using a standard Cash prize type will not support variable win amounts — the type must specifically be Variable Cash Prize.
TEST-DATA HINTS: Prize Type value: "Variable Cash Prize".

## WORKFLOW: Track and Mark Mailed/Shipped Prizes
KEYWORDS: ship prize, mail prize, unshipped prizes, prize closet, fulfillment method
JIRA:
---
WHAT: vPromotions can track which physical prizes still need to be mailed/shipped to winners and let you mark them as sent.
WHO: Users with Prize Closet access (typically Promotions Director role).
WHERE: Main Menu (hover your name, upper right) → Prize Closet → blue "Unshipped Prizes" button.
HOW:
1. When adding a Prize, set its Fulfillment Method to "Mail/Ship".
2. Go to Prize Closet from the Main Menu.
3. Click the blue "Unshipped Prizes" button (upper right of Prize Closet).
4. Enter a date range and Station to filter the list of prizes with Mail/Ship fulfillment that haven't shipped yet, including winner names/addresses.
5. Use the filters to locate a specific winner.
6. Click the green "Mark as Shipped" button; a confirmation dialog opens with a notes field (e.g., for a tracking number).
7. After marking, a "Ship Info" button appears for that winner to review shipping details later.
CONSTRAINTS: Only prizes with Fulfillment Method = Mail/Ship appear in this list.
GOTCHAS: Setting Fulfillment Method correctly at prize-creation time is what enables this tracking — it can't be tracked after the fact if set incorrectly.
TEST-DATA HINTS: Fulfillment Method value: "Mail/Ship".

## WORKFLOW: Require and Collect Winner Social Security Numbers for 1099 Reporting
KEYWORDS: SSN collection, 1099 threshold, require SS#, tax id, winner claim
JIRA:
---
WHAT: vPromotions automatically prompts for a winner's SSN once their cumulative claimed prizes reach the $600 IRS 1099-MISC threshold, or can require it per prize regardless of total.
WHO: Front Desk staff process claims; Promotions/Program Director configures per-prize requirements; only Firm Administrator can view/report SSNs.
WHERE: Prize claim screen (Front Desk); per-prize "Require SS#" checkbox on the prize entry.
HOW:
1. When a winner claims a prize, vPromotions checks their year-to-date total winnings.
2. If the claim pushes cumulative claimed prizes to $600+ and no SSN is on file, the system requires SSN entry before the claim can complete.
3. Winners who already provided an SSN show a check mark next to their name and are not asked again.
4. To force SSN collection regardless of total (e.g., high-value single prizes), open the prize entry and check "Require SS#".
CONSTRAINTS: Access to view SSNs for reporting is limited to users with Firm Administrator rights via reports/1099 printing; entered SSNs are encrypted.
GOTCHAS: SSN is only required once — a winner who already supplied it won't be re-prompted even for a different prize.
TEST-DATA HINTS: Reporting threshold: $600 cumulative claimed prizes.

## WORKFLOW: Enable Electronic Signed Winner Documents (W-9, Release Form, Banking Info, Photo ID)
KEYWORDS: signed documents, electronic W-9, release form, banking info, photo id, firm options
JIRA:
---
WHAT: Firms can require winners to electronically sign/submit documents (release forms, W-9s, banking info, photo ID) via an emailed secure link instead of collecting them in person.
WHO: Firm Admin configures this feature at the firm level.
WHERE: Settings / Firm / Firm Options (checkboxes); template setup at Settings / vPromo / Signed Documents Request Template.
HOW:
1. Go to Settings / Firm / Firm Options.
2. Check any needed options: "Auto Email Winners" (sends emails when prize email templates exist), "Require Release Form via Email Link", "Require W-9 (when needed) via Email Link" (only once threshold surpassed), "Require W-9 for all wins" (every win after threshold), "Collect Banking Info via Email Link" (Routing/Account Number for direct deposit), "Request Photo ID Upload via Email Link" (optionally required via "Require Photo ID Upload").
3. Set "Show Winners Requiring Signed Documents Going Back" to control how many months of unclaimed-prize winners appear in the Signed Documents Requested table.
4. Optionally enable "Manually input and track a Contest Number" to record a budget/account line item on the Contest PRF.
5. Go to Settings / vPromo / Signed Documents Request Template and build a template per station: state clearly that the link goes to a secure site, add station branding/logo, and (recommended) include a support email in case of login trouble.
CONSTRAINTS: This is a Firm Option — only a Firm Admin can turn it on.
GOTCHAS: Emails sent from vPromotions are "No Reply" — say so in the template so winners don't reply expecting a response.
TEST-DATA HINTS: none given beyond the checkbox labels themselves, which should be echoed verbatim: "Auto Email Winners", "Require Release Form via Email Link", "Require W-9 (when needed) via Email Link", "Require W-9 for all wins", "Collect Banking Info via Email Link", "Request Photo ID Upload via Email Link".

## WORKFLOW: Fix Missing Notification Emails from vPromotions
KEYWORDS: missing notifications, email settings, notification troubleshooting, spam folder
JIRA:
---
WHAT: If a user isn't receiving vPromotions notification emails, the cause is almost always a settings or spam-filter issue, not a system failure.
WHO: Any vPromotions user.
WHERE: Settings > User > Email Settings.
HOW: 1. Go to Settings > User > Email Settings. 2. Verify every notification type you want is checked. 3. Click Save. 4. Double-check your listed email address for typos/punctuation errors, and confirm only one address is listed. 5. Check your Spam/Junk folder and, if found there, adjust your email client to trust vCreative senders.
CONSTRAINTS: none specified.
GOTCHAS: A single mistyped character in the saved email address will silently stop delivery.
TEST-DATA HINTS: none given.

## WORKFLOW: Reschedule a Liner to Increase or Reduce How Often It Airs
KEYWORDS: reschedule liner, liner air count, priority-based liner, liner grid
JIRA:
---
WHAT: Changing how many times a liner airs is done by rescheduling it, and the method depends on which liner scheduling mode the firm uses.
WHO: Users with liner scheduling access.
WHERE: Home Calendar → Liners tab (for immediate scheduling); Priority-based Liner Scheduled setup (for daily scheduling).
HOW (Schedule liners immediately as entered): 1. From the Home Calendar, open the Liners tab. 2. Click a liner to open its popover from the liner grid. 3. Click the Reschedule icon (backwards clock). 4. Change the number of liners and run dates. All associated liners are removed and rescheduled per the new settings.
HOW (Priority-based Liner Scheduled - daily): 1. Change the number you want to air per day/daypart. 2. Choose a day that already has liners scheduled and reschedule liners on that day — this reschedules all liners for that configuration.
CONSTRAINTS: The correct method depends on which scheduling mode is active for the firm.
GOTCHAS: In immediate-scheduling mode, using Reschedule removes and recreates ALL associated liners for that entry — it isn't a partial edit.
TEST-DATA HINTS: none given.

## WORKFLOW: Create Mailing Labels from a Winner History Report
KEYWORDS: mailing labels, winner history report, export excel, avery merge
JIRA:
---
WHAT: vPromotions has no built-in mailing label printer, but you can export winner data and mail-merge it into labels using Avery Design & Print.
WHO: Any user with Reports access.
WHERE: Main Menu (hover your name) → Reports → Winner History; then external Avery Design & Print site.
HOW:
1. From the Main Menu, select Reports, then choose "Winner History".
2. Set Station(s), Status, Start/End Dates, and Prize Types, then click Generate Report.
3. On the generated report, click the Excel button (upper left) to export.
4. Go to Avery Design & Print (requires an Avery account) and click "Start Designing".
5. Choose your label number and click "Select This Template", then pick a design.
6. Click "Import Data Mail Merge" → "Start Import/Merge" → "Browse for File" and select the exported Excel file.
7. Uncheck any columns/rows you don't want printed, click "Next".
8. Arrange fields as desired on the label layout, click "Next".
9. Click "Finish", then "Preview", then "Print" → "Print It Yourself".
10. Save the Avery template/project so you can reprint later from your Avery Projects.
CONSTRAINTS: Requires a separate Avery Design & Print account; vPromotions only supplies the exported data.
GOTCHAS: Native label printing "is coming soon" per the article but was not available at time of writing — the Excel export workaround is the only current path.
TEST-DATA HINTS: none given.

## WORKFLOW: Merge Duplicate Winner Records
KEYWORDS: merge winners, duplicate winner, winner settings, dupe detector
JIRA:
---
WHAT: Duplicate winner records can be combined into one so history and totals (e.g., for 1099 thresholds) are accurate.
WHO: Firm Admins and Promotions Directors.
WHERE: Settings > Promo > Winners.
HOW: 1. Go to Settings > Promo > Winners. 2. Click Merge Winners. 3. Search for and select the record to merge FROM. 4. Search for and select the record to merge TO. 5. Confirm — the first record is removed and its data added to the second (target) record. You can search by any field on the winner record.
Related actions on the same page: search winners via the Search box (list updates live as you type); edit a winner via the pencil (edit) icon, make changes, and click Save; delete a single winner via the red trash-can icon; delete multiple winners by checking their boxes and using Bulk Actions → Delete.
CONSTRAINTS: Requires Firm Admin or Promotions Director access to this Settings page.
GOTCHAS: Always run this (or the Dupe Detector) before generating Year End Prize Reports, since duplicate winner records can cause inaccurate 1099 threshold totals.
TEST-DATA HINTS: none given.

## WORKFLOW: Fix "Wizard Won't Let Me Select a Liner Category" (Set Up Available Liner Slots)
KEYWORDS: liner category, liner wizard, available liner slots, liner clock
JIRA:
---
WHAT: The scheduling Wizard can't offer a Liner Category, and the Liners tab appears blank, until a "Liner Clock" is configured.
WHO: Users configuring Promo settings (setup typically done by Promotions Director/admin).
WHERE: Settings > Promo > Available Liner Slots.
HOW: 1. Go to Settings > Promo > Available Liner Slots. 2. Set up the Available Liner Slots (the "Liner Clock") for the categories/stations needed. 3. Return to the Wizard/Home Calendar Liners tab and confirm the Liner Category is now selectable.
CONSTRAINTS: Without a configured Liner Clock, Liners cannot be scheduled at all.
GOTCHAS: A blank Liners tab on the Home Calendar is a symptom of this same missing setup, not a display bug.
TEST-DATA HINTS: none given.

## WORKFLOW: Fix "Error" in the SS# Field on a Year End Report
KEYWORDS: SS# error, year end report, browser mismatch, decrypt, SSN
JIRA:
---
WHAT: The Year End Report shows "Error" instead of a Social Security Number when it can't decrypt the data, which happens due to a browser/login mismatch, not a data problem.
WHO: Whoever is viewing the Year End Report (must have Tax ID Access).
WHERE: Year End Report view, opened from the emailed report-ready link.
HOW: 1. Open the "report is ready" email. 2. Click the View Report link in the SAME browser where you are already logged into vPromotions. 3. Log in again when prompted. 4. Confirm SSNs now decrypt and display correctly.
CONSTRAINTS: The browser used to open the report link must match the browser session logged into vPromotions (e.g., don't open an Edge-emailed link while your active vPromotions session is in Chrome).
GOTCHAS: This is an intentional multi-layer security measure, not a bug — mismatched browser sessions will always show "Error" for SS# fields.
TEST-DATA HINTS: none given.

## WORKFLOW: Update Winner Info as On-Air Talent
KEYWORDS: on-air talent, edit winner details, assign winner, change winner
JIRA:
---
WHAT: On Air Talent can correct/edit a winner's information after entering them, without disturbing the recorded win date/time.
WHO: On Air Talent role.
WHERE: Winner entry screen, "edit winner details" link at the lower right after using the assigned winner button.
HOW (winner not yet assigned): 1. Click the assigned winner button. 2. Enter the winner's name. 3. Click the "edit winner details" link (lower right of the winner screen). 4. Make changes and save.
HOW (winner already entered/assigned): 1. Click the Change Winner button. 2. Enter the winner's information. 3. Click the "edit winner details" link. 4. Make changes and save.
CONSTRAINTS: none beyond On Air Talent role access to the winner screen.
GOTCHAS: Do NOT click Assign Winner again to fix details — that resets things. Use "edit winner details" instead so the original win date/time stays correct.
TEST-DATA HINTS: none given.

## WORKFLOW: Send Auto Winner Emails for Only One of Multiple Contests Sharing a Prize
KEYWORDS: auto email winners, prize package, use email template, winner email per contest
JIRA:
---
<!-- TRUNCATED — paste the rest of this workflow to complete kb-faq.md -->
WHAT: Winner Emails are triggered per-Prize, so to email winners of only ONE contest when the same prize is split across multiple contests, route the "email" copies through a separate Prize Package.
WHO: Users configuring Prizes/Prize Packages (Promotions Director).
WHERE: Prize Closet / Prizes on the Fly; Prize and Prize Package "Use Email Template" checkbox.
HOW (example: 100 identical prizes split 50/50 across two contests, only one should email):
1. Add the 100 base Prizes to the Prize Closet (or via Prizes on the Fly) and leave "Use Email Template" UNchecked on the Prize itself.
2. Create a Prize Package containing 50 of those prizes (on the fly or in the Prize Closet) and check "Use Email
<!-- content ends here — output was truncated mid-sentence -->
