# vPromotions — Create PRF (drawer flow)
# =======================================
# Source: vsuiteHotfix codebase. Every citation is verifiable there.
# PRF = Promotion Request Form. Right-side drawer at #prf_form_rightview.

## WORKFLOW: Open the New PRF drawer from the Home tab
KEYWORDS: new prf, create prf, start prf, open prf form, new promotion, prf drawer, create new prf, new prf button, add prf
---
Applies to a user with a creation-capable role. ROLE_ON_AIR,
ROLE_FRONT_DESK, ROLE_PROMO_ASSISTANT, NOBODY do NOT see the button
(fullcal.js.html.twig:979) — treat as PRECONDITION_MISSING.

PRECONDITIONS:
- Home tab fully rendered (see wf-auth-and-sso).
- `#create_new_prf:visible` (attached dynamically by FullCalendar).
- Register `page.on('dialog', d => d.accept())` BEFORE the click — the flow
  may fire `window.confirm('Discard unsaved modifications?...')` if a
  previous form was left modified (functions.js.html.twig:13440).

STEPS:

1. Click `#create_new_prf`.
   The delegate at delegates.js.html.twig:9890 calls `show_event_form(null, '')`
   which:
      - Resizes the calendar (`resize_promo_cal('shrink')`)
      - Calls `create_form_builder('#prf_form_rightview', {...})` — formbuilder
        builds the form INSIDE `#prf_form_rightview` (starts as
        `<div style="display:none;">` per calendar.html.twig:85)
      - Shows `#prf_form_rightview`
      - Focuses `.field-title` (the title input)

2. Wait for the drawer to open. ALL true:
      - `#prf_form_rightview:visible`
      - `#prf_form_rightview form[id$='_form']:visible`
      - `#prf_form_rightview input[id$='_title']:visible AND :focused`
   Form id is DYNAMIC — `prf_<recordId>_form` for existing records or
   `prf__form` for new. Always use suffix-match locators (`[id$='_form']`).

3. Verify the drawer is fresh:
      $('#prf_form_rightview').data('modified') === false

COMMON FAILURE:
- Discard-confirm dialog blocks the second form open. Register the dialog
  handler BEFORE the click. If Playwright auto-dismisses (returns false),
  `show_event_form` bails and the form does NOT open.

## WORKFLOW: Enumerate PRF form fields at runtime
KEYWORDS: prf fields, prf form fields, field list, required fields, prf inputs, formbuilder fields
---
The PRF drawer's field set is NOT static — it is driven by the `record`
object passed to `create_form_builder` (functions.js.html.twig:13453).
Fields differ by category, sub-PRF status, campaign vs. standalone, and
user role.

DO NOT rely on a hardcoded field list. Enumerate at runtime:

1. All rendered form controls carry `name` attributes prefixed with `_`
   (formbuilder.js.html.twig:303 for textareas, :325 for selects, similar
   for other types). Query:
       #prf_form_rightview form :input[name^='_']

2. `input_required` class marks required fields (formbuilder.js.html.twig:312-315
   for textareas, :341-344 for selects, similar for others).

3. `field-<selectorified-name>` class carries the semantic field name
   (formbuilder.js.html.twig:328 for selects). Use this class to bind AC
   step mentions ("fill the title", "pick the client") to concrete inputs.

WIDGET DETECTION TABLE (per formbuilder type):

| formbuilder type   | Detect by                                                                                   | Interaction     |
|--------------------|---------------------------------------------------------------------------------------------|-----------------|
| text               | `input[type=text][name^='_']` with NO `.datetimepicker` and NO `.select2` sibling           | native .fill()  |
| textarea           | `span.tasp[id$='_tasp']` alongside sibling `input[type=hidden][name^='_']`                  | contenteditable_tasp (see workflow below) |
| select2            | `div#s2id_<form-id>_<field>` with `a.select2-choice` inside                                 | select2 single  |
| select2tags        | `div#s2id_<form-id>_<field>.select2-container-multi` (formbuilder.js.html.twig:359-366)     | select2 multi   |
| select2typeahead   | `input.select2[type=text]` not backed by `<select>` (formbuilder.js.html.twig:369-377)      | select2 ajax    |
| date               | `input.datetimepicker[type=datetime]` with `.inputmask("99-99-9999")`, `showTimepicker:false` | hasdatepicker (date-only) |
| datetime           | `input.datetimepicker[type=datetime]` without the date-only inputmask                       | hasdatepicker (with time) |
| file               | `div.select2-container.select2-container-multi > a.upload_inital_prf_files`                 | Dropzone modal — see wf-prf-file-upload |

## WORKFLOW: Fill a PRF select2 single-select (native select-backed)
KEYWORDS: select2 single, pick client, choose client, sales assignment, sales person, salesperson, aaron stack, single select, dropdown pick, category single, tickets for event
---
Applies to any PRF field rendered as `formbuilder.type=select2` — sales
assignment, tickets-for-event, and similar. The DOM has:
   - Visible wrapper: `#s2id_<form-id>_<field>`
   - Trigger:         `a.select2-choice`   inside the wrapper
   - Backing hidden:  `<select id="<form-id>_<field>" class="select2-offscreen">`
   - Drop (body-child, only when open):
                      `body > div.select2-drop.select2-drop-active`
                        > `div.select2-search > input.select2-input`
                        > `ul.select2-results`

STEPS:

1. Locate: `#prf_form_rightview #s2id_<form-id>_<field>`.
2. Click `a.select2-choice` inside that container.
   NEVER click `a.select2-focusser` (transparent focus proxy).
   NEVER `.fill()` on the hidden `<select>` — writes value but UI never
   updates because select2 v3 is not bound to native <select> value changes.
3. Wait for `body > div.select2-drop.select2-drop-active:visible`.
4. `page.keyboard.type(query)` — writes into the drop's `.select2-input`.
   NEVER `.fill()` — Playwright's .fill() writes value but bypasses the
   keyup chain select2 v3 needs to trigger its matcher.
5. Wait for `ul.select2-results li:not(.select2-searching)` OR the presence
   of at least one `li.select2-result-selectable`.
6. Click the matching:
      ul.select2-results li.select2-result-selectable div.select2-result-label
   with an EXACT-text match. For sales assignment, options are formatted
   `Name (Role - Station)` by `getSalesPeopleForStation`
   (formbuilder.js.html.twig:478) — parentheses are LITERAL, do not escape.
7. Verify:
      #s2id_<form-id>_<field> span.select2-chosen  contains the picked text
      body > div.select2-drop-active                is gone (display:none)

FAILURE MODES:
- `get_by_role('combobox')` or `get_by_role('textbox', name='<placeholder>')`
  times out or matches multiple → select2 v3 renders `<a>` with
  role=combobox AND hides the real `<select>` offscreen AND mounts a
  `.select2-input` in the body-level drop. ARIA roles are inconsistent.
  Address by container id.
- Sales-person list is EMPTY → `getSalesPeopleForStation` depends on selected
  stations. Do stations FIRST.
- Click on a result li appears to work but nothing selects → select2 v3
  handles selection on mouseup. If the li scrolls between click and mouseup,
  the selection is lost. Ensure `.select2-result-selectable` (not
  `.select2-result-unselectable`), scroll into view, then click.

## WORKFLOW: Pick a PRF Category (SURFACE A — 23 documented failures)
KEYWORDS: category, contest, corporate contest, campaign, pick category, choose category, station contest, prf category, multi category, on air content, floating contest, cypress contest
---
The Category field is a `select2tags` multi-select (formbuilder.js.html.twig:359).
This is the top vQA failure surface for vPromotions — 23 failed clicks on
"Contest" via wrong locators.

CRITICAL FINDING: vQA's Contest failures may not be locator failures.
There is a `cat_change_checker` at functions.js.html.twig:13479 that
AUTO-REJECTS certain category combinations by removing the LI 300ms after
selection. If the click looked successful but the pick vanished, the checker
rejected it — not vQA's fault.

DOM:
   - Wrapper:      `#prf_form_rightview #s2id_<form-id>__category.select2-container-multi`
     (form field naming: `_<field>` — the underscore-prefixed name is what
     formbuilder emits — formbuilder.js.html.twig:303)
   - Trigger:      `ul.select2-choices` inside the wrapper
   - Inline input: `li.select2-search-field > input.select2-input`
   - Drop (body-child, when open): `body > div.select2-drop-multi.select2-drop-active`
   - Chosen items: `li.select2-search-choice` appended to `ul.select2-choices`

STEPS:

1. Click `#prf_form_rightview #s2id_<form-id>_category ul.select2-choices` to
   focus the inline `input.select2-input`.

2. `page.keyboard.type("Contest")` (or fuller text — see disambiguation
   below).

3. Wait for `body > div.select2-drop-multi.select2-drop-active:visible`.

4. Click `ul.select2-results li.select2-result-selectable` matching the
   target text. In multi-firm accounts the DISPLAYED text is
   `[Firm Name] Contest` even though the underlying id is `Contest`
   (functions.js.html.twig:13494). Match the full displayed text OR the
   trailing portion after `] `.

5. VERIFY after 300ms delay:
      #prf_form_rightview li.select2-search-choice  contains the chosen text
   If it disappeared, `cat_change_checker` rejected the combination — see
   failure modes below.

6. To add a second category: the input regains focus automatically after
   step 4 — just type again. Do NOT re-click the container in between (it
   blurs and closes the drop).

CATEGORY DISAMBIGUATION (name collisions):

The default select2 matcher is case-insensitive substring. When multiple
categories share a prefix, TYPE THE DISCRIMINATOR before clicking. Examples:
   - "Corporate Contest" vs "Corporate Content" — both match "Corporate Cont"
     → type "Corporate Contest" fully
   - "Contest" vs "Weekend Contest" vs "Floating Contest" — bare "Contest"
     matches all three → prefer the exact-text-match click

CAT_CHANGE_CHECKER (functions.js.html.twig:13479-13571):

Runs on every category change and can silently REMOVE the just-added pick:

   A. If ADDED = 'corporate contest' / 'corporate web contest' / 'corporate content'
      AND other categories already exist:
         toastr.error('When choosing Corporate Contest, it must be the only selection.')
         → the just-added pick is removed via .select2('data', newVals).trigger('change')
         (functions.js.html.twig:13499)

   B. If ADDED = 'Campaign' AND is not the FIRST selection:
         toastr.error('When choosing Campaign, it must be the first selection in the category!')
         → 'Campaign' is removed (functions.js.html.twig:13515)

   C. If a corporate-contest category is added AFTER other categories:
         Same as (A) — the added corporate cat is removed
         (functions.js.html.twig:13556-13569)

To avoid these: pick corporate-contest cats SOLO. Pick 'Campaign' FIRST when
combining.

FAILURE MODES:
- `.fill('_category')` or `.fill('#<form-id>_category')` writes to the hidden
  `<select>` — dropdown UI never updates. Discard `.fill()`.
- `get_by_role('option', name='Contest')` — 23 documented failures. select2
  v3 uses `role='option'` inconsistently; depend on
  `li.select2-result-selectable` instead.
- `get_by_text('Contest')` — matches the LI in the drop OR the ALREADY-chosen
  chip. Use the drop-scoped locator:
      body > div.select2-drop-multi.select2-drop-active
        ul.select2-results
          li.select2-result-selectable

## WORKFLOW: Fill a PRF Station selector
KEYWORDS: stations, pick station, choose station, prf stations, XXXX-FM, station select, station multi
---
Stations is `select2tags` — same widget-class as Category (see workflow
above). One difference: for sub-PRFs (`_is_sub` in
formbuilder.js.html.twig:418), the station list is filtered to the parent
PRF's stations. Picking a station not in the parent's set will not appear
in results at all.

Same recipe as Category. `#s2id_<form-id>_stations` is the wrapper.

## WORKFLOW: Fill a PRF contenteditable textarea (Description / Play Copy / Prize Info / Liner Copy / Liner Notes)
KEYWORDS: description, play copy, prize information, liner copy, liner notes, notes, contenteditable, tasp, rich text prf, prf description, prf notes, prf textarea, fill description, type description, enter description, type into description, fill the description, prf details field, describe the prf, add description, write description, fill copy, type into prf, fill prf field, multiline field, span contenteditable, prf multiline
---
The PRF drawer uses `.tasp` CONTENTEDITABLE spans for multi-line fields —
NOT wysihtml editors. Confirmed at formbuilder.js.html.twig:299-317 and
:2925-2938:

   textarea(meta) returns:
      1. hidden input: `<input type="hidden" name="_<field>"
                              id="<form-id>_<field>">`
      2. visible span: `<span contenteditable
                              name="_<field>"
                              id="<form-id>_<field>_tasp"
                              class="form-control multiline-example tasp">`

DOM shape:
   Sibling pair:
     - `input[type=hidden][name=_<field>][id=<form-id>_<field>]`
     - `span.tasp[contenteditable][id=<form-id>_<field>_tasp][name=_<field>]`

STEPS:

1. Click `span.tasp[id$="_<field>_tasp"]` to focus the caret.
2. `page.keyboard.type("<content>")` — writes into the contenteditable.
   Formbuilder's serializer at formbuilder.js.html.twig:1868 reads `.html()`
   from the span at submit time and pushes it into the hidden input's value.

WHAT NOT TO DO:
- DO NOT `.fill()` on the span — throws "Element is not an <input>".
- DO NOT `.fill()` on the hidden `input#<form-id>_<field>` — formbuilder
  overwrites it from the span during serialize.
- DO NOT `page.frame_locator('iframe.wysihtml5-sandbox')` — the PRF drawer
  has NO wysihtml iframe. wysihtml5 IS used elsewhere (Liners edit modal
  uses `.field-text` / `.field-notes`) but the PRF drawer's multi-line
  fields are `.tasp` spans.

REQUIRED DETECTION:
   `span.tasp.input_required`  OR  `span.tasp[required]`
Both are applied together — formbuilder.js.html.twig:311-315.

## WORKFLOW: Fill the PRF Start / End datetime
KEYWORDS: start date, end date, event_startdatetime, event_enddatetime, datetime, prf date, prf time, calendar picker, hasdatepicker, prf schedule, when
---
PRF Start and End are jQuery UI datetimepicker inputs with an inputmask.
The EXACT format is:

   **MM-DD-YYYY hh:mm A**   (e.g., `10-15-2026 09:00 AM`)

Evidence:
- formbuilder.js.html.twig:2514-2515 — defaults `date_format: 'mm-dd-yy'`
  (jQuery UI convention: `mm-dd-yy` = 2-digit month, 2-digit day, 4-digit year)
  and `time_format: 'hh:mm tt'` (12-hour with AM/PM).
- Moment validation format used throughout is `"MM-DD-YYYY hh:mm A"`
  (formbuilder.js.html.twig:175, :190, :207).

Do NOT use `MM/DD/YYYY` (slashes) or `HH:MM AM/PM` (uppercase HH = 24-hour).
Both are wrong.

STEPS:

1. Click the input `input.datetimepicker[type=datetime]` for the target
   field (Start = `event_startdatetime`, End = `event_enddatetime`).
2. `page.keyboard.type('MM-DD-YYYY hh:mm AM')` — inputmask enforces the
   shape.
3. Press Tab or click outside — triggers
   `vCreative.vDates.parseDateTime()` (formbuilder.js.html.twig:120-125).
   Invalid dates fire `toastr.error(..., 'Invalid Date')`.

CROSS-FIELD CONSTRAINTS:

Enforced client-side (formbuilder.js.html.twig:190-225) and server-side:
- When Start changes, End's `minDate` is set to Start. If End < new Start,
  End is cleared.
- When End changes, Start's `maxDate` is set to End. If Start > new End,
  Start is cleared.

SAFE FABRICATED DEFAULTS:
- Start = today + 7 days at `09:00 AM`
- End   = today + 8 days at `09:00 AM`

CALENDAR PICKER FALLBACK (approach B if direct typing rejected):

1. Click the calendar icon (sibling label with `.fa-calendar`).
2. Navigate months via `a.ui-datepicker-prev` / `a.ui-datepicker-next`
   inside `#ui-datepicker-div` (single shared body-child instance across
   all datepickers).
3. Click `td[data-handler='selectDay'][data-month='<0-indexed>']
    [data-year='<yyyy>'] a` whose text is the target day.
4. Set the time via the picker's time controls if present.
5. Datepicker closes; input value is set in the format above.

FAILURE MODES:
- Second click on a datepicker does not open — `#ui-datepicker-div` is a
  single shared node. If mid-fade or blocked by an overlapping modal,
  jQuery UI treats the second click as a close. Blur any focused element
  first, or call `$(input).datepicker('show')` via `page.evaluate`.
