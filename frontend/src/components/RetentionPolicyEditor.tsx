import { useId, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock, FileSearch, Download, Play, Trash2, Eraser } from 'lucide-react';
import { Button, CheckboxCard } from './ui';
import { api, type ScrubField } from '../services/api';
import { useDialog } from './DialogProvider';

/* The two answers that make a retention policy -- how long a closed request is
 * kept, and what is removed when that is up -- and the actions that apply or
 * run it.
 *
 * No state picker and no default period. It once looked up a retention period
 * in a table of all 51 US jurisdictions that nobody had checked; both answers
 * here come from the town.
 *
 * The field list, its labels and their descriptions are the server's catalog,
 * rendered as served. This file only decides how they are grouped on screen,
 * by id, and anything it does not recognise lands in "Other" rather than
 * being dropped -- a field missing from this screen is a field a town cannot
 * choose to clear. */

export type RetentionMode = 'redact' | 'purge';

export interface SavedRetention {
    days: number;
    mode: RetentionMode;
    fieldIds: string[];
}

interface Props {
    days: string;
    onDaysChange: (days: string) => void;
    mode: RetentionMode;
    onModeChange: (mode: RetentionMode) => void;
    fields: ScrubField[] | null;
    onFieldsChange: (fields: ScrubField[]) => void;
    /** What the server holds now, to tell whether there is anything to apply.
     *  Null while it is unknown, in which case Apply is always available. */
    saved: SavedRetention | null;
    /** After a save or a run has started: the message to show, and the cue to reload. */
    onApplied: (message: string) => void;
    onRunStarted: (message: string) => void;
    onError: (context: string, err: unknown) => void;
    onReview: () => void;
    reviewing: boolean;
    onExport: () => void;
    exportOpen: boolean;
}

const PRESETS = [
    { days: 365, label: '1 year' },
    { days: 1095, label: '3 years' },
    { days: 2555, label: '7 years' },
] as const;

const GROUPS: { key: string; title: string; ids: string[] }[] = [
    { key: 'reporter', title: 'Reporter', ids: ['name', 'email', 'phone'] },
    { key: 'said', title: 'What was said', ids: ['description', 'custom_fields', 'comments', 'closing_message', 'staff_notes', 'ai_analysis'] },
    { key: 'media', title: 'Media and location', ids: ['media', 'address', 'coordinates'] },
];

/** 2555 -> "7 years", 900 -> "2.5 years", 90 -> "about 3 months", 10 -> "10 days". */
export function formatRetention(days: number): string {
    if (days < 60) return `${days} ${days === 1 ? 'day' : 'days'}`;
    if (days < 365) return `about ${Math.round(days / 30.4)} months`;
    const years = days / 365;
    const rounded = Number.isInteger(years) ? years : Math.round(years * 10) / 10;
    return `${rounded} ${rounded === 1 ? 'year' : 'years'}`;
}

/** The catalog in display groups, in catalog order within each. */
export function groupScrubFields(fields: ScrubField[]) {
    const known = new Set(GROUPS.flatMap(g => g.ids));
    const groups = GROUPS.map(g => ({
        key: g.key,
        title: g.title,
        fields: g.ids.map(id => fields.find(f => f.id === id)).filter((f): f is ScrubField => !!f),
    }));
    const other = fields.filter(f => !known.has(f.id));
    if (other.length) groups.push({ key: 'other', title: 'Other', fields: other });
    return groups.filter(g => g.fields.length > 0);
}

export default function RetentionPolicyEditor({
    days, onDaysChange, mode, onModeChange, fields, onFieldsChange, saved,
    onApplied, onRunStarted, onError, onReview, reviewing, onExport, exportOpen,
}: Props) {
    const dialog = useDialog();
    const uid = useId();
    const daysInputRef = useRef<HTMLInputElement>(null);
    const [customChosen, setCustomChosen] = useState(false);
    const [saving, setSaving] = useState(false);
    const [running, setRunning] = useState(false);

    const dayCount = parseInt(days) || 0;
    const isPreset = PRESETS.some(p => String(p.days) === days);
    const custom = customChosen || (!!days && !isPreset);
    const chosen = (fields || []).filter(f => f.selected);
    const total = fields?.length ?? 0;
    const willRun = dayCount > 0 && (mode === 'purge' || chosen.length > 0);

    const dirty = !saved || saved.days !== dayCount || saved.mode !== mode
        || (mode === 'redact' && (
            chosen.length !== saved.fieldIds.length
            || chosen.some(f => !saved.fieldIds.includes(f.id))));

    const setSelected = (ids: string[], selected: boolean) =>
        onFieldsChange((fields || []).map(f => (ids.includes(f.id) ? { ...f, selected } : f)));

    const apply = async () => {
        setSaving(true);
        try {
            const result = await api.updateRetentionPolicy({
                mode,
                scrub_fields: chosen.map(f => f.id),
                // 0 explicitly clears the period, which stops retention
                // running. Omitting it would leave a previously-set period
                // stuck with no way to remove it.
                retention_days: days ? parseInt(days) : 0,
            });
            /* The server decides whether this is a policy, and says so.
               "Updated successfully" over a save that left retention switched
               off is the quiet the warning above exists to break. */
            onApplied(result.configured
                ? 'Retention policy saved and now in force'
                : `Saved, but retention still will not run. ${result.detail || ''}`);
        } catch (err) {
            onError('Could not apply the retention policy', err);
        } finally {
            setSaving(false);
        }
    };

    const runNow = async () => {
        /* Show the numbers, then ask. This button used to run immediately, and
         * the response came back before the task had touched anything, so
         * nothing on screen could say what had happened. */
        setRunning(true);
        let plan;
        try {
            plan = await api.previewRetentionRun();
        } catch (err) {
            setRunning(false);
            onError('Could not work out what this would affect', err);
            return;
        }
        setRunning(false);

        if (plan.blocked === 'legal_hold') {
            await dialog.alert({
                title: 'Legal hold is on',
                message: 'Nothing is archived or deleted while the instance-wide legal hold is on. Lift the hold to run retention.',
                variant: 'info',
            });
            return;
        }
        // Before "nothing is due", which would otherwise report an
        // unconfigured policy as a quiet success.
        if (plan.blocked === 'unconfigured') {
            await dialog.alert({
                title: 'No retention schedule is set',
                message: plan.detail || 'Set a retention period and the fields to clear before running retention.',
                variant: 'warning',
            });
            return;
        }
        if (!plan.eligible) {
            await dialog.alert({
                title: 'Nothing is due yet',
                message: `No closed records have passed the ${plan.retention_days}-day retention period.`,
                variant: 'info',
            });
            return;
        }

        const purging = plan.mode === 'purge';
        const count = plan.will_act_on ?? plan.eligible;
        const ok = await dialog.confirm({
            title: purging ? 'Clear every field on these records' : 'Redact these records',
            variant: purging ? 'danger' : 'warning',
            confirmText: purging ? 'Clear them' : 'Redact them',
            requireTyped: plan.confirmation_required || undefined,
            message: (
                <div className="space-y-3">
                    <p>
                        <strong className="text-white">{count}</strong>{' '}
                        closed {count === 1 ? 'record has' : 'records have'} passed
                        the {plan.retention_days}-day retention period this town set.
                    </p>
                    <p>
                        {purging
                            ? 'Every field is permanently cleared, including names, contact details, descriptions, photos, comments and the map pin. The rows stay so your totals don’t change. This can’t be undone.'
                            : 'The fields you checked are permanently cleared on these records. The rows and all other fields stay. This can’t be undone.'}
                    </p>
                    {/* Named, from the server's own list: a clerk approving
                        this should not have to remember which boxes are ticked
                        on a screen they cannot see right now. */}
                    {!!plan.scrub_fields?.length && (
                        <p className="text-white/70 text-sm">Cleared: {plan.scrub_fields.join(', ')}.</p>
                    )}
                    {!!plan.on_legal_hold && (
                        <p className="text-amber-300">
                            {plan.on_legal_hold} flagged {plan.on_legal_hold === 1 ? 'record is' : 'records are'} under
                            legal hold and will be skipped.
                        </p>
                    )}
                    <p className="text-slate-400 text-sm">The run covers every eligible record.</p>
                </div>
            ),
        });
        if (!ok) return;

        setRunning(true);
        try {
            const result = await api.runRetentionNow(plan.confirmation_required || undefined);
            onRunStarted(`Retention task started: ${result.message}`);
        } catch (err) {
            onError('Could not start the retention task', err);
        } finally {
            setRunning(false);
        }
    };

    const chipBase = 'relative inline-flex items-center justify-center rounded-full border px-3.5 sm:px-4 text-sm font-medium cursor-pointer select-none transition-colors duration-200 motion-reduce:transition-none';
    const chipIdle = 'border-white/25 bg-white/[0.04] text-white/80 hover:border-white/50 hover:text-white';
    const chipOn = 'has-[:checked]:border-primary-400 has-[:checked]:bg-primary-500/25 has-[:checked]:text-white';
    const chipFocus = 'has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-amber-300 has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-[#1B1B3A]';

    const modes: { value: RetentionMode; title: string; detail: string; Icon: typeof Eraser }[] = [
        {
            value: 'redact',
            title: 'Redact',
            detail: 'Clear only the fields you choose. The record stays and still counts.',
            Icon: Eraser,
        },
        {
            value: 'purge',
            title: 'Purge',
            detail: 'Clear every field. The row is kept only so your totals don’t change.',
            Icon: Trash2,
        },
    ];

    return (
        <div className="space-y-6">
            {/* Period */}
            <fieldset className="m-0 min-w-0 border-0 p-0">
                <legend className="mb-1 text-sm font-semibold text-white">Keep closed requests for</legend>
                <p className="mb-3 text-xs text-white/60">Counted from the day a request is closed.</p>
                <div className="flex flex-wrap gap-2">
                    {PRESETS.map(p => (
                        <label key={p.days} className={`${chipBase} ${chipIdle} ${chipOn} ${chipFocus}`}>
                            <input
                                type="radio"
                                name={`${uid}-period`}
                                className="sr-only"
                                checked={!custom && days === String(p.days)}
                                onChange={() => { setCustomChosen(false); onDaysChange(String(p.days)); }}
                            />
                            {p.label}
                        </label>
                    ))}
                    <label className={`${chipBase} ${chipIdle} ${chipOn} ${chipFocus}`}>
                        <input
                            type="radio"
                            name={`${uid}-period`}
                            className="sr-only"
                            checked={custom}
                            onChange={() => {
                                setCustomChosen(true);
                                requestAnimationFrame(() => daysInputRef.current?.focus());
                            }}
                        />
                        Custom
                    </label>
                </div>

                {custom && (
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                        <label htmlFor="retention-days" className="sr-only">Keep closed requests for (days)</label>
                        <div className="relative w-40">
                            <input
                                ref={daysInputRef}
                                id="retention-days"
                                type="number"
                                inputMode="numeric"
                                value={days}
                                onChange={(e) => onDaysChange(e.target.value)}
                                placeholder="e.g. 2555"
                                min="1"
                                max="36500"
                                aria-describedby={`${uid}-period-hint`}
                                className="w-full rounded-lg border border-white/30 bg-white/10 py-2.5 pl-3 pr-12 text-white placeholder:text-white/50 focus:outline-none focus-visible:ring-[3px] focus-visible:ring-amber-300"
                            />
                            <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-white/60" aria-hidden="true">days</span>
                        </div>
                    </div>
                )}

                {/* Shown in words as it is chosen. A schedule says "7 years" and
                    this takes days, so 7 typed here is a week -- a policy that
                    destroys almost everything on its first run. */}
                <p id={`${uid}-period-hint`} className="mt-2 text-xs text-white/65" aria-live="polite">
                    {dayCount > 0
                        ? <><span className="font-semibold text-white">{formatRetention(dayCount)}</span> ({dayCount.toLocaleString()} days), then the policy below applies.</>
                        : 'Not set, so nothing is cleared. Pick a period, or enter days under Custom.'}
                </p>
            </fieldset>

            {/* Mode */}
            <fieldset className="m-0 min-w-0 border-0 p-0">
                <legend className="mb-3 text-sm font-semibold text-white">When that time is up</legend>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {modes.map(m => (
                        <label
                            key={m.value}
                            className="group relative block cursor-pointer rounded-xl border border-white/15 bg-white/[0.03] p-3.5 transition-colors duration-200 motion-reduce:transition-none hover:border-white/35 hover:bg-white/[0.06] has-[:checked]:border-primary-400/70 has-[:checked]:bg-primary-500/[0.14] has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-amber-300 has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-[#1B1B3A]"
                        >
                            <span className="flex w-full self-start items-start gap-3">
                                <input
                                    type="radio"
                                    name={`${uid}-mode`}
                                    value={m.value}
                                    checked={mode === m.value}
                                    onChange={() => onModeChange(m.value)}
                                    aria-describedby={`${uid}-mode-${m.value}`}
                                    className="sr-only"
                                />
                                {/* The radio's visible form: a ring that fills. */}
                                <span aria-hidden="true" className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-[1.5px] border-white/60 transition-colors group-has-[:checked]:border-primary-300">
                                    <span className="h-2 w-2 scale-0 rounded-full bg-primary-300 transition-transform duration-200 group-has-[:checked]:scale-100 motion-reduce:transition-none" />
                                </span>
                                <span className="min-w-0 flex-1">
                                    <span className="flex items-center gap-2 text-sm font-medium leading-5 text-white">
                                        <m.Icon className="h-4 w-4 text-white/60 group-has-[:checked]:text-primary-300" aria-hidden="true" />
                                        {m.title}
                                    </span>
                                    <span id={`${uid}-mode-${m.value}`} className="mt-0.5 block text-xs leading-relaxed text-white/65">{m.detail}</span>
                                </span>
                            </span>
                        </label>
                    ))}
                </div>
            </fieldset>

            {/* What a run clears. Nothing is ticked until the town ticks it:
                a default that destroys is not a convenience. */}
            {mode === 'redact' && fields && (
                <section aria-labelledby={`${uid}-fields`} className="space-y-4">
                    <div>
                        <h4 id={`${uid}-fields`} className="text-sm font-semibold text-white">What gets cleared</h4>
                        <p className="mt-1 text-xs text-white/60">
                            The record stays and still counts in your statistics. Only the fields you check are
                            permanently cleared.
                        </p>
                    </div>
                    {groupScrubFields(fields).map(group => {
                        const ids = group.fields.map(f => f.id);
                        const on = group.fields.filter(f => f.selected).length;
                        const headId = `${uid}-group-${group.key}`;
                        return (
                            <div key={group.key} role="group" aria-labelledby={headId} className="rounded-2xl border border-white/10 bg-white/[0.02] p-3 sm:p-4">
                                <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
                                    <h5 id={headId} className="text-xs font-semibold uppercase tracking-wider text-white/80">{group.title}</h5>
                                    <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-medium text-white/75">
                                        {on} of {group.fields.length}
                                    </span>
                                    <span className="ml-auto flex gap-1">
                                        <button
                                            type="button"
                                            className="inline-btn rounded-md px-2 py-1 text-xs font-medium text-primary-200 hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:text-white/35 disabled:hover:bg-transparent focus:outline-none focus-visible:ring-[3px] focus-visible:ring-amber-300"
                                            onClick={() => setSelected(ids, true)}
                                            disabled={on === group.fields.length}
                                            aria-label={`Select all in ${group.title}`}
                                        >
                                            Select all
                                        </button>
                                        <button
                                            type="button"
                                            className="inline-btn rounded-md px-2 py-1 text-xs font-medium text-primary-200 hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:text-white/35 disabled:hover:bg-transparent focus:outline-none focus-visible:ring-[3px] focus-visible:ring-amber-300"
                                            onClick={() => setSelected(ids, false)}
                                            disabled={on === 0}
                                            aria-label={`None in ${group.title}`}
                                        >
                                            None
                                        </button>
                                    </span>
                                </div>
                                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                                    {group.fields.map(field => (
                                        <CheckboxCard
                                            key={field.id}
                                            checked={field.selected}
                                            onChange={(e) => setSelected([field.id], e.target.checked)}
                                            title={field.label}
                                            description={field.detail}
                                        />
                                    ))}
                                </div>
                            </div>
                        );
                    })}
                    {chosen.length === 0 && (
                        <p className="flex items-center gap-2 text-xs text-amber-300">
                            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
                            Check at least one field. Retention does not run until you do.
                        </p>
                    )}
                </section>
            )}

            {/* What the answers add up to, before anything is saved. */}
            <div className={`rounded-xl border p-4 ${willRun ? 'border-amber-400/40 bg-amber-500/10' : 'border-white/15 bg-white/[0.03]'}`}>
                <div className="flex items-start gap-3">
                    <Clock className={`mt-0.5 h-5 w-5 shrink-0 ${willRun ? 'text-amber-300' : 'text-white/50'}`} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                        {willRun ? (
                            <>
                                <p className="font-medium text-amber-200">
                                    Kept {formatRetention(dayCount)}, then{' '}
                                    {mode === 'purge'
                                        ? 'every field is cleared'
                                        : `${chosen.length} of ${total} ${total === 1 ? 'field' : 'fields'} cleared`}
                                </p>
                                {mode === 'redact' && (
                                    <ul aria-label="Fields cleared" className="mt-2 flex flex-wrap gap-1.5">
                                        {chosen.map(f => (
                                            <li key={f.id} className="rounded-full border border-amber-300/30 bg-amber-400/10 px-2 py-0.5 text-[11px] font-medium text-amber-100">
                                                {f.label}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                <p className="mt-2 text-xs text-white/60">
                                    This applies to every request. To keep one longer, place a legal hold on it.
                                </p>
                            </>
                        ) : (
                            <p className="text-sm text-white/75">
                                {dayCount > 0
                                    ? 'A period is set but no fields are checked, so retention will not run.'
                                    : 'No period is set, so retention will not run and closed requests are kept indefinitely.'}
                            </p>
                        )}
                    </div>
                </div>
            </div>

            {/* Actions */}
            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                <Button
                    onClick={apply}
                    disabled={saving || !dirty}
                    className="w-full sm:w-auto"
                >
                    {saving ? 'Saving…' : 'Apply policy'}
                </Button>
                <span className="text-xs sm:mr-auto" aria-live="polite">
                    {dirty
                        ? <span className="inline-flex items-center gap-1.5 text-amber-200"><span className="h-1.5 w-1.5 rounded-full bg-amber-300" aria-hidden="true" />Unsaved changes</span>
                        : <span className="inline-flex items-center gap-1.5 text-white/60"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />Saved</span>}
                </span>
                {/* Read before you press. A count cannot show that the oldest
                    eligible record is years past its date, nor that something
                    assumed exempt is in the list because nobody set the hold. */}
                <Button variant="secondary" onClick={onReview} disabled={reviewing} leftIcon={<FileSearch className="h-4 w-4" aria-hidden="true" />} className="w-full sm:w-auto">
                    {reviewing ? 'Checking…' : 'Review what would be archived'}
                </Button>
                {/* Named for the job, not for a statute. */}
                <Button variant="secondary" onClick={onExport} aria-expanded={exportOpen} leftIcon={<Download className="h-4 w-4" aria-hidden="true" />} className="w-full sm:w-auto">
                    Export for a records request
                </Button>
            </div>

            <div className="flex flex-col gap-3 rounded-xl border border-red-300/30 bg-red-500/[0.07] p-4 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-red-100">Run retention now</p>
                    <p className="mt-0.5 text-xs text-white/65">
                        Permanently clears fields on every record that is due, instead of waiting for the next
                        scheduled run. You see the count and confirm first.
                    </p>
                </div>
                <Button
                    variant="danger"
                    onClick={runNow}
                    disabled={running}
                    leftIcon={<Play className="h-4 w-4" aria-hidden="true" />}
                    className="w-full shrink-0 sm:w-auto"
                >
                    {running ? 'Running…' : 'Run retention now'}
                </Button>
            </div>
        </div>
    );
}
