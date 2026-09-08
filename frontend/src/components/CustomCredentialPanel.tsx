/**
 * vQA — CustomCredentialPanel
 * ============================
 * Module: frontend/src/components/CustomCredentialPanel.tsx
 *
 * Pre-flight credential input panel shown inline on RunTestView when the
 * Computer-Use loop requires admin credentials but none are configured.
 * Modelled on GhostCredentialPanel; no network call — credentials are
 * returned to the caller via onSave so RunTestView can update runConfig
 * and auto-retry the run.
 */

import { useState } from "react";

interface CustomCredentialPanelProps {
  /** Called with (email, password) when the user submits. */
  onSave: (email: string, password: string) => void;
  /** Called if the operator dismisses/cancels without saving. */
  onDismiss?: () => void;
}

export default function CustomCredentialPanel({
  onSave,
  onDismiss,
}: CustomCredentialPanelProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) return;
    onSave(email.trim(), password);
  };

  return (
    <div
      className="persona-credential-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="custom-cred-title"
    >
      {/* Header */}
      <div className="persona-credential-panel__header">
        <span className="persona-credential-panel__icon" aria-hidden="true">🔑</span>
        <h3
          id="custom-cred-title"
          className="persona-credential-panel__title"
        >
          Custom Credentials Required
        </h3>
        {onDismiss && (
          <button
            type="button"
            className="persona-credential-panel__close"
            aria-label="Dismiss custom credential panel"
            onClick={onDismiss}
          >
            ×
          </button>
        )}
      </div>

      {/* Context */}
      <p className="persona-credential-panel__description">
        This test run requires admin credentials. Enter an email and password to
        continue — credentials are used once and never stored on disk.
      </p>

      {/* Credential form */}
      <form
        className="persona-credential-panel__form"
        onSubmit={handleSubmit}
        noValidate
        aria-label="Custom Admin Credentials"
      >
        <div className="persona-credential-panel__field">
          <label
            htmlFor="custom-cred-email"
            className="persona-credential-panel__label"
          >
            Email
          </label>
          <input
            id="custom-cred-email"
            type="email"
            className="persona-credential-panel__input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@vpromedia.com"
            autoComplete="username"
            required
          />
        </div>

        <div className="persona-credential-panel__field">
          <label
            htmlFor="custom-cred-password"
            className="persona-credential-panel__label"
          >
            Password
          </label>
          <input
            id="custom-cred-password"
            type="password"
            className="persona-credential-panel__input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="current-password"
            required
          />
        </div>

        <div className="persona-credential-panel__actions">
          <button
            id="custom-cred-submit"
            type="submit"
            className="persona-credential-panel__submit"
            disabled={!email.trim() || !password.trim()}
          >
            Save Credentials &amp; Start
          </button>
        </div>
      </form>

      {/* Security note */}
      <p className="persona-credential-panel__security-note">
        🔒 Credentials are used once for this run and never stored on disk.
      </p>
    </div>
  );
}
