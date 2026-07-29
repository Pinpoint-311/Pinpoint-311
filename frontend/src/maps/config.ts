/**
 * Turn the town's saved GIS settings into a MapProviderConfig.
 *
 * The /gis/config payload is still Google-shaped (google_maps_api_key,
 * google_maps_map_id) because the backend has not grown provider fields yet.
 * This reads a `map_provider` key opportunistically and falls back to Google,
 * so the frontend is ready the moment the backend starts sending one and no
 * existing deployment changes behaviour in the meantime.
 */

import { isMapProviderId } from './registry';
import { MapProviderConfig, MapProviderId } from './types';

export const DEFAULT_MAP_PROVIDER: MapProviderId = 'google';

interface RawMapsConfig {
    map_provider?: string | null;
    google_maps_api_key?: string | null;
    google_maps_map_id?: string | null;
    map_api_key?: string | null;
    map_style_id?: string | null;
}

export function resolveMapProviderConfig(raw: RawMapsConfig | null | undefined): MapProviderConfig {
    const provider = isMapProviderId(raw?.map_provider) ? raw!.map_provider as MapProviderId : DEFAULT_MAP_PROVIDER;
    return {
        provider,
        apiKey: raw?.map_api_key ?? raw?.google_maps_api_key ?? null,
        styleId: raw?.map_style_id ?? raw?.google_maps_map_id ?? null,
    };
}

/**
 * Config for components that are still handed a bare Google API key as a prop.
 * Lets a component be ported to the interface without touching its call sites.
 */
export function legacyMapProviderConfig(
    apiKey: string | null | undefined,
    styleId?: string | null,
    provider?: MapProviderId,
): MapProviderConfig {
    return {
        provider: provider ?? DEFAULT_MAP_PROVIDER,
        apiKey: apiKey ?? null,
        styleId: styleId ?? null,
    };
}
