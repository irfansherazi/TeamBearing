## WORKFLOW: Spot Revision Process
KEYWORDS: revision, request revision, revise, re-record, revision request, revise spot, client revision, revision process, revision workflow
---
Source: vsuitePlatform/playwright/tests/qa-197-revision-process.test.ts

REVISION PROCESS WORKFLOW
Tested roles: DemoProdDirector, DemoAccountExecutive, DemoClient

A revision request is submitted when a client or AE wants changes to
an already-produced spot. The workflow creates a new revision on the
existing production order.

══════════════════════════════════════════
STEP 1: Navigate to the Production Order
══════════════════════════════════════════
From the Production Orders list, click the client name in the table row.
Strategy for client name: get_by_text(clientName).first() NOT get_by_role("link", name=clientName)
  - Angular table rows do NOT expose ARIA link role.
After click: wait for order detail page or slideout panel to open.

══════════════════════════════════════════
STEP 2: Locate the Revision Button
══════════════════════════════════════════
Look for "Request Revision" or "Revise" button on the order detail view.
Strategy: get_by_role("button", name="Request Revision") OR get_by_text("Request Revision")
If button is not visible: scroll down in the detail view.

══════════════════════════════════════════
STEP 3: Fill Revision Notes
══════════════════════════════════════════
A modal or panel appears with a text area for revision notes.
Strategy: get_by_label("Revision Notes") OR get_by_role("textbox", name="Revision Notes")
Fill with the required revision description.

══════════════════════════════════════════
STEP 4: Submit the Revision Request
══════════════════════════════════════════
Click the submit/confirm button: get_by_role("button", name="Submit") OR get_by_role("button", name="Send")
After submit: wait for toast confirmation OR status change on the order.

══════════════════════════════════════════
VERIFICATION
══════════════════════════════════════════
Success indicators:
- Toast message containing "revision" or "submitted"
- Order status changes to "Needs Producing" or "Revision Requested"
- Revision history shows the new revision entry
