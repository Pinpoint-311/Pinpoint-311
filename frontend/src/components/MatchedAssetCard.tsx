import { useState } from 'react';
import { ClipboardCheck, History, Link2 } from 'lucide-react';
import { Chip, StatusBadge } from './ui';
import { humanize, isEnumLike } from '../utils/humanize';

/**
 * The asset a report is tied to, on the staff incident view.
 *
 * An asset is only ever attached when the resident (or staff, at intake)
 * picked it on the map -- there is no proximity auto-match -- so this card
 * states that rather than showing a confidence or a distance (which is always
 * 0 for a picked asset). The work order prints the same asset automatically.
 *
 * Attributes come straight from the uploaded GeoJSON, so how many there are
 * and what they are called varies per layer: every one is shown, none hidden
 * behind an expander.
 */

export interface MatchedAsset {
    layer_name?: string;
    asset_id?: string | number;
    asset_type?: string;
    properties?: Record<string, unknown>;
}

export interface AssetReport {
    service_request_id: string;
    service_name: string;
    status: string;
    requested_datetime: string | null;
    description?: string | null;
}

// Keys that are either shown in the header already or are GIS bookkeeping
// rather than something a crew would want to read.
const HIDDEN_KEYS = new Set([
    'id', 'asset_id', 'name', 'layer_name', 'objectid', 'fid', 'gid',
    'shape', 'geometry', 'shape_length', 'shape_area', 'shape__length', 'shape__area',
]);

/** "install_year" / "installYear" / "INSTALL YEAR" -> "Install year". */
export function humanizeKey(key: string): string {
    return humanize(key);
}

export function formatValue(value: unknown): string {
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}

/** Every displayable attribute of the asset, in the file's own order. */
export function assetAttributes(properties: Record<string, unknown> | undefined): { key: string; label: string; value: string }[] {
    if (!properties) return [];
    return Object.entries(properties)
        .filter(([key, value]) =>
            !HIDDEN_KEYS.has(key.toLowerCase())
            && value !== null && value !== undefined && String(value).trim() !== '')
        .map(([key, value]) => ({ key, label: humanizeKey(key), value: formatValue(value) }));
}

/** A layer's `storm_drain` type reads "Storm drain"; a typed-in "Hydrant" stays as written. */
const assetType = (asset: MatchedAsset): string | undefined =>
    isEnumLike(asset.asset_type) ? humanize(asset.asset_type) : asset.asset_type;

/** The asset's display name: a `name` property if the file has one, else its ID. */
export function assetTitle(asset: MatchedAsset): string {
    const name = asset.properties?.name ?? asset.properties?.Name ?? asset.properties?.NAME;
    if (name !== undefined && name !== null && String(name).trim()) return String(name);
    if (asset.asset_id !== undefined && asset.asset_id !== null && String(asset.asset_id).trim()) {
        return `${assetType(asset) || asset.layer_name || 'Asset'} ${asset.asset_id}`;
    }
    return assetType(asset) || asset.layer_name || 'Asset';
}

export const fmtDate = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—';

const HISTORY_PREVIEW = 6;

interface ReportHistoryProps {
    /** "Asset history", "Parcel history". */
    title: string;
    /** Completes "N other reports ..." -- "in this parcel"; empty for none. */
    scope?: string;
    /** Shown when there are none: "No other reports on this asset." */
    emptyText: string;
    reports: AssetReport[];
    loading: boolean;
    onOpenReport: (id: string) => void;
}

/**
 * Other reports about the same thing, newest first, each one a button that
 * opens it. Shared by the asset card and the location context card so the two
 * histories read and behave the same.
 */
export function ReportHistory({ title, scope, emptyText, reports, loading, onOpenReport }: ReportHistoryProps) {
    const [showAll, setShowAll] = useState(false);
    const openCount = reports.filter(r => r.status !== 'closed').length;
    const oldest = reports.length ? reports[reports.length - 1].requested_datetime : null;
    const shown = showAll ? reports : reports.slice(0, HISTORY_PREVIEW);
    return (
        <div className="mt-4 border-t border-white/10 pt-3">
            <div className="mb-2 flex items-center gap-2">
                <History className="h-3.5 w-3.5 text-white/50" aria-hidden="true" />
                <span className="text-xs font-medium text-white/80">{title}</span>
                {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-transparent" aria-label="Loading" />}
            </div>
            {reports.length > 0 ? (
                <>
                    <p className="mb-2 text-xs text-white/55">
                        {reports.length} other report{reports.length !== 1 ? 's' : ''}{scope ? ` ${scope}` : ''}
                        {openCount > 0 && <> · <span className="text-amber-300">{openCount} still open</span></>}
                        {oldest && <> · first reported {fmtDate(oldest)}</>}
                    </p>
                    <ol className="divide-y divide-white/5 rounded-lg border border-white/10">
                        {shown.map(r => (
                            <li key={r.service_request_id}>
                                <button
                                    onClick={() => onOpenReport(r.service_request_id)}
                                    className="w-full px-3 py-2 text-left transition-colors hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-300"
                                >
                                    <div className="flex items-center gap-2">
                                        <span className="shrink-0"><StatusBadge status={r.status} size="xs" /></span>
                                        <span className="min-w-0 flex-1 truncate text-[13px] text-white/90">{r.service_name}</span>
                                        <span className="shrink-0 text-[11px] text-white/45">{fmtDate(r.requested_datetime)}</span>
                                    </div>
                                    {r.description && <p className="mt-0.5 truncate text-xs text-white/50">{r.description}</p>}
                                    <p className="mt-0.5 font-mono text-[10px] text-white/35">{r.service_request_id}</p>
                                </button>
                            </li>
                        ))}
                    </ol>
                    {reports.length > HISTORY_PREVIEW && (
                        <button onClick={() => setShowAll(v => !v)} className="btn-outline mt-2">
                            {showAll ? 'Show fewer' : `Show all ${reports.length} reports`}
                        </button>
                    )}
                </>
            ) : !loading ? (
                <p className="text-xs text-white/45">{emptyText}</p>
            ) : null}
        </div>
    );
}

interface Props {
    asset: MatchedAsset;
    layerColor?: string;
    reports: AssetReport[];
    loading: boolean;
    onOpenReport: (id: string) => void;
}

export default function MatchedAssetCard({ asset, layerColor, reports, loading, onOpenReport }: Props) {
    const attributes = assetAttributes(asset.properties);
    const color = layerColor || '#10b981';
    const subtitle = [asset.layer_name, asset.asset_id !== undefined && asset.asset_id !== null ? `ID ${asset.asset_id}` : null]
        .filter(Boolean).join(' · ');

    return (
        <section aria-label="Matched asset" className="mt-3 rounded-xl border border-white/10 bg-slate-900/40 p-4">
            {/* Header */}
            <div className="flex items-start gap-3">
                <span
                    className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border"
                    style={{ backgroundColor: `${color}26`, borderColor: `${color}66`, color }}
                    aria-hidden="true"
                >
                    <Link2 className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                    <p className="text-[15px] font-medium text-white break-words">{assetTitle(asset)}</p>
                    {subtitle && <p className="text-xs text-white/55 break-words font-mono">{subtitle}</p>}
                </div>
            </div>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
                <Chip tone="success">Selected on the map when reported</Chip>
                <Chip tone="info" icon={ClipboardCheck}>Included on the work order</Chip>
            </div>

            {/* Attributes: every field the layer's GeoJSON carries */}
            {attributes.length > 0 && <AttributeGrid attributes={attributes} />}

            {/* History of this asset */}
            <ReportHistory
                title="Asset history"
                emptyText="No other reports on this asset."
                reports={reports}
                loading={loading}
                onOpenReport={onOpenReport}
            />
        </section>
    );
}

/** Label/value pairs in the card's grid. */
export function AttributeGrid({ attributes }: { attributes: { key: string; label: string; value: string }[] }) {
    return (
        <dl className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-x-4 gap-y-2.5">
            {attributes.map(a => (
                <div key={a.key} className="min-w-0">
                    <dt className="text-[11px] text-white/45">{a.label}</dt>
                    <dd className="text-[13px] text-white/90 break-words">{a.value}</dd>
                </div>
            ))}
        </dl>
    );
}
