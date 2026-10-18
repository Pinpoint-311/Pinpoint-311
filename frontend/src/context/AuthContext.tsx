import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { AuthState } from '../types';
import { api } from '../services/api';

interface AuthContextType extends AuthState {
    setToken: (token: string) => Promise<void>;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [state, setState] = useState<AuthState>({
        user: null,
        token: localStorage.getItem('token'),
        isAuthenticated: false,
        isLoading: true,
    });

    const fetchUser = useCallback(async () => {
        const token = localStorage.getItem('token');
        if (!token) {
            setState(s => ({ ...s, isLoading: false }));
            return;
        }

        api.setToken(token);
        try {
            const user = await api.getMe();
            setState({
                user,
                token,
                isAuthenticated: true,
                isLoading: false,
            });
        } catch {
            localStorage.removeItem('token');
            api.setToken(null);
            setState({
                user: null,
                token: null,
                isAuthenticated: false,
                isLoading: false,
            });
        }
    }, []);

    useEffect(() => {
        fetchUser();

        // Global 401 handler: auto-logout when JWT expires mid-session
        api.setOnUnauthorized(() => {
            localStorage.removeItem('token');
            api.setToken(null);
            setState({
                user: null,
                token: null,
                isAuthenticated: false,
                isLoading: false,
            });
        });

        return () => { api.setOnUnauthorized(null); };
    }, [fetchUser]);

    // Set token from SSO callback
    const setToken = async (token: string) => {
        localStorage.setItem('token', token);
        api.setToken(token);

        try {
            const user = await api.getMe();
            setState({
                user,
                token,
                isAuthenticated: true,
                isLoading: false,
            });
        } catch {
            localStorage.removeItem('token');
            api.setToken(null);
            setState({
                user: null,
                token: null,
                isAuthenticated: false,
                isLoading: false,
            });
        }
    };

    const logout = async () => {
        /* The token is captured before it is forgotten and sent with the
         * sign-out call. This used to clear it and THEN call /api/auth/logout
         * with no Authorization header, so the call was always a 401: the
         * server never heard about the sign-out, nothing was revoked or
         * audited, and a copy of the token kept working until it expired. The
         * server now revokes every session this account holds. Local state is
         * still cleared synchronously, so callers can navigate straight away. */
        const token = localStorage.getItem('token') || state.token;
        localStorage.removeItem('token');
        api.setToken(null);
        setState({
            user: null,
            token: null,
            isAuthenticated: false,
            isLoading: false,
        });

        if (!token) return;
        try {
            const data = await api.logout(token, window.location.origin);
            // No identity provider: the server echoes return_to back, and the
            // caller has already navigated to the sign-in page -- stay there.
            if (data?.logout_url && data.logout_url !== window.location.origin) {
                window.location.href = data.logout_url;
            }
        } catch (err) {
            // Already revoked or offline: the local sign-out above stands.
            console.error('Failed to sign out on the server:', err);
        }
    };

    return (
        <AuthContext.Provider value={{ ...state, setToken, logout }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = (): AuthContextType => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
};

