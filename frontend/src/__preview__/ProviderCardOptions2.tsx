import {
    Check, AlertCircle, CircleDashed, ChevronDown, Sparkles, KeyRound,
    Map as MapIcon, Mail, MessageSquare, Lock, Image as ImageIcon, Languages,
} from 'lucide-react';

/**
 * Four more designs for the standing provider cards, in the console's own
 * idiom rather than a generic admin table.
 *
 * The first three were too utilitarian. The vocabulary this product already
 * has is a bubbly premium glassmorphism: 24px radii, a gradient tile behind
 * every icon, a glow bar across the top edge, gradient pills for state, a real
 * drop shadow and a lift on hover. These use it.
 *
 * Same eight capabilities and the same mixed states as the first set, so the
 * comparison is of the treatment and not of the content. Mockups: whichever is
 * chosen gets built against the live catalog and connector health.
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

/** Gradient pills, the same shape the service-category badges already use. */
const PILL: Record<State, { cls: string; label: string; Icon: typeof Check }> = {
    working: {
        cls: 'bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border-emerald-500/30 shadow-md shadow-emerald-950/40',
        label: 'Working', Icon: Check,
    },
    failing: {
        cls: 'bg-gradient-to-r from-red-500/25 to-rose-500/20 text-red-200 border-red-400/35 shadow-md shadow-red-950/40',
        label: 'Not working', Icon: AlertCircle,
    },
    unchecked: {
        cls: 'bg-white/[0.07] text-white/65 border-white/15',
        label: 'Not checked yet', Icon: CircleDashed,
    },
    unset: {
        cls: 'bg-white/[0.04] text-white/50 border-white/10',
        label: 'Not set up', Icon: CircleDashed,
    },
};

function Pill({ state }: { state: State }) {
    const p = PILL[state];
    return (
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-2xl text-xs font-semibold border ${p.cls}`}>
            <p.Icon className="w-3.5 h-3.5" aria-hidden="true" />
            {p.label}
        </span>
    );
}

function Tile({ icon: Icon, size = 'md' }: { icon: typeof Sparkles; size?: 'md' | 'lg' }) {
    const d = size === 'lg' ? 'w-14 h-14 rounded-2xl' : 'w-11 h-11 rounded-2xl';
    return (
        <div className={`${d} shrink-0 flex items-center justify-center bg-gradient-to-br from-primary-500/25 via-indigo-500/20 to-purple-500/15 border border-white/20 shadow-inner text-primary-200`}>
            <Icon className={size === 'lg' ? 'w-7 h-7' : 'w-5 h-5'} />
        </div>
    );
}

function Actions({ compact = false }: { compact?: boolean }) {
    const base = compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm';
    return (
        <div className="flex items-center gap-2 shrink-0">
            <button type="button" className={`${base} rounded-2xl font-medium text-white/85 hover:text-white bg-white/[0.08] hover:bg-white/[0.15] border border-white/20 transition-all`}>
                Test now
            </button>
            <button type="button" className={`${base} rounded-2xl font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 border border-primary-400/50 shadow-lg shadow-primary-500/25 transition-all inline-flex items-center gap-1.5`}>
                Edit <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />
            </button>
        </div>
    );
}

/* ── 4. Bubble rows ─────────────────────────────────────────────────────────
   Each capability its own floating glass pill with air between them, rather
   than rows divided by hairlines. Keeps the density of a list while looking
   like the rest of the console. */
export function OptionBubble() {
    return (
        <div className="space-y-3">
            {ROWS.map(r => (
                <div
                    key={r.title}
                    className="group relative flex items-center gap-4 px-5 py-4 rounded-3xl bg-gradient-to-br from-white/[0.07] via-white/[0.02] to-indigo-950/40 border border-white/12 backdrop-blur-2xl shadow-[0_10px_30px_rgba(0,0,0,0.35)] hover:shadow-[0_20px_50px_rgba(99,102,241,0.22)] hover:border-primary-400/45 hover:-translate-y-0.5 transition-all duration-300"
                >
                    <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-primary-400/40 to-transparent" aria-hidden="true" />
                    <Tile icon={r.icon} />
                    <div className="min-w-0 w-52">
                        <p className="font-semibold text-white group-hover:text-primary-100 transition-colors truncate">{r.title}</p>
                        <p className="text-xs text-white/55 truncate mt-0.5">{r.provider}</p>
                    </div>
                    <div className="min-w-0 flex-1 flex items-center gap-3">
                        <Pill state={r.state} />
                        <span className="text-xs text-white/45 truncate">
                            {r.detail ?? (r.checked ? `checked ${r.checked}` : '')}
                        </span>
                    </div>
                    <Actions compact />
                </div>
            ))}
        </div>
    );
}

/* ── 5. Aurora tiles ────────────────────────────────────────────────────────
   Two columns of full glass cards, each with the aurora glow this console uses
   behind section headers. The most decorative of the four, and the one that
   looks most like the resident-facing side of the product. */
export function OptionAurora() {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {ROWS.map(r => (
                <div
                    key={r.title}
                    className="group relative overflow-hidden p-6 rounded-3xl bg-gradient-to-br from-white/[0.08] via-white/[0.03] to-indigo-950/40 border border-white/15 backdrop-blur-2xl shadow-[0_10px_30px_rgba(0,0,0,0.35)] hover:shadow-[0_20px_50px_rgba(99,102,241,0.25)] hover:border-primary-400/50 hover:-translate-y-1 transition-all duration-300"
                >
                    <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-transparent via-primary-400/45 to-transparent rounded-t-3xl" aria-hidden="true" />
                    <div
                        className={`aurora-glow w-40 h-40 -top-14 -right-10 ${r.state === 'failing' ? 'opacity-40' : 'opacity-30'}`}
                        style={r.state === 'failing'
                            ? { background: 'radial-gradient(closest-side, rgba(244,63,94,0.5), transparent)' }
                            : undefined}
                        aria-hidden="true"
                    />
                    <div className="relative">
                        <div className="flex items-start justify-between gap-3">
                            <Tile icon={r.icon} size="lg" />
                            <Pill state={r.state} />
                        </div>
                        <h3 className="font-bold text-lg text-white tracking-tight mt-4 group-hover:text-primary-100 transition-colors">
                            {r.title}
                        </h3>
                        <p className="text-sm text-white/60 mt-0.5">{r.provider}</p>
                        <p className={`text-xs mt-2 min-h-[16px] ${r.state === 'failing' ? 'text-red-200/80' : 'text-white/45'}`}>
                            {r.detail ?? (r.checked ? `Checked ${r.checked}` : 'No check recorded yet')}
                        </p>
                        <div className="flex items-center justify-end gap-2.5 mt-5 pt-4 border-t border-white/10">
                            <Actions />
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
}

/* ── 6. Spotlight ───────────────────────────────────────────────────────────
   Anything wrong gets a full-width glass card with a coloured aurora; the rest
   become small bubbles in a grid. The status-first idea from option 3, in the
   console's own idiom rather than as a plain table. */
export function OptionSpotlight() {
    const wrong = ROWS.filter(r => r.state === 'failing' || r.state === 'unchecked');
    const rest = ROWS.filter(r => r.state === 'working' || r.state === 'unset');
    return (
        <div className="space-y-5">
            {wrong.map(r => {
                const bad = r.state === 'failing';
                return (
                    <div
                        key={r.title}
                        className={`relative overflow-hidden p-6 rounded-3xl border backdrop-blur-2xl shadow-[0_14px_40px_rgba(0,0,0,0.4)] ${bad
                            ? 'bg-gradient-to-br from-red-500/[0.14] via-white/[0.02] to-indigo-950/40 border-red-400/30'
                            : 'bg-gradient-to-br from-white/[0.08] via-white/[0.02] to-indigo-950/40 border-white/15'}`}
                    >
                        <div
                            className="aurora-glow w-64 h-64 -top-24 -left-10 opacity-45"
                            style={bad ? { background: 'radial-gradient(closest-side, rgba(244,63,94,0.5), transparent)' } : undefined}
                            aria-hidden="true"
                        />
                        <div className="relative flex items-start gap-5 flex-wrap">
                            <div className={`w-14 h-14 shrink-0 rounded-2xl flex items-center justify-center border shadow-inner ${bad
                                ? 'bg-gradient-to-br from-red-500/30 to-rose-600/20 border-red-400/35 text-red-200'
                                : 'bg-gradient-to-br from-primary-500/25 to-purple-500/15 border-white/20 text-primary-200'}`}>
                                {bad ? <AlertCircle className="w-7 h-7" /> : <CircleDashed className="w-7 h-7" />}
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-3 flex-wrap">
                                    <h3 className="font-bold text-lg text-white tracking-tight">{r.title}</h3>
                                    <Pill state={r.state} />
                                </div>
                                <p className={`mt-1.5 ${bad ? 'text-red-100/90' : 'text-white/70'}`}>
                                    {r.detail ?? 'Nothing has used this yet, so we cannot say whether it works.'}
                                </p>
                                <p className="text-xs text-white/50 mt-1.5">
                                    {r.provider}{r.checked ? ` · checked ${r.checked}` : ''}
                                </p>
                            </div>
                            <Actions />
                        </div>
                    </div>
                );
            })}

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {rest.map(r => (
                    <div
                        key={r.title}
                        className="group relative px-4 py-4 rounded-3xl bg-gradient-to-br from-white/[0.06] via-white/[0.02] to-indigo-950/40 border border-white/10 backdrop-blur-2xl hover:border-primary-400/40 hover:-translate-y-0.5 transition-all duration-300"
                    >
                        <div className="flex items-center gap-3">
                            <Tile icon={r.icon} />
                            <div className="min-w-0 flex-1">
                                <p className="font-semibold text-white text-sm truncate">{r.title}</p>
                                <p className="text-[11px] text-white/50 truncate">{r.provider}</p>
                            </div>
                            <span className={`shrink-0 ${r.state === 'working' ? 'text-emerald-300' : 'text-white/30'}`} aria-hidden="true">
                                {r.state === 'working' ? <Check className="w-4 h-4" /> : <CircleDashed className="w-4 h-4" />}
                            </span>
                        </div>
                        <p className="text-[11px] text-white/45 mt-2.5">
                            {r.checked ? `Checked ${r.checked}` : 'Optional — not set up'}
                        </p>
                    </div>
                ))}
            </div>
        </div>
    );
}

/* ── 7. Inset panel ─────────────────────────────────────────────────────────
   One outer glass panel holding soft inner bubbles, the way the setup guide
   holds its steps. Groups the whole set as one object on the page instead of
   eight competing ones, which matters when this sits under other sections. */
export function OptionInset() {
    return (
        <div className="setup-panel p-5 sm:p-6">
            <div className="flex items-baseline justify-between gap-3 mb-4 flex-wrap">
                <h3 className="font-bold text-white">Service providers</h3>
                <p className="text-xs text-white/50">
                    <span className="text-emerald-300 font-semibold">5 working</span> · 1 not working · 1 unchecked · 1 off
                </p>
            </div>
            <div className="space-y-2.5">
                {ROWS.map(r => (
                    <div
                        key={r.title}
                        className={`group flex items-center gap-4 px-4 py-3 rounded-2xl border transition-all duration-200 ${r.state === 'failing'
                            ? 'bg-red-500/[0.09] border-red-400/25 hover:border-red-400/40'
                            : 'bg-white/[0.045] border-white/10 hover:bg-white/[0.075] hover:border-white/20'}`}
                    >
                        <Tile icon={r.icon} />
                        <div className="min-w-0 w-48">
                            <p className="font-semibold text-white text-sm truncate">{r.title}</p>
                            <p className="text-[11px] text-white/55 truncate">{r.provider}</p>
                        </div>
                        <div className="min-w-0 flex-1 flex items-center gap-3">
                            <Pill state={r.state} />
                            <span className="text-[11px] text-white/45 truncate hidden lg:block">
                                {r.detail ?? (r.checked ? `checked ${r.checked}` : '')}
                            </span>
                        </div>
                        <Actions compact />
                    </div>
                ))}
            </div>
        </div>
    );
}
