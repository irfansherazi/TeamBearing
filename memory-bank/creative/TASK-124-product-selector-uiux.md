# UI/UX Decision: Product Selector — Multi-Product Support

**Created**: 2026-07-20
**Status**: DECIDED
**Decision Type**: UI/UX
**Task**: TASK-124 / FEAT-115

---

## User Context

### Target Users

- **Primary**: QA Lead / Automation Engineer — runs tests against specific product boards; needs to instantly know which product context is active so they never accidentally run a vProMedia ticket against vTrade's role set.
- **Primary**: Product Manager — self-verifies a ticket; the PM owns one product domain and must be confident the test uses the right personas, environment URL, and board.
- **Secondary**: Release Engineer / DevOps — batch runs are product-scoped; the engineer needs a clear, unambiguous product context label in the UI when debugging a failed CI-triggered run.
- **Secondary**: Platform Admin / vProMedia Engineering — configures new products; may have zero roles/boards for a product at initial rollout and must see the selector without the app crashing.

### User Goals

1. Know at a glance which product context is active without hunting through settings.
2. Switch product in ≤ 2 clicks from any tab (Run Test, Archive, Analytics, Playwright).
3. Understand why certain controls are disabled when a product has no configured roles or boards (AC-ERROR-2).

### Use Cases

| Use Case | User | Goal | Frequency |
|----------|------|------|-----------|
| Switch from vProMedia to vTrade before starting a run | QA Lead | Ensure correct role/board set | ~5–10x/day |
| First load — verify selector defaults to "vProMedia" | Any | Confirm existing behavior preserved | Every session |
| Reload page — selector remembers last product | Any | Session persistence | Every page reload |
| Select a product with zero roles/boards | Admin / QA | Understand empty-state before configuration | Rare (onboarding) |
| Notice Run Test is disabled; understand why | PM | Understand missing configuration | Occasional |

### Constraints

- **Devices**: Desktop (1280px+) primary; tablet (1024px) secondary. The internal tool is not used on mobile. The header must not wrap or collapse at 1024px viewport.
- **Accessibility**: WCAG AA. Full keyboard navigation; visible focus rings; screen-reader-compatible labels and `aria-haspopup`.
- **Existing Patterns**: The header uses `display: flex; justify-content: space-between` with `.header-left`, `.dashboard-tabs` (center), and `.header-right`. Any new element must slot cleanly into this flexbox row without introducing a fourth flex child that breaks the `space-between` rhythm.
- **Theme**: Dual-theme dark/light via CSS custom properties. No hardcoded hex colors in component JSX — use CSS variables exclusively.

---

## User Flow

### Flow Diagram

```
[Page Load]
     │
     ▼
[ProductContext reads localStorage → slug]
     │
     ├── valid slug found → set active product
     └── missing / corrupt → fall back to "vpromedia" (AC-ERROR-1)
               │
               ▼
     [ProductSelector renders in header — always visible]
               │
               ▼
     [User clicks selector trigger]
               │
               ▼
     [Dropdown opens — lists all configured products]
               │
     ┌─────────┴─────────┐
     │                   │
[product has         [product has
 roles + boards]      no roles/boards]
     │                   │
     ▼                   ▼
[select it]      [select it — shown with
     │            "Not configured" badge]
     │                   │
     └────────┬──────────┘
              ▼
    [ProductContext updates → localStorage saved]
              │
    ┌─────────┴──────────────┐
    │                        │
[boards/tickets          [roles empty →
 re-fetched with          role dropdown
 new product slug]        shows placeholder;
                          Run Test disabled
                          + tooltip]
```

### Flow Description

1. **Entry**: On every page load (Dashboard and Playwright page), `ProductContext` initializes from `localStorage.vqa_product`. Missing or corrupt values fall back to `"vpromedia"`.
2. **Selector visible**: The `<ProductSelector>` component renders inside `.dashboard-header` between `.header-left` and `.dashboard-tabs`. It is always visible — no tab dependency.
3. **User opens dropdown**: Click or keyboard (Enter/Space) opens the dropdown list. Focus moves to the list; arrow keys navigate options; Escape closes.
4. **User picks a product**: `ProductContext.setProduct(slug)` is called. `localStorage` is written synchronously. Any in-flight ticket fetch is cancelled (AC-ASYNC-1).
5. **UI reacts**: Ticket list re-fetches. Role dropdown repopulates (or shows disabled placeholder). Run Test button re-evaluates its enabled state.
6. **Exit**: Dropdown closes; focus returns to the trigger button.

### Error States

| Error | Cause | User Recovery |
|-------|-------|---------------|
| Corrupt localStorage slug | Manual edit of localStorage; migration of old data | Auto-fallback to "vpromedia"; user can re-select |
| Product with no boards | Product registered but Jira board not yet configured | Ticket list shows empty state: "No board configured for [Product Name]" |
| Product with no roles | Product registered but no personas/role credentials configured | Role dropdown disabled with placeholder; Run Test disabled + tooltip "No roles configured for [Product Name]" |
| Network failure on ticket re-fetch after product switch | Transient API error | Existing error banner pattern (`.error-banner`) handles this |

---

## Options Explored

### Option 1: Inline Header Pill (Between title and tabs)

- **Approach**: A compact `<button>` styled as a colored pill is inserted between `.header-left` and `.dashboard-tabs`. Clicking it opens a popover dropdown directly below the pill. The product name and a chevron are always visible. The pill carries the product's accent color as a left border or background tint.
- **Wireframe/Layout**:
  ```
  ┌────────────────────────────────────────────────────────────────────────────┐
  │  🔬 vQA   Autonomous QA Agent    [● vProMedia ▾]   [▶ Run][📚 Archive]…   ● All Systems Go  [Logout] │
  └────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼ (open)
                                    ┌────────────────┐
                                    │ ● vProMedia  ✓ │
                                    │ ● vTrade        │
                                    │ ○ vEP           │
                                    │ ○ vPPO          │
                                    │ ○ vPromotions   │
                                    │ ○ PSN           │
                                    └────────────────┘
  ```
- **User Flow**: Single click on pill → dropdown → single click on product → dropdown closes.
- **Pros**:
  - Proximity to the app title reinforces "this is the active context for this session."
  - Compact: one line of header, no layout shift.
  - Consistent with existing pill/badge patterns (`health-badge`, `panel-badge`).
  - Easy to discover — visually distinct between the familiar title and the tab nav.
- **Cons**:
  - Center of the header becomes visually crowded when the tab nav has 4+ tabs.
  - The flexbox `space-between` layout needs a center-anchor fix or the pill drifts left when tabs narrow.
  - Inline placement between two existing elements risks overlap on small-viewport desktops (~1024px).
- **Usability**: High — immediately visible; one-click access; familiar select pattern.
- **Accessibility**: High — button with `aria-haspopup="listbox"` and `aria-expanded`; list items are `role="option"`.
- **Implementation Complexity**: Low — a single new component dropped into the existing header flex row.

---

### Option 2: Full-Width Sub-Header Bar Below Main Header

- **Approach**: A distinct horizontal band spanning the full dashboard width appears between the main header and the tab navigation. It contains the product selector on the left, and optional product metadata (e.g., "9 roles · vProMedia board") on the right.
- **Wireframe/Layout**:
  ```
  ┌────────────────────────────────────────────────────────────────────────────┐
  │  🔬 vQA   Autonomous QA Agent                    ● All Systems Go  [Logout] │
  ├────────────────────────────────────────────────────────────────────────────┤
  │  Product: [vProMedia ▾]                        9 roles · vProMedia board   │
  ├────────────────────────────────────────────────────────────────────────────┤
  │  [▶ Run Test]  [📚 Reports Archive]  [📊 Analytics]  [🎭 Playwright]       │
  └────────────────────────────────────────────────────────────────────────────┘
  ```
- **User Flow**: Sub-header always visible; user clicks dropdown in sub-header.
- **Pros**:
  - No header crowding — the product context gets its own visual zone.
  - Space for future product metadata (board name, role count).
  - Clear visual hierarchy: brand → context → action tabs.
- **Cons**:
  - Adds ~44px of vertical height to the header region, pushing content down further.
  - The sub-header creates a double-border effect that looks heavy without careful styling.
  - The product selector is now physically separated from the tab nav, weakening the mental model that "the product I selected filters what I see in the tabs."
  - Over-engineered for a 6-product internal tool.
- **Usability**: Medium — visually clear but increases vertical chrome.
- **Accessibility**: High — straightforward to implement correctly.
- **Implementation Complexity**: Medium — requires adjusting `.dashboard-header` margins, introducing a new flex row.

---

### Option 3: Right-Side Context Badge (After header-right content)

- **Approach**: The product selector is appended to `.header-right`, after the health badge and Logout button, appearing as a compact badge/button on the far right. It acts as a "context indicator" rather than a primary navigation element.
- **Wireframe/Layout**:
  ```
  ┌────────────────────────────────────────────────────────────────────────────┐
  │  🔬 vQA   Autonomous QA Agent   [▶ Run][📚 Archive][📊 Analytics][🎭 PW]  ● All Systems Go  [Logout]  [vProMedia ▾] │
  └────────────────────────────────────────────────────────────────────────────┘
  ```
- **User Flow**: User must scan to the far right to find the selector; click opens dropdown near right edge.
- **Pros**:
  - Minimal header restructuring — append to existing `.header-right` flex group.
  - Product badge stays out of the way for users who rarely switch products.
- **Cons**:
  - Discoverability is low — the selector is buried after Logout, far from the content it controls.
  - Tab nav sits between the selector and the content it filters, breaking spatial proximity.
  - The far-right position is already occupied by health badge + Logout; adding another element creates a cluttered right side.
  - Users who need to switch products must scan across the full header to reach it.
- **Usability**: Low — poor spatial relationship between selector and affected content.
- **Accessibility**: Medium — technically accessible but cognitively buried.
- **Implementation Complexity**: Low.

---

### Option 4: Inline Header Pill with Explicit "Product:" Label (Refined Option 1)

- **Approach**: Same placement as Option 1 (between `.header-left` and `.dashboard-tabs`) but the trigger includes an explicit "Product:" label to remove any ambiguity about what the control does for first-time users. The pill uses a colored left-border accent (per-product color) rather than a full background fill, keeping it visually lighter.
- **Wireframe/Layout**:
  ```
  ┌─────────────────────────────────────────────────────────────────────────────────────────┐
  │  🔬 vQA  Autonomous QA Agent    Product: [▌ vProMedia ▾]   [▶ Run][📚 Archive][📊…][🎭] │   ● All Systems Go  [Logout]  │
  └─────────────────────────────────────────────────────────────────────────────────────────┘
  ```
  The "Product:" prefix is rendered as `.product-selector-label` in `--text-secondary` color so it recedes visually; the product name itself is in `--text-primary` weight 600.
- **User Flow**: Same as Option 1 — one click opens dropdown.
- **Pros**:
  - "Product:" label eliminates any "what is this?" confusion for new users.
  - Colored left-border accent (not full background) avoids overpowering the header.
  - Per-product color is visible but unobtrusive.
  - Existing `health-badge` CSS pattern can be extended with minimal new CSS.
- **Cons**:
  - "Product:" prefix adds ~60px horizontal width at default font size — marginally tighter at 1024px.
  - Still requires adjusting header flexbox so center element doesn't drift.
- **Usability**: High — labeled control, minimal interaction cost.
- **Accessibility**: High — explicit visible label supplements aria attributes.
- **Implementation Complexity**: Low.

---

## Evaluation Matrix

| Criteria | Option 1 (Inline Pill) | Option 2 (Sub-header bar) | Option 3 (Right-side badge) | Option 4 (Labeled Pill — Refined) |
|----------|------------------------|--------------------------|------------------------------|-----------------------------------|
| Usability | High | Medium | Low | High |
| Accessibility | High | High | Medium | High |
| Consistency with existing patterns | High | Medium | High | High |
| Responsiveness (1024px+) | Medium | Medium | High | Medium |
| Performance | High | High | High | High |
| Implementation Complexity | Low | Medium | Low | Low |
| Discoverability | High | High | Low | High |
| Header crowding risk | Medium | Low | High | Medium |

---

## Decision

**Chosen**: Option 4 — Labeled Inline Pill with Per-Product Colored Left-Border Accent

### Rationale

Option 4 wins on the intersection of discoverability, usability, and implementation cost. The "Product:" label explicitly communicates the control's purpose without requiring users to hover or read aria tooltips — a meaningful benefit for an internal tool where not all users will be power users. The per-product colored left-border accent anchors the selector visually without overwhelming the header's deep-purple palette. 

Placement between `.header-left` and `.dashboard-tabs` puts the product context immediately left of the tabs it governs, establishing a natural left-to-right reading flow: brand → context → actions. This matches how internal tools at this complexity level typically work (e.g., GitHub's repo selector precedes the nav tabs).

Option 2 was rejected because the extra header row adds visual weight disproportionate to the feature's scope. Option 3 was rejected on discoverability grounds — placing the selector after Logout violates the spatial proximity principle between a filter and the content it filters. Option 1 is essentially Option 4 minus the explicit label; the label is worth the extra width.

### Trade-offs Accepted

- **Header crowding at 1024px**: The header is densest at 1024px. This is acceptable because the tool's primary use is on 1280px+ desktop displays (per productBrief.md — internal tool, ~10–50 users). A `@media (max-width: 1100px)` rule will hide the "Product:" label text and show only the product name + chevron to recover 60px of width at smaller viewports.
- **No color for fully-unconfigured products**: Products with zero roles and zero boards get a neutral `--text-secondary` color with a dashed left border instead of a product accent, signaling "not yet configured" rather than a full product identity. This is the intended visual state for vEP, vPPO, and PSN at launch.

---

## Design Specifications

### Layout

**Full Header Structure After Change**:
```
.dashboard-header  [display: flex; justify-content: space-between; align-items: center]
├── .header-left         [flex-shrink: 0]
│     ├── h1.app-title  "🔬 vQA"
│     └── span.app-subtitle  "Autonomous QA Agent"
├── .product-selector-wrapper   ← NEW [flex-shrink: 0; margin: 0 var(--space-lg)]
│     └── <ProductSelector />
├── nav.dashboard-tabs   [flex: 1; display: flex; justify-content: center]
└── .header-right        [flex-shrink: 0]
      ├── .active-run-label (conditional)
      ├── <HealthBadge />
      └── button[Logout]
```

Note: `.dashboard-tabs` gains `flex: 1` so it fills available space between the selector pill and the right controls, preventing the tabs from drifting left.

- **Desktop (1280px+)**: Full layout — "Product: [▌ vProMedia ▾]" with colored left-border accent.
- **Tablet (1024–1279px)**: "Product:" label hidden; pill shows "[▌ vProMedia ▾]" only. Achieved via `.product-selector-label { display: none }` at `max-width: 1100px`.
- **Mobile (<1024px)**: Not a target device. Header will scroll horizontally before collapsing.

### Per-Product Visual Language

Each product receives a **CSS variable pair**: an accent color and a muted (background-tint) variant. The colored left-border of the pill uses the accent color at full opacity; the pill background on hover uses the muted tint.

| Product | Slug | Accent Color | Muted Tint | Rationale |
|---------|------|-------------|------------|-----------|
| vProMedia | vpromedia | `hsl(262, 80%, 65%)` | `hsla(262, 80%, 65%, 0.12)` | Existing app accent purple — reinforces that vProMedia is the "home" product |
| vTrade | vtrade | `hsl(198, 80%, 55%)` | `hsla(198, 80%, 55%, 0.12)` | Teal/cyan — financial/trade association |
| vEP | vep | `hsl(152, 60%, 45%)` | `hsla(152, 60%, 45%, 0.12)` | Green — events/entertainment promotion |
| vPPO | vppo | `hsl(28, 90%, 55%)` | `hsla(28, 90%, 55%, 0.12)` | Orange — production/post-production energy |
| vPromotions | vpromotions | `hsl(340, 75%, 60%)` | `hsla(340, 75%, 60%, 0.12)` | Rose/pink — promotions/marketing |
| PSN | psn | `hsl(215, 70%, 58%)` | `hsla(215, 70%, 58%, 0.12)` | Blue — platform/network services |

**CSS Variables to Add** (in `:root` or a new `/* Product Tokens */` block in `index.css`):

```css
/* ── Product Color Tokens ─────────────────────────────────── */
--product-color-vpromedia:      hsl(262, 80%, 65%);
--product-color-vtrade:         hsl(198, 80%, 55%);
--product-color-vep:            hsl(152, 60%, 45%);
--product-color-vppo:           hsl(28, 90%, 55%);
--product-color-vpromotions:    hsl(340, 75%, 60%);
--product-color-psn:            hsl(215, 70%, 58%);

--product-muted-vpromedia:      hsla(262, 80%, 65%, 0.12);
--product-muted-vtrade:         hsla(198, 80%, 55%, 0.12);
--product-muted-vep:            hsla(152, 60%, 45%, 0.12);
--product-muted-vppo:           hsla(28, 90%, 55%, 0.12);
--product-muted-vpromotions:    hsla(340, 75%, 60%, 0.12);
--product-muted-psn:            hsla(215, 70%, 58%, 0.12);

/* Unconfigured product — neutral */
--product-color-unconfigured:   hsl(215, 16%, 50%);
--product-muted-unconfigured:   hsla(215, 16%, 50%, 0.10);
```

The `ProductSelector` component applies the color via an inline style or a `data-product` attribute, allowing the CSS to pick the correct token:

```css
/* Applied via data-product="vpromedia" on the trigger button */
.product-selector-trigger[data-product="vpromedia"] { --product-color: var(--product-color-vpromedia); --product-muted: var(--product-muted-vpromedia); }
.product-selector-trigger[data-product="vtrade"]    { --product-color: var(--product-color-vtrade);    --product-muted: var(--product-muted-vtrade);    }
/* ... etc for each slug */
```

### Full Wireframe — Chosen Design

```
Desktop (1440px):
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│  🔬 vQA  Autonomous QA Agent    Product: ┃ vProMedia ▾    [▶ Run Test ●][📚 Archive][📊 Analytics][🎭 Playwright]    ● All Systems Go  [Logout]  │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                                │  (click opens dropdown below)
                                           ┌────────────────────────────┐
                                           │  ┃ vProMedia         ✓    │  ← active product (colored left border)
                                           │  ─ vTrade                  │
                                           │  ─ vEP           ⚠ empty  │  ← empty state badge
                                           │  ─ vPPO          ⚠ empty  │
                                           │  ─ vPromotions             │
                                           │  ─ PSN           ⚠ empty  │
                                           └────────────────────────────┘

Tablet (1024px) — label hidden:
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│  🔬 vQA  Autonomous QA Agent    ┃ vProMedia ▾    [▶ Run Test ●][📚 Archive][📊 Analytics][🎭 Playwright]    ● All Systems Go  [Logout]  │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

The colored `┃` character represents the 3px left-border accent in the product's assigned color.

### Key Components

| Component | Purpose | Behavior |
|-----------|---------|----------|
| `ProductSelector` | Trigger + dropdown for product switching | Button with aria-haspopup; opens dropdown on click/Enter/Space; closes on Escape or outside click |
| `ProductContext` | React context providing active product slug + setProduct | Reads/writes localStorage; exposes `activeProduct`, `setProduct`, `productConfig` |
| `useProductContext` | Custom hook for consuming context | Throws if used outside `ProductProvider` |
| `ProductProvider` | Context provider wrapping the app | Initializes from localStorage; validates slug; falls back to "vpromedia" |

### Interactions

| Trigger | Action | Feedback |
|---------|--------|----------|
| Click selector trigger | Open product dropdown | Dropdown slides down (`transform: scaleY(1)` from `scaleY(0.9)`); chevron rotates 180° |
| Click product in dropdown | Set active product | Dropdown closes; trigger updates to new product name + color; ticket list re-fetches (spinner in list) |
| Press Escape with dropdown open | Close dropdown | Dropdown closes; focus returns to trigger |
| Arrow keys with dropdown open | Navigate options | Focus moves between options; active option highlighted |
| Tab key with dropdown open | Close dropdown | Close dropdown, focus advances to next focusable element |
| Hover product item in dropdown | Preview | Background tints to product muted color |

### Responsive Behavior

| Breakpoint | Changes |
|------------|---------|
| < 1100px | `.product-selector-label` ("Product:") hidden; pill shows product name + chevron only |
| 1100–1279px | Full labeled pill |
| 1280px+ | Full labeled pill; tabs have comfortable spacing |

### Accessibility Requirements

- [x] Keyboard navigation support — trigger is a `<button>`; dropdown is a `role="listbox"` with `role="option"` children; arrow keys move focus
- [x] Screen reader compatibility — trigger has `aria-haspopup="listbox"` and `aria-expanded={isOpen}`; each option has `aria-selected`; active product option has `aria-selected="true"`
- [x] Color contrast compliance (WCAG AA) — product accent colors are checked: all HSL values used achieve ≥ 3:1 contrast ratio against `--bg-secondary` for the left-border; the product name text uses `--text-primary` which is ≥ 4.5:1 against `--bg-secondary` in both themes
- [x] Focus indicators visible — standard `outline: 2px solid var(--border-focus)` ring on trigger and each dropdown option
- [x] Error messages accessible — disabled Run Test button includes `title` attribute and a visually-rendered tooltip component (not CSS `title` alone)

---

## Implementation Guidelines

### For Developers

1. **ProductContext placement**: Wrap the `<App>` (or the `<Dashboard>` route) in `<ProductProvider>`. The context must be available in both `Dashboard.tsx` and the Playwright page component since the selector appears in both headers.

2. **Header restructuring**: The existing `.dashboard-header` flex layout is `justify-content: space-between` with two children (`.header-left` and `.header-right`). The tabs are currently a direct child of the header — they are functionally a third item. After this change, the header has four flex children: `.header-left`, `.product-selector-wrapper`, `.dashboard-tabs` (with `flex: 1; justify-content: center`), and `.header-right`. Test at 1024px to verify no wrapping.

3. **Single-product hide rule**: If `productConfig.products.length === 1`, render the selector as a non-interactive static badge instead of a button. Apply class `.product-selector-static` which removes `cursor: pointer`, the chevron, and `aria-haspopup`. This prevents a confusing dropdown that contains only one option. IMPORTANT: This must be evaluated from the config array length, not a hardcoded flag.

4. **Ticket fetch cancellation** (AC-ASYNC-1): When `setProduct` is called, fire an `AbortController` signal on any in-flight `authenticatedFetch` call for the ticket list in `SelectView`. The `useProductContext` hook should expose a `productChangeSignal` (an `AbortSignal`) that `SelectView` passes as the `signal` option to `authenticatedFetch`.

5. **Empty-state (AC-ERROR-2) propagation**: `productConfig` for each product must include `{ hasBoards: boolean, hasRoles: boolean }`. `SelectView` reads these flags from context: if `!hasRoles`, the role `<select>` gets `disabled` with placeholder text "No roles configured for [Product Name]". The Run Test button reads `!hasBoards || !hasRoles` to determine its disabled state; the disabled button renders a `<Tooltip>` with text "Run Test is unavailable — [Product Name] has no configured roles or boards."

6. **localStorage key**: Use `localStorage.setItem('vqa_product', slug)` and `localStorage.getItem('vqa_product')`. This key is separate from the existing `vqa_role` and `vqa_targetUrl` keys.

7. **Default environment URL per product**: Each product entry in the config should carry `defaultTargetUrl`. When the user switches products, `SelectView` resets `targetUrl` to `productConfig.activeProduct.defaultTargetUrl` rather than the hardcoded `https://two-test.vcreative.net`.

### Component Structure

```
frontend/src/context/
├── ProductContext.tsx          ← ProductProvider, ProductContext, useProductContext hook
└── ProductContext.test.tsx     ← unit tests: fallback, localStorage read/write, single-product guard

frontend/src/components/
├── ProductSelector.tsx         ← trigger button + dropdown list; consumes useProductContext
├── ProductSelector.test.tsx    ← unit tests: open/close, keyboard nav, aria attrs, empty-state badge
└── ProductSelector.css         ← scoped styles for trigger, dropdown, option, left-border accent
```

### Recommended Libraries/Patterns

- No additional libraries needed. The dropdown is a simple controlled `<div>` with `role="listbox"`, consistent with the existing ticket combobox pattern in `SelectView.tsx` (which implements its own dropdown). Reuse the `useEffect` + `mousedown` outside-click handler pattern already present in `SelectView.tsx`.
- The tooltip for the disabled Run Test button should use the existing `title` attribute for simplicity in Phase 1, upgraded to a custom `<Tooltip>` component if the pattern is already established in the codebase.

---

## Empty-Product State Visual Treatment (AC-ERROR-2)

When a product has zero boards AND zero roles, the following visual states apply:

**In the selector dropdown**:
```
┌─────────────────────────────────────┐
│  ┃ vProMedia              ✓         │
│  ─ vTrade                           │
│  ─ vEP              ⚠ not configured│  ← amber badge, item still selectable
│  ─ vPPO             ⚠ not configured│
│  ─ vPromotions                      │
│  ─ PSN              ⚠ not configured│
└─────────────────────────────────────┘
```
The "⚠ not configured" badge uses `--status-running` (amber/orange) color to signal "not a failure, just not ready." Products that have some config but are incomplete (e.g., vTrade with 3 roles but no Playwright tests) do NOT show this badge — they are fully functional for what is configured.

**After selecting an unconfigured product**:
- Ticket list area: empty state card with message "No Jira board configured for [Product Name]. Contact the Platform Admin to add board credentials."
- Role dropdown: `<select disabled>` with a single `<option>` value "" and display text "No roles configured for [Product Name]".
- Run Test button: `disabled` attribute set; wrapper has a `data-tooltip` or aria-described tooltip reading "Run Test is unavailable — configure roles for [Product Name] to enable this."
- The selector pill itself shows the neutral `--product-color-unconfigured` left-border color (medium gray) rather than the product accent.

**When only 1 product is configured**:
- The selector renders as a static badge (`<span>` not `<button>`) with no dropdown, no chevron.
- CSS class `.product-selector-static` removes interactive affordances.
- `aria-label="Current product: vProMedia"` applied to the span for screen readers.
- This prevents the UX anti-pattern of a dropdown with exactly one choice.

---

## Validation Checklist

- [x] Meets all user goals — single-click product switch; always-visible context; disabled state with explanation
- [x] Accessible per requirements — full keyboard nav; ARIA listbox pattern; WCAG AA contrast
- [x] Consistent with existing patterns — extends `health-badge` pill visual language; reuses outside-click handler from `SelectView.tsx`
- [x] Respects Guiding Principles — `Config in Environment` (product config comes from env/config, not hardcoded); `12-Factor App`; `Mode-Centric Progressive Disclosure` (empty-state disables Run Test progressively rather than showing an error modal)
- [x] Responsive across devices — 1024px+ supported; label hidden at 1100px breakpoint
- [x] Performance acceptable — context switch triggers a single `authenticatedFetch` for tickets; no layout jank; dropdown is pure CSS transition
- [x] Implementation feasible — no new dependencies; all patterns already exist in the codebase

---

## Next Steps

1. Implement `ProductContext.tsx` with `ProductProvider`, `useProductContext`, localStorage initialization, fallback to "vpromedia", and `AbortController`-based `productChangeSignal`.
2. Implement `ProductSelector.tsx` with trigger button, dropdown list, keyboard navigation, and per-product color via `data-product` attribute.
3. Add product CSS tokens block to `frontend/src/index.css` under a new `/* Product Tokens */` comment section.
4. Restructure `Dashboard.tsx` header to insert `<ProductSelector>` between `.header-left` and `.dashboard-tabs`; add `flex: 1` to `.dashboard-tabs`.
5. Update `SelectView.tsx` role `<select>` and environment `<select>` to consume `useProductContext` — populate roles from `productConfig.activeProduct.roles`; default `targetUrl` from `productConfig.activeProduct.defaultTargetUrl`.
6. Add disabled Run Test state + tooltip in `ExecutionPanel.tsx` when `!productConfig.activeProduct.hasBoards || !productConfig.activeProduct.hasRoles`.
7. Apply same `<ProductSelector>` to the Playwright page header.
8. Write unit tests for `ProductContext` (fallback, persistence, single-product guard) and `ProductSelector` (open/close, keyboard nav, empty-state badge, static-badge mode).
