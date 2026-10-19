import { useMemo, useRef, useState } from 'react';
import { Copy, FileUp } from 'lucide-react';

import type { RoutingContact, ServiceDefinition } from '../types';
import { useDialog } from './DialogProvider';
import { Chip } from './ui';
import { agencyRoads, cloneAgency, parseAgencyFile, savedAgencies } from '../utils/agencyLibrary';

/**
 * "Add a saved agency": reuse an agency, with its roads, that is already set up
 * on another category -- or import a ready-made set from a file -- instead of
 * typing it in again.
 *
 * Applying copies. The category being edited gets its own agency, so a later
 * edit here does not reach the category it came from, and vice versa. Nothing
 * is saved until the clerk saves this category, which is audited like any
 * other category edit (the server records the agencies added by name).
 */

interface Props {
    services: ServiceDefinition[];
    /** The category being edited; its own agencies are not offered back to it. */
    currentServiceId?: number | null;
    /** Agencies already on this category, to refuse a duplicate name. */
    currentAgencies: RoutingContact[];
    onApply: (agencies: RoutingContact[]) => void;
}

const readText = (file: File): Promise<string> => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(new Error('That file could not be read.'));
    reader.readAsText(file);
});

const roadCount = (n: number) => `${n} road${n === 1 ? '' : 's'}`;
const sameName = (a?: string, b?: string) => (a || '').trim().toLowerCase() === (b || '').trim().toLowerCase();

export default function AgencyReusePicker({ services, currentServiceId, currentAgencies, onApply }: Props) {
    const dialog = useDialog();
    const saved = useMemo(() => savedAgencies(services, currentServiceId), [services, currentServiceId]);
    const [selected, setSelected] = useState('');
    const [status, setStatus] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const fileRef = useRef<HTMLInputElement>(null);

    const alreadyHere = (agency: RoutingContact) => currentAgencies.some(a => sameName(a?.name, agency.name));

    const apply = () => {
        const choice = saved.find(s => s.key === selected);
        if (!choice || alreadyHere(choice.agency)) return;
        onApply([cloneAgency(choice.agency)]);
        setStatus(
            `Copied ${choice.agency.name} and ${roadCount(choice.roads.length)} from ${choice.usedBy.join(', ')}. ` +
            'This is a separate copy: editing it here changes only this category. Save to keep it.',
        );
        setError(null);
        setSelected('');
    };

    const importFile = async (file: File) => {
        setStatus(null);
        setError(null);
        let agencies: RoutingContact[];
        try {
            agencies = parseAgencyFile(await readText(file));
        } catch (err) {
            setError((err as Error).message);
            return;
        }
        const fresh = agencies.filter(a => !alreadyHere(a));
        const skipped = agencies.filter(a => alreadyHere(a)).map(a => a.name);
        if (fresh.length === 0) {
            setError(`Every agency in ${file.name} is already on this category.`);
            return;
        }
        const summary = fresh.map(a => `${a.name} (${roadCount(agencyRoads(a).length)})`).join(', ');
        const ok = await dialog.confirm({
            title: 'Import agencies',
            message: `Add ${summary} to this category?` +
                (skipped.length ? ` Already here, so skipped: ${skipped.join(', ')}.` : '') +
                ' Check the contact details afterwards: an imported file may leave them blank.',
            confirmText: 'Import',
        });
        if (!ok) return;
        onApply(fresh);
        setStatus(`Imported ${fresh.length} agenc${fresh.length === 1 ? 'y' : 'ies'} from ${file.name}. Save to keep them.`);
    };

    return (
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3.5 space-y-2.5">
            <div className="flex flex-col sm:flex-row sm:items-end gap-2">
                <div className="flex-1 min-w-0">
                    <label htmlFor="saved-agency-select" className="block text-[11px] font-semibold text-white/70 mb-1">
                        Add a saved agency
                    </label>
                    <select
                        id="saved-agency-select"
                        value={selected}
                        onChange={e => { setSelected(e.target.value); setStatus(null); }}
                        disabled={saved.length === 0}
                        className="w-full h-10 rounded-xl bg-white/[0.08] border border-white/20 text-white px-3 text-sm focus:outline-none focus:border-amber-400 disabled:opacity-60"
                    >
                        <option value="">
                            {saved.length ? 'Choose an agency set up on another category…' : 'No agencies on other categories yet'}
                        </option>
                        {saved.map(s => (
                            <option key={s.key} value={s.key} disabled={alreadyHere(s.agency)}>
                                {s.agency.name}: {roadCount(s.roads.length)} (on {s.usedBy.join(', ')})
                                {alreadyHere(s.agency) ? ', already on this category' : ''}
                            </option>
                        ))}
                    </select>
                </div>
                <button type="button" className="btn-outline btn-outline-md shrink-0" onClick={apply} disabled={!selected}>
                    <Copy className="w-4 h-4" aria-hidden="true" /> Apply to this category
                </button>
                <button type="button" className="btn-outline btn-outline-md shrink-0" onClick={() => fileRef.current?.click()}>
                    <FileUp className="w-4 h-4" aria-hidden="true" /> Import from file
                </button>
                <input
                    ref={fileRef}
                    type="file"
                    accept=".json,application/json"
                    className="hidden"
                    aria-label="Agencies file"
                    data-testid="agency-file-input"
                    onChange={e => {
                        const file = e.target.files?.[0];
                        e.target.value = '';
                        if (file) void importFile(file);
                    }}
                />
            </div>
            {selected && (() => {
                const choice = saved.find(s => s.key === selected);
                if (!choice) return null;
                return (
                    <div className="flex flex-wrap gap-1.5" aria-label={`Roads for ${choice.agency.name}`}>
                        {choice.roads.slice(0, 12).map(r => <Chip key={r} tone="neutral">{r}</Chip>)}
                        {choice.roads.length > 12 && <Chip tone="info">+{choice.roads.length - 12} more</Chip>}
                    </div>
                );
            })()}
            {status && <p role="status" className="text-xs text-emerald-300">{status}</p>}
            {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
        </div>
    );
}
