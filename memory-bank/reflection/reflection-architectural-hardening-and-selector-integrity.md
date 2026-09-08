# Reflection: architectural-hardening-and-selector-integrity — Architectural Hardening & Selector Integrity

## Context
This task was initiated to address core reliability issues in vQA: flakiness in the execution loop, amnesic behavior regarding failing selectors, and poor visibility of human intervention prompts.

## Key Changes
1.  **Immediate Escalation**: By lowering the Sonnet escalation threshold to `retry_count >= 1` for verifier rejections, the agent spends less time failing with the weaker Haiku model and applies high-reasoning power sooner.
2.  **Selector Guardrails**: Proactively banning dynamic IDs (like `ui-tabpanel-\d+`) and deep-DOM chains prevents the agent from latching onto fragile implementation details that change between renders or framework versions.
3.  **HITL Visibility**: The restoration of the `takeover-overlay` ensures that when the agent is stuck and needs human help, the operator is immediately notified via a clear, centered modal with a blurred background, preventing the "hidden prompt" issue.

## Learnings
- **State-Aware Routing**: The `ModelRouter` now effectively uses the verifier's feedback to make routing decisions, creating a tighter feedback loop between verification and planning.
- **Prompt Engineering as Constraint**: Injecting "BAN" rules into the core system prompt is an effective way to enforce architectural standards (like selector integrity) without complex code-level regex checks.
- **UI Prominence**: Modal overlays are essential for HITL interactions to ensure the user's attention is focused where it's needed most during a failure.

## Next Steps
- Monitor the `detailed_execution_log` in production to verify that Sonnet escalation is indeed reducing the number of total retries.
- Expand `vqa_id` coverage in the application under test to fully leverage the new selector mandate.
