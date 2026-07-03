import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Sparkles, Languages, KeyRound, CheckCircle, AlertCircle,
    ChevronDown, Loader2, Check, ShieldCheck,
} from 'lucide-react';

import { Select } from './ui';
import SecretField from './SecretField';
import { api, ProviderCatalog, ProviderInfo } from '../services/api';

type Capability = 'ai' | 'translation' | 'identity';

const CAPS: { key: Capability; title: string; blurb: string; icon: typeof Sparkles }[] = [
    { key: 'ai', title: 'AI Provider', blurb: 'Where AI triage & the analytics assistant run. Each town brings its own key and pays only for what it uses.', icon: Sparkles },
    { key: 'translation', title: 'Translation Provider', blurb: 'Powers end-to-end translation across 100+ languages.', icon: Languages },
    { key: 'identity', title: 'Staff Sign-In (Identity)', blurb: 'The identity provider that authenticates staff and admins.', icon: KeyRound },
];

function CapabilityCard({ cap, title, blurb, icon: Icon, delay }: {
    cap: Capability; title: string; blurb: string; icon: typeof Sparkles; delay: number;
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
        } catch (e: any) {
            setError(e?.message || 'Failed to load providers');
        }
    }, [cap]);

    useEffect(() => { load(); }, [load]);

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
        } catch (e: any) {
            setError(e?.message || 'Save failed');
        } finally {
            setBusy(null);
        }
    };

    const handleTest = async () => {
        setBusy('test'); setResult(null);
        try {
            setResult(await api.testProvider(cap));
        } catch (e: any) {
            setResult({ ok: false, detail: e?.message || 'Test failed' });
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
                                {cap === 'ai' && catalog.current_model ? <span className="text-white/45"> · {catalog.current_model}</span> : ''}
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
                                            <p className="text-white/40 text-[11px] flex items-center gap-1.5">
                                                <ShieldCheck className="w-3 h-3 text-primary-300/70 shrink-0" aria-hidden="true" />
                                                Compliance boundary: {active.boundary}
                                            </p>
                                        )}
                                    </div>
                                )}
                            </div>

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
                                    <span className="text-white/30 text-[11px] ml-auto hidden sm:block">Auth0 default · Entra / Okta supported</span>
                                )}
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}

export default function ServiceProviders() {
    return (
        <div className="relative">
            {/* Aurora glow behind the header for depth */}
            <div className="aurora-glow w-72 h-40 -top-10 -left-6" aria-hidden="true" />

            <div className="relative mb-5">
                <div className="inline-flex items-center gap-1.5 rounded-full bg-primary-500/15 border border-primary-400/25 px-2.5 py-1 mb-3">
                    <Sparkles className="w-3 h-3 text-primary-300" aria-hidden="true" />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-primary-200">Configure once</span>
                </div>
                <h2 className="text-2xl font-bold text-gradient tracking-tight">Service Providers</h2>
                <p className="text-white/50 text-sm mt-1.5 max-w-2xl leading-relaxed">
                    Choose which cloud powers each capability. Every option is pre-built — pick a provider, paste your key, and test.
                    <span className="text-white/70"> Google &amp; Auth0 are the defaults</span>, so you can leave these untouched and everything just works.
                </p>
            </div>

            <div className="relative grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {CAPS.map((c, i) => (
                    <CapabilityCard key={c.key} cap={c.key} title={c.title} blurb={c.blurb} icon={c.icon} delay={i * 0.08} />
                ))}
            </div>
        </div>
    );
}
