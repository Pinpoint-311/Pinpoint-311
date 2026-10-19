import type { ReactNode } from 'react';
import { Layers, MapPin } from 'lucide-react';

import type { MapLayer } from '../services/api';
import { PolygonLayerUploadForm } from './PolygonLayerManager';

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
 */

export type NewLayerType = '' | 'point' | 'polygon';

interface Props {
    layerType: NewLayerType;
    onTypeChange: (type: 'point' | 'polygon') => void;
    onCancel: () => void;
    onPolygonCreated: (layer: MapLayer) => void;
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

export default function AddLayerTypeStep({
    layerType, onTypeChange, onCancel, onPolygonCreated, onBusyChange, editing, children,
}: Props) {
    if (editing) return <>{children}</>;
    return (
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
    );
}
