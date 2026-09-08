---
legacy_id: human-readable-playwright-library-card-headers
---
# human-readable-playwright-library-card-headers: Human-Readable Playwright Library Card Headers

**Status**: COMPLETE
**Complexity**: Level 2
**Roadmap Link**: N/A
**Branch**: feature/FEAT-109-human-readable-playwright-names
**Created**: 2026-06-08

---

## Description

The Playwright Library page currently shows raw filenames as card headers (e.g., `qa-172-sales.test`, `qa-175-lockout.test`, `qa-185-saved-searches-sharing.test`). Product team members don't understand these. This task replaces them with human-readable labels like "QA-172 Sales Test", "QA-175 Lockout Test", and "QA-185 Saved Searches Sharing Test" across both the `PlaywrightPage` and `PlaywrightLibrary` components, and adds targeted unit testing to verify the formatting utility.

---

## Specification

### User Story
**As a** Product Team Member / Business Operator,
**I want** to see human-readable titles for the tests in the Playwright Library,
**So that** I can easily understand what each test card represents without decoding technical filenames.

### Acceptance Criteria

#### Happy Path
- **AC-1**: Test IDs are converted to human-readable names on the Playwright library page:
  - `qa-172-sales.test` -> `QA-172 Sales Test`
  - `qa-175-lockout.test` -> `QA-175 Lockout Test`
  - `qa-185-saved-searches-sharing.test` -> `QA-185 Saved Searches Sharing Test`
- **AC-2**: General formatting rules for filenames:
  - Remove suffixes like `.test`, `.spec`, `.ts`, `.js`.
  - Format ticket prefixes like `qa-172` or `qa_172` to uppercase `QA-172` with a hyphen.
  - Replace other hyphens/underscores with space.
  - Split camelCase words (e.g. `filePreWashUtility` -> `File Pre Wash Utility Test`).
  - Capitalize all words.
  - Append the word `Test` at the end if it does not already end with `Test` (case-insensitive).
- **AC-3**: `PlaywrightLibrary.tsx` maps the response data from the backend to ensure `test.name` is correctly populated with the human-readable display name, preserving backward compatibility.
- **AC-4**: `PlaywrightPage.tsx` displays the human-readable title as the main card header and the raw ID as a smaller meta sub-element.

#### Quality & Testing
- **AC-5**: Add dedicated frontend unit tests to verify the formatting utility behaves correctly with all expected input formats (Jira keys, camelCase, plain filenames, custom suffixes).

---

## Implementation Roadmap

### Phase 1: Planning & Design (Done)
- Identified relevant files: `frontend/src/pages/PlaywrightPage.tsx`, `frontend/src/components/PlaywrightLibrary.tsx`, `frontend/src/index.css`.
- Designed robust formatting helper.

### Phase 2: Implementation
- [x] **2.1** Define shared or localized helper function `getTestDisplayName` implementing formatting rules.
- [x] **2.2** Refactor `PlaywrightLibrary.tsx` to map incoming backend data and format `test.name` with the display name helper.
- [x] **2.3** Refactor `PlaywrightPage.tsx` to use the display name helper as the primary header (with a new `.pw-card-title` class) and show the raw ID as a smaller, styled subtitle.
- [x] **2.4** Add CSS style for `.pw-card-title` in `frontend/src/index.css`.

### Phase 3: Testing & Verification
- [x] **3.1** Add unit tests in `PlaywrightPage.test.tsx` or a new test file to verify formatting.
- [x] **3.2** Run all frontend tests via `vitest` to ensure no regressions.

---

## Test Strategy

### Unit Tests
- Create dedicated unit tests in `frontend/src/pages/__tests__/PlaywrightPage.test.tsx` (or a dedicated helper test file) asserting:
  - `qa-172-sales.test` formats to `QA-172 Sales Test`
  - `qa-185-saved-searches-sharing.test` formats to `QA-185 Saved Searches Sharing Test`
  - `email_check_validation.test` formats to `Email Check Validation Test`
  - `filePreWashUtility` formats to `File Pre Wash Utility Test`
