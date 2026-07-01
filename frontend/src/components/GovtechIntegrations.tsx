import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Landmark, CheckCircle, AlertCircle, ChevronDown, ChevronUp,
    ExternalLink, RefreshCw, Plug, Trash2, Copy, Check, Zap
} from 'lucide-react';

import { Button, Input, Select, Badge } from './ui';
import {
    api, IntegrationPlatform, IntegrationConfig, IntegrationSyncLog,
} from '../services/api';

const MODE_LABELS: Record<string, { label: string; className: string }> = {
    public_api: { label: 'Public API', className: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
    open311: { label: 'Open311 Standard', className: 'bg-sky-500/20 text-sky-300 border-sky-500/30' },
    partner_api: { label: 'Vendor-Issued API', className: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
};

export default function GovtechIntegrations() {
    const [catalog, setCatalog] = useState<IntegrationPlatform[]>([]);
    const [configs, setConfigs] = useState<IntegrationConfig[]>([]);
    const [expanded, setExpanded] = useState<string | null>(null);
    const [formValues, setFormValues] = useState<Record<string, Record<string, string>>>({});
    const [syncDirection, setSyncDirection] = useState<Record<string, string>>({});
    const [busy, setBusy] = useState<string | null>(null);
    const [testResult, setTestResult] = useState<Record<string, { ok: boolean; detail: string }>>({});
    const [logs, setLogs] = useState<Record<string, IntegrationSyncLog[]>>({});
    const [copied, setCopied] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [cat, cfgs] = await Promise.all([
                api.getIntegrationCatalog(),
                api.getIntegrations(),
            ]);
            setCatalog(cat);
            setConfigs(cfgs);
        } catch (err: any) {
            setError(err?.message || 'Failed to load integrations');
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const configFor = (platform: string) => configs.find(c => c.platform === platform);

    const setField = (platform: string, key: string, value: string) =>
        setFormValues(prev => ({ ...prev, [platform]: { ...(prev[platform] || {}), [key]: value } }));

    const handleSave = async (platform: IntegrationPlatform) => {
        const existing = configFor(platform.platform);
        const values = formValues[platform.platform] || {};
        const credentials: Record<string, string> = {};
        const config: Record<string, unknown> = {};
        platform.credential_fields.forEach(f => { if (values[f.key]) credentials[f.key] = values[f.key]; });
        platform.config_fields.forEach(f => { if (values[f.key] !== undefined && values[f.key] !== '') config[f.key] = values[f.key]; });

        setBusy(`save:${platform.platform}`);
        setError(null);
        try {
            const direction = syncDirection[platform.platform]
                || existing?.sync_direction
                || (platform.capabilities.includes('pull') ? 'bidirectional' : 'push');
            if (existing) {
                await api.updateIntegration(existing.id, { credentials, config, sync_direction: direction });
            } else {
                await api.createIntegration({
                    platform: platform.platform,
                    credentials,
                    config,
                    sync_direction: direction,
                    enabled: false,
                });
            }
            setFormValues(prev => ({ ...prev, [platform.platform]: {} }));
            await load();
        } catch (err: any) {
            setError(err?.message || 'Failed to save integration');
        } finally {
            setBusy(null);
        }
    };

    const handleToggle = async (existing: IntegrationConfig) => {
        setBusy(`toggle:${existing.platform}`);
        try {
            await api.updateIntegration(existing.id, { enabled: !existing.enabled });
            await load();
        } catch (err: any) {
            setError(err?.message || 'Failed to update integration');
        } finally {
            setBusy(null);
        }
    };

    const handleTest = async (existing: IntegrationConfig) => {
        setBusy(`test:${existing.platform}`);
        try {
            const result = await api.testIntegration(existing.id);
            setTestResult(prev => ({ ...prev, [existing.platform]: result }));
        } catch (err: any) {
            setTestResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Test failed' } }));
        } finally {
            setBusy(null);
        }
    };

    const handleSync = async (existing: IntegrationConfig) => {
        setBusy(`sync:${existing.platform}`);
        try {
            await api.syncIntegration(existing.id);
            setTestResult(prev => ({ ...prev, [existing.platform]: { ok: true, detail: 'Sync queued — check sync activity in a minute' } }));
        } catch (err: any) {
            setTestResult(prev => ({ ...prev, [existing.platform]: { ok: false, detail: err?.message || 'Sync failed to start' } }));
        } finally {
            setBusy(null);
        }
    };

    const handleDelete = async (existing: IntegrationConfig) => {
        if (!window.confirm(`Disconnect ${existing.platform_name}? Credentials and sync history will be removed.`)) return;
        setBusy(`delete:${existing.platform}`);
        try {
            await api.deleteIntegration(existing.id);
            await load();
        } catch (err: any) {
            setError(err?.message || 'Failed to delete integration');
        } finally {
            setBusy(null);
        }
    };

    const loadLogs = async (existing: IntegrationConfig) => {
        try {
            const entries = await api.getIntegrationLogs(existing.id);
            setLogs(prev => ({ ...prev, [existing.platform]: entries }));
        } catch { /* non-fatal */ }
    };

    const copyWebhook = (platform: string, path: string) => {
        navigator.clipboard.writeText(`${window.location.origin}${path}`);
        setCopied(platform);
        setTimeout(() => setCopied(null), 2000);
    };

    const connectedCount = configs.filter(c => c.enabled).length;

    return (
        <div>
            <h2 className="text-lg font-semibold text-white mb-1 flex items-center gap-2">
                <Landmark className="w-5 h-5 text-indigo-400" />
                GovTech Platform Connections
            </h2>
            <p className="text-white/50 text-sm mb-4">
                Two-way sync with municipal systems of record — requests pushed on submission, status changes mirrored back every 15 minutes.
                {connectedCount > 0 && <span className="text-emerald-300"> {connectedCount} active connection{connectedCount > 1 ? 's' : ''}.</span>}
            </p>

            {error && (
                <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0" /> {error}
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {catalog.map((platform, idx) => {
                    const existing = configFor(platform.platform);
                    const isOpen = expanded === platform.platform;
                    const mode = MODE_LABELS[platform.integration_mode] || MODE_LABELS.partner_api;
                    const values = formValues[platform.platform] || {};
                    const result = testResult[platform.platform];
                    const platformLogs = logs[platform.platform];

                    return (
                        <motion.div
                            key={platform.platform}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: idx * 0.04 }}
                            className={`relative rounded-2xl border backdrop-blur-xl p-5 transition-all duration-300 ${existing?.enabled
                                ? 'bg-gradient-to-br from-indigo-500/10 via-violet-500/5 to-purple-500/10 border-indigo-500/30 shadow-lg shadow-indigo-500/10'
                                : 'bg-white/5 border-white/10 hover:border-white/20'
                                } ${isOpen ? 'md:col-span-2' : ''}`}
                        >
                            {/* Card header */}
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
                                <div className="flex items-center gap-2 shrink-0">
                                    {existing?.enabled ? (
                                        <Badge variant="success">Active</Badge>
                                    ) : existing ? (
                                        <Badge variant="warning">Configured</Badge>
                                    ) : (
                                        <span className="text-white/30 text-xs">Not connected</span>
                                    )}
                                </div>
                            </div>

                            <div className="flex items-center gap-2 mt-3">
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${mode.className}`}>
                                    {mode.label}
                                </span>
                                <span className="text-white/30 text-[10px]">{platform.capabilities.filter(c => c !== 'test').join(' · ')}</span>
                            </div>

                            <p className="text-white/50 text-xs mt-2 leading-relaxed">{platform.description}</p>

                            {/* Last sync line */}
                            {existing?.last_sync_at && (
                                <p className={`text-[11px] mt-2 ${existing.last_sync_status === 'error' ? 'text-red-300' : 'text-white/40'}`}>
                                    Last sync {new Date(existing.last_sync_at).toLocaleString()} — {existing.last_sync_status}
                                    {existing.last_sync_error ? `: ${existing.last_sync_error.slice(0, 120)}` : ''}
                                </p>
                            )}

                            {/* Test/sync result */}
                            {result && (
                                <div className={`mt-2 rounded-lg px-3 py-2 text-xs border ${result.ok
                                    ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-200'
                                    : 'bg-red-500/10 border-red-500/25 text-red-200'}`}>
                                    {result.detail}
                                </div>
                            )}

                            {/* Actions */}
                            <div className="flex flex-wrap items-center gap-2 mt-4">
                                <Button
                                    size="sm"
                                    variant="ghost"
                                    className="text-xs"
                                    onClick={() => setExpanded(isOpen ? null : platform.platform)}
                                    rightIcon={isOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                                >
                                    {existing ? 'Settings' : 'Connect'}
                                </Button>
                                {existing && (
                                    <>
                                        <Button size="sm" variant="ghost" className="text-xs" onClick={() => handleTest(existing)} disabled={busy !== null}>
                                            {busy === `test:${platform.platform}` ? 'Testing…' : 'Test Connection'}
                                        </Button>
                                        {existing.enabled && platform.capabilities.includes('pull') && (
                                            <Button size="sm" variant="ghost" className="text-xs" onClick={() => handleSync(existing)} disabled={busy !== null} leftIcon={<RefreshCw className="w-3 h-3" />}>
                                                Sync Now
                                            </Button>
                                        )}
                                        <button
                                            onClick={() => handleToggle(existing)}
                                            disabled={busy !== null}
                                            className={`relative inline-flex items-center rounded-full transition-colors duration-300 shrink-0 ml-auto ${existing.enabled ? 'bg-indigo-500 shadow-lg shadow-indigo-500/30' : 'bg-slate-600'}`}
                                            style={{ width: 40, height: 22, padding: 0 }}
                                            role="switch"
                                            aria-checked={existing.enabled}
                                            aria-label={`Toggle ${platform.name}`}
                                        >
                                            <span
                                                className={`inline-block rounded-full bg-white shadow-md transition-transform duration-300 ${existing.enabled ? 'translate-x-[22px]' : 'translate-x-1'}`}
                                                style={{ width: 14, height: 14 }}
                                                aria-hidden="true"
                                            />
                                        </button>
                                    </>
                                )}
                            </div>

                            {/* Expanded settings */}
                            <AnimatePresence>
                                {isOpen && (
                                    <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: 'auto', opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        className="overflow-hidden"
                                    >
                                        <div className="mt-4 pt-4 border-t border-white/10 space-y-4">
                                            <div className="rounded-lg bg-white/[0.03] border border-white/10 px-3 py-2.5">
                                                <p className="text-white/50 text-xs leading-relaxed">
                                                    <Zap className="w-3 h-3 inline mr-1 text-amber-300" />
                                                    {platform.setup_notes}{' '}
                                                    <a href={platform.docs_url} target="_blank" rel="noopener noreferrer" className="text-indigo-300 hover:underline inline-flex items-center gap-0.5">
                                                        Vendor docs <ExternalLink className="w-3 h-3" />
                                                    </a>
                                                </p>
                                            </div>

                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                {/* Config fields */}
                                                {platform.config_fields.map(field => (
                                                    <div key={field.key}>
                                                        <label className="text-xs text-white/50 mb-1 block">
                                                            {field.label}{field.required && <span className="text-amber-300"> *</span>}
                                                            {existing && (existing.config as Record<string, unknown>)[field.key] !== undefined && (
                                                                <CheckCircle className="w-3 h-3 inline ml-1 text-green-400" />
                                                            )}
                                                        </label>
                                                        <Input
                                                            type="text"
                                                            placeholder={String((existing?.config as Record<string, unknown> | undefined)?.[field.key] ?? field.placeholder ?? '')}
                                                            value={values[field.key] || ''}
                                                            onChange={(e) => setField(platform.platform, field.key, e.target.value)}
                                                            className="text-sm"
                                                        />
                                                    </div>
                                                ))}
                                                {/* Credential fields */}
                                                {platform.credential_fields.map(field => (
                                                    <div key={field.key}>
                                                        <label className="text-xs text-white/50 mb-1 block">
                                                            {field.label}
                                                            {existing?.configured_credentials.includes(field.key) && (
                                                                <CheckCircle className="w-3 h-3 inline ml-1 text-green-400" />
                                                            )}
                                                        </label>
                                                        <Input
                                                            type={field.secret ? 'password' : 'text'}
                                                            placeholder={existing?.configured_credentials.includes(field.key) ? '•••••• (saved — leave blank to keep)' : '...'}
                                                            value={values[field.key] || ''}
                                                            onChange={(e) => setField(platform.platform, field.key, e.target.value)}
                                                            className="text-sm"
                                                        />
                                                    </div>
                                                ))}
                                                {/* Sync direction */}
                                                <div>
                                                    <label className="text-xs text-white/50 mb-1 block">Sync Direction</label>
                                                    <Select
                                                        options={[
                                                            { value: 'push', label: 'Push only (Pinpoint → platform)' },
                                                            { value: 'pull', label: 'Pull only (platform → Pinpoint)' },
                                                            { value: 'bidirectional', label: 'Bidirectional' },
                                                        ]}
                                                        value={syncDirection[platform.platform] || existing?.sync_direction || 'push'}
                                                        onChange={(e) => setSyncDirection(prev => ({ ...prev, [platform.platform]: e.target.value }))}
                                                    />
                                                </div>
                                            </div>

                                            {/* Inbound webhook URL */}
                                            {existing && (
                                                <div>
                                                    <label className="text-xs text-white/50 mb-1 block">Inbound Webhook URL (give this to the vendor for intake into Pinpoint)</label>
                                                    <div className="flex items-center gap-2">
                                                        <code className="flex-1 bg-black/30 rounded-lg px-3 py-2 text-[11px] text-indigo-200 break-all">
                                                            {window.location.origin}{existing.webhook_path}
                                                        </code>
                                                        <Button size="sm" variant="ghost" onClick={() => copyWebhook(platform.platform, existing.webhook_path)}>
                                                            {copied === platform.platform ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                                                        </Button>
                                                    </div>
                                                </div>
                                            )}

                                            <div className="flex flex-wrap items-center gap-2">
                                                <Button
                                                    size="sm"
                                                    className="bg-gradient-to-r from-indigo-500 to-violet-600 hover:from-indigo-600 hover:to-violet-700"
                                                    onClick={() => handleSave(platform)}
                                                    disabled={busy !== null}
                                                >
                                                    {busy === `save:${platform.platform}` ? 'Saving…' : existing ? 'Save Changes' : 'Save & Connect'}
                                                </Button>
                                                {existing && (
                                                    <>
                                                        <Button size="sm" variant="ghost" className="text-xs" onClick={() => loadLogs(existing)}>
                                                            {platformLogs ? 'Refresh Activity' : 'View Sync Activity'}
                                                        </Button>
                                                        <Button size="sm" variant="ghost" className="text-xs text-red-300 hover:text-red-200 ml-auto" onClick={() => handleDelete(existing)} leftIcon={<Trash2 className="w-3.5 h-3.5" />}>
                                                            Disconnect
                                                        </Button>
                                                    </>
                                                )}
                                            </div>

                                            {/* Sync activity log */}
                                            {platformLogs && (
                                                <div className="rounded-lg border border-white/10 divide-y divide-white/5 max-h-56 overflow-y-auto">
                                                    {platformLogs.length === 0 && (
                                                        <p className="text-white/30 text-xs px-3 py-2">No sync activity yet.</p>
                                                    )}
                                                    {platformLogs.map(entry => (
                                                        <div key={entry.id} className="px-3 py-2 flex items-start gap-2">
                                                            {entry.status === 'success'
                                                                ? <CheckCircle className="w-3.5 h-3.5 text-green-400 mt-0.5 shrink-0" />
                                                                : <AlertCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />}
                                                            <div className="min-w-0">
                                                                <p className="text-white/70 text-xs">
                                                                    <span className="font-medium">{entry.operation}</span>
                                                                    {entry.detail ? ` — ${entry.detail}` : ''}
                                                                </p>
                                                                <p className="text-white/30 text-[10px]">
                                                                    {entry.created_at ? new Date(entry.created_at).toLocaleString() : ''}
                                                                </p>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </motion.div>
                    );
                })}
            </div>
        </div>
    );
}
