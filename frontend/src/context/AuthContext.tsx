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
        localStorage.removeItem('token');
        api.setToken(null);
        setState({
            user: null,
            token: null,
            isAuthenticated: false,
            isLoading: false,
        });

        // Get Auth0 logout URL and redirect
        try {
            const response = await fetch(`/api/auth/logout?return_to=${encodeURIComponent(window.location.origin)}`);
            const data = await response.json();
            if (data.logout_url) {
                window.location.href = data.logout_url;
            }
        } catch (err) {
            console.error('Failed to get logout URL:', err);
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

