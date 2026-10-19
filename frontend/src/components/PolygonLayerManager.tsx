import { useEffect, useId, useMemo, useState } from 'react';
import {
    AlertTriangle, Check, Database, Eye, FileUp, History, Layers, ListChecks, MapPin, Search, Tag, Target, Upload,
    type LucideIcon,
} from 'lucide-react';
import { Button, Chip, Input, Modal, Select } from './ui';
import { api, MapLayer } from '../services/api';
import type { ServiceDefinition } from '../types';
import { useDialog } from './DialogProvider';
import { Switch } from './capabilityUI';
import { CategoryScopePicker } from './CategoryScopePicker';

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
 *     chosen or a chosen field looks like owner details;
 *   - which categories each side applies to: the reports the feature is
 *     recorded on (service_codes), and the residents who see the outlines
 *     (resident_service_codes). Empty is every category on both.
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

interface UploadFormProps {
    onCancel: () => void;
    onCreated: (layer: MapLayer) => void;
    /** Told when an upload starts and ends, so a host dialog can refuse to close mid-upload. */
    onBusyChange?: (busy: boolean) => void;
}

/**
 * The polygon upload itself: name, file, chunked upload, import. Rendered
 * inside the console's one "Add Layer" dialog once Polygons is chosen, and by
 * PolygonLayerUploadModal on its own.
 */
export function PolygonLayerUploadForm({ onCancel, onCreated, onBusyChange }: UploadFormProps) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [file, setFile] = useState<File | null>(null);
    const { progress, error, setError, run } = useUpload();

    useEffect(() => { onBusyChange?.(!!progress); }, [progress, onBusyChange]);

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
                    up to 100 MB and 200,000 features. Next you choose which field identifies a
                    polygon and what staff may see; nothing is shown until then.
                </p>
            </div>
            {progress && <p role="status" className="text-sm text-sky-300">{progress}</p>}
            {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
            <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                <Button type="button" variant="ghost" onClick={onCancel} disabled={!!progress}>Cancel</Button>
                <Button type="submit" isLoading={!!progress} leftIcon={<Upload className="w-4 h-4" />}>Upload and create</Button>
            </div>
        </form>
    );
}

interface UploadProps {
    isOpen: boolean;
    onClose: () => void;
    onCreated: (layer: MapLayer) => void;
}

export function PolygonLayerUploadModal({ isOpen, onClose, onCreated }: UploadProps) {
    const [busy, setBusy] = useState(false);
    return (
        <Modal isOpen={isOpen} onClose={() => { if (!busy) onClose(); }} title="Add polygon layer">
            {/* Remounted on every open, so it starts empty each time. */}
            {isOpen && <PolygonLayerUploadForm onCancel={onClose} onCreated={onCreated} onBusyChange={setBusy} />}
        </Modal>
    );
}

interface SettingsProps {
    layer: MapLayer | null;
    isOpen: boolean;
    onClose: () => void;
    onSaved: (layer: MapLayer) => void;
}

/** A titled block of the settings dialog. Each is a region named by its heading. */
function Section({ id, icon: Icon, title, aside, children }: {
    id: string; icon: LucideIcon; title: string; aside?: React.ReactNode; children: React.ReactNode;
}) {
    return (
        <section aria-labelledby={id} className="isolate rounded-2xl border border-white/10 bg-white/[0.04] p-4 sm:p-5 space-y-4">
            <div className="flex items-center justify-between gap-3">
                <h3 id={id} className="flex items-center gap-2 text-base font-semibold text-white">
                    <Icon className="w-4 h-4 text-primary-300" aria-hidden="true" />
                    {title}
                </h3>
                {aside}
            </div>
            {children}
        </section>
    );
}

const PURPOSES = [
    { value: 'context' as const, icon: MapPin, title: 'Location context', detail: 'Record the polygon each report falls in. Staff see it on the report and work order.' },
    { value: 'none' as const, icon: Eye, title: 'Display only', detail: 'Outlines on the map. Nothing is recorded on reports.' },
];

export function ContextLayerSettingsModal({ layer, isOpen, onClose, onSaved }: SettingsProps) {
    const [purpose, setPurpose] = useState<'context' | 'none'>('context');
    const [idProp, setIdProp] = useState('');
    const [labelProp, setLabelProp] = useState('');
    const [staff, setStaff] = useState<string[]>([]);
    const [portal, setPortal] = useState(false);
    const [visibleOnMap, setVisibleOnMap] = useState(true);
    const [staffCodes, setStaffCodes] = useState<string[]>([]);
    const [residentCodes, setResidentCodes] = useState<string[]>([]);
    const [services, setServices] = useState<ServiceDefinition[]>([]);
    const [servicesLoading, setServicesLoading] = useState(false);
    const [fieldQuery, setFieldQuery] = useState('');
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [warnings, setWarnings] = useState<string[]>([]);
    const [reuploadFile, setReuploadFile] = useState<File | null>(null);
    const [dragging, setDragging] = useState(false);
    const { progress, error, setError, run } = useUpload();
    const dialog = useDialog();
    const uid = useId();

    useEffect(() => {
        if (!layer || !isOpen) return;
        setPurpose(layer.routing_mode === 'context' ? 'context' : 'none');
        setIdProp(layer.feature_id_property || '');
        setLabelProp(layer.label_property || '');
        setStaff(layer.staff_properties || []);
        setPortal(!!layer.show_on_resident_portal);
        setVisibleOnMap(layer.visible_on_map !== false);
        setStaffCodes(layer.service_codes || []);
        setResidentCodes(layer.resident_service_codes || []);
        setFieldQuery('');
        setMessage(null);
        setWarnings(layer.warnings || []);
        setError(null);
        setReuploadFile(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [layer?.id, isOpen]);

    // The admin category list, hidden-from-public categories included: the
    // same source the point-layer form uses.
    useEffect(() => {
        if (!isOpen) return;
        let cancelled = false;
        setServicesLoading(true);
        api.getServices()
            .then(rows => { if (!cancelled) setServices(rows); })
            .catch(() => { /* the pickers say there are no categories */ })
            .finally(() => { if (!cancelled) setServicesLoading(false); });
        return () => { cancelled = true; };
    }, [isOpen]);

    const fields = layer?.available_properties || [];
    const flags = layer?.field_flags || {};
    const ownerChosen = staff.filter(f => flags[f] === 'owner');
    const portalBlocked = staff.length === 0
        ? 'Choose the fields staff see first.'
        : ownerChosen.length
            ? `Owner details are among the staff fields (${ownerChosen.join(', ')}).`
            : null;
    const portalOn = portal && !portalBlocked;
    const fieldOptions = useMemo(() => fields.map(f => ({ value: f, label: f })), [fields]);
    const shownFields = useMemo(() => {
        const q = fieldQuery.trim().toLowerCase();
        return q ? fields.filter(f => f.toLowerCase().includes(q)) : fields;
    }, [fields, fieldQuery]);

    if (!layer) return null;

    const busy = saving || !!progress;
    const id = (part: string) => `${uid}-${part}`;

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
                show_on_resident_portal: portalOn,
                // Empty = every category, on both.
                service_codes: staffCodes,
                resident_service_codes: residentCodes,
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
        const saved = await run(reuploadFile, uploadId => api.reuploadLayerFeatures(layer.id, uploadId));
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

    const imported = layer.features_imported_at
        ? new Date(layer.features_imported_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
        : null;

    return (
        <Modal isOpen={isOpen} onClose={() => { if (!busy) onClose(); }} title={layer.name} size="xl"
            aria-describedby={id('meta')}>
            {/* -mb-6 here, not on the footer: a sticky element cannot leave its
                parent, so the footer only reaches the dialog's bottom edge if
                the form itself extends over the body's padding. */}
            <form onSubmit={save} className="space-y-4 -mb-6">
                <p id={id('meta')} className="-mt-2 text-sm text-white/70">
                    Polygon layer settings · {(layer.feature_count ?? 0).toLocaleString()} polygons
                    {imported && <> · imported {imported}</>}
                </p>

                <Section id={id('purpose')} icon={Target} title="Purpose">
                    <div role="radiogroup" aria-labelledby={id('purpose')} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {PURPOSES.map(p => {
                            const on = purpose === p.value;
                            return (
                                <label key={p.value}
                                    className={`relative flex gap-3 rounded-xl border p-4 cursor-pointer transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-amber-300 ${on ? 'border-primary-300 bg-primary-500/20' : 'border-white/20 bg-white/[0.03] hover:bg-white/[0.07] hover:border-white/40'}`}>
                                    <input type="radio" name={id('purpose-radio')} value={p.value} checked={on}
                                        onChange={() => setPurpose(p.value)} className="sr-only"
                                        aria-describedby={id(`purpose-${p.value}`)} />
                                    <p.icon className={`w-5 h-5 mt-0.5 shrink-0 ${on ? 'text-primary-200' : 'text-white/60'}`} aria-hidden="true" />
                                    <span className="min-w-0">
                                        <span className="block text-sm font-semibold text-white">{p.title}</span>
                                        <span id={id(`purpose-${p.value}`)} className="block mt-0.5 text-xs text-white/70">{p.detail}</span>
                                    </span>
                                    {on && <Check className="absolute top-3 right-3 w-4 h-4 text-primary-200" aria-hidden="true" />}
                                </label>
                            );
                        })}
                    </div>
                </Section>

                <Section id={id('identify')} icon={Tag} title="Identify features">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <Select label="ID field" value={idProp} onChange={e => setIdProp(e.target.value)}
                            options={[{ value: '', label: 'None (identify by shape)' }, ...fieldOptions]}
                            helperText="Keeps a parcel's history together across re-uploads." />
                        <Select label="Label field" value={labelProp} onChange={e => setLabelProp(e.target.value)}
                            options={[{ value: '', label: 'Use the ID' }, ...fieldOptions]}
                            helperText="Shown on reports and the map, e.g. the address." />
                    </div>
                </Section>

                <Section id={id('fields')} icon={ListChecks} title="What staff see"
                    aside={fields.length > 0 && (
                        <span className="text-xs font-medium text-white/70 whitespace-nowrap">{staff.length} of {fields.length} selected</span>
                    )}>
                    <p className="-mt-2 text-xs text-white/70">
                        Only these fields are copied onto reports. The rest are used for matching and never shown.
                    </p>
                    {fields.length === 0 ? (
                        <p className="text-sm text-white/60">The file has no fields.</p>
                    ) : (
                        <>
                            <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                                <div className="relative flex-1 min-w-0">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/50 pointer-events-none z-10" aria-hidden="true" />
                                    <input type="search" value={fieldQuery} onChange={e => setFieldQuery(e.target.value)}
                                        aria-label="Search fields" placeholder="Search fields"
                                        className="glass-input !py-2 pl-9 text-sm w-full" />
                                </div>
                                <div className="flex gap-2 shrink-0">
                                    <button type="button" className="btn-outline" disabled={shownFields.length === 0}
                                        onClick={() => setStaff(prev => [...prev, ...shownFields.filter(f => !prev.includes(f))])}>
                                        {fieldQuery.trim() ? 'Select shown' : 'Select all'}
                                    </button>
                                    <button type="button" className="btn-outline" disabled={staff.length === 0}
                                        onClick={() => setStaff(prev => prev.filter(f => !shownFields.includes(f)))}>
                                        None
                                    </button>
                                </div>
                            </div>
                            {shownFields.length === 0 ? (
                                <p className="text-sm text-white/60">No field matches "{fieldQuery.trim()}".</p>
                            ) : (
                                <ul aria-label="Fields staff see" className="grid grid-cols-1 sm:grid-cols-2 gap-1 max-h-[22rem] overflow-y-auto p-1.5 rounded-xl bg-black/10 border border-white/10">
                                    {shownFields.map(field => {
                                        const on = staff.includes(field);
                                        return (
                                            <li key={field}>
                                                <label className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm cursor-pointer transition-colors ${on ? 'bg-primary-500/15 text-white' : 'text-white/85 hover:bg-white/10'}`}>
                                                    <input type="checkbox" checked={on} onChange={e => toggleStaff(field, e.target.checked)}
                                                        className="w-4 h-4 shrink-0 rounded border-white/40 bg-white/10 text-primary-500 focus:ring-primary-500 focus:ring-offset-0" />
                                                    <span className="min-w-0 flex-1 break-all">{field}</span>
                                                    {flags[field] === 'owner' && <Chip tone="danger">Owner details</Chip>}
                                                    {flags[field] === 'maybe' && <Chip tone="warning">May be personal</Chip>}
                                                </label>
                                            </li>
                                        );
                                    })}
                                </ul>
                            )}
                        </>
                    )}
                </Section>

                <Section id={id('visibility')} icon={Eye} title="Visibility">
                    <div className="divide-y divide-white/10">
                        <div className="flex items-start justify-between gap-4 pb-4">
                            <div className="min-w-0">
                                <p className="text-sm font-medium text-white">Show outlines on the staff map</p>
                                <p id={id('staffmap-help')} className="text-xs text-white/70">Drawn at parcel zoom.</p>
                            </div>
                            <Switch on={visibleOnMap} onChange={() => setVisibleOnMap(v => !v)}
                                label="Show outlines on the staff map" aria-describedby={id('staffmap-help')} />
                        </div>
                        <div className="flex items-start justify-between gap-4 pt-4">
                            <div className="min-w-0">
                                <p className="text-sm font-medium text-white">Show on the resident portal</p>
                                <p id={id('portal-help')} className={`text-xs ${portalBlocked ? 'text-amber-200' : 'text-white/70'}`}>
                                    {portalBlocked
                                        ? <><AlertTriangle className="inline w-3.5 h-3.5 mr-1 -mt-0.5" aria-hidden="true" />{portalBlocked} Stays staff-only until then.</>
                                        : 'Faint outlines at parcel zoom. Shapes only, never field values or IDs.'}
                                </p>
                            </div>
                            <Switch on={portalOn} disabled={!!portalBlocked} onChange={() => setPortal(v => !v)}
                                label="Show on the resident portal" aria-describedby={id('portal-help')} />
                        </div>
                    </div>
                    {warnings.length > 0 && (
                        <ul className="space-y-1 rounded-xl border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100">
                            {warnings.map(w => <li key={w}>{w}</li>)}
                        </ul>
                    )}
                </Section>

                <Section id={id('categories')} icon={Layers} title="Categories">
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        <CategoryScopePicker
                            label="Record on reports in"
                            description="Reports in these categories get this layer's feature attached for staff."
                            services={services}
                            loading={servicesLoading}
                            value={staffCodes}
                            onChange={setStaffCodes}
                            disabled={purpose !== 'context'}
                            disabledReason="Display-only layers are not recorded on reports."
                        />
                        <CategoryScopePicker
                            label="Show outlines to residents in"
                            description="Residents reporting in these categories see the outlines on the map."
                            services={services}
                            loading={servicesLoading}
                            value={residentCodes}
                            onChange={setResidentCodes}
                            disabled={!portalOn}
                            disabledReason="Turn on “Show on the resident portal” to choose."
                        />
                    </div>
                </Section>

                <Section id={id('data')} icon={Database} title="Data">
                    <div className="space-y-3">
                        <label
                            onDragOver={e => { e.preventDefault(); setDragging(true); }}
                            onDragLeave={() => setDragging(false)}
                            onDrop={e => {
                                e.preventDefault();
                                setDragging(false);
                                const f = e.dataTransfer.files?.[0];
                                if (f) setReuploadFile(f);
                            }}
                            className={`flex flex-col sm:flex-row sm:items-center gap-3 rounded-xl border-2 border-dashed p-4 cursor-pointer transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-amber-300 ${dragging ? 'border-primary-300 bg-primary-500/15' : 'border-white/30 hover:border-white/50 hover:bg-white/[0.04]'}`}>
                            <input type="file" accept=".geojson,.json,application/geo+json,application/json"
                                aria-label="Replacement GeoJSON file" aria-describedby={id('file-help')}
                                onChange={e => setReuploadFile(e.target.files?.[0] || null)}
                                className="sr-only" />
                            <FileUp className="w-6 h-6 shrink-0 text-white/70" aria-hidden="true" />
                            <span className="min-w-0 flex-1">
                                <span className="block text-sm font-medium text-white break-all">
                                    {reuploadFile ? reuploadFile.name : 'Replace the polygons'}
                                </span>
                                <span id={id('file-help')} className="block text-xs text-white/70">
                                    {reuploadFile
                                        ? `${mb(reuploadFile.size)} · ready to upload`
                                        : 'Drop a GeoJSON file here or choose one. Up to 100 MB.'}
                                </span>
                            </span>
                            <span className="btn-outline btn-outline-md self-start sm:self-center" aria-hidden="true">Choose file</span>
                        </label>
                        <div className="flex flex-wrap items-center gap-3">
                            <Button type="button" size="sm" disabled={!reuploadFile || busy} onClick={reupload}
                                leftIcon={<Upload className="w-4 h-4" />}>
                                Upload replacement
                            </Button>
                            <span className="text-xs text-white/70">Reports keep the context they were recorded with.</span>
                        </div>
                    </div>
                    {purpose === 'context' && layer.routing_mode === 'context' && (
                        <div className="flex flex-col sm:flex-row sm:items-center gap-3 border-t border-white/10 pt-4">
                            <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={backfill}
                                leftIcon={<History className="w-4 h-4" />} aria-describedby={id('backfill-help')}>
                                Record on existing reports
                            </Button>
                            <span id={id('backfill-help')} className="text-xs text-white/70">
                                Attach this layer to reports filed before it was added.
                            </span>
                        </div>
                    )}
                </Section>

                <div className="sticky bottom-0 z-10 -mx-6 px-6 py-4 border-t border-white/10 bg-slate-900/95 backdrop-blur rounded-b-2xl flex flex-col sm:flex-row sm:items-center gap-3">
                    <div className="min-w-0 flex-1 text-sm">
                        {progress && <p role="status" className="text-sky-200">{progress}</p>}
                        {message && <p role="status" className="text-emerald-200">{message}</p>}
                        {error && <p role="alert" className="text-red-200">{error}</p>}
                    </div>
                    <div className="flex justify-end gap-3">
                        <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
                        <Button type="submit" isLoading={saving}>Save settings</Button>
                    </div>
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
