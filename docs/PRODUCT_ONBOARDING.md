# 🚀 Onboarding a New Product to vQA

> **A step-by-step guide for tech leads adding a new vCreative product
> to the vQA autonomous testing platform.**
>
> *Estimated time: 2–4 hours for a functional product · 1–2 days for production-ready coverage*

[![Products](https://img.shields.io/badge/Products_Registered-6-blue?style=flat-square)](../backend/config/products.yaml)
[![Knowledge](https://img.shields.io/badge/KB_Format-TF--IDF_Indexed-009688?style=flat-square)](../backend/kb/loader.py)
[![Selectors](https://img.shields.io/badge/Selector_Registry-JSON-FF6B35?style=flat-square)](../knowledge/selector_registry.json)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture — How Products Are Wired](#2-architecture--how-products-are-wired)
3. [Step 1 — Register in products.yaml](#3-step-1--register-in-productsyaml)
4. [Step 2 — Create the Directory Scaffold](#4-step-2--create-the-directory-scaffold)
5. [Step 3 — Write Knowledge Base Articles](#5-step-3--write-knowledge-base-articles)
6. [Step 4 — Build the Selector Registry](#6-step-4--build-the-selector-registry)
7. [Step 5 — Create Role Personas](#7-step-5--create-role-personas)
8. [Step 6 — Register Roles in the Backend](#8-step-6--register-roles-in-the-backend)
9. [Step 7 — Create Playwright Helpers](#9-step-7--create-playwright-helpers)
10. [Step 8 — Record Your First Test](#10-step-8--record-your-first-test)
11. [Complete File Checklist](#11-complete-file-checklist)
12. [Product Maturity Levels](#12-product-maturity-levels)
13. [Reference — vProMotions as a Model](#13-reference--vpromotions-as-a-model)
14. [Current Product Status](#14-current-product-status)

---

## 1. Overview

vQA supports multiple vCreative products — vProMedia, vTrade, vProMotions, vEP, vPPO,
and PSN — each with its own test environment, user roles, knowledge base, and Playwright
test suite. This guide walks you through every file, directory, and configuration needed
to onboard a new product so the AI agent can autonomously test it.

The system is designed so that **adding a YAML entry + creating three directories** is all
it takes for a stub product. No Python code changes required. From there, you progressively
add knowledge, selectors, and helpers to increase test reliability.

```
 What you create                    What the system does with it
 ──────────────────────────────     ─────────────────────────────────────────────
 products.yaml entry          →    Registers environments, roles, Jira boards
 knowledge/<slug>/*.md        →    TF-IDF indexed; injected into LLM prompts
 knowledge/personas/<slug>/   →    Resolves login credentials + role permissions
 selector_registry.json       →    Registry-First Gate: deterministic selectors
 playwright/utils/<slug>/     →    Pre-built helpers replace 100+ AI UI steps
 playwright/tests/<slug>/     →    Automated test suite
```

---

## 2. Architecture — How Products Are Wired

```
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                      Product Onboarding Flow                            │
 │                                                                          │
 │  ┌─────────────────────┐                                                │
 │  │  products.yaml      │  ← Single source of truth                     │
 │  │  (config)           │                                                │
 │  └────────┬────────────┘                                                │
 │           │  Pydantic validates at startup                              │
 │           ▼                                                             │
 │  ┌─────────────────────┐     ┌─────────────────────┐                   │
 │  │  product_registry.py│────►│  /products API      │───► React UI      │
 │  │  (Python loader)    │     │  (public metadata)  │                   │
 │  └────────┬────────────┘     └─────────────────────┘                   │
 │           │                                                             │
 │    ┌──────┴──────┬────────────┬────────────────┐                       │
 │    ▼             ▼            ▼                ▼                        │
 │  ┌──────┐   ┌────────┐  ┌─────────┐   ┌────────────┐                  │
 │  │ KB   │   │ Roles  │  │Selector │   │ Playwright │                  │
 │  │Loader│   │Registry│  │Registry │   │ Tests Dir  │                  │
 │  │      │   │        │  │         │   │            │                  │
 │  │ TF-  │   │ Creds  │  │ First   │   │ *.test.ts  │                  │
 │  │ IDF  │   │ Perms  │  │ Gate    │   │ helpers/   │                  │
 │  └──────┘   └────────┘  └─────────┘   └────────────┘                  │
 │                                                                          │
 │  knowledge/    knowledge/    knowledge/        playwright/              │
 │  <slug>/       personas/     selector_         tests/<slug>/            │
 │  *.md          <slug>/       registry.json     utils/<slug>/            │
 │                *.md                                                      │
 └──────────────────────────────────────────────────────────────────────────┘
```

### What happens at each stage

| Stage | What the system does |
|-------|------|
| **Startup** | `product_registry.py` loads `products.yaml` → validates → creates `ProductContext` objects. Checks that `knowledge/<slug>/` exists for active products. `roles.py` resolves credentials (AWS SSM → persona files → env vars). `loader.py` indexes all `knowledge/*.md` into TF-IDF. |
| **Query time** | KB loader lazily builds a **product-scoped index** from only `knowledge/<slug>/*.md`. Registry-First Gate checks product-scoped selectors. AC parser checks the helpers manifest to emit helper calls. |
| **Frontend** | `ProductContext.tsx` fetches `/products` on mount. `ProductSelector.tsx` renders the dropdown. Selected slug is passed to `/execute` as `product=<slug>`. |

---

## 3. Step 1 — Register in `products.yaml`

> **File:** `backend/config/products.yaml`

This is the **single source of truth** for all products. Add a new entry under the `products:` key.
The YAML key becomes the product `slug` — lowercase alphanumeric + underscores only.

```yaml
products:
  # ... existing products ...

  mynewproduct:
    display_name: MyNewProduct
    description: >-
      Brief description of what the product does and what
      workflows vQA will test.
    order: 7                      # Display sort order (ascending)
    environments:
      qa: https://mynewproduct-qa.vcreative.net
    default_environment: qa       # Auto-set when only one env exists
    # If auth happens at a different URL (shared SSO):
    # ghost_login_environments:
    #   qa: https://qa.vcreative.net
    jira_board_ids: [42, 99]      # Jira board IDs for ticket fetching
    # ticket_title_filter: "MyProduct"  # Filter shared boards
    roles:
      - mynewproduct_admin
      - mynewproduct_user
    playwright_tests_dir: playwright/tests/mynewproduct
    personas_dir: knowledge/personas/mynewproduct
```

> **💡 No Python code changes are required.** The `product_registry.py` Pydantic loader
> auto-discovers the entry at startup and validates all fields.

### Field reference

| Field | Required | Description |
|-------|:--------:|-------------|
| `display_name` | ✅ | Human-readable name shown in the UI |
| `description` | ✅ | Product description for docs and tooltips |
| `order` | ✅ | Sort position in the ProductSelector dropdown |
| `environments` | ✅ | Map of environment name → base URL |
| `default_environment` | Auto | Which env to use when none is specified |
| `ghost_login_environments` | — | Override login URL for shared-SSO products |
| `jira_board_ids` | ✅ | Board IDs for the `/tickets` endpoint |
| `ticket_title_filter` | — | Substring filter for shared Jira boards |
| `roles` | ✅ | Role keys (must match entries in `roles.py`) |
| `playwright_tests_dir` | ✅ | Path to the Playwright test directory |
| `personas_dir` | ✅ | Path to persona knowledge files |

### Startup validation

The registry validates at startup via `validate_product_kb_roots()`:

- ✅ Every **active** product (`roles` ≠ `[]`) must have `knowledge/<slug>/` present
- ⚠️ Missing `personas_dir` is a warning (non-fatal)
- ⏭️ Stub products (`roles: []`) are exempt from all validation

---

## 4. Step 2 — Create the Directory Scaffold

```bash
# From the repo root:
mkdir -p knowledge/mynewproduct
mkdir -p knowledge/personas/mynewproduct
mkdir -p playwright/tests/mynewproduct
mkdir -p playwright/utils/mynewproduct        # optional: product-specific helpers
```

Add `.gitkeep` files so Git tracks the empty directories:

**`knowledge/mynewproduct/.gitkeep`**
```
# T3-a Product Isolation — mynewproduct KB partition
# This directory contains KB workflow files scoped to the mynewproduct product.
# Files placed here are loaded ONLY when product="mynewproduct" KB queries are made.
```

**`knowledge/personas/mynewproduct/.gitkeep`**
```
# Persona files for mynewproduct roles.
```

**`playwright/tests/mynewproduct/.gitkeep`**
```
# Playwright tests for mynewproduct.
```

---

## 5. Step 3 — Write Knowledge Base Articles

> **Directory:** `knowledge/<slug>/`

These are the files the AI agent reads to understand **how your product works**. The
KB loader indexes them via TF-IDF for semantic search. Each `## WORKFLOW:` section
becomes an individually queryable document that gets injected into the LLM prompt
when the agent encounters a matching AC step.

### 5.1 — KB articles from the Knowledge Site (`kb-*.md`)

**Source:** https://vcreativeinc.com/knowledge/

Scrape or manually extract help articles from your product's section on the vCreative
Knowledge Base site. One file per feature category, multiple `## WORKFLOW:` blocks per file.

```markdown
# <Product> Help Center — <Category Name>
# =============================================
# Source: https://vcreativeinc.com/knowledge/<slug>#<category-anchor>
# Extracted: YYYY-MM-DD
# Product-scoped: only loaded for <slug> runs.

## WORKFLOW: <Descriptive Action Name>
KEYWORDS: keyword1, keyword2, keyword3, relevant terms
JIRA:
---
WHAT: One-sentence description of what the user is doing.
WHO: Which roles can perform this action.
WHERE: Where in the app this happens (page, modal, tab).
HOW: Step-by-step instructions:
1. First step.
2. Second step.
3. Third step.
CONSTRAINTS: Any limitations or prerequisites.
GOTCHAS: Non-obvious pitfalls the agent should watch for.
TEST-DATA HINTS: Example values for test runs.
```

**Example naming:** `kb-contests-and-giveaways.md`, `kb-sponsorships.md`, `kb-faq.md`

### 5.2 — Technical workflow docs (`wf-*.md`)

These are **developer-authored** files describing DOM structure, selectors, and
interaction patterns for key workflows. They are cited to the product's actual
source code.

| File | Purpose |
|------|---------|
| `wf-auth-and-sso.md` | Login flow, SSO redirect chain, cookie model |
| `wf-create-<entity>.md` | Primary create flow (e.g., create order, create campaign) |
| `wf-<entity>-file-upload.md` | File upload interactions |
| `wf-ghost-login.md` | Ghost/impersonation login (if applicable) |
| `wf-submit-cancel-<entity>.md` | Save / submit / cancel patterns |
| `wf-approve-<entity>.md` | Approval workflows |
| `wf-revise-<entity>.md` | Revision / edit workflows |

**Template:**

```markdown
# <Product> — <Workflow Name>
# ====================================
# Source: <product codebase reference>

## WORKFLOW: <Action description>
KEYWORDS: keyword1, keyword2, keyword3
---
Applies to <context>.

PRECONDITIONS:
- <What must be true before starting>
- <Selectors or elements that must be visible>

STEPS:

1. <Step description>
   <DOM details, selector, code citations>

2. <Step description>
   Wait conditions: ALL true:
     - <selector>:visible
     - <selector>:enabled

COMMON FAILURE:
- <Known failure mode and how to handle it>
```

### 5.3 — Runtime policy (`<entity>-form.md`)

Documents **fabricated test data defaults** and field inventories. The agent needs
to know what values to use when the AC doesn't specify them.

```markdown
# <Product> — Form Runtime Policy

## WORKFLOW: <Entity> fabricated test data policy for vQA runs
KEYWORDS: test data, fabricated data, defaults, safe defaults
---
POLICY (confirmed with the <Product> product owner):
   <Product> runs use fabricated test values for every field.
   Do NOT pause the run asking for real data.

RECOMMENDED DEFAULTS by field name:
   Title              → "Test <Entity> <TICKET-ID>"
   Start Date         → today + 7 days at 09:00 AM
   Description        → "Test description for <TICKET-ID>"
```

### 5.4 — Human guidance (`human_guidance.md`)

This file is **auto-generated** by the HITL takeover system when a human operator
confirms a working interaction pattern. Create an empty placeholder:

```markdown
# <Product> — Human Guidance (auto-appended by HITL takeover)
# ===============================================================
# The vQA HITL write-back appends ## WORKFLOW: blocks here when a human
# operator confirms a working interaction during takeover. Do NOT hand-edit.
```

---

## 6. Step 4 — Build the Selector Registry

> **File:** `knowledge/selector_registry.json` (global) **or**
> `knowledge/<slug>/selector_registry.json` (product-scoped)

The selector registry maps AC step patterns to Playwright selectors. It powers
the **Registry-First Gate** — the system tries deterministic selectors before
falling back to AI-driven element discovery.

### Option A — Add to the global registry

Add a product-scoped section in the global `knowledge/selector_registry.json`:

```json
{
  "selectors": {
    "mynewproduct": {
      "_schema": "T3-b product-scoped entries",
      "_version": "1.0",
      "login_email_field": {
        "ticket_seed": "QA-001",
        "ac_step_patterns": [
          "enter email",
          "fill email field",
          "type.*email"
        ],
        "target_semantic_name": "Login Email Input",
        "playwright_strategy": "get_by_role",
        "role": "textbox",
        "name": "Email",
        "vqa_id": "login-email-input",
        "protected": true,
        "seed_source": "manual",
        "captured_at": "2026-01-01",
        "context": "Login form email input field.",
        "timing_note": ""
      }
    }
  }
}
```

### Option B — Create a product-scoped registry

Create `knowledge/<slug>/selector_registry.json` with full site metadata:

```json
{
  "registryVersion": "1.0",
  "generated": "2026-01-01",
  "site": {
    "name": "Product Display Name",
    "baseUrl": "https://product-url",
    "entryPoint": "/",
    "appType": "Angular SPA",
    "stack": ["Angular", "PrimeNG", "TypeScript"],
    "authNote": "Session-cookie authenticated"
  },
  "conventions": {
    "noTestIds": "App has no data-test-id attributes",
    "tabRouting": "How tab navigation works",
    "modals": "How modals/dialogs work",
    "dataTables": "How data grids are structured"
  },
  "global": { },
  "pages": { }
}
```

> **💡 Start with the critical paths** — login, main create flow, primary navigation.
> Grow the registry incrementally as you write more tests. The vProMotions product
> registry is 1,730 lines covering every page and component.

---

## 7. Step 5 — Create Role Personas

> **Directory:** `knowledge/personas/<slug>/`

One `.md` file per role. These files serve two purposes:

1. **Credential resolution** — the `# LOGIN EMAIL:` line provides the fallback login email
2. **Permission context** — tells the AI agent what each role can and cannot do

**Template:**

```markdown
# Role: <Role Display Name> (<Abbreviation>)
# LOGIN EMAIL: imail-test+<RoleName>@vcreativeinc.com

## Core Responsibilities
- **Primary Action**: What this role mainly does.
- **Secondary Action**: Other key responsibilities.

## Permissions & Features
- **Create Records**: YES / NO
- **View All Records**: YES / NO
- **Edit Status**: YES / NO
- **Admin Access**: YES / NO

## Code-Specific Notes
- **Special Logic**: Any code-level behavior tied to this role.
```

### Credential resolution priority

The system resolves login credentials in this order:

```
 1. AWS Bedrock Roles KB  ─── production (SSM Parameter Store)
         │ (miss)
         ▼
 2. Local persona file    ─── knowledge/personas/<slug>/<role>.md
         │ (miss)                # LOGIN EMAIL: line
         ▼
 3. Environment variable  ─── ROLE_EMAIL_<KEY>
         │ (miss)
         ▼
 4. Profile fallback      ─── hardcoded in roles.py (last resort)
```

---

## 8. Step 6 — Register Roles in the Backend

> **File:** `backend/engine/roles.py`

Each role key listed in `products.yaml` must have a corresponding entry in the role registry.
Add three things:

**1. Environment variable mapping** (in `_resolve_credentials()`):
```python
"mynewproduct_admin": "ROLE_EMAIL_MYNEWPRODUCT_ADMIN",
"mynewproduct_user": "ROLE_EMAIL_MYNEWPRODUCT_USER",
```

**2. Hardcoded email fallbacks:**
```python
"mynewproduct_admin": "imail-test+MyNewProductAdmin@vcreativeinc.com",
"mynewproduct_user": "imail-test+MyNewProductUser@vcreativeinc.com",
```

**3. Role context entries** in `_build_registry()` with permissions and LLM constraints.

> **⚠️ A role key must appear in exactly ONE product.** Startup validation enforces
> mutual exclusivity across the entire registry.

---

## 9. Step 7 — Create Playwright Helpers

> **Directory:** `playwright/utils/<product>/`
>
> *Optional but strongly recommended for complex workflows.*

Pre-built Playwright helpers replace hundreds of AI-driven UI interactions with
deterministic code. The vProMotions product has **9 helpers** that cut execution
time from 20+ minutes to under 15 seconds per flow.

### Recommended helper structure

```
playwright/utils/<product>/
├── AuthHelper.ts              # Login + SSO + wait-for-ready
├── GhostLoginHelper.ts        # Ghost impersonation (if applicable)
├── Create<Entity>Helper.ts    # Main create flow
├── Approve<Entity>Helper.ts   # Approval flow
├── Revise<Entity>Helper.ts    # Edit / revision flow
└── Submit<Entity>Helper.ts    # Save / submit / cancel
```

### Document helpers in the knowledge base

Create a **helpers manifest** (`<product>-helpers-manifest.md`) in the knowledge directory.
The AC parser uses this to emit helper calls instead of raw click/fill primitives:

```markdown
# <Product> Playwright Helpers Manifest

## AC → Helper Fast-Match Table

| AC phrase pattern              | Helper call                       | Time   |
|--------------------------------|-----------------------------------|--------|
| "log in as <user>"             | `loginAndWaitForReady(page, ...)` | 5–8s   |
| "create a new <entity>"        | `createEntityHappyPath(page, ...)` | 8–12s  |
| "approve the <entity>"         | `approveEntity(page, id, role)`   | 2–3s   |
```

---

## 10. Step 8 — Record Your First Test

> **Feature:** Record a Demo (Codegen)
>
> *Instead of hand-writing Playwright tests, use vQA's built-in codegen recorder
> to demonstrate the correct flow in a real browser. The system auto-generates a
> production-ready `.test.ts` file, commits it to a branch, and opens a PR.*

### How it works

```
 YOU                              vQA
 ───                              ───
 1. Select a Jira ticket     →    Fetches AC + ticket metadata
 2. Click "Record Demo"      →    Launches `playwright codegen` subprocess
 3. Interact with the real   →    Records every action as TypeScript in real-time
    browser (login, navigate,
    fill forms, click buttons)
 4. Close the browser        →    Monitor detects exit, reads the raw output
                              →    LLM transformer cleans up the code:
                                     • Injects auth fixtures
                                     • Converts pixel clicks → semantic locators
                                     • Adds date helpers, nav helpers
                                     • Flags fragile selectors with ⚠️ TODO
                              →    Saves to playwright/tests/<slug>/<ticket>.test.ts
                              →    Updates playwright_index.json
                              →    Records a passed run in run_history.db
                              →    Commits to a codegen/<ticket> branch
 5. Click "Create PR"        →    Opens a GitHub PR with the generated test
    (or "Skip")
```

### Step-by-step

1. **Open the vQA dashboard** and select your product from the dropdown
2. **Select a Jira ticket** from the ticket list (or enter a ticket ID manually)
3. **Click "Record Demo"** — this appears in the execution panel, especially when
   AC parsing is degraded and the system suggests recording a demo
4. **Interact with the browser** that opens — perform the exact workflow described
   in the Jira ticket's Acceptance Criteria. Login, navigate, fill forms, click
   buttons, verify results — just as a human QA tester would
5. **Close the browser** when you're done — vQA detects the session end and
   processes the recording
6. **Review the generated test** — the codegen transformer applies LLM-powered
   cleanup:

   | Transformation | What it does |
   |----------------|--------------|
   | Auth fixture | Injects the login helper instead of raw credential fills |
   | Date helpers | Replaces hardcoded dates with dynamic `today + N` logic |
   | Nav helpers | Consolidates repeated navigation into helper calls |
   | CAPTCHA helpers | Replaces reCAPTCHA iframe interactions with bypass helpers |
   | Fragile warnings | Flags pixel-coordinate clicks with `TODO(codegen)` comments |

7. **Create a PR** (or skip) — vQA commits the test to a `codegen/<ticket>` branch
   and opens a GitHub Pull Request with the generated `.test.ts` file

### Why Record a Demo instead of hand-writing tests

- **Zero Playwright knowledge required** — the tech lead just uses the app normally
- **Deterministic selectors** — Playwright codegen records `getByRole`, `getByLabel`,
  and `getByText` locators, not fragile CSS selectors
- **LLM cleanup** — the codegen transformer applies product-aware transformations
  that would take manual effort to write correctly
- **Instant PR** — the test goes straight from recording → branch → PR with no
  manual file creation

### Output

The generated test is saved to `playwright/tests/<slug>/` and looks like this:

```typescript
/**
 * Generated by vQA codegen on 2026-08-06T16:30:00Z
 * Ticket: QA-500 — Verify login and dashboard load
 * Product: mynewproduct
 */
import { test, expect } from '@playwright/test';

test.describe('QA-500 — Verify login and dashboard load', () => {
  test('recorded flow', async ({ page }) => {
    await page.goto('https://mynewproduct-qa.vcreative.net');

    // Login
    await page.getByRole('textbox', { name: 'Email' }).fill('test@example.com');
    await page.getByRole('textbox', { name: 'Password' }).fill('password');
    await page.getByRole('button', { name: 'Login' }).click();

    // Verify dashboard loaded
    await expect(page).toHaveURL(/dashboard/);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });
});
```

---

## 11. Complete File Checklist

### 🔴 Required — product won't load without these

| # | File | Action |
|---|------|--------|
| 1 | `backend/config/products.yaml` | **MODIFY** — add product entry |
| 2 | `knowledge/<slug>/.gitkeep` | **CREATE** — product KB directory |
| 3 | `knowledge/personas/<slug>/.gitkeep` | **CREATE** — persona directory |
| 4 | `playwright/tests/<slug>/.gitkeep` | **CREATE** — test directory |

### 🟡 Required for active products (roles ≠ `[]`)

| # | File | Action |
|---|------|--------|
| 5 | `knowledge/<slug>/wf-auth-and-sso.md` | **CREATE** — login workflow docs |
| 6 | `knowledge/<slug>/kb-<category>.md` | **CREATE** — help center articles (1+ files) |
| 7 | `knowledge/personas/<slug>/<role>.md` | **CREATE** — one per role |
| 8 | `backend/engine/roles.py` | **MODIFY** — register role entries |
| 9 | `knowledge/selector_registry.json` | **MODIFY** — add product-scoped selectors |

### 🟢 Recommended — significant reliability improvement

| # | File | Action |
|---|------|--------|
| 10 | `knowledge/<slug>/wf-create-<entity>.md` | **CREATE** — main create workflow |
| 11 | `knowledge/<slug>/<entity>-form.md` | **CREATE** — test data defaults |
| 12 | `knowledge/<slug>/human_guidance.md` | **CREATE** — HITL placeholder |
| 13 | `knowledge/<slug>/<entity>-helpers-manifest.md` | **CREATE** — AC → helper mapping |
| 14 | `playwright/utils/<product>/AuthHelper.ts` | **CREATE** — deterministic login |
| 15 | `playwright/utils/<product>/Create<Entity>Helper.ts` | **CREATE** — main create flow |
| 16 | `knowledge/<slug>/selector_registry.json` | **CREATE** — product-specific selectors |

### 🔵 Optional — progressive enhancement

| # | File | Action |
|---|------|--------|
| 17 | `knowledge/<slug>/wf-ghost-login.md` | **CREATE** — ghost login docs |
| 18 | `knowledge/<slug>/wf-approve-<entity>.md` | **CREATE** — approval workflow |
| 19 | `knowledge/<slug>/wf-revise-<entity>.md` | **CREATE** — revision workflow |
| 20 | `knowledge/<slug>/create-<entity>-helper.md` | **CREATE** — CU-loop injection docs |

---

## 12. Product Maturity Levels

Products in vQA exist at different maturity levels. Use this framework to gauge where
yours is and what to tackle next:

```
 Stub ──────► Skeleton ──────► Functional ──────► Production ──────► Mature
 │             │                │                  │                  │
 │ YAML entry  │ + Directories  │ + Personas       │ + Full KB        │ + Test suite
 │ roles: []   │ + .gitkeep     │ + Auth workflow   │ + Selectors      │ + Blueprints
 │             │ + Roles defined│ + Basic KB         │ + Helpers        │ + Comprehensive
 │             │                │                    │ + HITL guidance  │   selector registry
 │             │                │                    │                  │
 │ vEP         │ vTrade         │ (—)               │ vProMotions      │ vProMedia
 │ vPPO        │                │                    │                  │
 │ PSN         │                │                    │                  │
```

---

## 13. Reference — vProMotions as a Model

vProMotions is the most fully documented product. Use it as your template:

| Layer | vProMotions files | Your equivalent |
|-------|-------------------|-----------------|
| **KB articles** (6) | `kb-promotion-request-forms-prfs.md` · `kb-contests-and-giveaways.md` · `kb-sponsorships.md` · `kb-liners-psas-and-live-mentions.md` · `kb-idea-requests-proposals.md` · `kb-faq.md` | `kb-<your-categories>.md` |
| **Workflows** (7) | `wf-auth-and-sso.md` · `wf-create-prf.md` · `wf-submit-cancel-prf.md` · `wf-prf-file-upload.md` · `wf-ghost-login.md` · `wf-approve-prf.md` · `wf-revise-prf.md` | `wf-<your-workflows>.md` |
| **Runtime policy** (1) | `prf-form.md` | `<entity>-form.md` |
| **Helper docs** (2) | `prf-helpers-manifest.md` · `create-prf-helper.md` | `<entity>-helpers-manifest.md` |
| **Selectors** (1) | `selector_registry.json` (1,730 lines) | `selector_registry.json` |
| **HITL guidance** (1) | `human_guidance.md` (auto-populated) | `human_guidance.md` |
| **Helpers** (9) | `AuthHelper.ts` · `CreatePrfHelper.ts` · `ApprovePrfHelper.ts` · `RevisePrfHelper.ts` · `SubmitOrCancelPrfHelper.ts` · `UploadPrfFilesHelper.ts` · `GhostLoginHelper.ts` · `FormbuilderHelper.ts` · `Select2v3Helper.ts` | Your `AuthHelper.ts` · `Create<Entity>Helper.ts` · etc. |

> **📂 Browse the reference files:**
> - Knowledge: `knowledge/vpromotions/`
> - Helpers: `playwright/utils/prf/`
> - Personas: `knowledge/personas/vpromedia/` (vProMedia has 11 populated personas)

---

## 14. Current Product Status

| Product | Slug | Maturity | Roles | KB Coverage | Selector Registry | Playwright Helpers |
|---------|------|----------|:-----:|-------------|-------------------|-------------------|
| **vProMedia** | `vpromedia` | ✅ Mature | 9 | 7 files · 2,500+ lines | 248 KB global | SearchHelper · OrderHelper · NavHelper + more |
| **vTrade** | `vtrade` | 🟡 Skeleton | 3 | `.gitkeep` only | Global entries | None |
| **vProMotions** | `vpromotions` | ✅ Production | 1 | 19 files · 280 KB | 67 KB product registry | 9 PRF helpers |
| **vEP** | `vep` | ⬜ Stub | 0 | `.gitkeep` only | None | None |
| **vPPO** | `vppo` | ⬜ Stub | 0 | `.gitkeep` only | None | None |
| **PSN** | `psn` | ⬜ Stub | 0 | `.gitkeep` only | None | None |

---

*Built by vCreative Engineering · See also: [README.md](../README.md) · [DEPLOYMENT.md](../DEPLOYMENT.md)*
