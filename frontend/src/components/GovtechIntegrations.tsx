import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
    Landmark, CheckCircle, AlertCircle, ExternalLink,
    Plug, Trash2, Copy, Check, Mail, ClipboardList, Loader2, ArrowLeft,
    ChevronDown, ChevronUp, PartyPopper, Sparkles, Search,
    ArrowUpRight, ArrowDownLeft, MessageSquare, Image as ImageIcon, MapPin, ClipboardCheck,
    ShieldCheck,
} from 'lucide-react';

import { Button, Modal, CollapsibleSection } from './ui';
import SecretField from './SecretField';
import { useDialog } from './DialogProvider';
import {
    api, IntegrationPlatform, IntegrationConfig, IntegrationSyncLog, IntegrationTestResult,
} from '../services/api';
// The decisions worth checking directly live next door, with no JSX around them.
import {
    alreadyStored as alreadyStoredIn,
    buildSavePayload,
    connectionState,
    connectionStateLabel,
    healthKey,
    needsEnableConfirmation,
    requiredMissing as missingRequired,
    truncate,
    type ConnectorHealthRow,
} from './integrationState';
// The same tile, pill and buttons the capability cards use. These were
// hand-rolled here from utility classes, so the town-system cards and the
// provider cards drifted into looking like two different products -- and the
// pill said "Connected" off `enabled && last_sync_status !== 'error'`, which is
// the credentials-are-stored question this whole health system exists to stop
// badges from answering.
import { StatusPill, CapabilityTile, Action, hasAlert } from './capabilityUI';

const MODE_LABELS: Record<string, { label: string; className: string }> = {
    public_api: { label: 'Works with your account login', className: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
    open311: { label: 'Works with a standard address + key', className: 'bg-sky-500/20 text-sky-300 border-sky-500/30' },
    partner_api: { label: 'Vendor sends you the details', className: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
    generic: { label: 'Configure it yourself — not vendor-certified', className: 'bg-white/10 text-white/70 border-white/20' },
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
    const dialog = useDialog();
    const [catalog, setCatalog] = useState<IntegrationPlatform[]>([]);
    const [configs, setConfigs] = useState<IntegrationConfig[]>([]);
    // Keyed by integration id. One global string meant every card's controls
    // disabled while any one of them was working, so checking Accela greyed out
    // the Tyler card the clerk was about to look at.
    const [busy, setBusy] = useState<Record<number, string>>({});
    const [cardResult, setCardResult] = useState<Record<string, IntegrationTestResult>>({});
    // The govtech rows out of the shared connector-health table, keyed by
    // connector name. Same source the provider cards read, so both surfaces
    // answer "is it working" from the same evidence.
    const [healthRows, setHealth] = useState<Record<string, ConnectorHealthRow>>({});
    // A mute taken in this session, which is fresher than the row we loaded.
    const [muted, setMuted] = useState<Record<string, string | null>>({});
    const [muting, setMuting] = useState<string | null>(null);
    const [logs, setLogs] = useState<Record<string, IntegrationSyncLog[]>>({});
    const [logsOpen, setLogsOpen] = useState<string | null>(null);
    const [copied, setCopied] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    // Distinguishes "nothing matches" from "we have not asked yet". Without it
    // the first paint rendered `No platforms match ""` under the search box.
    const [loaded, setLoaded] = useState(false);
    // Which connector cards are expanded. With this many platforms, showing every
    // card fully expanded is a wall — collapse to a compact row and open on demand.
    const [openCards, setOpenCards] = useState<Set<string>>(new Set());
    const initialized = useRef(false);

    // Wizard state
    const [wizard, setWizard] = useState<IntegrationPlatform | null>(null);
    const [step, setStep] = useState<WizardStep>('intro');
    const [values, setValues] = useState<Record<string, string>>({});
    // Config keys the admin has asked to blank on save, sent as explicit nulls.
    const [cleared, setCleared] = useState<Set<string>>(new Set());
    const [syncChoice, setSyncChoice] = useState('bidirectional');
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<IntegrationTestResult | null>(null);
    const [showTechnical, setShowTechnical] = useState(false);
    // Errors from inside the wizard. The shared `error` banner renders behind the
    // modal, so a failed save made "Save & check the connection" look like a
    // button that does nothing at all.
    const [wizardError, setWizardError] = useState<string | null>(null);

    const busyOf = (existing?: IntegrationConfig | null) =>
        (existing && busy[existing.id]) || null;

    const setBusyFor = (id: number, action: string | null) =>
        setBusy(prev => {
            const next = { ...prev };
            if (action) next[id] = action; else delete next[id];
            return next;
        });

    const loadHealth = useCallback(async () => {
        try {
            const report = await api.getConnectorHealth();
            setHealth(Object.fromEntries(
                report.connectors
                    .filter(c => c.connector.startsWith('govtech:'))
                    .map(c => [c.connector, c as unknown as ConnectorHealthRow]),
            ));
        } catch {
            // No health is not the same as bad health. The cards fall back to
            // "not checked yet", which is the honest answer when we cannot ask.
        }
    }, []);

    const load = useCallback(async () => {
        try {
            const [cat, cfgs] = await Promise.all([api.getIntegrationCatalog(), api.getIntegrations()]);
            setCatalog(cat);
            setConfigs(cfgs);
            loadHealth();
        } catch (err: any) {
            setError(err?.message || 'Could not load the connections list. Try refreshing the page.');
        } finally {
            setLoaded(true);
        }
    }, [loadHealth]);

    useEffect(() => { load(); }, [load]);

    // Once configs first load, auto-expand the connected ones (the cards a clerk
    // actually manages); leave the rest collapsed. Only runs once so it never
    // fights a manual toggle.
    useEffect(() => {
        if (initialized.current || !configs || configs.length === 0) return;
        initialized.current = true;
        const connected = (configs || []).filter(c => c.enabled).map(c => c.platform);
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

    // Clipboard writes reject on a denied permission or a non-secure context, and
    // an unhandled rejection there left the button silently claiming "Copied".
    const copyText = (key: string, text: string) => {
        navigator.clipboard.writeText(text).then(
            () => {
                setCopied(key);
                setTimeout(() => setCopied(null), 2000);
            },
            () => setError('Your browser blocked the copy. Select the text and copy it manually.'),
        );
    };

    // ---------- Wizard ----------

    const openWizard = (platform: IntegrationPlatform, startAt: WizardStep) => {
        const existing = configFor(platform.platform);
        setWizard(platform);
        setStep(startAt);
        setValues({});
        setCleared(new Set());
        setSyncChoice(existing?.sync_direction || platform.recommended_sync_direction || 'bidirectional');
        setShowAdvanced(false);
        setTestResult(null);
        setShowTechnical(false);
        setWizardError(null);
    };

    const closeWizard = () => { setWizard(null); load(); };

    const requiredMissing = (platform: IntegrationPlatform): string[] =>
        missingRequired(platform, values, configFor(platform.platform), cleared);

    const saveWizard = async (platform: IntegrationPlatform): Promise<IntegrationConfig | null> => {
        const existing = configFor(platform.platform);
        const { credentials, config } = buildSavePayload(platform, values, cleared);

        setSaving(true);
        setError(null);
        setWizardError(null);
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
            setCleared(new Set());
            return saved;
        } catch (err: any) {
            setWizardError(err?.message || 'Could not save. Please try again.');
            return null;
        } finally {
            setSaving(false);
        }
    };

    const runFinishTest = async (platform: IntegrationPlatform, saved?: IntegrationConfig | null) => {
        const existing = saved || configFor(platform.platform);
        if (!existing) {
            // The finish step renders nothing at all when there is neither a
            // spinner nor a result, so returning silently here left an empty
            // modal with no explanation and no way forward but Back.
            setTestResult({
                ok: false,
                detail: 'No saved connection to check.',
                friendly: 'We could not find the saved connection to check. Go back a step and save it again.',
            });
            return;
        }
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
        if (!saved) return;  // wizardError is rendered in the modal
        setStep('finish');
        runFinishTest(platform, saved);
    };

    // ---------- Card actions ----------

    /** Reload configs, and the Activity drawer if it happens to be open.
     *
     * Every card action changes server state -- a test now writes a health row and
     * clears the breaker, a sync writes log entries -- and none of them reloaded,
     * so the card kept showing the state from page load until somebody refreshed
     * the browser. */
    const refreshAfterAction = async (existing: IntegrationConfig) => {
        await load();          // reloads health too

        if (logsOpen === existing.platform) {
            try {
                const entries = await api.getIntegrationLogs(existing.id);
                setLogs(prev => ({ ...prev, [existing.platform]: entries }));
            } catch { /* the drawer keeps what it had */ }
        }
    };

    const handleToggle = async (existing: IntegrationConfig, name: string) => {
        // Turning a connector *on* is the consequential direction, and the wizard
        // promises the connection stays off until a check passes. The toggle
        // bypassed that entirely, so a connector whose last check failed could be
        // switched on with one click and start dropping resident reports.
        {
            const lastResult = cardResult[existing.platform];
            if (needsEnableConfirmation(existing, lastResult)) {
                const detail = existing.last_sync_error || lastResult?.detail || '';
                const confirmed = await dialog.confirm({
                    title: `Turn on ${name} anyway?`,
                    message: `The last check on this connection failed${detail ? `:\n\n${truncate(detail, 300)}` : '.'}\n\n`
                        + 'Reports sent while it is broken are not queued and retried — they '
                        + 'are logged as failed. Run "Check connection" first unless you know '
                        + 'the problem is already fixed.',
                    variant: 'warning',
                    confirmText: 'Turn it on anyway',
                });
                if (!confirmed) return;
            }
        }
        setBusyFor(existing.id, 'toggle');
        try {
            await api.updateIntegration(existing.id, { enabled: !existing.enabled });
            await load();
        } catch (err: any) {
            setError(err?.message || 'Could not update the connection.');
        } finally {
            setBusyFor(existing.id, null);
        }
    };

    const handleCardTest = async (existing: IntegrationConfig) => {
        setBusyFor(existing.id, 'test');
        try {
            const result = await api.testIntegration(existing.id);
            setCardResult(prev => ({ ...prev, [existing.platform]: result }));
            await refreshAfterAction(existing);
        } catch (err: any) {
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Test failed' } }));
        } finally {
            setBusyFor(existing.id, null);
        }
    };

    const handleSync = async (existing: IntegrationConfig) => {
        setBusyFor(existing.id, 'sync');
        try {
            const response = await api.syncIntegration(existing.id);
            const partly = response.started
                && Object.values(response.started).some(started => !started);
            setCardResult(prev => ({
                ...prev,
                [existing.platform]: {
                    // A partial start is not a success. The endpoint says which
                    // half ran; repeating its message beats replacing it with a
                    // reassurance the server did not give.
                    ok: !partly,
                    detail: partly
                        ? response.message
                        : 'Update check started — new activity will appear within a minute or two.',
                },
            }));
            await refreshAfterAction(existing);
        } catch (err: any) {
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Could not start the update check.' } }));
        } finally {
            setBusyFor(existing.id, null);
        }
    };

    const handleSyncAssets = async (existing: IntegrationConfig) => {
        setBusyFor(existing.id, 'assets');
        try {
            await api.syncIntegrationAssets(existing.id);
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: true, detail: 'Copying their asset list (hydrants, lights, signs…) onto your map. This can take a few minutes.' } }));
            await refreshAfterAction(existing);
        } catch (err: any) {
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Could not start the asset copy.' } }));
        } finally {
            setBusyFor(existing.id, null);
        }
    };

    /** Stop (or resume) the alert emails about one connection.
     *
     * The mute endpoint has always accepted any connector name, including
     * `govtech:accela`, and nothing here offered it -- so the daily digest could
     * name a town system and the only place to silence it was a provider card
     * for something else entirely. Silences the email and nothing else: the card
     * keeps whatever colour the connection has earned. */
    const handleMute = async (existing: IntegrationConfig, currentlyMuted: boolean) => {
        const key = healthKey(existing.platform);
        setMuting(key);
        try {
            const r = await api.muteConnectorAlerts(key, currentlyMuted ? 0 : undefined);
            setMuted(prev => ({ ...prev, [key]: r.muted_until }));
        } catch (err: any) {
            // Leaving the button as it was is the honest failure: claiming a
            // mute that did not take would produce silence nobody asked for.
            setError(err?.message || 'Could not change the alert setting.');
        } finally {
            setMuting(null);
        }
    };

    const handleRegenerateToken = async (existing: IntegrationConfig, name: string) => {
        const confirmed = await dialog.confirm({
            title: `Issue a new address for ${name}?`,
            message: 'The current address stops working immediately. Anything the vendor '
                + 'sends to it will be refused until you give them the new one.\n\n'
                + 'Do this if the address may have been shared or logged somewhere it '
                + 'should not have been.',
            variant: 'warning',
            confirmText: 'Issue a new address',
        });
        if (!confirmed) return;
        setBusyFor(existing.id, 'rotate');
        try {
            const updated = await api.regenerateIntegrationWebhookToken(existing.id);
            setConfigs(prev => [...prev.filter(c => c.platform !== existing.platform), updated]);
            setCardResult(prev => ({ ...prev, [existing.platform]: { ok: true, detail: updated.message } }));
        } catch (err: any) {
            setError(err?.message || 'Could not issue a new address.');
        } finally {
            setBusyFor(existing.id, null);
        }
    };

    const handleDelete = async (existing: IntegrationConfig, name: string) => {
        const confirmed = await dialog.confirm({
            title: `Disconnect ${name}?`,
            message: 'Reports already sent will stay in both systems, but nothing new will '
                + 'sync. The credentials are removed from your Secret Manager too, so '
                + 'reconnecting means entering them again.',
            variant: 'danger',
            confirmText: 'Disconnect',
        });
        if (!confirmed) return;
        setBusyFor(existing.id, 'delete');
        try {
            await api.deleteIntegration(existing.id);
            // closeWizard already reloads; a second load() raced the first and
            // could paint the pre-delete list over the post-delete one.
            closeWizard();
        } catch (err: any) {
            setWizardError(err?.message || 'Could not disconnect.');
        } finally {
            setBusyFor(existing.id, null);
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
        // Deliberately without `cleared`: a field marked for clearing must keep
        // showing its Clear/Keep-it control so the choice can be undone.
        const alreadySet = alreadyStoredIn(existing, field.key, isCredential);
        // Config (non-secret) fields show their current value as the placeholder;
        // secrets show a masked "leave blank to keep" and get a reveal toggle.
        const currentConfigVal = !isCredential ? String((existing?.config as Record<string, unknown>)?.[field.key] ?? '') : '';
        const isCleared = cleared.has(field.key);
        return (
            <div key={field.key}>
                <SecretField
                    label={field.label}
                    secret={!!field.secret}
                    required={field.required}
                    value={values[field.key] || ''}
                    onChange={(v) => setValues(p => ({ ...p, [field.key]: v }))}
                    placeholder={!isCredential && alreadySet && !isCleared ? currentConfigVal : (field.placeholder || '')}
                    help={platform.field_help?.[field.key]}
                    savedHint={!!(isCredential && alreadySet)}
                />
                {/* Blank means "keep what is stored", so emptying the box cannot
                    delete a setting. A wrong jurisdiction_id was therefore
                    permanent. Clearing is asked for by name instead. */}
                {!isCredential && alreadySet && !field.required && (
                    isCleared ? (
                        <p className="text-[11px] text-amber-300/80 mt-1 flex items-center gap-2">
                            Will be cleared when you save.
                            <button
                                type="button"
                                className="underline hover:text-amber-200"
                                onClick={() => setCleared(prev => {
                                    const next = new Set(prev);
                                    next.delete(field.key);
                                    return next;
                                })}
                            >
                                Keep it
                            </button>
                        </p>
                    ) : (
                        <button
                            type="button"
                            className="text-[11px] text-white/45 hover:text-white/70 mt-1 underline"
                            onClick={() => {
                                setValues(p => ({ ...p, [field.key]: '' }));
                                setCleared(prev => new Set(prev).add(field.key));
                            }}
                        >
                            Clear this setting
                        </button>
                    )
                )}
            </div>
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

    /** The sync directions this connector can actually offer. */
    const syncOptionsFor = (platform: IntegrationPlatform) =>
        SYNC_CHOICES(platform.name).filter(c => c.value === 'bidirectional'
            ? platform.capabilities.includes('push') && platform.capabilities.includes('pull')
            : platform.capabilities.includes(c.value));

    // A single possible direction is not a choice, so the panel is hidden and the
    // value pinned. Pinning it happened during render, which is a state update in
    // a render body -- React warns, and under StrictMode it runs twice.
    useEffect(() => {
        if (!wizard) return;
        const options = syncOptionsFor(wizard);
        if (options.length === 1 && syncChoice !== options[0].value) {
            setSyncChoice(options[0].value);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [wizard, syncChoice]);

    // Filter by the clerk's search and surface connected platforms first.
    const q = query.trim().toLowerCase();
    const visibleCatalog = (catalog || [])
        .filter(p => !q || [p.name, p.vendor, p.category].some(s => (s || '').toLowerCase().includes(q)))
        .sort((a, b) => {
            const rank = (p: IntegrationPlatform) => (configFor(p.platform)?.enabled ? 0 : configFor(p.platform) ? 1 : 2);
            return rank(a) - rank(b);
        });

    // ---------- UI ----------

    return (
        <>
        {/* id so the setup page's status rail can link here, the way it does for
            every other section. Without it the rail's "town systems" entry had
            nowhere to scroll to. */}
        <div id="sec-town-systems">
        <CollapsibleSection
            title="Connect Your Other Town Systems"
            icon={Landmark}
            // Counts the catalog, not the filtered view. It read off
            // `visibleCatalog`, so typing in the search box rewrote the heading
            // to "1 platforms available" -- which reads as the town only having
            // one option rather than as a filter being applied.
            subtitle={`${(catalog || []).length} platforms available — Accela, Tyler, CivicPlus, Open311, or a generic connector for anything else`}
            defaultOpen={true}
            /* No connected-count badge. It counted `enabled` rows, and an
             * enabled row is a fact about our database, not about a working
             * connection -- a leftover test row that never synced once showed
             * "1 connected" over a grid of cards that all said otherwise. The
             * cards themselves carry the honest per-platform state, and a
             * headline number that can disagree with every card under it is
             * worse than no number. */
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
            {(catalog || []).length > 4 && (
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

            {/* "Nothing matches" and "we have not asked yet" are different
                answers. This rendered `No platforms match ""` on first paint. */}
            {!loaded && (
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-8 text-center text-white/50 text-sm flex items-center justify-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                    Loading the platforms your town can connect to…
                </div>
            )}

            {loaded && (visibleCatalog || []).length === 0 && (
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-8 text-center text-white/50 text-sm">
                    {query
                        ? <>No platforms match “{query}”. Don’t see yours? The <span className="text-white/70">Generic Open311</span> connector works with many systems.</>
                        : 'No platforms are available to connect.'}
                </div>
            )}

            <div className="relative space-y-2.5">
                {visibleCatalog.map((platform, idx) => {
                    const existing = configFor(platform.platform);
                    const mode = MODE_LABELS[platform.integration_mode] || MODE_LABELS.partner_api;
                    const result = cardResult[platform.platform];
                    const platformLogs = logs[platform.platform];
                    const isOpen = openCards.has(platform.platform);
                    // One word, from the same evidence and the same rules the
                    // capability cards use. Was `enabled && last_sync_status !==
                    // 'error'`, which drew a green "Connected" for a connection
                    // whose credentials had been revoked months ago.
                    const row = existing ? healthRows[healthKey(platform.platform)] : undefined;
                    const state = connectionState(existing, row, result);
                    const needsAttention = state === 'failing';
                    const muteKey = healthKey(platform.platform);
                    const mutedUntil = muteKey in muted
                        ? muted[muteKey]
                        : (row?.alerts_muted_until ?? null);

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
                                    <CapabilityTile
                                        icon={Plug}
                                        tone={needsAttention ? 'alert' : state === 'working' ? 'done' : 'normal'}
                                    />
                                    <div className="min-w-0">
                                        <h3 className="font-semibold text-white tracking-tight">{platform.name}</h3>
                                        <p className="text-white/60 text-xs truncate">{platform.category}</p>
                                    </div>
                                </div>
                                <div className="shrink-0 flex items-center gap-2">
                                    {state && (
                                        <StatusPill state={state} label={connectionStateLabel(existing, state)} />
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

                            {/* What the last check actually found, from the same
                                health row the provider cards read. The card had
                                only ever shown sync outcomes, so a connection
                                whose credentials were rejected an hour ago could
                                still show nothing but "Last checked … all good". */}
                            {row && (row.last_result || row.summary) && (
                                <p className={`relative text-[11px] mt-2 ${
                                    needsAttention ? 'text-red-200/85' : 'text-white/60'}`}>
                                    {truncate(row.last_result || row.summary || '')}
                                </p>
                            )}

                            {mutedUntil && (
                                <p className="relative text-[11px] mt-2 text-amber-200/85">
                                    Nobody is being emailed about this until{' '}
                                    {new Date(mutedUntil).toLocaleDateString()}.
                                    {needsAttention ? ' It is still not working.' : ''}
                                </p>
                            )}

                            {existing?.last_sync_at && (
                                <div className={`relative text-[11px] mt-2 ${existing.last_sync_status === 'error' ? 'text-amber-300' : 'text-white/60'}`}>
                                    {existing.last_sync_status === 'error' ? (
                                        <>
                                            <p>The last update check hit a problem:</p>
                                            {/* The vendor's own words. `last_sync_error` was
                                                fetched and never rendered, so the card said
                                                "hit a problem" and the only way to find out
                                                which problem was to press another button. */}
                                            {existing.last_sync_error && (
                                                <p className="text-amber-200/70 mt-0.5 break-words">
                                                    {truncate(existing.last_sync_error)}
                                                </p>
                                            )}
                                            <p className="text-amber-300/60 mt-0.5">
                                                Open Activity for the full message, or press “Check connection”
                                                for a plain-language explanation.
                                            </p>
                                        </>
                                    ) : (
                                        <p>Last checked {new Date(existing.last_sync_at).toLocaleString()} — all good.</p>
                                    )}
                                </div>
                            )}

                            {existing && existing.credentials_vaulted_state !== 'none' && (
                                existing.credentials_vaulted_state === 'partial' ? (
                                    /* Said plainly, because the reassuring version of this
                                       line used to appear whenever *any* field made it to
                                       the vault -- over-claiming exactly where a government
                                       deployment is relying on the claim. */
                                    <p className="relative text-[11px] mt-2 flex items-center gap-1.5 text-amber-300/80">
                                        <AlertCircle className="w-3 h-3 shrink-0" aria-hidden="true" />
                                        Some credentials are in your Secret Manager and some are stored
                                        encrypted in this app's database. Re-save them to move the rest.
                                    </p>
                                ) : (
                                    <p className="relative text-[11px] mt-2 flex items-center gap-1.5 text-emerald-300/80">
                                        <ShieldCheck className="w-3 h-3 shrink-0" aria-hidden="true" />
                                        Credentials stored in your Secret Manager — not in this app's database.
                                    </p>
                                )
                            )}

                            {result && (
                                <div className={`relative mt-2 rounded-lg px-3 py-2 text-xs border ${!result.ok
                                    ? 'bg-amber-500/10 border-amber-500/25 text-amber-200'
                                    : result.verified === false
                                        ? 'bg-sky-500/10 border-sky-500/25 text-sky-200'
                                        : 'bg-emerald-500/10 border-emerald-500/25 text-emerald-200'}`}>
                                    {/* A pass that verified nothing is not a pass in the sense a
                                        clerk reads "Connected" as. Open311 has no authenticated
                                        endpoint at all, so saying so is the only honest option. */}
                                    {result.ok && result.verified === false && (
                                        <span className="font-semibold block mb-0.5">Reachable — credentials not checked</span>
                                    )}
                                    {result.ok ? result.detail : (result.friendly || result.detail)}
                                </div>
                            )}

                            {/* The inbound address and the vendor email were reachable
                                only inside the wizard -- the address on its success
                                screen, the email on an intro step you could get back to
                                only by pressing Back. Both are things somebody needs
                                weeks later, when the vendor finally replies. */}
                            {existing && (
                                <div className="relative mt-3 space-y-2">
                                    {(() => {
                                        const url = webhookUrl(existing);
                                        if (!url) return null;
                                        return (
                                            <div className="rounded-lg bg-white/[0.03] border border-white/10 p-2.5">
                                                <p className="text-white/60 text-[11px] mb-1.5">
                                                    Inbound address for {platform.name} — the mailbox only they drop into.
                                                </p>
                                                <div className="flex items-center gap-2">
                                                    <code className="flex-1 bg-black/30 rounded px-2 py-1.5 text-[10px] text-indigo-200 break-all">{url}</code>
                                                    <Button size="sm" variant="ghost" onClick={() => copyText(`hook:${platform.platform}`, url)} aria-label="Copy the inbound address">
                                                        {copied === `hook:${platform.platform}` ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                                                    </Button>
                                                </div>
                                                <button
                                                    type="button"
                                                    onClick={() => handleRegenerateToken(existing, platform.name)}
                                                    disabled={busyOf(existing) !== null}
                                                    className="text-[10px] text-white/40 hover:text-white/70 underline mt-1.5 disabled:opacity-50"
                                                >
                                                    {busyOf(existing) === 'rotate' ? 'Issuing…' : 'Issue a new address'}
                                                </button>
                                            </div>
                                        );
                                    })()}
                                    {platform.vendor_ask && (
                                        <Button
                                            size="sm" variant="ghost" className="text-xs"
                                            onClick={() => copyText(`mail:${platform.platform}`, `Subject: ${platform.vendor_ask!.subject}\n\n${emailBody(platform)}`)}
                                            leftIcon={copied === `mail:${platform.platform}` ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Mail className="w-3.5 h-3.5" />}
                                        >
                                            {copied === `mail:${platform.platform}` ? 'Copied — paste it into an email' : 'Copy the vendor request email'}
                                        </Button>
                                    )}
                                </div>
                            )}

                            <div className="relative flex flex-wrap items-center gap-2 mt-4">
                                {!existing ? (
                                    <button
                                        className="shimmer-sweep inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold text-white bg-gradient-to-r from-primary-400 to-primary-600 hover:from-primary-300 hover:to-primary-500 border border-primary-300/40 shadow-lg shadow-primary-900/60 transition-all hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                        onClick={() => openWizard(platform, 'intro')}
                                    >
                                        <Plug className="w-4 h-4" /> Set up — about 10 minutes
                                    </button>
                                ) : (
                                    <>
                                        <Action size="sm" variant="primary" onClick={() => openWizard(platform, 'details')} chevron>
                                            Settings
                                        </Action>
                                        <Action size="sm" onClick={() => handleCardTest(existing)}
                                            busy={busyOf(existing) === 'test'} disabled={busyOf(existing) !== null}>
                                            {busyOf(existing) === 'test' ? 'Checking…' : 'Check connection'}
                                        </Action>
                                        {/* Only where something is actually alerting, and where
                                            a mute is already in force. Same rule as the provider
                                            cards: offering to silence a connector nobody is being
                                            emailed about is offering to stop a sound that was
                                            never going to be made. */}
                                        {(hasAlert(row?.status) || !!mutedUntil) && (
                                            <Action size="sm" onClick={() => handleMute(existing, !!mutedUntil)}
                                                busy={muting === muteKey} disabled={muting !== null}
                                                title={mutedUntil
                                                    ? 'Start emailing administrators about this again'
                                                    : 'Stop emailing administrators about this for a week. The card stays as it is.'}>
                                                {mutedUntil ? 'Unmute' : 'Mute alerts'}
                                            </Action>
                                        )}
                                        {existing.enabled && platform.capabilities.includes('pull') && (
                                            <Action size="sm" onClick={() => handleSync(existing)}
                                                busy={busyOf(existing) === 'sync'} disabled={busyOf(existing) !== null}>
                                                {/* The only button here that never said it was
                                                    working, so pressing it looked like nothing
                                                    happened -- which is also what a broken one
                                                    looks like. */}
                                                {busyOf(existing) === 'sync' ? 'Checking…' : 'Check for updates'}
                                            </Action>
                                        )}
                                        {existing.enabled && platform.capabilities.includes('assets') && (
                                            <Action size="sm" onClick={() => handleSyncAssets(existing)}
                                                busy={busyOf(existing) === 'assets'} disabled={busyOf(existing) !== null}>
                                                {busyOf(existing) === 'assets' ? 'Copying…' : 'Copy their assets to my map'}
                                            </Action>
                                        )}
                                        <Action size="sm" onClick={() => toggleLogs(existing)} chevron>
                                            Activity
                                        </Action>
                                        <label className="flex items-center gap-2 ml-auto text-[11px] text-white/60 cursor-pointer select-none">
                                            {existing.enabled ? 'On' : 'Off'}
                                            <button
                                                onClick={() => handleToggle(existing, platform.name)}
                                                disabled={busyOf(existing) !== null}
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
                                    {/* The current error in full, pinned above the history.
                                        Somebody who opened this drawer opened it to read the
                                        message, and the card only had room to clip it. */}
                                    {existing?.last_sync_status === 'error' && existing.last_sync_error && (
                                        <div className="px-3 py-2 bg-amber-500/[0.06]">
                                            <p className="text-amber-200 text-[11px] font-semibold">Most recent problem</p>
                                            <p className="text-amber-100/70 text-[11px] mt-0.5 break-words whitespace-pre-wrap">
                                                {existing.last_sync_error}
                                            </p>
                                        </div>
                                    )}
                                    {(platformLogs || []).length === 0 && (
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
        </div>

        {/* ---------- Setup wizard ---------- */}
        {wizard && (
                <Modal
                    isOpen={true}
                    onClose={closeWizard}
                    title={step === 'intro' ? `Connect ${wizard.name}` : step === 'details' ? `Connect ${wizard.name} — enter the details` : `Connect ${wizard.name} — final check`}
                    size="lg"
                >
                    {/* Step dots, plus the same thing in words.
                        The dots were aria-hidden with no textual equivalent, so a
                        screen-reader user had no way to know this was step 2 of 3 --
                        the one piece of orientation a multi-step form owes them. */}
                    <div className="flex items-center justify-between gap-3 mb-4">
                        <div className="flex items-center gap-2" aria-hidden="true">
                            {(['intro', 'details', 'finish'] as WizardStep[]).map((s) => (
                                <div key={s} className={`h-1.5 rounded-full transition-all ${step === s ? 'w-8 bg-indigo-400' : 'w-4 bg-white/15'}`} />
                            ))}
                        </div>
                        <p className="text-white/50 text-[11px]">
                            Step {step === 'intro' ? 1 : step === 'details' ? 2 : 3} of 3
                            <span className="sr-only">
                                {step === 'intro' ? ': what you need' : step === 'details' ? ': enter the details' : ': final check'}
                            </span>
                        </p>
                    </div>

                    {/* Inside the modal, because the shared banner renders behind it.
                        A failed save made "Save & check the connection" appear to do
                        nothing at all: the error was written, the step did not
                        advance, and the only visible change was the spinner
                        stopping. */}
                    {wizardError && (
                        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-start gap-2">
                            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                            <span className="break-words">{wizardError}</span>
                        </div>
                    )}

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
                                const syncOptions = syncOptionsFor(wizard);
                                // A single possible direction isn't a choice — don't ask. The
                                // value is pinned by an effect above, not here: setting state
                                // during render is what React warns about.
                                if ((syncOptions || []).length <= 1) return null;
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
                                    {/* Two different outcomes, and they were shown identically.
                                        "The connection works" is a claim about the credentials;
                                        for Open311, or a vendor with no key saved, nothing here
                                        has tested them and the first thing to find out otherwise
                                        would be a report that never arrived. */}
                                    <div className="flex flex-col items-center py-4 text-center">
                                        {testResult.verified === false ? (
                                            <>
                                                <div className="w-14 h-14 rounded-full bg-sky-500/20 border border-sky-500/40 flex items-center justify-center mb-3">
                                                    <CheckCircle className="w-7 h-7 text-sky-300" />
                                                </div>
                                                <h4 className="text-white font-semibold">Reachable — and switched on</h4>
                                                <p className="text-white/50 text-sm mt-1 max-w-sm">
                                                    We reached {wizard.name} and turned the connection on. Nothing here
                                                    could test your credentials, though:
                                                </p>
                                                <p className="text-sky-200/80 text-xs mt-2 max-w-sm">{testResult.detail}</p>
                                                <p className="text-white/40 text-xs mt-2 max-w-sm">
                                                    Send yourself a test report to confirm it arrives at their end.
                                                </p>
                                            </>
                                        ) : (
                                            <>
                                                <div className="w-14 h-14 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center mb-3">
                                                    <PartyPopper className="w-7 h-7 text-emerald-300" />
                                                </div>
                                                <h4 className="text-white font-semibold">You're connected!</h4>
                                                <p className="text-white/50 text-sm mt-1 max-w-sm">
                                                    The credentials were accepted and the connection has been turned on.
                                                    New resident reports will now flow to {wizard.name} automatically.
                                                </p>
                                            </>
                                        )}
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
