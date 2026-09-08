# vSuite / vProMedia — Agent Action Knowledge Base
# =================================================
# This file is loaded at startup and queried by the planner before each
# AC step. Add new workflows below using the established format.
#
# Format:
#   ## WORKFLOW: <short name>
#   KEYWORDS: <comma-separated trigger words>
#   ---
#   Step-by-step instructions the agent should follow.
#
# The agent will include the most relevant section(s) in its prompt
# when those keywords appear in the current AC step text.


## WORKFLOW: Login / Authentication
KEYWORDS: login, sign in, enter credentials, email field, password field, log in
FORBIDDEN_KEYWORDS: failed, invalid, wrong, error, denied, rejected, bad credentials
---
The vProMedia login page is at https://two-test.vcreative.net (or the target URL).

1. The login form has two fields:
   - Email: get_by_label("Email") or get_by_placeholder("Email")
   - Password: get_by_label("Password") or get_by_placeholder("Password")
2. Fill in the email field first, then the password field.
3. Click the "Login" button (get_by_role("button", name="Login")).
4. On successful login, the app redirects to the main dashboard/home screen.
5. On failed login (wrong credentials), a toaster/snackbar notification appears
   at the top or bottom of the page with the message "Error: Invalid User" or similar.
   The toaster appears IMMEDIATELY after clicking Login — check for it right away
   before it disappears (it auto-dismisses in ~3-5 seconds).
6. The login page URL typically ends in /login or /auth.


## WORKFLOW: Failed Login Testing
KEYWORDS: failed login, invalid login, wrong password, wrong credentials, invalid user, login failure, login error, bad credentials
FORBIDDEN_KEYWORDS: success, dashboard, already logged, logged in successfully
---
When testing FAILED login scenarios (expect_login_failure=True mode):

The browser starts on the login page WITHOUT any credentials filled in.
The agent has NOT authenticated — no JWT exists in localStorage.

The AC steps must explicitly:
1. Fill the email field with the test email (specified in the AC step text).
   Use: {"action": "fill", "strategy": "get_by_role", "role": "textbox", "name": "Email", "value": "<email from AC>"}
2. Fill the password field with the WRONG password (specified in the AC step text).
   Use: {"action": "fill", "strategy": "get_by_role", "role": "textbox", "name": "Password", "value": "<wrong password>"}
3. Click the Login button.
   Use: {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Login"}
4. Verify the failure indicators:
   - Toast message: "Error: Invalid User" or "Invalid credentials"
     Use: {"action": "verify", "strategy": "get_by_role", "role": "alert"}
     Or: {"action": "verify", "strategy": "get_by_text", "name": "Invalid"}
   - URL stays on /login (does NOT redirect to dashboard)
   - No vc2JWT in localStorage
   - Login form remains visible (email + password fields still present)
   - No sidebar navigation appears

TIMING: The error toaster appears IMMEDIATELY after clicking Login.
Check for it right away — it auto-dismisses in 3-5 seconds.
If the toast is missed, verify the URL still contains /login and the login form
is still visible as a fallback.

SELECTORS for failure verification:
  - Toast: get_by_role("alert") or css_selector(".p-toast-message-content")
  - Alert banner: css_selector(".alert.alert-danger")
  - URL check: verify URL still contains /login or /auth
  - Login form still visible: get_by_role("textbox", name="Email") is visible

IMPORTANT: In this mode, the agent should NOT attempt to authenticate successfully.
The entire purpose is to verify that the application correctly rejects invalid credentials.


## WORKFLOW: Create a New Quick Order (Radio Commercial)
KEYWORDS: new request, quick order, radio commercial, create order, new order, ad type
---
A "Quick Order" is a new production request. Steps to create one:

1. In the top-left navigation, below the "vProMedia" heading, click
   "New Request +" button.
2. A modal/drawer opens with Ad Type options. Select "Radio Commercial"
   (or the type specified in the AC).
3. After selecting the Ad Type, a Quick Order form appears with fields:
   - Client (required)
   - Station/Market
   - Spots / Due Date
   - Instructions / Copy
4. Fill in all required fields as specified in the AC.
5. To submit, click the "Submit" or "Save" button at the bottom of the form.
6. On success, the order appears in the Production Orders list.


## WORKFLOW: Navigate to Production Orders
KEYWORDS: production orders, order list, existing order, click the link in the client column, client column
---
1. In the left sidebar navigation, find "Production Orders" or similar.
2. Click to open the production orders list.
3. Orders are displayed in a table with columns: Client, Station, Status, Due Date, etc.
4. To open an existing order, click the link in the "Client" column (the client name
   is a clickable link, not the order ID).

⚠️ CRITICAL — ANGULAR TABLE ROW CLICKS:
Angular components in vProMedia do NOT expose proper ARIA link roles on table rows.
`get_by_role("link", name="Zombieland")` or any `get_by_role(link/row)` on table content
will ALWAYS TIMEOUT because the ARIA role is not present in the accessibility tree.

**CORRECT strategy for clicking any row/item in a list or table:**
- ALWAYS use: `strategy="get_by_text"` with `name="<exact visible text>"`
- Example: `{"action": "click", "strategy": "get_by_text", "name": "Zombieland"}`
- Do NOT use `get_by_role(link)`, `get_by_role(row)`, or `get_by_role(cell)` for table content
- If the name has special characters like `$` or `&`, still use `get_by_text` — it matches text content directly
- If multiple matches: add `.first` — Playwright will click the first visible occurrence


5. This opens the Quick Order detail view/drawer.


## WORKFLOW: Upload Files (Traffic / Production)
KEYWORDS: upload, attach file, upload files, traffic, production upload, drag and drop
---
1. File upload areas in vSuite typically appear as a dashed-border drop zone
   or a button labeled "Upload" / "Attach Files" / "+ Add Files".
2. To trigger file upload: click the upload button or the drop zone area.
3. A native file picker dialog will open. The agent cannot interact with native
   OS dialogs — use the "fill" action on a hidden file input if available:
   get_by_role("textbox") may not work; look for input[type=file] via
   strategy "css" with value "input[type='file']".
4. After file selection, a progress indicator shows upload status.
5. Uploaded files appear as a list with filename, size, and a remove (×) button.


## WORKFLOW: Inline Edit / Spot Editing
KEYWORDS: inline edit, edit spot, edit in place, inline, line edit, spot title
---
1. Inline-editable cells in vSuite typically become active on a single or double click.
2. Look for a pencil/edit icon (✏) that appears on hover near the cell.
3. Click the edit icon or double-click the cell text to enter edit mode.
4. A text input or dropdown replaces the display text.
5. To save: press Enter, click a checkmark/confirm button, or click outside the cell.
6. To cancel: press Escape, or click an × cancel button.
7. If a cell does NOT become editable, the user role may not have line_edit permission.


## WORKFLOW: Navigate to Approvals Queue
KEYWORDS: approvals, approve, approval queue, pending approval
---
1. In the left sidebar, look for "Approvals" or an approval-related menu item.
2. The approvals list shows items pending user action.
3. To approve: open the item, then click "Approve" or a green checkmark button.
4. To reject: click "Reject" and enter a reason if prompted.
5. Approved items move out of the queue immediately.


## WORKFLOW: Switch User Roles / Views
KEYWORDS: switch role, change role, role selector, view as, impersonate
---
1. Role switching in vSuite is done at the account level (separate logins per role).
2. Each role has distinct login credentials — the test credentials are in the Jira ticket.
3. There is no in-app role switcher; log out and log in with different credentials to change roles.
4. After login, the role's permission set determines what menu items, buttons, and


## WORKFLOW: Logout / Switch Account
KEYWORDS: logout, log out, switch account, switch to, sign out, switch back, switch user, voicer account
---
⚠️ **IMPORTANT — How to Logout in vProMedia:**

The Logout link is INSIDE a user dropdown menu that must be OPENED first.
`get_by_text('Logout')` WILL FAIL because the Logout link is hidden until the dropdown is open.
`get_by_text('<username>')` WILL FAIL because the username text appears 5+ times in the DOM (strict mode violation).

**Correct logout sequence:**
1. Click the user avatar button in the top-right corner using get_by_role to OPEN the dropdown.
   - ALWAYS USE: `{"action": "click", "strategy": "get_by_role", "role": "button", "name": "<current_username>"}`
   - Example: `{"action": "click", "strategy": "get_by_role", "role": "button", "name": "Cameron Works"}`
   - DO NOT use get_by_text for the username — it matches 5 elements and throws strict mode violation.
2. After the dropdown opens, THEN click Logout:
   - `{"action": "click", "strategy": "get_by_text", "name": "Logout"}`
3. The login page should appear after logout.
4. Log in with the new role's credentials.


## WORKFLOW: Navigate to MyBox / Side Navigation
KEYWORDS: mybox, my box, navigate to, open mybox, sidebar, left nav, navigation menu
---
⚠️ **IMPORTANT — MyBox text appears many times in the DOM (strict mode violation risk):**

`get_by_text('MyBox')` resolves to 9+ elements and will throw a strict mode violation.

**Correct strategy for sidebar nav:**
- ALWAYS use get_by_role to click nav links:
  `{"action": "click", "strategy": "get_by_role", "role": "link", "name": "MyBox"}`
- The Voice Requests folder inside MyBox:
  `{"action": "click", "strategy": "get_by_text", "name": "Voice Requests"}`
- The Production Orders sidebar nav:
  `{"action": "click", "strategy": "get_by_role", "role": "link", "name": "Production Orders"}`



## WORKFLOW: Toaster / Notification Verification
KEYWORDS: toaster, toast, notification, snackbar, banner, message appears, success message, error message
---
Toasters in vSuite are transient — they appear and auto-dismiss in 3-5 seconds.

CRITICAL TIMING RULE:
- The toaster appears IMMEDIATELY after the triggering action (button click).
- Do NOT wait or take another action before checking for the toaster.
- After any action that should produce a toaster, use "verify" action IMMEDIATELY.
- The verify action should look for get_by_role("alert") or get_by_text with the
  expected message text.
- If the toaster is gone by the time you check, the transient_page_text observation
  captured right after the action may still contain its text — check that too.

Common toaster patterns:
  - Success: "Saved successfully", "Order created", "File uploaded"
  - Error: "Error: Invalid User", "Something went wrong", "Permission denied"


## WORKFLOW: Form Submission and Validation
KEYWORDS: submit form, required field, validation, error, form error, save changes
---
1. Required fields in vSuite forms are usually marked with an asterisk (*) or red border.
2. If a required field is empty and you click Submit, an inline error message appears
   below the field (not always a toaster).
3. Use "verify" action to check for error messages after a failed submit.
4. Disabled submit buttons mean not all required fields are filled — check the form.
5. After successful submit, the form closes and the list/view refreshes.


## WORKFLOW: Navigation and Page URL Patterns
KEYWORDS: navigate to, go to url, testing url, target url, already on
---
Common vProMedia/vSuite URL patterns:
  - Login:              /login or /auth
  - Dashboard:          / or /home or /dashboard
  - Production Orders:  /production or /orders
  - Quick Orders:       /quick-orders or /requests
  - Approvals:          /approvals
  - Settings:           /settings
  - Reports:            /reports

If the AC step says "navigate to the testing URL" and you are already on that URL
(or any page within the app), return {"action": "done", "reasoning": "Already on the target URL."}.
Only issue a navigate action if you are on a completely different domain.


## WORKFLOW: Login Already Satisfied / Already Logged In
KEYWORDS: login as, log in as, demo, production director, prod man, already logged in, already on dashboard
FORBIDDEN_KEYWORDS: failed, invalid, wrong, error, denied, rejected
---
CRITICAL: Before attempting to fill a login form, ALWAYS check if the user is ALREADY logged in.

Signs the user is already logged in (return {"action": "done"} immediately):
- A user name or email is visible in the top-right corner of the page
- The URL is NOT a /login or /auth page
- You can see the vProMedia dashboard, MyBox, or production orders list
- The accessibility tree contains elements like "MyBox", "Production Orders", "New Request"

If ALREADY logged in, return:
{"action": "done", "reasoning": "User is already logged in as [name visible]. AC step satisfied."}

Only fill login credentials if you are actually on the login page (URL ends in /login or /auth,
and you can see Email + Password input fields with no dashboard content visible).


## WORKFLOW: MyBox — Producer / Production Manager View
KEYWORDS: mybox, my box, needs producing, production director, prod man, producer, production queue, find a spot
---
MyBox is the producer's personal queue. It shows spots assigned to them by status.

NAVIGATING TO MYBOX:
1. After login, MyBox is usually the default landing page for producers.
2. If not shown, click "MyBox" in the left sidebar navigation.
3. MyBox shows a table of spots with columns: Client, Title, Status, Due Date, Files, etc.

FINDING A SPOT WITH A SPECIFIC STATUS (e.g. "Needs Producing"):
⚠️ CRITICAL — vSuite tables use PrimeNG PAGINATION, NOT scroll.
Tables show 10-25 rows per page. Scrolling the page WILL NOT reveal more rows.

1. First CHECK the visible rows in the Status column for the desired status text.
2. If the desired status IS visible on the current page:
   → Click the CLIENT NAME (text in the Client column) in that row to open the order.
   → Use: {"action": "click", "strategy": "get_by_text", "name": "<client name>"}
3. If the desired status is NOT visible on the current page:
   → Click the NEXT PAGE button at the bottom of the table to load the next batch of rows.
   → The pagination controls look like: "1  2  3  4  >  >>"
   → To go to next page: {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Next Page"}
   → Or use: {"action": "click", "strategy": "get_by_text", "name": ">"}
   → After the new page loads, check the Status column again.
   → REPEAT pagination until you find the desired status.
4. NEVER use "scroll" action to find more items — it only scrolls the browser viewport,
   NOT the table data. The table data changes via pagination buttons.

OPENING A SPOT:
- Click the CLIENT NAME text in the row — it is a hyperlink.
- Use: {"action": "click", "strategy": "get_by_text", "name": "<client name>"}
- NEVER use get_by_role("link") for table rows — Angular does not expose ARIA link roles.
- Clicking the client name opens the Quick Order detail panel/drawer on the right.

IMPORTANT: "Needs Producing" is a STATUS LABEL displayed in the table row, NOT a clickable button.
Attempting get_by_role("button", name="Needs Producing") will ALWAYS fail.


## WORKFLOW: Status Badge / Status Dropdown Interaction
KEYWORDS: status, needs producing, needs dubbing, needs mixing, change status, update status, status dropdown, status badge
---
Status fields in vProMedia's list view are DROPDOWNS (combobox), not buttons.

CRITICAL RULES:
- NEVER use get_by_role("button", name="Needs Producing") — this will always timeout.
- Status badges in the list view are read-only display labels OR combobox dropdowns.
- To CHANGE a spot's status:
  1. First OPEN the spot by clicking the client name text.
  2. Inside the order detail, find the Status field — it is a <select> or combobox.
  3. Use: {"action": "select_option", "strategy": "get_by_role", "role": "combobox", "name": "Status", "value": "New Status Value"}
  4. Or click the status dropdown then click the desired option.
- To READ the current status: use verify action or read from the accessibility tree.

If you need to interact with a status shown in the LIST VIEW (not the order detail):
- Right-click the row to see if a context menu appears with status options.
- Or open the order first, then change status from within the order detail panel.


## WORKFLOW: Production Notes — Add / View Production Notes
KEYWORDS: production notes, add production notes, prod notes, add notes, production note, notes misc, notes section
---
"Add Production Notes" is a LINK inside the order detail panel, NOT a button.

CORRECT LOCATOR:
- Use: {"action": "click", "strategy": "get_by_text", "name": "Add Production Notes"}
- NEVER use get_by_role("button", name="Add Production Notes") — it is not a button element.

WHERE TO FIND IT:
1. Open the Quick Order detail panel (click client name text in the list view).
2. Look for the "Notes / Misc" section on the right side of the order panel.
3. If production notes already exist, a text block will be visible instead of the "Add" link.
4. If the link is not immediately visible, scroll down within the order detail panel.

ADDING NOTES:
1. Click the "Add Production Notes" link.
2. A text area / modal opens for entering notes.
3. Type the notes text using the "fill" action.
4. Click "Save" or "Submit" to save the notes.
5. Success: the notes text appears in the Notes/Misc section of the order.

CHECKING IF NOTES ALREADY EXIST:
- If the Notes/Misc section shows existing text (not the "Add Production Notes" link),
  the notes already exist — return {"action": "done", "reasoning": "Production notes already present."}.


## WORKFLOW: Script Access in Quick Order / Producer View
KEYWORDS: script, view script, script tab, open script, spot script, script content, check script, script exists
---
Scripts in vProMedia are stored within the Quick Order detail panel.

FINDING THE SCRIPT:
1. Open the order detail by clicking the client name text in the list view.
2. Inside the order panel, look for a "Script" tab or "Script" section.
3. Script content is displayed in a read-only text area or rich-text block.
4. The "Script" or "Copy" section is typically in the middle column of the order form.

CHECKING IF A SCRIPT EXISTS:
- If the Script field contains text, a script exists — you can read it from the a11y tree.
- If the Script field is empty or shows "No script", no script has been entered yet.
- Return {"action": "done", "reasoning": "Script confirmed present: [first few words]."} once verified.


## WORKFLOW: Locate a Spot with a Raw Script in the Files Column (View Script Link)
KEYWORDS: locate, spot, raw, script, view, files, column, link, view script, raw script, production orders files, QA-100
JIRA: QA-100
---
The "View Script" link appears in the **Files column** of the Production Orders table — the same column
that contains "Add Voice", "Add Music", "Upload File" etc.

⚠️ CRITICAL — Multiple rows may have a "View Script" link. Always use `.first` / `use_first: true`.

NAVIGATION:
1. You must be on the Production Orders page:
   {\"action\": \"click\", \"strategy\": \"get_by_role\", \"role\": \"link\", \"name\": \"Production Orders\"}
2. Scan visible rows in the **Files column** for a "View Script" link.
3. If no "View Script" is visible on the current page, use pagination (Next Page button) to find one.
4. If none exist at all, open a spot via its Title to add copy first.

CLICKING THE LINK:
- ALWAYS use `.first` — multiple rows may have this link:
  {\"action\": \"click\", \"strategy\": \"get_by_text\", \"name\": \"View Script\", \"use_first\": true}
- Do NOT use get_by_role(\"link\", name=\"View Script\") — may fail strict mode.
- The preferred selector: get_by_text(\"View Script\").first()

AFTER CLICKING "View Script":
- A slide-out panel opens on the right side of the screen showing the raw script copy.
- The panel contains a read-only text block with the script content.
- Verify the panel is visible: {\"action\": \"verify\", \"strategy\": \"get_by_text\", \"name\": \"Script\"}
- Read the script text from the accessibility tree or visible text block.

ANTI-PATTERNS:
  ✗ Do NOT try to open the order detail panel (client name click) — the "View Script" link is directly in the row.
  ✗ Do NOT use get_by_role(\"button\", name=\"View Script\") — it is a link, not a button.
  ✗ Do NOT scroll to find more rows — use pagination buttons (Next Page).


## WORKFLOW: Script Template Library Navigation
KEYWORDS: script template, template library, library, script library, copy library, template, open template
SECTION: Scripts & Copy
---
The Script Template Library stores reusable script templates that can be applied to production orders.

NAVIGATION PATH:
1. From the dashboard or any page, look in the left sidebar for a "Script Template Library" or "Templates" menu item.
   {\"action\": \"click\", \"strategy\": \"get_by_role\", \"role\": \"link\", \"name\": \"Script Template Library\"}
   OR: {\"action\": \"click\", \"strategy\": \"get_by_text\", \"name\": \"Script Template Library\"}
2. If not directly visible in the sidebar, look for it under a sub-menu:
   - Check "Settings" or "Admin" menus for a "Templates" submenu.
   - Or click "New Request +" → look for a "Use Template" option in the form.
3. The library opens as a list/table of saved script templates.

SELECTING A TEMPLATE:
- Each template row shows: Template Name, Client (if client-specific), Ad Type, Created By.
- Click the template name text to open/preview it:
  {\"action\": \"click\", \"strategy\": \"get_by_text\", \"name\": \"<template name>\"}
- To apply to a current order: look for an "Apply" or "Use This Template" button in the template detail.

CREATING A NEW TEMPLATE FROM A SCRIPT:
1. Open an existing order with a script.
2. In the Script/Copy section, look for a "Save as Template" or "Add to Library" link/button.
3. Give the template a name and click Save.

VERIFICATION:
- The library page shows a list of templates — verify with:
  {\"action\": \"verify\", \"strategy\": \"get_by_text\", \"name\": \"Script Template\"}
- After applying a template, the script field in the order should be pre-filled.

ANTI-PATTERNS:
  ✗ Do NOT confuse "Script Template Library" with the "View Script" link in the Files column — these are different features.
  ✗ Do NOT use get_by_role(\"button\") for template names — they are links or text.


## WORKFLOW: Self-Heal — Element Not Found / Timeout Recovery
KEYWORDS: timeout, element not found, timed out, locator, failed, retry, self heal, not visible
---
CRITICAL SELF-HEAL RULES — When an action times out or an element is not found:

1. NEVER repeat the exact same get_by_role/name combination that just failed.
2. Systematically try FALLBACK LOCATOR STRATEGIES in this order:
   a. get_by_text(exact element text visible on screen)
   b. get_by_label(label text near the input)
   c. get_by_placeholder(placeholder text in the input)
3. If the element is off-screen within a scrollable panel, use {"action": "scroll", "value": "down"} first.
   But NEVER scroll to find more TABLE ROWS — use pagination buttons instead.
4. After 2 consecutive timeouts on the same element:
   - Take a "wait" action for networkidle to let the page fully load.
   - Then try get_by_text() with the visible label text.
5. If an element has ARIA role combobox/select, use "select_option" not "click".

COMMON vSuite ELEMENT TYPES (not always announced correctly in a11y tree):
- Status badges → combobox or plain text, NOT button
- "Add X" links → <a> tags, use get_by_text NOT get_by_role("button")
- Tab headers → role="tab"
- Sidebar items → role="menuitem" or get_by_text
- Table row openers → use get_by_text (the client name text)
- "Add Voice" → <a> tag, use get_by_text("Add Voice")


## WORKFLOW: Opening an Order from List View (Client Name Link)
KEYWORDS: open order, open spot, click client, client name, open existing order, view order, open quick order, open the order
---
In vProMedia list views (MyBox, Production Orders, All Orders), orders are opened by
clicking the CLIENT NAME text — NOT the status badge, order ID, or row background.

CORRECT APPROACH:
1. Identify the order you want to open in the table.
2. Find the Client Name cell in that row — it is rendered as a hyperlink (<a> tag).
3. Click it: {"action": "click", "strategy": "get_by_text", "name": "<client name>"}
4. NEVER use get_by_role("link") — Angular does not expose ARIA link roles on table cells.
5. If multiple rows have the same client name, use the first match.
6. The Quick Order detail panel slides open on the right side of the screen.
7. Wait for the panel to fully load before interacting with fields inside it.

DO NOT:
- Click the Status badge/dropdown in the row (opens a status editor, not the order)
- Click row background (usually not interactive)
- Click the order number/ID column (may not be a link)


## WORKFLOW: Production Director / Production Manager — Workflow Steps
KEYWORDS: production director, prod director, production manager, prod man, demo prod, producer workflow, producing, producer
---
The Production Director / Production Manager role is responsible for fulfilling production orders.

TYPICAL PRODUCTION DIRECTOR WORKFLOW:
1. Log in with Production Director credentials (imail-test+DemoProdDirector@vcreativeinc.com).
2. MyBox loads automatically showing assigned production orders.
3. To work a "Needs Producing" spot:
   a. FIND the row with "Needs Producing" in the Status column (use PAGINATION if needed).
   b. Click the CLIENT NAME TEXT (not the status badge) to open the order.
      Use: {"action": "click", "strategy": "get_by_text", "name": "<client name>"}
   c. Review the Script tab for copy content.
   d. Check the Notes/Misc section for production notes.
   e. To add production notes if missing: click "Add Production Notes" (it is an <a> link — use get_by_text).
   f. To upload a produced file: use the file upload area (drag & drop zone).
   g. To mark as complete: change the Status from "Needs Producing" → next workflow status.
4. The status dropdown is inside the order detail panel — use select_option action.
5. Saving the status change triggers notifications to the assigned AE.


## WORKFLOW: Add Voice — Assign Voice Talent to a Spot
KEYWORDS: add voice, voice request, assign voice, voicer, talent, voice pool, voice assignment, voice part
---
"Add Voice" allows a Producer/Production Director to send a spot to voice talent.

PREREQUISITES:
- You must be logged in as a Producer or Production Director.
- The spot must be in a producible status (e.g. "Needs Producing").
- The spot must be opened (click the client name in the production orders table).

FINDING THE "ADD VOICE" LINK:
1. In the production orders list view, look at the FILES COLUMN for each row.
2. "Add Voice" appears as a clickable LINK (<a> tag) in the Files column.
3. It is NOT a button — it is an anchor link styled as blue text.
4. Use: {"action": "click", "strategy": "get_by_text", "name": "Add Voice"}
5. NEVER use get_by_role("button", name="Add Voice") — it will always time out.

VOICE REQUEST FORM:
1. After clicking "Add Voice", a form/dialog opens.
2. Fill in:
   - Due date / deadline for the voice part
   - Which part of the script to read (if multiple parts)
   - Notes to the voicer (instructions, pronunciation, tone, etc.)
3. Select the voice talent:
   - Search Type defaults to "Talent" — select specific talent by name
   - Or use "Talent Pool" to request from a group
   - Click the checkbox next to the desired talent name(s)
   - Click "Select Talent" to confirm
4. Click "Save" or "Send" to submit the voice request.

AFTER SUBMITTING:
- The Files column for that spot shows the voicer name(s) with "(waiting)" status.
- The voicer receives a notification and the spot appears in their "Voice Requests" folder.

VERIFYING VOICE ASSIGNMENT:
1. Check the Files column in the production orders list.
2. Look for the voicer name followed by "(waiting)" text.
3. Use verify action: {"action": "verify", "strategy": "get_by_text", "name": "(waiting)"}


## WORKFLOW: Voice Requests — Voicer's Perspective
KEYWORDS: voice requests folder, accept voice, voicer account, voice request accept, voice part, upload voice, record voice
---
When a producer assigns voice work, the voicer receives a request.

FINDING VOICE REQUESTS:
1. Log in as the voicer account.
2. In the left sidebar, navigate to MyBox.
3. Inside MyBox, look for the "Voice Requests" folder/section.
4. Click: {"action": "click", "strategy": "get_by_text", "name": "Voice Requests"}
5. The voice requests list shows pending assignments.

ACCEPTING A VOICE REQUEST:
1. Find the assigned spot in the Voice Requests list.
2. Click to open the spot detail.
3. Click "Accept" to accept the voice assignment.
   Use: {"action": "click", "strategy": "get_by_text", "name": "Accept"}
4. After accepting, the request opens showing:
   - Notes from the producer (entered during Add Voice)
   - The script / script section to read
   - File upload area for the voice recording

COMPLETING A VOICE REQUEST:
1. After accepting, you can:
   - View the script and production notes
   - Upload a voice file (attach a file)
   - Post a blog note about the voice work
2. Upload: drag & drop or click the upload area, select the audio file.
3. Blog: find the blog/notes section, type your message, click Post.
4. After uploading and blogging, the production director can see the attached file and notes.


## WORKFLOW: Table Pagination (PrimeNG)
KEYWORDS: pagination, next page, previous page, page 2, more results, table navigation, rows per page, load more
---
vSuite tables use PrimeNG pagination — NOT browser page scroll.

CRITICAL: NEVER use "scroll" action to find more items in a table.
Tables show a fixed number of rows (10, 25, 50, or 100 per page).
More rows are on OTHER PAGES accessed via pagination controls.

PAGINATION CONTROLS (at the bottom of the table):
- Page numbers: "1  2  3  4  5" — click a number to go to that page
- Next page: ">" button — click to go to next page
- Previous page: "<" button — click to go to previous page
- First page: "<<" button — click to go to first page
- Last page: ">>" button — click to go to last page
- Rows per page: dropdown showing "10" with options [10, 25, 50, 100]

HOW TO NAVIGATE PAGES:
1. To go to next page:
   {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Next Page"}
   Or: {"action": "click", "strategy": "get_by_text", "name": ">"}
2. To go to a specific page number:
   {"action": "click", "strategy": "get_by_text", "name": "3"}
3. To change rows per page (show more at once):
   Click the rows-per-page dropdown and select a higher number.

FINDING ITEMS:
1. Check visible rows on current page.
2. If not found, click next page button.
3. Repeat until item found or last page reached.
4. NEVER scroll — ALWAYS paginate.


---

## WORKFLOW: Table Views — Standard vs. Compact View
KEYWORDS: compact view, standard view, change view, table density, navigate to compact view
FORBIDDEN_KEYWORDS: list view, list layout, wide view
SECTION: Navigation & Layout
---
vSuite tables offer different viewing densities. "Standard" view shows more padding and multiline data, while "Compact" view compresses the rows.

To switch views, click the **Settings gear icon** (`button#settings-btn`) in the action bar above the table — this opens a `p-menu` popup with the available views.

══════════════════════════════════════════
STEP 1: Open the Settings menu
══════════════════════════════════════════
  {"action": "click", "strategy": "css_selector", "name": "button#settings-btn"}

The popup (`p-menu`) will appear with the following menu items:
  - id="listview"           → List (standard modern view)
  - id="compact_listview"   → Compact
  - id="minimal_listview"   → Minimal List
  - id="calendar"           → Calendar

⚠ ONLY click the Settings button ONCE per attempt. If you have already clicked it and the popup did not respond, click the menu item directly (see Step 2).

══════════════════════════════════════════
STEP 2: Click the desired view menu item
══════════════════════════════════════════
⚠ USE THE RECIPE — do not manually execute these steps:
  recipe: compact_view_navigate   params: view_label="Compact", view_css_class="compact"

If recipe is unavailable, use get_by_text (robust — works regardless of DOM structure):
To switch to Compact View:
  PRIMARY:  {"action": "click", "strategy": "get_by_text", "name": "Compact"}
  DEPRECATED: {"action": "click", "strategy": "css_selector", "name": "li#compact_listview a"}
  (li#compact_listview may not exist if p-menu renders differently)

To switch to Standard/List View:
  PRIMARY:  {"action": "click", "strategy": "get_by_text", "name": "List"}
  DEPRECATED: {"action": "click", "strategy": "css_selector", "name": "li#listview a"}

══════════════════════════════════════════
VERIFICATION — PERSISTENT DOM INDICATOR
══════════════════════════════════════════
Angular applies the active view name (lowercase) as a CSS class on div.po-table-wrapper.
Source: productionorders.html → <div class="po-table-wrapper {{ selectedTableView | lowercase }}">

✓ CORRECT selectors (persistent, exist after menu closes):
  Compact active:  selector_hint: "div.po-table-wrapper.compact"
  List active:     selector_hint: "div.po-table-wrapper.modern"
  Minimal active:  selector_hint: "div.po-table-wrapper.minimal"

✗ WRONG (ephemeral — menu closes and removes these from DOM):
  li#compact_listview.active, li#listview.active, li#minimal_listview.active

No toast notification appears on view change.

ANTI-PATTERNS:
  ✗ Do NOT click Settings more than once without clicking a menu item in between.
  ✗ Do NOT look for a "Compact View" toggle switch — there is none; use the p-menu.
  ✗ Do NOT verify with li#compact_listview.active — the li disappears when the menu closes.

---

## WORKFLOW: Column Chooser — Finding and Displaying Hidden Columns
KEYWORDS: missing column, hidden column, add column, show column, column chooser, customize columns, start date missing
SECTION: Navigation & Layout
---
If an Acceptance Criteria requires interacting with a column header (like 'Start Date' or 'End Date') but it is NOT visible in the accessibility tree or screenshot, do NOT attempt pagination. The column is hidden — you must use the Settings menu to reveal it.

NOTE: In the vSuite Production Orders list view, "Start / End" is a COMBINED dropdown column (not two separate columns). Both Start Date and End Date sorting is accessed via a single `p-select` dropdown in the "Start / End" column header (`p-select#header-sort-drop-down-startendCol`).

══════════════════════════════════════════
STEP 1: Check if the column is a known dropdown column
══════════════════════════════════════════
Before trying to enable a hidden column, verify whether the column is a known dropdown column:
  - "Due / Days" column → controlled by p-select#header-sort-drop-down-duedaysCol
  - "Start / End" column → controlled by p-select#header-sort-drop-down-startendCol

If the AC step mentions "Start Date" or "End Date", use the "Start / End" dropdown column — it is ALREADY VISIBLE. Do not look for a separate "Start Date" column header.

══════════════════════════════════════════
STEP 2: If a column is genuinely missing
══════════════════════════════════════════
Open the Settings menu (button#settings-btn) and check the Folder Options > Settings submenu.
Strategy: {"action": "click", "strategy": "css_selector", "name": "li#qfsettings a"}

ANTI-PATTERNS:
  ✗ Do NOT paginate to "find" a missing column — it will never appear on another page.
  ✗ Do NOT use get_by_title("Columns") — this attribute does not exist in vSuite.
  ✗ Do NOT try get_by_role("columnheader", name="Start Date") — this column does not exist separately.

---

## WORKFLOW: Production — Assigning Voice Talent / Dubbers
KEYWORDS: dubber, assign talent, assign voice, voiceover, voicer, add voice, talent request
SECTION: Production & Fulfillment
---
When a spot needs a voiceover, a producer must assign a "Dubber" or "Voice Talent" to the order.

══════════════════════════════════════════
STEP 1: Open the Voice Assignment panel
══════════════════════════════════════════
Inside the Production Order row (in the Files column), click the "Add Voice" or microphone icon.
Strategy: {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Add Voice"}
  OR:      {"action": "click", "strategy": "get_by_text", "name": "Add Voice"}

Wait 500ms for the side panel or modal to open.

══════════════════════════════════════════
STEP 2: Select the Talent
══════════════════════════════════════════
In the panel, click the talent dropdown/combobox to open the list:
  1. {"action": "click", "strategy": "get_by_role", "role": "combobox", "name": "Select Voice"}
  2. {"action": "wait", "value": 300}
  3. {"action": "click", "strategy": "get_by_role", "role": "option", "name": "Demo Voice Talent"}

If the talent selector is a searchbox, type a partial name first:
  1. {"action": "fill", "strategy": "get_by_role", "role": "searchbox", "name": "Voice"}, value: "Demo"
  2. {"action": "click", "strategy": "get_by_role", "role": "option", "name": "Demo Voice Talent"}

track_actor: {"role": "voicer", "name": "Demo Voice Talent"}

══════════════════════════════════════════
STEP 3: Set Due Date (if required) & Submit
══════════════════════════════════════════
Set voice due date via p-datepicker if the field is present (see p-datepicker KB entry).
Click Submit:
  {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Assign Voice"}
  OR: {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Submit"}

══════════════════════════════════════════
VERIFICATION
══════════════════════════════════════════
Wait for a toast notification confirming assignment.
The assigned talent's name should now appear in the "Voices" or "Talent" section of the order row.

---

## WORKFLOW: Batch Actions / Bulk Approvals
KEYWORDS: select multiple, batch action, bulk approve, action bar, select all, multiple orders
SECTION: Request Entry & Management
---
vSuite allows users to select multiple rows in the PrimeNG table and apply a single action (like Approve or Fulfill) to all of them at once via a sticky Action Bar that appears when rows are selected.

══════════════════════════════════════════
STEP 1: Select Rows
══════════════════════════════════════════
Click the PrimeNG table checkbox in the leftmost column of each target row.
  {"action": "click", "strategy": "get_by_role", "role": "checkbox", "name": "Select Row"}

⚠ If multiple checkboxes share the same ARIA label, use vqa_id from the element tree:
  {"action": "click", "strategy": "css_selector", "name": "[data-vqa-id='N']"}

To select ALL rows on the current page, click the header checkbox:
  {"action": "click", "strategy": "css_selector", "name": "p-tablecheckbox"}

══════════════════════════════════════════
STEP 2: Use the Sticky Action Bar
══════════════════════════════════════════
Once at least one row is checked, a sticky Action Bar appears at the top of the selection floater (NOT inside the table row).
Do NOT look for action buttons inside the table row itself.

  {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Approve Selected"}
  OR: {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Batch Complete"}
  OR: {"action": "click", "strategy": "get_by_text", "name": "Bulk Actions"}

══════════════════════════════════════════
VERIFICATION
══════════════════════════════════════════
Wait for a toast notification indicating X orders were updated.
The selected rows will reflect their new status after Angular re-renders.


---

## WORKFLOW: AUTO-LEARNED — Click STATUS & APPROVALS column header to sort ascending (A-Z)
KEYWORDS: click, status, approvals, column, header, sort, ascending
SECTION: Auto-Learned (recorded 2026-04-14, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked this th p-datatable-resizable-column p-datatable-reorderable-column po-col-statusCol table-th p-datatable-sortable-column ng-star-inserted p-datatable-column-sorted then made sure the value of this po-col-status ng-star-inserted p-highlight-contextmenu column was ssorted properly.

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked this th p-datatable-resizable-column p-datatable-reorderable-column po-col-statusCol table-th p-datatable-sortable-column ng-star-inserted p-datatable-column-sorted then made sure the value of this po-col-status ng-star-inserted p-highlight-contextmenu column was ssorted properly.

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click STATUS & APPROVALS column header again to sort descending (Z-A)
KEYWORDS: click, status, approvals, column, header, again, sort, descending
SECTION: Auto-Learned (recorded 2026-04-14, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Navigate to compact view
KEYWORDS: navigate, compact, view
SECTION: Auto-Learned (recorded 2026-04-14, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click TITLE column header to sort ascending (A-Z) in compact view
KEYWORDS: click, title, column, header, sort, ascending, compact, view
SECTION: Auto-Learned (recorded 2026-04-14, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Selected the "Title" option from the "sort by" dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: Selected the "Title" option from the "sort by" dropdown

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click SUBMITTED ON column header to sort descending (most recent first) in compact view
KEYWORDS: click, submitted, column, header, sort, descending, most, recent
SECTION: Auto-Learned (recorded 2026-04-14, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click SUBMITTED ON column header again to sort ascending (oldest first) in compact view
KEYWORDS: click, submitted, column, header, again, sort, ascending, oldest
SECTION: Auto-Learned (recorded 2026-04-14, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: Sorting in Compact View (Sort Popover Menu)
KEYWORDS: compact view, sort, sort menu, sort popover, column, client, due date, days
SECTION: Table Sorting — Compact View
---
In Compact View, there is NO visible column header row. Clicking column headers will fail.
Instead, the user must open the sort popover via a dedicated sort button, then click the
column name INSIDE the popover panel.

⚠ CRITICAL GOTCHA: The word "Client" (and other column names like "Due Date", "Days", "Status")
appears MANY TIMES on the page inside the compact data cards.
Using get_by_text("Client") WITHOUT a container will trigger a STRICT_MODE_VIOLATION (11+ matches).
You MUST pass container_selector to restrict the click to the sort popover.

══════════════════════════════════════════
STEP 1: Open the sort popover
══════════════════════════════════════════
Click the sort button to open the sort options panel.

  Action JSON:
    {"action": "click", "strategy": "css_selector", "name": "button#sort-btn",
     "reasoning": "Open sort options popover in Compact View"}

  Wait 300ms for the popover to animate open.

══════════════════════════════════════════
STEP 2: Click the desired column INSIDE the sort popover
══════════════════════════════════════════
Use container_selector to scope the locator to the popover ONLY.
This prevents STRICT_MODE_VIOLATION from the same text appearing in table rows.

  Action JSON (example — Client ascending):
    {"action": "click", "strategy": "get_by_text", "name": "Client",
     "container_selector": ".sort-panel",
     "reasoning": "Click Client inside sort popover — container scoped to avoid strict mode"}

  Action JSON (example — Due Date descending):
    {"action": "click", "strategy": "get_by_text", "name": "Due Date",
     "container_selector": ".sort-panel",
     "reasoning": "Click Due Date inside sort popover, scoped to .sort-panel"}

  Other valid column names inside the sort panel:
    "Client", "Due Date", "Days", "Submitted On", "Start Date", "End Date",
    "Status & Approvals", "Last Action"

══════════════════════════════════════════
STEP 3: Verify sort applied
══════════════════════════════════════════
After clicking, wait 500ms for Angular re-render, then use verify_table_sort to confirm.

  Action JSON:
    {"action": "verify_table_sort", "column": "Client", "order": "ascending",
     "reasoning": "Programmatic verification of sort result — do NOT attempt visual comparison"}

══════════════════════════════════════════
FORBIDDEN PATTERNS in Compact View sorting:
══════════════════════════════════════════
✗ FORBIDDEN: get_by_text("Client") WITHOUT container_selector — causes STRICT_MODE_VIOLATION
✗ FORBIDDEN: clicking th.po-col-clientCol in Compact View — column headers are hidden
✗ FORBIDDEN: get_by_role("columnheader", name="Client") in Compact View — no header row rendered
✗ FORBIDDEN: .first on any sort-related locator — selects wrong element silently


---

## WORKFLOW: AUTO-LEARNED — Click CLIENT column header to sort ascending (A-Z)
KEYWORDS: click, client, column, header, sort, ascending
SECTION: Auto-Learned (recorded 2026-04-14, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  The user had the compact view selected so i had to click the cog above the table and then select listview. AFter the litview loaded I clicked the Client header

NOTE: No browser actions were captured by the JS listener.
Human explanation: The user had the compact view selected so i had to click the cog above the table and then select listview. AFter the litview loaded I clicked the Client header

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: Compound Column Sorting — Due/Days and Run (Start/End) Dropdowns
KEYWORDS: compound, combobox, p-select, due date, days, dropdown, panel, overlay
SECTION: Table Sorting — Compound Columns
---
SOURCE VERIFIED from productionorders.component.ts (lines 629-691) and productionorders.html (lines 210-231).

There are TWO compound column dropdowns in the Production Orders list view:
  1. "Due / Days" (id=duedaysCol) — options: Due (date), Days (elapsed), Submitted On
  2. "Start / End" also labeled "Run" (id=startendCol) — options: Start (date), End (date)

Interacting with these requires TWO actions. A single combobox click ONLY OPENS the dropdown.
You MUST THEN click the field-name option inside the panel to apply the sort.

⚠ CRITICAL — OPTION LABELS ARE FIELD NAMES, NOT 'Ascending'/'Descending':
"Ascending" and "Descending" DO NOT EXIST as option labels in this dropdown.
You click the field name ("Due", "Days", "Submitted On", "Start", "End").
Each click toggles the sort direction for that field.
Only ONE direction option per field is visible at a time (conditional rendering).

══════════════════════════════════════════
STEP 1: Open the correct dropdown
══════════════════════════════════════════
For Due / Days column (also controls Submitted On sorting):
  {"action": "click", "strategy": "get_by_role", "role": "combobox", "name": "Due / Days",
   "reasoning": "Open Due/Days compound column p-select — contains Due, Days, Submitted On options"}

For Start / End / Run column:
  {"action": "click", "strategy": "get_by_role", "role": "combobox", "name": "Start / End",
   "reasoning": "Open Start/End (Run) compound column p-select — contains Start and End options"}

Wait 300ms for the po-sorting-dropdown-panel to attach to document.body.

══════════════════════════════════════════
STEP 2: Click the FIELD NAME inside the panel
══════════════════════════════════════════
The overlay panel class is: po-sorting-dropdown-panel (appended to document.body).
Use container_selector: ".po-sorting-dropdown-panel" on ALL clicks inside this overlay.

  Sort by DUE DATE (ascending or descending — clicks toggle direction):
  {"action": "click", "strategy": "get_by_text", "name": "Due",
   "container_selector": ".po-sorting-dropdown-panel",
   "reasoning": "Click Due inside po-sorting-dropdown-panel to apply Due Date sort"}

  Sort by DAYS:
  {"action": "click", "strategy": "get_by_text", "name": "Days",
   "container_selector": ".po-sorting-dropdown-panel",
   "reasoning": "Click Days inside po-sorting-dropdown-panel to sort by elapsed days"}

  Sort by SUBMITTED ON:
  {"action": "click", "strategy": "get_by_text", "name": "Submitted On",
   "container_selector": ".po-sorting-dropdown-panel",
   "reasoning": "Click Submitted On inside po-sorting-dropdown-panel — MUST use container to avoid 11 row matches"}

  Sort by START DATE:
  {"action": "click", "strategy": "get_by_text", "name": "Start",
   "container_selector": ".po-sorting-dropdown-panel",
   "reasoning": "Click Start inside po-sorting-dropdown-panel to sort by Start Date"}

  Sort by END DATE:
  {"action": "click", "strategy": "get_by_text", "name": "End",
   "container_selector": ".po-sorting-dropdown-panel",
   "reasoning": "Click End inside po-sorting-dropdown-panel to sort by End Date"}

After clicking, the panel closes automatically and Angular re-renders the table.
Wait 500ms before verifying.
To toggle direction (ascending→descending): repeat Step 1 + Step 2 with the same field name.

══════════════════════════════════════════
FULL EXAMPLE — Sort by Start Date ascending then descending:
══════════════════════════════════════════
  Action 1: click get_by_role(combobox, name='Start / End')                     ← opens panel
  Action 2: click get_by_text('Start', container='.po-sorting-dropdown-panel')  ← ascending applied
  Action 3: wait 500ms
  Action 4: click get_by_role(combobox, name='Start / End')                     ← opens panel again
  Action 5: click get_by_text('Start', container='.po-sorting-dropdown-panel')  ← descending applied
  Action 6: wait 500ms

══════════════════════════════════════════
FORBIDDEN PATTERNS for compound columns:
══════════════════════════════════════════
✗ FORBIDDEN: clicking the combobox a SECOND TIME instead of selecting from the panel — closes panel without sorting
✗ FORBIDDEN: get_by_text('Ascending') or get_by_text('Descending') — these labels DO NOT EXIST in this dropdown
✗ FORBIDDEN: css_selector('p-select#header-sort-drop-down-duedaysCol') — ID on inner <input>, times out
✗ FORBIDDEN: get_by_role('combobox', name='Run') — combobox aria-label is 'Start / End', not 'Run'
✗ FORBIDDEN: any click inside the panel WITHOUT container_selector — will match text in table rows

---

## WORKFLOW: Sorting by "Submitted On" in List View (Compound Column — duedaysCol)
KEYWORDS: submitted on, submitted, column, header, sort, ascending, descending, combobox
SECTION: Table Sorting — Compound Columns
JIRA: QA-321
---
SOURCE VERIFIED: productionorders.component.ts lines 650-656 — 'Submitted On' is reorderOption
index 4/5 inside the duedaysCol p-select with values 'submitted_on;1' and 'submitted_on;-1'.

⚠ CRITICAL: "Submitted On" is the THIRD FIELD inside the "Due / Days" compound column.
There is NO standalone "Submitted On" column header with its own combobox in List View.
The text "Submitted On" appears in the DATA ROWS (11+ times) — NEVER use it without a container.

══════════════════════════════════════════
STEP 1: Open the Due/Days compound column dropdown
══════════════════════════════════════════
  {"action": "click", "strategy": "get_by_role", "role": "combobox", "name": "Due / Days",
   "reasoning": "Open Due/Days compound p-select — contains Due, Days, AND Submitted On sort options"}

Wait 300ms for the po-sorting-dropdown-panel to attach to document.body.

══════════════════════════════════════════
STEP 2: Click "Submitted On" INSIDE the panel (MUST use container)
══════════════════════════════════════════
  {"action": "click", "strategy": "get_by_text", "name": "Submitted On",
   "container_selector": ".po-sorting-dropdown-panel",
   "reasoning": "Click Submitted On inside .po-sorting-dropdown-panel — container REQUIRED to avoid 11 row matches"}

The panel closes automatically. Wait 500ms for Angular to re-render.
To toggle direction: repeat Step 1 + Step 2 (each click cycles ascending→descending).

══════════════════════════════════════════
FORBIDDEN PATTERNS for Submitted On sorting:
══════════════════════════════════════════
✗ FORBIDDEN: get_by_text('Submitted On') WITHOUT container_selector → STRICT_MODE_VIOLATION (11 matches)
✗ FORBIDDEN: get_by_text('Submitted on') (lowercase o) → also matches row elements
✗ FORBIDDEN: get_by_role('columnheader', name='Submitted On') → no standalone Submitted On column
✗ FORBIDDEN: css_selector('p-select#header-sort-drop-down-duedaysCol') → times out
✗ FORBIDDEN: get_by_role(combobox, name='Submitted On') → no such combobox; name is 'Due / Days'
✗ FORBIDDEN: container_selector: 'p-select-overlay' → WRONG class; correct class is '.po-sorting-dropdown-panel'

---

## WORKFLOW: Compact View Navigation — Correct Verification Selector
KEYWORDS: compact view, navigate, switch view, element_visible, selector_hint, po-table-wrapper
SECTION: Navigation & Layout
---
When switching FROM List View TO Compact View via the settings menu, the verifier checks
that the navigation succeeded. Use the CORRECT persistent DOM verification selector.

⚠ CRITICAL — WRONG SELECTORS (cause infinite NOT_YET loop — DO NOT USE):
  ✗ WRONG: selector_hint: "li#compact_listview.active"
  ✗ WRONG: selector_hint: "li#listview.active"
  ✗ WRONG: selector_hint: "li#standard_listview.active"
  WHY: The p-menu closes immediately when you click a menu item. ALL li elements are
       REMOVED from the DOM as soon as the popup closes. element_visible on a detached
       li element WILL ALWAYS return NOT_YET, causing the planner to loop forever.

✓ CORRECT verification selectors (source: productionorders.html line 148):
  Angular applies (selectedTableView | lowercase) as a CSS class on div.po-table-wrapper.
  This element PERSISTS after the menu closes — it is the correct, durable indicator.

  Navigate to Compact View:  selector_hint: "div.po-table-wrapper.compact"
  Navigate to List View:     selector_hint: "div.po-table-wrapper.modern"
  Navigate to Minimal View:  selector_hint: "div.po-table-wrapper.minimal"

══════════════════════════════════════════
HOW TO SWITCH TO COMPACT VIEW (use the recipe):
══════════════════════════════════════════
Use recipe: compact_view_navigate with params:
  view_label: "Compact"
  view_css_class: "compact"

The recipe runs these steps and verifies automatically:
  STEP 1: Click button#settings-btn  (VIEW SWITCHER — NOT the sort button)
  STEP 2: Click "Compact" from the p-menu popup
  STEP 3: Verify div.po-table-wrapper.compact is present (persistent class indicator)

NOTE: button#settings-btn is the VIEW SWITCHER. Do NOT use it for sorting.
See "Sorting in Compact View" workflow for how to sort in Compact View.


---

## WORKFLOW: AUTO-LEARNED — Click Due Date column header to open sort dropdown
KEYWORDS: click, date, column, header, open, sort, dropdown
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Due Date column header again to open sort dropdown
KEYWORDS: click, date, column, header, again, open, sort, dropdown
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Clicked the Due/Days column header which then opens a dropdown then i clicked the "Due" option.

NOTE: No browser actions were captured by the JS listener.
Human explanation: Clicked the Due/Days column header which then opens a dropdown then i clicked the "Due" option.

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Days column header to open sort dropdown
KEYWORDS: click, days, column, header, open, sort, dropdown
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Select the due option from the dropdown that was already opened in the Due/Days column header

NOTE: No browser actions were captured by the JS listener.
Human explanation: Select the due option from the dropdown that was already opened in the Due/Days column header

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Navigate to Compact View
KEYWORDS: navigate, compact, view
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Title column header to sort ascending (A-Z) in Compact View
KEYWORDS: click, title, column, header, sort, ascending, compact, view
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Had to click the "Sort By" drdopdown above the table header and then selected the Title option

NOTE: No browser actions were captured by the JS listener.
Human explanation: Had to click the "Sort By" drdopdown above the table header and then selected the Title option

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Status & Approvals column header to sort ascending (A-Z) in Compact View
KEYWORDS: click, status, approvals, column, header, sort, ascending, compact
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Status & Approvals column header again to sort descending (Z-A) in Compact View
KEYWORDS: click, status, approvals, column, header, again, sort, descending
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  The sort by dropdown was already opened i just had to click the status option again and ensure it had a down arrow icon next to it then wait for the listview to load and verify that the status was indeed sorted descending z-a

NOTE: No browser actions were captured by the JS listener.
Human explanation: The sort by dropdown was already opened i just had to click the status option again and ensure it had a down arrow icon next to it then wait for the listview to load and verify that the status was indeed sorted descending z-a

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Due Date column header to sort ascending (closest first) in Compact View
KEYWORDS: click, date, column, header, sort, ascending, closest, first
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Click the sort by dropdown and then select the Due Date option

NOTE: No browser actions were captured by the JS listener.
Human explanation: Click the sort by dropdown and then select the Due Date option

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Submitted On column header to sort descending (most recent first) in Compact View
KEYWORDS: click, submitted, column, header, sort, descending, most, recent
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Submitted On column header again to sort ascending (oldest first) in Compact View
KEYWORDS: click, submitted, column, header, again, sort, ascending, oldest
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click End Date column header again to sort descending (oldest first)
KEYWORDS: click, date, column, header, again, sort, descending, oldest
SECTION: Auto-Learned (recorded 2026-04-15, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Navigate to Compact view
KEYWORDS: navigate, compact, view
SECTION: Auto-Learned (recorded 2026-04-16, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Start Date column header to sort ascending
KEYWORDS: click, start, date, column, header, sort, ascending
SECTION: Auto-Learned (recorded 2026-04-16, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click CLIENT column header to sort ascending in Compact view
KEYWORDS: click, client, column, header, sort, ascending, compact, view
SECTION: Auto-Learned (recorded 2026-04-16, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Title column header to sort ascending in Compact view
KEYWORDS: click, title, column, header, sort, ascending, compact, view
SECTION: Auto-Learned (recorded 2026-04-16, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Status & Approvals column header to sort ascending in Compact view
KEYWORDS: click, status, approvals, column, header, sort, ascending, compact
SECTION: Auto-Learned (recorded 2026-04-16, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Submitted On column header again to sort ascending in Compact view
KEYWORDS: click, submitted, column, header, again, sort, ascending, compact
SECTION: Auto-Learned (recorded 2026-04-16, ticket QA-321)
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

NOTE: No browser actions were captured by the JS listener.
Human explanation: (none provided)

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Save search results as a folder named 'Beta Boys automation'
KEYWORDS: save, search, results, folder, beta, boys, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-185, recorded 2026-04-17
---
A human operator completed this step manually during a vQA run (QA-185).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Need to type "Beta Boys automation" into the Folder name input and then click Save

NOTE: No browser actions were captured by the JS listener.
Human explanation: Need to type "Beta Boys automation" into the Folder name input and then click Save

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Verify folder appears in left navigation
KEYWORDS: verify, folder, appears, left, navigation, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-185, recorded 2026-04-17
---
A human operator completed this step manually during a vQA run (QA-185).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Need to type "Beta Boys Automation" into the New Folder Name input then click save, then wait for the page to load before looking in the left navigation for the new folder.

NOTE: No browser actions were captured by the JS listener.
Human explanation: Need to type "Beta Boys Automation" into the New Folder Name input then click save, then wait for the page to load before looking in the left navigation for the new folder. 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Access folder settings via cog wheel icon
KEYWORDS: access, folder, settings, wheel, icon, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-185, recorded 2026-04-17
---
A human operator completed this step manually during a vQA run (QA-185).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Needed to click the cog icon above table in the right side. Then click settings under the folder options header

NOTE: No browser actions were captured by the JS listener.
Human explanation: Needed to click the cog icon above table in the right side. Then click settings under the folder options header

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Share custom folder with one or multiple staff members
KEYWORDS: share, custom, folder, multiple, staff, members, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-185, recorded 2026-04-17
---
A human operator completed this step manually during a vQA run (QA-185).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Click the share icon next to the Beta Boys Automation folder that was created, this opens a "Share Filter" dialog and then from there I selected Demo Prod Woman from the dropdown and then clicked Share.

NOTE: No browser actions were captured by the JS listener.
Human explanation: Click the share icon next to the Beta Boys Automation folder that was created, this opens a "Share Filter" dialog and then from there I selected Demo Prod Woman from the dropdown and then clicked Share. 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Locate spot row with 'Needs Producing' status
KEYWORDS: locate, spot, needs, producing, status, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-62, recorded 2026-04-20
---
A human operator completed this step manually during a vQA run (QA-62).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Scroll down until the value of the Status & Approvals columns shows "Needs Producing"

NOTE: No browser actions were captured by the JS listener.
Human explanation: Scroll down until the value of the Status & Approvals columns shows "Needs Producing"

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Submitted on column header to sort ascending (most recent to oldest)
KEYWORDS: click, submitted, column, header, sort, ascending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-20
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Click on the Submitted On header which reveals a dropdown, then select the Submitted On option from there.

NOTE: No browser actions were captured by the JS listener.
Human explanation: Click on the Submitted On header which reveals a dropdown, then select the Submitted On option from there. 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select Due Date from sort dropdown to sort descending (oldest to newest)
KEYWORDS: select, date, sort, dropdown, descending, oldest, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-20
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  click the Sort By dropdown above the table, then selected the Due DAte option

NOTE: No browser actions were captured by the JS listener.
Human explanation: click the Sort By dropdown above the table, then selected the Due DAte option

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — ?
KEYWORDS: , human-learned, auto-learned, human, operator
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-20
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  all steps complete

NOTE: No browser actions were captured by the JS listener.
Human explanation: all steps complete

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Days column header again to sort descending (most first)
KEYWORDS: click, days, column, header, sort, descending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the Due/Days column header which opened a dropdown then i selected due date from that dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the Due/Days column header which opened a dropdown then i selected due date from that dropdown

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Sort By dropdown and select Status & Approvals to sort ascending
KEYWORDS: click, sort, dropdown, select, status, approvals, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Had to click the Sort By dropdown and thne selected the Status Option

NOTE: No browser actions were captured by the JS listener.
Human explanation: Had to click the Sort By dropdown and thne selected the Status Option 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Start/End Date column header and select End to sort ascending
KEYWORDS: click, start, date, column, select, sort, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Clicked the sort icon in the STart/End column then clicked the End option

NOTE: No browser actions were captured by the JS listener.
Human explanation: Clicked the sort icon in the STart/End column then clicked the End option

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Start/End Date column header again and select End to sort descending
KEYWORDS: click, start, date, column, select, sort, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  selected the end option from the dropdown in the start/end column

NOTE: No browser actions were captured by the JS listener.
Human explanation: selected the end option from the dropdown in the start/end column


VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Switch to Compact View
KEYWORDS: switch, compact, view, human-learned, auto-learned, human, operator
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  you did this already successfully

NOTE: No browser actions were captured by the JS listener.
Human explanation: you did this already successfully 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Sort by dropdown in Compact View
KEYWORDS: click, sort, dropdown, compact, view, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  you did this already

NOTE: No browser actions were captured by the JS listener.
Human explanation: you did this already 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select Client Name from Sort dropdown to sort ascending
KEYWORDS: select, client, name, sort, dropdown, ascending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  selected client from the sort by dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: selected client from the sort by dropdown

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Sort by dropdown again in Compact View
KEYWORDS: click, sort, dropdown, compact, view, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the sort by dropdown and clicked client again

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the sort by dropdown and clicked client again

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select Client Name from Sort dropdown to sort descending
KEYWORDS: select, client, name, sort, dropdown, descending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the sort by dropdown and then the client option

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the sort by dropdown and then the client option

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select Title from Sort dropdown to sort ascending
KEYWORDS: select, title, sort, dropdown, ascending, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  opened the sort by dropdown and clicked title

NOTE: No browser actions were captured by the JS listener.
Human explanation: opened the sort by dropdown and clicked title

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select Title from Sort dropdown to sort descending
KEYWORDS: select, title, sort, dropdown, descending, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-21
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  opened the sort by dropdown and clicked title

NOTE: No browser actions were captured by the JS listener.
Human explanation: opened the sort by dropdown and clicked title

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click CLIENT column header again to sort descending (Z-A) in compact view
KEYWORDS: click, client, column, header, sort, compact, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  navigate to compact view by selecting cog settings icon in top right then selecting compact from the dropdown options. Then selected client from the sort by dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: navigate to compact view by selecting cog settings icon in top right then selecting compact from the dropdown options. Then selected client from the sort by dropdown

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Navigate to Production Orders list view
KEYWORDS: navigate, production, orders, list, view, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the settings cog icon that is above the table to the right and then selected "Listview" from the dropdown options

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the settings cog icon that is above the table to the right and then selected "Listview" from the dropdown options

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Due Date column header again to sort descending (oldest to newest)
KEYWORDS: click, date, column, header, sort, descending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

NOTE: No browser actions were captured by the JS listener.
Human explanation: When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Days column header to sort ascending (least to most)
KEYWORDS: click, days, column, header, sort, ascending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

NOTE: No browser actions were captured by the JS listener.
Human explanation: When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Days column header again to sort descending (most to least)
KEYWORDS: click, days, column, header, sort, descending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

NOTE: No browser actions were captured by the JS listener.
Human explanation: When you switch to the Compact View, you will no longer use the column headers to sort.

Instead, click the "Sort by" dropdown and select the corresponding option from that menu.

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click End Date column header to sort ascending (closest to oldest)
KEYWORDS: click, date, column, header, sort, ascending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Click the Start/End column header and then click the End option from the dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: Click the Start/End column header and then click the End option from the dropdown

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Navigate to Production Orders compact view
KEYWORDS: navigate, production, orders, compact, view, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked settings cog on right above table then the compact option

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked settings cog on right above table then the compact option

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click 'Add Voice' link in files column of Needs Producing spot
KEYWORDS: click, voice, link, files, column, spot, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-62, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-62).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  In the files column there is an "Add Voice" link, click that

NOTE: No browser actions were captured by the JS listener.
Human explanation: In the files column there is an "Add Voice" link, click that

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click Add Voice link in files column
KEYWORDS: click, voice, link, files, column, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-62, recorded 2026-04-22
---
A human operator completed this step manually during a vQA run (QA-62).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  scrolled to the spot with the needs producing status and then clicked the add voice link in the files column.

NOTE: No browser actions were captured by the JS listener.
Human explanation: scrolled to the spot with the needs producing status and then clicked the add voice link in the files column.

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: vSuite Dynamic Form Builder — Generic Field Interaction Guide
KEYWORDS: dropdown, datepicker, calendar, autocomplete, p-inputtext, p-select, p-datepicker, p-autocomplete
---
⚠️ **CRITICAL — All vSuite forms use a dynamic form builder**

Every form in vSuite (Quick Orders, Voice Requests, Spot Details, Client Settings, etc.)
renders through `<app-v-forms>` and `<app-v-fields>`. Fields are NOT static HTML — they
are generated dynamically from a JSON form definition. This means:
- Field IDs are auto-generated: `input-{formUUID}-{field.id}-text-field`
- You CANNOT rely on `formControlName` attributes — fields use `[formControl]` binding
- `get_by_label("FieldName")` resolves to the `<label>`, NOT the `<input>` — fill will fail

**GENERIC STRATEGY FOR ANY FORM FIELD:**

1. **Text inputs** (`field_type='text'`):
   - Rendered as `<input type="text" class="p-inputtext">`
   - The label and input are siblings inside a `<div class="form-group">`
   - BEST: Use the label text to find the form-group, then target the child input:
     `css_selector` → `.form-group:has(label:text("FieldLabel")) input.p-inputtext`
   - ALTERNATIVE: Use `vqa_id` from the INTERACTIVE ELEMENTS list
   - ALTERNATIVE: Use coordinate_action to click the input, then press_key to type
   - NEVER use `get_by_label("X")` for fill — it will match the `<label>` element

2. **Textareas** (`field_type='textarea'`):
   - Rendered as `<textarea class="p-textarea p-inputtext">`
   - Same parent structure: `<div class="form-group">`
   - Target: `.form-group:has(label:text("FieldLabel")) textarea`

3. **Dropdowns** (`field_type='pdropdown'`):
   - Rendered as `<p-select>` (PrimeNG v19) inside `<div class="form-group">`
   - Has dynamic id: `drop-down-selection-allow-multi-{formUUID}-{field.id}`
   - DO NOT use `p-select[formControlName='...']` — the attribute does not exist
   - BEST: Use the primeng_dropdown tool with a scoped trigger_selector:
     `trigger_selector` → `.form-group:has(label:text("FieldLabel")) p-select`
   - Options appear in `.p-select-overlay` portal appended to body

4. **Date pickers** (`field_type='datepicker'`):
   - Rendered as `<p-datepicker>` with an inner `<input>` 
   - DO NOT use fill on the `<p-datepicker>` component — it is not an input
   - Target the inner input: `.form-group:has(label:text("FieldLabel")) p-datepicker input`
   - Or click the calendar icon and select a date from the popup
   - Calendar popup uses `.p-datepicker-panel` portal appended to body

5. **Autocomplete / Typeahead** (`field_type='select2typeahead'`):
   - Rendered as `<p-autocomplete>` with an inner `<input>` for typing
   - Target the inner input: `.form-group:has(label:text("FieldLabel")) p-autocomplete input`
   - Type at least 1 character to trigger suggestions
   - Select from the `.typeahead-panel` dropdown that appears

6. **Checkboxes / Toggles**:
   - Checkboxes: `<p-checkbox>` — use the check/uncheck action
   - Toggles: `<p-toggleswitch>` — use click action

**FORM CONTAINERS:**
- Sidebar forms open inside `<app-v-sidebar>` — check visibility with `app-v-sidebar`
- Dialog forms open inside `<p-dialog>` — check visibility with `p-dialog`
- DO NOT guess CSS classes like `.voice-part-form` — they rarely exist
- Use the actual component selector: `app-v-sidebar`, `p-dialog`, `p-sidebar`

**WHEN fill() FAILS WITH "Element is not an <input>":**
The executor will automatically try to find a child `<input>` inside the matched element.
If that also fails, switch to one of these strategies:
- Use `css_selector` with `.form-group:has(label:text("X")) input` pattern
- Use coordinate_action to click into the field, then press_key to type
- Check the INTERACTIVE ELEMENTS list for the field's `vqa_id`



---

## WORKFLOW: AUTO-LEARNED — Navigate to compact view page
KEYWORDS: navigate, compact, view, page, human-learned, auto-learned, human, operator
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-23
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Click the settings cog and then the compact option in the dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: Click the settings cog and then the compact option in the dropdown

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: vSuite Demo User Credentials and Accounts
KEYWORDS: demo user, credentials, login as, user account, email, password, production director, voicer
---
All vProMedia demo accounts use this email format and shared password:

  Email format:  imail-test+{UserName}@vcreativeinc.com
  Password:      Ep!cVCteam2026$
  JWT key:       localStorage.getItem('vc2JWT')  ← presence confirms login success

DEMO USER LIST (12 accounts):
  DemoProdDirector     → imail-test+DemoProdDirector@vcreativeinc.com    (Production Director)
  DemoProdMan          → imail-test+DemoProdMan@vcreativeinc.com          (Production Manager)
  DemoProdWoman        → imail-test+DemoProdWoman@vcreativeinc.com        (Production Manager alt)
  DemoSalesExec        → imail-test+DemoSalesExec@vcreativeinc.com        (Sales Executive / AE)
  DemoVoicer           → imail-test+DemoVoicer@vcreativeinc.com           (Voice Talent)
  DemoDigitalDir       → imail-test+DemoDigitalDir@vcreativeinc.com       (Digital Director)
  DemoDigitalProd      → imail-test+DemoDigitalProd@vcreativeinc.com      (Digital Producer)
  DemoTrafficDirector  → imail-test+DemoTrafficDirector@vcreativeinc.com  (Traffic Director)
  DemoTrafficAssnt     → imail-test+DemoTrafficAssnt@vcreativeinc.com     (Traffic Assistant)
  DemoGM               → imail-test+DemoGM@vcreativeinc.com               (General Manager)
  DemoGraphicArtist    → imail-test+DemoGraphicArtist@vcreativeinc.com    (Graphic Artist)
  writer               → imail-test+writer@vcreativeinc.com               (Copywriter)

VERIFYING LOGIN SUCCESS:
1. After clicking Login, wait for URL to no longer contain /login:
   waitForURL(url => !url.includes('/login'), timeout 20000ms)
2. OR check localStorage: localStorage.getItem('vc2JWT') should be non-null
3. OR look for: .vcreative-icon in the sidebar (timeout 15000ms)

If the Jira AC step says "Log in as [role]" without specifying credentials, map the role
description to the matching demo user above and use their email with password M@gicVCteam2026!.


---

## WORKFLOW: vSuite Environment URLs and Angular Hash Routing
KEYWORDS: environment, url, navigate, hash routing, testing url, prod, smoke, qa
---
vSuite is an Angular SPA using hash-based routing (#/).

ENVIRONMENT URLs:
  prod:  https://vcreative.net
  test:  https://two-test.vcreative.net   ← primary test environment for vQA
  smoke: https://smoketest.vcreative.net
  qa:    https://qa.vcreative.net

COMMON ROUTE PATTERNS (always prefixed with /#/):
  Login:              /#/login
  Dashboard/Home:     /#/home  or  / (root redirects to home)
  Production Orders:  /#/production-orders  or  /#/production
  Quick Orders:       /#/quick-orders
  MyBox:              /#/mybox
  Approvals:          /#/approvals
  Settings - Clients: /#/settings/clients
  Settings - Roles:   /#/settings/firm_roles
  Settings - Legacy:  /#/settings/firm_abilities  → redirects to firm_roles
  Admin HDash:        /#/hdash/failed-logins  (admin-only)
  Order Detail:       /#/production-order/{POID}

IMPORTANT: Angular router does NOT reload the page on hash navigation.
After navigating to a new /#/ route, wait for networkidle or specific page element.

If the AC step asks to "navigate to the testing URL" and the app is already loaded,
check if you're already on that URL — if so, return {"action": "done"}.


---

## WORKFLOW: File Upload via URL (Attach External File Link)
KEYWORDS: upload file via url, attach url, url as file, link file, url file, file url, attach link
---
vSuite allows attaching a file by providing a direct URL instead of uploading a physical file.
This is used in Client profiles (Settings > Clients) and Quick Order forms.

STEP-BY-STEP:
1. Scroll to the Files section in the form.
2. Click the "URL as File" link/button:
   {"action": "click", "strategy": "css_selector", "name": "#urlFileLink"}
   — OR —
   {"action": "click", "strategy": "get_by_text", "name": "URL as File"}

3. A modal/inline form opens. Fill in the file name:
   {"action": "fill", "strategy": "css_selector", "name": "input[name='fileName']", "value": "My File Name"}

4. Fill in the file URL:
   {"action": "fill", "strategy": "css_selector", "name": "input[name='fileUrl']", "value": "https://..."}

5. Click the upload confirmation button:
   {"action": "click", "strategy": "get_by_text", "name": "Upload File Using URL File"}

6. A "Select a File Type" p-dropdown appears. Click it to open, then click the desired option:
   Step A: {"action": "click", "strategy": "css_selector", "name": "p-dropdown button"}
            (scope to the dropdown containing 'Select a File Type' text if multiple dropdowns exist)
   Step B: {"action": "click", "strategy": "get_by_role", "role": "option", "name": "Prod File"}
   (Other valid file types: 'Client Logo', 'Background Music', 'Traffic Information File')

7. Click Save:
   {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Save"}

VERIFICATION:
- After Save, look for: a#showFileTypeName (the attached file link, shows selected type as text)
- Use: {"action": "verify", "strategy": "css_selector", "name": "a#showFileTypeName"}
- The link's text should match the selected file type (e.g. "Prod File")


---

## WORKFLOW: Test Asset Files Available for Upload
KEYWORDS: upload file, attach file, test file, audio file, mp3, jpg, doc, pdf
---
The following test files are available in the Playwright test assets directory
(playwright/storage/test_files/) for use in file upload test steps:

AUDIO FILES:
  Final Spot 15.mp3         — 15-second final spot audio
  Final Spot 30.mp3         — 30-second final spot audio
  Final Spot 60 .mp3        — 60-second final spot audio (note trailing space in filename)
  Voice Part 1.mp3          — Voice talent recording part 1
  Voice Part 2.mp3          — Voice talent recording part 2
  Voice Part 3.mp3          — Voice talent recording part 3
  Background Music.mp3      — Background music track

IMAGE FILES:
  Client Logo.jpg           — Client logo image (standard JPG)
  500x1500.jpg              — Tall/narrow test image
  Final Image Ad.png        — Digital ad image (PNG)

DOCUMENT FILES:
  Copy points.doc           — Script/copy document (Word)
  Final Script.doc          — Final script document (Word)
  Traffic Information File.pdf — Traffic instruction PDF

LONG-NAME FILE (edge case):
  Production_Audio_File_that_was_given_a_really_long_file_name_for_some_reason_or_another_I_gave_up_even-asking-anymore-questions-with-this-team.wav

WHEN THE AC STEP SAYS "upload a file" without specifying which one:
- For a production audio upload → use Final Spot 30.mp3
- For a client logo/image upload → use Client Logo.jpg
- For a background music upload → use Background Music.mp3
- For a voice part upload → use Voice Part 1.mp3
- For a script/copy upload → use Copy points.doc or Final Script.doc
- For a traffic file upload → use Traffic Information File.pdf

⚠ The agent cannot physically upload files via the OS dialog — use the hidden
  p-fileupload input[type="file"] via setInputFiles, or attach via URL method above.

---

## WORKFLOW: AUTO-LEARNED — Click Submitted On column header again to sort descending (oldest to most recent) in compact view
KEYWORDS: click, submitted, column, header, sort, descending, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-321, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-321).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the submit date option from the sort by dropdown.

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the submit date option from the sort by dropdown.

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Refresh page to verify archive persists
KEYWORDS: refresh, page, verify, archive, persists, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the browser refresh tool

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the browser refresh tool

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click status dropdown for spot in List View
KEYWORDS: click, status, dropdown, spot, list, view, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  this user does not have access to the Archive status so this test should fail

NOTE: No browser actions were captured by the JS listener.
Human explanation: this user does not have access to the Archive status so this test should fail

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click status dropdown for first spot row
KEYWORDS: click, status, dropdown, spot, human, operator, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the dropdown in the STatus & Approvals column for one of the spots

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the dropdown in the STatus & Approvals column for one of the spots 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select Archived status from dropdown
KEYWORDS: select, archived, status, dropdown, human, operator, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Selected the "Archive" option from the dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: Selected the "Archive" option from the dropdown


VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click status dropdown for spot in Compact View
KEYWORDS: click, status, dropdown, spot, compact, view, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the Archied option

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the Archied option

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Navigate to Production Order page in List View
KEYWORDS: navigate, production, order, page, list, view, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  You already navigated there, you know because there are column headers and a table

NOTE: No browser actions were captured by the JS listener.
Human explanation: You already navigated there, you know because there are column headers and a table

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click status dropdown for spot in Status & Approvals column
KEYWORDS: click, status, dropdown, spot, approvals, column, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  This is already done, you know because the dropdown is open

NOTE: No browser actions were captured by the JS listener.
Human explanation: This is already done, you know because the dropdown is open 

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select Archived from status dropdown
KEYWORDS: select, archived, status, dropdown, human, operator, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  selected the Archived option from the dropdown

NOTE: No browser actions were captured by the JS listener.
Human explanation: selected the Archived option from the dropdown

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Verify spot row displays Archived status in List View
KEYWORDS: verify, spot, displays, archived, status, list, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  Right after clicking the archived option from the dropdown I verified that the value of the Status & Approval column was "Archived"

NOTE: No browser actions were captured by the JS listener.
Human explanation: Right after clicking the archived option from the dropdown I verified that the value of the Status & Approval column was "Archived"

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Refresh page to verify archive persists in Compact View
KEYWORDS: refresh, page, verify, archive, persists, compact, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  refreshed the page

NOTE: No browser actions were captured by the JS listener.
Human explanation: refreshed the page

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Select first PRF Category checkbox
KEYWORDS: select, first, category, checkbox, human-learned, auto-learned, human, operator
SOURCE: Human Takeover — ticket QA-215, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-215).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  PRF Category is not a checkbox it is an option after clicking "Category" it is a multi select

NOTE: No browser actions were captured by the JS listener.
Human explanation: PRF Category is not a checkbox it is an option after clicking "Category" it is a multi select

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Locate spot row in List View table
KEYWORDS: locate, spot, list, view, table, human, human-learned, auto-learned
SOURCE: Human Takeover — ticket QA-254, recorded 2026-04-24
---
A human operator completed this step manually during a vQA run (QA-254).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

HUMAN EXPLANATION:
  clicked the all option in the left nav

NOTE: No browser actions were captured by the JS listener.
Human explanation: clicked the all option in the left nav

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Click the search panel open button
KEYWORDS: click, search, panel, open, button, human-learned, auto-learned, human, operator
SOURCE: Human Takeover — ticket QA-185, recorded 2026-06-01
---
A human operator completed this step manually during a vQA run (QA-185).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

══════════════════════════════════════════
CAPTURED ACTION SEQUENCE
══════════════════════════════════════════
  Step 1: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,333.5"}
  Step 2: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,99"}
  Step 3: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,0"}

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.

---

## WORKFLOW: AUTO-LEARNED — Login as Demo Prod Director
KEYWORDS: login, demo, prod, director, human-learned, auto-learned, human, operator
SOURCE: Human Takeover — ticket QA-185, recorded 2026-06-01
---
A human operator completed this step manually during a vQA run (QA-185).
The action sequence below was captured automatically and should be used
verbatim on future runs that encounter this exact AC step.

══════════════════════════════════════════
CAPTURED ACTION SEQUENCE
══════════════════════════════════════════
  Step 1: {"action": "scroll", "strategy": "window", "name": "window", "value": "0,400"}

VERIFICATION:
  Wait 500ms after the last step for Angular to re-render.
