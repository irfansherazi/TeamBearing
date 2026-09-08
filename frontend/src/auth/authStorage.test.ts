import { afterEach, describe, expect, it } from 'vitest';
import { authStorage } from './authStorage';

const SSO_COOKIE_NAME = import.meta.env.VITE_SSO_COOKIE_NAME || 'ssojwt_dev';

function clearDocumentCookies(): void {
  document.cookie.split(';').forEach((part) => {
    const name = part.split('=')[0]?.trim();
    if (name) {
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/`;
    }
  });
}

describe('authStorage SSO cookies on localhost', () => {
  afterEach(() => {
    authStorage.clearAll();
    clearDocumentCookies();
    localStorage.clear();
  });

  it('stores and reads the SSO cookie without a parent-domain attribute', () => {
    expect(window.location.hostname).toBe('localhost');

    authStorage.setSsoToken('localhost-sso-token');

    expect(authStorage.getSsoToken()).toBe('localhost-sso-token');
  });

  it('restores the app token from localStorage after a reload-style read', () => {
    authStorage.setAppToken('stored-app-token');
    expect(authStorage.getAppToken()).toBe('stored-app-token');
  });

  it('clears the host-only SSO cookie', () => {
    authStorage.setSsoToken('to-clear');
    authStorage.clearSsoToken();
    expect(authStorage.getSsoToken()).not.toBe('to-clear');
    expect(document.cookie.includes(`${SSO_COOKIE_NAME}=to-clear`)).toBe(false);
  });
});
