"""
vQA — Codegen Transformer
=========================
Module: backend/engine/codegen_transformer.py

Transforms raw Playwright codegen output into a maintainable test that uses
the project's existing helper utilities (setup.ts, NavHelper, OrderHelper,
QO_helpers, CaptchaHelper).

Called by codegen_session.py after the user closes the recording browser,
before the test file is written to disk or committed to GitHub.

Uses Claude Sonnet (via Bedrock) to intelligently rewrite the test — not a
brittle regex pass. Claude receives the full helper API surface as context so
it knows exactly what substitutions are available.
"""

import asyncio
import logging
import re
from pathlib import Path

import boto3

from backend.config import settings

logger = logging.getLogger(__name__)

# ─── Helper API surface injected into the Claude prompt ────────────────────
# Describes every available utility so Claude knows what it can use.
# Keep this in sync with the actual helper files.

_HELPER_API = """
## Available Helpers

### setup.ts — Auth Fixture (ALWAYS use this; never write a login block)
```typescript
import { test, expect, BASE_URL } from '../utils/setup';

// Place before the test() call to inject storage-state auth
test.use({ user: 'DemoProdDirector' });

// Available user shorthands (from imail-test+{Shorthand}@vcreativeinc.com):
// DemoProdDirector | DemoGM | DemoSalesExec | DemoDigitalDir | DemoDigitalProd
// DemoGraphicArtist | DemoProdMan | DemoProdWoman | DemoTrafficAssnt
// DemoTrafficDirector | DemoVoicer | writer | Admin
```

### QO_helpers.ts — Data Generators (never hardcode these values)
```typescript
import {
    generateRandomISCI,        // returns "ABCD-1234" style string
    generateRandomSpotTitle,   // returns "QUICKLY PRIME STORM" style string
    generateRandomCartId,      // returns unique 4-digit number (use String() if filling a field)
    generateUniqueClientName,  // returns "Test Client 1234"
    calculateDueDate,          // returns "MM/DD/YYYY" — 7-11 weekdays from today (skips weekends)
    calculateStartDate,        // returns "MM/DD/YYYY" — 14-22 days from today
    calculateEndDate,          // returns "MM/DD/YYYY" — 90-94 days from today
    calculateDueDateTime,      // returns Date object — now + 90 min (time-based due dates)
    demoScripts,               // { demo30sScript: string, demo60sScript: string }
    demoNotes,                 // { prodNotes, digitalNotes, trafficNotes, blogNotes, creativeNotes }
} from '../utils/QO_helpers';

// Usage: declare at test scope, pass to fill()
const spotTitle = generateRandomSpotTitle();
const spotIsci  = generateRandomISCI();
const dueDate   = calculateDueDate();
await page.getByRole('textbox', { name: 'Spot title' }).fill(spotTitle);
```

### NavHelper.ts — Sidebar Navigation
```typescript
import { goToFolder, openSpot, scrollToFolder } from '../utils/NavHelper';

// Navigate to a folder — handles lazy-load, scroll, and badge counts
await goToFolder(page, 'All');       // system folders: All, Inbox, MyBox, Drafts, Archived
await goToFolder(page, 'Inbox');
await goToFolder(page, 'My Custom Search');  // also works for saved searches

// Open a specific spot/order by its POID
await openSpot(page, poid);
```

### OrderHelper.ts — Order Form Interactions
```typescript
import {
    openQuickOrderForm,
    selectAdType,
    fillDateField,
    submitOrder,
} from '../utils/OrderHelper';

// Fill a PrimeNG datepicker by typing the date string directly (robust, no calendar clicks)
// Use this instead of any recorded calendar day-click sequence
await fillDateField(page, page.getByRole('combobox', { name: 'Due Date' }),   calculateDueDate());
await fillDateField(page, page.getByRole('combobox', { name: 'Start Date' }), calculateStartDate());
await fillDateField(page, page.getByRole('combobox', { name: 'End Date' }),   calculateEndDate());
```

### CaptchaHelper.ts — reCAPTCHA
```typescript
import { resolveCaptcha } from '../utils/CaptchaHelper';
// Use if codegen recorded interactions with the reCAPTCHA iframe
await resolveCaptcha(page);
```
"""

# ─── System prompt ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = f"""You are a Playwright test refactoring expert for the vCreative vProMedia platform.
Your sole job is to transform raw Playwright codegen output into a clean, production-ready test
that uses the project's existing helpers. Apply every rule below precisely.

{_HELPER_API}

## Transformation Rules

### Auth (ALWAYS apply)
1. Detect the user shorthand from the recorded email: `imail-test+{{Shorthand}}@vcreativeinc.com`.
2. Delete the ENTIRE login block: the `page.goto` to the login URL, the email fill, the password fill,
   and the login button click (or `.press('Enter')`). Also delete any Tab keypresses used only to move
   between login fields.
3. Change `import {{ test, expect }} from '@playwright/test'` to
   `import {{ test, expect, BASE_URL }} from '../utils/setup'`.
4. Insert `test.use({{ user: '{{Shorthand}}' }})` on the line immediately before the `test(` call.
5. If codegen recorded a reCAPTCHA interaction (iframe with title "reCAPTCHA"), replace it with
   `await resolveCaptcha(page)` and add the CaptchaHelper import.

### URLs
6. Replace every hardcoded environment domain
   (qa.vcreative.net, two-test.vcreative.net, smoketest.vcreative.net, vcreative.net)
   with the BASE_URL template literal: `` `${{BASE_URL}}` `` + the path portion.
   Strip any session-specific query parameters (`?user=NNNNNN`, `?session=...`).
   A bare login URL (`/#/login`) can simply be removed since auth is now handled by the fixture.

### Navigation
7. When codegen clicks a sidebar folder link (`page.getByRole('link', {{ name: 'All' }})` etc.),
   replace with `await goToFolder(page, 'FolderName')` and add the NavHelper import.

### Dynamic Data
8. Any `.fill()` on a field named 'Spot title', 'Title', or 'Name' that contains a literal string
   → replace the literal with `generateRandomSpotTitle()` declared as `const spotTitle = ...` at
   test scope, and use `spotTitle` in subsequent assertions too.
9. Any `.fill()` where the value matches the pattern `[A-Z]{{4}}-\\d{{4}}` (ISCI codes)
   → replace with `generateRandomISCI()` declared as `const spotIsci = ...` at test scope.
10. Any `.fill()` where the value matches `MM/DD/YYYY` date format on a Due Date field
    → replace with `calculateDueDate()`.
    Start Date field → `calculateStartDate()`.
    End Date field → `calculateEndDate()`.
11. Any `.fill()` on a Cart ID field with a 4-digit number → `String(generateRandomCartId())`.
12. If demoScripts or demoNotes values appear verbatim in fills, replace with the appropriate
    property reference.

### Calendar Date Pickers (replace entirely)
13. A "calendar interaction sequence" is: a click on a combobox with name 'MM-DD-YYYY' or
    'MM/DD/YYYY', followed by one or more `getByText(single-or-double-digit, {{ exact: true }}).click()`
    calls that navigate and pick a date. Replace the ENTIRE sequence with:
    `await fillDateField(page, page.getByRole('combobox', {{ name: '...' }}), calculateDueDate());`
    Add the OrderHelper import. Match the helper (Due/Start/End) by the surrounding field label context.

### Long Dynamic Text (replace, never keep verbatim)
14. Any `getByText('...')`, `.fill('...')`, or `toHaveText('...')` where the string is longer than
    60 characters is almost certainly dynamic content (AI-generated scripts, AI refusals, user-typed
    notes) that will differ on every run. Replace as follows:
    - If it is a `.fill()` on a script/notes field and the text resembles a broadcast script or
      production note, replace with `demoScripts.demo30sScript` or the appropriate `demoNotes`
      property and add the QO_helpers import (same as rule 12).
    - Otherwise, shorten the assertion to the first 5–8 words as a partial substring match:
      `await expect(someLocator).toContainText('first few words');`
      and add directly above:
      `// ⚠️ FRAGILE: Exact text was AI-generated or user-typed at record time and will vary on re-run.`
    Never leave a string longer than 60 characters verbatim in getByText / toHaveText / fill unless
    it exactly matches a demoScripts or demoNotes constant.

### Fragile Pattern Warnings (add comment, keep the line)
15. Any locator matching `#table-checkbox-\\d+` or `#action-button-row-\\d+` or any ID ending in a raw database number → add directly above:
    `// ⚠️ FRAGILE: Row ID is tied to a specific record. Locate by title, ISCI, or name instead.`
16. Locators using `tr:nth-child(N)` or `td:nth-child(N)` → add directly above:
    `// ⚠️ FRAGILE: Positional selector depends on row order. Use .filter({{ hasText: identifier }}) instead.`
17. `getByText('specific-user@email.com')` or `getByRole('cell', {{ name: 'specific-user@' }})` → add directly above:
    `// ⚠️ FRAGILE: Depends on a specific user existing. Use a fixture or create the user in test setup.`
18. `page.getByRole('button', {{ name: '\\d+' }})` where the number clearly refers to a page number
    (pagination) → add directly above:
    `// ⚠️ FRAGILE: Hardcoded pagination page. Data count may change across runs.`

### Imports
19. Only include imports for helpers you actually use. Never add unused imports.
20. Declare all generator constants (`const spotTitle = ...`, `const spotIsci = ...`, `const dueDate = ...`)
    at the top of the test function body, before any interactions.

### Step Annotations
21. Group related browser actions into logical QA milestones using `await test.step('Step name', async () => {{ ... }})`.
    Step names must be concise (3–8 words), action-oriented, and free of technical jargon.
    Good examples: "Navigate to production orders", "Create new request", "Set status to Needs Producing", "Verify polish button is visible", "Confirm script polish".
    Aim for 3–8 steps per test. Every `await` in the test body must be inside a step block.
    Generator constant declarations (`const spotTitle = ...`) stay outside step blocks, at the top of the test body.

## Output Format
Return ONLY the transformed TypeScript. No markdown fences. No explanation. No commentary.
The output must be valid TypeScript that Playwright can execute directly.
"""


# ─── Public API ─────────────────────────────────────────────────────────────


async def transform_recorded_test(raw_code: str, ticket_id: str) -> str:
    """
    Transform raw Playwright codegen TypeScript into a maintainable test.

    Uses Claude Sonnet (Bedrock) with the full helper API surface as context.
    Falls back to the original raw_code if the Bedrock call fails, so the
    codegen pipeline is never blocked by a transformer error.

    Args:
        raw_code: The TypeScript output from `playwright codegen`.
        ticket_id: Used for log messages only.

    Returns:
        Transformed TypeScript string.
    """
    code, _ = await transform_and_analyze(raw_code, ticket_id)
    return code


async def transform_and_analyze(raw_code: str, ticket_id: str) -> tuple[str, dict | None]:
    """
    Transform raw Playwright codegen TypeScript and return a transformation summary.

    Returns:
        (transformed_code, analysis_dict) on success, or (raw_code, None) if
        the Bedrock call fails (graceful degradation — pipeline is never blocked).
    """
    logger.info("[transformer:%s] Transforming %d-line codegen output", ticket_id, raw_code.count("\n"))

    try:
        transformed = await _call_bedrock(raw_code)
        transformed = _strip_fences(transformed)
        logger.info("[transformer:%s] Transformation complete (%d lines)", ticket_id, transformed.count("\n"))
        return transformed, _analyze_transformations(transformed)
    except Exception as exc:
        logger.warning(
            "[transformer:%s] Bedrock transform failed — using raw codegen output. Error: %s",
            ticket_id,
            exc,
        )
        return raw_code, None


# ─── Internal ───────────────────────────────────────────────────────────────


async def _call_bedrock(raw_code: str) -> str:
    bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_bedrock_region)

    # Use Sonnet for code-quality transformation (same model as heavy vision tasks)
    model_id = settings.bedrock_model_id_heavy

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        "Transform the following raw Playwright codegen recording into a "
                        "production-ready test using the project helpers. "
                        "Return only the transformed TypeScript.\n\n"
                        f"```typescript\n{raw_code}\n```"
                    )
                }
            ],
        }
    ]

    system = [{"text": _SYSTEM_PROMPT}]

    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: bedrock.converse(
            modelId=model_id,
            system=system,
            messages=messages,
            inferenceConfig={
                "maxTokens": 4096,
                "temperature": 0.0,
            },
        ),
    )

    content_blocks = response["output"]["message"].get("content", [])
    for block in content_blocks:
        text = block.get("text", "").strip()
        if text:
            return text

    raise ValueError("Bedrock returned an empty response")


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if the model wrapped the output anyway."""
    text = re.sub(r"^```(?:typescript|ts)?\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text.strip())
    return text.strip()


def _extract_step_names(code: str) -> list[str]:
    """Parse test.step('Name', ...) calls and return the step name strings in order."""
    return re.findall(r"test\.step\s*\(\s*['\"]([^'\"]+)['\"]", code)


def _analyze_transformations(transformed_code: str) -> dict:
    """
    Inspect transformed TypeScript and return a summary of what was applied.

    Returns:
        dict with keys: auth_applied (bool), date_helpers (int),
        nav_helpers (int), fragile_warnings (int), captcha_helpers (int),
        step_names (list[str])
    """
    auth_applied = bool(
        re.search(r"test\.use\s*\(", transformed_code)
        or "from '../utils/setup'" in transformed_code
    )

    date_helpers = len(re.findall(
        r"calculate(?:DueDate|StartDate|EndDate|DueDateTime)\s*\(",
        transformed_code,
    ))

    nav_helpers = len(re.findall(r"goToFolder\s*\(", transformed_code))

    fragile_warnings = len(re.findall(r"//\s*⚠️ FRAGILE:", transformed_code))

    captcha_helpers = len(re.findall(r"resolveCaptcha\s*\(", transformed_code))

    step_names = _extract_step_names(transformed_code)

    return {
        "auth_applied": auth_applied,
        "date_helpers": date_helpers,
        "nav_helpers": nav_helpers,
        "fragile_warnings": fragile_warnings,
        "captcha_helpers": captcha_helpers,
        "step_names": step_names,
    }
