/**
 * AuthService
 * Orchestrates authentication flows.
 */
import type { AuthApi } from './authTypes';
import { RealAuthApi } from './realAuthApi';
import { authStorage } from './authStorage';

class AuthService {
  private api: AuthApi;

  constructor() {
    this.api = new RealAuthApi();
  }

  async login(email: string, password: string) {
    const response = await this.api.login(email, password);
    if (response.appToken) {
      authStorage.setAppToken(response.appToken);
    }
    if (response.ssoToken) {
      authStorage.setSsoToken(response.ssoToken);
    }
    return response;
  }

  async verifyMfa(code: string, mfaToken: string) {
    const response = await this.api.verifyMfa(code, mfaToken);
    authStorage.setAppToken(response.appToken);
    authStorage.setSsoToken(response.ssoToken);
    return response;
  }

  async exchangeSession() {
    const ssoToken = authStorage.getSsoToken() || authStorage.getAppToken();
    const response = await this.api.exchangeSession(ssoToken || undefined);
    authStorage.setAppToken(response.appToken);
    return response;
  }

  async refreshSso() {
    const response = await this.api.refreshSsoToken();
    authStorage.setSsoToken(response.token);
    return response;
  }

  async refreshApp() {
    // /auth/app/refresh doesn't exist on vcapi; re-exchange via vproLogin
    return this.exchangeSession();
  }

  async logout() {
    try {
      await this.api.logout();
    } finally {
      authStorage.clearAll();
    }
  }
}

export const authService = new AuthService();
