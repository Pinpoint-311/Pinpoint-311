import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
import { Sparkles, AlertCircle, Shield, LogIn } from 'lucide-react';
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

    // Set page title for accessibility
    useEffect(() => {
        const previousTitle = document.title;
        document.title = `Staff Login | ${settings?.township_name || 'Township 311'}`;
        return () => {
            document.title = previousTitle;
        };
    }, [settings?.township_name]);

    // Check auth status on mount
    useEffect(() => {
        const checkAuth = async () => {
            try {
                const response = await fetch('/api/auth/status');
                const data = await response.json();
                setAuthStatus(data);
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
                                    alt={`${settings?.township_name || 'Township'} logo`}
                                    className="h-16 mx-auto mb-4"
                                />
                            ) : (
                                <div
                                    className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center glow-effect"
                                    aria-hidden="true"
                                >
                                    <Sparkles className="w-8 h-8 text-white" />
                                </div>
                            )}
                            <h1 className="text-2xl font-bold text-white" data-no-translate>
                                {settings?.township_name || 'Township 311'}
                            </h1>
                            <p className="text-white/50 mt-2">Staff Access Portal</p>
                        </div>

                        {/* Auth Status */}
                        {authStatus && !authStatus.auth0_configured ? (
                            <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 mb-6">
                                <div className="flex items-start gap-3">
                                    <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                                    <div>
                                        <p className="text-amber-300 font-medium">Authentication Not Configured</p>
                                        <p className="text-amber-200/70 text-sm mt-1">
                                            An administrator needs to configure Auth0 in the Admin Console before staff can log in.
                                        </p>
                                    </div>
                                </div>
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
                                        isLoading={isLoading}
                                        leftIcon={<LogIn className="w-5 h-5" />}
                                        aria-label={isLoading ? 'Signing in, please wait' : 'Sign in with your organization account'}
                                    >
                                        Sign In with SSO
                                    </Button>

                                    <div className="flex items-center justify-center gap-2 text-white/40 text-sm">
                                        <Shield className="w-4 h-4" />
                                        <span>Secured by Auth0 with MFA</span>
                                    </div>
                                </div>

                                {/* Supported Providers */}
                                <div className="mt-6 pt-6 border-t border-white/10">
                                    <p className="text-center text-white/40 text-xs mb-4">Sign in with your organization account</p>
                                    <div className="flex justify-center gap-4">
                                        <div className="flex items-center gap-2 text-white/50 text-sm">
                                            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                                                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                                                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                                                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                                                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                                            </svg>
                                            <span>Google</span>
                                        </div>
                                        <div className="flex items-center gap-2 text-white/50 text-sm">
                                            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                                                <path d="M11.4 24H0V12.6L11.4 0H24v11.4L11.4 24z" />
                                            </svg>
                                            <span>Microsoft</span>
                                        </div>
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
                                    href="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-primary-400/50 hover:text-primary-300 transition-colors"
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

