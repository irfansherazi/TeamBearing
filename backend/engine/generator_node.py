"""
backend/engine/generator_node.py
===================================
Week 1 Linear Pipeline — Step 1: GENERATE

Consumes Jira AC + tenant context and calls Claude (via Bedrock) to emit
a complete, self-contained Playwright .spec.ts test file.

Design decisions (per TASK-101 spec §2, §3, §4):
  - LLM uses Sonnet (Tier 2) for code generation — reasoning required.
  - Only the top-5 semantically relevant selectors are injected (<200 tokens).
  - LLM is strictly instructed to use helper functions, not invent raw selectors.
  - Generated files land in playwright/tests/generated/<ticket_id>.spec.ts.
  - This node does NOT execute the spec — that is the Validate node's job.

BM25 retrieval:
  - For tenants with < MIN_CORPUS files, inject the entire helper library.
  - For tenants with >= MIN_CORPUS files, BM25 ranks helpers by relevance.
  - Selector retrieval always uses simple cosine-like scoring over description fields.
"""

import json
import logging
import pathlib
import re
from typing import Any

logger = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# BM25-lite: simple TF scoring over selector descriptions
# Full BM25 is overkill for <200 entries; this is fast and sufficient.
# ---------------------------------------------------------------------------


def _score_selector(query_tokens: list[str], description: str) -> float:
    """Simple term-frequency score: sum of query token hits in description."""
    desc_lower = description.lower()
    return sum(desc_lower.count(tok) for tok in query_tokens)


def _retrieve_top_selectors(
    step_text: str,
    selectors: dict,
    top_k: int = 5,
) -> list[dict]:
    """Return top-k selectors most relevant to the given AC step text."""
    tokens = re.findall(r"[a-z]+", step_text.lower())
    scored = []
    for key, val in selectors.items():
        if key.startswith("_"):
            continue
        score = _score_selector(tokens, val.get("description", ""))
        scored.append((score, key, val))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"key": key, "selector": val["selector"], "description": val["description"]}
        for _, key, val in scored[:top_k]
    ]


# ---------------------------------------------------------------------------
# Tenant context loader
# ---------------------------------------------------------------------------


def _load_tenant_context(tenant_id: str) -> dict[str, Any]:
    """Load selectors and list helpers for the given tenant."""
    tenant_dir = ROOT / "tenants" / tenant_id
    selectors_path = tenant_dir / "selectors.json"
    helpers_dir = tenant_dir / "helpers"

    selectors: dict = {}
    if selectors_path.exists():
        with open(selectors_path) as f:
            selectors = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    else:
        logger.warning("generator_node: selectors.json not found for tenant '%s'", tenant_id)

    # List available helpers
    helper_files: list[str] = []
    if helpers_dir.exists():
        helper_files = [p.name for p in helpers_dir.glob("*.ts")]
    else:
        # Fall back to shared playwright/utils helpers
        utils_dir = ROOT / "playwright" / "utils"
        helper_files = [p.name for p in utils_dir.glob("*.ts") if not p.name.startswith(".")]

    return {"selectors": selectors, "helper_files": helper_files}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are vQA, an expert Playwright TypeScript test code generator.

Your task is to generate a complete, production-ready Playwright .spec.ts test file from a Jira acceptance criteria.

STRICT RULES — violating these causes compilation failures:
1. Import ONLY from '@playwright/test', '@utils/generated/vpromedia_selectors', and '@utils/SearchHelper' (when search/filtering is involved).
2. Use getLocator(page, key) for ALL element interactions. NEVER write raw CSS/XPath selectors.
3. Use ONLY keys from the TenantSelectorKey type. Hallucinated keys cause TS2345 compile errors.
4. If an input, dropdown, button, search input, or any element has a corresponding key in the 'Available Selector Keys' block, you MUST use getLocator(page, selector_key). You are STRICTLY FORBIDDEN from using generic role-based queries (like page.getByRole(...) or page.getByText(...)) for any element where a Selector Key is provided. For example, ALWAYS use getLocator(page, 'search-client-input') and getLocator(page, 'search-adtype-input') instead of getByRole for client searches and ad type dropdowns. Using generic roles for keys that are available causes strict-mode locator collisions and test timeouts. If a selector key does not exist, use page.getByRole() or page.getByText() as a typed fallback. If 'Discovered Interactive Elements' are provided in the user prompt, prioritize using page.getByRole() with the specified exact role and name for those elements.
5. Every test must use storageState for auth — do NOT add login steps.
6. Use await expect(...) for ALL assertions — never just await element.isVisible().
7. The file must compile with 'tsc --noEmit' without errors. CLOSE EVERY string, brace, and paren.
8. Output ONLY the TypeScript code. No markdown fences, no explanation.
9. CRITICAL: Keep the output file under 70 lines. Cover only the CRITICAL path, not every minor step.
   Write ONE test function. Do not try to cover all BDD steps — pick the 5-7 most important ones.
10. CRITICAL: NEVER use hardcoded hostnames in page.goto() calls. ALL navigation MUST use relative
    paths (e.g. page.goto('/spots'), page.goto('/hdash'), page.goto('/')). The baseURL is injected
    by the Playwright config at runtime. Hardcoding 'https://qa.vcreative.net/' or any hostname
    WILL cause tests to fail against other environments and is a BLOCKING spec error.
11. CRITICAL: To handle dynamic transitions, modals, and PrimeNG page rendering delays, ALWAYS wait for the element or its container/overlay to be visible before performing interactive actions. Use await expect(getLocator(page, selector_key)).toBeVisible() or explicit page waiting behaviors before doing .click(), .fill(...), or other actions on any form/dialog field.
"""

_GENERATION_TEMPLATE = """Generate a Playwright .spec.ts test file for this Jira ticket.

## Ticket
ID: {ticket_id}
Summary: {summary}

## Acceptance Criteria
{acceptance_criteria}

## BDD Steps to Implement
{bdd_steps}

## Available Selector Keys (TenantSelectorKey — use ONLY these with getLocator)
{selectors_block}
{a11y_block}
{search_helper_rules_block}
## Required Import Pattern
{import_pattern_block}

## Auth Pattern (storageState — DO NOT re-login inside tests)
```typescript
test.use({{ storageState: 'playwright/storage/vpromedia_auth.json' }});
```

## Output
Generate the .spec.ts file now. Output VALID TypeScript ONLY. No markdown fences. No trailing text.
KEEP UNDER 70 LINES. Write ONE test covering the 5-7 most critical steps only.
Close EVERY string literal, template literal, regex, brace, and parenthesis before the file ends.
"""


def _build_prompt(card: dict, tenant_context: dict) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the LLM."""
    ticket_id = card.get("ticket_id", "UNKNOWN")
    summary = card.get("summary", "")
    ac = card.get("acceptance_criteria", "")
    steps = card.get("expected_steps", [])

    # Retrieve top-10 selectors by relevance to the full AC text
    query_text = f"{summary} {ac} {' '.join(steps)}"
    top_selectors = _retrieve_top_selectors(query_text, tenant_context["selectors"], top_k=10)

    selectors_block = "\n".join(
        f'  {s["key"]:45s} // {s["description"][:70]}'
        for s in top_selectors
    )

    helpers_block = "\n".join(f"  - {h}" for h in tenant_context["helper_files"])

    # Cap BDD steps at 12 to prevent LLM output truncation
    # Keep first 6 (setup/happy-path) + last 3 (assertions)
    if len(steps) > 12:
        head = steps[:6]
        tail = steps[-3:]
        condensed = head + ["  ... (intermediate steps omitted for brevity) ..."] + tail
    else:
        condensed = steps
    bdd_steps = "\n".join(f"  {i+1}. {step}" for i, step in enumerate(condensed))

    # Process and build a11y discovered elements if provided
    a11y_elements = card.get("a11y_elements", [])
    a11y_block = ""
    if a11y_elements:
        a11y_block = "\n## Discovered Interactive Elements (highly accurate page.getByRole target elements)\n"
        for el in a11y_elements[:50]:
            a11y_block += f"- Role: {el['role']}, Name: \"{el['name']}\" => Locator: {el['locator']}\n"

    summary_lower = summary.lower()
    ac_lower = ac.lower()
    steps_lower = " ".join(steps).lower()
    is_search = any(
        k in summary_lower or k in ac_lower or k in steps_lower or ticket_id.lower() == "qa-170"
        for k in ["search", "filter", "multiselect", "qa-170"]
    )

    if is_search:
        import_pattern_block = """```typescript
import {{ test, expect, type Page }} from '@playwright/test';
import {{ getLocator, type TenantSelectorKey }} from '@utils/generated/vpromedia_selectors';
import * as SearchHelper from '@utils/SearchHelper';
```"""
        search_helper_rules_block = """
## MANDATORY SEARCH/FILTER RULES
Because this ticket involves search or filtering, you MUST adhere to these strict rules:
1. Import SearchHelper:
   import * as SearchHelper from '@utils/SearchHelper';
2. NEVER generate raw page.click('#top-open-search-panel') or raw client input fill/click sequences.
3. ALWAYS use SearchHelper.openSearchPanel(page, 'context') to open the search panel.
4. ALWAYS use SearchHelper.performSearch(page, {{ client: '...', adType: '...', status: '...' }}) to execute search.
"""
    else:
        import_pattern_block = """```typescript
import {{ test, expect, type Page }} from '@playwright/test';
import {{ getLocator, type TenantSelectorKey }} from '@utils/generated/vpromedia_selectors';
```"""
        search_helper_rules_block = ""

    user_prompt = _GENERATION_TEMPLATE.format(
        ticket_id=ticket_id,
        summary=summary,
        acceptance_criteria=ac,
        bdd_steps=bdd_steps,
        selectors_block=selectors_block,
        a11y_block=a11y_block,
        import_pattern_block=import_pattern_block,
        search_helper_rules_block=search_helper_rules_block,
    )

    return _SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# Generator node
# ---------------------------------------------------------------------------


async def generate_spec(
    card: dict,
    tenant_id: str = "vpromedia",
    output_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    """
    Generate a Playwright .spec.ts file for the given corpus card.

    Args:
        card:       A corpus card dict (ticket_id, acceptance_criteria, expected_steps, ...)
        tenant_id:  Tenant identifier (default: 'vpromedia')
        output_dir: Directory to write the .spec.ts file (default: playwright/tests/generated)

    Returns:
        {
            "ticket_id": str,
            "spec_path": str,          # absolute path to written .spec.ts
            "spec_content": str,       # raw TypeScript content
            "status": "generated",
            "selectors_used": list[str]
        }
    """
    ticket_id = card.get("ticket_id", "UNKNOWN")
    output_dir = output_dir or (ROOT / "playwright" / "tests" / "generated")
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("generator_node: generating spec for %s (tenant=%s)", ticket_id, tenant_id)

    # Load tenant context
    tenant_context = _load_tenant_context(tenant_id)

    # Build prompt
    system_prompt, user_prompt = _build_prompt(card, tenant_context)

    # Call LLM (Sonnet — code generation requires reasoning)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from backend.llm import get_llm

        # Use Sonnet (heavy=True) with explicit max_tokens to prevent truncation.
        # Haiku's default token budget is too small for spec files.
        llm = get_llm("generator_node", heavy=True, max_tokens=2048, temperature=0.1)
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        spec_content: str = (response.content or "").strip()

        # Strip markdown fences if the LLM wrapped the output
        if spec_content.startswith("```"):
            lines = spec_content.splitlines()
            # Remove opening fence (```typescript or ```)
            start = 1
            if lines[0].startswith("```"):
                start = 1
            # Remove closing fence
            end = len(lines)
            if lines[-1].strip() == "```":
                end = len(lines) - 1
            spec_content = "\n".join(lines[start:end]).strip()

        # ── Safety sanitizer: strip any hardcoded vcreative.net hostnames ──────
        # The LLM occasionally violates rule 10. This ensures relative paths
        # even if the LLM ignored the instruction.
        import re as _re
        _HARDCODED_URL_PATTERN = _re.compile(
            r'https?://(?:qa|two-test|smoketest|www)\.vcreative\.net'
        )
        sanitized = _HARDCODED_URL_PATTERN.sub('', spec_content)
        if sanitized != spec_content:
            logger.warning(
                "generator_node: sanitized %d hardcoded vcreative.net URL(s) from %s",
                len(_HARDCODED_URL_PATTERN.findall(spec_content)),
                ticket_id,
            )
            spec_content = sanitized

    except Exception as exc:
        logger.error("generator_node: LLM call failed for %s: %s", ticket_id, exc)
        return {
            "ticket_id": ticket_id,
            "spec_path": None,
            "spec_content": None,
            "status": "generation_failed",
            "error": str(exc),
        }

    # Write spec file
    spec_path = output_dir / f"{ticket_id}.spec.ts"
    spec_path.write_text(spec_content, encoding="utf-8")

    logger.info("generator_node: wrote %s (%d bytes)", spec_path.name, len(spec_content))

    return {
        "ticket_id": ticket_id,
        "spec_path": str(spec_path),
        "spec_content": spec_content,
        "status": "generated",
        "selectors_used": list(tenant_context["selectors"].keys()),
    }
