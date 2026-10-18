import { useCallback, useEffect, useId, useState } from 'react';
import { KeyRound, Copy, Check, Loader2, AlertTriangle } from 'lucide-react';

import { api } from '../services/api';
import type { Open311ApiKey, Open311ApiKeyCreated, Open311Settings } from '../services/api';
import { AccordionSection, Chip } from './ui';
import { useDialog } from './DialogProvider';

/**
 * Admin Console > Integrations: keys for third-party Open311 clients.
 *
 * GeoReport v2 requires an `api_key` on POST requests.json. A key identifies
 * one integrator, has its own rate limit, and can be revoked on its own. The
 * server keeps only a hash, so the key is shown exactly once, right after it
 * is created; after that the list shows its first eight characters.
 *
 * The town's own report form does not use a key (nothing in a browser can be
 * secret), so nothing here can break resident submissions.
 */

function formatDate(value: string | null): string {
    if (!value) return 'Never';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return 'Never';
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function Open311ApiKeys() {
    const dialog = useDialog();
    const nameId = useId();
    const contactId = useId();
    const anonDescId = useId();
    const [keys, setKeys] = useState<Open311ApiKey[]>([]);
    const [settings, setSettings] = useState<Open311Settings | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [name, setName] = useState('');
    const [contact, setContact] = useState('');
    const [creating, setCreating] = useState(false);
    const [created, setCreated] = useState<Open311ApiKeyCreated | null>(null);
    const [copied, setCopied] = useState(false);
    const [savingSetting, setSavingSetting] = useState(false);
    const [revoking, setRevoking] = useState<number | null>(null);

    const load = useCallback(async () => {
        setError(null);
        try {
            const [k, s] = await Promise.all([api.getOpen311Keys(), api.getOpen311Settings()]);
            setKeys(k);
            setSettings(s);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not load Open311 keys');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const create = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim() || !contact.trim()) return;
        setCreating(true);
        setError(null);
        try {
            const result = await api.createOpen311Key({ name: name.trim(), contact_email: contact.trim() });
            setCreated(result);
            setCopied(false);
            setName('');
            setContact('');
            // The list gets the metadata only; the key itself stays in `created`.
            const { api_key: _omit, ...listed } = result;
            void _omit;
            setKeys(prev => [listed, ...prev]);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not create the key');
        } finally {
            setCreating(false);
        }
    };

    const copy = async () => {
        if (!created) return;
        try {
            await navigator.clipboard.writeText(created.api_key);
            setCopied(true);
        } catch {
            setCopied(false);
            setError('Copy failed. Select the key and copy it by hand.');
        }
    };

    const revoke = async (key: Open311ApiKey) => {
        const ok = await dialog.confirm({
            title: 'Revoke API key',
            message: `Revoke the key for "${key.name}" (${key.key_prefix}…)? Its next request will be refused. This cannot be undone; issue a new key if they still need access.`,
            variant: 'danger',
            confirmText: 'Revoke',
        });
        if (!ok) return;
        setRevoking(key.id);
        setError(null);
        try {
            const updated = await api.revokeOpen311Key(key.id);
            setKeys(prev => prev.map(k => (k.id === updated.id ? updated : k)));
            if (created?.id === key.id) setCreated(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not revoke the key');
        } finally {
            setRevoking(null);
        }
    };

    const toggleAnonymous = async () => {
        if (!settings) return;
        const next = !settings.allow_anonymous_submissions;
        if (next) {
            const ok = await dialog.confirm({
                title: 'Allow anonymous Open311 submissions?',
                message: `Any app will be able to file reports through the Open311 API without a key, limited to ${settings.anonymous_rate_limit.replace('/', ' per ')} per address. You will not be able to tell which app filed them.`,
                variant: 'warning',
                confirmText: 'Allow',
            });
            if (!ok) return;
        }
        setSavingSetting(true);
        setError(null);
        try {
            setSettings(await api.updateOpen311Settings({ allow_anonymous_submissions: next }));
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not save the setting');
        } finally {
            setSavingSetting(false);
        }
    };

    const active = keys.filter(k => k.status === 'active').length;

    return (
        <AccordionSection
            title="Open311 API keys"
            subtitle="Keys for outside apps that file reports through the Open311 API"
            icon={KeyRound}
            iconClassName="text-amber-400"
            badge={<Chip tone={active ? 'success' : 'neutral'}>{active} active</Chip>}
        >
            <div className="space-y-6">
                <p className="text-sm text-white/60">
                    Outside apps need a key to file reports through <code className="text-white/80">POST /api/open311/v2/requests.json</code>.
                    Reading reports needs no key. Your own report form never uses one.
                </p>

                {error && (
                    <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
                        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
                        <span>{error}</span>
                    </div>
                )}

                {created && (
                    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 space-y-3" data-testid="open311-new-key">
                        <p className="text-sm font-medium text-amber-200">
                            Key for {created.name}. Copy it now: you won't see it again.
                        </p>
                        <div className="flex flex-col sm:flex-row gap-2">
                            <code className="flex-1 break-all rounded bg-black/30 px-3 py-2 font-mono text-sm text-white select-all">
                                {created.api_key}
                            </code>
                            <button type="button" className="btn-outline btn-outline-md" onClick={copy}>
                                {copied ? <Check className="w-4 h-4" aria-hidden="true" /> : <Copy className="w-4 h-4" aria-hidden="true" />}
                                <span>{copied ? 'Copied' : 'Copy key'}</span>
                            </button>
                        </div>
                        <p className="text-xs text-white/50">
                            Only a fingerprint is stored. If the key is lost, revoke it and create a new one.
                        </p>
                        <button type="button" className="btn-outline" onClick={() => setCreated(null)}>Done</button>
                    </div>
                )}

                <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-end">
                    <div>
                        <label htmlFor={nameId} className="block text-sm text-white/70 mb-1">Who is it for</label>
                        <input
                            id={nameId}
                            className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500"
                            placeholder="e.g. County 311 app"
                            maxLength={200}
                            required
                            value={name}
                            onChange={e => setName(e.target.value)}
                        />
                    </div>
                    <div>
                        <label htmlFor={contactId} className="block text-sm text-white/70 mb-1">Contact email</label>
                        <input
                            id={contactId}
                            type="email"
                            className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500"
                            placeholder="developer@example.com"
                            maxLength={254}
                            required
                            value={contact}
                            onChange={e => setContact(e.target.value)}
                        />
                    </div>
                    <button type="submit" className="btn-outline btn-outline-md" disabled={creating || !name.trim() || !contact.trim()}>
                        {creating ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <KeyRound className="w-4 h-4" aria-hidden="true" />}
                        <span>Create key</span>
                    </button>
                </form>

                {loading ? (
                    <p className="text-sm text-white/50 flex items-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading keys…
                    </p>
                ) : keys.length === 0 ? (
                    <p className="text-sm text-white/50">No keys yet.</p>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <caption className="sr-only">Open311 API keys</caption>
                            <thead>
                                <tr className="text-left text-white/50 border-b border-white/10">
                                    <th scope="col" className="py-2 pr-4 font-medium">Name</th>
                                    <th scope="col" className="py-2 pr-4 font-medium">Key</th>
                                    <th scope="col" className="py-2 pr-4 font-medium">Created</th>
                                    <th scope="col" className="py-2 pr-4 font-medium">Last used</th>
                                    <th scope="col" className="py-2 pr-4 font-medium">Status</th>
                                    <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/[0.06]">
                                {keys.map(k => (
                                    <tr key={k.id}>
                                        <td className="py-2 pr-4 text-white">
                                            <div>{k.name}</div>
                                            <div className="text-xs text-white/40">{k.contact_email}</div>
                                        </td>
                                        <td className="py-2 pr-4 font-mono text-white/70">{k.key_prefix}…</td>
                                        <td className="py-2 pr-4 text-white/60">{formatDate(k.created_at)}</td>
                                        <td className="py-2 pr-4 text-white/60">{formatDate(k.last_used_at)}</td>
                                        <td className="py-2 pr-4">
                                            {k.status === 'active'
                                                ? <Chip tone="success">Active</Chip>
                                                : <Chip tone="neutral">Revoked</Chip>}
                                        </td>
                                        <td className="py-2 text-right">
                                            {k.status === 'active' && (
                                                <button
                                                    type="button"
                                                    className="btn-outline btn-outline-danger"
                                                    onClick={() => revoke(k)}
                                                    disabled={revoking === k.id}
                                                    aria-label={`Revoke key for ${k.name}`}
                                                >
                                                    Revoke
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                {settings && (
                    <div className="flex items-start justify-between gap-4 rounded-lg bg-white/5 p-4">
                        <div>
                            <div className="text-sm font-medium text-white">Allow anonymous Open311 submissions</div>
                            <p id={anonDescId} className="text-xs text-white/50 mt-1">
                                Off: every outside app needs a key. On: apps can file without one, limited
                                to {settings.anonymous_rate_limit.replace('/', ' per ')} per address. Changes are recorded in the audit log.
                            </p>
                        </div>
                        <button
                            type="button"
                            role="switch"
                            aria-checked={settings.allow_anonymous_submissions}
                            aria-label="Allow anonymous Open311 submissions"
                            aria-describedby={anonDescId}
                            disabled={savingSetting}
                            onClick={toggleAnonymous}
                            className={`shrink-0 rounded-full focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 ${savingSetting ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                        >
                            <div
                                className={`flex items-center rounded-full p-[2px] transition-colors duration-200 ${settings.allow_anonymous_submissions ? 'bg-primary-500' : 'bg-slate-600'}`}
                                style={{ width: '44px', height: '24px' }}
                            >
                                <div
                                    className="bg-white rounded-full shadow transition-all duration-200"
                                    style={{ width: '20px', height: '20px', marginLeft: settings.allow_anonymous_submissions ? '20px' : '0px' }}
                                />
                            </div>
                        </button>
                    </div>
                )}
            </div>
        </AccordionSection>
    );
}
