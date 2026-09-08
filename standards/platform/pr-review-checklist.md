# Angular PR Code Review Script

On Angular app after code changes are done we run this script on cursor or copilot to review the code changes.

## How to Run

**Terminal (PASS/FAIL report):**
- Branch / PR diff: `npm run ai:review`
- Local uncommitted work: `npm run ai:review:changed`
- Override base: `npm run ai:review -- --base=master`
- Include test run: `npm run ai:review -- --run-tests`

**Chat (Cursor, Copilot, or any AI with project access):**
- Say `ai:review` or `ai:review:changed` in chat
- Agent runs `npm run ai:review:scope` and posts PASS/FAIL per checklist ID
- **Review only** — agent suggests fixes in chat; developer applies changes

**Full guide:** see [AI-REVIEW-GUIDE.md](AI-REVIEW-GUIDE.md)

**Full terminal automation for semantic items:** set `AI_REVIEW_COMMAND` to your AI CLI.

## Source of Truth
Use the following as strict source of truth:

- PROMPT_coding_conventions.md  
- Code-Conventions-Pilot.md  
- PROMPT_unit_test.md  
- The GitHub Pull Request Checklist below  

## Scope
- Review ONLY the changes introduced in this PR.  
- Do NOT review untouched code.  
- When a **handler, subscription, or multi-step array pipeline** is in scope, read the **entire changed block** end-to-end (split → transform → merge), not only isolated diff hunks. Logic-consistency bugs often span multiple lines in the same function.

## Verification Areas

### 1. Code Quality
- **[CQ-01]** Code follows team conventions (naming, formatting, structure).  
- **[CQ-02]** No commented-out or dead code.  
- **[CQ-03]** Safe Navigation is used where necessary.  
- **[CQ-04]** Deep review of modified logic completed.  
- **[CQ-05]** No console.log or debugger statements.  
- **[CQ-06]** Linting passes (npm run lint).  
- **[CQ-07]** Unit tests added/updated where required.  
- **[CQ-08]** Component lifecycle — no leaks after destroy (covers former CQ-18 + T-02). Score **once** under CQ-08. All that apply must hold; if none apply, mark **PASS** with note `N/A — no timers/async lifecycle in scope` (still score this ID — do not omit):
  1. Every `setTimeout` / poll timer is tracked and **cleared** in `ngOnDestroy` (or equivalent).
  2. Recursive polls (`setTimeout` → schedule next) must not leave a live timer after destroy.
  3. Promise `.then` / `.catch` (poll status, upload, submit, getSpots, etc.) must bail when destroyed — `if (this.destroyed) { return; }` — **or** use `destroy$` + `takeUntil` / equivalent so a destroyed instance cannot reschedule polls or keep making network calls.
  4. No unmanaged listeners / recognition / subjects that keep the instance alive after navigate-away.  
- **[CQ-09]** No hardcoded plain text; all user-facing strings use the translation service.  
- **[CQ-10]** Optional chaining is properly used.  
- **[CQ-11]** New or modified API calls use **vcAPI** (`VcApiService` / `this.vcApi` / `vcApiService`) — not `doRequest`. Any `doRequest` added or left in changed code should be migrated to vcAPI.
- **[CQ-12]** Boolean / nullish defaults use `??`, not `||` or `&&` (so `false` is not treated as missing).  
- **[CQ-13]** External browser / media API `stop()` / `abort()` (e.g. SpeechRecognition) wrapped in try/catch; listening/state flags always cleared afterward.  
- **[CQ-14]** Soft / inline UX errors (mic permission, voice, recoverable validation) must **not** use ErrorService severity that navigates away (e.g. severity `2` → toast + `backHome()`). Prefer inline message or non-navigating severity.  
- **[CQ-15]** Methods under a "Private helpers" (or equivalent) section are declared `private` / `protected`; specs use `(service as any)` or public API — do not leave helpers public by omission.  
- **[CQ-16]** No hard-coded floating US holidays as fixed MM/DD (e.g. Thanksgiving `"11/28"` / Day after `"11/29"`). Compute (4th Thursday of November + Friday after) or equivalent year-aware logic.  
- **[CQ-17]** Control-structure indentation matches nesting (no accidental +1 indent on `for` / `if` after merges).  
- **[CQ-19]** Do not type browser / Web Speech refs or their handlers as `any` (e.g. `recognition: any`, `onresult = (event: any)`). Use a proper type (`SpeechRecognition` / event type) or unknown + narrow/validate before reading `.result` / `.error` / looping. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[CQ-20]** API list → DTO mapping: coerce ids (`Number(...)`), normalize strings, and **filter** invalid rows (`Number.isFinite(id)`); do not map with untyped `any` and pass through raw `u.id` that can become `undefined` / `NaN` in UI. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[CQ-21]** Do not pre-translate the `user_message` passed into `ErrorService.logError()` (e.g. `this.translateService.instant(...)` / `.get(...)`). `logError` already runs `this.translateService.instant(user_message)` internally (`error.service.ts`); pass the raw translation key/string and let the service translate it once.  
- **[CQ-22]** New/changed HTML elements that render content (buttons, dropdowns, inputs, lists, etc.) have a unique, hyphen-separated `id` (e.g. `id="example-of-id"`), checked for uniqueness within the project before use.  
- **[CQ-23]** No `async`/`await` in frontend (Angular) code — use `.then()`/`.catch()` for all Promises.
- **[CQ-24]** No `hasOwnProperty()` — use optional chaining (`?.`) or explicit structure checks instead.
- **[CQ-25]** No disabling/suppressing ESLint rules in changed code (e.g. `// eslint-disable-next-line`, `/* eslint-disable */`) — fix the underlying issue instead.
- **[CQ-26]** String building uses template literals (`` `${a} ${b}` ``), not `+` concatenation.
- **[CQ-27]** Class members use `public`/`private` appropriately based on actual usage outside the component/service — not left public by default (extends CQ-15 beyond just "Private helpers" sections).
- **[CQ-28]** Observable-typed properties (`Subject`, `BehaviorSubject`, `ReplaySubject`, etc.) use a `$` suffix (e.g. `data$`). If not in scope, **PASS** with note `N/A — not in scope`.
- **[CQ-29]** `} else {` is formatted on the same line as the closing brace, not dropped to a new line.
- **[CQ-30]** Repetitive `if`/`else` chains use `switch` or an object/map lookup where applicable.
- **[CQ-31]** Callbacks use arrow functions, not anonymous `function` expressions.
- **[CQ-32]** No unnecessary duplicated logic — reuse existing helpers/services instead of re-implementing.
- **[CQ-33]** User-facing text in HTML templates uses `| language_pipe` (complements CQ-09, which covers TS-side `translateService` usage). If not in scope, **PASS** with note `N/A — not in scope`.

### 2. Functionality
- **[F-01]** No unintended functionality changes.  
- **[F-02]** No side effects introduced.  
- **[F-03]** Feature works as expected.  
- **[F-04]** Edge cases and error handling covered.  
- **[F-05]** No major performance concerns.  
- **[F-06]** Domain parity: date / lead-time / order rules match the established product path (e.g. Quick Orders `addLeadDays` / min-lead), not a one-off soft rule. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[F-07]** Dual-gate: business rules that create or reject server-side drafts (caps, invalid counts/durations, vague prompts) are enforced on **both** FE and backend. If not in scope, **PASS** with note `N/A — not in scope`.  
- **[F-08]** User-facing errors for expected mistakes match existing product tone (short “could not … Please … try again”), not raw Bedrock / unexpected-format text.  

### 3. Documentation
- **[D-01]** Code is self-explanatory or properly commented.  
- **[D-02]** Readme/docs updated if required.  
- **[D-03]** New/modified methods have a JSDoc block (description + `@param` per argument + return description where applicable).
- **[D-04]** Comments are adjacent/local to the code they describe, not detached, generic, or explaining unrelated lines.

### 4. Testing
- **[T-01]** All existing tests pass (npm run test).  
- **[T-03]** Relevant E2E/Cypress tests added or updated.  
- **[T-04]** Feature tested across roles/users if applicable.  
- **[T-05]** Spec setup: `await` async helpers in `beforeAll` / `beforeEach` (e.g. `getUserAndToken`); CI-known seed emails only (reuse emails already used in passing specs — avoid one-off users that 401 in CI).  
- **[T-06]** Specs do not pass a possibly-null `getUserForTest` / SSO fixture into code that reads `.user` without asserting or mocking a real user.  
- **[T-07]** New/modified unit tests use the required test-case-array structure (`description` / `setup` / `expectations` objects run through `.forEach(...)` + `it(...)`), not one-off `it()` blocks.
- **[T-08]** Tests cover valid, invalid, and edge-case inputs — not only the happy path. Before scoring **PASS**, name the specific ways the new/changed input can be malformed or wrong-shaped (e.g. valid JSON but wrong structure, empty vs. `null` vs. missing) and confirm a test exists for each one — a generically-labeled "edge case" test that doesn't exercise the actual failure mode does not satisfy this rule.
- **[T-09]** Test case names are descriptive, and `setup`/`expectations` functions are clear and single-purpose.

> Former **CQ-18** and **T-02** are folded into **CQ-08** — do not score them separately.

### 5. Collaboration & PR Hygiene
- **[PH-01]** PR title and description are clear.  
- **[PH-02]** Related ticket/issue/story is linked.  
- **[PH-03]** Screenshots/videos attached for UI changes.  
- **[PH-04]** Required SQL is added to Jira Dev Notes (not PR comments).  

### 6. Modified-Logic Deep Dive

Apply when changed code includes **handlers, RxJS subscriptions, or multi-step array pipelines** (split → transform → merge). If that pattern is not in scope for an ID, mark **PASS** with note `N/A — not in scope` (do not omit the ID).

- **[LD-01]** New logic matches established patterns in the **same file** for the same operation (e.g. same sort/filter/split style as an existing equivalent in that component/service).  
- **[LD-02]** No bare `Array.sort()` on arrays of objects — always use an explicit comparator (`localeCompare` for labels, numeric diff for `sort_order`, etc.).  
- **[LD-03]** Optional property checks are **consistent within the same handler** (value-based: `prop === undefined` / `prop !== undefined`); do not mix `'prop' in item` with value checks for the same field.  
- **[LD-04]** Handler flow integrity: trace split → transform → merge; no item bucketed in step 1 may be silently dropped before merge.  
- **[LD-05]** Regex and lookup guards: no `.match(...)[0]`, `.find()[0]`, or similar without checking for null/undefined first.  
- **[LD-06]** Logic that depends on a looked-up object runs **inside** its null/undefined guard block, not after it when the object may be missing.  
- **[LD-07]** `JSON.parse(...)` results assigned to a typed property, or used to branch business/UI logic, are shape-validated before use (e.g. `Array.isArray(...)`, expected keys present) — not just wrapped in try/catch. A successfully-parsed value of the wrong shape (a string, a plain object, an array of non-objects) must not be treated as if it matched the expected type.

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

// LD-07 FAIL — parses fine but shape isn't checked before use
try {
    this.scriptTables = JSON.parse(this._fieldControl.value);
} catch {
    this.scriptTables = null;
}

// LD-07 PASS — shape validated before assignment
try {
    const parsed = JSON.parse(this._fieldControl.value);
    this.scriptTables =
        Array.isArray(parsed) && parsed.every((row) => row && typeof row === 'object') ? parsed : null;
} catch {
    this.scriptTables = null;
}
```

#### Sendback examples (CQ-08, CQ-12 … CQ-33, T-05, T-07)

```ts
// CQ-12 FAIL — boolean false becomes null
datesAdjustedForLeadTime: flag || null

// CQ-12 PASS
datesAdjustedForLeadTime: flag ?? null

// CQ-13 FAIL — stop() can throw InvalidStateError; flags may stick
this.recognition.stop();
this.isListening = false;

// CQ-13 PASS
try { this.recognition.stop(); } catch { /* already ended */ }
this.isListening = false;

// CQ-14 FAIL — severity 2 navigates home
this.errorService.logError('Speech recognition error', 2, event.error);

// CQ-14 PASS — stay on page
this.speechError = 'Microphone access was blocked…';

// CQ-21 FAIL — double-translation, logError already calls instant() internally
this.errorService.logError(spot, 1, this.translateService.instant('There was an error posting your comment'), err);

// CQ-21 PASS — pass the raw key/string, let logError translate it
this.errorService.logError(spot, 1, 'There was an error posting your comment', err);

// CQ-22 FAIL — content-bearing button with no id
<button (click)="save()">Save</button>

// CQ-22 PASS — unique, hyphen-separated id
<button id="save-spot-button" (click)="save()">Save</button>

// CQ-15 FAIL — under "Private helpers" but public by default
toUserFacingIngestError(err: unknown): string { … }

// CQ-15 PASS
private toUserFacingIngestError(err: unknown): string { … }

// CQ-16 FAIL
"11/28": "Thanksgiving Day",
"11/29": "Day after Thanksgiving",

// CQ-08 FAIL — poll .then after destroy can reschedule forever
.getProcessStatus(processId).then((status) => {
    this.handlePollResult(processId, status); // no destroyed check
});

// CQ-08 PASS
.getProcessStatus(processId).then((status) => {
    if (this.destroyed) { return; }
    this.handlePollResult(processId, status);
});

// CQ-19 FAIL
private recognition: any = null;
r.onresult = (event: any) => { for (let i = event.resultIndex; …) }

// CQ-19 PASS
private recognition: SpeechRecognition | null = null;
r.onresult = (event: SpeechRecognitionEvent) => { /* use typed fields */ }

// CQ-20 FAIL
return list.map((u: any) => ({ id: u.id, first_name: u.first_name || '' }));

// CQ-20 PASS
return list
    .map((u) => ({
        id: Number((u as { id?: unknown })?.id),
        first_name: String((u as { first_name?: unknown })?.first_name ?? '').trim(),
    }))
    .filter((u) => Number.isFinite(u.id));

// T-05 FAIL
tokenAndUser = testService.getUserAndToken(...); // missing await
await getUserForTest('ProductionDir'); // unknown CI seed → 401

// T-05 PASS
tokenAndUser = await testService.getUserAndToken(...);
await getUserForTest('DemoProdDirector'); // known CI seed

// CQ-23 FAIL — async/await in frontend code
const result = await someServiceCall();

// CQ-23 PASS
someServiceCall().then(result => { /* handle */ }).catch(error => { /* handle */ });

// CQ-24 FAIL
if (config.hasOwnProperty('settings')) { /* ... */ }

// CQ-24 PASS
if (config?.settings) { /* ... */ }

// CQ-25 FAIL
// eslint-disable-next-line no-unused-vars
const unused = getThing();

// CQ-25 PASS — fix the underlying issue instead of silencing the rule

// CQ-26 FAIL
const greeting = hi + ' ' + name;

// CQ-26 PASS
const greeting = `${hi} ${name}`;

// CQ-28 FAIL
const loading = new BehaviorSubject<boolean>(true);

// CQ-28 PASS
const loading$ = new BehaviorSubject<boolean>(true);

// CQ-29 FAIL
if (x) {
    // ...
}
else {
    // ...
}

// CQ-29 PASS
if (x) {
    // ...
} else {
    // ...
}

// CQ-31 FAIL
items.forEach(function (item) { process(item); });

// CQ-31 PASS
items.forEach((item) => { process(item); });

// T-07 FAIL — one-off test, not the required array structure
it('should do the thing', () => {
    expect(myFunction('input')).toBe('expected');
});

// T-07 PASS
const myFunctionTestCases = [
    { description: 'should do the thing', setup: () => ({ input: 'input', expected: 'expected' }), expectations: (r, e) => expect(r).toBe(e) }
];
myFunctionTestCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
        const { input, expected } = setup();
        expectations(myFunction(input), expected);
    });
});
```

### 7. Open-Ended Review

The checklist above is not exhaustive — it is the set of bugs we already know to look for. After scoring every ID above, do one more pass over the diff **with no checklist in hand** and ask: "would this break, or is this unsafe, in a way none of the above IDs cover?" This is how issues like XSS from a new `[innerHTML]` binding, or a type-guard that's too loose for what it's discriminating, get caught before a human/Copilot review has to find them instead.

- **[OE-01]** Anything else noticed in the diff — a correctness bug, security issue (XSS, injection, unsafe binding), type-safety gap, or risky assumption — that isn't captured by another ID above. **FAIL** with a specific note (file + line + what breaks) for each issue found. **PASS** with note "No additional issues noted" only after actually re-reading the diff with this question in mind — do not default to PASS without doing the pass; a rubber-stamped PASS here defeats the point of the ID.

## Output Format
For EACH checklist item (CQ, F, D, T, PH, LD, OE):

- Mark PASS or FAIL (use **PASS** + `N/A — not in scope` when the rule does not apply — do not drop the ID)  
- If FAIL:
  - Explain clearly  
  - Show **suggested** corrected code in chat or Notes (example only — do not apply it)  

If no issues are found:
- Explicitly confirm that ALL checklist items PASS  
- Also mention which code you reviewed  
