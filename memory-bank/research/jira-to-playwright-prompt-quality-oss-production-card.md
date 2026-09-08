## Spike Card: OSS / Production

**Work slug**: jira-to-playwright-prompt-quality   |   **Status**: DEGRADED
**run_id**: 20260715-c5e7c39abca4
**framing_sha**: c5e7c39abca4
**approved_depth**: deep
**approved_lanes**: academic, oss-production, practitioner-discourse, docs, codebase
**MCP used**: FALLBACK (WebSearch/WebFetch)
**mcp_servers_available**: none
**fallback_used**: yes
**Sources consulted**: 18

> Status DEGRADED: github-search MCP unavailable. All repo stats retrieved via WebSearch + WebFetch fallback. Star counts and commit dates are point-in-time scrapes (2026-07-15), not authoritative API responses. Coverage depth reduced for GitHub Issues and PyPI download time-series.

---

### Findings

| Source | Type | Evidence Grade | Key Finding | Implications |
|--------|------|----------------|-------------|--------------|
| [Instructor PyPI — v1.15.4 (Jun 2026)](https://pypi.org/project/instructor/) | repo/registry | B | 1M+ monthly downloads; latest stable Jun 28 2026; MIT license; Bedrock extra available; maintained by jxnl | Actively maintained with strong adoption signal — highest-signal structured-output library available for Python + Bedrock stack. `source_tool: WebFetch/PyPI` |
| [Instructor Bedrock integration docs](https://python.useinstructor.com/integrations/bedrock/) | doc | B | Two modes: TOOLS (function calling for Claude) and MD_JSON (text fallback). Legacy BEDROCK_TOOLS/BEDROCK_JSON aliases deprecated. No guaranteed schema compliance — relies on model cooperation + retry. | Current Instructor/Bedrock integration is best-effort, not deterministic. Validation failure triggers retry loop; cost scales with failure rate. `source_tool: WebFetch` |
| [Instructor GitHub Issue #2084 — native Bedrock structured outputs](https://github.com/567-labs/instructor/issues/2084) | issue | C | As of issue date, Instructor has not yet implemented Bedrock's native `outputConfig.textFormat` (Feb 2026 feature). Still uses prompt-injection (BEDROCK_JSON) or basic toolConfig (BEDROCK_TOOLS). | Gap: Instructor on Bedrock today is not using constrained decoding — it is prompt-engineering-based enforcement only. Closing this gap requires tracking upstream PR. `source_tool: WebFetch` |
| [AWS Bedrock structured outputs official docs](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html) | doc (A-tier source) | A | Constrained decoding via `outputConfig.textFormat` (Converse API) or `output_config.format` (InvokeModel). Supported for Claude 4.5+ only. Grammar compiled on first use (up to minutes), then cached 24h. Strict tool use via `strict: true` flag also available. | Native structured output with schema enforcement exists on Bedrock — but only for Claude 4.5+, NOT Claude 3.5 Sonnet (current vQA model). Model upgrade required to access deterministic enforcement. `source_tool: WebFetch` |
| [Bedrock structured outputs — schema restrictions](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html) | doc | A | Not supported: recursive schemas, external `$ref`, numerical constraints (`minimum`/`maximum`), string length constraints, `additionalProperties` ≠ `false`. `anyOf`/`allOf` supported with limitations. | vQA's test-plan JSON schema must be audited against this subset before adopting native structured outputs. Complex union types or optional nested fields may not compile. `source_tool: WebFetch` |
| [fourtheorem — Bedrock structured outputs analysis](https://fourtheorem.com/amazon-bedrock-structured-outputs/) | B-tier blog (named org) | B | Three failure modes persist even with constrained decoding: (1) token-limit truncation cuts JSON mid-object; (2) safety refusals override structural constraints; (3) semantically invalid output (hallucinated field values) is structurally valid JSON. Grammar compilation timeout is a 4th documented failure. | Constrained decoding eliminates parse failures but does not solve semantic fidelity — the core vQA quality problem. Safety refusals and token truncation remain live failure modes requiring runtime handling. `source_tool: WebFetch` |
| [AWS What's New — structured outputs GA (Feb 2026)](https://aws.amazon.com/about-aws/whats-new/2026/02/structured-outputs-available-amazon-bedrock/) | doc | A | Structured outputs generally available for Claude Sonnet 4.5, Claude Haiku 4.5, Claude Opus 4.5/4.6, Claude Sonnet/Opus 4.7, Claude Sonnet 5. Claude 3.x family explicitly excluded. | Claude 3.5 Sonnet (vQA's current model) is confirmed not supported for native structured outputs. Any adoption path requires model upgrade. `source_tool: WebSearch` |
| [langchain-aws Issue #883 — native structured outputs for Converse API](https://github.com/langchain-ai/langchain-aws/issues/883) | issue | C | `ChatBedrockConverse.with_structured_output()` currently uses forced tool calling, not native `outputConfig`. Native support is tracked but not yet merged as of issue date. | vQA uses `ChatBedrockConverse` — the abstraction layer does not yet route to native structured outputs even when the underlying model supports it. Two gaps must close simultaneously: model upgrade AND langchain-aws implementation. `source_tool: WebFetch` |
| [langchain-aws known bugs — ChatBedrockConverse](https://github.com/langchain-ai/langchainjs/issues/6349) | issue | C | Documented bugs: (1) `strict` parameter rejected (TypeError) in streaming agents; (2) tool description length=0 triggers ParamValidationError; (3) model-specific limitations — structured output via forced tool-calling fails for models without tool-calling support; (4) Nova model incompatibility (ModelErrorException). | Forced tool-calling path in `with_structured_output()` has multiple model-specific failure modes in production. These are active GitHub issues, not fixed. Retry chains over `ChatBedrockConverse` inherit these failure surfaces. `source_tool: WebSearch` |
| [Instructor production failure rate data](https://tensoria.fr/en/blog/structured-outputs-llm-production) | C-tier blog | C | Prompt-only JSON generation fails 3–5% of production requests. Instructor with 3 retries reduces observable failure rate to <0.05% for well-designed schemas, but 2x P50 latency on first retry, 3x on second. 5% failure rate + 2 retries → ~8–10% token cost increase. | Baseline: current vQA JSON Compiler without structured enforcement likely has 3–5% structural failure rate. Instructor-style retry is effective but adds latency variance and cost overhead. `source_tool: WebSearch` |
| [Guardrails AI — GitHub](https://github.com/guardrails-ai/guardrails) | repo | B | 7.2k stars; v0.10.2 (Jun 4 2026); 26 open issues; 68 releases; Apache 2.0. RAIL-based validator with Guardrails Hub (65+ pre-built validators). No AWS Bedrock-specific integration documented in README. | Maintained and growing, but no confirmed Bedrock adapter. RAIL XML schema format differs significantly from Pydantic/JSON Schema — integration cost with existing vQA LangGraph + Pydantic stack is non-trivial. `source_tool: WebFetch` |
| [DSPy — GitHub releases](https://github.com/stanfordnlp/dspy/releases) | repo | B | 36.2k stars; v3.2.1 stable (May 5 2025); releases every 1–3 months; typed provider-neutral LM boundary in v3.3 beta. Stanford NLP origin. 160k+ monthly pip downloads per prior search. | Strong adoption signal. DSPy's optimizer approach (MIPROv2) targets prompt quality improvement through automatic few-shot selection and instruction tuning — directly relevant to vQA's BDD Normalizer quality gap. `source_tool: WebFetch` |
| [DSPy Bedrock/Claude support — GitHub Issue #1150](https://github.com/stanfordnlp/dspy/issues/1150) | issue | C | June 2024 issue: DSPy did not support Bedrock Messages API required for Claude 3. Status of resolution unclear from search results — issue thread referenced but content not fully verified. | DSPy's Bedrock support for Claude 3.x was an open problem as recently as Jun 2024. Current status (v3.2.1) unconfirmed. [SOURCE UNVERIFIED — issue content not fetched directly] `source_tool: WebSearch` |
| [vladikoff/playwright-ai — GitHub](https://github.com/vladikoff/playwright-ai) | repo | C | 60 stars; 9 commits; experimental/under development; generates Playwright tests from URLs via Claude or GPT-4; no acceptance criteria input; generated tests include failures requiring manual fixes. | Thin adoption, no AC-to-test pipeline, explicitly experimental. Not a viable OSS component for vQA's Jira-to-Playwright path as-is. `source_tool: WebFetch` |
| [shinesolutions/ai-jira-test-demo — GitHub](https://github.com/shinesolutions/ai-jira-test-demo) | repo | C | 0 stars; 5 commits; Claude Sonnet 4.5; generates structured docs (JSON/CSV/MD) from Jira AC; Playwright generation explicitly not implemented ("can be extended but is not implemented"). | Proof-of-concept only — confirms the Jira-to-structured-doc pipeline is achievable but shows Playwright generation is the unsolved hard part, not the AC parsing. `source_tool: WebFetch` |
| [Playwright MCP — official Playwright project](https://playwright.dev/) | repo | B | Playwright MCP (Model Context Protocol) shipped March 2025; Playwright Agents shipped October 2025; 90k GitHub stars on core repo. MCP enables LLM-driven browser control through Playwright. | Playwright MCP shifts test generation from code generation to LLM-directed browser interaction — a different architecture than vQA's current code-gen approach. Relevant as an alternative execution model, not a drop-in. `source_tool: WebSearch` |
| [LangChain PydanticOutputParser + RetryOutputParser](https://api.python.langchain.com/en/latest/output_parsers/langchain_core.output_parsers.pydantic.PydanticOutputParser.html) | doc | A | RetryOutputParser and RetryWithErrorOutputParser wrap primary parsers; feed error + original output back to model with correction instruction. Supports `max_retries` configuration. Works with `ChatBedrockConverse` via `include_raw` mode. | RetryOutputParser is already available in vQA's LangChain dependency — zero-library-add option for retry-on-validation-failure. However, it uses prompt-engineering correction, not constrained decoding. `source_tool: WebSearch` |
| [TECHSY — 8 LLM Structured Output Libraries Ranked (2026)](https://techsy.io/en/blog/best-llm-structured-output-libraries) | C-tier aggregator | C | Instructor ranked #1 by monthly downloads (1M+). Other ranked libraries: Outlines, LM Format Enforcer, Guidance, Marvin, Mirascope, Guardrails AI, jsonformer. Outlines and LM Format Enforcer use constrained decoding for local/self-hosted models. | Constrained-decoding libraries (Outlines, LM Format Enforcer) require model-level access — not compatible with managed Bedrock API calls. Confirms Instructor as the practical choice for cloud LLM providers. `source_tool: WebSearch` |

---

### TRAP Candidates

1. **Claude 3.5 Sonnet excluded from Bedrock native structured outputs** — AWS native constrained decoding (Feb 2026) supports Claude 4.5+ only. vQA's current model (Claude 3.5 Sonnet) cannot use this feature without a model upgrade. Adopting Bedrock structured outputs as a solution assumes a model upgrade that has its own latency/cost/compatibility implications. (sources: AWS docs A-grade, fourtheorem B-grade)

2. **Instructor on Bedrock is prompt-engineering enforcement, not constrained decoding** — As of Jul 2026, Instructor's Bedrock integration (issue #2084) has not implemented native `outputConfig.textFormat`. Using Instructor with Bedrock today is best-effort with retry loops, not guaranteed schema compliance. This is a significant gap if Instructor is adopted expecting deterministic output. (sources: Instructor issue #2084 C-grade, Instructor docs B-grade)

3. **ChatBedrockConverse `with_structured_output()` uses forced tool-calling with documented bugs** — The `strict` parameter rejection bug (TypeError), zero-length tool description error, and model-specific incompatibilities are open GitHub issues. A retry chain built on top of a buggy forced-tool-calling path compounds failure modes. (sources: langchain-aws issues #775, #359, #183 — C-grade)

4. **Retry loops have compounding cost and latency: not free** — A 3–5% structural failure rate with 3 retries adds 8–10% token cost and 2–3x latency variance on failing requests. For vQA's batch mode over many Jira tickets, retry cost can become a significant operational expense if the base schema is poorly matched to model output tendencies. (source: tensoria.fr C-grade — cost statistics not independently verified at A/B level)

5. **Guardrails AI — no confirmed Bedrock adapter; RAIL format migration cost** — Guardrails AI uses XML-based RAIL schema, which is a parallel ecosystem to Pydantic/JSON Schema used by vQA's existing stack. Migrating to Guardrails requires schema translation and adds a dependency on a 7.2k-star project with a different validation paradigm. No Bedrock integration documented. (source: GitHub repo B-grade)

6. **DSPy Bedrock/Claude 3.x support was an open issue as of Jun 2024** — Unresolved as of last verified information. DSPy's automatic prompt optimization is compelling for vQA's quality gap, but if Bedrock/Claude compatibility is incomplete in v3.2.1, integrating DSPy may require switching LLM provider or adding a proxy layer (e.g., LiteLLM/Portkey). (source: GitHub issue #1150 C-grade; DSPy status unverified at current version)

7. **OSS Jira-to-Playwright gap is unresolved in the ecosystem** — No mature OSS pipeline exists that takes Jira AC as input and emits runnable Playwright test code as output. The closest projects (ai-jira-test-demo, playwright-ai) are proofs-of-concept with 0–60 stars and incomplete implementations. vQA's two-stage pipeline is ahead of the OSS field for this specific problem shape.

---

### Open Questions

1. **Does langchain-aws Issue #883 have an open PR or merged fix?** The issue was open at fetch time, but a PR may have been merged in a recent langchain-aws release — this would change the native structured output availability for `ChatBedrockConverse` without a model upgrade.

2. **What is DSPy's current Bedrock + Claude 3.x compatibility status in v3.2.1?** Issue #1150 raised in Jun 2024 is unverified as resolved. DSPy's optimizer value for vQA is high (automated few-shot + instruction tuning), but it cannot be recommended without confirming Bedrock/Claude 3.5 Sonnet works end-to-end.

3. **Does vQA's current test-plan JSON schema comply with Bedrock's structured output subset?** The schema must be audited against Bedrock's restrictions (no recursive refs, no `minLength`/`maximum`, `additionalProperties: false` everywhere, `anyOf` with ≤ N members) before a model upgrade would unlock native constrained decoding.

4. **What is the actual structural failure rate of the current JSON Compiler in production?** The 3–5% industry baseline may not apply to vQA's specific prompt + Claude 3.5 Sonnet combination. Without measuring current failure rate, the cost-benefit of retry logic or structured enforcement cannot be calculated.

5. **Is Instructor's planned native Bedrock structured output implementation (issue #2084) on a tracked roadmap with a release date?** The issue was open with no timeline. If it ships, the integration path changes materially — Instructor + Bedrock would become a constrained-decoding solution without requiring a model upgrade (if Claude 3.5 Sonnet is also added to the supported model list).

6. **Do Playwright MCP / Playwright Agents represent a viable alternative architecture?** These ship an LLM-directed browser control model rather than code generation. Worth evaluating whether vQA's test execution layer could absorb Playwright MCP as an execution target, removing the code-generation quality problem by changing the abstraction.

---

### Libraries/Repos Evaluated

| Name | Stars | Last commit | Adoption signal | Maintained? |
|------|-------|-------------|-----------------|-------------|
| [instructor (567-labs)](https://github.com/567-labs/instructor) | n/a (PyPI: 1M+/mo downloads) | Jun 28 2026 (v1.15.4) | 1M+ monthly PyPI downloads; listed as #1 by download volume in 2026 rankings | yes |
| [guardrails-ai/guardrails](https://github.com/guardrails-ai/guardrails) | 7.2k | Jun 4 2026 (v0.10.2) | 65+ Hub validators; 68 releases; Apache 2.0 | yes |
| [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | 36.2k | May 5 2026 (v3.2.1 stable) | 160k+ monthly pip downloads; hundreds of production projects claimed | yes |
| [langchain-ai/langchain-aws](https://github.com/langchain-ai/langchain-aws) | n/a | active (multiple 2025 issues) | Core dependency of vQA; langchain-aws ecosystem broadly adopted | yes |
| [vladikoff/playwright-ai](https://github.com/vladikoff/playwright-ai) | 60 | unknown | 9 commits; experimental tag | unclear |
| [shinesolutions/ai-jira-test-demo](https://github.com/shinesolutions/ai-jira-test-demo) | 0 | unknown (5 commits) | Proof-of-concept only | unclear |
| [microsoft/playwright](https://github.com/microsoft/playwright) | 90k+ | active | MCP server (Mar 2025), Agents (Oct 2025) shipped | yes |
