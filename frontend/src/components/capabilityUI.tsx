import type { ReactNode } from 'react';
import { Check, AlertCircle, CircleDashed, HelpCircle, ChevronDown, Loader2 } from 'lucide-react';

/**
 * The shared vocabulary for a capability, wherever it appears.
 *
 * A capability shows up twice: inside the setup guide, where the question is
 * "how do I configure this", and on the standing cards below, where it is "is
 * it still working and where do I change it". Those are different jobs and
 * different layouts, but they are the same object and must not look like two
 * different products.
 *
 * They already had, twice. The provider cards and the department cards drifted
 * apart because each was hand-rolled from utility classes, and fixing one did
 * nothing for the other. This module is the answer to being asked to keep them
 * in sync: not a convention to remember, but one tile, one status pill and one
 * pair of buttons that both surfaces import. Restyling either now means editing
 * this file, and there is nowhere else to edit.
 */

export type CapabilityState =
    | 'working'      // a live check succeeded recently
    | 'failing'      // a live check failed, and we have the provider's words
    | 'unchecked'    // configured, but nothing has exercised it
    | 'unverifiable' // configured, and there is no way to check it from here
    | 'unset'        // deliberately not set up
    | 'done'         // setup finished (the guide's version of working)
    | 'todo';        // setup outstanding

/* Deliberately not merging `unchecked` into `failing` or `working`. A connector
 * nobody has exercised is not healthy and it is not broken; collapsing it into
 * either is how a revoked key keeps a green tick for a month. */
const PILL: Record<CapabilityState, { cls: string; label: string; Icon: typeof Check }> = {
    working: {
        cls: 'bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border-emerald-500/30 shadow-md shadow-emerald-950/40',
        label: 'Working', Icon: Check,
    },
    done: {
        cls: 'bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border-emerald-500/30 shadow-md shadow-emerald-950/40',
        label: 'Set up', Icon: Check,
    },
    failing: {
        cls: 'bg-gradient-to-r from-red-500/25 to-rose-500/20 text-red-200 border-red-400/35 shadow-md shadow-red-950/40',
        label: 'Not working', Icon: AlertCircle,
    },
    unchecked: {
        cls: 'bg-white/[0.07] text-white/70 border-white/15',
        label: 'Not checked yet', Icon: CircleDashed,
    },
    /* Not amber, and not grouped with the failures.
     *
     * A generic HTTP gateway cannot be exercised without sending a real text
     * message, so there is no check to run and there never will be. Reporting
     * that as "Not working" -- which is what happened -- is a red badge that
     * can never go green, and the whole page has been built around not doing
     * that. It is also not "not checked yet", which implies somebody could. */
    unverifiable: {
        cls: 'bg-white/[0.07] text-white/70 border-white/15',
        label: 'Set up · we cannot test this one', Icon: HelpCircle,
    },
    unset: {
        cls: 'bg-white/[0.05] text-white/55 border-white/12',
        label: 'Not set up', Icon: CircleDashed,
    },
    todo: {
        cls: 'bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border-amber-500/30 shadow-md shadow-amber-950/40',
        label: 'Needs setting up', Icon: CircleDashed,
    },
};

export function StatusPill({ state, label }: { state: CapabilityState; label?: string }) {
    const p = PILL[state];
    return (
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-2xl text-xs font-semibold border shrink-0 ${p.cls}`}>
            <p.Icon className="w-3.5 h-3.5" aria-hidden="true" />
            {label ?? p.label}
        </span>
    );
}

/** The gradient tile behind every capability icon.
 *
 * `label` is the fallback for things that have no icon of their own -- the
 * guide's steps are numbered rather than pictured. Giving those the same tile
 * is the point: a step in the guide and a capability on a card are the same
 * object at two moments in its life, and used to be drawn as a 24px circle in
 * one place and a 44px gradient square in the other.
 */
export function CapabilityTile({ icon: Icon, label, size = 'md', tone = 'normal', badge }: {
    icon?: React.ElementType;
    label?: ReactNode;
    size?: 'sm' | 'md' | 'lg';
    tone?: 'normal' | 'alert' | 'done';
    /** A step number, for the guide's numbered list. */
    badge?: ReactNode;
}) {
    const box = { sm: 'w-9 h-9 rounded-xl', md: 'w-11 h-11 rounded-2xl', lg: 'w-14 h-14 rounded-2xl' }[size];
    const glyph = { sm: 'w-4 h-4', md: 'w-5 h-5', lg: 'w-7 h-7' }[size];
    const type = { sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size];
    const skin = {
        alert: 'bg-gradient-to-br from-red-500/30 to-rose-600/20 border-red-400/35 text-red-200',
        done: 'bg-gradient-to-br from-emerald-500/25 to-teal-500/15 border-emerald-400/30 text-emerald-200',
        normal: 'bg-gradient-to-br from-primary-500/25 via-indigo-500/20 to-purple-500/15 border-white/20 text-primary-200',
    }[tone];
    return (
        <div className={`relative shrink-0 flex items-center justify-center border shadow-inner ${box} ${skin}`}>
            {Icon ? <Icon className={glyph} /> : <span className={`${type} font-bold tabular-nums`}>{label}</span>}
            {badge != null && (
                <span className="absolute -top-1.5 -left-1.5 w-5 h-5 rounded-full bg-primary-500 border-2 border-slate-900 text-[10px] font-bold text-white flex items-center justify-center">
                    {badge}
                </span>
            )}
        </div>
    );
}

/**
 * The two buttons a capability ever offers.
 *
 * One pair, so "Save & Test" in the guide and "Test now" on a card are visibly
 * the same kind of control. Both are 2xl-radius to match the pills and the
 * tiles; the primary carries the indigo gradient and its own shadow, which is
 * what the rest of the console uses for the one action a screen is about.
 */
export function Action({
    variant = 'ghost', size = 'md', busy = false, disabled, onClick, children, title, chevron = false,
}: {
    variant?: 'primary' | 'ghost';
    size?: 'sm' | 'md';
    busy?: boolean;
    disabled?: boolean;
    onClick?: () => void;
    children: ReactNode;
    title?: string;
    chevron?: boolean;
}) {
    const pad = size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm';
    const skin = variant === 'primary'
        ? 'font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 border-primary-400/50 shadow-lg shadow-primary-500/25 hover:shadow-primary-500/40'
        : 'font-medium text-white/85 hover:text-white bg-white/[0.08] hover:bg-white/[0.15] border-white/20 hover:border-white/30';
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled || busy}
            title={title}
            className={`${pad} ${skin} rounded-2xl border inline-flex items-center gap-1.5 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300`}
        >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />}
            {children}
            {chevron && <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />}
        </button>
    );
}

/* CapabilityRow was here.
 *
 * Written to reshape the setup guide's task rows onto the same component the
 * cards use, then left unused when the two surfaces were deliberately given
 * different layouts -- one is a walk through setup, the other is "is anything
 * wrong". Dead code that looks like a shared abstraction is worse than none:
 * the next person to touch this reasonably assumes both surfaces render it.
 *
 * What they actually share is below and above -- the tile, the pill and the
 * buttons -- which is the part that has to stay identical. */
