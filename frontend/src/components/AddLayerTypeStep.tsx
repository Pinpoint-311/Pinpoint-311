import { useId, useState, type ReactNode } from 'react';
import { FileUp, Globe, Layers, MapPin } from 'lucide-react';

import type { MapLayer } from '../services/api';
import { PolygonLayerUploadForm } from './PolygonLayerManager';
import { ArcGisImportForm } from './ArcGisImport';

/**
 * The first step of the console's one "Add Layer" dialog: what kind of layer.
 *
 * Points and Polygons are equal choices side by side. The choice decides the
 * rest of the dialog. Points continue into the point form (passed as
 * children), drawn in the browser and saved whole. Polygons -- parcels,
 * zoning, wards -- can be far larger, so they continue into the chunked
 * upload, which the server builds into a layer; the console then opens the
 * settings step (ID and label fields, staff fields, portal privacy rules).
 *
 * There used to be a separate "Add Polygon Layer" button beside "Add Layer",
 * which read as a different feature rather than a different kind of layer.
 *
 * Before the type, where the features come from: a file, or an ArcGIS link.
 * With a link the type follows from the layer's geometry, so the ArcGIS form
 * shows it preselected instead of asking.
 */

export type NewLayerType = '' | 'point' | 'polygon';

interface Props {
    layerType: NewLayerType;
    onTypeChange: (type: 'point' | 'polygon') => void;
    onCancel: () => void;
    onPolygonCreated: (layer: MapLayer) => void;
    /** A layer imported from ArcGIS. Defaults to onPolygonCreated for both kinds. */
    onArcGisCreated?: (layer: MapLayer, kind: 'points' | 'polygons') => void;
    onBusyChange?: (busy: boolean) => void;
    /** Editing an existing layer: its type is fixed, so only the form shows. */
    editing?: boolean;
    /** The point layer form, shown once Points is chosen (and when editing). */
    children?: ReactNode;
}

const OPTIONS = [
    { type: 'point', icon: MapPin, title: 'Points', desc: 'Individual locations (trees, lights, signs, etc.)' },
    { type: 'polygon', icon: Layers, title: 'Polygons', desc: 'Areas (tax parcels, zoning, wards, etc.)' },
] as const;

const SOURCES = [
    { value: 'file', icon: FileUp, title: 'Upload a file', desc: 'A GeoJSON file you exported' },
    { value: 'arcgis', icon: Globe, title: 'Import from ArcGIS', desc: 'Paste a link to an ArcGIS layer' },
] as const;

export default function AddLayerTypeStep({
    layerType, onTypeChange, onCancel, onPolygonCreated, onArcGisCreated, onBusyChange, editing, children,
}: Props) {
    const [source, setSource] = useState<'file' | 'arcgis'>('file');
    const uid = useId();
    if (editing) return <>{children}</>;
    return (
        <>
            <div className="space-y-2 mb-4">
                <span id={`${uid}-source`} className="block text-sm font-medium text-white/70">Source</span>
                <div role="radiogroup" aria-labelledby={`${uid}-source`} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {SOURCES.map(option => {
                        const on = source === option.value;
                        return (
                            <label key={option.value}
                                className={`flex items-center gap-3 rounded-lg border-2 px-3 py-2.5 cursor-pointer transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-amber-300 ${on
                                    ? 'border-primary-500 bg-primary-500/20 text-white'
                                    : 'border-white/20 bg-white/5 text-white/70 hover:border-white/40'}`}>
                                <input type="radio" name={`${uid}-source-radio`} value={option.value} checked={on}
                                    onChange={() => setSource(option.value)} className="sr-only" />
                                <option.icon className="w-5 h-5 shrink-0" aria-hidden="true" />
                                <span className="min-w-0">
                                    <span className="block text-sm font-semibold">{option.title}</span>
                                    <span className="block text-xs opacity-70">{option.desc}</span>
                                </span>
                            </label>
                        );
                    })}
                </div>
            </div>

            {source === 'arcgis' ? (
                <ArcGisImportForm
                    onCancel={onCancel}
                    onBusyChange={onBusyChange}
                    onCreated={(layer, kind) => (onArcGisCreated ? onArcGisCreated(layer, kind) : onPolygonCreated(layer))}
                />
            ) : (
            <>
            <div className="space-y-2 mb-4">
                <span id="layer-type-label" className="block text-sm font-medium text-white/70">
                    Layer Type <span className="text-red-400" aria-hidden="true">*</span>
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" role="group" aria-labelledby="layer-type-label">
                    {OPTIONS.map(option => (
                        <button
                            key={option.type}
                            type="button"
                            aria-pressed={layerType === option.type}
                            onClick={() => onTypeChange(option.type)}
                            className={`p-4 rounded-lg border-2 transition-all ${layerType === option.type
                                ? 'border-primary-500 bg-primary-500/20 text-white'
                                : 'border-white/20 bg-white/5 text-white/60 hover:border-white/40'
                                }`}
                        >
                            <option.icon className="w-6 h-6 mx-auto mb-1" aria-hidden="true" />
                            <div className="font-semibold">{option.title}</div>
                            <div className="text-xs opacity-60">{option.desc}</div>
                        </button>
                    ))}
                </div>
            </div>

            {layerType === 'polygon' && (
                <PolygonLayerUploadForm onCancel={onCancel} onCreated={onPolygonCreated} onBusyChange={onBusyChange} />
            )}
            {layerType === 'point' && children}
            </>
            )}
        </>
    );
}
