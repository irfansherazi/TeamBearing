## WORKFLOW: vProMedia State Machine — Valid Transitions for All Major Workflows
KEYWORDS: state, status, transition, order, sequence, precondition, postcondition, state machine, flow, valid transition, invalid, cannot, requires, first, before, after, workflow state
---
Source: vcapi workflow-service.service.ts + production vProMedia behavior

CRITICAL RULE: The agent MUST understand which application states are valid
preconditions for each action. Attempting actions out of order causes silent
failures or confusing error states.

══════════════════════════════════════════════════════════════
1. AUTHENTICATION STATE MACHINE
══════════════════════════════════════════════════════════════

  [Unauthenticated]
       │
       │ POST /auth (email + password)
       │ Success → ssoToken returned, stored in localStorage as 'vc2JWT'
       ▼
  [SSO Authenticated]
       │
       │ POST /auth/vproLogin (automatic, uses ssoToken)
       │ Success → vProToken returned
       ▼
  [Fully Authenticated — Dashboard Visible]
       │
       │ Token refresh: POST /auth/ssoRefresh (automatic, periodic)
       │ Token expiry → redirect to login page
       ▼
  [Session Expired] → back to [Unauthenticated]

PRECONDITIONS:
- Left sidebar nav is ONLY visible after [Fully Authenticated]
- 'New Request +' button is ONLY visible after [Fully Authenticated]
- Any /spots/* API call requires JWT in Authorization header
- vc2JWT appears in localStorage ASYNCHRONOUSLY after login API returns
  (poll up to 5 seconds before declaring login failed)

LOGOUT:
  [Fully Authenticated] → click user avatar dropdown → click 'Logout'
  → localStorage cleared → redirect to [Unauthenticated]

══════════════════════════════════════════════════════════════
2. QUICK ORDER (SPOT) LIFECYCLE STATE MACHINE
══════════════════════════════════════════════════════════════

  [No Order]
       │
       │ Click 'New Request +' → QO modal opens
       ▼
  [QO Form Open — Draft]
       │
       │ Select Ad Type (required first step in form)
       ▼
  [Ad Type Selected — Form Fields Visible]
       │
       │ Fill required fields:
       │   - Client/Advertiser (autocomplete, 500ms debounce)
       │   - Spot Title
       │   - Status (dropdown)
       │   - Length (dropdown)
       │   - Rotation
       │   - Station(s)
       │ Draft auto-saves to /spots (POST, creates spot_draft)
       ▼
  [All Required Fields Filled — Submit Button ENABLED]
       │
       │ Click 'Submit All' button
       │ API: POST /spots (creates spot from draft)
       │ OR PATCH /spots/:id (updates existing spot)
       ▼
  [Order Submitted — POID Assigned]
       │
       │ URL changes: .../production-order/{POID}
       │ Toast: "Order submitted successfully"
       │ Spot appears in Production Orders list
       ▼
  [In Production — Status-Driven Workflow Begins]

INVALID TRANSITIONS — WILL FAIL SILENTLY:
- ✗ Click 'Submit All' before selecting Ad Type → button stays disabled
- ✗ Click 'Submit All' before filling Client → button stays disabled
- ✗ Fill Client field without wait → autocomplete dropdown doesn't appear
- ✗ Type in Client field and immediately click Submit → Angular hasn't processed
- ✗ Navigate away before Submit All → order saved as Draft only

══════════════════════════════════════════════════════════════
3. SPOT STATUS LIFECYCLE STATE MACHINE
══════════════════════════════════════════════════════════════

Statuses are driven by the workflow engine (vsuite.wf_workflow_steps).
The exact available statuses depend on the firm's workflow configuration,
but the COMMON production workflow is:

  [Needs Writing]
       │
       │ Writer completes script → status changes
       ▼
  [Script Review]   ◄── (if "Require Script Approval" was checked on QO)
       │
       │ AE or client approves script
       │ API: PATCH /spots/approve/:id
       ▼
  [Needs Producing]
       │
       │ Producer completes spot
       │ API: PATCH /spots/:id {status: "Needs Dubbing"}
       ▼
  [Needs Dubbing]
       │
       │ Dubber completes voiceover
       ▼
  [Spot Review]   ◄── (if "Require Spot Approval" was checked on QO)
       │
       │ AE or client approves spot
       │ API: PATCH /spots/approve/:id
       ▼
  [Approved / Needs Scheduling]
       │
       │ Traffic/scheduler assigns to on-air rotation
       ▼
  [Scheduled / Carted]
       │
       │ Spot runs on air / billing completed
       ▼
  [Archived]

ALTERNATE PATHS:
  Any status → [Rejected]  (via Action Bar → Reject)
    API: PATCH /spots/:id or action bar reject flow
    Rejected spots return to submitter as Draft for re-work

  Any status → [Attention]  (manual override by manager)

  [Spot Review] → [Denied]  (client denies spot)
    API: PATCH /spots/deny/:id
    Returns to [Needs Producing] for re-work

IMPORTANT CONSTRAINTS:
- Status changes via the LIST VIEW use a combobox/dropdown (display-only
  for most roles). Only managers can change status inline.
- Status changes via the ORDER DETAIL panel use select_option action.
- The Submit All button on QO sets the INITIAL status — it cannot be used
  to change status after submission.
- Approval/denial uses SEPARATE API endpoints (/spots/approve/:id and
  /spots/deny/:id) — NOT the standard PATCH /spots/:id

══════════════════════════════════════════════════════════════
4. REVISION PROCESS STATE MACHINE
══════════════════════════════════════════════════════════════

  [Existing Spot — Any Active Status]
       │
       │ Select spot(s) in list → Action Bar appears
       │ Click 'Revise' in Action Bar
       ▼
  [Revision Panel Open]
       │
       │ Click right-arrow to begin revision for each spot
       │ QO form reopens with existing data
       ▼
  [QO Form in Revision Mode]
       │
       │ REQUIRED changes (cannot finish without):
       │   1. New Due Date
       │   2. Blog post explaining the revision
       │ Optional: change other fields (copy, production notes, etc.)
       │
       │ API: POST /mmorders/processExtensionOrRevisionForSingleSpot
       ▼
  [Revision Submitted]
       │
       │ Status resets to [Needs Writing] or [Needs Producing]
       │ (depending on workflow config)
       │ POC assignments may reset
       │ Toast: "Revision submitted" or similar
       ▼
  [Back in Production Workflow with New Revision Number]

PRECONDITIONS:
- Spot must be in an ACTIVE status (not Archived, not Deleted)
- User must have revision permission for their role
- At least one spot must be selected in the list view
- If revising multiple spots, each must be addressed individually
  (checkmark appears when minimum requirements met for each)

══════════════════════════════════════════════════════════════
5. FILE UPLOAD STATE MACHINE
══════════════════════════════════════════════════════════════

  [Order Detail Panel Open]
       │
       │ Files column visible in list view OR file area in detail panel
       ▼
  [File Upload Area Visible]
       │
       │ Click upload button or drag-and-drop zone
       │ Use input[type=file] for programmatic upload
       ▼
  [File Selected — Upload In Progress]
       │
       │ Progress indicator shows upload status
       │ API: multipart POST (binary upload)
       ▼
  [File Uploaded — Listed in Files Column]

PRECONDITIONS:
- Order must be submitted (not a Draft) for file types like 'Final Spot'
- User must have file upload permission for their role
- File size limit: 1GB (1000MB) per file
- File type must be allowed for the user's role (Restrict File Type Usage)

══════════════════════════════════════════════════════════════
6. COPY / EXTEND STATE MACHINES
══════════════════════════════════════════════════════════════

COPY:
  [Spot(s) Selected] → Action Bar → 'Copy'
       → Copy panel slides out
       → Click 'Finish' → QO form opens with pre-filled data
       → Modify as needed → Submit
       → NEW spot created (separate POID)

EXTEND:
  [Spot(s) Selected] → Action Bar → 'Extend'
       → Extend panel slides out (only End Date editable)
       → Update End Date → Click 'Finish'
       → SAME spot updated with new End Date

KEY DIFFERENCE: Copy creates NEW spots. Extend modifies EXISTING spots.

══════════════════════════════════════════════════════════════
7. FOLDER / NAVIGATION STATE MACHINE
══════════════════════════════════════════════════════════════

  [Fully Authenticated — Dashboard]
       │
       ├─ Click folder in left sidebar → table loads with folder's spots
       ├─ Click 'MyBox' → personal queue (role-specific default view)
       ├─ Click search icon → search results view
       └─ Click 'Production Orders' → all POs for the firm

After navigation:
  - Table rows render ASYNCHRONOUSLY (Angular change detection)
  - Wait for tbody tr to be visible before interacting with rows
  - Do NOT rely on networkidle for Angular client-side routes
  - Folder counts in sidebar may lag behind actual row count

══════════════════════════════════════════════════════════════
8. APPROVAL STATE MACHINE
══════════════════════════════════════════════════════════════

  [Spot in "Script Review" or "Spot Review"]
       │
       ├─ APPROVE: checkbox in Status/Tasks column or API /spots/approve/:id
       │    → Status advances to next workflow step
       │    → Notifications sent to POC
       │
       └─ DENY: Action Bar → Reject, or API /spots/deny/:id
            → Status returns to previous production step
            → Task notification sent to submitter
            → Blog post required explaining denial

PRECONDITIONS:
- Only users with approval ability can approve/deny
- Spot must be in a Review status (Script Review or Spot Review)
- Approval and denial are separate API endpoints from regular status updates
