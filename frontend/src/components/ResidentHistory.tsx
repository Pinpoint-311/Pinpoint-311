import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { History, Lock, Loader2, ChevronRight, ChevronDown, UserSearch } from 'lucide-react';

import { api } from '../services/api';
import type { ResidentHistoryItem } from '../types';

/**
 * The opt-in "Resident history" module, staff side.
 *
 * Two pieces: a card on a request showing the same resident's other reports
 * (matched by email), and a collapsible "Search by resident" option for an exact
 * full email or full name.
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

/** Other reports from the same resident email, on a request's detail view. */
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
                        Other reports from this resident
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
                    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Checking other reports…
                </div>
            )}
            {state.kind === 'error' && (
                <p className="py-2 text-sm text-amber-300/90" role="alert">{state.message}</p>
            )}
            {state.kind === 'ready' && !state.matched && (
                <p className="py-2 text-sm text-white/50">This report has no email address to match on.</p>
            )}
            {state.kind === 'ready' && state.matched && state.reports.length === 0 && (
                <p className="py-2 text-sm text-white/50">No other reports from this email address that you have access to.</p>
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

/** "Search by resident": exact search by full email address or full name.
 *  A quiet link until opened; then one field that works out from the "@"
 *  whether it was given an email or a name. */
export function ResidentSearch({ onOpen }: { onOpen: (id: string) => void }) {
    const [open, setOpen] = useState(false);
    const [value, setValue] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [result, setResult] = useState<{ total: number; reports: ResidentHistoryItem[] } | null>(null);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        const v = value.trim();
        const isEmail = v.includes('@');
        if (!v) {
            setError('Enter a full email address or a first and last name');
            return;
        }
        if (isEmail && !/\S+@\S+\.\S+/.test(v)) {
            setError('Enter the full email address');
            return;
        }
        if (!isEmail && v.split(/\s+/).length < 2) {
            setError('Enter both a first and a last name');
            return;
        }
        setBusy(true);
        setError('');
        try {
            const res = await api.searchResidents(isEmail ? { email: v } : { name: v });
            setResult({ total: res.total, reports: res.reports });
        } catch (err: any) {
            setResult(null);
            setError(err?.message || "Couldn't search. Try again.");
        } finally {
            setBusy(false);
        }
    };

    return (
        <div>
            <button
                type="button"
                onClick={() => setOpen(o => !o)}
                aria-expanded={open}
                aria-controls="resident-search-panel"
                className="inline-flex items-center gap-1.5 text-xs font-medium text-white/55 hover:text-white/85 transition-colors"
            >
                <UserSearch className="w-3.5 h-3.5" aria-hidden="true" />
                Search by resident
                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>

            <AnimatePresence initial={false}>
                {open && (
                    <motion.div
                        id="resident-search-panel"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden"
                    >
                        <form onSubmit={submit} className="relative mt-2">
                            <UserSearch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40 z-10" aria-hidden="true" />
                            <input
                                type="text"
                                value={value}
                                onChange={e => { setValue(e.target.value); setError(''); }}
                                placeholder="Full email or full name"
                                aria-label="Resident's full email address or full name"
                                aria-invalid={!!error}
                                aria-describedby={error ? 'resident-search-error' : 'resident-search-note'}
                                autoComplete="off"
                                className="glass-input pl-10 pr-10 py-2 text-sm"
                            />
                            <button
                                type="submit"
                                disabled={busy}
                                aria-label="Search by resident"
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-white/50 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-60"
                            >
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <ChevronRight className="w-4 h-4" aria-hidden="true" />}
                            </button>
                        </form>
                        {error
                            ? <p id="resident-search-error" className="text-xs text-red-400 mt-1.5" role="alert">{error}</p>
                            : <p id="resident-search-note" className="flex items-center gap-1 text-[11px] text-white/40 mt-1.5">
                                <Lock className="w-3 h-3" aria-hidden="true" /> Exact match · searches are logged
                            </p>}

                        {result && (
                            <div className="mt-2">
                                <p className="text-xs text-white/50" role="status">
                                    {result.total === 0
                                        ? 'No matching reports you have access to.'
                                        : `${result.total} report${result.total === 1 ? '' : 's'} found${result.total > result.reports.length ? `, showing the ${result.reports.length} most recent` : ''}.`}
                                </p>
                                {result.reports.length > 0 && <ReportRows reports={result.reports} onOpen={onOpen} />}
                            </div>
                        )}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
