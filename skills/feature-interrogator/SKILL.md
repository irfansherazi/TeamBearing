---
name: feature-interrogator
description: Interrogates a feature or task from roadmap.md or a task file. Runs an exhaustive back-and-forth debate between the feature's Author (Senior Engineer) and a Principal Engineer 'griller' to ensure simplicity, rule compliance, and minimal code footprint. Use this when you are asked to review, plan, design, or interrogate a feature, task, or roadmap item.
---

# Feature Interrogator Skill

## Overview

The `feature-interrogator` skill establishes an automated, highly-rigorous design review gate for any planned feature or task in the vQA codebase. It is designed to combat developer overconfidence, prevent over-engineering, enforce strict rule compliance (12-Factor, Observability, Blocking Violations), and keep the overall code footprint minimal.

By simulating or spawning two distinct engineering personas (a **Senior Engineer / Author** who defends and owns the task, and a **Principal Engineer / Griller** who critically deconstructs the design), this skill results in a highly optimized, compliant, and streamlined architectural blueprint before any code is written.

---

## Workflow Decision Tree

When triggered by a feature ID (e.g., `FEAT-020`) or a task file (e.g., `memory-bank/tasks/TASK-100.md`):

```
       [Start Interrogation]
                 │
                 ▼
     [Run extract_feature.py] ──► Extracts target details from roadmap.md or task file
                 │
                 ▼
     [Gather Codebase Context] ──► Read references/rules.md & any mentioned source files
                 │
                 ▼
     [Round 1: Senior Pitch] ──► Drafts initial file edits, line count estimates, test plan
                 │
                 ▼
     [Round 2: Principal Grill] ──► Challenges overconfidence, complexity, rules, duplication
                 │
                 ▼
    [Round 3: Senior Rebuttal] ──► Simplifies design, trims code fat, revises proposal
                 │
                 ▼
    [Round 4: Principal Signoff] ──► Verifies compliance, sets final guardrails
                 │
                 ▼
     [Compile & Save Report] ──► Writes markdown report to .agent-logs/interrogations/
```

---

## Detailed Step-by-Step Guide

### Step 1: Extract and Gather Context
1. Locate the feature or task details by running the extraction script:
   ```bash
   python3 skills/feature-interrogator/scripts/extract_feature.py <FEATURE_ID_OR_FILE>
   ```
2. Parse any file paths, technologies, or modules mentioned in the feature description.
3. Perform a quick, targeted `grep_search` or `glob` search on the codebase to understand the structure of those existing files or modules. This prevents the simulated personas from hallucinating code or inventing patterns that do not exist.
4. Load and review the coding rules in `skills/feature-interrogator/references/rules.md`.

---

### Step 2: Pitch — The Senior Engineer (Author / Defender)
Invoke a subagent (e.g., `generalist` or simulate within a structured chain of thought) playing the role of the **Senior Engineer / Author**.
- **Context Provided**: Feature description, gathered codebase context, `references/rules.md`.
- **Expected Output**: A formal implementation pitch containing:
  1. **Files Affected**: Precise list of files to be created, modified, or deleted.
  2. **Minimal Design Outline**: Key functions, classes, schemas, or hooks to be introduced.
  3. **Complexity & Line Count Estimates**: Estimated lines of code (LoC) for both production code and tests.
  4. **Verification & Test Strategy**: Detailed explanation of which tests (pytest or Vitest) will be added to prove correctness.
  5. **Simplicity Defense**: Why this is the absolute simplest way to solve the problem.

---

### Step 3: Grill — The Principal Engineer (The Griller)
Invoke a subagent playing the role of the **Principal Engineer / Griller**.
- **Context Provided**: Senior Engineer's Pitch, `references/rules.md`.
- **Expected Output**: A ruthless, highly critical review. The griller must actively challenge any sign of overconfidence or over-engineering:
  1. **Fat Trimming**: Can we achieve this exact outcome with 50% less code? Why are so many files being touched?
  2. **Rule Enforcement**: Ensure no 12-Factor or Observability rules are violated, and check for any potential blocking violations (e.g., console logs/standard prints, missing trace propagation, hardcoded constants).
  3. **Anti-Duplication**: Are they re-inventing a helper function or pattern that already exists in `backend/` or `frontend/`?
  4. **Edge-Case Exposure**: Challenge the robustness of their test strategy. What about race conditions, network failures, or null/empty inputs?
  5. **Targeted Questions**: Formulate 3-4 highly pointed, challenging questions that the Senior Engineer must answer.

---

### Step 4: Rebuttal — The Senior Engineer (Simplification)
Invoke the **Senior Engineer** subagent to answer the grill.
- **Context Provided**: Principal Engineer's critique and questions.
- **Expected Output**:
  1. **Answers to Grill**: Directly address each of the 3-4 pointed questions.
  2. **Revised Minimal Design**: Modify the implementation pitch to trim the fat pointed out by the griller. Reduce file touches and line count estimates.
  3. **Refined Test Strategy**: Bulletproof the tests to cover the edge cases raised.

---

### Step 5: Sign-Off — The Principal Engineer (Final Pass)
Invoke the **Principal Engineer** subagent for the final verdict.
- **Context Provided**: Senior Engineer's revised proposal.
- **Expected Output**:
  - A final assessment of the simplified plan.
  - If satisfied, issue a formal **Architectural Sign-Off** along with any strict constraints (e.g., "Max 30 lines added in main.py, absolute enforcement of JSON logger").
  - If still unsatisfied, reject and specify exactly what remaining fat must be trimmed.

---

### Step 6: Synthesis and Reporting
1. Compile the full back-and-forth transcript into an executive Markdown report.
2. Automatically create the directory `.agent-logs/interrogations/` if it does not exist.
3. Save the report to:
   ```
   .agent-logs/interrogations/<TARGET_ID>-interrogation-report.md
   ```
   *(Replacing `<TARGET_ID>` with the feature ID or sanitized task file name).*
4. Output a clean, high-signal summary of the debate, the major design compromises, and the final agreed-upon minimal plan to the user.

---

## Interrogation Report Template

Ensure all reports saved to `.agent-logs/interrogations/` follow this exact structure:

```markdown
# Feature Interrogation Report: [FEATURE_ID / TASK_ID]
- **Target**: [Feature or Task Name]
- **Date**: [Date]
- **Interrogators**:
  - Senior Engineer (Author / Defender)
  - Principal Engineer (The Griller)

---

## 1. Feature / Task Specification
[Extracted details from extract_feature.py]

---

## 2. Round 1: Senior Engineer Pitch
[Initial implementation design, files affected, line counts, testing strategy]

---

## 3. Round 2: Principal Engineer Grill
[Critical feedback, rule checks, edge cases, and 3-4 challenging questions]

---

## 4. Round 3: Senior Engineer Rebuttal & Simplified Plan
[Answers to questions, trimmed design, revised file touches, and enhanced test coverage]

---

## 5. Round 4: Principal Engineer Final Sign-Off
[Final verdict, architectural constraints, and sign-off status]

---

## 6. Final Agreed Implementation Blueprint
- **Files to Modify**:
  - `file1.py`: [Concise description of minimal change]
- **Files to Create**:
  - `test_file1.py`: [Concise description of minimal tests]
- **Total Estimated Line Count (Prod)**: [X] lines
- **Total Estimated Line Count (Test)**: [Y] lines
- **Strict Guardrails**: [List of rules/constraints to follow]
```
