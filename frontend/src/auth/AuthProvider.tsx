import React, { createContext, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import type { AuthState, LoginResponse } from './authTypes';
import { authService } from './authService';
import { authStorage } from './authStorage';
import { createSsoKeepalive } from './ssoKeepalive';
import type { SsoKeepalive } from './ssoKeepalive';

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<LoginResponse>;
  verifyMfa: (code: string) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<AuthState>({
    user: null,
    appToken: authStorage.getAppToken(),
    ssoToken: authStorage.getSsoToken(),
    isAuthenticated: false,
    isLoading: true,
    mfaToken: null,
    error: null,
  });

  const logout = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true }));
    try {
      await authService.logout();
    } finally {
      setState({
        user: null,
        appToken: null,
        ssoToken: null,
        isAuthenticated: false,
        isLoading: false,
        mfaToken: null,
        error: null,
      });
    }
  }, []);

  const hydrate = useCallback(async () => {
    const appToken = authStorage.getAppToken();
    const ssoToken = authStorage.getSsoToken();

    if (appToken) {
      try {
        const response = await authService.exchangeSession();
        setState(prev => ({
          ...prev,
          user: response.user,
          appToken: response.appToken,
          isAuthenticated: true,
          isLoading: false,
        }));
        return;
      } catch (e) {
        console.error('App token validation failed', e);
        authStorage.clearAppToken();
      }
    }

    if (ssoToken) {
      try {
        const response = await authService.exchangeSession();
        setState(prev => ({
          ...prev,
          user: response.user,
          appToken: response.appToken,
          ssoToken: ssoToken,
          isAuthenticated: true,
          isLoading: false,
        }));
        return;
      } catch (e) {
        console.error('SSO silent restore failed', e);
        authStorage.clearSsoToken();
      }
    }

    setState(prev => ({ ...prev, isLoading: false }));
  }, []);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // SSO keepalive — refreshes every 15s to prevent session expiry
  const keepaliveRef = useRef<SsoKeepalive | null>(null);

  useEffect(() => {
    if (!state.isAuthenticated) return;

    // App token refresh (every 15 min) — separate concern
    const appRefreshInterval = setInterval(async () => {
      try {
        await authService.refreshApp();
      } catch (e) {
        // Log but don't force logout — the SSO keepalive is the authoritative
        // session validator and will call onSessionInvalid if the session expires.
        console.warn('Background app token refresh failed, will retry next interval', e);
      }
    }, 15 * 60 * 1000);

    // SSO keepalive (every 15s)
    const keepalive = createSsoKeepalive({
      getToken: () => authStorage.getSsoToken(),
      setToken: (token: string) => {
        authStorage.setSsoToken(token);
        setState(prev => ({ ...prev, ssoToken: token }));
      },
      onSessionInvalid: () => logout(),
    });
    keepaliveRef.current = keepalive;
    keepalive.start();

    return () => {
      clearInterval(appRefreshInterval);
      keepalive.stop();
      keepaliveRef.current = null;
    };
  }, [state.isAuthenticated, logout]);

  const login = async (email: string, password: string) => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    try {
      const response = await authService.login(email, password);
      if (response.mfaRequired) {
        setState(prev => ({
          ...prev,
          isLoading: false,
          mfaToken: response.mfaToken || null,
        }));
      } else {
        setState(prev => ({
          ...prev,
          user: response.user || null,
          appToken: response.appToken || null,
          ssoToken: response.ssoToken || null,
          isAuthenticated: true,
          isLoading: false,
        }));
      }
      return response;
    } catch (e: any) {
      setState(prev => ({ ...prev, isLoading: false, error: e.message }));
      throw e;
    }
  };

  const verifyMfa = async (code: string) => {
    if (!state.mfaToken) throw new Error('No MFA token available');
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    try {
      const response = await authService.verifyMfa(code, state.mfaToken);
      setState(prev => ({
        ...prev,
        user: response.user,
        appToken: response.appToken,
        ssoToken: response.ssoToken,
        isAuthenticated: true,
        isLoading: false,
        mfaToken: null,
      }));
    } catch (e: any) {
      setState(prev => ({ ...prev, isLoading: false, error: e.message }));
      throw e;
    }
  };

  const clearError = () => setState(prev => ({ ...prev, error: null }));

  const value = useMemo(() => ({
    ...state,
    login,
    verifyMfa,
    logout,
    clearError,
  }), [state, logout]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};
