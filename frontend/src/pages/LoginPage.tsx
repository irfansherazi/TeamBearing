import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

/**
 * Email/password login for vReview.
 *
 * @returns The login screen
 */
export const LoginPage = () => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { login, isLoading, error, clearError } = useAuth();
  const navigate = useNavigate();

  /**
   * Submit credentials and route to MFA or home.
   *
   * @param event - Form submit event
   * @returns void
   */
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    login(email, password)
      .then((response) => {
        if (response.mfaRequired) {
          navigate("/mfa", { replace: true });
          return;
        }
        navigate("/", { replace: true });
      })
      .catch(() => undefined);
  };

  return (
    <div className="auth-screen">
      <div className="app-card auth-card">
        <div className="app-card-intro">
          <p className="auth-brand">vReview</p>
          <h1 className="app-page-title">Sign in</h1>
          <p className="app-card-subtitle">Use your vCreative account to open AI Review.</p>
        </div>
        <form onSubmit={handleSubmit} className="app-form">
          <div className="form-group">
            <label htmlFor="login-email">Email</label>
            <input
              id="login-email"
              type="email"
              className="form-input"
              placeholder="Enter your email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                clearError();
              }}
              required
              autoComplete="username"
            />
          </div>
          <div className="form-group">
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              className="form-input"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                clearError();
              }}
              required
              autoComplete="current-password"
            />
          </div>
          {error ? (
            <p className="ai-review-error" id="login-error">
              {error}
            </p>
          ) : null}
          <button
            id="login-submit"
            type="submit"
            className="btn-primary"
            disabled={isLoading}
          >
            {isLoading ? "Logging in..." : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
};
