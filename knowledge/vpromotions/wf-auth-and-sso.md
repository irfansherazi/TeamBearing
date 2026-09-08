# vPromotions — Auth & SSO
# =========================
# Source of truth: vsuiteHotfix codebase (Symfony 2.5, jQuery, select2 3.4.3).
# All citations reference files in the vPromotions codebase.

## WORKFLOW: Log in to vPromotions and land on Home
KEYWORDS: login, log in, sign in, authenticate, promo, vpromotions, home, sso, redirect, landing page, email, password
---
Applies to /promo (or /app_test.php/promo in test). Assumes the user is NOT
currently authenticated at the vCreative SSO layer. vQA has historically hit
AUTH_GATE_CHECK retries here because it snapshots the DOM mid-redirect.

COOKIE MODEL (DefaultController.php:48):
   - Prod:  `ssojwt`      at .vcreative.net
   - Test:  `ssojwt_test` at .vcreative.net
   If both are missing, /promo will 302 to the SSO landing.

STEPS:

1. Navigate to `${base_url}/promo` (or `/app_test.php/promo` in test).
   Register `page.on('dialog', d => d.accept())` BEFORE the navigation — early
   load code paths can raise browser confirms.

2. Follow the redirect chain. Up to THREE hops are possible:
      (a) rc → `/promo_login`             (unauthenticated app-level)
      (b) rc → SSO gateway root URL       (unauthenticated SSO-level;
                                           DefaultController.php:64-71)
      (c) rc → SSO `/#/select-product`    (SSO-authenticated but no
                                           promo access — kickemout=product_select;
                                           DefaultController.php:50-63)
   DO NOT snapshot DOM until browser navigation is idle. Wait for
   `networkidle` before assertions.

3. If landed on /promo_login (login.html.twig:130):
      - Fill `input#username` (email/username).
      - Fill `input#password`.
      - Click `button#_submit`.
      - Note: `#username` has `autofocus`. Prefer `.fill()` over `.click()`
        then `.type()` — a click can race the autofocus and drop the first
        character.

4. Wait for the POST → `/login_check` (FOSUserBundle, security.yml:26-33),
   then a 302 back to /promo. Wait for `networkidle`. Assert URL ends with
   `/promo` (or `/app_test.php/promo`) AND response HTML contains
   `body.page-header-fixed`.

5. Wait for the shell to render. ALL of these must be true simultaneously:
      - `body.page-header-fixed` present
      - `.header.navbar` rendered (base.top.nav.twig)
      - `#pg-content` present (index.html.twig:42)
      - Global JS ready: `typeof jQuery.noConflict === 'function' &&
        typeof App === 'object'`
        (jQuery noConflict at index.html.twig:64; `App` from app.js
        loaded via base.footerjs.twig:33)

6. Wait for the DEFERRED Home content. Home is NOT rendered by the initial
   /promo response — it is fetched by a 1000ms setTimeout at
   index.html.twig:113-115 that calls
   `ajax_load_page('ppo_promo_ajax_calendar', 'pg-content', '')`.
   Cold-cache load can take 5–8 seconds. Wait for BOTH:
      - `#pg-content #promoTabs > ul.nav-pills > li.active.promo_home_tab`
        (calendar.html.twig:36-37)
      - `#promo-all.tab-pane.active`

7. Wait for FullCalendar to render. Ready-state predicate:
       document.querySelector('#promo-all.tab-pane.active') &&
       document.querySelector('#promo-calendar .fc.fc-ltr .fc-toolbar')
   The `#create_new_prf` button (fullcal.js.html.twig:984) is appended AFTER
   `eventAfterAllRender`. For creation-capable roles it will appear. For
   ROLE_ON_AIR, ROLE_FRONT_DESK, ROLE_PROMO_ASSISTANT, NOBODY it never
   appears (fullcal.js.html.twig:979) — this is not an error.
   Do NOT assume DOM is stable until 3s past `.fc.fc-ltr` first paint —
   `render_tasks` runs at +3000ms (fullcal.js.html.twig:1036).

FAILURE MODES:
- AUTH_GATE_CHECK retries on Email/Password/LOGIN → snapshotting mid-redirect.
  Fix: `page.wait_for_load_state('networkidle')` before assertions.
- Landed on /#/select-product (SSO product picker) → the user's SSO record
  does not grant promo access; DefaultController.php:50-63 kicked them out.
  Treat as PRECONDITION_MISSING.
- Snapshot at ~2s returns scaffolding only → wait for the deferred load
  (step 6) before treating Home as rendered.
