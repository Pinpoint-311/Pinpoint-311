import { useState, useEffect, useRef } from 'react';

import { motion, AnimatePresence } from 'framer-motion';
import {
    Key, Shield, Cloud, MessageSquare, Mail, CheckCircle,
    AlertCircle, ChevronDown, ChevronUp, Copy, Check, Terminal,
    ExternalLink, AlertTriangle, Database, BookOpen,
    ListChecks
} from 'lucide-react';

import { Card, Button, Input, Select, Badge } from './ui';
import { SystemSecret } from '../types';
import SocialLoginConfig from './SocialLoginConfig';

interface ModulesState {
    ai_analysis: boolean;
    sms_alerts: boolean;
    email_notifications: boolean;
    research_portal: boolean;
}

interface SetupIntegrationsPageProps {
    secrets: SystemSecret[];
    onSaveSecret: (key: string, value: string) => Promise<void>;
    onRefresh: () => void;
    modules?: ModulesState;
    onUpdateModules?: (modules: ModulesState) => Promise<void>;
}


export default function SetupIntegrationsPage({ secrets, onSaveSecret, onRefresh, modules, onUpdateModules }: SetupIntegrationsPageProps) {
    const [secretValues, setSecretValues] = useState<Record<string, string>>({});
    const [savingKey, setSavingKey] = useState<string | null>(null);
    const [showTerminal, setShowTerminal] = useState(false);
    const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
    const [localSmsProvider, setLocalSmsProvider] = useState<string>('none');
    const [savingSmsProvider, setSavingSmsProvider] = useState(false);
    const userModifiedSms = useRef(false);
    const [expandedGuide, setExpandedGuide] = useState<string | null>(null);



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
    const smsProviderFromSecrets = secrets.find(s => s.key_name === 'SMS_PROVIDER')?.key_value;
    const smtpConfigured = isConfigured('SMTP_HOST') && isConfigured('SMTP_FROM_EMAIL');

    // Sync local SMS provider state with secrets (only if user hasn't modified)
    useEffect(() => {
        if (smsProviderFromSecrets && !userModifiedSms.current) {
            setLocalSmsProvider(smsProviderFromSecrets);
        }
    }, [smsProviderFromSecrets]);
    const sentryConfigured = isConfigured('SENTRY_DSN');
    const gcpConfigured = isConfigured('GOOGLE_CLOUD_PROJECT');
    const smsConfigured = !!(localSmsProvider && localSmsProvider !== 'none');

    // Setup progress calculation
    const setupSteps = [
        { label: 'Auth0 SSO', done: !!auth0Configured, required: true },
        { label: 'Email (SMTP)', done: !!smtpConfigured, required: false },
        { label: 'Google Cloud', done: !!gcpConfigured, required: false },
        { label: 'SMS Alerts', done: smsConfigured, required: false },
    ];
    const completedCount = setupSteps.filter(s => s.done).length;

    // Toggle helper for collapsible instruction panels
    const toggleGuide = (id: string) => setExpandedGuide(prev => prev === id ? null : id);

    // Reusable instruction step renderer
    const InstructionStep = ({ num, children }: { num: number; children: React.ReactNode }) => (
        <div className="flex gap-3 items-start">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-white/10 text-white/70 text-xs font-bold flex items-center justify-center mt-0.5">{num}</span>
            <div className="text-sm text-white/70 leading-relaxed">{children}</div>
        </div>
    );

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold text-white">Setup & Integrations</h1>
                <p className="text-gray-300 mt-1">Configure authentication, notifications, and cloud services</p>
            </div>

            {/* ── Setup Progress Tracker ── */}
            <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-slate-800/80 via-slate-900/90 to-slate-800/80 backdrop-blur-xl p-5"
            >
                <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                        <ListChecks className="w-5 h-5 text-white" />
                    </div>
                    <div>
                        <h2 className="font-semibold text-white">Setup Progress</h2>
                        <p className="text-white/50 text-xs">{completedCount} of {setupSteps.length} integrations configured</p>
                    </div>
                </div>

                {/* Progress bar */}
                <div className="h-2 rounded-full bg-white/10 mb-4 overflow-hidden">
                    <motion.div
                        className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-cyan-400"
                        initial={{ width: 0 }}
                        animate={{ width: `${(completedCount / setupSteps.length) * 100}%` }}
                        transition={{ duration: 0.8, ease: 'easeOut' }}
                    />
                </div>

                {/* Step chips */}
                <div className="flex flex-wrap gap-2">
                    {setupSteps.map(step => (
                        <span
                            key={step.label}
                            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all ${step.done
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                : step.required
                                    ? 'bg-amber-500/15 text-amber-300 border border-amber-500/25'
                                    : 'bg-white/5 text-white/40 border border-white/10'
                                }`}
                        >
                            {step.done ? <CheckCircle className="w-3.5 h-3.5" /> : step.required ? <AlertCircle className="w-3.5 h-3.5" /> : <div className="w-3.5 h-3.5 rounded-full border border-current" />}
                            {step.label}
                            {step.required && !step.done && <span className="text-[10px] opacity-70">required</span>}
                        </span>
                    ))}
                </div>
            </motion.div>

            {/* ── Setup Instructions (collapsible) ── */}
            <Card className="border-indigo-500/20 bg-indigo-500/5">
                <button
                    onClick={() => toggleGuide('master')}
                    className="w-full flex items-center justify-between"
                >
                    <div className="flex items-center gap-3">
                        <BookOpen className="w-5 h-5 text-indigo-400" />
                        <div className="text-left">
                            <h3 className="font-semibold text-white">Setup Instructions</h3>
                            <p className="text-white/50 text-xs">Step-by-step guides for each integration</p>
                        </div>
                    </div>
                    {expandedGuide === 'master' ? <ChevronUp className="w-5 h-5 text-white/50" /> : <ChevronDown className="w-5 h-5 text-white/50" />}
                </button>

                <AnimatePresence>
                    {expandedGuide === 'master' && (
                        <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="overflow-hidden"
                        >
                            <div className="mt-4 space-y-4">
                                {/* Auth0 Instructions */}
                                <div className="rounded-xl border border-orange-500/20 bg-orange-500/5 p-4">
                                    <div className="flex items-center gap-2 mb-3">
                                        <Key className="w-4 h-4 text-orange-400" />
                                        <h4 className="font-semibold text-white text-sm">Auth0 SSO Setup</h4>
                                        {auth0Configured && <Badge variant="success">Done</Badge>}
                                    </div>
                                    <div className="space-y-2.5">
                                        <InstructionStep num={1}>Go to <a href="https://auth0.com" target="_blank" rel="noopener noreferrer" className="text-orange-300 underline underline-offset-2">auth0.com</a> and create a free account (or use your organization's existing tenant).</InstructionStep>
                                        <InstructionStep num={2}>In the Auth0 Dashboard, go to <strong className="text-white/90">Applications → Create Application</strong>. Choose <strong className="text-white/90">Regular Web Application</strong>.</InstructionStep>
                                        <InstructionStep num={3}>In the app's <strong className="text-white/90">Settings</strong> tab, copy the <strong className="text-white/90">Domain</strong>, <strong className="text-white/90">Client ID</strong>, and <strong className="text-white/90">Client Secret</strong> into the fields below.</InstructionStep>
                                        <InstructionStep num={4}>
                                            Set the <strong className="text-white/90">Allowed Callback URL</strong> to: <code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}/api/auth/callback</code>
                                            <button onClick={() => copyToClipboard(`${window.location.origin}/api/auth/callback`, 'callback')} className="ml-1 inline-flex text-white/40 hover:text-white/70 transition-colors">
                                                {copyFeedback === 'callback' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                                            </button>
                                        </InstructionStep>
                                        <InstructionStep num={5}>Under <strong className="text-white/90">Security → Multi-factor Auth</strong>, enable MFA for staff login protection.</InstructionStep>
                                        <InstructionStep num={6}><em className="text-white/50">Optional:</em> Under <strong className="text-white/90">Authentication → Social</strong>, add Google and Microsoft connections for social login.</InstructionStep>
                                    </div>
                                </div>

                                {/* SMTP Instructions */}
                                <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
                                    <div className="flex items-center gap-2 mb-3">
                                        <Mail className="w-4 h-4 text-violet-400" />
                                        <h4 className="font-semibold text-white text-sm">Email (SMTP) Setup</h4>
                                        {smtpConfigured && <Badge variant="success">Done</Badge>}
                                    </div>
                                    <div className="space-y-2.5">
                                        <InstructionStep num={1}>Choose an SMTP provider. Common options for government: <strong className="text-white/90">SendGrid</strong>, <strong className="text-white/90">Gmail</strong> (via App Passwords), or your organization's <strong className="text-white/90">existing SMTP relay</strong>.</InstructionStep>
                                        <InstructionStep num={2}>
                                            <strong className="text-white/90">Gmail:</strong> Enable 2FA on your Google Account, then go to <em>Security → App Passwords</em> and generate one. Use <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">smtp.gmail.com</code> port <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">587</code>.
                                        </InstructionStep>
                                        <InstructionStep num={3}>
                                            <strong className="text-white/90">SendGrid:</strong> Create a free account at <a href="https://sendgrid.com" target="_blank" rel="noopener noreferrer" className="text-violet-300 underline underline-offset-2">sendgrid.com</a>. Generate an API key under <em>Settings → API Keys</em>. Use <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">smtp.sendgrid.net</code> port <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">587</code>, username <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">apikey</code>, password = your API key.
                                        </InstructionStep>
                                        <InstructionStep num={4}>Enter the host, port, from address, username, and password in the Email (SMTP) card below and click <strong className="text-white/90">Save SMTP Settings</strong>.</InstructionStep>
                                    </div>
                                </div>

                                {/* GCP Instructions */}
                                <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4">
                                    <div className="flex items-center gap-2 mb-3">
                                        <Cloud className="w-4 h-4 text-blue-400" />
                                        <h4 className="font-semibold text-white text-sm">Google Cloud Setup</h4>
                                        {gcpConfigured && <Badge variant="success">Done</Badge>}
                                    </div>
                                    <div className="space-y-2.5">
                                        <InstructionStep num={1}>Create a GCP project at <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">console.cloud.google.com</a>.</InstructionStep>
                                        <InstructionStep num={2}>Enable the following APIs: <strong className="text-white/90">Cloud KMS</strong>, <strong className="text-white/90">Cloud Translation</strong>, <strong className="text-white/90">Vertex AI</strong>, and <strong className="text-white/90">Secret Manager</strong>.</InstructionStep>
                                        <InstructionStep num={3}>Create a Service Account with the roles: <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud KMS Admin</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud Translation API User</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Vertex AI User</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Secret Manager Admin</code>.</InstructionStep>
                                        <InstructionStep num={4}>Download the Service Account JSON key file.</InstructionStep>
                                        <InstructionStep num={5}>
                                            Run the setup script on your server:
                                            <div className="mt-1.5 flex items-center gap-2">
                                                <code className="bg-black/30 px-2 py-1 rounded text-green-400 text-xs font-mono">./scripts/setup_gcp.sh YOUR_PROJECT_ID</code>
                                                <button onClick={() => copyToClipboard('./scripts/setup_gcp.sh YOUR_PROJECT_ID', 'gcp-cmd')} className="text-white/40 hover:text-white/70 transition-colors">
                                                    {copyFeedback === 'gcp-cmd' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                                                </button>
                                            </div>
                                        </InstructionStep>
                                        <InstructionStep num={6}>The script will configure KMS, Translation, Vertex AI, and Secret Manager automatically. Review the output for any errors.</InstructionStep>
                                    </div>
                                </div>

                                {/* SMS Instructions */}
                                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
                                    <div className="flex items-center gap-2 mb-3">
                                        <MessageSquare className="w-4 h-4 text-emerald-400" />
                                        <h4 className="font-semibold text-white text-sm">SMS Notifications Setup</h4>
                                        {smsConfigured && <Badge variant="success">Done</Badge>}
                                    </div>
                                    <div className="space-y-2.5">
                                        <InstructionStep num={1}><strong className="text-white/90">Twilio (recommended):</strong> Create an account at <a href="https://www.twilio.com" target="_blank" rel="noopener noreferrer" className="text-emerald-300 underline underline-offset-2">twilio.com</a>. Note your <strong className="text-white/90">Account SID</strong> and <strong className="text-white/90">Auth Token</strong> from the Console Dashboard.</InstructionStep>
                                        <InstructionStep num={2}>Purchase a phone number under <strong className="text-white/90">Phone Numbers → Manage → Buy a number</strong>.</InstructionStep>
                                        <InstructionStep num={3}>Select "Twilio" in the SMS Notifications card below, enter your credentials, and save.</InstructionStep>
                                        <InstructionStep num={4}><strong className="text-white/90">Custom HTTP API:</strong> Alternatively, select "Custom HTTP API" and provide your endpoint URL. The platform sends a POST with <code className="bg-black/30 px-1 rounded text-emerald-300 text-xs">{`{ "to": "+1...", "message": "..." }`}</code>.</InstructionStep>
                                    </div>
                                </div>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
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
                                    <p className="text-gray-300 text-xs">Staff authentication with MFA</p>
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
                                        <label className="text-xs text-gray-300 block mb-1">{label}</label>
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
                            Callback: <code className="bg-white/10 px-1 rounded break-all">{window.location.origin}/api/auth/callback</code>
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
                                    <p className="text-gray-300 text-xs">Primary data storage</p>
                                </div>
                            </div>
                            <Badge variant="success">Auto-configured</Badge>
                        </div>
                        <p className="text-gray-300 text-sm">
                            Database connection is configured via <code className="bg-white/10 px-1 rounded break-all">DATABASE_URL</code> environment variable in docker-compose.yml.
                        </p>
                        <div className="mt-4 flex items-center gap-2 text-green-400 text-sm">
                            <CheckCircle className="w-4 h-4" />
                            Connected and operational
                        </div>
                    </Card>
                </div>
            </div>

            {/* Social Login Configuration */}
            {auth0Configured && (
                <div>
                    <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Key className="w-5 h-5 text-purple-400" />
                        Social Login (Optional)
                    </h2>
                    <Card>
                        <SocialLoginConfig />
                    </Card>
                </div>
            )}

            {/* Optional Integrations - Premium Design */}
            <div>
                <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Cloud className="w-5 h-5 text-blue-400" />
                    Optional Integrations
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* SMS Notifications - Premium Card */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.1 }}
                        className={`relative rounded-2xl border backdrop-blur-xl p-6 transition-all duration-300 ${localSmsProvider && localSmsProvider !== 'none'
                            ? 'bg-gradient-to-br from-emerald-500/10 via-green-500/5 to-teal-500/10 border-emerald-500/30 shadow-lg shadow-emerald-500/10'
                            : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/[0.07]'
                            }`}
                    >

                        {/* Glow effect when configured */}
                        {localSmsProvider && localSmsProvider !== 'none' && (
                            <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/5 via-transparent to-teal-500/5 pointer-events-none" />
                        )}

                        <div className="relative">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-4">
                                    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-300 ${localSmsProvider && localSmsProvider !== 'none'
                                        ? 'bg-gradient-to-br from-emerald-400 to-teal-500 shadow-lg shadow-emerald-500/30'
                                        : 'bg-gradient-to-br from-slate-600/50 to-slate-700/50'
                                        }`}>
                                        <MessageSquare className="w-7 h-7 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-lg text-white">SMS Notifications</h3>
                                        <p className="text-white/50 text-sm">Text alerts to residents</p>
                                    </div>
                                </div>
                                {localSmsProvider && localSmsProvider !== 'none' ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border border-emerald-500/30 shadow-lg shadow-emerald-500/10">
                                        <CheckCircle className="w-3.5 h-3.5" />
                                        Active
                                    </span>
                                ) : (
                                    <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-white/10 text-white/50 border border-white/10">
                                        Disabled
                                    </span>
                                )}
                            </div>

                            {/* SMS Provider Selection */}
                            <div className="space-y-4">
                                <div>
                                    <label className="text-sm text-white/60 mb-2 block">Provider</label>
                                    <div className="flex gap-2">
                                        <Select
                                            options={[
                                                { value: 'none', label: 'Disabled' },
                                                { value: 'twilio', label: 'Twilio' },
                                                { value: 'http', label: 'Custom HTTP API' },
                                            ]}
                                            value={localSmsProvider}
                                            onChange={(e) => {
                                                userModifiedSms.current = true; // Mark as user-modified
                                                setLocalSmsProvider(e.target.value);
                                            }}
                                        />
                                        <Button
                                            size="sm"
                                            disabled={savingSmsProvider || localSmsProvider === (smsProviderFromSecrets || 'none')}
                                            onClick={async () => {
                                                setSavingSmsProvider(true);
                                                try {
                                                    await onSaveSecret('SMS_PROVIDER', localSmsProvider);

                                                    // Sync with modules if available
                                                    const wasEnabled = (smsProviderFromSecrets || 'none') !== 'none';
                                                    const isEnabled = localSmsProvider !== 'none';
                                                    if (modules && onUpdateModules && wasEnabled !== isEnabled) {
                                                        await onUpdateModules({ ...modules, sms_alerts: isEnabled });
                                                    }

                                                    userModifiedSms.current = false; // Reset flag after successful save
                                                } catch (err) {
                                                    console.error('Failed to save SMS provider:', err);
                                                }
                                                setSavingSmsProvider(false);
                                            }}
                                            className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 whitespace-nowrap"
                                        >
                                            {savingSmsProvider ? 'Saving...' : 'Save'}
                                        </Button>
                                    </div>
                                </div>


                                {/* Twilio Configuration Fields */}
                                {localSmsProvider === 'twilio' && (
                                    <div className="space-y-3 pt-2 border-t border-white/10">
                                        <div>
                                            <label className="text-sm text-white/60 mb-1.5 block">Account SID</label>
                                            <div className="flex gap-2">
                                                <Input
                                                    type="text"
                                                    placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                                                    value={secretValues['TWILIO_ACCOUNT_SID'] || ''}
                                                    onChange={(e) => setSecretValues(p => ({ ...p, 'TWILIO_ACCOUNT_SID': e.target.value }))}
                                                    className="flex-1 text-sm"
                                                />
                                            </div>
                                        </div>
                                        <div>
                                            <label className="text-sm text-white/60 mb-1.5 block">Auth Token</label>
                                            <Input
                                                type="password"
                                                placeholder="Your Twilio auth token"
                                                value={secretValues['TWILIO_AUTH_TOKEN'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'TWILIO_AUTH_TOKEN': e.target.value }))}
                                                className="text-sm"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-sm text-white/60 mb-1.5 block">From Phone Number</label>
                                            <Input
                                                type="text"
                                                placeholder="+1234567890"
                                                value={secretValues['TWILIO_PHONE_NUMBER'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'TWILIO_PHONE_NUMBER': e.target.value }))}
                                                className="text-sm"
                                            />
                                        </div>
                                        <Button
                                            size="sm"
                                            className="w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700"
                                            onClick={async () => {
                                                if (secretValues['TWILIO_ACCOUNT_SID']) await handleSave('TWILIO_ACCOUNT_SID');
                                                if (secretValues['TWILIO_AUTH_TOKEN']) await handleSave('TWILIO_AUTH_TOKEN');
                                                if (secretValues['TWILIO_PHONE_NUMBER']) await handleSave('TWILIO_PHONE_NUMBER');
                                            }}
                                            disabled={!secretValues['TWILIO_ACCOUNT_SID'] || savingKey !== null}

                                        >
                                            {savingKey ? 'Saving...' : 'Save Twilio Credentials'}
                                        </Button>
                                    </div>
                                )}

                                {/* Custom HTTP Configuration Fields */}
                                {localSmsProvider === 'http' && (
                                    <div className="space-y-3 pt-2 border-t border-white/10">
                                        <div>
                                            <label className="text-sm text-white/60 mb-1.5 block">API Endpoint URL</label>
                                            <Input
                                                type="text"
                                                placeholder="https://your-sms-api.com/send"
                                                value={secretValues['SMS_HTTP_ENDPOINT'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'SMS_HTTP_ENDPOINT': e.target.value }))}
                                                className="text-sm"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-sm text-white/60 mb-1.5 block">API Key (optional)</label>
                                            <Input
                                                type="password"
                                                placeholder="Your API key"
                                                value={secretValues['SMS_HTTP_API_KEY'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'SMS_HTTP_API_KEY': e.target.value }))}
                                                className="text-sm"
                                            />
                                        </div>
                                        <Button
                                            size="sm"
                                            className="w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700"
                                            onClick={async () => {
                                                if (secretValues['SMS_HTTP_ENDPOINT']) await handleSave('SMS_HTTP_ENDPOINT');
                                                if (secretValues['SMS_HTTP_API_KEY']) await handleSave('SMS_HTTP_API_KEY');
                                            }}
                                            disabled={!secretValues['SMS_HTTP_ENDPOINT'] || savingKey !== null}
                                        >
                                            {savingKey ? 'Saving...' : 'Save HTTP Settings'}
                                        </Button>
                                    </div>
                                )}

                                {/* Module sync indicator */}
                                {modules && (
                                    <div className={`flex items-center gap-2 text-xs ${modules.sms_alerts ? 'text-emerald-400' : 'text-white/40'}`}>
                                        {modules.sms_alerts ? (
                                            <>
                                                <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                                                Module enabled in Feature Settings
                                            </>
                                        ) : (
                                            <>
                                                <div className="w-2 h-2 rounded-full bg-white/30" />
                                                Module disabled in Feature Settings
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </motion.div>


                    {/* Email SMTP - Premium Card */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.2 }}
                        className={`relative overflow-hidden rounded-2xl border backdrop-blur-xl p-6 transition-all duration-300 ${smtpConfigured
                            ? 'bg-gradient-to-br from-violet-500/10 via-purple-500/5 to-fuchsia-500/10 border-violet-500/30 shadow-lg shadow-violet-500/10'
                            : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/[0.07]'
                            }`}
                    >
                        {smtpConfigured && (
                            <div className="absolute inset-0 bg-gradient-to-r from-violet-500/5 via-transparent to-fuchsia-500/5 pointer-events-none" />
                        )}

                        <div className="relative">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-4">
                                    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-300 ${smtpConfigured
                                        ? 'bg-gradient-to-br from-violet-400 to-purple-500 shadow-lg shadow-violet-500/30'
                                        : 'bg-gradient-to-br from-slate-600/50 to-slate-700/50'
                                        }`}>
                                        <Mail className="w-7 h-7 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-lg text-white">Email (SMTP)</h3>
                                        <p className="text-white/50 text-sm">Outgoing notifications</p>
                                    </div>
                                </div>
                                {smtpConfigured ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-violet-500/20 to-purple-500/20 text-violet-300 border border-violet-500/30 shadow-lg shadow-violet-500/10">
                                        <CheckCircle className="w-3.5 h-3.5" />
                                        Configured
                                    </span>
                                ) : (
                                    <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                        <AlertCircle className="w-3.5 h-3.5 mr-1" />
                                        Setup Required
                                    </span>
                                )}
                            </div>

                            {!smtpConfigured || secretValues['SMTP_HOST'] !== undefined ? (
                                <div className="space-y-3">
                                    <div className="flex gap-2">
                                        <Input
                                            type="text"
                                            placeholder="SMTP Host (e.g., smtp.gmail.com)"
                                            value={secretValues['SMTP_HOST'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'SMTP_HOST': e.target.value }))}
                                            className="flex-1 text-sm"
                                        />
                                        <Input
                                            type="text"
                                            placeholder="Port"
                                            value={secretValues['SMTP_PORT'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'SMTP_PORT': e.target.value }))}
                                            className="w-20 text-sm"
                                        />
                                    </div>
                                    <Input
                                        type="text"
                                        placeholder="From Email Address"
                                        value={secretValues['SMTP_FROM_EMAIL'] || ''}
                                        onChange={(e) => setSecretValues(p => ({ ...p, 'SMTP_FROM_EMAIL': e.target.value }))}
                                        className="text-sm"
                                    />
                                    <div className="flex gap-2">
                                        <Input
                                            type="text"
                                            placeholder="Username"
                                            value={secretValues['SMTP_USERNAME'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'SMTP_USERNAME': e.target.value }))}
                                            className="flex-1 text-sm"
                                        />
                                        <Input
                                            type="password"
                                            placeholder="Password"
                                            value={secretValues['SMTP_PASSWORD'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'SMTP_PASSWORD': e.target.value }))}
                                            className="flex-1 text-sm"
                                        />
                                    </div>
                                    <Button
                                        size="sm"
                                        className="w-full bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700"
                                        onClick={async () => {
                                            if (secretValues['SMTP_HOST']) await handleSave('SMTP_HOST');
                                            if (secretValues['SMTP_PORT']) await handleSave('SMTP_PORT');
                                            if (secretValues['SMTP_FROM_EMAIL']) await handleSave('SMTP_FROM_EMAIL');
                                            if (secretValues['SMTP_USERNAME']) await handleSave('SMTP_USERNAME');
                                            if (secretValues['SMTP_PASSWORD']) await handleSave('SMTP_PASSWORD');

                                            // Auto-enable email module when SMTP is configured
                                            if (modules && onUpdateModules && secretValues['SMTP_HOST']) {
                                                await onUpdateModules({ ...modules, email_notifications: true });
                                            }
                                        }}
                                        disabled={!secretValues['SMTP_HOST'] || savingKey !== null}
                                    >
                                        {savingKey ? 'Saving...' : 'Save SMTP Settings'}
                                    </Button>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    <div className="flex items-center gap-2">
                                        <div className="flex-1 h-10 rounded-xl bg-violet-500/20 border border-violet-500/30 flex items-center px-4">
                                            <CheckCircle className="w-4 h-4 text-violet-400 mr-2" />
                                            <span className="text-violet-200 text-sm">SMTP configured and ready</span>
                                        </div>
                                        <Button size="sm" variant="ghost" onClick={() => setSecretValues(p => ({ ...p, 'SMTP_HOST': '' }))}>
                                            Change
                                        </Button>
                                    </div>

                                    {/* Module sync indicator */}
                                    {modules && (
                                        <div className={`flex items-center gap-2 text-xs ${modules.email_notifications ? 'text-violet-400' : 'text-white/40'}`}>
                                            {modules.email_notifications ? (
                                                <>
                                                    <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
                                                    Module enabled in Feature Settings
                                                </>
                                            ) : (
                                                <>
                                                    <div className="w-2 h-2 rounded-full bg-white/30" />
                                                    Module disabled in Feature Settings
                                                </>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </motion.div>

                    {/* Google Cloud - Premium Card */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.3 }}
                        className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-blue-500/10 via-cyan-500/5 to-sky-500/10 border-blue-500/20 backdrop-blur-xl p-6 hover:border-blue-500/40 transition-all duration-300"
                    >
                        <div className="absolute inset-0 bg-gradient-to-r from-blue-500/5 via-transparent to-cyan-500/5 pointer-events-none" />

                        <div className="relative">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-4">
                                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-400 to-cyan-500 shadow-lg shadow-blue-500/30 flex items-center justify-center">
                                        <Cloud className="w-7 h-7 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-lg text-white">Google Cloud</h3>
                                        <p className="text-white/50 text-sm">AI, KMS, Secrets, Translation</p>
                                    </div>
                                </div>
                            </div>
                            <p className="text-white/60 text-sm mb-3">
                                Configure Google Cloud for AI analysis, encryption, and translation.
                                See the <strong className="text-blue-300">Deployment Guide</strong> above for step-by-step instructions.
                            </p>
                            <div className="bg-black/30 rounded-lg p-3 text-xs font-mono text-green-400">
                                <span className="text-white/40"># Run on your server:</span><br />
                                ./scripts/setup_gcp.sh YOUR_PROJECT_ID
                            </div>
                        </div>
                    </motion.div>

                    {/* Sentry Error Tracking - Premium Card */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.4 }}
                        className={`relative overflow-hidden rounded-2xl border backdrop-blur-xl p-6 transition-all duration-300 ${sentryConfigured
                            ? 'bg-gradient-to-br from-rose-500/10 via-red-500/5 to-orange-500/10 border-rose-500/30 shadow-lg shadow-rose-500/10'
                            : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/[0.07]'
                            }`}
                    >
                        {sentryConfigured && (
                            <div className="absolute inset-0 bg-gradient-to-r from-rose-500/5 via-transparent to-orange-500/5 pointer-events-none" />
                        )}

                        <div className="relative">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-4">
                                    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-300 ${sentryConfigured
                                        ? 'bg-gradient-to-br from-rose-400 to-orange-500 shadow-lg shadow-rose-500/30'
                                        : 'bg-gradient-to-br from-slate-600/50 to-slate-700/50'
                                        }`}>
                                        <AlertTriangle className="w-7 h-7 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-lg text-white">Sentry</h3>
                                        <p className="text-white/50 text-sm">Error monitoring</p>
                                    </div>
                                </div>
                                {sentryConfigured ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/30 shadow-lg shadow-rose-500/10">
                                        <CheckCircle className="w-3.5 h-3.5" />
                                        Active
                                    </span>
                                ) : (
                                    <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-white/10 text-white/50 border border-white/10">
                                        Optional
                                    </span>
                                )}
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
                                        className="bg-gradient-to-r from-rose-500 to-orange-500 hover:from-rose-600 hover:to-orange-600"
                                        onClick={() => handleSave('SENTRY_DSN')}
                                        disabled={!secretValues['SENTRY_DSN'] || savingKey === 'SENTRY_DSN'}
                                    >
                                        Save
                                    </Button>
                                </div>
                            ) : (
                                <div className="flex items-center gap-2">
                                    <div className="flex-1 h-10 rounded-xl bg-rose-500/20 border border-rose-500/30 flex items-center px-4">
                                        <CheckCircle className="w-4 h-4 text-rose-400 mr-2" />
                                        <span className="text-rose-200 text-sm">Monitoring active</span>
                                    </div>
                                    <Button size="sm" variant="ghost" onClick={() => setSecretValues(p => ({ ...p, 'SENTRY_DSN': '' }))}>
                                        Change
                                    </Button>
                                </div>
                            )}
                        </div>
                    </motion.div>
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
                            <p className="text-gray-300 text-xs">For manual server configuration</p>
                        </div>
                    </div>
                    {showTerminal ? <ChevronUp className="w-5 h-5 text-gray-300" /> : <ChevronDown className="w-5 h-5 text-gray-300" />}
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
                        href="https://github.com/Pinpoint-311/Pinpoint-311/blob/main/docs/SETUP.md"
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
