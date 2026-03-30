import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
import { AlertCircle, Shield, LogIn, Play } from 'lucide-react';
import { Button, Card } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';

export default function Login() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const { setToken, isAuthenticated, user } = useAuth();
    const { settings } = useSettings();

    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [authStatus, setAuthStatus] = useState<{ auth0_configured: boolean; message?: string } | null>(null);
    const [demoMode, setDemoMode] = useState(false);

    // Set page title for accessibility
    useEffect(() => {
        const previousTitle = document.title;
        document.title = `Staff Login | ${settings?.township_name || 'Municipality 311'}`;
        return () => {
            document.title = previousTitle;
        };
    }, [settings?.township_name]);

    // Check auth status on mount
    useEffect(() => {
        const checkAuth = async () => {
            try {
                const [authRes, demoRes] = await Promise.all([
                    fetch('/api/auth/status'),
                    fetch('/api/demo/info'),
                ]);
                const authData = await authRes.json();
                setAuthStatus(authData);
                if (demoRes.ok) {
                    const demoData = await demoRes.json();
                    setDemoMode(demoData.demo_mode === true);
                }
            } catch (err) {
                console.error('Failed to check auth status:', err);
            }
        };
        checkAuth();
    }, []);

    // Handle callback with token from Auth0
    useEffect(() => {
        const token = searchParams.get('token');
        if (token) {
            setToken(token);
            // Remove token from URL
            navigate('/login', { replace: true });
        }
    }, [searchParams, setToken, navigate]);

    // Redirect if already logged in
    useEffect(() => {
        if (isAuthenticated && user) {
            navigate(user.role === 'admin' ? '/admin' : '/staff');
        }
    }, [isAuthenticated, user, navigate]);

    const handleLogin = async () => {
        setError('');
        setIsLoading(true);

        try {
            // Get Auth0 login URL from backend
            const redirectUri = `${window.location.origin}/login`;
            const response = await fetch(`/api/auth/login?redirect_uri=${encodeURIComponent(redirectUri)}`);

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to initiate login');
            }

            const data = await response.json();

            // Redirect to Auth0
            window.location.href = data.auth_url;
        } catch (err) {
            setError((err as Error).message || 'Failed to start login');
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center p-4">
            {/* Main content landmark */}
            <main id="main-content" className="w-full max-w-md">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    <Card className="p-8">
                        {/* Logo */}
                        <div className="text-center mb-8">
                            {settings?.logo_url ? (
                                <img
                                    src={settings.logo_url}
                                    alt={`${settings?.township_name || 'Municipality'} logo`}
                                    className="h-16 mx-auto mb-4"
                                />
                            ) : (
                                <div className="h-16 w-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/30">
                                    <svg width="36" height="36" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" fill="white" opacity="0.95"/>
                                        <circle cx="12" cy="9" r="3" fill="url(#pinGrad)"/>
                                        <defs>
                                            <linearGradient id="pinGrad" x1="9" y1="6" x2="15" y2="12" gradientUnits="userSpaceOnUse">
                                                <stop stopColor="#818cf8"/>
                                                <stop offset="1" stopColor="#4f46e5"/>
                                            </linearGradient>
                                        </defs>
                                    </svg>
                                </div>
                            )}
                            <h1 className="text-2xl font-bold text-white" data-no-translate>
                                {settings?.township_name || 'Municipality 311'}
                            </h1>
                            <p className="text-white/50 mt-2">Staff Access Portal</p>
                        </div>

                        {/* Demo Mode Login */}
                        {demoMode ? (
                            <div className="space-y-4">
                                <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 mb-2">
                                    <p className="text-emerald-300 font-medium text-center">🎯 Live Demo Environment</p>
                                    <p className="text-emerald-200/70 text-sm mt-1 text-center">
                                        Explore the full staff dashboard and admin console.
                                    </p>
                                </div>
                                <a
                                    href="/api/auth/demo-login"
                                    className="flex items-center justify-center gap-2 w-full px-6 py-3 rounded-xl font-medium text-white bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 transition-all shadow-lg shadow-emerald-500/20"
                                >
                                    <Play className="w-5 h-5" />
                                    Enter Demo
                                </a>
                            </div>
                        ) : authStatus && !authStatus.auth0_configured ? (
                            <div className="space-y-4">
                                <div className="bg-primary-500/10 border border-primary-500/30 rounded-xl p-5 text-center">
                                    <div className="text-2xl mb-2">✦</div>
                                    <p className="text-primary-300 font-semibold text-lg">Welcome to Pinpoint 311</p>
                                    <p className="text-white/50 text-sm mt-2">
                                        Your system is ready for initial setup. Enter the Admin Console to configure your municipality, maps, AI, and authentication.
                                    </p>
                                </div>
                                <a
                                    href="/api/auth/bootstrap/auto"
                                    className="flex items-center justify-center gap-2 w-full px-6 py-3 rounded-xl font-medium text-white bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 transition-all shadow-lg shadow-indigo-500/20"
                                >
                                    <Shield className="w-5 h-5" />
                                    Enter Admin Console
                                </a>
                                <p className="text-white/30 text-xs text-center">
                                    This button is only available during initial setup
                                </p>
                            </div>
                        ) : (
                            <>
                                {/* Error Message */}
                                {error && (
                                    <motion.div
                                        initial={{ opacity: 0, y: -10 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        className="flex items-center gap-3 p-4 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300 mb-6"
                                        role="alert"
                                        aria-live="assertive"
                                    >
                                        <AlertCircle className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
                                        <span className="text-sm">{error}</span>
                                    </motion.div>
                                )}

                                {/* SSO Login Button */}
                                <div className="space-y-4">
                                    <Button
                                        size="lg"
                                        className="w-full"
                                        onClick={handleLogin}
                                        disabled={isLoading}
                                        isLoading={isLoading}
                                        leftIcon={<LogIn className="w-5 h-5" />}
                                        aria-label={isLoading ? 'Signing in, please wait' : 'Sign in with your organization account'}
                                    >
                                        Sign In with SSO
                                    </Button>

                                    <div className="flex items-center justify-center gap-2 text-white/40 text-sm">
                                        <Shield className="w-4 h-4" />
                                        <span>Secured by Auth0 SSO with MFA</span>
                                    </div>
                                </div>
                            </>
                        )}

                        {/* Footer */}
                        <div className="mt-8 pt-6 border-t border-white/10 text-center">
                            <p className="text-sm text-white/40">
                                Authorized users only. Contact an administrator to request access.
                            </p>
                            <Link
                                to="/"
                                className="inline-block mt-4 text-sm text-primary-400 hover:text-primary-300 transition-colors"
                            >
                                <span aria-hidden="true">←</span> Back to public portal
                            </Link>
                            <p className="text-white/20 text-xs mt-4">
                                Powered by{' '}
                                <a
                                    href="https://pinpoint311.org"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-primary-400/50 hover:text-primary-300 transition-colors inline-flex items-center gap-1"
                                    data-no-translate
                                >
                                    Pinpoint 311
                                </a>
                                {' '}— Free &amp; Open Source
                            </p>
                        </div>
                    </Card>
                </motion.div>
            </main>
        </div>
    );
}

