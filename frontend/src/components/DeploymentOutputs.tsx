import { AlertCircle, CheckCircle, Circle } from 'lucide-react';
import { useId, useMemo, useState } from 'react';

import { DEPLOY_OUTPUTS, outputsToValues, parseDeployOutputs } from './deployOutputs';
import type { MatchedOutput } from './deployOutputs';

/**
 * What the deployment gave back, in one paste.
 *
 * The missing half of the deploy button. The template ran, the cloud created
 * the resources and printed their addresses, and until this existed the
 * operator then went looking for four different cards to retype seven values
 * into. Made, but not connected.
 *
 * Three rules, and they are the whole design:
 *
 *   * Nothing is saved before it is shown. Matched, unmatched and missing are
 *     all on screen with the values visible, and a button that says how many.
 *   * An output nothing wanted is reported. It means the template and the
 *     credential catalogs have drifted, and a silent drop turns a bug we could
 *     have caught into a box somebody cannot find.
 *   * Saving goes through the page's own save, the same one a typed value uses.
 *     A second write path would be a second place for the secret store, the
 *     encryption and the read-back to be got wrong.
 */
export default function DeploymentOutputs({
    cloud, values, onChange, onSave, saving, isConfigured,
}: {
    cloud: 'azure' | 'aws';
    /** The page's pending values, so a paste lands where a keystroke would. */
    values: Record<string, string>;
    onChange: (key: string, value: string) => void;
    /** The page's own save, given the values rather than asked to look them
     *  up: nothing here was typed, so there is no state for it to read back
     *  in the same tick. Same write path as a typed value, deliberately. */
    onSave: (entries: Record<string, string>) => Promise<void>;
    saving: boolean;
    isConfigured: (key: string) => boolean;
}) {
    const spec = DEPLOY_OUTPUTS[cloud];
    const [text, setText] = useState('');
    const [saved, setSaved] = useState<string[] | null>(null);
    const uid = useId();

    const parsed = useMemo(() => parseDeployOutputs(cloud, text), [cloud, text]);
    const ready = parsed.matched.length > 0;

    if (!spec) return null;

    const apply = async (matched: MatchedOutput[]) => {
        const toSave = outputsToValues(matched);
        // Into the boxes as well as into the save, so the cards show what
        // landed rather than going green with nothing visible in them.
        for (const [key, value] of Object.entries(toSave)) onChange(key, value);
        await onSave(toSave);
        setSaved(Object.keys(toSave));
    };

    /* Still a human's job, and only the ones not already done. A list that
     * keeps naming credentials the town entered last week is a list nobody
     * reads to the end of. */
    const outstanding = spec.manual.filter(m => !isConfigured(m.key) && !values[m.key]);

    return (
        <div className="rounded-xl border border-white/15 bg-white/[0.04] p-4" data-testid="deployment-outputs">
            <h4 className="text-sm font-semibold text-white/85">Paste what the deployment gave back</h4>
            <p className="mt-1 text-xs text-white/55 leading-relaxed">{spec.sourceHint}</p>

            <label htmlFor={`${uid}-blob`} className="sr-only">{spec.sourceLabel}, as JSON</label>
            <textarea
                id={`${uid}-blob`}
                value={text}
                onChange={(e) => { setText(e.target.value); setSaved(null); }}
                rows={4}
                spellCheck={false}
                placeholder={'{ "keyVaultUrl": { "value": "https://…" }, … }'}
                aria-describedby={parsed.error ? `${uid}-error` : undefined}
                aria-invalid={parsed.error ? true : undefined}
                className="mt-2.5 w-full rounded-lg border border-white/15 bg-black/30 px-3 py-2 font-mono text-[11px] text-white/80 placeholder:text-white/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
            />

            {parsed.error && (
                <p id={`${uid}-error`} className="mt-1.5 flex items-start gap-1.5 text-xs text-amber-200/90">
                    <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
                    <span>{parsed.error}</span>
                </p>
            )}

            {/* What was read, before anything is written. */}
            {(parsed.matched.length > 0 || parsed.absent.length > 0 || parsed.unmatched.length > 0) && (
                <dl className="mt-3 space-y-1" data-testid="deployment-outputs-matched">
                    {parsed.matched.map(m => (
                        <div key={m.output} className="flex items-start gap-2 text-xs" data-output-status="matched" data-output={m.output}>
                            <CheckCircle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-emerald-300/80" aria-hidden="true" />
                            <dt className="text-white/70">{m.label}</dt>
                            <dd className="min-w-0 flex-1 truncate font-mono text-[11px] text-white/45">{m.value}</dd>
                        </div>
                    ))}
                    {parsed.absent.map(a => (
                        <div key={a.output} className="flex items-start gap-2 text-xs" data-output-status="absent" data-output={a.output}>
                            <Circle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-white/25" aria-hidden="true" />
                            <dt className="text-white/45">{a.label}</dt>
                            <dd className="text-[11px] text-white/35">not in this deployment</dd>
                        </div>
                    ))}
                    {parsed.unmatched.map(u => (
                        <div key={u.output} className="flex items-start gap-2 text-xs" data-output-status="unmatched" data-output={u.output}>
                            <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-300/80" aria-hidden="true" />
                            <dt className="text-amber-100/80">{u.output}</dt>
                            <dd className="text-[11px] text-amber-100/50">no box for this — worth reporting</dd>
                        </div>
                    ))}
                </dl>
            )}

            <button
                type="button"
                disabled={!ready || saving}
                onClick={() => apply(parsed.matched)}
                className="mt-3 inline-flex items-center rounded-lg bg-primary-500 px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-primary-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 transition-colors"
            >
                {saving ? 'Saving…' : ready ? `Fill in ${countKeys(parsed.matched)} boxes` : 'Fill in the boxes'}
            </button>

            {saved && (
                <p className="mt-2 text-xs text-emerald-300/80">
                    Saved. Those cards read as configured now; use Save &amp; Test on each to check
                    it against the real resource.
                </p>
            )}

            {/* The half no template can hand back. Said plainly, because an
                operator who pastes the outputs and finds boxes still empty
                concludes the paste failed. */}
            {outstanding.length > 0 && (
                <div className="mt-3.5 border-t border-white/10 pt-3">
                    <p className="text-xs text-white/60 leading-relaxed">
                        Keys are not in the outputs — deployment history is readable by more people
                        than the person deploying. Copy these from the portal:
                    </p>
                    <ul className="mt-1.5 space-y-0.5">
                        {outstanding.map(m => (
                            <li key={m.key} className="text-xs text-white/50" data-manual-credential={m.key}>
                                <span className="text-white/70">{m.label}</span> — {m.where}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}

function countKeys(matched: MatchedOutput[]): number {
    return Object.keys(outputsToValues(matched)).length;
}
