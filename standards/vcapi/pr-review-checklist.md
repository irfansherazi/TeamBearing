# vcAPI PR Code Review Script

On the **vcapi** (NestJS) app, after code changes are done, run this review on Cursor or Copilot to score the changes.

This checklist is for **vcapi only**. It does not replace GitHub PR tools (CodeRabbit / Copilot PR review / CI). It does not change `AGENTS.md` or existing vcapi workflows.

## How to Run

Commands live on the **vsuitePlatform** AI review tool and target this repo with `--app=vcapi`.

**Terminal (PASS/FAIL report)** — run from `vsuitePlatform/`:
- Branch / PR diff: `npm run ai:review -- --app=vcapi`
- Local uncommitted work: `npm run ai:review:changed -- --app=vcapi`
- Override base: `npm run ai:review -- --app=vcapi --base=master`
- Another branch: `npm run ai:review -- --app=vcapi --branch=Some/VC2-xxxx`
- Include test run: `npm run ai:review -- --app=vcapi --run-tests`

**Chat (Cursor, Copilot, or any AI with project access):**
- Say `ai:review --app=vcapi` or `ai:review:changed --app=vcapi`
- Agent runs the matching `ai:review:scope` command and posts PASS/FAIL per checklist ID
- **Review only** — agent suggests fixes in chat; developer applies changes

**Full terminal automation for semantic items:** set `AI_REVIEW_COMMAND` to your AI CLI.

> Branch comparison is always **within the vcapi git repo** (feature branch vs `develop` / `master` / etc.).

## Source of Truth

Use the following as strict source of truth:

- `AGENTS.md` (vcapi mandates — logging, catch handling, git branching, testing)
- The Pull Request Checklist below

## Scope

- Review ONLY the changes introduced in this PR / scope.  
- Do NOT review untouched code.  
- When a **handler, service method, or multi-step array pipeline** is in scope, read the **entire changed block** end-to-end (split → transform → merge), not only isolated diff hunks. Logic-consistency bugs often span multiple lines in the same function.

## Verification Areas

### 1. Code Quality

- **[CQ-01]** Code follows team conventions (naming, formatting, structure). Prefer **double quotes** to match existing vcapi style.  
- **[CQ-02]** No commented-out or dead code.  
- **[CQ-03]** Safe navigation is used where necessary.  
- **[CQ-04]** Deep review of modified logic completed.  
- **[CQ-05]** No `console.log` / `console.warn` / `console.error` / `debugger` inside NestJS services or controllers. `console.*` is only acceptable in non-NestJS scripts (plain Node CLI tools, migration scripts, etc.). Do not use NestJS `Logger` (`this.logger`) — it is not the team convention.  
- **[CQ-06]** Logging in NestJS services uses `request.emit('addLog', message)`. If a private helper needs to log, thread `request?: Request` and call `request?.emit(...)`. Never fall back to `console.*` in a helper that could receive a request.  
- **[CQ-07]** RabbitMQ consumers and other background/queue contexts (no real HTTP request) use `fakeRequest` from `src/app.service.util` and pass it as the `request` argument to service methods that accept one.  
- **[CQ-08]** Linting passes (`npm run lint`).  
- **[CQ-09]** Unit tests added/updated where required.  
- **[CQ-10]** Optional chaining is properly used.  
- **[CQ-11]** Boolean / nullish defaults use `??`, not `||` or `&&` (so `false` is not treated as missing).  
- **[CQ-12]** Methods under a "Private helpers" (or equivalent) section are declared `private` / `protected`; specs use `(service as any)` or public API — do not leave helpers public by omission.  
- **[CQ-13]** No hard-coded floating US holidays as fixed MM/DD (e.g. Thanksgiving `"11/28"` / Day after `"11/29"`). Compute year-aware dates (4th Thursday of November + Friday after) or equivalent. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[CQ-14]** Control-structure indentation matches nesting (no accidental +1 indent on `for` / `if` after merges).  
- **[CQ-15]** API / list → DTO or entity mapping: coerce ids (`Number(...)`), normalize strings, and **filter** invalid rows (`Number.isFinite(id)`); do not map with untyped `any` and pass through raw `u.id` that can become `undefined` / `NaN`. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[CQ-16]** No `hasOwnProperty()` — use optional chaining (`?.`) or explicit structure checks instead.  
- **[CQ-17]** No disabling/suppressing ESLint rules in changed code (e.g. `// eslint-disable-next-line`, `/* eslint-disable */`) — fix the underlying issue instead.  
- **[CQ-18]** String building uses template literals (`` `${a} ${b}` ``), not `+` concatenation.  
- **[CQ-19]** Class members use `public`/`private` appropriately based on actual usage outside the class — not left public by default (extends CQ-12 beyond just "Private helpers" sections).  
- **[CQ-20]** `} else {` is formatted on the same line as the closing brace, not dropped to a new line.  
- **[CQ-21]** Repetitive `if`/`else` chains use `switch` or an object/map lookup where applicable.  
- **[CQ-22]** Callbacks use arrow functions, not anonymous `function` expressions.  
- **[CQ-23]** No unnecessary duplicated logic — reuse existing helpers/services instead of re-implementing.  
- **[CQ-24]** Never leave empty/open `catch` blocks. Exceptions must be logged or handled. If the correct action is unclear, stop and ask — do not silently swallow errors.

### 2. Functionality

- **[F-01]** No unintended functionality changes.  
- **[F-02]** No side effects introduced.  
- **[F-03]** Feature works as expected.  
- **[F-04]** Edge cases and error handling covered.  
- **[F-05]** No major performance concerns.  
- **[F-06]** Domain parity: date / lead-time / order (or equivalent product) rules match the established path, not a one-off soft rule. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[F-07]** Dual-gate: business rules that create or reject server-side drafts or equivalent must be enforced on the backend (and stay aligned with FE when both change). If not in scope, **PASS** with note `N/A — not in scope`.  
- **[F-08]** User-facing or client-facing error messages for expected mistakes match existing product tone (short actionable text), not raw upstream / unexpected-format dumps. If not in scope, **PASS** with note `N/A — not in scope`.

### 3. Documentation

- **[D-01]** Code is self-explanatory or properly commented.  
- **[D-02]** Readme/docs updated if required.  
- **[D-03]** New/modified methods have a JSDoc block (description + `@param` per argument + return description where applicable).  
- **[D-04]** Comments are adjacent/local to the code they describe, not detached, generic, or explaining unrelated lines.

### 4. Testing

- **[T-01]** Relevant unit tests pass (`npm test`). Do **not** invoke `npx jest` directly — always use `npm test` (partial path match is fine, e.g. `npm test common-tpi.controller`).  
- **[T-02]** Feature tested across roles/users if applicable. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[T-03]** New/modified unit tests prefer a clear test-case structure (`description` / `setup` / `expectations` through `.forEach(...)` + `it(...)`) when that pattern fits the file — avoid opaque one-off tests without structure.  
- **[T-04]** Tests cover valid, invalid, and edge-case inputs — not only the happy path.  
- **[T-05]** Test case names are descriptive, and `setup`/`expectations` (or equivalent) helpers are clear and single-purpose.  
- **[T-06]** When a `describe` adds Jest spies, restore them in `afterEach` with `jest.restoreAllMocks()` (isolate spies per describe). If no spies were added, **PASS** with note `N/A — not in scope`.

### 5. Collaboration & PR Hygiene

- **[PH-01]** PR title and description are clear.  
- **[PH-02]** Related ticket/issue/story is linked.  
- **[PH-03]** Required SQL is added to Jira Dev Notes (not PR comments). If no SQL, **PASS** with note `N/A — not in scope`.  
- **[PH-04]** Feature branches created from a base use `--no-track` (e.g. `git checkout -b name --no-track origin/master`). First push of a new branch uses `-u` to set tracking to the feature branch (`git push -u origin name`). If branch creation/push is not part of this review, **PASS** with note `N/A — not in scope`.

### 6. Modified-Logic Deep Dive

Apply when changed code includes **handlers, service pipelines, or multi-step array pipelines** (split → transform → merge). If that pattern is not in scope for an ID, mark **PASS** with note `N/A — not in scope` (do not omit the ID).

- **[LD-01]** New logic matches established patterns in the **same file** for the same operation (e.g. same sort/filter/split style as an existing equivalent in that service).  
- **[LD-02]** No bare `Array.sort()` on arrays of objects — always use an explicit comparator (`localeCompare` for labels, numeric diff for sort fields, etc.).  
- **[LD-03]** Optional property checks are **consistent within the same handler** (value-based: `prop === undefined` / `prop !== undefined`); do not mix `'prop' in item` with value checks for the same field.  
- **[LD-04]** Handler flow integrity: trace split → transform → merge; no item bucketed in step 1 may be silently dropped before merge.  
- **[LD-05]** Regex and lookup guards: no `.match(...)[0]`, `.find()[0]`, or similar without checking for null/undefined first.  
- **[LD-06]** Logic that depends on a looked-up object runs **inside** its null/undefined guard block, not after it when the object may be missing.

#### Logic deep dive examples (for reviewers)

```ts
// LD-02 FAIL — default sort on objects
items.sort();

// LD-02 PASS
items.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));

// LD-03 PASS — consistent value checks in one handler
mainItems = items.filter(i => i.filterID === undefined);
folderItems = items.filter(i => i.filterID !== undefined);

// LD-05 FAIL
const count = folder.label.match(/\(\d+\)/)[0];

// LD-05 PASS
const countMatch = folder.label.match(/\(\d+\)/);
folder.label = countMatch ? `${newName} ${countMatch[0]}` : newName;
```

#### Sendback examples (CQ / T / PH)

```ts
// CQ-05 FAIL — console in Nest service
console.log('processing', dto);

// CQ-05 PASS — use request pipeline
request.emit('addLog', `processing ${dto.id}`);

// CQ-06 FAIL — helper logs with console
private helper() {
    console.warn('missing id');
}

// CQ-06 PASS — thread request
private helper(request?: Request) {
    request?.emit('addLog', 'missing id');
}

// CQ-07 FAIL — queue job with no request logging path
await this.aiService.processNaturalLanguage(dto);

// CQ-07 PASS
await this.aiService.processNaturalLanguage(dto, fakeRequest as any);

// CQ-11 FAIL — boolean false becomes null
datesAdjustedForLeadTime: flag || null

// CQ-11 PASS
datesAdjustedForLeadTime: flag ?? null

// CQ-24 FAIL — empty catch
try {
    await this.save(entity);
} catch (e) {}

// CQ-24 PASS — handle or log
try {
    await this.save(entity);
} catch (e) {
    request?.emit('addLog', `save failed: ${e}`);
    throw e;
}

// CQ-16 FAIL
if (config.hasOwnProperty('settings')) { /* ... */ }

// CQ-16 PASS
if (config?.settings) { /* ... */ }

// CQ-17 FAIL
// eslint-disable-next-line no-unused-vars
const unused = getThing();

// CQ-17 PASS — fix the underlying issue instead of silencing the rule

// CQ-18 FAIL
const greeting = hi + ' ' + name;

// CQ-18 PASS
const greeting = `${hi} ${name}`;

// CQ-20 FAIL
if (x) {
    // ...
}
else {
    // ...
}

// CQ-20 PASS
if (x) {
    // ...
} else {
    // ...
}

// CQ-22 FAIL
items.forEach(function (item) { process(item); });

// CQ-22 PASS
items.forEach((item) => { process(item); });

// T-01 FAIL
npx jest --testPathPattern=common-tpi.controller.spec

// T-01 PASS
npm test common-tpi.controller

// T-06 FAIL — spies left installed across tests
describe('MyService', () => {
    it('spies once', () => {
        jest.spyOn(service, 'save').mockResolvedValue(null);
    });
});

// T-06 PASS
describe('MyService', () => {
    afterEach(() => {
        jest.restoreAllMocks();
    });
    it('spies once', () => {
        jest.spyOn(service, 'save').mockResolvedValue(null);
    });
});

// PH-04 FAIL — tracks origin/master by accident
git checkout -b chrisf/my-feature origin/master

// PH-04 PASS
git checkout -b chrisf/my-feature --no-track origin/master
git push -u origin chrisf/my-feature
```

## Output Format

For EACH checklist item (CQ, F, D, T, PH, LD):

- Mark PASS or FAIL (use **PASS** + `N/A — not in scope` when the rule does not apply — do not drop the ID)  
- If FAIL:
  - Explain clearly  
  - Show **suggested** corrected code in chat or Notes (example only — do not apply it)  

If no issues are found:
- Explicitly confirm that ALL checklist items PASS  
- Also mention which code you reviewed  
