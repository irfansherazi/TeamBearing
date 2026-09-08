# C4 Component: Test Source Adapters

## Component Metadata

- **Component Name**: test-source-adapters
- **Run ID**: c4-2026-05-08-001
- **Generated**: 2026-05-08T00:00:00Z
- **Constituent Code Docs**: 3
  - `c4-code-backend-adapters.md` (backend/adapters — 6 files)
  - `c4-code-backend-jira.md` (backend/jira — 2 files)
  - `c4-code-backend-profiles.md` (backend/profiles — 4 files)

---

## Overview

The **Test Source Adapters** component is the acceptance-criteria ingestion boundary of the vQA system. It abstracts all external test sources behind a single `TestSourceAdapter` interface, fetches and normalises AC text regardless of origin (Jira, GitHub, or raw input), and supplies the resulting structured data to the LangGraph engine for planning and execution.

The component also houses the **Application Profiles** subsystem, which encapsulates all vendor-specific configuration — authentication strategies, DOM selectors, RBAC role definitions, and LLM prompt fragments — into pluggable, self-contained `AppProfile` instances. This eliminates hardcoded vendor configuration from the engine, enabling multi-application support without modifying core code.

### Responsibilities

1. Fetch acceptance criteria from Jira REST API v3 (primary source), GitHub Issues REST API, or raw text input
2. Auto-detect the correct adapter from an identifier string without requiring an explicit source type
3. Parse Atlassian Document Format (ADF) from Jira responses into plain text
4. Provide role credentials and RBAC metadata for test execution personas
5. Inject vendor-specific domain knowledge (DOM selectors, glossary, prompt rules) into the engine at runtime
6. Expose a health-check endpoint for Jira API connectivity validation

---

## Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | **Unified AC Fetch Interface** | All adapters implement `TestSourceAdapter.fetch_ac(identifier)` returning a normalised `ACResult`. Engine code has zero coupling to any specific source. |
| 2 | **Auto-Detection Factory** | `adapter_factory.detect_source_type()` applies regex priority rules (GitHub URL → GitHub shorthand → Jira key pattern → raw text) to resolve the adapter without caller input. |
| 3 | **Jira REST API v3 Client** | Full async HTTP client (`backend/jira/client.py`) covering ticket fetch, ADF-to-text conversion, credential extraction from AC text, board ticket listing, and comment posting. |
| 4 | **Pluggable Application Profiles** | `AppProfile` dataclass is the plugin contract. Profiles self-register at import time; `get_active_profile()` resolves via `VQA_PROFILE` env var with `"vsuite"` as default. |
| 5 | **RBAC Role Definitions** | Each `RoleDefinition` carries credentials (environment-variable-driven), permission flags, and natural-language constraint strings injected into the planner prompt. |
| 6 | **LLM Prompt Injection** | `AppProfile` stores domain glossary, framework rules, workflow rule triggers, and few-shot examples as strings; the engine reads these fields to vary LLM behaviour per target application. |

---

## Interfaces

### TestSourceAdapter ABC (`backend/adapters/base.py`)

```
TestSourceAdapter
  async fetch_ac(identifier: str) -> ACResult
    Parameters : source-specific identifier string
    Returns    : ACResult(ticket_id, summary, description, acceptance_criteria,
                          source_type, raw_metadata)
    Raises     : ValueError (invalid/empty identifier)
                 RuntimeError (source unreachable or HTTP error)
```

### Concrete Adapters

| Adapter | Identifier Format | Delegates To |
|---------|-------------------|--------------|
| `JiraAdapter` | `VC2-8967` (Jira key) | `backend.jira.client.fetch_ticket_context()` |
| `GitHubAdapter` | `https://github.com/o/r/issues/42` or `o/r#42` | GitHub REST API (httpx) |
| `RawTextAdapter` | Any plain text | Self (wraps text; generates `RAW-{UUID8}` ticket ID) |

### Adapter Registry (`backend/adapters/__init__.py`)

```
get_adapter(source_type: str = "jira") -> TestSourceAdapter
  Parameters : "jira" | "github" | "raw_text"
  Raises     : ValueError (unknown type — includes available list)

resolve_adapter_auto(identifier: str) -> TestSourceAdapter
  Delegates to adapter_factory.resolve_adapter(); auto-detects type
```

### Jira Client (`backend/jira/client.py`)

```
fetch_ticket_context(ticket_id: str) -> JiraTicketContext
  GET /rest/api/3/issue/{ticket_id}
  Raises : JiraClientError (401, 404, other non-200), httpx.HTTPError

validate_jira_connectivity() -> bool
  GET /rest/api/3/myself

fetch_board_tickets(project: str = "QA", board_ids: list[int] | None = None) -> list[dict]
  GET /rest/agile/1.0/board/{id}/issue  (paginated)

post_jira_comment(ticket_id: str, body: str) -> bool
  POST /rest/api/3/issue/{ticket_id}/comment  (ADF payload)
```

### Application Profiles (`backend/profiles/__init__.py`)

```
get_active_profile(override: Optional[str] = None) -> AppProfile
  Resolution order: override → VQA_PROFILE env var → "vsuite" (default)

ProfileRegistry.register(profile: AppProfile) -> None
ProfileRegistry.get(name: str) -> AppProfile          # raises KeyError
ProfileRegistry.get_active(override: Optional[str] = None) -> AppProfile
ProfileRegistry.list_profiles() -> list[str]
ProfileRegistry.is_registered(name: str) -> bool
```

### AppProfile Plugin Contract (key fields)

```
AppProfile
  Identity       : name, display_name, description
  Authentication : login_url_path, auth_verification, jwt_storage_key,
                   login_form_selectors (LocatorStep fallback chains)
  Roles          : roles (dict[str, RoleDefinition]), default_password_env,
                   role_aliases
  DOM Sync       : app_root_selectors, spinner_selectors, detail_panel_selectors
  LLM Injection  : domain_glossary, framework_rules, workflow_rules,
                   workflow_rule_triggers, identity_prompt, system_boundary_rule,
                   few_shot_examples
```

### RoleDefinition

```
RoleDefinition
  display_name: str
  email: str                   # default; overridden by email_env_var
  email_env_var: str           # env var for email credential
  password_env_var: str        # env var for password (falls back to profile default)
  permissions: dict[str, bool] # RBAC flags for violation detection
  constraints: list[str]       # natural-language constraints injected into planner
```

---

## External Dependencies

| Dependency | Used By | Purpose |
|------------|---------|---------|
| **Jira REST API v3** (Atlassian Cloud) | `backend/jira/client.py` | Ticket fetch, board listing, comment posting; Basic Auth (email:api_token) |
| **Jira Agile REST API v1.0** (Atlassian Cloud) | `backend/jira/client.py` | Board/sprint ticket listing (`/rest/agile/1.0/board/{id}/issue`) |
| **GitHub REST API** | `backend/adapters/github_adapter.py` | Issue fetch + comment scan; optional Bearer auth via `GITHUB_TOKEN` |
| **httpx** | `github_adapter.py`, `jira/client.py` | Async HTTP client; 15 s timeout (GitHub), 30 s / 10 s timeouts (Jira) |

---

## Configuration (Environment Variables)

All configuration follows the 12-Factor Config-in-Environment principle. No credentials or URLs are hardcoded in production code paths.

| Variable | Component | Purpose |
|----------|-----------|---------|
| `JIRA_EMAIL` | Jira client | Service account email for Basic Auth |
| `JIRA_API_TOKEN` | Jira client | API token for Basic Auth |
| `JIRA_DOMAIN` | Jira client | Jira instance domain (e.g., `vcreative.atlassian.net`) |
| `GITHUB_TOKEN` | GitHubAdapter | Personal access token (optional; unauthenticated if absent) |
| `VQA_PROFILE` | Profile registry | Active application profile name (default: `"vsuite"`) |
| `VQA_AE_EMAIL` / `VQA_AE_PASSWORD` | vSuite role definitions | Per-role credential env vars (pattern repeated for all 9 roles) |
| `VQA_DEFAULT_PASSWORD` | vSuite profile | Shared password fallback for all vSuite roles |

---

## Internal Dependencies

| Dependency | Direction | Purpose |
|------------|-----------|---------|
| `backend.config.settings` | consumed | Jira credentials, `jira_base_url`, `github_token` |
| `backend.engine.state.JiraTicketContext` | consumed | Type definition for parsed Jira ticket data |
| `backend.engine` (graph, executor, planner, prompts) | consumed by | Engine reads profile fields and calls `fetch_ac()` |

---

## Architecture Patterns

### Pluggable Adapter Pattern
All test sources implement `TestSourceAdapter`. The engine calls `fetch_ac(identifier)` with no knowledge of the underlying source. Adding a new source (e.g., Azure DevOps, Linear) requires: (1) a new `TestSourceAdapter` subclass, (2) registration in `_ensure_registered()`, (3) an optional detection rule in `detect_source_type()`.

### Auto-Detection Factory
`adapter_factory.py` applies regex priority rules to resolve the adapter type without an explicit `source_type` parameter. Highest-specificity patterns (GitHub URL) are evaluated first; multi-line or unmatched input falls back to raw text.

### Lazy Registration
Adapters register on the first `get_adapter()` call to avoid circular imports at module load time.

### ADF Recursive Descent Parser
The Jira client implements a recursive descent parser (`_extract_text_from_adf`) covering all ADF node types (doc, paragraph, heading, bulletList, orderedList, listItem, codeBlock, hardBreak, text). Structural newlines are preserved.

### AC Fallback Chain (Jira)
`customfield_10031` (Acceptance Criteria) is the authoritative source. If empty, the ticket description is used as fallback. If both are empty, a warning is logged and an empty string returned.

### Plugin Contract Pattern (Profiles)
`AppProfile` is the vendor plugin contract. `ProfileRegistry` is the plugin loader. Profiles self-register at import time (`profile_registry.register(VSUITE_PROFILE)`). Consumers call `get_active_profile()` which resolves via environment variable, enabling profile switching without code changes.

### RBAC + Prompt Injection
`RoleDefinition.permissions` (dict of flags) drives verifier violation detection. `RoleDefinition.constraints` (list of strings) is injected into the planner prompt as natural-language guardrails. `AppProfile.domain_glossary` and `few_shot_examples` are injected into LLM prompts at runtime.

---

## Observability

- Structured logging at INFO/DEBUG/WARNING/ERROR levels across all modules
- Adapter resolution logged at INFO level (source type, identifier prefix)
- Jira client logs ticket_id, AC field sizes, requirements source, and credential status
- GitHub adapter logs HTTP errors with status codes and identifier
- Profile registry logs registration and resolution actions at DEBUG/INFO level
- All log messages designed to carry `traceId`/`spanId` for distributed tracing via OpenTelemetry

---

## Extensibility

To add a new test source adapter:
1. Create a class extending `TestSourceAdapter` with `async fetch_ac(identifier) -> ACResult`
2. Register it in `_ensure_registered()` (or call `get_adapter()` with the new type string)
3. Add a detection rule to `detect_source_type()` if auto-detection is desired

To add a new application profile:
1. Create a module (e.g., `backend/profiles/salesforce.py`) with an `AppProfile` instance
2. Call `profile_registry.register(SALESFORCE_PROFILE)` at module level
3. Import the module in `backend/profiles/__init__.py` (side-effect import triggers registration)
4. Set `VQA_PROFILE=salesforce` to activate

---

## vSuite Reference Profile (9 Roles)

| Role Key | Display Name | Key Permissions |
|----------|-------------|-----------------|
| `account_executive` | Account Executive | view_own_drafts only |
| `sales_manager` | Sales Manager | all-firm visibility + impersonation |
| `sales_assistant` | Sales Assistant | delegate access (actual_user_id) |
| `production_manager` | Production Manager | job delegation, POC/Cart/House assignment |
| `producer` | Producer | creative upload, spot_users visibility |
| `gm_gsm` | GM/GSM | full oversight, personal inbox |
| `dubber` | Dubber | QC-only, autodub triggering, no creation |
| `digital_director` | Digital Director | display ads only (product_type filter) |
| `voice_talent` | Voice Talent | voice request assignments, upload only |
