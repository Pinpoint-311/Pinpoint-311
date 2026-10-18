import { useCallback, useEffect, useState } from 'react';
import { Gauge } from 'lucide-react';
import { api, type TranslationBudgetPeriod, type TranslationBudgetUsage } from '../services/api';
import { Chip, type ChipTone } from './ui';

/**
 * Translation spend against the town's character budget, on the translation
 * provider card.
 *
 * The public translate endpoint is unauthenticated, so the server refuses to
 * send more than the day's or the month's budget to the provider and serves
 * residents the untranslated text instead. This is where an admin sees how
 * close that is and moves the line. Cache hits are free and never counted.
 */

const fmt = (n: number) => n.toLocaleString('en-US');

export function periodTone(p: TranslationBudgetPeriod): { tone: ChipTone; label: string } {
    if (p.exhausted || p.percent >= 100) return { tone: 'danger', label: 'Budget reached' };
    if (p.percent >= 80) return { tone: 'warning', label: 'Near limit' };
    return { tone: 'success', label: 'Within budget' };
}

function Meter({ title, period, resets }: { title: string; period: TranslationBudgetPeriod; resets: string }) {
    const { tone, label } = periodTone(period);
    const pct = Math.max(0, Math.min(100, period.percent));
    const bar = tone === 'danger' ? 'bg-red-400' : tone === 'warning' ? 'bg-amber-400' : 'bg-emerald-400';
    const id = `translation-budget-${title.toLowerCase().replace(/\s+/g, '-')}`;
    return (
        <div className="space-y-1.5" data-testid={id}>
            <div className="flex items-center justify-between gap-2">
                <span id={`${id}-label`} className="text-white/80 text-xs font-medium">{title}</span>
                <Chip tone={tone}>{label}</Chip>
            </div>
            <div
                role="progressbar"
                aria-labelledby={`${id}-label`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(pct)}
                aria-valuetext={`${fmt(period.used)} of ${fmt(period.limit)} characters`}
                className="h-1.5 rounded-full bg-white/10 overflow-hidden"
            >
                <div className={`h-full ${bar}`} style={{ width: `${pct}%` }} />
            </div>
            <p className="text-white/60 text-[11px]">
                {fmt(period.used)} of {fmt(period.limit)} characters ({period.percent}%) · resets {resets}
            </p>
        </div>
    );
}

export default function TranslationBudgetPanel() {
    const [usage, setUsage] = useState<TranslationBudgetUsage | null>(null);
    const [editing, setEditing] = useState(false);
    const [daily, setDaily] = useState('');
    const [monthly, setMonthly] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setUsage(await api.getTranslationBudget());
        } catch {
            setUsage(null);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    // Nothing to show (no access, or an older server): render nothing rather
    // than a meter of zeros that reads as "no spend".
    if (!usage?.day || !usage?.month) return null;

    const startEdit = () => {
        setDaily(String(usage.day.limit));
        setMonthly(String(usage.month.limit));
        setError(null);
        setEditing(true);
    };

    const save = async () => {
        const d = Number(daily.replace(/[,_\s]/g, ''));
        const m = Number(monthly.replace(/[,_\s]/g, ''));
        if (!Number.isInteger(d) || !Number.isInteger(m) || d < 0 || m < 0) {
            setError('Enter whole numbers of characters, zero or more.');
            return;
        }
        if (d > m) {
            setError('The daily budget cannot be larger than the monthly budget.');
            return;
        }
        setSaving(true);
        setError(null);
        try {
            setUsage(await api.updateTranslationBudget(d, m));
            setEditing(false);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Could not save the budget.');
        } finally {
            setSaving(false);
        }
    };

    const input = 'w-full bg-white/[0.04] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-primary-400/60';

    return (
        <section aria-labelledby="translation-budget-heading" className="rounded-lg bg-white/[0.03] border border-white/10 px-3 py-3 space-y-3">
            <div className="flex items-center justify-between gap-2">
                <h4 id="translation-budget-heading" className="text-white/90 text-xs font-semibold flex items-center gap-1.5">
                    <Gauge className="w-3.5 h-3.5 text-primary-300/80" aria-hidden="true" />
                    Translation budget
                </h4>
                {!editing && (
                    <button type="button" className="btn-outline" onClick={startEdit}>Change budget</button>
                )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Meter title="Today" period={usage.day} resets="at midnight UTC" />
                <Meter title="This month" period={usage.month} resets="on the 1st" />
            </div>
            <p className="text-white/55 text-[11px] leading-relaxed">
                Only characters sent to the provider count; anything already translated is served
                from the cache for free. Past either budget, residents see the original text until it resets.
            </p>
            {usage.counter_store === 'memory' && (
                <p role="status" className="text-amber-300/90 text-[11px]">
                    The shared counter (Redis) is unreachable, so each server process is counting on its own.
                </p>
            )}
            {editing && (
                <form
                    className="grid gap-2 sm:grid-cols-[1fr_1fr_auto] items-end"
                    onSubmit={e => { e.preventDefault(); save(); }}
                >
                    <label className="text-white/70 text-[11px] space-y-1">
                        <span>Characters per day</span>
                        <input className={input} inputMode="numeric" value={daily} onChange={e => setDaily(e.target.value)} />
                    </label>
                    <label className="text-white/70 text-[11px] space-y-1">
                        <span>Characters per month</span>
                        <input className={input} inputMode="numeric" value={monthly} onChange={e => setMonthly(e.target.value)} />
                    </label>
                    <div className="flex gap-2">
                        <button type="submit" className="btn-outline" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
                        <button type="button" className="btn-outline" disabled={saving} onClick={() => setEditing(false)}>Cancel</button>
                    </div>
                    <p className="text-white/50 text-[11px] sm:col-span-3">
                        Defaults: {fmt(usage.defaults?.daily ?? 500000)} a day, {fmt(usage.defaults?.monthly ?? 5000000)} a month.
                        Zero serves only what is already translated.
                    </p>
                </form>
            )}
            {error && <p role="alert" className="text-red-300 text-[11px]">{error}</p>}
        </section>
    );
}
