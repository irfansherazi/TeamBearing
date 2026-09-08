# vPPO — Authentication and SSO Workflow
# ============================================
# Source: vPPO Auth & Shared vCreative SSO Architecture

## WORKFLOW: Log into vPPO via Shared SSO
KEYWORDS: login, authentication, SSO, credentials, sign in, vppo login
JIRA:
---
WHAT: Log in to the vPPO application as a specified role.
WHO: All vPPO user roles (Account Executive, Traffic Manager, Producer, Production Manager, etc.).
WHERE: Shared SSO login page at https://qa.vcreative.net (or https://vppo-qa.vcreative.net).
HOW:
1. Navigate to the login page (`https://vppo-qa.vcreative.net`).
2. If redirected to shared SSO (`https://qa.vcreative.net`), enter the role login email in the Email field.
3. Enter the password in the Password field.
4. Click the "Login" or "Sign In" button.
5. Verify JWT session token (`vc2JWT`) or session cookie is established in localStorage.
6. Verify redirect back to the vPPO dashboard.

CONSTRAINTS:
- Role credentials map to designated persona email accounts (e.g. `imail-test+SalesExec@vcreativeinc.com`, `imail-test+TrafficDir@vcreativeinc.com`).
- Ghost login requires authenticating at shared SSO before navigating to vPPO product URL.

GOTCHAS:
- If session expires, user is redirected back to the login page.
- Role permissions dictate visible navigation links and action buttons on the home dashboard.
