import { useCallback, useEffect, useState } from 'react';
import { ScanLine } from 'lucide-react';
import { api, type RedactionDetectors, type RedactionModelStatus } from '../services/api';
import { Chip } from './ui';

/**
 * The on-server detectors on the Photo Redaction card: which license plate
 * detector runs and what answers for faces when the cloud provider cannot.
 *
 * Both run on this server from model files the town downloads (never bundled),
 * so each select shows whether its file is installed. A missing file is shown
 * plainly rather than letting the option look available: selecting a plate
 * model that is not there would hold back every photo.
 */

const PLATE_OPTIONS = [
    { value: 'yolo', label: 'On-server plate model (recommended)' },
    { value: 'ocr', label: 'Text recognition' },
    { value: 'off', label: 'Off' },
] as const;

const FACE_OPTIONS = [
    { value: 'yunet', label: 'On-server face model (YuNet)' },
    { value: 'opencv', label: 'Basic on-server detection (OpenCV)' },
    { value: 'off', label: 'None — hold the photo for review' },
] as const;

export function ModelChip({ model }: { model: RedactionModelStatus }) {
    if (!model.present) return <Chip tone="warning">Model files missing — see setup</Chip>;
    if (model.error) return <Chip tone="danger">Model failed to load</Chip>;
    return <Chip tone="success">Model installed</Chip>;
}

export default function RedactionDetectorsPanel() {
    const [state, setState] = useState<RedactionDetectors | null>(null);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setState(await api.getRedactionDetectors());
        } catch {
            setState(null);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    // No access, or an older server: say nothing rather than show a broken control.
    if (!state?.models) return null;

    const save = async (body: Parameters<typeof api.updateRedactionDetectors>[0]) => {
        setSaving(true);
        setError(null);
        try {
            setState(await api.updateRedactionDetectors(body));
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Could not save.');
        } finally {
            setSaving(false);
        }
    };

    const select = 'w-full bg-white/[0.04] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-primary-400/60';
    const { plate, face } = state.models;

    return (
        <section aria-labelledby="redaction-detectors-heading" className="rounded-lg bg-white/[0.03] border border-white/10 px-3 py-3 space-y-3">
            <h4 id="redaction-detectors-heading" className="text-white/90 text-xs font-semibold flex items-center gap-1.5">
                <ScanLine className="w-3.5 h-3.5 text-primary-300/80" aria-hidden="true" />
                On-server detectors
            </h4>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                        <label htmlFor="plate-detector" className="text-white/80 text-xs font-medium">License plate detector</label>
                        <ModelChip model={plate} />
                    </div>
                    <select
                        id="plate-detector"
                        className={select}
                        value={state.plate_detector}
                        disabled={saving}
                        onChange={e => save({ plate_detector: e.target.value as RedactionDetectors['plate_detector'] })}
                    >
                        {PLATE_OPTIONS.map(o => (
                            <option key={o.value} value={o.value} disabled={o.value === 'yolo' && !plate.present}>
                                {o.label}
                            </option>
                        ))}
                        {state.plate_detector === 'redactor' && <option value="redactor">EgoBlur sidecar (experimental)</option>}
                    </select>
                    <p className="text-white/55 text-[11px]">
                        Finds plates by their shape, including vanity plates with no numbers. Text recognition
                        only blurs plates it can read as letters and numbers, and sometimes blurs street signs.
                    </p>
                </div>
                <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                        <label htmlFor="face-fallback" className="text-white/80 text-xs font-medium">If the face provider is unavailable</label>
                        <ModelChip model={face} />
                    </div>
                    <select
                        id="face-fallback"
                        className={select}
                        value={state.face_fallback}
                        disabled={saving}
                        onChange={e => save({ face_fallback: e.target.value as RedactionDetectors['face_fallback'] })}
                    >
                        {FACE_OPTIONS.map(o => (
                            <option key={o.value} value={o.value} disabled={o.value === 'yunet' && !face.present}>
                                {o.label}
                            </option>
                        ))}
                    </select>
                    <p className="text-white/55 text-[11px]">
                        Used only when your selected provider is down, slow or rejecting its credentials.
                    </p>
                </div>
            </div>
            {(!plate.present || !face.present) && (
                <p className="text-white/55 text-[11px]">
                    Model files are downloaded by your town into <code className="bg-black/30 px-1 rounded">{state.models.models_dir}</code>;
                    see the photo redaction models guide in the documentation.
                </p>
            )}
            {error && <p role="alert" className="text-red-300 text-[11px]">{error}</p>}
        </section>
    );
}
