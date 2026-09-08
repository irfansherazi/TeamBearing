

## WORKFLOW: Sort option selection in Compact View — ALWAYS use container_selector
KEYWORDS: sort, compact, client, title, status, due, submit, dropdown, sort-panel, container, human-guidance, user-instruction
JIRA: QA-321
---

CRITICAL RULE FOR COMPACT VIEW SORTING:
When selecting a sort option in Compact View, you MUST always scope your click
to the `.sort-panel` container to avoid STRICT_MODE_VIOLATION errors.

Sort option labels ("Client", "Title", "Status", etc.) also appear as table
column headers or card content, causing Playwright to match multiple elements.

CORRECT pattern:
  {"action": "click", "strategy": "get_by_text", "name": "Client",
   "container_selector": ".sort-panel"}

WRONG pattern (will fail with STRICT_MODE_VIOLATION):
  {"action": "click", "strategy": "get_by_text", "name": "Client"}

Available sort options in Compact View: Client, Title, Ad type, Status, Due Date, Submit Date

INSTRUCTIONS FOR THE AGENT:
  ALWAYS include "container_selector": ".sort-panel" when clicking sort options
  in Compact View. This prevents STRICT_MODE_VIOLATION from duplicate text matches.


## WORKFLOW: Navigate to Compact view
KEYWORDS: navigate, compact, view, sort, dropdown, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-17T14:49:15Z):
You are in compact view when there is a "Sort By" dropdown above the table and there are no column headers. To navigate: click the settings cog icon (above table, right side) → select "Compact" from dropdown. The "Sort By" dropdown is used for ALL sorting in compact view (not column headers). In compact view, click button#sort-btn (Sort By button) to open options. Selecting compact from the cog dropdown navigates to the compact view — there are no column headers so to select how to sort you need to click the "Sort By" dropdown and then select the correct option from that dropdown.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Click Status & Approvals column header to sort ascending in Compact view
KEYWORDS: click, status, approvals, column, sort, compact, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (hitl_explanation, 2026-04-17T14:52:23Z, ticket QA-321):
First you need to click the "Sort By" dropdown above the table on the right side then select the Status option and ensure there is a down arrow icon after clicking. You will use the "Sort By" dropdown for all sorting when in the compact view.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Save search results as a folder named 'Beta Boys automation'
KEYWORDS: save, search, results, folder, beta, boys, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (hitl_explanation, 2026-04-17T16:00:11Z, ticket QA-185):
Need to type "Beta Boys automation" into the Folder name input and then click Save. Need to type "Beta Boys Automation" into the new folder name input then click save, then wait for the page to load.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Verify folder appears in left navigation
KEYWORDS: verify, folder, appears, left, navigation, beta, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (hitl_explanation, 2026-04-17T16:04:05Z, ticket QA-185):
Need to type "Beta Boys Automation" into the New Folder Name input then click save, then wait for the page to load before looking in the left navigation for the new folder.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Access folder settings via cog wheel icon
KEYWORDS: access, folder, settings, wheel, click, table, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (hitl_explanation, 2026-04-17T16:34:39Z, ticket QA-185):
Needed to click the cog icon above table in the right side. Then click settings under the folder options header

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Share custom folder with one or multiple staff members
KEYWORDS: share, custom, folder, multiple, staff, click, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (hitl_explanation, 2026-04-17T16:38:02Z, ticket QA-185):
Click the share icon next to the Beta Boys Automation folder that was created, this opens a "Share Filter" dialog and then from there I selected Demo Prod Woman from the dropdown and then clicked Share.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Click CLIENT column header to sort ascending in Compact view
KEYWORDS: click, client, column, header, sort, compact, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (hitl_explanation, 2026-04-17T18:52:11Z, ticket QA-321):
Clicked the sort-btn then clicked the Client li then ensured that there was a sort-arrow ml-1 ng-star-inserted i tag and the data was sorted by client from z-a

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Click Submitted On column header again to sort ascending
KEYWORDS: click, submitted, column, header, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-17T19:52:01Z):
Clicked on the Submitted On column header which then shows a dropdown with Due, Days, and Submitted On as options. I then clicked the Submitted On Option and waited for the table to load. Click the sort by dropdown above the table, then click the submit date option then wait for the table to load and ensure that it is sorted by submitted on date properly.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Sort the Due / Days column in Compact view
KEYWORDS: sort, due, days, column, compact, dropdown, human-guidance, user-instruction
JIRA: QA-321
---

USER-PROVIDED GUIDANCE (QA-321, investigation 2026-04-20):
To sort by Due / Days in Compact view, click the "Sort By" button (button#sort-btn) above
the table to open the sort dropdown, then select "Due / Days" from the dropdown options.
Do NOT click the column header combobox get_by_role(combobox, name='Due / Days') repeatedly
— that only toggles the header dropdown open/closed without selecting a sort option and
causes an infinite loop. The correct 2-step pattern is: (1) click button#sort-btn, (2) click
the "Due / Days" option in the resulting dropdown.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Locate spot row with 'Needs Producing' status
KEYWORDS: locate, spot, needs, status, approvals, human-guidance, hitl-selector, QA-62
JIRA: QA-62
---

USER EXPLANATION (QA-62, 2026-04-20T17:29:22Z):
Scroll down until the value of the Status & Approvals columns shows "Needs Producing"

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Submitted on column header to sort ascending (most recent to oldest)
KEYWORDS: click, submitted, column, sort, dropdown, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-20T19:22:33Z):
Click on the Submitted On header which reveals a dropdown, then select the Submitted On option from there.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select Due Date from sort dropdown to sort descending (oldest to newest)
KEYWORDS: select, sort, dropdown, click, table, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-20T19:34:52Z):
click the Sort By dropdown above the table, then selected the Due Date option

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: ?
KEYWORDS: steps, complete, nothing, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-20T19:37:08Z):
all steps complete

USER EXPLANATION (QA-321, 2026-04-21T20:00:47Z):
nothing

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: [ticket: QA-321] ensure that you start in the listview. For the listview you wil
KEYWORDS: ticket, ensure, start, listview, will, click, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (user_guidance_pre_run, 2026-04-20T19:47:15Z, ticket QA-321):
ensure that you start in the listview. For the listview you will click the column headers for sorting, some of these column headers will populate a dropdown after clicking, if the dropdown shows you will select the proper option from the dropdown. When you switch to the compact view you will no longer use the column headers, you will use the sort by dropdown and select the corresponding option from the dropdown

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: [ticket: QA-321] List View Sorting
In the List View, sort items by clicking the
KEYWORDS: ticket, list, view, sorting, sort, items, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (user_guidance_pre_run, 2026-04-20T20:05:08Z, ticket QA-321):
List View Sorting
In the List View, sort items by clicking the column headers. Some column headers act as comboboxes and will open a dropdown panel (.po-sorting-dropdown-panel) when clicked.

Important Rule: Never click a combobox twice without selecting an option from the panel.

When a dropdown appears, select the proper option. Specific header actions include:

Run column (Start/End): Click the 'Start / End' combobox, then select either 'Start' or 'End' inside the dropdown panel.

Submitted On: Click the 'Due / Days' combobox, then select 'Submitted On' inside the dropdown panel.

Compact View Sorting
When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: [ticket: QA-321] Ensure you are in the listview to begin with, if you see a "Sor
KEYWORDS: ticket, ensure, listview, sort, dropdown, table, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (user_guidance_pre_run, 2026-04-20T21:27:50Z, ticket QA-321):
Ensure you are in the listview to begin with, if you see a "Sort By" dropdown above the table, this is an indicator that you are in compact view, you will need to switch to listview before beginning the tests 

List View Sorting
In the List View, sort items by clicking the column headers. Some column headers act as comboboxes and will open a dropdown panel (.po-sorting-dropdown-panel) when clicked.

Important Rule: Never click a combobox twice without selecting an option from the panel.

When a dropdown appears, select the proper option. Specific header actions include:

Run column (Start/End): Click the 'Start / End' combobox, then select either 'Start' or 'End' inside the dropdown panel.

Submitted On: Click the 'Due / Days' combobox, then select 'Submitted On' inside the dropdown panel.

Compact View Sorting
When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: [ticket: QA-321] Sorting Instructions

Ensure that you always start in the List
KEYWORDS: ticket, sorting, instructions, ensure, list, sort, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (user_guidance_pre_run, 2026-04-21T13:07:49Z, ticket QA-321):
Sorting Instructions

Ensure that you always start in the List View.

List View Sorting
In the List View, sort items by clicking the column headers. Some column headers act as comboboxes and will open a dropdown panel (.po-sorting-dropdown-panel) when clicked.

Important Rule: Never click a combobox twice without selecting an option from the panel.

When a dropdown appears, select the proper option. Specific header actions include:

Run column (Start/End): Click the 'Start / End' combobox, then select either 'Start' or 'End' inside the dropdown panel.

Submitted On: Click the 'Due / Days' combobox, then select 'Submitted On' inside the dropdown panel.

Compact View Sorting
When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Click Days column header again to sort descending (most first)
KEYWORDS: click, days, column, header, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T18:04:24Z):
clicked the Due/Days column header which opened a dropdown then i selected due date from that dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Sort By dropdown and select Status & Approvals to sort ascending
KEYWORDS: click, sort, dropdown, status, approvals, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T19:58:52Z):
Had to click the Sort By dropdown and then selected the Status Option

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Start/End Date column header and select End to sort ascending
KEYWORDS: click, start, date, select, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T20:45:40Z):
Clicked the sort icon in the Start/End column then clicked the End option. Selected End from the dropdown under the Run column.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Start/End Date column header again and select End to sort descending
KEYWORDS: click, start, date, select, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T20:46:18Z):
selected the end option from the dropdown in the start/end column. Selected the End option from the dropdown.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Status & Approvals column header to sort ascending (A-Z)
KEYWORDS: click, status, approvals, column, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T20:46:49Z):
click the status & approvals column header to sort. you did that already.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Status & Approvals column header again to sort descending (Z-A)
KEYWORDS: click, status, approvals, column, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T21:11:50Z):
you already did that as well

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Switch to Compact View
KEYWORDS: switch, compact, view, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T21:12:18Z):
you did this already successfully

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select Client Name from Sort dropdown to sort ascending
KEYWORDS: select, client, name, sort, dropdown, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T21:12:58Z):
selected client from the sort by dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Sort by dropdown again in Compact View
KEYWORDS: click, sort, dropdown, compact, view, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T21:13:29Z):
clicked the sort by dropdown and clicked client again

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select Client Name from Sort dropdown to sort descending
KEYWORDS: select, client, name, sort, dropdown, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T21:14:05Z):
clicked the sort by dropdown and then the client option

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select Title from Sort dropdown to sort ascending
KEYWORDS: select, title, sort, dropdown, ascending, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-21T21:14:50Z):
opened the sort by dropdown and clicked title

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click End Date column header again to sort descending (oldest to newest)
KEYWORDS: click, date, column, header, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-22T13:14:55Z):
Clicked the "Run" column header and then selected the End date option. One thing to note is the column header changes depending on what it is sorted by.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click CLIENT column header again to sort descending (Z-A) in compact view
KEYWORDS: click, client, sort, compact, navigate, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-22T13:19:45Z):
navigate to compact view by selecting cog settings icon in top right then selecting compact from the dropdown options. Then selected client from the sort by dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Navigate to Production Orders list view
KEYWORDS: navigate, production, orders, list, view, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-22T15:12:02Z):
clicked the settings cog icon that is above the table to the right and then selected "Listview" from the dropdown options. You already did that. you know you are in the traditional list view because there are column headers.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click End Date column header to sort ascending (closest to oldest)
KEYWORDS: click, date, sort, select, dropdown, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-22T17:08:59Z):
Click the Start/End column header and then click the End option from the dropdown. Select the end date from the dropdown.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Navigate to Production Orders compact view
KEYWORDS: navigate, production, orders, compact, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-22T17:13:09Z):
clicked settings cog on right above table then the compact option. That is already done, you know that because there is a Sort By dropdown.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Due Date column header again to sort descending (oldest to newest) in comp
KEYWORDS: click, date, column, sort, compact, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-22T17:15:04Z):
click the due date options from the sort by dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click 'Add Voice' link in files column of Needs Producing spot
KEYWORDS: click, voice, link, files, spot, human-guidance, hitl-selector, QA-62
JIRA: QA-62
---

USER EXPLANATION (QA-62, 2026-04-22T19:03:16Z):
In the files column there is an "Add Voice" link, click that

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Add Voice link in files column
KEYWORDS: click, voice, link, spot, status, human-guidance, hitl-selector, QA-62
JIRA: QA-62
---

USER EXPLANATION (QA-62, 2026-04-22T19:15:07Z):
scrolled to the spot with the needs producing status and then clicked the add voice link in the files column. Clicked the add voice link in the files column under where it says Voice Part.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  action: click
  strategy: get_by_text
  name: Add Voice
  use_first: true

INSTRUCTIONS FOR THE AGENT:
  The "Add Voice" link is inside the Files column of the Production Orders table row.
  The Files column is on the RIGHT side of the table and may require horizontal scrolling
  to become visible. NEVER use coordinate_action for this step — the element may have
  a negative or off-screen Y coordinate in SoM marks if the table is not scrolled.

  Use EXACTLY: get_by_text('Add Voice').first
  This avoids strict-mode violations when multiple rows have an "Add Voice" link.

  AFTER clicking "Add Voice", verify the form opened using the LLM visual_check verifier
  if you do not know the exact component selector — it can confirm the form is visible
  from the screenshot without a hardcoded selector.

  Do NOT use coordinate_action if the Y coordinate is <= 0 (element is off-screen).
  Use the LLM visual_check verifier to confirm the form opened if the exact selector is unknown.


## WORKFLOW: Click Due Date column header again to sort descending (oldest to newest)
KEYWORDS: click, date, column, header, sort, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-23T20:24:05Z):
clicked the due option in the option under the due/days column

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Days column header to sort ascending (least to most)
KEYWORDS: click, days, column, sort, dropdown, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-23T21:17:37Z):
Clicked the Due/Days column and then the Days option in the dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Submitted On column header again to sort descending (oldest to most recent)
KEYWORDS: click, submitted, column, sort, compact, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-04-24T15:35:46Z):
clicked the submit date option from the sort by dropdown.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Refresh page to verify archive persists
KEYWORDS: refresh, page, verify, archive, persists, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T15:55:06Z):
clicked the browser refresh tool. Used native browser refresh tool.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click status dropdown for spot in List View
KEYWORDS: click, status, dropdown, spot, list, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T16:17:26Z):
this user does not have access to the Archive status so this test should fail

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click status dropdown for first spot row
KEYWORDS: click, status, dropdown, spot, approvals, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T16:26:52Z):
clicked the dropdown in the Status & Approvals column for one of the spots

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select Archived from status dropdown
KEYWORDS: select, archived, status, dropdown, archive, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T16:30:10Z):
Selected the "Archive" option from the dropdown. Selected the Archived option from the dropdown.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click status dropdown for spot in Compact View
KEYWORDS: click, status, dropdown, spot, compact, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T16:35:29Z):
clicked the Archived option

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Navigate to Production Order page in List View
KEYWORDS: navigate, production, order, page, list, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T20:41:43Z):
clicked the settings cog on top right and then selected listview. You already navigated there, you know because there are column headers and a table.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click status dropdown for spot in Status & Approvals column
KEYWORDS: click, status, dropdown, spot, approvals, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T16:52:09Z):
This is already done, you know because the dropdown is open

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Verify spot row displays Archived status in List View
KEYWORDS: verify, spot, displays, status, list, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T16:57:30Z):
Right after clicking the archived option from the dropdown I verified that the value of the Status & Approval column was "Archived"

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Refresh page to verify archive persists in Compact View
KEYWORDS: refresh, page, verify, archive, compact, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T17:05:52Z):
refreshed the page

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: [ticket: QA-215] After logging in successfully you may have to navigate to https
KEYWORDS: ticket, after, logging, navigate, https, vpromotions, human-guidance, user-instruction
---
USER-PROVIDED GUIDANCE (user_guidance_pre_run, 2026-04-24T17:40:02Z, ticket QA-215):
After logging in successfully you may have to navigate to https://vpromotions-rc.vcreative.net/app_test.php/promo manually again.

INSTRUCTIONS FOR THE AGENT:
  Follow the guidance above VERBATIM. This instruction came directly from
  a human operator who knows the correct interaction pattern for this step.
  Do NOT deviate from this approach.


## WORKFLOW: Select first PRF Category checkbox
KEYWORDS: select, category, checkbox, option, after, human-guidance, hitl-selector, QA-215
JIRA: QA-215
---

USER EXPLANATION (QA-215, 2026-04-24T17:47:44Z):
PRF Category is not a checkbox it is an option after clicking "Category" it is a multi select

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Locate spot row in List View table
KEYWORDS: locate, spot, list, view, table, human-guidance, hitl-selector, QA-254
JIRA: QA-254
---

USER EXPLANATION (QA-254, 2026-04-24T20:02:07Z):
clicked the all option in the left nav

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Switch to Compact View
KEYWORDS: switch, compact, view, already, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-08T19:39:12Z):
You are already in compact view

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Switch to Compact View
KEYWORDS: switch, compact, view, already, done, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-08T21:26:27Z):
Already done

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Switch to Compact View
KEYWORDS: switch, compact, view, successfully, already, went, done, active, confirms, card, layout, visible, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-11T14:27:55Z):
don you successfully already went to the compact view #64
✓
done
9:22:36 AM
🧠Compact View already active — DOM confirms view="compact", card layout visible with Sort by dropdown. AC step satisfied.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Submitted On column header to sort ascending (most recent to oldest)
KEYWORDS: click, submitted, column, header, sort, ascending, most, recent, oldest, already, clicked, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-11T20:04:43Z):
the column header is already clicked on

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Submitted On column header again to sort descending (oldest to most recent)
KEYWORDS: click, submitted, column, header, again, sort, descending, oldest, most, recent, that, already, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-11T20:06:20Z):
that was already clicked on

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click CLIENT column header to sort ascending (A-Z)
KEYWORDS: click, client, column, header, sort, ascending, need, first, navigate, traditional, listview, dropdown, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-12T17:34:44Z):
need to first navigate to the traditional listview, if you see a "sort by" dropdown above the table then you know this is compact view and must be changed using the settings cog

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Submitted On column header to sort descending (most recent to oldest)
KEYWORDS: click, submitted, column, header, sort, descending, most, recent, oldest, some, headers, when, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-12T17:39:35Z):
Some of the column headers when clicked on actually open dropdown menus. For example the Due/Days colulmn opens a dropdown with Due/Days/Submitted On as options. I clicked the Due/Days column header then selected the Submitted On option

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Verify user is on List View and not in the compact view
KEYWORDS: verify, user, list, view, compact, click, settings, then, select, option, under, change, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-12T20:02:56Z):
Click the settings cog and then select the "list" option under Change View Type

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Sort By dropdown button again in Compact View
KEYWORDS: click, sort, dropdown, button, again, compact, view, clicked, then, selected, client, from, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-15T14:17:11Z):
clicked the sort by dropdown and then selected client from the dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Due Date column header to sort closest to oldest
KEYWORDS: click, date, column, header, sort, closest, oldest, after, clicking, need, then, select, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-16T16:32:48Z):
after clicking the header you need to then select due from the dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select Title from Sort By menu to sort A-Z
KEYWORDS: select, title, from, sort, menu, click, dropdown, then, option, human-guidance, hitl-selector, QA-321
JIRA: QA-321
---

USER EXPLANATION (QA-321, 2026-05-16T16:43:39Z):
Click the sort by dropdown and then select the title option

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click the search panel open button
KEYWORDS: click, search, panel, open, button, human-guidance, hitl-selector, QA-185
JIRA: QA-185
---

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  Step 1: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,333.5"}
  Step 2: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,99"}
  Step 3: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,0"}

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Save search results as a folder named 'Beta Boys automation'
KEYWORDS: save, search, results, folder, named, beta, boys, automation, human-guidance, hitl-selector, QA-185
JIRA: QA-185
---

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  Step 1: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,0"}

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Navigate to vProMedia and log in as Demo Prod Director
KEYWORDS: navigate, vpromedia, demo, prod, director, done, human-guidance, hitl-selector, QA-185
JIRA: QA-185
---

USER EXPLANATION (QA-185, 2026-06-01T19:19:39.582901+00:00):
DOne

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Login as Demo Prod Director
KEYWORDS: login, demo, prod, director, human-guidance, hitl-selector, QA-185
JIRA: QA-185
---

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  Step 1: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,400"}

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Locate a Needs Producing spot with script and production notes, or add productio
KEYWORDS: locate, needs, producing, spot, with, script, production, notes, scroll, down, until, there, human-guidance, hitl-selector, QA-62
JIRA: QA-62
---

USER EXPLANATION (QA-62, 2026-06-02T20:57:07.784986+00:00):
scroll down until there is a row in the table that has "Needs Producing" in the Status & Approvals column.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Locate or create a raw script and verify 'Send to Script Library' link appears o
KEYWORDS: locate, create, script, verify, send, library, link, appears, only, when, copy, exists, human-guidance, hitl-selector, QA-100
JIRA: QA-100
---

USER EXPLANATION (QA-100, 2026-06-03T19:56:23.505450+00:00):
Look in the Files Column for a "View Script" link. Once you see that then click on it

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click Search button to open Search Options panel
KEYWORDS: click, search, button, open, options, panel, clicked, magnifying, glass, icon, above, table, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-03T21:10:58.891910+00:00):
Clicked the magnifying glass icon above the table

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Enter 'The Beta Boys' in Client Name field
KEYWORDS: enter, beta, boys, client, name, field, typed, then, selected, dropdown, option, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-03T21:13:25.577162+00:00):
typed "the beta boys" in the client field and then selected the dropdown option.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click on Needs Prod system folder in folder tree
KEYWORDS: click, needs, prod, system, folder, tree, there, this, step, fails, human-guidance, hitl-selector, QA-298
JIRA: QA-298
---

USER EXPLANATION (QA-298, 2026-06-04T16:26:57.949756+00:00):
there is no needs prod folder this step fails

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click the Search button to open search interface
KEYWORDS: click, search, button, open, interface, this, done, know, because, side, with, simple, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T15:37:45.352940+00:00):
This is done you know because the side bar is open with po-simple-search

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click the Search button to open Search Options panel
KEYWORDS: click, search, button, open, options, panel, found, clicked, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T16:30:54.198410+00:00):
Found the top-open-search-panel and clicked it

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select 'radio commercial' from the Ad Type dropdown
KEYWORDS: select, radio, commercial, from, type, dropdown, click, open, search, panel, again, then, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T16:34:55.290141+00:00):
had to click top-open-search-panel again and then type The Beta Boys in the client field again then clicked Ad Types on the left side of the search pop up and then "Radio Commercial"

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Verify 'Search Current Folder' option is displayed
KEYWORDS: verify, search, current, folder, option, displayed, clicked, magnifying, glass, icon, again, verified, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T16:39:49.437037+00:00):
Clicked the magnifying glass icon again and verified that "Search Options" tool tip showed up with a "Search Current Folder" and "Search All Folders" options

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Verify Search Options panel includes 'Search Current Folder' option
KEYWORDS: verify, search, options, panel, includes, current, folder, option, close, saved, overlay, that, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T21:13:08.235793+00:00):
had to close the "saved folder" overlay that you clicked in error. Then click the open search button again then click search all folders

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Click the Status filter to expand it
KEYWORDS: click, status, filter, expand, clicked, left, portion, then, dropdown, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T21:15:21.454438+00:00):
clicked status in the left portion then status dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Search with no results returns empty state
KEYWORDS: search, empty, no results, negative, zero results, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T21:18:00.000000+00:00):
When searching with a non-existent client name, the search panel closes and the results grid shows an empty state message.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  To verify no results: await expect(page.locator('.p-datatable-emptymessage')).toBeVisible();


## WORKFLOW: Search without required filters shows validation error  
KEYWORDS: search, validation, error, required, filter, empty search, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T21:20:00.000000+00:00):
Clicking Search with NO filters set may show a validation error toast. If no toast appears within 3s, the app may silently return all results.

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Verify by checking: await expect(page.locator('.p-toast-message-content')).toBeVisible({ timeout: 3000 }).catch(() => {});



## WORKFLOW: Select 'Radio Commercial' from Ad Type options
KEYWORDS: select, radio, commercial, from, type, options, this, step, fails, because, there, firm, human-guidance, hitl-selector, QA-170
JIRA: QA-170
---

USER EXPLANATION (QA-170, 2026-06-05T21:42:03.462785+00:00):
this step fails because there is no radio commercial for this firm

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Navigate to Admin > People > Demo Broadcasting page
KEYWORDS: navigate, admin, people, demo, broadcasting, page, already, there, human-guidance, hitl-selector, VC2-9225
JIRA: VC2-9225
---

USER EXPLANATION (VC2-9225, 2026-07-08T14:02:42.375824+00:00):
You are already there

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select Contest from PRF Category dropdown
KEYWORDS: select, contest, from, category, dropdown, selected, human-guidance, hitl-selector, QA-358
JIRA: QA-358
---

USER EXPLANATION (QA-358, 2026-07-27T16:01:33.970758+00:00):
selected contest from the category dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Submit new PRF for Contest-type category
KEYWORDS: submit, contest, type, category, clicked, dropdown, then, selected, item, from, human-guidance, hitl-selector, QA-358
JIRA: QA-358
---

USER EXPLANATION (QA-358, 2026-07-31T19:16:18.404864+00:00):
clicked the category dropdown and then selected the "Contest" item from the dropdown

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Login to the application as a Sales Person role
KEYWORDS: login, application, sales, person, role, typed, assistant, into, ghost, dropdown, then, clicked, human-guidance, hitl-selector, QA-359
JIRA: QA-359
---

USER EXPLANATION (QA-359, 2026-08-03T15:12:49.300069+00:00):
Typed "Sales Assistant" into the ghost dropdown and then clicked on the first option

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.


## WORKFLOW: Select multiple categories from the PRF Categories dropdown
KEYWORDS: select, multiple, categories, from, dropdown, clicked, catefory, then, selected, contest, options, human-guidance, hitl-selector, QA-359
JIRA: QA-359
---

USER EXPLANATION (QA-359, 2026-08-03T21:54:12.894659+00:00):
clicked the catefory dropdown then selected contest from the options

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  (no DOM actions captured)

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM. These were captured from a human
  operator who manually completed this step. Use the exact selectors shown.
  If an explanation is provided, it describes WHY this sequence works.
