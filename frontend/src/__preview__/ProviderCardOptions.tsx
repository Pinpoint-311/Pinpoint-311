import {
    Check, AlertCircle, Loader2, ChevronDown, Sparkles, KeyRound,
    Map as MapIcon, Mail, MessageSquare, Lock, Image as ImageIcon, Languages,
} from 'lucide-react';

/**
 * Three candidate designs for the standing provider cards.
 *
 * Not the setup wizard -- these are what a town looks at after setup, when the
 * question is no longer "how do I configure this" but "is it still working, and
 * where do I change it".
 *
 * Mockups, deliberately: the live card needs a catalog, connector health and a
 * cloud profile to render, and stubbing all of that to compare three visual
 * treatments would prove less than it costs. Whichever is chosen gets built for
 * real in ServiceProviders.tsx against the live data.
 *
 * The sample deliberately mixes states, because a page where everything is
 * green is the easy case and not the one worth designing for.
 */

type State = 'working' | 'failing' | 'unchecked' | 'unset';

interface Row {
    icon: typeof Sparkles;
    title: string;
    provider: string;
    state: State;
    checked?: string;
    detail?: string;
}

const ROWS: Row[] = [
    { icon: KeyRound, title: 'Staff sign-in', provider: 'Microsoft Entra ID', state: 'working', checked: '6 hours ago' },
    { icon: MapIcon, title: 'Maps', provider: 'Google Maps', state: 'working', checked: '6 hours ago' },
    { icon: Sparkles, title: 'AI triage', provider: 'Azure OpenAI · gpt-4o', state: 'failing', checked: '20 minutes ago', detail: '401 — the API key was rejected' },
    { icon: Languages, title: 'Translation', provider: 'Azure Translator', state: 'working', checked: 'yesterday' },
    { icon: Mail, title: 'Email', provider: 'Azure Communication Services', state: 'unchecked' },
    { icon: MessageSquare, title: 'Text messages', provider: 'Not set up', state: 'unset' },
    { icon: Lock, title: 'Key management', provider: 'Azure Key Vault', state: 'working', checked: '6 hours ago' },
    { icon: ImageIcon, title: 'Photo redaction', provider: 'On this server', state: 'working', checked: '6 hours ago' },
];

const TONE: Record<State, { dot: string; text: string; label: string }> = {
    working: { dot: 'bg-emerald-400', text: 'text-emerald-300', label: 'Working' },
    failing: { dot: 'bg-red-400', text: 'text-red-300', label: 'Not working' },
    unchecked: { dot: 'bg-white/35', text: 'text-white/55', label: 'Not checked yet' },
    unset: { dot: 'bg-white/20', text: 'text-white/45', label: 'Not set up' },
};

function Actions({ compact = false }: { compact?: boolean }) {
    const base = compact
        ? 'px-2.5 py-1.5 text-xs rounded-lg'
        : 'px-3.5 py-2 text-sm rounded-xl';
    return (
        <div className="flex items-center gap-2 shrink-0">
            <button type="button" className={`${base} font-medium text-white/80 hover:text-white bg-white/[0.07] hover:bg-white/[0.13] border border-white/15 transition-colors`}>
                Test now
            </button>
            <button type="button" className={`${base} font-medium text-white/70 hover:text-white hover:bg-white/[0.08] border border-transparent hover:border-white/15 transition-colors inline-flex items-center gap-1.5`}>
                Edit <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />
            </button>
        </div>
    );
}

/* ── 1. Row ─────────────────────────────────────────────────────────────────
   A list, not a grid. Eight capabilities at a glance with the states lined up
   in a column, so "which one is red" is answered by scanning rather than
   reading. The densest of the three and the least like a dashboard. */
export function OptionRow() {
    return (
        <div className="setup-panel divide-y divide-white/[0.06] overflow-hidden">
            {ROWS.map(r => {
                const t = TONE[r.state];
                return (
                    <div key={r.title} className="flex items-center gap-4 px-5 py-3.5 hover:bg-white/[0.03] transition-colors">
                        <div className="setup-tile w-9 h-9 rounded-xl flex items-center justify-center shrink-0">
                            <r.icon className="w-4 h-4 text-white" />
                        </div>
                        <div className="min-w-0 w-56">
                            <p className="text-sm font-semibold text-white/90 truncate">{r.title}</p>
                            <p className="text-xs text-white/50 truncate">{r.provider}</p>
                        </div>
                        <div className="min-w-0 flex-1">
                            <p className={`text-xs font-medium ${t.text} inline-flex items-center gap-1.5`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${t.dot}`} aria-hidden="true" />
                                {t.label}
                                {r.checked && <span className="text-white/40 font-normal">· checked {r.checked}</span>}
                            </p>
                            {r.detail && <p className="text-[11px] text-red-200/70 truncate mt-0.5">{r.detail}</p>}
                        </div>
                        <Actions compact />
                    </div>
                );
            })}
        </div>
    );
}

/* ── 2. Tile ────────────────────────────────────────────────────────────────
   Two columns of cards, closest to what is there now. More room per capability
   — the model name, the error in full — at the cost of scrolling to see all
   eight and of the states being harder to compare. */
export function OptionTile() {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {ROWS.map(r => {
                const t = TONE[r.state];
                return (
                    <div key={r.title} className="setup-panel p-5">
                        <div className="flex items-start gap-3.5">
                            <div className="setup-tile w-11 h-11 rounded-xl flex items-center justify-center shrink-0">
                                <r.icon className="w-5 h-5 text-white" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <p className="font-semibold text-white truncate">{r.title}</p>
                                <p className="text-xs text-white/50 truncate mt-0.5">{r.provider}</p>
                            </div>
                        </div>
                        <p className={`text-xs font-medium ${t.text} inline-flex items-center gap-1.5 mt-3.5`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${t.dot}`} aria-hidden="true" />
                            {t.label}
                            {r.checked && <span className="text-white/40 font-normal">· checked {r.checked}</span>}
                        </p>
                        {r.detail && <p className="text-[11px] text-red-200/70 mt-1">{r.detail}</p>}
                        <div className="flex items-center justify-end mt-4 pt-3.5 border-t border-white/[0.07]">
                            <Actions />
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

/* ── 3. Status first ────────────────────────────────────────────────────────
   Sorted worst-first, with anything needing attention pulled to the top and
   given a coloured surface. The rest collapse to a quiet line. Answers "is
   anything wrong" before it answers "what have I got", which is the question
   somebody opening this page a month after setup is actually asking. */
export function OptionStatusFirst() {
    const needsAttention = ROWS.filter(r => r.state === 'failing' || r.state === 'unchecked');
    /* Working and "not set up" are different things and must not share a
     * heading. The first draft of this put "Text messages — Not set up" under a
     * bar reading "Working — 5 of 8", which is the same class of lie as a green
     * tick on a revoked key. */
    const working = ROWS.filter(r => r.state === 'working');
    const off = ROWS.filter(r => r.state === 'unset');
    return (
        <div className="space-y-4">
            {needsAttention.map(r => {
                const bad = r.state === 'failing';
                return (
                    <div
                        key={r.title}
                        className={`rounded-2xl border p-5 ${bad
                            ? 'bg-red-500/[0.08] border-red-400/25'
                            : 'bg-white/[0.03] border-white/10'}`}
                    >
                        <div className="flex items-start gap-3.5">
                            <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${bad
                                ? 'bg-red-500/20 border border-red-400/30'
                                : 'setup-tile'}`}>
                                {bad
                                    ? <AlertCircle className="w-5 h-5 text-red-300" />
                                    : <Loader2 className="w-5 h-5 text-white/60" />}
                            </div>
                            <div className="min-w-0 flex-1">
                                <p className="font-semibold text-white">{r.title}</p>
                                <p className={`text-sm mt-0.5 ${bad ? 'text-red-200/85' : 'text-white/60'}`}>
                                    {r.detail ?? 'Nothing has used this yet, so we cannot say whether it works.'}
                                </p>
                                <p className="text-xs text-white/45 mt-1">
                                    {r.provider}{r.checked ? ` · checked ${r.checked}` : ''}
                                </p>
                            </div>
                            <Actions />
                        </div>
                    </div>
                );
            })}

            <div className="setup-panel divide-y divide-white/[0.06] overflow-hidden">
                <p className="px-5 py-2.5 text-[11px] uppercase tracking-wider text-white/40 font-semibold">
                    Working — {working.length} of {ROWS.length}
                </p>
                {working.map(r => {
                    const t = TONE[r.state];
                    return (
                        <div key={r.title} className="flex items-center gap-3.5 px-5 py-3 hover:bg-white/[0.03] transition-colors">
                            <span className={`shrink-0 ${r.state === 'working' ? 'text-emerald-300' : 'text-white/30'}`} aria-hidden="true">
                                {r.state === 'working' ? <Check className="w-4 h-4" /> : <span className="block w-4 h-4 rounded-full border border-current" />}
                            </span>
                            <p className="text-sm text-white/85 w-44 truncate">{r.title}</p>
                            <p className="text-xs text-white/50 flex-1 truncate">{r.provider}</p>
                            <p className={`text-xs ${t.text} shrink-0 hidden sm:block`}>
                                {r.checked ? `checked ${r.checked}` : t.label}
                            </p>
                            <Actions compact />
                        </div>
                    );
                })}
            </div>

            {off.length > 0 && (
                <div className="setup-panel divide-y divide-white/[0.06] overflow-hidden">
                    <p className="px-5 py-2.5 text-[11px] uppercase tracking-wider text-white/40 font-semibold">
                        Switched off — {off.length}
                    </p>
                    {off.map(r => (
                        <div key={r.title} className="flex items-center gap-3.5 px-5 py-3">
                            <span className="shrink-0 block w-4 h-4 rounded-full border border-white/25" aria-hidden="true" />
                            <p className="text-sm text-white/60 w-44 truncate">{r.title}</p>
                            <p className="text-xs text-white/40 flex-1">Not set up — optional</p>
                            <Actions compact />
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
