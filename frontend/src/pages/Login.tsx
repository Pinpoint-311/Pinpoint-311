import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, Link } from 'react-router-dom';
import { Sparkles, User, Lock, AlertCircle } from 'lucide-react';
import { Button, Input, Card } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';

export default function Login() {
    const navigate = useNavigate();
    const { login, isAuthenticated, user } = useAuth();
    const { settings } = useSettings();

    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    // Set page title for accessibility
    useEffect(() => {
        const previousTitle = document.title;
        document.title = `Staff Login | ${settings?.township_name || 'Township 311'}`;
        return () => {
            document.title = previousTitle;
        };
    }, [settings?.township_name]);

    // Redirect if already logged in
    useEffect(() => {
        if (isAuthenticated && user) {
            navigate(user.role === 'admin' ? '/admin' : '/staff');
        }
    }, [isAuthenticated, user, navigate]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            await login(username, password);
            // Navigation will happen via useEffect
        } catch (err) {
            setError((err as Error).message || 'Invalid credentials');
        } finally {
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

                        {/* Form */}
                        <form onSubmit={handleSubmit} className="space-y-5" aria-label="Staff login form">
                            {error && (
                                <motion.div
                                    initial={{ opacity: 0, y: -10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className="flex items-center gap-3 p-4 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300"
                                    role="alert"
                                    aria-live="assertive"
                                >
                                    <AlertCircle className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
                                    <span className="text-sm">{error}</span>
                                </motion.div>
                            )}

                            <Input
                                label="Username"
                                placeholder="Enter your username"
                                leftIcon={<User className="w-5 h-5" />}
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                required
                                autoComplete="username"
                                aria-describedby={error ? 'login-error' : undefined}
                            />

                            <Input
                                label="Password"
                                type="password"
                                placeholder="Enter your password"
                                leftIcon={<Lock className="w-5 h-5" />}
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                autoComplete="current-password"
                            />

                            <Button
                                type="submit"
                                size="lg"
                                className="w-full"
                                isLoading={isLoading}
                                aria-label={isLoading ? 'Signing in, please wait' : 'Sign in to staff portal'}
                            >
                                Sign In
                            </Button>
                        </form>

                        {/* Footer */}
                        <div className="mt-8 pt-6 border-t border-white/10 text-center">
                            <p className="text-sm text-white/40">
                                Authorized users only. Unauthorized access is prohibited.
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
