import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Chrome, ExternalLink, CheckCircle2, AlertCircle, Loader2, Key, Shield, XCircle } from 'lucide-react';
import api from '../services/api';

interface SocialConnectionStatus {
    google: boolean;
    microsoft: boolean;
    google_error?: string;
    microsoft_error?: string;
}

export default function SocialLoginConfig() {
    const [status, setStatus] = useState<SocialConnectionStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Form states
    const [showGoogleForm, setShowGoogleForm] = useState(false);
    const [showMicrosoftForm, setShowMicrosoftForm] = useState(false);

    // Google credentials
    const [googleClientId, setGoogleClientId] = useState('');
    const [googleClientSecret, setGoogleClientSecret] = useState('');
    const [googleSubmitting, setGoogleSubmitting] = useState(false);
    const [googleSuccess, setGoogleSuccess] = useState(false);
    const [googleError, setGoogleError] = useState<string | null>(null);

    // Microsoft credentials
    const [msClientId, setMsClientId] = useState('');
    const [msClientSecret, setMsClientSecret] = useState('');
    const [msTenantId, setMsTenantId] = useState('common');
    const [msSubmitting, setMsSubmitting] = useState(false);
    const [msSuccess, setMsSuccess] = useState(false);
    const [msError, setMsError] = useState<string | null>(null);

    useEffect(() => {
        loadStatus();
    }, []);

    const loadStatus = async () => {
        try {
            setLoading(true);
            const data = await api.getSocialConnectionStatus();
            setStatus(data);
            setError(null);
        } catch (err) {
            setError('Failed to load social connection status');
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleGoogleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!googleClientId || !googleClientSecret) return;

        setGoogleSubmitting(true);
        setGoogleError(null);
        setGoogleSuccess(false);

        try {
            await api.configureGoogleOAuth(googleClientId, googleClientSecret);
            setGoogleSuccess(true);
            setGoogleClientId('');
            setGoogleClientSecret('');
            setShowGoogleForm(false);
            await loadStatus();
        } catch (err: any) {
            setGoogleError(err.message || 'Failed to configure Google OAuth');
        } finally {
            setGoogleSubmitting(false);
        }
    };

    const handleMicrosoftSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!msClientId || !msClientSecret) return;

        setMsSubmitting(true);
        setMsError(null);
        setMsSuccess(false);

        try {
            await api.configureMicrosoftOAuth(msClientId, msClientSecret, msTenantId);
            setMsSuccess(true);
            setMsClientId('');
            setMsClientSecret('');
            setMsTenantId('common');
            setShowMicrosoftForm(false);
            await loadStatus();
        } catch (err: any) {
            setMsError(err.message || 'Failed to configure Microsoft OAuth');
        } finally {
            setMsSubmitting(false);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-primary-400" />
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                        <Shield className="w-5 h-5 text-primary-400" />
                        Social Login Configuration
                    </h3>
                    <p className="text-sm text-white/60 mt-1">
                        Enable Google and Microsoft sign-in for staff authentication
                    </p>
                </div>
                <button
                    onClick={loadStatus}
                    className="px-3 py-1.5 text-sm bg-white/10 hover:bg-white/15 rounded-lg text-white/70 hover:text-white transition-colors"
                >
                    Refresh Status
                </button>
            </div>

            {error && (
                <div className="p-4 bg-red-500/20 border border-red-500/30 rounded-xl text-red-300 text-sm">
                    {error}
                </div>
            )}

            {/* Connection Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Google OAuth Card */}
                <div className="p-5 rounded-xl bg-gradient-to-br from-slate-800/80 to-slate-900/80 border border-white/10">
                    <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-red-500 to-yellow-500 flex items-center justify-center">
                                <Chrome className="w-5 h-5 text-white" />
                            </div>
                            <div>
                                <h4 className="font-medium text-white">Google</h4>
                                <p className="text-xs text-white/50">Sign in with Google</p>
                            </div>
                        </div>
                        {status?.google ? (
                            <span className="flex items-center gap-1 text-xs font-medium text-emerald-400 bg-emerald-400/20 px-2 py-1 rounded-full">
                                <CheckCircle2 className="w-3 h-3" />
                                Configured
                            </span>
                        ) : (
                            <span className="flex items-center gap-1 text-xs font-medium text-white/50 bg-white/10 px-2 py-1 rounded-full">
                                <XCircle className="w-3 h-3" />
                                Not Configured
                            </span>
                        )}
                    </div>

                    <AnimatePresence mode="wait">
                        {showGoogleForm ? (
                            <motion.form
                                key="google-form"
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                onSubmit={handleGoogleSubmit}
                                className="space-y-3"
                            >
                                <a
                                    href="https://console.cloud.google.com/apis/credentials"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 mb-2"
                                >
                                    <ExternalLink className="w-3 h-3" />
                                    Open Google Cloud Console
                                </a>

                                <input
                                    type="text"
                                    placeholder="Client ID"
                                    value={googleClientId}
                                    onChange={(e) => setGoogleClientId(e.target.value)}
                                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500/50"
                                    required
                                />
                                <input
                                    type="password"
                                    placeholder="Client Secret"
                                    value={googleClientSecret}
                                    onChange={(e) => setGoogleClientSecret(e.target.value)}
                                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500/50"
                                    required
                                />

                                {googleError && (
                                    <p className="text-xs text-red-400">{googleError}</p>
                                )}

                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={() => setShowGoogleForm(false)}
                                        className="flex-1 px-3 py-2 text-sm bg-white/10 hover:bg-white/15 rounded-lg text-white/70 transition-colors"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        type="submit"
                                        disabled={googleSubmitting}
                                        className="flex-1 px-3 py-2 text-sm bg-primary-500 hover:bg-primary-600 rounded-lg text-white font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                                    >
                                        {googleSubmitting ? (
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                        ) : (
                                            <>
                                                <Key className="w-4 h-4" />
                                                Configure
                                            </>
                                        )}
                                    </button>
                                </div>

                                <p className="text-xs text-white/40 mt-2">
                                    Credentials are NOT stored — used only to configure Auth0
                                </p>
                            </motion.form>
                        ) : (
                            <motion.div
                                key="google-button"
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                            >
                                {googleSuccess && (
                                    <p className="text-xs text-emerald-400 mb-2 flex items-center gap-1">
                                        <CheckCircle2 className="w-3 h-3" />
                                        Google OAuth configured successfully!
                                    </p>
                                )}
                                <button
                                    onClick={() => setShowGoogleForm(true)}
                                    className="w-full px-4 py-2 text-sm bg-white/10 hover:bg-white/15 rounded-lg text-white/80 hover:text-white transition-colors"
                                >
                                    {status?.google ? 'Update Credentials' : 'Configure Google OAuth'}
                                </button>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {/* Microsoft OAuth Card */}
                <div className="p-5 rounded-xl bg-gradient-to-br from-slate-800/80 to-slate-900/80 border border-white/10">
                    <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center">
                                <svg className="w-5 h-5 text-white" viewBox="0 0 23 23" fill="currentColor">
                                    <path d="M0 0h11v11H0zM12 0h11v11H12zM0 12h11v11H0zM12 12h11v11H12z" />
                                </svg>
                            </div>
                            <div>
                                <h4 className="font-medium text-white">Microsoft</h4>
                                <p className="text-xs text-white/50">Sign in with Microsoft</p>
                            </div>
                        </div>
                        {status?.microsoft ? (
                            <span className="flex items-center gap-1 text-xs font-medium text-emerald-400 bg-emerald-400/20 px-2 py-1 rounded-full">
                                <CheckCircle2 className="w-3 h-3" />
                                Configured
                            </span>
                        ) : (
                            <span className="flex items-center gap-1 text-xs font-medium text-white/50 bg-white/10 px-2 py-1 rounded-full">
                                <XCircle className="w-3 h-3" />
                                Not Configured
                            </span>
                        )}
                    </div>

                    <AnimatePresence mode="wait">
                        {showMicrosoftForm ? (
                            <motion.form
                                key="ms-form"
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                onSubmit={handleMicrosoftSubmit}
                                className="space-y-3"
                            >
                                <a
                                    href="https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 mb-2"
                                >
                                    <ExternalLink className="w-3 h-3" />
                                    Open Azure Portal
                                </a>

                                <input
                                    type="text"
                                    placeholder="Application (client) ID"
                                    value={msClientId}
                                    onChange={(e) => setMsClientId(e.target.value)}
                                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500/50"
                                    required
                                />
                                <input
                                    type="password"
                                    placeholder="Client Secret"
                                    value={msClientSecret}
                                    onChange={(e) => setMsClientSecret(e.target.value)}
                                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500/50"
                                    required
                                />
                                <input
                                    type="text"
                                    placeholder="Tenant ID (optional, default: common)"
                                    value={msTenantId}
                                    onChange={(e) => setMsTenantId(e.target.value)}
                                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500/50"
                                />

                                {msError && (
                                    <p className="text-xs text-red-400">{msError}</p>
                                )}

                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={() => setShowMicrosoftForm(false)}
                                        className="flex-1 px-3 py-2 text-sm bg-white/10 hover:bg-white/15 rounded-lg text-white/70 transition-colors"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        type="submit"
                                        disabled={msSubmitting}
                                        className="flex-1 px-3 py-2 text-sm bg-primary-500 hover:bg-primary-600 rounded-lg text-white font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                                    >
                                        {msSubmitting ? (
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                        ) : (
                                            <>
                                                <Key className="w-4 h-4" />
                                                Configure
                                            </>
                                        )}
                                    </button>
                                </div>

                                <p className="text-xs text-white/40 mt-2">
                                    Credentials are NOT stored — used only to configure Auth0
                                </p>
                            </motion.form>
                        ) : (
                            <motion.div
                                key="ms-button"
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                            >
                                {msSuccess && (
                                    <p className="text-xs text-emerald-400 mb-2 flex items-center gap-1">
                                        <CheckCircle2 className="w-3 h-3" />
                                        Microsoft OAuth configured successfully!
                                    </p>
                                )}
                                <button
                                    onClick={() => setShowMicrosoftForm(true)}
                                    className="w-full px-4 py-2 text-sm bg-white/10 hover:bg-white/15 rounded-lg text-white/80 hover:text-white transition-colors"
                                >
                                    {status?.microsoft ? 'Update Credentials' : 'Configure Microsoft OAuth'}
                                </button>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </div>

            {/* Info Note */}
            <div className="p-4 rounded-xl bg-blue-500/10 border border-blue-500/20">
                <div className="flex gap-3">
                    <AlertCircle className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-blue-200 space-y-1">
                        <p className="font-medium">How it works:</p>
                        <ul className="list-disc list-inside text-blue-300/80 space-y-0.5 text-xs">
                            <li>Create an OAuth app in Google Cloud Console or Azure Portal</li>
                            <li>Enter the credentials here — they are used to configure Auth0 directly</li>
                            <li>Credentials are processed in-memory and never saved to our database</li>
                            <li>Users will see Google/Microsoft login options on the staff login page</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    );
}
