import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Check, Globe, Layers, Link2, MapPin, RefreshCw, Search } from 'lucide-react';
import { Button, Chip, Input, Select } from './ui';
import { api, type ArcGisInspection, type ArcGisJob, type ArcGisLayerChoice, type ArcGisSync, type MapLayer } from '../services/api';
import { useDialog } from './DialogProvider';

/**
 * Map layers from an ArcGIS link instead of an exported file.
 *
 * The import form: paste a layer, service, ArcGIS Online item or Hub dataset
 * link (and a sign-in token for a secured service) -> "Check link" -> pick a
 * layer -> the kind follows from its geometry -> name it -> Import. The import
 * runs on the server as a job this polls for progress; the result is the same
 * layer a file upload makes, so the console carries on exactly as it does for
 * uploads (polygons open their settings).
 *
 * The source panel: on a layer that came from ArcGIS, where it came from, when
 * it was last synced, automatic sync, "Check now", and "Refresh from ArcGIS".
 *
 * A token is held in this component's state only for the request it is typed
 * for. It is never stored, by the browser or the server.
 */

const POLL_MS = 1000;

export const formatDate = (iso?: string | null) => iso
    ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    : null;

/** "From ArcGIS · last synced Oct 19, 2026" for a layer that has a source. */
export function arcgisSourceLabel(layer: Pick<MapLayer, 'source_url' | 'source_synced_at'>): string | null {
    if (!layer.source_url) return null;
    const when = formatDate(layer.source_synced_at);
    return when ? `From ArcGIS · last synced ${when}` : 'From ArcGIS';
}

/** Start a job and poll it to the end. Resolves with the finished job; rejects with its error. */
export async function runArcGisJob(
    start: () => Promise<ArcGisJob>,
    onProgress?: (job: ArcGisJob) => void,
    wait: (ms: number) => Promise<void> = ms => new Promise(r => setTimeout(r, ms)),
): Promise<ArcGisJob> {
    let job = await start();
    onProgress?.(job);
    while (job.state === 'running') {
        await wait(POLL_MS);
        job = await api.getArcGisJob(job.job_id);
        onProgress?.(job);
    }
    if (job.state === 'failed') throw new Error(job.error || 'The import failed.');
    return job;
}

const progressText = (job: ArcGisJob, verb = 'Importing') => {
    if (!job.read) return `${verb} from ArcGIS…`;
    const of = job.expected ? ` of about ${job.expected.toLocaleString()}` : '';
    return `${verb}: ${job.read.toLocaleString()}${of} features read…`;
};

const GEOMETRY_LABEL: Record<string, string> = { point: 'Points', polygon: 'Polygons', line: 'Lines' };

function countText(layer: ArcGisLayerChoice, area: string | null): string {
    if (layer.feature_count == null) return 'feature count unknown';
    const total = `${layer.feature_count.toLocaleString()} feature${layer.feature_count === 1 ? '' : 's'}`;
    if (area && layer.in_area_count != null && layer.in_area_count !== layer.feature_count) {
        return `${total}, about ${layer.in_area_count.toLocaleString()} near ${area}`;
    }
    return total;
}

interface ImportFormProps {
    onCancel: () => void;
    /** The finished layer, and what kind it became. */
    onCreated: (layer: MapLayer, kind: 'points' | 'polygons') => void;
    onBusyChange?: (busy: boolean) => void;
}

export function ArcGisImportForm({ onCancel, onCreated, onBusyChange }: ImportFormProps) {
    const uid = useId();
    const id = (part: string) => `${uid}-${part}`;
    const [url, setUrl] = useState('');
    const [token, setToken] = useState('');
    const [needsToken, setNeedsToken] = useState(false);
    const [checking, setChecking] = useState(false);
    const [found, setFound] = useState<ArcGisInspection | null>(null);
    const [pickedUrl, setPickedUrl] = useState('');
    const [name, setName] = useState('');
    const [progress, setProgress] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const busy = checking || !!progress;

    useEffect(() => { onBusyChange?.(!!progress); }, [progress, onBusyChange]);

    const picked = found?.layers.find(l => l.url === pickedUrl) || null;
    const kind: 'points' | 'polygons' | null = picked?.geometry === 'point' ? 'points'
        : picked?.geometry === 'polygon' ? 'polygons' : null;

    const pick = (layer: ArcGisLayerChoice) => {
        setPickedUrl(layer.url);
        setName(prev => prev.trim() ? prev : layer.name);
    };

    const check = async (e?: React.FormEvent) => {
        e?.preventDefault();
        setError(null);
        setFound(null);
        setPickedUrl('');
        if (!url.trim()) {
            setError('Paste an ArcGIS layer link first.');
            return;
        }
        setChecking(true);
        try {
            const result = await api.inspectArcGis(url.trim(), token.trim() || undefined);
            setFound(result);
            const usable = result.layers.filter(l => l.importable);
            if (usable.length === 1) pick(usable[0]);
        } catch (err) {
            const message = (err as Error).message || 'That link could not be read.';
            if (/sign-in token/i.test(message)) setNeedsToken(true);
            setError(message);
        } finally {
            setChecking(false);
        }
    };

    const runImport = async () => {
        if (!picked || !kind) return;
        if (!name.trim()) {
            setError('Give the layer a name.');
            return;
        }
        setError(null);
        setProgress('Starting the import…');
        try {
            const job = await runArcGisJob(
                () => api.importArcGis({ url: picked.url, token: token.trim() || undefined, name: name.trim(), as: kind }),
                j => setProgress(progressText(j)),
            );
            setToken('');
            if (job.result?.layer) onCreated(job.result.layer, kind);
        } catch (err) {
            setError((err as Error).message || 'The import failed.');
        } finally {
            setProgress(null);
        }
    };

    return (
        <div className="space-y-4">
            <p className="text-sm text-white/70">
                Paste a link to an ArcGIS layer: its REST address (ending in /FeatureServer/0), its
                service, or its ArcGIS Online page. The features are downloaded and kept inside the
                township, the same as an uploaded file.
            </p>
            <form onSubmit={check} className="space-y-3" aria-describedby={id('url-help')}>
                <Input label="ArcGIS link" type="url" inputMode="url" autoComplete="off" spellCheck={false}
                    placeholder="https://services.arcgis.com/…/FeatureServer/0" value={url}
                    onChange={e => { setUrl(e.target.value); setFound(null); setPickedUrl(''); }}
                    required maxLength={2048} disabled={!!progress} />
                <p id={id('url-help')} className="-mt-2 text-xs text-white/60">https links only.</p>
                <details open={needsToken} onToggle={e => setNeedsToken((e.target as HTMLDetailsElement).open)}
                    className="rounded-xl border border-white/15 bg-white/[0.03] px-3 py-2">
                    <summary className="cursor-pointer text-sm text-white/80 py-1">This service needs a sign-in</summary>
                    <div className="pt-2 space-y-1">
                        <Input label="Sign-in token" type="password" autoComplete="off" spellCheck={false}
                            value={token} onChange={e => setToken(e.target.value)} maxLength={4096}
                            disabled={!!progress} aria-describedby={id('token-help')} />
                        <p id={id('token-help')} className="text-xs text-white/60">
                            Used for this import only and never saved. A layer that needs a token can't sync
                            automatically; refresh it by hand.
                        </p>
                    </div>
                </details>
                <div className="flex justify-end">
                    <Button type="submit" variant="secondary" isLoading={checking} disabled={busy}
                        leftIcon={<Search className="w-4 h-4" />}>
                        Check link
                    </Button>
                </div>
            </form>

            {found && (
                <fieldset className="space-y-2" disabled={!!progress}>
                    <legend className="text-sm font-medium text-white/80 mb-2">
                        {found.layers.length === 1 ? 'Layer found' : `${found.layers.length} layers found. Choose one.`}
                    </legend>
                    <ul className="space-y-2">
                        {found.layers.map(layer => {
                            const on = layer.url === pickedUrl;
                            const Icon = layer.geometry === 'point' ? MapPin : Layers;
                            return (
                                <li key={layer.url}>
                                    <label className={`flex gap-3 rounded-xl border p-3 transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-amber-300 ${layer.importable ? 'cursor-pointer' : 'cursor-not-allowed opacity-80'} ${on ? 'border-primary-300 bg-primary-500/20' : 'border-white/20 bg-white/[0.03] hover:border-white/40'}`}>
                                        <input type="radio" name={id('layer')} value={layer.url} checked={on}
                                            disabled={!layer.importable} onChange={() => pick(layer)}
                                            className="sr-only" aria-describedby={id(`layer-${layer.id}`)} />
                                        <Icon className="w-5 h-5 mt-0.5 shrink-0 text-white/70" aria-hidden="true" />
                                        <span className="min-w-0 flex-1">
                                            <span className="block text-sm font-semibold text-white break-words">{layer.name}</span>
                                            <span id={id(`layer-${layer.id}`)} className="block text-xs text-white/70">
                                                {layer.geometry ? GEOMETRY_LABEL[layer.geometry] : 'No locations'} · {countText(layer, found.area)}
                                                {layer.problem && <span className="block text-amber-200 mt-0.5">{layer.problem}</span>}
                                                {!layer.problem && layer.warning && <span className="block text-amber-200 mt-0.5">{layer.warning}</span>}
                                            </span>
                                        </span>
                                        {on && <Check className="w-4 h-4 shrink-0 text-primary-200" aria-hidden="true" />}
                                    </label>
                                </li>
                            );
                        })}
                    </ul>
                </fieldset>
            )}

            {picked && kind && (
                <div className="space-y-3 border-t border-white/10 pt-4">
                    <div role="group" aria-labelledby={id('kind')} className="space-y-2">
                        <span id={id('kind')} className="block text-sm font-medium text-white/70">Layer type</span>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            {(['points', 'polygons'] as const).map(k => (
                                <button key={k} type="button" aria-pressed={kind === k} disabled={kind !== k}
                                    className={`p-3 rounded-lg border-2 text-left ${kind === k
                                        ? 'border-primary-500 bg-primary-500/20 text-white'
                                        : 'border-white/10 bg-white/5 text-white/60 cursor-not-allowed'}`}>
                                    <span className="font-semibold">{k === 'points' ? 'Points' : 'Polygons'}</span>
                                    <span className="block text-xs text-white/70">
                                        {kind === k ? 'Chosen from the layer’s geometry' : `This layer has ${picked.geometry} features`}
                                    </span>
                                </button>
                            ))}
                        </div>
                    </div>
                    <Input label="Layer name" value={name} onChange={e => setName(e.target.value)} required maxLength={100}
                        disabled={!!progress} />
                    {found?.clipped
                        ? <p className="text-xs text-white/60">Only features inside {found.area} (and 100 m around it) are kept.</p>
                        : <p className="text-xs text-white/60">No township boundary is set, so every feature is imported. Set one in Setup to limit layers to the township.</p>}
                </div>
            )}

            {progress && <p role="status" className="text-sm text-sky-300">{progress}</p>}
            {error && <p role="alert" className="text-sm text-red-300">{error}</p>}

            <div className="flex flex-col-reverse sm:flex-row justify-end gap-3 pt-4 border-t border-white/10">
                <Button type="button" variant="ghost" onClick={onCancel} disabled={!!progress}>Cancel</Button>
                <Button type="button" onClick={runImport} disabled={!picked || !kind || busy} isLoading={!!progress}
                    leftIcon={<Globe className="w-4 h-4" />}>
                    Import
                </Button>
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// On an imported layer: where it came from, sync, refresh
// ---------------------------------------------------------------------------

const SYNC_OPTIONS = [
    { value: 'off', label: 'Off' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
];

function statusChip(layer: MapLayer) {
    switch (layer.source_sync_status) {
        case 'held': return <Chip tone="warning">Needs review</Chip>;
        case 'updated': return <Chip tone="success">Updated</Chip>;
        case 'ok': return <Chip tone="neutral">Up to date</Chip>;
        case 'error': return <Chip tone="danger">Sync failed</Chip>;
        default: return null;
    }
}

/** Refresh from ArcGIS, with the confirm that says it replaces the features. */
export function useArcGisRefresh(onUpdated: (layer: MapLayer) => void) {
    const dialog = useDialog();
    const [progress, setProgress] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const refresh = useCallback(async (layer: MapLayer, opts: { token?: string; applyAnyway?: boolean } = {}) => {
        const ok = await dialog.confirm({
            title: opts.applyAnyway ? 'Apply the held update' : 'Refresh from ArcGIS',
            message: opts.applyAnyway
                ? `Apply the latest data for "${layer.name}" even though the automatic check held it back? This replaces all ${(layer.feature_count ?? 0).toLocaleString()} features. Reports keep the context they were recorded with.`
                : `Replace the features of "${layer.name}" with the current data from ArcGIS? This replaces all ${(layer.feature_count ?? 0).toLocaleString()} features. Reports keep the context they were recorded with.`,
            variant: 'warning',
            confirmText: opts.applyAnyway ? 'Apply anyway' : 'Replace features',
        });
        if (!ok) return false;
        setError(null);
        setMessage(null);
        setProgress('Refreshing from ArcGIS…');
        try {
            const job = await runArcGisJob(
                () => api.refreshArcGisLayer(layer.id, { token: opts.token, apply_anyway: opts.applyAnyway }),
                j => setProgress(progressText(j, 'Refreshing')),
            );
            const r = job.result;
            if (r?.layer) {
                const counts = r.before != null && r.after != null
                    ? `${r.before.toLocaleString()} features before, ${r.after.toLocaleString()} now. `
                    : '';
                setMessage(`${counts}${r.layer.import_summary?.clip_message || ''}`.trim() || 'Refreshed.');
                onUpdated(r.layer);
            }
            return true;
        } catch (err) {
            setError((err as Error).message || 'The refresh failed.');
            return false;
        } finally {
            setProgress(null);
        }
    }, [dialog, onUpdated]);

    return { refresh, progress, message, error, setError, setMessage, setProgress };
}

/** A compact "Refresh from ArcGIS" for the layer list. */
export function ArcGisRefreshButton({ layer, onUpdated }: { layer: MapLayer; onUpdated: (layer: MapLayer) => void }) {
    const { refresh, progress, message, error } = useArcGisRefresh(onUpdated);
    return (
        <span className="inline-flex flex-col items-end">
            <button type="button" onClick={() => refresh(layer)} disabled={!!progress}
                aria-label={`Refresh ${layer.name} from ArcGIS`} title="Refresh from ArcGIS"
                className="p-2 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-all disabled:opacity-50">
                <RefreshCw className={`w-4 h-4 ${progress ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            </button>
            <span className="sr-only" role="status">{progress || message || ''}</span>
            {error && <span role="alert" className="text-xs text-red-300 max-w-[16rem] text-right">{error}</span>}
        </span>
    );
}

/** The ArcGIS block of a layer's settings: source, sync, check now, refresh. */
export function ArcGisSourcePanel({ layer, onUpdated }: { layer: MapLayer; onUpdated: (layer: MapLayer) => void }) {
    const uid = useId();
    const id = (part: string) => `${uid}-${part}`;
    const [token, setToken] = useState('');
    const [syncSaving, setSyncSaving] = useState(false);
    const [syncError, setSyncError] = useState<string | null>(null);
    const [checkNote, setCheckNote] = useState<string | null>(null);
    const { refresh, progress, message, error, setError, setProgress } = useArcGisRefresh(onUpdated);
    const mounted = useRef(true);
    useEffect(() => () => { mounted.current = false; }, []);

    if (!layer.source_url) return null;
    const synced = formatDate(layer.source_synced_at);
    const sync: ArcGisSync = layer.source_sync || 'off';
    const held = layer.source_sync_status === 'held';

    const changeSync = async (value: ArcGisSync) => {
        setSyncSaving(true);
        setSyncError(null);
        try {
            onUpdated(await api.setArcGisSync(layer.id, value));
        } catch (err) {
            setSyncError((err as Error).message || 'Could not change auto-sync.');
        } finally {
            if (mounted.current) setSyncSaving(false);
        }
    };

    const checkNow = async () => {
        setError(null);
        setCheckNote(null);
        setProgress('Checking ArcGIS for changes…');
        try {
            const job = await runArcGisJob(() => api.checkArcGisLayer(layer.id), j => setProgress(progressText(j, 'Checking')));
            const r = job.result;
            if (r?.layer) onUpdated(r.layer);
            const s = r?.sync;
            setCheckNote(!s ? 'Checked.'
                : s.state === 'unchanged' ? 'No changes in ArcGIS since the last sync.'
                    : s.state === 'updated' ? `Updated: ${s.before?.toLocaleString()} features before, ${s.after?.toLocaleString()} now.`
                        : s.state === 'held' ? `Held for review: ${s.reason}`
                            : 'The check failed. Try again later.');
        } catch (err) {
            setError((err as Error).message || 'The check failed.');
        } finally {
            setProgress(null);
        }
    };

    return (
        <div className="space-y-4 rounded-xl border border-white/15 bg-white/[0.03] p-4" aria-labelledby={id('title')} role="group">
            <div className="flex flex-wrap items-center gap-2">
                <Link2 className="w-4 h-4 text-primary-300" aria-hidden="true" />
                <h4 id={id('title')} className="text-sm font-semibold text-white">From ArcGIS</h4>
                {statusChip(layer)}
            </div>
            <p className="text-xs text-white/70 break-all">{layer.source_url}</p>
            <p className="text-sm text-white/80">
                {synced ? `Last synced ${synced}` : 'Not synced yet'} · {(layer.feature_count ?? 0).toLocaleString()} features
            </p>
            {held && (
                <div role="alert" className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-3 text-sm text-amber-100 space-y-2">
                    <p><strong className="font-semibold">Needs review.</strong> {layer.source_sync_error} The layer keeps its previous features.</p>
                    <div className="flex flex-wrap gap-2">
                        <Button type="button" size="sm" variant="secondary" disabled={!!progress}
                            onClick={() => refresh(layer, { token: token.trim() || undefined, applyAnyway: true })}>
                            Apply anyway
                        </Button>
                        <Button type="button" size="sm" variant="ghost" disabled={syncSaving} onClick={() => changeSync('off')}>
                            Turn auto-sync off
                        </Button>
                    </div>
                </div>
            )}
            {!held && layer.source_sync_status === 'error' && layer.source_sync_error && (
                <p className="text-sm text-red-200">{layer.source_sync_error}</p>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-start">
                <div>
                    <Select label="Auto-sync" value={sync} options={SYNC_OPTIONS} disabled={syncSaving || !!progress}
                        onChange={e => changeSync(e.target.value as ArcGisSync)} aria-describedby={id('sync-help')} />
                    <p id={id('sync-help')} className="mt-1 text-xs text-white/60">
                        Auto-sync needs a public service. For secured services, use Refresh from ArcGIS.
                        Large changes are held for review instead of applied.
                    </p>
                    {syncError && <p role="alert" className="mt-1 text-xs text-red-300">{syncError}</p>}
                </div>
                <div className="flex flex-wrap gap-2 sm:justify-end sm:pt-7">
                    <Button type="button" size="sm" variant="secondary" disabled={!!progress} onClick={checkNow}>
                        Check now
                    </Button>
                    <Button type="button" size="sm" disabled={!!progress}
                        onClick={() => refresh(layer, { token: token.trim() || undefined })}
                        leftIcon={<RefreshCw className="w-4 h-4" aria-hidden="true" />}>
                        Refresh from ArcGIS
                    </Button>
                </div>
            </div>
            <details className="text-sm">
                <summary className="cursor-pointer text-white/80">This service needs a sign-in</summary>
                <div className="pt-2">
                    <Input label="Sign-in token for this refresh" type="password" autoComplete="off" spellCheck={false}
                        value={token} onChange={e => setToken(e.target.value)} maxLength={4096} />
                    <p className="mt-1 text-xs text-white/60">Used for this refresh only and never saved.</p>
                </div>
            </details>
            {progress && <p role="status" className="text-sm text-sky-200">{progress}</p>}
            {!progress && (message || checkNote) && <p role="status" className="text-sm text-emerald-200">{message || checkNote}</p>}
            {error && <p role="alert" className="text-sm text-red-200">{error}</p>}
        </div>
    );
}
