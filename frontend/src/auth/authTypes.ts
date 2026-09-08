/**
 * Auth Types
 * Centralized interfaces and types.
 */
export interface User {
  id: string;
  email: string;
  name: string;
  roles: string[];
}

export interface AuthState {
  user: User | null;
  appToken: string | null;
  ssoToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  mfaToken: string | null;
  error: string | null;
}

export interface LoginResponse {
  ssoToken?: string;
  appToken?: string;
  sessionSalt?: string;
  user?: User;
  mfaRequired?: boolean;
  mfaToken?: string;
}

export interface MfaVerifyResponse {
  ssoToken: string;
  appToken: string;
  sessionSalt: string;
  user: User;
}

export interface SessionExchangeResponse {
  appToken: string;
  sessionSalt: string;
  user: User;
}

export interface RefreshResponse {
  token: string;
  sessionSalt: string;
}

export interface AuthApi {
  login(email: string, password: string): Promise<LoginResponse>;
  verifyMfa(code: string, mfaToken: string): Promise<MfaVerifyResponse>;
  exchangeSession(ssoToken?: string): Promise<SessionExchangeResponse>;
  refreshSsoToken(): Promise<RefreshResponse>;
  refreshAppToken(currentAppToken: string): Promise<RefreshResponse>;
  logout(): Promise<void>;
}
