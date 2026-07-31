import { useState, useEffect, useRef, useCallback } from 'react';

import { motion, AnimatePresence } from 'framer-motion';
import {
    Key, Shield, CheckCircle, CircleDashed,
    AlertCircle, ChevronDown, ChevronUp,
    ExternalLink, AlertTriangle, Database, BookOpen,
    ListChecks, HardDrive, Bell,
} from 'lucide-react';

import { Card, Button, Input, Badge, CollapsibleSection } from './ui';
import { SystemSecret } from '../types';
import { api } from '../services/api';
import type { Capability, ProviderStatusMap } from '../services/api';
import GovtechIntegrations from './GovtechIntegrations';
import ServiceProviders from './ServiceProviders';
import SetupWizard from './SetupWizard';
import { buildPlan, summarise, nameList } from './setupPlan';
// Registers every provider's setup steps as a side effect, so the guide can
// render them inline rather than pointing at the cards that do.
import './setupStepsContent';
import StorageStatusLine from './StorageStatusLine';
import SecretField from './SecretField';
import { openStayInformed } from './StayInformed';


/* One question in the questionnaire.
 *
 * Declared at module scope, not inside the page's render. A component defined
 * during render is a fresh type every render, so React unmounts and remounts it
 * -- which, for anything holding state, silently discards what was typed.
 */
/* The optional features, as id-and-label pairs.
 *
 * One list rather than two. An id in the feature set with no chip is a feature
 * that cannot be switched off; a chip whose id is not in the set is a control
 * that does nothing when clicked. Both existed, so the set is now derived from
 * the chips and the pair cannot drift.
 */
const FEATURES = [
    ['ai', 'AI triage'],
    ['translation', 'Translation'],
    ['safety', 'Screening and blurring'],
    ['email', 'Email'],
    ['sms', 'Text messages'],
    ['secrets', 'Key management'],
    ['backups', 'Backups'],
    ['errors', 'Crash reporting'],
] as const;

const ALL_FEATURES: readonly string[] = FEATURES.map(([id]) => id);

function Ask({ n, label, hint, children }: {
    n: number; label: string; hint?: string; children: React.ReactNode;
}) {
    return (
        <div className="mb-4 last:mb-0">
            <p className="text-[11px] uppercase tracking-wider text-white/50 font-semibold">
                {n}. {label}
            </p>
            {hint && <p className="text-white/40 text-[11px] mt-0.5 mb-1.5">{hint}</p>}
            <div className="mt-1.5">{children}</div>
        </div>
    );
}

/** A row of mutually exclusive choices. */
function Options({ value, onChange, options }: {
    value: string;
    onChange: (v: string) => void;
    options: readonly (readonly [string, string])[];
}) {
    return (
        <div className="flex flex-wrap gap-2">
            {options.map(([id, label]) => (
                <button
                    key={id}
                    type="button"
                    onClick={() => onChange(id)}
                    aria-pressed={value === id}
                    className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${value === id
                        ? 'bg-primary-500/20 border-primary-400/50 text-white'
                        : 'bg-white/5 border-white/10 text-white/60 hover:text-white'}`}
                >
                    {label}
                </button>
            ))}
        </div>
    );
}

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


/* The boxes for the account credentials, directly under the steps that
 * produce them.
 *
 * These used to live in a "Google Cloud" card several thousand pixels down
 * the page, which made the walk above end on "that file is what you paste
 * into the boxes below" with no boxes below. A clerk following the guide
 * downloaded a credential file and hit a dead end -- the same handoff the
 * rest of this page had already been fixed for, missed because the phrase
 * was not one the test looked for.
 *
 * Google only, and not an oversight. Google needs one account-level
 * credential shared by AI, KMS, secrets and translation. Azure Key Vault
 * takes a vault URL and prefers a managed identity with nothing to type,
 * and AWS needs a region and can use the instance profile -- for both, the
 * per-service keys live on the capability itself. Inventing an "Azure
 * account" box to make the three look symmetrical would ask for something
 * that does not exist.
 */
function GoogleAccountFields({
secretValues, setSecretValues, handleSave, savingKey, isConfigured, modules, onUpdateModules,
}: {
secretValues: Record<string, string>;
setSecretValues: React.Dispatch<React.SetStateAction<Record<string, string>>>;
handleSave: (key: string) => Promise<void>;
savingKey: string | null;
isConfigured: (key: string) => boolean | undefined;
modules: any;
onUpdateModules?: (m: any) => Promise<void>;
}) {
    const jsonKey = 'GCP_SERVICE_ACCOUNT_JSON';
    const [showKms, setShowKms] = useState(false);
    const pending = ['GOOGLE_CLOUD_PROJECT', jsonKey, 'KMS_LOCATION', 'KMS_KEY_RING', 'KMS_KEY_ID']
        .filter(k => secretValues[k]);
    return (
        <div className="ml-9 mt-1 rounded-xl border border-white/10 bg-white/[0.03] p-3.5 space-y-3">
            <div>
                <label className="text-[11px] uppercase tracking-wider text-white/55 font-semibold flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5 text-amber-300/80" aria-hidden="true" />
                    The .json file you just downloaded
                    {isConfigured(jsonKey) && <span className="text-emerald-300/80 normal-case font-medium">· Saved</span>}
                </label>
                <label className="mt-1.5 block cursor-pointer">
                    <div className="h-10 rounded-lg border border-dashed border-white/20 flex items-center justify-center text-white/50 text-xs hover:border-white/40 hover:text-white/70 transition-colors">
                        Choose the file, or drop it here
                    </div>
                    <input
                        type="file"
                        accept=".json,application/json"
                        className="hidden"
                        onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (!file) return;
                            const reader = new FileReader();
                            reader.onload = (ev) => setSecretValues(p => ({
                                ...p, [jsonKey]: (ev.target?.result as string) || '',
                            }));
                            reader.readAsText(file);
                        }}
                    />
                </label>
                {secretValues[jsonKey] && (
                    <p className="text-[11px] text-emerald-200/80 mt-1.5">
                        File read. Press Save below to store it.
                    </p>
                )}
                {/* Pasting is still allowed -- some towns get the key by
                    email from whoever administers the project -- but the
                    file picker is first, because a downloaded file is what
                    step 4 actually leaves you holding. */}
                <textarea
                    placeholder="…or paste the contents"
                    value={secretValues[jsonKey] || ''}
                    onChange={(e) => setSecretValues(p => ({ ...p, [jsonKey]: e.target.value }))}
                    rows={2}
                    className="mt-2 w-full text-xs bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 focus:outline-none focus:border-primary-400/50 resize-none font-mono"
                />
            </div>

            <SecretField
                label="Project ID"
                value={secretValues['GOOGLE_CLOUD_PROJECT'] || ''}
                onChange={(v: string) => setSecretValues(p => ({ ...p, 'GOOGLE_CLOUD_PROJECT': v }))}
                savedHint={!!isConfigured('GOOGLE_CLOUD_PROJECT')}
                placeholder="my-town-311-4821"
                help="The short code from step 1, not the name you typed."
            />

            {/* Behind a disclosure because the defaults are right for
                almost everyone, and three boxes that should stay empty
                read as three more things to get wrong. */}
            <button
                type="button"
                onClick={() => setShowKms(v => !v)}
                className="text-[11px] text-white/55 hover:text-white/85 underline underline-offset-2"
            >
                {showKms ? 'Hide' : 'I was given different'} encryption key names
            </button>
            {showKms && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    {[
                        ['KMS_LOCATION', 'Location', 'us-central1'],
                        ['KMS_KEY_RING', 'Key ring', 'pinpoint311-keyring'],
                        ['KMS_KEY_ID', 'Key name', 'pii-encryption-key'],
                    ].map(([key, label, placeholder]) => (
                        <SecretField
                            key={key}
                            label={label}
                            value={secretValues[key] || ''}
                            onChange={(v: string) => setSecretValues(p => ({ ...p, [key]: v }))}
                            savedHint={!!isConfigured(key)}
                            placeholder={placeholder}
                            help={`Leave blank for ${placeholder}.`}
                        />
                    ))}
                </div>
            )}

            <div className="flex flex-wrap items-center gap-2.5 pt-1">
                <button
                    type="button"
                    onClick={async () => {
                        for (const k of pending) await handleSave(k);
                        // AI cannot run without this, so having entered it
                        // and left the module off is never what was meant.
                        if (modules && onUpdateModules && secretValues['GOOGLE_CLOUD_PROJECT'] && !modules.ai_analysis) {
                            await onUpdateModules({ ...modules, ai_analysis: true });
                        }
                    }}
                    disabled={pending.length === 0 || savingKey !== null}
                    className="inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold text-white bg-primary-500 hover:bg-primary-400 border border-primary-400/50 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                >
                    {savingKey ? 'Saving…' : 'Save'}
                </button>
                {isConfigured('GOOGLE_CLOUD_PROJECT') && isConfigured(jsonKey) && pending.length === 0 && (
                    <span className="text-[11px] text-emerald-300/80">
                        Saved. Leave a box blank to keep what is stored.
                    </span>
                )}
            </div>
            <StorageStatusLine />
        </div>
    );
}


export default function SetupIntegrationsPage({ secrets, onSaveSecret, onRefresh, modules, onUpdateModules }: SetupIntegrationsPageProps) {
    const [secretValues, setSecretValues] = useState<Record<string, string>>({});
    const [savingKey, setSavingKey] = useState<string | null>(null);
    // The backup passphrase is generated rather than invented, shown once, and
    // gated on someone confirming they have put a copy somewhere else. See the
    // /setup/backup-key endpoint for why that last part cannot be automated.
    const [backupKey, setBackupKey] = useState<string | null>(null);
    const [backupKeyAcknowledged, setBackupKeyAcknowledged] = useState(false);

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
    const [wantedFeatures, setWantedFeatures] = useState<Set<string>>(new Set(ALL_FEATURES));
    const toggleFeature = (f: string) =>
        setWantedFeatures(prev => {
            const next = new Set(prev);
            next.has(f) ? next.delete(f) : next.add(f);
            return next;
        });
    const wants = (f: string) => wantedFeatures.has(f);

    /* The questionnaire's answers, translated into the provider ids the
     * catalogs actually use.
     *
     * The point of asking "which cloud hosts your town's services" at the top
     * is that nothing below should ask again. So AI, translation and key
     * management take their provider from that answer rather than showing a
     * second picker -- the guide sets up Vertex on Google, Azure OpenAI on
     * Azure, Bedrock on AWS, without a further decision.
     *
     * Email, SMS and photo redaction are different: they are genuinely not a
     * cloud decision. A town on Google may well send mail through SES, and
     * redaction on this server is a reasonable choice on any cloud. Those keep
     * a picker, seeded from the cloud answer so the common case is already
     * right and only a town that wants something else has to touch it. */
    const AI_BY_CLOUD = { google: 'vertex', azure: 'azure', aws: 'bedrock' } as const;
    const EMAIL_BY_CLOUD = { google: 'smtp', azure: 'acs', aws: 'ses' } as const;
    const SMS_BY_CLOUD = { google: 'twilio', azure: 'acs', aws: 'sns' } as const;

    /* null means "still following the cloud answer". Holding the override
     * rather than the value is what lets changing the cloud at the top move
     * these along with it, while a deliberate pick here stays put. */
    const [emailOverride, setEmailOverride] = useState<string | null>(null);
    const [smsOverride, setSmsOverride] = useState<string | null>(null);
    const [redactionOverride, setRedactionOverride] = useState<string | null>(null);

    const aiProvider = AI_BY_CLOUD[setupCloud];
    const emailProvider = emailOverride ?? EMAIL_BY_CLOUD[setupCloud];
    const smsProvider = smsOverride ?? SMS_BY_CLOUD[setupCloud];
    const redactionProvider = redactionOverride ?? setupCloud;


    /* The setup questions are asked in feature terms ("AI triage", "Secret
     * storage + PII encryption") and the provider cards are keyed by
     * capability. This is the one mapping between them. `secrets` covers the
     * KMS card because the same question is what a town answers about where
     * keys and resident data are protected.
     *
     * Redaction used to hang off the `moderation` tick, which was wrong in both
     * directions: unticking "content moderation" silently hid face blurring,
     * and there was no way to have blurring without it. They are different
     * decisions -- one screens what a resident wrote, the other blurs a
     * bystander who never wrote anything -- so they are now separate ticks. */
    const FEATURE_TO_CAPABILITY: Record<string, Capability> = {
        ai: 'ai', translation: 'translation', email: 'email',
        sms: 'sms', secrets: 'kms', safety: 'redaction',
    };
    const wantedCapabilities = new Set<Capability>(
        Object.entries(FEATURE_TO_CAPABILITY)
            .filter(([feature]) => wantedFeatures.has(feature))
            .map(([, capability]) => capability),
    );


    // Managed (state-hosted) mode: infrastructure cards are locked because the
    // state's orchestrator owns those keys (Google Cloud, Backups, domain).
    const [managedMode, setManagedMode] = useState(false);
    /* The address residents actually use, for the callback URLs the setup steps
     * tell an admin to paste into a vendor console.
     *
     * Not window.location.origin, which is wherever the admin happens to be
     * -- an internal hostname, a port-forward, an IP. A redirect URI registered
     * from one of those can never be redirected to, and the login then fails
     * after the password is accepted, which looks like a wrong secret rather
     * than a wrong URL. null means nothing has configured a domain yet, and the
     * browser's origin is the best guess available. */
    const [publicOrigin, setPublicOrigin] = useState<string | null>(null);
    /* Which provider each capability is on, and which are set up.
     *
     * Per provider, not per capability: "maps is configured" was true if any
     * map provider's key existed, so switching to one with no credentials still
     * showed a tick. Refetched whenever something saves. */
    const [providerStatus, setProviderStatus] = useState<ProviderStatusMap | null>(null);
    /* The guide and the provider cards below are two views of one set of
     * credentials, on one screen. Until this token existed neither told the
     * other anything: a key entered in the guide left the card below still
     * reading "Not set up", and the only conclusion available to a clerk from
     * that is that the save did not take. */
    const [providerRefresh, setProviderRefresh] = useState(0);
    /* Health, for the badge on the collapsed panel. Provider status alone can
     * only say whether a credential is stored, and "stored" is the fact that
     * stays true through a key being revoked. */
    const [connectorHealth, setConnectorHealth] = useState<Record<string, string>>({});
    const loadHealth = useCallback(() => {
        api.getConnectorHealth()
            .then(r => setConnectorHealth(Object.fromEntries(r.connectors.map(c => [c.connector, c.status]))))
            .catch(() => { /* no health is not the same as bad health */ });
    }, []);
    useEffect(() => { loadHealth(); }, [loadHealth, providerRefresh]);
    const loadProviderStatus = useCallback(() => {
        api.getProviderStatus()
            .then(setProviderStatus)
            .catch(() => { /* leaves everything unfinished, which is the safe way to be wrong */ });
    }, []);
    useEffect(() => { loadProviderStatus(); }, [loadProviderStatus, secrets.length]);
    useEffect(() => {
        fetch('/api/system/config')
            .then(r => (r.ok ? r.json() : null))
            .then(cfg => {
                setManagedMode(!!cfg?.managed_mode);
                setPublicOrigin(cfg?.public_origin ?? null);
            })
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

    /* Whether one wizard item is already set up.
     *
     * Reuses the flags computed above rather than fetching eight catalogs to
     * fill in a list of ticks -- the answer is already in `secrets`, which the
     * page has loaded anyway. Anything not listed is treated as unfinished,
     * which is the safe direction: an item wrongly shown as done is one nobody
     * ever opens.
     */
    const DONE_BY_ITEM: Record<string, boolean> = {
        identity: !!signInConfigured,
        maps: !!mapsConfigured,
        ai: !!aiConfigured,
        translation: !!translationConfigured,
        kms: !!kmsConfigured,
        safety: !!redactionConfigured,
        email: !!smtpConfigured,
        sms: smsConfigured,
        backups: !!backupConfigured,
        errors: !!sentryConfigured,
    };
    const itemDone = (id: string) => DONE_BY_ITEM[id] ?? false;

    /* What the badge on the collapsed header reports.
     *
     * Built from buildPlan with the same inputs the wizard is given, so the
     * count can never say something the list inside it does not. Reproducing
     * the arithmetic here instead would be a second implementation of "what is
     * left", and those drift. */
    const planSummary = summarise(
        buildPlan({
            cloud: setupCloud, idp: setupIdp, maps: setupMaps, aiProvider,
            emailProvider, smsProvider, redactionProvider, wanted: wantedFeatures,
        }),
        {
            isDone: (item) => (item.cap && item.provider)
                ? providerStatus?.[item.cap]?.configured?.[item.provider] === true
                : itemDone(item.id),
            /* Only a real failure counts. `unknown` means nobody has looked and
             * `stale` means not lately -- neither is evidence of a fault, and
             * badging them as one produces a number that never reaches zero on
             * a town whose sweep has not run yet. */
            stateOf: (item) => {
                const status = item.cap ? connectorHealth[item.cap] : undefined;
                return status === 'failing' || status === 'down' ? 'failing' : status;
            },
        },
    );
    const outstanding = planSummary.notSetUp.length + planSummary.notWorking.length;

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

    /* Sections that need a credential mount InlineProviderSetup directly --
     * not through a wrapper defined in here. A component declared during render
     * is a fresh type on every render, so React unmounts and remounts it, and
     * everything typed into it is gone. Ticking any chip in the questionnaire
     * re-renders this component, which would have made that a routine way to
     * lose a half-entered client secret.
     *
     * Why the guide sets providers up at all, rather than pointing at the cards
     * below, is written where it applies: InlineProviderSetup.tsx. */

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

    /* The account itself, before anything is created inside it.
     *
     * This belongs to no single capability -- a project, a resource group, an
     * IAM identity are the thing every other item in a cloud task sits inside.
     * The wizard shows it once at the top of that task, which is the whole
     * reason for grouping by login: it used to be repeated, in slightly
     * different words, in each of the four sections that needed it.
     */
    const renderFoundation = (cloud: 'google' | 'azure' | 'aws') => (
        <div className="space-y-2.5">
            <p className="text-[11px] uppercase tracking-wider text-white/45 font-semibold">First, the account</p>
            {cloud === 'google' && <>
                <InstructionStep num={1} check={<>a Project ID like <code className="bg-black/30 px-1 rounded">my-town-311-4821</code>.</>}>
                    Go to <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">console.cloud.google.com</a> and make a new project. Copy its <strong className="text-white/90">Project ID</strong> — that is the short code, not the name you typed.
                </InstructionStep>
                <InstructionStep num={2}>
                    Add a billing account under <strong className="text-white/90">Billing</strong>. Google asks for this even for the things it does not charge you for; without it the requests come back refused.
                </InstructionStep>
                <InstructionStep num={3} check={<>your service account listed under IAM &amp; Admin.</>}>
                    Under <strong className="text-white/90">IAM &amp; Admin → Service Accounts</strong>, create one called <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311</code>. This is a login for the software, so nothing is tied to your own account.
                </InstructionStep>
                <InstructionStep num={4} check={<>a file ending in <code className="bg-black/30 px-1 rounded">.json</code> in your Downloads.</>}>
                    Open it, then <strong className="text-white/90">Keys → Add Key → Create new key → JSON</strong>. A file downloads — that is the one you add below.
                </InstructionStep>
                <Trouble>Google will not let you download that file again. Keep a copy somewhere the town controls, not on your own laptop.</Trouble>
                <GoogleAccountFields
                    secretValues={secretValues} setSecretValues={setSecretValues}
                    handleSave={handleSave} savingKey={savingKey} isConfigured={isConfigured}
                    modules={modules} onUpdateModules={onUpdateModules}
                />
            </>}
            {cloud === 'azure' && <>
                <InstructionStep num={1}>
                    In the <a href="https://portal.azure.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">Azure Portal</a>, search for <strong className="text-white/90">Resource groups</strong> and create one called <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311-rg</code>. Everything below goes in it, so it all sits together and bills together.
                </InstructionStep>
                <InstructionStep num={2} check={<>a region set. If your state has a rule about where data is held, pick one that satisfies it.</>}>
                    Pick a region when it asks.
                </InstructionStep>
                <InstructionStep num={3}>
                    Each thing below is a resource you create in that group. When you open one, its <strong className="text-white/90">Keys and Endpoint</strong> page has the two values the boxes here ask for.
                </InstructionStep>
            </>}
            {cloud === 'aws' && <>
                <InstructionStep num={1}>
                    In the <a href="https://console.aws.amazon.com" target="_blank" rel="noopener noreferrer" className="text-blue-300 underline underline-offset-2">AWS Console</a>, pick a <strong className="text-white/90">Region</strong> at the top right and use the same one throughout.
                </InstructionStep>
                <InstructionStep num={2}>
                    Under <strong className="text-white/90">IAM → Users → Create user</strong>, make one called <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311</code>. If Pinpoint runs on EC2 or ECS, create a role instead — then there is no key to look after at all.
                </InstructionStep>
                <InstructionStep num={3} check={<>an Access key ID and a Secret access key. The secret is shown once.</>}>
                    If you made a user, go to <strong className="text-white/90">Security credentials → Create access key</strong> and choose the option for an application running outside AWS.
                </InstructionStep>
            </>}
            <p className="text-xs text-white/45 leading-relaxed pl-9">
                Each box below has a <strong className="text-white/70">Save &amp; Test</strong> button. It makes a real call and tells you either that it worked or exactly what went wrong, so you find out now rather than when a resident does.
            </p>
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

                {/* Below the chips and outside the count on purpose. This is the
                  * one thing on this page that is not an integration and cannot
                  * be "done" -- counting it would make the percentage a measure
                  * of whether somebody gave us their email, which it is not. It
                  * lives here so the form stays reachable after the prompt has
                  * been dismissed, which is permanent. */}
                <div className="mt-4 pt-3 border-t border-white/10 flex items-center gap-2 flex-wrap">
                    <Bell className="w-3.5 h-3.5 text-white/35" />
                    <span className="text-xs text-white/45">
                        We have no way to reach you about security fixes — Pinpoint calls home about nothing.
                    </span>
                    <button
                        type="button"
                        onClick={openStayInformed}
                        className="text-xs text-indigo-300 hover:text-indigo-200 underline underline-offset-2"
                    >
                        Share a contact (optional)
                    </button>
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
                            <p className="text-white/50 text-xs">Answer a few questions, then work through one thing at a time</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2.5 shrink-0">
                        {/* Two pills, never one.
                            "Not set up" and "not working" need different things
                            from a clerk -- a credential entered, or a credential
                            replaced -- and merging them into "4 issues" sends
                            them to the wrong place. Named where the list is
                            short enough to name, because "which ones" is the
                            next question either way. */}
                        {planSummary.notWorking.length > 0 && (
                            <span
                                title={nameList(planSummary.notWorking, 99)}
                                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-2xl text-xs font-semibold border bg-gradient-to-r from-red-500/25 to-rose-500/20 text-red-200 border-red-400/35 shadow-md shadow-red-950/40"
                            >
                                <AlertCircle className="w-3.5 h-3.5" aria-hidden="true" />
                                {planSummary.notWorking.length} not working
                            </span>
                        )}
                        {planSummary.notSetUp.length > 0 && (
                            <span
                                title={nameList(planSummary.notSetUp, 99)}
                                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-2xl text-xs font-semibold border bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border-amber-500/30 shadow-md shadow-amber-950/40"
                            >
                                <CircleDashed className="w-3.5 h-3.5" aria-hidden="true" />
                                {planSummary.notSetUp.length} still to set up
                            </span>
                        )}
                        {/* Only once the server has actually said so. Before
                            provider status arrives everything looks unfinished,
                            and a green "all set up" flashed at that moment is
                            the false completion message all over again. */}
                        {providerStatus && outstanding === 0 && planSummary.total > 0 && (
                            <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-2xl text-xs font-semibold border bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border-emerald-500/30 shadow-md shadow-emerald-950/40">
                                <CheckCircle className="w-3.5 h-3.5" aria-hidden="true" />
                                All set up
                            </span>
                        )}
                        {outstanding > 0 && (
                            <span className="sm:hidden text-xs font-semibold text-amber-300">{outstanding}</span>
                        )}
                        {expandedGuide === 'master' ? <ChevronUp className="w-5 h-5 text-white/50" /> : <ChevronDown className="w-5 h-5 text-white/50" />}
                    </div>
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
                                        <strong className="text-white">You do not have to do all of this.</strong> Two things are needed
                                        before the town can take reports — <strong className="text-white/90">staff sign-in</strong> and a{' '}
                                        <strong className="text-white/90">map</strong>. Everything else can be added whenever you like, and
                                        nothing breaks while it is switched off. What you save is kept, so you can stop and come back.
                                    </p>
                                    <p className="text-xs text-white/50 leading-relaxed mt-2">
                                        Each step says what you should be looking at, so you can tell it worked. Where there is a copy
                                        button, use it instead of retyping. You will be asked to sign in to one or two outside services;
                                        the steps say exactly where to click.
                                    </p>
                                </div>

                                <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                                    <p className="text-sm font-semibold text-white mb-0.5">Answer a few questions and we will hide the rest</p>
                                    <p className="text-white/50 text-xs mb-3">Sign-in and maps are always shown — a town needs both before it can take a report.</p>

                                    {/* Every provider decision, in one place.
                                      *
                                      * They used to be split: the cloud, sign-in
                                      * and maps here, and email, text and
                                      * screening on pickers nested inside their
                                      * own sections further down. That meant the
                                      * questionnaire could say one thing and a
                                      * section another, and a clerk had no single
                                      * place to see what the town had chosen.
                                      *
                                      * Extras come first because there is no
                                      * point asking who sends your email before
                                      * asking whether you want email at all. */}
                                    <Ask
                                        n={1}
                                        label="What do you want to switch on? (all optional)"
                                        hint="Sign-in and maps are always needed. Tick anything else you want; untick to remove it."
                                    >
                                        <div className="flex flex-wrap gap-2">
                                            {FEATURES.map(([f, label]) => (
                                                <button key={f} type="button" onClick={() => toggleFeature(f)}
                                                    aria-pressed={wants(f)}
                                                    className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${wants(f) ? 'bg-emerald-500/15 border-emerald-400/40 text-emerald-100' : 'bg-white/5 border-white/10 text-white/60 hover:text-white'}`}>
                                                    {wants(f) ? '\u2713 ' : ''}{label}
                                                </button>
                                            ))}
                                        </div>
                                    </Ask>

                                    <Ask
                                        n={2}
                                        label="Which company hosts your town's services?"
                                        hint="If the town already uses Microsoft 365, pick Microsoft Azure. If you are not sure, pick Google — you can change it later."
                                    >
                                        <Options
                                            value={setupCloud}
                                            onChange={(v) => setSetupCloud(v as typeof setupCloud)}
                                            options={[['google', 'Google Cloud'], ['azure', 'Microsoft Azure'], ['aws', 'AWS']]}
                                        />
                                    </Ask>

                                    <Ask
                                        n={3}
                                        label="How will staff sign in?"
                                        hint="If your staff already sign in to Microsoft 365, you already have Entra and can use it. Auth0 is for when there is nothing in place yet."
                                    >
                                        <Options
                                            value={setupIdp}
                                            onChange={(v) => setSetupIdp(v as typeof setupIdp)}
                                            options={[['auth0', 'Auth0'], ['entra', 'Microsoft Entra ID'], ['okta', 'Okta'], ['oidc', 'Other (OIDC)']]}
                                        />
                                    </Ask>

                                    <Ask
                                        n={4}
                                        label="Which map provider?"
                                        hint="If the town or county already has an ArcGIS agreement, Esri lets you use it. Otherwise any of these will do."
                                    >
                                        <Options
                                            value={setupMaps}
                                            onChange={(v) => setSetupMaps(v as typeof setupMaps)}
                                            options={[['google', 'Google Maps'], ['esri', 'Esri / ArcGIS'], ['azure', 'Azure Maps'], ['apple', 'Apple Maps']]}
                                        />
                                    </Ask>

                                    {/* Only asked about what the town ticked.
                                      * These three are not a cloud decision -- a
                                      * town on Google may well send through SES --
                                      * so each starts on whatever suits the cloud
                                      * above and can be changed here. */}
                                    {wants('email') && (
                                        <Ask n={5} label="Who sends your email?"
                                            hint="SMTP uses the mail server the town already has. Microsoft 365 and Google Workspace block plain SMTP by default, so SES or Azure Communication Services may be less work than getting an exception.">
                                            <Options
                                                value={emailProvider}
                                                onChange={setEmailOverride}
                                                options={[['smtp', 'Our mail server (SMTP)'], ['ses', 'Amazon SES'], ['acs', 'Azure Communication Services']]}
                                            />
                                        </Ask>
                                    )}

                                    {wants('sms') && (
                                        <Ask n={6} label="Who sends your text messages?"
                                            hint="Whichever you pick, start the 10DLC carrier registration early — it is not a technical step and it is not immediate.">
                                            <Options
                                                value={smsProvider}
                                                onChange={setSmsOverride}
                                                options={[['twilio', 'Twilio'], ['sns', 'Amazon SNS'], ['acs', 'Azure Communication Services'], ['http', 'Other (HTTP gateway)']]}
                                            />
                                        </Ask>
                                    )}

                                    {wants('safety') && (
                                        <Ask n={7} label="Where should photos be checked and blurred?"
                                            hint="On this server needs no account and no photo ever leaves the building; it finds fewer faces than the clouds do.">
                                            <Options
                                                value={redactionProvider}
                                                onChange={setRedactionOverride}
                                                options={[['local', 'On this server'], ['google', 'Google Cloud Vision'], ['azure', 'Azure Face + Vision'], ['aws', 'AWS Rekognition']]}
                                            />
                                        </Ask>
                                    )}
                                </div>

                                <SetupWizard
                                    cloud={setupCloud}
                                    idp={setupIdp}
                                    maps={setupMaps}
                                    aiProvider={aiProvider}
                                    emailProvider={emailProvider}
                                    smsProvider={smsProvider}
                                    redactionProvider={redactionProvider}
                                    wanted={wantedFeatures}
                                    status={providerStatus}
                                    isDone={itemDone}
                                    secretValues={secretValues}
                                    onSecretChange={(key, value) => setSecretValues(prev => ({ ...prev, [key]: value }))}
                                    onSaveSecrets={async (keys) => { for (const k of keys) await handleSave(k); }}
                                    savingSecret={savingKey}
                                    isSecretConfigured={(key) => !!isConfigured(key)}
                                    onRefresh={() => { onRefresh(); loadProviderStatus(); setProviderRefresh(t => t + 1); }}
                                    publicOrigin={publicOrigin}
                                    renderFoundation={renderFoundation}
                                />
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
                    refreshToken={providerRefresh}
                    publicOrigin={publicOrigin}
                    onChanged={() => { onRefresh(); loadProviderStatus(); }}
                    extras={
                        <>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* The Google Cloud card that used to open this
                                section has gone. Its instructions and its two
                                boxes now sit together in the setup guide's
                                Google task, so the walk that says "download
                                this file" ends where the file is added rather
                                than pointing thousands of pixels down the page.

                                Nothing replaces it for Azure or AWS, and that
                                is correct: neither has an account-level
                                credential to enter. */}
                            {/* Where the stored data actually lives.
                              *
                              * This used to be two buttons -- "Vault Local Secrets to GCP
                              * Identity" and "Re-encrypt All PII Data (after key rotation)" --
                              * which asked a clerk to recognise the need for work they had no
                              * way to know about. Both now run on a schedule, so all that is
                              * left is one sentence.
                              *
                              * Deliberately outside the Google Cloud card. Secret storage and
                              * key management are pluggable, and anything nested in that card
                              * is invisible to a town on Azure or AWS -- which is exactly the
                              * town most likely to want to know where its credentials are. */}
                            <div className="px-1">
                                <StorageStatusLine />
                            </div>


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
                                                {!backupKey ? (
                                                    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                                                        <p className="text-white/50 text-xs mb-2.5">
                                                            {isConfigured('BACKUP_ENCRYPTION_KEY')
                                                                ? "A passphrase is already set and backups are being encrypted with it. Creating a new one means older backups can only be restored with the old passphrase — so only do this if the current one has been exposed."
                                                                : "Backups are encrypted before they leave this server. We'll create the passphrase for you — you don't need to think one up."}
                                                        </p>
                                                        <Button
                                                            size="sm"
                                                            variant="ghost"
                                                            className="w-full border border-white/15 hover:bg-white/10"
                                                            onClick={async () => {
                                                                try {
                                                                    const { key } = await api.generateBackupKey();
                                                                    setBackupKey(key);
                                                                } catch (err: any) {
                                                                    setSaveMessage(`❌ ${err.message || 'Could not create a passphrase'}`);
                                                                }
                                                            }}
                                                        >
                                                            {isConfigured('BACKUP_ENCRYPTION_KEY')
                                                                ? 'Replace backup passphrase'
                                                                : 'Create backup passphrase'}
                                                        </Button>
                                                    </div>
                                                ) : (
                                                    <div className="rounded-xl border border-amber-400/30 bg-amber-500/[0.07] p-3 space-y-2.5">
                                                        <p className="text-amber-100/90 text-xs leading-relaxed">
                                                            This is shown once. Put a copy somewhere that is <strong>not this
                                                            server</strong> — a password manager, or a sealed envelope in the
                                                            clerk's safe. Without it, a backup cannot be restored, and that is the
                                                            one thing we cannot do for you.
                                                        </p>
                                                        <div className="flex items-center gap-2">
                                                            <code className="flex-1 bg-black/40 rounded-lg px-3 py-2 text-[11px] text-amber-200 break-all select-all">
                                                                {backupKey}
                                                            </code>
                                                            <Button
                                                                size="sm"
                                                                variant="ghost"
                                                                onClick={() => navigator.clipboard?.writeText(backupKey)}
                                                            >
                                                                Copy
                                                            </Button>
                                                        </div>
                                                        <label className="flex items-start gap-2 text-xs text-white/70 cursor-pointer">
                                                            <input
                                                                type="checkbox"
                                                                checked={backupKeyAcknowledged}
                                                                onChange={(e) => setBackupKeyAcknowledged(e.target.checked)}
                                                                className="mt-0.5 accent-amber-400"
                                                            />
                                                            I have saved a copy of this passphrase somewhere off this server.
                                                        </label>
                                                    </div>
                                                )}
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
                                                    // The passphrase is stored by the endpoint that
                                                    // generates it, so there is nothing to save here.
                                                    if (secretValues['BACKUP_S3_ENDPOINT']) await handleSave('BACKUP_S3_ENDPOINT');
                                                    if (secretValues['BACKUP_S3_REGION']) await handleSave('BACKUP_S3_REGION');
                                                }}
                                                disabled={!secretValues['BACKUP_S3_BUCKET']
                                                    || !(backupKeyAcknowledged || (!backupKey && isConfigured('BACKUP_ENCRYPTION_KEY')))
                                                    || savingKey !== null}
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
