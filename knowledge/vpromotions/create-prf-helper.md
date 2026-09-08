# vQA Helper — Create PRF (vPromotions)
# =======================================
# Compact, MODEL-FACING helper injected into the Computer-Use loop when a
# ticket's AC targets PRF creation. Distilled from wf-create-prf.md,
# prf-form.md, wf-submit-cancel-prf.md, and wf-prf-file-upload.md.
#
# Reading contract: this file is designed to be pasted into the initial
# user message. Every rule below trades verbosity for hit rate — if you
# can't act on a line, cut it.

## When to use this helper

Use when the AC mentions any of: "PRF", "Promotion Request Form", "New PRF",
"Create PRF", "Copy PRF", "Edit PRF", or the target URL contains
`vpromotions`. Ignore this helper for non-PRF tickets — the widget
recipes below are PRF-drawer-specific.

## FIRST — try `run_scripted_flow("createPrfHappyPath", …)`

For happy-path PRF creation the ONE-CALL macro replaces every step below
from "open drawer" through "click Save". It uses the SAME deterministic
Playwright recipe the vQA test suite uses (title → category → stations →
sales_assignment → start/end datetimes → description → save). One call.
No per-field iteration.

Example (fill the args from the AC — leave anything the AC doesn't
specify blank so safe defaults apply):

    run_scripted_flow(name="createPrfHappyPath", args={
        "title": "QA-359 Test PRF",
        "category": "Contest",                     # or list for multi
        "stations": ["XXXX-FM"],
        "sales_assignment": "Aaron Stack (Prog - Gotham City)",
        "description": "Test description for QA-359",
        "save_as": "submit"                        # "draft" if AC says draft
    })

When to fall back to per-field tools:
  1. The AC needs fields the flow's args don't cover — call the flow first
     for the boilerplate, then use `fill` / `select2_pick` / `select` for
     the delta.
  2. The AC needs multi-section PRFs (e.g. "Contest AND Appearance category
     both present") — the flow supports a list of category values; still
     prefer one call.
  3. The flow returns an error message (validation failure, no matching
     option, drawer didn't open). Read the returned string and act on it.

If the flow returns `ok`, mark the relevant AC step(s) `passed` and move
on — do NOT re-drive the same fields with click/fill.

## Terminal signal — call `done` as soon as this holds

Call `done(summary=...)` the moment ALL of the following are true:

1. Every AC step is marked `passed` via `mark_step_status`.
2. A `.toast-success` appeared after clicking Save.
3. Either the drawer closed (`#prf_form_rightview` hidden) OR the drawer
   stayed open in edit-mode with a numeric `input[id$='_id']` value.

DO NOT continue into Edit-PRF, Copy-PRF, or navigation-back flows unless
the AC explicitly asks for them. Extra iterations past the terminal
signal burn cost without covering new AC. The runner will also
auto-terminate when every step in the numbered AC list is `passed` —
so leaving one step stuck at `in_progress` will keep the loop running
past your intended endpoint.

## Mark AC steps IN ORDER

`mark_step_status` calls must move each step through
`in_progress` → `passed` (or `failed` / `skipped`) BEFORE you advance
to the next step's index. Skipping an intermediate step's `passed`
call leaves it stuck at `in_progress`, which:
  1. Prevents auto-terminal (loop keeps running past AC completion).
  2. Displays as "failed — run ended" if the human cancels.

If two AC steps describe overlapping actions (e.g. "leave required
fields empty" and "click Save and observe validation errors" — one
action satisfies both), mark BOTH: pass step N first, then pass step
N+1 in the same turn. Do NOT let a step linger.

## Scrolling — DO NOT use PageDown / PageUp

The PRF drawer (`#prf_form_rightview`) is its own scrollable container.
Page-level `press("PageDown")` scrolls the PAGE, not the drawer — the
drawer's contents don't move, so the model wastes iterations "scrolling"
without effect. This is the #1 cost sink after coordinate-guessing.

Preferred alternatives (in order):

1. `press("Tab")` — advances focus to the next form control. The browser
   auto-scrolls the focused element into view WITHIN the drawer's
   scrollable ancestor. This is the correct scroll primitive for
   forms.
2. `click(target="<css-selector-of-target-field>", hint="css")` — clicking
   a Playwright locator triggers auto-scrolling to the element BEFORE
   the click. Combining "navigate + click" in one tool call.
3. If you MUST scroll without focus, use a fresh page evaluate via
   `click_at` on the drawer's own scrollbar track (right edge of the
   drawer, NOT the page's outer scrollbar).

Never chain 3+ PageDown / PageUp presses in a row. If you find yourself
about to, use `press("Tab")` instead.

## Loading spinner — WAIT, do not click

If a `.loading_spinner`, spinner overlay, or full-screen semi-transparent
mask is on-screen after a Save or navigation, the request is IN FLIGHT.

- DO NOT try to dismiss it by clicking elsewhere.
- DO NOT press Escape.
- USE `wait(seconds=2)` to `wait(seconds=5)` and re-observe the
  screenshot on the next turn.

The Dropzone upload flow has NO client-side timeout on the spinner —
if the spinner persists past ~30 seconds of `wait` calls, treat as
network failure and `mark_step_status(status="failed", note=...)` or
`request_help`.

## Save Draft ALSO validates required fields

The Save Draft button (`#prf_form_rightview .btn-is-draft`) is NOT a
bypass for required-field validation. Per the prf.js code, clicking
Save Draft sets `data-$save-draft=true` on the drawer and then
triggers a click on `.prf_submit` anyway — the full submit path runs
including formbuilder's per-field validation. If required fields are
empty, you'll get the same `This field is required` errors as with
Save.

Order of operations:
1. Fill EVERY required field first (look for `.input_required` class
   markers).
2. Only then click Save OR Save Draft.
3. The difference between Save and Save Draft is what `status_code_id`
   the record ends up in — validation runs either way.

## Escalation ladder — DEFAULT TO SEMANTIC CLICK, NOT click_at

The PRF drawer has stable IDs and CSS selectors. `click_at(x, y)` is a
LAST resort — using it as the default doubles your iteration count and
misses the widget's event handlers half the time. Use this ladder:

1. `click(target=<visible-text>)` — hint defaults to "text".
2. `click(target=<label>, hint="label")` — for labeled form controls.
3. `click(target=<css-selector>, hint="css")` — use the selectors below.
4. `click_at(x, y, reason=...)` — ONLY after (1)-(3) failed on the SAME
   visual target. Two failed semantic tries → escalate.

## Field-by-field playbook

All selectors below are scoped to `#prf_form_rightview` — do not use
unscoped locators (SURFACE D collisions with other modals).

### Open the New PRF drawer
- click(target="+ New PRF") OR click(target="New PRF")
- Wait until an input with focus appears inside `#prf_form_rightview`.
- If a "Discard unsaved modifications?" dialog fires, dismiss with OK
  (accept discards). The dialog is triggered when a prior form was left
  modified.

### Category (multi-select — SELECT2 TAGS widget)
- Selector: `#prf_form_rightview [id^='s2id_'][id$='_category'] ul.select2-choices`
- Recipe: click that selector → `press` letters or use `fill(target="input.select2-input", hint="css", value="Contest")` → click the drop option.
- Drop option selector (body-mounted): `body > div.select2-drop-multi.select2-drop-active ul.select2-results li.select2-result-selectable`
- CRITICAL — `cat_change_checker` auto-rejects certain combinations
  300ms after selection. The pick silently disappears if:
  a. You add "Corporate Contest" / "Corporate Web Contest" /
     "Corporate Content" AND other categories exist. → Pick these SOLO.
  b. You add "Campaign" as a non-first pick. → Pick Campaign FIRST.
  c. You add any corporate-contest cat after other cats. → Same as (a).
- Safe default: single category "Contest" (no combination needed).
- Anti-patterns:
  * `fill()` on the hidden `<select>` — UI never updates.
  * `get_by_role('option', name='Contest')` — 23 documented failures.
  * `get_by_text('Contest')` — matches BOTH the drop LI AND the chip.

### Stations (multi-select — same widget as Category)
- Selector: `#prf_form_rightview [id^='s2id_'][id$='_stations'] ul.select2-choices`
- Same recipe. Sub-PRFs are filtered to the parent's stations.
- Safe default: any single station (e.g. "XXXX-FM" in test env).

### Title (plain text input)
- Selector: `#prf_form_rightview input[id$='_title']`
- `fill(target="Title", hint="label", value="QA-<ticket-id> Test PRF")` OR
  `fill(target="#prf_form_rightview input[id$='_title']", hint="css", value=...)`.

### Client (select2 typeahead — AJAX-backed)
- Selector: `#prf_form_rightview [id^='s2id_'][id$='_client']`
- Click to open → the `.select2-input` mounts in `body > div.select2-drop-active` → `page.keyboard.type("<query>")` → wait ~1s for AJAX → click the option.
- Anti-pattern: `fill(target="input:focus", value=...)` — writes text
  but bypasses the select2 keyup chain; AJAX search never fires.
  ALWAYS use `press` / `keyboard.type` on select2 inputs.
- Safe default: "Test Client" (pick first result).

### Sales Assignment (select2 single)
- Selector: `#prf_form_rightview [id^='s2id_'][id$='_sales_person'] a.select2-choice`
- Options depend on selected Stations — fill Stations FIRST or the list
  is empty. Formatted `Name (Role - Station)`.

### Start / End datetime
- Format is STRICT: `MM-DD-YYYY hh:mm A` (12-hour with literal AM/PM).
  Example: `10-15-2026 09:00 AM`.
  Wrong formats: `MM/DD/YYYY`, `HH:MM AM/PM` (uppercase HH = 24h).
- Selectors:
  * Start: `#prf_form_rightview input[id$='_event_startdatetime']`
  * End:   `#prf_form_rightview input[id$='_event_enddatetime']`
- Preferred recipe: click input → `keyboard.type("10-15-2026 09:00 AM")` → press Tab.
- Cross-field constraints: changing Start clamps End's minDate;
  changing End clamps Start's maxDate. If End < Start after a Start
  change, End clears — refill End.
- Safe defaults: Start = today + 7 days at 09:00 AM;
                 End   = today + 8 days at 09:00 AM.

### Description / Play Copy / Prize Info / Liner Copy / Liner Notes
- These are contenteditable `<span class="tasp">` — NOT `<textarea>`.
- Selector: `span.tasp[id$='_<field>_tasp']` (e.g. `_description_tasp`).
- **Preferred recipe (one tool call — runtime handles the details)**:
  `fill(target="span.tasp[id$='_description_tasp']", hint="css", value="...")`.
  The runtime auto-detects the contenteditable and internally clicks-to-
  focus + types the value. `fill()` on `.tasp` is SUPPORTED — no
  keyboard.type sequence needed.
- Anti-pattern (do NOT do this): `fill(target="*:focus", hint="css", value=...)`
  — `*:focus` matches whatever happens to be focused, which is often a
  transient element (e.g. a select2 input, a date picker cell) that the
  runtime cannot reliably classify. ALWAYS pass an explicit CSS selector
  pointing directly at the `.tasp` span.
- Anti-pattern: `fill()` on the sibling hidden input — formbuilder
  overwrites it at submit.

### File Upload (SKIP unless AC requires it)
- The initial upload is NOT server-enforced on bare create.
- If AC requires it: it's a Dropzone modal, not a native file input.
  See wf-prf-file-upload.md for the full recipe.

## Save vs Save as Draft — READ THE AC LITERALLY

The New-PRF drawer shows TWO save buttons side-by-side. They land the
record in different statuses and drive different post-conditions.
Which one you click depends ENTIRELY on the AC step's wording. Do not
substitute one for the other.

| AC step wording (literal)         | Button to click                                     | Selector                                     | Post-condition                          |
|-----------------------------------|-----------------------------------------------------|----------------------------------------------|-----------------------------------------|
| "Click Save" (bare "Save")        | Save (submits for review)                           | `#prf_form_rightview .prf_submit`            | `.toast-success` + drawer closes OR flips to edit-mode |
| "Click Save as Draft" / "Save Draft" / "Save the PRF as a draft" | Save as Draft (keeps in draft status) | `#prf_form_rightview .btn-is-draft`          | `.toast-success` + record stays in draft (status_code_id=33) |

Rules:
- If the AC step CONTAINS the phrase "draft" (case-insensitive), you MUST
  click `.btn-is-draft`. Do not click `.prf_submit`.
- If the AC step says only "Save" with NO "draft" qualifier, click
  `.prf_submit`.
- Clicking the wrong button means the record ends up in the wrong
  status and downstream AC steps (approval flow, edit-in-draft) will
  fail. This is a functional test failure, not a UI polish issue.
- Text-based `click(target="Save")` is BANNED — there are 8+ "Save"
  buttons across the page. Always use the CSS selectors above with
  `hint="css"`.

### Fallback: when only one button is present

- If the record is already in Draft status (`record.status_code_id == 33`)
  from a prior save, `.prf_submit` is `.hidden` — only `.btn-is-draft`
  is clickable. In that case use `.btn-is-draft` regardless of AC wording.
- On a fresh New-PRF drawer BOTH buttons are visible; disambiguation
  is by AC wording, not by which button is visible.

## Delete a PRF — STATE-GATED

The Actions dropdown's contents CHANGE based on the record's status.
This is the #1 cause of "Delete button not found" runaway loops.

| PRF status                        | Actions menu items                          | Delete visible? |
|-----------------------------------|---------------------------------------------|-----------------|
| Draft (status_code_id=33)         | Edit PRF, Copy PRF, **Delete**              | YES             |
| Submitted / Awaiting approval     | Edit PRF, Copy PRF, **Request to Cancel**   | NO — use Request to Cancel |
| Approved / Live                   | Edit PRF, Copy PRF, Request to Cancel       | NO              |

Rules:
- If the AC step says "Delete the copied PRF" (or similar), the copy
  must be in Draft state at the time of deletion. This means: after
  Copy PRF opens a new drawer, click `.btn-is-draft` (Save as Draft),
  NOT `.prf_submit` (Save). Saving-and-submitting the copy makes
  Delete disappear — no amount of re-clicking Actions will bring it
  back.
- If the record IS submitted and the AC explicitly asks for Delete,
  either (a) `mark_step_status(status="failed", note="Delete unavailable — PRF is submitted, Actions shows Request to Cancel")`
  or (b) `request_help` — do NOT substitute Request to Cancel for
  Delete unless the AC explicitly permits it. They are different
  operations with different downstream effects.
- Confirmation dialog: Delete opens a JS `confirm()` — the runner does
  NOT auto-dismiss confirms. Use `press("Enter")` after clicking Delete
  to accept, or the run will hang on the modal.

Escalation ladder if you can't find Delete:
1. Verify the PRF's status badge on the details page (top-right of the
   record view). If it's not "Draft", stop looking for Delete.
2. Do NOT open-close-reopen the Actions dropdown looking for a
   different menu — the menu doesn't change between opens on the same
   record.
3. Do NOT do another Copy PRF as a workaround. It creates orphan
   records and doesn't satisfy the AC.
4. After 2 failed attempts to locate Delete, call `request_help`.

## Waits — DON'T after menu opens or field clicks

Menus and form-field focuses render synchronously — a follow-up `wait`
tool call before the next click just burns an iteration. Reserve `wait`
for:
- After Save / Submit while a spinner is visible.
- After navigate() to a new URL.
- After AJAX-backed select2 typeahead (Client, Sales Person) — ~1s.

Do NOT wait after:
- click on a native <select> or button-triggered dropdown (Actions, category, stations).
- click_at on any coordinate.
- fill / type_text into a text input.
- press for Tab/Escape/Enter.

Two `wait` turns in a row is now a backpressure warning — expect it and
skip the wait next time.

### Preconditions before clicking either

- The button is NOT `:disabled` AND NOT `.hidden`.
- Every `.input_required` field has been filled. Both buttons run the
  same validation path (see next section) — the model has ONE shot at
  passing validation regardless of which is clicked.

## Verify success

Positive verification (all true):
- `.toast-success:visible` OR present in DOM
- AND (`#prf_form_rightview:hidden` OR `#prf_form_rightview input[id$='_id']` value is numeric)

If a `.toast-error` appears, read its text and either fix the flagged
field or `mark_step_status(..., status="failed", note=<toast-text>)`.

## Safe defaults when AC leaves values open

Confirmed with the vPromotions product owner — fabricated data is
acceptable for every field. Do NOT pause to ask.

| Field                | Default value                            |
|----------------------|------------------------------------------|
| Category             | Contest (solo)                           |
| Client               | "Test Client" → pick first result        |
| Stations             | any single station (e.g. XXXX-FM)        |
| Title                | "QA-<TICKET-ID> Test PRF"                |
| Start                | today + 7 days at 09:00 AM               |
| End                  | today + 8 days at 09:00 AM               |
| Sales Assignment     | any single option                        |
| Description          | "Test description for <TICKET-ID>"       |
| Play Copy            | short placeholder                        |
| Prize Information    | short placeholder                        |
| Liner Copy           | short placeholder                        |
| Liner Notes          | short placeholder                        |
| Tickets For Event?   | No                                       |
| Value of each prize  | 100                                      |
| Liners Requested     | 5                                        |
| How many prizes?     | 1                                        |
| Upload Files         | SKIP unless AC requires                  |

## Enumerate at runtime when you're unsure

The PRF drawer's field set is DRIVEN by the record — not static. If a
field you expect isn't visible, do NOT assume it's missing. Use a css
click on `#prf_form_rightview form :input[name^='_']` (all form
controls) and `.input_required` (required subset) to discover what's
actually on-screen.

## Anti-patterns — do NOT do these

1. `click_at(x, y)` as the first attempt. Use it only after two
   semantic-click failures on the SAME visual target.
2. `fill()` on select2 hidden `<select>` elements — the UI never
   updates because select2 v3 doesn't bind to value changes.
3. `get_by_role('option', name=...)` inside select2 dropdowns —
   select2 v3's role attributes are inconsistent.
4. Text-only `click(target="Save")` — collides with ~8 other Save
   buttons. Use `#prf_form_rightview .prf_submit`.
5. PageDown/PageUp scroll loops. The PRF drawer scrolls INTERNALLY —
   page-level PageDown does nothing. Use `press("Tab")` or click the
   next field's CSS selector; Playwright auto-scrolls on click.
6. Repeating the SAME failing action three or more times in a row.
   The screenshot won't magically change — reason about why the
   action didn't take, then try a DIFFERENT approach or
   `request_help`.
7. Filling required-field errors one at a time. After the first Save
   surface all validation errors — batch the fixes.
8. Clicking a loading spinner / overlay to dismiss it. Spinners mean
   the app is working — `wait(seconds=2..5)` instead.
9. Skipping a step's `passed` `mark_step_status` call before starting
   the next step. If two AC steps overlap, mark them both in one
   turn — don't leave a step stuck at `in_progress`.
10. Assuming Save Draft skips validation. It doesn't — fill required
    fields first.
