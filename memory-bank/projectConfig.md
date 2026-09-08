# Project Configuration

## Banyan Memory Bank

This section is auto-managed by `/bmb:init`. Do not edit manually.

- **Banyan Version**: 2.1.0
- **Initialized**: 2026-05-07
- **Last Updated**: 2026-07-22
- **metadata_branch**: main
- **protected_branches**: [main]
- **pr_target**: main
- **archive_strategy**: push-and-pr
- **worktree_root**: ~/banyan-wt/vQA/

## UAT

Project-wide defaults for `/vc-uat`. Edit freely — these are read at the start of every UAT run. All keys are optional; omitted keys fall back to plugin defaults.

- **default_sections**: happy,mobile         # Default for `/vc-uat` when --sections is not passed.
                                              # Vocabulary: happy | mobile | negatives | errors | all
                                              # Examples:
                                              #   happy,mobile         (fastest signal — recommended for most teams)
                                              #   happy,mobile,errors  (catch error-path regressions too)
                                              #   all                  (full coverage; ~12-16 min)
- **default_skip_ux_check**: false           # When true, treat --skip-ux-check as on by default
- **default_environment**: dev                # Which `environments[*].name` from uat-config.md to use
- **artifact_git_policy**: ignore             # ignore | commit — controls whether run-scoped artifacts
                                              # (screenshots, GIFs) are committed alongside the markdown report
- **uat_required_for_archive**: false         # When true, /vc-archive surfaces a warning unless a
                                              # PASS report exists for the task

## Agent Backends

Which execution backend drives each configurable **seam** of the workflow. BMB runs on Anthropic
(Claude) by default; a project may route individual content-producing seams to the optional
`codex@openai-codex` plugin instead. **This block is the per-project source of truth — edit it here
to override backends for this project.**

Each value is `<provider>[:<model>]` — `anthropic[:haiku|sonnet|opus]` or `codex[:<codex-model>]`:

```yaml
backends:
  plan:                  anthropic      # anthropic[:tier] | codex[:model]   (codex not recommended)
  tdd:                   anthropic      # anthropic[:tier] | codex[:model]   — build RED→GREEN implementation
  code-review:           anthropic      # anthropic[:tier] | codex[:model]   — build Step 8 quality gate
  creative-architecture: anthropic      # anthropic[:tier] | codex[:model]   — system-design doc
  creative-uiux:         anthropic      # anthropic[:tier] | codex[:model]   — UI/UX design doc
  creative-algorithm:    anthropic      # anthropic[:tier] | codex[:model]   — algorithm design doc
  creative-user-journey: anthropic      # anthropic[:tier] | codex[:model]   — user-journey doc
  creative-critique:     codex          # anthropic[:tier] | codex[:model] | off  — advisory adversarial pass
  availability:          auto           # auto = silently fall back to Anthropic if Codex is down
                                        # on   = fall back the same way, but emit a visible ⚠ warning
# tier ∈ haiku|sonnet|opus — tunes the Claude sub-agent that runs the seam; bare `anthropic` keeps its default.
```

Codex not installed — mandatory seams default to `anthropic` (behavior identical to pre-integration
BMB). `creative-critique: codex` is advisory and silently skips when Codex is absent; it
self-enables automatically once Codex is installed and authenticated. To also enable
`code-review: codex` (Codex judges code quality; BMB's gated security/observability/API audits
still run on Anthropic), install the Codex companion plugin and run `/bmb:doctor`. The
machine-specific companion path lives in the gitignored `memory-bank/.local/codex-cache.md`.
