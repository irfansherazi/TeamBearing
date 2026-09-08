# UAT Configuration

This file is created and maintained by `/vc-uat-init`. It carries project-specific UAT infrastructure (base URLs, persona credentials, auth strategy, viewport presets, isolation strategy) specifically tuned for the **vQA React/Vite frontend**.

**Companion file**: `memory-bank/projectConfig.md` `## UAT` section carries project-wide *ergonomic* defaults (default sections, artifact git policy). Keep secrets/infra here; keep ergonomics there.

---

**Status**: Configured
**Last Updated**: 2026-06-04

## Environments

| Name     | Base URL                            | Default |
|----------|-------------------------------------|---------|
| dev      | http://localhost:5173               | yes     |

> `/vc-uat` refuses to run against environments where `name == "prod"`. There is no override flag — production UAT must be intentionally invoked via a separate (future) command.
> 
> *Note on dev server*: The dev base URL maps to the local React/Vite dev server running on port `5173` (as orchestrated by `./start.sh`'s `FRONTEND_PORT`).

## Auth

- **Strategy**: login
  - `token` — inject localStorage/cookies from `.auth/<persona>.json`, hard-reload. Fastest.
  - `login` — drive the IDP UI. Slower but resilient to expired tokens.
  - `token+fallback` (default) — try token first; on auth failure or 401, fall back to `login` and cache fresh tokens back to `.auth/<persona>.json`.
- **Credential vault**: `.auth/` (must be in `.gitignore`)
- **Token file pattern**: `.auth/<persona>.json`
- **Login selectors** (specifically matched to `frontend/src/pages/LoginPage.tsx` inputs and buttons):
  - username: `input[type="email"]`
  - password: `input[type="password"]`
  - submit:   `button[type="submit"]`
  - post-login wait: element `.dashboard` appears (renders inside `frontend/src/components/Dashboard.tsx` root div after successful login)

## Persona Map

Each row maps a persona role discovered in `productBrief.md` → a test account → an auth reference (token path or env var name for password).

| Role             | Test Account                  | Auth Reference                       |
|------------------|-------------------------------|--------------------------------------|
| qa_lead          | josh.schauer@vcreativeinc.com | $ROLE_DEFAULT_PASSWORD               |
| product_manager  | josh.schauer@vcreativeinc.com | $ROLE_DEFAULT_PASSWORD               |
| devops           | josh.schauer@vcreativeinc.com | $ROLE_DEFAULT_PASSWORD               |

## Viewports

| Name    | Width | Height | Default For      |
|---------|-------|--------|------------------|
| desktop | 1280  | 720    | all non-mobile   |
| mobile  | 375   | 667    | mobile section   |

## Execution

- **max_parallel_tabs**: 1
- **isolation_strategy**: auto          # auto | same-persona-only | incognito
  - `auto` (default) — probes incognito support at run start; falls back to `same-persona-only` if unavailable. Today this always falls back; the browser_subagent tool does not yet expose incognito tab creation.
  - `same-persona-only` — explicit conservative. Walkers with the same resolved persona run in parallel; walkers with different personas serialize.
  - `incognito` — reserved for a future browser_subagent release. Selecting today errors at the phase gate.
- **auth_cookies_to_clear**:            # cookie names to scrub between persona groups
- **logout_url**: /logout               # path to hit for forced logout (or empty to skip)
- **screenshot_retention**: keep all
- **default_timeout_ms**: 15000
- **ux_pattern_check**: enabled

## Notes

- The credential vault directory MUST be added to `.gitignore`. UAT artifacts may include screenshots that contain test-account PII; configure `artifact_git_policy` in `projectConfig.md` accordingly.
- `--persona-override` flags warn when the supplied address does not match the project's documented test-account pattern. Update the Persona Map rather than relying on overrides for repeated runs.
