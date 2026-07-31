import { CheckCircle, AlertCircle, ShieldCheck } from 'lucide-react';

import SecretField from './SecretField';
import { claimedFields, stepsFor } from './setupSteps';
import type { StepContext } from './setupSteps';
import type { Capability, CloudIdentity, ProviderInfo } from '../services/api';

/**
 * The console walk and the boxes it fills, as one thing.
 *
 * This is the only place that renders a provider's setup steps, and it exists
 * because there were nearly two. The provider cards grew the "step owns its
 * fields" layout first; the setup guide at the top of the page was then left
 * pointing at them -- "scroll down to the Maps card" -- which is not what a
 * guide is for. Someone following it had to leave it to do the thing it was
 * describing, and come back to find their place.
 *
 * Putting the walk in both places is right. Writing it twice is not: the last
 * time this page carried two copies they drifted, and the guide spent months
 * telling towns to invent a backup passphrase that no longer existed. So the
 * content stays in setupStepsContent.tsx, the layout stays here, and both the
 * card and the guide mount this.
 *
 * Deliberately dumb. It owns no catalog, no save, no request -- the caller
 * holds the values and decides what a save means, because the card saves one
 * capability at a time from a picker while the guide saves the provider the
 * town already chose in the questionnaire.
 */
export default function ProviderCredentialSteps({
    cap, provider, active, values, onChange, ctx, identity, alreadySet = false, compact = false,
}: {
    cap: Capability;
    /** Which provider's walk to render. Not read off the catalog: the guide
     *  pins this to the questionnaire answer, the card to its picker. */
    provider: string;
    active: ProviderInfo;
    values: Record<string, string>;
    onChange: (key: string, value: string) => void;
    ctx: StepContext;
    /** Attached cloud identity, if any -- turns credential boxes it replaces
     *  into "nothing to enter" rather than leaving them looking unfinished. */
    identity?: CloudIdentity | null;
    /** Credentials for this provider are already stored, so an empty box means
     *  "keep what is there" rather than "not done yet". */
    alreadySet?: boolean;
    /** Tighter spacing for the guide, which nests this inside a step list. */
    compact?: boolean;
}) {
    const field = (key: string) => {
        const f = active.credential_fields.find(x => x.key === key);
        if (!f) return null;  // the catalog changed under the steps

        /* This server already has an identity on the cloud, so this box needs
         * no value -- and empty is the better answer, not merely a permitted
         * one: the platform issues a token minutes at a time and rotates it, so
         * no long-lived secret exists to be mis-copied, vaulted, or left to
         * expire. Two of the three clouds already behaved this way and nothing
         * said so, so towns pasted keys into boxes that did not need them. */
        if (identity?.skippable_keys?.includes(f.key)) {
            return (
                <div key={f.key} className="rounded-xl border border-emerald-400/25 bg-emerald-500/[0.07] px-3 py-2.5">
                    <div className="flex items-start gap-2">
                        <ShieldCheck className="w-3.5 h-3.5 text-emerald-300 mt-0.5 shrink-0" aria-hidden="true" />
                        <div>
                            <p className="text-xs text-emerald-100/90">
                                <span className="font-semibold">{f.label}</span> — nothing to enter.
                            </p>
                            <p className="text-[11px] text-white/45 mt-0.5">
                                This server already has an identity on{' '}
                                {CLOUD_LABEL[identity.provider ?? ''] ?? 'your cloud'}
                                {identity.identity ? <> (<code className="bg-black/30 px-1 rounded">{identity.identity}</code>)</> : null}.
                                It signs in with that, so there is no key to create, copy, or renew.
                            </p>
                        </div>
                    </div>
                </div>
            );
        }

        return (
            <SecretField
                key={f.key}
                label={f.label}
                secret={f.secret}
                value={values[f.key] || ''}
                onChange={(v) => onChange(f.key, v)}
                placeholder={`Enter ${f.label.toLowerCase()}`}
                help={active.field_help?.[f.key]}
                savedHint={alreadySet}
            />
        );
    };

    const steps = stepsFor(cap, provider, ctx);
    const claimed = claimedFields(steps);
    const leftover = active.credential_fields.filter(f => !claimed.has(f.key));

    return (
        <div>
            {steps.map((st, i) => (
                <div key={i} className={compact ? 'mb-3' : 'mb-4'}>
                    <div className="flex gap-3">
                        <span className="mt-0.5 w-6 h-6 shrink-0 rounded-full bg-white/10 border border-white/15 text-[11px] font-semibold text-white/70 flex items-center justify-center">
                            {i + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                            <div className="text-sm text-white/75 leading-relaxed">{st.body}</div>
                            {st.check && (
                                <p className="mt-1.5 text-xs text-emerald-300/75 flex items-start gap-1.5">
                                    <CheckCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
                                    <span><span className="font-medium">You should see:</span> {st.check}</span>
                                </p>
                            )}
                            {st.trouble && (
                                <p className="mt-1.5 text-xs text-amber-200/90 flex items-start gap-1.5">
                                    <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
                                    <span>{st.trouble}</span>
                                </p>
                            )}
                            {/* No icon and no colour. A note competing visually
                                with a warning is what made the warnings stop
                                registering. */}
                            {st.note && (
                                <p className="mt-1.5 text-xs text-white/55 leading-relaxed">{st.note}</p>
                            )}
                            {!!st.fields?.length && (
                                <div className="mt-2.5 grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-3">
                                    {st.fields.map(field)}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            ))}

            {/* A field no step claims still renders, at the end. Adding a
                credential to a catalog can never make it silently unreachable. */}
            {leftover.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-3">
                    {leftover.map(f => field(f.key))}
                </div>
            )}
        </div>
    );
}

/** Cloud names for the "nothing to enter" note. */
const CLOUD_LABEL: Record<string, string> = {
    google: 'Google Cloud',
    azure: 'Azure',
    aws: 'AWS',
};
