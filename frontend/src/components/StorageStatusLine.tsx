import { useEffect, useState } from 'react';
import { ShieldCheck, RefreshCw } from 'lucide-react';

import { api } from '../services/api';
import type { StorageStatus } from '../services/api';

/**
 * One sentence about where the town's secrets and resident data actually sit.
 *
 * It replaces two buttons: "Vault Local Secrets to GCP Identity" and
 * "Re-encrypt All PII Data (after key rotation)". Both did real work, and
 * neither could be pressed at the right time by anybody who had not been told
 * what they meant -- the second was conditioned on a key rotation, an event a
 * clerk has no reason to know has occurred.
 *
 * Both now run on a schedule. So the only thing left worth saying is whether
 * anything is mid-flight, and the normal answer is a green tick. Numbers are
 * given in things a person recognises -- keys, resident records -- rather than
 * in the vocabulary of the operation that produces them.
 */
export function StorageStatusLine() {
    const [status, setStatus] = useState<StorageStatus | null>(null);

    useEffect(() => {
        let cancelled = false;
        api.getStorageStatus()
            .then(s => { if (!cancelled) setStatus(s); })
            // Advisory only. A status line that cannot load is not worth an
            // error message on a page about something else.
            .catch(() => undefined);
        return () => { cancelled = true; };
    }, []);

    if (!status) return null;

    /* No store, no sentence.
     *
     * This defaulted to "Google Secret Manager" for anything it did not
     * recognise, including a town that has not chosen a store -- so the line
     * told a fresh install its secrets were in a Google product it had never
     * signed in to. The setup gate says the rest; there is nothing useful to
     * add here. */
    if (!status.secrets.store) return null;

    const storeName = {
        azure: 'Azure Key Vault',
        aws: 'AWS Secrets Manager',
        database: "this deployment's own encrypted database",
    }[status.secrets.store] ?? 'Google Secret Manager';

    const pending: string[] = [];
    if (status.secrets.count && status.secrets.reachable) {
        pending.push(
            `${status.secrets.count} ${status.secrets.count === 1 ? 'key is' : 'keys are'} ` +
            `still in the database and will move to ${storeName}`
        );
    }
    /* Only what the nightly job can actually do. `stale` includes `legacy` --
     * values encrypted under a key that no longer exists -- and this line used
     * to promise those would be "re-encrypted overnight, nothing for you to
     * do", which was a promise the job re-broke every single night. */
    const fixable = Math.max(0, status.pii.stale - status.pii.legacy);
    if (fixable) {
        pending.push(
            `${fixable.toLocaleString()} resident ${fixable === 1 ? 'record' : 'records'} ` +
            `will be re-encrypted onto your current key`
        );
    }

    /* Not "pending": no amount of waiting fixes these. Said separately, in its
     * own tone, because the honest message is the opposite of the pending one
     * -- something already happened (a key rotation left these behind), and a
     * human does have a decision to make. */
    const legacy = status.pii.legacy ? (
        <p className="mt-1 text-amber-200/75">
            {status.pii.legacy.toLocaleString()} older{' '}
            {status.pii.legacy === 1 ? 'record is' : 'records are'} encrypted with a key that no
            longer exists — from before a key rotation — so their contact details cannot be read
            or re-encrypted. They can only be restored from a pre-rotation backup, or have those
            fields cleared.
        </p>
    ) : null;

    if (!pending.length) {
        return (
            <div>
                <p className="flex items-center justify-center gap-2 text-[11px] text-emerald-300/70">
                    <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
                    {status.pii.legacy
                        ? `Secrets are in ${storeName}, and everything readable is on your current encryption key.`
                        : `Secrets are in ${storeName} and resident data is on your current encryption key.`}
                </p>
                {legacy && <div className="text-[11px]">{legacy}</div>}
            </div>
        );
    }

    return (
        <div className="flex items-start gap-2 text-[11px] text-white/50">
            <RefreshCw className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary-300" />
            <div>
                <p>
                    {pending.join(', and ')}. This happens automatically overnight — everything stays
                    encrypted and readable in the meantime, and there is nothing for you to do.
                </p>
                {legacy}
            </div>
        </div>
    );
}

export default StorageStatusLine;
