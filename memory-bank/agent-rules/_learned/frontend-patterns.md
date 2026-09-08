---
derived_from: [cu-loop-default-remove-toggle]
evidence_count: 2
last_validated: 2026-08-11
---
# Learned Rules: frontend-patterns

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **three-way-css-variant** (`frontend/src/components/*.tsx`, `*.css`): When a UI status banner or badge must distinguish between `pass`, `warn`, and `fail` states, introduce a **three-way CSS variant class** (`copilot-complete--pass`, `copilot-complete--warn`, `copilot-complete--fail`) from the start rather than a boolean `isSuccess` flag. A boolean flag cannot cleanly represent an intermediate warning state — it forces warning into either pass or fail, producing the "All N steps passed" class of misleading banner bug. Compute a `bannerVariant: "pass" | "warn" | "fail"` variable in the component and bind it to the class name: `className={`element--${bannerVariant}`}`.
  - _Source_: reflection-TASK-049 (2026-05-21)
  - _Reinforced_: 0x

- **disabled-link-pointer-events** (`frontend/src/components/*.tsx`, `*.css`): When rendering a disabled link as a `<span>` instead of an `<a>` (to prevent navigation to an unavailable resource), always set `pointer-events: none; cursor: default` in the CSS for the disabled variant. Without `pointer-events: none`, the span still responds to hover/click events — users experience ghost interactions (e.g., tooltip appears on hover, click does nothing), which is confusing. The disabled appearance (grayed color, cursor change) must be paired with disabled interactivity.
  - _Source_: reflection-TASK-049 (2026-05-21) — caught by code review Phase 4
  - _Reinforced_: 0x

- **colocate-page-css** (`frontend/src/pages/`, `frontend/src/index.css`): When creating a new React page that will exceed 300 lines of CSS, create a co-located `PageName.module.css` from the start rather than appending to `index.css`. Global CSS appends in a large codebase cause specificity conflicts and make component ownership opaque. The refactor cost grows linearly with the number of component-specific rules. Rule of thumb: if CSS blocks are prefixed with a unique page class (e.g., `.playwright-page`, `.playwright-terminal`), they belong in a module CSS file, not the global stylesheet.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **mode-centric-state-machine** (`frontend/src/components/*.tsx`): Decouple test configuration from execution using a 4-mode state machine (SELECT → REVIEW → RUNNING → COMPLETE) for complex multi-phase workflows. This reduces cognitive load by showing only the controls relevant to the current moment and allows the UI to stay clean and focused.
  - _Source_: reflection-TASK-065 (2026-05-29)
  - _Reinforced_: 0x

- **mode-aware-component-reuse** (`frontend/src/components/*.tsx`): Use a single component (e.g., `StepTable`) to handle data display across multiple workflow modes (e.g., REVIEW, RUNNING, COMPLETE). Pass a `mode` prop to toggle interaction levels (editable in REVIEW, read-only with live badges in RUNNING/COMPLETE) to ensure visual consistency and reduce code duplication.
  - _Source_: reflection-TASK-065 (2026-05-29)
  - _Reinforced_: 0x

- **data-theme-css-theming** (`frontend/src/index.css`, `frontend/index.html`, `frontend/src/hooks/useTheme.ts`): For app-wide theming, use `document.documentElement.setAttribute('data-theme', theme)` as the single source of truth rather than React state, context, or CSS-in-JS. Scope all color tokens under `[data-theme="dark"]` and `[data-theme="light"]` in `index.css`; keep non-color tokens (spacing, radii, fonts, transitions) in `:root {}` for universal availability. This approach requires zero prop-drilling, zero context overhead, and allows all CSS selectors to react to a single HTML attribute change — making theme transitions instant and all-encompassing.
  - _Source_: reflection-TASK-081 (2026-05-31)
  - _Reinforced_: 0x

- **fouc-prevention-inline-script** (`frontend/index.html`): When reading theme preference from `localStorage` at app startup, place a synchronous inline `<script>` in `<head>` that applies the `data-theme` attribute _before_ the browser renders any pixels. A React `useEffect` runs after first paint and causes a visible flash-of-unstyled-content (FOUC). The inline script's fallback chain (localStorage → matchMedia → default) must be identical to the custom hook's `getInitialTheme()` function to ensure consistency.
  - _Source_: reflection-TASK-081 (2026-05-31)
  - _Reinforced_: 0x

- **hook-without-context-l2** (`frontend/src/hooks/*.ts`): For Level 2 theming and preference features, a single `useEffect`-syncing custom hook (e.g., `useTheme`) is sufficient — no `Context`, no `Provider`, no Redux slice. The DOM attribute (`data-theme` on `<html>`) replaces the context as the broadcast mechanism for CSS. Reserve `ThemeContext` for cases where the theme value must be _read_ synchronously by multiple React subtrees that cannot observe the DOM attribute (e.g., in jsdom test environments).
  - _Source_: reflection-TASK-081 (2026-05-31)
  - _Reinforced_: 0x

- **theme-aware-vnc-injection** (`backend/engine/human_takeover.py`): Inject the application's active PrimeNG theme class (`p-theme-light` or `p-theme-dark`) into the `document.body` of the VNC session via `add_init_script`. This ensures visual consistency and prevents interactive elements from becoming invisible due to theme-mismatch CSS rules.
  - _Source_: reflection-TASK-084 (2026-06-01)
  - _Reinforced_: 0x

- **keyed-local-state-isolation** (`frontend/src/components/*.tsx`): When mounting a sub-component with local editing state (e.g. textareas, checkboxes, dropdowns) representing a specific item, always key the component call-site using the item's unique identifier (e.g., `key={selectedTicket.id}`). This leverages React's native unmounting/remounting boundary to automatically clean up and initialize state when switching items, completely avoiding state-bleed bugs without requiring complex manual `useEffect` or property resetting logic.
  - _Source_: reflection-TASK-098 (2026-06-03)
  - _Reinforced_: 1x (TASK-108 applied + confirmed)

- **form-label-counter-alignment** (`frontend/src/components/*.tsx`, `*.css`): For form inputs with length limits, lay out the input label and character counter in a flex container with `justify-content: space-between`. This keeps the counter aligned to the far right on the same line as the label, avoiding awkward vertical line wrapping or layout shifts when operators type long instructions.
  - _Source_: reflection-TASK-098 (2026-06-03)
  - _Reinforced_: 0x

- **hitl-dom-capture-reminder-banner** (`frontend/src/components/TakeoverPanel.tsx`): Display a warning banner to operators when they start typing an explanation but have not interacted with the browser window (meaning recorded actions count is zero). This prevents the operator from completing the session with a text-only explanation that the agent's learning engine cannot use, and guides them to demonstrate the workflow physically in the VNC screen.
  - _Source_: reflection-TASK-103 (2026-06-03)
  - _Reinforced_: 0x

- **metadata-display-name-fallback** (`frontend/src/components/*.tsx`): In client-side registries presenting file-backed metadata (such as tests or scripts), always provide a robust text-formatting utility (e.g., stripping file extensions, transforming hyphens/underscores to spaces, and capitalizing words while preserving acronyms) as a fallback when an explicit `display_name` attribute is missing. This prevents displaying raw, unpolished filenames to users.
  - _Source_: reflection-TASK-108 (2026-06-08)
  - _Reinforced_: 0x

- **react-fast-refresh-isolated-helpers** (`frontend/src/lib/*.ts`, `frontend/src/pages/*.tsx`): In modern React/Vite projects, never export non-component modules (such as helper functions or state structures) directly from React page or component files. Doing so violates Fast Refresh/Hot Module Replacement regulations, degrading HMR performance and causing ESLint Fast Refresh compiler errors. Shared helper functions and text formatters must always be isolated in dedicated library or utility modules (`src/lib/*` or `src/utils/*`) to keep components clean, fast, and fully compilable.
  - _Source_: reflection-TASK-109 (2026-06-08)
  - _Reinforced_: 1x (TASK-122: `buildGuidance()` wizard serialization extracted to `wizardGuidance.ts`, enabling 5 pure unit tests without React mounting)

- **modal-serialization-utility-extraction** (`frontend/src/lib/*.ts`, `frontend/src/components/*.tsx`): When a modal component must serialize its internal state (e.g., selected paths, resolutions) into a string payload for an API request, extract the serialization function into a standalone `src/lib/` utility module rather than inlining it in the component or the parent handler — this enables pure unit testing of the serialization logic without mounting the component and is required by the Fast Refresh isolated-helpers constraint.
  - _Source_: reflection-TASK-122 (2026-07-14)
  - _Reinforced_: 0x

- **bundle-transitive-cleanup-with-removal** (`frontend/src/components/*.tsx`, `frontend/src/pages/*.tsx`): When a code-deletion task removes a React state, effect, or JSX block, delete the transitively unused dependents (imports, local vars, hook destructures, type imports that were only referenced from the removed branch) in the **same commit** as the primary removal. TypeScript's `noUnusedLocals`/`noUnusedParameters` and `tsc --noEmit` make these transitively dead references trivial to detect. Bundling keeps the diff coherent — a reviewer sees "this state is gone AND everything that fed it is gone" in one hunk — and avoids a follow-up "clean up unused vars" commit that obscures the original intent. Example: removing `useComputerUseLoop` also deletes the `ExecuteRequest` import, the `pendingGuidance` state, the `finalGuidance` local, and the `startExecution` destructure — all in one commit.
  - _Source_: reflection-cu-loop-default-remove-toggle (2026-08-11)
  - _Reinforced_: 0x
