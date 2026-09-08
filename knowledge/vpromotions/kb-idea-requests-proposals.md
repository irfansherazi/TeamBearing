# vPromotions Help Center — Idea Requests & Proposals
# =============================================
# Source: https://vcreativeinc.com/knowledge/vpromotions#idea-requests-proposals
# Extracted: 2026-07-27
# Product-scoped: only loaded for vpromotions runs.

## WORKFLOW: Submit an Idea Request
KEYWORDS: idea request, +idea button, proposals tab, account executive, required fields
JIRA:
---
WHAT: An Idea Request lets an Account Executive kick off the ideation process for a client when they have partial information but no complete promotion concept yet.
WHO: Account Executives/salespeople; the feature must first be activated by a Firm Admin (Settings > Firm > Firm Options > Enable Proposal Workflow, which adds the +Idea button and Proposals tab).
WHERE: The +Idea button on the Home Calendar; submitted requests appear in the Proposals tab.
HOW:
1. Click the +Idea button.
2. Fill in all information available from the client. Five fields are required: Client, Station(s), Presenting to Client Date, Amount of Buy, and What is Client Providing?
3. Submit — the request appears in the Proposals tab with a separate copy of the request for each selected station.
CONSTRAINTS: All five required fields must be completed. The Proposals tab and +Idea button do not exist until a Firm Admin activates Idea Requests and Proposals.
GOTCHAS: Selecting multiple stations creates a separate copy of the request per station, so station-specific personnel (such as Content Managers) can approve or deny individually — expect multiple rows, not one.
TEST-DATA HINTS: Client name, multiple stations across markets, a Presenting to Client Date in the near future, Amount of Buy value.

## WORKFLOW: Approve or Deny Idea Requests Across Markets
KEYWORDS: approve idea request, approve all requests, deny, multi-market, tasks
JIRA:
---
WHAT: Approvers review station-specific copies of an Idea Request and approve or deny them individually or in bulk, regardless of which market they are in.
WHO: Any approver in the configured approval chain (e.g., Sales Manager, Program Director, Promotions Director) who has access to the stations selected on the request.
WHERE: The Proposals tab, plus a Task generated for each approver in the chain.
HOW:
1. Each person in the Proposal Approval Process receives a Task when the Idea Request reaches them.
2. Click the View Information button on the Task to view the request, then Approve or Deny it.
3. To approve every copy of the request at once, use the Approve All Requests button — this approves all copies for any stations you have access to in vPromotions.
CONSTRAINTS: An approver can only act on stations they have access to in vPromotions; approvers may be located in any market as long as that station access exists.
GOTCHAS: A denied request generates a Task for the submitting salesperson — clicking View Denied lets them edit and resubmit the request or delete it entirely.
TEST-DATA HINTS: An AE in one market (e.g., Greenville) with approvers in others (e.g., Charlotte, Atlanta, Dallas, Baltimore).

## WORKFLOW: Create a Proposal from an Approved Idea Request
KEYWORDS: create proposal, view info, new promotion, existing sponsorship, multi-station proposal
JIRA:
---
WHAT: The final approver converts an approved Idea Request into a client-ready Proposal containing promotion and/or sponsorship elements.
WHO: The final approver in the chain (usually the Promotions Director); the creator may be in any market provided they have access to the selected stations.
WHERE: The task list — a task with "Need to create proposal" in the Explanation column — then the Proposal form.
HOW:
1. On final approval, open the task showing "Need to create proposal" and click the View Info action button.
2. Review the request info and click Create Proposal.
3. On the Proposal form, propose a New Promotion, an Existing Sponsorship opportunity (drawn from Details > Sponsorships in a PRF), or any combination of the two Elements.
4. Specify what the station will provide and what the client will provide in return (e.g., tickets, a cash buy) along with their values.
5. Click Save. For multi-station requests, all approved stations appear on the form and saving creates one proposal covering them all, replacing the separate per-station Idea Requests.
CONSTRAINTS: Removing stations from the initial proposal form creates a proposal only for the stations left in, and leaves the removed stations' Idea Requests outstanding for a separate proposal.
GOTCHAS: For multi-station proposals, specify items per station explicitly (e.g., 30 Liners on WXXX-FM, 30 Liners on WYYY-FM) — otherwise deliverables are ambiguous across stations.
TEST-DATA HINTS: "30 Liners on WXXX-FM, 30 Liners on WYYY-FM" as station-specific proposal elements.

## WORKFLOW: Release a Proposal to Sales and Convert It to a PRF
KEYWORDS: release to sales, print proposal, sold it, create prf, attach files
JIRA:
---
WHAT: Sends a completed Proposal to the requesting salesperson, who sells it and converts it into a PRF.
WHO: The proposal creator releases it; the requesting Account Executive sells and converts it.
WHERE: The Proposals tab, using the action buttons on the saved proposal.
HOW:
1. A saved proposal offers these actions: Edit (change it before release), Print Proposal (view/save/print a client-ready proposal including station and client logos where available), View the original Idea Request, Release to Sales, Delete, and Attach Files (for logos, etc.).
2. Click Release to Sales to send the completed proposal to the requesting salesperson.
3. The AE sees the proposal in their Proposals tab with these actions: Print Proposal, View Proposal, View the original Idea Request, Sold It, Attach Files (e.g., a contract), and optionally View Files.
4. The AE clicks Sold It to mark the proposal sold, attaching the order if needed.
5. After the sale confirmation, the AE returns to the Proposals tab and clicks Create PRF for any New Promotion Elements in the proposal; the resulting PRF then follows the normal approval workflow.
CONSTRAINTS: Proposals remain saved as drafts until Release to Sales is clicked. If enabled in Firm Options, Program Director(s) approve at release; otherwise the proposal goes straight to the AE's Proposals tab with a notification.
GOTCHAS: Only New Promotion elements convert via Create PRF — Existing Sponsorship elements are handled through the sponsorship record itself. (See also the Promotions-Initiated Proposal Workflow block in kb-promotion-request-forms-prfs.md, where Promotions starts the proposal instead of an AE.)
TEST-DATA HINTS: Attach a contract file at the Sold It step.

## WORKFLOW: Track Idea Request Progress and Configure Proposal Notifications
KEYWORDS: proposals tab, email settings, idea request submitted, acknowledge, task list
JIRA:
---
WHAT: Provides visibility into where each Idea Request sits in the approval process and configures the email/task alerts that drive the workflow.
WHO: Managers (Sales Manager, Promotions Director, Program Director, General Manager abilities) and salespeople each have their own notification options.
WHERE: The Proposals tab for status visibility; Settings > User > Email Settings (also referred to as Email Options) for notification configuration.
HOW:
1. Open the Proposals tab to view all Idea Requests and Released Proposals and see where each request stands in the approval process.
2. Managers: in Settings > User > Email Options, enable "Email me when an Idea Request is submitted" (alerts on any new Idea Request in the Proposals tab) and/or "Email me when an Idea Request required my approval" (alerts when one is waiting in your task list).
3. Salespeople: in Settings > User > Email Options, enable notification for when an Idea Request is approved at each step of the approval process, and check "Email me when a Proposal has been created for me" to be emailed when a new proposal is ready.
4. Work the Task queue: approvers get an approval/denial task, the final approver gets a create-proposal task, salespeople get a task when a request is denied (View Denied to edit/resubmit or delete) and when a request becomes an available Proposal (click Acknowledge to jump to the Proposals tab, where the proposal appears with the green Sold It button).
CONSTRAINTS: If the Proposals tab is not visible, the Firm Admin must add Idea Requests and Proposals for the market.
GOTCHAS: Manager and salesperson notification options are separate settings under the same Email Options screen — enabling manager alerts does not notify sellers, and vice versa.
TEST-DATA HINTS: n/a (settings and status-tracking reference).
