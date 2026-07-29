/**
 * Runtime provider selection.
 *
 * Adapters are reached through dynamic import() so Vite emits one chunk per
 * provider: a town configured for MapLibre must never download Google's adapter
 * (or @googlemaps/markerclusterer), and must never see a maps.googleapis.com
 * request. That is the whole point of the indirection — it is not just tidiness.
 */

import {
    GeocodingProvider,
    MapInitOptions,
    MapProviderConfig,
    MapProviderFactory,
    MapProviderId,
    MapRenderer,
} from './types';

type FactoryLoader = () => Promise<MapProviderFactory>;

const LOADERS: Partial<Record<MapProviderId, FactoryLoader>> = {
    google: async () => (await import('./providers/google')).googleMapProvider,
    maplibre: async () => (await import('./providers/maplibre')).maplibreMapProvider,
    esri: async () => (await import('./providers/esri')).esriMapProvider,
    // apple / azure land here once their adapters are written.
};

const cache = new Map<MapProviderId, Promise<MapProviderFactory>>();

export function isMapProviderId(value: unknown): value is MapProviderId {
    return typeof value === 'string' && value in LOADERS;
}

export function availableMapProviders(): MapProviderId[] {
    return Object.keys(LOADERS) as MapProviderId[];
}

export function loadMapProvider(id: MapProviderId): Promise<MapProviderFactory> {
    const loader = LOADERS[id];
    if (!loader) return Promise.reject(new Error(`Unknown map provider: ${id}`));

    let pending = cache.get(id);
    if (!pending) {
        // Drop the cache entry on failure so a transient network error does not
        // permanently poison the provider for the rest of the session.
        pending = loader().catch(err => {
            cache.delete(id);
            throw err;
        });
        cache.set(id, pending);
    }
    return pending;
}

/** Load the provider's SDK and attach a map to `container`. */
export async function createMap(
    container: HTMLElement,
    config: MapProviderConfig,
    options: MapInitOptions,
): Promise<MapRenderer> {
    const factory = await loadMapProvider(config.provider);
    await factory.load(config);
    return factory.createRenderer(container, config, options);
}

/**
 * Geocoding is resolved independently of rendering, so a town can render with
 * one vendor and geocode with another. Falls back to the render provider only
 * when no geocoder is configured.
 */
export async function createGeocoder(config: MapProviderConfig): Promise<GeocodingProvider | null> {
    const factory = await loadMapProvider(config.provider);
    if (!factory.createGeocoder) return null;
    await factory.load(config);
    return factory.createGeocoder(config);
}

/**
 * Try each geocoder in order until one answers. Used to keep the existing
 * "backend first (it meters usage for cost reporting), SDK second" behaviour
 * without either half knowing about the other.
 */
export function chainGeocoders(...providers: (GeocodingProvider | null | undefined)[]): GeocodingProvider {
    const chain = providers.filter((p): p is GeocodingProvider => !!p);

    const attempt = async <T>(
        run: (p: GeocodingProvider) => Promise<T | null>,
        empty: T,
    ): Promise<T> => {
        for (let i = 0; i < chain.length; i++) {
            try {
                const result = await run(chain[i]);
                if (result !== null && result !== undefined) return result;
            } catch (error) {
                if (i === chain.length - 1) throw error;
                console.warn(`Geocoder "${chain[i].id}" failed, falling back:`, error);
            }
        }
        return empty;
    };

    const widgetProvider = chain.find(p => p.attachAutocomplete);
    const suggestProvider = chain.find(p => p.suggest);

    return {
        id: chain.map(p => p.id).join('+') || 'none',
        reverseGeocode: position => attempt(p => p.reverseGeocode(position), null),
        geocode: query => attempt(async p => {
            const results = await p.geocode(query);
            return results.length ? results : null;
        }, []),
        suggest: suggestProvider
            ? (query, options) => suggestProvider.suggest!(query, options)
            : undefined,
        resolveSuggestion: suggestProvider?.resolveSuggestion
            ? suggestion => suggestProvider.resolveSuggestion!(suggestion)
            : undefined,
        attachAutocomplete: widgetProvider
            ? (input, options) => widgetProvider.attachAutocomplete!(input, options)
            : undefined,
    };
}
