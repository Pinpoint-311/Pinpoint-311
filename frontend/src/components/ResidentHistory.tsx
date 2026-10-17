import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { History, Lock, Loader2, Mail, Search, UserRound, ChevronRight } from 'lucide-react';

import { api } from '../services/api';
import type { ResidentHistoryItem } from '../types';

/**
 * The opt-in "Resident history" module, staff side.
 *
 * Two pieces: a card on a request showing the same resident's earlier reports
 * (matched by email), and a "Find a resident" search by full email or full name.
 * Both only render when an administrator has switched the module on, and the
 * server enforces everything that matters regardless of what this file draws:
 * the module switch, department scoping, minimal fields, exact matching, and an
 * audit record for every lookup. The footers say so, because a clerk should know
 * their lookups are recorded before they make one.
 */

const STATUS_STYLES: Record<string, { label: string; cls: string }> = {
    open: { label: 'Open', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/25' },
    in_progress: { label: 'In progress', cls: 'bg-sky-500/15 text-sky-300 border-sky-500/25' },
    closed: { label: 'Closed', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25' },
};

function formatDate(value: string | null): string {
    if (!value) return '';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    const sameYear = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleDateString(undefined, sameYear
        ? { month: 'short', day: 'numeric' }
        : { month: 'short', day: 'numeric', year: 'numeric' });
}

function ReportRows({ reports, onOpen }: { reports: ResidentHistoryItem[]; onOpen: (id: string) => void }) {
    return (
        <ul className="divide-y divide-white/[0.06]">
            {reports.map((r, i) => {
                const status = STATUS_STYLES[r.status || ''] || { label: r.status || 'Unknown', cls: 'bg-white/5 text-white/60 border-white/10' };
                return (
                    <motion.li
                        key={r.service_request_id}
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(i, 8) * 0.03 }}
                    >
                        <button
                            type="button"
                            onClick={() => onOpen(r.service_request_id)}
                            className="group w-full grid grid-cols-[minmax(0,auto)_minmax(0,1fr)_auto_auto] items-center gap-3 px-1 py-2.5 text-left rounded-lg hover:bg-white/[0.04] focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 transition-colors"
                            aria-label={`Open ${r.service_request_id}, ${r.service_name || 'report'}, ${status.label}`}
                        >
                            <span className="font-mono text-xs text-primary-300 truncate">{r.service_request_id}</span>
                            <span className="text-sm text-white/85 truncate">{r.service_name || 'Report'}</span>
                            <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${status.cls}`}>{status.label}</span>
                            <span className="flex items-center gap-1 text-xs text-white/45 tabular-nums">
                                {formatDate(r.requested_datetime)}
                                <ChevronRight className="w-3.5 h-3.5 text-white/25 group-hover:text-white/60 transition-colors" aria-hidden="true" />
                            </span>
                        </button>
                    </motion.li>
                );
            })}
        </ul>
    );
}

function AuditFooter({ children }: { children: React.ReactNode }) {
    return (
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-white/40 pt-3 mt-1 border-t border-white/[0.06]">
            <Lock className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
            <span>{children}</span>
        </p>
    );
}

/** Earlier reports from the same resident email, on a request's detail view. */
export function ResidentHistoryCard({ serviceRequestId, onOpen }: {
    serviceRequestId: string;
    onOpen: (id: string) => void;
}) {
    const [state, setState] = useState<
        | { kind: 'loading' }
        | { kind: 'error'; message: string }
        | { kind: 'ready'; total: number; reports: ResidentHistoryItem[]; matched: boolean }
    >({ kind: 'loading' });

    useEffect(() => {
        let cancelled = false;
        setState({ kind: 'loading' });
        api.getResidentHistory(serviceRequestId)
            .then(res => {
                if (!cancelled) setState({ kind: 'ready', total: res.total, reports: res.reports, matched: res.matched_by === 'email' });
            })
            .catch((err: Error) => {
                if (!cancelled) setState({ kind: 'error', message: err.message || "Couldn't load this resident's history." });
            });
        return () => { cancelled = true; };
    }, [serviceRequestId]);

    const count = state.kind === 'ready' ? state.total : 0;

    return (
        <section
            aria-labelledby={`resident-history-${serviceRequestId}`}
            className="p-4 rounded-xl bg-gradient-to-br from-primary-500/[0.07] via-slate-800/50 to-slate-800/50 border border-white/10"
        >
            <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500/25 to-indigo-600/10 border border-primary-500/25 flex items-center justify-center">
                        <History className="w-4 h-4 text-primary-300" aria-hidden="true" />
                    </div>
                    <h3 id={`resident-history-${serviceRequestId}`} className="font-medium text-white">
                        Earlier reports from this resident
                    </h3>
                </div>
                {state.kind === 'ready' && state.matched && (
                    <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-primary-500/15 text-primary-200 border border-primary-500/25">
                        {count === 0 ? 'None' : `${count} found`}
                    </span>
                )}
            </div>

            {state.kind === 'loading' && (
                <div className="flex items-center gap-2 py-3 text-sm text-white/50" role="status">
                    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Checking earlier reports…
                </div>
            )}
            {state.kind === 'error' && (
                <p className="py-2 text-sm text-amber-300/90" role="alert">{state.message}</p>
            )}
            {state.kind === 'ready' && !state.matched && (
                <p className="py-2 text-sm text-white/50">This report has no email address to match on.</p>
            )}
            {state.kind === 'ready' && state.matched && state.reports.length === 0 && (
                <p className="py-2 text-sm text-white/50">This is the first report from this email address that you have access to.</p>
            )}
            {state.kind === 'ready' && state.reports.length > 0 && (
                <>
                    <ReportRows reports={state.reports} onOpen={onOpen} />
                    {state.total > state.reports.length && (
                        <p className="text-xs text-white/40 pt-1">Showing the {state.reports.length} most recent of {state.total}.</p>
                    )}
                </>
            )}

            <AuditFooter>Matched by email. Only reports you already have access to. Viewing is logged.</AuditFooter>
        </section>
    );
}

/** "Find a resident": exact search by full email address or full name. */
export function ResidentSearch({ onOpen }: { onOpen: (id: string) => void }) {
    const [mode, setMode] = useState<'email' | 'name'>('email');
    const [value, setValue] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [result, setResult] = useState<{ total: number; reports: ResidentHistoryItem[] } | null>(null);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        const v = value.trim();
        if (!v) {
            setError(mode === 'email' ? 'Enter a full email address' : 'Enter a first and last name');
            return;
        }
        if (mode === 'email' && !/\S+@\S+\.\S+/.test(v)) {
            setError('Enter the full email address');
            return;
        }
        if (mode === 'name' && v.split(/\s+/).length < 2) {
            setError('Enter both a first and a last name');
            return;
        }
        setBusy(true);
        setError('');
        try {
            const res = await api.searchResidents(mode === 'email' ? { email: v } : { name: v });
            setResult({ total: res.total, reports: res.reports });
        } catch (err: any) {
            setResult(null);
            setError(err?.message || "Couldn't search. Try again.");
        } finally {
            setBusy(false);
        }
    };

    const switchMode = (next: 'email' | 'name') => {
        setMode(next);
        setValue('');
        setError('');
        setResult(null);
    };

    return (
        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/10 space-y-2.5">
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-white/50">Find a resident</span>
                <div className="inline-flex p-0.5 rounded-lg bg-white/5 border border-white/10" role="radiogroup" aria-label="Search by">
                    {([['email', 'Email', Mail], ['name', 'Name', UserRound]] as const).map(([key, label, Icon]) => (
                        <button
                            key={key}
                            type="button"
                            role="radio"
                            aria-checked={mode === key}
                            onClick={() => switchMode(key)}
                            className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${mode === key
                                ? 'bg-gradient-to-r from-primary-500 to-indigo-600 text-white shadow shadow-primary-500/30'
                                : 'text-white/60 hover:text-white'}`}
                        >
                            <Icon className="w-3 h-3" aria-hidden="true" /> {label}
                        </button>
                    ))}
                </div>
            </div>

            <form onSubmit={submit} className="flex gap-2">
                <input
                    type={mode === 'email' ? 'email' : 'text'}
                    value={value}
                    onChange={e => { setValue(e.target.value); setError(''); }}
                    placeholder={mode === 'email' ? 'jane.doe@example.com' : 'Jane Doe'}
                    aria-label={mode === 'email' ? 'Resident email address' : 'Resident full name'}
                    aria-invalid={!!error}
                    aria-describedby={error ? 'resident-search-error' : undefined}
                    autoComplete="off"
                    className="glass-input text-sm py-2 flex-1 min-w-0"
                />
                <button
                    type="submit"
                    disabled={busy}
                    className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium bg-white/10 border border-white/15 text-white hover:bg-white/15 transition-colors disabled:opacity-60"
                >
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <Search className="w-4 h-4" aria-hidden="true" />}
                    Search
                </button>
            </form>
            {error && <p id="resident-search-error" className="text-xs text-red-400" role="alert">{error}</p>}

            <AnimatePresence initial={false}>
                {result && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden"
                    >
                        <p className="text-xs text-white/50 pt-1" role="status">
                            {result.total === 0
                                ? 'No reports you have access to match exactly.'
                                : `${result.total} report${result.total === 1 ? '' : 's'} found${result.total > result.reports.length ? `, showing the ${result.reports.length} most recent` : ''}.`}
                        </p>
                        {result.reports.length > 0 && <ReportRows reports={result.reports} onOpen={onOpen} />}
                    </motion.div>
                )}
            </AnimatePresence>

            <AuditFooter>Exact match on the full {mode === 'email' ? 'address' : 'name'}. Searches are logged without what you typed.</AuditFooter>
        </div>
    );
}
