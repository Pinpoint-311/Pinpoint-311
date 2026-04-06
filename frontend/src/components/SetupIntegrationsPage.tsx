import { useState, useEffect, useRef } from 'react';

import { motion, AnimatePresence } from 'framer-motion';
import {
    Key, Shield, Cloud, MessageSquare, Mail, CheckCircle,
    AlertCircle, ChevronDown, ChevronUp, Copy, Check,
    ExternalLink, AlertTriangle, Database, BookOpen,
    ListChecks, HardDrive, MapPin
} from 'lucide-react';

import { Card, Button, Input, Select, Badge } from './ui';
import { SystemSecret } from '../types';


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
    const mapsConfigured = isConfigured('GOOGLE_MAPS_API_KEY');
    const smsConfigured = !!(localSmsProvider && localSmsProvider !== 'none');
    const backupConfigured = isConfigured('BACKUP_S3_BUCKET') && isConfigured('BACKUP_S3_ACCESS_KEY') && isConfigured('BACKUP_S3_SECRET_KEY') && isConfigured('BACKUP_ENCRYPTION_KEY');

    // Setup progress calculation
    const setupSteps = [
        { label: 'Auth0 SSO', done: !!auth0Configured, required: true },
        { label: 'Email (SMTP)', done: !!smtpConfigured, required: false },
        { label: 'Google Cloud', done: !!gcpConfigured, required: false },
        { label: 'Google Maps', done: !!mapsConfigured, required: false },
        { label: 'SMS Alerts', done: smsConfigured, required: false },
        { label: 'DB Backups', done: !!backupConfigured, required: false },
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
                                        <InstructionStep num={3}>Under the app's <strong className="text-white/90">Organizations</strong> tab, ensure <strong className="text-orange-300">"Require users to belong to an organization"</strong> is disabled.</InstructionStep>
                                        <InstructionStep num={4}>In the app's <strong className="text-white/90">Settings</strong> tab, copy the <strong className="text-white/90">Domain</strong>, <strong className="text-white/90">Client ID</strong>, and <strong className="text-white/90">Client Secret</strong> into the fields below.</InstructionStep>
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
                                        <InstructionStep num={1}>Go to <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">console.cloud.google.com</a> and create a new project (or select an existing one). Note the <strong className="text-white/90">Project ID</strong>.</InstructionStep>
                                        <InstructionStep num={2}>Go to <strong className="text-white/90">APIs & Services → Library</strong> and enable: <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud KMS API</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud Translation API</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Vertex AI API</code>, and <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Secret Manager API</code>.</InstructionStep>
                                        <InstructionStep num={3}>
                                            <strong className="text-white/90">Create a KMS Key Ring and Key:</strong> Go to <strong className="text-white/90">Security → Key Management</strong>. Click <strong className="text-white/90">Create Key Ring</strong>, name it (e.g. <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311</code>), select a location (e.g. <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">us-central1</code>). Then create a key inside the ring (e.g. <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pii-encryption</code>), purpose: <strong className="text-white/90">Symmetric encrypt/decrypt</strong>.
                                        </InstructionStep>
                                        <InstructionStep num={4}>
                                            <strong className="text-white/90">Create a Service Account:</strong> Go to <strong className="text-white/90">IAM & Admin → Service Accounts → Create</strong>. Grant it the roles: <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud KMS CryptoKey Encrypter/Decrypter</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud Translation API User</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Vertex AI User</code>, and <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Secret Manager Admin</code>.
                                        </InstructionStep>
                                        <InstructionStep num={5}>On the Service Account page, go to <strong className="text-white/90">Keys → Add Key → Create new key → JSON</strong>. Download the key file and keep it secure.</InstructionStep>
                                        <InstructionStep num={6}>Enter your <strong className="text-white/90">Project ID</strong>, <strong className="text-white/90">KMS Location</strong>, <strong className="text-white/90">Key Ring</strong>, and <strong className="text-white/90">Key ID</strong> in the Google Cloud card below and click <strong className="text-white/90">Save GCP Settings</strong>.</InstructionStep>
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

                                {/* Database Backup Instructions */}
                                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                                    <div className="flex items-center gap-2 mb-3">
                                        <HardDrive className="w-4 h-4 text-amber-400" />
                                        <h4 className="font-semibold text-white text-sm">Database Backup Setup</h4>
                                        {backupConfigured && <Badge variant="success">Done</Badge>}
                                    </div>
                                    <div className="space-y-2.5">
                                        <InstructionStep num={1}>You need an <strong className="text-white/90">S3-compatible object storage</strong> bucket. This can be <strong className="text-white/90">AWS S3</strong>, <strong className="text-white/90">Oracle Object Storage</strong>, <strong className="text-white/90">MinIO</strong>, or any S3-compatible provider.</InstructionStep>
                                        <InstructionStep num={2}><strong className="text-white/90">AWS S3:</strong> Create a bucket in the <a href="https://s3.console.aws.amazon.com" target="_blank" rel="noopener noreferrer" className="text-amber-300 underline underline-offset-2">AWS Console</a>. Create an IAM user with <code className="bg-black/30 px-1 rounded text-amber-300 text-xs">s3:PutObject</code>, <code className="bg-black/30 px-1 rounded text-amber-300 text-xs">s3:GetObject</code>, <code className="bg-black/30 px-1 rounded text-amber-300 text-xs">s3:ListBucket</code>, and <code className="bg-black/30 px-1 rounded text-amber-300 text-xs">s3:DeleteObject</code> permissions. Generate an access key.</InstructionStep>
                                        <InstructionStep num={3}><strong className="text-white/90">Oracle Object Storage:</strong> Create a bucket in your OCI tenancy. Generate a <em>Customer Secret Key</em> under your user settings — this provides S3-compatible access key and secret key. The endpoint is <code className="bg-black/30 px-1 rounded text-amber-300 text-xs">{`https://<namespace>.compat.objectstorage.<region>.oraclecloud.com`}</code>.</InstructionStep>
                                        <InstructionStep num={4}>Choose a strong <strong className="text-white/90">encryption passphrase</strong> for AES-256 backup encryption. Store this passphrase securely — without it, backups cannot be restored.</InstructionStep>
                                        <InstructionStep num={5}>Enter your S3 bucket name, access key, secret key, encryption key, and optionally the endpoint/region in the <strong className="text-white/90">Database Backups</strong> card below.</InstructionStep>
                                    </div>
                                    <div className="mt-3 rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-2">
                                        <p className="text-amber-200/80 text-xs"><strong>⚠ Privacy note:</strong> Backups contain a full database snapshot including resident PII. Old backups are deleted per the retention policy, but PII anonymization only applies to the live database — not to previously created backup files.</p>
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

                    {/* Google Maps - Required Card */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.15 }}
                        className={`relative overflow-hidden rounded-2xl border backdrop-blur-xl p-6 transition-all duration-300 col-span-full ${mapsConfigured
                            ? 'bg-gradient-to-br from-green-500/10 via-emerald-500/5 to-teal-500/10 border-green-500/30 shadow-lg shadow-green-500/10'
                            : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/[0.07]'
                            }`}
                    >
                        {mapsConfigured && (
                            <div className="absolute inset-0 bg-gradient-to-r from-green-500/5 via-transparent to-emerald-500/5 pointer-events-none" />
                        )}

                        <div className="relative">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-4">
                                    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-300 ${mapsConfigured
                                        ? 'bg-gradient-to-br from-green-400 to-emerald-500 shadow-lg shadow-green-500/30'
                                        : 'bg-gradient-to-br from-slate-600/50 to-slate-700/50'
                                        }`}>
                                        <MapPin className="w-7 h-7 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-lg text-white">Google Maps</h3>
                                        <p className="text-white/50 text-sm">Maps, geocoding, location picker</p>
                                    </div>
                                </div>
                                {mapsConfigured ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-green-500/20 to-emerald-500/20 text-green-300 border border-green-500/30 shadow-lg shadow-green-500/10">
                                        <CheckCircle className="w-3.5 h-3.5" />
                                        Configured
                                    </span>
                                ) : (
                                    <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                        Required
                                    </span>
                                )}
                            </div>

                            <p className="text-white/60 text-sm mb-4">
                                Powers the interactive map in the resident portal, staff dashboard, and location-based request submission.
                            </p>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {/* Google Maps API Key */}
                                <div>
                                    <label className="text-sm text-white/60 mb-1.5 block flex items-center gap-2">
                                        Google Maps API Key
                                        {isConfigured('GOOGLE_MAPS_API_KEY') && <CheckCircle className="w-3.5 h-3.5 text-green-400" />}
                                    </label>
                                    <div className="flex gap-2">
                                        <Input
                                            type="password"
                                            placeholder="AIzaSy..."
                                            value={secretValues['GOOGLE_MAPS_API_KEY'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'GOOGLE_MAPS_API_KEY': e.target.value }))}
                                            className="flex-1 text-sm"
                                        />
                                        <Button
                                            size="sm"
                                            className="bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-600 hover:to-emerald-700"
                                            onClick={() => handleSave('GOOGLE_MAPS_API_KEY')}
                                            disabled={!secretValues['GOOGLE_MAPS_API_KEY'] || savingKey === 'GOOGLE_MAPS_API_KEY'}
                                        >
                                            {savingKey === 'GOOGLE_MAPS_API_KEY' ? '...' : 'Save'}
                                        </Button>
                                    </div>
                                    <p className="text-white/30 text-xs mt-1">Restrict to Maps JS API &amp; Geocoding API only</p>
                                </div>

                                {/* Google Maps Map ID */}
                                <div>
                                    <label className="text-sm text-white/60 mb-1.5 block">Google Maps Map ID <span className="text-white/30">(optional)</span></label>
                                    <div className="flex gap-2">
                                        <Input
                                            type="text"
                                            placeholder="Map ID for custom styling"
                                            value={secretValues['GOOGLE_MAPS_MAP_ID'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'GOOGLE_MAPS_MAP_ID': e.target.value }))}
                                            className="flex-1 text-sm"
                                        />
                                        <Button
                                            size="sm"
                                            onClick={() => handleSave('GOOGLE_MAPS_MAP_ID')}
                                            disabled={!secretValues['GOOGLE_MAPS_MAP_ID'] || savingKey === 'GOOGLE_MAPS_MAP_ID'}
                                        >
                                            {savingKey === 'GOOGLE_MAPS_MAP_ID' ? '...' : 'Save'}
                                        </Button>
                                    </div>
                                    <p className="text-white/30 text-xs mt-1">Optional — for custom map styling</p>
                                </div>
                            </div>
                        </div>
                    </motion.div>
                </div>
            </div>



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
                        className={`relative overflow-hidden rounded-2xl border backdrop-blur-xl p-6 transition-all duration-300 ${gcpConfigured
                            ? 'bg-gradient-to-br from-blue-500/10 via-cyan-500/5 to-sky-500/10 border-blue-500/30 shadow-lg shadow-blue-500/10'
                            : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/[0.07]'
                            }`}
                    >
                        {gcpConfigured && (
                            <div className="absolute inset-0 bg-gradient-to-r from-blue-500/5 via-transparent to-cyan-500/5 pointer-events-none" />
                        )}

                        <div className="relative">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-4">
                                    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-300 ${gcpConfigured
                                        ? 'bg-gradient-to-br from-blue-400 to-cyan-500 shadow-lg shadow-blue-500/30'
                                        : 'bg-gradient-to-br from-slate-600/50 to-slate-700/50'
                                        }`}>
                                        <Cloud className="w-7 h-7 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-lg text-white">Google Cloud</h3>
                                        <p className="text-white/50 text-sm">AI, KMS, Secrets, Translation</p>
                                    </div>
                                </div>
                                {gcpConfigured ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-blue-500/20 to-cyan-500/20 text-blue-300 border border-blue-500/30 shadow-lg shadow-blue-500/10">
                                        <CheckCircle className="w-3.5 h-3.5" />
                                        Configured
                                    </span>
                                ) : (
                                    <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-white/10 text-white/50 border border-white/10">
                                        Optional
                                    </span>
                                )}
                            </div>

                            <p className="text-white/60 text-sm mb-4">
                                Enables AI analysis (Vertex AI), PII encryption (Cloud KMS), multi-language translation, and secure secrets storage.
                                See the <strong className="text-blue-300">Setup Instructions</strong> above for a full walkthrough.
                            </p>

                            {/* Manual configuration fields */}
                            {!gcpConfigured || secretValues['GOOGLE_CLOUD_PROJECT'] !== undefined ? (
                                <div className="space-y-3">
                                    <div>
                                        <label className="text-sm text-white/60 mb-1.5 block">GCP Project ID</label>
                                        <div className="flex gap-2">
                                            <Input
                                                type="text"
                                                placeholder="my-municipality-project"
                                                value={secretValues['GOOGLE_CLOUD_PROJECT'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'GOOGLE_CLOUD_PROJECT': e.target.value }))}
                                                className="flex-1 text-sm"
                                            />
                                            <Button
                                                size="sm"
                                                className="bg-gradient-to-r from-blue-500 to-cyan-600 hover:from-blue-600 hover:to-cyan-700"
                                                onClick={() => handleSave('GOOGLE_CLOUD_PROJECT')}
                                                disabled={!secretValues['GOOGLE_CLOUD_PROJECT'] || savingKey === 'GOOGLE_CLOUD_PROJECT'}
                                            >
                                                {savingKey === 'GOOGLE_CLOUD_PROJECT' ? '...' : 'Save'}
                                            </Button>
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-3 gap-2">
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">KMS Location</label>
                                            <Input
                                                type="text"
                                                placeholder="us-central1"
                                                value={secretValues['KMS_LOCATION'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'KMS_LOCATION': e.target.value }))}
                                                className="text-xs"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">KMS Key Ring</label>
                                            <Input
                                                type="text"
                                                placeholder="pinpoint311"
                                                value={secretValues['KMS_KEY_RING'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'KMS_KEY_RING': e.target.value }))}
                                                className="text-xs"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">KMS Key ID</label>
                                            <Input
                                                type="text"
                                                placeholder="pii-encryption"
                                                value={secretValues['KMS_KEY_ID'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'KMS_KEY_ID': e.target.value }))}
                                                className="text-xs"
                                            />
                                        </div>
                                    </div>

                                    <Button
                                        size="sm"
                                        className="w-full bg-gradient-to-r from-blue-500 to-cyan-600 hover:from-blue-600 hover:to-cyan-700"
                                        onClick={async () => {
                                            if (secretValues['GOOGLE_CLOUD_PROJECT']) await handleSave('GOOGLE_CLOUD_PROJECT');
                                            if (secretValues['KMS_LOCATION']) await handleSave('KMS_LOCATION');
                                            if (secretValues['KMS_KEY_RING']) await handleSave('KMS_KEY_RING');
                                            if (secretValues['KMS_KEY_ID']) await handleSave('KMS_KEY_ID');

                                            // Auto-enable AI module when GCP is configured
                                            if (modules && onUpdateModules && secretValues['GOOGLE_CLOUD_PROJECT']) {
                                                await onUpdateModules({ ...modules, ai_analysis: true });
                                            }
                                        }}
                                        disabled={!secretValues['GOOGLE_CLOUD_PROJECT'] || savingKey !== null}
                                    >
                                        {savingKey ? 'Saving...' : 'Save GCP Settings'}
                                    </Button>

                                    <p className="text-white/40 text-xs">
                                        KMS fields are optional — the platform defaults to <code className="bg-black/20 px-1 rounded">us-central1</code> / <code className="bg-black/20 px-1 rounded">pinpoint311</code> / <code className="bg-black/20 px-1 rounded">pii-encryption</code> if left blank.
                                    </p>

                                    {/* Divider */}
                                    <div className="border-t border-white/10 my-4" />

                                    {/* GCP Service Account JSON */}
                                    <div>
                                        <label className="text-sm text-white/60 mb-1.5 block flex items-center gap-2">
                                            <Key className="w-4 h-4 text-amber-400" />
                                            GCP Service Account JSON
                                            {isConfigured('GCP_SERVICE_ACCOUNT_JSON') && <CheckCircle className="w-3.5 h-3.5 text-green-400" />}
                                        </label>
                                        <textarea
                                            placeholder='{"type": "service_account", "project_id": "...", ...}'
                                            value={secretValues['GCP_SERVICE_ACCOUNT_JSON'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'GCP_SERVICE_ACCOUNT_JSON': e.target.value }))}
                                            rows={4}
                                            className="w-full text-sm bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 resize-none font-mono"
                                        />
                                        <div className="flex gap-2 mt-2">
                                            <label className="flex-1 cursor-pointer">
                                                <div className="h-9 rounded-lg border border-dashed border-white/20 flex items-center justify-center text-white/40 text-xs hover:border-white/40 transition-colors">
                                                    📁 Or drop / select a .json key file
                                                </div>
                                                <input
                                                    type="file"
                                                    accept=".json"
                                                    className="hidden"
                                                    onChange={(e) => {
                                                        const file = e.target.files?.[0];
                                                        if (file) {
                                                            const reader = new FileReader();
                                                            reader.onload = (ev) => {
                                                                setSecretValues(p => ({ ...p, 'GCP_SERVICE_ACCOUNT_JSON': ev.target?.result as string || '' }));
                                                            };
                                                            reader.readAsText(file);
                                                        }
                                                    }}
                                                />
                                            </label>
                                            <Button
                                                size="sm"
                                                className="bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700"
                                                onClick={() => handleSave('GCP_SERVICE_ACCOUNT_JSON')}
                                                disabled={!secretValues['GCP_SERVICE_ACCOUNT_JSON'] || savingKey === 'GCP_SERVICE_ACCOUNT_JSON'}
                                            >
                                                {savingKey === 'GCP_SERVICE_ACCOUNT_JSON' ? 'Saving...' : 'Save Key'}
                                            </Button>
                                        </div>
                                        <p className="text-white/30 text-xs mt-1">Required for Vertex AI analysis, multi-language translation, and secure secrets storage</p>
                                    </div>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    <div className="flex items-center gap-2">
                                        <div className="flex-1 h-10 rounded-xl bg-blue-500/20 border border-blue-500/30 flex items-center px-4">
                                            <CheckCircle className="w-4 h-4 text-blue-400 mr-2" />
                                            <span className="text-blue-200 text-sm">GCP configured and ready</span>
                                        </div>
                                        <Button size="sm" variant="ghost" onClick={() => setSecretValues(p => ({ ...p, 'GOOGLE_CLOUD_PROJECT': '' }))}>
                                            Change
                                        </Button>
                                    </div>

                                    {/* Module sync indicator */}
                                    {modules && (
                                        <div className={`flex items-center gap-2 text-xs ${modules.ai_analysis ? 'text-blue-400' : 'text-white/40'}`}>
                                            {modules.ai_analysis ? (
                                                <>
                                                    <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                                                    AI Analysis module enabled
                                                </>
                                            ) : (
                                                <>
                                                    <div className="w-2 h-2 rounded-full bg-white/30" />
                                                    AI Analysis module disabled
                                                </>
                                            )}
                                        </div>
                                    )}

                                    {/* Migrate Secrets to GCP */}
                                    <div className="border-t border-white/10 pt-3 mt-3">
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            className="w-full text-xs text-white/50 hover:text-white hover:bg-white/10"
                                            onClick={async () => {
                                                try {
                                                    setSaveMessage('Migrating secrets to GCP...');
                                                    const result = await api.migrateToSecretManager();
                                                    setSaveMessage(
                                                        `✅ Migrated: ${result.migrated} keys. Scrubbed from DB: ${result.scrubbed}.` +
                                                        (result.failed > 0 ? ` Failed: ${result.failed}` : '')
                                                    );
                                                } catch (err: any) {
                                                    setSaveMessage(`❌ ${err.message || 'Migration failed'}`);
                                                }
                                            }}
                                        >
                                            Vault Local Secrets to GCP Identity
                                        </Button>
                                        <p className="text-white/30 text-[10px] mt-1 text-center">
                                            Moves database-encrypted API keys into Secret Manager
                                        </p>
                                    </div>

                                    {/* Re-encrypt PII after KMS key rotation */}
                                    <div className="border-t border-white/10 pt-3 mt-1">
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            className="w-full text-xs text-white/50 hover:text-white hover:bg-white/10"
                                            onClick={async () => {
                                                try {
                                                    setSaveMessage('Re-encrypting PII data...');
                                                    const result = await api.reencryptPii();
                                                    setSaveMessage(
                                                        `✅ Done: ${result.reencrypted}/${result.total} rows re-encrypted` +
                                                        (result.migrated_from_fernet > 0 ? `, ${result.migrated_from_fernet} migrated from Fernet` : '') +
                                                        (result.errors > 0 ? `, ${result.errors} errors` : '')
                                                    );
                                                } catch (err: any) {
                                                    setSaveMessage(`❌ ${err.message || 'Re-encryption failed'}`);
                                                }
                                            }}
                                        >
                                            🔐 Re-encrypt All PII Data (after key rotation)
                                        </Button>
                                        <p className="text-white/30 text-[10px] mt-1 text-center">
                                            Migrates historical PII to the current primary KMS key version
                                        </p>
                                    </div>
                                </div>
                            )}
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

                    {/* Database Backups - Premium Card */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.5 }}
                        className={`relative overflow-hidden rounded-2xl border backdrop-blur-xl p-6 transition-all duration-300 ${backupConfigured
                            ? 'bg-gradient-to-br from-amber-500/10 via-yellow-500/5 to-orange-500/10 border-amber-500/30 shadow-lg shadow-amber-500/10'
                            : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/[0.07]'
                            }`}
                    >
                        {backupConfigured && (
                            <div className="absolute inset-0 bg-gradient-to-r from-amber-500/5 via-transparent to-orange-500/5 pointer-events-none" />
                        )}

                        <div className="relative">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-4">
                                    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-300 ${backupConfigured
                                        ? 'bg-gradient-to-br from-amber-400 to-orange-500 shadow-lg shadow-amber-500/30'
                                        : 'bg-gradient-to-br from-slate-600/50 to-slate-700/50'
                                        }`}>
                                        <HardDrive className="w-7 h-7 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-lg text-white">Database Backups</h3>
                                        <p className="text-white/50 text-sm">Encrypted S3-compatible storage</p>
                                    </div>
                                </div>
                                {backupConfigured ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border border-amber-500/30 shadow-lg shadow-amber-500/10">
                                        <CheckCircle className="w-3.5 h-3.5" />
                                        Configured
                                    </span>
                                ) : (
                                    <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-white/10 text-white/50 border border-white/10">
                                        Optional
                                    </span>
                                )}
                            </div>

                            <p className="text-white/60 text-sm mb-4">
                                Backups are encrypted with AES-256 and stored in your S3-compatible bucket. Backup cleanup follows your configured retention policy.
                                See the <strong className="text-amber-300">Setup Instructions</strong> above for provider-specific guidance.
                            </p>

                            {!backupConfigured || secretValues['BACKUP_S3_BUCKET'] !== undefined ? (
                                <div className="space-y-3">
                                    <div>
                                        <label className="text-sm text-white/60 mb-1.5 block">S3 Bucket Name</label>
                                        <div className="flex gap-2">
                                            <Input
                                                type="text"
                                                placeholder="my-backup-bucket"
                                                value={secretValues['BACKUP_S3_BUCKET'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'BACKUP_S3_BUCKET': e.target.value }))}
                                                className="flex-1 text-sm"
                                            />
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 gap-2">
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">Access Key</label>
                                            <Input
                                                type="text"
                                                placeholder="AKIA..."
                                                value={secretValues['BACKUP_S3_ACCESS_KEY'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'BACKUP_S3_ACCESS_KEY': e.target.value }))}
                                                className="text-sm"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">Secret Key</label>
                                            <Input
                                                type="password"
                                                placeholder="Your S3 secret key"
                                                value={secretValues['BACKUP_S3_SECRET_KEY'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'BACKUP_S3_SECRET_KEY': e.target.value }))}
                                                className="text-sm"
                                            />
                                        </div>
                                    </div>

                                    <div>
                                        <label className="text-sm text-white/60 mb-1.5 block">Encryption Passphrase</label>
                                        <Input
                                            type="password"
                                            placeholder="Strong passphrase for AES-256 encryption"
                                            value={secretValues['BACKUP_ENCRYPTION_KEY'] || ''}
                                            onChange={(e) => setSecretValues(p => ({ ...p, 'BACKUP_ENCRYPTION_KEY': e.target.value }))}
                                            className="text-sm"
                                        />
                                    </div>

                                    <div className="grid grid-cols-2 gap-2">
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">S3 Endpoint <span className="text-white/30">(optional)</span></label>
                                            <Input
                                                type="text"
                                                placeholder="https://... (non-AWS only)"
                                                value={secretValues['BACKUP_S3_ENDPOINT'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'BACKUP_S3_ENDPOINT': e.target.value }))}
                                                className="text-xs"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">Region <span className="text-white/30">(optional)</span></label>
                                            <Input
                                                type="text"
                                                placeholder="us-ashburn-1"
                                                value={secretValues['BACKUP_S3_REGION'] || ''}
                                                onChange={(e) => setSecretValues(p => ({ ...p, 'BACKUP_S3_REGION': e.target.value }))}
                                                className="text-xs"
                                            />
                                        </div>
                                    </div>

                                    <Button
                                        size="sm"
                                        className="w-full bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700"
                                        onClick={async () => {
                                            if (secretValues['BACKUP_S3_BUCKET']) await handleSave('BACKUP_S3_BUCKET');
                                            if (secretValues['BACKUP_S3_ACCESS_KEY']) await handleSave('BACKUP_S3_ACCESS_KEY');
                                            if (secretValues['BACKUP_S3_SECRET_KEY']) await handleSave('BACKUP_S3_SECRET_KEY');
                                            if (secretValues['BACKUP_ENCRYPTION_KEY']) await handleSave('BACKUP_ENCRYPTION_KEY');
                                            if (secretValues['BACKUP_S3_ENDPOINT']) await handleSave('BACKUP_S3_ENDPOINT');
                                            if (secretValues['BACKUP_S3_REGION']) await handleSave('BACKUP_S3_REGION');
                                        }}
                                        disabled={!secretValues['BACKUP_S3_BUCKET'] || !secretValues['BACKUP_ENCRYPTION_KEY'] || savingKey !== null}
                                    >
                                        {savingKey ? 'Saving...' : 'Save Backup Settings'}
                                    </Button>

                                    <p className="text-white/40 text-xs">
                                        Endpoint and Region are optional — only needed for non-AWS providers (Oracle, MinIO, etc.).
                                    </p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    <div className="flex items-center gap-2">
                                        <div className="flex-1 h-10 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center px-4">
                                            <CheckCircle className="w-4 h-4 text-amber-400 mr-2" />
                                            <span className="text-amber-200 text-sm">Backup storage configured</span>
                                        </div>
                                        <Button size="sm" variant="ghost" onClick={() => setSecretValues(p => ({ ...p, 'BACKUP_S3_BUCKET': '' }))}>
                                            Change
                                        </Button>
                                    </div>
                                </div>
                            )}
                        </div>
                    </motion.div>
                </div>
            </div>




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
