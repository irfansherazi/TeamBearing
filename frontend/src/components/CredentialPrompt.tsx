/**
 * vQA — Credential Prompt Component
 * =====================================
 * Module: frontend/src/components/CredentialPrompt.tsx
 *
 * Inline prompt shown inside ExecutionPanel when the Jira ticket has
 * partial credentials (only email OR only password found).
 *
 * The user fills in the missing field; the value is passed back to
 * ExecutionPanel and included in the execute request as override fields.
 */

interface CredentialPromptProps {
  /** Which field is missing */
  missingField: "email" | "password";
  /** The email found in the ticket (pre-filled if email is NOT missing) */
  foundEmail: string;
  /** Called when the user fills in the missing value */
  onChange: (value: string) => void;
  /** Current value of the missing field input */
  value: string;
}

/**
 * Inline credential prompt — fills in the one missing field.
 */
export function CredentialPrompt({ missingField, foundEmail, onChange, value }: CredentialPromptProps) {
  return (
    <div className="credential-prompt">
      <div className="credential-prompt-header">
        <span className="credential-prompt-icon">⚠️</span>
        <span className="credential-prompt-title">Credential Required</span>
      </div>

      <p className="credential-prompt-desc">
        The ticket specifies{" "}
        {missingField === "password" ? (
          <>email <strong>{foundEmail}</strong> but no password.</>
        ) : (
          <>a password but no email address.</>
        )}
        {" "}Please provide the missing field to continue.
      </p>

      <div className="form-group">
        <label htmlFor="cred-prompt-input">
          {missingField === "password" ? "Password for this test" : "Email for this test"}
        </label>
        <input
          id="cred-prompt-input"
          type={missingField === "password" ? "password" : "email"}
          placeholder={missingField === "password" ? "Enter password..." : "Enter email..."}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="form-input credential-input"
          autoFocus
        />
        <span className="form-hint">
          This credential is only used for this test run and is not stored.
        </span>
      </div>
    </div>
  );
}
