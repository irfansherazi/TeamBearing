/**
 * authStorage
 * Centralizes all token read/write/clear logic.
 */

const APP_TOKEN_KEY = 'vqa_app_token';
const SSO_COOKIE_NAME = import.meta.env.VITE_SSO_COOKIE_NAME;
const COOKIE_DOMAIN = import.meta.env.VITE_COOKIE_DOMAIN;

/**
 * Host-only cookies on localhost — browsers reject Domain=.vcreative.net
 * when the page origin is localhost, so refresh would lose the SSO session.
 */
function isLocalDevHost(): boolean {
  const host = window.location.hostname;
  return host === 'localhost' || host === '127.0.0.1';
}

function ssoCookiePathAndDomain(): string {
  if (isLocalDevHost() || !COOKIE_DOMAIN) {
    return 'path=/';
  }
  return `path=/;domain=${COOKIE_DOMAIN}`;
}

export const authStorage = {
  getAppToken: (): string | null => {
    return localStorage.getItem(APP_TOKEN_KEY);
  },

  setAppToken: (token: string): void => {
    localStorage.setItem(APP_TOKEN_KEY, token);
  },

  clearAppToken: (): void => {
    localStorage.removeItem(APP_TOKEN_KEY);
  },

  getSsoToken: (): string | null => {
    const name = SSO_COOKIE_NAME + "=";
    const decodedCookie = decodeURIComponent(document.cookie);
    const ca = decodedCookie.split(';');
    for (let i = 0; i < ca.length; i++) {
      let c = ca[i];
      while (c.charAt(0) === ' ') {
        c = c.substring(1);
      }
      if (c.indexOf(name) === 0) {
        return c.substring(name.length, c.length);
      }
    }
    return null;
  },

  setSsoToken: (token: string, expiresDays: number = 7): void => {
    const d = new Date();
    d.setTime(d.getTime() + (expiresDays * 24 * 60 * 60 * 1000));
    const expires = "expires=" + d.toUTCString();
    // In production, should be Secure and SameSite=Lax/Strict
    // HttpOnly can only be set by the server
    document.cookie = `${SSO_COOKIE_NAME}=${token};${expires};${ssoCookiePathAndDomain()}`;
  },

  clearSsoToken: (): void => {
    document.cookie = `${SSO_COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; ${ssoCookiePathAndDomain()}`;
  },

  clearAll: (): void => {
    authStorage.clearAppToken();
    authStorage.clearSsoToken();
  }
};
