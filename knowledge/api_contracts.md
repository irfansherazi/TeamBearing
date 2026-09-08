## WORKFLOW: vProMedia API Contracts — Action → Endpoint → Success Indicator
KEYWORDS: api, endpoint, request, response, post, patch, save, submit, create, update, delete, success, failure, silent, toast, error, network, api call, http
---
Source: vcapi controllers (auth.controller.ts, spots.controller.ts, prod-orders.controller.ts,
       spot-blogs.controller.ts, mmorders.controller.ts, client-spots.controller.ts)

CRITICAL RULE: When verifying that an action succeeded, the agent MUST know
which API endpoint was called and what the success indicator is. If a button
click triggers an API call that fails silently (no toast, no URL change), the
agent may incorrectly think the action worked when it didn't.

══════════════════════════════════════════════════════════════
1. AUTHENTICATION
══════════════════════════════════════════════════════════════

ACTION: Login
  ENDPOINT: POST /auth
  PAYLOAD: { email, password }
  SUCCESS INDICATORS:
    - Response: { ssoToken: "..." } — JWT returned
    - localStorage: vc2JWT is written ASYNCHRONOUSLY by Angular (poll up to 5s)
    - URL changes from /login to /dashboard or /
    - Left sidebar becomes visible with nav links
  FAILURE INDICATORS:
    - Toast: "Error: Invalid User" or "Invalid credentials"
    - Response: 401 Unauthorized
    - URL stays on /login
    - No sidebar visible

ACTION: Logout
  ENDPOINT: none (client-side only — localStorage cleared, redirect)
  SUCCESS INDICATORS:
    - URL changes to /login or /auth
    - Login form (Email + Password fields) visible
    - vc2JWT removed from localStorage
  FAILURE INDICATORS:
    - Still on dashboard page after clicking Logout
    - User avatar still visible in top-right

══════════════════════════════════════════════════════════════
2. SPOT (ORDER) CREATION — QUICK ORDER SUBMIT
══════════════════════════════════════════════════════════════

ACTION: Submit New Quick Order (Submit All button)
  ENDPOINT: POST /spots
  PAYLOAD: Spot object with all form fields (client_id, adtype_id, status, etc.)
  SUCCESS INDICATORS:
    - Response: { error: false, insertId: <POID> }
    - URL changes to include /production-order/{POID} (positive integer)
    - Toast: "Order submitted successfully" (appears within 2000ms)
    - Spot appears in Production Orders list view
  FAILURE INDICATORS:
    - Submit All button stays disabled (form validation not met)
    - Toast: error message (e.g., "Error creating spot")
    - No URL change
    - Response: 500 InternalServerError
  SILENT FAILURE RISK: LOW — submit always produces a toast or stays disabled

══════════════════════════════════════════════════════════════
3. SPOT UPDATE — INLINE EDIT / STATUS CHANGE
══════════════════════════════════════════════════════════════

ACTION: Update spot field (status, title, dates, etc.)
  ENDPOINT: PATCH /spots/:id
  PAYLOAD: { fieldName: newValue, metadata: {...} }
  SUCCESS INDICATORS:
    - Response: { error: false, affectedRows: 1, fieldsChangedOnSubmit: {...} }
    - If status changed: status badge updates in list view
    - If workflow triggered: additional fields may update (updatedFieldsByWf)
    - Realtime push: other connected users see the change
  FAILURE INDICATORS:
    - Response: 500 error
    - Field reverts to previous value on page refresh
    - No visual change after click
  SILENT FAILURE RISK: MEDIUM — status changes sometimes don't produce a toast.
    VERIFY by checking the status badge text after the PATCH completes.

ACTION: Inline edit from list view (click editable cell)
  ENDPOINT: PATCH /spots/:id (same as above)
  ADDITIONAL BEHAVIOR:
    - Cell locks to prevent other users from editing simultaneously
    - After save: cell unlocks and value updates
    - If another user has the cell locked: edit is blocked (no error toast)

══════════════════════════════════════════════════════════════
4. SPOT APPROVAL / DENIAL
══════════════════════════════════════════════════════════════

ACTION: Approve a spot (Script Review → approved, Spot Review → approved)
  ENDPOINT: PATCH /spots/approve/:id
  PAYLOAD: { table: "vppo.spots", data: {...}, payload: {...} }
  SUCCESS INDICATORS:
    - Status advances to next workflow step
    - Approval checkbox appears checked in Status/Tasks column
    - Workflow engine triggers status change (updatedFieldsByWf)
    - Notification sent to POC assignments
  FAILURE INDICATORS:
    - User doesn't have approval permission → 403 or no change
    - Spot is not in a Review status → no effect
  SILENT FAILURE RISK: MEDIUM — verify by checking status after approval

ACTION: Deny a spot
  ENDPOINT: PATCH /spots/deny/:id
  PAYLOAD: { table: "vppo.spots", data: {...}, payload: {...} }
  SUCCESS INDICATORS:
    - Status reverts to previous production step
    - Task notification sent to submitter
    - Blog post required (pre-denial condition)
  FAILURE INDICATORS:
    - Same as approval — check status after denial

⚠️ IMPORTANT:
  approve and deny use SEPARATE endpoints from the regular PATCH /spots/:id.
  Do NOT use the standard update endpoint for approval/denial actions.

══════════════════════════════════════════════════════════════
5. PRODUCTION ORDER MANAGEMENT
══════════════════════════════════════════════════════════════

ACTION: Create Production Order
  ENDPOINT: POST /prod-orders/:firmId
  SUCCESS INDICATORS:
    - Response: new PO object with ID
    - PO appears in Production Orders list
  FAILURE: 500 error response

ACTION: Get Production Order details
  ENDPOINT: GET /prod-orders/:id
  SUCCESS: JSON response with PO data + related spots

ACTION: Get spots by Production Order
  ENDPOINT: GET /spots/spotsByProdOrderId/:prodOrderId
  SUCCESS: Array of spot objects belonging to that PO

══════════════════════════════════════════════════════════════
6. REVISION PROCESS
══════════════════════════════════════════════════════════════

ACTION: Submit Revision for a spot
  ENDPOINT: POST /mmorders/processExtensionOrRevisionForSingleSpot
  PAYLOAD: { id, crstatus, payload, agencySpot, newDate }
  SUCCESS INDICATORS:
    - Status resets to production starting status (Needs Writing/Producing)
    - Revision count increments on the spot
    - Toast: "Revision submitted" or similar
    - POC assignments may reset (based on revisionresetspocflag)
  FAILURE INDICATORS:
    - No status change
    - Missing required blog post → revision rejected
  SILENT FAILURE RISK: LOW — toast always fires on successful revision

ACTION: Submit Extension for spots
  ENDPOINT: POST /mmorders/processExtensionForSpots
  PAYLOAD: { ids, crstatus, payload, agencySpot, newDate }
  SUCCESS INDICATORS:
    - End date updated on all selected spots
    - Status may change to "Extended"
    - Toast confirmation
  FAILURE: 500 error or no date change

══════════════════════════════════════════════════════════════
7. BLOG / COMMENTS
══════════════════════════════════════════════════════════════

ACTION: Get blogs for a Production Order
  ENDPOINT: GET /spot-blogs/getBlogsByPOID/:poId
  SUCCESS: Array of blog entries with timestamps and authors

ACTION: Post a blog (revision note, comment, rejection reason)
  BLOGS are embedded in the spot update payload — they are NOT a separate
  API call. The blog content is included in the PATCH /spots/:id payload
  or in the revision payload.
  SUCCESS: Blog appears in the order detail under Notes/Blog section
  FAILURE: Blog text empty → revision/rejection cannot complete

══════════════════════════════════════════════════════════════
8. SPOT HISTORY / AUDIT LOG
══════════════════════════════════════════════════════════════

ACTION: View spot change history
  ENDPOINT: GET /spot-history/getSpotHistoryByUserIdAndDate/:userId/:fromDate/:endDate
  SUCCESS: Array of historical change records

═══════════════════════════════════════════════════════════════
9. CLIENT SPOT UPDATE (External Client Portal)
══════════════════════════════════════════════════════════════

ACTION: Client updates a spot (from ALPS portal)
  ENDPOINT: POST /client-spots/processSpotUpdate/:spotId
  PAYLOAD: { action, emitter, _lastUpdateTS }
  AUTH: Client JWT (VClientJwtAuthGuard)
  SUCCESS: Spot data updated, returns updated spot or true
  NOTE: This is the EXTERNAL client-facing endpoint. Internal users
        use the regular PATCH /spots/:id endpoint.

══════════════════════════════════════════════════════════════
10. VERIFICATION STRATEGIES BY ACTION TYPE
══════════════════════════════════════════════════════════════

For the agent to verify that an action succeeded, use these strategies
in priority order:

  | Action | Primary Verification | Fallback |
  |--------|---------------------|----------|
  | Login | URL not /login + sidebar visible | localStorage has vc2JWT |
  | Submit QO | URL contains POID | Toast "submitted" |
  | Status change | Status badge text matches new value | API response has affectedRows=1 |
  | Approval | Status advances to next step | Checkbox checked in tasks column |
  | Denial | Status reverts to production step | Task notification appears |
  | Revision | Status resets + revision count up | Toast "revision submitted" |
  | Extension | End date updated in list view | Toast confirmation |
  | File upload | File name appears in Files column | Progress indicator completes |
  | Blog post | Blog text visible in Notes section | Blog count increments |
  | Logout | URL is /login or /auth | Login form visible |

CRITICAL TIMING:
  - Toast notifications auto-dismiss in 3-5 seconds
  - Check for toast IMMEDIATELY after the triggering click
  - If toast is missed, fall back to DOM state verification
  - API responses return before Angular finishes change detection
    (wait 300ms after API response before checking DOM state)
