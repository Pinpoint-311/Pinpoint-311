/**
 * BaseMapType -> MapLibre style.
 *
 * 'roadmap' | 'satellite' | 'hybrid' | 'terrain' is a Google vocabulary and has
 * no native meaning in MapLibre, which only knows "a style document". So the
 * four names are mapped onto four *configurable* styles. A town overrides any
 * of them through MapProviderConfig.options.styles; what is left are free,
 * key-less defaults so an unconfigured MapLibre town still renders.
 *
 * There is deliberately no default for 'hybrid': imagery-plus-labels needs a
 * composed style that no free provider publishes ready-made, and quietly
 * serving plain satellite instead would be a lie. Unconfigured, 'hybrid' is
 * simply absent from capabilities.baseMapTypes and setBaseMapType('hybrid') is
 * a no-op.
 *
 * The default satellite/terrain tiles below are third-party services with their
 * own attribution and fair-use terms. They exist so the adapter works out of
 * the box; a real deployment should point `options.styles` at its own tiles.
 */

import { BaseMapType } from '../../types';

/** A style URL or an inline MapLibre style document. */
export type BaseMapStyle = string | object;

export interface MapLibreProviderOptions {
    styles?: Partial<Record<BaseMapType, BaseMapStyle>>;
    /** Extra attribution appended to the map's attribution control. */
    attribution?: string;
}

const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function rasterStyle(tiles: string[], attribution: string, maxzoom: number): object {
    return {
        version: 8,
        sources: {
            base: {
                type: 'raster',
                tiles,
                tileSize: 256,
                maxzoom,
                attribution,
            },
        },
        layers: [{ id: 'base', type: 'raster', source: 'base' }],
    };
}

const DEFAULT_STYLES: Partial<Record<BaseMapType, BaseMapStyle>> = {
    // OpenFreeMap: free, no key, OSM data, self-hostable.
    roadmap: 'https://tiles.openfreemap.org/styles/liberty',
    satellite: rasterStyle(
        ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        'Imagery &copy; Esri, Maxar, Earthstar Geographics',
        19,
    ),
    terrain: rasterStyle(
        ['https://tile.opentopomap.org/{z}/{x}/{y}.png'],
        `${OSM_ATTRIBUTION}, <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)`,
        17,
    ),
    // hybrid: intentionally absent — see the module comment.
};

export const ALL_BASE_MAP_TYPES: BaseMapType[] = ['roadmap', 'satellite', 'hybrid', 'terrain'];

/**
 * Styles this instance can actually serve. `styleId` (MapInitOptions) overrides
 * 'roadmap' specifically: it is the town's chosen default style document, and
 * roadmap is the type every caller falls back to.
 */
export function resolveStyles(
    options: MapLibreProviderOptions | undefined,
    styleId: string | null | undefined,
): Partial<Record<BaseMapType, BaseMapStyle>> {
    const resolved: Partial<Record<BaseMapType, BaseMapStyle>> = { ...DEFAULT_STYLES, ...options?.styles };
    if (styleId) resolved.roadmap = styleId;
    return resolved;
}

export function availableBaseMapTypes(
    styles: Partial<Record<BaseMapType, BaseMapStyle>>,
): BaseMapType[] {
    return ALL_BASE_MAP_TYPES.filter(type => !!styles[type]);
}

export function readProviderOptions(options: Record<string, unknown> | undefined): MapLibreProviderOptions {
    return (options ?? {}) as MapLibreProviderOptions;
}
