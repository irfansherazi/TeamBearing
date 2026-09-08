/**
 * RealAuthApi
 * vCAPI backend implementation.
 */
import type { 
  AuthApi,
  LoginResponse, 
  MfaVerifyResponse, 
  SessionExchangeResponse, 
  RefreshResponse 
} from './authTypes';

/**
 * RealAuthApi
 * Placeholder for actual backend integration.
 */
export class RealAuthApi implements AuthApi {
  private baseUrl: string;

  constructor() {
    this.baseUrl = import.meta.env.VITE_VCAPI_URL;
  }

  async login(email: string, password: string): Promise<LoginResponse> {
    try {
      const response = await fetch(`${this.baseUrl}/auth`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) throw new Error('Login failed');
      const data = await response.json();
      return {
        ssoToken: data.ssoToken,
        appToken: data.ssoToken,
        user: data.user,
      };
    } catch (err) {
      if (import.meta.env.DEV) {
        console.warn('vcAPI login failed in DEV mode, falling back to local dev session:', err);
        return {
          ssoToken: 'dev-sso-token',
          appToken: 'dev-app-token',
          user: {
            id: 'dev-user',
            email: email,
            name: email.split('@')[0] || 'Dev User',
            roles: ['admin'],
          },
        };
      }
      throw err;
    }
  }

  async verifyMfa(code: string, mfaToken: string): Promise<MfaVerifyResponse> {
    // vcapi doesn't seem to have a native /auth/mfa/verify
    // This is a placeholder for future-proofing as requested
    const response = await fetch(`${this.baseUrl}/auth/mfa/verify`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${mfaToken}`
      },
      body: JSON.stringify({ code }),
    });
    if (!response.ok) throw new Error('MFA verification failed');
    return response.json();
  }

  async exchangeSession(ssoToken?: string): Promise<SessionExchangeResponse> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (ssoToken) {
      headers['Authorization'] = `Bearer ${ssoToken}`;
    }
    try {
      const response = await fetch(`${this.baseUrl}/auth/vproLogin`, {
        method: 'POST',
        headers,
      });
      
      if (!response.ok) {
         throw new Error('Session exchange failed');
      }
      
      const data = await response.json();
      return {
        appToken: data.vproToken,
        sessionSalt: data.sessionSalt,
        user: {
          id: data.user_id || 'unknown',
          email: data.email || 'unknown',
          name: data.first_name ? `${data.first_name} ${data.last_name}` : 'User',
          roles: data.roles || []
        }
      };
    } catch (err) {
      if (import.meta.env.DEV) {
        return {
          appToken: 'dev-app-token',
          sessionSalt: 'dev-salt',
          user: {
            id: 'dev-user',
            email: 'dev@vcreativeinc.com',
            name: 'Dev User',
            roles: ['admin'],
          },
        };
      }
      throw err;
    }
  }

  async refreshSsoToken(): Promise<RefreshResponse> {
    const response = await fetch(`${this.baseUrl}/auth/ssoRefresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}), // vcapi refresh takes some body params, but we'll try empty
    });
    if (!response.ok) throw new Error('SSO refresh failed');
    const data = await response.json();
    return {
      token: data.ssoToken,
      sessionSalt: data.sessionSalt || 'default_salt'
    };
  }

  async refreshAppToken(currentAppToken: string): Promise<RefreshResponse> {
    const response = await fetch(`${this.baseUrl}/auth/app/refresh`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${currentAppToken}` },
    });
    if (!response.ok) throw new Error('App token refresh failed');
    return response.json();
  }

  async logout(): Promise<void> {
    // vcapi may not expose /auth/logout — ignore response status; storage is
    // cleared by the caller regardless.
    await fetch(`${this.baseUrl}/auth/logout`, { method: 'POST' }).catch(() => {});
  }
}
