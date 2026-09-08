# vPromotions — PRF Form Runtime Policy
# ======================================
# This file was rewritten to remove widget-mechanics content that is now
# authoritatively covered by source-cited workflows in wf-*.md files:
#   - wf-create-prf.md          Drawer open, field enumeration, select2 (single/multi),
#                               contenteditable_tasp, datetime (MM-DD-YYYY hh:mm A),
#                               Category cat_change_checker
#   - wf-submit-cancel-prf.md   Save / Save Draft / Cancel
#   - wf-prf-file-upload.md     Dropzone upload flow (NOT native <input type=file>)
#   - wf-ghost-login.md         Ghost impersonation
#   - wf-auth-and-sso.md        Login / SSO redirect chain
#
# What remains here is RUNTIME POLICY confirmed by the vPromotions product
# owner that is NOT derivable from the vsuiteHotfix codebase:
#   - Fabricated test values are acceptable
#   - Recommended safe defaults for each field
#
# For every widget mechanic, DOM shape, selector, or datetime format, see
# the wf-*.md files above — they are cited to vsuiteHotfix source.

## WORKFLOW: PRF fabricated test data policy for vQA runs
KEYWORDS: prf test data, prf fabricated data, prf defaults, safe defaults prf, prf placeholder values, prf test values, fake prf data, fabricated values
---
POLICY (confirmed with the vPromotions product owner):
   vPromotions runs use fabricated test values for every field.
   Do NOT pause the run asking for real client names, real prize
   values, or broadcast-safe copy. Use plausibly-formatted placeholders
   and move on.

RECOMMENDED DEFAULTS by field name (use unless the AC dictates otherwise):

   Category               → Contest
                            Notes: See wf-create-prf for `cat_change_checker`
                            rejection rules. Pick this SOLO — do not combine
                            with 'Corporate Contest' or 'Campaign' variants
                            unless the AC explicitly requires it, or the pick
                            will be silently removed 300ms after selection.

   Client                 → type "Test Client", pick the first result
                            (select2 typeahead)

   Stations               → any single station from the list
                            (e.g. XXXX-FM in test env)

   Title                  → "Test Contest <TICKET-ID>"

   Start (event_startdatetime) → today + 7 days at 09:00 AM
                            Format: MM-DD-YYYY hh:mm A
                            Example: 10-15-2026 09:00 AM

   End (event_enddatetime)   → today + 8 days at 09:00 AM
                            Format: MM-DD-YYYY hh:mm A
                            (Start MUST be before End; both MUST be
                            in the future.)

   Sales Assignment       → any single option (e.g. "Sales Exec (...)")
                            Depends on selected stations — do stations FIRST.

   Description            → "Test description for QA-<ticket>"
                            (contenteditable .tasp — use keyboard.type)

   Play Copy              → single-line placeholder
   Prize Information      → single-line placeholder
   Liner Copy             → single-line placeholder
   Liner Notes            → single-line placeholder
   Tickets For An Event?  → no
                            (unless the ticket exercises the ticket flow)

   Value of each prize    → 100
   Liners Requested       → 5
   How many prizes?       → 1

   Upload Files           → SKIP unless the AC requires an attachment.
                            No server-side enforcement on the initial upload.
                            (Widget is Dropzone — see wf-prf-file-upload.)

## WORKFLOW: PRF field inventory (reference — verify at runtime)
KEYWORDS: prf field list, prf field inventory, prf form fields reference
---
The PRF drawer's field set is DRIVEN by the record passed to
`create_form_builder` (functions.js.html.twig:13453) — it is NOT static
and there is no fixed 17-field guarantee. Enumerate at runtime by walking
`#prf_form_rightview form :input[name^='_']`. See wf-create-prf
"Enumerate PRF form fields at runtime" for the detection recipe.

Historically observed field labels (for AC-language mapping only — do
NOT rely on presence):
   Category, Client, Stations, Title, Start, End, Description,
   Sales Assignment, Play Copy, Prize Information, Liner Copy,
   Liners Requested, Liner Notes, Tickets For An Event?, Upload Files,
   How many prizes?, Value of each prize

Historically observed Category options (grouped in the UI):
   On Air        Weekend Sponsorship, Floating Contest,
                 Cypress Contest Do Not Touch, Contest, On Air Content
   On Site       Appearance Only, Van Hit, Remote
   Multi-Media   Campaign, Talent Endorsement
   Online        Web Contest

These groupings and options come from server data (`myCategory` global),
not from static templates. In a multi-firm account the displayed labels
carry a `[Firm Name] ` prefix — `[FirmName] Contest` — see wf-create-prf
"Pick a PRF Category" for the disambiguation rules.
