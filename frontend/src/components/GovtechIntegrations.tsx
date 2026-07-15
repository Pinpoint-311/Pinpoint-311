import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
    Landmark, CheckCircle, AlertCircle, ExternalLink, RefreshCw,
    Plug, Trash2, Copy, Check, Mail, ClipboardList, Loader2, ArrowLeft,
    ChevronDown, ChevronUp, PartyPopper, Sparkles, Search,
    ArrowUpRight, ArrowDownLeft, MessageSquare, Image as ImageIcon, MapPin, ClipboardCheck,
} from 'lucide-react';

import { Button, Modal, CollapsibleSection } from './ui';
import SecretField from './SecretField';
import {
    api, IntegrationPlatform, IntegrationConfig, IntegrationSyncLog, IntegrationTestResult,
} from '../services/api';

const MODE_LABELS: Record<string, { label: string; className: string }> = {
    sandbox: { label: 'No account needed — try it now', className: 'bg-violet-500/20 text-violet-300 border-violet-500/30' },
    public_api: { label: 'Works with your account login', className: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
    open311: { label: 'Works with a standard address + key', className: 'bg-sky-500/20 text-sky-300 border-sky-500/30' },
    partner_api: { label: 'Vendor sends you the details', className: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
};

// Capability chips make each connector's real breadth visible at a glance —
// what actually flows between Pinpoint and the vendor, driven by the catalog.
const CAPABILITY_CHIPS: { key: string; label: string; icon: typeof Sparkles }[] = [
    { key: 'push', label: 'Send reports', icon: ArrowUpRight },
    { key: 'pull', label: 'Receive updates', icon: ArrowDownLeft },
    { key: 'comments', label: 'Comments', icon: MessageSquare },
    { key: 'documents', label: 'Photos & files', icon: ImageIcon },
    { key: 'assets', label: 'Assets → map', icon: MapPin },
    { key: 'work_orders', label: 'Work orders', icon: ClipboardCheck },
];

const SYNC_CHOICES = (name: string) => [
    { value: 'bidirectional', label: 'Keep both systems in sync', help: `New reports go to ${name}, and their updates come back here. Recommended.` },
    { value: 'push', label: `Only send reports to ${name}`, help: 'Updates made there will not come back here.' },
    { value: 'pull', label: `Only receive from ${name}`, help: 'Reports made here will not be sent there.' },
];

type WizardStep = 'intro' | 'details' | 'finish';

export default function GovtechIntegrations() {
    const [catalog, setCatalog] = useState<IntegrationPlatform[]>([]);
    const [configs, setConfigs] = useState<IntegrationConfig[]>([]);
    const [busy, setBusy] = useState<string | null>(null);
    const [cardResult, setCardResult] = useState<Record<string, IntegrationTestResult>>({});
    const [logs, setLogs] = useState<Record<string, IntegrationSyncLog[]>>({});
    const [logsOpen, setLogsOpen] = useState<string | null>(null);
    const [copied, setCopied] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    // Which connector cards are expanded. With 11 platforms, showing every card
    // fully expanded is a wall — collapse to a compact row and open on demand.
    const [openCards, setOpenCards] = useState<Set<string>>(new Set());
    const initialized = useRef(false);

    // Wizard state
    const [wizard, setWizard] = useState<IntegrationPlatform | null>(null);
    const [step, setStep] = useState<WizardStep>('intro');
    const [values, setValues] = useState<Record<string, string>>({});
    const [syncChoice, setSyncChoice] = useState('bidirectional');
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<IntegrationTestResult | null>(null);
    const [showTechnical, setShowTechnical] = useState(false);
    const testStarted = useRef(false);

    const load = useCallback(async () => {
        try {
            const [cat, cfgs] = await Promise.all([api.getIntegrationCatalog(), api.getIntegrations()]);
            setCatalog(cat);
            setConfigs(cfgs);
        } catch (err: any) {
            setError(err?.message || 'Could not load the connections list. Try refreshing the page.');
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    // Once configs first load, auto-expand the connected ones (the cards a clerk
    // actually manages); leave the rest collapsed. Only runs once so it never
    // fights a manual toggle.
    useEffect(() => {
        if (initialized.current || configs.length === 0) return;
        initialized.current = true;
        const connected = configs.filter(c => c.enabled).map(c => c.platform);
        if (connected.length) setOpenCards(new Set(connected));
    }, [configs]);

    const toggleCard = (platform: string) => {
        setOpenCards(prev => {
            const next = new Set(prev);
            next.has(platform) ? next.delete(platform) : next.add(platform);
            return next;
        });
    };

    const configFor = (platform: string) => configs.find(c => c.platform === platform);

    const webhookUrl = (existing?: IntegrationConfig) =>
        existing ? `${window.location.origin}${existing.webhook_path}` : null;

    const copyText = (key: string, text: string) => {
        navigator.clipboard.writeText(text);
        setCopied(key);
        setTimeout(() => setCopied(null), 2000);
    };

    // ---------- Wizard ----------

    const openWizard = (platform: IntegrationPlatform, startAt: WizardStep) => {
        const existing = configFor(platform.platform);
        setWizard(platform);
        setStep(startAt);
        setValues({});
        setSyncChoice(existing?.sync_direction || platform.recommended_sync_direction || 'bidirectional');
        setShowAdvanced(false);
        setTestResult(null);
        setShowTechnical(false);
        testStarted.current = false;
    };

    const closeWizard = () => { setWizard(null); load(); };

    const requiredMissing = (platform: IntegrationPlatform): string[] => {
        const existing = configFor(platform.platform);
        return platform.config_fields
            .filter(f => f.required)
            .filter(f => !values[f.key] && (existing?.config as Record<string, unknown> | undefined)?.[f.key] === undefined)
            .map(f => f.label);
    };

    const saveWizard = async (platform: IntegrationPlatform): Promise<IntegrationConfig | null> => {
        const existing = configFor(platform.platform);
        const credentials: Record<string, string> = {};
        const config: Record<string, unknown> = {};
        // Trim on save — a stray copy-paste space is the most common reason a
        // correct key or URL is rejected by the vendor.
        platform.credential_fields.forEach(f => { const v = (values[f.key] || '').trim(); if (v) credentials[f.key] = v; });
        platform.config_fields.forEach(f => { const v = (values[f.key] ?? '').trim(); if (v !== '') config[f.key] = v; });

        setSaving(true);
        setError(null);
        try {
            let saved: IntegrationConfig;
            if (existing) {
                saved = await api.updateIntegration(existing.id, { credentials, config, sync_direction: syncChoice });
            } else {
                saved = await api.createIntegration({
                    platform: platform.platform, credentials, config,
                    sync_direction: syncChoice, enabled: false,
                });
            }
            setConfigs(prev => [...prev.filter(c => c.platform !== platform.platform), saved]);
            return saved;
        } catch (err: any) {
            setError(err?.message || 'Could not save. Please try again.');
            return null;
        } finally {
            setSaving(false);
        }
    };

    const runFinishTest = async (platform: IntegrationPlatform, saved?: IntegrationConfig | null) => {
        const existing = saved || configFor(platform.platform);
        if (!existing) return;
        setTesting(true);
        setTestResult(null);
        setShowTechnical(false);
        try {
            const result = await api.testIntegration(existing.id);
            setTestResult(result);
            if (result.ok && !existing.enabled) {
                const updated = await api.updateIntegration(existing.id, { enabled: true });
                setConfigs(prev => [...prev.filter(c => c.platform !== platform.platform), updated]);
            }
        } catch (err: any) {
            setTestResult({ ok: false, detail: err?.message || 'Test failed', friendly: 'Something went wrong running the check. Please try again.' });
        } finally {
            setTesting(false);
        }
    };

    const goToFinish = async (platform: IntegrationPlatform) => {
        const saved = await saveWizard(platform);
        if (!saved) return;
        setStep('finish');
        testStarted.current = true;
        runFinishTest(platform, saved);
    };

    // ---------- Card actions ----------

    const handleToggle = async (existing: IntegrationConfig) => {
        setBusy(`toggle:${existing.platform}`);
        try {
            await api.updateIntegration(existing.id, { enabled: !existing.enabled });
            await load();
        } catch (err: any) {
            setError(err?.message || 'Could not update the connection.');
        } finally {
            setBusy(null);
        }
    };

    const handleCardTest = async (existing: IntegrationConfig) => {
        setBusy(`test:${existing.platform}`);
        try {
            const result = await api.testIntegration(existing.id);
            setCardResult(prev => ({ ...prev, [existing.platform]: result }));
        } catch (err: any) {
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Test failed' } }));
        } finally {
            setBusy(null);
        }
    };

    const handleSync = async (existing: IntegrationConfig) => {
        setBusy(`sync:${existing.platform}`);
        try {
            await api.syncIntegration(existing.id);
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: true, detail: 'Update check started — new activity will appear within a minute or two.' } }));
        } catch (err: any) {
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Could not start the update check.' } }));
        } finally {
            setBusy(null);
        }
    };

    const handleSyncAssets = async (existing: IntegrationConfig) => {
        setBusy(`assets:${existing.platform}`);
        try {
            await api.syncIntegrationAssets(existing.id);
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: true, detail: 'Copying their asset list (hydrants, lights, signs…) onto your map. This can take a few minutes.' } }));
        } catch (err: any) {
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Could not start the asset copy.' } }));
        } finally {
            setBusy(null);
        }
    };

    const handleDelete = async (existing: IntegrationConfig, name: string) => {
        if (!window.confirm(`Disconnect ${name}? Reports already sent will stay in both systems, but nothing new will sync.`)) return;
        setBusy(`delete:${existing.platform}`);
        try {
            await api.deleteIntegration(existing.id);
            closeWizard();
            await load();
        } catch (err: any) {
            setError(err?.message || 'Could not disconnect.');
        } finally {
            setBusy(null);
        }
    };

    const toggleLogs = async (existing: IntegrationConfig) => {
        if (logsOpen === existing.platform) { setLogsOpen(null); return; }
        setLogsOpen(existing.platform);
        try {
            const entries = await api.getIntegrationLogs(existing.id);
            setLogs(prev => ({ ...prev, [existing.platform]: entries }));
        } catch { /* non-fatal */ }
    };

    // ---------- Render helpers ----------

    const renderField = (platform: IntegrationPlatform, field: { key: string; label: string; secret?: boolean; placeholder?: string; required?: boolean }, isCredential: boolean) => {
        const existing = configFor(platform.platform);
        const alreadySet = isCredential
            ? !!existing?.configured_credentials.includes(field.key)
            : existing !== undefined && (existing.config as Record<string, unknown>)[field.key] !== undefined;
        // Config (non-secret) fields show their current value as the placeholder;
        // secrets show a masked "leave blank to keep" and get a reveal toggle.
        const currentConfigVal = !isCredential ? String((existing?.config as Record<string, unknown>)?.[field.key] ?? '') : '';
        return (
            <SecretField
                key={field.key}
                label={field.label}
                secret={!!field.secret}
                required={field.required}
                value={values[field.key] || ''}
                onChange={(v) => setValues(p => ({ ...p, [field.key]: v }))}
                placeholder={!isCredential && alreadySet ? currentConfigVal : (field.placeholder || '')}
                help={platform.field_help?.[field.key]}
                savedHint={!!(isCredential && alreadySet)}
            />
        );
    };

    const emailBody = (platform: IntegrationPlatform) => {
        const existing = configFor(platform.platform);
        const url = webhookUrl(existing);
        return (platform.vendor_ask?.body || '').replace(
            /\{\{WEBHOOK_URL\}\}/g,
            url || '(we will send you this address once our side is set up)'
        );
    };

    const connectedCount = configs.filter(c => c.enabled).length;

    // Filter by the clerk's search and surface connected platforms first.
    const q = query.trim().toLowerCase();
    const visibleCatalog = catalog
        .filter(p => !q || [p.name, p.vendor, p.category].some(s => (s || '').toLowerCase().includes(q)))
        .sort((a, b) => {
            const rank = (p: IntegrationPlatform) => (configFor(p.platform)?.enabled ? 0 : configFor(p.platform) ? 1 : 2);
            return rank(a) - rank(b);
        });

    // ---------- UI ----------

    return (
        <>
        <CollapsibleSection
            title="Connect Your Other Town Systems"
            icon={Landmark}
            subtitle={`${visibleCatalog.length || catalog.length} platforms available — Accela, Tyler, CivicPlus, Cityworks, and more`}
            defaultOpen={true}
            badge={connectedCount > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 border border-emerald-400/30 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">
                    <span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 text-emerald-400" aria-hidden="true" />
                    {connectedCount} connected
                </span>
            ) : undefined}
        >
            <p className="text-white/60 text-sm max-w-2xl leading-relaxed mb-4">
                Full two-way connectors for the platforms your town already runs. Reports, photos, comments,
                and status updates flow between them automatically — no double entry.
            </p>

            {error && (
                <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0" /> {error}
                </div>
            )}

            {/* Search — with 10+ platforms, let staff jump straight to theirs */}
            {catalog.length > 4 && (
                <div className="relative mb-4 max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/35" aria-hidden="true" />
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search — e.g. Accela, permitting, SeeClickFix…"
                        aria-label="Search platforms"
                        className="w-full rounded-xl bg-white/[0.04] border border-white/10 text-white text-sm pl-9 pr-3 py-2.5 placeholder:text-white/40 transition-all focus:outline-none focus:border-primary-400/50 focus:bg-white/[0.06] focus:shadow-[0_0_0_3px_rgba(99,102,241,0.15)]"
                    />
                </div>
            )}

            {visibleCatalog.length === 0 && (
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-8 text-center text-white/50 text-sm">
                    No platforms match “{query}”. Don’t see yours? The <span className="text-white/70">Generic Open311</span> connector works with many systems.
                </div>
            )}

            <div className="relative space-y-2.5">
                {visibleCatalog.map((platform, idx) => {
                    const existing = configFor(platform.platform);
                    const mode = MODE_LABELS[platform.integration_mode] || MODE_LABELS.partner_api;
                    const result = cardResult[platform.platform];
                    const platformLogs = logs[platform.platform];
                    const isWorking = existing?.enabled && existing.last_sync_status !== 'error';
                    const needsAttention = existing?.enabled && existing.last_sync_status === 'error';
                    const isOpen = openCards.has(platform.platform);

                    return (
                        <motion.div
                            key={platform.platform}
                            initial={{ opacity: 0, y: 14 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: Math.min(idx, 8) * 0.03, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                            className={`relative rounded-xl border p-4 transition-colors ${needsAttention
                                ? 'border-amber-500/40 bg-amber-500/[0.04]'
                                : existing?.enabled
                                    ? 'border-primary-400/30 bg-primary-500/[0.06]'
                                    : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.05]'}`}
                        >
                            <button
                                type="button"
                                onClick={() => toggleCard(platform.platform)}
                                aria-expanded={isOpen}
                                aria-controls={`conn-body-${platform.platform}`}
                                className="relative w-full flex items-center justify-between gap-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 rounded-xl"
                            >
                                <div className="flex items-center gap-3.5 min-w-0">
                                    <div className="relative shrink-0">
                                        {existing?.enabled && (
                                            <div className="absolute -inset-1 rounded-2xl bg-gradient-to-br from-primary-400/40 to-primary-600/20 blur-md" aria-hidden="true" />
                                        )}
                                        <div className={`relative w-11 h-11 rounded-2xl flex items-center justify-center shadow-lg ${existing?.enabled
                                            ? 'bg-gradient-to-br from-primary-500/30 to-primary-700/20 border border-primary-400/30 shadow-primary-900/40'
                                            : 'bg-white/[0.06] border border-white/10 shadow-black/20'
                                            }`}>
                                            <Plug className={`w-5 h-5 ${existing?.enabled ? 'text-primary-200' : 'text-white/60'}`} />
                                        </div>
                                    </div>
                                    <div className="min-w-0">
                                        <h3 className="font-semibold text-white tracking-tight">{platform.name}</h3>
                                        <p className="text-white/60 text-xs truncate">{platform.category}</p>
                                    </div>
                                </div>
                                <div className="shrink-0 flex items-center gap-2">
                                    {isWorking ? (
                                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-200 border border-emerald-400/30">
                                            <span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 text-emerald-400" aria-hidden="true" /> Connected
                                        </span>
                                    ) : needsAttention ? (
                                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                            <AlertCircle className="w-3 h-3" /> Needs attention
                                        </span>
                                    ) : existing ? (
                                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium bg-white/10 text-white/50 border border-white/10">
                                            Turned off
                                        </span>
                                    ) : (
                                        <span className="text-white/60 text-xs">Not connected</span>
                                    )}
                                    <motion.span animate={{ rotate: isOpen ? 180 : 0 }} transition={{ duration: 0.3 }} aria-hidden="true" className="text-white/60">
                                        <ChevronDown className="w-4 h-4" />
                                    </motion.span>
                                </div>
                            </button>

                            {/* Collapsed preview: quiet mode label so the row stays calm */}
                            {!isOpen && (
                                <p className="relative text-[11px] text-white/60 mt-1.5 ml-[3.75rem]">{mode.label}</p>
                            )}

                            <div id={`conn-body-${platform.platform}`} className={isOpen ? 'block' : 'hidden'}>
                            <span className={`relative inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border mt-3 ${mode.className}`}>
                                {mode.label}
                            </span>

                            <p className="relative text-white/60 text-xs mt-2 leading-relaxed">{platform.plain_summary || platform.description}</p>

                            {/* Capability chips — what actually flows with this connector */}
                            <div className="relative flex flex-wrap gap-1.5 mt-3">
                                {CAPABILITY_CHIPS.filter(c => platform.capabilities.includes(c.key)).map(c => (
                                    <span key={c.key} className="inline-flex items-center gap-1 rounded-md bg-white/[0.04] border border-white/10 px-1.5 py-0.5 text-[10px] text-white/75">
                                        <c.icon className="w-2.5 h-2.5 text-primary-300/80" aria-hidden="true" /> {c.label}
                                    </span>
                                ))}
                            </div>

                            {existing?.last_sync_at && (
                                <p className={`relative text-[11px] mt-2 ${existing.last_sync_status === 'error' ? 'text-amber-300' : 'text-white/60'}`}>
                                    {existing.last_sync_status === 'error'
                                        ? 'The last update check hit a problem — press "Check connection" for a plain-language explanation.'
                                        : `Last checked ${new Date(existing.last_sync_at).toLocaleString()} — all good.`}
                                </p>
                            )}

                            {result && (
                                <div className={`relative mt-2 rounded-lg px-3 py-2 text-xs border ${result.ok
                                    ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-200'
                                    : 'bg-amber-500/10 border-amber-500/25 text-amber-200'}`}>
                                    {result.ok ? result.detail : (result.friendly || result.detail)}
                                </div>
                            )}

                            <div className="relative flex flex-wrap items-center gap-2 mt-4">
                                {!existing ? (
                                    <button
                                        className="shimmer-sweep inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-900/40 transition-all hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                        onClick={() => openWizard(platform, 'intro')}
                                    >
                                        {platform.platform === 'sandbox'
                                            ? <><Sparkles className="w-4 h-4" /> Try it — 2 minutes</>
                                            : <><Plug className="w-4 h-4" /> Set up — about 10 minutes</>}
                                    </button>
                                ) : (
                                    <>
                                        <Button size="sm" variant="ghost" className="text-xs" onClick={() => openWizard(platform, 'details')}>
                                            Settings
                                        </Button>
                                        <Button size="sm" variant="ghost" className="text-xs" onClick={() => handleCardTest(existing)} disabled={busy !== null}>
                                            {busy === `test:${platform.platform}` ? 'Checking…' : 'Check connection'}
                                        </Button>
                                        {existing.enabled && platform.capabilities.includes('pull') && (
                                            <Button size="sm" variant="ghost" className="text-xs" onClick={() => handleSync(existing)} disabled={busy !== null} leftIcon={<RefreshCw className="w-3 h-3" />}>
                                                Check for updates
                                            </Button>
                                        )}
                                        {existing.enabled && platform.capabilities.includes('assets') && (
                                            <Button size="sm" variant="ghost" className="text-xs" onClick={() => handleSyncAssets(existing)} disabled={busy !== null}>
                                                {busy === `assets:${platform.platform}` ? 'Copying…' : 'Copy their assets to my map'}
                                            </Button>
                                        )}
                                        <Button size="sm" variant="ghost" className="text-xs" onClick={() => toggleLogs(existing)} rightIcon={logsOpen === platform.platform ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}>
                                            Activity
                                        </Button>
                                        <label className="flex items-center gap-2 ml-auto text-[11px] text-white/60 cursor-pointer select-none">
                                            {existing.enabled ? 'On' : 'Off'}
                                            <button
                                                onClick={() => handleToggle(existing)}
                                                disabled={busy !== null}
                                                role="switch"
                                                aria-checked={existing.enabled}
                                                aria-label={`Turn ${platform.name} connection ${existing.enabled ? 'off' : 'on'}`}
                                                className={`relative inline-flex h-[18px] w-[30px] shrink-0 items-center rounded-full transition-colors duration-300 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 ${existing.enabled ? 'bg-primary-500' : 'bg-white/20'}`}
                                            >
                                                <span
                                                    aria-hidden="true"
                                                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-300 ${existing.enabled ? 'translate-x-[14px]' : 'translate-x-0.5'}`}
                                                />
                                            </button>
                                        </label>
                                    </>
                                )}
                            </div>

                            {logsOpen === platform.platform && platformLogs && (
                                <div className="relative mt-3 rounded-lg border border-white/10 divide-y divide-white/5 max-h-48 overflow-y-auto">
                                    {platformLogs.length === 0 && (
                                        <p className="text-white/60 text-xs px-3 py-2">Nothing has synced yet. Activity will show up here once reports start flowing.</p>
                                    )}
                                    {platformLogs.map(entry => (
                                        <div key={entry.id} className="px-3 py-2 flex items-start gap-2">
                                            {entry.status === 'success'
                                                ? <CheckCircle className="w-3.5 h-3.5 text-green-400 mt-0.5 shrink-0" />
                                                : <AlertCircle className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />}
                                            <div className="min-w-0">
                                                <p className="text-white/70 text-xs">{entry.detail || entry.operation}</p>
                                                <p className="text-white/60 text-[10px]">{entry.created_at ? new Date(entry.created_at).toLocaleString() : ''}</p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                            </div>
                        </motion.div>
                    );
                })}
            </div>
        </CollapsibleSection>

        {/* ---------- Setup wizard ---------- */}
        {wizard && (
                <Modal
                    isOpen={true}
                    onClose={closeWizard}
                    title={step === 'intro' ? `Connect ${wizard.name}` : step === 'details' ? `Connect ${wizard.name} — enter the details` : `Connect ${wizard.name} — final check`}
                    size="lg"
                >
                    {/* Step dots */}
                    <div className="flex items-center gap-2 mb-4" aria-hidden="true">
                        {(['intro', 'details', 'finish'] as WizardStep[]).map((s) => (
                            <div key={s} className={`h-1.5 rounded-full transition-all ${step === s ? 'w-8 bg-indigo-400' : 'w-4 bg-white/15'}`} />
                        ))}
                    </div>

                    {step === 'intro' && (
                        <div className="space-y-4">
                            <p className="text-white/70 text-sm leading-relaxed">{wizard.plain_summary}</p>

                            <div className="rounded-xl bg-white/[0.04] border border-white/10 p-4">
                                <h4 className="text-white font-semibold text-sm mb-2 flex items-center gap-2">
                                    <ClipboardList className="w-4 h-4 text-indigo-300" /> What you'll need
                                </h4>
                                <ul className="space-y-1.5">
                                    {(wizard.what_you_need || []).map((item, i) => (
                                        <li key={i} className="text-white/60 text-sm flex gap-2">
                                            <span className="text-indigo-300 shrink-0">•</span> {item}
                                        </li>
                                    ))}
                                </ul>
                            </div>

                            {wizard.vendor_ask && (
                                <div className="rounded-xl bg-indigo-500/5 border border-indigo-500/20 p-4">
                                    <h4 className="text-white font-semibold text-sm mb-1 flex items-center gap-2">
                                        <Mail className="w-4 h-4 text-indigo-300" /> Don't have these yet? Send this email
                                    </h4>
                                    <p className="text-white/50 text-xs mb-3">Send to: <span className="text-white/70">{wizard.vendor_ask.to_hint}</span></p>
                                    <div className="rounded-lg bg-black/30 p-3 text-xs text-white/60 whitespace-pre-wrap max-h-44 overflow-y-auto">
                                        <p className="text-white/80 mb-2">Subject: {wizard.vendor_ask.subject}</p>
                                        {emailBody(wizard)}
                                    </div>
                                    <Button
                                        size="sm" variant="ghost" className="mt-2 text-xs"
                                        onClick={() => copyText('email', `Subject: ${wizard.vendor_ask!.subject}\n\n${emailBody(wizard)}`)}
                                        leftIcon={copied === 'email' ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                                    >
                                        {copied === 'email' ? 'Copied — paste it into an email' : 'Copy this email'}
                                    </Button>
                                    <p className="text-white/60 text-xs mt-2">
                                        You can close this window and come back once they reply — nothing is lost.
                                    </p>
                                </div>
                            )}

                            <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-2">
                                <a href={wizard.docs_url} target="_blank" rel="noopener noreferrer" className="text-indigo-300 text-xs hover:underline inline-flex items-center gap-1 self-center sm:self-auto">
                                    {wizard.vendor} website <ExternalLink className="w-3 h-3" />
                                </a>
                                <button
                                    className="shimmer-sweep w-full sm:w-auto inline-flex items-center justify-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-900/40 transition-all hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                    onClick={() => setStep('details')}
                                >
                                    I have these — continue
                                </button>
                            </div>
                        </div>
                    )}

                    {step === 'details' && (
                        <div className="space-y-4">
                            <p className="text-white/50 text-sm">
                                Copy and paste each item exactly as it was sent to you. Watch out for extra spaces at the start or end.
                            </p>

                            <div className="space-y-3">
                                {wizard.config_fields.filter(f => f.required).map(f => renderField(wizard, f, false))}
                                {wizard.credential_fields.map(f => renderField(wizard, f, true))}
                            </div>

                            {wizard.config_fields.some(f => !f.required) && (
                                <div>
                                    <button
                                        onClick={() => setShowAdvanced(v => !v)}
                                        className="text-white/60 text-xs hover:text-white/70 inline-flex items-center gap-1"
                                    >
                                        {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                                        Optional settings — most towns skip these
                                    </button>
                                    {showAdvanced && (
                                        <div className="space-y-3 mt-3">
                                            {wizard.config_fields.filter(f => !f.required).map(f => renderField(wizard, f, false))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {(() => {
                                const syncOptions = SYNC_CHOICES(wizard.name).filter(c => c.value === 'bidirectional'
                                    ? wizard.capabilities.includes('push') && wizard.capabilities.includes('pull')
                                    : wizard.capabilities.includes(c.value));
                                // A single possible direction isn't a choice — don't ask. Just
                                // pin it so the payload is correct and skip the redundant panel.
                                if (syncOptions.length <= 1) {
                                    if (syncOptions[0] && syncChoice !== syncOptions[0].value) setSyncChoice(syncOptions[0].value);
                                    return null;
                                }
                                return (
                            <div className="rounded-xl bg-white/[0.04] border border-white/10 p-4">
                                <h4 className="text-white font-semibold text-sm mb-3">How should the two systems work together?</h4>
                                <div className="space-y-2" role="radiogroup" aria-label="Sync direction">
                                    {syncOptions
                                        .map(choice => {
                                            const isSel = syncChoice === choice.value;
                                            const recommended = choice.value === (wizard.recommended_sync_direction || 'bidirectional');
                                            return (
                                                <button
                                                    key={choice.value}
                                                    type="button"
                                                    role="radio"
                                                    aria-checked={isSel}
                                                    onClick={() => setSyncChoice(choice.value)}
                                                    className={`w-full text-left rounded-xl px-3.5 py-3 border transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 ${isSel
                                                        ? 'bg-gradient-to-br from-primary-500/25 to-primary-700/15 border-primary-400/50 shadow-lg shadow-primary-900/30'
                                                        : 'bg-white/[0.03] border-white/10 hover:bg-white/[0.06] hover:border-white/20'}`}
                                                >
                                                    <span className="flex items-center justify-between gap-2">
                                                        <span className={`text-sm font-medium ${isSel ? 'text-white' : 'text-white/75'}`}>
                                                            {choice.label}
                                                            {recommended && <span className="text-emerald-300 text-xs ml-2 font-normal">Recommended</span>}
                                                        </span>
                                                        {isSel && (
                                                            <span className="shrink-0 w-4 h-4 rounded-full bg-primary-400 flex items-center justify-center">
                                                                <Check className="w-3 h-3 text-primary-950" strokeWidth={3} />
                                                            </span>
                                                        )}
                                                    </span>
                                                    <span className="block text-white/65 text-xs mt-0.5">{choice.help}</span>
                                                </button>
                                            );
                                        })}
                                </div>
                            </div>
                                );
                            })()}

                            {requiredMissing(wizard).length > 0 && (
                                <p className="text-amber-300/80 text-xs">
                                    Still needed before we can continue: {requiredMissing(wizard).join(', ')}
                                </p>
                            )}

                            <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-2">
                                <div className="flex items-center justify-between sm:justify-start gap-2">
                                    <Button variant="ghost" size="sm" onClick={() => setStep('intro')} leftIcon={<ArrowLeft className="w-3.5 h-3.5" />}>
                                        Back
                                    </Button>
                                    {configFor(wizard.platform) && (
                                        <Button size="sm" variant="ghost" className="text-xs text-red-300 hover:text-red-200"
                                            onClick={() => handleDelete(configFor(wizard.platform)!, wizard.name)}
                                            leftIcon={<Trash2 className="w-3.5 h-3.5" />}>
                                            Disconnect
                                        </Button>
                                    )}
                                </div>
                                <button
                                    className="shimmer-sweep w-full sm:w-auto inline-flex items-center justify-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-900/40 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                    onClick={() => goToFinish(wizard)}
                                    disabled={saving || requiredMissing(wizard).length > 0}
                                >
                                    {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</> : <><Sparkles className="w-4 h-4" /> Save &amp; check the connection</>}
                                </button>
                            </div>
                        </div>
                    )}

                    {step === 'finish' && (
                        <div className="space-y-4">
                            {testing && (
                                <div className="flex flex-col items-center py-8 text-center">
                                    <Loader2 className="w-8 h-8 text-indigo-300 animate-spin mb-3" />
                                    <p className="text-white/70 text-sm">Checking the connection to {wizard.name}…</p>
                                    <p className="text-white/60 text-xs mt-1">This usually takes a few seconds.</p>
                                </div>
                            )}

                            {!testing && testResult?.ok && (
                                <div className="space-y-4">
                                    <div className="flex flex-col items-center py-4 text-center">
                                        <div className="w-14 h-14 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center mb-3">
                                            <PartyPopper className="w-7 h-7 text-emerald-300" />
                                        </div>
                                        <h4 className="text-white font-semibold">You're connected!</h4>
                                        <p className="text-white/50 text-sm mt-1 max-w-sm">
                                            The connection works and has been turned on. New resident reports will
                                            now flow to {wizard.name} automatically — nothing else to do.
                                        </p>
                                    </div>

                                    {(() => {
                                        const existing = configFor(wizard.platform);
                                        const url = webhookUrl(existing);
                                        if (!url || !wizard.vendor_ask?.body.includes('{{WEBHOOK_URL}}')) return null;
                                        return (
                                            <div className="rounded-xl bg-white/[0.04] border border-white/10 p-4">
                                                <h4 className="text-white font-semibold text-sm mb-1">One last thing (optional)</h4>
                                                <p className="text-white/50 text-xs mb-2">
                                                    If {wizard.name} will also send things to you, give the vendor this address.
                                                    It's like a mailbox that only they can drop into.
                                                </p>
                                                <div className="flex items-center gap-2">
                                                    <code className="flex-1 bg-black/30 rounded-lg px-3 py-2 text-[11px] text-indigo-200 break-all">{url}</code>
                                                    <Button size="sm" variant="ghost" onClick={() => copyText('webhook', url)}>
                                                        {copied === 'webhook' ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                                                    </Button>
                                                </div>
                                            </div>
                                        );
                                    })()}

                                    <div className="flex justify-end">
                                        <Button className="w-full sm:w-auto bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700" onClick={closeWizard}>
                                            Done
                                        </Button>
                                    </div>
                                </div>
                            )}

                            {!testing && testResult && !testResult.ok && (
                                <div className="space-y-4">
                                    <div className="rounded-xl bg-amber-500/10 border border-amber-500/25 p-4">
                                        <h4 className="text-amber-200 font-semibold text-sm mb-1 flex items-center gap-2">
                                            <AlertCircle className="w-4 h-4" /> Not connected yet — but this is fixable
                                        </h4>
                                        <p className="text-amber-100/80 text-sm">{testResult.friendly || testResult.detail}</p>
                                        <button
                                            onClick={() => setShowTechnical(v => !v)}
                                            className="text-amber-200/50 text-xs mt-2 hover:text-amber-200/80"
                                        >
                                            {showTechnical ? 'Hide' : 'Show'} technical details (for the vendor's support team)
                                        </button>
                                        {showTechnical && (
                                            <code className="block mt-2 bg-black/30 rounded-lg px-3 py-2 text-[11px] text-white/50 break-all">{testResult.detail}</code>
                                        )}
                                    </div>
                                    <p className="text-white/60 text-xs">
                                        Your entries are saved. You can fix them now, or close this window and try again later —
                                        the connection stays off until a check passes.
                                    </p>
                                    <div className="flex items-center justify-between">
                                        <Button variant="ghost" size="sm" onClick={() => setStep('details')} leftIcon={<ArrowLeft className="w-3.5 h-3.5" />}>
                                            Go back and fix
                                        </Button>
                                        <Button size="sm" variant="ghost" onClick={() => runFinishTest(wizard)}>
                                            Try the check again
                                        </Button>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </Modal>
            )}
        </>
    );
}
