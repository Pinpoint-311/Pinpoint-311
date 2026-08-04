import { useCallback, useEffect, useState } from 'react';
import { Lock, ShieldCheck, AlertCircle } from 'lucide-react';

import { api } from '../services/api';
import type { SecretStoreChoice } from '../services/api';

/**
 * The first question, and nothing can be entered before it is answered.
 *
 * Not tidiness, and not a preference. `_persist_secret` falls back to the
 * encrypted database when the external store is unreachable, and reports that
 * it did. `vault_secrets` later sweeps those rows into the store and scrubs the
 * database copy -- on a schedule, and again after every provider save -- so the
 * live database heals itself and the whole thing looks harmless.
 *
 * Database *backups* taken inside that window do not heal. They keep the row
 * forever and they go off-site: a pg_dump of a Pinpoint instance contains
 * `COPY public.system_secrets (id, key_name, key_value, ...)`. Sweeping the
 * live row reaches nothing that has already been dumped. So the credential has
 * to not be written until somebody has decided where it belongs.
 *
 * The gate is on the *choice*, not on standing up a cloud vault. The encrypted
 * database is one of the four answers, with the backup consequence written on
 * screen rather than discovered later, and a town whose cloud procurement is
 * unfinished is not dead-ended. What must not happen is a town landing there
 * without being asked -- which is exactly what an unset `SECRETS_PROVIDER`
 * quietly defaulting to Google used to arrange.
 */

const STORES: { id: string; name: string; blurb: string }[] = [
    {
        id: 'google',
        name: 'Google Secret Manager',
        blurb: 'Uses the Google Cloud account you set up below. Nothing to buy separately.',
    },
    {
        id: 'azure',
        name: 'Azure Key Vault',
        blurb: 'The natural choice if the town already runs on Microsoft 365 or Azure.',
    },
    {
        id: 'aws',
        name: 'AWS Secrets Manager',
        blurb: 'Uses your AWS account, or this server’s instance role if it has one.',
    },
    {
        id: 'database',
        name: 'This server’s own encrypted database',
        blurb: 'No cloud account needed. Read the note below before choosing it.',
    },
];

const LABEL: Record<string, string> = Object.fromEntries(STORES.map(s => [s.id, s.name]));

export default function SecretStoreGate({ onChosen }: {
    /** So the page can re-enable everything it had disabled. */
    onChosen?: () => void;
} = {}) {
    const [choice, setChoice] = useState<SecretStoreChoice | null>(null);
    const [picked, setPicked] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(() => {
        api.getSecretStore()
            .then(setChoice)
            /* Silent, and it leaves `choice` null so nothing is rendered. The
             * backend refuses the credential regardless -- this panel explains
             * the refusal, it does not enforce it -- so a panel that cannot
             * load its own state is better absent than guessing. */
            .catch(() => undefined);
    }, []);
    useEffect(load, [load]);

    if (!choice) return null;

    if (choice.chosen) {
        return (
            <p className="flex items-center gap-2 text-[11px] text-emerald-300/70">
                <ShieldCheck className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                Credentials on this page are kept in{' '}
                <strong className="text-emerald-200/90 font-semibold">
                    {LABEL[choice.store ?? ''] ?? choice.store}
                </strong>
                {choice.store !== 'database' && !choice.reachable && (
                    <span className="text-white/50">
                        · not reachable yet, so anything saved now waits in the encrypted
                        database and moves across on its own
                    </span>
                )}
            </p>
        );
    }

    return (
        <div role="region" aria-label="Choose a secret store"
            className="rounded-xl border border-amber-400/30 bg-amber-500/[0.07] p-4">
            <div className="flex items-start gap-2.5">
                <Lock className="w-4 h-4 text-amber-300/90 mt-0.5 shrink-0" aria-hidden="true" />
                <div className="min-w-0">
                    <p className="text-sm font-semibold text-white">
                        First: where should this town’s credentials be kept?
                    </p>
                    <p className="text-xs text-white/60 leading-relaxed mt-1">
                        Nothing below will accept a key until this is answered. Every password and
                        API key on this page goes to whichever of these you pick, and moving them
                        afterwards is not something a click can do — so it is asked once, first,
                        rather than assumed.
                    </p>
                </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-3.5">
                {/* Every store this build knows about, unless the server
                    narrowed the list. An absent `options` is a response that
                    did not say, and offering nothing at all would be a gate
                    with no way through it -- this panel is the only place the
                    choice can be made. */}
                {STORES.filter(s => !choice.options || choice.options.includes(s.id)).map(store => (
                    <button
                        key={store.id}
                        type="button"
                        onClick={() => { setPicked(store.id); setError(null); }}
                        aria-pressed={picked === store.id}
                        className={`text-left px-3.5 py-3 rounded-xl border transition-colors ${picked === store.id
                            ? 'bg-primary-500/20 border-primary-400/50'
                            : 'bg-white/[0.04] border-white/10 hover:border-white/25'}`}
                    >
                        <p className="text-sm font-semibold text-white">{store.name}</p>
                        <p className="text-[11px] text-white/55 leading-relaxed mt-0.5">{store.blurb}</p>
                    </button>
                ))}
            </div>

            {/* Spelled out rather than implied, and only when it is the answer
                being considered. This is the whole reason the database is an
                allowed choice instead of a fallback: a town may reasonably pick
                it, and cannot reasonably pick it without knowing this. */}
            {picked === 'database' && (
                <div className="mt-3 rounded-lg border border-white/15 bg-black/25 px-3.5 py-3">
                    <p className="text-xs text-amber-100/85 leading-relaxed">
                        <strong className="text-amber-100">What this means.</strong> Your credentials
                        are encrypted in this deployment’s own PostgreSQL database. They are also in
                        every <strong>backup</strong> of it — and backups are copied off this server.
                        Anyone who can read a backup file can read the keys, so treat those backups
                        the way the town treats its other secrets: encrypted, access-controlled, and
                        not sitting in a shared drive.
                    </p>
                    <p className="text-xs text-white/50 leading-relaxed mt-2">
                        This is a supported choice and a reasonable one for a small install. You can
                        move to a cloud vault later; the credentials migrate across when you do.
                    </p>
                </div>
            )}

            {error && (
                <p role="alert" className="text-xs text-red-200 mt-3">{error}</p>
            )}

            <div className="flex flex-wrap items-center gap-2.5 mt-3.5">
                <button
                    type="button"
                    disabled={!picked || saving}
                    onClick={async () => {
                        if (!picked) return;
                        setSaving(true); setError(null);
                        try {
                            setChoice(await api.chooseSecretStore(picked));
                            onChosen?.();
                        } catch (err: any) {
                            setError(err?.message || 'That could not be saved.');
                        } finally {
                            setSaving(false);
                        }
                    }}
                    className="inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold text-white bg-primary-500 hover:bg-primary-400 border border-primary-400/50 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                >
                    {saving ? 'Saving…' : 'Use this store'}
                </button>
                <span className="inline-flex items-center gap-1.5 text-[11px] text-white/45">
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    Picking a cloud vault here does not require it to be working yet.
                </span>
            </div>
        </div>
    );
}
