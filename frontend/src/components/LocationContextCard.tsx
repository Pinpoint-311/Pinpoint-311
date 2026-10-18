import { useEffect, useState } from 'react';
import { ClipboardCheck, MapPinned } from 'lucide-react';
import { Chip } from './ui';
import { humanize } from '../utils/humanize';
import { api, GisContextEntry } from '../services/api';
import { AssetReport, AttributeGrid, ReportHistory, formatValue } from './MatchedAssetCard';

/**
 * Where a report sits on the town's context layers -- the tax parcel, the
 * zoning district -- on the staff incident view.
 *
 * Unlike a matched asset, nobody picks this: the server works out which
 * polygons contain the report's point when it comes in, and keeps a copy of
 * the fields the admin allowed staff to see AS THEY READ THEN. That copy is
 * the GIS history; re-uploading the parcel layer later does not rewrite it,
 * which is why the card says when it was recorded rather than implying it is
 * the parcel record today.
 *
 * Only the layer's allowlisted fields ever reach this card. Every one of them
 * is shown: the admin chose them, so none is "bookkeeping" to hide.
 */

/** "Tax Parcels" -> "parcel"; anything else is an "area". */
export function featureNoun(layerName: string): string {
    if (/parcel|lot|property|tax/i.test(layerName)) return 'parcel';
    if (/zon/i.test(layerName)) return 'zone';
    if (/district|ward/i.test(layerName)) return 'district';
    return 'area';
}

export function contextAttributes(properties: Record<string, unknown> | undefined) {
    if (!properties) return [];
    return Object.entries(properties)
        .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== '')
        .map(([key, value]) => ({ key, label: humanize(key), value: formatValue(value) }));
}

interface CardProps {
    entry: GisContextEntry;
    layerColor?: string;
    reports: AssetReport[];
    loading: boolean;
    onOpenReport: (id: string) => void;
}

export default function LocationContextCard({ entry, layerColor, reports, loading, onOpenReport }: CardProps) {
    const color = layerColor || '#f59e0b';
    const noun = featureNoun(entry.layer_name);
    const attributes = contextAttributes(entry.properties);
    const subtitle = [entry.layer_name, entry.feature_key && entry.feature_key !== entry.label && !entry.feature_key.startsWith('g:')
        ? `ID ${entry.feature_key}` : null].filter(Boolean).join(' · ');

    return (
        <section aria-label={`Location context: ${entry.layer_name}`} className="mt-3 rounded-xl border border-white/10 bg-slate-900/40 p-4">
            <div className="flex items-start gap-3">
                <span
                    className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border"
                    style={{ backgroundColor: `${color}26`, borderColor: `${color}66`, color }}
                    aria-hidden="true"
                >
                    <MapPinned className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                    <p className="text-[11px] uppercase tracking-wide text-white/45">Location context</p>
                    <p className="text-[15px] font-medium text-white break-words">{entry.label || entry.feature_key}</p>
                    {subtitle && <p className="text-xs text-white/55 break-words font-mono">{subtitle}</p>}
                </div>
            </div>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
                <Chip tone="success">Recorded when reported</Chip>
                <Chip tone="info" icon={ClipboardCheck}>Included on the work order</Chip>
            </div>

            {attributes.length > 0 && <AttributeGrid attributes={attributes} />}

            <ReportHistory
                title={`${humanize(noun)} history`}
                scope={`in this ${noun}`}
                emptyText={`No other reports in this ${noun}.`}
                reports={reports}
                loading={loading}
                onOpenReport={onOpenReport}
            />
        </section>
    );
}

interface SectionProps {
    entries: GisContextEntry[] | null | undefined;
    /** The open report, left out of each feature's history. */
    requestId: string;
    layerColors?: Record<number, string>;
    onOpenReport: (id: string) => void;
}

/** One card per matched feature, each loading its own report history. */
export function LocationContextSection({ entries, requestId, layerColors, onOpenReport }: SectionProps) {
    const [reports, setReports] = useState<Record<string, AssetReport[]>>({});
    const [loading, setLoading] = useState(false);
    const list = entries || [];
    const signature = list.map(e => `${e.layer_id}:${e.feature_key}`).join('|');

    useEffect(() => {
        if (!list.length) {
            setReports({});
            return;
        }
        let cancelled = false;
        setLoading(true);
        Promise.all(list.map(e =>
            api.getFeatureReports(e.layer_id, e.feature_key, requestId)
                .then(rows => [`${e.layer_id}:${e.feature_key}`, rows] as const)
                .catch(() => [`${e.layer_id}:${e.feature_key}`, []] as const),
        )).then(pairs => {
            if (!cancelled) setReports(Object.fromEntries(pairs));
        }).finally(() => {
            if (!cancelled) setLoading(false);
        });
        return () => { cancelled = true; };
        // `signature` stands in for `list`, which is a new array every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [signature, requestId]);

    if (!list.length) return null;
    return (
        <>
            {list.map(e => {
                const key = `${e.layer_id}:${e.feature_key}`;
                return (
                    <LocationContextCard
                        key={key}
                        entry={e}
                        layerColor={layerColors?.[e.layer_id]}
                        reports={reports[key] || []}
                        loading={loading}
                        onOpenReport={onOpenReport}
                    />
                );
            })}
        </>
    );
}
