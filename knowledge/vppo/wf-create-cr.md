# vPPO — Create and Manage Creative Requests (CR)
# ================================================
# Source: legacy-ppo codebase & vPPO User Workflows

## WORKFLOW: Create a New Quick Order / Creative Request
KEYWORDS: create request, new spot, quick order, QO, create CR, enter request
JIRA:
---
WHAT: Create a new Creative Request (Quick Order) in vPPO.
WHO: Account Executive, Sales Assistant, Production Manager, Traffic Manager, GM/GSM.
WHERE: vPPO Top Navigation / Dashboard → "New Request +" button.
HOW:
1. Click the "New Request +" button on the main navigation bar or dashboard.
2. Select the Client/Advertiser from the dropdown.
3. Enter the Title / Spot Name (e.g. "Test Spot VPPO-101").
4. Select the Start Date and End Date using date pickers.
5. Select the Ad Type / Media Type (Radio, TV, Digital, etc.).
6. Fill in production instructions / notes into the Production Notes field.
7. Click "Submit" to save and submit the request, or "Save Draft" to keep as draft.
8. Verify success toast or redirection to the spot details view with status `N` (Needs Writing) or `A` (Submitted).

PRECONDITIONS:
- User must be logged in with a role that has `enter_requests: True`.

GOTCHAS:
- If Sales Assistant enters request, system tracks AE in `user_id` and assistant in `actual_user_id`.
- Creating a request automatically adds the creator to `spot_users` as a Point of Contact (POC).
