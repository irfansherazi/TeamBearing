# Playwright Optimization & Documentation Plan (Q1 2026)

## 1. Executive Summary
This document outlines the optimization strategy for the Playwright test suite, focusing on the "DONE" Q1 2026 items. The review of `QA-298`, `QA-170`, `QA-185`, `QA-254`, and `QA-247` revealed significant opportunities for code reuse, helper consolidation, and documentation hardening. The goal is to transition from "working scripts" to a "maintainable framework".

## 2. Documentation Enhancements (Knowledge Base)
We will update the `knowledge-base/behaviors` files to reflect "ground truth" behaviors discovered during test implementation.

### `folder_logic.md`
- **Add:** "Hidden System Folders": Document that the 'All' folder may be hidden by default for some users and requires enabling via Settings.
- **Add:** "Virtualization": Note that folder lists use virtual scrolling, requiring specific interaction patterns (scroll-fetch loops) for automation.

### `search_filtering.md`
- **Add:** "Filter Retention": Explicitly document that search criteria (Client, Ad Type) persist when refining searches (e.g., switching from 'Search All' to 'Search Current').
- **Add:** "Search Options Dropdown": Document the "Search Current Folder" vs "Search All Folders" split button behavior.

### `archive_logic.md`
- **Add:** "View Disappearance": Clarify that archiving a spot immediately removes it from standard active views (Inbox, etc.), necessitating specific verification strategies (Toast check vs. Row presence).

---

## 3. Helper Refactoring & Consolidation
We will refactor `playwright/utils` to absorb the robust but duplicated logic currently living inside individual test files.

### 3.1 New: `SearchHelper.ts` (Extract from QA-170 & QA-185)
*   **`performSearch(criteria: SearchCriteria)`**: Encapsulate the complex interaction of opening the search panel, handling the "All/Current" dropdown, and filling fields (Client, Ad Type, Status).
*   **`saveSearchAsFolder(folderName: string)`**: standardized logic for saving a search, including the "Show Save Button" toggle.
*   **`verifyRetention(criteria)`**: Logic to assert fields match expected values.

### 3.2 Enhance: `NavHelper.ts` (Absorb from QA-298 & QA-185)
*   **`scrollToFolder(name)`**: Update the existing function with the robust "scroll-fetch-check" loop used in QA-298/185 to handle large, virtualized sidebars.
*   **`ensureSystemFolder(name)`**: New function implementing the QA-298 logic to check if a system folder (like 'All') is visible, and if not, enable it via Settings.

### 3.3 Enhance: `ViewHelper.ts` (Absorb from QA-247 & QA-254)
*   **`changeStatus(row, status)`**: Standardize the PrimeNG 19 "Select Status" dropdown interaction found in QA-254.
*   **`openSettings(menuName)`**: Centralize the logic to open the generic Settings/Filter Options drawer (used in QA-298, QA-185, QA-254).

### 3.4 Enhance: `OrderHelper.ts` (Absorb from QA-247)
*   **`approveSpot(row)`**: Extract the specific approval logic (finding the button, handling force clicks).

---

## 4. Test Remediation Plan
Once helpers are updated, we will refactor the existing tests to use them.

### [REF] QA-298 (Folder Logic)
*   Replace manual "Enable All Folder" logic with `NavHelper.ensureSystemFolder`.
*   Replace manual sidebar scrolling with `NavHelper.scrollToFolder`.
*   Replace manual header count extraction with `NavHelper.getHeaderCount`.

### [REF] QA-170 (Search)
*   Replace valid Search execution blocks with `SearchHelper.performSearch`.
*   Replace retention checks with `SearchHelper.verifyRetention`.
*   Outcome: Reduce file size by ~40%.

### [REF] QA-185 (Saved Search Sharing)
*   Replace Search & Save logic with `SearchHelper`.
*   Replace "Open Settings" logic with `ViewHelper.openSettings`.
*   Replace Scroll logic with `NavHelper.scrollToFolder`.

### [REF] QA-247 (Dubbed Checkbox)
*   Replace manual "Select Status" interaction with `ViewHelper.changeStatus`.
*   Replace "Approve" button logic with `OrderHelper.approveSpot`.

### [REF] QA-254 (Manual Archive)
*   Replace `ensureListView` manual block with `ViewHelper.ensureListView` (already imported but not fully used).
*   Replace manual status change with `ViewHelper.changeStatus`.

## 5. Execution Order
1.  **Docs**: Update Knowledge Base files (Safe, no code impact).
2.  **Helpers**: Create `SearchHelper` and update `Nav`, `View`, `Order` helpers.
3.  **Verify**: Run existing tests *before* modifying them to ensure baseline green.
4.  **Refactor**: Update tests one by one, verifying pass status after each refactor.
