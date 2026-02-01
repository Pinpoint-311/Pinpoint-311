import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Key, Shield, Cloud, MessageSquare, Mail, Sparkles, CheckCircle,
    AlertCircle, ChevronDown, ChevronUp, Copy, Check, Terminal,
    ExternalLink, AlertTriangle, Database
} from 'lucide-react';
import { Card, Button, Input, Select, Badge } from './ui';
import { SystemSecret } from '../types';

interface SetupIntegrationsPageProps {
    secrets: SystemSecret[];
    onSaveSecret: (key: string, value: string) => Promise<void>;
    onRefresh: () => void;
}

export default function SetupIntegrationsPage({ secrets, onSaveSecret, onRefresh }: SetupIntegrationsPageProps) {
    const [secretValues, setSecretValues] = useState<Record<string, string>>({});
    const [savingKey, setSavingKey] = useState<string | null>(null);
    const [showTerminal, setShowTerminal] = useState(false);
    const [copyFeedback, setCopyFeedback] = useState<string | null>(null);

    const isConfigured = (key: string) => secrets.find(s => s.key_name === key)?.is_configured;

    const handleSave = async (key: string) => {
        if (!secretValues[key]) return;
        setSavingKey(key);
        try {
            await onSaveSecret(key, secretValues[key]);
            setSecretValues(prev => ({ ...prev, [key]: '' }));
            onRefresh();
        } catch (err) {
            console.error('Failed to save secret:', err);
        } finally {
            setSavingKey(null);
        }
    };

    const copyToClipboard = (text: string, label: string) => {
        navigator.clipboard.writeText(text);
        setCopyFeedback(label);
        setTimeout(() => setCopyFeedback(null), 2000);
    };

    // Status badge rendering - icons are inline where needed

    const getStatusBadge = (configured: boolean | undefined) => {
        if (configured) return <Badge variant="success">Configured</Badge>;
        return <Badge variant="warning">Not Configured</Badge>;
    };

    // Check configuration status
    const auth0Configured = isConfigured('AUTH0_DOMAIN') && isConfigured('AUTH0_CLIENT_ID') && isConfigured('AUTH0_CLIENT_SECRET');
    const smsProvider = secrets.find(s => s.key_name === 'SMS_PROVIDER')?.key_value;
    const smtpConfigured = isConfigured('SMTP_HOST') && isConfigured('SMTP_FROM_EMAIL');
    const sentryConfigured = isConfigured('SENTRY_DSN');

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold text-white">Setup & Integrations</h1>
                <p className="text-gray-400 mt-1">Configure authentication, notifications, and cloud services</p>
            </div>

            {/* Setup Wizard CTA */}
            <Card className="bg-gradient-to-r from-indigo-600/20 to-purple-600/20 border-indigo-500/30">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-indigo-500/30 flex items-center justify-center">
                            <Sparkles className="w-6 h-6 text-indigo-400" />
                        </div>
                        <div>
                            <h3 className="text-lg font-bold text-white">Automated Setup Wizard</h3>
                            <p className="text-white/70 text-sm">Configure Auth0 and Google Cloud in minutes — no SSH required!</p>
                        </div>
                    </div>
                    <Button
                        onClick={() => window.location.href = '/setup'}
                        className="bg-indigo-600 hover:bg-indigo-700"
                    >
                        <Sparkles className="w-4 h-4 mr-2" />
                        Launch Wizard
                    </Button>
                </div>
            </Card>

            {/* Required Integrations */}
            <div>
                <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Shield className="w-5 h-5 text-red-400" />
                    Required Integrations
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Auth0 SSO */}
                    <Card className="h-full">
                        <div className="flex items-start justify-between mb-4">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-lg bg-orange-500/20 flex items-center justify-center">
                                    <Key className="w-5 h-5 text-orange-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">Auth0 SSO</h3>
                                    <p className="text-gray-400 text-xs">Staff authentication with MFA</p>
                                </div>
                            </div>
                            {getStatusBadge(auth0Configured)}
                        </div>

                        <div className="space-y-3">
                            {['AUTH0_DOMAIN', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET'].map(key => {
                                const configured = isConfigured(key);
                                const label = key.replace('AUTH0_', '').replace(/_/g, ' ');
                                return (
                                    <div key={key}>
                                        <label className="text-xs text-gray-400 block mb-1">{label}</label>
                                        {configured && !secretValues[key] ? (
                                            <div className="flex items-center gap-2">
                                                <div className="flex-1 h-9 rounded-lg bg-green-500/20 border border-green-500/30 flex items-center px-3">
                                                    <span className="text-green-300 text-xs">✓ Configured</span>
                                                </div>
                                                <Button size="sm" variant="ghost" onClick={() => setSecretValues(p => ({ ...p, [key]: '' }))}>
                                                    Change
                                                </Button>
                                            </div>
                                        ) : (
                                            <div className="flex gap-2">
                                                <Input
                                                    type={key.includes('SECRET') ? 'password' : 'text'}
                                                    placeholder={key.includes('DOMAIN') ? 'yourorg.us.auth0.com' : '...'}
                                                    value={secretValues[key] || ''}
                                                    onChange={(e) => setSecretValues(p => ({ ...p, [key]: e.target.value }))}
                                                    className="flex-1 text-sm"
                                                />
                                                <Button
                                                    size="sm"
                                                    onClick={() => handleSave(key)}
                                                    disabled={!secretValues[key] || savingKey === key}
                                                >
                                                    {savingKey === key ? '...' : 'Save'}
                                                </Button>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>

                        <div className="mt-4 text-xs text-gray-500">
                            Callback: <code className="bg-white/10 px-1 rounded">{window.location.origin}/api/auth/callback</code>
                        </div>
                    </Card>

                    {/* Database - usually auto-configured */}
                    <Card className="h-full">
                        <div className="flex items-start justify-between mb-4">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center">
                                    <Database className="w-5 h-5 text-purple-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">PostgreSQL Database</h3>
                                    <p className="text-gray-400 text-xs">Primary data storage</p>
                                </div>
                            </div>
                            <Badge variant="success">Auto-configured</Badge>
                        </div>
                        <p className="text-gray-400 text-sm">
                            Database connection is configured via <code className="bg-white/10 px-1 rounded">DATABASE_URL</code> environment variable in docker-compose.yml.
                        </p>
                        <div className="mt-4 flex items-center gap-2 text-green-400 text-sm">
                            <CheckCircle className="w-4 h-4" />
                            Connected and operational
                        </div>
                    </Card>
                </div>
            </div>

            {/* Optional Integrations */}
            <div>
                <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Cloud className="w-5 h-5 text-blue-400" />
                    Optional Integrations
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {/* Google Cloud */}
                    <Card>
                        <div className="flex items-start justify-between mb-3">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
                                    <Cloud className="w-5 h-5 text-blue-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">Google Cloud</h3>
                                    <p className="text-gray-400 text-xs">KMS, AI, Secrets, Translation</p>
                                </div>
                            </div>
                        </div>
                        <p className="text-gray-400 text-sm mb-3">
                            Set up via environment variables or the Setup Wizard.
                        </p>
                        <Button
                            size="sm"
                            variant="secondary"
                            className="w-full"
                            onClick={() => window.location.href = '/setup'}
                        >
                            <Sparkles className="w-4 h-4 mr-2" />
                            Configure with Wizard
                        </Button>
                    </Card>

                    {/* SMS Notifications */}
                    <Card>
                        <div className="flex items-start justify-between mb-3">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-lg bg-green-500/20 flex items-center justify-center">
                                    <MessageSquare className="w-5 h-5 text-green-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">SMS Notifications</h3>
                                    <p className="text-gray-400 text-xs">Twilio or custom HTTP</p>
                                </div>
                            </div>
                            {getStatusBadge(!!(smsProvider && smsProvider !== 'none'))}
                        </div>
                        <Select
                            options={[
                                { value: 'none', label: 'Disabled' },
                                { value: 'twilio', label: 'Twilio' },
                                { value: 'http', label: 'Custom HTTP API' },
                            ]}
                            value={smsProvider || 'none'}
                            onChange={(e) => onSaveSecret('SMS_PROVIDER', e.target.value)}
                        />
                    </Card>

                    {/* Email SMTP */}
                    <Card>
                        <div className="flex items-start justify-between mb-3">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center">
                                    <Mail className="w-5 h-5 text-purple-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">Email (SMTP)</h3>
                                    <p className="text-gray-400 text-xs">Outgoing notifications</p>
                                </div>
                            </div>
                            {getStatusBadge(smtpConfigured)}
                        </div>
                        <p className="text-gray-400 text-xs">
                            Configure SMTP credentials in the detailed settings above.
                        </p>
                    </Card>

                    {/* Sentry Error Tracking */}
                    <Card>
                        <div className="flex items-start justify-between mb-3">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-lg bg-red-500/20 flex items-center justify-center">
                                    <AlertTriangle className="w-5 h-5 text-red-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">Sentry</h3>
                                    <p className="text-gray-400 text-xs">Error monitoring</p>
                                </div>
                            </div>
                            {getStatusBadge(sentryConfigured)}
                        </div>
                        {!sentryConfigured || secretValues['SENTRY_DSN'] !== undefined ? (
                            <div className="flex gap-2">
                                <Input
                                    type="text"
                                    placeholder="https://xxx@sentry.io/xxx"
                                    value={secretValues['SENTRY_DSN'] || ''}
                                    onChange={(e) => setSecretValues(p => ({ ...p, 'SENTRY_DSN': e.target.value }))}
                                    className="flex-1 text-sm"
                                />
                                <Button
                                    size="sm"
                                    onClick={() => handleSave('SENTRY_DSN')}
                                    disabled={!secretValues['SENTRY_DSN'] || savingKey === 'SENTRY_DSN'}
                                >
                                    Save
                                </Button>
                            </div>
                        ) : (
                            <div className="flex items-center gap-2">
                                <div className="flex-1 h-9 rounded-lg bg-green-500/20 border border-green-500/30 flex items-center px-3">
                                    <span className="text-green-300 text-xs">✓ Configured</span>
                                </div>
                                <Button size="sm" variant="ghost" onClick={() => setSecretValues(p => ({ ...p, 'SENTRY_DSN': '' }))}>
                                    Change
                                </Button>
                            </div>
                        )}
                    </Card>
                </div>
            </div>

            {/* Terminal Commands (Collapsible) */}
            <Card className="bg-slate-900/50">
                <button
                    onClick={() => setShowTerminal(!showTerminal)}
                    className="w-full flex items-center justify-between"
                >
                    <div className="flex items-center gap-3">
                        <Terminal className="w-5 h-5 text-green-400" />
                        <div className="text-left">
                            <h3 className="font-semibold text-white">Advanced: Terminal Setup Commands</h3>
                            <p className="text-gray-400 text-xs">For manual server configuration</p>
                        </div>
                    </div>
                    {showTerminal ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
                </button>

                <AnimatePresence>
                    {showTerminal && (
                        <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="overflow-hidden"
                        >
                            <div className="mt-4 space-y-4">
                                {/* GCP Setup */}
                                <div className="bg-black/30 rounded-lg p-4">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-white/60 text-sm font-medium">Google Cloud Platform Setup</span>
                                        <button
                                            onClick={() => copyToClipboard('./scripts/setup_gcp.sh YOUR_PROJECT_ID', 'GCP')}
                                            className="flex items-center gap-2 px-3 py-1 bg-white/10 hover:bg-white/20 rounded text-xs text-white/80 transition-colors"
                                        >
                                            {copyFeedback === 'GCP' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                                            Copy
                                        </button>
                                    </div>
                                    <code className="text-green-400 font-mono text-sm">./scripts/setup_gcp.sh YOUR_PROJECT_ID</code>
                                </div>

                                {/* Auth0 Setup */}
                                <div className="bg-black/30 rounded-lg p-4">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-white/60 text-sm font-medium">Auth0 Configuration Helper</span>
                                        <button
                                            onClick={() => copyToClipboard('./scripts/setup_auth0.sh', 'Auth0')}
                                            className="flex items-center gap-2 px-3 py-1 bg-white/10 hover:bg-white/20 rounded text-xs text-white/80 transition-colors"
                                        >
                                            {copyFeedback === 'Auth0' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                                            Copy
                                        </button>
                                    </div>
                                    <code className="text-green-400 font-mono text-sm">./scripts/setup_auth0.sh</code>
                                </div>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </Card>

            {/* Help Link */}
            <Card className="bg-blue-500/10 border-blue-500/20">
                <div className="flex items-center gap-3">
                    <AlertCircle className="w-5 h-5 text-blue-400" />
                    <p className="text-blue-200/80 text-sm flex-1">
                        Need help? Check the <strong>System Health</strong> tab to verify your integrations are working correctly.
                    </p>
                    <a
                        href="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/blob/main/docs/SETUP.md"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-400 text-sm hover:underline flex items-center gap-1"
                    >
                        Setup Docs <ExternalLink className="w-3 h-3" />
                    </a>
                </div>
            </Card>
        </div>
    );
}
