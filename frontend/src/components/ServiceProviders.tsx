import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Sparkles, Languages, KeyRound, CheckCircle, AlertCircle,
    ChevronDown, Loader2, Check, ShieldCheck, RefreshCw,
    Cloud, MapPin, Lock, Info,
} from 'lucide-react';

import { Select, CollapsibleSection } from './ui';
import SecretField from './SecretField';
import { api, ProviderCatalog, ProviderInfo, CloudProfileState } from '../services/api';

type Capability = 'ai' | 'translation' | 'identity';

const CAPS: { key: Capability; title: string; blurb: string; icon: typeof Sparkles }[] = [
    { key: 'ai', title: 'AI Provider', blurb: 'Where AI triage & the analytics assistant run. Each town brings its own key and pays only for what it uses.', icon: Sparkles },
    { key: 'translation', title: 'Translation Provider', blurb: 'Powers end-to-end translation across 100+ languages.', icon: Languages },
    { key: 'identity', title: 'Staff Sign-In (Identity)', blurb: 'The identity provider that authenticates staff and admins.', icon: KeyRound },
];

export interface CapStatus { providerName?: string; onDefault?: boolean; verified?: boolean | null }

function CapabilityCard({ cap, title, blurb, icon: Icon, delay, recheckToken, reloadToken, onStatus }: {
    cap: Capability; title: string; blurb: string; icon: typeof Sparkles; delay: number;
    recheckToken: number; reloadToken: number; onStatus: (cap: Capability, s: CapStatus) => void;
}) {
    const [catalog, setCatalog] = useState<ProviderCatalog | null>(null);
    const [selected, setSelected] = useState<string>('');
    const [model, setModel] = useState<string>('');
    const [values, setValues] = useState<Record<string, string>>({});
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState<'save' | 'test' | null>(null);
    const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const cat = await api.getProviderCatalog(cap);
            setCatalog(cat);
            setSelected(cat.current_provider);
            setModel(cat.current_model || '');
            onStatus(cap, {
                providerName: cat.providers.find(p => p.provider === cat.current_provider)?.name || cat.current_provider,
                onDefault: !cat.default_provider || cat.current_provider === cat.default_provider,
            });
        } catch (e: any) {
            setError(e?.message || 'Failed to load providers');
        }
    }, [cap, onStatus]);

    useEffect(() => { load(); }, [load]);

    // A cloud-profile switch changes the selected provider server-side; reload so
    // the card reflects the new selection (and its credential fields).
    useEffect(() => {
        if (reloadToken > 0) load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reloadToken]);

    // Parent "Recheck all" bumps this token — each card verifies its own live
    // connection and reports the result up for the summary.
    useEffect(() => {
        if (recheckToken > 0) handleTest();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [recheckToken]);

    if (error) {
        return (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" /> {title}: {error}
            </div>
        );
    }
    if (!catalog) {
        return <div className="premium-card p-6 h-32 animate-pulse" aria-busy="true" />;
    }

    const active: ProviderInfo | undefined = catalog.providers.find(p => p.provider === selected);
    const currentName = catalog.providers.find(p => p.provider === catalog.current_provider)?.name || catalog.current_provider;

    const handleSave = async () => {
        if (!active) return;
        setBusy('save'); setResult(null); setError(null);
        try {
            const settings: Record<string, string> = {};
            // Trim on save — a stray space from copy-paste is the #1 cause of a
            // "correct" key failing. Trimming here keeps mid-word typing intact.
            active.credential_fields.forEach(f => {
                const v = (values[f.key] || '').trim();
                if (v) settings[f.key] = v;
            });
            await api.saveProvider(cap, { provider: selected, model: model || undefined, settings });
            setValues({});
            await load();
            // Immediately verify
            const t = await api.testProvider(cap);
            setResult(t);
            onStatus(cap, { verified: t.ok });
        } catch (e: any) {
            setError(e?.message || 'Save failed');
        } finally {
            setBusy(null);
        }
    };

    const handleTest = async () => {
        setBusy('test'); setResult(null);
        try {
            const t = await api.testProvider(cap);
            setResult(t);
            onStatus(cap, { verified: t.ok });
        } catch (e: any) {
            setResult({ ok: false, detail: e?.message || 'Test failed' });
            onStatus(cap, { verified: false });
        } finally {
            setBusy(null);
        }
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            className="premium-card p-5"
        >
            {/* Header */}
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3.5 min-w-0">
                    <div className="relative shrink-0">
                        <div className="absolute -inset-1 rounded-2xl bg-gradient-to-br from-primary-400/40 to-primary-600/20 blur-md" aria-hidden="true" />
                        <div className="relative w-11 h-11 rounded-2xl bg-gradient-to-br from-primary-500/30 to-primary-700/20 border border-primary-400/30 flex items-center justify-center shadow-lg shadow-primary-900/40">
                            <Icon className="w-5 h-5 text-primary-200" />
                        </div>
                    </div>
                    <div className="min-w-0">
                        <h3 className="font-semibold text-white tracking-tight">{title}</h3>
                        <div className="flex items-center gap-1.5 mt-1">
                            <span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 text-emerald-400" aria-hidden="true" />
                            <p className="text-white/55 text-xs">
                                Active: <span className="text-white/80 font-medium">{currentName}</span>
                                {cap === 'ai' && catalog.current_model ? <span className="text-white/65"> · {catalog.current_model}</span> : ''}
                            </p>
                        </div>
                    </div>
                </div>
                <button
                    onClick={() => setOpen(v => !v)}
                    className="shrink-0 inline-flex items-center gap-1 text-xs font-medium text-white/70 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 rounded-full pl-3 pr-2.5 py-1.5 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                    aria-expanded={open}
                    aria-controls={`prov-${cap}`}
                >
                    Configure
                    <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.3 }} aria-hidden="true">
                        <ChevronDown className="w-3.5 h-3.5" />
                    </motion.span>
                </button>
            </div>

            <p className="text-white/50 text-xs mt-3 leading-relaxed">{blurb}</p>

            {result && (
                <motion.div
                    initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }}
                    className={`mt-3 rounded-xl px-3 py-2.5 text-xs border flex items-start gap-2 ${result.ok
                        ? 'bg-emerald-500/10 border-emerald-400/30 text-emerald-200'
                        : 'bg-amber-500/10 border-amber-400/30 text-amber-200'}`}
                >
                    {result.ok ? <CheckCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> : <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />}
                    <span>{result.detail}</span>
                </motion.div>
            )}

            <AnimatePresence initial={false}>
                {open && (
                    <motion.div
                        id={`prov-${cap}`}
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                        className="overflow-hidden"
                    >
                        <div className="mt-4 pt-4 border-t border-white/10 space-y-5">
                            {/* Provider picker — segmented tiles */}
                            <div>
                                <label className="text-[11px] uppercase tracking-wider text-white/60 mb-2 block font-semibold">Provider</label>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" role="radiogroup" aria-label={`${title} provider`}>
                                    {catalog.providers.map(p => {
                                        const isSel = p.provider === selected;
                                        const isCurrent = p.provider === catalog.current_provider;
                                        const isDefault = catalog.default_provider ? p.provider === catalog.default_provider : false;
                                        return (
                                            <button
                                                key={p.provider}
                                                role="radio"
                                                aria-checked={isSel}
                                                onClick={() => { setSelected(p.provider); setResult(null); setModel(p.default_model || ''); }}
                                                className={`relative text-left rounded-xl px-3 py-2.5 border transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 ${isSel
                                                    ? 'bg-gradient-to-br from-primary-500/25 to-primary-700/15 border-primary-400/50 shadow-lg shadow-primary-900/30'
                                                    : 'bg-white/[0.03] border-white/10 hover:bg-white/[0.06] hover:border-white/20'}`}
                                            >
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className={`text-sm font-medium truncate ${isSel ? 'text-white' : 'text-white/70'}`}>{p.name}</span>
                                                    {isSel && (
                                                        <span className="shrink-0 w-4 h-4 rounded-full bg-primary-400 flex items-center justify-center">
                                                            <Check className="w-3 h-3 text-primary-950" strokeWidth={3} />
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="flex items-center gap-1.5 mt-1">
                                                    {isCurrent && (
                                                        <span className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300/90">In use</span>
                                                    )}
                                                    {isDefault && !isCurrent && (
                                                        <span className="text-[10px] font-semibold uppercase tracking-wide text-primary-300/90">Recommended</span>
                                                    )}
                                                </div>
                                            </button>
                                        );
                                    })}
                                </div>
                                {(active?.description || active?.boundary) && (
                                    <div className="mt-2.5 rounded-lg bg-white/[0.03] border border-white/10 px-3 py-2 space-y-1">
                                        {active?.description && <p className="text-white/55 text-xs leading-relaxed">{active.description}</p>}
                                        {active?.boundary && (
                                            <p className="text-white/60 text-[11px] flex items-center gap-1.5">
                                                <ShieldCheck className="w-3 h-3 text-primary-300/70 shrink-0" aria-hidden="true" />
                                                Compliance boundary: {active.boundary}
                                            </p>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Switching identity forces a re-login */}
                            {cap === 'identity' && selected !== catalog.current_provider && (
                                <div className="rounded-lg bg-amber-500/10 border border-amber-400/25 px-3 py-2 text-[11px] text-amber-200 flex items-start gap-2">
                                    <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
                                    Switching sign-in providers signs everyone out — staff will sign in again through {active?.name || 'the new provider'} next time.
                                </div>
                            )}

                            {/* AI model dropdown */}
                            {cap === 'ai' && active?.models && active.models.length > 0 && (
                                <div>
                                    <label className="text-[11px] uppercase tracking-wider text-white/60 mb-2 block font-semibold">Model</label>
                                    <Select
                                        options={active.models.map(m => ({ value: m.id, label: m.label }))}
                                        value={model || active.default_model || active.models[0].id}
                                        onChange={(e) => setModel(e.target.value)}
                                        aria-label="AI model"
                                    />
                                </div>
                            )}

                            {/* Credential/config fields */}
                            {active && active.credential_fields.length > 0 && (
                                <div className="space-y-3">
                                    {active.credential_fields.map(f => {
                                        const alreadySet = !!(catalog.configured?.[selected] && selected === catalog.current_provider);
                                        return (
                                            <SecretField
                                                key={f.key}
                                                label={f.label}
                                                secret={f.secret}
                                                value={values[f.key] || ''}
                                                onChange={(v) => setValues(p => ({ ...p, [f.key]: v }))}
                                                placeholder={`Enter ${f.label.toLowerCase()}`}
                                                help={active.field_help?.[f.key]}
                                                savedHint={alreadySet}
                                            />
                                        );
                                    })}
                                </div>
                            )}

                            <div className="flex flex-wrap items-center gap-2.5 pt-1">
                                <button
                                    onClick={handleSave}
                                    disabled={busy !== null}
                                    className="shimmer-sweep inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-900/40 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                >
                                    {busy === 'save'
                                        ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</>
                                        : <><Sparkles className="w-4 h-4" /> Save &amp; Test</>}
                                </button>
                                <button
                                    onClick={handleTest}
                                    disabled={busy !== null}
                                    className="inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2.5 text-sm font-medium text-white/75 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                                >
                                    {busy === 'test' ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Testing…</> : 'Test connection'}
                                </button>
                                {cap === 'identity' && (
                                    <span className="text-white/60 text-[11px] ml-auto hidden sm:block">Auth0 default · Entra / Okta supported</span>
                                )}
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}

const COMPONENT_LABEL: Record<string, string> = {
    // AI
    vertex: 'Google Vertex AI', bedrock: 'AWS Bedrock',
    // shared cloud names
    azure: 'Azure', google: 'Google', aws: 'AWS',
    // identity
    auth0: 'Auth0', entra: 'Microsoft Entra ID', okta: 'Okta', oidc: 'OIDC (e.g. Cognito)',
    // email / sms
    smtp: 'SMTP', ses: 'Amazon SES', acs: 'Azure Communication Services',
    sns: 'Amazon SNS', twilio: 'Twilio',
};

const label = (v: string) => COMPONENT_LABEL[v] || v || '—';
const secretsLabel = (v: string) => v === 'google' ? 'Secret Manager' : v === 'azure' ? 'Key Vault' : v === 'aws' ? 'Secrets Manager' : label(v);

// Per-cloud visual identity — a monogram tile + accent so each option reads at a
// glance without pulling in third-party brand logos (which carry trademark rules).
const CLOUD_VISUAL: Record<string, { glyph: string; tile: string; ring: string; glow: string }> = {
    google: { glyph: 'G', tile: 'from-sky-400/30 to-blue-600/20 border-sky-300/40 text-sky-100', ring: 'border-sky-300/50', glow: 'shadow-sky-900/40' },
    azure:  { glyph: 'A', tile: 'from-cyan-400/30 to-indigo-600/20 border-cyan-300/40 text-cyan-100', ring: 'border-cyan-300/50', glow: 'shadow-cyan-900/40' },
    aws:    { glyph: 'A', tile: 'from-amber-400/30 to-orange-600/20 border-amber-300/40 text-amber-100', ring: 'border-amber-300/50', glow: 'shadow-amber-900/40' },
    mixed:  { glyph: '⋯', tile: 'from-white/15 to-white/5 border-white/20 text-white/80', ring: 'border-white/25', glow: 'shadow-black/40' },
};
const cloudVisual = (id: string) => CLOUD_VISUAL[id] || CLOUD_VISUAL.mixed;

// Hybrid "one choice" front door: a jurisdiction is authorized under one cloud
// boundary, so picking it sets AI + translation + secret store together. Identity
// stays separate (only recommended). Google Maps is fixed.
function CloudEnvironment({ onApplied }: { onApplied: () => void }) {
    const [state, setState] = useState<CloudProfileState | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [result, setResult] = useState<{ profile: string; warnings: string[]; identity_recommended: string } | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try { setState(await api.getCloudProfile()); }
        catch (e: any) { setError(e?.message || 'Could not load the cloud environment.'); }
    }, []);
    useEffect(() => { load(); }, [load]);

    const apply = async (profileId: string, applyIdentity = false) => {
        if (!state || state.managed) return;
        setBusy(profileId); setError(null); setResult(null);
        try {
            const r = await api.setCloudProfile(profileId, applyIdentity);
            setResult({ profile: r.profile, warnings: r.warnings || [], identity_recommended: r.identity_recommended });
            await load();
            onApplied(); // refresh the capability cards to show the new selections
        } catch (e: any) {
            setError(e?.message || 'Could not switch the cloud environment.');
        } finally {
            setBusy(null);
        }
    };

    if (error && !state) {
        return (
            <div className="mb-5 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" /> {error}
            </div>
        );
    }
    if (!state) return <div className="premium-card p-6 h-40 mb-5 animate-pulse" aria-busy="true" />;

    const identityLabel = COMPONENT_LABEL[state.components.identity] || state.components.identity;

    return (
        <motion.div
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            className="premium-card p-5 mb-5"
        >
            <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="relative shrink-0">
                        <div className="absolute -inset-1 rounded-2xl bg-gradient-to-br from-primary-400/40 to-primary-600/20 blur-md" aria-hidden="true" />
                        <div className="relative w-11 h-11 rounded-2xl bg-gradient-to-br from-primary-500/30 to-primary-700/20 border border-primary-400/30 flex items-center justify-center shadow-lg shadow-primary-900/40">
                            <Cloud className="w-5 h-5 text-primary-200" />
                        </div>
                    </div>
                    <div className="min-w-0">
                        <h3 className="font-semibold text-white tracking-tight">Cloud environment</h3>
                        <p className="text-white/50 text-xs mt-0.5 max-w-xl leading-relaxed">
                            One choice sets your AI, translation, secret storage, PII encryption (KMS), and
                            email/text to match your authorized cloud. Sign-in and Google Maps are configured
                            separately below.
                        </p>
                    </div>
                </div>
                {state.managed && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-white/10 text-white/60 border border-white/10">
                        <Lock className="w-3 h-3" aria-hidden="true" /> Managed by your state
                    </span>
                )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-4" role="radiogroup" aria-label="Cloud environment">
                {state.profiles.map(p => {
                    const isActive = state.profile === p.id;
                    const isBusy = busy === p.id;
                    const vis = cloudVisual(p.id);
                    const caps = [
                        { k: 'AI', v: label(p.ai) },
                        { k: 'Translation', v: label(p.translation) },
                        { k: 'Secrets', v: secretsLabel(p.secrets) },
                        { k: 'KMS', v: label(p.kms) },
                        { k: 'Email', v: label(p.email) },
                        ...(p.sms ? [{ k: 'Text', v: label(p.sms) }] : []),
                    ];
                    return (
                        <button
                            key={p.id}
                            type="button"
                            role="radio"
                            aria-checked={isActive}
                            disabled={state.managed || busy !== null}
                            onClick={() => apply(p.id)}
                            className={`group relative text-left rounded-2xl p-4 border transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 disabled:cursor-not-allowed ${isActive
                                ? `bg-gradient-to-br from-primary-500/20 to-primary-800/10 ${vis.ring} shadow-lg ${vis.glow}`
                                : 'bg-white/[0.03] border-white/10 hover:bg-white/[0.06] hover:border-white/20 disabled:opacity-60'}`}
                        >
                            {isActive && <div className={`absolute -inset-px rounded-2xl border ${vis.ring} opacity-60 pointer-events-none`} aria-hidden="true" />}
                            <div className="flex items-center gap-3">
                                <div className={`relative shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br border flex items-center justify-center font-bold text-sm ${vis.tile} ${isActive ? 'shadow-md ' + vis.glow : 'opacity-90 group-hover:opacity-100'}`}>
                                    {vis.glyph}
                                </div>
                                <span className={`font-semibold tracking-tight flex-1 min-w-0 truncate ${isActive ? 'text-white' : 'text-white/80'}`}>{p.label}</span>
                                {isBusy ? <Loader2 className="w-4 h-4 animate-spin text-primary-200 shrink-0" />
                                    : isActive && <span className="shrink-0 w-5 h-5 rounded-full bg-primary-400 flex items-center justify-center"><Check className="w-3 h-3 text-primary-950" strokeWidth={3} /></span>}
                            </div>
                            <p className="text-[11px] text-white/60 mt-2.5 flex items-start gap-1.5 leading-relaxed">
                                <ShieldCheck className="w-3 h-3 text-primary-300/70 shrink-0 mt-0.5" aria-hidden="true" />
                                {p.boundary}
                            </p>
                            <div className="mt-3 pt-3 border-t border-white/[0.06] grid grid-cols-2 gap-x-3 gap-y-1.5">
                                {caps.map(c => (
                                    <div key={c.k} className="flex flex-col min-w-0">
                                        <span className="text-[9px] uppercase tracking-wider text-white/35">{c.k}</span>
                                        <span className="text-[11px] text-white/75 truncate leading-tight">{c.v}</span>
                                    </div>
                                ))}
                            </div>
                        </button>
                    );
                })}
            </div>

            {state.profile === 'mixed' && (
                <p className="text-white/50 text-xs mt-3 flex items-center gap-1.5">
                    <Info className="w-3.5 h-3.5 text-primary-300/70 shrink-0" aria-hidden="true" />
                    You're running a custom mix of providers. Pick a cloud above to standardize, or fine-tune each capability below.
                </p>
            )}

            {result && result.warnings.length > 0 && (
                <div className="mt-3 rounded-xl bg-amber-500/10 border border-amber-400/30 px-3 py-2.5 text-xs text-amber-200 space-y-1">
                    {result.warnings.map((w, i) => (
                        <p key={i} className="flex items-start gap-2"><AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {w}</p>
                    ))}
                </div>
            )}

            {/* Identity is orthogonal — recommend, never force. */}
            {result && result.identity_recommended && state.components.identity !== result.identity_recommended && !state.managed && (
                <div className="mt-3 rounded-xl bg-white/[0.04] border border-white/10 px-3 py-2.5 text-xs text-white/60 flex flex-wrap items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5">
                        <KeyRound className="w-3.5 h-3.5 text-primary-300/80" aria-hidden="true" />
                        Recommended sign-in for this cloud: <span className="text-white/85 font-medium">{COMPONENT_LABEL[result.identity_recommended] || result.identity_recommended}</span> (currently {identityLabel}).
                    </span>
                    <button
                        onClick={() => apply(result.profile, true)}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-medium text-primary-100 bg-primary-500/20 hover:bg-primary-500/30 border border-primary-400/30 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                    >
                        Switch sign-in too
                    </button>
                </div>
            )}

            <div className="mt-3 pt-3 border-t border-white/10 flex items-center gap-1.5 text-[11px] text-white/60">
                <MapPin className="w-3 h-3 text-primary-300/70 shrink-0" aria-hidden="true" />
                Mapping always uses <span className="text-white/60">{state.maps.label}</span> — it isn't affected by the cloud choice.
            </div>
        </motion.div>
    );
}

export default function ServiceProviders() {
    const [recheckToken, setRecheckToken] = useState(0);
    const [reloadToken, setReloadToken] = useState(0);
    const [statuses, setStatuses] = useState<Record<string, CapStatus>>({});

    const onStatus = useCallback((cap: Capability, s: CapStatus) => {
        setStatuses(prev => ({ ...prev, [cap]: { ...prev[cap], ...s } }));
    }, []);

    const loaded = CAPS.filter(c => statuses[c.key]);
    const onDefaultCount = loaded.filter(c => statuses[c.key]?.onDefault).length;
    const verifiedCount = loaded.filter(c => statuses[c.key]?.verified === true).length;
    const failedCount = loaded.filter(c => statuses[c.key]?.verified === false).length;

    return (
        <CollapsibleSection
            title="Service Providers"
            icon={Sparkles}
            accent="primary"
            defaultOpen={true}
            subtitle="AI, translation, sign-in & cloud environment — defaults work out of the box"
            trailing={
                <button
                    onClick={() => setRecheckToken(t => t + 1)}
                    className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium text-white/80 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                >
                    <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" /> Recheck
                </button>
            }
        >
            <p className="text-white/60 text-sm max-w-2xl leading-relaxed mb-1">
                Choose which cloud powers each capability. Every option is pre-built — pick a provider, paste your key, and test.
                Google &amp; Auth0 are the defaults, so you can leave these untouched and everything just works.
            </p>
            {loaded.length > 0 && (
                <div className="text-[11px] text-white/55 flex flex-wrap items-center gap-x-3 gap-y-0.5 mb-4">
                    <span>{onDefaultCount === loaded.length
                        ? 'All on recommended defaults'
                        : `${loaded.length - onDefaultCount} customized · ${onDefaultCount} on defaults`}</span>
                    {verifiedCount > 0 && <span className="text-emerald-300/80 inline-flex items-center gap-1"><CheckCircle className="w-3 h-3" />{verifiedCount} verified</span>}
                    {failedCount > 0 && <span className="text-amber-300/90 inline-flex items-center gap-1"><AlertCircle className="w-3 h-3" />{failedCount} need attention</span>}
                </div>
            )}

            <CloudEnvironment onApplied={() => setReloadToken(t => t + 1)} />

            <div className="relative grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {CAPS.map((c, i) => (
                    <CapabilityCard key={c.key} cap={c.key} title={c.title} blurb={c.blurb} icon={c.icon} delay={i * 0.08}
                        recheckToken={recheckToken} reloadToken={reloadToken} onStatus={onStatus} />
                ))}
            </div>
        </CollapsibleSection>
    );
}
