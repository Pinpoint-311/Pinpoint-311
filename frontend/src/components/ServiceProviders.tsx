import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Sparkles, Languages, KeyRound, CheckCircle, AlertCircle,
    ChevronDown, ChevronUp, Loader2,
} from 'lucide-react';

import { Button, Input, Select } from './ui';
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
        return <div className="rounded-2xl border border-white/10 bg-white/5 p-5 h-28 animate-pulse" aria-busy="true" />;
    }

    const active: ProviderInfo | undefined = catalog.providers.find(p => p.provider === selected);
    const currentName = catalog.providers.find(p => p.provider === catalog.current_provider)?.name || catalog.current_provider;

    const handleSave = async () => {
        if (!active) return;
        setBusy('save'); setResult(null); setError(null);
        try {
            const settings: Record<string, string> = {};
            active.credential_fields.forEach(f => { if (values[f.key]) settings[f.key] = values[f.key]; });
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
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay }}
            className="relative rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-xl p-5 shadow-2xl"
        >
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary-500/20 to-primary-600/10 border border-primary-500/20 flex items-center justify-center shrink-0">
                        <Icon className="w-5 h-5 text-primary-400" />
                    </div>
                    <div className="min-w-0">
                        <h3 className="font-semibold text-white">{title}</h3>
                        <p className="text-white/40 text-xs truncate">Active: {currentName}{cap === 'ai' && catalog.current_model ? ` · ${catalog.current_model}` : ''}</p>
                    </div>
                </div>
                <button
                    onClick={() => setOpen(v => !v)}
                    className="text-white/50 hover:text-white/80 inline-flex items-center gap-1 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/50 rounded px-2 py-1"
                    aria-expanded={open}
                    aria-controls={`prov-${cap}`}
                >
                    Configure {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
            </div>

            <p className="text-white/50 text-xs mt-2 leading-relaxed">{blurb}</p>

            {result && (
                <div className={`mt-3 rounded-lg px-3 py-2 text-xs border flex items-start gap-2 ${result.ok
                    ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-200'
                    : 'bg-amber-500/10 border-amber-500/25 text-amber-200'}`}>
                    {result.ok ? <CheckCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> : <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />}
                    <span>{result.detail}</span>
                </div>
            )}

            <AnimatePresence>
                {open && (
                    <motion.div
                        id={`prov-${cap}`}
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden"
                    >
                        <div className="mt-4 pt-4 border-t border-white/10 space-y-4">
                            {/* Provider picker */}
                            <div>
                                <label className="text-xs text-white/60 mb-1.5 block font-medium">Provider</label>
                                <Select
                                    options={catalog.providers.map(p => ({ value: p.provider, label: p.name }))}
                                    value={selected}
                                    onChange={(e) => { setSelected(e.target.value); setResult(null); const np = catalog.providers.find(pp => pp.provider === e.target.value); setModel(np?.default_model || ''); }}
                                    aria-label={`${title} provider`}
                                />
                                {active?.description && <p className="text-white/40 text-xs mt-1">{active.description}</p>}
                                {active?.boundary && <p className="text-white/30 text-[11px] mt-0.5">Compliance boundary: {active.boundary}</p>}
                            </div>

                            {/* AI model dropdown */}
                            {cap === 'ai' && active?.models && active.models.length > 0 && (
                                <div>
                                    <label className="text-xs text-white/60 mb-1.5 block font-medium">Model</label>
                                    <Select
                                        options={active.models.map(m => ({ value: m.id, label: m.label }))}
                                        value={model || active.default_model || active.models[0].id}
                                        onChange={(e) => setModel(e.target.value)}
                                        aria-label="AI model"
                                    />
                                </div>
                            )}

                            {/* Credential/config fields */}
                            {active?.credential_fields.map(f => {
                                const alreadySet = catalog.configured?.[selected] && selected === catalog.current_provider;
                                return (
                                    <div key={f.key}>
                                        <label className="text-xs text-white/60 mb-1 block font-medium">{f.label}</label>
                                        <Input
                                            type={f.secret ? 'password' : 'text'}
                                            placeholder={alreadySet ? 'Saved — leave blank to keep' : ''}
                                            value={values[f.key] || ''}
                                            onChange={(e) => setValues(p => ({ ...p, [f.key]: e.target.value }))}
                                            className="text-sm"
                                        />
                                        {active.field_help?.[f.key] && (
                                            <p className="text-white/40 text-xs mt-1">{active.field_help[f.key]}</p>
                                        )}
                                    </div>
                                );
                            })}

                            <div className="flex flex-wrap items-center gap-2 pt-1">
                                <Button
                                    size="sm"
                                    className="bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500"
                                    onClick={handleSave}
                                    disabled={busy !== null}
                                    leftIcon={busy === 'save' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : undefined}
                                >
                                    {busy === 'save' ? 'Saving…' : 'Save & Test'}
                                </Button>
                                <Button size="sm" variant="ghost" className="text-xs" onClick={handleTest} disabled={busy !== null}>
                                    {busy === 'test' ? 'Testing…' : 'Test connection'}
                                </Button>
                                {cap === 'identity' && (
                                    <span className="text-white/30 text-[11px] ml-auto">Auth0 default · Entra / Okta supported</span>
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
        <div>
            <h2 className="text-lg font-semibold text-white mb-1 flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-primary-400" />
                Service Providers
            </h2>
            <p className="text-white/50 text-sm mb-4">
                Choose which cloud powers each capability. Every option is pre-built — pick a provider, paste your key, and test. Google/Auth0 are the defaults.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {CAPS.map((c, i) => (
                    <CapabilityCard key={c.key} cap={c.key} title={c.title} blurb={c.blurb} icon={c.icon} delay={i * 0.05} />
                ))}
            </div>
        </div>
    );
}
