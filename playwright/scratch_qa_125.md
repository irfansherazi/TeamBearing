# Scratch Document: QA-125 - New User Experience

## JIRA Card Information
- **Key**: QA-125
- **Summary**: New User Experience - (1 Vote)
- **Description**: New User Experience

## Feasibility Analysis
- **Captcha**: **High Feasibility**. The site uses a Google reCAPTCHA v2 test key (`6Lf30gcTAAAAAMJ7Pthe6JF5tb92UcUreIklyIN-`). It can be automated with Playwright without a challenge-puzzle being triggered.
- **Signup Flow**: **High Feasibility**. The form fields are standard and easily targetable via locators found in `UserSignup.html`.
- **End-to-End Workflow**: **Moderate Dependency**. The application requires Admin approval before a new user can log in. 
  - *Current Status*: We can automate the *Signup* process now.
  - *Blocker*: To test the *Login* of the new user, we need the Admin approval procedure (locators/workflow for the Admin interface).

## Proposed Playwright SOP for Captcha
1. **Target Iframe**: `page.frameLocator('iframe[title="reCAPTCHA"]')`
2. **Click Anchor**: `.locator('#recaptcha-anchor').click()`
3. **Assert Success**: `.toHaveAttribute('aria-checked', 'true')`

## Information Request for Dev/User
To enable a full end-to-end test (Signup -> Approval -> Login), please provide:
1. **Admin Approval Workflow**: Where does an Admin go to approve pending users? 
2. **Environment Configuration**: Confirmation that the backend is also configured with the reCAPTCHA test secret key (standard for dev/test).
