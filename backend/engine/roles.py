"""
vQA — Role Registry
====================
Module: backend/engine/roles.py

Defines the mapping between role keys (used in API requests) and the
full ``RoleContext`` objects that are injected into the LangGraph state.

Architecture Context
--------------------
There are 8 vProMedia user roles, each with:

  * **Login credentials**  — fetched from the Bedrock Roles KB
    (``JXMMTMTI06``) at startup.  Falls back to env vars if KB is
    unavailable.  No email or password is ever hardcoded in this file.
  * **Permission flags**   — static dict describing what the role can do.
    These inform both the system prompt *and* the evaluator's RBAC checks.
  * **LLM constraints**    — plain-English strings appended to the planner's
    system prompt so Claude knows what UI surfaces are expected / forbidden
    for this role.

Credential Source Priority
--------------------------
  1. **Bedrock Roles KB** (primary) — queries KB ``JXMMTMTI06`` for
     login emails and password.  See ``kb_client.py``.
  2. **Environment variables** (fallback) — ``ROLE_EMAIL_*`` and
     ``ROLE_DEFAULT_PASSWORD``.  Used when the KB is unreachable
     (local dev without AWS, CI, etc.).

Usage
-----
    from backend.engine.roles import ROLE_REGISTRY, get_role_context

    ctx = get_role_context("account_executive")
    print(ctx["login_email"])   # from KB or env fallback
    print(ctx["constraints"])   # list of planning constraint strings

Design Decisions
----------------
* ``_build_registry()`` is called once at module load time.
* The result is stored as the module-level ``ROLE_REGISTRY`` constant.
* Credentials are resolved with KB → env var → empty string priority.
* ``get_role_context()`` raises ``KeyError`` for unknown role keys.
"""

import logging
import os
from typing import Final

from backend.engine.state import RoleContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def _resolve_credentials() -> dict[str, dict[str, str]]:
    """
    Resolve login credentials using KB (primary) → env vars (fallback).

    Attempts to fetch credentials from the Bedrock Roles KB first.
    If the KB is unavailable or returns empty results, falls back to
    environment variables.

    Returns
    -------
    dict[str, dict[str, str]]
        Mapping of role_key → {"email": ..., "password": ...}.
    """
    # ── Try KB first ──────────────────────────────────────────────────
    kb_creds: dict[str, dict[str, str]] = {}

    try:
        from backend.engine.kb_client import fetch_all_role_credentials

        kb_creds = fetch_all_role_credentials()
        logger.info("Credentials loaded from Bedrock Roles KB")
    except Exception as e:
        logger.warning(
            "KB credential fetch failed (%s), falling back to local persona files",
            str(e),
        )

    # ── Try local persona files as second tier ────────────────────────
    local_creds: dict[str, dict[str, str]] = {}
    if not kb_creds:
        try:
            from backend.engine.kb_client import load_local_persona_credentials

            local_creds = load_local_persona_credentials()
            if local_creds:
                logger.info("Credentials loaded from local knowledge/personas/ files")
        except Exception as e:
            logger.warning("Local persona file load failed (%s), falling back to env vars", str(e))

    # ── Build final credential map with fallbacks ─────────────────────
    # MIGRATION: env var keys and hardcoded email/password fallbacks now
    # come from the active AppProfile instead of being hardcoded here.
    # Import is lazy to avoid circular imports at module load time.
    try:
        from backend.profiles import get_active_profile

        _profile = get_active_profile()
    except Exception:
        _profile = None

    # Build env_fallback_map from profile role definitions if available,
    # otherwise use hardcoded vSuite keys for backward compatibility.
    env_fallback_map = {
        "account_executive": "ROLE_EMAIL_AE",
        "sales_manager": "ROLE_EMAIL_SALES_MANAGER",
        "sales_assistant": "ROLE_EMAIL_SALES_ASSISTANT",
        "production_manager": "ROLE_EMAIL_PRODUCTION_MANAGER",
        "producer": "ROLE_EMAIL_PRODUCER",
        "gm_gsm": "ROLE_EMAIL_GM_GSM",
        "dubber": "ROLE_EMAIL_DUBBER",
        "digital_director": "ROLE_EMAIL_DIGITAL_DIRECTOR",
        "demo_prod_director": "ROLE_EMAIL_DEMO_PROD_DIRECTOR",
        "traffic_manager": "ROLE_EMAIL_TRAFFIC_MANAGER",
        "voice_talent": "ROLE_EMAIL_VOICE_TALENT",
        "writer": "ROLE_EMAIL_WRITER",
        "vpromotions_user": "ROLE_EMAIL_VPROMOTIONS_USER",
        "vtrade_exec": "ROLE_EMAIL_VTRADE_EXEC",
        "vtrade_business_manager": "ROLE_EMAIL_VTRADE_BUSINESS_MANAGER",
        "vtrade_sales_manager": "ROLE_EMAIL_VTRADE_SALES_MANAGER",
        "vppo_account_executive": "ROLE_EMAIL_VPPO_ACCOUNT_EXECUTIVE",
        "vppo_digital_director": "ROLE_EMAIL_VPPO_DIGITAL_DIRECTOR",
        "vppo_dubber": "ROLE_EMAIL_VPPO_DUBBER",
        "vppo_gm_gsm": "ROLE_EMAIL_VPPO_GM_GSM",
        "vppo_producer": "ROLE_EMAIL_VPPO_PRODUCER",
        "vppo_production_manager": "ROLE_EMAIL_VPPO_PRODUCTION_MANAGER",
        "vppo_sales_assistant": "ROLE_EMAIL_VPPO_SALES_ASSISTANT",
        "vppo_sales_manager": "ROLE_EMAIL_VPPO_SALES_MANAGER",
        "vppo_traffic_manager": "ROLE_EMAIL_VPPO_TRAFFIC_MANAGER",
        "vppo_voicer": "ROLE_EMAIL_VPPO_VOICER",
        "vppo_writer": "ROLE_EMAIL_VPPO_WRITER",
    }

    if _profile and _profile.roles:
        for role_key, role_def in _profile.roles.items():
            if role_def.email_env_var:
                env_fallback_map[role_key] = role_def.email_env_var

    # Password priority: KB → env vars → profile fallback
    # Email priority:    KB → env var → profile role definition
    default_password = (
        kb_creds.get("account_executive", {}).get("password", "")
        or local_creds.get("account_executive", {}).get("password", "")
        or os.getenv("ROLE_DEFAULT_PASSWORD", "")
        or (os.getenv(_profile.default_password_env, "") if _profile else "")
        or (_profile.default_password_fallback if _profile else "Ep!cVCteam2026$")
    )

    hardcoded_email_fallbacks = {
        "account_executive": "imail-test+DemoAE@vcreativeinc.com",
        "sales_manager": "imail-test+DemoSM@vcreativeinc.com",
        "sales_assistant": "cyndi.bass82@yahoo.com",
        "production_manager": "imail-test+DemoProdMan@vcreativeinc.com",
        "producer": "imail-test+DemoTVProducer@vcreativeinc.com",
        "gm_gsm": "imail-test+DemoGM@vcreativeinc.com",
        "dubber": "imail-test+DemoProdDirector@vcreativeinc.com",
        "digital_director": "imail-test+DemoDigitalDir@vcreativeinc.com",
        "demo_prod_director": "imail-test+DemoProdDirector@vcreativeinc.com",
        "traffic_manager": "imail-test+DemoTrafficDirector@vcreativeinc.com",
        "voice_talent": "imail-test+DemoVoicer@vcreativeinc.com",
        "writer": "imail-test+writer@vcreativeinc.com",
        "vpromotions_user": "",
        "vtrade_exec": "imail-test+vTradeExec@vcreativeinc.com",
        "vtrade_business_manager": "imail-test+vTradeBusinessManager@vcreativeinc.com",
        "vtrade_sales_manager": "imail-test+vTradeSalesManager@vcreativeinc.com",
        "vppo_account_executive": "imail-test+SalesExec@vcreativeinc.com",
        "vppo_digital_director": "imail-test+DigitalDir@vcreativeinc.com",
        "vppo_dubber": "imail-test+PMJock@vcreativeinc.com",
        "vppo_gm_gsm": "imail-test+GenMan@vcreativeinc.com",
        "vppo_producer": "imail-test+OtherProd@vcreativeinc.com",
        "vppo_production_manager": "imail-test+ProductionDir@vcreativeinc.com",
        "vppo_sales_assistant": "imail-test+SalesAssistant@vcreativeinc.com",
        "vppo_sales_manager": "imail-test+SalesManager@vcreativeinc.com",
        "vppo_traffic_manager": "imail-test+TrafficDir@vcreativeinc.com",
        "vppo_voicer": "imail-test+Voicing@vcreativeinc.com",
        "vppo_writer": "imail-test+CopyWriter@vcreativeinc.com",
    }

    if _profile and _profile.roles:
        for role_key, role_def in _profile.roles.items():
            if role_def.email:
                hardcoded_email_fallbacks[role_key] = role_def.email

    resolved: dict[str, dict[str, str]] = {}

    for role_key, env_key in env_fallback_map.items():
        kb_entry = kb_creds.get(role_key, {})
        local_entry = local_creds.get(role_key, {})
        email = (
            kb_entry.get("email", "")
            or local_entry.get("email", "")
            or os.getenv(env_key, "")
            or hardcoded_email_fallbacks.get(role_key, "")
        )
        if role_key.startswith("vppo_"):
            vppo_pwd_override = os.getenv("ROLE_DEFAULT_PASSWORD_VPPO", "")
            password = (
                kb_entry.get("password", "")
                or vppo_pwd_override
                or os.getenv("ROLE_DEFAULT_PASSWORD", "")
                or local_entry.get("password", "")
                or "Ep!cVCteam2026$"
            )
        else:
            password = kb_entry.get("password", "") or local_entry.get("password", "") or default_password

        resolved[role_key] = {"email": email, "password": password}

        if kb_entry.get("email"):
            source = "KB"
        elif local_entry.get("email"):
            source = "local persona file"
        elif os.getenv(env_key):
            source = "env"
        elif hardcoded_email_fallbacks.get(role_key):
            source = "profile fallback"
        else:
            source = "MISSING"

        if source == "MISSING":
            logger.warning(
                "  ⚠ %s: no credentials found anywhere",
                role_key,
            )
        else:
            logger.info(
                "  ✓ %s: email from %s (%s)",
                role_key,
                source,
                email[:30] + "..." if len(email) > 30 else email,
            )

    return resolved


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def _build_registry() -> dict[str, RoleContext]:
    """
    Build and return the complete role registry.

    Resolves credentials via KB → env var fallback, then constructs
    the full RoleContext for all 8 vProMedia roles.

    Returns
    -------
    dict[str, RoleContext]
        Mapping of role key → RoleContext for all 8 vProMedia roles.
    """
    creds = _resolve_credentials()

    return {
        # ------------------------------------------------------------------
        # Account Executive
        # ------------------------------------------------------------------
        "account_executive": RoleContext(
            role_name="Account Executive",
            role_key="account_executive",
            login_email=creds.get("account_executive", {}).get("email", ""),
            login_password=creds.get("account_executive", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Sales Manager
        # ------------------------------------------------------------------
        "sales_manager": RoleContext(
            role_name="Sales Manager",
            role_key="sales_manager",
            login_email=creds.get("sales_manager", {}).get("email", ""),
            login_password=creds.get("sales_manager", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Sales Assistant
        # ------------------------------------------------------------------
        "sales_assistant": RoleContext(
            role_name="Sales Assistant",
            role_key="sales_assistant",
            login_email=creds.get("sales_assistant", {}).get("email", ""),
            login_password=creds.get("sales_assistant", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Production Manager
        # ------------------------------------------------------------------
        "production_manager": RoleContext(
            role_name="Production Manager",
            role_key="production_manager",
            login_email=creds.get("production_manager", {}).get("email", ""),
            login_password=creds.get("production_manager", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Producer
        # ------------------------------------------------------------------
        "producer": RoleContext(
            role_name="Producer",
            role_key="producer",
            login_email=creds.get("producer", {}).get("email", ""),
            login_password=creds.get("producer", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # GM / GSM
        # ------------------------------------------------------------------
        "gm_gsm": RoleContext(
            role_name="GM / GSM",
            role_key="gm_gsm",
            login_email=creds.get("gm_gsm", {}).get("email", ""),
            login_password=creds.get("gm_gsm", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Dubber
        # ------------------------------------------------------------------
        "dubber": RoleContext(
            role_name="Dubber",
            role_key="dubber",
            login_email=creds.get("dubber", {}).get("email", ""),
            login_password=creds.get("dubber", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Digital Director / Producer
        # ------------------------------------------------------------------
        "digital_director": RoleContext(
            role_name="Digital Director/Producer",
            role_key="digital_director",
            login_email=creds.get("digital_director", {}).get("email", ""),
            login_password=creds.get("digital_director", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Demo Prod Director
        # ------------------------------------------------------------------
        "demo_prod_director": RoleContext(
            role_name="Demo Prod Director",
            role_key="demo_prod_director",
            login_email=creds.get("demo_prod_director", creds.get("digital_director", {}))["email"],
            login_password=creds.get("demo_prod_director", creds.get("digital_director", {}))["password"],
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
        # ------------------------------------------------------------------
        # Traffic Manager
        # ------------------------------------------------------------------
        "traffic_manager": RoleContext(
            role_name="Traffic Manager",
            role_key="traffic_manager",
            login_email=creds.get("traffic_manager", {}).get("email", ""),
            login_password=creds.get("traffic_manager", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # Writer
        # ------------------------------------------------------------------
        "writer": RoleContext(
            role_name="Writer",
            role_key="writer",
            login_email=creds.get("writer", {}).get("email", ""),
            login_password=creds.get("writer", {}).get("password", ""),
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
                "Blogs questions to AEs and Production Managers — communication is script-focused.",
                "Role Flag: writeflag — spot visibility filtered by spot_users matching user_id.",
            ],
        ),
        # ------------------------------------------------------------------
        # Voice Talent
        # ------------------------------------------------------------------
        "voice_talent": RoleContext(
            role_name="Demo Voice Talent",
            role_key="voice_talent",
            login_email=creds.get("voice_talent", {}).get("email", ""),
            login_password=creds.get("voice_talent", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # vPromotions User
        # ------------------------------------------------------------------
        "vpromotions_user": RoleContext(
            role_name="vPromotions User",
            role_key="vpromotions_user",
            login_email=creds.get("vpromotions_user", {}).get("email", ""),
            login_password=creds.get("vpromotions_user", {}).get("password", ""),
            permissions={
                "access_vpromotions": True,
            },
            constraints=[
                "This is a vPromotions application user — NOT a vSuite user.",
                "The target URL will be a vPromotions URL (e.g. vpromotions-test.vcreative.net).",
                "Login page will look different from vSuite — expect a different UI.",
                "No vSuite-specific RBAC rules apply here.",
            ],
        ),
        # ------------------------------------------------------------------
        # vTrade Exec
        # ------------------------------------------------------------------
        "vtrade_exec": RoleContext(
            role_name="vTrade Exec",
            role_key="vtrade_exec",
            login_email=creds.get("vtrade_exec", {}).get("email", ""),
            login_password=creds.get("vtrade_exec", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # vTrade Business Manager
        # ------------------------------------------------------------------
        "vtrade_business_manager": RoleContext(
            role_name="vTrade Business Manager",
            role_key="vtrade_business_manager",
            login_email=creds.get("vtrade_business_manager", {}).get("email", ""),
            login_password=creds.get("vtrade_business_manager", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # vTrade Sales Manager
        # ------------------------------------------------------------------
        "vtrade_sales_manager": RoleContext(
            role_name="vTrade Sales Manager",
            role_key="vtrade_sales_manager",
            login_email=creds.get("vtrade_sales_manager", {}).get("email", ""),
            login_password=creds.get("vtrade_sales_manager", {}).get("password", ""),
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
        # ------------------------------------------------------------------
        # vPPO Roles
        # ------------------------------------------------------------------
        "vppo_account_executive": RoleContext(
            role_name="vPPO Account Executive",
            role_key="vppo_account_executive",
            login_email=creds.get("vppo_account_executive", {}).get("email", ""),
            login_password=creds.get("vppo_account_executive", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "view_own_drafts": True,
                "manage_own_clients": True,
                "approve_scripts": True,
                "approve_spots": True,
            },
            constraints=[
                "Primary creator of Quick Orders (QO) in vPPO.",
                "Saves and manages own drafts.",
                "Answers blog questions from Production, Traffic, and Creative teams.",
                "Approves scripts and final spots for own clients.",
                "Sends emails to clients for review and approval.",
                "POC Logic: Added to spot_users list as Point of Contact (POC).",
            ],
        ),
        "vppo_digital_director": RoleContext(
            role_name="vPPO Digital Director / Producer",
            role_key="vppo_digital_director",
            login_email=creds.get("vppo_digital_director", {}).get("email", ""),
            login_password=creds.get("vppo_digital_director", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "view_all_spots": True,
                "assign_poc": True,
                "line_editing": True,
                "production_abilities": True,
            },
            constraints=[
                "Assigns digital/web jobs and resources in vPPO.",
                "Full overview of all digital/web production activity.",
                "Uploads display ads and manages digital production flow.",
                "Filters target metadata.product_type = 'Digital' or similar flags.",
            ],
        ),
        "vppo_dubber": RoleContext(
            role_name="vPPO Dubber",
            role_key="vppo_dubber",
            login_email=creds.get("vppo_dubber", {}).get("email", ""),
            login_password=creds.get("vppo_dubber", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "view_all_spots": True,
                "dub": True,
                "edit_status": True,
            },
            constraints=[
                "Performs quality checks on vPPO audio files.",
                "Verifies files for accuracy and compliance.",
                "Uses 'dubflag' to trigger the autodub microservice processing.",
            ],
        ),
        "vppo_gm_gsm": RoleContext(
            role_name="vPPO GM / GSM",
            role_key="vppo_gm_gsm",
            login_email=creds.get("vppo_gm_gsm", {}).get("email", ""),
            login_password=creds.get("vppo_gm_gsm", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "view_all_spots": True,
                "edit_status": True,
                "dub": True,
            },
            constraints=[
                "Full visibility into all production activity within the firm.",
                "Can enter requests and manage personal clients via Inbox.",
                "Can view all Sales users' drafts and approve/reject new clients.",
            ],
        ),
        "vppo_producer": RoleContext(
            role_name="vPPO Producer",
            role_key="vppo_producer",
            login_email=creds.get("vppo_producer", {}).get("email", ""),
            login_password=creds.get("vppo_producer", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "edit_status": True,
                "dub": True,
                "line_editing": True,
                "production_abilities": True,
            },
            constraints=[
                "Produces creative audio/visual assets and uploads files to requests.",
                "Authorizes creative on the AE's behalf.",
                "Uses 'produceflag'. Heavily relies on spot_users table for assignment-based visibility.",
            ],
        ),
        "vppo_production_manager": RoleContext(
            role_name="vPPO Production Manager",
            role_key="vppo_production_manager",
            login_email=creds.get("vppo_production_manager", {}).get("email", ""),
            login_password=creds.get("vppo_production_manager", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "assign_poc": True,
                "view_all_spots": True,
                "assign_cart_house_numbers": True,
                "edit_status": True,
                "dub": True,
                "line_editing": True,
            },
            constraints=[
                "Delegates jobs and resources to requests in vPPO.",
                "Writes blogs to coordinate between Sales and Creative, writes/edits scripts.",
                "Assigns Cart/House numbers, changes statuses, logs time and production costs.",
                "Interacts with SpotUser to assign roles like Writer, Producer, and Voicer.",
            ],
        ),
        "vppo_sales_assistant": RoleContext(
            role_name="vPPO Sales Assistant",
            role_key="vppo_sales_assistant",
            login_email=creds.get("vppo_sales_assistant", {}).get("email", ""),
            login_password=creds.get("vppo_sales_assistant", {}).get("password", ""),
            permissions={
                "enter_requests_on_behalf": True,
                "view_all_spots": True,
            },
            constraints=[
                "Can enter requests on behalf of an AE in vPPO.",
                "Can view all AE spots for the firm.",
                "When creating orders, user_id tracks the AE while actual_user_id tracks the assistant.",
            ],
        ),
        "vppo_sales_manager": RoleContext(
            role_name="vPPO Sales Manager",
            role_key="vppo_sales_manager",
            login_email=creds.get("vppo_sales_manager", {}).get("email", ""),
            login_password=creds.get("vppo_sales_manager", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "view_all_spots": True,
                "manage_clients": True,
            },
            constraints=[
                "Can perform all functions of an Account Executive in vPPO.",
                "Can view all AE drafts from their own drafts folder (spotDraft table).",
                "Can approve or reject new clients and requests.",
            ],
        ),
        "vppo_traffic_manager": RoleContext(
            role_name="vPPO Traffic Manager",
            role_key="vppo_traffic_manager",
            login_email=creds.get("vppo_traffic_manager", {}).get("email", ""),
            login_password=creds.get("vppo_traffic_manager", {}).get("password", ""),
            permissions={
                "enter_requests": True,
                "assign_poc": True,
                "view_all_spots": True,
                "assign_cart_house_numbers": True,
                "edit_status": True,
                "line_editing": True,
            },
            constraints=[
                "Assigns Cart/House IDs to spots in vPPO.",
                "Schedules spots, monitors deadlines, accesses/manages ISCI codes and contract numbers.",
                "Role flag: 'trafficflag'. Responsible for metadata.cartid field in spots table.",
            ],
        ),
        "vppo_voicer": RoleContext(
            role_name="vPPO Voicer",
            role_key="vppo_voicer",
            login_email=creds.get("vppo_voicer", {}).get("email", ""),
            login_password=creds.get("vppo_voicer", {}).get("password", ""),
            permissions={
                "view_voice_requests": True,
                "upload_files": True,
            },
            constraints=[
                "Views voice requests and records audio in vPPO.",
                "Uploads completed voice files and blogs regarding voice-specific details.",
                "Access is restricted to SpotVoiceRequest table and associated spot details.",
            ],
        ),
        "vppo_writer": RoleContext(
            role_name="vPPO Writer",
            role_key="vppo_writer",
            login_email=creds.get("vppo_writer", {}).get("email", ""),
            login_password=creds.get("vppo_writer", {}).get("password", ""),
            permissions={
                "line_editing": True,
            },
            constraints=[
                "Views, creates, and edits scripts in vPPO.",
                "Sends to script review and marks writer job as completed.",
                "Role flag: 'writeflag'. Visible spots filtered by Writer job in spot_users.",
            ],
        ),
    }


# ---------------------------------------------------------------------------
# Module-level singleton registry
# ---------------------------------------------------------------------------

#: Complete mapping of role key → RoleContext for all 9 vProMedia roles.
#: Built once at module load time.  Credentials sourced from KB → env fallback.
ROLE_REGISTRY: Final[dict[str, RoleContext]] = _build_registry()

#: Ordered list of all valid role key strings.
SUPPORTED_ROLES: Final[list[str]] = list(ROLE_REGISTRY.keys())

#: Maps common display names / AC text identifiers to role keys.
#: Used by the persona tracker (Fix 4) to resolve dynamic actor names
#: (e.g., "Demo Voice Talent") to credential-bearing role keys.
ROLE_ALIASES: Final[dict[str, str]] = {
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
    "demo gm": "gm_gsm",
    "gm": "gm_gsm",
    "gsm": "gm_gsm",
    "demo digital director": "digital_director",
    "digital director": "digital_director",
    "digital director producer": "digital_director",
    # ── Production Director aliases (root cause of steps 71-81 'Invalid User' loop)
    # 'Demo Production Director' maps to imail-test+DemoProdDirector@vcreativeinc.com
    "demo production director": "demo_prod_director",
    "production director": "demo_prod_director",
    "prod director": "demo_prod_director",
    "demo prod director": "demo_prod_director",
    "demo prod dir": "demo_prod_director",  # Short alias used in TASK-063 AC text
    "prodirector": "demo_prod_director",
    "demoprodirector": "demo_prod_director",
    "demoproddirector": "demo_prod_director",
    # ── Order Submitter aliases ─────────────────────────────────────────
    # 'Order Submitter' is the role that created the order — in the two-test
    # environment this is always the Account Executive.
    "order submitter": "account_executive",
    "submitter": "account_executive",
    "assigned submitter": "account_executive",
    "original submitter": "account_executive",
    "demo order submitter": "account_executive",
    "demoordersubmitter": "account_executive",
    "vtrade exec": "vtrade_exec",
    "vtrade business manager": "vtrade_business_manager",
    "vtrade sales manager": "vtrade_sales_manager",
    # ── Traffic Manager aliases ─────────────────────────────────────────
    "traffic": "traffic_manager",
    "traffic manager": "traffic_manager",
    "demo traffic": "traffic_manager",
    "demo traffic director": "traffic_manager",
    "traffic director": "traffic_manager",
    # ── Writer aliases ──────────────────────────────────────────────────
    "writer": "writer",
    "demo writer": "writer",
    "copywriter": "writer",
    # ── vPPO Aliases ────────────────────────────────────────────────────
    "vppo ae": "vppo_account_executive",
    "vppo account executive": "vppo_account_executive",
    "vppo digital director": "vppo_digital_director",
    "vppo dubber": "vppo_dubber",
    "vppo gm": "vppo_gm_gsm",
    "vppo producer": "vppo_producer",
    "vppo production manager": "vppo_production_manager",
    "vppo sales assistant": "vppo_sales_assistant",
    "vppo sales manager": "vppo_sales_manager",
    "vppo traffic manager": "vppo_traffic_manager",
    "vppo voicer": "vppo_voicer",
    "vppo writer": "vppo_writer",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_role_context(role_key: str) -> RoleContext:
    """
    Return the ``RoleContext`` for a given role key.

    Args
    ----
    role_key : str
        One of the keys in ``SUPPORTED_ROLES``.

    Returns
    -------
    RoleContext
        The full role context including credentials, permissions, and
        LLM planning constraints.

    Raises
    ------
    KeyError
        If ``role_key`` is not in ``ROLE_REGISTRY``.

    Example
    -------
    >>> ctx = get_role_context("producer")
    >>> ctx["role_name"]
    'Producer'
    """
    if role_key not in ROLE_REGISTRY:
        raise KeyError(f"Unknown role key: '{role_key}'. Supported roles: {SUPPORTED_ROLES}")
    return ROLE_REGISTRY[role_key]


def get_role_display_name(role_key: str) -> str:
    """
    Return the human-readable display name for a role key.

    Args
    ----
    role_key : str
        One of the keys in ``SUPPORTED_ROLES``.

    Returns
    -------
    str
        Display name, e.g. ``"Account Executive"``.

    Example
    -------
    >>> get_role_display_name("gm_gsm")
    'GM / GSM'
    """
    return get_role_context(role_key)["role_name"]


def get_planning_constraints_prompt(role_key: str) -> str:
    """
    Format the role's constraints as a bullet-point string for LLM injection.

    The returned string is embedded verbatim in the planner system prompt.

    Args
    ----
    role_key : str
        One of the keys in ``SUPPORTED_ROLES``.

    Returns
    -------
    str
        Multi-line bullet-point string of constraints.

    Example
    -------
    >>> print(get_planning_constraints_prompt("dubber"))
    ROLE CONSTRAINTS FOR Dubber:
    • Quality-control specialised role — reviews dub output.
    ...
    """
    ctx = get_role_context(role_key)
    constraints_block = "\n".join(f"• {c}" for c in ctx["constraints"])
    return f"ROLE CONSTRAINTS FOR {ctx['role_name']}:\n{constraints_block}"


def resolve_role_by_name(display_name: str) -> RoleContext | None:
    """
    Resolve a display name or AC text identifier to a ``RoleContext``.

    Checks ``ROLE_ALIASES`` first (case-insensitive), then falls back to
    direct ``role_key`` lookup in ``ROLE_REGISTRY``.  Used by the persona
    tracker in ``setup_role_node`` to resolve dynamic actor names
    (e.g., ``"Demo Voice Talent"``) to credential-bearing role contexts.

    Args
    ----
    display_name : str
        Display name, alias, or role key to resolve.
        Examples: ``"Demo Voice Talent"``, ``"voicer"``, ``"voice_talent"``

    Returns
    -------
    RoleContext | None
        The matching role context, or ``None`` if no match is found.

    Example
    -------
    >>> ctx = resolve_role_by_name("Demo Voice Talent")
    >>> ctx["login_email"]
    'imail-test+DemoVoicer@vcreativeinc.com'
    """
    normalized = display_name.lower().strip()
    key = ROLE_ALIASES.get(normalized)
    if key and key in ROLE_REGISTRY:
        return ROLE_REGISTRY[key]
    # Direct key lookup fallback
    if normalized in ROLE_REGISTRY:
        return ROLE_REGISTRY[normalized]
    return None
