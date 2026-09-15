"""
vQA — Pydantic API Schemas
============================
Module: backend/api/schemas.py

Defines the Pydantic request/response models for all FastAPI endpoints.
These models provide:

  1. **Input validation** — malformed requests are rejected with clear
     422 errors before hitting any business logic.
  2. **Serialisation** — response data is consistently structured.
  3. **OpenAPI documentation** — FastAPI auto-generates the /docs page
     from these model definitions.

Model Hierarchy
---------------
::

    Requests:
      ExecuteRequest        → POST /execute
      BatchExecuteRequest   → POST /execute-batch

    Responses:
      ExecuteResponse       → POST /execute
      BatchExecuteResponse  → POST /execute-batch
      StatusResponse        → GET /status/{run_id}
      BatchStatusResponse   → GET /batch-status/{batch_id}
      HealthResponse        → GET /health

    WebSocket messages:
      WSStepMessage         → per-action log event
      WSTerminalMessage     → completion/failure event

Dependencies
------------
  - ``pydantic`` — BaseModel, Field, field_validator
  - ``backend/engine/roles.py`` — SUPPORTED_ROLES for validation

See Also
--------
  - ``backend/api/routes.py`` — consumes these models
  - ``backend/engine/state.py`` — ExecutionStep mirrors WSStepMessage
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Supported roles (imported at validation time to avoid circular deps)
# ---------------------------------------------------------------------------

#: Valid role key strings for API validation.
#: Kept as a constant here to avoid importing roles.py at module level
#: (which would trigger env var reads during tests).
VALID_ROLES: list[str] = [
    "account_executive",
    "sales_manager",
    "sales_assistant",
    "production_manager",
    "producer",
    "gm_gsm",
    "dubber",
    "digital_director",
    "demo_prod_director",
    "vpromotions_user",
    "vtrade_exec",
    "vtrade_business_manager",
    "vtrade_sales_manager",
    "vppo_account_executive",
    "vppo_digital_director",
    "vppo_dubber",
    "vppo_gm_gsm",
    "vppo_producer",
    "vppo_production_manager",
    "vppo_sales_assistant",
    "vppo_sales_manager",
    "vppo_traffic_manager",
    "vppo_voicer",
    "vppo_writer",
]


# ---------------------------------------------------------------------------
# Product registry — lazy singleton (loaded once at first validation call)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_product_registry_cached():
    """Load products.yaml once and cache for the process lifetime.

    Returns None if the file does not exist (e.g. during early development
    before products.yaml is created), which skips cross-validation gracefully.
    """
    from pathlib import Path
    from backend.config.product_registry import load_product_registry, DEFAULT_REGISTRY_PATH

    registry_path = Path(DEFAULT_REGISTRY_PATH)
    if not registry_path.exists():
        return None
    try:
        return load_product_registry(path=registry_path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ExecuteRequest(BaseModel):
    """
    Request body for ``POST /execute`` — single ticket test execution.

    Example
    -------
    .. code-block:: json

        {
            "jira_ticket_id": "VC2-8967",
            "role": "account_executive",
            "target_url": "https://two-test.vcreative.net",
            "mode": "interactive"
        }
    """

    jira_ticket_id: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description=("Jira issue key to fetch and test against. Example: 'VC2-8967'"),
        examples=["VC2-8967"],
    )

    role: str = Field(
        ...,
        description=(
            "User role key to test as.  Must be one of the 8 supported "
            "vProMedia roles.  See VALID_ROLES for the complete list."
        ),
        examples=["account_executive", "producer"],
    )

    target_url: str = Field(
        default="",
        description=(
            "Base URL of the application under test. "
            "When not explicitly provided, auto-resolved from the product registry "
            "using the product's default environment URL. "
            "Falls back to https://two-test.vcreative.net if resolution fails."
        ),
        examples=["https://two-test.vcreative.net"],
    )

    mode: Literal["interactive", "headless"] = Field(
        default="interactive",
        description=(
            "'interactive' streams screenshots for live browser view. "
            "'headless' runs Playwright headless — fastest mode."
        ),
    )

    # Optional credential override — supplied by the user when the ticket
    # has partial credentials (only email or only password found).
    override_email: str = Field(
        default="",
        description="Override login email (for testing specific accounts).",
    )
    override_password: str = Field(
        default="",
        description="Override login password.",
    )

    # Pre-flight Ghost Login credentials — supplied by the UI when the ticket
    # contains a Ghost Login step. Bypasses the mid-run
    # GHOST_CREDENTIALS_REQUIRED WebSocket gate so the run proceeds without
    # operator intervention.
    ghost_admin_email: str = Field(
        default="",
        description=(
            "Admin email for Ghost Login pre-flight. When provided, the "
            "mid-run credential gate is skipped."
        ),
    )
    ghost_admin_password: str = Field(
        default="",
        description="Admin password for Ghost Login pre-flight.",
    )
    user_guidance: str = Field(
        default="",
        description=(
            "Optional human guidance injected into the planner prompt. "
            "Provided via the Triage Panel after a failed run to help the agent "
            "understand how to complete a specific step."
        ),
    )
    pre_parse_guidance: str = Field(
        default="",
        description=(
            "Optional context provided BEFORE the AC parser runs. "
            "Injected into the Stage 1 BDD Normalizer Bedrock prompt so the LLM "
            "generates more accurate, specific test steps. "
            "Example: 'This ticket tests Compact view. No column headers — use Sort By dropdown.'"
        ),
    )
    override_steps: list[str] = Field(
        default_factory=list,
        description=(
            "Pre-confirmed AC steps. When non-empty, the LLM AC parser is skipped "
            "and these steps are used verbatim. Use this after the /preview-steps "
            "endpoint returns parsed steps for human review and correction."
        ),
    )
    vision_mode: Literal["dom", "som_css", "som_coordinates"] = Field(
        default="dom",
        description=(
            "Controls the agent's observation strategy. "
            "'dom' (default): screenshot + accessibility tree + DOM text — fastest and cheapest. "
            "'som_css': annotated screenshot → box_id → CSS selector resolution. "
            "'som_coordinates': annotated screenshot → mark_id → pixel coordinate click — "
            "most resilient for complex PrimeNG UIs but slower/costlier due to vision model tokens. "
            "Auto-escalated to 'som_coordinates' if the agent fails repeatedly in 'dom' mode."
        ),
    )

    expect_login_failure: bool = Field(
        default=False,
        description=(
            "When True, the login_node navigates to the login page but does NOT "
            "authenticate. The browser is left on the blank login form so the AC "
            "steps can drive a failed login flow (wrong credentials, locked account, etc.). "
            "The agent should verify failure indicators (error toast, URL stays on /login, no JWT)."
        ),
    )

    profile: str = Field(
        default="",
        description=(
            "AppProfile name to use for this run. Empty = use VQA_PROFILE env var "
            "(defaults to 'vsuite'). Determines authentication flow, domain glossary, "
            "spinner selectors, and LLM prompt identity."
        ),
    )

    source_type: Literal["jira", "raw_text", "github", "auto"] = Field(
        default="jira",
        description=(
            "Test source type. 'jira' (default) fetches AC from Jira using "
            "jira_ticket_id. 'raw_text' uses raw_ac_text directly. "
            "'github' fetches AC from GitHub issues. "
            "'auto' auto-detects from the identifier format."
        ),
    )

    raw_ac_text: str = Field(
        default="",
        description=(
            "Raw acceptance criteria text (used when source_type='raw_text'). "
            "Bypasses Jira fetch and passes this text directly to the AC parser."
        ),
    )

    webhook_url: str = Field(
        default="",
        description=(
            "Per-run webhook URL for completion notifications. "
            "Overrides the global WEBHOOK_URL config setting. "
            "Leave empty to use the global default."
        ),
    )

    playwright_test_id: str | None = Field(
        default=None,
        description="ID of a static Playwright test to execute (used when execution_engine='static').",
    )

    execution_engine: Literal["ai", "static", "linear"] = Field(
        default="ai",
        description=(
            "'ai' (default) uses the autonomous LLM-driven agent. "
            "'static' executes a pre-written Playwright test from the library. "
            "'linear' uses the deterministic Generate→Validate→Execute→Analyze pipeline "
            "(TASK-105/TASK-106). Recommended for all new runs. No LLM in the execution "
            "hot-path — prevents amnesic loops and stagnation bugs."
        ),
    )

    tenant_id: str = Field(
        default="vpromedia",
        description=(
            "Tenant identifier for the linear pipeline's multi-tenant config resolution. "
            "Maps to tenants/{tenant_id}/vqa.config.json and selectors.json. "
            "Only used when execution_engine='linear'. Default: 'vpromedia'."
        ),
    )

    product: str = Field(
        default="vpromedia",
        description=(
            "Active product context for this test run. "
            "Must match a slug registered in backend/config/products.yaml. "
            "Defaults to 'vpromedia' for backwards compatibility with existing callers."
        ),
        examples=["vpromedia", "vtrade"],
    )

    # ── Pinned TestPlan (Lock B — deterministic replay) ───────────────
    # When set, ac_parser_node short-circuits at its very top and injects
    # this plan verbatim — no LLM call, no cache lookup, no re-parse.
    # Obtain a plan_id by calling POST /preview-steps with inline
    # acceptance_criteria.  Missing or expired ids raise 404/410 loudly
    # (never a silent fallback to re-parse).
    # plan_id and override_steps are mutually exclusive — supplying both
    # raises HTTP 400.
    plan_id: str | None = Field(
        default=None,
        description=(
            "Opaque id returned by POST /preview-steps.  When provided, the "
            "ac_parser_node is short-circuited and the pinned TestPlan is "
            "replayed verbatim — no LLM re-parse occurs.  "
            "Mutually exclusive with override_steps (HTTP 400 if both are set)."
        ),
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Ensure the role key is one of the supported user-facing roles."""
        if v not in VALID_ROLES:
            raise ValueError(f"Invalid role '{v}'. Must be one of: {VALID_ROLES}")
        return v

    @field_validator("jira_ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: str) -> str:
        """Ensure the ticket ID looks like a Jira issue key (e.g. VC2-8967)."""
        v = v.strip().upper()
        if not v:
            raise ValueError("jira_ticket_id cannot be empty")
        return v

    @model_validator(mode="after")
    def validate_role_product_match(self) -> ExecuteRequest:
        """Cross-check that self.role is assigned to self.product in products.yaml.

        AC-ERROR-3: Backend rejects a run request whose role does not belong to
        the requested product with a clear 400-level error.
        """
        registry = _load_product_registry_cached()
        if registry is None:
            return self
        registered = sorted(registry.slugs())
        try:
            product_ctx = registry.get(self.product)
        except KeyError:
            raise ValueError(
                f"Unknown product '{self.product}'. "
                f"Registered products: {registered}"
            )
        if not product_ctx.has_role(self.role):
            raise ValueError(
                f"Role '{self.role}' is not available for product '{self.product}'. "
                f"Available roles: {sorted(product_ctx.roles)}"
            )
        # T3-a AC-ERROR-1: Reject runs whose product KB root is missing from disk.
        # Runs BEFORE browser launch, Bedrock call, or S3 write (CQ-A1).
        if product_ctx.roles:
            from backend.config.product_registry import product_kb_available  # noqa: PLC0415
            if not product_kb_available(self.product, registry):
                raise ValueError(
                    f"product_kb_missing: The knowledge base directory for product "
                    f"'{self.product}' is not present on disk. "
                    f"Ensure 'knowledge/{self.product}/' (or the path declared in "
                    f"products.yaml knowledge_dir) exists before starting a run."
                )
        # Phase 4: auto-resolve target_url from product registry when not explicitly provided
        if not self.target_url:
            try:
                object.__setattr__(self, "target_url", product_ctx.resolve_target_url())
            except (KeyError, AttributeError):
                object.__setattr__(self, "target_url", "https://two-test.vcreative.net")
        return self


class ACQualityStep(BaseModel):
    """Quality breakdown for a single AC step."""
    step_text: str
    score: int
    warnings: list[str]

class ACQualityResultSchema(BaseModel):
    """Full quality assessment result."""
    overall_score: int
    quality_grade: str
    warnings: list[str]
    step_scores: list[ACQualityStep]

class PreviewStepsRequest(BaseModel):
    """
    Request body for ``POST /preview-steps`` — pinned-plan authoring.

    Accepts inline acceptance criteria text and persists a pinned TestPlan
    (Lock B) to disk.  The returned ``plan_id`` in ``PreviewStepsResponse``
    can be passed to ``POST /execute`` to replay the plan verbatim without
    re-invoking any LLM stage.

    The existing ``GET /preview-steps?ticket_id=...`` path is unchanged
    for callers that do not need pinned plans.

    Example
    -------
    .. code-block:: json

        {
            "acceptance_criteria": "Given the QO form is open\\nWhen the user..."
        }
    """

    acceptance_criteria: str = Field(
        ...,
        min_length=1,
        description=(
            "Raw acceptance criteria text to parse into a pinned TestPlan. "
            "This text is passed through the vQA AC parser (Stage 1 + Stage 2) "
            "and the resulting plan is persisted under an opaque plan_id. "
            "Must be non-empty."
        ),
    )


class PreviewStepsResponse(BaseModel):
    """
    Response for ``GET /preview-steps`` and ``POST /preview-steps``.

    Returns the Jira ticket summary and the LLM-parsed AC steps so the
    product team can review and correct them before triggering execution.

    For ``POST /preview-steps`` (pinned-plan authoring), ``plan_id`` is
    populated with the opaque id of the persisted pinned plan.  For the
    existing ``GET /preview-steps?ticket_id=...`` path, ``plan_id`` is
    ``None``.
    """

    ticket_id: str
    summary: str
    acceptance_criteria: str  # raw AC text from Jira
    steps: list[str]  # LLM-parsed steps (editable before execution)
    parse_quality: str | None = None  # "rejected", "poor", "fair", "good"
    parse_quality_reason: str | None = None  # explanation for rejection/low score
    ac_quality: ACQualityResultSchema | None = None  # FEAT-001 detailed feedback

    # ── Pinned TestPlan id (Lock B) ───────────────────────────────────
    # Populated by POST /preview-steps; None for GET /preview-steps.
    plan_id: str | None = Field(
        default=None,
        description=(
            "Opaque id of the persisted pinned TestPlan.  Set only when "
            "this response is from POST /preview-steps (pinned-plan authoring). "
            "Pass to POST /execute as plan_id to replay the plan verbatim."
        ),
    )
    detected_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Navigation paths found in the Jira AC text using '>' delimiter notation. "
            "Empty list for single-path or non-navigation tickets."
        ),
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        description=(
            "Vague terms, undefined values, or missing test data detected in the AC. "
            "Each entry is a human-readable warning string."
        ),
    )
    pending_jira_comment: str | None = Field(
        default=None,
        description=(
            "Comment vQA wants to post to Jira (rejection or test plan proposal). "
            "Only set during preview calls — the frontend must confirm before posting."
        ),
    )
    has_ghost_login: bool = Field(
        default=False,
        description=(
            "True when the parsed AC contains a GHOST_LOGIN step (or the AC quality "
            "gate flagged GHOST_CREDENTIALS_REQUIRED). The frontend uses this to "
            "render the admin-credentials gate on the Review screen."
        ),
    )
    has_ghost_description: bool = Field(
        default=False,
        description=(
            "True when the plain word 'ghost' appears in the Jira description. "
            "The frontend uses this to prompt for override email/password credentials "
            "(injected as override_email/override_password to skip the preflight auth check)."
        ),
    )


class CredentialCheckResponse(BaseModel):
    """
    Response from ``GET /ticket/{ticket_id}/credentials``.

    Returns the credential status so the frontend can decide whether
    to prompt the user for missing fields before starting a run.
    """

    ticket_id: str
    status: Literal["complete", "partial", "none"]
    email_found: bool
    password_found: bool
    # The email found in the ticket (empty if none)
    email: str
    # Human-readable message for the frontend to display
    message: str


class BatchTicketItem(BaseModel):
    """
    A single ticket entry within a batch execution request.

    Attributes
    ----------
    jira_ticket_id : str
        Jira issue key.
    role : str
        Role key to test as.
    """

    jira_ticket_id: str = Field(..., min_length=1, max_length=20)
    role: str = Field(...)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Ensure the role key is valid."""
        if v not in VALID_ROLES:
            raise ValueError(f"Invalid role '{v}'. Must be one of: {VALID_ROLES}")
        return v


class BatchExecuteRequest(BaseModel):
    """
    Request body for ``POST /execute-batch`` — CI/CD batch test execution.

    Always runs in headless mode.  Each ticket+role pair becomes an
    independent run with its own audit report.

    Example
    -------
    .. code-block:: json

        {
            "tickets": [
                {"jira_ticket_id": "VC2-8967", "role": "account_executive"},
                {"jira_ticket_id": "VC2-8968", "role": "producer"}
            ],
            "target_url": "https://staging.vcreative.net"
        }
    """

    tickets: list[BatchTicketItem] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="List of ticket+role pairs to test.  Max 20 per batch.",
    )

    target_url: str = Field(
        default="https://two-test.vcreative.net",
        description="Base URL of the application under test.",
    )


# ---------------------------------------------------------------------------
# Playwright Standard Library Models (TASK-060 / FEAT-052)
# ---------------------------------------------------------------------------

class PlaywrightRunRequest(BaseModel):
    """
    Request body for POST /playwright/run.
    """
    test_id: str = Field(..., description="ID of the test to run from playwright_index.json")
    env: Literal["prod", "test", "smoke", "qa"] = Field(default="test")
    user: str = Field(default="DemoSalesExec")
    browser: Literal["chromium", "firefox", "webkit"] = Field(default="chromium")

class PlaywrightSuiteRunRequest(BaseModel):
    """
    Request body for POST /playwright/run-all.
    """
    env: Literal["prod", "test", "smoke", "qa"] = Field(default="test")
    user: str = Field(default="DemoSalesExec")
    browser: Literal["chromium", "firefox", "webkit"] = Field(default="chromium")

class PlaywrightRunResponse(BaseModel):
    """
    Response body for POST /playwright/run.
    """
    run_id: str
    websocket_url: str
    novnc_url: str | None = Field(
        default=None,
        description="noVNC URL for live browser streaming (interactive mode only).",
    )


class AiReviewRunRequest(BaseModel):
    """
    Request body for POST /ai-review/run.
    Maps 1:1 to vReview ``npm run ai:review`` flags.
    """

    app: str = Field(default="platform", description="Review target: platform (vsuite) or vcapi")
    branch: str = Field(..., description="Target git branch (--branch)")
    commits: str = Field(default="", description="Optional comma-separated SHAs (--commits)")
    base: str = Field(default="Develop", description="Base branch (--base)")


class AiReviewRunResponse(BaseModel):
    """
    Response body for POST /ai-review/run.
    """

    run_id: str
    websocket_url: str


class AiReviewHistoryItem(BaseModel):
    """
    One saved AI Review run for the history list (no log or checklist rows).
    """

    review_id: str
    status: str
    app: str = "platform"
    branch: str
    base: str
    commits: str = ""
    pass_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    started_at: str
    finished_at: str | None = None


class AiReviewHistoryRow(BaseModel):
    """
    One checklist row stored with a saved review.
    """

    item: str
    status: str
    evidence: str = ""


class AiReviewHistoryDetail(AiReviewHistoryItem):
    """
    Full saved review: list fields plus checklist table and log.
    """

    rows: list[AiReviewHistoryRow] = Field(default_factory=list)
    log_text: str = ""


class MemoryWatchRunRequest(BaseModel):
    """Request body for POST /memory-watch/run."""

    flow: str = Field(default="qo-open-close-snapshot", description="Flow recipe id")
    env: str = Field(default="qa", description="Target vSuite env: local, qa, test, or smoke")
    cycles: int = Field(default=5, description="Open/close repeats after baseline")


class MemoryWatchRunResponse(BaseModel):
    """Response body for POST /memory-watch/run."""

    run_id: str
    websocket_url: str


class MemoryWatchSample(BaseModel):
    """One heap sample stored with a Memory Watch run."""

    cycle: int
    label: str = ""
    usedMb: float = 0
    deltaMb: float = 0
    gcRuns: int = 0
    status: str = "watching"


class MemoryWatchHistoryItem(BaseModel):
    """One saved Memory Watch run for the history list."""

    run_id: str
    status: str
    flow: str
    env: str
    cycles: int = 5
    verdict_pass: bool | None = None
    growth_mb: float | None = None
    started_at: str
    finished_at: str | None = None


class MemoryWatchHistoryDetail(MemoryWatchHistoryItem):
    """Full saved Memory Watch run: samples, checklist, log, artifacts."""

    samples: list[MemoryWatchSample] = Field(default_factory=list)
    rows: list[AiReviewHistoryRow] = Field(default_factory=list)
    log_text: str = ""
    report_dir: str = ""
    video_file: str = ""


class PlaywrightTestMetadata(BaseModel):
    """
    Schema for a single Playwright test entry.
    """
    id: str
    file: str
    jira_keys: list[str]
    description: str
    steps_count: int
    step_names: list[str]
    display_name: str | None = None

class PlaywrightStorageStatus(BaseModel):
    """
    Schema for storage state session validity.
    """
    env: str
    user: str
    exists: bool
    path: str
    last_modified: str | None = None

class PlaywrightStorageGenerateRequest(BaseModel):
    """
    Request body for POST /playwright/storage/generate.
    """
    envs: list[Literal["prod", "test", "smoke", "qa"]] = Field(default_factory=lambda: ["test"])
    force: bool = Field(default=False)

class PlaywrightMatchResponse(BaseModel):
    """
    Response body for GET /playwright/match/{ticket_id}.
    """
    matched: bool
    tests: list[PlaywrightTestMetadata]


class PlaywrightSuiteRunResponse(BaseModel):
    """
    Response body for POST /playwright/run-all.
    """
    suite_run_id: str
    status: Literal["running"]
    started_at: str


class NightlyRunResponse(BaseModel):
    """
    Response body for POST /playwright/nightly.
    Returns 202 Accepted immediately; poll /run-all/{suite_run_id}/report for results.
    """
    suite_run_id: str
    status: str = "started"
    message: str = "Nightly suite dispatched"


class PlaywrightSuiteResult(BaseModel):
    """
    Result schema for a single test inside a parallel suite run.
    """
    test_id: str
    name: str
    status: Literal["PASS", "FAIL", "PENDING", "RUNNING"]
    duration_ms: float
    error_snippet: str | None = None


class FailureDigestEntry(BaseModel):
    """
    Schema for a consolidated failure digest entry.
    """
    test_id: str
    name: str
    error_summary: str


class PlaywrightSuiteReportResponse(BaseModel):
    """
    Response body for GET /playwright/run-all/{suite_run_id}/report.
    """
    suite_run_id: str
    status: Literal["running", "completed", "failed"]
    started_at: str
    completed_at: str | None = None
    total: int
    passed: int
    failed: int
    results: list[PlaywrightSuiteResult]
    outcome: Literal["PASS", "FAIL"] | None = None
    fail_reason: str | None = None
    failure_digest: list[FailureDigestEntry] | None = None


class PlaywrightGroupRunRequest(BaseModel):
    """
    Request body for POST /playwright/run-group.
    """
    test_ids: list[str] = Field(..., min_length=1, max_length=50, description="Ordered list of test IDs to run sequentially")
    env: Literal["prod", "test", "smoke", "qa"] = Field(default="test")
    user: str = Field(default="DemoSalesExec")
    browser: Literal["chromium", "firefox", "webkit"] = Field(default="chromium")


class PlaywrightHealPromptRequest(BaseModel):
    """
    Request body for POST /playwright/heal-prompt.
    """
    run_id: str


class PlaywrightHealPromptResponse(BaseModel):
    """
    Response body for POST /playwright/heal-prompt.
    """
    prompt: str


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ExecuteResponse(BaseModel):
    """
    Response for ``POST /execute``.

    Returned immediately after the run is queued.  The client should
    connect to ``stream_url`` (WebSocket) for real-time log updates,
    or poll ``GET /status/{run_id}``.

    Attributes
    ----------
    run_id : str
        Internal unique identifier (used for WS routing and S3 paths).
    run_label : str
        Human-readable label, e.g. "QA-280 · Account Executive · Apr 2 2:44 PM".
    status : str
        Initial status — always "running" on success.
    stream_url : str
        WebSocket URL for real-time log streaming.
    novnc_url : str | None
        noVNC URL for live browser view (interactive mode only).
    """

    run_id: str = Field(..., description="Internal run identifier (UUID-based).")
    run_label: str = Field(default="", description="Human-readable run label.")
    status: str = Field(default="running", description="Initial run status.")
    stream_url: str = Field(..., description="WebSocket URL: ws://host/ws/{run_id}")
    novnc_url: str | None = Field(
        default=None,
        description="noVNC URL for live browser (interactive mode only).",
    )


class BatchRunItem(BaseModel):
    """Status of a single run within a batch."""

    run_id: str
    jira_ticket_id: str
    role: str
    status: str = "queued"


class BatchExecuteResponse(BaseModel):
    """
    Response for ``POST /execute-batch``.

    Attributes
    ----------
    batch_id : str
        Unique identifier for the batch.
    total_tickets : int
        Number of ticket+role pairs in the batch.
    runs : list[BatchRunItem]
        Individual run statuses.
    """

    batch_id: str
    total_tickets: int
    runs: list[BatchRunItem]


class ArtifactsInfo(BaseModel):
    """Artifact URLs from a completed run."""

    video_url: str = Field(default="", description="S3 URL of the .webm session recording.")
    report_url: str = Field(default="", description="S3 URL of the HTML audit report.")
    screenshots: list[str] = Field(default_factory=list, description="S3 URLs of all step screenshots.")


class StatusResponse(BaseModel):
    """
    Response for ``GET /status/{run_id}``.

    Provides the current run status, progress, and artifact URLs
    (once the run completes).

    Attributes
    ----------
    run_id : str
        The run identifier.
    status : str
        One of: "queued", "running", "completed", "failed".
    jira_ticket_id : str
        The Jira ticket being tested.
    role : str
        The role being tested.
    duration_ms : int
        Total run duration in milliseconds (0 if still running).
    ac_steps_total : int
        Total number of AC steps.
    ac_steps_completed : int
        Number of AC steps successfully validated.
    browser_actions : int
        Total number of browser actions taken.
    bugs_found : int
        Number of bugs detected.
    artifacts : ArtifactsInfo
        Artifact URLs (populated after completion).
    novnc_url : str | None
        noVNC URL for live browser view (interactive mode only).
    """

    run_id: str
    status: str
    jira_ticket_id: str = ""
    role: str = ""
    duration_ms: int = 0
    ac_steps_total: int = 0
    ac_steps_completed: int = 0
    browser_actions: int = 0
    bugs_found: int = 0
    artifacts: ArtifactsInfo = Field(default_factory=ArtifactsInfo)
    novnc_url: str | None = Field(
        default=None,
        description="noVNC URL for live browser (interactive mode only).",
    )
    run_metrics: dict = Field(default_factory=dict, description="Per-run LLM usage metrics")
    kb_update_proposals: list[dict] = Field(
        default_factory=list,
        description="Auto-proposed KB updates from proven patterns",
    )
    # FAIR Guardrail (TASK-096): True when ac_parser_node is blocked waiting
    # for operator guidance or approval on a FAIR-graded ticket.
    awaiting_pre_parse_guidance: bool = Field(
        default=False,
        description=(
            "True when the run is paused for operator guidance on a FAIR-quality "
            "Jira ticket before AC parsing begins. The UI should show the "
            "pre-parse guidance panel."
        ),
    )


class KBProposalItem(BaseModel):
    """A single KB update proposal from cross-run pattern learning."""

    situation: str = Field(description="What was being attempted")
    strategy: str = Field(description="The proven locator strategy")
    success_count: int = Field(description="Number of successful uses")
    proposed_kb_entry: str = Field(description="Proposed KB markdown entry")


class KBProposalsResponse(BaseModel):
    """Response for ``GET /kb-proposals``."""

    total: int = Field(description="Total number of proposals")
    proposals: list[KBProposalItem] = Field(default_factory=list)


class RunHistoryItem(BaseModel):
    """A single run in the history."""

    run_id: str = ""
    ticket_id: str = ""
    role: str = ""
    status: str = ""
    duration_ms: int = 0
    ac_total: int = 0
    ac_passed: int = 0
    cost_usd: float = 0.0
    report_url: str = ""
    video_url: str = ""
    profile: str = "vsuite"
    created_at: str = ""


class RunHistoryResponse(BaseModel):
    """Response for ``GET /runs/history``."""

    total: int = Field(description="Total runs matching the query")
    runs: list[RunHistoryItem] = Field(default_factory=list)


class TopTicket(BaseModel):
    """Top ticket by run count."""

    ticket_id: str = ""
    runs: int = 0
    passes: int = 0


class RunAnalyticsResponse(BaseModel):
    """Response for ``GET /runs/analytics``."""

    period_days: int = 30
    total_runs: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    total_cost_usd: float = 0.0
    avg_cost_usd: float = 0.0
    avg_duration_ms: int = 0
    total_ac_steps: int = 0
    total_ac_passed: int = 0
    top_tickets: list[TopTicket] = Field(default_factory=list)


class BatchStatusResponse(BaseModel):
    """Response for ``GET /batch-status/{batch_id}``."""

    batch_id: str
    status: str  # "running", "completed", "failed"
    total_tickets: int = 0
    completed_tickets: int = 0
    failed_tickets: int = 0
    runs: list[StatusResponse] = Field(default_factory=list)
    report_url: str = ""


# ---------------------------------------------------------------------------
# Test Suite schemas (Phase 7)
# ---------------------------------------------------------------------------


class SuiteTicketItem(BaseModel):
    """A single ticket in a test suite."""

    jira_ticket_id: str = Field(..., description="Jira ticket key (e.g. QA-280)")
    role: str = Field(default="account_executive", description="User role to test as")


class SuiteCreate(BaseModel):
    """Request body for ``POST /suites``."""

    name: str = Field(..., min_length=1, max_length=100, description="Unique suite name")
    description: str = Field(default="", max_length=500)
    tickets: list[SuiteTicketItem] = Field(..., min_length=1, description="Tickets in this suite")
    schedule_cron: str = Field(
        default="",
        description="Optional cron expression for recurring runs (e.g. '0 6 * * 1-5')",
    )


class SuiteUpdate(BaseModel):
    """Request body for ``PUT /suites/{suite_id}``."""

    name: str | None = None
    description: str | None = None
    tickets: list[SuiteTicketItem] | None = None
    schedule_cron: str | None = None
    enabled: bool | None = None


class SuiteResponse(BaseModel):
    """Response for a single test suite."""

    id: str = ""
    name: str = ""
    description: str = ""
    tickets: list[SuiteTicketItem] = Field(default_factory=list)
    schedule_cron: str = ""
    enabled: bool = True
    last_run_id: str = ""
    last_run_at: str = ""
    last_status: str = ""
    ticket_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class SuiteListResponse(BaseModel):
    """Response for ``GET /suites``."""

    total: int = 0
    suites: list[SuiteResponse] = Field(default_factory=list)


class HealthCheck(BaseModel):
    """
    Response for ``GET /health`` and ``GET /health/ready``.

    Attributes
    ----------
    status : str
        "ok" if all checks pass.
    mode : str
        Current execution mode.
    version : str
        vQA version string.
    build_number : str
        The deployment build number (TASK-117).
    checks : dict
        Sub-check results: bedrock, s3, jira.
    uptime_seconds : float
        Seconds since the process started.
    active_runs : int
        Number of runs currently in progress.
    total_runs_completed : int
        Total runs completed since boot.
    """

    status: str = "ok"
    mode: str = "interactive"
    version: str = "1.0.0"
    build_number: str = "dev"
    checks: dict = Field(default_factory=dict)
    uptime_seconds: float = Field(default=0.0, description="Seconds since process started")
    active_runs: int = Field(default=0, description="Currently running executions")
    total_runs_completed: int = Field(default=0, description="Total completed since boot")


# ---------------------------------------------------------------------------
# WebSocket message models
# ---------------------------------------------------------------------------


class WSStepMessage(BaseModel):
    """
    WebSocket message sent after each browser action.

    Mirrors the ``ExecutionStep`` fields relevant for real-time display.
    """

    type: str = "step"
    step_index: int
    timestamp: str
    action_type: str
    locator: str = ""
    success: bool
    screenshot_url: str = ""
    llm_reasoning: str = ""


class WSScreenshotMessage(BaseModel):
    """
    WebSocket message sent after the planner captures a screenshot.

    Carries the base64-encoded PNG so the frontend can display
    a live view without noVNC or any platform-specific display server.
    Works on macOS, Linux, Windows, and Docker.
    """

    type: str = "screenshot"
    run_id: str
    step_index: int = 0
    screenshot_b64: str  # base64-encoded PNG, WITHOUT data URI prefix
    ac_step: int = 0  # which AC step is currently running
    ac_total: int = 0


class WSThinkingMessage(BaseModel):
    """
    WebSocket message sent immediately before an action executes.

    Carries the LLM's current reasoning so the frontend can show a
    live "Agent Thinking..." strip with typewriter animation.
    Cleared when the next WSStepMessage arrives.
    """

    type: str = "thinking"
    run_id: str
    text: str  # the llm_reasoning text
    ac_step: int = 0
    ac_total: int = 0


class WSTerminalLogMessage(BaseModel):
    """
    WebSocket message for real-time terminal output from static tests.
    """

    type: str = "terminal_log"
    run_id: str
    line: str
    stream: Literal["stdout", "stderr"] = "stdout"


class WSTerminalMessage(BaseModel):
    """
    WebSocket message sent when a run completes or fails.

    The client should close the WebSocket connection after receiving this.
    """

    type: str  # "completed" or "failed"
    run_id: str
    report_url: str = ""
    video_url: str = ""
    error: str = ""
    # Result counts so the frontend can show true pass/fail,
    # not just whether the graph ran to completion.
    ac_steps_passed: int = 0
    ac_steps_total: int = 0
    bugs_found: int = 0


class WSTriageMessage(BaseModel):
    """
    WebSocket message sent after a FAILED run carrying the LLM failure analysis.

    Sent BEFORE WSTerminalMessage so the frontend can show the triage
    panel alongside (or instead of) the terminal card.
    """

    type: str = "triage"  # always "triage"
    run_id: str
    overall: str  # "product_bug" | "agent_issue" | "mixed" | "unknown"
    summary: str  # executive summary for the product team
    steps: list[dict]  # per-step classification list
    jira_comment: str  # pre-formatted Jira wiki-markup (for manual post)


class WSHumanTakeoverMessage(BaseModel):
    """
    WebSocket message broadcast when the agent is stuck and needs human help.

    On receipt, the frontend switches the screenshot panel to interactive
    (clickable) mode and shows the takeover UI.
    """

    type: str = "human_takeover"  # always "human_takeover"
    run_id: str
    ac_step: str  # The AC step text the agent is stuck on
    ac_step_index: int  # 0-based AC step index
    error_message: str  # Last error from the executor
    novnc_url: str | None = None  # Optional dynamic noVNC URL


class WSHitlScreenshotMessage(BaseModel):
    """
    WebSocket message for real-time HITL screencast frames (MJPEG-over-WS).
    """

    type: str = "hitl_screenshot_update"
    run_id: str
    data: str  # base64-encoded JPEG


class WSHitlActionRecordedMessage(BaseModel):
    """
    WebSocket message sent when a human action is echoed (real-time).
    """

    type: str = "hitl_action_recorded"
    run_id: str
    action: dict  # The captured action data


class WSHitlDialogMessage(BaseModel):
    """
    WebSocket message for intercepted browser dialogs (alert/confirm/prompt).
    """

    type: str = "hitl_dialog_opened"
    run_id: str
    message: str
    default_value: str = ""
    dialog_type: str  # "alert", "confirm", "prompt"


class WSAcStep(BaseModel):
    """
    A single AC step with its current execution status.

    Embedded in WSAcProgressMessage to provide the Copilot sidebar
    with a full, real-time view of all acceptance criteria steps.
    """

    index: int  # 0-based step index
    text: str  # AC step description
    status: Literal[
        "pending",
        "in_progress",
        "passed",
        "failed",
        "skipped",
        "awaiting_human",
    ] = "pending"
    error: str = ""  # populated on "failed" / "awaiting_human"
    human_selector: str = ""  # populated after a successful HITL click capture


class WSAcProgressMessage(BaseModel):
    """
    WebSocket message broadcast whenever any AC step status changes.

    Carries the FULL step list — the frontend replaces its entire state
    on each receipt rather than applying diffs.  Broadcast on every
    astream loop tick where ac_step_index or ac_steps_completed changes.
    """

    type: str = "ac_progress"
    run_id: str
    steps: list[WSAcStep]


class WSCopilotReadyMessage(BaseModel):
    """
    WebSocket message sent when the agent is stuck and the Copilot's
    'Takeover & Resume' panel should appear.

    Replaces the legacy WSHumanTakeoverMessage for the Copilot sidebar.
    The headed browser window is already open on the user's desktop;
    this message tells the UI to surface the Resume button.
    """

    type: str = "copilot_ready"  # always "copilot_ready"
    run_id: str
    ac_step_index: int  # 0-based index of the stuck step
    ac_step_text: str  # AC step text, shown in the sidebar
    error_message: str  # Last executor error — context for the human
    instructions: str = (
        "The agent is stuck. Take control of the headed browser window "
        "on your screen, complete this step manually, then click "
        "'Resume Agent' in the sidebar."
    )


class WSPreParseGuidanceMessage(BaseModel):
    """
    WebSocket message broadcast when ac_parser_node detects a FAIR-grade
    ticket and pauses to request operator guidance before Stage 1 BDD
    normalization.

    On receipt, the frontend should display the Pre-Parse Guidance panel
    (a modal/sidebar with the quality warnings and a text area for the
    operator to provide context).  The operator can either:

      1. Submit guidance text → POST /run/{run_id}/resume with
         pre_parse_guidance="..." (text injected into Stage 1 BDD normalizer)
      2. Click "Proceed Anyway" → POST /run/{run_id}/resume with
         pre_parse_guidance_approved=True (bypass logged at INFO)

    FAIR Guardrail — TASK-096 / FEAT-077
    """

    type: str = "pre_parse_guidance_required"  # always "pre_parse_guidance_required"
    run_id: str
    warnings: list[str]  # FAIR-grade deficiency descriptions from score_ac_quality()
    quality_grade: str  # always "fair" when this message is sent
    overall_score: int  # 0-10 overall quality score from ACQualityResult
    instructions: str = (
        "The ticket's Acceptance Criteria scored FAIR quality. "
        "Providing guidance will help the AI parse more accurate test steps. "
        "You may also proceed without guidance."
    )


class InteractRequest(BaseModel):
    """
    Body for ``POST /runs/{run_id}/interact``.

    Injects a single input action into the live Playwright page
    while the run is paused for human takeover.

    Actions
    -------
    click       Requires x_pct and y_pct (0.0–1.0, relative to viewport).
    type        Requires text. Types character-by-character into focused element.
    key         Requires key (e.g. "Enter", "Tab", "Escape").
    scroll      Requires direction ("up" | "down").
    """

    action: Literal["click", "type", "key", "scroll"]
    x_pct: float | None = Field(None, ge=0.0, le=1.0, description="X fraction of viewport width (click only)")
    y_pct: float | None = Field(None, ge=0.0, le=1.0, description="Y fraction of viewport height (click only)")
    text: str | None = Field(None, description="Text to type (type action only)")
    key: str | None = Field(None, description="Key to press, e.g. 'Enter' (key action only)")
    direction: Literal["up", "down"] | None = Field(None, description="Scroll direction (scroll action only)")


class InteractResponse(BaseModel):
    """
    Response from ``POST /runs/{run_id}/interact``.

    Returns a fresh screenshot after the action so the frontend can
    update the interactive view immediately.
    """

    ok: bool
    screenshot_b64: str = ""  # base64-encoded PNG of the current page
    viewport_width: int = 1280
    viewport_height: int = 720
    error: str = ""


class HumanTakeoverDoneRequest(BaseModel):
    """
    Body for ``POST /runs/{run_id}/human-takeover/done``.

    The frontend sends this when the user clicks "Done" or "Skip".
    """

    explanation: str = Field(
        default="",
        max_length=500,
        description=(
            "Optional description of what the user did to complete the step. "
            "Written to long_term_memory so the agent learns from it."
        ),
    )
    skip: bool = Field(
        default=False,
        description="If True, skip this AC step (mark SKIPPED) rather than retrying.",
    )


class HitlDialogResponseRequest(BaseModel):
    """
    Body for ``POST /runs/{run_id}/human-takeover/dialog``.

    The frontend sends this when the user responds to an intercepted
    browser dialog (alert/confirm/prompt).
    """

    accept: bool = Field(default=True, description="True to click OK/Accept, False for Cancel/Dismiss.")
    prompt_text: str = Field(default="", description="The text to enter for 'prompt' type dialogs.")


class ResumeRequest(BaseModel):
    """
    Body for ``POST /run/{run_id}/resume``.

    Allows injecting updated AC steps before resuming execution, or
    providing guidance / approval for the FAIR-quality guardrail.
    """

    override_steps: list[str] | None = Field(
        default=None,
        description="Optional updated AC steps to inject into the run state.",
    )
    # FAIR Guardrail (TASK-096)
    pre_parse_guidance: str | None = Field(
        default=None,
        description=(
            "Operator guidance text to inject into the Stage 1 BDD Normalizer "
            "before AC parsing runs. Only consumed when the run is paused on a "
            "FAIR-grade ticket (awaiting_pre_parse_guidance=True)."
        ),
    )
    pre_parse_guidance_approved: bool | None = Field(
        default=None,
        description=(
            "When True, the operator has clicked 'Proceed Anyway' to bypass the "
            "FAIR guardrail without providing additional guidance. The bypass is "
            "logged at INFO level and does NOT change the quality_grade in the report."
        ),
    )


class TeachRequest(BaseModel):
    """
    Payload for ``POST /runs/{run_id}/teach`` (Pause and Teach HITL).

    The human provides the exact selector, action, optional fill value,
    and a description that is written to the KB via RAG for future runs.
    """

    selector: str = Field(
        ...,
        description=(
            "CSS selector or XPath for the target element. "
            "E.g. 'th.po-col-clientCol' or '#submit-order-btn' or "
            "'//button[@aria-label=\"Save\"]'."
        ),
    )
    action: str = Field(
        ...,
        description="Action to perform: 'click', 'fill', or 'navigate'.",
    )
    value: str = Field(
        default="",
        description=(
            "For 'fill': the text to type into the element. For 'navigate': the full URL. Ignored for 'click'."
        ),
    )
    description: str = Field(
        ...,
        description=(
            "Human explanation of what this action does and why. "
            "Written to human_guidance.md and selector_registry.json "
            "so the agent retrieves it via RAG on future runs."
        ),
    )
    ac_step: str = Field(
        default="",
        description=("The AC step this action satisfies. Used as the KB entry heading in human_guidance.md."),
    )


class TeachResponse(BaseModel):
    """Response from ``POST /runs/{run_id}/teach``."""

    ok: bool
    screenshot_b64: str = ""  # Fresh page screenshot after the action
    error: str = ""  # Non-empty if action or KB write failed
    kb_written: bool = False  # True if both registry + guidance.md were updated


class CaptureClickRequest(BaseModel):
    """
    Payload for ``POST /runs/{run_id}/teach/capture-click``.

    The frontend sends (x_pct, y_pct) from the TakeoverPanel screenshot click
    event. The backend identifies the element at those coordinates and returns
    the auto-generated selector — zero manual CSS typing required.
    """

    x_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Horizontal click position as a fraction of screenshot width (0.0–1.0).",
    )
    y_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Vertical click position as a fraction of screenshot height (0.0–1.0).",
    )


class CaptureClickResponse(BaseModel):
    """
    Response from ``POST /runs/{run_id}/teach/capture-click``.

    On success, ``ok=True`` and the frontend receives everything it needs to
    show the "Captured: <selector>" badge and pre-fill the teach form.

    On failure (nothing found at coordinates, page closed, etc.),
    ``ok=False`` and ``error`` contains a human-readable message.
    """

    ok: bool

    # The generated CSS selector — ready to pass directly to /teach
    selector: str = ""

    # Human-readable label for display: "th.po-col-clientCol (th) — 'CLIENT'"
    element_label: str = ""

    # Fresh screenshot WITH the green highlight overlay visible
    screenshot_b64: str = ""

    # Raw element metadata for the UI (optional — for debugging/display)
    tag: str = ""  # HTML tag (e.g. "button", "th", "p-select")
    role: str = ""  # ARIA role or tag
    text: str = ""  # Visible text / aria-label (truncated)
    match_count: int = 1  # How many elements match the selector (1 = unique)

    error: str = ""


# ---------------------------------------------------------------------------
# AC Sync schemas (AC Confirmation Gate)
# ---------------------------------------------------------------------------


class SyncACRequest(BaseModel):
    """
    Request body for ``POST /ticket/{ticket_id}/sync-ac``.

    Carries the user-added acceptance criteria steps that should be
    appended to the Jira ticket's AC field.

    Attributes
    ----------
    added_steps : list[str]
        Only the NEW user-added steps (not the LLM-parsed ones).
        These are appended to the Jira AC field.
    original_ac_text : str
        The raw AC text from Jira at the time of preview — used
        for display in the sync confirmation dialog.
    """

    added_steps: list[str] = Field(
        ...,
        min_length=1,
        description="The new user-added AC steps to append to the Jira ticket.",
    )
    original_ac_text: str = Field(
        default="",
        description=(
            "Original raw AC from the Jira ticket at preview time. "
            "Used by the frontend confirmation dialog to show before/after."
        ),
    )


class SyncACResponse(BaseModel):
    """
    Response from ``POST /ticket/{ticket_id}/sync-ac``.

    Reports whether the Jira update succeeded and returns the
    final merged AC text.
    """

    ticket_id: str
    synced: bool
    added_count: int
    new_ac_text: str = Field(
        default="",
        description="The full AC text now on the Jira card (existing + appended).",
    )
    comment_posted: bool = Field(
        default=False,
        description="Whether the audit comment was successfully posted.",
    )
    error: str = Field(
        default="",
        description="Error message if the sync failed.",
    )


# ---------------------------------------------------------------------------
# Persona HITL credential schemas (TASK-063 Phase 4)
# ---------------------------------------------------------------------------


class PersonaCredentialsRequest(BaseModel):
    """
    Request body for ``POST /runs/{run_id}/persona-credentials``.

    Sent by the frontend when the operator provides credentials for an
    unrecognised persona during a mid-test persona switch.

    Security notes
    --------------
    - ``password`` is NEVER stored to disk and is scrubbed from logs
    - Credentials are stored ephemerally (in-memory only) in
      ``persona_switch_node._persona_creds`` and discarded on run completion

    Attributes
    ----------
    persona_name : str
        The raw persona name string as emitted in the
        ``HITL_PERSONA_CREDENTIALS_REQUIRED`` WebSocket event.
    email : str
        Login email for the unrecognised persona.
    password : str
        Login password.  Never echoed in the response.
    """

    persona_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="The persona name string as broadcast in HITL_PERSONA_CREDENTIALS_REQUIRED.",
    )
    email: str = Field(
        ...,
        min_length=1,
        max_length=254,
        description="Login email for the unrecognised persona.",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Login password.  Never stored to disk or echoed in the response.",
    )


class PersonaCredentialsResponse(BaseModel):
    """
    Response from ``POST /runs/{run_id}/persona-credentials``.

    Deliberately omits ``password`` — credentials are never echoed back.

    Attributes
    ----------
    ok : bool
        True if credentials were stored and the waiting event was unblocked.
    message : str
        Optional human-readable status or error message.
    """

    ok: bool
    message: str = Field(default="", description="Optional status or error detail.")


class WSPersonaCredentialsMessage(BaseModel):
    """
    WebSocket message broadcast by ``persona_switch_node`` when an unknown
    persona is encountered and operator credentials are required.

    On receipt the frontend should surface the ``PersonaCredentialPanel``
    component so the operator can enter credentials without leaving the UI.

    Attributes
    ----------
    type : str
        Always ``"HITL_PERSONA_CREDENTIALS_REQUIRED"``.
    run_id : str
        The run that is paused waiting for credentials.
    persona_name : str
        The raw persona string from the PERSONA_SWITCH AC step.
    message : str
        Human-readable prompt displayed above the credential form.
    """

    type: str = "HITL_PERSONA_CREDENTIALS_REQUIRED"
    run_id: str
    persona_name: str
    message: str = Field(
        default="",
        description="Human-readable prompt shown in the credential panel.",
    )


class WSVerifierCorrectionMessage(BaseModel):
    """
    WebSocket message sent by the FRONTEND to the backend when a user
    manually overrides a verifier verdict (e.g. "False Positive").
    """

    type: str = "verifier_correction"
    run_id: str
    ac_step_index: int
    reason: str = "User marked as satisfied (False Positive override)"


# ---------------------------------------------------------------------------
# Ghost Login HITL credential schemas (TASK-102)
# ---------------------------------------------------------------------------


class GhostCredentialsRequest(BaseModel):
    """
    Request body for ``POST /runs/{run_id}/ghost-credentials``.

    Sent by the frontend when the operator provides Admin credentials
    at run start or during execution.

    Either ``sso_token`` OR both ``email`` + ``password`` must be provided.
    ``sso_token`` is the experimental fast-path: the operator's existing vQA
    session token is injected directly into the Playwright browser context,
    skipping the browser form login entirely.
    """

    email: str | None = Field(
        None,
        min_length=1,
        max_length=254,
        description="Login email for the Admin user.",
    )
    password: str | None = Field(
        None,
        min_length=1,
        max_length=500,
        description="Login password for the Admin user.",
    )
    sso_token: str | None = Field(
        None,
        min_length=1,
        description="[Experimental] Operator's SSO/app token from their active vQA session. When provided, the backend injects it as the JWT in the Playwright browser context instead of performing a full browser form login.",
    )

    @model_validator(mode="after")
    def _require_creds_or_token(self) -> "GhostCredentialsRequest":
        has_creds = bool(self.email and self.password)
        has_token = bool(self.sso_token)
        if not has_creds and not has_token:
            raise ValueError("Provide either sso_token or both email and password.")
        return self


class GhostCredentialsResponse(BaseModel):
    """
    Response from ``POST /runs/{run_id}/ghost-credentials``.
    """

    ok: bool
    message: str = Field(default="", description="Optional status or error detail.")


class WSGhostCredentialsMessage(BaseModel):
    """
    WebSocket message broadcast when a GHOST_LOGIN step is present
    and operator admin credentials are required.
    """

    type: str = "GHOST_CREDENTIALS_REQUIRED"
    run_id: str
    message: str = Field(
        default="Admin credentials required for Ghost Login impersonation.",
        description="Human-readable prompt shown in the credential panel.",
    )


# ---------------------------------------------------------------------------
# Codegen Demo Recording schemas
# ---------------------------------------------------------------------------


class CodegenStartRequest(BaseModel):
    ticket_id: str
    ticket_summary: str
    target_url: str = "https://qa.vcreative.net"


class CodegenStartResponse(BaseModel):
    session_id: str
    stream_url: str
    novnc_url: str | None = None


class CodegenDoneEvent(BaseModel):
    """Shape of the WebSocket "recording_done" payload."""
    test_file: str
    test_path: str
    commit_hash: str
    run_id: str
    lines: int
