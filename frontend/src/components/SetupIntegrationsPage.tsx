import { useState, useEffect, useRef } from 'react';

import { motion, AnimatePresence } from 'framer-motion';
import {
    Key, Shield, Cloud, MessageSquare, Mail, CheckCircle,
    AlertCircle, ChevronDown, ChevronUp, Copy, Check,
    ExternalLink, AlertTriangle, Database, BookOpen,
    ListChecks, HardDrive, MapPin,
    Sparkles, Languages, Lock, Image as ImageIcon, Landmark,
    Clock, DollarSign,
} from 'lucide-react';

import { Card, Button, Input, Badge, CollapsibleSection } from './ui';
import { SystemSecret } from '../types';
import { api } from '../services/api';
import type { Capability } from '../services/api';
import GovtechIntegrations from './GovtechIntegrations';
import ServiceProviders from './ServiceProviders';


interface ModulesState {
    ai_analysis: boolean;
    sms_alerts: boolean;
    email_notifications: boolean;
    research_portal: boolean;
    unlisted_reports: boolean;
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
    /* The guide starts open on a fresh install and closed once the required
     * integrations are in. It is a first-run document: hidden behind a click it
     * is missed by the person who needs it most, and left open forever it pushes
     * the actual controls off the screen for everyone else.
     *
     * null means "not decided yet" so the effect below can set it once the
     * config has loaded, without overriding a deliberate click afterwards. */
    const [expandedGuide, setExpandedGuide] = useState<string | null>(null);
    const guideAutoSet = useRef(false);
    const [saveMessage, setSaveMessage] = useState<string | null>(null);

    // Setup Instructions chooser: the guide shows ONLY the steps for the cloud
    // and optional features the admin actually wants to set up.
    const [setupCloud, setSetupCloud] = useState<'google' | 'azure' | 'aws'>('google');
    const [setupIdp, setSetupIdp] = useState<'auth0' | 'entra' | 'okta' | 'oidc'>('auth0');
    const [setupMaps, setSetupMaps] = useState<'google' | 'esri' | 'azure' | 'apple'>('google');
    /* Everything on, untick to hide.
     *
     * This started as opt-in with three ticked, which quietly set the default
     * for every town that never touched it: a page that asks what you want,
     * pre-answered "not much". A town that never opens this question should end
     * up with the whole platform switched on, not the three we happened to
     * pre-tick -- so the list below is every feature, and a town removes what
     * it genuinely does not want. */
    const ALL_FEATURES = ['ai', 'translation', 'moderation', 'email', 'sms', 'secrets', 'govtech', 'backups'];
    const [wantedFeatures, setWantedFeatures] = useState<Set<string>>(new Set(ALL_FEATURES));
    const toggleFeature = (f: string) =>
        setWantedFeatures(prev => {
            const next = new Set(prev);
            next.has(f) ? next.delete(f) : next.add(f);
            return next;
        });
    const wants = (f: string) => wantedFeatures.has(f);

    /* The setup questions are asked in feature terms ("AI triage", "Secret
     * storage + PII encryption") and the provider cards are keyed by
     * capability. This is the one mapping between them. `secrets` covers the
     * KMS card because the same question is what a town answers about where
     * keys and resident data are protected, and `moderation` covers photo
     * redaction for the same reason -- both are about screening what gets
     * stored. */
    const FEATURE_TO_CAPABILITY: Record<string, Capability> = {
        ai: 'ai', translation: 'translation', email: 'email',
        sms: 'sms', secrets: 'kms', moderation: 'redaction',
    };
    const wantedCapabilities = new Set<Capability>(
        Object.entries(FEATURE_TO_CAPABILITY)
            .filter(([feature]) => wantedFeatures.has(feature))
            .map(([, capability]) => capability),
    );

    /* What to do to obtain the credentials for a given provider, shown inside
     * the card immediately above the boxes.
     *
     * Short on purpose. The long guide above still exists for someone starting
     * from nothing; this is the reminder you want when you are already looking
     * at the field and have forgotten which console page the value is on. Keyed
     * by capability and provider so switching provider switches the reminder,
     * the same way the fields themselves switch.
     *
     * Returning null is normal -- a provider that needs no explanation beyond
     * its field labels should not be given filler. */
    const cardInstructions = (cap: Capability, provider: string): React.ReactNode => {
        const K: Record<string, React.ReactNode> = {
            'ai:vertex': <>Enable <strong className="text-white/85">Vertex AI API</strong> in Google Cloud, then use the project ID and service-account JSON from the Google Cloud step above.</>,
            'ai:azure': <>Create an <strong className="text-white/85">Azure OpenAI</strong> resource and deploy a vision-capable model. The deployment name is what goes in the third box, not the model name.</>,
            'ai:bedrock': <>In <strong className="text-white/85">Bedrock → Model access</strong>, enable the models you want first — a region alone is not enough if nothing is enabled in it.</>,
            'translation:google': <>Nothing new to fetch. Enable <strong className="text-white/85">Cloud Translation API</strong> and reuse the same project as AI.</>,
            'translation:azure': <>Create a <strong className="text-white/85">Translator</strong> resource; its Key and Region are on the resource's Keys and Endpoint page.</>,
            'translation:aws': <>No resource to create. Amazon Translate works with the region and credentials you already use.</>,
            'identity:auth0': <>Applications → your app → Settings. Add <code className="bg-black/30 px-1 rounded text-[11px]">{window.location.origin}/api/auth/callback</code> as an Allowed Callback URL first, or sign-in fails after the password.</>,
            'identity:entra': <>App registrations → your app. Overview holds both IDs; the secret <em>Value</em> (not the Secret ID) is under Certificates &amp; secrets and is shown only once.</>,
            'identity:okta': <>The Issuer is your Okta domain, e.g. <code className="bg-black/30 px-1 rounded text-[11px]">https://your-org.okta.com</code>. Assign the app to a staff group or nobody can sign in.</>,
            'identity:oidc': <>Enter the issuer itself. If your provider's docs show a URL ending <code className="bg-black/30 px-1 rounded text-[11px]">/.well-known/openid-configuration</code>, leave that part off.</>,
            'maps:google': <>Enable Maps JavaScript, Geocoding and Places, attach billing, then restrict the key to <code className="bg-black/30 px-1 rounded text-[11px]">{window.location.origin}/*</code>. Without billing the key looks fine and the map stays grey.</>,
            'maps:esri': <>An API key from ArcGIS Location Platform. Check whether your county's licence already covers you before buying one.</>,
            'maps:azure': <>Azure Maps account → Authentication → Primary Key.</>,
            'maps:apple': <>Needs a paid Apple Developer account. Paste the whole <code className="bg-black/30 px-1 rounded text-[11px]">.p8</code> file including its BEGIN and END lines.</>,
            'email:smtp': <>Your existing mail server. For Microsoft 365 or Google Workspace this needs an <strong className="text-white/85">app password</strong>, not the account password.</>,
            'email:ses': <>SES refuses to send from an address or domain you have not verified in its console first.</>,
            'email:acs': <>The endpoint and key are on the Communication Services resource, under Keys.</>,
            'sms:none': <>Nothing to enter. Residents still get email updates.</>,
            'sms:twilio': <>Account SID and Auth Token are on the Twilio console home page. The number must be one you own there, in <code className="bg-black/30 px-1 rounded text-[11px]">+1XXXXXXXXXX</code> form.</>,
            'sms:sns': <>Uses your existing AWS credentials. New AWS accounts are sandboxed for SMS — request production access or only verified numbers receive anything.</>,
            'sms:acs': <>The same Communication Services resource as email, plus a number provisioned in it.</>,
            'sms:http': <>For a gateway not listed here. Not certified against any particular vendor, so send a test before relying on it.</>,
            'kms:google': <>Enable <strong className="text-white/85">Cloud KMS API</strong>. The three boxes only name the key inside your project; leave them blank for the defaults.</>,
            'kms:azure': <>Key Vault URL and key name, plus an app registration that can wrap and unwrap with it.</>,
            'kms:aws': <>A KMS key ID or ARN in the same region as the rest of your AWS setup.</>,
            'kms:local': <>Nothing to enter. Resident data is still encrypted, using the application's own key rather than a cloud key service.</>,
            'redaction:local': <>Nothing to enter — detection runs here and no photo leaves the building. Less accurate than the cloud detectors.</>,
        };
        const cloud = K[`${cap}:${provider}`];
        if (cloud) return cloud;
        if (cap === 'redaction') {
            return <>No new credentials — this reuses the {provider === 'google' ? 'Google Cloud' : provider === 'aws' ? 'AWS' : 'Azure'} keys you entered above. Both toggles are on by default; plate detection guesses, and what it occasionally blurs is a house number.</>;
        }
        return null;
    };

    // Managed (state-hosted) mode: infrastructure cards are locked because the
    // state's orchestrator owns those keys (Google Cloud, Backups, domain).
    const [managedMode, setManagedMode] = useState(false);
    useEffect(() => {
        fetch('/api/system/config')
            .then(r => (r.ok ? r.json() : null))
            .then(cfg => setManagedMode(!!cfg?.managed_mode))
            .catch(() => setManagedMode(false));
    }, []);



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


    // Check configuration status
    // Staff sign-in is required; Auth0 specifically is not. Identity is a
    // pluggable capability with four providers (Auth0, Entra, Okta, and generic
    // OIDC for anything else), so the checklist asks whether ANY of them is
    // configured. Naming one vendor as "required" was both wrong and exactly
    // the kind of lock-in framing this platform exists to avoid.
    const signInConfigured =
        (isConfigured('AUTH0_DOMAIN') && isConfigured('AUTH0_CLIENT_ID') && isConfigured('AUTH0_CLIENT_SECRET'))
        || (isConfigured('ENTRA_TENANT_ID') && isConfigured('ENTRA_CLIENT_ID') && isConfigured('ENTRA_CLIENT_SECRET'))
        || (isConfigured('OKTA_ISSUER') && isConfigured('OKTA_CLIENT_ID') && isConfigured('OKTA_CLIENT_SECRET'))
        || (isConfigured('OIDC_ISSUER') && isConfigured('OIDC_CLIENT_ID') && isConfigured('OIDC_CLIENT_SECRET'));
    const smsProviderFromSecrets = secrets.find(s => s.key_name === 'SMS_PROVIDER')?.key_value;
    // Email is provider-pluggable too (EMAIL_PROVIDER = smtp | ses | acs), so
    // checking only the SMTP pair marked a town running SES or Azure
    // Communication Services as unconfigured. Same bug as sign-in and maps.
    const smtpConfigured =
        (isConfigured('SMTP_HOST') && isConfigured('SMTP_FROM_EMAIL'))
        || (isConfigured('AWS_REGION') && (isConfigured('SES_FROM_EMAIL') || isConfigured('SMTP_FROM_EMAIL')))
        || (isConfigured('ACS_ENDPOINT') && isConfigured('ACS_ACCESS_KEY'));

    const sentryConfigured = isConfigured('SENTRY_DSN');
    const gcpConfigured = isConfigured('GOOGLE_CLOUD_PROJECT');
    // Same trap as sign-in: maps is a pluggable capability with four providers,
    // so checking only Google's key left a town running Esri or Apple showing
    // "map provider: not configured" forever.
    const mapsConfigured =
        isConfigured('GOOGLE_MAPS_API_KEY')
        || isConfigured('ARCGIS_API_KEY')
        || isConfigured('AZURE_MAPS_KEY')
        || (isConfigured('APPLE_MAPKIT_TEAM_ID') && isConfigured('APPLE_MAPKIT_KEY_ID')
            && isConfigured('APPLE_MAPKIT_PRIVATE_KEY'));
    // Read straight from the stored provider: the Text Messages card writes it,
    // and 'none' is a real value there rather than an absence.
    const smsConfigured = !!(smsProviderFromSecrets && smsProviderFromSecrets !== 'none');
    const backupConfigured = isConfigured('BACKUP_S3_BUCKET') && isConfigured('BACKUP_S3_ACCESS_KEY') && isConfigured('BACKUP_S3_SECRET_KEY') && isConfigured('BACKUP_ENCRYPTION_KEY');
    // The capabilities that gained a card. Each is "done" when any one of its
    // providers has the credentials that provider needs, so a town on Azure is
    // not marked incomplete for having no Google key.
    const aiConfigured = isConfigured('VERTEX_AI_PROJECT') || isConfigured('AZURE_OPENAI_API_KEY') || isConfigured('AWS_REGION');
    const translationConfigured = isConfigured('GOOGLE_CLOUD_PROJECT') || isConfigured('AZURE_TRANSLATOR_KEY') || isConfigured('AWS_REGION');
    const kmsConfigured = isConfigured('KMS_KEY_ID') || isConfigured('AZURE_KEYVAULT_URL') || isConfigured('AWS_KMS_KEY_ID');
    // Redaction needs no credentials of its own -- it reuses the cloud ones --
    // so it counts as set up once a detector has been chosen.
    const redactionConfigured = isConfigured('REDACTION_PROVIDER');

    // Setup progress calculation. In managed mode the platform-managed steps
    // (Google Cloud, DB Backups) are excluded — the state handles them, so
    // counting them would leave progress permanently "incomplete".
    const setupSteps = [
        { label: 'Staff sign-in', done: !!signInConfigured, required: false },
        { label: 'Email', done: !!smtpConfigured, required: false },
        ...(managedMode ? [] : [{ label: 'Google Cloud', done: !!gcpConfigured, required: false }]),
        { label: 'Map provider', done: !!mapsConfigured, required: false },
        { label: 'SMS Alerts', done: smsConfigured, required: false },
        { label: 'AI triage', done: !!aiConfigured, required: false },
        { label: 'Translation', done: !!translationConfigured, required: false },
        { label: 'PII encryption', done: !!kmsConfigured, required: false },
        { label: 'Photo redaction', done: !!redactionConfigured, required: false },
        ...(managedMode ? [] : [{ label: 'DB Backups', done: !!backupConfigured, required: false }]),
    ];

    /* Required first, and counted separately.
     *
     * "5 of 6 configured" mixes two different questions: can this town take
     * reports at all, and how much of the optional surface is switched on. A
     * town with both required items done and nothing else is ready to go live,
     * and a bar reading 33% told it the opposite. The headline now answers the
     * first question and the count answers the second. */
    const completedCount = setupSteps.filter(s => s.done).length;

    useEffect(() => {
        // secrets arrives as a prop; an empty array means it has not loaded yet.
        if (guideAutoSet.current || secrets.length === 0) return;
        guideAutoSet.current = true;
        if (!signInConfigured || !mapsConfigured) setExpandedGuide('master');
    }, [secrets.length, signInConfigured, mapsConfigured]);

    // Toggle helper for collapsible instruction panels
    const toggleGuide = (id: string) => setExpandedGuide(prev => prev === id ? null : id);

    /* One numbered step.
     *
     * `check` is the important addition: the clerk following this has no way to
     * tell a step that worked from one that silently didn't, and finding out six
     * steps later means unpicking all six. Saying what they should be looking at
     * turns each step into its own checkpoint. */
    const InstructionStep = ({ num, check, children }: {
        num: number; check?: React.ReactNode; children: React.ReactNode;
    }) => (
        <div className="flex gap-3 items-start">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-white/10 text-white/70 text-xs font-bold flex items-center justify-center mt-0.5">{num}</span>
            <div className="text-sm text-white/70 leading-relaxed">
                {children}
                {check && (
                    <p className="mt-1.5 flex items-start gap-1.5 text-xs text-emerald-200/70">
                        <CheckCircle className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
                        <span><span className="font-semibold">You should see:</span> {check}</span>
                    </p>
                )}
            </div>
        </div>
    );

    /* "If it goes wrong" for a step, called out rather than buried in prose.
     *
     * Every one of these is a real failure someone hits, and the symptom is
     * usually indistinguishable from a bug in Pinpoint -- a grey map, a login
     * loop, silence instead of an email. Naming the symptom is what lets someone
     * search for their own problem. */
    const Trouble = ({ children }: { children: React.ReactNode }) => (
        <div className="ml-9 rounded-lg bg-amber-500/[0.07] border border-amber-400/20 px-3 py-2 flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 text-amber-300/80 mt-0.5 shrink-0" aria-hidden="true" />
            <p className="text-xs text-amber-100/75 leading-relaxed">{children}</p>
        </div>
    );

    /* A term worth glossing inline. Hovering is not discoverable, so the plain
     * meaning goes in parentheses right there in the sentence. */
    const Term = ({ children, means }: { children: React.ReactNode; means: string }) => (
        <span>
            <strong className="text-white/90">{children}</strong>
            <span className="text-white/45"> ({means})</span>
        </span>
    );

    // Static tone classes (kept literal so Tailwind doesn't purge them).
    const TONES: Record<string, { box: string; icon: string }> = {
        orange: { box: 'border-orange-500/20 bg-orange-500/5', icon: 'text-orange-400' },
        violet: { box: 'border-violet-500/20 bg-violet-500/5', icon: 'text-violet-400' },
        blue: { box: 'border-blue-500/20 bg-blue-500/5', icon: 'text-blue-400' },
        emerald: { box: 'border-emerald-500/20 bg-emerald-500/5', icon: 'text-emerald-400' },
        amber: { box: 'border-amber-500/20 bg-amber-500/5', icon: 'text-amber-400' },
        sky: { box: 'border-sky-500/20 bg-sky-500/5', icon: 'text-sky-400' },
        rose: { box: 'border-rose-500/20 bg-rose-500/5', icon: 'text-rose-400' },
        cyan: { box: 'border-cyan-500/20 bg-cyan-500/5', icon: 'text-cyan-400' },
    };
    /* A single guide block; renders nothing unless `show` is true.
     *
     * `what`, `time` and `cost` exist because the person doing this is usually a
     * clerk who was handed the job, not an engineer. Before a numbered list is
     * any use they need to know what they are about to sign the town up for:
     * what it actually does, roughly how long it takes, and whether it costs
     * money. Without that, "create a service account" is just alarming.
     *
     * `time` is honest-to-slow. Being told 10 minutes and taking 40 is worse
     * than being told 30.
     */
    const Guide = ({ show = true, tone, icon: Icon, title, done, what, time, cost, children }: {
        show?: boolean; tone: string; icon: React.ElementType; title: string;
        done?: boolean; what?: React.ReactNode; time?: string; cost?: string;
        children: React.ReactNode;
    }) => {
        if (!show) return null;
        const t = TONES[tone] || TONES.blue;
        return (
            <div className={`rounded-xl border p-4 ${t.box}`}>
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <Icon className={`w-4 h-4 ${t.icon}`} />
                    <h4 className="font-semibold text-white text-sm">{title}</h4>
                    {done && <Badge variant="success">Done</Badge>}
                </div>
                {what && <p className="text-xs text-white/55 leading-relaxed mb-2">{what}</p>}
                {/* Stacked and top-aligned. The cost note is often a sentence
                    rather than a figure -- the Google "you still need a card on
                    file" caveat especially -- and a wrapped second line running
                    back to the margin read as a separate item. */}
                {(time || cost) && (
                    <div className="flex flex-col gap-1 mb-3 text-[11px]">
                        {time && (
                            <span className="flex items-start gap-1.5 text-white/50">
                                <Clock className="w-3 h-3 shrink-0 mt-0.5" aria-hidden="true" />
                                <span>{time}</span>
                            </span>
                        )}
                        {cost && (
                            <span className="flex items-start gap-1.5 text-white/50">
                                <DollarSign className="w-3 h-3 shrink-0 mt-0.5" aria-hidden="true" />
                                <span>{cost}</span>
                            </span>
                        )}
                    </div>
                )}
                <div className="space-y-2.5">{children}</div>
            </div>
        );
    };

    const cloudLabel = { google: 'Google Cloud', azure: 'Microsoft Azure', aws: 'AWS' }[setupCloud];

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
                        <p className="text-white/50 text-xs">
                            {completedCount} of {setupSteps.length} integrations configured{' · '}
                            <span className="text-white/70 font-medium">{Math.round((completedCount / setupSteps.length) * 100)}%</span>
                            {completedCount < setupSteps.length && (
                                <span className="text-white/40">{' · '}{setupSteps.length - completedCount} left</span>
                            )}
                        </p>
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
                            <p className="text-white/50 text-xs">Step-by-step, in plain language — answer a few questions and see only your steps</p>
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
                            <div className="mt-4 space-y-5">
                                {/* ── Chooser: only show the steps you need ── */}
                                {/* A plain-language preface for the whole panel.
                                    Someone opening this is often a clerk who was
                                    handed the job. Two things settle most of the
                                    anxiety: only sign-in and maps are actually
                                    required, and nothing here has to be finished
                                    in one sitting. */}
                                <div className="rounded-xl border border-indigo-400/20 bg-indigo-500/[0.07] p-4">
                                    <p className="text-sm text-white/75 leading-relaxed">
                                        <strong className="text-white">You do not have to do all of this.</strong> Only two things are
                                        required to take reports: <strong className="text-white/90">staff sign-in</strong> and a{' '}
                                        <strong className="text-white/90">map</strong>. Everything else can be added later, in any order,
                                        and nothing breaks while it is switched off. Your progress is saved as you go, so it is fine to
                                        stop and come back.
                                    </p>
                                    <p className="text-xs text-white/50 leading-relaxed mt-2">
                                        Each step tells you what to look for so you know it worked. If a step mentions something
                                        unfamiliar, the plain meaning is in brackets right after it. Where a value has a copy button,
                                        use it rather than retyping.
                                    </p>
                                </div>

                                <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                                    <p className="text-sm font-semibold text-white mb-0.5">Answer a few questions and we will hide the rest</p>
                                    <p className="text-white/50 text-xs mb-3">Sign-in and maps are always shown — a town needs both before it can take a report.</p>

                                    <label className="text-[11px] uppercase tracking-wider text-white/50 font-semibold">1. Which company hosts your town's services?</label>
                                    <p className="text-white/40 text-[11px] mt-0.5 mb-1">Most towns pick Google. If your staff already use Microsoft 365, Microsoft Azure may be easier. If you genuinely do not know, choose Google — you can change this later.</p>
                                    <div className="flex flex-wrap gap-2 mt-1.5 mb-4">
                                        {(['google', 'azure', 'aws'] as const).map(c => (
                                            <button key={c} type="button" onClick={() => setSetupCloud(c)}
                                                className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${setupCloud === c ? 'bg-primary-500/20 border-primary-400/50 text-white' : 'bg-white/5 border-white/10 text-white/60 hover:text-white'}`}>
                                                {{ google: 'Google Cloud', azure: 'Microsoft Azure', aws: 'AWS' }[c]}
                                            </button>
                                        ))}
                                    </div>

                                    <label className="text-[11px] uppercase tracking-wider text-white/50 font-semibold">2. How will staff sign in?</label>
                                    <p className="text-white/40 text-[11px] mt-0.5 mb-1">If your staff already sign in to Microsoft 365, Entra is less work than standing up a new service. Auth0 is the fastest from nothing.</p>
                                    <div className="flex flex-wrap gap-2 mt-1.5 mb-4">
                                        {(['auth0', 'entra', 'okta', 'oidc'] as const).map(c => (
                                            <button key={c} type="button" onClick={() => setSetupIdp(c)}
                                                className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${setupIdp === c ? 'bg-primary-500/20 border-primary-400/50 text-white' : 'bg-white/5 border-white/10 text-white/60 hover:text-white'}`}>
                                                {{ auth0: 'Auth0', entra: 'Microsoft Entra ID', okta: 'Okta', oidc: 'Other (OIDC)' }[c]}
                                            </button>
                                        ))}
                                    </div>

                                    <label className="text-[11px] uppercase tracking-wider text-white/50 font-semibold">3. Which map provider?</label>
                                    <p className="text-white/40 text-[11px] mt-0.5 mb-1">Google is the quickest to set up. Pick Esri if your county already publishes an ArcGIS basemap you are entitled to use.</p>
                                    <div className="flex flex-wrap gap-2 mt-1.5 mb-4">
                                        {(['google', 'esri', 'azure', 'apple'] as const).map(c => (
                                            <button key={c} type="button" onClick={() => setSetupMaps(c)}
                                                className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${setupMaps === c ? 'bg-primary-500/20 border-primary-400/50 text-white' : 'bg-white/5 border-white/10 text-white/60 hover:text-white'}`}>
                                                {{ google: 'Google Maps', esri: 'Esri / ArcGIS', azure: 'Azure Maps', apple: 'Apple Maps' }[c]}
                                            </button>
                                        ))}
                                    </div>

                                    <label className="text-[11px] uppercase tracking-wider text-white/50 font-semibold">4. Which extras do you want? (all optional)</label>
                                    <p className="text-white/40 text-[11px] mt-0.5 mb-1">Tick anything that sounds useful — each one adds its own short guide below with what it does and what it costs. Untick it to hide the guide again.</p>
                                    <div className="flex flex-wrap gap-2 mt-1.5">
                                        {([
                                            ['ai', 'AI triage'], ['translation', 'Translation'],
                                            ['moderation', 'Content moderation'], ['email', 'Email'],
                                            ['sms', 'Text / SMS'], ['secrets', 'Secret storage + PII encryption'],
                                            ['govtech', 'Town-system connector'], ['backups', 'Database backups'],
                                        ] as const).map(([f, label]) => (
                                            <button key={f} type="button" onClick={() => toggleFeature(f)}
                                                className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${wants(f) ? 'bg-emerald-500/15 border-emerald-400/40 text-emerald-100' : 'bg-white/5 border-white/10 text-white/60 hover:text-white'}`}>
                                                {wants(f) ? '✓ ' : ''}{label}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                {/* ── 1. Staff sign-in (always required) ── */}
                                <Guide tone="orange" icon={Key} title="Staff sign-in" done={signInConfigured}
                                    what={<>Residents never sign in — this is only for the clerks and staff who work the reports. Rather than Pinpoint storing staff passwords itself, an outside sign-in service handles that, which is what lets you require two-factor and switch off an ex-employee in one place. The steps below follow whichever service you picked above.</>}
                                    time={setupIdp === 'auth0' ? "About 20 minutes, and you only ever do it once" : "About 10 minutes if you already administer it"}
                                    cost={setupIdp === 'auth0' ? "Auth0 is free up to 25,000 monthly logins — far more than a town's staff will use" : "Usually already covered by the licence your town has for it"}>
                                    {setupIdp === 'auth0' && <>
                                    <InstructionStep num={1}
                                        check={<>the Auth0 dashboard, with your town's name in the top-left corner.</>}
                                    >Make the account. Go to <a href="https://auth0.com" target="_blank" rel="noopener noreferrer" className="text-orange-300 underline underline-offset-2">auth0.com</a> and sign up with a <strong className="text-white/90">shared town email address</strong>, not your personal one — whoever replaces you will need to get in. When it asks for a <Term means="which part of the world your staff logins are stored in">region</Term>, pick the one closest to you. <strong className="text-white/90">This cannot be changed later</strong>, so if your town or state has a rule about keeping data in the US, choose a US region now.</InstructionStep>
                                    <InstructionStep num={2}
                                        check={<>a settings page with boxes labelled Domain, Client ID and Client Secret. Leave this tab open — you come back to it in step 5.</>}
                                    >Tell Auth0 about Pinpoint. In the left menu click <strong className="text-white/90">Applications</strong>, then <strong className="text-white/90">Applications</strong> again, then the <strong className="text-white/90">Create Application</strong> button. Name it <em className="text-white/60">"{`{township} 311`}"</em>. From the list of types choose <strong className="text-white/90">Regular Web Application</strong> — not Single Page, not Machine to Machine — and click Create. If it then asks you to pick a technology (React, Node, and so on), <strong className="text-white/90">ignore that and close it</strong>; it only shows sample code you do not need.</InstructionStep>
                                    <InstructionStep num={3}>Tell Auth0 where to send people back to. Still on the <strong className="text-white/90">Settings</strong> tab, scroll down to <strong className="text-white/90">Application URIs</strong>. Copy each value below into the matching box using the copy button — <strong className="text-white/90">do not retype them</strong>, a single missing character stops sign-in working:
                                        <div className="mt-2 space-y-1.5">
                                            <div className="flex items-center gap-2 flex-wrap"><span className="text-white/45 text-xs w-40 shrink-0">Allowed Callback URLs</span><code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}/api/auth/callback</code>
                                                <button onClick={() => copyToClipboard(`${window.location.origin}/api/auth/callback`, 'callback')} aria-label="Copy to clipboard" className="inline-flex text-white/40 hover:text-white/70 transition-colors">{copyFeedback === 'callback' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}</button></div>
                                            <div className="flex items-center gap-2 flex-wrap"><span className="text-white/45 text-xs w-40 shrink-0">Allowed Logout URLs</span><code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}</code>
                                                <button onClick={() => copyToClipboard(window.location.origin, 'logout')} aria-label="Copy to clipboard" className="inline-flex text-white/40 hover:text-white/70 transition-colors">{copyFeedback === 'logout' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}</button></div>
                                            <div className="flex items-center gap-2 flex-wrap"><span className="text-white/45 text-xs w-40 shrink-0">Allowed Web Origins</span><code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}</code>
                                                <button onClick={() => copyToClipboard(window.location.origin, 'weborigin')} aria-label="Copy to clipboard" className="inline-flex text-white/40 hover:text-white/70 transition-colors">{copyFeedback === 'weborigin' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}</button></div>
                                        </div>
                                        <span className="block mt-1.5 text-white/45 text-xs">Then scroll to the very bottom and click <strong className="text-white/70">Save Changes</strong> — it is easy to miss, and nothing you typed is kept until you do.</span>
                                    </InstructionStep>
                                    <Trouble>If sign-in later bounces you straight back to the login page, or you see <em>"Callback URL mismatch"</em>, it is almost always this step: the address in Auth0 has to match your site exactly, including <code className="bg-black/30 px-1 rounded">https://</code> and with no trailing slash.</Trouble>
                                    <InstructionStep num={4}
                                        check={<>"Always" selected under Define Policies, and at least one factor switched on.</>}
                                    >Require a second step at login. This is the single most valuable thing on this page: it means a stolen or guessed staff password is not enough on its own to get into resident records. Go to <strong className="text-white/90">Security → Multi-factor Auth</strong>, turn on <strong className="text-white/90">One-Time Password</strong> (a code from an app like Google Authenticator) or <strong className="text-white/90">Passkeys</strong> if your staff have newer phones. Then under <strong className="text-white/90">Define Policies</strong> choose <strong className="text-white/90">Always</strong>. Warn staff first — the next time they sign in they will be asked to set this up.</InstructionStep>
                                    <InstructionStep num={5}
                                        check={<>a green tick and "connection OK" on the card. If you get amber text instead, it tells you which value it could not use.</>}
                                    >Copy the three values into Pinpoint. Back on that Auth0 <strong className="text-white/90">Settings</strong> tab there are three boxes: <strong className="text-white/90">Domain</strong>, <strong className="text-white/90">Client ID</strong> and <strong className="text-white/90">Client Secret</strong> (you will need to click "reveal" to see the secret). Copy each one into the box with the same name on the <strong className="text-white/90">Staff Sign-In</strong> card, in <strong className="text-white/90">Service Providers</strong> at the bottom of this page. Then press <strong className="text-white/90">Save &amp; Test</strong>, which stores them and immediately checks they work.</InstructionStep>
                                    <Trouble>Copy and paste rather than retyping, and do not worry about accidentally grabbing a space at either end — Pinpoint trims those for you. The Client Secret is shown only as dots until you reveal it; a half-copied secret is the most common reason this step fails.</Trouble>
                                    <InstructionStep num={6}
                                        check={<>their name in Pinpoint's User Management list after they have signed in once.</>}
                                    >Add your first staff member. In Auth0 go to <strong className="text-white/90">User Management → Users → Create User</strong> and add them with their work email. <strong className="text-white/90">They have to sign in to Pinpoint once before you can give them a role</strong> — signing in is what creates their record here. After that, open <strong className="text-white/90">User Management</strong> in Pinpoint, set them to Admin or Staff, and choose their department.</InstructionStep>
                                    <InstructionStep num={7}>
                                        <strong className="text-white/90">The shortcut, if it applies to you.</strong> Does your town already sign in to Microsoft 365 / Office 365, or to Okta? Then you do not need Auth0 at all — skip steps 1 to 4, and on the <strong className="text-white/90">Staff Sign-In</strong> card choose <strong className="text-white/90">Microsoft Entra ID</strong> (that is what Microsoft 365 sign-in is called) or <strong className="text-white/90">Okta</strong>. Your IT provider can give you the three values it asks for. This is usually less work, and staff get to use the password they already have. The web addresses in step 3 are the same whichever you choose.
                                    </InstructionStep>
                                    </>}
                                    {setupIdp === 'entra' && <>
                                        <InstructionStep num={1} check={<>the app listed under App registrations, with a Directory (tenant) ID and Application (client) ID on its Overview page.</>}>In the <strong className="text-white/90">Microsoft Entra admin centre</strong>, go to <strong className="text-white/90">App registrations → New registration</strong>. Name it <em className="text-white/60">"{`{township} 311`}"</em>, and for supported account types choose the option limited to your own organisation.</InstructionStep>
                                        <InstructionStep num={2}>Set the redirect URI. Platform <strong className="text-white/90">Web</strong>, and paste exactly: <code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}/api/auth/callback</code>
                                            <button onClick={() => copyToClipboard(`${window.location.origin}/api/auth/callback`, 'entracb')} aria-label="Copy to clipboard" className="ml-1 inline-flex text-white/40 hover:text-white/70 transition-colors">{copyFeedback === 'entracb' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}</button></InstructionStep>
                                        <InstructionStep num={3} check={<>the secret <strong className="text-white/80">Value</strong> — not the Secret ID. It is shown once and cannot be retrieved later.</>}>Under <strong className="text-white/90">Certificates &amp; secrets → New client secret</strong>, create one and copy its Value immediately.</InstructionStep>
                                        <InstructionStep num={4}>Paste into <strong className="text-white/90">Service Providers → Staff Sign-In → Microsoft Entra ID</strong>: the <strong className="text-white/90">Directory (tenant) ID</strong>, <strong className="text-white/90">Application (client) ID</strong> and the secret Value. <span className="text-white/45">Government tenants also set the Authority host to <code className="bg-black/30 px-1 rounded">login.microsoftonline.us</code>.</span> Then press Save &amp; Test.</InstructionStep>
                                    </>}
                                    {setupIdp === 'okta' && <>
                                        <InstructionStep num={1} check={<>a Client ID and Client secret on the app's General tab.</>}>In the Okta admin console, <strong className="text-white/90">Applications → Create App Integration</strong>. Choose <strong className="text-white/90">OIDC — OpenID Connect</strong> and <strong className="text-white/90">Web Application</strong>.</InstructionStep>
                                        <InstructionStep num={2}>Set the sign-in redirect URI to <code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}/api/auth/callback</code>
                                            <button onClick={() => copyToClipboard(`${window.location.origin}/api/auth/callback`, 'oktacb')} aria-label="Copy to clipboard" className="ml-1 inline-flex text-white/40 hover:text-white/70 transition-colors">{copyFeedback === 'oktacb' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}</button> and the sign-out URI to <code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}</code>. Assign the app to the staff group who should get in.</InstructionStep>
                                        <InstructionStep num={3}>Paste into <strong className="text-white/90">Service Providers → Staff Sign-In → Okta</strong>: the <strong className="text-white/90">Issuer URL</strong> (your Okta domain, e.g. <code className="bg-black/30 px-1 rounded">https://your-org.okta.com</code>), the Client ID and the Client Secret. Then Save &amp; Test.</InstructionStep>
                                    </>}
                                    {setupIdp === 'oidc' && <>
                                        <InstructionStep num={1}>Any provider speaking OpenID Connect works. In its admin console register a <strong className="text-white/90">confidential web application</strong> (one that can hold a secret), with the redirect URI <code className="bg-black/30 px-1.5 py-0.5 rounded text-orange-300 text-xs break-all">{window.location.origin}/api/auth/callback</code>
                                            <button onClick={() => copyToClipboard(`${window.location.origin}/api/auth/callback`, 'oidccb')} aria-label="Copy to clipboard" className="ml-1 inline-flex text-white/40 hover:text-white/70 transition-colors">{copyFeedback === 'oidccb' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}</button></InstructionStep>
                                        <InstructionStep num={2}>Paste the <strong className="text-white/90">Issuer URL</strong>, Client ID and Client Secret into <strong className="text-white/90">Service Providers → Staff Sign-In → Generic OIDC</strong>, then Save &amp; Test.</InstructionStep>
                                        <Trouble>Enter the issuer itself, not the discovery document. If the docs show a URL ending in <code className="bg-black/30 px-1 rounded">/.well-known/openid-configuration</code>, drop that part — Pinpoint appends it. Pasting the full discovery URL is the single most common mistake here, and the field will warn you about it.</Trouble>
                                    </>}
                                </Guide>

                                {/* ── 2. Cloud foundation (only if a cloud-backed feature is wanted) ── */}
                                <Guide show={wants('ai') || wants('translation') || wants('secrets') || wants('moderation')}
                                    tone="blue" icon={Cloud} title={`Set up ${cloudLabel} (foundation)`}>
                                    <p className="text-xs text-white/45 -mt-1 mb-1">Do this once. Every {cloudLabel} feature you picked reuses this same project + credentials, so you won't repeat it per feature.</p>
                                    {setupCloud === 'google' && <>
                                        <InstructionStep num={1}>Create the project. At <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">console.cloud.google.com</a>, click the project dropdown (top bar) → <strong className="text-white/90">New Project</strong>, name it, and create. Copy the <strong className="text-white/90">Project ID</strong> (not the display name — it looks like <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">my-town-311-4821</code>).</InstructionStep>
                                        <InstructionStep num={2}>Enable billing. <strong className="text-white/90">Billing → Link a billing account</strong>. Required even though most usage stays in the free tier — without it the APIs return 403.</InstructionStep>
                                        <InstructionStep num={3}>Enable the APIs. Go to <strong className="text-white/90">APIs &amp; Services → Library</strong> and enable each of: {wants('ai') && <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Vertex AI API</code>}{wants('translation') && <> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud Translation API</code></>}{wants('secrets') && <> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud KMS API</code> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Secret Manager API</code></>}{wants('moderation') && <> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud Vision API</code> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Cloud Natural Language API</code></>}. Search each by name and click <strong className="text-white/90">Enable</strong> (a minute each).</InstructionStep>
                                        <InstructionStep num={4} check={<>pinpoint311 listed on the Service Accounts page.</>}>Create a <Term means="a login for the software rather than for a person, so nothing is tied to your personal account">service account</Term>. Go to <strong className="text-white/90">IAM &amp; Admin → Service Accounts → Create Service Account</strong>, name it <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311</code>, and click Create &amp; Continue.</InstructionStep>
                                        <InstructionStep num={5}>Grant roles for what you picked, then Done:
                                            <ul className="mt-1.5 space-y-1 list-disc list-inside text-white/55 text-xs">
                                                {wants('ai') && <li><code className="bg-black/30 px-1 rounded text-blue-300">Vertex AI User</code></li>}
                                                {wants('translation') && <li><code className="bg-black/30 px-1 rounded text-blue-300">Cloud Translation API User</code></li>}
                                                {wants('secrets') && <li><code className="bg-black/30 px-1 rounded text-blue-300">Cloud KMS CryptoKey Encrypter/Decrypter</code> + <code className="bg-black/30 px-1 rounded text-blue-300">Secret Manager Admin</code></li>}
                                                {wants('moderation') && <li><code className="bg-black/30 px-1 rounded text-blue-300">Cloud Vision API User</code> (Natural Language needs no extra role)</li>}
                                            </ul>
                                        </InstructionStep>
                                        <InstructionStep num={6} check={<>a file ending in <code className="bg-black/30 px-1 rounded">.json</code> in your Downloads folder.</>}>Download its key file. Open the service account you just made, then <strong className="text-white/90">Keys → Add Key → Create new key → JSON</strong>. A file downloads automatically. This single file is what you paste or upload into the cards further down the page.<br /><strong className="text-white/90">Google will not let you download it again.</strong> Save a copy somewhere your town controls — a shared drive, not just your laptop — and do not email it.</InstructionStep>
                                    </>}
                                    {setupCloud === 'azure' && <>
                                        <InstructionStep num={1}>Create a resource group. In the <a href="https://portal.azure.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">Azure Portal</a> search <strong className="text-white/90">Resource groups → Create</strong>, name it <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311-rg</code>, and pick a region (a US-Gov region if your jurisdiction requires it). Everything below goes in this group.</InstructionStep>
                                        <InstructionStep num={2}>Note your <strong className="text-white/90">Subscription</strong> and <strong className="text-white/90">Tenant ID</strong> (Subscriptions / Microsoft Entra ID → Overview) — some resources ask for them.</InstructionStep>
                                        <InstructionStep num={3}>You'll create one resource per feature you picked in the guides below ({wants('ai') && 'Azure OpenAI'}{wants('translation') && ', Translator'}{wants('secrets') && ', Key Vault'}{wants('moderation') && ', AI Content Safety'}). Each gives you an <strong className="text-white/90">Endpoint</strong> + <strong className="text-white/90">Key</strong> under its <strong className="text-white/90">Keys and Endpoint</strong> blade that you paste into the matching provider card. Create them in <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311-rg</code> so they're easy to find and bill together.</InstructionStep>
                                    </>}
                                    {setupCloud === 'aws' && <>
                                        <InstructionStep num={1}>Pick a region. In the <a href="https://console.aws.amazon.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">AWS Console</a> choose a <strong className="text-white/90">Region</strong> (top-right; e.g. <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">us-east-1</code>, or <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">us-gov-west-1</code> for GovCloud). Use the same region everywhere below.</InstructionStep>
                                        <InstructionStep num={2}>Create an IAM identity. <strong className="text-white/90">IAM → Users → Create user</strong> (or a role if Pinpoint runs on EC2/ECS — a role avoids long-lived keys). Name it <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311</code>.</InstructionStep>
                                        <InstructionStep num={3}>Attach permissions for what you picked: {wants('ai') && <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">bedrock:InvokeModel</code>}{wants('translation') && <> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">translate:TranslateText</code></>}{wants('secrets') && <> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">secretsmanager:*</code> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">kms:Encrypt/Decrypt</code></>}{wants('moderation') && <> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">rekognition:DetectModerationLabels</code> <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">comprehend:DetectToxicContent</code></>}. Scope to specific resources for production.</InstructionStep>
                                        <InstructionStep num={4}>If you used a user, create an <strong className="text-white/90">access key</strong> (Security credentials → Create access key → Application running outside AWS). Save the <strong className="text-white/90">Access key ID</strong> + <strong className="text-white/90">Secret access key</strong> — you'll enter them plus the region in the provider cards.</InstructionStep>
                                    </>}
                                    <p className="text-xs text-white/50 leading-relaxed pl-9"><em>Tip:</em> after entering credentials in any provider card, press <strong className="text-white/80">Save &amp; Test</strong> — Pinpoint makes a live call and shows a green check on success or the exact error (wrong role, API not enabled, bad region) so you can fix it before going live.</p>
                                </Guide>

                                {/* ── AI ── */}
                                <Guide show={wants('ai')} tone="sky" icon={Sparkles} title="AI triage"
                                    what={<>Reads each new report and suggests a priority and a department, so a clerk is confirming a guess rather than sorting from scratch. It never closes or assigns anything on its own — staff always decide.</>}
                                    time="About 10 minutes once your cloud account exists"
                                    cost="Pennies per report. A town filing 500 reports a month typically spends a few dollars.">
                                    {setupCloud === 'google' && <>
                                        <InstructionStep num={1}>With Vertex AI enabled above, open <strong className="text-white/90">Service Providers → AI Provider</strong>, pick <strong className="text-white/90">Google Vertex AI</strong>, and paste your Project ID + service-account JSON.</InstructionStep>
                                        <InstructionStep num={2}>Choose a model. Press <strong className="text-white/90">Refresh from provider</strong> to pull the current Gemini models live — no need to track model names by hand.</InstructionStep>
                                    </>}
                                    {setupCloud === 'azure' && <>
                                        <InstructionStep num={1}>Create an <strong className="text-white/90">Azure OpenAI</strong> resource, then <strong className="text-white/90">Deploy</strong> a vision-capable model (e.g. <code className="bg-black/30 px-1 rounded text-sky-300 text-xs">gpt-4o</code>). Note the deployment name.</InstructionStep>
                                        <InstructionStep num={2}>In <strong className="text-white/90">Service Providers → AI Provider</strong> pick <strong className="text-white/90">Azure</strong> and paste the <strong className="text-white/90">Endpoint</strong>, <strong className="text-white/90">API key</strong>, and <strong className="text-white/90">Deployment name</strong>. "Refresh from provider" lists your live deployments.</InstructionStep>
                                    </>}
                                    {setupCloud === 'aws' && <>
                                        <InstructionStep num={1}>In <strong className="text-white/90">Bedrock → Model access</strong>, enable the models you want (e.g. a Claude model). Vision-capable models also cover image moderation.</InstructionStep>
                                        <InstructionStep num={2}>In <strong className="text-white/90">Service Providers → AI Provider</strong> pick <strong className="text-white/90">AWS Bedrock</strong> and enter your region; credentials come from your AWS setup above.</InstructionStep>
                                    </>}
                                    <InstructionStep num={3}><em className="text-white/50">Optional:</em> AI is skippable — if it's off or unreachable, requests still submit and the triage panel shows the computed context (history, nearby, weather); only the AI summary is skipped.</InstructionStep>
                                </Guide>

                                {/* ── Translation ── */}
                                <Guide show={wants('translation')} tone="cyan" icon={Languages} title="Translation"
                                    what={<>Lets a resident file in their own language and read updates in it, while staff see everything in English. Useful in most New Jersey towns; if you are not sure you need it, you can turn it on later.</>}
                                    time="About 5 minutes once your cloud account exists"
                                    cost="Charged per character translated — usually a few dollars a month.">
                                    {setupCloud === 'google' && <InstructionStep num={1}>Cloud Translation is enabled in the foundation step. In <strong className="text-white/90">Service Providers → Translation</strong> pick <strong className="text-white/90">Google</strong> — it uses the same service account.</InstructionStep>}
                                    {setupCloud === 'azure' && <InstructionStep num={1}>Create a <strong className="text-white/90">Translator</strong> resource, copy its <strong className="text-white/90">Key</strong> + <strong className="text-white/90">Region</strong>, and enter them under <strong className="text-white/90">Service Providers → Translation → Azure</strong>.</InstructionStep>}
                                    {setupCloud === 'aws' && <InstructionStep num={1}>Amazon Translate needs no extra resource. In <strong className="text-white/90">Service Providers → Translation</strong> pick <strong className="text-white/90">AWS</strong>; it uses your region + credentials.</InstructionStep>}
                                </Guide>

                                {/* ── Secrets + PII encryption ── */}
                                <Guide show={wants('secrets')} tone="violet" icon={Lock} title="Secure storage for keys and resident data (recommended)"
                                    what={<>All the keys you are pasting in during setup have to live somewhere. By default they sit in Pinpoint's own database; with this turned on they live in your cloud's dedicated vault instead, and residents' names, phone numbers and emails are encrypted with a key only your town controls. This is the option to point at when someone asks how resident data is protected.</>}
                                    time="About 20 minutes"
                                    cost="Well under a dollar a month at a town's scale.">
                                    {setupCloud === 'google' && <>
                                        <InstructionStep num={1}>In <strong className="text-white/90">Security → Key Management</strong> create a key ring <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">pinpoint311-keyring</code> and a symmetric key <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">pii-encryption-key</code> (or your own names).</InstructionStep>
                                        <InstructionStep num={2}>Grant the service account <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">Cloud KMS CryptoKey Encrypter/Decrypter</code> and <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">Secret Manager Admin</code>, then fill the Google Cloud card below.</InstructionStep>
                                    </>}
                                    {setupCloud === 'azure' && <InstructionStep num={1}>Create an <strong className="text-white/90">Azure Key Vault</strong>. Pinpoint stores integration secrets and wraps the PII encryption key there — set <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">SECRETS_PROVIDER=azure</code> and the vault URL/credentials.</InstructionStep>}
                                    {setupCloud === 'aws' && <InstructionStep num={1}>Create a <strong className="text-white/90">KMS key</strong> and enable <strong className="text-white/90">Secrets Manager</strong>. Set <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">SECRETS_PROVIDER=aws</code>; the same AWS credentials cover both.</InstructionStep>}
                                    <InstructionStep num={2}>Once a vault is configured, integration credentials are stored <strong className="text-white/90">there</strong> (the app keeps only a reference), not in the app database. The connector card shows a "stored in your Secret Manager" badge.</InstructionStep>
                                </Guide>

                                {/* ── Email ── */}
                                <Guide show={wants('email')} tone="violet" icon={Mail} title="Email notifications" done={smtpConfigured}
                                    what={<>Sends the resident a confirmation when they file, and an update when staff change the status. Without it a resident has no way to know anything happened, which is the most common complaint about 311 systems.</>}
                                    time="About 15 minutes"
                                    cost="Free at a town's volume with most providers.">
                                    <InstructionStep num={1}><strong className="text-white/90">Any cloud — SMTP:</strong> use SendGrid, Gmail App Passwords, or your org relay. Host <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">smtp.sendgrid.net</code> / <code className="bg-black/30 px-1 rounded text-violet-300 text-xs">587</code>, then fill the <strong className="text-white/90">Email</strong> card in Service Providers, picking <strong className="text-white/90">SMTP</strong>.</InstructionStep>
                                    {setupCloud === 'azure' && <InstructionStep num={2}><strong className="text-white/90">Or native Azure:</strong> create an <strong className="text-white/90">Azure Communication Services</strong> resource, connect an email domain, and use its connection string (provider "acs").</InstructionStep>}
                                    {setupCloud === 'aws' && <InstructionStep num={2}><strong className="text-white/90">Or native AWS:</strong> verify a sender/domain in <strong className="text-white/90">Amazon SES</strong> and use SES (provider "ses") with your region + credentials.</InstructionStep>}
                                </Guide>

                                {/* ── SMS ── */}
                                <Guide show={wants('sms')} tone="emerald" icon={MessageSquare} title="Text message notifications" done={smsConfigured}
                                    what={<>The same updates as email, by text. Optional, and residents choose whether to give a mobile number.</>}
                                    time="About 20 minutes, plus a wait"
                                    cost="Roughly a cent per message. Note that US carriers now require you to register your town before you can send texts, which takes a few business days — start this early if you want it.">
                                    <InstructionStep num={1}><strong className="text-white/90">Any cloud — Twilio:</strong> create an account at <a href="https://www.twilio.com" target="_blank" rel="noopener noreferrer" className="text-emerald-300 underline underline-offset-2">twilio.com</a>, buy a number, and enter the SID/token/number in the SMS card.</InstructionStep>
                                    {setupCloud === 'azure' && <InstructionStep num={2}><strong className="text-white/90">Or native Azure:</strong> use <strong className="text-white/90">Azure Communication Services</strong> SMS (provider "acs") with a provisioned number.</InstructionStep>}
                                    {setupCloud === 'aws' && <InstructionStep num={2}><strong className="text-white/90">Or native AWS:</strong> use <strong className="text-white/90">Amazon SNS</strong> (provider "sns"); it uses your region + credentials.</InstructionStep>}
                                </Guide>

                                {/* ── Content moderation ── */}
                                <Guide show={wants('moderation')} tone="rose" icon={ImageIcon} title="Blocking abusive reports and photos"
                                    what={<>Anything a resident submits can end up on a public municipal website. Offensive language is always screened, with or without this; turning it on adds checking of photos too, and catches abuse a word list misses.</>}
                                    time="About 10 minutes once your cloud account exists"
                                    cost="Fractions of a cent per report.">
                                    <InstructionStep num={1}><strong className="text-white/90">Built in, no setup:</strong> resident text is always screened — explicit/abusive descriptions and comments are blocked at submission; mild profanity posts but is flagged for staff.</InstructionStep>
                                    {setupCloud === 'google' && <InstructionStep num={2}><strong className="text-white/90">Cloud layer (optional):</strong> enable the <code className="bg-black/30 px-1 rounded text-rose-300 text-xs">Vision</code> + <code className="bg-black/30 px-1 rounded text-rose-300 text-xs">Natural Language</code> APIs. No extra keys — it uses your service account for image (SafeSearch) + text moderation.</InstructionStep>}
                                    {setupCloud === 'azure' && <InstructionStep num={2}><strong className="text-white/90">Cloud layer (optional):</strong> create an <strong className="text-white/90">Azure AI Content Safety</strong> resource and set <code className="bg-black/30 px-1 rounded text-rose-300 text-xs">AZURE_CONTENT_SAFETY_ENDPOINT</code> + <code className="bg-black/30 px-1 rounded text-rose-300 text-xs">AZURE_CONTENT_SAFETY_KEY</code> for text + image screening.</InstructionStep>}
                                    {setupCloud === 'aws' && <InstructionStep num={2}><strong className="text-white/90">Cloud layer (optional):</strong> allow <code className="bg-black/30 px-1 rounded text-rose-300 text-xs">rekognition:DetectModerationLabels</code> (image) + <code className="bg-black/30 px-1 rounded text-rose-300 text-xs">comprehend:DetectToxicContent</code> (text) on your AWS credentials.</InstructionStep>}
                                    <InstructionStep num={3}>Set <code className="bg-black/30 px-1 rounded text-rose-300 text-xs">MODERATION_PROVIDER</code> to your cloud, or leave it to follow your AI cloud automatically. If the cloud layer is off, text still uses the built-in scan and images use the AI vision assessment.</InstructionStep>
                                </Guide>

                                {/* ── Maps (always) ── */}
                                <Guide tone="blue" icon={MapPin} title="Maps" done={mapsConfigured}
                                    what={<>Every town needs one. Without it a resident cannot search for their address or drop a pin, so reports arrive with no location. Any of the four providers works — the steps below follow the one you picked above.</>}
                                    time={setupMaps === 'google' ? "About 15 minutes" : "About 10 minutes"}
                                    cost={setupMaps === 'google'
                                        ? "Google gives $200 of free map use every month, far more than a town of any size will reach. You still have to put a card on file — Google will not turn the maps on without one."
                                        : setupMaps === 'esri' ? "Often already covered by a county or state ArcGIS agreement — check before buying."
                                        : setupMaps === 'apple' ? "Needs a paid Apple Developer account (about $99/year)."
                                        : "Pay-as-you-go, with a free tier that covers a town's volume."}>
                                    {setupMaps === 'google' && <>
                                    <InstructionStep num={1}
                                        check={<>a blue "API Enabled" banner on each of the three, and a billing account listed under Billing.</>}
                                    >Turn on the three map services. Go to <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">Google Cloud</a> and sign in with a <strong className="text-white/90">shared town account</strong>. If you already made a project in an earlier step, use that one. Go to <strong className="text-white/90">APIs &amp; Services → Library</strong>, search for each of these and click Enable on all three: <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Maps JavaScript API</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Geocoding API</code>, <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">Places API</code>. Then go to <strong className="text-white/90">Billing</strong> and attach a payment method.</InstructionStep>
                                    <Trouble>The payment method is not optional and it is the step people skip. Google will happily give you a key without it, the key will look correct, and the map will show a grey box saying <em>"this page can't load Google Maps correctly"</em> with no other explanation. If you see that grey box, check Billing first.</Trouble>
                                    <InstructionStep num={2}
                                        check={<>a long string starting with <code className="bg-black/30 px-1 rounded">AIza</code>. Copy it somewhere safe for a moment — you need it in step 4.</>}
                                    >Create the key. Go to <strong className="text-white/90">APIs &amp; Services → Credentials</strong>, click <strong className="text-white/90">Create Credentials</strong> at the top, and choose <strong className="text-white/90">API key</strong>.</InstructionStep>
                                    <InstructionStep num={3}
                                        check={<>your site listed under Website restrictions, and only the three services ticked under API restrictions.</>}
                                    >Lock the key to your own website. Do not skip this — an unrestricted key can be copied off your site and run up a bill on your town's card. Click the key you just made. Under <strong className="text-white/90">Application restrictions</strong> choose <strong className="text-white/90">Websites</strong>, click Add, and paste exactly this: <code className="bg-black/30 px-1.5 py-0.5 rounded text-blue-300 text-xs break-all">{window.location.origin}/*</code>
                                        <button onClick={() => copyToClipboard(`${window.location.origin}/*`, 'mapsref')} aria-label="Copy to clipboard" className="ml-1 inline-flex text-white/40 hover:text-white/70 transition-colors">{copyFeedback === 'mapsref' ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}</button> — the <code className="bg-black/30 px-1 rounded">/*</code> on the end matters. Then under <strong className="text-white/90">API restrictions</strong> choose <strong className="text-white/90">Restrict key</strong> and tick the same three services from step 1. Save.</InstructionStep>
                                    <InstructionStep num={4}
                                        check={<>the address box offering suggestions as you type, and a pin appearing when you click the map.</>}
                                    >Paste the key into Pinpoint and check it. Put it in the <strong className="text-white/90">Maps Provider</strong> card in <strong className="text-white/90">Service Providers</strong> at the bottom of this page, then press <strong className="text-white/90">Save &amp; Test</strong>. Now open the resident portal in another tab and try filing a test report. <span className="text-white/45">(The <strong className="text-white/70">Map ID</strong> box is optional — it only changes how the map looks. Leave it empty.)</span></InstructionStep>
                                    <Trouble>Changes to a Google key can take up to five minutes to take effect. If the map is still grey straight after saving, wait a few minutes and reload before changing anything else.</Trouble>
                                    </>}
                                    {setupMaps === 'esri' && <>
                                        <InstructionStep num={1} check={<>an API key listed in your ArcGIS developer dashboard.</>}>Sign in to <strong className="text-white/90">ArcGIS Location Platform</strong> with your organisation's account, and create an <strong className="text-white/90">API key</strong>. Scope it to the basemap and geocoding services you are entitled to use.</InstructionStep>
                                        <InstructionStep num={2}>Paste it into <strong className="text-white/90">Service Providers → Maps Provider → Esri / ArcGIS</strong> as the <strong className="text-white/90">ArcGIS API key</strong>, then Save &amp; Test. <span className="text-white/45">Basemap ID and Address locator URL are optional — set them only if your county publishes its own, which is the usual reason to choose Esri.</span></InstructionStep>
                                        <Trouble>Check with whoever administers your county or state ArcGIS agreement before buying anything. Many New Jersey towns are already covered by a county licence, and geocoding against the county's own locator is more accurate for local addresses than a national one.</Trouble>
                                    </>}
                                    {setupMaps === 'azure' && <>
                                        <InstructionStep num={1} check={<>two keys listed under Authentication; either one works.</>}>In the Azure portal create an <strong className="text-white/90">Azure Maps</strong> account, then open <strong className="text-white/90">Authentication</strong> and copy the <strong className="text-white/90">Primary Key</strong>.</InstructionStep>
                                        <InstructionStep num={2}>Paste it into <strong className="text-white/90">Service Providers → Maps Provider → Azure Maps</strong> as the <strong className="text-white/90">Subscription key</strong>, then Save &amp; Test.</InstructionStep>
                                    </>}
                                    {setupMaps === 'apple' && <>
                                        <InstructionStep num={1} check={<>a downloaded <code className="bg-black/30 px-1 rounded">.p8</code> file. It downloads once and cannot be downloaded again.</>}>This needs a paid <strong className="text-white/90">Apple Developer</strong> account. In the developer portal create a <strong className="text-white/90">MapKit JS</strong> key and download it.</InstructionStep>
                                        <InstructionStep num={2}>Collect three values: your <strong className="text-white/90">Team ID</strong> (membership details), the <strong className="text-white/90">Key ID</strong> shown next to the key, and the contents of the <code className="bg-black/30 px-1 rounded">.p8</code> file.</InstructionStep>
                                        <InstructionStep num={3}>Enter all three under <strong className="text-white/90">Service Providers → Maps Provider → Apple Maps</strong>, then Save &amp; Test.</InstructionStep>
                                        <Trouble>Paste the whole <code className="bg-black/30 px-1 rounded">.p8</code> file including the <code className="bg-black/30 px-1 rounded">-----BEGIN PRIVATE KEY-----</code> and <code className="bg-black/30 px-1 rounded">-----END PRIVATE KEY-----</code> lines. Pasting only the middle block is the usual mistake, and the field will tell you if you do.</Trouble>
                                    </>}
                                </Guide>

                                {/* ── GovTech connector ── */}
                                <Guide show={wants('govtech')} tone="amber" icon={Landmark} title="Connecting to a system the town already uses"
                                    what={<>If your town already runs permitting or work-order software, Pinpoint can push reports into it so staff are not working in two places. You will need someone with an administrator login to that system, and possibly a call to the vendor for an API key.</>}
                                    time="An hour or more, and usually a vendor email"
                                    cost="No cost from Pinpoint. Some vendors charge for API access.">
                                    <InstructionStep num={1}>Scroll to <strong className="text-white/90">Connect Your Other Town Systems</strong> below. Purpose-built connectors exist for <strong className="text-white/90">Accela</strong>, <strong className="text-white/90">Tyler</strong>, <strong className="text-white/90">CivicPlus/SeeClickFix</strong>, and any <strong className="text-white/90">Open311</strong> endpoint.</InstructionStep>
                                    <InstructionStep num={2}>For anything else (Cityworks, SDL, Edmunds, GovPilot, FastTrackGov, Polimorphic…) use <strong className="text-white/90">Other REST System</strong> and enter the base URL + key from your vendor's API docs.</InstructionStep>
                                    <InstructionStep num={3}>Each connector has a guided wizard and a <strong className="text-white/90">Check connection</strong> button — always run it (and a test report) before going live.</InstructionStep>
                                </Guide>

                                {/* ── Database backups ── */}
                                {/* ── Photo redaction ── */}
                                <Guide show={wants('moderation')} tone="rose" icon={ImageIcon} title="Blurring faces and licence plates" done={redactionConfigured}
                                    what={<>Residents photograph the pothole and the neighbour walking past it. This finds faces and plates before the photo is stored, so the municipal site never publishes them. It runs on the way in — the unblurred original is never saved.</>}
                                    time="About 2 minutes"
                                    cost={setupCloud === 'google' ? "Roughly a tenth of a cent per photo on Cloud Vision." : "A fraction of a cent per photo, or nothing at all on your own server."}>
                                    <InstructionStep num={1}>Open <strong className="text-white/90">Service Providers → Photo Redaction</strong> and pick a detector. The cloud ones reuse the credentials you already entered — there is no new key. <strong className="text-white/90">On this server</strong> needs no account at all and no photo leaves the building, at some cost in accuracy.</InstructionStep>
                                    <InstructionStep num={2} check={<>a face blurred in the photo on the request you just filed.</>}>Faces and plates are both on by default. Save, then file a test report with a photo of a person or a car and open it in the staff view.</InstructionStep>
                                    <Trouble>Plate detection guesses, and what it occasionally guesses wrong is a house number. If your crews work from those, switch <strong className="text-white/90">Blur licence plates</strong> off on the same card — faces stay on.</Trouble>
                                </Guide>

                                {/* ── Error reporting ── */}
                                <Guide tone="violet" icon={AlertTriangle} title="Knowing when something breaks" done={sentryConfigured}
                                    what={<>Without this, a page that crashes for a resident is something you hear about only if they phone. Browser crashes are already collected and shown under Browser errors in the admin console; this sends them somewhere off the server as well, so they survive a container restart.</>}
                                    time="About 5 minutes"
                                    cost="Sentry's free tier covers a town's volume comfortably.">
                                    <InstructionStep num={1} check={<>a DSN that looks like <code className="bg-black/30 px-1 rounded">https://…@…ingest.sentry.io/…</code></>}>Create a free account at <a href="https://sentry.io" target="_blank" rel="noopener noreferrer" className="text-violet-300 underline underline-offset-2">sentry.io</a>, make a project, and copy its <strong className="text-white/90">DSN</strong>.</InstructionStep>
                                    <InstructionStep num={2}>Paste it into the <strong className="text-white/90">Sentry</strong> card under Other settings, and save.</InstructionStep>
                                    <InstructionStep num={3}><em className="text-white/50">Optional:</em> this is genuinely skippable. Crashes are still recorded in the admin console without it — Sentry adds alerting and keeps the history longer.</InstructionStep>
                                </Guide>

                                <Guide show={wants('backups')} tone="amber" icon={HardDrive} title="Automatic backups" done={backupConfigured}
                                    what={<>Takes a nightly encrypted copy of everything and stores it off the server. Do this one. 311 reports are public records the town is legally required to keep, and a server can fail.</>}
                                    time="About 20 minutes"
                                    cost="A few dollars a month for storage.">
                                    <InstructionStep num={1}>Provision an <strong className="text-white/90">S3-compatible</strong> bucket (AWS S3, Oracle Object Storage, MinIO, …) with put/get/list/delete permissions and an access key.</InstructionStep>
                                    <InstructionStep num={2}>Choose a strong <strong className="text-white/90">AES-256 passphrase</strong> and store it safely — backups can't be restored without it.</InstructionStep>
                                    <InstructionStep num={3}>Enter the bucket, keys, encryption passphrase, and optional endpoint/region in the <strong className="text-white/90">Database Backups</strong> card below.</InstructionStep>
                                    <div className="mt-3 rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-2">
                                        <p className="text-amber-200/80 text-xs"><strong>⚠ Privacy note:</strong> Backups contain a full snapshot including resident PII. Retention deletes old backups, but PII anonymization only applies to the live database — not to existing backup files.</p>
                                    </div>
                                </Guide>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </Card>



            {/* Required Integrations */}
            {/* Order is the flow itself: the two required integrations live in
                Service Providers, so it goes first. Optional extras next. The
                town's own systems after that, because connecting one presumes
                the basics work. Database last -- it is read-only status set from
                DATABASE_URL, there is nothing to do there, and it used to sit
                open above everything that actually needed attention. */}

            {/* 1 — Required + core capabilities: sign-in, maps, AI, translation */}
            {/* Only the capabilities the town asked for. The question above is
                the single place that decides what this page shows, so answering
                it once removes the steps and the inputs together rather than
                leaving inputs for providers whose instructions are hidden. */}
            <div id="sec-providers">
                <ServiceProviders
                    show={wantedCapabilities}
                    instructions={cardInstructions}
                    extras={
                        <>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Google Cloud - Premium Card (locked in managed mode: the state owns these keys) */}
                            {managedMode ? (
                                <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-6">
                                    <div className="flex items-center gap-4 mb-2">
                                        <div className="w-14 h-14 rounded-2xl flex items-center justify-center bg-white/10">
                                            <Cloud className="w-7 h-7 text-white/50" />
                                        </div>
                                        <div>
                                            <h3 className="font-bold text-lg text-white/70">Google Cloud</h3>
                                            <p className="text-white/40 text-sm">AI, encryption &amp; translation infrastructure</p>
                                        </div>
                                        <span className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/10 text-white/60 border border-white/15">
                                            <Shield className="w-3.5 h-3.5" />
                                            Managed by your state
                                        </span>
                                    </div>
                                    <p className="text-white/50 text-sm">
                                        Cloud project, KMS encryption keys, and secrets storage are provisioned and maintained by your state hosting program. Nothing to configure here.
                                    </p>
                                </div>
                            ) : (
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.3 }}
                                className={`relative rounded-3xl border p-6 transition-all duration-300 ${gcpConfigured
                                    ? 'bg-gradient-to-br from-blue-500/10 via-cyan-500/5 to-sky-500/10 border-blue-500/30 shadow-lg shadow-blue-500/10'
                                    : 'setup-panel border-transparent'
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
                                                : 'setup-tile'
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
                                                        placeholder="pinpoint311-keyring"
                                                        value={secretValues['KMS_KEY_RING'] || ''}
                                                        onChange={(e) => setSecretValues(p => ({ ...p, 'KMS_KEY_RING': e.target.value }))}
                                                        className="text-xs"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="text-xs text-white/50 mb-1 block">KMS Key ID</label>
                                                    <Input
                                                        type="text"
                                                        placeholder="pii-encryption-key"
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
                                                KMS fields are optional — the platform defaults to <code className="bg-black/20 px-1 rounded">us-central1</code> / <code className="bg-black/20 px-1 rounded">pinpoint311-keyring</code> / <code className="bg-black/20 px-1 rounded">pii-encryption-key</code> if left blank. These must match your KMS key ring and key names exactly, or PII encryption silently falls back to local (Fernet) encryption.
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
                            )}


                            {/* Sentry Error Tracking - Premium Card */}
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.4 }}
                                className={`relative rounded-3xl border p-6 transition-all duration-300 ${sentryConfigured
                                    ? 'bg-gradient-to-br from-rose-500/10 via-red-500/5 to-orange-500/10 border-rose-500/30 shadow-lg shadow-rose-500/10'
                                    : 'setup-panel border-transparent'
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
                                                : 'setup-tile'
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

                            {/* Database Backups - Premium Card (locked in managed mode: the state owns backups) */}
                            {managedMode ? (
                                <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-6">
                                    <div className="flex items-center gap-4 mb-2">
                                        <div className="w-14 h-14 rounded-2xl flex items-center justify-center bg-white/10">
                                            <HardDrive className="w-7 h-7 text-white/50" />
                                        </div>
                                        <div>
                                            <h3 className="font-bold text-lg text-white/70">Database Backups</h3>
                                            <p className="text-white/40 text-sm">Encrypted off-site backups</p>
                                        </div>
                                        <span className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/10 text-white/60 border border-white/15">
                                            <Shield className="w-3.5 h-3.5" />
                                            Managed by your state
                                        </span>
                                    </div>
                                    <p className="text-white/50 text-sm">
                                        Automated encrypted backups run under your state hosting program's disaster-recovery plan. Nothing to configure here.
                                    </p>
                                </div>
                            ) : (
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.5 }}
                                className={`relative rounded-3xl border p-6 transition-all duration-300 ${backupConfigured
                                    ? 'bg-gradient-to-br from-amber-500/10 via-yellow-500/5 to-orange-500/10 border-amber-500/30 shadow-lg shadow-amber-500/10'
                                    : 'setup-panel border-transparent'
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
                                                : 'setup-tile'
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
                            )}
                        </div>
                        </>
                    }
                />
            </div>



            {/* 3 — The town's own systems */}
            <GovtechIntegrations />

            <CollapsibleSection id="sec-database" title="Database" icon={Database} subtitle="Read-only status. Configured by your host through DATABASE_URL, not on this page." defaultOpen={false}>
                <div className="grid grid-cols-1 gap-4">
                    {/* The Auth0 card that used to live here has been removed.
                        Sign-in is a pluggable capability with four providers
                        (Auth0, Entra, Okta, and generic OIDC for anything else),
                        and this card wrote the same three AUTH0_* secrets the
                        Staff Sign-In card already owns -- while implying Auth0
                        was the only option. The callback URL a town has to
                        register is in the Staff sign-in guide above, with a copy
                        button. */}

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

                    {/* The Google Maps card that used to live here has been
                        removed. Maps is a pluggable capability now, so this page
                        showed a second, Google-only copy of the same two fields
                        writing to the same two secrets -- with worse help text
                        than the provider catalog carries, and no way to pick
                        Esri, Apple or Azure. One place to configure a map. */}
                </div>
            </CollapsibleSection>

            {/* Optional Integrations */}
            {saveMessage && (
                <div className="rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-sm text-white/80">
                    {saveMessage}
                </div>
            )}


            {/* Help Link — dark surface (not the translucent glass-card, whose
                white veil dropped these blues below AA contrast) with light text. */}
            <div className="rounded-2xl border border-blue-400/30 bg-blue-950/50 p-5">
                <div className="flex flex-wrap items-center gap-3">
                    <AlertCircle className="w-5 h-5 text-blue-300 shrink-0" aria-hidden="true" />
                    <p className="text-blue-50 text-sm flex-1 min-w-0">
                        Need help? Check the <strong className="text-white">System Health</strong> tab to verify your integrations are working correctly.
                    </p>
                    <a
                        href="https://github.com/Pinpoint-311/Pinpoint-311/blob/main/docs/SETUP.md"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-200 text-sm font-medium hover:text-white hover:underline flex items-center gap-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 rounded"
                    >
                        Setup Docs <ExternalLink className="w-3 h-3" aria-hidden="true" />
                    </a>
                </div>
            </div>
        </div>
    );
}
