"""
vQA — vSuite/vProMedia Application Profile
=============================================
Module: backend/profiles/vsuite.py

REFERENCE IMPLEMENTATION — migrates ALL hardcoded vProMedia/vSuite
configuration into a single, self-contained AppProfile instance.

This profile replicates 100% of the pre-modernization behavior:
  - 9 role email/password fallbacks (from roles.py)
  - Angular/PrimeNG root, spinner, and panel selectors (from graph.py, executor.py)
  - Login form selectors with fallback chains (from graph.py)
  - PrimeNG domain glossary (from prompts.py)
  - vSuite-specific planner rules and few-shot examples (from planner.py)

Migration Notes
---------------
The original hardcoded values remain in their source files during the
transition period (marked with ``# MIGRATION: moved to profiles/vsuite.py``).
Once all consumers have been updated to read from the profile, the
hardcoded values will be removed.

See Also
--------
  - ``backend/profiles/base.py``    — AppProfile dataclass definition
  - ``backend/engine/roles.py``     — original credential locations
  - ``backend/engine/graph.py``     — original login node logic
  - ``backend/engine/executor.py``  — original spinner/panel selectors
  - ``backend/engine/planner.py``   — original rules and examples
  - ``backend/engine/prompts.py``   — original domain glossary
"""

from backend.profiles.base import (
    AppProfile,
    LocatorStep,
    LoginFormSelectors,
    RoleDefinition,
)
from backend.profiles.registry import profile_registry

# ---------------------------------------------------------------------------
# Role definitions (migrated from roles.py lines 106–399)
# ---------------------------------------------------------------------------

_VSUITE_ROLES: dict[str, RoleDefinition] = {
    "account_executive": RoleDefinition(
        display_name="Account Executive",
        email="imail-test+DemoAE@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_AE",
        permissions={
            "enter_requests": True,
            "view_own_drafts": True,
            "view_all_drafts": False,
            "view_all_spots": False,
            "approve_own_scripts": True,
            "approve_all_scripts": False,
        },
        constraints=[
            "Can create Quick Orders (QO) via 'New Request +' button.",
            "Can only view and manage drafts for own clients.",
            "CANNOT access 'View All Spots' — flag as RBAC violation if visible.",
            "CANNOT view drafts for other AEs' clients.",
            "Can approve scripts, but only for own clients.",
            "Dashboard should show only own client list.",
        ],
    ),
    "sales_manager": RoleDefinition(
        display_name="Sales Manager",
        email="imail-test+DemoSM@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_SALES_MANAGER",
        permissions={
            "view_all_firm_spot_drafts": True,
            "approve_reject_clients": True,
            "act_as_ae": True,
            "view_all_spots": True,
            "enter_requests": True,
        },
        constraints=[
            "Can view ALL firm spot drafts across all AEs.",
            "Can approve or reject client relationships.",
            "Can act as (impersonate) any Account Executive.",
            "'View All Spots' should be present and accessible — verify it loads.",
            "Full visibility into the production pipeline.",
        ],
    ),
    "sales_assistant": RoleDefinition(
        display_name="Sales Assistant",
        email="imail-test+DemoSA@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_SALES_ASSISTANT",
        permissions={
            "enter_requests_on_behalf": True,
            "view_all_firm_spots": True,
            "approve_reject": False,
            "uses_actual_user_id": True,
        },
        constraints=[
            "Enters requests ON BEHALF of an Account Executive.",
            "Uses actual_user_id (not user_id) in API payloads — a key RBAC signal.",
            "Can view all firm spots.",
            "CANNOT approve or reject anything — flag as RBAC violation if those buttons appear.",
            "No independent client ownership — acts as an AE's delegate.",
        ],
    ),
    "production_manager": RoleDefinition(
        display_name="Production Manager",
        email="imail-test+DemoPM@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_PRODUCTION_MANAGER",
        permissions={
            "delegate_jobs": True,
            "assign_poc_cart_house": True,
            "line_edit": True,
            "oversee_all_production": True,
            "view_all_spots": True,
        },
        constraints=[
            "Can delegate production jobs to individual Producers.",
            "Can assign POC, Cart, and House numbers to spots.",
            "Can line-edit production items directly.",
            "Full oversight visibility across all production.",
            "Production management dashboard should be the default view.",
        ],
    ),
    "producer": RoleDefinition(
        display_name="Producer",
        email="imail-test+DemoProducer@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_PRODUCER",
        permissions={
            "produce_creative": True,
            "upload_files": True,
            "authorize_creative": True,
            "uses_spot_users_table": True,
            "view_all_spots": False,
        },
        constraints=[
            "Produces and uploads creative assets (audio, video, copy).",
            "Can authorize creative output for assigned spots.",
            "Visibility is LIMITED to spots in the spot_users table (assigned spots only).",
            "CANNOT see spots they are not assigned to — flag as RBAC violation if shown.",
            "Upload file UI should be present and functional.",
        ],
    ),
    "gm_gsm": RoleDefinition(
        display_name="GM / GSM",
        email="imail-test+DemoGM@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_GM_GSM",
        permissions={
            "full_oversight": True,
            "personal_clients_inbox": True,
            "view_all_spots": True,
            "view_all_firm_drafts": True,
            "approve_reject_clients": True,
        },
        constraints=[
            "Full system oversight — should see all firm spots and drafts.",
            "Has a personal client list accessible via Inbox.",
            "'View All Spots', 'View All Drafts', and Inbox should all be accessible.",
            "Can approve or reject client relationships.",
            "No restrictions — flag any missing navigation as a potential regression.",
        ],
    ),
    "dubber": RoleDefinition(
        display_name="Dubber",
        email="imail-test+DemoDubber@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_DUBBER",
        permissions={
            "quality_control": True,
            "trigger_autodub": True,
            "uses_dubflag": True,
            "produce_creative": False,
            "upload_files": False,
            "line_edit": False,
        },
        constraints=[
            "Quality-control specialised role — reviews dub output.",
            "Can trigger the autodub microservice via the dubflag mechanism.",
            "CANNOT create, edit, or upload creative — read-only access to production items.",
            "Flag as RBAC violation if Upload or Edit buttons are present.",
            "Dub approval interface should be the primary workflow surface.",
        ],
    ),
    "digital_director": RoleDefinition(
        display_name="Digital Director/Producer",
        email="imail-test+DemoProdDirector@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_DIGITAL_DIRECTOR",
        permissions={
            "upload_display_ads": True,
            "filter_by_digital": True,
            "view_digital_spots_only": True,
            "view_radio_spots": False,
        },
        constraints=[
            "Specialised in digital (display ad) creative.",
            "Spot list should be filtered by metadata.product_type = 'Digital'.",
            "Can upload display ad files.",
            "Should NOT see radio/audio spots — flag if they appear.",
            "Digital product filter should be active by default.",
        ],
    ),
    "demo_prod_director": RoleDefinition(
        display_name="Demo Prod Director",
        email="imail-test+DemoProdDirector@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_DEMO_PROD_DIRECTOR",
        permissions={
            "upload_display_ads": True,
            "filter_by_digital": True,
            "view_digital_spots_only": True,
            "view_radio_spots": False,
            "delegate_jobs": True,
            "oversee_all_production": True,
            "view_all_spots": True,
        },
        constraints=[
            "Production Director — full oversight of production pipeline.",
            "Can delegate production jobs.",
            "Can view all spots and manage production workflow.",
            "Has digital and production capabilities.",
        ],
    ),
    "voice_talent": RoleDefinition(
        display_name="Demo Voice Talent",
        email="imail-test+DemoVoicer@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_VOICE_TALENT",
        permissions={
            "view_assigned_voice_requests": True,
            "upload_voice_files": True,
            "complete_voice_parts": True,
            "view_all_spots": False,
            "enter_requests": False,
        },
        constraints=[
            "Voice talent user — receives and completes voice request assignments.",
            "Can view and act on voice requests assigned to them.",
            "Can upload voice recordings for assigned parts.",
            "CANNOT create orders, manage production, or access admin areas.",
            "Voice Requests folder should be the primary workflow surface.",
        ],
    ),
    "vtrade_exec": RoleDefinition(
        display_name="vTrade Exec",
        email="imail-test+vTradeExec@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_VTRADE_EXEC",
        permissions={
            "view_vtrade_dashboard": True,
            "approve_vtrade_orders": True,
        },
        constraints=[
            "This is a vTrade application user.",
            "Has executive oversight of vTrade transactions.",
            "Can approve or reject high-level trade orders.",
            "Dashboard should show vTrade-specific metrics.",
        ],
    ),
    "vtrade_business_manager": RoleDefinition(
        display_name="vTrade Business Manager",
        email="imail-test+vTradeBusinessManager@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_VTRADE_BM",
        permissions={
            "manage_vtrade_contracts": True,
            "audit_vtrade_ledger": True,
        },
        constraints=[
            "This is a vTrade application user.",
            "Manages the financial and contractual aspects of vTrade.",
            "Can view and audit vTrade ledgers and contracts.",
            "Primary workflow involves contract verification and financial auditing.",
        ],
    ),
    "vtrade_sales_manager": RoleDefinition(
        display_name="vTrade Sales Manager",
        email="imail-test+vTradeSalesManager@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_VTRADE_SM",
        permissions={
            "manage_vtrade_sales": True,
            "view_sales_reports": True,
        },
        constraints=[
            "This is a vTrade application user.",
            "Oversees the sales pipeline within the vTrade platform.",
            "Can manage sales opportunities and view detailed sales reports.",
            "Focuses on driving trade volume and managing sales team performance.",
        ],
    ),
    "vpromotions_user": RoleDefinition(
        display_name="vPromotions User",
        email="",
        email_env_var="ROLE_EMAIL_VPROMOTIONS_USER",
        permissions={
            "access_vpromotions": True,
        },
        constraints=[
            "This is a vPromotions application user — NOT a vSuite user.",
            "The target URL will be a vPromotions URL (e.g. vpromotions-rc.vcreative.net).",
            "Login page will look different from vSuite — expect a different UI.",
            "No vSuite-specific RBAC rules apply here.",
        ],
    ),
    "writer": RoleDefinition(
        display_name="Writer",
        email="imail-test+writer@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_WRITER",
        permissions={
            "enter_requests": False,
            "assign_poc": False,
            "view_all_spots": False,
            "view_assigned_spots": True,
            "line_edit_scripts": True,
        },
        constraints=[
            "CANNOT create or enter requests — flag as RBAC violation if New Request button is visible.",
            "CANNOT assign POC — flag as RBAC violation if delegation UI appears.",
            "Can ONLY see spots directly assigned to them via spot_users table (writeflag).",
            "Writes and edits scripts; sends to script review; marks writer job as completed.",
            "Role Flag: writeflag — spot visibility filtered by spot_users matching user_id.",
        ],
    ),
    "traffic_manager": RoleDefinition(
        display_name="Traffic Manager",
        email="imail-test+DemoTrafficDirector@vcreativeinc.com",
        email_env_var="ROLE_EMAIL_TRAFFIC_MANAGER",
        permissions={
            "enter_requests_on_behalf": True,
            "assign_poc_traffic_only": True,
            "view_all_spots": True,
            "assign_cart_house": True,
            "edit_status": True,
            "line_edit": True,
        },
        constraints=[
            "Can enter requests ON BEHALF of an AE — not as originator.",
            "Assigns Cart/House IDs to spots — primary cartid owner.",
            "Schedules spots and monitors deadlines.",
            "POC assignment is limited to Traffic jobs only — flag if broader POC delegation is shown.",
            "Manages ISCI codes (metadata.cartid) and contract numbers.",
            "Role Flag: trafficflag — used in metadata queries for traffic-specific views.",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Role aliases (migrated from roles.py lines 417–444)
# ---------------------------------------------------------------------------

_VSUITE_ROLE_ALIASES: dict[str, str] = {
    "demo voice talent": "voice_talent",
    "voice talent": "voice_talent",
    "voicer": "voice_talent",
    "demo voicer": "voice_talent",
    "demo account executive": "account_executive",
    "demo ae": "account_executive",
    "ae": "account_executive",
    "account executive": "account_executive",
    "demo sales manager": "sales_manager",
    "sales manager": "sales_manager",
    "demo production manager": "digital_director",
    "production manager": "production_manager",
    "demo producer": "producer",
    "producer": "producer",
    "demo dubber": "dubber",
    "dubber": "dubber",
    "digital director": "digital_director",
    "demo prod director": "demo_prod_director",
    "demo production director": "demo_prod_director",
    "production director": "demo_prod_director",
    "prod director": "demo_prod_director",
    "demo gm": "gm_gsm",
    "gm": "gm_gsm",
    "gsm": "gm_gsm",
    "general manager": "gm_gsm",
    "sales assistant": "sales_assistant",
    "vtrade exec": "vtrade_exec",
    "vtrade business manager": "vtrade_business_manager",
    "vtrade sales manager": "vtrade_sales_manager",
}


# ---------------------------------------------------------------------------
# Login form selectors (migrated from graph.py login_node lines 640–693)
# ---------------------------------------------------------------------------

_VSUITE_LOGIN_SELECTORS = LoginFormSelectors(
    email_input=[
        LocatorStep("get_by_role", ("textbox",), {"name": "Email"}),
        LocatorStep("get_by_placeholder", ("Email",)),
    ],
    password_input=[
        LocatorStep("get_by_role", ("textbox",), {"name": "Password"}),
        LocatorStep("get_by_placeholder", ("Password",)),
    ],
    submit_button=[
        LocatorStep("get_by_role", ("button",), {"name": "Log In"}),
        LocatorStep("get_by_role", ("button",), {"name": "Login"}),
        LocatorStep("get_by_role", ("button",), {"name": "Sign In"}),
        LocatorStep("css_selector", ("button[type='submit'], input[type='submit']",)),
    ],
)


# ---------------------------------------------------------------------------
# Angular/PrimeNG root selectors (migrated from graph.py lines 181–186)
# ---------------------------------------------------------------------------

_VSUITE_APP_ROOT_SELECTORS: list[str] = [
    "app-root",  # Standard Angular root component
    "vp-root",  # vProMedia-specific root
    "[ng-version]",  # Angular version attribute (set after bootstrap)
    "router-outlet",  # Angular router outlet (present after hydration)
]


# ---------------------------------------------------------------------------
# Spinner selectors (migrated from executor.py lines 229–236)
# ---------------------------------------------------------------------------

_VSUITE_SPINNER_SELECTORS: list[str] = [
    ".p-datatable-loading-overlay",
    ".p-datatable-loading-icon",
    ".vcreative-icon.loading",
    ".loading-overlay",
    ".ui-blockui",
    ".p-blockui",
]


# ---------------------------------------------------------------------------
# Detail panel selectors (migrated from executor.py lines 163–170)
# ---------------------------------------------------------------------------

_VSUITE_DETAIL_PANEL_SELECTORS: list[str] = [
    "app-spot-detail",  # Spot detail component
    ".spot-detail-panel",  # Spot detail panel class
    "app-production-order-detail",  # PO detail component
    ".detail-panel",  # Generic detail panel
    ".slideout-panel.open",  # Slideout panel in open state
    "app-quick-order",  # QO form (counts as open panel)
]


# ---------------------------------------------------------------------------
# Domain glossary (migrated from prompts.py lines 127–200)
# ---------------------------------------------------------------------------

_VSUITE_DOMAIN_GLOSSARY = """\
DOMAIN GLOSSARY (map UI terms → component identifiers):
- "Spots Grid", "Production Grid", "Production Orders table" = p-table
- "Ad Type Dropdown", "select ad type" = p-dropdown
- "Client Search", "client field", "client autocomplete" = p-autocomplete
- "Success Message", "toast", "notification", "error toast" = p-toast
  → selector_hint MUST be ".p-toast-message" (NOT ".p-toast" — that is the wrapper
    container which is always in the DOM and will never be "visible" when empty)
  → For toast verification, always use type "toast_message" with expected_text;
    NEVER use type "element_visible" with a toast target.
- "Calendar", "date picker", "due date", "date field" = p-calendar
- "Confirm Dialog", "confirmation modal", "are you sure" = p-confirmdialog
- "Multi-select", "select multiple" = p-multiselect
- "Checkbox", "toggle", "check/uncheck" = p-checkbox
- Login page = login-form
- Navigation links, sidebar = nav-link
- Standard buttons (Save, Submit, Create, etc.) = button
- Standard text inputs = text-input
- "Column header", "sort column", "sort by CLIENT/STATUS/etc.", \
  "clicks column to sort" → step_type="CLICK", target_component="p-table",
  verification type="table_sort" with expected_column and expected_direction.
  NEVER use visual_check or element_visible to verify sort order.
  Sortable column names — use the EXACT DOM label in expected_column:
    CLIENT → expected_column="CLIENT"
    STATUS & APPROVALS → expected_column="Status & Approvals"  (NOT "STATUS/TASKS")
      DUE DATE / DAYS → compound column, uses a dropdown inside the header (see below)
    START DATE / END DATE → compound column, uses a dropdown inside the header (see below)
  List view: click the <th> column header directly for CLIENT and Status & Approvals.
  COMPOUND COLUMNS (Due/Days, Start/End): These use a PrimeNG p-select inside the
    column header. ALWAYS COMBINE the open+select into ONE step. Use recipe step_type.
      ONE COMBINED STEP: goal="Click Due Date column header to sort ascending"
        → step_type="CLICK", use recipe p_select_column_sort
        → verification type="table_sort", expected_column="Due Date", expected_direction="ascending"
    DO NOT create separate "open dropdown" + "select option" steps for compound columns.
    FORBIDDEN: clicking combobox twice (closes without selecting).
    FORBIDDEN: css_selector p-select#header-sort-drop-down-duedaysCol (times out).
    FORBIDDEN: element_visible with selector_hint='p-select-overlay' for compound column steps.
      (p-select-overlay closes in <100ms — verifier always fires after it has closed)
  Compact/Minimal view: sort via button#sort-btn, NOT button#settings-btn.
    button#settings-btn → View Type switcher (List/Compact/Minimal). WRONG button.
    button#sort-btn     → Sort popover. Use this for compact view sorting.
    Sortable in Compact View: CLIENT, Title.
    NOT sortable in Compact View: Status & Approvals, Due Date, Submitted On.
"""


# ---------------------------------------------------------------------------
# System boundary rule (migrated from prompts.py lines 96–103)
# ---------------------------------------------------------------------------

_VSUITE_SYSTEM_BOUNDARY = """\
You are generating a test plan strictly for the vProMedia web application. \
If the Jira ticket includes instructions to "vote on the card", "comment on \
the card", "move card to approved/done", "notify the smoke room", "update the \
Jira ticket", or any other action that takes place OUTSIDE the vProMedia \
application (Jira administration, Slack messages, email notifications, etc.), \
IGNORE THEM entirely. Do not create test steps for Jira administration or \
external communication tools. Only create steps that can be executed inside \
the vProMedia application at the target URL."""


# ---------------------------------------------------------------------------
# Identity prompt (migrated from planner.py SYSTEM_PROMPT_TEMPLATE line 663)
# ---------------------------------------------------------------------------

_VSUITE_IDENTITY = "a web application called vProMedia/vSuite by executing Acceptance Criteria from a Jira ticket"


# ---------------------------------------------------------------------------
# Few-shot examples (migrated from planner.py lines 738–788)
# ---------------------------------------------------------------------------

_VSUITE_FEW_SHOT = """\
Example 1: Ad Type Selection (custom dropdown — NOT combobox)
  click get_by_role('button', name='') inside '#qo-form-panel'
  then click get_by_label('Radio Commercial')

Example 2: Client Autocomplete (type partial -> wait -> click option)
  fill get_by_role('searchbox', name='Client ') value='Bob'
  click get_by_role('option', name="Bob's Burgers")

Example 3: File Upload (NEVER click Browse)
  {{"action": "set_input_files", "selector": "p-fileupload input[type='file']", "value": "Client Logo.jpg"}}

Example 4: Sorting a Standard Column
  {{"action": "click", "strategy": "css_selector", "name": "th.po-col-clientCol"}}
  {{"action": "wait", "value": 1000}}
  {{"action": "verify_table_sort", "column": "CLIENT", "order": "ascending"}}

Example 5: Strict Mode — use vqa_id
  # Failure diary: "Strict mode violation: get_by_text('Save') matched 3 elements"
  # Element tree: [vqa_id=17] button "Save" (main footer)
  {{"action": "click", "strategy": "css_selector", "name": "[data-vqa-id='17']"}}

Example 6: PrimeNG Dropdown (Sort By, p-select, combobox) — ALWAYS use primeng_dropdown
  # ❌ WRONG — causes toggle loop (click opens, second click closes):
  #   {{"action": "click", "strategy": "css_selector", "name": "button#sort-btn"}}
  #   {{"action": "click", "strategy": "get_by_text", "name": "Due Date A-Z"}}
  #
  # ✅ CORRECT — single atomic action, no loop risk:
  {{"action": "primeng_dropdown",
    "trigger_selector": "button#sort-btn",
    "target_text": "Due Date A-Z",
    "portal_class": ".po-sorting-dropdown-panel",
    "reasoning": "use primeng_dropdown for Sort By portal"}}

  # For the header-sort p-select (Due/Days column):
  # ⚠️ NOTE: inputId="header-sort-drop-down-duedaysCol" sets the id on the INNER <input>,
  # NOT on the host <p-select> element. So p-select#header-sort-drop-down-duedaysCol is
  # INVALID CSS that will always timeout. Use the th-scoped selector instead:
  {{"action": "primeng_dropdown",
    "trigger_selector": "th.po-col-duedaysCol p-select",
    "target_text": "Due Date A-Z",
    "portal_class": ".po-sorting-dropdown-panel",
    "reasoning": "atomic compound-column sort via primeng_dropdown"}}

  # For the Start/End compound column:
  {{"action": "primeng_dropdown",
    "trigger_selector": "th.po-col-startendCol p-select",
    "target_text": "Start Date A-Z",
    "portal_class": ".po-sorting-dropdown-panel",
    "reasoning": "atomic compound-column sort — Start/End column"}}
"""


# ---------------------------------------------------------------------------
# Assemble the profile
# ---------------------------------------------------------------------------

VSUITE_PROFILE = AppProfile(
    # ── Identity ──────────────────────────────────────────────────────
    name="vsuite",
    display_name="vProMedia/vSuite 2.0",
    description="vProMedia SaaS platform — Angular 19 + PrimeNG UI framework",
    # ── Authentication ────────────────────────────────────────────────
    login_url_path="/login",
    auth_verification="jwt_localstorage",
    jwt_storage_key="vc2JWT",
    login_form_selectors=_VSUITE_LOGIN_SELECTORS,
    # ── Roles ─────────────────────────────────────────────────────────
    roles=_VSUITE_ROLES,
    default_password_env="ROLE_DEFAULT_PASSWORD",
    default_password_fallback="Ep!cVCteam2026$",
    role_aliases=_VSUITE_ROLE_ALIASES,
    # ── DOM Synchronization ───────────────────────────────────────────
    app_root_selectors=_VSUITE_APP_ROOT_SELECTORS,
    spinner_selectors=_VSUITE_SPINNER_SELECTORS,
    detail_panel_selectors=_VSUITE_DETAIL_PANEL_SELECTORS,
    # ── Domain Knowledge ──────────────────────────────────────────────
    domain_glossary=_VSUITE_DOMAIN_GLOSSARY,
    system_boundary_rule=_VSUITE_SYSTEM_BOUNDARY,
    identity_prompt=_VSUITE_IDENTITY,
    few_shot_examples=_VSUITE_FEW_SHOT,
)


# ---------------------------------------------------------------------------
# Auto-register at import time
# ---------------------------------------------------------------------------

profile_registry.register(VSUITE_PROFILE)
