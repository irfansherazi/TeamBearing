# vSuite UI Paradigm Guide
# Agent Operational Reference — Read Before Any Browser Action
# ─────────────────────────────────────────────────────────────────────────────
#
# KEYWORDS: ui, paradigm, ui-paradigm, list, view, compact, view, layout, sorting, column,
#   headers, dropdown, sort-by, sort-btn, portal, strict-mode, violation, locator, defense,
#   thought-process, state-declaration, rag, alignment, duplicate, hidden, element,
#   detect-view, which-view, before-action, mandatory
#
# This document defines the two mutually exclusive UI paradigms used by the
# vSuite Production Orders interface.  The agent MUST identify which paradigm
# is active before executing ANY interaction involving sorting, filtering, or
# bulk actions.  Failure to declare the correct paradigm is the PRIMARY cause
# of infinite interaction loops and Strict Mode violations.
# ─────────────────────────────────────────────────────────────────────────────


## PARADIGM 1 — List View
KEYWORDS: list, view, wide, table, column, headers, visible, sort, click, header, dropdown, portal, Due, Days
---

### How to recognise List View
- The table has **visible column headers** (Client, Status, Due / Days, Submitted On, etc.)
- There is NO global "Sort By" dropdown button above the table
- The table spans the full width of the viewport

### Sorting in List View
- Sorting is triggered by **clicking directly on a Column Header** in the table row
- Simple columns (Client, Status): a single click toggles sort direction
- **Compound columns** (Due / Days, Submitted On):
  - Clicking the header opens a **contextual dropdown portal** — the panel is
    appended to `document.body`, NOT inside the table DOM
  - The portal contains sub-options: e.g. "Due Date", "Days Remaining", "Submitted On"
  - You MUST click the correct sub-option inside the portal to set the sort field

### Locator Defense — List View Portal
The dropdown portal creates **duplicate text nodes** in the DOM:
one hidden in the table header, one visible in the floating portal.
Using a bare `get_by_text("Due Date")` or generic CSS will match BOTH and
throw a Strict Mode violation.

CORRECT approach:
```python
# Step 1 — click the compound column header to open the portal
page.get_by_role("columnheader", name="Due / Days").click()
page.wait_for_timeout(400)   # allow portal animation to complete

# Step 2 — scope click to the VISIBLE portal panel only
portal = page.locator(".p-dropdown-panel:visible, .p-overlay-panel:visible").last
portal.get_by_text("Due Date", exact=True).click()
```

WRONG approach (causes Strict Mode violation):
```python
page.get_by_text("Due Date").click()   # ← matches hidden + visible = CRASH
```


## PARADIGM 2 — Compact / Mobile View
KEYWORDS: compact, view, mobile, sort-by, button, sort-btn, dropdown, no column headers, global, menu
---

### How to recognise Compact View
- There is a **"Sort By" button** (`button#sort-btn`) visible above the table
  (typically on the right side of the toolbar)
- There are **NO column headers** — the table shows a condensed card layout
- A ⚙ (cog) icon is visible for view/settings control

### Sorting in Compact View
Column headers **do not exist** in Compact View.
ALL sorting must be performed through the centralised "Sort By" dropdown.

CORRECT 2-step pattern:
```python
# Step 1 — open the Sort By dropdown
page.locator("button#sort-btn").click()
page.wait_for_timeout(300)

# Step 2 — select the desired sort field from the dropdown list
sort_panel = page.locator(".sort-dropdown:visible, [id*='sort']:visible").last
sort_panel.get_by_text("Due / Days", exact=True).click()

# Step 3 — verify the sort arrow indicator
# A sort arrow (.sort-arrow, .ml-1 inside the sort panel) should appear
# after the selected option name to confirm the sort was applied
```

WRONG approach (causes infinite loop):
```python
# Clicking the column combobox get_by_role("combobox", name="Due / Days")
# in Compact View only opens/closes the header widget — it does NOT apply a sort.
# This creates an infinite toggle loop.
page.get_by_role("combobox", name="Due / Days").click()   # ← WRONG in Compact View
```

### Known Compact-View Sort Options (as of 2026-04)
| Dropdown Option Label | Sorts By              |
|-----------------------|-----------------------|
| Client                | Client name A→Z / Z→A |
| Status                | Status & Approvals     |
| Due / Days            | Due date / Days remaining |
| Submitted On          | Submission date        |

### Compact View Sort Verification
After clicking the sort option, look for one of:
- A **down-arrow** icon (`<i class="sort-arrow ml-1 ng-star-inserted">`) appearing
  next to the selected option label
- Table rows reordering visibly


## MANDATORY PRE-ACTION THOUGHT PROCESS
KEYWORDS: thought-process, mandatory, before, action, state, declaration, rag, alignment, locator, defense
---

Before executing ANY sorting, filtering, or bulk action, the agent MUST
produce an explicit `<thought_process>` block covering all four steps:

```
<thought_process>
1. STATE DECLARATION:
   I am currently in [List View | Compact View].
   Evidence: [describe the visible indicator — "Sort By button present"
              OR "Column headers visible, no Sort By button"]

2. RAG ALIGNMENT:
   The correct strategy for [sorting | filtering | bulk action] in [view] is:
   [state the correct interaction pattern from this document]

3. LOCATOR DEFENSE:
   [Identify any portal/dropdown/overlay risk]
   I will scope my locator to [the active portal | button#sort-btn panel]
   to avoid Strict Mode violations from hidden duplicate elements.

4. ACTION PLAN:
   Step 1: [exact action + locator]
   Step 2: [exact action + locator]
   Fallback: If timeout after [N]ms, [alternative strategy]
</thought_process>
```

Omitting this block is PROHIBITED.  An agent that skips state declaration
will be treated as having produced an invalid action plan.


## COMMON FAILURE PATTERNS TO AVOID
KEYWORDS: failure, patterns, avoid, anti-pattern, infinite, loop, strict, mode, violation
---

| Failure Pattern | Root Cause | Correct Fix |
|---|---|---|
| Clicking `get_by_role("combobox", name="Due / Days")` in Compact View | No column headers in Compact View — combobox is a header widget that only toggles | Use `button#sort-btn` → select from dropdown |
| `strict mode violation` on portal text | `get_by_text()` matches hidden + visible copies | Scope to `.p-dropdown-panel:visible` or `.p-overlay-panel:visible` |
| Sort applied but table doesn't update | Clicked sort option before portal animation finished | Add `wait_for_timeout(300-500ms)` after opening portal |
| `Sort By` button not found | Agent is in List View, not Compact View | Check for column headers; use column header click instead |
| Infinite toggle on column header | Clicked header twice thinking first click did nothing | After first click, wait for portal; do NOT click header again |


## VIEW DETECTION ALGORITHM
KEYWORDS: detection, algorithm, how-to-detect, which-view, current, programmatic
---

Use this programmatic check to auto-detect the active view before acting:

```python
def detect_view(page) -> str:
    """Returns 'compact' or 'list'."""
    # Compact view: Sort By button is visible
    sort_btn = page.locator("button#sort-btn")
    if sort_btn.is_visible():
        return "compact"
    # List view: at least one columnheader exists
    headers = page.get_by_role("columnheader")
    if headers.count() > 0:
        return "list"
    # Unknown — wait briefly and retry
    page.wait_for_timeout(500)
    return "unknown"
```

Always call `detect_view(page)` at the start of any sorting step if you are
uncertain which paradigm is active.  Never assume the view based on prior
steps — Angular routing or user navigation may have changed it.


## RELATIONSHIP TO human_guidance.md
KEYWORDS: relationship, human-guidance, precedence, override
---

- **`human_guidance.md`** contains HITL step-level overrides for specific
  AC steps on specific Jira tickets.  Those instructions are authoritative
  for their named step and take precedence over the general patterns here.

- **This document (`ui_paradigms.md`)** provides the general architectural
  ruleset that applies to ALL steps not covered by a specific HITL override.

Priority order (highest → lowest):
  1. `human_guidance.md` HITL override for the exact AC step
  2. Blueprint recipe (`knowledge/blueprints/`) for the workflow
  3. This document (`ui_paradigms.md`) — general paradigm rules
  4. Agent's own DOM reasoning (lowest authority)
