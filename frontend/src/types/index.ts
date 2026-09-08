/**
 * vQA — TypeScript Type Definitions
 * ==================================
 * Module: frontend/src/types/index.ts
 *
 * Centralised type definitions for the vQA React frontend.
 * These types mirror the backend Pydantic schemas (backend/api/schemas.py)
 * to ensure type-safe API communication.
 *
 * Architecture Context:
 * - All API responses are typed using these interfaces
 * - WebSocket messages use the WS* types
 * - Component props reference these types directly
 */


// ---------------------------------------------------------------------------
// Execution Request / Response
// ---------------------------------------------------------------------------

/**
 * Request body for POST /execute.
 *
 * @example
 * const req: ExecuteRequest = {
 *   jira_ticket_id: "VC2-8967",
 *   role: "account_executive",
 *   target_url: "https://two-test.vcreative.net",
 *   mode: "interactive",
 * };
 */
export interface ExecuteRequest {
  /** Jira issue key (e.g. "VC2-8967") */
  jira_ticket_id: string;
  /** User role key (e.g. "account_executive") */
  role: RoleKey;
  /** Application URL to test against */
  target_url: string;
  /** Execution mode: "interactive" (noVNC) or "headless" */
  mode: ExecutionMode;
  /** Override email — supplied when ticket has partial credentials */
  override_email?: string;
  /** Override password — supplied when ticket has partial credentials */
  override_password?: string;
  /** Optional human guidance injected into the planner for a re-run */
  user_guidance?: string;
  /**
   * Context provided BEFORE AC generation — injected into the Stage 1 BDD
   * Normalizer prompt so the LLM generates more accurate steps.
   * Example: "This ticket tests Compact view. There are no column headers —
   * use the Sort By dropdown for all sorting."
   */
  pre_parse_guidance?: string;
  /**
   * Pre-confirmed AC steps from the human review flow.
   * When set, the LLM AC parser is skipped and these are used verbatim.
   */
  override_steps?: string[];
  /**
   * When true, login_node navigates to the login page but does NOT
   * authenticate. AC steps drive the login attempt with intentionally
   * wrong credentials to verify failure indicators (error toast, no JWT, etc.).
   */
  expect_login_failure?: boolean;
  /** Execution engine: "ai" (default) or "static" */
  execution_engine?: "ai" | "static";
  /** ID of a static Playwright test (required if execution_engine="static") */
  playwright_test_id?: string;
  /** Active product slug (e.g. "vpromedia", "vtrade") — scopes KB, personas, and product context */
  product?: string;
  /** Admin email for Ghost Login pre-flight — bypasses the mid-run credential gate */
  ghost_admin_email?: string;
  /** Admin password for Ghost Login pre-flight */
  ghost_admin_password?: string;
}

/**
 * Response from POST /preview-steps?ticket_id=...
 * Returns parsed AC steps for human review before execution.
 */
export interface PreviewStepsResponse {
  ticket_id: string;
  summary: string;
  acceptance_criteria: string;
  /** LLM-parsed steps — editable before confirming */
  steps: string[];
  /** Quality gate status: 'rejected', 'poor', 'fair', 'good' */
  parse_quality?: string;
  /** Human-readable reason for rejection or low score */
  parse_quality_reason?: string;
  /** Navigation paths detected via '>' notation. Empty for single-path tickets. */
  detected_paths?: string[];
  /** Vague terms or missing test data surfaced from the AC. */
  ambiguities?: string[];
  /** True when at least one parsed step is a GHOST_LOGIN step requiring Admin credentials. */
  has_ghost_login?: boolean;
  /**
   * True when the word "ghost" appears in the Jira ticket description.
   * The frontend prompts for email/password which are sent as override_email/override_password,
   * superseding stored role credentials and skipping the preflight auth check.
   */
  has_ghost_description?: boolean;
}



/**
 * Response from POST /execute.
 * Returned immediately after the run is queued.
 */
export interface ExecuteResponse {
  /** Internal unique run identifier (UUID-based, used for WS/S3 routing) */
  run_id: string;
  /** Human-readable label, e.g. "QA-280 · Account Executive · 4/2 2:44 PM" */
  run_label: string;
  /** Initial status — always "running" */
  status: RunStatus;
  /** WebSocket URL for real-time log streaming */
  stream_url: string;
  /** noVNC URL for live browser view (interactive mode only) */
  novnc_url: string | null;
}


// ---------------------------------------------------------------------------
// Status Polling
// ---------------------------------------------------------------------------

/**
 * Response from GET /status/{run_id}.
 * Provides progress tracking and artifact URLs.
 */
export interface StatusResponse {
  run_id: string;
  status: RunStatus;
  jira_ticket_id: string;
  role: string;
  duration_ms: number;
  ac_steps_total: number;
  ac_steps_completed: number;
  browser_actions: number;
  bugs_found: number;
  artifacts: ArtifactsInfo;
  novnc_url: string | null;
}

/**
 * Artifact URLs from a completed run.
 */
export interface ArtifactsInfo {
  /** S3 URL of the .webm session recording */
  video_url: string;
  /** S3 URL of the HTML audit report */
  report_url: string;
  /** S3 URLs of all step screenshots */
  screenshots: string[];
}


// ---------------------------------------------------------------------------
// Health Check
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: "ok" | "degraded";
  mode: ExecutionMode;
  version: string;
  build_number?: string;
  checks: {
    jira: "connected" | "not_checked" | "error";
    s3: "connected" | "not_checked" | "error";
    bedrock: "configured" | "not_checked" | "error";
  };
  uptime_seconds: number;
  active_runs: number;
  total_runs_completed: number;
}


// ---------------------------------------------------------------------------
// WebSocket Messages
// ---------------------------------------------------------------------------

/**
 * Per-action WebSocket message sent by the backend after each browser step.
 * Received by the ExecutionLog component for real-time display.
 */
export interface WSStepMessage {
  type: "step";
  step_index: number;
  timestamp: string;
  action_type: string;
  locator: string;
  success: boolean;
  screenshot_url: string;
  llm_reasoning: string;
}

/**
 * Terminal WebSocket message sent when a run completes or fails.
 * The client should close the WebSocket after receiving this.
 */
export interface WSTerminalMessage {
  type: "completed" | "failed";
  run_id: string;
  report_url: string;
  video_url: string;
  error: string;
  /** Number of AC steps that were fully validated */
  ac_steps_passed: number;
  /** Total number of AC steps in this run */
  ac_steps_total: number;
  /** Number of bugs/failures detected */
  bugs_found: number;
}

/**
 * Screenshot WebSocket message — sent after each planner iteration.
 * Carries the base64 PNG for the live browser panel.
 * Works on all platforms without noVNC or Xvfb.
 */
export interface WSScreenshotMessage {
  type: "screenshot";
  run_id: string;
  step_index: number;
  screenshot_b64: string;  // base64 PNG, no data URI prefix
  ac_step: number;
  ac_total: number;
}

/**
 * Thinking WebSocket message — sent before each step executes.
 * Carries the LLM reasoning for the live thinking panel.
 */
export interface WSThinkingMessage {
  type: "thinking";
  run_id: string;
  text: string;
  ac_step: number;
  ac_total: number;
}

/**
 * Triage WebSocket message — sent on FAILED runs before the terminal message.
 * Carries the LLM failure analysis for the TriagePanel UI.
 */
export interface WSTriageMessage {
  type: "triage";
  run_id: string;
  /** Overall failure classification */
  overall: "product_bug" | "agent_issue" | "mixed" | "unknown";
  /** 2-3 sentence executive summary for the product team */
  summary: string;
  /** Per-step classification list */
  steps: Array<{
    ac_index: number;
    ac_step: string;
    classification: "product_bug" | "agent_issue" | "passed";
    confidence: "high" | "medium" | "low";
    reason: string;
  }>;
  /** Pre-formatted Jira wiki-markup for manual posting */
  jira_comment: string;
}

export interface WSHumanTakeoverMessage {
  type: "human_takeover";
  run_id: string;
  /** The AC step the agent is stuck on */
  ac_step: string;
  /** 0-based AC step index */
  ac_step_index: number;
  /** Last error from the executor */
  error_message: string;
  /** Optional dynamic noVNC URL for takeover */
  novnc_url?: string | null;
}

/**
 * WebSocket message for real-time HITL screencast frames (MJPEG-over-WS).
 */
export interface WSHitlScreenshotMessage {
  type: "hitl_screenshot_update";
  run_id: string;
  data: string; // base64-encoded JPEG
}

/**
 * WebSocket message sent when a human action is echoed (real-time).
 */
export interface WSHitlActionRecordedMessage {
  type: "hitl_action_recorded";
  run_id: string;
  action: HitlActionRecord; // The captured action record
}

/**
 * Data structure for a single captured human action during takeover.
 */
export interface HitlActionRecord {
  run_id: string;
  event_type: string;
  timestamp: string;
  strategy?: string;
  best_selector?: string;
  text?: string;
  key?: string;
  direction?: string;
}

/**
 * WebSocket message for intercepted browser dialogs (alert/confirm/prompt).
 */
export interface WSHitlDialogMessage {
  type: "hitl_dialog_opened";
  run_id: string;
  message: string;
  dialog_type: string;
  default_value: string;
}

/**
 * WebSocket message broadcast when an unknown persona is encountered during
 * a PERSONA_SWITCH step and the operator must supply credentials.
 *
 * On receipt the frontend should show PersonaCredentialPanel with an
 * email + password form. The operator submits to
 * POST /runs/{run_id}/persona-credentials to unblock the agent.
 */
export interface WSPersonaCredentialsMessage {
  type: "HITL_PERSONA_CREDENTIALS_REQUIRED";
  run_id: string;
  /** The raw persona name string from the PERSONA_SWITCH AC step */
  persona_name: string;
  /** Human-readable prompt displayed above the credential form */
  message: string;
}

/**
 * WebSocket message broadcast when Admin credentials are required
 * for Ghost Login impersonation.
 */
export interface WSGhostCredentialsMessage {
  type: "GHOST_CREDENTIALS_REQUIRED";
  run_id: string;
  /** Human-readable prompt displayed above the credential form */
  message: string;
}

/**
 * A single AC step with its current execution status.
 * Embedded in WSAcProgressMessage to provide real-time updates.
 */
export interface WSAcStep {
  index: number;
  text: string;
  status: "pending" | "in_progress" | "passed" | "failed" | "skipped" | "awaiting_human";
  error: string;
  human_selector: string;
}

/**
 * WebSocket message broadcast whenever any AC step status changes.
 */
export interface WSAcProgressMessage {
  type: "ac_progress";
  run_id: string;
  steps: WSAcStep[];
}

/** Union type for all WebSocket messages */
export type WSMessage =
  | WSStepMessage
  | WSTerminalMessage
  | WSScreenshotMessage
  | WSThinkingMessage
  | WSTriageMessage
  | WSHumanTakeoverMessage
  | WSHitlScreenshotMessage
  | WSHitlActionRecordedMessage
  | WSHitlDialogMessage
  | WSPersonaCredentialsMessage
  | WSGhostCredentialsMessage
  | WSAcProgressMessage;


/**
 * Raw terminal log line from a Playwright subprocess.
 * Streamed line-by-line via WebSocket during a Playwright test run.
 */
export interface WSTerminalLogMessage {
  type: "terminal_log";
  run_id: string;
  /** Single stdout or stderr line (already scrubbed of secrets) */
  line: string;
  /** Source stream: "stdout" | "stderr" */
  stream: "stdout" | "stderr";
}


// ---------------------------------------------------------------------------
// Playwright Standard Library (FEAT-052 / TASK-060)
// ---------------------------------------------------------------------------

/**
 * A single entry from playwright/playwright_index.json.
 * Mirrors the backend registry format exactly.
 */
export interface PlaywrightTest {
  id: string;
  file: string;
  jira_keys: string[];
  description: string;
  steps_count: number;
  step_names: string[];
  display_name?: string;
}

/**
 * Request body for POST /playwright/run.
 */
export interface PlaywrightRunRequest {
  test_id: string;
  env: "prod" | "test" | "smoke" | "qa";
  user: string;
  browser: "chromium" | "firefox" | "webkit";
}

/**
 * Response from POST /playwright/run.
 */
export interface PlaywrightRunResponse {
  run_id: string;
  websocket_url: string;
  /** noVNC URL for live browser streaming (interactive mode only) */
  novnc_url: string | null;
}

/**
 * Per-user, per-environment session file status.
 * Status meanings:
 *   "valid"   — file exists and mtime < 24 hours ago
 *   "expired" — file exists but mtime >= 24 hours ago
 *   "missing" — file does not exist
 */
export type StorageStateStatus = "valid" | "expired" | "missing";

/**
 * Response from GET /playwright/storage/status.
 * A 13×4 matrix of session file validity.
 */
export interface PlaywrightStorageStatusResponse {
  environments: {
    [env in "prod" | "test" | "smoke" | "qa"]: {
      [username: string]: StorageStateStatus;
    };
  };
}

/**
 * Request body for POST /playwright/storage/generate.
 */
export interface PlaywrightStorageGenerateRequest {
  envs?: ("prod" | "test" | "smoke" | "qa")[];
}

/**
 * Response from POST /playwright/storage/generate.
 */
export interface PlaywrightStorageGenerateResponse {
  status: "ok";
  generated: number;
}

/**
 * Response from GET /playwright/storage/generate/status.
 * Used to poll background storage generation progress.
 */
export interface PlaywrightStorageGenerateStatusResponse {
  status: "idle" | "running" | "done" | "error";
  envs_requested: string[];
  envs_completed: string[];
  envs_failed: string[];
  error: string | null;
  started_at: number | null;
  finished_at: number | null;
}


/**
 * Request body for POST /playwright/run-group.
 */
export interface PlaywrightGroupRunRequest {
  test_ids: string[];
  env: "prod" | "test" | "smoke" | "qa";
  user: string;
  browser: "chromium" | "firefox" | "webkit";
}

/**
 * Request body for POST /playwright/run-all.
 */
export interface PlaywrightSuiteRunRequest {
  env: "prod" | "test" | "smoke" | "qa";
  user: string;
  browser: "chromium" | "firefox" | "webkit";
}

/**
 * Response from POST /playwright/run-all.
 */
export interface PlaywrightSuiteRunResponse {
  suite_run_id: string;
  status: "running";
  started_at: string;
}

/**
 * Result schema for a single test inside a parallel suite run.
 */
export interface PlaywrightSuiteResult {
  test_id: string;
  name: string;
  status: "PASS" | "FAIL" | "PENDING" | "RUNNING";
  duration_ms: number;
  error_snippet: string | null;
}

export interface FailureDigestEntry {
  test_id: string;
  name: string;
  error_summary: string;
}

/**
 * Response from GET /playwright/run-all/{suite_run_id}/report.
 */
export interface PlaywrightSuiteReportResponse {
  suite_run_id: string;
  status: "running" | "completed" | "failed";
  started_at: string;
  completed_at: string | null;
  total: number;
  passed: number;
  failed: number;
  results: PlaywrightSuiteResult[];
  outcome?: "PASS" | "FAIL" | null;
  fail_reason?: string | null;
  failure_digest?: FailureDigestEntry[] | null;
}

/**
 * Request body for POST /playwright/heal-prompt.
 */
export interface PlaywrightHealPromptRequest {
  run_id: string;
}

/**
 * Response from POST /playwright/heal-prompt.
 */
export interface PlaywrightHealPromptResponse {
  prompt: string;
}


// ---------------------------------------------------------------------------
// Credential Check
// ---------------------------------------------------------------------------

/**
 * Response from GET /ticket/{ticket_id}/credentials.
 * Used by the frontend to show inline credential prompts.
 */
export interface CredentialCheckResponse {
  ticket_id: string;
  status: "complete" | "partial" | "none";
  email_found: boolean;
  password_found: boolean;
  email: string;    // email found in ticket (empty if none)
  message: string;  // human-readable status message
}

/**
 * Response from POST /ticket/{ticket_id}/sync-ac.
 * Reports whether user-added ACs were successfully appended to the Jira ticket.
 */
export interface SyncACResponse {
  ticket_id: string;
  synced: boolean;
  added_count: number;
  /** The full AC text now on the Jira card (existing + appended) */
  new_ac_text: string;
  /** Whether the audit comment was posted to the ticket */
  comment_posted: boolean;
  error: string;
}

/**
 * Request body for POST /runs/{run_id}/persona-credentials.
 * Sent by PersonaCredentialPanel when the operator provides login
 * credentials for an unrecognised persona mid-test.
 */
export interface PersonaCredentialsRequest {
  /** The raw persona name from the HITL_PERSONA_CREDENTIALS_REQUIRED event */
  persona_name: string;
  /** Operator-provided login email */
  email: string;
  /** Operator-provided login password — never stored to disk */
  password: string;
}

/**
 * Request body for POST /runs/{run_id}/ghost-credentials.
 * Sent by GhostCredentialPanel when the operator provides login
 * credentials for the Admin user.
 */
export interface GhostCredentialsRequest {
  /** Operator-provided Admin login email */
  email?: string;
  /** Operator-provided Admin login password */
  password?: string;
  /**
   * [Experimental] Operator's SSO/app token from their active vQA session.
   * When provided, the backend injects it directly as the JWT in the Playwright
   * browser context, skipping the browser form login.
   * Either sso_token OR email+password must be present.
   */
  sso_token?: string;
}

/**
 * A single step in the AC preview/confirmation editor.
 * Tracks provenance so the frontend knows which steps to sync to Jira.
 */
export interface PreviewStep {
  /** The step text content */
  text: string;
  /** Where this step originated: 'jira' = parsed from ticket, 'user_added' = typed by user */
  source: 'jira' | 'user_added';
}


// ---------------------------------------------------------------------------
// Enums & Constants
// ---------------------------------------------------------------------------

/** Execution mode */
export type ExecutionMode = "interactive" | "headless";

/** Run lifecycle status */
export type RunStatus = "queued" | "running" | "completed" | "failed";

/**
 * Supported vProMedia user role keys.
 * Must match VALID_ROLES in backend/api/schemas.py.
 */
export type RoleKey =
  | "account_executive"
  | "sales_manager"
  | "sales_assistant"
  | "production_manager"
  | "producer"
  | "gm_gsm"
  | "dubber"
  | "digital_director"
  | "demo_prod_director"
  | "vpromotions_user"
  | "vtrade_exec"
  | "vtrade_business_manager"
  | "vtrade_sales_manager"
  | "vppo_account_executive"
  | "vppo_digital_director"
  | "vppo_dubber"
  | "vppo_gm_gsm"
  | "vppo_producer"
  | "vppo_production_manager"
  | "vppo_sales_assistant"
  | "vppo_sales_manager"
  | "vppo_traffic_manager"
  | "vppo_voicer"
  | "vppo_writer";

/**
 * Human-readable role display names.
 * Used in the role selector dropdown.
 */
export const ROLE_DISPLAY_NAMES: Record<RoleKey, string> = {
  account_executive: "Account Executive",
  sales_manager: "Sales Manager",
  sales_assistant: "Sales Assistant",
  production_manager: "Production Manager",
  producer: "Producer",
  gm_gsm: "GM / GSM",
  dubber: "Dubber",
  digital_director: "Digital Director/Producer",
  demo_prod_director: "Demo Prod Director",
  vpromotions_user: "vPromotions User",
  vtrade_exec: "vTrade Exec",
  vtrade_business_manager: "vTrade Business Manager",
  vtrade_sales_manager: "vTrade Sales Manager",
  vppo_account_executive: "vPPO Account Executive",
  vppo_digital_director: "vPPO Digital Director / Producer",
  vppo_dubber: "vPPO Dubber",
  vppo_gm_gsm: "vPPO GM / GSM",
  vppo_producer: "vPPO Producer",
  vppo_production_manager: "vPPO Production Manager",
  vppo_sales_assistant: "vPPO Sales Assistant",
  vppo_sales_manager: "vPPO Sales Manager",
  vppo_traffic_manager: "vPPO Traffic Manager",
  vppo_voicer: "vPPO Voicer",
  vppo_writer: "vPPO Writer",
};

/**
 * All supported role keys as an array.
 * Used to populate the role selector dropdown.
 */
export const ALL_ROLES: RoleKey[] = Object.keys(ROLE_DISPLAY_NAMES) as RoleKey[];

/**
 * Backend API base URL.
 * In development, the Vite dev server proxies to localhost:8000.
 * In production, we use the current origin.
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  (typeof window !== "undefined" ? `${window.location.origin}/api` : "http://localhost:8000");

/**
 * WebSocket base URL for log streaming.
 */
export const WS_BASE_URL =
  import.meta.env.VITE_WS_URL ||
  (typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
    : "ws://localhost:8000");


// ---------------------------------------------------------------------------
// Codegen Demo Recording
// ---------------------------------------------------------------------------

export interface CodegenStartRequest {
  ticket_id: string;
  ticket_summary: string;
  target_url: string;
}

export interface CodegenStartResponse {
  session_id: string;
  stream_url: string;
  novnc_url?: string | null;
}

export interface CodegenTransformations {
  auth_applied: boolean;
  date_helpers: number;
  nav_helpers: number;
  fragile_warnings: number;
  captcha_helpers: number;
}

export interface CodegenDoneEvent {
  test_file: string;
  test_path: string;
  commit_hash: string;
  branch: string;
  pr_url: string;
  run_id: string;
  lines: number;
  transformations?: CodegenTransformations;
}
