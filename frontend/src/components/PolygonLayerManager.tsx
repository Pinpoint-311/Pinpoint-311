import { useEffect, useMemo, useState } from 'react';
import { Upload } from 'lucide-react';
import { Button, Chip, Input, Modal } from './ui';
import { api, MapLayer } from '../services/api';
import { useDialog } from './DialogProvider';

/**
 * Polygon layers for the admin console: tax parcels, zoning, districts.
 *
 * Two dialogs. The upload dialog sends the GeoJSON in parts (a parcel file is
 * far larger than one request may be) and the server builds the layer from
 * it. The settings dialog is where an admin decides what the layer is FOR and
 * what staff may see of it:
 *
 *   - purpose: record which feature each report falls in ("location context"),
 *     or display only;
 *   - which field identifies a feature (PARCEL_ID, PIN) and which labels it;
 *   - which fields staff see -- none until chosen. Nothing outside this list
 *     is ever copied onto a report or shown anywhere;
 *   - the resident portal, off by default and refused while no fields are
 *     chosen or a chosen field looks like owner details.
 */

export const MAX_LAYER_UPLOAD_BYTES = 100 * 1024 * 1024;

/** Send a file to the server in parts. Returns the upload id to import from. */
export async function uploadInChunks(file: Blob, onProgress?: (sent: number, total: number) => void): Promise<string> {
    if (file.size > MAX_LAYER_UPLOAD_BYTES) {
        throw new Error(`The file is ${Math.round(file.size / 1048576)} MB; the limit is 100 MB. Split the layer, or drop columns you do not need before exporting.`);
    }
    const { upload_id, chunk_bytes } = await api.startLayerUpload(file.size);
    try {
        let index = 0;
        for (let offset = 0; offset < file.size; offset += chunk_bytes, index++) {
            await api.uploadLayerChunk(upload_id, index, file.slice(offset, offset + chunk_bytes));
            onProgress?.(Math.min(offset + chunk_bytes, file.size), file.size);
        }
    } catch (err) {
        api.discardLayerUpload(upload_id).catch(() => { /* expires on its own */ });
        throw err;
    }
    return upload_id;
}

const mb = (n: number) => `${(n / 1048576).toFixed(n < 10485760 ? 1 : 0)} MB`;

function useUpload() {
    const [progress, setProgress] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const run = async <T,>(file: File, importer: (uploadId: string) => Promise<T>): Promise<T | null> => {
        setError(null);
        try {
            setProgress(`Uploading 0 of ${mb(file.size)}…`);
            const id = await uploadInChunks(file, (sent, total) => setProgress(`Uploading ${mb(sent)} of ${mb(total)}…`));
            setProgress('Importing features. A large parcel layer can take a minute…');
            return await importer(id);
        } catch (err) {
            setError((err as Error).message || 'The upload failed.');
            return null;
        } finally {
            setProgress(null);
        }
    };
    return { progress, error, setError, run };
}

interface UploadProps {
    isOpen: boolean;
    onClose: () => void;
    onCreated: (layer: MapLayer) => void;
}

export function PolygonLayerUploadModal({ isOpen, onClose, onCreated }: UploadProps) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [file, setFile] = useState<File | null>(null);
    const { progress, error, setError, run } = useUpload();

    useEffect(() => {
        if (isOpen) { setName(''); setDescription(''); setFile(null); setError(null); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim() || !file) {
            setError('Enter a name and choose a GeoJSON file.');
            return;
        }
        const layer = await run(file, upload_id => api.createPolygonLayer({
            name: name.trim(), description: description.trim() || undefined, upload_id, routing_mode: 'context',
        }));
        if (layer) onCreated(layer);
    };

    return (
        <Modal isOpen={isOpen} onClose={() => { if (!progress) onClose(); }} title="Add polygon layer">
            <form onSubmit={submit} className="space-y-4">
                <p className="text-sm text-white/60">
                    Tax parcels, zoning, wards or any other polygons. Each new report records which
                    polygon it falls in, and staff see that on the report and the work order.
                </p>
                <Input label="Layer name" placeholder="e.g., Tax Parcels" value={name}
                    onChange={e => setName(e.target.value)} required maxLength={100} />
                <Input label="Description (optional)" value={description}
                    onChange={e => setDescription(e.target.value)} maxLength={500} />
                <div>
                    <label htmlFor="polygon-layer-file" className="block text-sm font-medium text-white/70 mb-2">GeoJSON file</label>
                    <input
                        id="polygon-layer-file"
                        type="file"
                        accept=".geojson,.json,application/geo+json,application/json"
                        onChange={e => setFile(e.target.files?.[0] || null)}
                        className="w-full text-sm text-white/60 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary-500 file:text-white hover:file:bg-primary-600 file:cursor-pointer"
                    />
                    <p className="text-xs text-white/40 mt-1">
                        A FeatureCollection of Polygon / MultiPolygon features in WGS 84 (EPSG:4326),
                        up to 100 MB and 200,000 features.
                    </p>
                </div>
                {progress && <p role="status" className="text-sm text-sky-300">{progress}</p>}
                {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
                <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                    <Button type="button" variant="ghost" onClick={onClose} disabled={!!progress}>Cancel</Button>
                    <Button type="submit" isLoading={!!progress} leftIcon={<Upload className="w-4 h-4" />}>Upload and create</Button>
                </div>
            </form>
        </Modal>
    );
}

interface SettingsProps {
    layer: MapLayer | null;
    isOpen: boolean;
    onClose: () => void;
    onSaved: (layer: MapLayer) => void;
}

export function ContextLayerSettingsModal({ layer, isOpen, onClose, onSaved }: SettingsProps) {
    const [purpose, setPurpose] = useState<'context' | 'none'>('context');
    const [idProp, setIdProp] = useState('');
    const [labelProp, setLabelProp] = useState('');
    const [staff, setStaff] = useState<string[]>([]);
    const [portal, setPortal] = useState(false);
    const [visibleOnMap, setVisibleOnMap] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [warnings, setWarnings] = useState<string[]>([]);
    const [reuploadFile, setReuploadFile] = useState<File | null>(null);
    const { progress, error, setError, run } = useUpload();
    const dialog = useDialog();

    useEffect(() => {
        if (!layer || !isOpen) return;
        setPurpose(layer.routing_mode === 'context' ? 'context' : 'none');
        setIdProp(layer.feature_id_property || '');
        setLabelProp(layer.label_property || '');
        setStaff(layer.staff_properties || []);
        setPortal(!!layer.show_on_resident_portal);
        setVisibleOnMap(layer.visible_on_map !== false);
        setMessage(null);
        setWarnings(layer.warnings || []);
        setError(null);
        setReuploadFile(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [layer?.id, isOpen]);

    const fields = layer?.available_properties || [];
    const flags = layer?.field_flags || {};
    const ownerChosen = staff.filter(f => flags[f] === 'owner');
    const portalBlocked = staff.length === 0
        ? 'Choose the fields staff see first. A layer with no reviewed fields stays staff-only.'
        : ownerChosen.length
            ? `Layers whose staff fields include owner details (${ownerChosen.join(', ')}) stay off the resident portal.`
            : null;
    const fieldOptions = useMemo(() => fields.map(f => ({ value: f, label: f })), [fields]);

    if (!layer) return null;

    const toggleStaff = (field: string, on: boolean) => {
        setStaff(prev => on ? [...prev, field] : prev.filter(f => f !== field));
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        setMessage(null);
        try {
            const saved = await api.updateMapLayer(layer.id, {
                routing_mode: purpose,
                feature_id_property: idProp,
                label_property: labelProp,
                staff_properties: staff,
                visible_on_map: visibleOnMap,
                show_on_resident_portal: portal && !portalBlocked,
            });
            setWarnings(saved.warnings || []);
            setMessage('Saved.');
            onSaved(saved);
        } catch (err) {
            setError((err as Error).message || 'Could not save the layer.');
        } finally {
            setSaving(false);
        }
    };

    const reupload = async () => {
        if (!reuploadFile) return;
        const saved = await run(reuploadFile, id => api.reuploadLayerFeatures(layer.id, id));
        if (saved) {
            setMessage(`Replaced with ${saved.feature_count?.toLocaleString()} features. Reports keep the context they were recorded with.`);
            setReuploadFile(null);
            onSaved(saved);
        }
    };

    const backfill = async () => {
        const ok = await dialog.confirm({
            title: 'Record on existing reports',
            message: `Record "${layer.name}" on existing reports that don't have it yet? Each report updated gets a timeline entry. Reports already carrying this layer keep what was recorded at intake.`,
            variant: 'info',
            confirmText: 'Record',
        });
        if (!ok) return;
        setSaving(true);
        setError(null);
        try {
            const r = await api.backfillLayerContext(layer.id);
            setMessage(`Checked ${r.scanned.toLocaleString()} reports; ${r.updated.toLocaleString()} now carry this layer's context.`);
        } catch (err) {
            setError((err as Error).message || 'The backfill failed.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <Modal isOpen={isOpen} onClose={() => { if (!progress && !saving) onClose(); }} title={`Layer settings: ${layer.name}`} size="lg">
            <form onSubmit={save} className="space-y-5">
                <p className="text-xs text-white/50">
                    {(layer.feature_count ?? 0).toLocaleString()} polygons
                    {layer.features_imported_at && <> · imported {new Date(layer.features_imported_at).toLocaleDateString()}</>}
                </p>

                <fieldset className="space-y-2">
                    <legend className="text-sm font-medium text-white/70 mb-1">Purpose</legend>
                    <label className="flex items-start gap-2 text-sm text-white/80">
                        <input type="radio" name="layer-purpose" checked={purpose === 'context'} onChange={() => setPurpose('context')} className="mt-1" />
                        <span>Location context <span className="block text-xs text-white/45">Record which polygon each new report falls in. Staff see it on the report, with other reports in the same polygon, and on the work order.</span></span>
                    </label>
                    <label className="flex items-start gap-2 text-sm text-white/80">
                        <input type="radio" name="layer-purpose" checked={purpose === 'none'} onChange={() => setPurpose('none')} className="mt-1" />
                        <span>Display only <span className="block text-xs text-white/45">Nothing is recorded on reports.</span></span>
                    </label>
                </fieldset>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                        <label htmlFor="layer-id-field" className="block text-sm font-medium text-white/70 mb-1">ID field</label>
                        <select id="layer-id-field" value={idProp} onChange={e => setIdProp(e.target.value)}
                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3">
                            <option value="">None (identify by shape)</option>
                            {fieldOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                        <p className="text-xs text-white/40 mt-1">Keeps a parcel's report history together when the layer is re-uploaded.</p>
                    </div>
                    <div>
                        <label htmlFor="layer-label-field" className="block text-sm font-medium text-white/70 mb-1">Label field</label>
                        <select id="layer-label-field" value={labelProp} onChange={e => setLabelProp(e.target.value)}
                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3">
                            <option value="">Use the ID</option>
                            {fieldOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                        <p className="text-xs text-white/40 mt-1">The name shown on the report and the map, e.g. the property address.</p>
                    </div>
                </div>

                <fieldset>
                    <legend className="text-sm font-medium text-white/70 mb-1">Fields staff see</legend>
                    <p className="text-xs text-white/45 mb-2">
                        None until you choose. Only these are copied onto reports (as they read when the report came in);
                        every other field in the file is used for matching and never shown.
                    </p>
                    {fields.length === 0 ? (
                        <p className="text-sm text-white/40">The file has no fields.</p>
                    ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 max-h-56 overflow-y-auto p-2 rounded-lg bg-white/5 border border-white/10">
                            {fields.map(field => (
                                <label key={field} className="flex items-center gap-2 text-sm text-white/75 p-1.5 rounded hover:bg-white/5">
                                    <input type="checkbox" checked={staff.includes(field)} onChange={e => toggleStaff(field, e.target.checked)} />
                                    <span className="min-w-0 truncate font-mono text-[13px]">{field}</span>
                                    {flags[field] === 'owner' && <Chip tone="danger">Owner details</Chip>}
                                    {flags[field] === 'maybe' && <Chip tone="warning">May be personal</Chip>}
                                </label>
                            ))}
                        </div>
                    )}
                </fieldset>

                <div className="space-y-2">
                    <label className="flex items-center gap-2 text-sm text-white/80">
                        <input type="checkbox" checked={visibleOnMap} onChange={e => setVisibleOnMap(e.target.checked)} />
                        Show outlines on the staff map (at parcel zoom)
                    </label>
                    <label className="flex items-start gap-2 text-sm text-white/80">
                        <input type="checkbox" checked={portal && !portalBlocked} disabled={!!portalBlocked}
                            onChange={e => setPortal(e.target.checked)} className="mt-1"
                            aria-describedby="layer-portal-help" />
                        <span>Show on the resident portal
                            <span id="layer-portal-help" className="block text-xs text-white/45">
                                {portalBlocked || 'Off by default. Residents see faint outlines on the Community Requests map at parcel zoom: shapes only, never field values or IDs.'}
                            </span>
                        </span>
                    </label>
                </div>

                {warnings.length > 0 && (
                    <ul className="space-y-1 rounded-lg border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-200">
                        {warnings.map(w => <li key={w}>{w}</li>)}
                    </ul>
                )}

                <div className="rounded-lg border border-white/10 p-3 space-y-2">
                    <p className="text-sm font-medium text-white/70">Replace the polygons</p>
                    <input type="file" accept=".geojson,.json,application/geo+json,application/json"
                        aria-label="Replacement GeoJSON file"
                        onChange={e => setReuploadFile(e.target.files?.[0] || null)}
                        className="w-full text-xs text-white/60" />
                    <div className="flex flex-wrap gap-2">
                        <Button type="button" size="sm" variant="secondary" disabled={!reuploadFile || !!progress} onClick={reupload}>Upload replacement</Button>
                        {purpose === 'context' && layer.routing_mode === 'context' && (
                            <Button type="button" size="sm" variant="secondary" disabled={saving || !!progress} onClick={backfill}>Record on existing reports</Button>
                        )}
                    </div>
                </div>

                {progress && <p role="status" className="text-sm text-sky-300">{progress}</p>}
                {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}
                {error && <p role="alert" className="text-sm text-red-300">{error}</p>}

                <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                    <Button type="button" variant="ghost" onClick={onClose} disabled={saving || !!progress}>Close</Button>
                    <Button type="submit" isLoading={saving}>Save settings</Button>
                </div>
            </form>
        </Modal>
    );
}

/** "routing_mode: context" reads "Location context" in the layer list. */
export function layerPurposeLabel(layer: MapLayer): string | null {
    if (layer.routing_mode === 'context') return 'Location context';
    if (layer.feature_storage === 'table') return 'Display only';
    return null;
}
