# vPromotions Help Center — Contests and Giveaways
# =============================================
# Source: https://vcreativeinc.com/knowledge/vpromotions#contests-and-giveaways
# Extracted: 2026-07-27
# Product-scoped: only loaded for vpromotions runs.

## WORKFLOW: Send Auto Winner Emails for Only One of Multiple Contests Sharing a Prize
KEYWORDS: auto email winners, prize package, use email template, winner email per contest
JIRA:
---
WHAT: Winner Emails are triggered per-Prize, so to email winners of only ONE contest when the same prize is split across multiple contests, route the "email" copies through a separate Prize Package.
WHO: Users configuring Prizes/Prize Packages (Promotions Director).
WHERE: Prize Closet / Prizes on the Fly; Prize and Prize Package "Use Email Template" checkbox.
HOW (example: 100 identical prizes split 50/50 across two contests, only one should email):
1. Add the 100 base Prizes to the Prize Closet (or via Prizes on the Fly) and leave "Use Email Template" UNchecked on the Prize itself.
2. Create a Prize Package containing 50 of those prizes (on the fly or in the Prize Closet) and check "Use Email Template" on the Prize Package.
3. Assign that Prize Package to the Plays in the Contest for which Winner Emails should send; assign the plain (non-package) Prizes to the other Contest.
CONSTRAINTS: Winner Email behavior is controlled at the Prize or Prize Package level, not at the Contest level.
GOTCHAS: Checking "Use Email Template" directly on a shared Prize sends the email to every winner of that prize across ALL contests using it — wrapping the desired subset in a Prize Package is the only way to scope the email to one contest.
TEST-DATA HINTS: Example values: 100 total Prizes, split into 50 with email template (via Prize Package) and 50 without.

## WORKFLOW: Add Multiple Categories to a Single PRF
KEYWORDS: multiple categories, PRF category field, add category
JIRA:
---
WHAT: A single PRF's Category field accepts more than one entry, so you can add an additional Category to a PRF you already started.
WHO: Any user building/editing a PRF.
WHERE: Top of the PRF form, Category field.
HOW: 1. Open the PRF form (e.g., a Remote you're already filling out). 2. At the top of the form, add the additional Category (e.g., a social media post) to the Category field. 3. Scroll below the original Category's fields to find and complete the new fields specific to the newly added Category.
CONSTRAINTS: none specified.
GOTCHAS: Each added Category brings its own set of category-specific fields appended below the first — don't miss filling those in.
TEST-DATA HINTS: Example scenario: a Remote PRF that also needs a social media post added as a second Category.

## WORKFLOW: Bulk-Edit Times on Scheduled Plays
KEYWORDS: bulk edit times, scheduled plays, contest solicits, PD ability
JIRA:
---
WHAT: Multiple scheduled Plays on a PRF can have their times changed simultaneously without affecting their dates.
WHO: Requires Promotions Director, Program Director, or General Manager ability.
WHERE: PRF Details → Plays tab → Bulk Actions → "Edit Selected Times".
HOW: 1. Open the PRF Details and go to the Plays tab. 2. Select the checkboxes for the Plays you want to adjust. 3. Click Bulk Actions, then "Edit Selected Times". 4. Enter the new time to apply to all selected Plays. 5. Click Save.
CONSTRAINTS: Requires PD/Program Director/GM ability; only the time changes, dates are unaffected.
GOTCHAS: If the PRF uses Contest Solicits, the time you enter is applied to the Solicit, and the Winner portion of the Play is automatically scheduled the configured number of minutes afterward — it is not a separate entry.
TEST-DATA HINTS: none given.

## WORKFLOW: Manually Upload a Winner's W-9 or Photo ID
KEYWORDS: upload W-9, upload photo ID, winner documents, front desk
JIRA:
---
WHAT: Staff can manually upload a scanned/photographed W-9 or ID for a winner instead of relying on the winner's electronic self-upload.
WHO: Promotions Director, Program Director, or General Manager (via Settings); Front Desk staff (via Front Desk tab).
WHERE: Settings > vPromo > Winners (manager path); Front Desk tab (front desk path).
HOW (Manager path): 1. Go to Settings. 2. Click vPromo. 3. Click Winners. 4. Enter the winner's name in the Winner Search box. 5. Under Winner's History / Actions, click the upload icon for W-9 or Photo ID.
HOW (Front Desk path): 1. From the Front Desk tab, enter the winner's name. 2. If the winner has unclaimed prizes, click the upload icon for W-9 or Photo ID.
CONSTRAINTS: Front Desk path only works if the winner has unclaimed prizes.
GOTCHAS: none beyond the permission/prerequisite differences between the two paths.
TEST-DATA HINTS: none given.

## WORKFLOW: Customize Fields on the Winner Information Form
KEYWORDS: customize winner form, winner fields, required fields, promo settings
JIRA:
---
WHAT: The fields captured on the Winner information form can be added, removed, or marked required/optional per firm preference.
WHO: Promotions Director or Program Director.
WHERE: Settings > Promo > Customize Winner Form.
HOW: 1. Go to Settings > Promo > Customize Winner Form. 2. Add or remove fields as needed. 3. For each field, choose whether it is required or optional.
CONSTRAINTS: Requires Promotions/Program Director access.
GOTCHAS: none specified in this article (see also the more detailed Show/Required/Winner Required breakdown in the Contests and Giveaways category's "Self-Entry of Winner Information" workflow).
TEST-DATA HINTS: none given.

## WORKFLOW: Manage Plays from the PRF Details Plays Tab
KEYWORDS: plays tab, assign prize, remove prize, consolation prize, bulk actions, edit copy
JIRA:
---
WHAT: The Plays tab inside a contest PRF's Details is where you edit and manage every scheduled play, its on-air copy, its assigned prize, and its winner.
WHO: Users with appropriate manager role for winner assignment; general editing available to PRF-authorized users.
WHERE: PRF Details → Plays tab (a number next to the tab shows how many plays are scheduled).
HOW:
1. Open the Plays tab; the PRF name shows in the upper-left.
2. Click "+ Add New" to schedule additional plays.
3. Use the Actions column per play: the Edit (pencil) icon to update on-air copy — choose to apply changes to "Current Play", "Current and Future Plays", or "All Plays"; the trash-can icon to Delete a play; the yellow/orange minus-sign box to remove an assigned prize (it becomes a plus sign to assign a new one); the blue gift icon to add a consolation prize; the trophy icon (managers only) to Assign Winner directly.
4. Click the telephone icon next to a winner's name to open Call History and log contact attempts; an envelope icon indicates an email was sent.
5. To act on many plays at once, check the boxes next to each (or the header checkbox for all), then use Bulk Actions to Delete, Assign prizes, Remove prizes, Edit scheduled times, or Add/Remove consolation prizes.
6. Use the Print/Export options to output the play list to Excel, PDF, or print.
CONSTRAINTS: The trophy (Assign Winner) icon is only available to users with manager role. Certain prize fields (e.g., value) cannot be edited once a winner is assigned — remove the winner first, edit, then reassign.
GOTCHAS: The "Automatically Return Prizes to the Prize Closet" checkbox lives at the top of this tab too (see its own workflow). The Type column shows On-Air vs Off-Air Play — Off-Air plays don't appear on the On Air tab and must be assigned from here.
TEST-DATA HINTS: Example PRF title used in the article: "Christmas in July – On-Air Contest".

## WORKFLOW: View the Master Plays Calendar by Station (Color-Coded Play Status)
KEYWORDS: plays tab, home calendar, play status colors, jackpot yellow
JIRA:
---
WHAT: The main Plays tab on the Home/Calendar page shows the plays schedule across your stations, color-coded by status.
WHO: Any user with calendar access to the relevant stations.
WHERE: Home/Calendar page → Plays tab.
HOW: 1. Confirm the correct station is selected in the Stations filter. 2. Choose Week or Month view. 3. Use the forward/backward arrows to navigate, or click Today to return to the current date. 4. Click a play to open a popover with status details and available actions (assign prize, assign winner, view PRF details, view All Plays, or Delete depending on status).
CONSTRAINTS: none beyond station filter visibility.
GOTCHAS: Colors mean: Light green = Approved, no prize assigned yet; Green = prize assigned, no winner yet; Dark Green = winner assigned; White = prize claimed, workflow complete; Yellow = Jackpot contest play with no winner assigned yet. On the date/time grid you can drag a play to a new time slot to reschedule it.
TEST-DATA HINTS: none given.

## WORKFLOW: Assign a Winner from the On Air Tab
KEYWORDS: assign winner, on air, winner search, create new winner
JIRA:
---
WHAT: Assigning a winner to a contest Play is done directly from the On Air Timeline.
WHO: On Air staff / any user with On Air access.
WHERE: On Air Timeline → click the contest Play → green "Assign Winner" button on the right panel.
HOW: 1. Click the contest Play in the On Air Timeline; contest info appears on the right, including the green "Assign Winner" button. 2. Click Assign Winner. 3. Enter the winner's Name, Email Address, or Phone Number — after 3 characters, vPromotions searches existing winners. 4. If found, click the winner's info to select them. 5. If not found, click "create new..." and fill out the winner form. 6. Click Assign Winner to finalize.
CONSTRAINTS: none beyond On Air access.
GOTCHAS: Email addresses and phone numbers are unique identifiers, so searching by one of those is the most reliable way to find an existing winner. When entering a NEW winner's info, vPromotions' Dupe Detector will alert you if another winner already exists with the same email or phone number — check that alert before creating a duplicate record.
TEST-DATA HINTS: none given.

## WORKFLOW: Create a Floating Contest PRF Category and Schedule a Floating Contest
KEYWORDS: floating contest, PRF category, play schedule, pick-a-prize package
JIRA:
---
WHAT: A Floating Contest is a special PRF type whose play "floats" at the top of the On Air screen during a scheduled daily time window, creating a new play each time a winner is assigned.
WHO: Category setup restricted to General Manager, Program Director, and Promotions Director (visibility auto-set on category creation).
WHERE: Settings / vPromo / PRF Categories (to create the category); PRF Details → Wizard (to configure a Floating Contest PRF).
HOW:
1. In Settings / vPromo / PRF Categories, create a new category, name it, choose its Group, and set Type to "Floating Contest". Visibility auto-restricts to GM/PD/Promotions Director. Click Save.
2. Submit a Floating Contest PRF, then go directly to the Wizard (skip the Plays tab — there are no Plays until winners exist).
3. In Wizard Step 2 "Play Schedule": enter Start Date, End Date, Days of the Week, Daily Start Time, Daily End Time, optional On Air Copy, then click Save.
4. In Wizard Step 3 "Assign Prizes": Floating Contests only accept Pick-a-Prize Packages — use the "Prize Closet" link to build the package, then "Return to PRF".
CONSTRAINTS: Floating Contests only accept Pick-a-Prize Packages, not standalone prizes. The play is only visible on the On Air screen within its scheduled window (e.g., a 6a-9a Mon-Fri floating contest is invisible outside those hours).
GOTCHAS: Each time a winner is assigned, a NEW play is auto-created in the On Air schedule and also appears on the Plays tab with Prize, Winner, assigner, and timestamp.
TEST-DATA HINTS: Example window: a morning show floating contest scheduled 6a-9a, Monday-Friday.

## WORKFLOW: Create a Pick-a-Prize Package Contest
KEYWORDS: pick a prize package, prize choice, package quantity, avail field
JIRA:
---
WHAT: Lets winners choose their own prize from a set of options within a package, rather than being assigned one automatically.
WHO: Users with Prize Closet access.
WHERE: Prize Closet → new Prize Package, "Pick a Prize Package" checkbox.
HOW: 1. Choose the Station. 2. Enter a Package Name. 3. Check the "Pick a Prize Package" checkbox. 4. Click +Add Prize to Package, then enter the total Qty of that prize to add (the Avail field auto-updates as prizes are assigned to winners), and the Qty Ea field for how many each winner receives. 5. Repeat to add more prizes; use Delete to remove one. 6. Click Save.
On Air: when a winner is entered, the Pick A Prize choices list below Winner Name/Notes with a checkbox per item — check the box for the item won.
CONSTRAINTS: Packages can be edited any time, but prizes already assigned to winners cannot be removed.
GOTCHAS: Enable an email notification (in Email Settings) to be alerted if plays are scheduled to exceed available prizes in the package.
TEST-DATA HINTS: Example use case: a "Pick Your Ticket Contest."

## WORKFLOW: Set Up a Local Text-to-Win Contest
KEYWORDS: text to win, keyword, shortcode, plays tab
JIRA:
---
WHAT: Text-to-Win contests let listeners enter via SMS keyword/shortcode, which vPromotions merges into the on-air copy automatically.
WHO: Users scheduling contest Plays.
WHERE: Contest Wizard (Add Plays step) → "Text-to-Win Play(s)" checkbox; PRF Details / Plays tab → Shortcode field and per-play Keyword field.
HOW: 1. When adding Plays, check "Text-to-Win Play(s)" (alongside any recurring options). 2. Format the play copy using the merge field convention: begin/end with underscore and use all-caps, e.g. _KEYWORD_ and _SHORTCODE_ — copy/paste the provided instructions to get formatting right. 3. After Plays are scheduled and prizes added, go to Details / Plays tab; enter the Shortcode at the top of the page and a Keyword per Play. 4. On the On Air screen, the Keyword and Shortcode populate automatically for each play.
CONSTRAINTS: This workflow applies to Local Text-to-Win Contests only — Collective (Corporate) Text-to-Win contests behave differently on the On Air tab.
GOTCHAS: Getting the underscore/all-caps merge field format wrong will break the auto-insertion of Keyword/Shortcode into the copy.
TEST-DATA HINTS: Merge field format example: _KEYWORD_ and _SHORTCODE_.

## WORKFLOW: Archive and Restore Prizes & Prize Packages
KEYWORDS: archive prize, restore prize, prize closet, auto archive expired
JIRA:
---
WHAT: Prizes/Packages no longer relevant can be archived out of the active Prize Closet, and restored later if needed.
WHO: Any user with Prize Closet access (bulk/auto-archive setup is Firm Admin only).
WHERE: Prize Closet, Actions column (Archive/Restore icons); "Show Archived" button (top right, next to Unshipped Prizes); Settings / Firm / Firm Options for auto-archive.
HOW (manual archive): Click the Archive icon in the Actions column for the prize or package.
HOW (manual restore): Click "Show Archived" in the Prize Closet, then click the Restore icon in the Actions column for the item.
HOW (bulk archive): Check the boxes next to multiple prizes/packages, then use Bulk Actions → Archive.
HOW (auto-archive expired prizes): In Settings / Firm / Firm Options, check "Auto Archive Expired Prizes", enter the number of days after expiration to wait, then click Save Changes.
CONSTRAINTS: A Package auto-archives once ALL of its component prizes are archived. Bulk-restoring is not available — restoring must be done one item at a time.
GOTCHAS: Archived prizes still show in Plays/On Air if already assigned to an active contest (not recommended), at the Front Desk for a winner's Unclaimed Prizes, and in Reports — they only disappear from assignment dropdowns, Front Desk prize-name search, and the main Prize Closet listing.
TEST-DATA HINTS: none given.

## WORKFLOW: Create a New Prize in the Prize Closet
KEYWORDS: new prize, prize closet, prize type, fulfillment method
JIRA:
---
WHAT: Prizes are created and tracked in the Prize Closet, scoped per station, with value tracked per winner for tax purposes.
WHO: Users with Prize Closet access.
WHERE: Prize Closet (hover your name, upper right) → "+ New Prize" button.
HOW: Click "+ New Prize" and complete the form: Name; Type (choose the prize type — use "Variable Cash" only when On Air Talent must enter the amount at assignment); Quantity (for Variable Cash, enter the total dollar budget instead of a unit count); Value (defaults to $1 for Variable Cash); Expiration (for perishable prizes like tickets); Client; Station; Description (shown on-air to describe the prize); Fulfillment Method; Fulfillment Notes. Click Save.
CONSTRAINTS: Prizes are Station-based. Description, Fulfillment Method, and Fulfillment Notes all display on the On Air screen during the contest play.
GOTCHAS: See the dedicated "Create a Variable Cash Prize" workflow for full detail on that prize type. Use the Edit (pencil) icon to modify a prize, the trash-can to delete it, or Bulk Actions to delete multiple at once.
TEST-DATA HINTS: none given beyond the field list above.

## WORKFLOW: Create a New Prize Package
KEYWORDS: prize package, add prize package, package quantity
JIRA:
---
WHAT: A Prize Package groups multiple individual Prizes (already in the Prize Closet) into one giveaway unit, such as "Dinner and a Movie."
WHO: Users with Prize Closet access.
WHERE: Prize Closet → "+ New Prize Package" button.
HOW: 1. Ensure the component Prizes already exist in the Prize Closet. 2. Click "+ New Prize Package". 3. Choose the Station. 4. Enter a Package Name (editable later). 5. Enter the total Quantity of packages being created (editable later). 6. Click "+Add Prize Package" for each component Prize and choose it; enter the Qty for how many of that prize go into EACH package (e.g., 2 tickets + 2 dinners for a "Dinner and a Movie for 2" package). 7. Save.
CONSTRAINTS: As prizes are assigned into packages, they are deducted from each Prize's own Available Quantity. If any item in a package expires, the whole package expires.
GOTCHAS: A Prize Package's value is tracked per component prize for tax purposes when won, not as a single lump value.
TEST-DATA HINTS: Example package: "Dinner and a Movie for 2" — Qty 2 for each of ticket and dinner prizes.

## WORKFLOW: Set Up Audience (Web) Contesting Integration
KEYWORDS: audience integration, web contest, audience api, take me to audience
JIRA:
---
WHAT: Integrates vPromotions with the third-party Audience.io platform so web contest Plays are sent to Audience and winners sent back automatically.
WHO: Requires a separate Audience.io account; setup requires Firm-level Station configuration access.
WHERE: Settings / Firm / Stations ("Use Audience" checkbox); Settings / vPromo / PRF Categories (category-level "Use Audience" checkbox); PRF Details → green Actions button → "Take Me to Audience".
HOW: 1. Contact vCreative (Client Services Manager or Help Desk) and your Audience representative to enable the integration on both sides. 2. In Settings / Firm / Stations, check "Use Audience" for each station to enable; enter the Audience Account ID and Contact Email (found in Audience's "Edit Account Details" screen) and click Verify Account. 3. In Settings / vPromo / PRF Categories, find or create a "Web Contest"/"Audience Contest" category, click its Edit (pencil) icon, check "Use Audience", and Save. 4. Build the contest Plays and assign Prizes as normal in the Wizard using that category. 5. From PRF Details, click the green Actions button and choose "Take Me to Audience" to push the Plays to Audience for editing/posting.
CONSTRAINTS: Requires an active Audience.io account and integration enabled by both vCreative and Audience.
GOTCHAS: You cannot choose the winner from within vPromotions for Audience-enabled plays — the winner must be picked in Audience, then it syncs back to vPromotions for Front Desk fulfillment.
TEST-DATA HINTS: none given.

## WORKFLOW: Set Up and Run a Collective/Corporate Contest
KEYWORDS: corporate contest, collective contest, CCM, CCL, CCPD, main-cc
JIRA:
---
WHAT: Corporate Contesting lets a Corporate Contest Manager run one contest that mirrors out to multiple local firms/stations, with roles handling local acceptance, winner assignment, and prize shipping.
WHO: Requires a Corporate Firm with local firms associated (set up via Help Desk), plus assigned roles: Corporate Contest Manager (CCM), Corporate Contest Liaison (CCL, one per local firm), optional Corporate Contest Point Person (CCPP), and Corporate Contest Prize Distributor (CCPD).
WHERE: Corporate Contest PRF (Main-CC); PRF Details / Plays tab; green Actions button.
HOW:
1. CCM fills out the Corporate Contest PRF, selecting target stations via Custom Station Groups, Format(s), Market(s), or individually, and clicks Save — this creates mirrored local PRFs, with the Parent ("Main-CC") visible only to Corporate Firm users.
2. Each CCL is notified; for Mandatory Contests they choose "Accept" or "Conflict" (CCM can override a Conflict); for Optional Contests they choose "Accept" or "Deny".
3. CCM schedules Plays (checking "Text-To-Win" for keyword contests, "Live Plays" for cross-timezone simultaneous scheduling), using _SHORTCODE_ and _KEYWORD_ merge fields in the copy.
4. CCM assigns Prizes and eligibility rules, then enters the Shortcode (top of Plays tab) and a per-play Keyword (auto-copied to all participating local stations).
5. On Air Talent announces the Keyword/Shortcode and clicks "Mark Executed".
6. CCPP pulls a winner from the text platform, clicks the trophy (Assign Winner) icon on the Main-CC Plays tab, and assigns the market/station/winner (see the dedicated CCPP workflow for detail).
7. CCPD is notified, ships the prize, and clicks "Shipped".
8. CCL clicks "Received" upon prize arrival.
9. Front Desk fulfills the prize and clicks "Claimed".
CONSTRAINTS: Only users in the Corporate Firm see the Main-CC PRF. Local PRFs mirror the parent automatically.
GOTCHAS: Play scheduling across many stations "may take some time to complete" — be patient. Keyword propagation to local stations is also not instantaneous.
TEST-DATA HINTS: none given.

## WORKFLOW: Assign a Winner to a Corporate Contest as the Corporate Contest Point Person (CCPP)
KEYWORDS: CCPP, assign winner, corporate contest, main-cc, viewing firm
JIRA:
---
WHAT: The CCPP ability lets a local-market user assign winners to a Corporate (Collective) Contest without needing every firm/station on their account.
WHO: Requires the "Corporate Contest Point Person" ability (usually paired with "Large Multimarket User"); the Corporate Firm must be assigned to the CCPP by vCreative/Help Desk.
WHERE: Viewing Firm selector (top black bar); Main-CC PRF Details → Plays tab → trophy (Assign Winner) icon.
HOW:
1. If a Viewing Firm selector appears in the top black bar, select the Corporate Firm.
2. Find the "Main CC" calendar item for the contest, click it, and choose "Details" from the pop-over.
3. Go to the Plays tab on the Main-CC Details screen, find the Play needing a winner, and click the Assign Winner (trophy) icon.
4. Select the Firm (market) and Station where the winner is listening — all Firms/Stations your account can access appear in the dropdowns.
5. Enter the winner's email, phone, or name (past winners list after 3 characters); click "create new..." for a first-time winner.
6. Review the winner's last three win dates shown (informational, not an error), then click Assign Winner to finalize — this immediately attaches the winner to the Play across all participating stations' On Air tabs.
7. After assignment, the trophy icon is replaced by three icons: Remove Winner, Swap Winner, and Upload Winner Audio (uploads propagate to all participating stations' On Air tabs and local PRFs).
CONSTRAINTS: Requires the CCPP ability and Corporate Firm assignment set up in advance by vCreative/Help Desk.
GOTCHAS: The "last three times the winner has won" display is purely informational, not a warning or error.
TEST-DATA HINTS: none given.

## WORKFLOW: Create a Variable Cash Prize
KEYWORDS: variable cash prize, jackpot budget, on air talent enters amount, total qty
JIRA:
---
WHAT: A Variable Cash Prize is used when the cash amount won isn't known until the contest play happens — either in a Jackpot Contest or a recurring contest where On Air Talent enters the amount in the Control Room.
WHO: Users creating Prizes (Promotions Director); On Air Talent enters the amount at assignment time.
WHERE: Prize Closet / Prizes on the Fly → Type field set to "Variable Cash".
HOW: 1. Create a new Prize and set Type to "Variable Cash". 2. Enter the total budget for the contest in the Total Qty field (Value Ea. defaults to $1). 3. Fill out the rest of the prize form normally. 4. When assigning a winner (in studio or from Plays), click Assign Winner as usual and find an eligible winner — a blank field appears for entering the amount won.
CONSTRAINTS: The amount entered at assignment cannot exceed the total remaining budget from the Total Qty field. When used inside a Jackpot Contest, the amount is instead governed by the Jackpot's minimum/maximum and per-non-winner increase amounts (see the Jackpot Contests workflow).
GOTCHAS: This is the same "Variable Cash Prize" referenced briefly in the FAQ category's cash-contest stub — this workflow is the authoritative, detailed version.
TEST-DATA HINTS: Value Ea. default: $1.

## WORKFLOW: Enable Prize Chain of Custody (PCoC)
KEYWORDS: prize chain of custody, prize entry, prize verification, surplus
JIRA:
---
WHAT: Prize Chain of Custody tracks and verifies prizes from intake through fulfillment using two gated roles/abilities.
WHO: Requires Help Desk to enable; then relies on users assigned the Prize Entry and Prize Verification abilities.
WHERE: Main menu → "Prize Entry" (for users with that ability); Prize Closet listings show in-house status.
HOW: 1. Contact the Help Desk to enable Prize Chain of Custody for your firm. 2. Assign the Prize Entry ability to staff who will log new prizes as they arrive — they'll see "Prize Entry" in their main menu. 3. Assign the Prize Verification ability to staff who compare physical prizes to entries — they get notified when a new prize needs verification, and verifying it makes the prize available in the Prize Closet.
CONSTRAINTS: A prize is not available to give away until Prize Verification confirms it matches the Prize Entry.
GOTCHAS: Prizes with a Start/End Date on the Prize Entry form that pass their End Date will be flagged as "leftovers." Prizes not yet in-house (e.g., a WIBYCBI) show a yellow reminder in the Prize Closet and prompt for an attached signed contract from the provider; an Expected Delivery Date reminder also notifies the responsible person as that date nears.
TEST-DATA HINTS: none given.

## WORKFLOW: Track Winner Contact Attempts (Call History)
KEYWORDS: call history, contact winner, phone icon, winner pickup
JIRA:
---
WHAT: Managers can log and see at a glance whether a winner has been successfully contacted about prize pickup, directly on the Plays screen.
WHO: Promotions and Program Directors.
WHERE: PRF Details → Plays tab, phone icon next to a winner's name.
HOW: 1. Locate the winner's phone icon on the Plays tab. 2. Hover over the icon to see contact details. 3. Click the icon to log another contact attempt and its result/notes.
CONSTRAINTS: A maximum of 3 attempts is tracked (the number next to the icon shows attempts so far).
GOTCHAS: Green icon = winner was reached or a voicemail was left; Red icon = winner not reached (no voicemail possible or bad number).
TEST-DATA HINTS: Maximum tracked attempts: 3.

## WORKFLOW: Add a Grand Prize Drawing to an Existing Contest
KEYWORDS: grand prize, live drawing, draw winner, ticket icon
JIRA:
---
WHAT: A Grand Prize option can be layered onto an existing contest PRF so one of the contest's own winners (or a live-drawn entrant) wins an additional bigger prize.
WHO: Program Director, General Manager, or Promotions Director can draw the winner if Live Drawing is used; On Air staff can also draw if given the ticket icon.
WHERE: PRF Details → Plays tab → "+ Add New"; Grand Prize checkbox and Live Drawing checkbox in the play form.
HOW: 1. Create the contest PRF with its baseline qualifying prizes/plays first. 2. In the Plays tab, click "+Add New". 3. Check the Grand Prize option checkbox. 4. Optionally check Live Drawing to have vPromotions randomly select the winner instead of a human. 5. Set the "when" field to a time AFTER the last baseline play. 6. Refresh your browser; a Grand Prize Drawing option appears at the bottom of the Plays tab with a ticket icon. 7. Click the ticket icon to draw (or re-draw) a winner at random from all winners already assigned to that PRF, or to assign manually if Live Drawing was not checked.
CONSTRAINTS: Requires at least the baseline qualifying plays/winners to already exist before drawing the Grand Prize winner.
GOTCHAS: If Live Drawing isn't checked, On Air staff get the traditional "assign winner" option instead of "draw winner."
TEST-DATA HINTS: Example: a $50 gift card given daily for two weeks, with one of those winners drawn for a $500 gift card grand prize.

## WORKFLOW: Set Up and Run a Jackpot Contest
KEYWORDS: jackpot contest, minimum jackpot, jackpot increment, variable cash, consolation prize
JIRA:
---
WHAT: Jackpot Contests automatically increase a cash jackpot each time there's no winner, and can award consolation prizes.
WHO: Promotions Director sets it up; On Air Talent runs it.
WHERE: Contest Wizard, via Actions on the PRF Details screen.
HOW:
1. Open the Contest Wizard from Actions on the Jackpot contest PRF's Details screen.
2. On Wizard Step 1 (Add Plays), choose "Jackpot Prize" — the form changes to the Jackpot Add Plays form.
3. Enter the Minimum Jackpot amount (the reset value after a win) and the Jackpot Incr. (the increase amount each time there's no winner), plus standard Play info.
4. On Step 2 (Assign Prizes), choose or create a Jackpot prize; set Type to "Variable Cash" and Total Qty. to the contest's total dollar budget.
5. Choose or create a Consolation Prize and set the quantity each non-Jackpot winner receives.
6. Complete the rest of the Wizard as usual.
On Air: the current Jackpot Amount shows under the Contest Copy/Notes, and the Assign Winner button reads "$ Jackpot Options."
CONSTRAINTS: Do not enter a Jackpot Winner's name until you've confirmed whether they won the jackpot or not.
GOTCHAS: Pair this with the Jackpot Low Quantity Warning and Correct Jackpot Amounts workflows for ongoing management.
TEST-DATA HINTS: none given beyond the field names above.

## WORKFLOW: Correct a Jackpot Amount
KEYWORDS: correct jackpot, change current jackpot, jackpot fix
JIRA:
---
WHAT: Fixes an incorrect current Jackpot amount on an active Jackpot Contest.
WHO: Promotions Director, Program Director, or General Manager.
WHERE: PRF Details → green Actions button → "Change Current Jackpot".
HOW: 1. Find the Jackpot Contest PRF on the Home Calendar, click it, and choose Details. 2. Hover the green Actions button and choose "Change Current Jackpot". 3. Select the correct amount from the dropdown list. 4. Click "Update".
CONSTRAINTS: Requires PD/Program Director/GM ability.
GOTCHAS: none specified.
TEST-DATA HINTS: none given.

## WORKFLOW: Set a Jackpot Low Quantity Warning
KEYWORDS: jackpot low quantity warning, variable cash threshold, jackpot notification
JIRA:
---
WHAT: Sends a banner and email notification when a Jackpot Contest's remaining Variable Cash budget drops to or below a chosen threshold.
WHO: Users configuring the Jackpot Contest.
WHERE: Contest Wizard → Jackpot Contest set-up form → Low Quantity Warning field.
HOW: 1. In the Jackpot Contest set-up form in the Contest Wizard, set a Low Quantity Warning amount. 2. When the remaining Variable Cash prize amount reaches or falls below that amount, a banner appears at the top of the vPromotions Calendar and an email notification is sent.
CONSTRAINTS: none specified beyond being part of Jackpot Contest setup.
GOTCHAS: This is a proactive alert to avoid running out of jackpot budget mid-contest — set it before the contest goes live.
TEST-DATA HINTS: none given.

## WORKFLOW: Create Contest Plays via the Contest Wizard (Play Types)
KEYWORDS: create plays, contest wizard, recurring plays, multiple plays, off air play
JIRA:
---
WHAT: A Play is a single execution/drawing of a Contest; a Contest can contain many Plays, each with exactly one Winner.
WHO: Promotions Directors and Program Directors can edit; created via the PRF's Plays tab.
WHERE: PRF Details → Plays tab → green "+Add New" button → Contest Wizard Step 2 (Create Plays).
HOW: 1. Click "+Add New" on the Plays tab to open the Wizard at Step 2. 2. For a single Play/Winner, leave all Play Type boxes unchecked and fill the required fields. 3. For a Grand Prize Play, ensure at least 2 prior Plays exist and place it last; optionally check Live Play for on-air random drawing. 4. For Recurring Plays (most common), use the green + to add multiple daily times and select the Days of the Week. 5. For Multiple Plays, schedule several Plays/Winners at once (e.g., 10 prizes at 10 AM tomorrow). 6. For Text-to-Win, check that Play type (see the dedicated Text-to-Win workflow). 7. For Jackpot Prize, enter Minimum/Maximum Jackpot Amount and Jackpot Incr., plus a Variable Cash Prize with the total budget in Qty. 8. Fill in When (date/time or Start/End Date with daily times and days), Copy (on-air script), and Notes (background info for On Air Talent). 9. Optionally check "Automatically return Prizes/Packages to the Prize Closet After Contest" or "Off Air Plays" (hides the play from the On Air tab).
CONSTRAINTS: Grand Prize Plays require at least 2 preceding Plays. Off Air Plays must be assigned a winner from within the PRF rather than the On Air tab.
GOTCHAS: Super User Tip — to make Recurring Plays appear at varied times per day rather than the same time, schedule them first, then drag-and-drop them into different times from the Plays tab on the main Calendar.
TEST-DATA HINTS: Example: 10 Multiple Plays scheduled at 10 AM tomorrow.

## WORKFLOW: Use Contest Solicits (Separate Call-to-Action from Winner Announcement)
KEYWORDS: contest solicits, solicit copy, winner copy, minutes between solicit
JIRA:
---
WHAT: Contest Solicits split the call-to-action ("text now to win") from the winner announcement/playback into two separately trackable on-air moments.
WHO: Promotions Directors and Program Directors.
WHERE: PRF Details → Plays tab, "Add Contest Solicit" checkbox when scheduling Plays.
HOW: 1. When scheduling Plays, check "Add Contest Solicit". 2. Enter "Minutes Between Solicit & Winner" — the Solicit airs at the scheduled Play time(s), and the Winner announcement airs that many minutes later. 3. Note the Copy field becomes "Solicit Copy" and Contest Notes becomes "Winner Copy" — each shown separately in studio.
CONSTRAINTS: none beyond PD/Program Director access to scheduling.
GOTCHAS: In the On Air tab, the Solicit gets a "Mark As Read"/"Mark As Tracked" button while the Winner keeps the normal "Assign Winner" button — they are tracked as separate credit-worthy mentions. On the Home Calendar's Liner Tab, Contest Solicits display shaded in blue.
TEST-DATA HINTS: none given.

## WORKFLOW: Assign Contest Rules to a PRF
KEYWORDS: assign rules, contest eligibility, override ineligibility, wizard step
JIRA:
---
WHAT: Contest Rules define winner eligibility criteria and are attached to a contest PRF so ineligible winners get flagged.
WHO: Any user building the PRF; Firm Admins control whether overriding ineligibility is allowed by default.
WHERE: PRF Details → Wizard tab → Assign Rules step; also a quick-view "Assign Rules" tab under Actions in PRF Details.
HOW: 1. Open the Wizard from the PRF Details page. 2. Go to the Assign Rules step. 3. Click into the Rules field to see existing contest rules and select the ones that apply. 4. Use "+New Rule" to create a new rule inline if needed.
CONSTRAINTS: If a winner doesn't meet the assigned eligibility rules, vPromotions flags them at assignment time with a reason and the winner's history.
GOTCHAS: A default "Override ineligibility and assign anyway" checkbox is available, but Firm Admins can disable that default for the market in Settings - Firm Tab - Firm Options; Promotions Director, Program Director, and General Manager ability users always retain the override option regardless of that setting.
TEST-DATA HINTS: none given.

## WORKFLOW: Upload Corporate Contest Keywords via CSV
KEYWORDS: keyword upload, corporate contesting, CSV, station call letters, ALL keyword
JIRA:
---
WHAT: Bulk-assigns unique text-to-win keywords per station per play across a Corporate Contest using a CSV upload, instead of entering each manually.
WHO: Corporate Contest Manager (CCM).
WHERE: PRF Details / Plays listing → "Upload Keywords" button (upper right).
HOW:
1. Build a spreadsheet with exact column headers in this order: start_time (Col A), end_time (Col B), station_call_letters (Col C), keyword (Col D).
2. Format Start Time as MM/DD/YYYY h:mm AM/PM, beginning 3 minutes before the corresponding Play time; format End Time the same way.
3. Use each station's exact call letters as shown in the Main-CC PRF Details, OR enter "ALL" in station_call_letters to apply that play's keyword to every contest station not individually listed.
4. Include one line per station for every Play; save as a CSV file.
5. On the Plays listing, click "Upload Keywords" (upper right), then drag the CSV into the gray drop area or click it to browse and upload.
6. After upload, each play's keyword field shows "Keywords Uploaded".
CONSTRAINTS: File must be CSV format; column headers must match exactly and in order.
GOTCHAS: Excel reformats CSV date/time values in ways that may not match what's actually saved — verify formatting by opening the CSV in a plain text editor like Notepad before uploading.
TEST-DATA HINTS: Column headers (verbatim): start_time, end_time, station_call_letters, keyword. Use "ALL" as a station shortcut.

## WORKFLOW: Change a Prize's Claimed Date
KEYWORDS: change claimed date, edit claimed date, winner settings
JIRA:
---
WHAT: Corrects the date/time recorded when a prize was marked claimed by a winner.
WHO: Promotions Director, Program Director, or General Manager ability.
WHERE: Settings / vPromo / Winners.
HOW: 1. Go to Settings / vPromo / Winners. 2. Look up the winner. 3. Click the pen/pad "Edit Claimed Date" icon next to the Prize Claimed information. 4. Click into the date field and change the date/time. 5. Click Save.
CONSTRAINTS: The prize cannot be marked claimed before the date/time the winner was originally assigned.
GOTCHAS: none beyond that constraint.
TEST-DATA HINTS: none given.

## WORKFLOW: Show Only Available Prizes in the Prize Closet
KEYWORDS: show only available, prize closet filter, hide expired prizes
JIRA:
---
WHAT: A single toggle filter in the Prize Closet replaces two separate firm-level settings, letting any user hide expired/zero-quantity prizes on demand.
WHO: Any user with Prize Closet access.
WHERE: Prize Closet, "Show Only Available / Show All Prizes" toggle.
HOW: 1. Open the Prize Closet. 2. Use the "Show Only Available / Show All Prizes" toggle to switch between seeing only available prizes (hiding expired and zero-quantity prizes) or all prizes.
CONSTRAINTS: This replaced the old firm settings "Hide Zero Quantity Prizes in the Prize Closet" and "Hide Expired Prizes in the Prize Closet", which no longer exist.
GOTCHAS: A separate Firm Setting to Auto Archive Expired Prizes still exists for permanently keeping expired prizes out of the main closet (see the Archive/Restore workflow).
TEST-DATA HINTS: none given.

## WORKFLOW: Enable New Corporate Contest Winner Email Notification
KEYWORDS: corporate contest notification, winner assigned email, email settings
JIRA:
---
WHAT: An optional email notification can alert relevant staff whenever a Collective (Corporate) Contest winner is assigned.
WHO: Available to users with Promotions Director, Program Director, General Manager, or On Air Talent ability.
WHERE: Settings / User / Email Settings (near the bottom of the options).
HOW: 1. Go to Settings / User / Email Settings. 2. Scroll near the bottom to find the Corporate Contest winner notification option. 3. Check it to turn it on (or uncheck to turn off).
CONSTRAINTS: Only available to the listed ability roles.
GOTCHAS: The email includes Winner Name, Winner Station, Winner Market, Prize Name, and Contest Name.
TEST-DATA HINTS: none given.

## WORKFLOW: Exclude a Prize from Annual/Year End Prize Totals
KEYWORDS: exclude from annual prize total, third party 1099, year end exclusion
JIRA:
---
WHAT: When a third-party prize provider will issue their own 1099 for a prize, that prize's value can be excluded from vPromotions' annual winner totals.
WHO: Users adding/editing Prizes.
WHERE: New/Edit Prize form, "Exclude from Annual Prize Total" checkbox.
HOW: 1. When adding or editing a Prize, check "Exclude from Annual Prize Total". 2. Save the prize.
CONSTRAINTS: Checked prizes are excluded from the Year End Prize Report, Year End Prize Detail Report, and Year End Cash/Non-Cash Report, and their value will not count toward whether a winner crosses the $600 taxable threshold requiring a W-9.
GOTCHAS: Use this only when you're certain the third party is handling that winner's 1099 for this prize — excluding it removes vPromotions' own tax tracking for that value.
TEST-DATA HINTS: Example use case: a concert flyaway provided by a music label that issues its own 1099. Threshold referenced: $600.

## WORKFLOW: Run the Cash/Non-Cash Report Including All Winners
KEYWORDS: cash non-cash report, include all winners, tax id access
JIRA:
---
WHAT: The Year End Cash/Non-Cash Report can optionally include every winner for the year (not just those over the taxable threshold), split into Cash vs Non-Cash totals.
WHO: Requires Tax ID Access.
WHERE: Year End Cash/Non-Cash Report generation screen, "Include All Winners" checkbox.
HOW: 1. Open the Year End Cash/Non-Cash Report (Reports menu). 2. Check "Include All Winners" to see every winner regardless of total winnings, broken into Cash and Non-Cash totals. 3. Generate the report as usual.
CONSTRAINTS: Requires Tax ID Access to run this report at all.
GOTCHAS: Without checking this box, the report only includes winners who crossed the taxable threshold — see the General category's "Cash / Non-Cash Report" workflow for the default (taxable-only) behavior.
TEST-DATA HINTS: none given.

## WORKFLOW: Filter Winners by Status on the Signed Documents Screen
KEYWORDS: status filter, signed documents, front desk, prize fulfillment status
JIRA:
---
WHAT: A one-click status filter narrows the Signed Documents winner list to a specific fulfillment stage, such as prizes about to expire or ready to claim.
WHO: Front Desk / fulfillment staff.
WHERE: Signed Documents screen, filter control above the "Front Desk" and Reload buttons (upper right).
HOW: 1. Open the Signed Documents screen. 2. Use the status filter above the Front Desk/Reload buttons to select a specific status category. 3. The winner list narrows to just that status.
CONSTRAINTS: none specified.
GOTCHAS: none specified.
TEST-DATA HINTS: none given.

## WORKFLOW: Manage Multi-Market Prize Fulfillment (All Markets View)
KEYWORDS: multi-market fulfillment, all markets button, signed documents dashboard
JIRA:
---
WHAT: The Signed Documents table can act as a fulfillment dashboard across every market/station a multi-market user has access to, not just one station at a time.
WHO: Users with Front Desk, Promotions Director, Program Director, or General Manager ability across multiple markets/stations.
WHERE: Front Desk → Signed Documents tab → "All Markets" button (above the Search box).
HOW: 1. Go to the Signed Documents tab under Front Desk. 2. Click "All Markets" (above the Search box) to view unclaimed winners across every market/station you have access to. 3. Use the status/task dropdown above the "Front Desk"/"All Markets / Single Market" buttons to further filter the combined list.
CONSTRAINTS: Only shows markets/stations the logged-in user has access to.
GOTCHAS: This enables one person to send document requests, manage electronic transfers, or fulfill prizes centrally for multiple markets — useful for Corporate Contest Managers.
TEST-DATA HINTS: none given.

## WORKFLOW: Add a Canadian Contest Skills Test to the Release Form
KEYWORDS: Canadian skills test, release form, math question, electronic signed documents
JIRA:
---
WHAT: Adds the legally required Canadian "Skills Test" math question to the electronic Release Form, since Canadian winners must answer a skill-testing question to accept a prize.
WHO: Firm Admin.
WHERE: Settings / Firm / Firm Options → "Signed Document Emails" section.
HOW: 1. Go to Settings / Firm / Firm Options, "Signed Document Emails" section. 2. Check the option to enable the Canadian Skills Test. 3. Two new fields appear — enter the test Question and its Answer. 4. When a winner signs into Electronic Signed Documents, the question/answer field displays on the Release Form below their info and above the signature area.
CONSTRAINTS: The question must contain at least three mathematical operations to satisfy the legal skill-testing requirement.
GOTCHAS: If the winner answers incorrectly, they can go back and try again — it doesn't lock them out.
TEST-DATA HINTS: Example question: "(16 × 5) - (12 ÷ 4)" with answer 77.

## WORKFLOW: Set Up the Prize In House Email Template & Track Prizes Not Yet In House
KEYWORDS: prize in house, not in house, prize source, expected delivery, mark in house
JIRA:
---
WHAT: Tracks prizes that haven't physically arrived yet (e.g., concert tickets months away), reminds staff before the expected delivery date, and auto-emails winners once the prize actually arrives.
WHO: Promotions Director, Program Director, or General Manager to configure and manage; requires Winner Emails enabled for the template tab to appear.
WHERE: Settings / vPromo (Prize In House Email Template tab); Prize on the Fly or Prize Closet entry form ("Prize In House" field).
HOW:
1. When adding a prize (via Prize on the Fly or the Prize Closet), set "Prize In House" to "No" if it isn't physically available yet.
2. Three additional fields appear: Prize Source (defaults to you, but can be reassigned to any staff member responsible for the prize arriving), Expected Delivery (date it should arrive), and "Send winners an email when available" (opens the Prize In House Email Template to customize the arrival email).
3. Build/edit the Prize In House Email Template in Settings / vPromo so it's ready (e.g., "Your prize is ready for pick up!"), and consider pairing it with an "Other" fulfillment Winner Email Template that says the prize isn't in yet.
4. Two days before Expected Delivery, a task appears for the Prize Source and the Promotions Director with two actions: "Mark In House" (also available via the house icon next to the prize in the Prize Closet) to trigger the Prize In House email, or "Extend Expected Delivery Date" if delayed.
CONSTRAINTS: The Prize In House Email Template tab only populates if Winner Emails are enabled for your market.
GOTCHAS: The Auto Forfeit feature will not forfeit a not-in-house prize until the prescribed number of days AFTER it is marked in-house, not from the original win date.
TEST-DATA HINTS: Example email copy: "Your prize is not in yet, but we will email you when it is!" and "Your prize is ready for pick up!"

## WORKFLOW: Customize the Electronic Signed Documents Success Page
KEYWORDS: success page, signed documents, station logo, fulfillment notes
JIRA:
---
WHAT: Customizes the confirmation screen a winner sees after completing all required Electronic Signed Documents.
WHO: Users with access to vPromo settings (typically Promotions/Program Director).
WHERE: Settings / vPromo / Signed Documents Success Page.
HOW: 1. Go to Settings / vPromo / Signed Documents Success Page. 2. Choose the Station to customize. 3. Insert the station Logo (must already be uploaded in Settings / Firm / Stations). 4. Optionally add Fulfillment Notes from the Prize — written so listeners can understand them. 5. Save.
CONSTRAINTS: The station logo must already exist in Settings / Firm / Stations before it can be inserted here.
GOTCHAS: Without customization, winners see a generic default message — worth updating to match station branding/voice.
TEST-DATA HINTS: none given.

## WORKFLOW: Automatically Return Unassigned Prizes to the Prize Closet After a Contest
KEYWORDS: automatically return prizes, prize closet, end of contest, default setting
JIRA:
---
WHAT: Any Prizes or Prize Packages that were never assigned to a winner during a contest can be automatically returned to the Prize Closet once the contest ends, so they can be reused.
WHO: Users creating/editing contest Plays.
WHERE: Two equivalent locations: Contest Wizard "Create Plays" step (below Contest Notes, above the Off Air Play(s) checkbox) and PRF Details / Plays tab (checkbox at the top of the tab) — both labeled "Automatically return Prizes/Packages to the Prize Closet After Contest".
HOW: 1. In either the Wizard's Create Plays step or the Plays tab, check "Automatically return Prizes/Packages to the Prize Closet After Contest". 2. After checking/unchecking, a popup asks if you want to make that your default for all future contests — choose accordingly.
CONSTRAINTS: Return happens only after the PRF's End Date/Time has passed, and only for prizes/packages never assigned to a winner.
GOTCHAS: You'll get a notification in your To Do badge when prizes are returned this way, but only if the contest's station is included in your "Receive Approval Task Notifications for" stations in Settings / User / General Settings.
TEST-DATA HINTS: none given.
