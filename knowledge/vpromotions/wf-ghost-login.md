# vPromotions — Ghost (Impersonation) Login
# ===========================================
# Source: vsuiteHotfix codebase.

## WORKFLOW: Ghost in as another user via the top-nav Select Person dropdown
KEYWORDS: ghost, ghost in, ghost login, impersonate, select person, ghost id, ghost dropdown, ghost_id, aaron stack, select target user, admin ghost, ghost user, ghost people
---
Applies to an authenticated admin session (ROLE_ADMIN, ROLE_FIRM_ADMIN,
ROLE_PROMOTIONS_DIRECTOR, ROLE_HR, or already-ghosted). If none of these
roles apply, the `adminjs.html.twig` include is skipped
(base.footerjs.twig:69-71) and the ghost input still renders but has no
select2 binding — clicks do nothing. Treat as PRECONDITION_MISSING.

## Why vQA has failed here 18+ times

vQA repeatedly tried `fill textbox('Select Person...')` — WRONG. The dropdown
is legacy select2 3.4.3 with an AJAX source. The placeholder "Select
Person..." (base.top.nav.menu.twig:196) belongs to an OFFSCREEN
`<input type=text id=ghost_id>`. Playwright's role=textbox matches BOTH the
offscreen input AND the inline `.select2-focusser` AND, once the drop is
open, the search input — a strict-mode collision that never selects the
real target.

## Correct interaction (ONLY sequence that works)

1. Verify the widget is bound. Preconditions:
      - `#s2id_ghost_id` exists (created by adminjs.html.twig:91 applying
        select2 to `#ghost_id`)
      - `$('#s2id_ghost_id').length === 1`
   If 0, current user lacks ghost privileges.

2. Click `#s2id_ghost_id a.select2-choice`.
   NEVER click `a.select2-focusser` (transparent focus proxy).
   NEVER click the underlying `input#ghost_id` (hidden offscreen).
   Only `a.select2-choice` opens the drop.

3. Wait for `body > div.select2-drop.select2-drop-active` to become visible.
   The drop is a direct body child (select2 v3 convention), NOT inside
   `#s2id_ghost_id`. Do not scope by the container.

4. Type the target user's name with `page.keyboard.type("<name>")`.
   MUST be ≥ 3 characters — adminjs.html.twig:93 sets
   `minimumInputLength: 3`. Fewer chars = no XHR.

5. Wait for the ajax request to resolve. Two throttles apply:
      - `minimumInputLength: 3`  (fewer chars = no request)
      - `quietMillis: 2000`      (adminjs.html.twig:94 — fast subsequent
                                  keystrokes reset the timer)
   During the request `ul.select2-results` shows
   `li.select2-searching` with text "Searching…". Wait ≥ 2500ms plus XHR
   round-trip, then wait for `li.select2-searching` to disappear and at
   least one `li.select2-result-selectable` to appear.

6. Click the target result:
      body > div.select2-drop-active
        ul.select2-results
          li.select2-result-selectable
            div.select2-result-label:has-text("<full name>")
   Server formats each result via `ghostFormatResult`
   (adminjs.html.twig:66-72) as `<p>Aaron Stack [Firm Name]</p>` — the
   parenthesised suffix is literal. Filter for `.select2-result-selectable`
   explicitly (skip `.select2-result-unselectable`).

7. IMMEDIATELY after the click, treat the current page as expiring.
   On selection, `$('#ghost_id').change()` (adminjs.html.twig:155) fires:
      → `_this.ghost_in(id)`
      → POST `/Admin_ghost_in` (adminjs.html.twig:17) with
        `{personid: <id>, sso_token: <cookie>}`
      → response has `data.email` on success
      → `ssoUserSync({ghost_email, action: 'ssoGhost'})`
        (adminjs.html.twig:29-34)
      → callback sets cookie `ssojwt` or `ssojwt_test` with new sso_token
      → `location.reload()` (adminjs.html.twig:39)
   Wait for the load event and re-fingerprint the DOM before any further
   action. Total elapsed 1–5 seconds.

8. Confirm impersonation on the reloaded page. The top nav now shows a
   "Return to Yourself" link — `#be_me` (adminjs.html.twig:162 binds it).
   Assert `$('#be_me').length === 1`.

## Failure modes and recovery

- `.toast-error` containing "Error Ghosting" (adminjs.html.twig:27) →
  server-side ghost failed. SCENARIO_FAILED.
- Selection made, NO reload after 5s → `ssoUserSync` silently failed. The
  local `#ghost_id` was cleared but session was NOT switched. SILENT_FAILURE
  — reload manually and re-check `#be_me`.
- Drop stays open with no results after 10s → press Escape, then re-open.
  If the session lost auth, expect a redirect to `/promo_login`.
- Reloaded page landed on a NON-Home page → the target user's SSO record
  may kick to `/#/select-product` (DefaultController.php:50-72). Re-fingerprint
  before asserting on Home elements.

## What NOT to do

- Do NOT match by placeholder text ("Select Person...", "Select person...").
- Do NOT use `get_by_role('textbox', name='Select Person...')` — strict-mode
  collision with the offscreen `.select2-focusser` and drop `.select2-input`.
- Do NOT `.fill()` the visible `.select2-input` — Playwright's .fill()
  bypasses the keyup chain select2 v3 needs. Use `page.keyboard.type()`.
- Do NOT `.fill()` the underlying `input#ghost_id` — it is offscreen and
  select2 UI is not bound to native value changes.
