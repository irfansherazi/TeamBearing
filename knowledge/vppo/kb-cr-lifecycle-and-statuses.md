# vPPO Help Center — Creative Request (CR) Status Lifecycle & Rules
# ==================================================================
# Source: legacy-ppo RAG Knowledge Base

## WORKFLOW: Understand Creative Request (CR) Statuses
KEYWORDS: CR status, status code, crstatus, lifecycle, approval gates, spot status, status transition
JIRA:
---
WHAT: Understand the status lifecycle and transitions for Creative Requests (CRs) in vPPO.
WHO: All vPPO roles.
WHERE: vPPO Main Dashboard, Spot Details View, Status Change Modals.
HOW:
1. Each Creative Request has a single-character `crstatus` code in the `creativerequest` database table.
2. Happy Path Transitions:
   - `A` (Submitted/Approved) → `B` (Needs Production) when script is approved.
   - `B` (Needs Production) → `P` (Script Review) if script approval gate is pending.
   - `B` (Needs Production) → `M` (Completed) when producer finishes production.
   - `M` (Completed) → `Q` (Spot Review) if spot approval gate is active (`approvespotflag=1`).
   - `M` (Completed) → `U` (Needs Dubbed) when spot is approved or no approval is required.
   - `U` (Needs Dubbed) → `Z` (Needs Scheduled) or `V` (Archived) when dubbed and scheduled.

STATUS CODES:
- `A` (Submitted): New CR created and submitted, awaiting assignment.
- `B` (Needs Production): Script approved, ready for production work.
- `C` (Canceled): Soft-cancelled request.
- `D` (Deleted): Soft-deleted request.
- `H` (On Hold): Spot placed on hold.
- `I` (In Progress): Actively being worked on by producer/writer.
- `J` (Rejected): Spot or script rejected by AE/Client.
- `M` (Completed): Production done, ready for review or dubbing.
- `N` (Needs Writing): New CR requiring script/copywriting.
- `P` (Script Review): Script pending review gate.
- `Q` (Spot Review): Final audio/visual spot pending review gate.
- `U` (Needs Dubbed): Production complete, ready for Traffic Manager dubbing.
- `V` (Archived): Final archived state (fully dubbed and scheduled).
- `Z` (Needs Scheduled): Dubbed but awaiting traffic system scheduling.

CONSTRAINTS:
- Inactive statuses (`C`, `D`, `S`, `V`) clear new item flags (`crflag`).
- Changing status to `I` (In Progress) automatically assigns producer/writer POC.
