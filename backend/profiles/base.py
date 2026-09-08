"""
vQA — AppProfile Base Types
=============================
Module: backend/profiles/base.py

Defines the ``AppProfile`` dataclass — the core plugin contract for
target application configuration.

An AppProfile encapsulates EVERYTHING vendor-specific about a target
application:
  - Authentication flow (selectors, JWT keys, credentials)
  - DOM synchronization (spinners, panels, root elements)
  - Domain knowledge (glossary, rules, few-shot examples)
  - Role definitions (RBAC permissions, constraints)
  - LLM prompt identity (how Claude "sees" the app)

Architecture Context
--------------------
Every module that previously hardcoded vSuite/vProMedia strings now
reads from the active AppProfile instead.  The profile is resolved
once at run start and threaded through the graph via VQAState.

The ``vsuite.py`` profile is the REFERENCE IMPLEMENTATION and
replicates 100% of the pre-modernization behavior.

Plugin Contract
---------------
Third-party profiles must subclass ``AppProfile`` or construct an
instance with all required fields.  The ``ProfileRegistry`` validates
completeness at registration time.

See Also
--------
  - ``backend/profiles/registry.py``  — singleton registry
  - ``backend/profiles/vsuite.py``    — reference vSuite profile
  - ``backend/engine/graph.py``       — reads profile for login
  - ``backend/engine/executor.py``    — reads profile for spinners
  - ``backend/engine/planner.py``     — reads profile for prompts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocatorStep:
    """
    One step in a multi-strategy locator fallback chain.

    Used by ``LoginFormSelectors`` to express "try get_by_role first,
    then fall back to get_by_placeholder" without hardcoding specific
    Playwright methods in the login node.

    Attributes
    ----------
    method : str
        Playwright locator method: ``"get_by_role"``, ``"get_by_placeholder"``,
        ``"get_by_label"``, ``"get_by_text"``, ``"css_selector"``.

    args : tuple[str, ...]
        Positional args for the method.
        e.g. ``("textbox",)`` for ``get_by_role("textbox", ...)``.

    kwargs : dict[str, str]
        Keyword args for the method.
        e.g. ``{"name": "Email"}`` for ``get_by_role("textbox", name="Email")``.

    Example
    -------
    >>> step = LocatorStep("get_by_role", ("textbox",), {"name": "Email"})
    >>> # Equivalent to: page.get_by_role("textbox", name="Email")
    """

    method: str
    args: tuple[str, ...] = ()
    kwargs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LoginFormSelectors:
    """
    Login form element locators with fallback chains.

    Each field is an ordered list of ``LocatorStep`` objects.
    The login node tries each step in order until one succeeds.

    Attributes
    ----------
    email_input : list[LocatorStep]
        Locator chain for the email/username input field.

    password_input : list[LocatorStep]
        Locator chain for the password input field.

    submit_button : list[LocatorStep]
        Locator chain for the login submit button.
        Multiple entries cover text variations across environments
        (e.g., "Log In" vs "Login" vs "Sign In").

    Example
    -------
    >>> sel = LoginFormSelectors(
    ...     email_input=[
    ...         LocatorStep("get_by_role", ("textbox",), {"name": "Email"}),
    ...         LocatorStep("get_by_placeholder", ("Email",)),
    ...     ],
    ...     password_input=[
    ...         LocatorStep("get_by_role", ("textbox",), {"name": "Password"}),
    ...         LocatorStep("get_by_placeholder", ("Password",)),
    ...     ],
    ...     submit_button=[
    ...         LocatorStep("get_by_role", ("button",), {"name": "Log In"}),
    ...         LocatorStep("get_by_role", ("button",), {"name": "Login"}),
    ...         LocatorStep("css_selector", ("button[type='submit']",)),
    ...     ],
    ... )
    """

    email_input: list[LocatorStep] = field(default_factory=list)
    password_input: list[LocatorStep] = field(default_factory=list)
    submit_button: list[LocatorStep] = field(default_factory=list)


@dataclass
class RoleDefinition:
    """
    Credential and permission definition for one user role.

    This replaces the hardcoded email/password entries in ``roles.py``
    and serves as the profile-level fallback when KB + env vars are not set.

    Attributes
    ----------
    display_name : str
        Human-readable role name.
        Example: ``"Account Executive"``

    email : str
        Default/fallback email for this role.
        Overridden by: env var → KB → Jira ticket credentials.

    email_env_var : str
        Environment variable name that overrides ``email``.
        Example: ``"ROLE_EMAIL_AE"``

    password_env_var : str
        Environment variable name for the role's password.
        Falls back to the profile's ``default_password_env``.

    permissions : dict[str, bool]
        RBAC permission flags used for violation detection.

    constraints : list[str]
        Plain-English constraint strings injected into the planner prompt.
    """

    display_name: str
    email: str = ""
    email_env_var: str = ""
    password_env_var: str = ""
    permissions: dict[str, bool] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Auth verification strategy
# ---------------------------------------------------------------------------

AuthVerificationStrategy = Literal[
    "jwt_localstorage",  # Check localStorage for a JWT key
    "cookie",  # Check document.cookie for a session cookie
    "url_redirect",  # Verify URL changed from login page
    "none",  # Skip auth verification
]


# ---------------------------------------------------------------------------
# AppProfile — core plugin contract
# ---------------------------------------------------------------------------


@dataclass
class AppProfile:
    """
    Plugin contract for target application configuration.

    An AppProfile is a complete, self-contained configuration bundle
    that tells vQA how to interact with a specific web application.
    It replaces ALL hardcoded vSuite/vProMedia configuration that was
    previously scattered across ``roles.py``, ``graph.py``,
    ``executor.py``, ``planner.py``, and ``prompts.py``.

    Creating a New Profile
    ----------------------
    1. Create ``backend/profiles/myapp.py``
    2. Instantiate ``AppProfile(name="myapp", ...)`` with all fields
    3. Call ``profile_registry.register(profile)`` in the module body
    4. The profile is now selectable via ``VQA_PROFILE=myapp`` env var
       or ``{"profile": "myapp"}`` in the ``/execute`` request body.

    Backward Compatibility
    ----------------------
    The ``vsuite`` profile is always registered and is the default.
    When no profile is specified, vQA behaves identically to the
    pre-modernization codebase.
    """

    # ── Identity ─────────────────────────────────────────────────────────
    name: str
    """Machine-readable profile key. Example: ``"vsuite"``, ``"salesforce"``."""

    display_name: str
    """Human-readable application name. Example: ``"vProMedia/vSuite 2.0"``."""

    description: str
    """Brief description injected into debug logs and health checks."""

    # ── Authentication ───────────────────────────────────────────────────
    login_url_path: str = "/login"
    """
    Path appended to ``target_url`` to reach the login page.
    Example: ``"/login"``, ``"/auth/signin"``, ``"/"``.
    """

    auth_verification: AuthVerificationStrategy = "jwt_localstorage"
    """How to verify successful authentication after login."""

    jwt_storage_key: str = ""
    """
    localStorage key name for the JWT token.
    Only used when ``auth_verification == "jwt_localstorage"``.
    Example: ``"vc2JWT"``, ``"authToken"``.
    """

    login_form_selectors: LoginFormSelectors = field(default_factory=LoginFormSelectors)
    """Ordered locator fallback chains for the login form elements."""

    # ── Roles ────────────────────────────────────────────────────────────
    roles: dict[str, RoleDefinition] = field(default_factory=dict)
    """
    Mapping of role_key → RoleDefinition.
    Example: ``{"account_executive": RoleDefinition(...), ...}``
    """

    default_password_env: str = "ROLE_DEFAULT_PASSWORD"
    """
    Env var name for the default password shared across all roles.
    The actual password is NEVER stored in this dataclass.
    """

    default_password_fallback: str = ""
    """
    Hardcoded fallback password (only for development/test environments).
    Loaded when neither env var nor SSM provides a password.
    """

    role_aliases: dict[str, str] = field(default_factory=dict)
    """
    Maps common display names to role keys.
    Example: ``{"demo voice talent": "voice_talent", ...}``
    """

    # ── DOM Synchronization ──────────────────────────────────────────────
    app_root_selectors: list[str] = field(default_factory=list)
    """
    CSS selectors to detect that the SPA has bootstrapped/hydrated.
    The login node tries each in order; first visible one confirms
    the app is ready. Example: ``["app-root", "[ng-version]"]``
    """

    spinner_selectors: list[str] = field(default_factory=list)
    """
    CSS selectors for loading indicators that must disappear before
    the agent acts. Example: ``[".p-datatable-loading-overlay", ...]``
    """

    detail_panel_selectors: list[str] = field(default_factory=list)
    """
    CSS selectors for detail/slideout panels. Used for idempotent
    click detection (don't re-click if panel is already open).
    Example: ``["app-spot-detail", ".slideout-panel.open"]``
    """

    # ── Domain Knowledge (LLM Prompt Injection) ──────────────────────────
    domain_glossary: str = ""
    """
    Mapping of human UI terms → component identifiers.
    Injected into the Stage 2 JSON Compiler prompt.
    Example: ``"'Spots Grid' = p-table\\n'Client Search' = p-autocomplete"``
    """

    framework_rules: str = ""
    """
    Framework-specific interaction rules (PrimeNG, Material, Ant Design).
    Injected into the planner system prompt.
    """

    workflow_rules: dict[str, str] = field(default_factory=dict)
    """
    Keyword-triggered rule blocks for the planner.
    Keys are rule category names, values are the rule text.
    Example: ``{"login": "LOGIN RULES:\\n...", "sort": "TABLE SORT RULES:\\n..."}``

    The planner's ``_select_rules()`` function matches AC step text
    against keywords in these rule names and injects matching rules.
    """

    workflow_rule_triggers: dict[str, list[str]] = field(default_factory=dict)
    """
    Maps rule category name → list of trigger keywords.
    Example: ``{"login": ["login", "sign in", "credentials"]}``
    """

    # ── Prompt Identity ──────────────────────────────────────────────────
    identity_prompt: str = "a web application"
    """
    Application identity string injected into the LLM system prompt.
    Example: ``"vProMedia/vSuite by executing Acceptance Criteria from a Jira ticket"``
    """

    system_boundary_rule: str = ""
    """
    System boundary instruction for the AC compiler — tells the LLM
    which actions are OUT of scope (e.g., Jira admin, Slack, email).
    """

    few_shot_examples: str = ""
    """
    App-specific planner examples injected into ``<few_shot_examples>``.
    Example: Action patterns for PrimeNG dropdowns, Angular autocompletes, etc.
    """
