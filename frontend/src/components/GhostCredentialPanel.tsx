/**
 * vQA — GhostCredentialPanel
 * ==============================
 * Module: frontend/src/components/GhostCredentialPanel.tsx
 *
 * HITL credential input panel shown when a GHOST_LOGIN step is reached
 * and Admin credentials must be supplied.
 */

import { useState } from "react";
import type { WSGhostCredentialsMessage, GhostCredentialsRequest } from "../types";
import { API_BASE_URL } from "../types";

interface GhostCredentialPanelProps {
  /** The GHOST_CREDENTIALS_REQUIRED WebSocket message */
  message: WSGhostCredentialsMessage;
  /** Callback fired after credentials are successfully submitted */
  onSubmitted?: () => void;
  /** Callback fired if the operator dismisses/cancels */
  onDismiss?: () => void;
}

async function postGhostCredentials(
  runId: string,
  payload: GhostCredentialsRequest
): Promise<void> {
  const resp = await fetch(`${API_BASE_URL}/runs/${runId}/ghost-credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${resp.status}`);
  }
}

export default function GhostCredentialPanel({
  message,
  onSubmitted,
  onDismiss,
}: GhostCredentialPanelProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) {
      setError("Admin email and password are required.");
      return;
    }

    setSubmitting(true);
    setError("");

    try {
      await postGhostCredentials(message.run_id, {
        email: email.trim(),
        password,
      });
      setSubmitted(true);
      onSubmitted?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to submit Admin credentials: ${msg}`);
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
          Admin credentials submitted. The agent is logging in as Admin…
        </p>
      </div>
    );
  }

  return (
    <div
      className="persona-credential-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="ghost-cred-title"
    >
      {/* Header */}
      <div className="persona-credential-panel__header">
        <span className="persona-credential-panel__icon" aria-hidden="true">👤</span>
        <h3
          id="ghost-cred-title"
          className="persona-credential-panel__title"
        >
          Admin Login Required (Ghost Login)
        </h3>
        {onDismiss && (
          <button
            type="button"
            className="persona-credential-panel__close"
            aria-label="Dismiss admin credential panel"
            onClick={onDismiss}
          >
            ×
          </button>
        )}
      </div>

      {/* Context */}
      <p className="persona-credential-panel__description">
        {message.message ||
          "The test plan contains a Ghost Login step which requires Admin credentials to proceed with impersonation."}
      </p>

      {/* Credential form */}
      <form
        className="persona-credential-panel__form"
        onSubmit={handleSubmit}
        noValidate
        aria-label="Admin Credentials for Ghost Login"
      >
        <div className="persona-credential-panel__field">
          <label
            htmlFor="ghost-cred-email"
            className="persona-credential-panel__label"
          >
            Admin Email
          </label>
          <input
            id="ghost-cred-email"
            type="email"
            className="persona-credential-panel__input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@vpromedia.com"
            autoComplete="username"
            disabled={submitting}
            required
          />
        </div>

        <div className="persona-credential-panel__field">
          <label
            htmlFor="ghost-cred-password"
            className="persona-credential-panel__label"
          >
            Password
          </label>
          <input
            id="ghost-cred-password"
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
            id="ghost-cred-submit"
            type="submit"
            className="persona-credential-panel__submit"
            disabled={submitting || !email.trim() || !password.trim()}
          >
            {submitting ? "Submitting…" : "Submit Admin Credentials"}
          </button>
        </div>
      </form>

      {/* Security note */}
      <p className="persona-credential-panel__security-note">
        🔒 Admin credentials are used once for login and never stored on disk.
      </p>
    </div>
  );
}
