import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

interface SsoPayload {
    jti: string;
    vc_guid: string;
    email: string;
    vc_id: number;
    vc_status: number;
    session_salt: string;
    exp?: number;
    [key: string]: unknown;
}

interface AuthContextType {
    isAuthenticated: boolean;
    user: SsoPayload | null;
    token: string | null;
    login: (token: string) => void;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [token, setToken] = useState<string | null>(localStorage.getItem('vqa_sso_token'));
    const [user, setUser] = useState<SsoPayload | null>(null);

    const logout = useCallback(() => {
        setToken(null);
        setUser(null);
        localStorage.removeItem('vqa_sso_token');
    }, []);

    useEffect(() => {
        if (token) {
            localStorage.setItem('vqa_sso_token', token);
            try {
                const payloadStr = atob(token.split('.')[1]);
                const payload = JSON.parse(payloadStr) as SsoPayload;
                setUser(payload);
            } catch (e) {
                console.error("Failed to decode token", e);
                logout();
            }
        } else {
            localStorage.removeItem('vqa_sso_token');
            setUser(null);
        }
    }, [token, logout]);

    const login = (newToken: string) => {
        setToken(newToken);
    };

    return (
        <AuthContext.Provider value={{ isAuthenticated: !!token, user, token, login, logout }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
