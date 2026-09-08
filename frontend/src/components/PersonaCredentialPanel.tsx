/**
 * vQA — PersonaCredentialPanel
 * ==============================
 * Module: frontend/src/components/PersonaCredentialPanel.tsx
 *
 * HITL credential input panel shown when persona_switch_node encounters an
 * unknown persona during mid-test execution and broadcasts
 * HITL_PERSONA_CREDENTIALS_REQUIRED via WebSocket.
 *
 * Operator flow:
 *   1. Agent hits a PERSONA_SWITCH step with an unrecognised persona
 *   2. Backend broadcasts HITL_PERSONA_CREDENTIALS_REQUIRED WS message
 *   3. This panel appears with the persona name and email/password fields
 *   4. Operator fills in credentials and clicks Submit
 *   5. Panel POSTs to /runs/{run_id}/persona-credentials
 *   6. Backend unblocks persona_switch_node, switch executes, run continues
 *
 * Security:
 *   - Password field uses type="password" (never shown as plaintext)
 *   - Credentials are only sent once to the backend over HTTPS
 *   - Backend stores them ephemerally and never writes to disk
 *
 * TASK-063 Phase 4 — HITL Integration
 */

import { useState } from "react";
import type { WSPersonaCredentialsMessage, PersonaCredentialsRequest } from "../types";
import { API_BASE_URL } from "../types";

interface PersonaCredentialPanelProps {
  /** The HITL_PERSONA_CREDENTIALS_REQUIRED WebSocket message */
  message: WSPersonaCredentialsMessage;
  /** Callback fired after credentials are successfully submitted */
  onSubmitted?: () => void;
  /** Callback fired if the operator dismisses/cancels */
  onDismiss?: () => void;
}

export default function PersonaCredentialPanel({
  message,
  onSubmitted,
  onDismiss,
}: PersonaCredentialPanelProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) {
      setError("Email and password are required.");
      return;
    }

    setSubmitting(true);
    setError("");

    const payload: PersonaCredentialsRequest = {
      persona_name: message.persona_name,
      email: email.trim(),
      password: password,
    };

    try {
      const resp = await fetch(
        `${API_BASE_URL}/runs/${message.run_id}/persona-credentials`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );

      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }

      setSubmitted(true);
      onSubmitted?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to submit credentials: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div
        className="persona-credential-panel persona-credential-panel--submitted"
        role="status"
        aria-live="polite"
      >
        <div className="persona-credential-panel__icon" aria-hidden="true">✅</div>
        <p className="persona-credential-panel__success">
          Credentials submitted. The agent is logging in as{" "}
          <strong>{message.persona_name}</strong>…
        </p>
      </div>
    );
  }

  return (
    <div
      className="persona-credential-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="persona-cred-title"
    >
      {/* Header */}
      <div className="persona-credential-panel__header">
        <span className="persona-credential-panel__icon" aria-hidden="true">🔑</span>
        <h3
          id="persona-cred-title"
          className="persona-credential-panel__title"
        >
          Persona Login Required
        </h3>
        {onDismiss && (
          <button
            type="button"
            className="persona-credential-panel__close"
            aria-label="Dismiss persona credential panel"
            onClick={onDismiss}
          >
            ×
          </button>
        )}
      </div>

      {/* Context */}
      <p className="persona-credential-panel__description">
        {message.message ||
          `The agent needs to switch to "${message.persona_name}" but this persona is not in the role registry. Please provide login credentials to continue.`}
      </p>

      <p className="persona-credential-panel__persona-badge">
        <strong>Persona:</strong> {message.persona_name}
      </p>

      {/* Credential form */}
      <form
        className="persona-credential-panel__form"
        onSubmit={handleSubmit}
        noValidate
        aria-label={`Credentials for persona: ${message.persona_name}`}
      >
        <div className="persona-credential-panel__field">
          <label
            htmlFor="persona-cred-email"
            className="persona-credential-panel__label"
          >
            Email
          </label>
          <input
            id="persona-cred-email"
            type="email"
            className="persona-credential-panel__input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@vcreative.net"
            autoComplete="username"
            disabled={submitting}
            required
          />
        </div>

        <div className="persona-credential-panel__field">
          <label
            htmlFor="persona-cred-password"
            className="persona-credential-panel__label"
          >
            Password
          </label>
          <input
            id="persona-cred-password"
            type="password"
            className="persona-credential-panel__input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="current-password"
            disabled={submitting}
            required
          />
        </div>

        {error && (
          <p
            className="persona-credential-panel__error"
            role="alert"
            aria-live="assertive"
          >
            {error}
          </p>
        )}

        <div className="persona-credential-panel__actions">
          <button
            id="persona-cred-submit"
            type="submit"
            className="persona-credential-panel__submit"
            disabled={submitting || !email.trim() || !password.trim()}
          >
            {submitting ? "Submitting…" : "Submit Credentials"}
          </button>
        </div>
      </form>

      {/* Security note */}
      <p className="persona-credential-panel__security-note">
        🔒 Credentials are used once for login and never stored to disk.
      </p>
    </div>
  );
}
