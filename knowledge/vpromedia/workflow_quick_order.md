## WORKFLOW: Create and Submit a Quick Order — All Ad Types
KEYWORDS: quick order, QO, new request, radio commercial, streaming, commercial, image ad, banner, create order, submit order, open form, ad type
---
Source: vsuitePlatform/playwright/tests/qo_form_basic.test.ts (VERIFIED WORKING)

⚠️ CRITICAL VERIFIER RULE — READ BEFORE GENERATING TEST STEPS:
The Quick Order form is a SIDE PANEL, not a new page. Clicking 'New Request' does NOT
change the URL. The URL stays on the current route (e.g. /#/vpr/production-orders).

  DO NOT use url_check for "Navigate to the Quick Order form page" steps.
  DO NOT use url_check for any step that opens the QO form.
  USE element_visible with selector_hint='h2:has-text("Create Order")' or '#qo-form-panel'

AC parser NAVIGATE step for QO should be compiled as:
  verification: [{"type": "element_visible", "selector_hint": "h2:has-text(\"Create Order\")", "expected_text": "Create Order"}]

QUICK ORDER FORM — COMPLETE WORKFLOW
Tested roles: DemoSalesExec, DemoProdDirector, DemoAccountExecutive

Prerequisites:
- User must be logged in with 'Enter Requests: YES' permission
- Left sidebar must be visible (confirms JWT and authenticated state)

══════════════════════════════════════════
STEP 1: Open the Quick Order Form
══════════════════════════════════════════
Click the 'New Request +' link in the left sidebar.

VERIFIED SELECTORS (from qo_form_basic.test.ts line 39):
  get_by_role("link", name="New Request")
  get_by_text("New Request")

After click: wait for "Create Order" and "Select an Adtype" text to appear.
The QO form panel opens on the right side of the page.
URL does NOT change. Verify success by checking element_visible on 'Create Order' heading.

══════════════════════════════════════════
STEP 2: Select Ad Type (CRITICAL — NOT a combobox!)
══════════════════════════════════════════
⚠️ The Ad Type selector is NOT a standard combobox/dropdown.
It is a custom PrimeNG component with a two-step interaction:

STEP 2a: Click the ad-type dropdown BUTTON (it may appear as an empty button icon):
  VERIFIED: page.locator('#qo-form-panel').getByRole('button', { name: '' }).click()
  
  FALLBACK: If the above doesn't work, look for a dropdown/chevron icon
  inside the form panel near "Select an Adtype" text and click it.

STEP 2b: Click the specific ad type option using its LABEL:
  VERIFIED (from qo_form_basic.test.ts line 43):
    get_by_label("Radio Commercial") → then click get_by_text("Radio Commercial")
  
  Available ad types:
  - "Radio Commercial" → status options: "Needs Writing", "Needs Producing"
  - "Commercial+Streaming" → also requires Digital URL field
  - "Streaming Only" → also requires Digital URL field
  - "Image Ad (Banner)" → status: "Needs Producing"

After selecting ad type: verify "Radio Commercial" appears in the spot cards area.
Wait 300ms for form fields to update.

KNOWN BAD SELECTORS (DO NOT USE):
  ❌ get_by_role("combobox", name="Ad Type") — DOES NOT EXIST
  ❌ get_by_label("Ad Type") — WILL TIMEOUT
  ❌ get_by_role("button", name="Ad Type") — NO SUCH BUTTON

══════════════════════════════════════════
STEP 3: Fill Client / Advertiser
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 47-49):
  Click: get_by_role("searchbox", name="Client ")
  Fill: Type partial client name (e.g. "Bob")
  WAIT 500ms for autocomplete dropdown to appear (API debounce).
  Click option: get_by_role("option", name="Bob's Burgers")

══════════════════════════════════════════
STEP 4: Fill Spot Title
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 62-63):
  get_by_role("textbox", name="Spot title")
  Fill with a unique title.

══════════════════════════════════════════
STEP 5: Set Status
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 66-67):
  Click: get_by_text("Select Status")
  Then click: get_by_text("Needs Writing") or get_by_text("Needs Producing")

NOTE: This is NOT a combobox. Click "Select Status" text first, then click the option.

══════════════════════════════════════════
STEP 6: Fill ISCI Code
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 70-71):
  get_by_placeholder("AD-ID OR ISCI CODE")
  Fill with code like "ABCD-1234"

══════════════════════════════════════════
STEP 7: Set Length
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 74-75):
  get_by_role("textbox", name="Length ")
  Fill with "30" or "60"

══════════════════════════════════════════
STEP 8: Set Rotation
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 78-79):
  get_by_role("textbox", name="Rotation ")
  Fill with "100"

══════════════════════════════════════════
STEP 9: Fill Dates
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 82-87):
  Due Date:   get_by_role("textbox", name="Due Date ")
  Start Date: get_by_role("textbox", name="Start Date ")
  End Date:   get_by_role("textbox", name="End Date ")
  Fill in MM-DD-YYYY format. Can type directly into the field.

══════════════════════════════════════════
STEP 10: Fill Creative Notes (optional)
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 113-114):
  get_by_role("textbox", name="Creative Notes")

══════════════════════════════════════════
STEP 11: Submit the Order
══════════════════════════════════════════
VERIFIED (from qo_form_basic.test.ts line 117):
  get_by_role("button", name="Submit All")

IMPORTANT: Button is DISABLED until ALL required fields are filled.

After clicking Submit All:
- URL changes to include a POID: /production-order/{number}
- A toast notification appears: "Order submitted successfully"

══════════════════════════════════════════
VERIFICATION
══════════════════════════════════════════
Success = URL contains /production-order/ AND POID is a non-zero integer.
Alternatively: toast text contains "submitted" or "success".
