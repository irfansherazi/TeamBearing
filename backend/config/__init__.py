"""
vQA — Environment Configuration
================================
Module: backend/config.py

This module is the single source of truth for all environment-driven
configuration in the vQA system.  It uses Pydantic's BaseSettings to:

  1. Load values from environment variables (or a local .env file).
  2. Validate that required values are present and correctly typed at
     startup — so the app fails fast with a clear error rather than
     silently misbehaving at runtime.
  3. Provides a singleton ``settings`` instance that every other module
     imports, avoiding scattered ``os.getenv()`` calls.

Secret Resolution Order
-----------------------
Sensitive credentials (Jira tokens, role passwords) are resolved
automatically at startup — no user configuration required:

  1. **AWS SSM Parameter Store** — ``/vQA/jira/*`` and ``/vQA/roles/*``
     paths are fetched and decrypted at startup via ``backend.secrets``.
  2. **Environment variable** — fallback for local dev / CI without SSM.
  3. **Empty string** — system starts but logs a warning; affected
     operations will fail at the authentication step.

Jira credentials are pre-loaded from SSM so the user only needs to
provide a Jira ticket ID — not credentials.

Usage
-----
    from backend.config import settings

    print(settings.jira_domain)     # loaded from SSM, no .env needed
    print(settings.bedrock_model_id)

Environment Variables
---------------------
All variables are documented in ``.env.example`` at the project root.
For production, store secrets in AWS SSM Parameter Store (see DEPLOYMENT.md §3).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object for vQA.

    All fields map 1-to-1 to environment variables.  Pydantic will raise a
    ``ValidationError`` on startup if any required field is missing.

    Attributes are grouped by subsystem to make the file easy to navigate.
    """

    # ------------------------------------------------------------------
    # Pydantic model configuration
    # ------------------------------------------------------------------
    model_config = SettingsConfigDict(
        # Look for a .env file in the current working directory.
        # Variables already set in the real environment take precedence.
        env_file=".env",
        env_file_encoding="utf-8",
        # Ignore extra keys in the .env file (e.g. comments as KEY=VALUE).
        extra="ignore",
        # Make field lookup case-insensitive: JIRA_EMAIL == jira_email.
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Jira Integration
    # ------------------------------------------------------------------
    # These fields default to empty — they are populated at startup by
    # ``model_post_init`` which calls ``backend.secrets.load_all_secrets()``
    # to resolve values from SSM Parameter Store → env var fallback.
    # Users do NOT need to configure Jira credentials manually.
    # ------------------------------------------------------------------

    jira_email: str = Field(
        default="",
        description=("Jira service account email. Auto-loaded from SSM /vQA/jira/email. Fallback: JIRA_EMAIL env var."),
    )

    jira_api_token: str = Field(
        default="",
        description=(
            "Jira API token. Auto-loaded from SSM /vQA/jira/api_token (SecureString). Fallback: JIRA_API_TOKEN env var."
        ),
    )

    jira_domain: str = Field(
        default="",
        description=(
            "Atlassian domain without protocol. Auto-loaded from SSM /vQA/jira/domain. "
            "Fallback: JIRA_DOMAIN env var. Example: vcreative.atlassian.net"
        ),
    )

    jira_ac_fields: list[str] | str = Field(
        default=["customfield_10031", "customfield_10010", "customfield_10016"],
        description=(
            "Priority-ordered list of Jira custom field IDs to scan for Acceptance Criteria. "
            "Configurable via JIRA_AC_FIELDS env var (comma-separated)."
        ),
    )

    jira_board_ids: list[int] | str = Field(
        default=[27, 36],
        description=(
            "Jira Software board IDs to fetch tickets from. "
            "Configurable via JIRA_BOARD_IDS env var (comma-separated)."
        ),
    )

    jira_cache_ttl_seconds: int = Field(
        default=300,
        description=(
            "Time-to-live (seconds) for the in-memory Jira ticket cache. "
            "Prevents redundant API calls between preview-steps and execute. "
            "Defaults to 300s (5 minutes)."
        ),
    )

    ac_cache_ttl_seconds: int = Field(
        default=3600,
        description=(
            "Time-to-live (seconds) for the in-memory parsed AC steps cache. "
            "Prevents redundant LLM calls for the same ticket + guidance. "
            "Defaults to 3600s (1 hour)."
        ),
    )

    pinned_plan_ttl_days: int = Field(
        default=14,
        description=(
            "Time-to-live (days) for pinned TestPlan files stored under "
            "``storage/pinned_plans/``.  A pinned plan older than this value "
            "is treated as expired — ``POST /execute`` with that plan_id returns "
            "HTTP 410 Gone.  At 14 days and ~10 preview calls/day (~50 KB each), "
            "the store stays under ~7 MB.  Configurable via PINNED_PLAN_TTL_DAYS "
            "env var.  Part of Lock B (vqa-pinned-testplans)."
        ),
    )

    ac_parser_llm_timeout_seconds: int = Field(
        default=180,
        description=(
            "Timeout (seconds) for each Stage 1 / Stage 2 Bedrock LLM call in the "
            "AC parser. Prevents silent hangs when Bedrock stalls on large inputs "
            "(e.g., 180-step enriched ACs). On timeout, the request fails fast "
            "with a clear ValueError instead of blocking the request thread. "
            "Configurable via AC_PARSER_LLM_TIMEOUT_SECONDS env var."
        ),
    )

    @property
    def jira_base_url(self) -> str:
        """
        Construct the full Jira REST API v3 base URL.

        Returns
        -------
        str
            e.g. ``https://vcreative.atlassian.net/rest/api/3``
        """
        return f"https://{self.jira_domain}/rest/api/3"

    # ------------------------------------------------------------------
    # AWS Credentials & Region
    # ------------------------------------------------------------------

    aws_access_key_id: str | None = Field(
        default=None,
        description=(
            "AWS IAM access key. Optional if running on EC2/ECS with an "
            "instance profile — boto3 will pick up credentials automatically."
        ),
    )

    aws_secret_access_key: str | None = Field(
        default=None,
        description="AWS IAM secret key. Optional when using an instance profile.",
    )

    aws_region: str = Field(
        default="us-east-1",
        description="Primary AWS region for S3 and other services.",
    )

    aws_bedrock_region: str = Field(
        default="us-west-2",
        description=(
            "AWS region where Bedrock is invoked. Claude 3.5 Sonnet is available "
            "in us-west-2; cross-region inference profiles cover us-east-1."
        ),
    )

    # ------------------------------------------------------------------
    # AppProfile
    # ------------------------------------------------------------------

    vqa_profile: str = Field(
        default="vsuite",
        description=(
            "Active AppProfile name. Determines authentication flow, "
            "domain glossary, spinner selectors, and LLM prompt identity. "
            "Can be overridden per-run via the 'profile' field in /execute. "
            "Available profiles: 'vsuite' (default)."
        ),
    )

    # ------------------------------------------------------------------
    # LLM / Bedrock
    # ------------------------------------------------------------------

    llm_provider: Literal["bedrock", "openai", "anthropic"] = Field(
        default="bedrock",
        description=(
            "LLM provider. 'bedrock' (default) uses AWS Bedrock. "
            "'openai' and 'anthropic' are planned for Phase 2. "
            "This field exists to make future provider swaps a config change, "
            "not a code change."
        ),
    )

    bedrock_model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        description=(
            "Bedrock model identifier for the default LLM tier. "
            "Used for planner, verifier, evaluator, and most LLM calls. "
            "FEAT-114: Upgraded from claude-haiku-4-5 to claude-sonnet-4 for better "
            "UI reasoning quality. Cost: $3.00/$15.00 per 1M in/out tokens. "
            "NOTE: The AC parser uses bedrock_model_id_parser (also Sonnet) — not this field."
        ),
    )

    bedrock_model_id_heavy: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        description=(
            "Bedrock model identifier for the heavy LLM tier (complex reasoning). "
            "Used when the planner auto-escalates after repeated self-heal failures. "
            "Claude Sonnet 4 — slower and more expensive but better at complex UI reasoning."
        ),
    )

    # ------------------------------------------------------------------
    # FEAT-114: AC Parser Quality — dedicated parser model tier
    # ------------------------------------------------------------------

    bedrock_model_id_parser: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        description=(
            "Bedrock model identifier for the AC parser (Stage 1 BDD normalizer "
            "and Stage 2 JSON compiler). Defaults to Claude Sonnet 4 for superior "
            "reasoning quality on complex Jira AC text. Separated from bedrock_model_id "
            "(Haiku) so cost-sensitive nodes (planner, verifier) are unaffected. "
            "Override with BEDROCK_MODEL_ID_PARSER env var for A/B testing."
        ),
    )

    # ------------------------------------------------------------------
    # Critic Pass LLM Evaluator (critic-pass-llm-evaluator)
    # ------------------------------------------------------------------

    bedrock_model_id_critic: str = Field(
        default="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        description=(
            "Bedrock model identifier for the critic_node pre-execution LLM evaluator. "
            "Defaults to Claude Haiku 4.5 — cheap and fast (~0.8-1.5s per call) for "
            "comparing AC text against compiled TestPlan before browser work begins. "
            "Override with BEDROCK_MODEL_ID_CRITIC env var for A/B testing. "
            "See: memory-bank/creative/critic-pass-llm-evaluator-architecture.md"
        ),
    )

    critic_enabled: bool = Field(
        default=True,
        description=(
            "Feature flag for the Critic Pass LLM Evaluator. "
            "When True, critic_node fires between ac_parser and setup_role on every "
            "AI-mode run (execution_engine != 'static'), re-reading AC text + compiled "
            "TestPlan with a Haiku model to detect drift before browser work begins. "
            "When False, critic_node returns a synthetic pass (critic_skipped=True) "
            "and the run proceeds normally — no LLM call, no latency overhead. "
            "Set CRITIC_ENABLED=false to disable during performance testing."
        ),
    )

    max_critic_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description=(
            "Maximum number of critic-planner retry cycles per run. "
            "When the critic emits verdict='mismatch' and retry_count < max_critic_retries, "
            "the run routes back to ac_parser with structured critic_feedback for re-compilation. "
            "When retry_count reaches this limit, the run proceeds to setup_role with the "
            "imperfect plan and a WARNING log. "
            "Default 2 — each retry adds ~5-10s (Sonnet Stage 1+2 re-compile). "
            "Set MAX_CRITIC_RETRIES=0 to disable retries (critic can flag but never re-route)."
        ),
    )

    enable_hitl_before_executor: bool = Field(
        default=False,
        description=(
            "FEAT-114: When True, the LangGraph graph is compiled with "
            "interrupt_before=['executor'] so execution pauses before every "
            "executor_node invocation for human approval. Requires a checkpointer "
            "(MemorySaver) to be passed to build_graph(). Set to True for "
            "step-by-step HITL review workflows. Default False preserves current "
            "fully-autonomous execution behavior."
        ),
    )

    auto_escalate_threshold: int = Field(
        default=3,
        description=(
            "Number of consecutive self-heal retries before the planner auto-escalates "
            "from the default model (Haiku) to the heavy model (Sonnet). "
            "Set to 0 to always use the heavy model."
        ),
    )

    prompt_budget_enabled: bool = Field(
        default=True,
        description=(
            "When True, _build_system_prompt_v2() is used — assembles sections via "
            "PromptBudget with priority-based dropping and slot-ordered layout. "
            "Set to False to fall back to the legacy _build_system_prompt() for A/B comparison."
        ),
    )

    prompt_budget_max_tokens: int = Field(
        default=8000,
        ge=2000,
        le=20000,
        description=(
            "Token ceiling for the assembled planner system prompt (chars ÷ 4 estimate). "
            "8000 tokens is optimal for Claude Haiku attention quality. "
            "Increase to 12000 when using Sonnet (auto-escalation) for more context headroom."
        ),
    )

    # ------------------------------------------------------------------
    # FEAT-060: Execution Performance Overhaul (TASK-080 Phase 1)
    # ------------------------------------------------------------------

    model_router_enabled: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable three-tier model routing. "
            "When True, deterministic actions (click, fill, navigate) use Haiku (Tier 1), "
            "planning/disambiguation actions use Sonnet (Tier 2), and vision/HITL "
            "coordinate actions use Sonnet Vision full (Tier 3). "
            "When False, all calls use bedrock_model_id (pre-FEAT-060 behavior). "
            "Env var: MODEL_ROUTER_ENABLED."
        ),
    )

    prompt_compression_enabled: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable ARIA differential diffing + screenshot downscaling. "
            "When True, only changed ARIA nodes are sent to the planner (AriaDiff), "
            "reducing LLM input tokens by 60-80% for stable pages. "
            "When False, full ARIA tree is always sent (pre-FEAT-060 behavior). "
            "Env var: PROMPT_COMPRESSION_ENABLED."
        ),
    )

    speculative_prefetch_enabled: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable speculative KB pre-fetch for the next AC step. "
            "When True, KBPrefetcher schedules asyncio.create_task() after each "
            "planner action to pre-load KB context for step N+1 while the "
            "browser action executes, eliminating ~150ms of KB latency. "
            "When False, KB queries are always synchronous (pre-FEAT-060 behavior). "
            "Env var: SPECULATIVE_PREFETCH_ENABLED."
        ),
    )

    kb_min_similarity_score: float = Field(
        default=0.2,
        description=(
            "FEAT-088: Minimum similarity threshold for TF-IDF/RAG Knowledge Base retrieval. "
            "Matches scoring below this threshold are discarded. "
            "Env var: KB_MIN_SIMILARITY_SCORE."
        ),
    )

    rolling_summarization_window: int = Field(
        default=5,
        ge=3,
        le=20,
        description=(
            "FEAT-060: Number of planner iterations between rolling context "
            "summarization triggers. At every N-th iteration, the verbatim "
            "action history is replaced with a compact <session_summary> digest. "
            "Lower values summarize more aggressively (more token savings, "
            "less history detail). Set to 0 to disable summarization. "
            "Env var: ROLLING_SUMMARIZATION_WINDOW."
        ),
    )

    # ------------------------------------------------------------------
    # FEAT-060: Execution Performance Overhaul (TASK-080 Phase 2)
    # ------------------------------------------------------------------

    prompt_caching_enabled: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable Anthropic prompt caching via Bedrock cache_control breakpoints. "
            "When True, static system prompt sections (tool schemas, global rules, recipe library) "
            "are annotated with cachePoint markers so Bedrock caches them across turns. "
            "Expected: 60-80% reduction in input token cost on turns 2+ of a run. "
            "When False, all content is re-sent each turn (pre-FEAT-060 behavior). "
            "Env var: PROMPT_CACHING_ENABLED."
        ),
    )

    native_assertion_enabled: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable Playwright-native assertion bypass before LLM verifier. "
            "When True, AssertionCompiler parses AC step text and runs deterministic "
            "Playwright assertions (toHaveText, toBeVisible, url_check, etc.). "
            "If all assertions pass, the LLM verifier is skipped entirely. "
            "Target: bypass LLM on ≥ 40% of AC steps (AC-HAPPY-3). "
            "When False, always calls the LLM verifier (pre-FEAT-060 behavior). "
            "Env var: NATIVE_ASSERTION_ENABLED."
        ),
    )

    spa_hydration_event_driven: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable event-driven SPA hydration detection after page transitions. "
            "When True, SpaHydration injects Angular ApplicationRef.isStable() + "
            "MutationObserver to detect page stability without a fixed delay. "
            "Falls back to 2s fixed timeout if stability event does not fire. "
            "When False, always uses fixed wait_for_timeout (pre-FEAT-060 behavior). "
            "Env var: SPA_HYDRATION_EVENT_DRIVEN."
        ),
    )

    bedrock_roles_kb_id: str = Field(
        default="JXMMTMTI06",
        description=(
            "Bedrock Knowledge Base ID for the vProMedia-Roles-KB. "
            "This KB contains the RBAC permission matrix for all 8 user roles. "
            "The History KB and Code KB have been deprecated in vQA."
        ),
    )

    disable_bedrock_roles_kb: bool = Field(
        default=False,
        description=(
            "When True, skip all Bedrock Roles KB queries at startup and use only "
            "local persona files / env vars / hardcoded fallbacks for role credentials. "
            "Set DISABLE_BEDROCK_ROLES_KB=true to prevent the 9 Titan-Embed model "
            "invocations that fire on every ECS task start or restart. "
            "Safe to enable when the local persona files or env vars already have "
            "the correct credential values."
        ),
    )

    # ------------------------------------------------------------------
    # FEAT-060: Execution Performance Overhaul (TASK-080 Phase 3)
    # ------------------------------------------------------------------

    parallel_tickets_enabled: bool = Field(
        default=False,
        description=(
            "FEAT-060: Enable parallel ticket execution via RunOrchestrator. "
            "When True, POST /execute-batch dispatches N tickets concurrently, "
            "each in an isolated Playwright BrowserContext (no shared state). "
            "When False, tickets run sequentially — identical to the existing /execute path. "
            "DEFAULT: False until Phase 1+2 stability confirmed in production (Golden 10 benchmark). "
            "Env var: PARALLEL_TICKETS_ENABLED."
        ),
    )

    parallel_ticket_pool_size: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "FEAT-060: Max concurrent tickets when parallel_tickets_enabled=True. "
            "RunOrchestrator uses asyncio.Semaphore(pool_size) to gate concurrent "
            "BrowserContext creation. 3 is the recommended initial value. "
            "Env var: PARALLEL_TICKET_POOL_SIZE."
        ),
    )

    parallel_steps_enabled: bool = Field(
        default=False,
        description=(
            "FEAT-060: Enable DependencyAnalyzer parallel AC step groups. "
            "When True, consecutive VERIFY_ONLY steps are executed concurrently "
            "via asyncio.gather() — they share no write state by definition. "
            "WRITE steps (CLICK, FILL, NAVIGATE, etc.) are always sequential. "
            "When False, all steps execute sequentially (pre-FEAT-060 behavior). "
            "DEFAULT: False until parallel_tickets is proven stable. "
            "Env var: PARALLEL_STEPS_ENABLED."
        ),
    )

    speculative_planning_enabled: bool = Field(
        default=False,
        description=(
            "FEAT-060: Enable SpeculativePlanner background plan pre-generation. "
            "When True, while step N executes, SpeculativePlanner spawns a background "
            "asyncio.Task to pre-generate the plan for step N+1. If step N succeeds, "
            "the plan is applied immediately — eliminating one LLM round-trip per step. "
            "If step N fails, the speculative plan is discarded (poison signal). "
            "When False, plans are generated synchronously (pre-FEAT-060 behavior). "
            "DEFAULT: False until parallel_steps is proven stable. "
            "Env var: SPECULATIVE_PLANNING_ENABLED."
        ),
    )

    # ------------------------------------------------------------------
    # FEAT-060: Execution Performance Overhaul (TASK-080 Phase 4)
    # ------------------------------------------------------------------

    step_scoped_prompts_enabled: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable PromptAssembler step-scoped system prompts. "
            "When True, PromptAssembler builds step-scoped prompts that only include "
            "rules relevant to the predicted action type and AC step keywords. "
            "Global rules (identity, JSON format, locators) are injected only on "
            "the first turn — on subsequent turns they are served from the prompt cache "
            "(FEAT-060 Phase 2 Item 4). "
            "Expected: 20-30% token reduction per turn for Tier 1 actions. "
            "When False, the full monolithic system prompt is used (pre-FEAT-060 behavior). "
            "Env var: STEP_SCOPED_PROMPTS_ENABLED."
        ),
    )

    confidence_gated_hitl_enabled: bool = Field(
        default=True,
        description=(
            "FEAT-060: Enable confidence-score gated HITL escalation. "
            "When True, the evaluator reads _verifier_confidence from the verifier and "
            "uses a three-band model: "
            "  confidence < confidence_hitl_threshold_low AND retries > threshold → HITL; "
            "  confidence between low–high → lightweight retry with alternate strategy; "
            "  confidence > confidence_hitl_threshold_high → accept as VERIFIED. "
            "Reduces unnecessary HITL by estimated 30-50%. "
            "When False, the original binary HITL escalation is used (pre-FEAT-060 behavior). "
            "Env var: CONFIDENCE_GATED_HITL_ENABLED."
        ),
    )

    confidence_hitl_threshold_low: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description=(
            "FEAT-060: Confidence score below which the verifier verdict is treated as "
            "low-confidence. Combined with high retry_count, this triggers HITL escalation "
            "instead of a standard retry. Range: 0.0–1.0 (internally, verifier confidence "
            "is 0–100 int, normalized to float here). Default: 0.4. "
            "Env var: CONFIDENCE_HITL_THRESHOLD_LOW."
        ),
    )

    confidence_hitl_threshold_high: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "FEAT-060: Confidence score above which the verifier verdict is accepted "
            "as VERIFIED even on mid-range cases. Range: 0.0–1.0. Default: 0.7. "
            "Env var: CONFIDENCE_HITL_THRESHOLD_HIGH."
        ),
    )

    adaptive_timeouts_enabled: bool = Field(
        default=False,
        description=(
            "FEAT-060: Enable TimeoutProfiler dynamic P95-based Playwright timeouts. "
            "When True, compute_action_timeout() returns P95 × 2 from historical timing data "
            "(stored in timing_db_path) instead of the hardcoded worst-case values. "
            "When False, hardcoded timeout values are used everywhere (pre-FEAT-060 behavior). "
            "DEFAULT: False — opt-in after sufficient timing data is collected (≥10 runs). "
            "Env var: ADAPTIVE_TIMEOUTS_ENABLED."
        ),
    )

    timing_db_path: str = Field(
        default="memory/timing.db",
        description=(
            "FEAT-060: Path to the SQLite timing database used by TimeoutProfiler. "
            "Co-located in the memory/ directory alongside accepted tests. "
            "Relative paths are resolved from the project root. "
            "Env var: TIMING_DB_PATH."
        ),
    )

    # ------------------------------------------------------------------
    # GitHub Integration (Phase 4B)
    # ------------------------------------------------------------------

    github_token: str = Field(
        default="",
        description=(
            "GitHub personal access token for private repository access. "
            "Optional — public repos can be fetched without a token. "
            "Set GITHUB_TOKEN env var or add to .env file."
        ),
    )

    github_repo: str = Field(
        default="vcreativeinc/vQA",
        description=(
            "GitHub repository in 'owner/repo' format used by codegen to commit "
            "recorded tests and open pull requests via the GitHub API. "
            "Set GITHUB_REPO env var to override."
        ),
    )

    vsuite_platform_path: str = Field(
        default="",
        description=(
            "Absolute path to a vsuitePlatform checkout that has npm run ai:review "
            "(branch Syed/TD-260). Leave blank to use ../vsuitePlatform or the "
            "auto-created ../vsuitePlatform-ai-review worktree."
        ),
    )

    # ------------------------------------------------------------------
    # Webhook Notifications (Phase 5B)
    # ------------------------------------------------------------------

    webhook_url: str = Field(
        default="",
        description=(
            "Webhook URL for run completion notifications. "
            "Supports Slack, Teams, and generic JSON endpoints. "
            "Leave empty to disable webhooks."
        ),
    )

    webhook_format: Literal["generic", "slack", "teams"] = Field(
        default="generic",
        description=(
            "Webhook payload format: 'generic' (plain JSON), 'slack' (Block Kit), or 'teams' (Adaptive Card)."
        ),
    )

    # ------------------------------------------------------------------
    # API Authentication (Phase 5D)
    # ------------------------------------------------------------------

    api_keys: str = Field(
        default="",
        description=(
            "Comma-separated list of valid API keys for endpoint protection. "
            "Clients must send X-VQA-API-Key header. "
            "Leave empty to disable API key enforcement."
        ),
    )

    api_auth_enabled: bool = Field(
        default=False,
        description=(
            "When True, all endpoints except /health and /docs require a valid authentication (API Key or SSO Token)."
        ),
    )

    sso_public_key_path: str = Field(
        default="vcapi/public_key.pem",
        description="Path to the RS256 public key for SSO token validation (file fallback).",
    )

    sso_public_key: str = Field(
        default="",
        description="RS256 public key content for SSO token validation. If set, takes priority over sso_public_key_path.",
    )

    sso_enabled: bool = Field(
        default=True,
        description="When True, vQA will validate RS256 SSO tokens from vcAPI.",
    )

    # ------------------------------------------------------------------
    # Recovery Router (TASK-004 Phase 1)
    # ------------------------------------------------------------------

    recovery_strict_mode_enabled: bool = Field(
        default=True,
        description="Enable automatic recovery for Playwright strict mode (multiple matches) errors.",
    )

    recovery_timeout_enabled: bool = Field(
        default=True,
        description="Enable automatic recovery for Playwright timeout errors.",
    )

    # ------------------------------------------------------------------
    # ARIA Tree Pruning (FEAT-025)
    # ------------------------------------------------------------------

    aria_pruning_enabled: bool = Field(
        default=True,
        description="Enable multi-stage ARIA accessibility tree pruning.",
    )

    enable_session_navigation_context: bool = Field(
        default=True,
        description="Inject <session_context> block (URL, heading, history) into planner prompt.",
    )

    viewport_pruning_enabled: bool = Field(
        default=True,
        description="Prune elements outside the current browser viewport.",
    )

    semantic_pruning_enabled: bool = Field(
        default=True,
        description="Prune elements that do not match the target_element_types for the current step.",
    )

    always_keep_roles: list[str] | str = Field(
        default=[
            "button",
            "link",
            "textbox",
            "combobox",
            "checkbox",
            "tab",
            "menuitem",
            "option",
            "radio",
            "switch",
            "slider",
            "spinbutton",
            "searchbox",
            "gridcell",
            "columnheader",
            "rowheader",
        ],
        description="ARIA roles to always keep even when pruning (safety set).",
    )

    recovery_not_visible_enabled: bool = Field(
        default=True,
        description="Enable automatic recovery for 'element is not visible' errors.",
    )

    recovery_detached_enabled: bool = Field(
        default=True,
        description="Enable automatic recovery for 'element is detached from DOM' errors.",
    )

    recovery_intercepted_enabled: bool = Field(
        default=True,
        description="Enable automatic recovery for 'click intercepted' (overlay) errors.",
    )

    # ------------------------------------------------------------------
    # Toast Capture Infrastructure (TASK-009)
    # ------------------------------------------------------------------

    enable_toast_buffer: bool = Field(
        default=True,
        description=(
            "When True, a MutationObserver is injected into the browser context "
            "to capture PrimeNG toast messages into window.__VQA_TOAST_BUFFER__."
        ),
    )

    # ------------------------------------------------------------------
    # Deferred Verification Queue (TASK-005)
    # ------------------------------------------------------------------

    enable_deferred_verification: bool = Field(
        default=True,
        description=(
            "When True, the verifier enqueues 'soft assertions' instead of "
            "auto-satisfying transient selector and sparse dataset bypasses. "
            "Deferred re-checks fire N steps later. When False, the old "
            "auto-satisfy behavior is preserved exactly."
        ),
    )

    deferred_check_delay: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "Number of AC steps to wait before re-checking a deferred "
            "soft assertion. Too short may re-check before the page "
            "stabilizes; too long may backtrack into a fundamentally "
            "different page state."
        ),
    )

    deferred_backtrack_limit: int = Field(
        default=2,
        ge=0,
        le=5,
        description=(
            "Maximum number of steps the evaluator may backtrack when "
            "a deferred re-check fails. If the current step is beyond "
            "this distance from the deferred step, the failure is recorded "
            "as a DVF but no backtrack occurs."
        ),
    )

    per_step_budget_max: int = Field(
        default=30,
        ge=5,
        le=100,
        description=(
            "Maximum number of planner iterations allowed per single AC step. "
            "Prevents a single stuck step from consuming the entire global budget. "
            "Actual budget is min(this, remaining_global_budget / remaining_steps)."
        ),
    )

    # ------------------------------------------------------------------
    # HITL Threshold Tuning (TASK-006)
    # ------------------------------------------------------------------

    hitl_threshold_general: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Default number of consecutive failures before triggering human takeover.",
    )

    hitl_threshold_intercepted: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Escalation threshold for INTERCEPTED (overlay blocking) failures.",
    )

    hitl_threshold_strict_mode: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Escalation threshold for STRICT_MODE (multiple matches) failures.",
    )

    # ------------------------------------------------------------------
    # Exploration Mode (FEAT-040)
    # ------------------------------------------------------------------

    enable_exploration_mode: bool = Field(
        default=True,
        description=(
            "When True, ExplorationRunner fires inside evaluator_node after "
            "debugger intervention and before HITL escalation. The runner "
            "autonomously navigates adjacent UI topology (scroll, expand accordions, "
            "click sibling tabs) to locate missing target elements. "
            "Set to False to disable exploration and fall through to human_takeover "
            "immediately (same behaviour as before FEAT-040). "
            "Env var: ENABLE_EXPLORATION_MODE."
        ),
    )

    exploration_max_steps: int = Field(
        default=8,
        ge=1,
        le=30,
        description=(
            "Maximum number of Playwright actions ExplorationRunner may dispatch "
            "during a single exploration episode.  Keeps exploration overhead "
            "bounded (≤ 8 additional steps per stuck element). "
            "Env var: EXPLORATION_MAX_STEPS."
        ),
    )

    exploration_min_dom_failures: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Minimum ac_step_action_fail_count before ExplorationRunner activates. "
            "Ensures exploration only fires after the standard failure chain "
            "(retry → debugger) has been exhausted.  Must be > hitl_threshold_general "
            "to avoid activating exploration before HITL is warranted. "
            "Env var: EXPLORATION_MIN_DOM_FAILURES."
        ),
    )

    # ------------------------------------------------------------------
    # State Store
    # ------------------------------------------------------------------

    state_store: Literal["memory", "redis"] = Field(
        default="memory",
        description=(
            "Run state storage backend. 'memory' (default) uses an in-process dict — "
            "zero config, single-container only. 'redis' uses Redis for persistence "
            "and multi-container horizontal scaling."
        ),
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL. Only used when state_store='redis'.",
    )

    redis_run_ttl_hours: int = Field(
        default=24,
        description=(
            "TTL (hours) for completed run entries in Redis. "
            "Runs expire after this duration to prevent unbounded growth. "
            "Only used when state_store='redis'."
        ),
    )

    # ------------------------------------------------------------------
    # S3 Storage
    # ------------------------------------------------------------------

    s3_bucket: str = Field(
        default="vcreative-deployments",
        description="S3 bucket name where all vQA artifacts are stored.",
    )

    s3_prefix: str = Field(
        default="vSuitePlatform/Buildartif/vqa-results",
        description=("Key prefix (folder path) within the S3 bucket. Sub-paths: screenshots/, videos/, reports/"),
    )

    @property
    def s3_screenshots_prefix(self) -> str:
        """Return the S3 prefix for screenshot artifacts."""
        return f"{self.s3_prefix}/screenshots"

    @property
    def s3_videos_prefix(self) -> str:
        """Return the S3 prefix for session video recordings."""
        return f"{self.s3_prefix}/videos"

    @property
    def s3_reports_prefix(self) -> str:
        """Return the S3 prefix for HTML audit reports."""
        return f"{self.s3_prefix}/reports"

    # ------------------------------------------------------------------
    # Role Credentials (Optional — KB is primary source)
    # ------------------------------------------------------------------
    # Credentials are fetched from the Bedrock Roles KB (JXMMTMTI06) at
    # startup.  These env vars serve as a FALLBACK for environments
    # without KB access (local dev, CI without AWS, etc.).
    # See backend/engine/kb_client.py for the KB query implementation.
    # ------------------------------------------------------------------

    role_default_password: str = Field(
        default="",
        description=(
            "Fallback shared password for test accounts. "
            "Primary source: Bedrock Roles KB. "
            "Only needed if KB is unavailable."
        ),
    )

    role_email_ae: str = Field(
        default="",
        description="Fallback email for AE. Primary source: Roles KB.",
    )

    role_email_sales_manager: str = Field(
        default="",
        description="Fallback email for Sales Manager. Primary source: Roles KB.",
    )

    role_email_sales_assistant: str = Field(
        default="",
        description="Fallback email for Sales Assistant. Primary source: Roles KB.",
    )

    role_email_production_manager: str = Field(
        default="",
        description="Fallback email for Production Manager. Primary source: Roles KB.",
    )

    role_email_producer: str = Field(
        default="",
        description="Fallback email for Producer. Primary source: Roles KB.",
    )

    role_email_gm_gsm: str = Field(
        default="",
        description="Fallback email for GM / GSM. Primary source: Roles KB.",
    )

    role_email_dubber: str = Field(
        default="",
        description="Fallback email for Dubber. Primary source: Roles KB.",
    )

    role_email_digital_director: str = Field(
        default="",
        description="Fallback email for Digital Director. Primary source: Roles KB.",
    )

    # ------------------------------------------------------------------
    # Per-User Session Isolation (per-user-session-isolation, Phase 1)
    # ------------------------------------------------------------------

    session_isolation_enabled: bool = Field(
        default=False,
        description=(
            "Kill switch for per-user session isolation. "
            "When False (Stage 1 rollout), /execute* endpoints skip the session cookie "
            "requirement and run anonymously (legacy behavior). "
            "When True (Stage 2+), every /execute* call requires a vqa_session cookie "
            "and runs are bound to the caller's session. "
            "Flip to True and restart the container — no code deploy required."
        ),
    )

    max_concurrent_sessions: int = Field(
        default=4,
        ge=1,
        le=32,
        description=(
            "Upper bound on simultaneous active user sessions. "
            "Sized by container memory: N × ~700MB (browser+display) + backend baseline. "
            "Also templates docker/supervisord.conf.template at container start. "
            "Bump to 8 in Stage 3 rollout if memory + latency support it."
        ),
    )

    max_jwt_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description=(
            "Maximum allowed JWT TTL at the vQA boundary. "
            "Rejects tokens where (exp - now) > this value. "
            "Defense-in-depth against forever-tokens (ADR-6). "
            "Coordinate with vcAPI SSO owner before increasing."
        ),
    )

    session_cookie_name: str = Field(
        default="vqa_session",
        description=(
            "Name of the HttpOnly session cookie issued at /session/start "
            "and re-issued at /session/rebind."
        ),
    )

    rebind_grace_seconds: int = Field(
        default=60,
        ge=0,
        description=(
            "Additional grace period (seconds) past jwt_valid_until before the "
            "periodic tick terminates the session. "
            "Worst-case linger = rebind_grace_seconds + session_tick_interval_seconds ≈ 90s."
        ),
    )

    session_tick_interval_seconds: int = Field(
        default=30,
        ge=5,
        description=(
            "Cadence (seconds) of the SessionManager background tick task. "
            "Enforces JWT expiry + grace, sweeps allocator leaks, "
            "evicts DETACHED_GRACE sessions."
        ),
    )

    session_reconnect_grace_seconds: int = Field(
        default=0,
        ge=0,
        description=(
            "Time (seconds) between last WS disconnect and TERMINATING transition. "
            "Default 0 = strict tab-close-terminates (per user Decision 2). "
            "The state machine skips DETACHED_GRACE entirely when this is 0. "
            "Non-zero values are a runtime knob for future operational tuning."
        ),
    )

    ws_heartbeat_interval_seconds: int = Field(
        default=15,
        ge=5,
        description="Server-side ping interval (seconds) on /ws/session/{session_id}.",
    )

    ws_heartbeat_timeout_seconds: int = Field(
        default=15,
        ge=5,
        description=(
            "Maximum time (seconds) without a heartbeat pong before authoritative session teardown. "
            "ADR-10: heartbeat timeout is the correctness path; beforeunload is best-effort."
        ),
    )

    log_format: Literal["json", "text"] = Field(
        default="json",
        description=(
            "Log output format. "
            "'json' (default) uses JsonFormatter for CloudWatch Metric Filters. "
            "'text' uses human-readable plain-text for local development. "
            "ADR-8: structured JSON logs as the observability transport; OTel is future work."
        ),
    )

    # ------------------------------------------------------------------
    # VNC / UI Appearance
    # ------------------------------------------------------------------

    vnc_theme: Literal["light", "dark"] = Field(
        default="light",
        description="Default theme for the VNC injection layer (p-theme-light or p-theme-dark).",
    )

    # ------------------------------------------------------------------
    # Application Behaviour
    # ------------------------------------------------------------------

    vqa_mode: Literal["interactive", "headless"] = Field(
        default="interactive",
        description=(
            "Execution mode. "
            "'interactive' starts Xvfb + noVNC for live browser streaming. "
            "'headless' runs Playwright with headless=True — no virtual display needed."
        ),
    )

    target_url: str = Field(
        default="https://two-test.vcreative.net",
        description=("Default application URL under test. Can be overridden per-request in the /execute payload."),
    )

    skip_preflight: bool = Field(
        default=False,
        description=(
            "Skip pre-flight session health checks (URL reachability, auth freshness, "
            "role scope) before starting a run. Set VQA_SKIP_PREFLIGHT=1 for local development."
        ),
    )

    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Maximum number of self-heal retry attempts per AC step. "
            "On each failure the agent re-captures a screenshot and re-plans."
        ),
    )

    max_planner_iterations: int = Field(
        default=500,
        ge=5,
        le=1000,
        description=(
            "Safety cap on the see-think-act loop (EVALUATOR check). "
            "For E2E integration tests with 30-50 AC steps (each needing 5-10 "
            "browser actions), 500 is a safe default. Increase via env var for "
            "exceptionally large tickets. The run is marked FAILED if this limit is hit. "
            "NOTE: LangGraph's graph-level recursion_limit (set in routes.py) counts "
            "GRAPH NODE VISITS, not planner iterations — it is set to ~6x this value "
            "to ensure the evaluator guard fires before the LangGraph hard stop."
        ),
    )

    max_run_wall_clock_seconds: int = Field(
        default=1800,
        ge=60,
        le=7200,
        description=(
            "Hard wall-clock limit per run in seconds. Run is terminated with "
            "FAILED verdict if exceeded. Default: 30 minutes (1800s)."
        ),
    )

    max_run_cost_usd: float = Field(
        default=2.00,
        ge=0.10,
        le=50.00,
        description=(
            "Hard USD cost cap per run. Run terminated with FAILED verdict if "
            "RunMetrics.estimated_cost_usd exceeds this. Default: $2.00."
        ),
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Python logging level for the FastAPI application.",
    )

    novnc_port: int = Field(
        default=6080,
        description="Port that noVNC WebSocket proxy listens on (interactive mode only).",
    )

    api_port: int = Field(
        default=8000,
        description="Port that the FastAPI / uvicorn server binds to.",
    )

    external_host: str = Field(
        default="localhost",
        description=(
            "Public hostname for constructing WebSocket and noVNC URLs (e.g. vqa.vcreative.net). "
            "Used by the frontend to connect to the live stream."
        ),
    )

    external_protocol: Literal["http", "https"] = Field(
        default="http",
        description=(
            "Public protocol for constructing URLs. 'https' implies 'wss' for WebSockets. Set to 'https' in production."
        ),
    )

    # ------------------------------------------------------------------
    # Test Persistence & Smart Replay (TASK-031 / FEAT-043)
    # ------------------------------------------------------------------

    accepted_tests_dir: str = Field(
        default="memory/accepted_tests",
        description=(
            "Filesystem directory (relative to vQA root) where accepted test records "
            "are stored as JSON files. Each accepted run is serialized into a deterministic "
            "action sequence file at: <accepted_tests_dir>/<ticket_id>-<ac_hash>.json. "
            "The index file (index.json) in this directory maps ticket_id+ac_hash → filename. "
            "Env var: ACCEPTED_TESTS_DIR."
        ),
    )

    accepted_tests_max_count: int = Field(
        default=1000,
        ge=1,
        description="Maximum number of accepted test records to keep. Pruning removes oldest by last_used.",
    )

    accepted_tests_max_age_days: int = Field(
        default=30,
        ge=1,
        description="Maximum age (days) of accepted test records. Records older than this are pruned.",
    )

    enable_smart_replay: bool = Field(
        default=True,
        description=(
            "When True, vQA checks for an accepted test at the start of every /execute run. "
            "If a matching accepted test is found (same ticket_id + AC hash), the run "
            "replays the deterministic action sequence without invoking the LLM planner, "
            "completing in ≤ 30%% of the original AI-driven time. Falls back transparently "
            "to full AI generation on replay failure (selector mismatch, etc.). "
            "Set to False to always use full AI-driven execution. "
            "Env var: ENABLE_SMART_REPLAY."
        ),
    )

    # ------------------------------------------------------------------
    # Playwright Standard Library (TASK-060 / FEAT-052)
    # ------------------------------------------------------------------

    playwright_tests_dir: str = Field(
        default="playwright/tests",
        description="Directory containing Playwright test files (.test.ts).",
    )

    playwright_registry_file: str = Field(
        default="playwright/playwright_index.json",
        description="Path to the generated test index file.",
    )

    shared_test_password: str = Field(
        default="",
        description="Shared password for all test accounts. Fallback: SHARED_TEST_PASSWORD env var.",
    )

    admin_test_password: str = Field(
        default="",
        description="Admin password for doc+test_admin@vcreativeinc.com. Fallback: ADMIN_TEST_PASSWORD env var.",
    )

    test_env: Literal["prod", "test", "smoke", "qa"] = Field(
        default="test",
        description="Target environment for Playwright runs: prod, test, smoke, qa.",
    )

    # ------------------------------------------------------------------
    # CV Fallback Layer (FEAT-037 / TASK-028)
    # ------------------------------------------------------------------

    cv_fallback_enabled: bool = Field(
        default=True,
        description=(
            "Enable executor-side CV fallback after DOM failure exhaustion. "
            "When True, CvFallbackResolver activates after cv_fallback_min_dom_failures "
            "consecutive Playwright failures on a click/coordinate_action step, capturing "
            "a Set-of-Marks annotated screenshot and invoking the vision LLM (Claude Sonnet) "
            "to resolve a coordinate click. Set to False to disable entirely — the normal "
            "HITL escalation path runs unchanged. "
            "Env var: CV_FALLBACK_ENABLED"
        ),
    )

    cv_fallback_min_dom_failures: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Minimum consecutive DOM action failures before CV fallback activates. "
            "Steps with cv_fallback_eligible=True in their action use threshold=1 instead. "
            "Default of 3 ensures the normal retry chain (recovery router, wait/scroll) "
            "is fully exhausted before invoking the vision LLM. "
            "Env var: CV_FALLBACK_MIN_DOM_FAILURES"
        ),
    )

    # ------------------------------------------------------------------
    # Nightly Scheduled Playwright Test Suite (nightly-scheduled-playwright-test-suite-run)
    # ------------------------------------------------------------------
    # Configuration for the nightly EventBridge → Fargate endpoint that
    # runs a pinned two-test subset and posts results to Slack.
    # All values have pinned defaults; override via env vars for smoke-testing.
    # The Slack webhook URL is loaded from SSM /vQA/slack/nightly_webhook_url
    # at startup (see model_post_init below).
    # ------------------------------------------------------------------

    nightly_test_ids: list[str] = Field(
        default=[
            "qa-100-script-library.test",
            "qa-101-client-merging.test",
            "qa-125-new-user-experience.test",
            "qa-157-large-order-testing.test",
            "qa-170-search.test",
            "qa-172-production.test",
            "qa-172-sales.test",
            "qa-175-lockout.test",
            "qa-185-saved-searches-sharing.test",
            "qa-192-recorded.test",
            "qa-196-Files.test",
            "qa-197-revision-process.test",
            "qa-203-datetime-picker-pastdue.test",
            "qa-204-client-approval-upon-submit.test",
            "qa-247-job-completion-hover-feature.test",
            "qa-254-manual_archive.test",
            "qa-257-Exporting_spot_info.test",
            "qa-279-send-email.test",
            "qa-298-folder-count-equals-visible-spot-count.test",
            "qa-321-sorting-list-and-compact.test",
            "qa-46-basic-ad-types.test",
            "qa-58-59-poc-delegation.test",
            "vc2-9225-recorded.test",
            "vc2-9267-recorded.test",
            "verify-login.test",
            "webkit-qo-baseline.test",
        ],
        description=(
            "Pinned test IDs for the nightly regression subset. "
            "The full 26-test DemoProdDirector-friendly library — every test "
            "shown in the frontend picker under the ProdDirector persona. "
            "qa-359-recorded.test is intentionally excluded (not persona-aligned). "
            "Only used when nightly_mode == 'pinned'. "
            "Override via NIGHTLY_TEST_IDS env var (comma-separated)."
        ),
    )

    nightly_mode: Literal["pinned", "all"] = Field(
        default="pinned",
        description=(
            "Nightly test-selection mode. "
            "'pinned' (default) runs the fixed list in nightly_test_ids. "
            "'all' expands to every .test.ts file registered in playwright_index.json. "
            "Override via NIGHTLY_MODE env var."
        ),
    )

    nightly_env: str = Field(
        default="test",
        description=(
            "Target environment for the nightly run. "
            "'test' resolves to two-test.vcreative.net (per products.yaml). "
            "Override via NIGHTLY_ENV env var."
        ),
    )

    nightly_user: str = Field(
        default="DemoProdDirector",
        description=(
            "vQA user persona for the nightly run (ProdDirector role). "
            "Override via NIGHTLY_USER env var."
        ),
    )

    nightly_browser: str = Field(
        default="chromium",
        description=(
            "Browser for the nightly run. "
            "Override via NIGHTLY_BROWSER env var."
        ),
    )

    nightly_slack_webhook_url: str = Field(
        default="",
        description=(
            "Slack incoming webhook URL for nightly run notifications. "
            "Auto-loaded from SSM /vQA/slack/nightly_webhook_url at startup. "
            "Fallback: NIGHTLY_SLACK_WEBHOOK_URL env var. "
            "Leave empty to disable Slack notifications."
        ),
    )

    nightly_poll_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description=(
            "Seconds between polls of the suite run store inside the nightly "
            "background task. 5s balances responsiveness vs. CPU overhead. "
            "Override via NIGHTLY_POLL_INTERVAL_SECONDS env var."
        ),
    )

    nightly_poll_timeout_seconds: int = Field(
        default=5400,
        ge=60,
        le=7200,
        description=(
            "Maximum seconds the nightly background task polls before posting "
            "an AC-ERROR-1 timeout message. Default 90 minutes — sized for the "
            "26-test DemoProdDirector library at ~3 min/test sequential. "
            "Override via NIGHTLY_POLL_TIMEOUT_SECONDS env var."
        ),
    )

    # ------------------------------------------------------------------
    # Build Number Tracking (TASK-117)
    # ------------------------------------------------------------------
    vqa_build_number: str = Field(
        default="1.0.0",
        description=(
            "Build number of the current deployment. Loaded from VQA_BUILD_NUMBER env "
            "var with fallback to a local .build_number / BUILD_NUMBER file, "
            "defaulting to '1.0.0'."
        ),
    )

    # ------------------------------------------------------------------
    # Accessibility Tree Grounding (feature/accessibility-tree-grounding)
    # Two-flag shadow-mode rollout (Architecture Decision 4):
    #   - a11y_resolver_enabled: enables A11yLocatorResolver for
    #     click/fill/check/uncheck. Off by default; turn on after verifying
    #     aria_enrichment_hit_rate with enrichment-only mode first.
    #   - a11y_enrichment_enabled: (Phase 3) enables ac_aria_enricher to
    #     populate aria_role/aria_name on TestPlanStep at plan time.
    #     Off by default; enable first to measure enrichment coverage.
    # ------------------------------------------------------------------

    a11y_resolver_enabled: bool = Field(
        default=False,
        description=(
            "Enable A11yLocatorResolver for click/fill/check/uncheck actions. "
            "When True, the executor attempts page.get_by_role(aria_role, name=aria_name) "
            "before falling back to the existing CSS/PrimeNG selector path. "
            "Feature flag: A11Y_RESOLVER_ENABLED=true in environment. "
            "Off by default — enable after validating aria_enrichment_hit_rate "
            "(accessibility-tree-grounding Architecture Decision 4)."
        ),
    )

    a11y_enrichment_enabled: bool = Field(
        default=False,
        description=(
            "Enable ac_aria_enricher post-login ARIA enrichment of TestPlanStep fields. "
            "When True, ac_aria_enricher.py runs after login_node to populate "
            "aria_role/aria_name on each TestPlanStep from the live ARIA snapshot. "
            "Feature flag: A11Y_ENRICHMENT_ENABLED=true in environment. "
            "Off by default — enable first, before a11y_resolver_enabled, "
            "to measure enrichment hit rate (accessibility-tree-grounding Phase 3)."
        ),
    )

    recovery_a11y_ambiguous_enabled: bool = Field(
        default=False,
        description=(
            "Enable automatic recovery for A11Y_AMBIGUOUS locator failures. "
            "When True, the recovery router attempts to disambiguate a11y-resolved steps "
            "that returned N>1 matches by injecting aria_disambiguators as a container_selector. "
            "Off by default — opt-in only. Requires a11y_resolver_enabled=True to be useful. "
            "Feature flag: RECOVERY_A11Y_AMBIGUOUS_ENABLED=true in environment "
            "(accessibility-tree-grounding Phase 3 — AC-VERIFY-8)."
        ),
    )

    a11y_ambiguous_max_retries: int = Field(
        default=2,
        description=(
            "Maximum number of A11Y_AMBIGUOUS recovery retries per (role, name, page-scope) "
            "fingerprint per run. Governs the Failure Diary cap for the A11Y_AMBIGUOUS handler. "
            "Default 2 — enough to cover a transient DOM race without allowing a wedged locator "
            "to burn recovery slots indefinitely (accessibility-tree-grounding Algorithm Decision 2)."
        ),
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    def model_post_init(self, __context: object) -> None:
        """
        Load secrets from SSM Parameter Store after Pydantic initialisation.

        This hook runs after all fields are set.  It calls
        ``backend.secrets.load_all_secrets()`` to resolve Jira credentials,
        role passwords, and other sensitive values from SSM → env var fallback.

        After this runs, fields like ``jira_email`` and ``jira_api_token``
        will have real values even if they were not set in the environment,
        as long as the SSM parameters exist and the AWS IAM role has access.

        Notes
        -----
        We use ``object.__setattr__`` to bypass Pydantic's immutability
        (Settings is model_config ``frozen=False`` by default in BaseSettings).
        """
        # Import here to avoid circular imports (secrets.py has no vQA imports)
        try:
            from backend.secrets import load_all_secrets

            resolved = load_all_secrets()

            # Override empty Jira fields with SSM/env values
            if not self.jira_email and resolved.get("jira_email"):
                object.__setattr__(self, "jira_email", resolved["jira_email"])
            if not self.jira_api_token and resolved.get("jira_api_token"):
                object.__setattr__(self, "jira_api_token", resolved["jira_api_token"])
            if not self.jira_domain and resolved.get("jira_domain"):
                object.__setattr__(self, "jira_domain", resolved["jira_domain"])

            # Override empty role password with SSM/env value
            if not self.role_default_password and resolved.get("role_default_password"):
                object.__setattr__(self, "role_default_password", resolved["role_default_password"])

            # Override Sales Manager email (KB gap — stored in SSM)
            if not self.role_email_sales_manager and resolved.get("role_email_sales_manager"):
                object.__setattr__(self, "role_email_sales_manager", resolved["role_email_sales_manager"])

            # Override Playwright secrets
            if not self.shared_test_password and resolved.get("shared_test_password"):
                object.__setattr__(self, "shared_test_password", resolved["shared_test_password"])
            if not self.admin_test_password and resolved.get("admin_test_password"):
                object.__setattr__(self, "admin_test_password", resolved["admin_test_password"])

            # Override nightly Slack webhook URL from SSM
            if not self.nightly_slack_webhook_url and resolved.get("nightly_slack_webhook_url"):
                object.__setattr__(self, "nightly_slack_webhook_url", resolved["nightly_slack_webhook_url"])

        except Exception as e:
            # Never crash the app on secrets load failure — just log
            import logging

            logging.getLogger(__name__).warning(
                "Secrets load failed (SSM unavailable?): %s. Falling back to env vars only.",
                str(e),
            )

        # Resolve build number fallback if environment variable is not set, empty, or "dev" (AC-2)
        import os
        env_val = os.environ.get("VQA_BUILD_NUMBER") or os.environ.get("vqa_build_number")
        if not env_val or env_val.strip() == "" or env_val.lower() == "dev":
            found_build = None
            for base_dir in [".", ".."]:
                for filename in [".build_number", "BUILD_NUMBER"]:
                    target_path = os.path.join(base_dir, filename)
                    if os.path.exists(target_path):
                        try:
                            with open(target_path, "r", encoding="utf-8") as f:
                                content = f.read().strip()
                                if content:
                                    found_build = content
                                    break
                        except Exception:
                            pass
                if found_build:
                    break

            if found_build:
                object.__setattr__(self, "vqa_build_number", found_build)
            else:
                git_version = None
                try:
                    import subprocess
                    result = subprocess.run(
                        ["git", "rev-list", "--count", "HEAD"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=True,
                    )
                    count_val = result.stdout.strip()
                    if count_val and count_val.isdigit():
                        git_version = f"1.0.{count_val}"
                except Exception:
                    pass

                if git_version:
                    object.__setattr__(self, "vqa_build_number", git_version)
                else:
                    object.__setattr__(self, "vqa_build_number", "1.0.0")
        else:
            object.__setattr__(self, "vqa_build_number", env_val.strip())

    @field_validator("jira_ac_fields", "always_keep_roles", "jira_board_ids", mode="before")
    @classmethod
    def parse_comma_separated_list(cls, v: str | list[str] | list[int]) -> list[str] | list[int]:
        """
        Support comma-separated strings for list fields (e.g. from env vars).
        """
        if isinstance(v, str):
            items = [x.strip() for x in v.split(",") if x.strip()]
            # If the field is supposed to be int (jira_board_ids), convert it
            # Pydantic's type hint will handle the final conversion if we return strings,
            # but being explicit here is safer.
            return items
        return v

    @field_validator("jira_domain")
    @classmethod
    def strip_protocol_from_domain(cls, v: str) -> str:
        """
        Ensure the Jira domain does not include a protocol prefix.

        Pydantic will call this before storing the value. If the user
        accidentally sets JIRA_DOMAIN=https://foo.atlassian.net, this
        strips the prefix so downstream URL construction works correctly.

        Args
        ----
        v : str
            Raw value from the environment variable.

        Returns
        -------
        str
            Domain without protocol or trailing slash.

        Example
        -------
        >>> strip_protocol_from_domain("https://vcreative.atlassian.net/")
        'vcreative.atlassian.net'
        """
        return v.replace("https://", "").replace("http://", "").rstrip("/")

    @field_validator("s3_prefix")
    @classmethod
    def strip_trailing_slash_from_prefix(cls, v: str) -> str:
        """
        Remove any trailing slash from the S3 prefix.

        Prevents double-slash keys like ``prefix//screenshots/file.png``.

        Args
        ----
        v : str
            Raw S3 prefix string.

        Returns
        -------
        str
            Prefix without trailing slash.
        """
        return v.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.

    Uses ``functools.lru_cache`` so the .env file is only read once per
    process, regardless of how many modules call this function.

    In unit tests, clear the cache between tests if you need to inject
    different environment variables:

        from backend.config import get_settings
        get_settings.cache_clear()

    Returns
    -------
    Settings
        The validated application configuration object.

    Raises
    ------
    pydantic.ValidationError
        If any required environment variable is missing or invalid.
        The error message lists every missing field with a human-readable
        description.

    Example
    -------
    >>> from backend.config import get_settings
    >>> s = get_settings()
    >>> s.jira_base_url
    'https://vcreative.atlassian.net/rest/api/3'
    """
    return Settings()  # type: ignore[call-arg]  # pydantic reads from env


# ---------------------------------------------------------------------------
# Module-level singleton — use this in all other vQA modules.
# ---------------------------------------------------------------------------
#
# Import pattern:
#   from backend.config import settings
#
# Do NOT call get_settings() at import time inside other modules; import the
# pre-built singleton instead.  This keeps test overrides simple.
#
settings: Settings = get_settings()
