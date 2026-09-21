import { useState, type FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

/**
 * MFA code entry after password login.
 *
 * @returns The verification screen
 */
export const MfaPage = () => {
  const [code, setCode] = useState("");
  const { verifyMfa, isLoading, error, clearError, mfaToken } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const fromState = location.state as { from?: { pathname?: string } } | null;
  const from = fromState?.from?.pathname || "/";

  if (!mfaToken && !isLoading) {
    return (
      <div className="auth-screen">
        <div className="app-card auth-card">
          <p>Invalid session. Please login again.</p>
        </div>
      </div>
    );
  }

  /**
   * Submit the 6-digit code and continue to the original page.
   *
   * @param event - Form submit event
   * @returns void
   */
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    verifyMfa(code)
      .then(() => {
        navigate(from, { replace: true });
      })
      .catch(() => undefined);
  };

  return (
    <div className="auth-screen">
      <div className="app-card auth-card">
        <div className="app-card-intro">
          <h1 className="app-page-title">Verification code</h1>
          <p className="app-card-subtitle">
            Enter the 6-digit code sent to your device.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="app-form">
          <div className="form-group">
            <label htmlFor="mfa-code">Code</label>
            <input
              id="mfa-code"
              type="text"
              className="form-input"
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
                clearError();
              }}
              required
              placeholder="123456"
              maxLength={6}
              autoComplete="one-time-code"
            />
          </div>
          {error ? (
            <p className="ai-review-error" id="mfa-error">
              {error}
            </p>
          ) : null}
          <button
            id="mfa-submit"
            type="submit"
            className="btn-primary"
            disabled={isLoading}
          >
            {isLoading ? "Verifying..." : "Verify"}
          </button>
        </form>
      </div>
    </div>
  );
};
