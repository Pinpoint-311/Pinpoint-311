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
    if (status.pii.stale) {
        pending.push(
            `${status.pii.stale.toLocaleString()} resident ${status.pii.stale === 1 ? 'record' : 'records'} ` +
            `will be re-encrypted onto your current key`
        );
    }

    if (!pending.length) {
        return (
            <p className="flex items-center justify-center gap-2 text-[11px] text-emerald-300/70">
                <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
                Secrets are in {storeName} and resident data is on your current encryption key.
            </p>
        );
    }

    return (
        <div className="flex items-start gap-2 text-[11px] text-white/50">
            <RefreshCw className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary-300" />
            <p>
                {pending.join(', and ')}. This happens automatically overnight — everything stays
                encrypted and readable in the meantime, and there is nothing for you to do.
            </p>
        </div>
    );
}

export default StorageStatusLine;
