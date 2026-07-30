import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ChevronDown, RefreshCw } from 'lucide-react';

import { api } from '../services/api';
import type { ClientErrorEntry } from '../types';

/**
 * Browser crashes, shown to the administrator.
 *
 * The error screen tells whoever hit it that the crash "has been reported".
 * That was true only in the sense that a line went into the application log --
 * which for a town self-hosting this, with no Sentry, is the same as nowhere.
 * The promise resolved to a container log that rotates away in days. This is
 * where the promise is kept.
 *
 * Identical crashes arrive collapsed with a count, because a render loop emits
 * hundreds of the same error in seconds and a list of hundreds of identical
 * rows hides every other fault on the page.
 */
function ago(iso: string | null): string {
    if (!iso) return '';
    const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (secs < 90) return 'just now';
    const mins = Math.round(secs / 60);
    if (mins < 90) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 36) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
}

function ErrorRow({ entry }: { entry: ClientErrorEntry }) {
    const [open, setOpen] = useState(false);
    // The component tree is usually more use than the JS stack: production
    // frames are minified, so a stack reads "at Ke (index-abc.js:12:3)" while
    // the tree still names real components.
    const detail = entry.component_stack || entry.stack;

    return (
        <div className="rounded-xl bg-white/[0.03] border border-white/10 overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen(v => !v)}
                disabled={!detail}
                className="w-full text-left px-3.5 py-3 flex items-start gap-3 hover:bg-white/[0.03] disabled:hover:bg-transparent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                aria-expanded={open}
            >
                <AlertTriangle className="w-4 h-4 text-amber-300/80 mt-0.5 shrink-0" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                    <p className="text-sm text-white/85 break-words">{entry.message}</p>
                    <p className="text-[11px] text-white/40 mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                        {entry.url && <span className="font-mono truncate max-w-[22rem]">{entry.url}</span>}
                        <span>{ago(entry.last_seen_at)}</span>
                        {entry.occurrences > 1 && (
                            <span className="text-amber-300/70 font-medium">seen {entry.occurrences} times</span>
                        )}
                    </p>
                </div>
                {detail && (
                    <ChevronDown
                        className={`w-4 h-4 text-white/30 shrink-0 mt-0.5 transition-transform ${open ? 'rotate-180' : ''}`}
                        aria-hidden="true"
                    />
                )}
            </button>
            {open && detail && (
                <pre className="px-3.5 pb-3 text-[11px] leading-relaxed text-white/50 whitespace-pre-wrap break-words font-mono max-h-64 overflow-y-auto">
                    {detail}
                </pre>
            )}
        </div>
    );
}

export default function ClientErrorPanel() {
    const [errors, setErrors] = useState<ClientErrorEntry[] | null>(null);
    const [busy, setBusy] = useState(false);
    const [failed, setFailed] = useState(false);

    const load = useCallback(async () => {
        setBusy(true);
        try {
            setErrors((await api.getClientErrors()).errors);
            setFailed(false);
        } catch {
            // Distinguished from "no errors": a panel that cannot load must not
            // render as an all-clear, which is the same mistake the connector
            // badges used to make.
            setFailed(true);
        } finally {
            setBusy(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    return (
        <div className="setup-panel p-5">
            <div className="relative flex items-start justify-between gap-4 mb-4 flex-wrap">
                <div>
                    <h3 className="font-semibold text-white">Browser errors</h3>
                    <p className="text-white/50 text-xs mt-0.5">
                        Crashes staff and residents have hit. Identical ones are grouped.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={load}
                    disabled={busy}
                    className="inline-flex items-center gap-1.5 text-xs text-white/60 hover:text-white transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 rounded"
                >
                    <RefreshCw className={`w-3.5 h-3.5 ${busy ? 'animate-spin' : ''}`} aria-hidden="true" />
                    Refresh
                </button>
            </div>

            <div className="relative">
                {failed ? (
                    <p className="text-sm text-amber-200/75">
                        Could not load the error list. That is itself worth investigating.
                    </p>
                ) : errors === null ? (
                    <p className="text-sm text-white/40">Loading…</p>
                ) : errors.length === 0 ? (
                    <p className="text-sm text-white/45">
                        Nothing reported. Browser crashes will appear here automatically.
                    </p>
                ) : (
                    <div className="space-y-2">
                        {errors.map(e => <ErrorRow key={e.id} entry={e} />)}
                    </div>
                )}
            </div>
        </div>
    );
}
