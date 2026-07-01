import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
    Landmark, CheckCircle, AlertCircle, ExternalLink, RefreshCw,
    Plug, Trash2, Copy, Check, Mail, ClipboardList, Loader2, ArrowLeft,
    ChevronDown, ChevronUp, PartyPopper
} from 'lucide-react';

import { Button, Input, Modal } from './ui';
import {
    api, IntegrationPlatform, IntegrationConfig, IntegrationSyncLog, IntegrationTestResult,
} from '../services/api';

const MODE_LABELS: Record<string, { label: string; className: string }> = {
    public_api: { label: 'Works with your account login', className: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
    open311: { label: 'Works with a standard address + key', className: 'bg-sky-500/20 text-sky-300 border-sky-500/30' },
    partner_api: { label: 'Vendor sends you the details', className: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
};

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
        platform.credential_fields.forEach(f => { if (values[f.key]) credentials[f.key] = values[f.key]; });
        platform.config_fields.forEach(f => { if (values[f.key] !== undefined && values[f.key] !== '') config[f.key] = values[f.key]; });

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
            ? existing?.configured_credentials.includes(field.key)
            : existing !== undefined && (existing.config as Record<string, unknown>)[field.key] !== undefined;
        const help = platform.field_help?.[field.key];
        return (
            <div key={field.key}>
                <label className="text-sm text-white/70 mb-1 block font-medium">
                    {field.label}
                    {field.required && !alreadySet && <span className="text-amber-300"> (required)</span>}
                    {alreadySet && <span className="text-green-400 text-xs ml-2 inline-flex items-center gap-1"><CheckCircle className="w-3 h-3" /> already saved</span>}
                </label>
                <Input
                    type={field.secret ? 'password' : 'text'}
                    placeholder={alreadySet
                        ? (isCredential ? 'Saved — leave blank to keep it' : String((existing?.config as Record<string, unknown>)?.[field.key] ?? ''))
                        : (field.placeholder || '')}
                    value={values[field.key] || ''}
                    onChange={(e) => setValues(p => ({ ...p, [field.key]: e.target.value }))}
                    className="text-sm"
                />
                {help && <p className="text-white/40 text-xs mt-1">{help}</p>}
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

    const connectedCount = configs.filter(c => c.enabled).length;

    // ---------- UI ----------

    return (
        <div>
            <h2 className="text-lg font-semibold text-white mb-1 flex items-center gap-2">
                <Landmark className="w-5 h-5 text-indigo-400" />
                Connect Your Other Town Systems
            </h2>
            <p className="text-white/50 text-sm mb-4">
                If your town also uses one of these systems, connect it and resident reports, photos, comments,
                and status updates will flow between them automatically — no double entry.
                {connectedCount > 0 && <span className="text-emerald-300"> {connectedCount} connected.</span>}
            </p>

            {error && (
                <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0" /> {error}
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {catalog.map((platform, idx) => {
                    const existing = configFor(platform.platform);
                    const mode = MODE_LABELS[platform.integration_mode] || MODE_LABELS.partner_api;
                    const result = cardResult[platform.platform];
                    const platformLogs = logs[platform.platform];
                    const isWorking = existing?.enabled && existing.last_sync_status !== 'error';
                    const needsAttention = existing?.enabled && existing.last_sync_status === 'error';

                    return (
                        <motion.div
                            key={platform.platform}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: idx * 0.04 }}
                            className={`relative rounded-2xl border backdrop-blur-xl p-5 transition-all duration-300 ${isWorking
                                ? 'bg-gradient-to-br from-indigo-500/10 via-violet-500/5 to-purple-500/10 border-indigo-500/30 shadow-lg shadow-indigo-500/10'
                                : needsAttention
                                    ? 'bg-amber-500/5 border-amber-500/30'
                                    : 'bg-white/5 border-white/10 hover:border-white/20'
                                }`}
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex items-center gap-3 min-w-0">
                                    <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${existing?.enabled
                                        ? 'bg-gradient-to-br from-indigo-400 to-violet-500 shadow-lg shadow-indigo-500/30'
                                        : 'bg-gradient-to-br from-slate-600/50 to-slate-700/50'
                                        }`}>
                                        <Plug className="w-5 h-5 text-white" />
                                    </div>
                                    <div className="min-w-0">
                                        <h3 className="font-semibold text-white truncate">{platform.name}</h3>
                                        <p className="text-white/40 text-xs truncate">{platform.category}</p>
                                    </div>
                                </div>
                                <div className="shrink-0">
                                    {isWorking ? (
                                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                                            <CheckCircle className="w-3 h-3" /> Connected
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
                                        <span className="text-white/30 text-xs">Not connected</span>
                                    )}
                                </div>
                            </div>

                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border mt-3 ${mode.className}`}>
                                {mode.label}
                            </span>

                            <p className="text-white/50 text-xs mt-2 leading-relaxed">{platform.plain_summary || platform.description}</p>

                            {existing?.last_sync_at && (
                                <p className={`text-[11px] mt-2 ${existing.last_sync_status === 'error' ? 'text-amber-300' : 'text-white/40'}`}>
                                    {existing.last_sync_status === 'error'
                                        ? 'The last update check hit a problem — press "Check connection" for a plain-language explanation.'
                                        : `Last checked ${new Date(existing.last_sync_at).toLocaleString()} — all good.`}
                                </p>
                            )}

                            {result && (
                                <div className={`mt-2 rounded-lg px-3 py-2 text-xs border ${result.ok
                                    ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-200'
                                    : 'bg-amber-500/10 border-amber-500/25 text-amber-200'}`}>
                                    {result.ok ? result.detail : (result.friendly || result.detail)}
                                </div>
                            )}

                            <div className="flex flex-wrap items-center gap-2 mt-4">
                                {!existing ? (
                                    <Button
                                        size="sm"
                                        className="bg-gradient-to-r from-indigo-500 to-violet-600 hover:from-indigo-600 hover:to-violet-700"
                                        onClick={() => openWizard(platform, 'intro')}
                                    >
                                        Set up — takes about 10 minutes
                                    </Button>
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
                                        <label className="flex items-center gap-1.5 ml-auto text-[11px] text-white/50 cursor-pointer select-none">
                                            {existing.enabled ? 'On' : 'Off'}
                                            <button
                                                onClick={() => handleToggle(existing)}
                                                disabled={busy !== null}
                                                className={`relative inline-flex items-center rounded-full transition-colors duration-300 shrink-0 ${existing.enabled ? 'bg-indigo-500 shadow-lg shadow-indigo-500/30' : 'bg-slate-600'}`}
                                                style={{ width: 40, height: 22, padding: 0 }}
                                                role="switch"
                                                aria-checked={existing.enabled}
                                                aria-label={`Turn ${platform.name} connection ${existing.enabled ? 'off' : 'on'}`}
                                            >
                                                <span
                                                    className={`inline-block rounded-full bg-white shadow-md transition-transform duration-300 ${existing.enabled ? 'translate-x-[22px]' : 'translate-x-1'}`}
                                                    style={{ width: 14, height: 14 }}
                                                    aria-hidden="true"
                                                />
                                            </button>
                                        </label>
                                    </>
                                )}
                            </div>

                            {logsOpen === platform.platform && platformLogs && (
                                <div className="mt-3 rounded-lg border border-white/10 divide-y divide-white/5 max-h-48 overflow-y-auto">
                                    {platformLogs.length === 0 && (
                                        <p className="text-white/30 text-xs px-3 py-2">Nothing has synced yet. Activity will show up here once reports start flowing.</p>
                                    )}
                                    {platformLogs.map(entry => (
                                        <div key={entry.id} className="px-3 py-2 flex items-start gap-2">
                                            {entry.status === 'success'
                                                ? <CheckCircle className="w-3.5 h-3.5 text-green-400 mt-0.5 shrink-0" />
                                                : <AlertCircle className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />}
                                            <div className="min-w-0">
                                                <p className="text-white/70 text-xs">{entry.detail || entry.operation}</p>
                                                <p className="text-white/30 text-[10px]">{entry.created_at ? new Date(entry.created_at).toLocaleString() : ''}</p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </motion.div>
                    );
                })}
            </div>

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
                                    <p className="text-white/40 text-xs mt-2">
                                        You can close this window and come back once they reply — nothing is lost.
                                    </p>
                                </div>
                            )}

                            <div className="flex items-center justify-between pt-2">
                                <a href={wizard.docs_url} target="_blank" rel="noopener noreferrer" className="text-indigo-300 text-xs hover:underline inline-flex items-center gap-1">
                                    {wizard.vendor} website <ExternalLink className="w-3 h-3" />
                                </a>
                                <Button
                                    className="bg-gradient-to-r from-indigo-500 to-violet-600 hover:from-indigo-600 hover:to-violet-700"
                                    onClick={() => setStep('details')}
                                >
                                    I have these — continue
                                </Button>
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
                                        className="text-white/40 text-xs hover:text-white/70 inline-flex items-center gap-1"
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

                            <div className="rounded-xl bg-white/[0.04] border border-white/10 p-4">
                                <h4 className="text-white font-semibold text-sm mb-2">How should the two systems work together?</h4>
                                <div className="space-y-2">
                                    {SYNC_CHOICES(wizard.name)
                                        .filter(c => c.value === 'bidirectional'
                                            ? wizard.capabilities.includes('push') && wizard.capabilities.includes('pull')
                                            : wizard.capabilities.includes(c.value))
                                        .map(choice => (
                                            <label key={choice.value} className={`flex items-start gap-2.5 rounded-lg px-3 py-2 cursor-pointer border transition-colors ${syncChoice === choice.value ? 'bg-indigo-500/15 border-indigo-500/40' : 'border-transparent hover:bg-white/5'}`}>
                                                <input
                                                    type="radio"
                                                    name="sync-choice"
                                                    className="mt-1 accent-indigo-500"
                                                    checked={syncChoice === choice.value}
                                                    onChange={() => setSyncChoice(choice.value)}
                                                />
                                                <span>
                                                    <span className="text-white/80 text-sm block">
                                                        {choice.label}
                                                        {choice.value === (wizard.recommended_sync_direction || 'bidirectional') && (
                                                            <span className="text-emerald-300 text-xs ml-2">Recommended</span>
                                                        )}
                                                    </span>
                                                    <span className="text-white/40 text-xs">{choice.help}</span>
                                                </span>
                                            </label>
                                        ))}
                                </div>
                            </div>

                            {requiredMissing(wizard).length > 0 && (
                                <p className="text-amber-300/80 text-xs">
                                    Still needed before we can continue: {requiredMissing(wizard).join(', ')}
                                </p>
                            )}

                            <div className="flex items-center justify-between pt-2">
                                <Button variant="ghost" size="sm" onClick={() => setStep('intro')} leftIcon={<ArrowLeft className="w-3.5 h-3.5" />}>
                                    Back
                                </Button>
                                <div className="flex items-center gap-2">
                                    {configFor(wizard.platform) && (
                                        <Button size="sm" variant="ghost" className="text-xs text-red-300 hover:text-red-200"
                                            onClick={() => handleDelete(configFor(wizard.platform)!, wizard.name)}
                                            leftIcon={<Trash2 className="w-3.5 h-3.5" />}>
                                            Disconnect
                                        </Button>
                                    )}
                                    <Button
                                        className="bg-gradient-to-r from-indigo-500 to-violet-600 hover:from-indigo-600 hover:to-violet-700"
                                        onClick={() => goToFinish(wizard)}
                                        disabled={saving || requiredMissing(wizard).length > 0}
                                    >
                                        {saving ? 'Saving…' : 'Save & check the connection'}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    )}

                    {step === 'finish' && (
                        <div className="space-y-4">
                            {testing && (
                                <div className="flex flex-col items-center py-8 text-center">
                                    <Loader2 className="w-8 h-8 text-indigo-300 animate-spin mb-3" />
                                    <p className="text-white/70 text-sm">Checking the connection to {wizard.name}…</p>
                                    <p className="text-white/40 text-xs mt-1">This usually takes a few seconds.</p>
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
                                        <Button className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700" onClick={closeWizard}>
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
                                    <p className="text-white/40 text-xs">
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
        </div>
    );
}
